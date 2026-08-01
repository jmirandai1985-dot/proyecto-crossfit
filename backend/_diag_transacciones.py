"""Script de diagnostico: consulta transacciones_financieras directamente."""
import psycopg2

URL = 'postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-muddy-term-aclwd3w7-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

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
