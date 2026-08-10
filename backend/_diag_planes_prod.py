"""SOLO LECTURA: lista columnas de la tabla planes en PRODUCCION (withered-silence)."""
import psycopg2

URL_PROD = "postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

print("SOLO LECTURA - PRODUCCION (withered-silence)")
print("=" * 60)

c = psycopg2.connect(URL_PROD)
cur = c.cursor()

cur.execute("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'planes'
    ORDER BY ordinal_position
""")
rows = cur.fetchall()
print(f"COLUMNAS DE 'planes' EN PRODUCCION ({len(rows)} total):")
print("-" * 60)
for r in rows:
    print(f"  {r[0]:<40} {r[1]:<20} null={r[2]:<3} default={r[3]}")

print("-" * 60)
nombres = [r[0] for r in rows]
print(f"es_estudiante existe: {'es_estudiante' in nombres}")
print(f"requiere_certificado_estudiante existe: {'requiere_certificado_estudiante' in nombres}")
print(f"requiere_coach existe: {'requiere_coach' in nombres}")

cur.close()
c.close()
print("\nDIAGNOSTICO COMPLETO (solo lectura)")