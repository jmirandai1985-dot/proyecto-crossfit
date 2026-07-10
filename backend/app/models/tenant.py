"""
Modelo SQLAlchemy para la tabla tenants
"""
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.database import Base


class Tenant(Base):
    """
    Modelo de Tenant (Box/Gimnasio)
    Representa cada cliente de la plataforma SaaS
    """
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), nullable=False)
    subdomain = Column(String(63), nullable=False, unique=True)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    # Relaciones
    # usuarios = relationship("Usuario", back_populates="tenant")
    # planes = relationship("Plan", back_populates="tenant")

    def __repr__(self):
        return f"<Tenant(id={self.id}, nombre='{self.nombre}', subdomain='{self.subdomain}')>"
