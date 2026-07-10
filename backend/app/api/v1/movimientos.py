"""
Router de endpoints para gestión de Movimientos
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.movimiento import Movimiento
from app.schemas.movimiento import (
    MovimientoCreate, MovimientoUpdate, MovimientoResponse, MovimientoListItem
)

router = APIRouter()


@router.post("", response_model=MovimientoResponse, status_code=status.HTTP_201_CREATED)
def crear_movimiento(
    movimiento_data: MovimientoCreate,
    db: Session = Depends(get_db)
):
    """Crea un nuevo movimiento"""

    db_movimiento = Movimiento(
        tenant_id=movimiento_data.tenant_id,
        nombre=movimiento_data.nombre,
        descripcion=movimiento_data.descripcion,
        activo=movimiento_data.activo
    )

    db.add(db_movimiento)
    db.commit()
    db.refresh(db_movimiento)

    return db_movimiento


@router.get("/{movimiento_id}", response_model=MovimientoResponse)
def obtener_movimiento(
    movimiento_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un movimiento por su ID"""
    movimiento = db.query(Movimiento).filter(
        Movimiento.id == movimiento_id,
        Movimiento.tenant_id == tenant_id
    ).first()

    if not movimiento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Movimiento con ID {movimiento_id} no encontrado"
        )

    return movimiento


@router.get("", response_model=List[MovimientoListItem])
def listar_movimientos(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    activo: bool = None,
    db: Session = Depends(get_db)
):
    """Lista movimientos de un tenant con paginación"""
    query = db.query(Movimiento).filter(Movimiento.tenant_id == tenant_id)

    if activo is not None:
        query = query.filter(Movimiento.activo == activo)

    movimientos = query.offset(skip).limit(limit).all()

    return movimientos


@router.put("/{movimiento_id}", response_model=MovimientoResponse)
def actualizar_movimiento(
    movimiento_id: int,
    movimiento_data: MovimientoUpdate,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Actualiza un movimiento existente"""
    movimiento = db.query(Movimiento).filter(
        Movimiento.id == movimiento_id,
        Movimiento.tenant_id == tenant_id
    ).first()

    if not movimiento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Movimiento con ID {movimiento_id} no encontrado"
        )

    update_data = movimiento_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(movimiento, field, value)

    db.commit()
    db.refresh(movimiento)

    return movimiento


@router.delete("/{movimiento_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_movimiento(
    movimiento_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Desactiva un movimiento (soft delete)"""
    movimiento = db.query(Movimiento).filter(
        Movimiento.id == movimiento_id,
        Movimiento.tenant_id == tenant_id
    ).first()

    if not movimiento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Movimiento con ID {movimiento_id} no encontrado"
        )

    movimiento.activo = False
    db.commit()

    return None
