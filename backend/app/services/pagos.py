"""
Orquestación de los pagos online: crear el cobro y aplicar su resultado.

Reglas que este módulo hace cumplir (y que no viven en el endpoint):

* **El monto lo calcula el backend** y se congela en `pagos.monto_clp`. El front
  nunca manda plata, y el webhook compara el monto que confirma MP con ESE número
  (`monto_clp`): un pago por otro importe no activa nada.
* **Idempotencia doble**: `pagos_eventos.notificacion_id` UNIQUE (dedupe exacto de
  reintentos) + `UPDATE pagos ... WHERE estado IN (abiertos)` (una sola aplicación
  aunque dos eventos distintos cuenten lo mismo). Si el pago ya está `aprobado`,
  un evento repetido devuelve `duplicado` y no toca el negocio.
* **El negocio se aplica por la MISMA función que el admin**: `activar_plan` para
  membresías y `marcar_validado` para pedidos del Bazar. Acá no se escribe ni una
  `Suscripcion` ni una `TransaccionFinanciera` a mano.
* **Un pago aprobado de un pedido que ya venció no se revive**: se avisa a los
  admins para que devuelvan el dinero o repongan stock (medios "en efectivo" se
  acreditan días después; por eso el Bazar los excluye de la preferencia).

El webhook NUNCA crea solicitudes ni pedidos: sólo cambia el estado de algo que ya
existe y está vinculado por `pago_id`. Un evento fuera de orden es inocuo.
"""
import logging
import uuid
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models.pago import ESTADOS_PAGO_ABIERTOS, Pago, PagoEvento
from app.models.pedido import Pedido
from app.models.plan import Plan
from app.models.producto import Producto
from app.models.solicitud_plan import SolicitudPlan
from app.models.usuario import Usuario
from app.services import aprobacion_planes
from app.services import beneficios_service as beneficios
from app.services import mercadopago_cliente as mp
from app.services import pedidos_estado
from app.services.notificaciones_panel import notificar_admins_del_tenant
from app.utils.santiago import ahora_santiago

logger = logging.getLogger(__name__)

CONCEPTO_MEMBRESIA = "membresia"
CONCEPTO_BAZAR = "bazar"


class ErrorPago(Exception):
    """Error de negocio del checkout (el endpoint lo traduce a HTTP).

    `status_code` es el código con el que se responde y `detalle` el mensaje que
    ve el alumno: "el pago online no está disponible, usa transferencia" en vez
    de un 500.
    """

    def __init__(self, detalle: str, status_code: int = 400):
        super().__init__(detalle)
        self.detalle = detalle
        self.status_code = status_code


def _email(db: Session, usuario_id: int) -> str:
    fila = db.query(Usuario.correo).filter(Usuario.id == usuario_id).first()
    return (fila.correo if fila else "") or ""


def _alertar_admins(db: Session, tenant_id: int, tipo: str, mensaje: str) -> None:
    """Aviso en la campana del box (best-effort: nunca tumba el cobro)."""
    try:
        notificar_admins_del_tenant(db, tenant_id, tipo, mensaje)
    except Exception as error:  # pragma: no cover - best-effort
        logger.warning("No se pudo avisar a los admins del box %s: %s",
                       tenant_id, error)



