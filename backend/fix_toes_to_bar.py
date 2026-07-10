"""
Verifica y corrige el tipo_rm de Toes to Bar en historial_rm
"""
import psycopg2

DATABASE_URL = "postgresql://neondb_owner:npg_uFlE47iJbMgn@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

print("🔌 Conectando a la base de datos...")
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# 1. Encontrar el ID del movimiento Toes to Bar
cur.execute(
    "SELECT id, nombre FROM movimientos WHERE nombre LIKE '%Toes to Bar%' AND tenant_id=1")
movs = cur.fetchall()
if not movs:
    print("❌ No se encontró movimiento 'Toes to Bar'")
    cur.close()
    conn.close()
    exit()

print(f"\n📋 Movimiento(s) encontrado(s):")
for m in movs:
    print(f"   ID={m[0]}, nombre='{m[1]}'")

mov_id = movs[0][0]

# 2. Verificar registros actuales en historial_rm
cur.execute("SELECT id, movimiento_id, peso_kg, tipo_rm, valor_extra, notas FROM historial_rm WHERE movimiento_id=%s AND tenant_id=1", (mov_id,))
registros = cur.fetchall()
print(
    f"\n📋 Registros en historial_rm para Toes to Bar (movimiento_id={mov_id}):")
for r in registros:
    print(
        f"   ID={r[0]}, mov_id={r[1]}, peso_kg={r[2]}, tipo_rm='{r[3]}', valor_extra='{r[4]}', notas='{r[5]}'")

if not registros:
    print("   (sin registros)")
    cur.close()
    conn.close()
    exit()

# 3. Verificar si hay registros con tipo_rm = 'peso' que deberían ser 'reps'
needs_fix = [r for r in registros if r[3] == 'peso']
if needs_fix:
    print(
        f"\n⚠️ {len(needs_fix)} registro(s) con tipo_rm='peso' detectados. Corrigiendo...")
    for r in needs_fix:
        cur.execute(
            "UPDATE historial_rm SET tipo_rm='reps', peso_kg=0 WHERE id=%s", (r[0],))
        print(f"   ✅ Actualizado ID={r[0]}: tipo_rm='peso' -> 'reps'")
    conn.commit()
else:
    print("\n✅ No hay registros con tipo_rm='peso' - ya están correctos")

# 4. Verificar después del fix
cur.execute("SELECT id, movimiento_id, peso_kg, tipo_rm, valor_extra, notas FROM historial_rm WHERE movimiento_id=%s AND tenant_id=1", (mov_id,))
registros_updated = cur.fetchall()
print(f"\n📋 Registros DESPUÉS del fix:")
for r in registros_updated:
    print(
        f"   ID={r[0]}, peso_kg={r[2]}, tipo_rm='{r[3]}', valor_extra='{r[4]}'")

cur.close()
conn.close()
print("\n🔌 Conexión cerrada.")
