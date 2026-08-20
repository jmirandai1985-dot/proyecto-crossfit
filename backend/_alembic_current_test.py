"""alembic current sobre la branch de TEST (sin imprimir la connection string).

Equivalente a 'alembic current' pero SIN exponer la URL: lee version_num de la
BD activa (ENVIRONMENT=test carga .env.test) y lo compara con el head de las
migraciones locales. Solo lectura.
"""
import os

os.environ["ENVIRONMENT"] = "test"

from sqlalchemy import create_engine, text  # noqa: E402
from app.core.config import settings  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
head = script.get_current_head()
print(f"head de migraciones (local): {head}")

engine = create_engine(settings.DATABASE_URL)
with engine.connect() as c:
    actual = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
print(f"revision en la BD de TEST:   {actual}")

if actual == head:
    print("RESULTADO: OK - la branch de TEST esta al dia con el head de migraciones")
else:
    print(f"RESULTADO: DIFERENTE - branch en {actual}, head local en {head}")
