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
from app.core.dependencies import get_current_user

router = APIRouter()


class ConfiguracionUpdate(BaseModel):
    banco: Optional[str] = None
    numero_cuenta: Optional[str] = None
    tipo_cuenta: Optional[str] = None
    rut: Optional[str] = None
    email_comprobantes: Optional[str] = None


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
        "configurado": True
    }


@router.put("")
def actualizar_configuracion(
    tenant_id: int,
    data: ConfiguracionUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Actualiza o crea la configuracion del negocio. Solo admin."""
    # Verificar rol admin
    user = db.query(Usuario).filter(
        Usuario.id == current_user["usuario_id"]).first()
    if not user or user.rol not in ("administrador", "admin"):
        raise HTTPException(
            status_code=403, detail="Accion no permitida: se requiere rol de administrador"
        )

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
        "configurado": True
    }