def crear_pago_membresia(db: Session, *, current_user: dict, plan_id: int,
                         certificado_estudiante_url: Optional[str] = None) -> dict:
    """Crea la solicitud + la fila `pagos` + la preferencia de Checkout Pro.

    Valida lo mismo que el flujo manual (plan del box, sin otra solicitud
    pendiente) y congela el precio con la aritmética existente: el descuento
    vigente (F2) se aplica acá y ese número es el que se cobra y el que después
    registra la transacción.

    La solicitud NACE `pending` y SIN comprobante (`origen_pago='mercadopago'`):
    el admin verá el badge "Pagado online" en vez de un voucher inexistente. Si
    MP confirma el pago, el webhook la aprueba con `activar_plan`.
    """
    # Fail-fast ANTES de tocar la base: si la pasarela está apagada no se crea
    # una solicitud huérfana que después hay que rechazar a mano.
    config = mp.configuracion()  # noqa: F841  (valida habilitado + credenciales)

    tenant_id = current_user["tenant_id"]
    alumno_id = current_user["usuario_id"]

    plan = db.query(Plan).filter(
        Plan.id == plan_id, Plan.tenant_id == tenant_id).first()
    if not plan:
        raise ErrorPago("Plan no encontrado", 404)

    # Misma regla que POST /solicitudes/solicitar: una sola solicitud pendiente.
    existente = db.query(SolicitudPlan).filter(
        SolicitudPlan.alumno_id == alumno_id,
        SolicitudPlan.tenant_id == tenant_id,
        SolicitudPlan.estado == "pending",
    ).first()
    if existente:
        raise ErrorPago("Ya tienes una solicitud pendiente", 400)

    # ── F2: el descuento VIGENTE se aplica a ESTA compra ──
    # La aritmética la hace el servicio de beneficios (un % calculado en dos
    # lados es un % que se desincroniza).
    descuento = {}
    lista = mp.monto_clp(plan.precio_clp)
    if lista > 0:
        vigente = beneficios.vigente(
            db, alumno_id, tipo=beneficios.TIPO_DESCUENTO)
        if vigente is not None:
            aritmetica = beneficios.desglose(vigente, lista)
            descuento = {
                "beneficio_id": vigente.id,
                "descuento_pct": aritmetica["descuento_pct"],
                # Se congela el precio final: es exactamente lo que cobra MP y
                # lo que va a registrar `activar_plan` (sin re-descuentos).
                "precio_final_clp": aritmetica["precio_final_clp"],
            }

    monto = mp.monto_clp(descuento.get("precio_final_clp") or lista)
    if monto <= 0:
        raise ErrorPago(
            "Este plan no tiene un precio cobrable online. Usa transferencia.",
            400)

    solicitud = SolicitudPlan(
        tenant_id=tenant_id,
        alumno_id=alumno_id,
        plan_id=plan.id,
        estado="pending",
        # Sin voucher: el cobro lo prueba Mercado Pago, no un archivo.
        voucher_url=None,
        certificado_estudiante_url=certificado_estudiante_url or None,
        precio_clp_snapshot=plan.precio_clp,
        # Precio final SIEMPRE congelado (aunque no haya descuento): así
        # `activar_plan` no aplica un descuento de referido que MP no cobró y la
        # `TransaccionFinanciera` coincide con el pago, peso por peso.
        precio_final_clp=monto,
        origen_pago=aprobacion_planes.ORIGEN_MERCADOPAGO,
        beneficio_id=descuento.get("beneficio_id"),
        descuento_pct=descuento.get("descuento_pct"),
    )
    db.add(solicitud)
    db.flush()

    pago = Pago(
        tenant_id=tenant_id,
        usuario_id=alumno_id,
        concepto=CONCEPTO_MEMBRESIA,
        referencia_tipo="solicitud_plan",
        referencia_id=solicitud.id,
        monto_clp=monto,
        estado="pendiente",
        # UUID: el id secuencial de la fila no se filtra a un tercero.
        external_reference=str(uuid.uuid4()),
    )
    db.add(pago)
    db.flush()
    solicitud.pago_id = pago.id
    db.commit()

    return _crear_preferencia(db, pago, titulo=f"Plan {plan.nombre}")



def _crear_preferencia(db: Session, pago: Pago, *, titulo: str,
                       excluir_medios=()) -> dict:
    """Pide la preferencia a MP y guarda su `preference_id`.

    Si MP falla, la fila `pagos` queda `pendiente` (NO se borra): el job de
    expiración la cierra y, si el alumno alcanzó a pagar, la reconciliación lo
    recupera. El alumno recibe un 503 con "usa transferencia", nunca un error
    genérico.
    """
    try:
        preference_id, init_point = mp.crear_preferencia(
            pago=pago,
            titulo=titulo,
            email=_email(db, pago.usuario_id),
            excluir_medios=excluir_medios,
        )
    except mp.ErrorMercadoPago as error:
        logger.warning("Pago %s: no se pudo crear la preferencia (%s)",
                       pago.id, error)
        raise ErrorPago(
            "Mercado Pago no está disponible en este momento. "
            "Puedes pagar por transferencia.", 503)

    pago.preference_id = preference_id
    db.commit()
    return {
        "pago_id": pago.id,
        "init_point": init_point,
        "monto_clp": pago.monto_clp,
    }


