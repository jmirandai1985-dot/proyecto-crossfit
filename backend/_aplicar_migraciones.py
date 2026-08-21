"""Aplica las migraciones autorizadas: stamp 006 + upgrade head.
Usa la URL real de settings.DATABASE_URL (alembic.ini tiene placeholder)."""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import settings  # noqa: E402

cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

print("== [1/2] alembic stamp 006_add_campos_texto_libre_wods ==")
command.stamp(cfg, "006_add_campos_texto_libre_wods")

print("== [2/2] alembic upgrade head ==")
command.upgrade(cfg, "head")

print("\nOK: stamp + upgrade head aplicados.")
