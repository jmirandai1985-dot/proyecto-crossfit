import psycopg2

conn = psycopg2.connect(
    'postgresql://neondb_owner:npg_uFlE47iJbMgn@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require')
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