def crear_pago_bazar(db: Session, *, current_user: dict, producto_id: int,
                     cantidad: int) -> dict:
    """Crea el pedido (reservando stock) + el pago + la preferencia de MP.

    El pedido nace `pendiente` y el stock se descuenta ATÓMICAMENTE al crearlo,
    igual que en el flujo de transferencia: reservar stock recién al cobrar
    permitiría que dos alumnos paguen la última polera. Si el pago no llega en
    30 minutos, la expiración lo rechaza y el stock vuelve por el mismo camino
    ya probado (`rechazar_pedido`).
    """
    mp.configuracion()  # fail-fast: apagado / sin credenciales -> no se toca stock

    tenant_id = current_user["tenant_id"]
    alumno_id = current_user["usuario_id"]

    producto = db.query(Producto).filter(
        Producto.id == producto_id, Producto.tenant_id == tenant_id).first()
    if not producto:
        raise ErrorPago("Producto no encontrado", 404)
    if not producto.activo:
        raise ErrorPago("El producto no está disponible en el Bazar", 400)
    if (producto.stock or 0) < cantidad:
        raise ErrorPago(
            f"Stock insuficiente. Disponible: {producto.stock}, "
            f"Solicitado: {cantidad}", 400)

    # CLP entero: `productos.precio` es Float y MP no acepta decimales en CLP.
    total = mp.monto_clp(producto.precio) * cantidad
    if total <= 0:
        raise ErrorPago("El producto no tiene un precio cobrable online", 400)

    pedido = Pedido(
        tenant_id=tenant_id,
        alumno_id=alumno_id,
        producto_id=producto.id,
        cantidad=cantidad,
        total=float(total),
        estado="pendiente",
        # Sin comprobante: el cobro lo prueba el webhook de MP.
        voucher_url=None,
        origen_pago=pedidos_estado.ORIGEN_MERCADOPAGO,
    )

    try:
        # Mismo UPDATE condicional que el POST manual: si dos compras piden el
        # último ítem, sólo una obtiene rowcount=1.
        resultado = db.execute(
            update(Producto)
            .where(Producto.id == producto.id)
            .where(Producto.tenant_id == tenant_id)
            .where(Producto.stock >= cantidad)
            .values(stock=Producto.stock - cantidad)
        )
        if resultado.rowcount == 0:
            raise ErrorPago(
                f"Stock insuficiente. Disponible: {producto.stock}, "
                f"Solicitado: {cantidad}", 400)
        db.add(pedido)
        db.flush()
        pago = Pago(
            tenant_id=tenant_id,
            usuario_id=alumno_id,
            concepto=CONCEPTO_BAZAR,
            referencia_tipo="pedido",
            referencia_id=pedido.id,
            monto_clp=total,
            estado="pendiente",
            external_reference=str(uuid.uuid4()),
        )
        db.add(pago)
        db.flush()
        pedido.pago_id = pago.id
        db.commit()
    except DBAPIError:
        db.rollback()
        raise ErrorPago("Alta demanda, intenta de nuevo", 503)

    return _crear_preferencia(
        db, pago, titulo=f"{producto.nombre} x{cantidad}",
        # `ticket` se acredita días después y el pedido ya habría vencido.
        excluir_medios=mp.MEDIOS_EXCLUIDOS_BAZAR)


# ── Webhooks: bitácora + aplicación del pago ────────────────────────────────
def registrar_evento(db: Session, *, notificacion_id: str, tipo: Optional[str] = None,
                     recurso_id: Optional[str] = None, firma_valida: bool = False,
                     request_id: Optional[str] = None,
                     ts_header: Optional[str] = None) -> Optional[PagoEvento]:
    """Inserta el evento o devuelve `None` si ya existía (reintento de MP).

    Se usa un SAVEPOINT (`begin_nested`): el UNIQUE de `notificacion_id` dispara
    IntegrityError y, sin savepoint, esa excepción dejaría la transacción
    completa inservible.
    """
    evento = PagoEvento(
        proveedor="mercadopago",
        notificacion_id=notificacion_id,
        tipo=tipo,
        recurso_id=recurso_id,
        firma_valida=firma_valida,
        request_id=request_id,
        ts_header=ts_header,
    )
    try:
        with db.begin_nested():
            db.add(evento)
            db.flush()
    except IntegrityError:
        db.rollback()
        return None
    db.commit()
    return evento


def buscar_pago(db: Session, detalle: dict) -> Optional[Pago]:
    """Localiza la fila `pagos` del pago de MP (por `external_reference`)."""
    referencia = detalle.get("external_reference")
    if referencia:
        pago = db.query(Pago).filter(
            Pago.external_reference == str(referencia)).first()
        if pago is not None:
            return pago
    # Fallback: el `payment_id` que ya hubiéramos guardado (reintento de MP de
    # un pago que sí llegó a aplicarse y cuyo external_reference no vino).
    payment_id = detalle.get("id")
    if payment_id:
        return db.query(Pago).filter(
            Pago.payment_id == str(payment_id)).first()
    return None


