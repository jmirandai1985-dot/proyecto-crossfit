"""Diagnostica la conexión que usa alembic (search_path, alembic_version)."""
from sqlalchemy import text
from sqlalchemy.engine import create_engine

from app.core.config import settings

url = settings.DATABASE_URL
print("URL host:", url.split("@")[-1].split("/")[0])
print("DB:", url.split("/")[-1])
eng = create_engine(url, poolclass=__import__("sqlalchemy").pool.NullPool)
try:
    with eng.connect() as c:
        sp = c.execute(text("SHOW search_path")).fetchone()
        print("search_path:", sp)
        try:
            v = c.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            print("alembic_version:", v)
        except Exception as e:
            print("alembic_version lectura FALLO:", str(e)[:200])
        t = c.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='alembic_version'")).scalar()
        print("alembic_version en public:", t)
finally:
    eng.dispose()
