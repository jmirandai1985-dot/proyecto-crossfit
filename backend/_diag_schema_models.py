"""Diff SOLO LECTURA modelo ORM vs schema real de la BD activa.
Reporta tablas del modelo que no existen y columnas faltantes por tabla."""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import text  # noqa: E402
from app.db.database import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  (registra todos los modelos)

with engine.connect() as c:
    rows = c.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema='public'")).fetchall()
    db_cols = {}
    for t, col in rows:
        db_cols.setdefault(t, set()).add(col)

print("Modelos registrados en Base.metadata:", len(Base.metadata.tables))
print("Tablas en BD (public):", len(db_cols))

missing_tables = []
missing_cols = {}
for tname in sorted(Base.metadata.tables):
    tbl = Base.metadata.tables[tname]
    if tname not in db_cols:
        missing_tables.append(tname)
        continue
    model_cols = set(tbl.columns.keys())
    falta = model_cols - db_cols[tname]
    if falta:
        missing_cols[tname] = sorted(falta)

print("\n" + "=" * 60)
print("TABLAS del modelo que NO existen en la BD")
print("=" * 60)
if missing_tables:
    for t in missing_tables:
        print(f"  ❌ {t}")
else:
    print("  (ninguna)")

print("\n" + "=" * 60)
print("COLUMNAS FALTANTES por tabla (modelo pide, BD no tiene)")
print("=" * 60)
if not missing_cols:
    print("  (ninguna)")
for t in sorted(missing_cols):
    print(f"  {t}: {missing_cols[t]}")

print("\nDiff completado (solo lectura).")
