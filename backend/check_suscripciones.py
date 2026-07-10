import psycopg2
from app.core.config import settings

conn = psycopg2.connect(settings.DATABASE_URL)
cur = conn.cursor()

cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'suscripciones'
    ORDER BY ordinal_position
""")
cols = cur.fetchall()
print("Columnas en tabla suscripciones:")
for c in cols:
    print(f"  {c[0]} -> {c[1]}")

cur.execute("SELECT COUNT(*) FROM suscripciones")
print(f"\nRegistros: {cur.fetchone()[0]}")

cur.execute("SELECT * FROM suscripciones LIMIT 3")
rows = cur.fetchall()
if rows:
    print("\nPrimeros registros:")
    for r in rows:
        print(f"  {r}")

conn.close()
