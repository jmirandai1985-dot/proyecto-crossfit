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
    # ── F2 Fidelización: tope del descuento que un beneficio puede ofrecer ──
    # Cuánto % puede regalar el box en el "próximo plan" (`beneficios.valor`). Es
    # configuración y no una constante del código: un box puede querer 20% y otro
    # 50%. `beneficios_service.tope_descuento()` lo lee y cae al default (50) si la
    # fila no existe o el valor es imposible (>100).
    beneficio_descuento_max_pct = Column(
        Integer, nullable=False, server_default="50", default=50)
