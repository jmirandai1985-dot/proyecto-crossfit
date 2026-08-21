"""Aplica SOLO la migración 011 (tenant_id en notificaciones_enviadas).

Corre alembic upgrade head desde la versión actual (010) → aplica únicamente 011.
Usa la URL real de settings.DATABASE_URL (alembic.ini tiene placeholder).
Ejecutar DESPUÉS del backup previo.
"""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import settings  # noqa: E402

cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

print("== alembic upgrade head (aplica 011) ==")
command.upgrade(cfg, "head")
print("\nOK: migración 011 aplicada.")
