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
    # ── Bloque C: el contacto del box para los correos ────────────────────────
    # El pie de TODOS los correos ofrece "responde este correo" y, si esta columna tiene
    # un número, también el WhatsApp del box (`email_service.contacto_del_box`). Se guarda
    # como texto y no como teléfono normalizado porque lo escribe el admin a mano (+56 9
    # 1234 5678, 9 1234 5678, ...): `wa_link()` normaliza los dígitos al armar el link.
    # NULL/vacío = el correo no promete un canal que el box no atiende.
    whatsapp = Column(String(30), nullable=True)
