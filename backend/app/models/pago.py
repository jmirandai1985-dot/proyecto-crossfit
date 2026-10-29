"""
Modelos de la pasarela de pagos online (Mercado Pago Checkout Pro).

Dos tablas, con roles distintos a propósito:

* `pagos` es la **fuente de verdad del cobro**: una fila por intento de pago,
  con el monto calculado server-side, el `external_reference` que viaja a MP y
  el `payment_id` que devuelve MP cuando el dinero existe. El estado del negocio
  (`suscripciones`, `pedidos`) NO se deduce de acá: se aplica con la misma
  función que usa el admin (ver `services/aprobacion_planes.py` y
  `services/pedidos_estado.py`).

* `pagos_eventos` es la **bitácora de webhooks**: se inserta ANTES de procesar
  y su `notificacion_id` (el `id` del body de MP) es UNIQUE, así que un
  reintento del mismo aviso no se procesa dos veces. Si el proceso falla, la
  fila queda con `procesado_en = NULL` y el job de reconciliación la levanta.

`transacciones_financieras` no cambia de estructura: la pasarela escribe el
ingreso por la MISMA ruta que la aprobación manual (una sola vez), y el Bazar
sigue contando el ingreso por `pedidos.estado` (ESTADOS_PAGO_BAZAR), sin
transacción nueva.
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, String,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base

# ── Estados internos del pago (NO son los strings de MP) ─────────────────────
# La traducción MP -> interno vive en `services/mercadopago_cliente.py`
# (`estado_desde_mp`) y se prueba sin red en
# `tests/test_pagos_mercadopago_estados.py`.
ESTADOS_PAGO = (
    "pendiente",     # preferencia creada, MP todavía no dijo nada
    "en_proceso",    # in_process / authorized
    "aprobado",      # approved: la plata existe
    "rechazado",     # rejected: se puede reintentar con otro medio
    "cancelado",     # cancelled
    "reembolsado",   # refunded / charged_back (NO se revierte solo)
    "expirado",      # nunca se pagó (job de expiración)
)

# Estados desde los que un pago todavía puede cambiar. `aprobado` sólo puede
# pasar a `reembolsado` (contracargo); `reembolsado` es final.
ESTADOS_PAGO_ABIERTOS = ("pendiente", "en_proceso", "rechazado", "cancelado")



class Pago(Base):
    """Un intento de cobro por pasarela (membresía o compra del Bazar)."""

    __tablename__ = "pagos"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    # Quién paga. Sale del JWT (nunca del body).
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # membresia | bazar | emergencia (emergencia queda para una fase posterior)
    concepto = Column(String(20), nullable=False)
    # solicitud_plan | pedido | suscripcion (referencia polimórfica, igual que
    # `transacciones_financieras`: sin FK, porque apunta a tablas distintas)
    referencia_tipo = Column(String(30), nullable=True)
    referencia_id = Column(Integer, nullable=True)
    # ⚠️ ENTERO en CLP. `pedidos.total` es Float y hay que redondearlo:
    # mandar decimales a MP con moneda CLP es un monto inválido.
    monto_clp = Column(Integer, nullable=False)
    moneda = Column(String(3), nullable=False, server_default="CLP")
    estado = Column(String(20), nullable=False, server_default="pendiente")
    proveedor = Column(String(20), nullable=False, server_default="mercadopago")
    # ids de MP. NULL hasta que existan; UNIQUE para que dos filas no puedan
    # reclamar el mismo cobro.
    preference_id = Column(String(64), nullable=True, unique=True)
    payment_id = Column(String(64), nullable=True, unique=True)
    # UUID que mandamos a MP y con el que volvemos a encontrar el pago cuando
    # el webhook sólo trae el `data.id`. NUNCA es el id secuencial de la fila:
    # ese número no se filtra a un tercero.
    external_reference = Column(String(64), nullable=False, unique=True)
    metodo_pago = Column(String(50), nullable=True)   # payment_method_id
    tipo_pago = Column(String(30), nullable=True)     # payment_type_id
    estado_detalle = Column(String(60), nullable=True)  # status_detail
    pagado_en = Column(TIMESTAMP(timezone=True), nullable=True)
    # Último snapshot del pago leído a MP: auditoría y depuración sin volver a
    # consultar la API. NO se usa para decidir nada (la decisión sale del
    # estado traducido, que se guarda en `estado`).
    detalle_json = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_pagos_tenant_created", "tenant_id", "created_at"),
        Index("ix_pagos_usuario_created", "usuario_id", "created_at"),
        Index("ix_pagos_referencia", "referencia_tipo", "referencia_id"),
        Index("ix_pagos_estado", "estado"),
        CheckConstraint(
            "concepto IN ('membresia', 'bazar', 'emergencia')",
            name="ck_pagos_concepto"),
        CheckConstraint(
            "monto_clp > 0",
            name="ck_pagos_monto_positivo"),
        CheckConstraint(
            "estado IN ('pendiente', 'en_proceso', 'aprobado', 'rechazado', "
            "'cancelado', 'reembolsado', 'expirado')",
            name="ck_pagos_estado"),
    )

    def __repr__(self):
        return (f"<Pago(id={self.id}, concepto='{self.concepto}', "
                f"monto_clp={self.monto_clp}, estado='{self.estado}')>")



class PagoEvento(Base):
    """Un webhook recibido (o un intento rechazado por firma)."""

    __tablename__ = "pagos_eventos"

    id = Column(Integer, primary_key=True)
    # Puede no saberse todavía (si el evento llega antes de asociarlo a un pago).
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="SET NULL"), nullable=True)
    pago_id = Column(Integer, ForeignKey(
        "pagos.id", ondelete="SET NULL"), nullable=True)
    proveedor = Column(String(20), nullable=False, server_default="mercadopago")
    # El `id` (UUID) del body de MP. UNIQUE = dedupe exacto de reintentos: el
    # candado más fuerte contra aplicar dos veces el mismo pago.
    notificacion_id = Column(String(64), nullable=False, unique=True)
    tipo = Column(String(30), nullable=True)         # payment, chargebacks, ...
    recurso_id = Column(String(64), nullable=True)   # data.id (id en MP)
    firma_valida = Column(Boolean, nullable=False, server_default="false")
    request_id = Column(String(64), nullable=True)   # header x-request-id
    ts_header = Column(String(20), nullable=True)    # `ts` de x-signature
    # aplicado | duplicado | monto_no_coincide | desconocido | error | firma_invalida
    resultado = Column(String(40), nullable=True)
    recibido_en = Column(TIMESTAMP(timezone=True),
                         nullable=False, server_default=func.now())
    # NULL = quedó pendiente de reintento/reconciliación.
    procesado_en = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pagos_eventos_pago", "pago_id"),
        Index("ix_pagos_eventos_recibido", "recibido_en"),
    )

    def __repr__(self):
        return (f"<PagoEvento(id={self.id}, tipo='{self.tipo}', "
                f"resultado='{self.resultado}')>")
