"""Verificación amplia de leftovers del harness E2E Fase 4 (solo lectura)."""
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL, poolclass=__import__("sqlalchemy").pool.NullPool)
try:
    with e.connect() as c:
        t = c.execute(text(
            "SELECT id, subdomain FROM tenants WHERE subdomain LIKE 'test-stock-bajo-%'"
        )).fetchall()
        u = c.execute(text(
            "SELECT id, tenant_id, rut, correo FROM usuarios WHERE rut LIKE 'TSB%'"
        )).fetchall()
        pr = c.execute(text(
            "SELECT id, tenant_id, nombre FROM productos WHERE nombre LIKE '%E2E Stock%'"
        )).fetchall()
        pe = c.execute(text(
            "SELECT id, tenant_id FROM pedidos WHERE tenant_id IN "
            "(SELECT id FROM tenants WHERE subdomain LIKE 'test-stock-bajo-%')"
        )).fetchall()
        print("tenants:", [(r.id, r.subdomain) for r in t])
        print("usuarios TSB:", [(r.id, r.tenant_id, r.rut, r.correo) for r in u])
        print("productos E2E:", [(r.id, r.tenant_id, r.nombre) for r in pr])
        print("pedidos tenant stock-bajo:", [(r.id, r.tenant_id) for r in pe])
        total = len(t) + len(u) + len(pr) + len(pe)
        print("TOTAL leftovers:", total)
        raise SystemExit(0 if total == 0 else 1)
finally:
    e.dispose()
