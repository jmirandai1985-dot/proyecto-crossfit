"""Verifica que no queden datos de prueba de la Fase 2 en TEST."""
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL, poolclass=__import__("sqlalchemy").pool.NullPool)
try:
    with e.connect() as c:
        p = c.execute(text(
            "SELECT count(*) FROM productos WHERE nombre LIKE 'TEST Alerta%'")).scalar()
        o = c.execute(text(
            "SELECT count(*) FROM pedidos p JOIN productos pr ON pr.id=p.producto_id "
            "WHERE pr.nombre LIKE 'TEST Alerta%'")).scalar()
        print("productos de prueba restantes:", p)
        print("pedidos de prueba restantes:", o)
        print("alembic_version:", c.execute(text("SELECT version_num FROM alembic_version")).scalar())
        print("RESULTADO:", "LIMPIO" if (p == 0 and o == 0) else "SUCIO")
        raise SystemExit(0 if (p == 0 and o == 0) else 1)
finally:
    e.dispose()
