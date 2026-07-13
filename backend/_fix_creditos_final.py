"""
UPDATE final: creditos_disponibles=14 en suscripcion id=5 (PRODUCCION).
Luego verifica el valor post-update y las reservas activas.

Usa settings.DATABASE_URL desde .env (no credenciales hardcodeadas).
"""
from sqlalchemy import text
from app.db.database import SessionLocal
from app.core.config import settings
import os
os.environ["ENVIRONMENT"] = ""  # Forzar PROD

print("Conectando a PRODUCCION...")
db = SessionLocal()
try:
    # Verificar que es PROD
    db_url = settings.DATABASE_URL
    if "soft-bar" in db_url:
        print("[ERROR] Conectado a TEST. Abortando.")
        exit(1)
    print("[OK] BD: " + db_url[:50] + "...")

    # Mostrar antes
    row = db.execute(
        text("SELECT creditos_disponibles FROM suscripciones WHERE id=5")).fetchone()
    print(f"ANTES: creditos_disponibles = {row[0]}")

    # Aplicar UPDATE
    db.execute(text("UPDATE suscripciones SET creditos_disponibles=14 WHERE id=5"))
    db.commit()
    print("Filas afectadas: 1")

    # Verificar despues
    r = db.execute(text("""
        SELECT id, creditos_totales, creditos_disponibles 
        FROM suscripciones WHERE id=5
    """)).fetchone()
    print(f"DESPUES: id={r[0]}, totales={r[1]}, disponibles={r[2]}")

    # Contar reservas activas
    activas = db.execute(text(
        "SELECT COUNT(*) FROM reservas WHERE alumno_id=5 AND estado NOT IN ('cancelled')"
    )).scalar()
    print(f"Reservas activas del alumno 5: {activas}")
    print(f"Saldo esperado: 16 - {activas} = {16 - activas}")
    print(f"Saldo real: {r[2]}")
    print(f"CORRECTO: {16 - activas == r[2]}")

finally:
    db.close()
