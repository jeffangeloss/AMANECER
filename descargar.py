import os, re, csv, sys, time, json, html, argparse, requests
from pathlib import Path
from comun import sanear, destino_base, carpeta_archivos, cargar_perfil, rutas_perfil

# La consola de Windows usa cp1252 y revienta con acentos combinantes
# (NFD) que vienen en algunos nombres de archivo de Blackboard.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PERFIL = cargar_perfil()          # lee --perfil / BB_PERFIL y carga el .env
HOST = os.getenv("BB_HOST", "").rstrip("/")
COOKIE = os.getenv("BB_COOKIE", "")
DELAY = 0.7
SALIDA = rutas_perfil(PERFIL)["salida"]

# Handlers que pueden traer adjuntos. El resto (folder, externallink,
# bltiplacement, asmt-test-link) no tiene, no vale gastarles un request.
CON_ADJUNTOS = ("x-bb-file", "x-bb-document", "x-bb-assignment",
                "x-bb-lesson", "scormengine")

s = requests.Session()
s.headers.update({"Cookie": COOKIE, "Accept": "application/json"})
_x = re.search(r"xsrf:([0-9a-f-]+)", COOKIE)
if _x:
    s.headers["X-Blackboard-XSRF"] = _x.group(1)

# Sesion aparte, SIN la cookie de Bb: la URL firmada del 302 se rompe si
# se le manda (el almacenamiento valida la firma, no la sesion).
anon = requests.Session()


class Pasado(Exception):
    """El archivo supero --max-mb a mitad de la descarga. Propia, y no
    ValueError, porque requests lanza MissingSchema (que hereda de
    ValueError) y se confundiria con un limite excedido."""


def sin_cookies(metodo, url, **kw):
    """La URL firmada deja cookies en la respuesta. Si se arrastran al
    siguiente archivo, su firma se invalida y responde 401. Se limpian
    antes de cada descarga; dentro de una misma cadena de redirects si
    hacen falta, por eso no se desactivan del todo."""
    anon.cookies.clear()
    return anon.request(metodo, url, **kw)


def get(path, **p):
    r = s.get(HOST + path, params=p or None, timeout=30)
    time.sleep(DELAY)
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        raise SystemExit("Sesion vencida: renueva BB_COOKIE en .env")


def paginar(path, **p):
    p.setdefault("limit", 100)
    out, nxt, first = [], path, True
    while nxt:
        d = get(nxt, **(p if first else {}))
        first = False
        if not d:
            break
        out += d.get("results", [])
        nxt = d.get("paging", {}).get("nextPage")
    return out


def embebidos(pk, cid):
    """Archivos incrustados en el cuerpo de un Documento Ultra.

    Un Documento Ultra NO expone /attachments: la API lo reporta como
    `folder`, con un hijo `document` llamado ultraDocumentBody, y los
    archivos van dentro del HTML como <a data-bbfile="{json}">. Ese JSON
    trae el nombre real y una resourceUrl ya firmada.
    """
    d = get(f"/learn/api/public/v1/courses/{pk}/contents/{cid}")
    cuerpo = (d or {}).get("body") or ""
    out = []
    for crudo in re.findall(r'data-bbfile="([^"]+)"', cuerpo):
        try:
            j = json.loads(html.unescape(crudo))
        except ValueError:
            continue
        nombre = j.get("linkName") or j.get("displayName")
        url = j.get("resourceUrl")
        if nombre and url:
            out.append({"fileName": nombre, "mimeType": j.get("mimeType") or "",
                        "url": html.unescape(url)})
    return out


def url_embebido(pk, cid, nombre):
    """Re-deriva la URL en el momento de bajar: la firma del body caduca."""
    for e in embebidos(pk, cid):
        if e["fileName"] == nombre:
            return e["url"]
    return None


def firmar(pk, cid, aid):
    """El /download responde 302 a una URL firmada. Devuelve esa URL."""
    u = f"{HOST}/learn/api/public/v1/courses/{pk}/contents/{cid}/attachments/{aid}/download"
    r = s.get(u, allow_redirects=False, timeout=30)
    time.sleep(DELAY)
    if r.status_code in (301, 302, 303, 307, 308):
        return r.headers.get("Location")
    if r.status_code == 200:  # algunos responden el binario directo
        return u
    return None


def pesar(url):
    """Content-Length siguiendo la cadena de redirects, sin cookie de Bb."""
    try:
        h = sin_cookies("HEAD", url, timeout=30, allow_redirects=True)
    except Exception:
        return None
    n = h.headers.get("Content-Length")
    return int(n) if n and n.isdigit() else None


