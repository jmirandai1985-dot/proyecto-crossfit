"""
Router de endpoints para gestión de Auditoría
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List
from datetime import datetime, date

from app.db.database import get_db
from app.models.auditoria import Auditoria
from app.schemas.auditoria import (
    AuditoriaCreate, AuditoriaResponse, AuditoriaListItem
)

router = APIRouter()


@router.post("", response_model=AuditoriaResponse, status_code=status.HTTP_201_CREATED)
def crear_auditoria(
    auditoria_data: AuditoriaCreate,
    db: Session = Depends(get_db)
):
    """Crea un nuevo registro de auditoría"""

    db_auditoria = Auditoria(
        tenant_id=auditoria_data.tenant_id,
        usuario_id=auditoria_data.usuario_id,
        accion=auditoria_data.accion,
        entidad=auditoria_data.entidad,
        entidad_id=auditoria_data.entidad_id,
        detalle=auditoria_data.detalle
    )

    db.add(db_auditoria)
    db.commit()
    db.refresh(db_auditoria)

    return db_auditoria


@router.get("/{auditoria_id}", response_model=AuditoriaResponse)
def obtener_auditoria(
    auditoria_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un registro de auditoría por su ID"""
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
    tenant_id: int,
    skip: int = 0,
    limit: int = 50,
    usuario_id: int = None,
    accion: str = None,
    entidad: str = None,
    fecha_desde: date = None,
    fecha_hasta: date = None,
    db: Session = Depends(get_db)
):
    """
    Lista registros de auditoría con filtros opcionales.

    Filtros disponibles:
    - usuario_id: ID del usuario que realizó la acción
    - accion: Tipo de acción (CREATE, UPDATE, DELETE, LOGIN)
    - entidad: Nombre de la entidad afectada
    - fecha_desde: Fecha inicial (inclusive)
    - fecha_hasta: Fecha final (inclusive)
    """
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
    tenant_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Obtiene el historial de auditoría de un usuario específico"""
    auditoria = db.query(Auditoria).filter(
        Auditoria.tenant_id == tenant_id,
        Auditoria.usuario_id == usuario_id
    ).order_by(Auditoria.fecha.desc()).offset(skip).limit(limit).all()

    return auditoria


@router.get("/entidad/{entidad}/{entidad_id}", response_model=List[AuditoriaListItem])
def obtener_auditoria_entidad(
    entidad: str,
    entidad_id: int,
    tenant_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Obtiene el historial de auditoría de una entidad específica"""
    auditoria = db.query(Auditoria).filter(
        Auditoria.tenant_id == tenant_id,
        Auditoria.entidad == entidad,
        Auditoria.entidad_id == entidad_id
    ).order_by(Auditoria.fecha.desc()).offset(skip).limit(limit).all()

    return auditoria
