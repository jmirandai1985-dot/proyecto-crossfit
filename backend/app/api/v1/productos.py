"""
Router de endpoints para gestión de Productos
"""
import json

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional

from app.db.database import get_db
from app.models.producto import (
    Producto, ProductoImagen, ProductoVariante, es_talla_duplicada,
)
from app.schemas.producto import (
    ProductoUpdate, ProductoResponse, ProductoListItem,
    ProductoImagenResponse, ProductoImagenesOrden, ProductoVarianteInput,
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

# Tope de tallas por producto (migración 083). No lo pide el negocio, pero evita
# que un payload enorme deje la fila del Bazar o el modal sin poder renderizarse.
MAX_VARIANTES_PRODUCTO = 100


# ── Helpers de tallas/variantes (migración 083) ───────────────────────────────
# El texto de la talla es LIBRE (S/M/L, sabores, numeración) y la unicidad la
# garantiza el índice FUNCIONAL `uq_producto_variantes_producto_talla` sobre
# `(producto_id, lower(talla))`. Acá se valida antes para dar el mensaje exacto
# con el nombre de la talla, y se traduce el IntegrityError como última red.
def _mensaje_talla_duplicada(talla: Optional[str]) -> str:
    """Mensaje de negocio del índice único de tallas (el que ve el admin)."""
    if talla:
        return f"Ya existe la talla '{talla}' para este producto."
    return "Ya existe una talla repetida para este producto."


def _normalizar_variantes(variantes: Optional[List[ProductoVarianteInput]]) -> List[dict]:
    """Valida y normaliza la lista de tallas que manda el admin.

    - recorta espacios (el Form y el PUT llegan crudos),
    - rechaza una talla vacía,
    - rechaza duplicados CASE-INSENSITIVE antes de tocar la BD: 'S' y 's' son la
      MISMA talla para el admin, aunque en Postgres sean textos distintos.
    """
    normalizadas = []
    vistas = {}
    for item in variantes or []:
        talla = " ".join((item.talla or "").split())
        if not talla:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La talla no puede estar vacía.",
            )
        clave = talla.lower()
        if clave in vistas:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_mensaje_talla_duplicada(vistas[clave]),
            )
        vistas[clave] = talla
        normalizadas.append({"talla": talla, "stock": int(item.stock or 0)})

    if len(normalizadas) > MAX_VARIANTES_PRODUCTO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Máximo {MAX_VARIANTES_PRODUCTO} tallas por producto.",
        )
    return normalizadas


def _parsear_variantes_json(crudo: Optional[str]) -> List[dict]:
    """Lee `variantes_json` del POST multipart (lista de `{talla, stock}`).

    El POST es multipart por las fotos, así que la lista no puede viajar como
    Form anidado: el front la serializa y acá se revalida con el schema, igual
    que un body JSON normal.
    """
    if not crudo or not crudo.strip():
        return []
    try:
        datos = json.loads(crudo)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El formato de las tallas no es válido.",
        )
    if not isinstance(datos, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las tallas deben venir como una lista.",
        )
    try:
        variantes = [ProductoVarianteInput(**item) for item in datos]
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cada talla necesita un nombre de hasta 30 caracteres y un stock válido.",
        )
    return _normalizar_variantes(variantes)


def _reemplazar_variantes(db: Session, producto: Producto,
                          variantes: List[dict]) -> None:
    """Deja las tallas del producto EXACTAMENTE como la lista recibida.

    Se compara por talla normalizada (`lower`) porque el front manda texto, no
    ids: se borran las que ya no están, se actualiza el stock de las que siguen y
    se crean las nuevas. `activo` se conserva en las existentes.

    Borrar una talla NO rompe el historial: `pedidos.variante_id` es ON DELETE
    SET NULL y `pedidos.talla` ya guardó el texto al momento de comprar (083).
    """
    existentes = {v.talla.lower(): v for v in producto.variantes}
    recibidas = set()
    for item in variantes:
        clave = item["talla"].lower()
        recibidas.add(clave)
        actual = existentes.get(clave)
        if actual is None:
            db.add(ProductoVariante(producto_id=producto.id,
                                    talla=item["talla"], stock=item["stock"]))
        else:
            # Se conserva el texto guardado (el admin pudo escribir "S" y mandar
            # "s"): sólo se actualiza el stock.
            actual.stock = item["stock"]
    for clave, variante in existentes.items():
        if clave not in recibidas:
            db.delete(variante)


