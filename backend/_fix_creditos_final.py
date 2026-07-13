"""
UPDATE final: creditos_disponibles=14 en suscripcion id=5 (PRODUCCION).
Luego verifica el valor post-update y las reservas activas.
"""
import psycopg2

PROD = "postgresql://neondb_owner:npg_uFlE47iJbMgn@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
conn = psycopg2.connect(PROD)
cur = conn.cursor()

# Mostrar antes
cur.execute("SELECT creditos_disponibles FROM suscripciones WHERE id=5")
print(f"ANTES: creditos_disponibles = {cur.fetchone()[0]}")

# Aplicar UPDATE
cur.execute("UPDATE suscripciones SET creditos_disponibles=14 WHERE id=5")
print(f"Filas afectadas: {cur.rowcount}")
conn.commit()

# Verificar despues
cur.execute(
    "SELECT id, creditos_totales, creditos_disponibles FROM suscripciones WHERE id=5")
r = cur.fetchone()
print(f"DESPUES: id={r[0]}, totales={r[1]}, disponibles={r[2]}")

# Contar reservas activas
cur.execute(
    "SELECT COUNT(*) FROM reservas WHERE alumno_id=5 AND estado NOT IN ('cancelled')")
activas = cur.fetchone()[0]
print(f"Reservas activas del alumno 5: {activas}")
print(f"Saldo esperado: 16 - {activas} = {16 - activas}")
print(f"Saldo real: {r[2]}")
print(f"CORRECTO: {16 - activas == r[2]}")

cur.close()
conn.close()
