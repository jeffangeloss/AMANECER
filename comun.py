"""Helpers compartidos por descargar.py y zoom.py.

Viven aca para que los dos armen EXACTAMENTE el mismo arbol: si el saneo
de nombres diverge, cada script crea su propia carpeta para el mismo
curso. Por la misma razon se aplica el juego de reglas MAS estricto
(el de Windows) en todas las plataformas: asi macOS y Windows generan
nombres identicos y los arboles se pueden comparar y sincronizar.
"""
import os, re, sys, json, glob, unicodedata
from pathlib import Path
from dotenv import load_dotenv

WINDOWS = sys.platform.startswith("win")


def cargar_perfil(requiere_env=True):
    """Selecciona la cuenta y carga su .env. Devuelve el nombre del perfil.

    El perfil sale de `--perfil NOMBRE` en la linea de comandos (se saca de
    sys.argv para que el argparse de cada script no lo vea) o de la variable
    BB_PERFIL. Sin perfil = la cuenta por defecto (la del dueno).

    Cada cuenta tiene lo suyo:  .env-NOMBRE  .perfil-chrome-NOMBRE
    salida-NOMBRE/  ...pero el MATERIAL de curso va a la carpeta compartida
    (ver destino_base): dos personas del mismo curso comparten los archivos,
    que es justo lo que se quiere. Lo unico por-persona son notas y entregas.
    """
    perfil = os.getenv("BB_PERFIL", "").strip()
    if "--perfil" in sys.argv:
        i = sys.argv.index("--perfil")
        if i + 1 < len(sys.argv):
            perfil = sys.argv[i + 1].strip()
            del sys.argv[i:i + 2]
    perfil = re.sub(r"[^A-Za-z0-9_-]", "", perfil)  # va en nombres de archivo
    envfile = f".env-{perfil}" if perfil else ".env"
    if requiere_env and perfil and not Path(envfile).exists():
        raise SystemExit(f"No existe {envfile}. Corre primero: sesion.py --perfil {perfil} --login")
    load_dotenv(envfile)
    os.environ["BB_PERFIL"] = perfil  # para que lo herede quien sea
    return perfil


def rutas_perfil(perfil):
    """Rutas por-cuenta derivadas del nombre de perfil."""
    suf = f"-{perfil}" if perfil else ""
    return {
        "env": Path(f".env{suf}"),
        "chrome": Path(f".perfil-chrome{suf}"),
        "salida": Path(f"salida{suf}"),
    }

# Windows prohibe estos y ademas reserva nombres de dispositivo: un
# archivo llamado NUL.pdf o COM1.txt no se puede crear, y el error que
# devuelve no dice por que.
ILEGALES = '\\/:*?"<>|'
RESERVADOS = ({"CON", "PRN", "AUX", "NUL"}
              | {f"COM{i}" for i in range(1, 10)}
              | {f"LPT{i}" for i in range(1, 10)})


def sanear(nombre):
    """Nombre valido en APFS y en NTFS a la vez, normalizado a NFC."""
    n = unicodedata.normalize("NFC", (nombre or "").strip())
    for ch in ILEGALES:
        n = n.replace(ch, "-")
    n = re.sub(r"[\x00-\x1f]", "", n)
    n = re.sub(r"\s+", " ", n).strip(" .")
    if n.split(".")[0].upper() in RESERVADOS:
        n = "_" + n
    return n[:120] or "sin_nombre"


def base_drive():
    """Destino por defecto segun la maquina.

    BB_DESTINO en .env manda sobre todo lo demas; es lo que se usa en la
    PC Windows para apuntar al disco grande.
    """
    env = os.getenv("BB_DESTINO", "").strip()
    if env:
        return Path(os.path.expanduser(env))

    if WINDOWS:
        # el disco con mas espacio libre, sin contar el del sistema
        cands = []
        for letra in "DEFGHIJKLMNOPQRSTUVWXYZ":
            p = Path(f"{letra}:\\")
            try:
                if p.exists():
                    cands.append((os.statvfs(p).f_bavail if hasattr(os, "statvfs")
                                  else __import__("shutil").disk_usage(p).free, p))
            except Exception:
                pass
        if cands:
            return max(cands)[1] / "Blackboard ULIMA"
        return Path.home() / "Blackboard ULIMA"

    pat = os.path.expanduser("~/Library/CloudStorage/GoogleDrive-*/Mi unidad")
    hallados = sorted(glob.glob(pat))
    if not hallados:  # sin Google Drive para escritorio: carpeta en el inicio
        return Path.home() / "Blackboard ULIMA"
    return Path(hallados[0]) / "Blackboard ULIMA"


