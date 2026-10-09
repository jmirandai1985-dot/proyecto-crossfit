"""
Router de endpoints para gestión de Pedidos
"""
import io
import logging
from app.core.urls import url_frontend  # B.2
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.database import get_db
from app.models.auditoria import Auditoria
from app.models.pedido import Pedido
from app.models.producto import Producto
from app.models.usuario import Usuario
from app.schemas.pedido import (
    PedidoCreate, PedidoUpdate, PedidoResponse, PedidoListItem,
    PedidoEntregaRequest, PedidoEntregaResponse, PedidoRechazoRequest,
)
from app.core.dependencies import (
    get_current_admin, get_current_coach, get_current_user, require_full_access,
)
from app.core.rate_limit import limiter, LIMIT_CODIGO_RETIRO
from app.core.config import settings
# El comprobante de un pedido se sirve con el MISMO helper que el voucher de una
# solicitud de plan: dos orígenes (/static/uploads y /privado/vouchers), media type
# real y resolución del path sin salirse de la carpeta base.
from app.core.documentos_privados import (
    puede_ver_documento, respuesta_documento,
)
# Avisos del PANEL (tabla `notificaciones`, la que lee la campana): el Bazar no
# dejaba ninguna traza y el pedido sólo se veía entrando a las pantallas de
# Pedidos. Ver services/notificaciones_panel.py.
from app.services.notificaciones_panel import (
    notificar_admins_del_tenant, notificar_alumno,
)
# Las dos caras del código de retiro del Bazar (migración 044): generarlo al VALIDAR
# y consumirlo en el mesón. Toda la regla vive en el servicio (formato, unicidad por
# box, normalización de lo que se tipea/escanea y los textos de los 409).
from app.services import codigos_retiro
# Recordatorio MANUAL de retiro (panel móvil): dedupe del envío humano (tipos
# `*_manual`, reabriendo la fila del día si el intento falló) y la traza en auditoría.
from app.services.alertas_email_service import (
    _marcar_fallido, reclamar_envio_manual,
)
from app.services.auditoria_service import registrar_auditoria
from app.services import email_service
from app.services.email_service import (
    render_con_contacto, render_email_aviso_retiro, send_aviso_retiro,
)
from app.utils.santiago import ahora_santiago

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

# Mensaje de campana para el alumno dueño cuando el admin avanza su pedido.
# OJO: 'validado' NO está en este mapa a propósito — ese aviso lleva el CÓDIGO DE
# RETIRO y lo arma services/codigos_retiro.texto_validado().
# 'rechazado' (T3) sí está: el texto lo completa `texto_rechazo()` con el motivo del box.
MENSAJES_ESTADO_PEDIDO = {
    "entregado": "📦 Tu pedido de {producto} x{cantidad} fue entregado",
    "rechazado": "❌ Tu pedido de {producto} x{cantidad} fue rechazado",
}


def _nombre_de(db: Session, usuario_id: Optional[int]) -> Optional[str]:
    """Nombre del usuario `usuario_id` (o None): lo usa el 409 de 'ya entregado'."""
    if not usuario_id:
        return None
    fila = db.query(Usuario.nombre).filter(Usuario.id == usuario_id).first()
    return fila.nombre if fila else None


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

    # ── P0-4 (B-02): no se compran productos DESACTIVADOS ──
    # El catálogo los oculta (`GET /productos?activo=true`), pero el POST los
    # aceptaba igual: con el id a mano se podía comprar un producto retirado
    # (reproducido en TEST: 201 sobre `poleras` con activo=false).
    if not producto.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El producto no está disponible en el Bazar",
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
            detail="Alta demanda, intenta de nuevo",
        )

    # ── Aviso en el PANEL de los admins del box (campana; sin correo) ──
    # El pedido ya está commiteado: el aviso es best-effort (nunca tumba la
    # compra). Destinatarios: los administradores ACTIVOS del mismo tenant.
    if current_user.get("rol") in ("coach", "admin", "administrador"):
        nombre_alumno = alumno.nombre if alumno else "Atleta"
    else:
        nombre_alumno = current_user.get("nombre", "Atleta")
    notificar_admins_del_tenant(
        db, tenant_id, "pedido_nuevo",
        f"Nuevo pedido de {nombre_alumno}: {producto.nombre} "
        f"x{pedido_data.cantidad}")

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
            url_frontend("/alumno/mis-pedidos"),
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


