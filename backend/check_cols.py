import psycopg2
from app.core.config import settings
conn_str = settings.DATABASE_URL.replace('?sslmode=require&channel_binding=require', '?sslmode=require')


conn = psycopg2.connect(
    conn_str)
conn.autocommit = True
cur = conn.cursor()

for tabla in ['planes', 'horarios', 'clases', 'reservas']:
    cur.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = %s
        ORDER BY ordinal_position
    """, (tabla,))
    cols = cur.fetchall()
    print(f"\nColumnas en tabla {tabla}:")
    for c in cols:
        print(f"  {c[0]} -> {c[1]}")

conn.close()
