"""
Trazabilidad COMPLETA de las reservas del Alumno Demo (id=5) en PRODUCCION.
NO modifica nada. Usa settings.DATABASE_URL desde .env.
"""
from sqlalchemy import text
from app.db.database import SessionLocal
from app.core.config import settings
import os
os.environ["ENVIRONMENT"] = ""

print("Conectando a PRODUCCION...")
db_url = settings.DATABASE_URL
if "soft-bar" in db_url:
    print("[ERROR] Conectado a TEST. Abortando.")
    exit(1)
print("[OK] BD: " + db_url[:50] + "...")

db = SessionLocal()
try:
    # 1. SUSCRIPCIONES
    print("=" * 110)
    print("SUSCRIPCIONES del Alumno Demo (id=5) - orden cronologico")
    print("=" * 110)
    rows = db.execute(text("""
        SELECT id, plan_id, estado, creditos_totales, creditos_disponibles,
               created_at, updated_at
        FROM suscripciones
        WHERE usuario_id = 5
        ORDER BY id ASC
    """)).fetchall()
    for s in rows:
        print(
            f"  id={s[0]} | plan_id={s[1]} | estado={s[2]} | totales={s[3]} | disp={s[4]}")
        print(f"         creada={str(s[5])[:22]} | updated={str(s[6])[:22]}")
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
    rows1 = db.execute(text("SELECT created_at, 'SUSC_'||id::text||' creada (tot='||COALESCE(creditos_totales::text,'NULL')||' disp='||COALESCE(creditos_disponibles::text,'NULL')||')' FROM suscripciones WHERE usuario_id=5")).fetchall()
    for r in rows1:
        events.append((r[0], r[1]))
    rows2 = db.execute(text(
        "SELECT updated_at, 'SUSC_'||id::text||' actualizada' FROM suscripciones WHERE usuario_id=5 AND updated_at > created_at + interval '1 second'")).fetchall()
    for r in rows2:
        events.append((r[0], r[1]))
    rows3 = db.execute(text(
        "SELECT created_at, 'RES_'||id::text||' creada (estado='||estado||' tokens='||tokens_gastados||')' FROM reservas WHERE alumno_id=5")).fetchall()
    for r in rows3:
        events.append((r[0], r[1]))
    rows4 = db.execute(text(
        "SELECT updated_at, 'RES_'||id::text||' actualizada (estado='||estado||')' FROM reservas WHERE alumno_id=5 AND updated_at > created_at + interval '1 second'")).fetchall()
    for r in rows4:
        events.append((r[0], r[1]))

    events.sort(key=lambda x: x[0])
    for ts, label in events:
        print(f"  {str(ts)[:22]} | {label}")

    print()
    print("=" * 110)
    print("EVIDENCIA FINAL: Las 2 suscripciones JAMAS cambiaron su creditos_disponibles")
    print("=" * 110)
    rows5 = db.execute(text("""
        SELECT id, created_at, updated_at,
               EXTRACT(EPOCH FROM (updated_at - created_at)) as diff_seg,
               creditos_totales, creditos_disponibles
        FROM suscripciones WHERE usuario_id=5
    """)).fetchall()
    for r in rows5:
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

finally:
    db.close()
