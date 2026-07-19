"""
Seed IDEMPOTENTE para la BD de TEST.
Siempre limpia los datos de prueba anteriores y los recrea con fechas DINAMICAS.
Cada corrida empieza desde cero, sin importar cuando se ejecute.
"""
from datetime import datetime, timedelta, timezone, date, time
import importlib
import os
import sys
# PROD se obtiene de settings.DATABASE_URL con ENVIRONMENT=''
# (definido en _run_tests_orchestrator.py)


# ── SEGURIDAD: Verificar que ENVIRONMENT sea 'test' ───────────────
# Si alguien ejecuta este script directamente sin ENVIRONMENT=test,
# config.py cargaría .env (producción) y borraría datos reales.
# Esta verificación ocurre ANTES de cualquier import que cargue config.
ENV = os.environ.get("ENVIRONMENT", "")
if ENV != "test":
    print("="*60)
    print("ABORTADO: ENVIRONMENT debe ser 'test' para correr este seed.")
    print("Usa el orquestador (python _run_tests_orchestrator.py) o")
    print("exporta ENVIRONMENT=test manualmente antes de ejecutar.")
    print(f"ENVIRONMENT actual: '{ENV}'")
    print("="*60)
    sys.exit(1)

# MUST be set before any app import (redundante pero explícito)
os.environ["ENVIRONMENT"] = "test"

settings = importlib.import_module("app.core.config").settings
engine = importlib.import_module("app.db.database").engine
Base = importlib.import_module("app.db.database").Base
DB = importlib.import_module("app.db.database").SessionLocal
text = importlib.import_module("sqlalchemy").text
Tenant = importlib.import_module("app.models.tenant").Tenant
Usuario = importlib.import_module("app.models.usuario").Usuario
Movimiento = importlib.import_module("app.models.movimiento").Movimiento
Plan = importlib.import_module("app.models.plan").Plan
Suscripcion = importlib.import_module("app.models.suscripcion").Suscripcion
Disciplina = importlib.import_module("app.models.disciplina").Disciplina
Horario = importlib.import_module("app.models.horario_base").HorarioBase
Clase = importlib.import_module("app.models.clase").Clase
Wod = importlib.import_module("app.models.wod").Wod
EstadoWod = importlib.import_module("app.models.wod").EstadoWod
WodMovimiento = importlib.import_module(
    "app.models.wod_movimiento").WodMovimiento
HistorialRM = importlib.import_module("app.models.historial_rm").HistorialRM
Reserva = importlib.import_module("app.models.reserva").Reserva


DB_URL = settings.DATABASE_URL

print("="*60)
print(f"BD de TEST: {DB_URL[:70]}...")
print(f"PURPLE-CHERRY (DIRECT): {'purple-cherry' in DB_URL}")
print("="*60)
if 'purple-cherry' not in DB_URL:
    sys.exit("FATAL: Not test branch (purple-cherry)")

Base.metadata.create_all(bind=engine)
print("Tables created")

