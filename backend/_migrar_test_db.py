"""
Aplica migracion 006 a la BD de TEST (soft-bar).
"""
from sqlalchemy import create_engine, text
import os
import sys
import importlib
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
os.chdir(base)
os.environ["ENVIRONMENT"] = "test"

settings = importlib.import_module("app.core.config").settings

url = settings.DATABASE_URL.replace(
    "?sslmode=require&channel_binding=require", "?sslmode=require"
)
engine = create_engine(url)

with engine.connect() as conn:
    conn.execute(
        text("ALTER TABLE wods ADD COLUMN IF NOT EXISTS calentamiento TEXT"))
    conn.execute(
        text("ALTER TABLE wods ADD COLUMN IF NOT EXISTS fuerza_habilidad TEXT"))
    conn.execute(
        text("ALTER TABLE wods ADD COLUMN IF NOT EXISTS wod_principal TEXT"))
    conn.execute(
        text("ALTER TABLE wods ADD COLUMN IF NOT EXISTS tipo_metcon VARCHAR(50)"))
    conn.commit()
    print("TEST DB migration applied successfully")
    r = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name='wods' ORDER BY ordinal_position")
    )
    cols = [row[0] for row in r]
    print(f"wods columns ({len(cols)}): {cols}")
