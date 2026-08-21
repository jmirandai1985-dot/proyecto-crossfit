"""Solo lectura: estado de alembic_version, columna tenant_id y backfill."""
import sys
sys.stderr = open("_err_tmp.log", "w", encoding="utf-8")
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL)
c = e.connect()
print("version_num:", c.execute(text("SELECT version_num FROM alembic_version")).scalar())
print("col tenant_id existe:", bool(c.execute(text(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_name='notificaciones_enviadas' AND column_name='tenant_id'"
)).fetchone()))
print("filas totales:", c.execute(text("SELECT COUNT(*) FROM notificaciones_enviadas")).scalar())
print("filas tenant NULL:", c.execute(text(
    "SELECT COUNT(*) FROM notificaciones_enviadas WHERE tenant_id IS NULL")).scalar())
print("filas backfilleadas:", c.execute(text(
    "SELECT COUNT(*) FROM notificaciones_enviadas WHERE tenant_id IS NOT NULL")).scalar())
c.close()