def _con_nombres(db: Session, pedidos: List[Pedido]) -> List[dict]:
    """Adjunta los NOMBRES de alumno y producto a cada pedido del listado.

    El panel admin muestra "alumno / producto": resolverlos acá son 2 consultas con
    IN (no N+1) en vez de que el frontend cruce listados paginados (que además no
    siempre traen el alumno del pedido). Los ids se mantienen en la respuesta.
    """
    if not pedidos:
        return []
    ids_alumnos = {p.alumno_id for p in pedidos}
    ids_productos = {p.producto_id for p in pedidos}
    # El que entregó también es un usuario: se resuelve en la MISMA consulta con IN
    # (antes eran 2 consultas, ahora sigue siendo 2 pese a sumar la traza de entrega).
    ids_entrego = {p.entregado_por for p in pedidos if p.entregado_por}
    alumnos = db.query(Usuario.id, Usuario.nombre, Usuario.correo).filter(
        Usuario.id.in_(ids_alumnos | ids_entrego)).all()
    productos = db.query(Producto.id, Producto.nombre).filter(
        Producto.id.in_(ids_productos)).all()
    mapa_alumnos = {a.id: a for a in alumnos}
    mapa_productos = {p.id: p.nombre for p in productos}

    items = []
    for p in pedidos:
        alumno = mapa_alumnos.get(p.alumno_id)
        entrego = mapa_alumnos.get(p.entregado_por)
        items.append({
            "id": p.id,
            "alumno_id": p.alumno_id,
            "producto_id": p.producto_id,
            "cantidad": p.cantidad,
            "total": p.total,
            "estado": p.estado,
            "voucher_url": p.voucher_url,
            "fecha_pedido": p.fecha_pedido,
            "alumno_nombre": alumno.nombre if alumno else None,
            "alumno_email": alumno.correo if alumno else None,
            "producto_nombre": mapa_productos.get(p.producto_id),
            # Código de retiro + traza de la entrega (migración 044): es lo que el
            # panel del admin y el del alumno pintan (código destacado, QR y "quién
            # entregó").
            "codigo_retiro": p.codigo_retiro,
            "entregado_en": p.entregado_en,
            "entregado_por": p.entregado_por,
            "entregado_por_nombre": entrego.nombre if entrego else None,
            # La última actualización es lo que el panel móvil muestra como
            # "esperando retiro desde …" (la validación es el UPDATE que la mueve).
            "updated_at": p.updated_at,
        })
    return items


