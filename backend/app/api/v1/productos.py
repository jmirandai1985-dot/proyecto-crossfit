"""
Router de endpoints para gestión de Productos
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional

from app.db.database import get_db
from app.models.producto import Producto, ProductoImagen
from app.schemas.producto import (
    ProductoUpdate, ProductoResponse, ProductoListItem,
    ProductoImagenResponse, ProductoImagenesOrden,
)
from app.core.dependencies import get_current_admin, get_current_user, require_full_access
# La subida de imágenes PÚBLICAS vive en un módulo compartido: la usan la foto del
# producto (acá) y el flyer de un aviso de marketing (app/api/v1/marketing.py), con
# los MISMOS chequeos y el MISMO destino (app/services/storage.py).
from app.core.imagenes_publicas import guardar_imagen_publica
from app.services import storage
# El aviso `producto_bazar` del carrusel del Inicio es DERIVADO del producto: lo
# crea/RELANZA/quita `sincronizar_producto` cada vez que el admin guarda el producto
# con `dias_anuncio` (Bloque 3). Guardar los días es lo que relanza la ventana desde
# hoy; el sync sólo se llama si ese campo viene en el payload.
from app.services import avisos_marketing as avisos

# FIX 1: catálogo de movimientos restringido para alumnos de prueba
router = APIRouter(dependencies=[Depends(require_full_access)])

# Tope de la galería. El mínimo (1) se valida al borrar: la última foto no se
# puede eliminar. `imagen_url` sigue siendo la portada derivada (orden=0) para
# que el carrusel "Novedades del box" y las tarjetas no cambien.
MAX_IMAGENES_PRODUCTO = 5


# ── Helpers de galería ────────────────────────────────────────────────────────
# Una sola definición del orden y de la portada para todos los endpoints: si la
# galería se toca por cualquier camino, `imagen_url` queda apuntando a orden=0.
def _imagenes_ordenadas(db: Session, producto_id: int) -> List[ProductoImagen]:
    return (db.query(ProductoImagen)
              .filter(ProductoImagen.producto_id == producto_id)
              .order_by(ProductoImagen.orden, ProductoImagen.id)
              .all())


def _renumerar(imagenes: List[ProductoImagen]) -> None:
    """Deja `orden` en 0..n-1 (sin huecos) sobre la lista ya ordenada."""
    for posicion, imagen in enumerate(imagenes):
        imagen.orden = posicion


def _sincronizar_portada(db: Session, producto: Producto) -> List[ProductoImagen]:
    """Copia la foto orden=0 en `productos.imagen_url` (portada derivada)."""
    # La sesión se crea con autoflush=False: sin este flush, una foto recién
    # agregada o un `orden` recién cambiado todavía no se ven en la consulta y
    # la portada quedaría desactualizada (o en None).
    db.flush()
    imagenes = _imagenes_ordenadas(db, producto.id)
    producto.imagen_url = imagenes[0].url if imagenes else None
    return imagenes


def _asegurar_galeria_legacy(db: Session, producto: Producto) -> None:
    """Producto con `imagen_url` pero sin filas (dato previo a la 055).

    La migración hace el backfill, así que esto es sólo una red de seguridad
    para una fila que se haya creado por fuera. No hace nada si ya hay fotos.
    """
    if not producto.imagen_url:
        return
    if _imagenes_ordenadas(db, producto.id):
        return
    db.add(ProductoImagen(producto_id=producto.id,
                          url=producto.imagen_url, orden=0))
    db.flush()


def _producto_del_tenant(db: Session, producto_id: int, tenant_id: int,
                         con_imagenes: bool = False) -> Producto:
    """Busca el producto del box del token (o 404). El tenant NUNCA viene del cliente."""
    query = db.query(Producto)
    if con_imagenes:
        query = query.options(selectinload(Producto.imagenes))
    producto = query.filter(
        Producto.id == producto_id,
        Producto.tenant_id == tenant_id,
    ).first()
    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID {producto_id} no encontrado",
        )
    return producto


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
    # `file` es el campo legacy (041) con UNA foto. `files` permite crear el
    # producto y su galería completa en la MISMA petición: si un archivo falla,
    # no queda un producto a medio crear y el admin no duplica al reintentar.
    file: Optional[UploadFile] = File(None),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea un nuevo producto. Acepta multipart/form-data con 0..5 fotos. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (el Form se ignora).
    tenant_id = current_user["tenant_id"]

    # Normalización: el Form llega crudo (quedó "poleras " con espacio final
    # en la BD). Mismo criterio que alumnos.py: strip al guardar.
    nombre = (nombre or "").strip()
    descripcion = (descripcion or "").strip() or None

    # El orden recibido ES el orden de la galería: `file` (legacy) primero y
    # luego `files`, que es como lo envía el modal (portada = primera foto).
    archivos = ([file] if file and file.filename else [])
    archivos.extend(f for f in (files or []) if f and f.filename)
    if len(archivos) > MAX_IMAGENES_PRODUCTO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Máximo {MAX_IMAGENES_PRODUCTO} fotos por producto."),
        )

    # Se suben TODAS las fotos antes de tocar la BD. Si una falla (tipo, tamaño,
    # contenido o almacenamiento) se borran las ya guardadas en esta petición.
    urls_guardadas: List[str] = []
    try:
        for archivo in archivos:
            urls_guardadas.append(await guardar_imagen_publica(archivo))
    except Exception:
        for url in urls_guardadas:
            storage.borrar_publico(url)
        raise

    imagen_url = urls_guardadas[0] if urls_guardadas else None
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

    try:
        db.add(db_producto)
        db.flush()  # necesitamos el id para las filas de la galería
        for orden, url in enumerate(urls_guardadas):
            db.add(ProductoImagen(producto_id=db_producto.id,
                                  url=url, orden=orden))
        db.commit()
    except Exception:
        db.rollback()
        for url in urls_guardadas:
            storage.borrar_publico(url)
        raise

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

    # Este endpoint sigue existiendo para el flujo de una sola foto: reemplaza la
    # PORTADA de la galería (orden=0), conservando el resto de las fotos.
    _asegurar_galeria_legacy(db, producto)
    imagenes = _imagenes_ordenadas(db, producto.id)
    if imagenes:
        imagenes[0].url = url_nueva
        _renumerar(imagenes)
    else:
        db.add(ProductoImagen(producto_id=producto.id,
                              url=url_nueva, orden=0))
    _sincronizar_portada(db, producto)
    db.commit()
    db.refresh(producto)

    # Recién ahora se borra la vieja, y es best-effort: nunca rompe la respuesta.
    # Sólo si esa URL ya no está en la galería (no borrar una foto compartida).
    if url_previa and url_previa != url_nueva:
        referenciada = any(i.url == url_previa
                           for i in _imagenes_ordenadas(db, producto.id))
        if not referenciada:
            storage.borrar_publico(url_previa)

    return producto


# ── Galería (3 a 5 fotos) ─────────────────────────────────────────────────────
# `GET` lista, `POST` agrega hasta 5, `PUT .../orden` reordena la galería completa
# y `DELETE` quita una foto (nunca la última). Toda mutación reescribe la portada
# derivada `productos.imagen_url` con la foto orden=0.
@router.get("/{producto_id}/imagenes", response_model=List[ProductoImagenResponse])
def listar_imagenes_producto(
    producto_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Galería ordenada del producto. La ve el alumno en el detalle y el admin."""
    tenant_id = current_user["tenant_id"]
    producto = _producto_del_tenant(db, producto_id, tenant_id)

    # Red de seguridad para productos previos a la migración 055: si tienen
    # `imagen_url` pero todavía no una fila, se crea la portada orden=0.
    _asegurar_galeria_legacy(db, producto)
    db.commit()

    return _imagenes_ordenadas(db, producto.id)


