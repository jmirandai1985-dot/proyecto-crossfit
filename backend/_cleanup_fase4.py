"""Limpieza de leftovers del harness E2E Fase 4 (tenant test-stock-bajo-*)."""
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL, poolclass=__import__("sqlalchemy").pool.NullPool)
try:
    with e.connect() as c:
        rows = c.execute(text(
            "SELECT id, nombre, subdomain FROM tenants "
            "WHERE subdomain LIKE 'test-stock-bajo-%'")).fetchall()
        print("tenants leftovers:", [(r.id, r.subdomain) for r in rows])

    for (tid,) in [(r.id,) for r in rows]:
        tids = f"({tid})"
        with e.begin() as c:
            for sql in [
                f"DELETE FROM pedidos WHERE tenant_id IN {tids}",
                f"DELETE FROM productos WHERE tenant_id IN {tids}",
                f"DELETE FROM suscripciones WHERE tenant_id IN {tids}",
                f"DELETE FROM planes WHERE tenant_id IN {tids}",
                f"DELETE FROM usuarios WHERE tenant_id IN {tids}",
                f"DELETE FROM tenants WHERE id IN {tids}",
            ]:
                c.execute(text(sql))
        print(f"  limpiado tenant {tid}")

    with e.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM tenants WHERE subdomain LIKE 'test-stock-bajo-%'"
        )).scalar()
        print("tenants restantes:", n)
        print("RESULTADO:", "LIMPIO" if n == 0 else "SUCIO")
        raise SystemExit(0 if n == 0 else 1)
finally:
    e.dispose()
