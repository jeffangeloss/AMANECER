"""Ciclo completo en un comando: sesion -> materiales -> grabaciones -> estado.

    python bb_todo.py                     todo, con la cuenta por defecto (.env)
    python bb_todo.py --perfil cuenta2    otra cuenta (.env-cuenta2)
    python bb_todo.py --curso ERP         solo los cursos que contengan "ERP"
    python bb_todo.py --sin-grabaciones   solo materiales
    python bb_todo.py --sin-materiales    solo grabaciones
    python bb_todo.py --destino "D:/BB"   bajar a otra carpeta

Es idempotente: lo que ya esta bajado con el mismo tamano se salta, asi
que se puede correr cada semana y solo trae lo nuevo. Si la sesion SSO
vencio, abre Chrome para que inicies sesion (usuario, clave y MFA) y sigue
solo. Cada corrida deja su registro en logs/.
"""
import os, re, sys, time, argparse, subprocess
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AQUI = Path(__file__).resolve().parent
os.chdir(AQUI)  # los scripts resuelven .env y salida/ relativo a esta carpeta

ap = argparse.ArgumentParser(description="Baja materiales y grabaciones de Blackboard")
ap.add_argument("--perfil", default="", help="cuenta: usa .env-PERFIL (sin esto, .env)")
ap.add_argument("--curso", default="", help="filtrar por texto en el nombre del curso")
ap.add_argument("--destino", default=None, help="carpeta base de descarga")
ap.add_argument("--local", action="store_true", help="bajar a ./descargas")
ap.add_argument("--sin-materiales", action="store_true", help="no bajar documentos")
ap.add_argument("--sin-grabaciones", action="store_true", help="no bajar grabaciones de Zoom")
ap.add_argument("--max-mb", type=float, default=None, help="omitir documentos mas grandes")
ap.add_argument("--login", action="store_true", help="forzar la ventana de login")
a = ap.parse_args()

LOGS = AQUI / "logs"
LOGS.mkdir(exist_ok=True)
log = (LOGS / f"bb-todo-{a.perfil or 'principal'}-{time.strftime('%Y%m%d-%H%M%S')}.log").open(
    "w", encoding="utf-8")
COOKIE_RE = re.compile(r"(BbRouter|JSESSIONID)=[^;\s']+")


def decir(texto=""):
    print(texto, flush=True)
    log.write(COOKIE_RE.sub(r"\1=***", texto) + "\n")
    log.flush()


def correr(script, *args):
    """Corre un script del proyecto, muestra y registra su salida.
    Devuelve (codigo, texto)."""
    cmd = [sys.executable, script, *args]
    if a.perfil:
        cmd += ["--perfil", a.perfil]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", env=env)
    lineas = []
    for ln in p.stdout:
        ln = ln.rstrip("\n")
        lineas.append(ln)
        decir("  " + ln)
    p.wait()
    return p.returncode, "\n".join(lineas)


def paso(titulo):
    decir(f"\n=== {titulo} " + "=" * max(0, 60 - len(titulo)))


comunes = []
if a.curso:
    comunes += ["--curso", a.curso]
destino = []
if a.destino:
    destino += ["--destino", a.destino]
if a.local:
    destino += ["--local"]

inicio = time.time()
problemas = []

# 1) sesion: renovacion silenciosa y, si el SSO vencio, login a mano
paso("1/4 Sesion de Blackboard")
cod = 1
if not a.login:
    cod, _ = correr("sesion.py")
if cod != 0:
    decir("  Se abre Chrome: inicia sesion con tu usuario, clave y MFA.")
    cod, _ = correr("sesion.py", "--login")
    if cod != 0:
        decir("\nNo hubo sesion. Vuelve a correr el comando e inicia sesion en la ventana.")
        sys.exit(1)

# 2) materiales: inventario fresco (con tamanos, para saltar lo ya bajado) y descarga
if not a.sin_materiales:
    paso("2/4 Inventario de materiales")
    cod, _ = correr("descargar.py", "--inventario", *comunes)
    if cod != 0:
        problemas.append("inventario de materiales")
    else:
        paso("2/4 Descarga de materiales")
        extra = ["--max-mb", str(a.max_mb)] if a.max_mb else []
        cod, txt = correr("descargar.py", *comunes, *destino, *extra)
        m = re.search(r"(\d+) fallidos", txt)
        if cod != 0 or (m and int(m.group(1)) > 0):
            problemas.append("descarga de materiales (hay fallidos, vuelve a correr)")

# 3) grabaciones: catalogo fresco (sin ventana) y descarga de los MP4 nuevos
if not a.sin_grabaciones:
    paso("3/4 Catalogo de grabaciones de Zoom")
    cod, txt = correr("zoom.py", *comunes)
    cursos = int((re.search(r"(\d+) cursos con Zoom", txt) or [0, 0])[1])
    ok = len(re.findall(r"^\s+\d+ grabaciones$", txt, re.M))
    if cod == 0 and cursos and ok == 0:
        # Ultra a veces no arranca con la cookie inyectada; con una sesion
        # abierta en la misma corrida si (ver zoom.esperar_login).
        decir("  Ningun curso respondio sin ventana. Reintento con Chrome visible.")
        cod, txt = correr("zoom.py", "--login", *comunes)
    if cod != 0:
        problemas.append("catalogo de grabaciones")
    else:
        paso("3/4 Descarga de grabaciones")
        cod, txt = correr("zoom.py", "--descargar", *comunes, *destino)
        if cod != 0 or "FALLA" in txt:
            problemas.append("descarga de grabaciones (hay fallas, vuelve a correr)")

# 4) resumen: que hay en disco frente al catalogo
paso("4/4 Estado")
if a.local or a.destino:
    decir("  (estado.py revisa el destino por defecto; omitido con --destino/--local)")
else:
    correr("estado.py")

min_ = (time.time() - inicio) / 60
decir(f"\nTermino en {min_:.0f} min. Registro: {Path(log.name).relative_to(AQUI)}")
if problemas:
    decir("Con problemas: " + "; ".join(problemas))
    sys.exit(2)
decir("Todo en orden.")