@router.post("/{producto_id}/imagenes",
             response_model=List[ProductoImagenResponse],
             status_code=status.HTTP_201_CREATED)
async def agregar_imagenes_producto(
    producto_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Agrega una o varias fotos (máximo 5 en total). Solo admin.

    La primera foto de un producto sin galería queda como portada (orden=0). Las
    siguientes se agregan al final. Si falla cualquier archivo, se borran las
    imágenes ya guardadas en esta misma petición: no quedan huérfanas.
    """
    tenant_id = current_user["tenant_id"]
    producto = _producto_del_tenant(db, producto_id, tenant_id)
    _asegurar_galeria_legacy(db, producto)
    db.flush()

    actuales = _imagenes_ordenadas(db, producto.id)
    archivos = [f for f in files if f and f.filename]
    if not archivos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes adjuntar al menos una foto.",
        )
    if len(actuales) + len(archivos) > MAX_IMAGENES_PRODUCTO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Máximo {MAX_IMAGENES_PRODUCTO} fotos por producto. "
                    f"Ya tiene {len(actuales)}."),
        )

    urls_guardadas: List[str] = []
    try:
        for archivo in archivos:
            urls_guardadas.append(await guardar_imagen_publica(archivo))
    except Exception:
        # Rollback lógico de los archivos ya subidos en esta petición.
        for url in urls_guardadas:
            storage.borrar_publico(url)
        raise

    siguiente_orden = max((i.orden for i in actuales), default=-1) + 1
    for offset, url in enumerate(urls_guardadas):
        db.add(ProductoImagen(producto_id=producto.id,
                              url=url,
                              orden=siguiente_orden + offset))

    # Si no había fotos, la primera recién creada pasa a ser la portada.
    _sincronizar_portada(db, producto)

    try:
        db.commit()
    except Exception:
        db.rollback()
        for url in urls_guardadas:
            storage.borrar_publico(url)
        raise

    db.refresh(producto)
    return _imagenes_ordenadas(db, producto.id)


@router.put("/{producto_id}/imagenes/orden",
            response_model=List[ProductoImagenResponse])
def reordenar_imagenes_producto(
    producto_id: int,
    payload: ProductoImagenesOrden,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Reordena la galería completa. El primer id queda como portada. Solo admin."""
    tenant_id = current_user["tenant_id"]
    producto = _producto_del_tenant(db, producto_id, tenant_id)
    _asegurar_galeria_legacy(db, producto)
    db.flush()

    imagenes = _imagenes_ordenadas(db, producto.id)
    ids_pedidos = payload.imagen_ids
    ids_actuales = {imagen.id for imagen in imagenes}

    if len(set(ids_pedidos)) != len(ids_pedidos):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El orden no puede repetir fotos.",
        )
    if set(ids_pedidos) != ids_actuales:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El orden debe incluir todas las fotos del producto.",
        )

    por_id = {imagen.id: imagen for imagen in imagenes}
    for posicion, imagen_id in enumerate(ids_pedidos):
        por_id[imagen_id].orden = posicion

    _sincronizar_portada(db, producto)
    db.commit()
    db.refresh(producto)

    return _imagenes_ordenadas(db, producto.id)