@router.get("/{pedido_id}/voucher")
def descargar_voucher_pedido(
    pedido_id: int,
    inline: bool = False,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Devuelve el COMPROBANTE de pago (voucher) de un pedido del Bazar.

    POR QUÉ EXISTE: el comprobante se subía con ?privado=1 a la carpeta privada
    (fuera de /static/), pero NADIE podía verlo: no había endpoint que lo sirviera,
    así que el admin no podía revisar el pago de un pedido.

    Mismo contrato que el voucher de una solicitud de plan:
    - solo el alumno dueño del pedido o el staff del MISMO box;
    - ?inline=1 para previsualizar (por defecto: descarga forzada).
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param no existe acá.
    tenant_id = current_user["tenant_id"]
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.tenant_id == tenant_id,
    ).first()
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado",
        )

    # 🔒 IDOR: solo el dueño del pedido o el staff del box (mismo guard que el GET).
    visible = puede_ver_documento(
        usuario_id=current_user["usuario_id"],
        tenant_id=tenant_id,
        alumno_id=pedido.alumno_id,
        tenant_documento=pedido.tenant_id,
        rol=current_user.get("rol", ""),
    )
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes ver el comprobante de este pedido",
        )

    if not pedido.voucher_url:
        raise HTTPException(status_code=404, detail="Sin comprobante disponible")

    return respuesta_documento(pedido.voucher_url, "comprobante", inline)


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

    # Los nombres (alumno / producto) los completa el backend: el panel admin los
    # muestra en la tabla y el panel del alumno sigue leyendo los ids.
    return _con_nombres(db, pedidos)


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

    # ── CÓDIGO DE RETIRO: se genera UNA sola vez, al VALIDAR (migración 044) ──
    # En la MISMA transacción que la validación, para que el aviso de campana de
    # abajo viaje con el código definitivo. Si el pedido ya tiene uno (revalidar
    # tras un 400, datos viejos), se respeta: el código no cambia nunca.
    if nuevo_estado == "validado" and not pedido.codigo_retiro:
        try:
            pedido.codigo_retiro = codigos_retiro.generar_codigo_unico(
                db, tenant_id)
        except codigos_retiro.SinCodigoDisponible as error:
            db.rollback()
            logger.error(f"No se pudo generar el código de retiro: {error}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo generar el código de retiro. Intenta de nuevo.",
            )

    # La entrega deja SIEMPRE su traza (quién y cuándo), venga del mesón (código)
    # o de este respaldo del admin.
    if nuevo_estado == "entregado":
        pedido.entregado_por = current_user["usuario_id"]
        pedido.entregado_en = ahora_santiago()

    db.commit()
    db.refresh(pedido)

    # ── Aviso en el PANEL del alumno dueño (campana; sin correo) ──
    # Antes, el avance del pedido sólo se veía entrando a Mis Pedidos.
    producto_pedido = db.query(Producto).filter(
        Producto.id == pedido.producto_id).first()
    nombre_producto = (
        producto_pedido.nombre if producto_pedido else "tu producto")
    if nuevo_estado == "validado":
        # El aviso de validación llega con el CÓDIGO DE RETIRO adentro.
        mensaje = codigos_retiro.texto_validado(
            nombre_producto, pedido.cantidad, pedido.codigo_retiro)
    else:
        plantilla = MENSAJES_ESTADO_PEDIDO.get(nuevo_estado)
        mensaje = (plantilla.format(producto=nombre_producto, cantidad=pedido.cantidad)
                   if plantilla else None)
    if mensaje:
        notificar_alumno(
            db, pedido.alumno_id, f"pedido_{nuevo_estado}", mensaje)

    return pedido


# ═══════════════════════════════════════════════════════════════════════════════
#  RECHAZO DE UN PEDIDO PENDIENTE (admin, T3)
#
#  Un pedido `pendiente` (comprobante subido, sin validar) se puede RECHAZAR con un
#  motivo. Es el camino que faltaba: sin esto, un comprobante inválido quedaba pendiente
#  para siempre (o el admin lo borraba, perdiendo el rastro) y el alumno no se enteraba.
#
#  Reglas (dinero/stock, por eso viven juntas):
#   * SÓLO desde `pendiente`: un `validado`/`entregado` ya se cobró y devolverlo es un
#     reembolso (otro flujo) → 400, no se toca el stock.
#   * La devolución de stock es ATÓMICA: el pedido y el producto se bloquean con
#     `with_for_update()` y el cambio de estado + stock van en UNA transacción (dos
#     rechazos simultáneos no devuelven el stock dos veces).
#   * `rechazado` NO está en `ESTADOS_PAGO_BAZAR` → no suma en ventas del Bazar (BI,
#     Excel e historial) por construcción.
#   * El alumno recibe el motivo en su campana (`notificar_alumno`, best-effort).
# ═══════════════════════════════════════════════════════════════════════════════
def texto_rechazo(producto: str, cantidad: int, motivo: str) -> str:
    """Mensaje de campana del pedido rechazado, CON el motivo que dejó el box.

    Puro (se testea sin BD). El motivo se agrega al final para que el aviso funcione igual
    aunque el motivo venga vacío en una llamada interna.
    """
    base = MENSAJES_ESTADO_PEDIDO["rechazado"].format(producto=producto, cantidad=cantidad)
    return f"{base}. Motivo: {motivo}"