def _fecha_mp(valor):
    """`date_approved` de MP (ISO 8601) como datetime; si no se puede, ahora."""
    from datetime import datetime
    if isinstance(valor, str) and valor:
        try:
            return datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            pass
    return ahora_santiago()


def aplicar_pago(db: Session, pago: Pago, detalle: dict) -> str:
    """Aplica UN resultado de MP sobre UN pago. Devuelve el `resultado`.

    Pasos, en este orden (cada uno es un candado):

    1. El estado de MP se traduce al interno (`estado_desde_mp`); un estado
       desconocido no toca nada.
    2. El MONTO que confirma MP tiene que ser el que calculamos. Si no coincide,
       no se activa nada y se avisa a los admins.
    3. `UPDATE ... WHERE estado = <el que leímos>` (compare-and-swap): de dos
       eventos simultáneos, sólo uno aplica el negocio.
    4. `approved` → la MISMA función que el admin (`activar_plan` /
       `marcar_validado`). `reembolsado`/`charged_back` sobre un pago ya
       aprobado → alerta (NO se revierte solo: devolver un plan o revivir stock
       automáticamente es una decisión humana).
    """
    estado = mp.estado_desde_mp(detalle.get("status"))
    if estado is None:
        logger.info("Pago %s: estado de MP desconocido (%r)",
                    pago.id, detalle.get("status"))
        return "desconocido"

    monto_mp = mp.monto_clp(detalle.get("transaction_amount"))
    if monto_mp != pago.monto_clp:
        logger.warning("Pago %s: monto de MP %s != esperado %s",
                       pago.id, monto_mp, pago.monto_clp)
        _alertar_admins(
            db, pago.tenant_id, "pago_monto_no_coincide",
            (f"⚠️ Mercado Pago confirmó un pago de ${monto_mp:,} pero el cobro "
             f"#{pago.id} era de ${pago.monto_clp:,}. No se activó nada: "
             "revisa el pago en el panel de MP."))
        return "monto_no_coincide"

    anterior = pago.estado
    # `aprobado` sólo puede pasar a `reembolsado`; el resto es un reintento.
    if anterior == "reembolsado":
        return "duplicado"
    if anterior == "aprobado" and estado != "reembolsado":
        return "duplicado"

    payment_id = str(detalle.get("id") or "") or None
    if payment_id:
        ajeno = db.query(Pago.id).filter(
            Pago.payment_id == payment_id, Pago.id != pago.id).first()
        if ajeno is not None:
            logger.warning("Pago %s: el payment_id %s ya pertenece al pago %s",
                           pago.id, payment_id, ajeno.id)
            return "duplicado"

    resultado = db.execute(
        update(Pago)
        .where(Pago.id == pago.id)
        .where(Pago.estado == anterior)   # CAS: nadie más lo movió
        .values(
            estado=estado,
            payment_id=payment_id,
            metodo_pago=(detalle.get("payment_method_id") or None),
            tipo_pago=(detalle.get("payment_type_id") or None),
            estado_detalle=(detalle.get("status_detail") or None)[:60]
            if detalle.get("status_detail") else None,
            pagado_en=(_fecha_mp(detalle.get("date_approved"))
                       if estado == "aprobado" else pago.pagado_en),
            detalle_json=mp.sin_none({
                "id": detalle.get("id"),
                "status": detalle.get("status"),
                "status_detail": detalle.get("status_detail"),
                "transaction_amount": detalle.get("transaction_amount"),
                "payment_method_id": detalle.get("payment_method_id"),
                "payment_type_id": detalle.get("payment_type_id"),
                "external_reference": detalle.get("external_reference"),
                "date_approved": detalle.get("date_approved"),
                "live_mode": detalle.get("live_mode"),
            }),
        )
    )
    if resultado.rowcount == 0:
        db.rollback()
        return "duplicado"
    # El UPDATE se hizo por SQL: hay que refrescar el ORM para no seguir leyendo
    # el estado viejo en memoria.
    db.expire(pago)
    pago = db.query(Pago).filter(Pago.id == pago.id).first()

    # ── Efecto en el negocio ──
    if estado == "aprobado":
        _aplicar_beneficio(db, pago)
        db.commit()
    elif estado == "reembolsado" and anterior == "aprobado":
        # NO se revierte solo: se avisa para que un humano decida.
        _alertar_admins(
            db, pago.tenant_id, "pago_reembolsado",
            (f"↩️ Mercado Pago informó un reembolso/contracargo del pago "
             f"#{pago.id} (${pago.monto_clp:,}, {pago.concepto}). El beneficio "
             "NO se revirtió automáticamente: revisa el caso."))
        db.commit()
    else:
        db.commit()
    return "aplicado"


