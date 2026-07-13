import psycopg2
from app.core.config import settings
conn_str = settings.DATABASE_URL.replace('?sslmode=require&channel_binding=require', '?sslmode=require')


conn = psycopg2.connect(
    conn_str)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'horarios_base'
    ORDER BY ordinal_position
""")
cols = cur.fetchall()
print("\nColumnas en tabla horarios_base:")
for c in cols:
    print(f"  {c[0]} -> {c[1]}")

cur.execute("SELECT COUNT(*) FROM horarios_base")
print(f"\nRegistros en horarios_base: {cur.fetchone()[0]}")

conn.close()
