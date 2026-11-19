"""Cataloga las grabaciones de Zoom que cuelgan del LTI de Blackboard.

La logica de la API es la de arma_maestra.txt, pero corriendo dentro del
iframe via Playwright en vez de pegada a mano en DevTools. El LTI vive en
applications.zoom.us, o sea otro origin: hay que evaluar el JS EN ESE
frame, no en la pagina de Blackboard.

    python3 zoom.py                  -> salida/zoom.csv, no baja nada
    python3 zoom.py --curso PROG     -> solo los cursos que matcheen
    python3 zoom.py --descargar      -> baja los MP4 con yt-dlp a Drive
"""
import os, re, sys, csv, json, time, argparse, subprocess, requests
from datetime import date, timedelta
from pathlib import Path
from comun import (sanear, destino_base, carpeta_grabaciones, cargar_perfil, rutas_perfil,
                   registrar_cursos)

# La consola de Windows usa cp1252 y revienta con acentos combinantes
# (NFD) que vienen en algunos titulos de Blackboard.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PERFIL = cargar_perfil()          # lee --perfil / BB_PERFIL y carga el .env

# playwright se importa dentro de recolectar(): descargar solo necesita
# el catalogo y yt-dlp, y asi la maquina que solo baja no lo instala.

HOST = os.getenv("BB_HOST", "https://ulima.blackboard.com").rstrip("/")
COOKIE = os.getenv("BB_COOKIE", "")
_r = rutas_perfil(PERFIL)
CHROME = _r["chrome"]             # directorio del perfil de Chrome, por cuenta
SALIDA = _r["salida"]
if PERFIL:
    print(f"[perfil: {PERFIL}]")

# Corre dentro del frame de Zoom. Devuelve las filas en vez de disparar
# la descarga de un txt como hacia el script de consola original.
JS = """
async () => {
  const scid = (window.appConf && window.appConf.page && window.appConf.page.scid)
    || new URLSearchParams(location.search).get('lti_scid');
  if (!scid) return {error: 'no encontre lti_scid'};

  const arr = (window.appConf && window.appConf.ajaxHeaders) || [];
  if (!arr.length) return {error: 'no encontre appConf.ajaxHeaders'};
  const headers = Object.fromEntries(arr.map(h => [h.key, h.value]));

  const hoy = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Lima'}).format(new Date());

  const pedir = async (url) => {
    const res = await fetch(url, {
      method: 'GET', credentials: 'include',
      headers: {...headers, Accept: 'application/json, text/plain, */*'},
    });
    if (!res.ok) {
      const t = await res.text().catch(() => '');
      throw new Error('HTTP ' + res.status + (t.includes('"errorCode":"csrf"') ? ' (CSRF/sesion vencida)' : ''));
    }
    return res.json();
  };

  // 1) listar reuniones, paginado
  const reuniones = [];
  let total = 0;
  try {
    for (let page = 1; page <= 30; page++) {
      const u = '/api/v1/lti/rich/recording/COURSE?startTime=&endTime=' +
        encodeURIComponent(hoy) + '&keyWord=&searchType=1&status=&page=' + page +
        '&total=' + total + '&lti_scid=' + encodeURIComponent(scid);
      const j = await pedir(u);
      const lista = (j && j.result && (j.result.list || j.result.data || j.result.recordings)) || [];
      if (!lista.length) break;
      reuniones.push(...lista);
      total = (j && j.result && j.result.total) || total;
    }
  } catch (e) {
    return {error: 'listando: ' + e.message};
  }

  // 2) detalle por reunion, para sacar el MP4 y su peso
  const filas = [];
  for (const m of reuniones) {
    const meetingId = m.meetingId || m.id;
    const fila = {
      meetingId: String(meetingId || ''),
      tema: m.topic || '',
      inicio: m.startTime || m.listStartTime || '',
      duracion: m.duration == null ? '' : String(m.duration),
      mp4: '', bytes: '', archivos: '',
    };
    try {
      const d = await pedir('/api/v1/lti/rich/recording/file?meetingId=' +
        encodeURIComponent(meetingId) + '&lti_scid=' + encodeURIComponent(scid));
      const fs = (d && d.result && d.result.recordingFiles) || [];
      fila.archivos = fs.map(f => f.fileType).filter(Boolean).join('|');
      const mp4 = fs.find(f => f.fileType === 'MP4');
      if (mp4) {
        fila.mp4 = mp4.playUrl || mp4.downloadUrl || '';
        if (mp4.fileSize != null) fila.bytes = String(mp4.fileSize);
      }
    } catch (e) {
      fila.error = e.message;
    }
    filas.push(fila);
    await new Promise(r => setTimeout(r, 250));
  }
  return {scid, filas};
}
"""


