"""Render SOLO LECTURA del SQL que aplicarían las migraciones 007->009
(offline, no conecta ni modifica la BD). La URL real se toma de settings."""
import contextlib
import io
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import settings  # noqa: E402

cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    command.upgrade(
        cfg,
        "006_add_campos_texto_libre_wods:2b922f9cd037",
        sql=True,
    )

sql = buf.getvalue()
with open("migraciones_preview.sql", "w", encoding="utf-8") as f:
    f.write(sql)
print(f"Preview SQL generado: {len(sql)} caracteres -> migraciones_preview.sql")
