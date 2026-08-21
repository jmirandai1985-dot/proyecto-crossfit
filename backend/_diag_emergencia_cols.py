"""Check columnas de cobertura_emergencia y notificaciones en la BD activa."""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL)
with e.connect() as c:
    for t in ('cobertura_emergencia', 'notificaciones'):
        rows = c.execute(text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"),
            {"t": t}).fetchall()
        print(f"=== {t} ===")
        for r in rows:
            print(f"  {r[0]} ({r[1]}, null={r[2]})")
