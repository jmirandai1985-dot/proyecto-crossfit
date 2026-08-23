"""Compara la conexión de la app (SessionLocal) vs create_engine directo."""
from sqlalchemy import text
from app.db.database import SessionLocal

db = SessionLocal()
try:
    sp = db.execute(text("SHOW search_path")).fetchone()
    print("search_path (app SessionLocal):", sp)
    n = db.execute(text("SELECT count(*) FROM tenants")).scalar()
    print("tenants (app):", n)
    v = db.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    print("alembic_version (app):", v)
finally:
    db.close()
