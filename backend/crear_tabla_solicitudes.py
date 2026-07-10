"""
Script para crear la tabla solicitudes_planes
Importamos todos los modelos para que SQLAlchemy resuelva las FK
"""
from app.db.database import engine, Base
from app.models.tenant import Tenant
from app.models.usuario import Usuario
from app.models.plan import Plan
from app.models.solicitud_plan import SolicitudPlan

if __name__ == "__main__":
    print("Creando tabla solicitudes_planes...")
    Base.metadata.create_all(bind=engine)
    print("✅ Tabla solicitudes_planes creada exitosamente!")
