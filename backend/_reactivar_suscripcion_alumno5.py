"""
Reactiva la suscripciÃ³n del Alumno Demo (id=5) en TEST (small-butterfly).
El Alumno Demo tiene suscripciÃ³n expirada (2026-07-31); hoy es 2026-08-01.
Se extiende la fecha de expiraciÃ³n para poder verificar el flujo de reserva.

SOLO actÃºa sobre TEST. SEGURIDAD: ENVIRONMENT=test.
"""
import os
import sys
import importlib

os.environ["ENVIRONMENT"] = "test"

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

settings = importlib.import_module("app.core.config").settings
db = importlib.import_module("app.db.database").SessionLocal()
text = importlib.import_module("sqlalchemy").text

DB_URL = settings.DATABASE_URL
if "small-butterfly" not in DB_URL:
    sys.exit("FATAL: no es small-butterfly")

print(f"BD: {DB_URL.split('@')[1][:40]}")
try:
    # Mostrar suscripciones actuales del alumno 5
    rows = db.execute(text(
        "SELECT id, plan_id, estado, creditos_disponibles, creditos_totales, fecha_expiracion "
        "FROM suscripciones WHERE usuario_id=5 AND tenant_id=1 ORDER BY id"
    )).fetchall()
    print("Suscripciones alumno 5 ANTES:")
    for r in rows:
        print(
            f"  id={r[0]} plan={r[1]} estado={r[2]} creditos={r[3]}/{r[4]} exp={r[5]}")

    # Extender las suscripciones activas vencidas a +30 dÃ­as
    db.execute(text(
        "UPDATE suscripciones SET fecha_expiracion = NOW() + INTERVAL '30 days' "
        "WHERE usuario_id=5 AND tenant_id=1 AND estado='activo' AND fecha_expiracion < NOW()"
    ))
    db.commit()

    rows2 = db.execute(text(
        "SELECT id, plan_id, estado, creditos_disponibles, creditos_totales, fecha_expiracion "
        "FROM suscripciones WHERE usuario_id=5 AND tenant_id=1 ORDER BY id"
    )).fetchall()
    print("Suscripciones alumno 5 DESPUÃ‰S:")
    for r in rows2:
        print(
            f"  id={r[0]} plan={r[1]} estado={r[2]} creditos={r[3]}/{r[4]} exp={r[5]}")
finally:
    db.close()