def arbol(items):
    """Reconstruye la ruta de carpetas subiendo por parentId."""
    porid = {i["id"]: i for i in items if i.get("id")}
    cache = {}

    def ruta(iid):
        if iid in cache:
            return cache[iid]
        it = porid.get(iid)
        if not it:
            return []
        cache[iid] = []  # corta ciclos si los hubiera
        padre = it.get("parentId")
        r = (ruta(padre) if padre and padre != iid else []) + [sanear(it.get("title"))]
        cache[iid] = r
        return r

    return {iid: ruta(iid) for iid in porid}


def recolectar(cursos, con_tamanos):
    """Recorre cursos -> contenidos -> adjuntos. Devuelve filas de inventario."""
    filas = []
    for pk, nombre in cursos:
        items = paginar(f"/learn/api/public/v1/courses/{pk}/contents", recursive="true")
        rutas = arbol(items)
        candidatos = [i for i in items
                      if any(h in (i.get("contentHandler") or {}).get("id", "")
                             for h in CON_ADJUNTOS)]
        print(f"  {nombre}  ({len(candidatos)} contenidos con posible adjunto)")

        def agregar(it, cid, aid, fn, mime, ruta, url_directa=None):
            fila = {
                "curso": nombre,
                "curso_pk": pk,
                "carpeta": "/".join(ruta),
                "contenido": it.get("title"),
                "content_id": cid,
                "attachment_id": aid,
                "archivo": fn,
                "ext": (os.path.splitext(fn)[1].lstrip(".") or "").lower(),
                "mime": mime or "",
                "origen": "embebido" if url_directa else "adjunto",
                "bytes": "",
                "mb": "",
            }
            if con_tamanos:
                url = url_directa or firmar(pk, cid, aid)
                n = pesar(url) if url else None
                if n:
                    fila["bytes"] = n
                    fila["mb"] = round(n / 1048576, 2)
            filas.append(fila)
            marca = f"{fila['mb']:>7}" if fila["bytes"] != "" else "      ?"
            print(f"      {marca} MB  {fn[:60]}")

        for it in candidatos:
            cid = it.get("id")
            for a in paginar(f"/learn/api/public/v1/courses/{pk}/contents/{cid}/attachments"):
                agregar(it, cid, a.get("id"), a.get("fileName") or "",
                        a.get("mimeType"), rutas.get(cid, [])[:-1])

        # Documentos Ultra: la API los marca `folder`, asi que quedaban
        # fuera del filtro de arriba y sus archivos nunca se veian.
        for it in items:
            if "x-bb-folder" not in (it.get("contentHandler") or {}).get("id", ""):
                continue
            hijos = paginar(f"/learn/api/public/v1/courses/{pk}/contents/{it['id']}/children")
            for c in hijos:
                if "x-bb-document" not in (c.get("contentHandler") or {}).get("id", ""):
                    continue
                for e in embebidos(pk, c["id"]):
                    agregar(it, c["id"], "", e["fileName"], e["mimeType"],
                            rutas.get(it["id"], [])[:-1], url_directa=e["url"])
    return filas


def escribir_inventario(filas, vistos=None):
    """Fusiona con lo que ya haya en inventario.csv. Sin esto, correr con
    --curso borraria del catalogo los cursos que no se procesaron."""
    SALIDA.mkdir(exist_ok=True)
    p = SALIDA / "inventario.csv"
    if vistos and p.exists():
        with p.open(encoding="utf-8-sig") as fh:
            previas = [r for r in csv.DictReader(fh) if r.get("curso") not in vistos]
        if previas:
            print(f"  (conservo {len(previas)} de cursos no procesados)")
        filas = filas + previas
    if not filas:
        print("  nada que escribir")
        return
    campos = list(filas[0])
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    tot = sum(int(f["bytes"]) for f in filas if str(f.get("bytes", "")).isdigit())
    print(f"\nsalida/inventario.csv  ({len(filas)} adjuntos"
          + (f", {tot/1048576:.1f} MB en total)" if tot else ")"))


