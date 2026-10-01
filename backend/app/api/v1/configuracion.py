"""
Router de Configuracion del Negocio (datos bancarios por tenant)
GET /api/v1/configuracion?tenant_id=1 — publico (lo ve el alumno al subir voucher)
PUT /api/v1/configuracion — solo admin, para editar
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.models.configuracion import ConfiguracionNegocio
from app.models.usuario import Usuario
from app.core.dependencies import get_current_user, get_current_admin

router = APIRouter()


class ConfiguracionUpdate(BaseModel):
    banco: Optional[str] = None
    numero_cuenta: Optional[str] = None
    tipo_cuenta: Optional[str] = None
    rut: Optional[str] = None
    email_comprobantes: Optional[str] = None
    # Bloque C: el WhatsApp del box para el pie de los correos (vacío = sólo responder
    # el correo). El link lo arma `email_service.wa_link()` a partir de los dígitos.
    whatsapp: Optional[str] = None


@router.get("")
def obtener_configuracion(
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene la configuracion del negocio (datos bancarios) para un tenant."""
    config = db.query(ConfiguracionNegocio).filter(
        ConfiguracionNegocio.tenant_id == tenant_id
    ).first()

    if not config:
        return {
            "tenant_id": tenant_id,
            "banco": None,
            "numero_cuenta": None,
            "tipo_cuenta": None,
            "rut": None,
            "email_comprobantes": None,
            "whatsapp": None,
            "configurado": False
        }

    return {
        "id": config.id,
        "tenant_id": config.tenant_id,
        "banco": config.banco,
        "numero_cuenta": config.numero_cuenta,
        "tipo_cuenta": config.tipo_cuenta,
        "rut": config.rut,
        "email_comprobantes": config.email_comprobantes,
        "whatsapp": config.whatsapp,
        "configurado": True
    }


@router.put("")
def actualizar_configuracion(
    tenant_id: Optional[int] = None,
    data: ConfiguracionUpdate = None,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Actualiza o crea la configuracion del negocio. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    # Buscar o crear configuracion
    config = db.query(ConfiguracionNegocio).filter(
        ConfiguracionNegocio.tenant_id == tenant_id
    ).first()

    if not config:
        config = ConfiguracionNegocio(tenant_id=tenant_id)
        db.add(config)

    # Actualizar campos
    if data.banco is not None:
        config.banco = data.banco
    if data.numero_cuenta is not None:
        config.numero_cuenta = data.numero_cuenta
    if data.tipo_cuenta is not None:
        config.tipo_cuenta = data.tipo_cuenta
    if data.rut is not None:
        config.rut = data.rut
    if data.email_comprobantes is not None:
        config.email_comprobantes = data.email_comprobantes
    if data.whatsapp is not None:
        # Se guarda recortado y con "" -> None: un campo vacío en el formulario significa
        # "sin WhatsApp" y no una cadena vacía que después habría que chequear en cada uso.
        config.whatsapp = data.whatsapp.strip() or None

    db.commit()
    db.refresh(config)

    return {
        "id": config.id,
        "tenant_id": config.tenant_id,
        "banco": config.banco,
        "numero_cuenta": config.numero_cuenta,
        "tipo_cuenta": config.tipo_cuenta,
        "rut": config.rut,
        "email_comprobantes": config.email_comprobantes,
        "whatsapp": config.whatsapp,
        "configurado": True
    }
