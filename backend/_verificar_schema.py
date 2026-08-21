"""Verificación SOLO LECTURA del schema tras aplicar las migraciones."""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import text  # noqa: E402
from app.db.database import engine  # noqa: E402

with engine.connect() as c:
    print("=" * 60)
    print("1) VERSIÓN ALEMBIC EN LA BD")
    print("=" * 60)
    v = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    print("  alembic_version =", v)
    print("  (head esperado  = 2b922f9cd037)")

    print("\n" + "=" * 60)
    print("2) LAS 4 TABLAS NUEVAS (columnas)")
    print("=" * 60)
    tablas = ["coach_disciplinas", "cobertura_emergencia",
              "notificaciones_enviadas", "transacciones_financieras"]
    for t in tablas:
        cols = c.execute(text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t "
            "ORDER BY ordinal_position"), {"t": t}).fetchall()
        print(f"\n  {t}:")
        for col in cols:
            print(f"    - {col[0]:15s} {col[1]:30s} null={col[2]:3s} default={col[3]}")

    print("\n" + "=" * 60)
    print("3) ÍNDICES DE LAS TABLAS NUEVAS")
    print("=" * 60)
    for t in tablas:
        idx = [r[0] for r in c.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename=:t"), {"t": t}).fetchall()]
        print(f"  {t}: {idx}")

    print("\n" + "=" * 60)
    print("4) LAS 4 COLUMNAS NUEVAS (en tablas existentes)")
    print("=" * 60)
    cols = [
        ("planes", "es_estudiante"),
        ("planes", "primera_clase_tomada"),
        ("disciplinas", "requiere_coach"),
        ("pedidos", "voucher_url"),
    ]
    for t, col in cols:
        row = c.execute(text(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:col"),
            {"t": t, "col": col}).fetchone()
        print(f"  {t}.{col}: tipo={row[0]} null={row[1]} default={row[2]}")

print("\nVerificación completada.")
