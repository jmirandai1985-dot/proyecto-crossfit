"""
Router de endpoints para gestión de Pedidos
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.database import get_db
from app.models.pedido import Pedido
from app.models.producto import Producto
from app.models.usuario import Usuario
from app.schemas.pedido import (
    PedidoCreate, PedidoUpdate, PedidoResponse, PedidoListItem
)
from app.core.dependencies import get_current_admin, get_current_user, require_full_access
from app.core.config import settings

logger = logging.getLogger(__name__)

# FIX 1: alumnos con plan de prueba NO pueden ver/comprar en el Bazar.
# FIX 2: el POST de pedidos pasa a get_current_user (alumno con acceso completo).
router = APIRouter(dependencies=[Depends(require_full_access)])

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
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Crea un nuevo pedido (Bazar).

    🔒 FIX 2: un alumno con acceso completo (no prueba) puede comprar SOLO para
    sí mismo: tenant y alumno_id salen del token, estado forzado a 'pendiente'.
    Staff/admin: pueden crear en nombre de un alumno del box (tenant del token).
    Alumnos de prueba quedan bloqueados por require_full_access (403).
    Valida stock y descuenta automáticamente.
    """
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    if rol not in ("coach", "admin", "administrador"):
        # Alumno: solo compra para sí mismo, en estado pendiente.
        pedido_data.tenant_id = tenant_id
        pedido_data.alumno_id = current_user["usuario_id"]
        pedido_data.estado = "pendiente"
    else:
        pedido_data.tenant_id = tenant_id
        if pedido_data.alumno_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar el alumno destino del pedido",
            )
        alumno = db.query(Usuario).filter(
            Usuario.id == pedido_data.alumno_id,
            Usuario.tenant_id == tenant_id,
        ).first()
        if not alumno:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El alumno destino no pertenece a este box",
            )

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
        estado=pedido_data.estado,
        voucher_url=pedido_data.voucher_url
    )

    # Descontar stock ATÓMICAMENTE (FIX concurrencia / test de esfuerzo):
    # UPDATE condicional — solo descuenta si hay stock suficiente. Si dos
    # compras concurrentes piden el último ítem, solo una obtiene rowcount=1
    # (la otra ve rowcount=0 → 400), evitando stock negativo.
    # ── FIX cierre (test de esfuerzo): wrapper de errores de BD ──
    # Bajo contención extrema el UPDATE condicional puede fallar con deadlock
    # o timeout (visto como 500 transitorio en el Escenario D). Se captura y
    # devuelve 503 "Alta demanda" en vez de un 500 genérico.
    try:
        result = db.execute(
            update(Producto)
            .where(Producto.id == producto.id)
            .where(Producto.tenant_id == pedido_data.tenant_id)
            .where(Producto.stock >= pedido_data.cantidad)
            .values(stock=Producto.stock - pedido_data.cantidad)
        )
        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stock insuficiente. Disponible: {producto.stock}, Solicitado: {pedido_data.cantidad}"
            )

        db.add(db_pedido)
        db.commit()
        db.refresh(db_pedido)
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alta demanda, intentá de nuevo",
        )

    # ── Correo al alumno: confirmación de compra en el Bazar (no bloqueante) ──
    try:
        from app.services.email_service import send_confirmacion_pedido
        if current_user.get("rol") not in ("coach", "admin", "administrador"):
            # Alumno comprando para sí mismo: current_user trae nombre/correo (BD).
            destino_nombre = current_user.get("nombre", "Atleta")
            destino_correo = current_user.get("correo", "")
        else:
            # Staff creando a nombre de un alumno del box.
            destino_nombre = alumno.nombre if alumno else "Atleta"
            destino_correo = alumno.correo if alumno else ""
        send_confirmacion_pedido(
            destino_nombre, destino_correo,
            producto.nombre, pedido_data.cantidad, total,
            f"{settings.FRONTEND_URL}/alumno/mis-pedidos",
            current_user.get("usuario_id") if current_user.get("rol") not in ("coach", "admin", "administrador") else (alumno.id if alumno else None))
    except Exception as e:
        logger.warning(f"No se pudo enviar correo de confirmación de pedido: {e}")

    # ── Alerta de stock bajo al admin (Bazar, no bloqueante) ──────────────
    # Si el producto tiene `stock_minimo` configurado (no NULL), tras el
    # descuento atómico quedó en/bajo el umbral, y aún no se avisó en este
    # ciclo (alerta_stock_enviada=False), se envía el correo al admin del box.
    # Si el envío es exitoso se marca el flag para no repetir el aviso hasta que
    # el admin reponga por encima del umbral (PUT /productos/{id} lo resetea).
    try:
        db.refresh(producto)  # stock real post-descuento atómico
        if (producto.stock_minimo is not None
                and producto.stock <= producto.stock_minimo
                and not producto.alerta_stock_enviada):
            from app.services.email_service import send_alerta_stock_bajo
            enviado = send_alerta_stock_bajo(
                producto.nombre, producto.stock, producto.stock_minimo,
                tenant_id)
            if enviado:
                producto.alerta_stock_enviada = True
                db.commit()
    except Exception as e:
        logger.warning(f"No se pudo procesar alerta de stock bajo: {e}")

    return db_pedido


@router.get("/{pedido_id}", response_model=PedidoResponse)
def obtener_pedido(
    pedido_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Obtiene un pedido por su ID (propio o staff del box, tenant del token)"""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.tenant_id == tenant_id
    ).first()

    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado"
        )

    # 🔒 IDOR: solo el dueño del pedido o staff del box.
    if rol not in ("coach", "admin", "administrador") and pedido.alumno_id != current_user["usuario_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes ver los pedidos de otro alumno",
        )

    return pedido


@router.get("", response_model=List[PedidoListItem])
def listar_pedidos(
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    estado: str = None,
    alumno_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lista pedidos del tenant con filtros opcionales (propios o staff)"""
    # 🔒 SEGURIDAD: tenant_id del token + ownership.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    if alumno_id is not None:
        if rol not in ("coach", "admin", "administrador") and alumno_id != current_user["usuario_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes ver los pedidos de otro alumno",
            )
    elif rol not in ("coach", "admin", "administrador"):
        alumno_id = current_user["usuario_id"]

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
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Actualiza el estado de un pedido.
    Solo permite avanzar: pendiente → validado → entregado (no retroceder)
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
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
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Actualiza un pedido existente. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
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
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Elimina un pedido (solo si está en estado pendiente). Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
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
