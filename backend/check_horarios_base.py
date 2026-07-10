import psycopg2

conn = psycopg2.connect(
    'postgresql://neondb_owner:npg_uFlE47iJbMgn@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require')
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
