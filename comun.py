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


def _carpeta_banco(curso, etiqueta):
    """Carpeta del Banco para un curso, separando por tipo.

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
