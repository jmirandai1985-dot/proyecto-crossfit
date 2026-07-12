"""
Modelo SQLAlchemy para la tabla usuarios
"""
from sqlalchemy import Column, Integer, Float, String, Boolean, Date, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from app.db.database import Base


class RolUsuario(str, enum.Enum):
    """Enum para los roles de usuario"""
    alumno = "alumno"
    coach = "coach"
    administrador = "administrador"


class Usuario(Base):
    """
    Modelo de Usuario
    Representa a los usuarios del sistema (alumnos, coaches, administradores)
    """
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    rut = Column(String(12), nullable=False)
    nombre = Column(String(150), nullable=False)
    telefono = Column(String(20), nullable=True)
    correo = Column(String(150), nullable=False)
    password_hash = Column(String(255), nullable=False)
    rol = Column(SQLEnum(RolUsuario, name="rol_usuario"),
                 nullable=False, default=RolUsuario.alumno)
    activo = Column(Boolean, nullable=False, default=True)
    peso_kg = Column(Float, nullable=True)
    estatura_cm = Column(Integer, nullable=True)
    genero = Column(String(10), nullable=True)
    fecha_nacimiento = Column(Date, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    # Relaciones
    # tenant = relationship("Tenant", back_populates="usuarios")
    # suscripciones = relationship("Suscripcion", back_populates="usuario")
    # reservas = relationship("Reserva", back_populates="usuario")

    def __repr__(self):
        return f"<Usuario(id={self.id}, nombre='{self.nombre}', rol='{self.rol}')>"
