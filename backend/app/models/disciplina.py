"""
Modelo SQLAlchemy para la tabla disciplinas
"""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Disciplina(Base):
    __tablename__ = "disciplinas"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String(500), nullable=True)
    es_open_box = Column(Boolean, nullable=False, default=False)
    activo = Column(Boolean, nullable=False, default=True)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_disciplinas_tenant_nombre',
              'tenant_id', 'nombre', unique=True),
    )

    def __repr__(self):
        return f"<Disciplina(id={self.id}, nombre='{self.nombre}')>"