def cursos_con_zoom(filtro):
    """Devuelve (pk, nombre, deep_link) por curso que tenga item de Zoom.

    El deep link sale de `links[rel=alternate]` del propio contenido, que
    es lo que usa la UI; asi no hay que adivinar la URL de lanzamiento.
    """
    s = requests.Session()
    s.headers.update({"Cookie": COOKIE, "Accept": "application/json"})
    x = re.search(r"xsrf:([0-9a-f-]+)", COOKIE)
    if x:
        s.headers["X-Blackboard-XSRF"] = x.group(1)

    r = s.get(f"{HOST}/learn/api/public/v1/users/me", timeout=30)
    if r.status_code != 200:
        raise SystemExit("Sesion vencida. Corre: python3 sesion.py")
    uid = r.json()["id"]

    out, con_zoom = [], []
    d = s.get(f"{HOST}/learn/api/v1/users/{uid}/memberships",
              params={"expand": "course", "limit": 100}, timeout=30).json()
    time.sleep(0.7)
    for m in d.get("results", []):
        c = m.get("course") or {}
        nom = c.get("name") or c.get("courseId") or ""
        if not c.get("id"):
            continue
        if filtro and filtro.lower() not in nom.lower():
            continue
        # PAGINAR: con un solo request de limit=100 los cursos con mas de
        # 100 contenidos perdian su item de Zoom si caia despues del
        # primer centenar, y el curso se descartaba en silencio.
        items, nxt, first = [], f"/learn/api/public/v1/courses/{c['id']}/contents", True
        while nxt:
            rr = s.get(HOST + nxt,
                       params={"recursive": "true", "limit": 100} if first else None,
                       timeout=30)
            first = False
            time.sleep(0.7)
            if rr.status_code != 200:
                break
            d = rr.json()
            items += d.get("results", [])
            nxt = d.get("paging", {}).get("nextPage")
        for it in items:
            if "blti" not in (it.get("contentHandler") or {}).get("id", ""):
                continue
            href = next((l.get("href") for l in it.get("links") or []
                         if l.get("rel") == "alternate"), None)
            out.append((c["id"], nom, href, it.get("id")))
            con_zoom.append(c)
            break
    registrar_cursos(s, HOST, con_zoom)  # semestre y profesor, para la ruta del Banco
    return out


def cookies_de_env():
    """Siembra el navegador con la cookie de .env. Chrome no persiste las
    cookies de sesion, asi que el perfil puede estar deslogueado aunque
    .env siga vigente: .env es la fuente de verdad, no el perfil."""
    out = []
    for parte in COOKIE.split(";"):
        parte = parte.strip()
        if "=" not in parte:
            continue
        k, v = parte.split("=", 1)
        out.append({"name": k, "value": v, "domain": "ulima.blackboard.com",
                    "path": "/", "secure": True})
    return out


# Placement institucional de Zoom. Igual en todos los cursos: se
# verifico contra 3 cursos distintos, cada uno devolvio su propio scid.
PLACEMENT = "_213_1"


def url_launch(pk, cid):
    """Lanza el LTI directo, sin pasar por el outline.

    Es la unica forma confiable: la SPA de Ultra renderiza el outline de
    manera inconsistente bajo automatizacion y en algunos cursos el item
    de Zoom nunca llegaba al DOM. Este endpoint monta el iframe en ~3s.
    Ojo con el escape: Blackboard espera `~2F` en vez de `/` dentro de
    toolHref, y el resto percent-encoded. No re-encodear.
    """
    th = ("https:~2F~2Fulima.blackboard.com~2Fwebapps~2Fblackboard~2Fexecute"
          "~2Fblti~2FlaunchPlacement"
          f"%3Fblti_placement_id%3D{PLACEMENT}%26content_id%3D{cid}"
          f"%26course_id%3D{pk}%26wrapped%3Dtrue%26from_ultra%3Dtrue")
    return (f"{HOST}/ultra/courses/{pk}/outline/lti/launchFrame"
            f"?toolHref={th}&toolTitle=Zoom%20Meeting&contentId={cid}")