def destino_base(destino=None, local=False):
    """Resuelve la carpeta base segun los flags comunes de ambos scripts."""
    if destino:
        return Path(os.path.expanduser(destino))
    if local:
        return Path("descargas")
    return base_drive()


def cargar_banco():
    """Config del Banco Integral (banco.json), o None si no existe."""
    p = Path("banco.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _seccion(curso):
    """La seccion es lo que va despues del ultimo '/' en el nombre del curso.
    Ej: 'AUD.Y CONT.SISTE. / 851' -> '851'."""
    return curso.rsplit("/", 1)[-1].strip() if "/" in curso else ""


# --- Banco Integral compartido en Google Drive ------------------------------
# Destino por defecto del material de los cursos de la ULima:
#   <Banco>/<[AAAA-S] apodo>/<[AAAA-S] NOMBRE COMPLETO>/[Archivos - seccion] Profesor/
# El semestre sale del codigo del curso (PROPUESTA_20262_...), el profesor de
# la API de Blackboard y el nombre completo de nombres_cursos.json.
BANCO = "[E.P.L.A.] Banco Integral CIS,CII & DEMÁS"
_TERMINO = re.compile(r"_(20\d\d)([0-2])_")


def semestre_de(course_id):
    """'PROPUESTA_20262_650084_1051' -> '2026-2'; None si no es de un semestre."""
    m = _TERMINO.search(course_id or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def raiz_banco():
    """Carpeta del Banco en el Drive de esta maquina, o None.

    BB_BANCO en .env manda. Si no, se busca en Google Drive para escritorio
    (en Windows, cualquier letra con 'My Drive' o 'Mi unidad'; en macOS,
    ~/Library/CloudStorage). Para que aparezca, la carpeta compartida tiene
    que tener un acceso directo en 'Mi unidad'.
    """
    env = os.getenv("BB_BANCO", "").strip()
    if env:
        p = Path(os.path.expanduser(env))
        return p if p.is_dir() else None
    unidades = ("My Drive", "Mi unidad")
    if WINDOWS:
        cands = [Path(f"{l}:\\") / u / BANCO for l in "DEFGHIJKLMNOPQRSTUVWXYZ" for u in unidades]
    else:
        cands = [Path(g) / BANCO for u in unidades for g in sorted(glob.glob(
            os.path.expanduser(f"~/Library/CloudStorage/GoogleDrive-*/{u}")))]
    for c in cands:
        try:
            if c.is_dir():
                return c
        except OSError:
            pass
    return None


def carpeta_semestre(sem):
    """Carpeta '[2026-2] <apodo>' del Banco. No se crea: el apodo lo pone el dueno."""
    raiz = raiz_banco()
    if not raiz or not sem:
        return None
    hallados = sorted(d for d in raiz.glob(f"[[]{sem}[]]*") if d.is_dir())
    if not hallados or not _escribible(hallados[0]):
        return None
    return hallados[0]


_PRUEBAS = {}


def _escribible(carpeta):
    """True si esta cuenta puede crear archivos ahi. Quien tiene la carpeta
    compartida como lector la ve en el Drive pero no puede subir, y
    os.access no lo detecta en Drive para escritorio: se prueba creando un
    archivo vacio propio y quitandolo enseguida. Una vez por corrida."""
    if carpeta not in _PRUEBAS:
        prueba = carpeta / f".amanecer-prueba-{os.getpid()}"
        try:
            prueba.write_bytes(b"")
            prueba.unlink()
            _PRUEBAS[carpeta] = True
        except OSError:
            _PRUEBAS[carpeta] = False
            print(f"  (sin permiso para subir a {carpeta.name}: uso la carpeta personal)")
    return _PRUEBAS[carpeta]


def _abreviatura(curso):
    """'3_SEM.INVES.I / 958' -> 'SEM.INVES.I'."""
    base = curso.rsplit("/", 1)[0].strip() if "/" in curso else curso.strip()
    return unicodedata.normalize("NFC", re.sub(r"^\d+_", "", base))


def nombre_completo(curso):
    """Nombre del curso para la carpeta del Banco. Sale de nombres_cursos.json
    (va en el repo, sin datos personales); si no esta, la abreviatura."""
    p = Path(__file__).with_name("nombres_cursos.json")
    try:
        nombres = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        nombres = {}
    nombres = {unicodedata.normalize("NFC", k): v for k, v in nombres.items()}
    ab = _abreviatura(curso)
    return nombres.get(ab) or ab


def _cache_cursos():
    return rutas_perfil(os.getenv("BB_PERFIL", ""))["salida"] / "cursos.json"


def leer_cursos():
    try:
        return json.loads(_cache_cursos().read_text(encoding="utf-8"))
    except Exception:
        return {}


def registrar_cursos(sesion, host, cursos):
    """Guarda semestre y profesor de cada curso (lista de objetos `course`
    de la API) en salida/cursos.json, para que descargar, zoom y estado
    armen la misma ruta del Banco sin volver a preguntar."""
    cache = leer_cursos()
    for c in cursos:
        nombre = c.get("name") or c.get("courseId") or ""
        info = {"semestre": semestre_de(c.get("courseId")), "profesor": ""}
        try:
            r = sesion.get(f"{host}/learn/api/public/v1/courses/{c['id']}/users",
                           params={"expand": "user", "role": "Instructor"}, timeout=30)
            if r.status_code == 200:
                for u in r.json().get("results", []):
                    n = (u.get("user") or {}).get("name") or {}
                    prof = f"{n.get('given', '')} {n.get('family', '')}".strip()
                    if prof:
                        info["profesor"] = prof
                        break
        except Exception:
            pass
        cache[nombre] = info
    f = _cache_cursos()
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _carpeta_banco(curso, etiqueta):
    """Carpeta del Banco para un curso, separando por tipo.

    Primero el Banco compartido, con el semestre que dice Blackboard. Si el
    curso no tiene semestre (cursos de induccion, examenes de ingles) o este
    Drive no tiene el Banco, se usa banco.json (configuracion vieja del
    dueno) y, si tampoco, el destino personal.
    """
    info = leer_cursos().get(curso) or {}
    sem_dir = carpeta_semestre(info.get("semestre"))
    if sem_dir:
        banco = cargar_banco() or {}
        c = banco.get("cursos", {}).get(curso) or {}
        prof = (info.get("profesor") or c.get("profesor") or "").strip()
        curso_dir = sem_dir / sanear(f"[{info['semestre']}] {nombre_completo(curso)}")
        return curso_dir / sanear(f"[{etiqueta} - {_seccion(curso)}] {prof}")
    return _carpeta_banco_json(curso, etiqueta)


def _carpeta_banco_json(curso, etiqueta):
    """Carpeta del Banco segun banco.json (semestre fijo).

    etiqueta = 'Archivos' o 'Grabaciones'. Sigue la convencion del usuario:
      <banco>/<semestre>/<[pref] NOMBRE>/[etiqueta - seccion] Profesor/
    Los nombres del Banco van VERBATIM (calzan carpetas que ya existen).
    Devuelve None si no hay banco.json o el curso no esta mapeado.
    """
    banco = cargar_banco()
    if not banco:
        return None
    c = banco.get("cursos", {}).get(curso)
    if not c:
        return None
    raiz = destino_base().parent / banco["banco"] / banco["semestre"]
    curso_dir = raiz / f"{banco['prefijo']} {c['nombre']}"
    prof = (c.get("profesor") or "").strip()
    sub = f"[{etiqueta} - {_seccion(curso)}] {prof}".rstrip()
    return curso_dir / sub


def carpeta_archivos(curso, destino=None, local=False):
    """Donde van los documentos de un curso."""
    if not destino and not local:
        r = _carpeta_banco(curso, "Archivos")
        if r:
            return r
    return destino_base(destino, local) / sanear(curso)


def carpeta_grabaciones(curso, destino=None, local=False):
    """Donde van las grabaciones de un curso (MP4 directos, sin subcarpeta)."""
    if not destino and not local:
        r = _carpeta_banco(curso, "Grabaciones")
        if r:
            return r
    # fallback clasico: una subcarpeta Grabaciones dentro de la del curso
    return destino_base(destino, local) / sanear(curso) / "Grabaciones"
