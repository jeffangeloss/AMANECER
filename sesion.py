"""Renueva BB_COOKIE en .env sin pasar por DevTools.

Usa un perfil de Chrome propio del proyecto (.perfil-chrome/). La primera
vez abre una ventana para que hagas el login con MFA a mano; de ahi en
adelante esa sesion SSO queda viva semanas, y Blackboard emite una cookie
nueva sola con solo visitar el sitio.

    python3 sesion.py --login    primera vez, o cuando el SSO expire
    python3 sesion.py            renovacion silenciosa
"""
import os, re, json, time, argparse, requests
from pathlib import Path
from playwright.sync_api import sync_playwright
from comun import cargar_perfil, rutas_perfil

NOMBRE = cargar_perfil(requiere_env=False)  # --login crea el .env que falta
_r = rutas_perfil(NOMBRE)
HOST = os.getenv("BB_HOST", "https://ulima.blackboard.com").rstrip("/")
PERFIL = _r["chrome"]
ESTADO = PERFIL / "estado.json"
ENV = _r["env"]


def cookie_de(ctx):
    """Arma el string que espera la API a partir de las cookies del perfil."""
    got = {c["name"]: c["value"] for c in ctx.cookies()
           if c["name"] in ("JSESSIONID", "BbRouter")}
    if "BbRouter" not in got:
        return None
    partes = []
    if "JSESSIONID" in got:
        partes.append(f"JSESSIONID={got['JSESSIONID']}")
    partes.append(f"BbRouter={got['BbRouter']}")
    return "; ".join(partes)


def sirve(cookie):
    """La prueba real no es que exista la cookie, sino que /users/me
    conteste JSON y no el HTML del login. Devuelve el uid o None."""
    s = requests.Session()
    s.headers.update({"Cookie": cookie, "Accept": "application/json"})
    x = re.search(r"xsrf:([0-9a-f-]+)", cookie)
    if x:
        s.headers["X-Blackboard-XSRF"] = x.group(1)
    try:
        r = s.get(HOST + "/learn/api/public/v1/users/me", timeout=30)
        if r.status_code != 200:
            return None
        return r.json().get("id")
    except Exception:
        return None


def guardar_estado(ctx):
    """Chrome NO persiste las cookies de sesion: al cerrar se pierden las
    del SSO y la corrida siguiente aparece deslogueada. Las guardamos a
    mano. El archivo vale tanto como .env, va con permisos 600."""
    ESTADO.write_text(json.dumps(ctx.cookies()), encoding="utf-8")
    os.chmod(ESTADO, 0o600)


def restaurar_estado(ctx):
    if not ESTADO.exists():
        return
    try:
        ctx.add_cookies(json.loads(ESTADO.read_text(encoding="utf-8")))
    except Exception:
        pass  # estado corrupto: se sigue, el login manual lo rehace


def obtener(headless, espera):
    """Abre el perfil, espera a tener una cookie que funcione."""
    cookie = uid = None
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PERFIL), channel="chrome", headless=headless,
            args=["--no-first-run", "--no-default-browser-check"])
        try:
            restaurar_estado(ctx)
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(f"{HOST}/ultra/course", wait_until="domcontentloaded", timeout=60000)
            limite = time.time() + espera
            while time.time() < limite:
                cookie = cookie_de(ctx)
                if cookie:
                    uid = sirve(cookie)
                    if uid:
                        guardar_estado(ctx)
                        break
                pg.wait_for_timeout(2000)
        finally:
            ctx.close()
    return (cookie, uid) if uid else (None, None)


def guardar(cookie):
    """Reescribe solo la linea BB_COOKIE, respetando el resto del .env.
    Para una cuenta nueva el .env no existe: se crea con BB_HOST y la cookie."""
    lineas, puesto = [], False
    if ENV.exists():
        for ln in ENV.read_text(encoding="utf-8").splitlines():
            if ln.startswith("BB_COOKIE"):
                lineas.append(f"BB_COOKIE='{cookie}'")
                puesto = True
            else:
                lineas.append(ln)
    if not any(l.startswith("BB_HOST") for l in lineas):
        lineas.insert(0, f"BB_HOST={HOST}")
    if not puesto:
        lineas.append(f"BB_COOKIE='{cookie}'")
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    os.chmod(ENV, 0o600)


ap = argparse.ArgumentParser(description="Renueva la cookie de Blackboard")
ap.add_argument("--login", action="store_true",
                help="abre la ventana para hacer el login con MFA a mano")
ap.add_argument("--espera", type=int, default=0,
                help="segundos a esperar (por defecto 20 silencioso, 300 con --login)")
a = ap.parse_args()

espera = a.espera or (300 if a.login else 20)
if a.login:
    print("Se abre Chrome. Inicia sesion en Blackboard (usuario, clave y MFA).")
    print("Cuando el curso cargue, esta ventana se cierra sola.\n")

cookie, uid = obtener(headless=not a.login, espera=espera)

if not cookie:
    if a.login:
        raise SystemExit("No se completo el login a tiempo. Reintenta: python3 sesion.py --login")
    raise SystemExit("La sesion SSO ya no sirve. Corre: python3 sesion.py --login")

guardar(cookie)
exp = re.search(r"expires:([0-9]+)", cookie)
cuando = time.strftime("%H:%M", time.localtime(int(exp.group(1)))) if exp else "?"
quien = f"[{NOMBRE}] " if NOMBRE else ""
print(f"{quien}Cookie renovada para {uid}, vence {cuando}. Escrita en {ENV}")
