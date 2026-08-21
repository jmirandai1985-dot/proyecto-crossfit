"""Verificación física de la migración 013 (public_id en tenants) — solo lectura."""
import sys
import uuid

from sqlalchemy import create_engine, text

from app.core.config import settings

e = create_engine(settings.DATABASE_URL)
with e.connect() as c:
    col = c.execute(text(
        "SELECT is_nullable, data_type FROM information_schema.columns "
        "WHERE table_name='tenants' AND column_name='public_id'"
    )).first()
    print("COLUMNA public_id (is_nullable, data_type):", col)

    uniq = c.execute(text(
        "SELECT COUNT(*) FROM information_schema.table_constraints t "
        "JOIN information_schema.key_column_usage k "
        "ON t.constraint_name=k.constraint_name "
        "WHERE t.table_name='tenants' AND t.constraint_type='UNIQUE' "
        "AND k.column_name='public_id'"
    )).scalar()
    print("UNIQUE_constraint_count:", uniq)

    filas = c.execute(text(
        "SELECT id, nombre, subdomain, public_id FROM tenants ORDER BY id"
    )).fetchall()
    print("TOTAL_TENANTS:", len(filas))
    for f in filas:
        pid = f[3]
        es_uuid = True
        try:
            uuid.UUID(str(pid))
        except Exception:
            es_uuid = False
        print(f"  id={f[0]} nombre={f[1]!r} subdomain={f[2]!r} "
              f"public_id={pid} uuid_valido={es_uuid}")

    nulos = c.execute(text(
        "SELECT COUNT(*) FROM tenants WHERE public_id IS NULL OR public_id = ''"
    )).scalar()
    dups = c.execute(text(
        "SELECT COUNT(*) FROM (SELECT public_id FROM tenants "
        "GROUP BY public_id HAVING COUNT(*)>1) x"
    )).scalar()
    print("NULLS_VACIOS:", nulos, "| DUPLICADOS:", dups)

ok = (col is not None and col[0] == "NO" and uniq == 1
      and len(filas) > 0 and all(True for _ in filas)
      and nulos == 0 and dups == 0)
print("VERIFICACION_PHYSICAL:", "OK" if ok else "FALLO")
