"""
Diagnóstico: Reconstruir saldo de créditos del Alumno Demo (id=5) en PRODUCCIÓN.
NO modifica nada, solo consulta.
"""
import psycopg2

PROD = "postgresql://neondb_owner:npg_uFlE47iJbMgn@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
conn = psycopg2.connect(PROD)
cur = conn.cursor()

print("=" * 70)
print("1. SUSCRIPCION / PLAN del Alumno Demo (id=5)")
print("=" * 70)

cur.execute("""
    SELECT s.id, s.usuario_id, s.plan_id, s.estado,
           s.creditos_totales, s.creditos_disponibles,
           s.fecha_inicio, s.fecha_expiracion,
           p.nombre, p.creditos, p.es_ilimitado
    FROM suscripciones s
    JOIN planes p ON s.plan_id = p.id
    WHERE s.usuario_id = 5 AND s.estado = 'activo'
    ORDER BY s.fecha_inicio DESC
""")
for r in cur.fetchall():
    print(f"  suscripcion_id={r[0]}, plan='{r[8]}', estado={r[3]}")
    print(f"  creditos_totales={r[4]}, creditos_disponibles={r[5]}")
    print(f"  plan.creditos={r[9]}, es_ilimitado={r[10]}")
    print(f"  vigencia: {r[6]} -> {r[7]}")

print()
print("=" * 70)
print("2. RESERVAS ACTIVAS (NO canceladas) del Alumno Demo")
print("=" * 70)

cur.execute("""
    SELECT r.id, r.clase_id, r.estado, r.tokens_gastados,
           r.asistio, c.fecha, c.hora_inicio
    FROM reservas r
    JOIN clases c ON r.clase_id = c.id
    WHERE r.alumno_id = 5 AND r.estado NOT IN ('cancelled')
    ORDER BY c.fecha DESC
""")
reservas = cur.fetchall()
print(f"  Total reservas activas: {len(reservas)}")
for r in reservas:
    print(
        f"  id={r[0]} | clase={r[1]} | estado={r[2]} | tokens={r[3]} | {r[5]} {r[6]}")

print()
print("=" * 70)
print("3. HISTORIAL COMPLETO (TODAS las reservas, incluídas canceladas)")
print("=" * 70)

cur.execute("""
    SELECT r.id, r.clase_id, r.estado, r.tokens_gastados,
           r.asistio, c.fecha
    FROM reservas r
    JOIN clases c ON r.clase_id = c.id
    WHERE r.alumno_id = 5
    ORDER BY r.id ASC
""")
all_res = cur.fetchall()
print(f"  Total reservas (histórico): {len(all_res)}")
for r in all_res:
    print(
        f"  id={r[0]:3} | clase={r[1]:3} | estado={r[2]:12} | tokens={r[3]} | fecha={r[5]}")

print()
print("=" * 70)
print("4. RECONSTRUCCION DEL SALDO")
print("=" * 70)

cur.execute("""
    SELECT s.creditos_totales, s.creditos_disponibles
    FROM suscripciones s
    WHERE s.usuario_id = 5 AND s.estado = 'activo'
    ORDER BY s.fecha_inicio DESC LIMIT 1
""")
s = cur.fetchone()
base = s[0]
actual = s[1]
print(f"  creditos_totales (base asignada):    {base}")
print(f"  creditos_disponibles (en BD ahora):  {actual}")

# Contar reservas
cur.execute(
    "SELECT COUNT(*) FROM reservas WHERE alumno_id = 5 AND estado NOT IN ('cancelled')")
activas = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM reservas WHERE alumno_id = 5")
total_res = cur.fetchone()[0]
cur.execute(
    "SELECT COUNT(*) FROM reservas WHERE alumno_id = 5 AND estado = 'cancelled'")
canceladas = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM reservas WHERE alumno_id = 5 AND tokens_gastados > 0 AND estado NOT IN ('cancelled')")
con_tokens = cur.fetchone()[0]

print(f"  Reservas activas (no canceladas):    {activas}")
print(f"  - de ellas con tokens_gastados > 0:  {con_tokens}")
print(f"  Reservas canceladas:                 {canceladas}")
print(f"  Total histórico:                     {total_res}")

esperado = base - activas if base else 0
print(f"")
print(
    f"  Saldo ESPERADO (base - activas):     {base} - {activas} = {esperado}")
print(f"  Saldo REAL en BD:                    {actual}")
print(f"  DIFERENCIA:                          {actual - esperado}")

print()
print("=" * 70)
print("5. BUSQUEDA DE POSIBLE CONTAMINACION POR TEST")
print("=" * 70)

# Buscar si hay registros con notas TEST
cur.execute("""
    SELECT id, created_at FROM suscripciones
    WHERE usuario_id = 5
    ORDER BY id ASC
""")
suscripciones = cur.fetchall()
print(f"  Suscripciones históricas del alumno 5: {len(suscripciones)}")
for r in suscripciones:
    print(f"  id={r[0]}, creada={r[1]}")

# Ver si en algun momento hubo creditos_totales diferente
cur.execute("""
    SELECT id, created_at, creditos_totales, creditos_disponibles
    FROM suscripciones
    WHERE usuario_id = 5
    ORDER BY id ASC
""")
print(f"  Evolución de créditos por suscripción:")
for r in cur.fetchall():
    print(
        f"  id={r[0]:3} | creada={str(r[1])[:19]} | totales={r[2]} | disponibles={r[3]}")

cur.close()
conn.close()
