"""Re-organiza lo ya movido: separa el `Blackboard/` de cada curso en las
dos carpetas de la convencion del usuario:

    [2026-1] NOMBRE/Blackboard/Grabaciones/*   ->  [2026-1] NOMBRE/[Grabaciones - sec] Profesor/
    [2026-1] NOMBRE/Blackboard/<lo demas>      ->  [2026-1] NOMBRE/[Archivos - sec] Profesor/

Luego borra el `Blackboard/` vacio. Todo dentro del mismo Drive (metadatos).

    python3 reorganizar_banco.py --dry-run
    python3 reorganizar_banco.py
"""
import os, sys, shutil, argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from comun import (destino_base, cargar_banco,
                   carpeta_archivos, carpeta_grabaciones)


def mover_contenido(origen, destino, dry):
    """Mueve origen/* dentro de destino, sin pisar (merge recursivo)."""
    movidos = 0
    for item in sorted(origen.iterdir()):
        t = destino / item.name
        if not t.exists():
            if not dry:
                destino.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item), str(t))
            movidos += 1
        elif item.is_dir() and t.is_dir():
            movidos += mover_contenido(item, t, dry)
            if not dry and not any(item.iterdir()):
                item.rmdir()
    return movidos


ap = argparse.ArgumentParser(description="Separa Blackboard/ en Archivos y Grabaciones")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()

banco = cargar_banco()
if not banco:
    raise SystemExit("Falta banco.json")
raiz = destino_base().parent / banco["banco"] / banco["semestre"]
print(f"{'DRY-RUN' if a.dry_run else 'EJECUTANDO'}  en {banco['semestre']}\n")

tot = 0
for curso, c in banco["cursos"].items():
    curso_dir = raiz / f"{banco['prefijo']} {c['nombre']}"
    bb = curso_dir / "Blackboard"
    if not bb.exists():
        print(f"  --  {c['nombre']}: sin Blackboard/, nada que hacer")
        continue
    if not (c.get("profesor") or "").strip():
        print(f"  !!  {c['nombre']}: FALTA profesor en banco.json, lo salto")
        continue

    dst_arch = carpeta_archivos(curso)
    dst_grab = carpeta_grabaciones(curso)
    grabs = bb / "Grabaciones"
    n_g = sum(1 for _ in grabs.glob("*")) if grabs.exists() else 0
    n_a = sum(1 for x in bb.iterdir() if x.name != "Grabaciones")
    print(f"  {c['nombre']}")
    print(f"     grabaciones -> {dst_grab.name}   ({n_g})")
    print(f"     archivos    -> {dst_arch.name}   ({n_a} items)")

    if grabs.exists():
        tot += mover_contenido(grabs, dst_grab, a.dry_run)
        if not a.dry_run and not any(grabs.iterdir()):
            grabs.rmdir()
    if bb.exists():
        tot += mover_contenido(bb, dst_arch, a.dry_run)
        if not a.dry_run and bb.exists() and not any(bb.iterdir()):
            bb.rmdir()

print(f"\n{'se moverian' if a.dry_run else 'movidos'}: {tot} items")
