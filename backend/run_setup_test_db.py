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


# MUST be set before any app import
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


PROD = settings.DATABASE_URL
TEST = settings.DATABASE_URL

print("="*60)
print(f"PROD: {PROD[:70]}...")
print(f"TEST: {TEST[:70]}...")
print(f"DIFFERENT: {PROD != TEST}")
print(f"SOFT-BAR: {'soft-bar' in TEST}")
print("="*60)
if 'soft-bar' not in TEST:
    sys.exit("FATAL: Not test branch")

Base.metadata.create_all(bind=engine)
print("Tables created")

db = DB()
try:
    # ── 1. LIMPIAR TODO ───────────────────────────────────
    print("\n=== LIMPIANDO datos anteriores...")
    # Orden inverso de FK
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

    # ── 7. SUSCRIPCIÓN ────────────────────────────────────
    db.add(Suscripcion(tenant_id=1, usuario_id=999, plan_id=1,
                       fecha_inicio=ahora - timedelta(days=10),
                       fecha_expiracion=ahora + timedelta(days=20),
                       creditos_disponibles=50, estado='activo'))
    db.flush()
    print("   Suscripcion activa (50 creditos)")

    # ── 8. DISCIPLINA ─────────────────────────────────────
    db.add(Disciplina(id=1, tenant_id=1, nombre="CrossFit", activo=True))
    db.flush()
    print("   Disciplina 1")

    # ── 9. HORARIOS BASE (Lun-Vie dinámicos) ──────────────
    for i in range(5):
        db.add(Horario(tenant_id=1, disciplina_id=1,
                       dia_semana=(hoy.weekday() + i) % 7,
                       hora_inicio=time(10, 0), hora_fin=time(11, 0),
                       cupo_maximo=20, activo=True))
    db.flush()
    horario_id = db.query(Horario).filter(Horario.tenant_id == 1).first().id
    print(f"   5 horarios base (desde {hoy.weekday()})")

    # ── 10. CLASES (próximos 7 días) ──────────────────────
    for offset in range(7):
        dia = hoy + timedelta(days=offset)
        db.add(Clase(tenant_id=1, disciplina_id=1,
                     horario_base_id=horario_id,
                     fecha=dia,
                     hora_inicio=time(10, 0),
                     hora_fin=time(11, 0),
                     coach_id=1000, cupo_maximo=20))
    db.flush()
    print("   7 clases (proximos 7 dias)")

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

    db.commit()
    print(f"\n=== DONE! Test DB ready. Fecha: {hoy} ===")
except Exception as e:
    db.rollback()
    print(f"\nError: {e}")
    raise
finally:
    db.close()
