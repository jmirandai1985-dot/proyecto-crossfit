"""
DIAGNOSTICO: Alumnos reales con 2+ suscripciones activas simultaneas
SOLO LECTURA - No modifica datos de produccion
Proposito: Verificar si existen otros alumnos (no Demo) con el mismo bug
de "2 suscripciones activas" que corregimos hoy.
"""
from sqlalchemy import text
from app.db.database import SessionLocal
from app.core.config import settings
import os
import sys
from datetime import datetime, timezone

# Forzar conexion a PRODUCCION para diagnostico
os.environ["ENVIRONMENT"] = ""

print("=" * 70)
print("DIAGNOSTICO: Suscripciones activas duplicadas por alumno")
print("=" * 70)

# Verificar que BD estamos usando
db_url = settings.DATABASE_URL
if "soft-bar" in db_url or "test" in db_url.lower():
    print("[ERROR] Conectado a BD de TEST:")
    print(db_url[:60] + "...")
    print("Se requiere la BD de PRODUCCION para este diagnostico.")
    sys.exit(1)

print("[OK] Conectado a BD de PRODUCCION: " + db_url[:60] + "...")
print()

# Conectar
db = SessionLocal()
try:
    # 1. Total suscripciones
    total_suscripciones = db.execute(
        text("SELECT COUNT(*) FROM suscripciones")
    ).scalar()
    print("[DATA] Total suscripciones en BD: " + str(total_suscripciones))

    # 2. Alumnos con 2+ suscripciones activas ahora mismo
    now = datetime.now(timezone.utc)
    sql = text("""
        SELECT 
            s.usuario_id,
            u.nombre AS alumno_nombre,
            u.correo,
            COUNT(*) AS total_activas,
            SUM(CASE WHEN s.creditos_disponibles IS NOT NULL THEN s.creditos_disponibles ELSE 0 END) AS creditos_totales,
            STRING_AGG(s.plan_id::text, ',') AS plan_ids,
            STRING_AGG(p.nombre, ', ') AS planes_nombre,
            STRING_AGG(s.estado::text, ',') AS estados,
            STRING_AGG(s.fecha_expiracion::text, ',') AS fechas_expiracion,
            STRING_AGG(s.creditos_disponibles::text, ',') AS creditos_por_suscripcion
        FROM suscripciones s
        JOIN usuarios u ON s.usuario_id = u.id
        LEFT JOIN planes p ON s.plan_id = p.id
        WHERE s.estado = 'activo'
          AND s.fecha_expiracion > :now
        GROUP BY s.usuario_id, u.nombre, u.correo
        HAVING COUNT(*) >= 2
        ORDER BY COUNT(*) DESC
    """)

    rows = db.execute(sql, {"now": now}).fetchall()

    if not rows:
        print()
        print("[OK] No hay alumnos con 2+ suscripciones activas simultaneas.")
        print("(El unico caso conocido era el usuario Demo, ya corregido)")
    else:
        print()
        print("[WARN] ALUMNOS CON 2+ SUSCRIPCIONES ACTIVAS: " + str(len(rows)))
        print("-" * 70)
        for r in rows:
            print("  Usuario ID: " + str(r.usuario_id))
            print("     Nombre: " + str(r.alumno_nombre) +
                  " (" + str(r.correo) + ")")
            print("     Total activas: " + str(r.total_activas))
            print("     Planes: " + str(r.planes_nombre))
            print("     Estados: " + str(r.estados))
            print("     Creditos totales: " + str(r.creditos_totales))
            print("     Creditos por suscripcion: " +
                  str(r.creditos_por_suscripcion))
            print("     Fechas expiracion: " + str(r.fechas_expiracion))
            print()

    # 3. Total alumnos con al menos 1 suscripcion activa
    total_alumnos_activos = db.execute(text("""
        SELECT COUNT(DISTINCT s.usuario_id)
        FROM suscripciones s
        WHERE s.estado = 'activo'
          AND s.fecha_expiracion > NOW()
    """)).scalar()
    print("[DATA] Total alumnos con al menos 1 suscripcion activa: " +
          str(total_alumnos_activos))

finally:
    db.close()

print()
print("=" * 70)
print("DIAGNOSTICO COMPLETADO - Solo lectura, sin modificar datos")
print("=" * 70)