def esperar_frame(pg, segundos):
    """Espera a que monte el iframe del LTI (id lti-launch-iframe)."""
    for _ in range(segundos):
        f = next((f for f in pg.frames
                  if "applications.zoom.us" in (f.url or "")), None)
        if f:
            return f
        pg.wait_for_timeout(1000)
    return None


def esperar_scid(pg, frame, segundos=25):
    """El frame monta ANTES de que su JS defina window.appConf.

    Evaluar apenas aparece el iframe da 'no encontre lti_scid' de forma
    intermitente: en unos cursos appConf ya estaba y en otros no. Hay que
    esperar a que el scid exista antes de correr la logica.
    """
    for _ in range(segundos):
        try:
            scid = frame.evaluate(
                "() => (window.appConf && window.appConf.page && window.appConf.page.scid)"
                " || new URLSearchParams(location.search).get('lti_scid') || null")
            if scid:
                return True
        except Exception:
            pass  # frame navegando: reintentar
        pg.wait_for_timeout(1000)
    return False


def esperar_login(pg, ctx, espera=300):
    """La SPA de Ultra no arranca con la cookie inyectada: necesita una
    sesion de verdad. Y como Chrome descarta las cookies de sesion al
    cerrar, el login y el catalogo tienen que pasar en la MISMA corrida."""
    print("Se abre Chrome. Inicia sesion en Blackboard (usuario, clave y MFA).")
    print("Cuando veas tus cursos, sigo solo.\n")
    pg.goto(f"{HOST}/ultra/course", wait_until="domcontentloaded", timeout=60000)
    limite = time.time() + espera
    while time.time() < limite:
        if "/ultra/" in pg.url and "new_loc" not in pg.url:
            got = {c["name"] for c in ctx.cookies()}
            if "BbRouter" in got and "JSESSIONID" in got:
                pg.wait_for_timeout(4000)
                print("Sesion lista.\n")
                return True
        pg.wait_for_timeout(2000)
    return False


