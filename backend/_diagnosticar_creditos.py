"""
Diagnóstico: Reconstruir saldo de creditos del Alumno Demo (id=5) en PRODUCCION.
NO modifica nada, solo consulta.
Usa settings.DATABASE_URL desde .env (no credenciales hardcodeadas).
"""
from sqlalchemy import text
from app.db.database import SessionLocal
from app.core.config import settings
import os
os.environ["ENVIRONMENT"] = ""  # Forzar PROD

print("Conectando a PRODUCCION...")
db_url = settings.DATABASE_URL
if "soft-bar" in db_url:
    print("[ERROR] Conectado a TEST. Abortando.")
    exit(1)
print("[OK] BD: " + db_url[:50] + "...")

db = SessionLocal()
try:
    print("=" * 70)
    print("1. SUSCRIPCION / PLAN del Alumno Demo (id=5)")
    print("=" * 70)

    rows = db.execute(text("""
        SELECT s.id, s.usuario_id, s.plan_id, s.estado,
               s.creditos_totales, s.creditos_disponibles,
               s.fecha_inicio, s.fecha_expiracion,
               p.nombre, p.creditos, p.es_ilimitado
        FROM suscripciones s
        JOIN planes p ON s.plan_id = p.id
        WHERE s.usuario_id = 5 AND s.estado = 'activo'
        ORDER BY s.fecha_inicio DESC
    """)).fetchall()
    for r in rows:
        print(f"  suscripcion_id={r[0]}, plan='{r[8]}', estado={r[3]}")
        print(f"  creditos_totales={r[4]}, creditos_disponibles={r[5]}")
        print(f"  plan.creditos={r[9]}, es_ilimitado={r[10]}")
        print(f"  vigencia: {r[6]} -> {r[7]}")

    print()
    print("=" * 70)
    print("2. RESERVAS ACTIVAS (NO canceladas) del Alumno Demo")
    print("=" * 70)

    reservas = db.execute(text("""
        SELECT r.id, r.clase_id, r.estado, r.tokens_gastados,
               r.asistio, c.fecha, c.hora_inicio
        FROM reservas r
        JOIN clases c ON r.clase_id = c.id
        WHERE r.alumno_id = 5 AND r.estado NOT IN ('cancelled')
        ORDER BY c.fecha DESC
    """)).fetchall()
    print(f"  Total reservas activas: {len(reservas)}")
    for r in reservas:
        print(
            f"  id={r[0]} | clase={r[1]} | estado={r[2]} | tokens={r[3]} | {r[5]} {r[6]}")

    print()
    print("=" * 70)
    print("3. HISTORIAL COMPLETO (TODAS las reservas, incluídas canceladas)")
    print("=" * 70)

    all_res = db.execute(text("""
        SELECT r.id, r.clase_id, r.estado, r.tokens_gastados,
               r.asistio, c.fecha
        FROM reservas r
        JOIN clases c ON r.clase_id = c.id
        WHERE r.alumno_id = 5
        ORDER BY r.id ASC
    """)).fetchall()
    print(f"  Total reservas (historico): {len(all_res)}")
    for r in all_res:
        print(
            f"  id={r[0]:3} | clase={r[1]:3} | estado={r[2]:12} | tokens={r[3]} | fecha={r[5]}")

    print()
    print("=" * 70)
    print("4. RECONSTRUCCION DEL SALDO")
    print("=" * 70)

    s = db.execute(text("""
        SELECT s.creditos_totales, s.creditos_disponibles
        FROM suscripciones s
        WHERE s.usuario_id = 5 AND s.estado = 'activo'
        ORDER BY s.fecha_inicio DESC LIMIT 1
    """)).fetchone()
    base = s[0]
    actual = s[1]
    print(f"  creditos_totales (base asignada):    {base}")
    print(f"  creditos_disponibles (en BD ahora):  {actual}")

    activas = db.execute(text(
        "SELECT COUNT(*) FROM reservas WHERE alumno_id = 5 AND estado NOT IN ('cancelled')"
    )).scalar()
    total_res = db.execute(text(
        "SELECT COUNT(*) FROM reservas WHERE alumno_id = 5"
    )).scalar()
    canceladas = db.execute(text(
        "SELECT COUNT(*) FROM reservas WHERE alumno_id = 5 AND estado = 'cancelled'"
    )).scalar()
    con_tokens = db.execute(text(
        "SELECT COUNT(*) FROM reservas WHERE alumno_id = 5 AND tokens_gastados > 0 AND estado NOT IN ('cancelled')"
    )).scalar()

    print(f"  Reservas activas (no canceladas):    {activas}")
    print(f"  - de ellas con tokens_gastados > 0:  {con_tokens}")
    print(f"  Reservas canceladas:                 {canceladas}")
    print(f"  Total historico:                     {total_res}")

    esperado = base - activas if base else 0
    print()
    print(
        f"  Saldo ESPERADO (base - activas):     {base} - {activas} = {esperado}")
    print(f"  Saldo REAL en BD:                    {actual}")
    print(f"  DIFERENCIA:                          {actual - esperado}")

    print()
    print("=" * 70)
    print("5. BUSQUEDA DE POSIBLE CONTAMINACION POR TEST")
    print("=" * 70)

    suscripciones = db.execute(text("""
        SELECT id, created_at FROM suscripciones
        WHERE usuario_id = 5
        ORDER BY id ASC
    """)).fetchall()
    print(f"  Suscripciones historicas del alumno 5: {len(suscripciones)}")
    for r in suscripciones:
        print(f"  id={r[0]}, creada={r[1]}")

    print(f"  Evolucion de creditos por suscripcion:")
    evol = db.execute(text("""
        SELECT id, created_at, creditos_totales, creditos_disponibles
        FROM suscripciones
        WHERE usuario_id = 5
        ORDER BY id ASC
    """)).fetchall()
    for r in evol:
        print(
            f"  id={r[0]:3} | creada={str(r[1])[:19]} | totales={r[2]} | disponibles={r[3]}")

finally:
    db.close()
