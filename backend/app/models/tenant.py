"""
Modelo SQLAlchemy para la tabla tenants
"""
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Tenant(Base):
    """
    Modelo de Tenant (Box/Gimnasio)
    Representa cada cliente de la plataforma SaaS
    """
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    subdomain = Column(String(63), nullable=False, unique=True)
    # Identificador NO secuencial (UUID v4) para exponer el box en URLs
    # públicas sin autenticación (pantalla TV del ranking de asistencia).
    # Nunca usar `id` (serial adivinable) ni `subdomain` (texto corto) acá.
    public_id = Column(String(36), nullable=False, unique=True)
    activo = Column(Boolean, nullable=False, default=True)
    # ── Matrícula configurable (UN valor por box, no por plan) ──────────────────
    # Se cobra UNA sola vez, al alumno NUEVO (sin membresía paga previa), y el monto
    # se CONGELA en la solicitud (`solicitudes_planes.matricula_clp_snapshot`): si el
    # admin la apaga o la cambia después, las compras en curso no se mueven.
    # `matricula_activada_en` es la fecha que muestra el panel ("Activa desde el X"):
    # se escribe al encenderla y NO se borra al apagarla (historial del último cambio).
    matricula_activa = Column(Boolean, nullable=False, default=False,
                              server_default="false")
    matricula_monto_clp = Column(Integer, nullable=True)
    matricula_activada_en = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    # Relaciones
    # usuarios = relationship("Usuario", back_populates="tenant")
    # planes = relationship("Plan", back_populates="tenant")

    def __repr__(self):
        return f"<Tenant(id={self.id}, nombre='{self.nombre}', subdomain='{self.subdomain}')>"