def recolectar(cursos, headless, login):
    """Abre cada curso, entra al iframe de Zoom y corre el JS."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Falta playwright (solo hace falta para catalogar):\n"
                         "  pip install playwright")
    filas = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(CHROME), channel="chrome", headless=headless,
            args=["--no-first-run", "--no-default-browser-check"])
        try:
            estado = CHROME / "estado.json"
            if estado.exists():
                try:
                    ctx.add_cookies(json.loads(estado.read_text(encoding="utf-8")))
                except Exception:
                    pass
            ctx.add_cookies(cookies_de_env())
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()

            if login and not esperar_login(pg, ctx):
                print("No se completo el login a tiempo.")
                return filas

            for pk, nombre, href, cid in cursos:
                print(f"  {nombre}")
                frame = None
                for intento in range(1, 4):
                    try:
                        pg.goto(url_launch(pk, cid), wait_until="domcontentloaded",
                                timeout=60000)
                    except Exception as e:
                        print(f"      no pude abrir el LTI ({str(e)[:50]})")
                        break
                    frame = esperar_frame(pg, 30)
                    if frame and esperar_scid(pg, frame):
                        break
                    frame = None  # monto pero sin scid: recargar y reintentar
                    if intento < 3:
                        print(f"      intento {intento} sin scid, reintento")
                if not frame:
                    print("      no aparecio el iframe / no cargo el scid")
                    continue

                try:
                    res = frame.evaluate(JS)
                except Exception as e:
                    print(f"      fallo el JS ({str(e)[:60]})")
                    continue
                if res.get("error"):
                    print(f"      {res['error']}")
                    continue

                for f in res["filas"]:
                    f["curso"] = nombre
                    filas.append(f)
                print(f"      {len(res['filas'])} grabaciones")

            if login:  # guardar para que sesion.py renueve sin ventana
                try:
                    (CHROME / "estado.json").write_text(
                        json.dumps(ctx.cookies()), encoding="utf-8")
                    os.chmod(CHROME / "estado.json", 0o600)
                except Exception:
                    pass
        finally:
            ctx.close()
    return filas


def escribir(filas, vistos):
    """Fusiona con lo que ya haya en zoom.csv. Sin esto, correr con
    --curso borraria del catalogo los cursos que no se procesaron."""
    SALIDA.mkdir(exist_ok=True)
    campos = ["curso", "inicio", "tema", "duracion", "bytes", "mb",
              "archivos", "mp4", "meetingId", "error", "visto"]
    # Marca de cuando se catalogo cada fila: las que se conservan de
    # corridas anteriores quedan con su marca vieja, y --desde las filtra.
    ahora = time.strftime("%Y-%m-%d %H:%M:%S")
    for f in filas:
        f["visto"] = ahora
    p = SALIDA / "zoom.csv"
    if p.exists():
        with p.open(encoding="utf-8-sig") as fh:
            previas = [r for r in csv.DictReader(fh) if r.get("curso") not in vistos]
        if previas:
            print(f"  (conservo {len(previas)} de cursos no procesados)")
        filas = filas + previas
    for f in filas:
        b = f.get("bytes")
        f["mb"] = round(int(b) / 1048576, 1) if b and str(b).isdigit() else ""
    filas.sort(key=lambda f: (f.get("curso", ""), f.get("inicio", "")))
    with (SALIDA / "zoom.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    tot = sum(int(f["bytes"]) for f in filas if str(f.get("bytes", "")).isdigit())
    print(f"\n{SALIDA}/zoom.csv  ({len(filas)} grabaciones"
          + (f", {tot/1073741824:.1f} GB)" if tot else ", sin pesos)"))


def nombrar(filas):
    """`S{semana}.Clase {n} - DD.MM.YY.mp4`, la convencion que ya se venia
    usando a mano. Semana = semana calendario relativa a la primera clase
    del curso; n = correlativo cronologico dentro del curso.

    Se calcula sobre TODAS las filas del curso, no sobre las que se van a
    bajar, para que --max no altere la numeracion.
    """
    out, porcurso = {}, {}
    for f in filas:
        if f.get("inicio"):
            porcurso.setdefault(f["curso"], []).append(f)
    for curso, fs in porcurso.items():
        fs.sort(key=lambda x: x["inicio"])
        d0 = date.fromisoformat(fs[0]["inicio"][:10])
        lun0 = d0 - timedelta(days=d0.weekday())
        for i, f in enumerate(fs, 1):
            d = date.fromisoformat(f["inicio"][:10])
            lun = d - timedelta(days=d.weekday())
            sem = ((lun - lun0).days // 7) + 1
            out[(curso, f["meetingId"])] = \
                f"S{sem}.Clase {i} - {d.strftime('%d.%m.%y')}.mp4"
    return out


def bajar_api(url, salida):
    """Plan B cuando yt-dlp no reconoce la pagina de Zoom (desde nov-2026
    /rec/play es una SPA sin window.__data__). La misma pagina llama a
    /nws/recording/1.0/play/info/<id>, que devuelve el viewMp4Url firmado;
    hay que pedirlo con las cookies que deja /rec/play y con Referer."""
    host = url.split("/rec/")[0]
    rid = url.split("/play/")[1].split("?")[0]
    z = requests.Session()
    z.headers["User-Agent"] = "Mozilla/5.0"
    z.get(url, timeout=60)
    j = z.get(f"{host}/nws/recording/1.0/play/info/{rid}",
              headers={"Referer": url}, timeout=60).json()
    r = (j or {}).get("result") or {}
    mp4 = r.get("viewMp4Url") or r.get("mp4Url")
    if not mp4:
        raise RuntimeError(f"play/info sin mp4 ({j.get('errorCode')} {j.get('errorMessage')})")
    tmp = salida.with_name(salida.name + ".part")
    with z.get(mp4, headers={"Referer": url}, stream=True, timeout=120) as res:
        res.raise_for_status()
        esperado = int(res.headers.get("Content-Length") or 0)
        escritos = 0
        with open(tmp, "wb") as fh:
            for trozo in res.iter_content(1 << 20):
                fh.write(trozo)
                escritos += len(trozo)
    # se cuentan los bytes escritos y no tmp.stat(): en G: (Drive para
    # escritorio) el tamano tarda en actualizarse y da falsos incompletos
    if esperado and escritos != esperado:
        raise RuntimeError(f"incompleto: {escritos} de {esperado} bytes")
    tmp.replace(salida)


def bajar(filas, destino, local, maximo):
    """yt-dlp por grabacion. El playUrl lleva token propio, no necesita cookie."""
    nombres = nombrar(filas)
    n = 0
    for f in filas:
        if not f.get("mp4"):
            continue
        if maximo and n >= maximo:
            print(f"corto en {maximo} por --max")
            break
        carpeta = carpeta_grabaciones(f["curso"], destino, local)
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = nombres.get((f["curso"], f["meetingId"]))
        if not nombre:  # sin fecha no hay semana ni correlativo
            nombre = sanear(f"{f.get('tema') or f['meetingId']}") + ".mp4"
        salida = carpeta / sanear(nombre)
        if salida.exists() and salida.stat().st_size > 0:
            print(f"  ya esta  {nombre[:60]}")
            continue
        print(f"  bajando  {nombre[:60]}")
        # encoding explicito: yt-dlp escribe en cp1252 en Windows y sin esto el
        # hilo lector de subprocess muere con UnicodeDecodeError, dejando la
        # descarga como "exitosa" sin que exista el archivo.
        try:
            r = subprocess.run(["yt-dlp", "-o", str(salida), f["mp4"]],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        except FileNotFoundError:  # sin yt-dlp instalado: directo a la API
            r = subprocess.CompletedProcess([], 1, "", "yt-dlp no instalado")
        err = (r.stderr or "").strip()
        if r.returncode != 0:
            try:
                bajar_api(f["mp4"], salida)
                print("      ok via API de Zoom (yt-dlp no reconocio la pagina)")
                n += 1
            except Exception as e:
                print(f"      FALLA  {err.splitlines()[-1][:80] if err else '?'} | API: {str(e)[:80]}")
        elif not (salida.exists() and salida.stat().st_size > 0):
            # returncode 0 no alcanza: verificar que el archivo exista de verdad
            print(f"      FALLA  yt-dlp no dejo archivo en {salida.name}")
        else:
            n += 1
    print(f"\n{n} grabaciones bajadas")


ap = argparse.ArgumentParser(description="Grabaciones de Zoom desde el LTI de Blackboard")
ap.add_argument("--curso", default="", help="filtrar por texto en el nombre del curso")
ap.add_argument("--descargar", action="store_true", help="bajar los MP4 (por defecto solo cataloga)")
ap.add_argument("--max", type=int, default=None, help="cortar despues de N grabaciones")
ap.add_argument("--destino", default=None, help="carpeta base de descarga")
ap.add_argument("--local", action="store_true", help="bajar a ./descargas")
ap.add_argument("--desde", default="",
                help="con --descargar, solo filas catalogadas desde 'AAAA-MM-DD HH:MM:SS'")
ap.add_argument("--ver", action="store_true", help="mostrar el navegador (para depurar)")
ap.add_argument("--login", action="store_true",
                help="abre ventana, te logueas y cataloga en la misma corrida")
ap.add_argument("--fusionar", default="",
                help="ruta del zoom_manual.json de consola_zoom.js; requiere --curso")
a = ap.parse_args()

if a.fusionar:
    if not a.curso:
        raise SystemExit("--fusionar necesita --curso con el nombre exacto del curso")
    datos = json.loads(Path(os.path.expanduser(a.fusionar)).read_text(encoding="utf-8"))
    for f in datos:
        f["curso"] = a.curso
    print(f"{len(datos)} grabaciones de {a.curso}")
    escribir(datos, {a.curso})
    raise SystemExit(0)

if a.descargar and (SALIDA / "zoom.csv").exists():
    with (SALIDA / "zoom.csv").open(encoding="utf-8-sig") as fh:
        filas = [f for f in csv.DictReader(fh)
                 if (not a.curso or a.curso.lower() in f["curso"].lower())
                 and (not a.desde or (f.get("visto") or "") >= a.desde)]
    print(f"{len(filas)} grabaciones en el catalogo\n")
else:
    cursos = cursos_con_zoom(a.curso)
    print(f"{len(cursos)} cursos con Zoom\n")
    filas = recolectar(cursos, headless=not (a.ver or a.login), login=a.login)
    escribir(filas, {c[1] for c in cursos})

if a.descargar:
    bajar(filas, a.destino, a.local, a.max)
