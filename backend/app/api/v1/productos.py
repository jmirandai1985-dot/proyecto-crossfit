"""
Router de endpoints para gestión de Productos
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.database import get_db
from app.models.producto import Producto
from app.schemas.producto import (
    ProductoUpdate, ProductoResponse, ProductoListItem
)
from app.core.dependencies import get_current_admin, get_current_user, require_full_access
# La subida de imágenes PÚBLICAS vive en un módulo compartido: la usan la foto del
# producto (acá) y el flyer de un aviso de marketing (app/api/v1/marketing.py), con
# los MISMOS chequeos y el MISMO destino (app/services/storage.py).
from app.core.imagenes_publicas import guardar_imagen_publica
from app.services import storage
# El aviso `producto_bazar` del carrusel del Inicio es DERIVADO del producto: lo
# crea/actualiza/quita `sincronizar_producto` cada vez que el admin guarda el
# producto con `dias_anuncio` (Bloque 3).
from app.services import avisos_marketing as avisos

# FIX 1: catálogo de movimientos restringido para alumnos de prueba
router = APIRouter(dependencies=[Depends(require_full_access)])


# Las fotos del Bazar son PÚBLICAS y las guarda `app/core/imagenes_publicas.py`
# (capa ÚNICA de almacenamiento: disco en dev/TEST, bucket público de R2 en PROD).


@router.post("", response_model=ProductoResponse, status_code=status.HTTP_201_CREATED)
async def crear_producto(
    nombre: str = Form(...),
    precio: float = Form(...),
    stock: int = Form(...),
    tenant_id: Optional[int] = Form(None),
    descripcion: Optional[str] = Form(None),
    stock_minimo: Optional[int] = Form(None),
    dias_anuncio: Optional[int] = Form(None),
    activo: bool = Form(True),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea un nuevo producto. Acepta multipart/form-data para soportar imagen opcional. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (el Form se ignora).
    tenant_id = current_user["tenant_id"]

    # Normalización: el Form llega crudo (quedó "poleras " con espacio final
    # en la BD). Mismo criterio que alumnos.py: strip al guardar.
    nombre = (nombre or "").strip()
    descripcion = (descripcion or "").strip() or None

    # Imagen opcional: se valida y se guarda con la capa ÚNICA de almacenamiento
    # (disco en dev/TEST, bucket público de R2 en PROD). Sin archivo queda NULL.
    imagen_url = (await guardar_imagen_publica(file)
                  if file and file.filename else None)

    db_producto = Producto(
        tenant_id=tenant_id,
        nombre=nombre,
        descripcion=descripcion or None,
        precio=precio,
        stock=stock,
        stock_minimo=stock_minimo,
        imagen_url=imagen_url,
        dias_anuncio=max(int(dias_anuncio or 0), 0),
        activo=activo,
    )

    db.add(db_producto)
    db.commit()
    db.refresh(db_producto)

    # El aviso del carrusel del Inicio sale del MISMO guardado: con días de anuncio
    # (>0) se crea/actualiza; con 0 no se anuncia (y se quita el que hubiera).
    avisos.sincronizar_producto(db, db_producto,
                               creado_por=current_user["usuario_id"])

    return db_producto


@router.post("/{producto_id}/imagen", response_model=ProductoResponse)
async def subir_imagen_producto(
    producto_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Agrega o REEMPLAZA la imagen de un producto existente (multipart). Solo admin.

    El PUT /{id} es JSON (no puede llevar archivo), así que la imagen se sube por
    acá. La foto VIEJA se borra del almacenamiento (no queda huérfana).
    """
    # 🔒 SEGURIDAD: tenant_id del token (el producto tiene que ser del mismo box).
    tenant_id = current_user["tenant_id"]
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.tenant_id == tenant_id
    ).first()

    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID {producto_id} no encontrado"
        )

    # Primero se guarda la NUEVA: si el guardado falla (503) la foto vieja sigue
    # intacta y el producto no queda sin imagen.
    url_nueva = await guardar_imagen_publica(file)
    url_previa = producto.imagen_url

    producto.imagen_url = url_nueva
    db.commit()
    db.refresh(producto)

    # Recién ahora se borra la vieja, y es best-effort: nunca rompe la respuesta.
    if url_previa and url_previa != url_nueva:
        storage.borrar_publico(url_previa)

    return producto


@router.get("/{producto_id}", response_model=ProductoResponse)
def obtener_producto(
    producto_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Obtiene un producto por su ID (tenant del token)"""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.tenant_id == tenant_id
    ).first()

    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID {producto_id} no encontrado"
        )

    return producto


@router.get("", response_model=List[ProductoListItem])
def listar_productos(
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lista productos del tenant (derivado del token) con paginación"""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    query = db.query(Producto).filter(Producto.tenant_id == tenant_id)

    if activo is not None:
        query = query.filter(Producto.activo == activo)

    productos = query.offset(skip).limit(limit).all()

    return productos


@router.put("/{producto_id}", response_model=ProductoResponse)
def actualizar_producto(
    producto_id: int,
    producto_data: ProductoUpdate,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Actualiza un producto existente. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.tenant_id == tenant_id
    ).first()

    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID {producto_id} no encontrado"
        )

    update_data = producto_data.model_dump(exclude_unset=True)
    imagen_previa = producto.imagen_url

    # Normalización: sin espacios sobrantes al guardar (nombre/descripción).
    for _campo in ("nombre", "descripcion"):
        if isinstance(update_data.get(_campo), str):
            update_data[_campo] = update_data[_campo].strip()

    for field, value in update_data.items():
        setattr(producto, field, value)

    # ── Alerta de stock bajo: si el producto quedó por ENCIMA del umbral
    #    (el admin repuso stock o subió/desactivó el umbral), se rearma el
    #    ciclo para que la próxima bajada vuelva a alertar al admin.
    if producto.stock_minimo is not None and producto.stock > producto.stock_minimo:
        producto.alerta_stock_enviada = False

    db.commit()
    db.refresh(producto)

    # Botón "Quitar imagen" (imagen_url=null explícito): el archivo no se deja
    # huérfano, se borra DESPUÉS de que el cambio quedó guardado en la BD.
    if imagen_previa and producto.imagen_url is None:
        storage.borrar_publico(imagen_previa)

    # Días de anuncio: si el admin los tocó, el aviso del carrusel se recalcula en
    # el MISMO guardado (crear, actualizar la foto/nombre o quitarlo con 0). El
    # sync NO corre en cada PUT a propósito: reabriría la ventana de un anuncio ya
    # terminado cada vez que alguien edita el stock.
    if "dias_anuncio" in update_data:
        avisos.sincronizar_producto(db, producto,
                                    creado_por=current_user["usuario_id"])

    return producto


@router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_producto(
    producto_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Desactiva un producto (soft delete). Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.tenant_id == tenant_id
    ).first()

    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID {producto_id} no encontrado"
        )

    producto.activo = False
    db.commit()

    return None
