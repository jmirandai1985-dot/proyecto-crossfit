"""Aplica SOLO la migración 012 (Sistema de Asistencia + Hitos) a la BD ACTIVA.

Usa la URL real de settings.DATABASE_URL (alembic.ini tiene placeholder).
Ejecutar DESPUÉS del backup previo:
    $env:ENVIRONMENT='test'; python _aplicar_migracion_012.py
"""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import settings  # noqa: E402

cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

print("== alembic upgrade head (aplica 012_add_asistencia_hitos) ==")
command.upgrade(cfg, "head")
print("\nOK: migración 012 aplicada.")