def _talla_en_conflicto(db: Session, producto_id: int,
                        tallas: List[str]) -> Optional[str]:
    """Cuál de esas tallas ya existe en la BD (para el 400 del índice único).

    Sólo se usa en el camino de error (carrera entre dos guardados), así que la
    consulta extra no cuesta nada en el caso normal.
    """
    if not tallas:
        return None
    existentes = {
        fila[0] for fila in
        db.query(func.lower(ProductoVariante.talla))
          .filter(ProductoVariante.producto_id == producto_id)
          .all()
    }
    for talla in tallas:
        if talla.lower() in existentes:
            return talla
    return None


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
    # Las tallas (083) viajan SIEMPRE en la respuesta (`ProductoResponse`), así
    # que se cargan de una vez con el producto: sin esto la serialización
    # dispararía un lazy load por producto.
    query = db.query(Producto).options(selectinload(Producto.variantes))
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
    descuento_pct: Optional[int] = Form(None),
    activo: bool = Form(True),
    # Tallas/variantes (migración 083). El POST es multipart por las fotos, así
    # que la lista no puede ser un Form anidado: el front la serializa a JSON y
    # acá se revalida con `ProductoVarianteInput` (`_parsear_variantes_json`).
    tiene_variantes: bool = Form(False),
    variantes_json: Optional[str] = Form(None),
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

    # Las tallas se validan ANTES de subir ninguna foto: un payload inválido no
    # tiene que dejar archivos huérfanos en el almacenamiento. Con el switch
    # APAGADO la lista se ignora por completo: el producto nace sin variantes.
    variantes = _parsear_variantes_json(variantes_json) if tiene_variantes else []
    if tiene_variantes and not variantes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Agrega al menos una talla o desactiva "
                    "«Este producto tiene tallas»."),
        )

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
        # Con tallas, `productos.stock` queda congelado en 0: el stock real vive
        # en `producto_variantes` y el número que ve el Bazar es la suma de las
        # tallas activas (calculada al armar la respuesta). No se mantiene un
        # total redundante en paralelo (decisión de la 083).
        stock=0 if tiene_variantes else stock,
        stock_minimo=stock_minimo,
        imagen_url=imagen_url,
        dias_anuncio=max(int(dias_anuncio or 0), 0),
        # Descuento manual (migración 072). None/ausente = sin descuento.
        descuento_pct=descuento_pct,
        activo=activo,
        tiene_variantes=bool(tiene_variantes),
    )

    try:
        db.add(db_producto)
        db.flush()  # necesitamos el id para las filas de la galería
        for orden, url in enumerate(urls_guardadas):
            db.add(ProductoImagen(producto_id=db_producto.id,
                                  url=url, orden=orden))
        # Misma transacción que el producto y la galería: si algo falla no queda
        # un producto con tallas a medias.
        for variante in variantes:
            db.add(ProductoVariante(producto_id=db_producto.id,
                                    talla=variante["talla"],
                                    stock=variante["stock"]))
        db.commit()
    except IntegrityError as error:
        db.rollback()
        for url in urls_guardadas:
            storage.borrar_publico(url)
        if es_talla_duplicada(error):
            # En el alta es prácticamente imposible (un producto nuevo no choca
            # con otra talla), pero se traduce igual a 400 y nunca a un 500.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_mensaje_talla_duplicada(None),
            )
        raise
    except Exception:
        db.rollback()
        for url in urls_guardadas:
            storage.borrar_publico(url)
        raise

    db.refresh(db_producto)
    # La respuesta incluye el desglose de tallas (083): se carga explícitamente
    # después del commit para no depender de un lazy load.
    db.refresh(db_producto, ["variantes"])

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
    producto = db.query(Producto).options(
        selectinload(Producto.variantes)
    ).filter(
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

    # `selectinload` evita N+1 al serializar la galería y las tallas de cada producto.
    query = (db.query(Producto)
               .options(selectinload(Producto.imagenes),
                        selectinload(Producto.variantes))
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

    # ── Tallas/variantes (migración 083) ─────────────────────────────────────
    # `variantes` NO es una columna: se saca del setattr genérico y se aplica como
    # reemplazo del set completo. Se valida ANTES de tocar la fila: un payload con
    # tallas repetidas no puede dejar el producto a medio guardar.
    variantes_recibidas = (
        _normalizar_variantes(producto_data.variantes)
        if producto_data.variantes is not None else None
    )
    update_data.pop("variantes", None)
    # `tiene_variantes` es NOT NULL en la BD: un null explícito se ignora (equivale
    # a no mandarlo) en vez de romper el UPDATE.
    if "tiene_variantes" in update_data and update_data["tiene_variantes"] is None:
        update_data.pop("tiene_variantes")
    tiene_variantes_final = update_data.get("tiene_variantes",
                                            producto.tiene_variantes)
    if tiene_variantes_final:
        # Encender el switch sin tallas dejaría el producto "agotado" para
        # siempre: o hay desglose, o el producto vuelve al stock plano.
        if variantes_recibidas is not None:
            sin_tallas = not variantes_recibidas
        else:
            sin_tallas = not producto.variantes
        if sin_tallas:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Agrega al menos una talla o desactiva "
                        "«Este producto tiene tallas»."),
            )

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

    # Reemplazo del set de tallas (crea / actualiza stock / borra las que faltan).
    if variantes_recibidas is not None:
        _reemplazar_variantes(db, producto, variantes_recibidas)

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
    #    Con tallas el stock útil es la SUMA de las tallas: `productos.stock`
    #    queda congelado para estos productos (083).
    if producto.tiene_variantes:
        if variantes_recibidas is not None:
            stock_actual = sum(v["stock"] for v in variantes_recibidas)
        else:
            stock_actual = sum((v.stock or 0) for v in producto.variantes if v.activo)
    else:
        stock_actual = producto.stock or 0
    if producto.stock_minimo is not None and stock_actual > producto.stock_minimo:
        producto.alerta_stock_enviada = False

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if not es_talla_duplicada(error):
            raise
        # Última red del índice único (083): dos guardados simultáneos del mismo
        # producto. Se busca la talla que ya existe para responder el mensaje
        # exacto del admin en vez de un 500.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_mensaje_talla_duplicada(_talla_en_conflicto(
                db, producto_id,
                [v["talla"] for v in (variantes_recibidas or [])])),
        )
    db.refresh(producto)
    # El desglose (y el `stock` derivado de la respuesta) se devuelve fresco.
    db.refresh(producto, ["variantes"])

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
