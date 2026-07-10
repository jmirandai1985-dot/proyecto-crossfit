import psycopg2
from app.core.config import settings

conn = psycopg2.connect(settings.DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'reservas' ORDER BY ordinal_position
""")
print("Columnas actuales en reservas:")
for c in cur.fetchall():
    print(f"  {c[0]}")

conn.close()
