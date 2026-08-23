"""Chequeo puntual del tenant 9263800 (creado por el harness E2E Fase 4)."""
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL, poolclass=__import__("sqlalchemy").pool.NullPool)
try:
    with e.connect() as c:
        t = c.execute(text("SELECT id, nombre, subdomain FROM tenants WHERE id = 9263800")).fetchall()
        print("tenant 9263800:", [dict(r._mapping) for r in t])
        u = c.execute(text("SELECT id, tenant_id, correo FROM usuarios WHERE tenant_id = 9263800")).fetchall()
        print("usuarios del tenant:", [dict(r._mapping) for r in u])
        p = c.execute(text("SELECT id, tenant_id, nombre FROM productos WHERE tenant_id = 9263800")).fetchall()
        print("productos del tenant:", [dict(r._mapping) for r in p])
finally:
    e.dispose()
