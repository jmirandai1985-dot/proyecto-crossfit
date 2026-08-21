"""alembic current sobre PRODUCCIÓN (sin imprimir la connection string).

Igual que _alembic_current_test.py pero usa el .env real (no fuerza
ENVIRONMENT=test): lee version_num de la BD activa y lo compara con el head
de las migraciones locales. Solo lectura.
"""
from sqlalchemy import create_engine, text  # noqa: E402
from app.core.config import settings  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
head = script.get_current_head()
print(f"head de migraciones (local): {head}")

url = settings.DATABASE_URL
print(f"BD activa (host/db): {url.split('@')[-1].split('?')[0] if '@' in url else url[:30]}")

engine = create_engine(url)
with engine.connect() as c:
    actual = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
print(f"revision en la BD activa:   {actual}")

if actual == head:
    print("RESULTADO: OK - la BD activa esta al dia con el head de migraciones")
else:
    print(f"RESULTADO: DIFERENTE - BD en {actual}, head local en {head}")
