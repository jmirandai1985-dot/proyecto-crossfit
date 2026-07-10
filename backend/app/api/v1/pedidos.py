"""
Router de endpoints para gestión de Pedidos
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.pedido import Pedido
from app.models.producto import Producto
from app.schemas.pedido import (
    PedidoCreate, PedidoUpdate, PedidoResponse, PedidoListItem
)

router = APIRouter()

# Estados válidos y transiciones permitidas
ESTADOS_VALIDOS = ["pendiente", "validado", "entregado"]
TRANSICIONES_PERMITIDAS = {
    "pendiente": ["validado"],
    "validado": ["entregado"],
    "entregado": []
}


@router.post("", response_model=PedidoResponse, status_code=status.HTTP_201_CREATED)
def crear_pedido(
    pedido_data: PedidoCreate,
    db: Session = Depends(get_db)
):
    """
    Crea un nuevo pedido.
    Valida stock y descuenta automáticamente.
    """

    # Obtener el producto
    producto = db.query(Producto).filter(
        Producto.id == pedido_data.producto_id,
        Producto.tenant_id == pedido_data.tenant_id
    ).first()

    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado"
        )

    # Validar stock
    if producto.stock < pedido_data.cantidad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stock insuficiente. Disponible: {producto.stock}, Solicitado: {pedido_data.cantidad}"
        )

    # Calcular total
    total = producto.precio * pedido_data.cantidad

    # Crear pedido
    db_pedido = Pedido(
        tenant_id=pedido_data.tenant_id,
        alumno_id=pedido_data.alumno_id,
        producto_id=pedido_data.producto_id,
        cantidad=pedido_data.cantidad,
        total=total,
        estado=pedido_data.estado
    )

    # Descontar stock
    producto.stock -= pedido_data.cantidad

    db.add(db_pedido)
    db.commit()
    db.refresh(db_pedido)

    return db_pedido


@router.get("/{pedido_id}", response_model=PedidoResponse)
def obtener_pedido(
    pedido_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un pedido por su ID"""
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.tenant_id == tenant_id
    ).first()

    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado"
        )

    return pedido


@router.get("", response_model=List[PedidoListItem])
def listar_pedidos(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    estado: str = None,
    alumno_id: int = None,
    db: Session = Depends(get_db)
):
    """Lista pedidos de un tenant con filtros opcionales"""
    query = db.query(Pedido).filter(Pedido.tenant_id == tenant_id)

    if estado is not None:
        query = query.filter(Pedido.estado == estado)

    if alumno_id is not None:
        query = query.filter(Pedido.alumno_id == alumno_id)

    pedidos = query.order_by(Pedido.fecha_pedido.desc()).offset(
        skip).limit(limit).all()

    return pedidos


@router.put("/{pedido_id}/estado", response_model=PedidoResponse)
def actualizar_estado_pedido(
    pedido_id: int,
    nuevo_estado: str,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Actualiza el estado de un pedido.
    Solo permite avanzar: pendiente → validado → entregado (no retroceder)
    """
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.tenant_id == tenant_id
    ).first()

    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado"
        )

    # Validar que el nuevo estado es válido
    if nuevo_estado not in ESTADOS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Estado inválido. Estados válidos: {ESTADOS_VALIDOS}"
        )

    # Validar que la transición es permitida
    if nuevo_estado not in TRANSICIONES_PERMITIDAS.get(pedido.estado, []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede cambiar de '{pedido.estado}' a '{nuevo_estado}'. Transiciones permitidas: {TRANSICIONES_PERMITIDAS.get(pedido.estado, [])}"
        )

    pedido.estado = nuevo_estado
    db.commit()
    db.refresh(pedido)

    return pedido


@router.put("/{pedido_id}", response_model=PedidoResponse)
def actualizar_pedido(
    pedido_id: int,
    pedido_data: PedidoUpdate,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Actualiza un pedido existente"""
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.tenant_id == tenant_id
    ).first()

    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado"
        )

    update_data = pedido_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(pedido, field, value)

    db.commit()
    db.refresh(pedido)

    return pedido


@router.delete("/{pedido_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_pedido(
    pedido_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Elimina un pedido (solo si está en estado pendiente)"""
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.tenant_id == tenant_id
    ).first()

    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado"
        )

    if pedido.estado != "pendiente":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se pueden eliminar pedidos en estado pendiente"
        )

    # Restaurar stock
    producto = db.query(Producto).filter(
        Producto.id == pedido.producto_id
    ).first()

    if producto:
        producto.stock += pedido.cantidad

    db.delete(pedido)
    db.commit()

    return None
