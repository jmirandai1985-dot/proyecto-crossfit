"""
Modelo de Configuracion del Negocio (datos bancarios por tenant)
"""
from sqlalchemy import Column, Integer, String, ForeignKey
from app.db.database import Base


class ConfiguracionNegocio(Base):
    __tablename__ = "configuracion_negocio"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"),
                       nullable=False, unique=True)
    banco = Column(String(200), nullable=True)
    numero_cuenta = Column(String(50), nullable=True)
    # Corriente, Vista, Rut, etc.
    tipo_cuenta = Column(String(50), nullable=True)
    rut = Column(String(20), nullable=True)
    email_comprobantes = Column(String(200), nullable=True)
