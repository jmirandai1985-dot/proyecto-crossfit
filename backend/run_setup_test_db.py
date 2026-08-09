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


# â”€â”€ SEGURIDAD: Verificar que ENVIRONMENT sea 'test' â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Si alguien ejecuta este script directamente sin ENVIRONMENT=test,
# config.py cargarÃ­a .env (producciÃ³n) y borrarÃ­a datos reales.
# Esta verificaciÃ³n ocurre ANTES de cualquier import que cargue config.
ENV = os.environ.get("ENVIRONMENT", "")
if ENV != "test":
    print("="*60)
    print("ABORTADO: ENVIRONMENT debe ser 'test' para correr este seed.")
    print("Usa el orquestador (python _run_tests_orchestrator.py) o")
    print("exporta ENVIRONMENT=test manualmente antes de ejecutar.")
    print(f"ENVIRONMENT actual: '{ENV}'")
    print("="*60)
    sys.exit(1)

# MUST be set before any app import (redundante pero explÃ­cito)
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
print(f"lingering-shape (DIRECT): {'lingering-shape' in DB_URL}")
print("="*60)
if 'lingering-shape' not in DB_URL:
    sys.exit("FATAL: Not test branch (lingering-shape/test-nuevo)")

# La branch TEST nueva clona a PROD con tablas/FKs/índices que el mapeo de modelos
# no conoce exactamente. La solución estructural es resetear TODO el schema public
# (CASCADE) y dejar que create_all() lo reconstruya limpio.
# Para evitar el caché del pooler de Neon entre el DROP y el CREATE, esta operación
# usa la conexión DIRECTA (sin "-pooler") con un engine NUEVO dedicado al setup.
from sqlalchemy import create_engine
_setup_url = settings.DATABASE_URL
_setup_url = _setup_url.replace("-pooler.sa-east-1", ".sa-east-1")
setup_engine = create_engine(_setup_url, pool_pre_ping=True)

with setup_engine.connect() as reset_conn:
    reset_conn.execute(text("DROP SCHEMA public CASCADE"))
    reset_conn.execute(text("CREATE SCHEMA public"))
    reset_conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    reset_conn.commit()
    reset_conn.close()
setup_engine.dispose()

# create_all() también usa un engine fresco sobre la conexión directa para
# garantizar que el catálogo vea el esquema recién creado.
Base.metadata.create_all(bind=create_engine(_setup_url))
print("Tables created (schema public reseteado via directa + create_all limpio)")

