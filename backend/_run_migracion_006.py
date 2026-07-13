"""
Ejecuta migracion 006 en BD de PRODUCCION:
- Agrega columnas calentamiento, fuerza_habilidad, wod_principal, tipo_metcon
- Borra los 4 WODs viejos con formato estructurado
"""
from sqlalchemy import create_engine, text
import importlib
import os
import sys

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
os.chdir(base)
os.environ["ENVIRONMENT"] = ""

# Import using importlib AFTER setting ENVIRONMENT
settings = importlib.import_module("app.core.config").settings


url = settings.DATABASE_URL.replace(
    "?sslmode=require&channel_binding=require", "?sslmode=require"
)
print(f"Conectando a: {url[:70]}...")
engine = create_engine(url)

with engine.connect() as conn:
    # Migracion: agregar columnas
    conn.execute(
        text("ALTER TABLE wods ADD COLUMN IF NOT EXISTS calentamiento TEXT"))
    conn.execute(
        text("ALTER TABLE wods ADD COLUMN IF NOT EXISTS fuerza_habilidad TEXT"))
    conn.execute(
        text("ALTER TABLE wods ADD COLUMN IF NOT EXISTS wod_principal TEXT"))
    conn.execute(
        text("ALTER TABLE wods ADD COLUMN IF NOT EXISTS tipo_metcon VARCHAR(50)"))
    conn.commit()
    print("Columnas agregadas (o ya existian)")

    # Verificar columnas
    r = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name='wods' ORDER BY ordinal_position")
    )
    cols = [row[0] for row in r]
    print(f"Columnas en wods ({len(cols)}): {cols}")

    # Borrar WODs viejos
    r = conn.execute(text("SELECT COUNT(*) FROM wods"))
    antes = r.scalar()
    print(f"WODs antes de borrar: {antes}")

    conn.execute(text("DELETE FROM wod_movimientos"))
    conn.execute(text("DELETE FROM wods"))
    conn.commit()

    r = conn.execute(text("SELECT COUNT(*) FROM wods"))
    despues = r.scalar()
    print(
        f"WODs despues de borrar: {despues} {'OK' if despues == 0 else 'ERROR'}")

print("Migracion 006 completada.")
