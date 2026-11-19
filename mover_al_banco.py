"""Mueve el material ya descargado de `Blackboard ULIMA/<curso>` a la
estructura del Banco Integral: `<Banco>/<semestre>/<[pref] NOMBRE>/Blackboard/`.

Todo vive en el mismo Drive (Mi unidad), asi que mover es una operacion de
metadatos: instantanea, sin re-subir ni materializar los videos.

    python3 mover_al_banco.py --dry-run     muestra los moves, no toca nada
    python3 mover_al_banco.py               ejecuta

Solo mueve los cursos mapeados en banco.json. Los no mapeados (ej. el
Seminario sin confirmar) se quedan donde estan.
"""
import os, sys, shutil, argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from comun import sanear, destino_base, carpeta_curso, cargar_banco


def fusionar(origen, destino, dry, prof=0):
    """Mueve el contenido de origen dentro de destino. Si un item no existe
    en destino, lo mueve entero (rename, instantaneo). Si ya existe y es
    carpeta, baja recursivo; si es archivo, lo salta (no pisa)."""
    movidos = saltados = 0
    for item in sorted(origen.iterdir()):
        t = destino / item.name
        if not t.exists():
            if not dry:
                destino.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item), str(t))
            movidos += 1
        elif item.is_dir() and t.is_dir():
            m, s = fusionar(item, t, dry, prof + 1)
            movidos += m
            saltados += s
            if not dry and not any(item.iterdir()):
                item.rmdir()
        else:
            saltados += 1  # archivo ya presente: no pisar
    return movidos, saltados


ap = argparse.ArgumentParser(description="Mueve lo descargado al Banco Integral")
ap.add_argument("--dry-run", action="store_true", help="mostrar sin mover")
a = ap.parse_args()

banco = cargar_banco()
if not banco:
    raise SystemExit("Falta banco.json")

base = destino_base()  # Blackboard ULIMA
print(f"origen : {base}")
print(f"banco  : {banco['banco']} / {banco['semestre']}")
print(f"{'DRY-RUN (no toca nada)' if a.dry_run else 'EJECUTANDO'}\n")

tot_mov = tot_salt = 0
for curso in banco["cursos"]:
    origen = base / sanear(curso)
    destino = carpeta_curso(curso)  # .../[pref NOMBRE]/Blackboard
    if not origen.exists():
        print(f"  --  {curso}: sin carpeta en origen, nada que mover")
        continue
    if not destino.parent.exists():
        # curso nuevo en el Banco: se crea, pero se avisa por si es un typo
        print(f"  ++  NUEVA carpeta de curso en el Banco: {destino.parent.name}")
    n_arch = sum(1 for _ in origen.rglob("*") if _.is_file())
    print(f"  {curso}")
    print(f"     {origen}")
    print(f"  -> {destino}   ({n_arch} archivos)")
    m, s = fusionar(origen, destino, a.dry_run)
    tot_mov += m
    tot_salt += s
    if not a.dry_run and origen.exists() and not any(origen.iterdir()):
        origen.rmdir()

print(f"\n{'se moverian' if a.dry_run else 'movidos'}: {tot_mov} items"
      + (f", {tot_salt} ya presentes (saltados)" if tot_salt else ""))