@router.post("/{pedido_id}/rechazar", response_model=PedidoResponse)
def rechazar_pedido(
    pedido_id: int,
    data: PedidoRechazoRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """RECHAZA un pedido PENDIENTE con un motivo (sólo admin del box del token).

    Devuelve el stock de forma atómica, deja el pedido en `rechazado` y avisa al alumno
    en su campana con el motivo. Un pedido ya cobrado (`validado`/`entregado`) → 400.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param no existe acá.
    tenant_id = current_user["tenant_id"]
    motivo = (data.motivo or "").strip()

    # Bloqueo del pedido: dos admins no pueden rechazarlo/entregarlo a la vez.
    pedido = (
        db.query(Pedido)
        .filter(Pedido.id == pedido_id, Pedido.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado",
        )
    if pedido.estado != "pendiente":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Sólo se puede rechazar un pedido pendiente. Un pedido "
                    f"'{pedido.estado}' ya fue cobrado: para devolverlo hace falta un "
                    "reembolso, no un rechazo."),
        )

    try:
        # El stock se devuelve en la MISMA transacción que el cambio de estado.
        producto = (
            db.query(Producto)
            .filter(Producto.id == pedido.producto_id)
            .with_for_update()
            .first()
        )
        if producto is not None:
            producto.stock = (producto.stock or 0) + pedido.cantidad
        pedido.estado = "rechazado"
        db.commit()
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alta demanda, intenta de nuevo",
        )
    db.refresh(pedido)

    # ── Aviso en la campana del alumno dueño (best-effort, ya commiteado) ────
    nombre_producto = producto.nombre if producto else "tu producto"
    notificar_alumno(
        db, pedido.alumno_id, "pedido_rechazado",
        texto_rechazo(nombre_producto, pedido.cantidad, motivo))

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


# ══════════════════════════════════════════════════════════════════════════════
#  CÓDIGO DE RETIRO DEL BAZAR (migración 044 · services/codigos_retiro.py)
#
#  El código se GENERA al validar (PUT /{id}/estado, arriba) y se CONSUME acá, en el
#  mesón: el alumno muestra su QR/código, quien atiende lo ingresa o lo escanea y el
#  pedido pasa a `entregado` con quién y cuándo. El endpoint va declarado por su
#  ruta completa (`/entregar`) y usa POST, así que no compite con `GET /{pedido_id}`.
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/entregar", response_model=PedidoEntregaResponse)
@limiter.limit(LIMIT_CODIGO_RETIRO)
def entregar_pedido_con_codigo(
    request: Request,
    data: PedidoEntregaRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Entrega un pedido del Bazar contra su CÓDIGO DE RETIRO (pantalla del mesón).

    Quién: el administrador o un COACH DEL MISMO BOX (`get_current_coach`). Un alumno
    nunca pasa este guard (403): el código prueba que quien retira es el dueño, pero
    sólo el staff puede cerrar la entrega.

    Respuestas:
    - 200: entregado (alumno / producto / cantidad, SIN montos: el coach no
      administra el Bazar);
    - 404 genérico: el código no existe EN ESTE BOX (uno de otro box da lo mismo:
      el 404 no revela que exista en otro lado);
    - 409: el código existe pero su pedido no se puede entregar todavía (sigue
      pendiente) o YA se entregó, con la fecha y quién lo entregó.

    Rate limit propio: un código son 4 símbolos, sin límite se podría barrer.
    """
    # 🔒 SEGURIDAD: el box sale del TOKEN; no hay query param que se pueda falsear.
    tenant_id = current_user["tenant_id"]

    pedido = codigos_retiro.buscar_pedido_por_codigo(db, tenant_id, data.codigo)
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Código de retiro no válido",
        )

    motivo = codigos_retiro.motivo_no_entregable(pedido)
    if motivo == codigos_retiro.MOTIVO_YA_ENTREGADO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=codigos_retiro.texto_ya_entregado(
                pedido, _nombre_de(db, pedido.entregado_por)),
        )
    if motivo == codigos_retiro.MOTIVO_NO_VALIDADO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=codigos_retiro.texto_no_validado(pedido),
        )

    # ── Entrega ATÓMICA (mismo patrón que el descuento de stock del Bazar) ───
    # UPDATE condicional: sólo pasa si el pedido SIGUE validado. Si dos mesones
    # escanean el mismo código a la vez, el segundo ve rowcount=0 y recibe el 409
    # de "ya fue entregado" en vez de entregar el pedido dos veces.
    try:
        resultado = db.execute(
            update(Pedido)
            .where(Pedido.id == pedido.id)
            .where(Pedido.tenant_id == tenant_id)
            .where(Pedido.estado == "validado")
            .values(
                estado="entregado",
                entregado_por=current_user["usuario_id"],
                entregado_en=ahora_santiago(),
            )
            .execution_options(synchronize_session=False)
        )
        if resultado.rowcount == 0:
            # Se lo llevaron entre la lectura y el UPDATE: se informa el estado real.
            db.rollback()
            otro = codigos_retiro.buscar_pedido_por_codigo(
                db, tenant_id, data.codigo)
            detalle = (
                codigos_retiro.texto_ya_entregado(
                    otro, _nombre_de(db, otro.entregado_por))
                if otro is not None else
                "Este pedido ya no se puede entregar")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=detalle)
        db.commit()
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alta demanda, intenta de nuevo",
        )
    db.refresh(pedido)

    # ── Aviso en la campana del alumno dueño (best-effort, ya commiteado) ────
    producto = db.query(Producto.nombre).filter(
        Producto.id == pedido.producto_id).first()
    nombre_producto = producto.nombre if producto else "tu producto"
    notificar_alumno(
        db, pedido.alumno_id, "pedido_entregado",
        MENSAJES_ESTADO_PEDIDO["entregado"].format(
            producto=nombre_producto, cantidad=pedido.cantidad))

    alumno = db.query(Usuario.nombre).filter(
        Usuario.id == pedido.alumno_id).first()
    return PedidoEntregaResponse(
        pedido_id=pedido.id,
        alumno_nombre=alumno.nombre if alumno else None,
        producto_nombre=nombre_producto,
        cantidad=pedido.cantidad,
        entregado_en=pedido.entregado_en,
        codigo=pedido.codigo_retiro,
    )


