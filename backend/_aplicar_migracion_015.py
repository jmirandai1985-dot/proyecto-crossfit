"""Aplica SOLO la migración 015 (ensancha notificaciones_enviadas.tipo a VARCHAR(50)).

Fix de FASE 1: el tipo 'confirmacion_renovacion' (23 chars) desbordaba el
VARCHAR(20) de notificaciones_enviadas.tipo → el correo se enviaba pero la fila
de trazabilidad no se creaba (StringDataRightTruncation en silencio).

Usa la URL real de settings.DATABASE_URL (alembic.ini tiene placeholder).
Ejecutar contra TEST (ENVIRONMENT=test):
    python _aplicar_migracion_015.py
"""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import settings  # noqa: E402

cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

print("== alembic upgrade head (aplica 015_widen_notif_enviadas_tipo) ==")
command.upgrade(cfg, "head")
print("\nOK: migración 015 aplicada.")