# â”€â”€ MIGRACIONES POST-CREATE (BD nueva puede no tener columnas migradas) â”€â”€
# Son idempotentes; el mismo ALTER/CREATE existe en sync_test_from_prod.py
with engine.connect() as conn:
    conn.execute(text(
        "ALTER TABLE disciplinas ADD COLUMN IF NOT EXISTS requiere_coach BOOLEAN NOT NULL DEFAULT true"))
    conn.execute(text(
        "ALTER TABLE planes ADD COLUMN IF NOT EXISTS es_estudiante BOOLEAN NOT NULL DEFAULT false"))
    conn.execute(text(
        "ALTER TABLE planes ADD COLUMN IF NOT EXISTS requiere_certificado_estudiante BOOLEAN NOT NULL DEFAULT false"))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS coach_disciplinas (
            id SERIAL PRIMARY KEY,
            tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            coach_id INT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            disciplina_id INT NOT NULL REFERENCES disciplinas(id) ON DELETE CASCADE,
            activo BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cobertura_emergencia (
            id SERIAL PRIMARY KEY,
            tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            usuario_id INT REFERENCES usuarios(id) ON DELETE CASCADE,
            coach_id INT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            clase_id INT NOT NULL REFERENCES clases(id) ON DELETE CASCADE,
            disciplina_id INT NOT NULL REFERENCES disciplinas(id) ON DELETE CASCADE,
            accion VARCHAR(50) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text(
        "ALTER TABLE cobertura_emergencia ADD COLUMN IF NOT EXISTS usuario_id INT REFERENCES usuarios(id) ON DELETE CASCADE"))
    conn.execute(text(
        "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS voucher_url VARCHAR(500)"))
    conn.commit()
print("[OK] Migraciones post-create aplicadas (requiere_coach, es_estudiante, coach_disciplinas, cobertura_emergencia, pedidos.voucher_url)")

db = DB()
try:
    # â”€â”€ 1. LIMPIAR TODO â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("\n=== LIMPIANDO datos anteriores...")
    # Orden inverso de FK
    db.execute(text("DELETE FROM solicitudes_planes"))
    db.execute(text("DELETE FROM notificaciones_enviadas"))
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

    # â”€â”€ 2. FECHAS DINÃMICAS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ahora = datetime.now(timezone.utc)
    hoy = date.today()
    print(f"\n   Fecha actual: {hoy}")

    # â”€â”€ 3. TENANT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    db.add(Tenant(id=1, nombre="Box Test", subdomain="test-box"))
    db.flush()
    print("   Tenant 1")

    # â”€â”€ 4. USUARIOS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ 5. MOVIMIENTOS (con categorÃ­as) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ 6. PLAN â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    db.add(Plan(id=1, tenant_id=1, nombre="Plan Test",
                precio_clp=0, creditos=50,
                duracion_dias=30, activo=True, genero="unisex"))
    db.flush()
    print("   Plan 1")

    # â”€â”€ 7. SUSCRIPCIÃ“N (una sola, siempre) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Asegurar que solo exista UNA suscripciÃ³n activa
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

    # â”€â”€ 8. DISCIPLINAS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    disc_data = [
        (1, "CrossFit"), (2, "Open Box"), (3,
                                           "MusculaciÃ³n"), (4, "Levantamiento OlÃ­mpico"),
    ]
    # Gap se crea como INACTIVA y se filtrarÃ¡ por activo=true en lugar de nombre hardcodeado
    db.add(Disciplina(id=5, tenant_id=1, nombre="Gap", activo=False))
    for d_id, d_nombre in disc_data:
        db.add(Disciplina(id=d_id, tenant_id=1, nombre=d_nombre, activo=True))
    db.flush()
    print(f"   {len(disc_data)} disciplinas activas + Gap (inactiva)")

    # â”€â”€ 8b. COACH-DISCIPLINA (coach 1000 asignado a CrossFit disc 1) â”€â”€
    CoachDisciplina = importlib.import_module(
        "app.models.coach_disciplina").CoachDisciplina
    db.add(CoachDisciplina(tenant_id=1, coach_id=1000, disciplina_id=1, activo=True))
    db.flush()
    print("   Coach 1000 asignado a CrossFit (disc 1)")
    db.flush()

    # â”€â”€ 9. HORARIO BASE (UNO por disciplina activa) â”€â”€â”€â”€â”€â”€
    # Regla de negocio: el seed genera 1 horario por disciplina.
    # En produccion real, un box puede tener multiples turnos por disciplina.
    # Eso es una decision de negocio separada, no del seed de test.
    horario_id_map = {}
    horario_data = [
        # (id, disciplina_id, hora_inicio, hora_fin, cupo, dia_semana)
        (1, 1, time(10, 0), time(11, 0), 20, hoy.weekday()),  # CrossFit - hoy
        (2, 2, time(10, 0), time(11, 0), 10, hoy.weekday()),  # Open Box - hoy
        (3, 3, time(10, 0), time(11, 0), 15, hoy.weekday()),  # MusculaciÃ³n - hoy
        (4, 4, time(10, 0), time(11, 0), 12, hoy.weekday()),  # Lev. OlÃ­mpico - hoy
    ]
    for h_id, disc_id, h_ini, h_fin, cupo, dia in horario_data:
        db.add(Horario(id=h_id, tenant_id=1, disciplina_id=disc_id,
                       dia_semana=dia, hora_inicio=h_ini, hora_fin=h_fin,
                       cupo_maximo=cupo, activo=True))
        horario_id_map[disc_id] = h_id
    db.flush()
    print(f"   {len(horario_data)} horario(s) base (1 por disciplina)")

    # â”€â”€ 10. CLASES (hoy + maÃ±ana para tests de reserva futura) â”€
    class_counter = 1
    # Saltar domingos: la operaciÃ³n estÃ¡ cerrada los domingos (test_c16 lo verifica).
    # Si "maÃ±ana" es domingo, usar el lunes siguiente para la clase futura.
    manana = hoy + timedelta(days=1)
    if manana.weekday() == 6:  # Sunday
        manana = manana + timedelta(days=1)
    for fecha_clase in [hoy, manana]:
        for disc_id, (h_id, h_ini, h_fin, cupo) in {d[1]: (d[0], d[2], d[3], d[4]) for d in horario_data}.items():
            db.add(Clase(id=class_counter, tenant_id=1, disciplina_id=disc_id,
                         horario_base_id=h_id, fecha=fecha_clase,
                         hora_inicio=h_ini, hora_fin=h_fin,
                         coach_id=1000 if disc_id == 1 else None, cupo_maximo=cupo))
            class_counter += 1
    db.flush()
    total_clases = class_counter - 1
    print(
        f"   {total_clases} clase(s) (hoy + manana, {len(horario_data)} disciplinas c/u)")

    # â”€â”€ 11. WOD PUBLICADO PARA HOY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
