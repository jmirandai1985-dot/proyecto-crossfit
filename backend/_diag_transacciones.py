"""Script de diagnostico: consulta transacciones_financieras directamente."""
import os
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ENVIRONMENT", "test")
from app.core.config import settings

if settings.DATABASE_URL.startswith("postgresql://user:pass@"):
    print("FATAL: Define DATABASE_URL en backend/.env.test (copia .env.example)")
    sys.exit(1)
URL = settings.DATABASE_URL

c = psycopg2.connect(URL)
cur = c.cursor()

print("=== transacciones_financieras ===")
cur.execute("SELECT id, tipo, monto, categoria, fecha, descripcion, referencia_tipo FROM transacciones_financieras WHERE tenant_id=1 ORDER BY id")
for r in cur.fetchall():
    print(
        f"  id={r[0]} tipo={r[1]} monto={r[2]} cat={r[3]} fecha={r[4]} desc={r[5]} ref={r[6]}")
print(f"  Total: {cur.rowcount} filas")

print("\n=== Suma ingresos ===")
cur.execute("SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE 0 END), 0) FROM transacciones_financieras WHERE tenant_id=1 AND fecha >= '2026-07-01' AND fecha <= '2026-07-31'")
print(f"  Ingresos del mes: {cur.fetchone()[0]}")

print("=== Suma egresos ===")
cur.execute("SELECT COALESCE(SUM(CASE WHEN tipo='egreso' THEN monto ELSE 0 END), 0) FROM transacciones_financieras WHERE tenant_id=1 AND fecha >= '2026-07-01' AND fecha <= '2026-07-31'")
print(f"  Egresos del mes: {cur.fetchone()[0]}")

cur.close()
c.close()
