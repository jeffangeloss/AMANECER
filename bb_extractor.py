import os, re, csv, json, time, html, sys, requests
from pathlib import Path
from comun import cargar_perfil, rutas_perfil

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PERFIL = cargar_perfil()          # lee --perfil / BB_PERFIL y carga el .env
HOST = os.getenv("BB_HOST", "").rstrip("/")
COOKIE = os.getenv("BB_COOKIE", "")
DELAY = 0.7
SALIDA = rutas_perfil(PERFIL)["salida"]
if PERFIL:
    print(f"[perfil: {PERFIL}]  salida -> {SALIDA}/\n")

s = requests.Session()
s.headers.update({"Cookie": COOKIE, "Accept": "application/json"})
_x = re.search(r"xsrf:([0-9a-f-]+)", COOKIE)
if _x:
    s.headers["X-Blackboard-XSRF"] = _x.group(1)


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


def limpiar(t):
    if not t:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", " ", t)).strip()[:500]


def escribir(nombre, filas):
    if not filas:
        print(f"    {nombre}: vacio")
        return
    SALIDA.mkdir(exist_ok=True)
    campos = list(dict.fromkeys(k for f in filas for k in f))
    with (SALIDA / f"{nombre}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    print(f"    {SALIDA}/{nombre}.csv  ({len(filas)} filas)")


# --- identidad -------------------------------------------------------------
me = get("/learn/api/public/v1/users/me")
if not me:
    raise SystemExit("No autentico. Renueva la cookie.")
UID = me["id"]
print(f"Usuario {UID}\n")

# --- periodos --------------------------------------------------------------
terms = {t["id"]: t.get("name", "") for t in paginar("/learn/api/v1/terms")}

# --- cursos ----------------------------------------------------------------
membs = paginar(f"/learn/api/v1/users/{UID}/memberships", expand="course")
cursos, mapa = [], []
for m in membs:
    c = m.get("course") or {}
    cursos.append({
        "pk": c.get("id"),
        "codigo": c.get("courseId"),
        "nombre": c.get("name"),
        "periodo": terms.get(c.get("termId"), ""),
        "rol": m.get("courseRoleId"),
        "disponible": (c.get("availability") or {}).get("available"),
        "ultimo_acceso": m.get("lastAccessed"),
    })
    if c.get("id"):
        mapa.append((c["id"], c.get("name") or c.get("courseId")))

print(f"{len(cursos)} cursos\n")

contenidos, notas, entregas, anuncios = [], [], [], []

for pk, nombre in mapa:
    print(f"  {nombre}")

    for i in paginar(f"/learn/api/public/v1/courses/{pk}/contents", recursive="true"):
        contenidos.append({
            "curso": nombre,
            "titulo": i.get("title"),
            "tipo": (i.get("contentHandler") or {}).get("id", "").replace("resource/x-bb-", ""),
            "parent_id": i.get("parentId"),
            "creado": i.get("created"),
            "modificado": i.get("modified"),
            "disponible": (i.get("availability") or {}).get("available"),
        })

    cols = paginar(f"/learn/api/public/v1/courses/{pk}/gradebook/columns")
    porid = {c["id"]: c for c in cols}

    for c in cols:
        due = (c.get("grading") or {}).get("due")
        if due:
            entregas.append({
                "curso": nombre,
                "actividad": c.get("name"),
                "vence": due,
                "puntaje_max": (c.get("score") or {}).get("possible"),
                "intentos": (c.get("grading") or {}).get("attemptsAllowed"),
            })

    for g in paginar(f"/learn/api/public/v1/courses/{pk}/gradebook/users/{UID}"):
        col = porid.get(g.get("columnId"), {})
        dg = g.get("displayGrade") or {}
        notas.append({
            "curso": nombre,
            "actividad": col.get("name"),
            "nota": dg.get("score", g.get("score")),
            "sobre": (col.get("score") or {}).get("possible"),
            "texto": dg.get("text"),
            "estado": g.get("status"),
            "vence": (col.get("grading") or {}).get("due"),
        })

    for a in paginar(f"/learn/api/public/v1/courses/{pk}/announcements"):
        anuncios.append({
            "curso": nombre,
            "titulo": a.get("title"),
            "creado": a.get("created"),
            "cuerpo": limpiar(a.get("body")),
        })

print("\nEscribiendo:")
escribir("cursos", cursos)
escribir("contenidos", contenidos)
escribir("calificaciones", notas)
escribir("entregas", entregas)
escribir("anuncios", anuncios)
