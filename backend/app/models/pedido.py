"""
Modelo SQLAlchemy para la tabla pedidos
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Pedido(Base):
    """
    Modelo de Pedido
    Representa los pedidos del Bazar Fit
    """
    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    producto_id = Column(Integer, ForeignKey(
        "productos.id", ondelete="CASCADE"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    total = Column(Float, nullable=False)
    # pendiente, validado, entregado
    estado = Column(String(20), nullable=False, default="pendiente")
    voucher_url = Column(String(500), nullable=True)
    # ── Código de retiro (Bazar, migración 044) ──────────────────────────────
    # Se genera UNA vez al VALIDAR el pedido (`services/codigos_retiro.py`) y el
    # alumno lo muestra en el mesón para retirar. Único POR BOX (índice único
    # `uq_pedidos_codigo_retiro`): los pedidos pendientes lo tienen en NULL y en
    # Postgres varios NULL no chocan entre sí.
    codigo_retiro = Column(String(12), nullable=True)
    # Traza de la entrega: quién entregó (admin o coach del box) y cuándo.
    entregado_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    entregado_en = Column(TIMESTAMP(timezone=True), nullable=True)
    fecha_pedido = Column(TIMESTAMP(timezone=True),
                          nullable=False, server_default=func.now())
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Ãndices para bÃºsquedas
    __table_args__ = (
        Index('ix_pedidos_tenant_id', 'tenant_id'),
        Index('ix_pedidos_alumno_id', 'alumno_id'),
        Index('ix_pedidos_producto_id', 'producto_id'),
        Index('ix_pedidos_estado', 'estado'),
        Index('ix_pedidos_fecha_pedido', 'fecha_pedido'),
        # Un codigo de retiro = un solo pedido del box (migracion 044). Los NULL
        # (pedidos sin validar) no chocan entre si en Postgres.
        Index('uq_pedidos_codigo_retiro', 'tenant_id', 'codigo_retiro', unique=True),
        # El formato del codigo vive aca y en services/codigos_retiro.py (PATRON):
        # espejo del CHECK `ck_pedidos_codigo_retiro_formato` de la migracion 044.
        CheckConstraint(
            r"codigo_retiro IS NULL OR "
            r"codigo_retiro ~ '^UB-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$'",
            name='ck_pedidos_codigo_retiro_formato'),
    )

    def __repr__(self):
        return f"<Pedido(id={self.id}, alumno_id={self.alumno_id}, producto_id={self.producto_id}, cantidad={self.cantidad}, estado='{self.estado}')>"
