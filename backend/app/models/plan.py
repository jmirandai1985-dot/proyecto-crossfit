"""
Modelo SQLAlchemy para la tabla planes
"""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Plan(Base):
    __tablename__ = "planes"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(100), nullable=False)
    creditos = Column(Integer, nullable=True)      # NULL = ilimitado
    es_ilimitado = Column(Boolean, nullable=False, default=False)
    genero = Column(String(20), nullable=True)
    es_estudiante = Column(Boolean, nullable=False, default=False)
    requiere_certificado_estudiante = Column(
        Boolean, nullable=False, default=False)
    precio_clp = Column(Integer, nullable=False)
    duracion_dias = Column(Integer, nullable=False, default=30)
    activo = Column(Boolean, nullable=False, default=True)
    # ── ¿Es una membresía COMERCIAL? ──
    # `false` = el plan se materializa como suscripción para habilitar el acceso, pero NO cuenta
    # como cliente: lo excluyen MRR, retención, cohortes, "vigentes", churn y el dataset del ML
    # (`shared.estados.sql_plan_comercial()`, migración 037). Hoy: el "Pase de regreso" de
    # Fidelización. El plan "Prueba" sigue en `true` (no se movió ninguna métrica a propósito).
    es_comercial = Column(Boolean, nullable=False, default=True)
    # ── Plan de prueba (registro de alumno nuevo) ──
    primera_clase_tomada = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    # ── Un nombre de plan por box ──
    # UNIQUE porque dos planes con el mismo nombre en el mismo box son el mismo plan dos veces, y
    # porque es lo que respalda el `ON CONFLICT (tenant_id, nombre) DO NOTHING` con el que
    # `beneficios_service._crear_plan_del_pase` crea (una sola vez) el plan del pase. Hasta la
    # migración 040 ese "si no existe, créalo" se serializaba a mano con un `FOR UPDATE` del box.
    # El NOMBRE del índice es el MISMO que crea esa migración (`CREATE UNIQUE INDEX CONCURRENTLY
    # planes_tenant_nombre`): el seed de TEST y los drills arman el esquema con `create_all()`
    # (run_setup_test_db.py) y un nombre distinto dejaría dos objetos para la misma regla.
    __table_args__ = (
        Index('planes_tenant_nombre', 'tenant_id', 'nombre', unique=True),
    )

    def __repr__(self):
        return f"<Plan(id={self.id}, nombre='{self.nombre}')>"