def _aplicar_beneficio(db: Session, pago: Pago) -> None:
    """Ejecuta la activación que corresponde al concepto del pago."""
    if pago.concepto == CONCEPTO_MEMBRESIA:
        try:
            aprobacion_planes.activar_plan(
                db, pago.referencia_id,
                actor_id=None,
                origen=aprobacion_planes.ORIGEN_MERCADOPAGO,
                pago_id=pago.id,
            )
        except aprobacion_planes.SolicitudNoProcesable as error:
            if error.motivo == "ya_procesada":
                # El admin la aprobó (o rechazó) mientras el pago viajaba.
                solicitud = db.query(SolicitudPlan).filter(
                    SolicitudPlan.id == pago.referencia_id).first()
                if solicitud is not None and solicitud.estado == "rejected":
                    # El alumno pagó y la solicitud está rechazada: plata sin
                    # contraprestación. Un humano tiene que devolverla.
                    _alertar_admins(
                        db, pago.tenant_id, "pago_aprobado_solicitud_rechazada",
                        (f"⚠️ Se aprobó el pago #{pago.id} "
                         f"(${pago.monto_clp:,}) de una solicitud de plan que "
                         "estaba RECHAZADA. Devuelve el dinero o activa el plan "
                         "a mano."))
            return
        except aprobacion_planes.PlanNoEncontrado:
            _alertar_admins(
                db, pago.tenant_id, "pago_aprobado_sin_plan",
                (f"⚠️ El pago #{pago.id} se aprobó pero su plan ya no existe "
                 "en el box. Revisa el cobro en el panel de MP."))
        return

    if pago.concepto == CONCEPTO_BAZAR:
        pedido = (
            db.query(Pedido)
            .filter(Pedido.id == pago.referencia_id,
                    Pedido.tenant_id == pago.tenant_id)
            .with_for_update()
            .first()
        )
        if pedido is None:
            _alertar_admins(
                db, pago.tenant_id, "pago_bazar_sin_pedido",
                (f"⚠️ El pago #{pago.id} se aprobó pero el pedido "
                 f"#{pago.referencia_id} ya no existe. Revisa el cobro."))
            return
        if pedido.estado == "pendiente":
            # Deja `SinCodigoDisponible` subir: el llamador hace rollback y el
            # evento queda sin procesar para que la reconciliación reintente.
            pedidos_estado.marcar_validado(
                db, pedido,
                origen=pedidos_estado.ORIGEN_MERCADOPAGO,
                pago_id=pago.id,
            )
            return
        if pedido.estado == "rechazado":
            # Pagó después del vencimiento (o de un rechazo): el pedido NO se
            # revive (el stock ya volvió y pudo venderse a otro).
            _alertar_admins(
                db, pago.tenant_id, "pago_bazar_pedido_vencido",
                (f"⚠️ Se aprobó el pago #{pago.id} (${pago.monto_clp:,}) de un "
                 f"pedido que ya estaba {pedido.estado}. Devuelve el dinero o "
                 "repon el stock a mano."))


def procesar_notificacion(db: Session, evento: PagoEvento,
                          detalle: dict) -> str:
    """Aplica el pago real (ya releído de MP) y cierra el evento.

    Si `_aplicar_beneficio` falla (BD, código de retiro, etc.), el evento queda
    con `procesado_en = NULL` y el `resultado` en `error`: la reconciliación lo
    levanta. Nunca se responde 5xx por un pago ya aplicado.
    """
    pago = buscar_pago(db, detalle)
    if pago is None:
        logger.warning("Webhook: no hay pago para external_reference=%r id=%r",
                       detalle.get("external_reference"), detalle.get("id"))
        evento.resultado = "desconocido"
        evento.procesado_en = ahora_santiago()
        db.commit()
        return "desconocido"

    evento.pago_id = pago.id
    evento.tenant_id = pago.tenant_id
    evento.resultado = aplicar_pago(db, pago, detalle)
    evento.procesado_en = ahora_santiago()
    db.commit()
    return evento.resultado


