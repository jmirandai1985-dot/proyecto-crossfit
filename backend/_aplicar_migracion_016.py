"""Aplica SOLO la migración 016 (stock_minimo + alerta_stock_enviada en productos).

Alerta de stock bajo del Bazar (FASE 1). Usa la URL real de settings.DATABASE_URL.
Ejecutar DESPUÉS del backup (nunca sin backup):
    python _aplicar_migracion_016.py
(Sin ENVIRONMENT=test → apunta a producción vía .env.)
"""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import settings  # noqa: E402

cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

print("== alembic upgrade head (aplica 016_add_stock_minimo_alerta) ==")
command.upgrade(cfg, "head")
print("\nOK: migración 016 aplicada.")
