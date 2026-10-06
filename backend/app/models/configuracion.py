"""
Modelo de Configuracion del Negocio (datos bancarios por tenant)
"""
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

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
    # ── Bloque C: el contacto del box para los correos ────────────────────────
    # El pie de TODOS los correos ofrece "responde este correo" y, si esta columna tiene
    # un número, también el WhatsApp del box (`email_service.contacto_del_box`). Se guarda
    # como texto y no como teléfono normalizado porque lo escribe el admin a mano (+56 9
    # 1234 5678, 9 1234 5678, ...): `wa_link()` normaliza los dígitos al armar el link.
    # NULL/vacío = el correo no promete un canal que el box no atiende.
    whatsapp = Column(String(30), nullable=True)

    # ── Trazabilidad del último cambio (I1, migración 046) ───────────────────
    # Con DOS admins por box, "quién cambió la cuenta bancaria y cuándo" no puede vivir
    # sólo en `auditoria` (el admin que abre esta pantalla no lee la auditoría): el que
    # guarda pisa el valor del otro sin avisar. `updated_at` lo escribe la BD (server
    # default en el alta + `onupdate` en cada UPDATE) y `updated_by` lo setea el endpoint
    # con el usuario del token. NULL en `updated_by` = fila anterior a la 046 o borrada
    # la cuenta del admin (`ondelete="SET NULL"`).
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())
    updated_by = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
                        nullable=True)
