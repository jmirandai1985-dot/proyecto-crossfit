"""Verificación física de la migración 016 en productos (stock_minimo, alerta_stock_enviada)."""
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL, poolclass=__import__("sqlalchemy").pool.NullPool)
try:
    with e.connect() as c:
        v = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print("alembic_version:", v)
        rows = c.execute(text(
            "SELECT column_name, data_type, is_nullable, COALESCE(column_default,'-') AS default "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='productos' "
            "AND column_name IN ('stock_minimo','alerta_stock_enviada') ORDER BY column_name"
        )).fetchall()
        for r in rows:
            print("columna:", dict(r._mapping))
        total = c.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='productos'"
        )).scalar()
        print("total columnas en productos:", total)
        ok = v == "016_add_stock_minimo_alerta" and len(rows) == 2
        print("RESULTADO:", "OK - 016 aplicada y columnas presentes" if ok else "DIFERENTE - revisar")
        raise SystemExit(0 if ok else 1)
finally:
    e.dispose()
