"""Compara lo que hay en disco contra el catalogo. Sirve en cualquiera de
las dos maquinas: el destino sale de comun.destino_base().

    python estado.py            resumen por curso
    python estado.py --faltan   lista lo que falta, para saber que bajar
"""
import sys, csv, argparse, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from comun import sanear, destino_base, carpeta_archivos, carpeta_grabaciones, cargar_perfil, rutas_perfil

PERFIL = cargar_perfil()
SALIDA = rutas_perfil(PERFIL)["salida"]


def nombres_zoom(rs):
    """Mismo esquema que zoom.nombrar(): S{semana}.Clase {n} - DD.MM.YY."""
    out, porcurso = {}, {}
    for r in rs:
        if r.get("inicio"):
            porcurso.setdefault(r["curso"], []).append(r)
    for curso, fs in porcurso.items():
        fs.sort(key=lambda x: x["inicio"])
        d0 = datetime.date.fromisoformat(fs[0]["inicio"][:10])
        lun0 = d0 - datetime.timedelta(days=d0.weekday())
        for i, f in enumerate(fs, 1):
            d = datetime.date.fromisoformat(f["inicio"][:10])
            lun = d - datetime.timedelta(days=d.weekday())
            out[(curso, f["meetingId"])] = \
                f"S{((lun - lun0).days // 7) + 1}.Clase {i} - {d.strftime('%d.%m.%y')}.mp4"
    return out


ap = argparse.ArgumentParser(description="Que hay bajado y que falta")
ap.add_argument("--faltan", action="store_true", help="listar lo que falta")
ap.add_argument("--destino", default=None)
a = ap.parse_args()

base = destino_base(a.destino)
print(f"destino: {base}")
print(f"existe : {base.exists()}\n")

# --- grabaciones ---------------------------------------------------------
p = SALIDA / "zoom.csv"
faltan_z = []
if p.exists():
    with p.open(encoding="utf-8-sig") as fh:
        rs = list(csv.DictReader(fh))
    nom = nombres_zoom(rs)
    porcurso = {}
    for r in rs:
        porcurso.setdefault(r["curso"], []).append(r)
    print("GRABACIONES            hay/total      GB faltantes")
    for curso in sorted(porcurso):
        hay = falta = 0
        bytes_falta = 0
        for r in porcurso[curso]:
            n = nom.get((curso, r["meetingId"]))
            if not n:
                continue
            f = carpeta_grabaciones(curso) / sanear(n)
            esp = int(r["bytes"]) if r["bytes"].isdigit() else 0
            if f.exists() and (not esp or abs(f.stat().st_size - esp) <= esp * 0.02):
                hay += 1
            else:
                falta += 1
                bytes_falta += esp
                faltan_z.append((curso, n))
        print(f"  {curso:30s} {hay:3d}/{hay+falta:<3d}   {bytes_falta/1073741824:6.1f}")

# --- adjuntos ------------------------------------------------------------
p = SALIDA / "inventario.csv"
faltan_a = []
if p.exists():
    with p.open(encoding="utf-8-sig") as fh:
        rs = list(csv.DictReader(fh))
    hay = falta = 0
    bytes_falta = 0
    for r in rs:
        d = carpeta_archivos(r["curso"])
        for parte in filter(None, r["carpeta"].split("/")):
            d = d / sanear(parte)
        f = d / sanear(r["archivo"])
        esp = int(r["bytes"]) if r["bytes"].isdigit() else 0
        if f.exists() and (not esp or abs(f.stat().st_size - esp) <= esp * 0.02):
            hay += 1
        else:
            falta += 1
            bytes_falta += esp
            faltan_a.append((r["curso"], r["ext"], r["archivo"]))
    print(f"\nADJUNTOS                 {hay}/{hay+falta}   faltan {bytes_falta/1073741824:.1f} GB")

if a.faltan:
    if faltan_z:
        print(f"\n--- grabaciones que faltan ({len(faltan_z)}) ---")
        for c, n in faltan_z:
            print(f"  {c:30s} {n}")
    if faltan_a:
        print(f"\n--- adjuntos que faltan ({len(faltan_a)}) ---")
        for c, e, n in faltan_a:
            print(f"  {c:30s} .{e:5s} {n[:60]}")
