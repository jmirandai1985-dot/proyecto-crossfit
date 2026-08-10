"""
DiagnÃ³stico rÃ¡pido: horarios + clases en TEST (lingering-shape).
Solo consulta, no modifica.

SEGURIDAD: setea ENVIRONMENT=test ANTES de importar cualquier mÃ³dulo de app.
"""
from datetime import date
import os
import sys
import importlib

# â”€â”€ SEGURIDAD: forzar ENVIRONMENT=test ANTES de importar app â”€â”€
os.environ["ENVIRONMENT"] = "test"

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

settings = importlib.import_module("app.core.config").settings
db = importlib.import_module("app.db.database").SessionLocal()
text = importlib.import_module("sqlalchemy").text

DB_URL = settings.DATABASE_URL
if "lingering-shape" not in DB_URL:
    sys.exit("FATAL: no es lingering-shape")

hoy = date.today()
print(f"date.today() = {hoy} (weekday={hoy.weekday()})")

try:
    rows = db.execute(text(
        "SELECT id, disciplina_id, dia_semana, hora_inicio, hora_fin, activo, cupo_maximo "
        "FROM horarios WHERE tenant_id=1 ORDER BY disciplina_id, dia_semana, hora_inicio"
    )).fetchall()
    print(f"\nHORARIOS ({len(rows)}):")
    for r in rows:
        print(
            f"  id={r[0]} disc={r[1]} ds={r[2]} {r[3]}-{r[4]} activo={r[5]} cupo={r[6]}")

    rows2 = db.execute(text(
        "SELECT id, fecha, disciplina_id, hora_inicio, hora_fin, coach_id, wod_id "
        "FROM clases WHERE tenant_id=1 ORDER BY fecha DESC LIMIT 20"
    )).fetchall()
    print(f"\nCLASES RECIENTES ({len(rows2)}):")
    for r in rows2:
        print(
            f"  id={r[0]} fecha={r[1]} disc={r[2]} {r[3]}-{r[4]} coach={r[5]} wod={r[6]}")

    total = db.execute(
        text("SELECT COUNT(*) FROM clases WHERE tenant_id=1")).scalar()
    print(f"\nTOTAL CLASES tenant=1: {total}")

    rango = db.execute(text(
        "SELECT MIN(fecha), MAX(fecha) FROM clases WHERE tenant_id=1"
    )).fetchone()
    print(f"RANGO CLASES: {rango[0]} â†’ {rango[1]}")
finally:
    db.close()