@router.delete("/{producto_id}/imagenes/{imagen_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def eliminar_imagen_producto(
    producto_id: int,
    imagen_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Borra una foto (nunca la última). La siguiente pasa a ser portada si hace falta."""
    tenant_id = current_user["tenant_id"]
    producto = _producto_del_tenant(db, producto_id, tenant_id)
    _asegurar_galeria_legacy(db, producto)
    db.flush()

    imagenes = _imagenes_ordenadas(db, producto.id)
    imagen = next((i for i in imagenes if i.id == imagen_id), None)
    if not imagen:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Foto con ID {imagen_id} no encontrada en este producto",
        )

    if len(imagenes) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El producto debe conservar al menos una foto.",
        )

    url_borrada = imagen.url
    db.delete(imagen)
    db.flush()

    restantes = _imagenes_ordenadas(db, producto.id)
    _renumerar(restantes)
    _sincronizar_portada(db, producto)
    db.commit()
    db.refresh(producto)

    # Best-effort: si ninguna otra fila usa la misma URL, el archivo se borra.
    if not any(i.url == url_borrada for i in _imagenes_ordenadas(db, producto.id)):
        storage.borrar_publico(url_borrada)

    return None


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

    producto = _producto_del_tenant(db, producto_id, tenant_id,
                                    con_imagenes=True)
    _asegurar_galeria_legacy(db, producto)
    db.commit()

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

    # `selectinload` evita N+1 al serializar la galería de cada producto.
    query = (db.query(Producto)
               .options(selectinload(Producto.imagenes))
               .filter(Producto.tenant_id == tenant_id))

    if activo is not None:
        query = query.filter(Producto.activo == activo)

    productos = query.offset(skip).limit(limit).all()

    # Red de seguridad para datos previos a la 055 que no pasaron por el backfill:
    # sin esto el modal de edición recibiría `imagenes=[]` y no tendría el id de la
    # portada para reordenar/eliminar. Normalmente no hace ninguna escritura.
    heredados = [p for p in productos
                 if p.imagen_url and not p.imagenes]
    if heredados:
        for producto in heredados:
            _asegurar_galeria_legacy(db, producto)
        db.commit()
        # El commit expira la sesión: se vuelve a leer CON la galería ya cargada.
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
    producto = _producto_del_tenant(db, producto_id, tenant_id)

    update_data = producto_data.model_dump(exclude_unset=True)
    imagen_previa = producto.imagen_url

    # Si el payload toca `imagen_url` hay que reflejarlo en la galería. Se
    # asegura la fila legacy ANTES del setattr: después ya no sabríamos cuál era
    # la portada si el valor nuevo es null.
    if "imagen_url" in update_data:
        _asegurar_galeria_legacy(db, producto)

    # Normalización: sin espacios sobrantes al guardar (nombre/descripción).
    for _campo in ("nombre", "descripcion"):
        if isinstance(update_data.get(_campo), str):
            update_data[_campo] = update_data[_campo].strip()

    for field, value in update_data.items():
        setattr(producto, field, value)

    if "imagen_url" in update_data:
        imagenes = _imagenes_ordenadas(db, producto.id)
        if update_data["imagen_url"] is None:
            # "Quitar portada": se elimina la foto orden=0 y, si quedan más, la
            # siguiente pasa a ser la portada (el producto nunca se queda con
            # `imagen_url` apuntando a un archivo borrado).
            if imagenes:
                db.delete(imagenes[0])
                db.flush()
                imagenes = _imagenes_ordenadas(db, producto.id)
                _renumerar(imagenes)
            producto.imagen_url = imagenes[0].url if imagenes else None
        else:
            # Reemplazo directo de la URL de portada (sin archivo nuevo).
            if imagenes:
                imagenes[0].url = update_data["imagen_url"]
            else:
                db.add(ProductoImagen(producto_id=producto.id,
                                      url=update_data["imagen_url"], orden=0))
            _sincronizar_portada(db, producto)

    # ── Alerta de stock bajo: si el producto quedó por ENCIMA del umbral
    #    (el admin repuso stock o subió/desactivó el umbral), se rearma el
    #    ciclo para que la próxima bajada vuelva a alertar al admin.
    if producto.stock_minimo is not None and producto.stock > producto.stock_minimo:
        producto.alerta_stock_enviada = False

    db.commit()
    db.refresh(producto)

    # El archivo viejo no se deja huérfano: se borra DESPUÉS de que el cambio
    # quedó guardado, y sólo si ya no lo referencia ninguna foto de la galería.
    if imagen_previa and imagen_previa != producto.imagen_url:
        referenciada = any(i.url == imagen_previa
                           for i in _imagenes_ordenadas(db, producto.id))
        if not referenciada:
            storage.borrar_publico(imagen_previa)

    # Días de anuncio: si el admin los tocó, el aviso del carrusel se recalcula en
    # el MISMO guardado (crear, relanzar la ventana con esos días o quitarlo con 0).
    # El sync NO corre en cada PUT a propósito: guardar el stock (o el precio, o el
    # nombre) sin tocar los días no puede relanzar el anuncio desde hoy.
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
