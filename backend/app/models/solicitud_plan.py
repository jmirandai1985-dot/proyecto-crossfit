"""
Modelo de Solicitud de Plan (pendiente de aprobación admin)
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.db.database import Base


class SolicitudPlan(Base):
    __tablename__ = "solicitudes_planes"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("planes.id"), nullable=False)
    # pending, approved, rejected
    estado = Column(String(20), default="pending", nullable=False)
    voucher_url = Column(Text, nullable=True)
    certificado_estudiante_url = Column(Text, nullable=True)
    # ── P0-4 (S-01): precio del plan AL MOMENTO DE SOLICITAR ──
    # Snapshot para que la aprobación/ingreso no dependa del precio vigente al
    # aprobar (migración 035). NULL en solicitudes históricas.
    precio_clp_snapshot = Column(Integer, nullable=True)
    # ── F2 Fidelización: el descuento que se aplicó a ESTA compra ──
    # El snapshot del descuento es de la solicitud y no del beneficio (el beneficio
    # no sabe qué plan va a comprar el alumno): `precio_clp_snapshot` es el precio de
    # LISTA, `descuento_pct` el % del beneficio usado y `precio_final_clp` lo que se
    # cobró. NULL = se compró sin beneficio (o la solicitud es histórica).
    beneficio_id = Column(Integer, ForeignKey(
        "beneficios.id", ondelete="SET NULL"), nullable=True)
    descuento_pct = Column(Integer, nullable=True)
    precio_final_clp = Column(Integer, nullable=True)
    comentario_admin = Column(String(500), nullable=True)
    aprobado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    # ── Pago online (migración 067) ──
    # `origen_pago='mercadopago'` ⇒ la solicitud NO tiene comprobante: el panel
    # del admin muestra "Pagado online" en vez de intentar abrir un voucher que
    # no existe (GET /solicitudes/{id}/voucher daría 404). `pago_id` es la fila
    # de `pagos` que la cobró (NULL en las transferencias).
    origen_pago = Column(String(12), nullable=False, server_default="manual",
                         default="manual")
    pago_id = Column(Integer, ForeignKey(
        "pagos.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