db = DB()
try:
    # ── 1. LIMPIAR TODO ───────────────────────────────────
    print("\n=== LIMPIANDO datos anteriores...")
    # Orden inverso de FK
    db.execute(text("DELETE FROM solicitudes_planes"))
    db.execute(text("DELETE FROM notificaciones"))
    db.execute(text("DELETE FROM reservas"))
    db.execute(text("DELETE FROM wod_movimientos"))
    db.execute(text("DELETE FROM historial_rm"))
    db.execute(text("DELETE FROM wods"))
    db.execute(text("DELETE FROM clases"))
    db.execute(text("DELETE FROM horarios"))
    db.execute(text("DELETE FROM suscripciones"))
    db.execute(text("DELETE FROM planes"))
    db.execute(text("DELETE FROM movimientos"))
    db.execute(text("DELETE FROM usuarios"))
    db.execute(text("DELETE FROM disciplinas"))
    db.execute(text("DELETE FROM tenants"))
    db.flush()
    print("   LIMPIEZA COMPLETA.")

    # ── 2. FECHAS DINÁMICAS ───────────────────────────────
    ahora = datetime.now(timezone.utc)
    hoy = date.today()
    print(f"\n   Fecha actual: {hoy}")

    # ── 3. TENANT ─────────────────────────────────────────
    db.add(Tenant(id=1, nombre="Box Test", subdomain="test-box"))
    db.flush()
    print("   Tenant 1")

    # ── 4. USUARIOS ───────────────────────────────────────
    db.add(Usuario(id=999, tenant_id=1, rut="99.999.999-9",
                   nombre="Alumno Test",
                   correo="at@t.com", password_hash="x", rol="alumno",
                   peso_kg=70, genero="masculino", activo=True))
    db.flush()
    print("   Alumno 999")

    db.add(Usuario(id=1000, tenant_id=1, rut="11.111.111-1",
                   nombre="Coach Test",
                   correo="ct@t.com", password_hash="x", rol="coach", activo=True))
    db.flush()
    print("   Coach 1000")

    db.add(Usuario(id=1001, tenant_id=1, rut="11.111.111-2",
                   nombre="Admin Test",
                   correo="admin@test.com", password_hash="x", rol="administrador", activo=True))
    db.flush()
    print("   Admin 1001")

    db.add(Usuario(id=1010, tenant_id=1, rut="11.111.111-3",
                   nombre="Alumno Admin Test",
                   correo="alumno_admin@test.com", password_hash="x", rol="alumno",
                   peso_kg=75, genero="masculino", activo=True))
    db.flush()
    print("   Alumno Admin 1010")

    # ── 5. MOVIMIENTOS (con categorías) ───────────────────
    mov_data = [
        ("Clean", "fuerza"), ("Snatch", "fuerza"),
        ("Deadlift", "fuerza"), ("Back Squat", "fuerza"),
        ("Pull-ups", "gimnastico"), ("Burpees", "metabolico"),
        ("Box Jumps", "metabolico"), ("Wall Balls", "metabolico"),
        ("Row", "cardio"), ("Assault Bike", "cardio"),
        ("Ski Erg", "cardio"),
    ]
    mov_ids = {}
    for nombre, cat in mov_data:
        m = Movimiento(tenant_id=1, nombre=nombre, activo=True, categoria=cat)
        db.add(m)
        db.flush()
        mov_ids[nombre] = m.id
    print(f"   {len(mov_data)} movimientos con categorias")

    # ── 6. PLAN ───────────────────────────────────────────
    db.add(Plan(id=1, tenant_id=1, nombre="Plan Test",
                precio_clp=0, creditos=50,
                duracion_dias=30, activo=True, genero="unisex"))
    db.flush()
    print("   Plan 1")

    # ── 7. SUSCRIPCIÓN (una sola, siempre) ────────────────
    # Asegurar que solo exista UNA suscripción activa
    db.execute(text("DELETE FROM suscripciones WHERE usuario_id = 999"))
    db.flush()
    db.add(Suscripcion(tenant_id=1, usuario_id=999, plan_id=1,
                       fecha_inicio=ahora - timedelta(days=10),
                       fecha_expiracion=ahora + timedelta(days=20),
                       creditos_disponibles=50, estado='activo'))
    db.flush()
    count = db.execute(text(
        "SELECT COUNT(*) FROM suscripciones WHERE usuario_id = 999 AND estado = 'activo'")).scalar()
    assert count == 1, f"Esperaba exactamente 1 suscripcion activa, hay {count}"
    print("   Suscripcion activa (50 creditos) [OK: exactamente 1]")

    # ── 8. DISCIPLINAS ─────────────────────────────────────
    disc_data = [
        (1, "CrossFit"), (2, "Open Box"), (3,
                                           "Musculación"), (4, "Levantamiento Olímpico"),
    ]
    # Gap se crea como INACTIVA y se filtrará por activo=true en lugar de nombre hardcodeado
    db.add(Disciplina(id=5, tenant_id=1, nombre="Gap", activo=False))
    for d_id, d_nombre in disc_data:
        db.add(Disciplina(id=d_id, tenant_id=1, nombre=d_nombre, activo=True))
    db.flush()
    print(f"   {len(disc_data)} disciplinas activas + Gap (inactiva)")
    db.flush()

    # ── 9. HORARIOS BASE (varios turnos por disciplina) ───
    horario_id_map = {}
    horario_counter = 1
    turnos = [
        # (disciplina_id, hora_inicio, hora_fin, cupo)
        (1, time(7, 0), time(8, 0), 20),   # CrossFit AM
        (1, time(8, 0), time(9, 0), 20),
        (1, time(10, 0), time(11, 0), 20),  # CrossFit AM2
        (1, time(12, 0), time(13, 0), 15),  # CrossFit MD
        (1, time(17, 0), time(18, 0), 20),  # CrossFit PM
        (1, time(18, 0), time(19, 0), 20),
        (1, time(19, 0), time(20, 0), 20),
        (2, time(8, 0), time(9, 0), 10),   # Open Box
        (2, time(10, 0), time(11, 0), 10),
        (2, time(12, 0), time(13, 0), 10),
        (2, time(17, 0), time(18, 0), 10),
        (2, time(18, 0), time(19, 0), 10),
        (3, time(7, 0), time(8, 0), 15),   # Musculación
        (3, time(10, 0), time(11, 0), 15),
        (3, time(12, 0), time(13, 0), 15),
        (3, time(17, 0), time(19, 0), 15),
        (4, time(8, 0), time(9, 0), 12),   # Lev. Olímpico
        (4, time(10, 0), time(11, 0), 12),
        (4, time(17, 0), time(18, 0), 12),
    ]
    for disc_id, h_ini, h_fin, cupo in turnos:
        db.add(Horario(id=horario_counter, tenant_id=1, disciplina_id=disc_id,
                       dia_semana=(hoy.weekday() + 0) % 7,  # Hoy
                       hora_inicio=h_ini, hora_fin=h_fin,
                       cupo_maximo=cupo, activo=True))
        horario_id_map[(disc_id, h_ini)] = horario_counter
        horario_counter += 1
    db.flush()
    print(f"   {len(turnos)} horarios base (hoy, multiples turnos)")

    # ── 10. CLASES (próximos 7 días) ──────────────────────
    class_counter = 1
    for offset in range(7):
        dia = hoy + timedelta(days=offset)
        dia_sem = (hoy.weekday() + offset) % 7
        # Por cada disciplina, crear clases para los horarios de ese día
        for disc_id, h_ini, h_fin, cupo in turnos:
            # Solo crear si el dia_semana coincide con el horario (todos son hoy por simplicidad)
            if offset > 0 and dia_sem > 4:  # Finde: menos clases
                if disc_id not in [1, 3]:
                    continue
                if h_ini.hour not in [10, 12, 17]:
                    continue
            db.add(Clase(id=class_counter, tenant_id=1, disciplina_id=disc_id,
                         horario_base_id=horario_id_map.get(
                             (disc_id, h_ini), 1),
                         fecha=dia,
                         hora_inicio=h_ini, hora_fin=h_fin,
                         coach_id=1000, cupo_maximo=cupo))
            class_counter += 1
    db.flush()
    total_clases = class_counter - 1
    print(f"   {total_clases} clases ({7} dias)")

    # ── 11. WOD PUBLICADO PARA HOY ────────────────────────
    clean_id = mov_ids.get("Clean", 1)
    wod = Wod(tenant_id=1, fecha=hoy, titulo="WOD Test",
              descripcion="WOD de prueba para tests",
              coach_id=1000, estado=EstadoWod.publicado)
    db.add(wod)
    db.flush()
    wod_mov = WodMovimiento(wod_id=wod.id, movimiento_id=clean_id,
                            orden=1, series=3, repeticiones="10")
    db.add(wod_mov)
    db.flush()
    print("   WOD publicado para hoy")

    # Extra safety: force-clean any suscripcion for user 999 that startup_event might have created
    # and ensure exactly 1 remains
    db.execute(text(
        "DELETE FROM suscripciones WHERE usuario_id = 999 AND creditos_disponibles != 50"))
    db.flush()
    count_final = db.execute(text(
        "SELECT COUNT(*) FROM suscripciones WHERE usuario_id = 999 AND estado = 'activo'")).scalar()
    if count_final != 1:
        db.execute(text("DELETE FROM suscripciones WHERE usuario_id = 999"))
        db.flush()
        db.add(Suscripcion(tenant_id=1, usuario_id=999, plan_id=1,
                           fecha_inicio=ahora - timedelta(days=10),
                           fecha_expiracion=ahora + timedelta(days=20),
                           creditos_disponibles=50, estado='activo'))
        db.flush()
        print("   [SAFETY] Suscripcion recreada forzosamente")

    db.commit()
    count_verify = db.execute(text(
        "SELECT COUNT(*) FROM suscripciones WHERE usuario_id = 999 AND estado = 'activo'")).scalar()
    assert count_verify == 1, f"FATAL: {count_verify} suscripciones activas para alumno 999 despues del commit"
    print(f"\n=== DONE! Test DB ready. Fecha: {hoy} ===")
except Exception as e:
    db.rollback()
    print(f"\nError: {e}")
    raise
finally:
    db.close()
