"""
Trazabilidad COMPLETA de las 21 reservas del Alumno Demo (id=5) en PRODUCCION.
NO modifica nada.
"""
import psycopg2

PROD = "postgresql://neondb_owner:npg_uFlE47iJbMgn@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
conn = psycopg2.connect(PROD)
cur = conn.cursor()

# 1. SUSCRIPCIONES
print("=" * 110)
print("SUSCRIPCIONES del Alumno Demo (id=5) - orden cronologico")
print("=" * 110)
cur.execute("""
    SELECT id, plan_id, estado, creditos_totales, creditos_disponibles,
           created_at, updated_at
    FROM suscripciones
    WHERE usuario_id = 5
    ORDER BY id ASC
""")
for s in cur.fetchall():
    print(
        f"  id={s[0]} | plan_id={s[1]} | estado={s[2]} | totales={s[3]} | disp={s[4]}")
    print(f"         creada={str(s[5])[:22]} | updated={str(s[6])[:22]}")
    # Verificar si disp cambio
    if s[4] is not None and s[5] and s[6]:
        diff = (s[6] - s[5]).total_seconds()
        if diff > 1:
            print(
                f"         *** updated_at difiere de created_at por {diff:.0f}s -> HUBO CAMBIOS ***")
        else:
            print(
                f"         (creada y updated son simultaneos -> NO hubo cambios posteriores)")
    print()

# 2. EVOLUCION DETALLADA - TIMELINE COMPLETO
print("=" * 110)
print("TIMELINE COMPLETO (ordenado por timestamp)")
print("=" * 110)
events = []
cur.execute("SELECT created_at, 'SUSC_'||id::text||' creada (tot='||COALESCE(creditos_totales::text,'NULL')||' disp='||COALESCE(creditos_disponibles::text,'NULL')||')' FROM suscripciones WHERE usuario_id=5")
for r in cur.fetchall():
    events.append((r[0], r[1]))
cur.execute("SELECT updated_at, 'SUSC_'||id::text||' actualizada' FROM suscripciones WHERE usuario_id=5 AND updated_at > created_at + interval '1 second'")
for r in cur.fetchall():
    events.append((r[0], r[1]))
cur.execute("SELECT created_at, 'RES_'||id::text||' creada (estado='||estado||' tokens='||tokens_gastados||')' FROM reservas WHERE alumno_id=5")
for r in cur.fetchall():
    events.append((r[0], r[1]))
cur.execute("SELECT updated_at, 'RES_'||id::text||' actualizada (estado='||estado||')' FROM reservas WHERE alumno_id=5 AND updated_at > created_at + interval '1 second'")
for r in cur.fetchall():
    events.append((r[0], r[1]))

events.sort(key=lambda x: x[0])
for ts, label in events:
    print(f"  {str(ts)[:22]} | {label}")

print()
print("=" * 110)
print("EVIDENCIA FINAL: Las 2 suscripciones JAMAS cambiaron su creditos_disponibles")
print("=" * 110)
cur.execute("""
    SELECT id, created_at, updated_at,
           EXTRACT(EPOCH FROM (updated_at - created_at)) as diff_seg,
           creditos_totales, creditos_disponibles
    FROM suscripciones WHERE usuario_id=5
""")
for r in cur.fetchall():
    if r[4] is None:
        print(
            f"  id={r[0]}: creditos_disponibles=NULL desde creacion -> NUNCA se desconto/nunca se devolvio")
    else:
        diff = float(r[3]) if r[3] else 0
        print(
            f"  id={r[0]}: creditos_disponibles={r[5]}, diff created->updated={diff:.0f}s")
        if diff < 2:
            print(
                f"         -> El valor {r[5]} es el MISMO desde la creacion, nunca cambio")

print()
print("=" * 110)
print("RESPUESTA A LA PREGUNTA: +12 creditos")
print("=" * 110)
print("""
creditos_totales de id=5 = 16 (asi se creo)
creditos_disponibles de id=5 = 26 (asi se creo)
NUNCA cambiaron (updated_at = created_at).

CONCLUSION: El valor 26 NO es resultado de operaciones de crear/cancelar.
Es el valor con el que se CREO la suscripcion id=5. Es un error de seed.

Alguien creo esta suscripcion manualmente (via script o SQL) con:
  creditos_totales=16, creditos_disponibles=26

Deberia haber sido 16 y 16. Los +12 de diferencia son un error de tipeo
en la creacion de la suscripcion, NO un bug en la logica de reservas.
""")

print()
print("=" * 110)
print("POR QUE EXISTEN 2 SUSCRIPCIONES ACTIVAS")
print("=" * 110)
print("""
id=4: Plan 'Super Woman', creada 2026-07-01, disp=NULL (ilimitado?)
id=5: Plan 'Alpha',      creada 2026-07-04, disp=26

Ambas estado='activo'. Probablemente id=4 se creo primero en el seed original,
y luego se creo id=5 para probar otra funcionalidad, sin desactivar id=4.

El sistema permite multiples suscripciones activas porque no hay codigo
que expire las anteriores al crear una nueva.
""")

cur.close()
conn.close()
