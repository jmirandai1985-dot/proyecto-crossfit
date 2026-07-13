from app.models.disciplina import Disciplina
from app.models.horario_base import HorarioBase as Horario
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan
from app.models.movimiento import Movimiento
from app.models.usuario import Usuario
from app.models.tenant import Tenant
from app.db.database import engine, Base, SessionLocal as DB
from app.core.config import settings
from sqlalchemy import text
import os
import sys

# MUST be set before any app import
os.environ["ENVIRONMENT"] = "test"


# Register models

PROD = "postgresql://neondb_owner:npg_uFlE47iJbMgn@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
TEST = settings.DATABASE_URL

print("=" * 60)
print(f"PROD URL: {PROD[:70]}...")
print(f"TEST URL: {TEST[:70]}...")
print(f"Different? {PROD != TEST}")
print(f"Has soft-bar? {'soft-bar' in TEST}")
print("=" * 60)

if 'soft-bar' not in TEST:
    print("FATAL: Not pointing to test branch")
    sys.exit(1)

Base.metadata.create_all(bind=engine)
print("Tables created.")

db = DB()
try:
    if not db.query(Tenant).filter(Tenant.id == 1).first():
        db.add(Tenant(id=1, nombre="Box Test", subdomain="test-box"))
        db.flush()
        print("Tenant 1")

    if not db.query(Usuario).filter(Usuario.id == 999).first():
        db.add(Usuario(id=999, tenant_id=1, nombre="Alumno Test",
                       email="at@t.com", password_hash="x", rol="alumno",
                       peso_kg=70, genero="masculino", activo=True))
        print("Alumno 999")

    if not db.query(Usuario).filter(Usuario.id == 1000).first():
        db.add(Usuario(id=1000, tenant_id=1, nombre="Coach Test",
                       email="ct@t.com", password_hash="x", rol="coach", activo=True))
        print("Coach 1000")

    if db.query(Movimiento).filter(Movimiento.tenant_id == 1).count() == 0:
        for n in ["Clean", "Snatch", "Deadlift", "Pull-ups", "Burpees"]:
            db.add(Movimiento(tenant_id=1, nombre=n, activo=True))
        print("5 movements")

    if not db.query(Plan).filter(Plan.id == 1).first():
        db.add(Plan(id=1, tenant_id=1, nombre="Plan Test", precio=0,
                    clases_por_semana=5, duracion_dias=30, activo=True, genero="unisex"))
        print("Plan 1")

    from datetime import datetime, timedelta, timezone
    if not db.query(Suscripcion).filter(Suscripcion.usuario_id == 999,
                                        Suscripcion.estado == 'activo').first():
        db.add(Suscripcion(tenant_id=1, usuario_id=999, plan_id=1,
                           fecha_inicio=datetime.now(
                               timezone.utc) - timedelta(days=10),
                           fecha_expiracion=datetime.now(
                               timezone.utc) + timedelta(days=20),
                           creditos_disponibles=50, estado='activo'))
        print("Subscription")

    if not db.query(Disciplina).filter(Disciplina.id == 1).first():
        db.add(Disciplina(id=1, tenant_id=1, nombre="CrossFit", activo=True))
        print("Disciplina 1")

    db.commit()
    print("\nDone! Test DB ready.")
except Exception as e:
    db.rollback()
    print(f"\nError: {e}")
    raise
finally:
    db.close()
