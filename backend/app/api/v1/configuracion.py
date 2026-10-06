"""
Router de Configuración del Negocio (datos bancarios por tenant)

    GET /api/v1/configuracion — autenticado: el box sale del TOKEN
    PUT /api/v1/configuracion — sólo admin del box

🔒 R1: el GET era PÚBLICO "por diseño" (SECURITY.md §3.2) porque lo consumen pantallas
de alumno, pero las TRES pantallas que lo usan (Configuración, Bazar y Solicitar plan)
están detrás del login y mandan el token. Público + `tenant_id` por query significaba
que cualquiera podía enumerar banco / cuenta / RUT / email / WhatsApp de TODOS los boxes
con `GET /configuracion?tenant_id=1..N` (200, sin credencial alguna). Ahora exige token,
toma el `tenant_id` del JWT (el query param se ignora) y tiene rate limit en GET y PUT.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.models.configuracion import ConfiguracionNegocio
from app.models.usuario import Usuario
from app.core.dependencies import get_current_user, get_current_admin
from app.core.rate_limit import LIMIT_CONFIG_LECTURA, LIMIT_CRITICO, limiter

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
@limiter.limit(LIMIT_CONFIG_LECTURA)
def obtener_configuracion(
    request: Request,
    tenant_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Configuración del negocio del box del TOKEN (datos bancarios para transferencias).

    ⚠️ El `tenant_id` del query se IGNORA (queda declarado sólo por compatibilidad con
    los clientes que todavía lo mandan): pedir el box de otro devuelve el PROPIO —y, si
    ese box todavía no cargó nada, `configurado: False`—, así que no hay forma de
    enumerar la ficha bancaria de los demás boxes.
    """
    # 🔒 SEGURIDAD (R1): el box sale del token, nunca del request.
    tenant_id = current_user["tenant_id"]

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
@limiter.limit(LIMIT_CRITICO)
def actualizar_configuracion(
    request: Request,
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