def leer_inventario():
    p = SALIDA / "inventario.csv"
    if not p.exists():
        raise SystemExit("Falta salida/inventario.csv. Corre primero: descargar.py --inventario")
    with p.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def descargar(filas, base, tipos, max_mb):
    lim = max_mb * 1048576 if max_mb else None
    bajados = saltados = fallidos = 0
    total = 0
    usados = {}  # ruta -> attachment_id que la reclamo

    for f in filas:
        if tipos and f["ext"] not in tipos:
            continue
        prev = int(f["bytes"]) if f.get("bytes", "").isdigit() else None
        if lim and prev and prev > lim:
            print(f"  omito (>{max_mb} MB)  {f['archivo'][:60]}")
            saltados += 1
            continue

        destino = carpeta_archivos(f["curso"], a.destino, a.local)
        for parte in filter(None, f["carpeta"].split("/")):
            destino = destino / sanear(parte)
        archivo = destino / sanear(f["archivo"])

        # Dos adjuntos distintos pueden llamarse igual en la misma carpeta
        # (pasa con los .zip resubidos). Sin esto el segundo pisa al primero.
        # Los embebidos no tienen attachment_id: se identifican por content_id.
        clave = f["attachment_id"] or f["content_id"]
        if usados.get(archivo, clave) != clave:
            tallo, ext = os.path.splitext(archivo.name)
            i = 2
            while usados.get(destino / f"{tallo} ({i}){ext}", clave) != clave:
                i += 1
            archivo = destino / f"{tallo} ({i}){ext}"
        usados[archivo] = clave

        if archivo.exists() and prev and archivo.stat().st_size == prev:
            saltados += 1
            continue

        if f.get("origen") == "embebido":
            url = url_embebido(f["curso_pk"], f["content_id"], f["archivo"])
        else:
            url = firmar(f["curso_pk"], f["content_id"], f["attachment_id"])
        if not url:
            print(f"  FALLA firma  {f['archivo'][:60]}")
            fallidos += 1
            continue
        try:
            r = sin_cookies("GET", url, timeout=60, stream=True)
            n = r.headers.get("Content-Length")
            n = int(n) if n and n.isdigit() else None
            if lim and n and n > lim:
                r.close()
                print(f"  omito (>{max_mb} MB)  {f['archivo'][:60]}")
                saltados += 1
                continue
            destino.mkdir(parents=True, exist_ok=True)
            tmp = destino / (archivo.name + ".parcial")
            escrito = 0
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(65536):
                    if not chunk:
                        continue
                    escrito += len(chunk)
                    if lim and escrito > lim:  # sin Content-Length, corto al vuelo
                        raise Pasado()
                    fh.write(chunk)
            r.close()
            tmp.replace(archivo)
            bajados += 1
            total += escrito
            try:
                rel = archivo.relative_to(base)
            except ValueError:  # ruta del Banco, no cuelga de base
                rel = Path(*archivo.parts[-3:])
            print(f"  {escrito/1048576:7.2f} MB  {rel}")
        except Pasado:
            tmp.unlink(missing_ok=True)
            print(f"  omito (>{max_mb} MB)  {f['archivo'][:60]}")
            saltados += 1
        except Exception as e:
            print(f"  FALLA  {f['archivo'][:60]}  ({e})")
            fallidos += 1

    print(f"\n{bajados} bajados ({total/1048576:.1f} MB), {saltados} saltados, {fallidos} fallidos")
    print(f"en {base}")


ap = argparse.ArgumentParser(description="Inventario y descarga de adjuntos de Blackboard")
ap.add_argument("--inventario", action="store_true", help="solo inventariar, no descargar")
ap.add_argument("--sin-tamanos", action="store_true", help="inventario rapido, sin pesar cada adjunto")
ap.add_argument("--tipos", default="", help="extensiones a bajar, ej: pdf,pptx,docx")
ap.add_argument("--max-mb", type=float, default=None, help="omitir archivos mas grandes")
ap.add_argument("--destino", default=None, help="carpeta base de descarga")
ap.add_argument("--local", action="store_true", help="bajar a ./descargas en vez de Google Drive")
ap.add_argument("--curso", default="", help="filtrar por texto en el nombre del curso")
a = ap.parse_args()

if not HOST or not COOKIE:
    raise SystemExit("Falta BB_HOST o BB_COOKIE en .env")

if a.inventario:
    me = get("/learn/api/public/v1/users/me")
    if not me:
        raise SystemExit("No autentico. Renueva la cookie.")
    UID = me["id"]
    cursos = []
    for m in paginar(f"/learn/api/v1/users/{UID}/memberships", expand="course"):
        c = m.get("course") or {}
        nom = c.get("name") or c.get("courseId") or ""
        if c.get("id") and (not a.curso or a.curso.lower() in nom.lower()):
            cursos.append((c["id"], nom))
    print(f"{len(cursos)} cursos\n")
    filas = recolectar(cursos, not a.sin_tamanos)
    escribir_inventario(filas, {c[1] for c in cursos})
else:
    filas = leer_inventario()
    if a.curso:
        filas = [f for f in filas if a.curso.lower() in f["curso"].lower()]
    tipos = {t.strip().lstrip(".").lower() for t in a.tipos.split(",") if t.strip()}
    base = destino_base(a.destino, a.local)
    print(f"{len(filas)} adjuntos en el inventario -> {base}\n")
    descargar(filas, base, tipos, a.max_mb)
