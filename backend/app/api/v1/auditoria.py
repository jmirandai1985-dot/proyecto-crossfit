"""
Router de endpoints de LECTURA de Auditoría.

La ESCRITURA de auditoría se realiza exclusivamente vía el servicio interno
`app.services.auditoria_service.registrar_*` desde las acciones del sistema
(aprobación de comprobantes, cambios de rol, edición/borrado de PRs, ajustes
de tokens). El antiguo `POST /auditoria` (público) fue retirado: permitía
inyectar logs falsos y ningún módulo del frontend lo utilizaba (ver SECURITY.md §3.2, Tarea D).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from datetime import datetime, date

from app.db.database import get_db
from app.models.auditoria import Auditoria
from app.core.dependencies import get_current_admin
from app.schemas.auditoria import (
    AuditoriaResponse, AuditoriaListItem
)

router = APIRouter()


@router.get("/{auditoria_id}", response_model=AuditoriaResponse)
def obtener_auditoria(
    auditoria_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Obtiene un registro de auditoría por su ID (solo admin, tenant del token)"""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    auditoria = db.query(Auditoria).filter(
        Auditoria.id == auditoria_id,
        Auditoria.tenant_id == tenant_id
    ).first()

    if not auditoria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Auditoría con ID {auditoria_id} no encontrada"
        )

    return auditoria


@router.get("", response_model=List[AuditoriaListItem])
def listar_auditoria(
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    usuario_id: Optional[int] = None,
    accion: Optional[str] = None,
    entidad: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Lista registros de auditoría con filtros opcionales. Solo admin (tenant del token).

    Filtros disponibles:
    - usuario_id: ID del usuario que realizó la acción
    - accion: Tipo de acción (CREATE, UPDATE, DELETE, LOGIN)
    - entidad: Nombre de la entidad afectada
    - fecha_desde: Fecha inicial (inclusive)
    - fecha_hasta: Fecha final (inclusive)
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    query = db.query(Auditoria).filter(Auditoria.tenant_id == tenant_id)

    if usuario_id is not None:
        query = query.filter(Auditoria.usuario_id == usuario_id)

    if accion is not None:
        query = query.filter(Auditoria.accion == accion)

    if entidad is not None:
        query = query.filter(Auditoria.entidad == entidad)

    if fecha_desde is not None:
        fecha_desde_dt = datetime.combine(fecha_desde, datetime.min.time())
        query = query.filter(Auditoria.fecha >= fecha_desde_dt)

    if fecha_hasta is not None:
        fecha_hasta_dt = datetime.combine(fecha_hasta, datetime.max.time())
        query = query.filter(Auditoria.fecha <= fecha_hasta_dt)

    auditoria = query.order_by(Auditoria.fecha.desc()).offset(
        skip).limit(limit).all()

    return auditoria


@router.get("/usuario/{usuario_id}", response_model=List[AuditoriaListItem])
def obtener_auditoria_usuario(
    usuario_id: int,
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Obtiene el historial de auditoría de un usuario específico. Solo admin."""
    # 🔒 SEGURIDAD: tenant_id del token.
    tenant_id = current_user["tenant_id"]
    auditoria = db.query(Auditoria).filter(
        Auditoria.tenant_id == tenant_id,
        Auditoria.usuario_id == usuario_id
    ).order_by(Auditoria.fecha.desc()).offset(skip).limit(limit).all()

    return auditoria


@router.get("/entidad/{entidad}/{entidad_id}", response_model=List[AuditoriaListItem])
def obtener_auditoria_entidad(
    entidad: str,
    entidad_id: int,
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Obtiene el historial de auditoría de una entidad específica. Solo admin."""
    # 🔒 SEGURIDAD: tenant_id del token.
    tenant_id = current_user["tenant_id"]
    auditoria = db.query(Auditoria).filter(
        Auditoria.tenant_id == tenant_id,
        Auditoria.entidad == entidad,
        Auditoria.entidad_id == entidad_id
    ).order_by(Auditoria.fecha.desc()).offset(skip).limit(limit).all()

    return auditoria
