"""Aplica SOLO la migración 013 (public_id en tenants) a la BD ACTIVA.

Usa la URL real de settings.DATABASE_URL (alembic.ini tiene placeholder).
Ejecutar DESPUÉS del backup previo (nunca sin backup):
    python _aplicar_migracion_013.py
(Sin ENVIRONMENT=test → apunta a producción vía .env; verificado por
_alembic_current_prod.py antes y después.)
"""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import settings  # noqa: E402

cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

print("== alembic upgrade head (aplica 013_add_public_id_tenants) ==")
command.upgrade(cfg, "head")
print("\nOK: migración 013 aplicada.")