@router.get("/{pedido_id}/qr.svg")
@limiter.limit("30/minute")
def qr_retiro_pedido(
    request: Request,
    pedido_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """SVG del QR del CÓDIGO DE RETIRO del pedido (lo escanea el mesón).

    Contenido del QR: SÓLO el código ("UB-4827"), no una URL — así lo lee cualquier
    lector, incluida la cámara del celular. El mesón lo tipea o lo escanea en la
    pantalla de entrega.

    Mismo guard de visibilidad que el comprobante: el alumno DUEÑO o el staff del
    box. Sin código (pedido todavía sin validar) → 404.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param no existe acá.
    tenant_id = current_user["tenant_id"]
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.tenant_id == tenant_id,
    ).first()
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado",
        )

    # 🔒 IDOR: solo el dueño del pedido o el staff del box.
    visible = puede_ver_documento(
        usuario_id=current_user["usuario_id"],
        tenant_id=tenant_id,
        alumno_id=pedido.alumno_id,
        tenant_documento=pedido.tenant_id,
        rol=current_user.get("rol", ""),
    )
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes ver el código de retiro de este pedido",
        )

    if not pedido.codigo_retiro:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El pedido todavía no tiene código de retiro",
        )

    # Import diferido: segno es pura Python y sólo se necesita acá (igual que el QR
    # del box en tenants.py).
    from segno import make as qr_make

    qr = qr_make(pedido.codigo_retiro, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=8)
    return Response(
        content=buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "private, max-age=300"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  RECORDATORIO MANUAL DE RETIRO (panel admin móvil <768px)
#
#  "Pedidos listos para entrega" = los VALIDADOS que aún nadie retiró (código de
#  retiro generado y sin entrega): el listado sale de `GET /pedidos?estado=validado`,
#  que ya existe.
#
#  El correo de acá es ADICIONAL a la campana automática `pedido_validado` (esa ya
#  viaja al alumno al validar, con el código): NO la reemplaza ni la duplica — este
#  flujo no escribe en `notificaciones` (la campana), sólo manda el correo y deja
#  su traza.
# ═══════════════════════════════════════════════════════════════════════════════
AVISO_RETIRO_TIPO = "pedido_recordatorio_manual"


def _pedido_del_box(db: Session, current_user: dict, pedido_id: int) -> Pedido:
    """Pedido del box del token, o 404 (sin revelar si el id existe en otro box)."""
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.tenant_id == current_user["tenant_id"],
    ).first()
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido con ID {pedido_id} no encontrado",
        )
    return pedido


def _pedido_para_avisar(db: Session, current_user: dict, pedido_id: int):
    """`(pedido, alumno, nombre_producto)` de un pedido que SÍ se puede recordar.

    La regla es la MISMA que la del mesón (`codigos_retiro.motivo_no_entregable`):
    un pedido `pendiente` todavía no se validó (no hay retiro que recordar) y uno
    `entregado` ya no espera nada. El alumno sin correo corta con 400 (no falla en
    silencio).
    """
    pedido = _pedido_del_box(db, current_user, pedido_id)
    motivo = codigos_retiro.motivo_no_entregable(pedido)
    if motivo == codigos_retiro.MOTIVO_YA_ENTREGADO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=codigos_retiro.texto_ya_entregado(pedido),
        )
    if motivo is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este pedido todavía no fue validado: no hay retiro que recordar",
        )
    if not pedido.codigo_retiro:
        # Datos viejos (validados antes de la migración 044) no tienen código: el
        # correo prometería un retiro sin código, así que se corta acá.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El pedido todavía no tiene código de retiro",
        )

    alumno = db.query(Usuario).filter(Usuario.id == pedido.alumno_id).first()
    if not alumno or not alumno.correo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El alumno no tiene correo registrado: no hay a dónde mandar el aviso",
        )
    producto = db.query(Producto.nombre).filter(
        Producto.id == pedido.producto_id).first()
    return pedido, alumno, (producto.nombre if producto else "tu producto")


def ultimo_aviso_manual(db: Session, tenant_id: int, pedido_ids: list) -> dict:
    """`{pedido_id: 'YYYY-MM-DDTHH:MM:SS'}` del último aviso MANUAL de retiro.

    Una sola consulta (GROUP BY) para toda la lista: alimenta el "Informado hace X" de
    cada fila. La traza vive en `auditoria` (accion `EMAIL_MANUAL` + entidad `pedido`)
    porque `notificaciones_enviadas` dedupea por (alumno, tipo, día) y no sabe de
    pedidos: el aviso manual es POR PEDIDO.
    """
    if not pedido_ids:
        return {}
    filas = (
        db.query(Auditoria.entidad_id, func.max(Auditoria.fecha))
        .filter(
            Auditoria.tenant_id == tenant_id,
            Auditoria.accion == "EMAIL_MANUAL",
            Auditoria.entidad == "pedido",
            Auditoria.entidad_id.in_(pedido_ids),
        )
        .group_by(Auditoria.entidad_id)
        .all()
    )
    return {pedido_id: (fecha.isoformat() if fecha else None)
            for pedido_id, fecha in filas}



@router.get("/{pedido_id}/aviso-retiro/preview")
def preview_aviso_retiro(
    pedido_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Vista previa del recordatorio: asunto y HTML EXACTOS (no manda ni registra).

    Usa la MISMA función de render que el envío real, así el modal del panel móvil no
    puede mostrar un correo distinto del que sale. Sólo admin del box.
    """
    pedido, alumno, nombre_producto = _pedido_para_avisar(db, current_user, pedido_id)

    asunto, html = render_email_aviso_retiro(
        alumno.nombre, nombre_producto, pedido.cantidad, pedido.codigo_retiro)
    html = render_con_contacto(html, current_user["tenant_id"])

    return {
        "pedido_id": pedido.id,
        "nombre": alumno.nombre,
        "destinatario": alumno.correo,
        "asunto": asunto,
        "html": html,
        "producto": nombre_producto,
        "cantidad": pedido.cantidad,
        "codigo_retiro": pedido.codigo_retiro,
        "esperando_desde": pedido.updated_at.isoformat() if pedido.updated_at else None,
        "informado_en": ultimo_aviso_manual(
            db, current_user["tenant_id"], [pedido.id]).get(pedido.id),
    }


@router.post("/{pedido_id}/aviso-retiro")
def enviar_aviso_retiro(
    pedido_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Manda el recordatorio manual de retiro (uno por alumno + día).

    Dedupe: `reclamar_envio_manual` con un `tipo` PROPIO del envío manual, así que no
    toca el conteo del scheduler ni la campana automática (`pedido_validado`). Si el
    envío de hoy ya salió, no se repite y se devuelve la hora (`ya_enviado: true`);
    si el de hoy había FALLADO, se reintenta (se reabre esa fila).
    """
    pedido, alumno, nombre_producto = _pedido_para_avisar(db, current_user, pedido_id)
    tenant_id = current_user["tenant_id"]

    envio_id = reclamar_envio_manual(db, alumno.id, AVISO_RETIRO_TIPO,
                                     tenant_id=tenant_id)
    if envio_id is None:
        return {
            "exito": True,
            "ya_enviado": True,
            "estado": "enviado",
            "detalle_error": None,
            "informado_en": ultimo_aviso_manual(db, tenant_id, [pedido.id]).get(pedido.id),
        }

    exito = send_aviso_retiro(alumno.nombre, alumno.correo, nombre_producto,
                              pedido.cantidad, pedido.codigo_retiro, registrar=False)

    detalle_error = None
    if not exito:
        detalle_error = email_service.ULTIMO_ERROR_SMTP or (
            "No se pudo enviar el correo (revisar SMTP y el correo del alumno).")
        _marcar_fallido(db, envio_id, f"{AVISO_RETIRO_TIPO} FALLIDO -> {alumno.correo}")

    # Traza POR PEDIDO (el "Informado hace X" de la fila) + quién lo mandó.
    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="EMAIL_MANUAL",
        entidad="pedido",
        entidad_id=pedido.id,
        detalle={"tipo": AVISO_RETIRO_TIPO, "codigo_retiro": pedido.codigo_retiro,
                 "exito": exito, "origen": "panel_admin_movil"},
    )

    return {
        "exito": exito,
        "ya_enviado": False,
        "estado": "enviado" if exito else "fallido",
        "detalle_error": detalle_error,
        "informado_en": (ultimo_aviso_manual(db, tenant_id, [pedido.id]).get(pedido.id)
                         if exito else None),
    }

