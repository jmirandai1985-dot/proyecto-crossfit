"""
SYNC PROD -> TEST (curly-rain).
IDEMPOTENTE: TRUNCATE + copia todos los datos desde PRODUCCIÓN.
Preserva tablas custom (transacciones_financieras) mediante backup/restore.
"""
from app.core.config import settings
import os
import sys
import psycopg2
import json
import importlib
import re

# ── SEGURIDAD: Verificar ENVIRONMENT ──
ENV = os.environ.get("ENVIRONMENT", "")
if ENV != "test":
    print("="*60)
    print("  ERROR: ENVIRONMENT no es 'test'")
    print("  Si ejecutas esto sin ENVIRONMENT=test borraras PRODUCCION")
    print("  Abortando.")
    sys.exit(1)

# ── CONFIGS y URLs ──
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENVIRONMENT"] = "test"

URL_PROD = settings.DATABASE_URL_PROD
URL_TEST = settings.DATABASE_URL

print("="*60)
print(f"BD de TEST: {URL_TEST[:100]}...")
print(f"CURLY-RAIN (DIRECT): {'curly-rain' in URL_TEST}")
print("="*60)

# ── CONECTAR ──
c_prod = psycopg2.connect(URL_PROD)
c_test = psycopg2.connect(URL_TEST)
c_test.autocommit = True
cur_prod = c_prod.cursor()
cur_test = c_test.cursor()

# ── 1. RESPALDAR tablas custom ──
print("\n[BACKUP] Respaldo transacciones_financieras...")
try:
    cur_test.execute(
        "SELECT id, tenant_id, tipo, categoria, monto, descripcion, referencia_tipo, referencia_id, fecha, created_at FROM transacciones_financieras ORDER BY id")
    backup_tx = cur_test.fetchall()
    print(f"  {len(backup_tx)} transacciones respaldadas")
except Exception as e:
    print(f"  No hay datos para respaldar: {e}")
    backup_tx = []

# ── 2. TRUNCATE CASCADE TEST ──
print("\nTRUNCATE CASCADE TEST...")
cur_test.execute("""
    TRUNCATE TABLE
        tenants, usuarios, movimientos, disciplinas, planes, horarios,
        clases, reservas, historial_rm, notificaciones, productos, pedidos,
        suscripciones, coach_disciplinas, cobertura_emergencia, wods, wod_movimientos,
        solicitudes_plan, compras_emergencia, transacciones_financieras
    CASCADE
""")
print("TEST limpia")

# ── 3. COPIAR PROD→TEST (tablas estándar) ──
print("\nCopiando PROD->TEST...")
TABLAS = [
    ("tenants", None),
    ("movimientos", "id, tenant_id, nombre, descripcion, categoria, activo, created_at, updated_at"),
    ("disciplinas", None),
    ("planes", None),
    ("horarios", None),
    ("usuarios", None),
    ("suscripciones", None),
    ("productos", None),
    ("clases", None),
    ("reservas", None),
    ("historial_rm", None),
    ("notificaciones", None),
]

for tabla, columnas in TABLAS:
    cols = columnas or "*"
    try:
        cur_prod.execute(f"SELECT {cols} FROM {tabla}")
        rows = cur_prod.fetchall()
        if not rows:
            continue
        col_names = [desc[0] for desc in cur_prod.description]
        placeholders = ",".join(["%s"] * len(col_names))
        cols_str = ",".join(col_names)
        for row in rows:
            cur_test.execute(
                f"INSERT INTO {tabla} ({cols_str}) VALUES ({placeholders})", row)
        print(f"  {tabla}: {len(rows)}")
    except Exception as e:
        print(f"  {tabla}: ERROR {e}")

c_test.commit()

# ── 4. RESTAURAR tablas custom ──
print("\n[RESTORE] Restaurando transacciones_financieras...")
if backup_tx:
    for row in backup_tx:
        try:
            cur_test.execute("""
                INSERT INTO transacciones_financieras (id, tenant_id, tipo, categoria, monto, descripcion, referencia_tipo, referencia_id, fecha, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, row)
        except Exception as e:
            print(f"  Error restaurando id={row[0]}: {e}")
    c_test.commit()
    print(f"  {len(backup_tx)} transacciones restauradas")
else:
    print("  Sin datos para restaurar (tabla estaba vacía)")

# ── 5. VERIFICACION ──
print("\nVERIFICACION:")
for tabla in ["tenants", "movimientos", "disciplinas", "planes", "horarios",
              "usuarios", "suscripciones", "productos", "clases", "reservas",
              "historial_rm", "notificaciones"]:
    try:
        cur_test.execute(f"SELECT COUNT(*) FROM {tabla}")
        print(f"  {tabla}: {cur_test.fetchone()[0]}")
    except:
        print(f"  {tabla}: ERROR")

try:
    cur_test.execute("SELECT COUNT(*) FROM transacciones_financieras")
    print(f"  transacciones_financieras: {cur_test.fetchone()[0]}")
except:
    print(f"  transacciones_financieras: 0")

cur_prod.close()
c_prod.close()
cur_test.close()
c_test.close()

print("\nSYNC COMPLETE")