def estado_publico(db: Session, pago: Pago) -> dict:
    """`GET /pagos/{id}`: estado del cobro + si el beneficio ya se aplicó."""
    from shared.estados import ESTADOS_PAGO_BAZAR

    aplicado = False
    if pago.referencia_id:
        if pago.concepto == CONCEPTO_MEMBRESIA:
            fila = db.query(SolicitudPlan.estado).filter(
                SolicitudPlan.id == pago.referencia_id).first()
            aplicado = bool(fila and fila.estado == "approved")
        elif pago.concepto == CONCEPTO_BAZAR:
            fila = db.query(Pedido.estado).filter(
                Pedido.id == pago.referencia_id).first()
            aplicado = bool(fila and fila.estado in ESTADOS_PAGO_BAZAR)

    return {
        "id": pago.id,
        "concepto": pago.concepto,
        "estado": pago.estado,
        "monto_clp": pago.monto_clp,
        "moneda": pago.moneda or "CLP",
        "metodo_pago": pago.metodo_pago,
        "pagado_en": (pago.pagado_en.isoformat() if pago.pagado_en else None),
        "referencia_tipo": pago.referencia_tipo,
        "referencia_id": pago.referencia_id,
        "aplicado": aplicado,
    }


def expirar_pendientes(db: Session, *, minutos_bazar: int = 30,
                       horas_membresia: int = 24) -> dict:
    """Cierra los pagos que nunca se cobraron y libera lo que reservaban.

    * **Bazar (30 min)**: el stock vuelve por `rechazar_pedido` (el mismo camino
      del rechazo manual). Un pedido `pendiente` con la plata sin llegar es un
      producto bloqueado que otro alumno no puede comprar.
    * **Membresía (24 h)**: la solicitud pasa a `rejected` con
      `comentario_admin='Pago online no completado'` para que salga de la cola
      de pendientes del admin (no se crea basura que nadie va a aprobar).

    Un pago aprobado DESPUÉS de esto no revive nada: lo detecta `aplicar_pago`
    y avisa a los admins (ver `_aplicar_beneficio`).

    Lo llama `maintenance/reconciliar_pagos.py`; es idempotente.
    """
    from datetime import timedelta

    ahora = ahora_santiago()
    abiertos = db.query(Pago).filter(
        Pago.estado.in_(("pendiente", "en_proceso"))).all()

    contadores = {"expirados": 0, "pedidos_rechazados": 0,
                  "solicitudes_rechazadas": 0}
    for pago in abiertos:
        creado = pago.created_at
        if creado is None:
            continue
        if pago.concepto == CONCEPTO_BAZAR:
            if creado > ahora - timedelta(minutes=minutos_bazar):
                continue
        elif pago.concepto == CONCEPTO_MEMBRESIA:
            if creado > ahora - timedelta(hours=horas_membresia):
                continue
        else:  # concepto sin expiración definida (emergencia, futuro)
            continue

        # CAS: si el webhook lo aprobó mientras recorríamos la lista, no se toca.
        cerrado = db.execute(
            update(Pago)
            .where(Pago.id == pago.id)
            .where(Pago.estado.in_(("pendiente", "en_proceso")))
            .values(estado="expirado")
        )
        if cerrado.rowcount == 0:
            db.rollback()
            continue
        contadores["expirados"] += 1

        if pago.concepto == CONCEPTO_BAZAR:
            pedido = (
                db.query(Pedido)
                .filter(Pedido.id == pago.referencia_id,
                        Pedido.tenant_id == pago.tenant_id)
                .with_for_update()
                .first()
            )
            if pedido is not None and pedido.estado == "pendiente":
                pedidos_estado.rechazar_pedido(
                    db, pedido, "Pago online no completado",
                    origen=pedidos_estado.ORIGEN_MERCADOPAGO)
                contadores["pedidos_rechazados"] += 1
            else:
                db.commit()
        else:
            cambiadas = db.execute(
                update(SolicitudPlan)
                .where(SolicitudPlan.id == pago.referencia_id)
                .where(SolicitudPlan.estado == "pending")
                .values(estado="rejected",
                        comentario_admin="Pago online no completado")
            )
            if cambiadas.rowcount:
                contadores["solicitudes_rechazadas"] += 1
            db.commit()

    return contadores
