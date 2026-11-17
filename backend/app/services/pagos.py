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

El webhook NUNCA crea solicitudes ni pedidos: la solicitud de una membresía ya
existe en `iniciado` (oculta) desde el clic y el primer aviso real de MP la
ABRE (`pending`) o la CIERRA (`rejected`); el resto es cambiar el estado de algo
vinculado por `pago_id`. Un evento fuera de orden es inocuo.
"""
import logging
import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models.pago import Pago, PagoEvento
from app.models.pedido import Pedido
from app.models.plan import Plan
from app.models.producto import Producto, ProductoVariante
from app.models.solicitud_plan import SolicitudPlan
from app.models.usuario import Usuario
from app.services import aprobacion_planes, pedidos_estado
from app.services import beneficios_service as beneficios
from app.services import matricula_service
from app.services import mercadopago_cliente as mp
from app.services import referidos_service as referidos
from app.services.notificaciones_panel import notificar_admins_del_tenant
from app.utils.santiago import ahora_santiago

logger = logging.getLogger(__name__)

CONCEPTO_MEMBRESIA = "membresia"
CONCEPTO_BAZAR = "bazar"

# ── Cuándo se cierra un cobro ABANDONADO ─────────────────────────────────────
# Hay dos abandonos distintos y este módulo los trata distinto a propósito:
#
# 1. **El alumno nunca hizo nada en Mercado Pago** (cerró la pestaña o volvió con
#    el botón atrás del teléfono antes de meter un dato). No hay webhook: el pago
#    queda `iniciado` y la solicitud oculta, y el admin NO ve nada. No hace falta
#    cron para este caso; el guard de intentos en curso se libera solo a los
#    `MINUTOS_GUARD_MEMBRESIA` (5) y el siguiente intento limpia la fila vieja.
#
# 2. **Sí hubo un aviso real de MP y el alumno abandonó a mitad de camino** (dejó
#    el formulario a medio llenar, pagó en efectivo, etc.). Ahí la solicitud ya es
#    `pending` (visible) y hay que cerrarla:
#   • el botón "Cancelar" de la pantalla de retorno (`POST /pagos/{id}/cancelar`)
#     para el alumno que SÍ vuelve a la app;
#   • esta expiración automática para el que nunca vuelve.
#
# **DOS umbrales de membresía, a propósito** (no se igualan):
#   • `MINUTOS_GUARD_MEMBRESIA` (5): cuánto bloquea un intento `iniciado` sin
#     ningún aviso de MP y cuándo se limpia esa fila invisible. Es lo que ve el
#     alumno al volver a tocar "Pagar".
#   • `MINUTOS_MEMBRESIA` (30): cuánto se espera un pago REAL que MP ya reportó
#     como `pendiente`/`en_proceso` (transferencia, efectivo, revisión) antes de
#     expirarlo. Un aviso real merece margen: si el cron lo expira antes de la
#     aprobación, el plan no se activa solo.
# El Bazar conserva su ventana (`MINUTOS_BAZAR`, 30) porque reserva stock.
# ⚠️ El cron de producción (`render.yaml`, job `box-crossfit-expirar-pendientes`)
# corre cada HORA: con 5 min de umbral para el intento, el cierre efectivo ocurre
# dentro de la hora siguiente a vencer (hasta ~60 min); el guard en tiempo real no
# depende del cron. El botón Cancelar es el camino rápido.
MINUTOS_BAZAR = 30
MINUTOS_MEMBRESIA = 30
MINUTOS_GUARD_MEMBRESIA = 5
# Comentario que ve el admin cuando la expiración automática cierra la solicitud
# de un pago REAL (ya había un aviso de MP).
COMENTARIO_EXPIRADA = f"Expirada: pago online no completado en {MINUTOS_MEMBRESIA} min"
# Comentario para la intención `iniciado` que nunca tuvo aviso de MP (no la ve el
# admin; es trazabilidad interna).
COMENTARIO_EXPIRADA_INTENTO = (
    "Expirada: intento de pago no completado en "
    f"{MINUTOS_GUARD_MEMBRESIA} min"
)
# Comentario cuando es el PROPIO alumno el que cancela desde la app.
COMENTARIO_CANCELADO_ALUMNO = "Cancelado por el alumno antes de completar el pago"
# Estados desde los que un pago todavía se puede cancelar desde la app: si el
# webhook ya dijo `aprobado`, la plata existe y no se deshace desde acá.
# `iniciado` entra: el alumno puede volver a PagoResultado antes del primer
# webhook y cerrar el intento con el botón "Cancelar pago".
ESTADOS_PAGO_CANCELABLES = ("iniciado", "pendiente", "en_proceso")
# Estados de MP con los que la solicitud oculta se CIERRA en vez de abrirse: el
# alumno sí hizo algo real en la pasarela, pero no hay nada que cobrar ni que el
# admin deba aprobar. `reembolsado` sin aprobación previa también cae acá.
ESTADOS_WEBHOOK_QUE_CIERRAN = ("rechazado", "cancelado", "reembolsado")
# Mensaje del guard cuando ya hay un checkout online abierto sin webhook.
MENSAJE_PAGO_EN_CURSO = (
    "Ya tienes un pago en curso. Termínalo o espera "
    f"{MINUTOS_GUARD_MEMBRESIA} minutos antes de intentar otra vez."
)


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


# ── Guard de "solicitud en curso" (membresía) ────────────────────────────────
# Dos cosas distintas bloquean abrir OTRO checkout/solicitud para el mismo
# alumno: una solicitud `pending` (transferencia enviada u online ya avisada por
# MP) o un pago `iniciado` con menos de `MINUTOS_GUARD_MEMBRESIA` (checkout
# abierto sin ningún aviso todavía). El guard se libera por tiempo, sin depender
# de un cron; los 5 min son sólo para el intento `iniciado`, no para un pago real.
def iniciado_vigente(pago, *, ahora=None,
                     minutos: int = MINUTOS_GUARD_MEMBRESIA) -> bool:
    """¿Este pago `iniciado` todavía reserva el guard de intentos en curso?

    Puro (sin DB): un pago de membresía en `iniciado` con `created_at` dentro de
    la ventana de `minutos` (por defecto `MINUTOS_GUARD_MEMBRESIA`, 5). Un
    `created_at` NULL no reserva nada (se considera viejo): es preferible dejar
    pasar un intento a bloquear al alumno para siempre por una fila sin fecha.
    """
    if pago is None or pago.concepto != CONCEPTO_MEMBRESIA:
        return False
    if pago.estado != "iniciado" or pago.created_at is None:
        return False
    ahora = ahora or ahora_santiago()
    return pago.created_at > ahora - timedelta(minutes=minutos)


def _payment_intent_vigente(db: Session, *, tenant_id: int, alumno_id: int,
                            ahora=None,
                            minutos: int = MINUTOS_GUARD_MEMBRESIA):
    """Pago `iniciado` de membresía que todavía cuenta como intento en curso."""
    candidatos = db.query(Pago).filter(
        Pago.tenant_id == tenant_id,
        Pago.usuario_id == alumno_id,
        Pago.concepto == CONCEPTO_MEMBRESIA,
        Pago.estado == "iniciado",
    ).order_by(Pago.created_at.desc()).all()
    for pago in candidatos:
        if iniciado_vigente(pago, ahora=ahora, minutos=minutos):
            return pago
    return None


def bloqueo_solicitud_en_curso(db: Session, *, tenant_id: int,
                               alumno_id: int, ahora=None) -> Optional[str]:
    """Motivo por el que no se puede abrir otra solicitud/checkout, o `None`.

    Devuelve `"solicitud_pendiente"` (mensaje histórico) o `"pago_en_curso"`
    (hay un checkout online iniciado y fresco, sin webhook todavía). Lo usan el
    endpoint de transferencia y el de "Pagar con tarjeta": una sola regla para
    los dos caminos.
    """
    pendiente = db.query(SolicitudPlan.id).filter(
        SolicitudPlan.alumno_id == alumno_id,
        SolicitudPlan.tenant_id == tenant_id,
        SolicitudPlan.estado == "pending",
    ).first()
    if pendiente is not None:
        return "solicitud_pendiente"
    if _payment_intent_vigente(
            db, tenant_id=tenant_id, alumno_id=alumno_id,
            ahora=ahora) is not None:
        return "pago_en_curso"
    return None


def _cerrar_iniciados_vencidos(db: Session, *, tenant_id: int, alumno_id: int,
                               ahora=None,
                               minutos: int = MINUTOS_GUARD_MEMBRESIA) -> int:
    """Cierra los checkouts `iniciado` que ya pasaron el umbral (housekeeping).

    No hace falta para que el admin deje de verlos (nunca los vio): es para que
    un alumno que abandona cinco veces no acumule filas. Se ejecuta cuando el
    alumno vuelve a intentar; el cron de expiración también los levanta.
    """
    candidatos = db.query(Pago).filter(
        Pago.tenant_id == tenant_id,
        Pago.usuario_id == alumno_id,
        Pago.concepto == CONCEPTO_MEMBRESIA,
        Pago.estado == "iniciado",
    ).all()
    viejos = [pago.id for pago in candidatos
              if not iniciado_vigente(pago, ahora=ahora, minutos=minutos)]
    if not viejos:
        return 0

    db.execute(
        update(Pago)
        .where(Pago.id.in_(viejos))
        .where(Pago.estado == "iniciado")
        .values(estado="expirado")
    )
    db.execute(
        update(SolicitudPlan)
        .where(SolicitudPlan.pago_id.in_(viejos))
        .where(SolicitudPlan.estado == "iniciado")
        .values(estado="expirada", comentario_admin=COMENTARIO_EXPIRADA_INTENTO)
    )
    db.commit()
    return len(viejos)


def _datos_pagador(db: Session, usuario_id: int) -> tuple[str, str]:
    """Correo y RUT del alumno que paga; vacíos si la fila no existe.

    Se leen juntos porque los dos viajan a la preferencia de MP: el correo como
    `payer.email` y el RUT (si es válido) como `payer.identification`.
    """
    fila = db.query(Usuario.correo, Usuario.rut).filter(
        Usuario.id == usuario_id).first()
    if not fila:
        return "", ""
    return (fila.correo or ""), (fila.rut or "")


def _alertar_admins(db: Session, tenant_id: int, tipo: str, mensaje: str) -> None:
    """Aviso en la campana del box (best-effort: nunca tumba el cobro)."""
    try:
        notificar_admins_del_tenant(db, tenant_id, tipo, mensaje)
    except Exception as error:  # pragma: no cover - best-effort
        logger.warning("No se pudo avisar a los admins del box %s: %s",
                       tenant_id, error)


def _marcar_beneficio_usado(db: Session, alumno_id: int, beneficio_id: int,
                            precio_lista_clp: int) -> None:
    """Marca el beneficio como USADO al crear la solicitud online.

    Mismo efecto que `POST /solicitudes/solicitar`: si no se marcara, el descuento
    seguiría "vigente" y el alumno podría aplicarlo a una segunda compra. Es
    best-effort: la solicitud ya está guardada con su precio final.
    """
    try:
        beneficio = beneficios.vigente(
            db, alumno_id, tipo=beneficios.TIPO_DESCUENTO)
        if beneficio is not None and beneficio.id == beneficio_id:
            beneficios.usar(db, beneficio, precio_lista_clp=precio_lista_clp)
    except Exception as error:
        logger.warning("No se pudo marcar el beneficio #%s como usado: %s",
                       beneficio_id, error)


def _avisar_solicitud_online(db: Session, *, solicitud: SolicitudPlan,
                             nombre_plan: str) -> None:
    """Campana del admin: el PRIMER webhook real hizo visible la solicitud.

    No se manda al crear la preferencia (el alumno todavía no hizo nada en MP):
    se manda cuando `_promover_solicitud_webhook` la pasa de `iniciado` a
    `pending`. El admin no tiene un voucher que revisar, pero sí un cobro que
    vigilar.
    """
    try:
        alumno = db.query(Usuario).filter(
            Usuario.id == solicitud.alumno_id).first()
        nombre = alumno.nombre if alumno else f"Alumno #{solicitud.alumno_id}"
        notificar_admins_del_tenant(
            db, solicitud.tenant_id, "plan_solicitado",
            f"💳 Nueva solicitud de plan de {nombre}: {nombre_plan} "
            f"(solicitud #{solicitud.id}) — pago online")
    except Exception as error:  # pragma: no cover - best-effort
        logger.warning("No se pudo avisar la solicitud online %s: %s",
                       solicitud.id, error)


def _avisar_pedido_online(db: Session, *, tenant_id: int, alumno_id: int,
                          producto: str, cantidad: int) -> None:
    """Campana del admin: pedido nuevo del Bazar creado por checkout."""
    try:
        alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
        nombre = alumno.nombre if alumno else "Atleta"
        notificar_admins_del_tenant(
            db, tenant_id, "pedido_nuevo",
            f"Nuevo pedido de {nombre}: {producto} x{cantidad} — pago online")
    except Exception as error:  # pragma: no cover - best-effort
        logger.warning("No se pudo avisar el pedido online del alumno %s: %s",
                       alumno_id, error)



def crear_pago_membresia(db: Session, *, current_user: dict, plan_id: int,
                         certificado_estudiante_url: Optional[str] = None) -> dict:
    """Crea la solicitud OCULTA + el pago `iniciado` + la preferencia de MP.

    El clic en "Pagar con tarjeta" no puede ensuciar la cola del admin: hasta que
    Mercado Pago no avise algo REAL (webhook), el alumno no hizo nada en la
    pasarela. Por eso la solicitud nace `iniciado` y el pago también: la fila
    existe (el backend necesita `referencia_id` para el webhook) pero ninguna
    consulta de pendientes la trae. El primer aviso de MP la abre
    (`_promover_solicitud_webhook`) o la cierra si fue rechazada/cancelada.

    Valida lo mismo que el flujo manual (plan del box, sin otra solicitud en
    curso) y congela el precio con la aritmética existente: el descuento vigente
    (F2) se aplica acá y ese número es el que se cobra y el que después registra
    la transacción.
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

    # Housekeeping: los checkouts que ya pasaron los 5 min no bloquean ni se
    # acumulan (no hay cron dedicado para la intención invisible).
    _cerrar_iniciados_vencidos(db, tenant_id=tenant_id, alumno_id=alumno_id)

    # Una sola solicitud pendiente (flujo manual) y un solo checkout online EN
    # CURSO. Sin lo segundo, cinco clics abrirían cinco preferencias en paralelo
    # antes de que cualquiera genere webhook.
    motivo = bloqueo_solicitud_en_curso(
        db, tenant_id=tenant_id, alumno_id=alumno_id)
    if motivo == "solicitud_pendiente":
        raise ErrorPago("Ya tienes una solicitud pendiente", 400)
    if motivo == "pago_en_curso":
        raise ErrorPago(MENSAJE_PAGO_EN_CURSO, 400)

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

    # ── Fase 3b: el descuento del REFERIDO también entra en la preferencia ──
    # El monto que cobra Mercado Pago tiene que incluir el premio del programa de
    # referidos: antes se aplicaba al aprobar el webhook, o sea DESPUÉS de que MP
    # ya había cobrado el precio de lista. `previsualizar_compra` NO convierte el
    # referido ni consume el crédito (una preferencia abandonada no puede gastar
    # el premio); sólo fija el número. Sin apilar: si hay beneficio F2, el
    # referido espera.
    if lista > 0 and not descuento:
        premio = referidos.previsualizar_compra(
            db, tenant_id=tenant_id, usuario_id=alumno_id,
            precio_lista_clp=lista)
        if premio is not None and premio["descuento_clp"] > 0:
            descuento = {
                # `descuento_pct` es Integer en la solicitud: el % del programa
                # se guarda redondeado para mostrarlo; el monto exacto que manda
                # es `precio_final_clp`.
                "descuento_pct": int(round(premio["porcentaje"])),
                "precio_final_clp": premio["precio_final_clp"],
            }

    monto = mp.monto_clp(descuento.get("precio_final_clp") or lista)
    if monto <= 0:
        raise ErrorPago(
            "Este plan no tiene un precio cobrable online. Usa transferencia.",
            400)

    # ── Matrícula configurable (cobro ÚNICO del alumno nuevo) ──
    # Se cobra junto con el plan en la MISMA preferencia: MP recibe el total
    # (`pago.monto_clp`) y el webhook lo compara con ESE número. El snapshot queda
    # en la solicitud (no en el pago) porque es lo que después registra
    # `activar_plan` como ingreso separado de `categoria='matricula'`.
    matricula = matricula_service.monto_para_alumno(db, tenant_id, alumno_id)
    monto_total = monto + (matricula or 0)

    solicitud = SolicitudPlan(
        tenant_id=tenant_id,
        alumno_id=alumno_id,
        plan_id=plan.id,
        # OCULTA: la cola del admin sólo filtra `pending`, y esta fila pasa a
        # `pending` recién con el primer webhook real de MP.
        estado="iniciado",
        # Sin voucher: el cobro lo prueba Mercado Pago, no un archivo.
        voucher_url=None,
        certificado_estudiante_url=certificado_estudiante_url or None,
        precio_clp_snapshot=plan.precio_clp,
        # Precio final SIEMPRE congelado (aunque no haya descuento): así
        # `activar_plan` no aplica un descuento de referido que MP no cobró y la
        # `TransaccionFinanciera` coincide con el pago, peso por peso.
        # OJO: es el precio del PLAN; la matrícula va aparte (snapshot propio).
        precio_final_clp=monto,
        matricula_clp_snapshot=matricula,
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
        # Lo que cobra MP: plan + matrícula. El webhook compara el monto aprobado
        # de MP con `pago.monto_clp`, así que incluirla acá es lo que la cobra.
        monto_clp=monto_total,
        estado="iniciado",
        # UUID: el id secuencial de la fila no se filtra a un tercero.
        external_reference=str(uuid.uuid4()),
    )
    db.add(pago)
    db.flush()
    solicitud.pago_id = pago.id
    db.commit()

    # La preferencia se pide ANTES de consumir el beneficio: si MP no responde,
    # `_crear_preferencia` deshace la solicitud y el descuento del alumno sigue
    # vivo (no se pierde un beneficio por un checkout que nunca existió).
    resultado = _crear_preferencia(db, pago, titulo=f"Plan {plan.nombre}")

    # ── Efecto secundario del flujo manual, ahora para el pago online ──
    # El beneficio (F2) se marca usado al iniciar la compra: si no, el mismo
    # descuento se podría aplicar a otra compra. La campana del admin NO se
    # manda acá: se manda cuando el primer webhook hace visible la solicitud.
    if descuento.get("beneficio_id"):
        _marcar_beneficio_usado(db, alumno_id, descuento["beneficio_id"], lista)

    return resultado



def _crear_preferencia(db: Session, pago: Pago, *, titulo: str,
                       excluir_medios=()) -> dict:
    """Pide la preferencia a MP y guarda su `preference_id`.

    Si MP falla se DESHACE lo reservado (`_limpiar_cobro_fallido`): no hay
    checkout, así que no tiene sentido dejar la solicitud pendiente (que además le
    bloquearía enviar el voucher) ni el stock del Bazar tomado por 30 minutos. El
    alumno recibe un 503 con "usa transferencia", nunca un error genérico.
    """
    email, rut = _datos_pagador(db, pago.usuario_id)
    try:
        preference_id, init_point = mp.crear_preferencia(
            pago=pago,
            titulo=titulo,
            email=email,
            rut=rut,
            excluir_medios=excluir_medios,
        )
    except mp.ErrorMercadoPago as error:
        logger.warning("Pago %s: no se pudo crear la preferencia (%s)",
                       pago.id, error)
        _limpiar_cobro_fallido(db, pago)
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


def _limpiar_cobro_fallido(db: Session, pago: Pago) -> None:
    """Deshace la reserva de un pago que nunca llegó a tener checkout.

    Es el caso "MP no respondió al crear la preferencia": no existe `init_point`,
    así que nadie puede pagar. Sin esta limpieza el alumno quedaría con una
    solicitud `iniciado`/`pending` (y no podría ni mandar el voucher) o con el
    stock del Bazar reservado por un cobro imposible.

    Best-effort: si falla, el job de expiración lo cierra igual (5 min si era
    `iniciado`; 30 min si ya había un aviso real de MP).
    """
    try:
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
                    db, pedido, "No se pudo iniciar el pago online",
                    origen=pedidos_estado.ORIGEN_MERCADOPAGO)
        elif pago.concepto == CONCEPTO_MEMBRESIA:
            db.execute(
                update(SolicitudPlan)
                .where(SolicitudPlan.id == pago.referencia_id)
                .where(SolicitudPlan.estado.in_(("iniciado", "pending")))
                .values(estado="rejected",
                        comentario_admin="No se pudo iniciar el pago online")
            )
        db.execute(
            update(Pago)
            .where(Pago.id == pago.id)
            .where(Pago.estado.in_(("iniciado", "pendiente")))
            .values(estado="cancelado")
        )
        db.commit()
    except Exception as error:  # pragma: no cover - best-effort
        db.rollback()
        logger.warning("No se pudo limpiar el pago fallido %s: %s",
                       pago.id, error)



def crear_pago_bazar(db: Session, *, current_user: dict, producto_id: int,
                     cantidad: int, variante_id: Optional[int] = None) -> dict:
    """Crea el pedido (reservando stock) + el pago + la preferencia de MP.

    El pedido nace `pendiente` y el stock se descuenta ATÓMICAMENTE al crearlo,
    igual que en el flujo de transferencia: reservar stock recién al cobrar
    permitiría que dos alumnos paguen la última polera. Si el pago no llega en
    30 minutos, la expiración lo rechaza y el stock vuelve por el mismo camino
    ya probado (`rechazar_pedido`).

    Tallas (migración 083): si el producto tiene variantes, `variante_id` es
    obligatorio y lo que se reserva/descuenta es el stock de ESA talla. En un
    producto sin tallas `variante_id` se ignora, igual que en el pedido manual.
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

    variante = None
    if producto.tiene_variantes:
        if variante_id is None:
            raise ErrorPago("Debes elegir una talla", 400)
        variante = db.query(ProductoVariante).filter(
            ProductoVariante.id == variante_id,
            ProductoVariante.producto_id == producto.id,
        ).first()
        if variante is None or not variante.activo:
            raise ErrorPago("La talla elegida no está disponible", 400)
        if (variante.stock or 0) < cantidad:
            raise ErrorPago(
                f"Stock insuficiente. Disponible: {variante.stock}, "
                f"Solicitado: {cantidad}", 400)
    elif (producto.stock or 0) < cantidad:
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
        # Snapshot de la talla (083): el historial la muestra aunque la variante
        # se borre después (SET NULL en `variante_id`).
        variante_id=variante.id if variante is not None else None,
        talla=variante.talla if variante is not None else None,
        cantidad=cantidad,
        total=float(total),
        estado="pendiente",
        # Sin comprobante: el cobro lo prueba el webhook de MP.
        voucher_url=None,
        origen_pago=pedidos_estado.ORIGEN_MERCADOPAGO,
    )

    try:
        # Mismo UPDATE condicional que el POST manual: si dos compras piden el
        # último ítem, sólo una obtiene rowcount=1. Con tallas se aplica a la
        # fila de `producto_variantes` (nunca a `productos.stock`).
        if variante is not None:
            resultado = db.execute(
                update(ProductoVariante)
                .where(ProductoVariante.id == variante.id)
                .where(ProductoVariante.producto_id == producto.id)
                .where(ProductoVariante.stock >= cantidad)
                .values(stock=ProductoVariante.stock - cantidad)
            )
            disponible = variante.stock
        else:
            resultado = db.execute(
                update(Producto)
                .where(Producto.id == producto.id)
                .where(Producto.tenant_id == tenant_id)
                .where(Producto.stock >= cantidad)
                .values(stock=Producto.stock - cantidad)
            )
            disponible = producto.stock
        if resultado.rowcount == 0:
            raise ErrorPago(
                f"Stock insuficiente. Disponible: {disponible}, "
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

    # Campana del admin (mismo `tipo` que el pedido manual). NO se manda el correo
    # de "compra confirmada": el pedido todavía no está cobrado (nace pendiente).
    resultado = _crear_preferencia(
        db, pago, titulo=f"{producto.nombre} x{cantidad}",
        # `ticket` se acredita días después y el pedido ya habría vencido.
        excluir_medios=mp.MEDIOS_EXCLUIDOS_BAZAR)

    _avisar_pedido_online(db, tenant_id=tenant_id, alumno_id=alumno_id,
                          producto=producto.nombre, cantidad=cantidad)
    return resultado


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
                if solicitud is not None and solicitud.estado in ("rejected", "expirada"):
                    # El alumno pagó y la solicitud está rechazada o expirada:
                    # plata sin contraprestación. Un humano tiene que devolverla.
                    _alertar_admins(
                        db, pago.tenant_id, "pago_aprobado_solicitud_rechazada",
                        (f"⚠️ Se aprobó el pago #{pago.id} "
                         f"(${pago.monto_clp:,}) de una solicitud de plan que "
                         "estaba RECHAZADA o EXPIRADA. Devuelve el dinero o activa "
                         "el plan a mano."))
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


def _comentario_cierre_mp(detalle: dict) -> str:
    """Comentario corto para el historial cuando MP rechaza/cancela el cobro."""
    estado = mp.estado_desde_mp(detalle.get("status"))
    sufijo = str(detalle.get("status_detail") or "").strip()
    base = {
        "rechazado": "Mercado Pago rechazó el pago",
        "cancelado": "Cancelado en Mercado Pago",
        "reembolsado": "Reembolsado en Mercado Pago",
    }.get(estado, "Pago no completado en Mercado Pago")
    return (f"{base} ({sufijo})" if sufijo else base)[:500]


def _promover_solicitud_webhook(db: Session, pago: Pago,
                                detalle: dict) -> Optional[str]:
    """Abre o cierra la solicitud OCULTA con el PRIMER aviso real de MP.

    El clic en "Pagar con tarjeta" deja la solicitud en `iniciado` (invisible).
    Este es el único lugar que la hace visible:

      * aviso `aprobado`/`pendiente`/`en_proceso` ⇒ `iniciado` → `pending` (el
        admin la ve con el badge del estado REAL del pago);
      * aviso `rechazado`/`cancelado`/`reembolsado` ⇒ `iniciado` (o `pending`
        si antes hubo un aviso intermedio) → `rejected`: no hay nada que el
        admin deba aprobar y el alumno puede volver a intentar. Sin esto un
        rechazo dejaba la solicitud `pending` para siempre y el guard
        "ya tienes una solicitud pendiente" le impedía reintentar.

    Devuelve `"pending"` SÓLO cuando la fila recién se hizo visible (para
    mandar la campana del admin una única vez), `"rejected"` cuando la cerró, o
    `None` si no había nada que cambiar (p. ej. un webhook repetido).

    Un estado de MP desconocido no se toca: no se puede inventar visibilidad
    con un dato que no se entiende.
    """
    if pago.concepto != CONCEPTO_MEMBRESIA or not pago.referencia_id:
        return None

    estado = mp.estado_desde_mp(detalle.get("status"))
    if estado is None:
        return None

    if estado in ESTADOS_WEBHOOK_QUE_CIERRAN:
        cerrada = db.execute(
            update(SolicitudPlan)
            .where(SolicitudPlan.id == pago.referencia_id)
            .where(SolicitudPlan.tenant_id == pago.tenant_id)
            .where(SolicitudPlan.estado.in_(("iniciado", "pending")))
            .values(estado="rejected",
                    comentario_admin=_comentario_cierre_mp(detalle))
        )
        return "rejected" if cerrada.rowcount else None

    abierta = db.execute(
        update(SolicitudPlan)
        .where(SolicitudPlan.id == pago.referencia_id)
        .where(SolicitudPlan.tenant_id == pago.tenant_id)
        .where(SolicitudPlan.estado == "iniciado")
        .values(estado="pending")
    )
    return "pending" if abierta.rowcount else None


def procesar_notificacion(db: Session, evento: PagoEvento,
                          detalle: dict) -> str:
    """Aplica el pago real (ya releído de MP) y cierra el evento.

    Antes de aplicar el cobro se abre/cierra la solicitud oculta: el primer
    aviso REAL de Mercado Pago es lo que la hace visible para el admin (o la
    cierra si el medio fue rechazado). La campana del admin se manda DESPUÉS de
    aplicar, para no avisar de un pago que terminó en error.

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
    promocion = _promover_solicitud_webhook(db, pago, detalle)
    evento.resultado = aplicar_pago(db, pago, detalle)
    evento.procesado_en = ahora_santiago()
    db.commit()

    if promocion == "pending":
        # Best-effort: el aviso de campana no puede tumbar un pago ya aplicado.
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == pago.referencia_id).first()
        if solicitud is not None:
            plan = db.query(Plan.nombre).filter(
                Plan.id == solicitud.plan_id).first()
            _avisar_solicitud_online(
                db, solicitud=solicitud,
                nombre_plan=plan[0] if plan else "tu plan")

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


def cancelar_pago(db: Session, pago: Pago, *,
                  comentario: str = COMENTARIO_CANCELADO_ALUMNO) -> dict:
    """Cierra un checkout ABANDONADO por el propio alumno (o el admin).

    El caso que resuelve: el alumno tocó "Pagar con tarjeta", el backend creó la
    solicitud `iniciado` + el pago `iniciado`, y volvió a la app SIN meter los
    datos de la tarjeta. Mercado Pago no generó ningún pago, así que no hay
    webhook que rechace nada y hay que cerrarlo desde acá: la solicitud está
    oculta (el admin no la ve), pero el guard de "pago en curso" le impide
    generar otra durante 5 minutos.

    Reglas:

    * **CAS (`UPDATE ... WHERE estado IN (iniciado, pendiente, en_proceso)`)**: si
      el webhook aprobó el pago mientras el alumno volvía a la app, el UPDATE no
      toca ninguna fila y se lanza `ErrorPago` (409). Un cobro confirmado NO se
      cancela desde acá: se devuelve con un reembolso en Mercado Pago.
    * **Membresía** → la `SolicitudPlan` asociada pasa a `rejected` (el MISMO
      valor que usa el rechazo por webhook, ver `_limpiar_cobro_fallido`) y sólo
      si seguía `iniciado`/`pending`: un admin pudo haberla aprobado en paralelo.
    * **Bazar** → el pedido se rechaza por el camino ya probado
      (`pedidos_estado.rechazar_pedido`), que devuelve el stock reservado.

    Un medio que se acredita DESPUÉS (efectivo/ticket) puede confirmarse cuando
    el pago ya está `cancelado`: lo aplica `aplicar_pago` igual y avisa a los
    admins porque la solicitud quedó `rejected` (ver `_aplicar_beneficio`). Es
    el mismo camino que un pago aprobado sobre una solicitud expirada.

    Es seguro ante reintentos: la segunda cancelación simultánea responde 409
    porque el pago ya no está abierto.
    """
    cerrado = db.execute(
        update(Pago)
        .where(Pago.id == pago.id)
        .where(Pago.tenant_id == pago.tenant_id)
        .where(Pago.estado.in_(ESTADOS_PAGO_CANCELABLES))
        .values(estado="cancelado")
    )
    if cerrado.rowcount == 0:
        # El webhook (o la expiración) ya movió el pago: no hay nada que
        # cancelar y lo cobrado, si existe, se devuelve por fuera de la app.
        db.rollback()
        raise ErrorPago(
            "Este pago ya no se puede cancelar: Mercado Pago lo confirmó o "
            "el cobro ya venció. Revisa tu plan o tus pedidos.", 409)

    if pago.concepto == CONCEPTO_MEMBRESIA:
        db.execute(
            update(SolicitudPlan)
            .where(SolicitudPlan.id == pago.referencia_id)
            .where(SolicitudPlan.tenant_id == pago.tenant_id)
            .where(SolicitudPlan.estado.in_(("iniciado", "pending")))
            .values(estado="rejected", comentario_admin=comentario)
        )
    elif pago.concepto == CONCEPTO_BAZAR:
        pedido = (
            db.query(Pedido)
            .filter(Pedido.id == pago.referencia_id,
                    Pedido.tenant_id == pago.tenant_id)
            .with_for_update()
            .first()
        )
        if pedido is not None and pedido.estado == "pendiente":
            pedidos_estado.rechazar_pedido(
                db, pedido, comentario,
                origen=pedidos_estado.ORIGEN_MERCADOPAGO)
    db.commit()
    # El UPDATE se hizo por SQL: hay que refrescar el ORM para no seguir
    # leyendo el estado viejo en memoria (mismo criterio que `aplicar_pago`).
    db.expire(pago)
    return {"estado": "cancelado"}


def pago_vencido(pago, *, ahora, minutos_bazar: int = MINUTOS_BAZAR,
                 minutos_membresia: int = MINUTOS_MEMBRESIA,
                 minutos_intento: int = MINUTOS_GUARD_MEMBRESIA) -> bool:
    """True si un pago abierto superó el umbral de expiración de su concepto.

    Puro (sin DB): decide por `created_at` contra `ahora`. `None` (fila sin
    fecha) y los conceptos sin expiración definida (emergencia, futuro) nunca
    vencen. `<=` hace que el pago venza JUSTO en el límite (no un minuto después).

    **Dos umbrales de membresía** (no se igualan):
      * `iniciado`: `minutos_intento` (5). No hay ningún aviso de MP.
      * `pendiente`/`en_proceso`: `minutos_membresia` (30). Hay un aviso real y
        se le da margen para completarlo; si se expira antes de la aprobación,
        el plan no se activa solo.
      * Bazar: `minutos_bazar` (30), porque reserva stock.
    """
    if pago.created_at is None:
        return False
    if pago.concepto == CONCEPTO_BAZAR:
        return pago.created_at <= ahora - timedelta(minutes=minutos_bazar)
    if pago.concepto == CONCEPTO_MEMBRESIA:
        minutos = (minutos_intento if pago.estado == "iniciado"
                   else minutos_membresia)
        return pago.created_at <= ahora - timedelta(minutes=minutos)
    return False


def expirar_pendientes(db: Session, *, minutos_bazar: int = MINUTOS_BAZAR,
                       minutos_membresia: int = MINUTOS_MEMBRESIA,
                       minutos_intento: int = MINUTOS_GUARD_MEMBRESIA) -> dict:
    """Cierra los pagos que nunca se cobraron y libera lo que reservaban.

    * **Bazar (30 min)**: el stock vuelve por `rechazar_pedido` (el mismo camino
      del rechazo manual). Un pedido `pendiente` con la plata sin llegar es un
      producto bloqueado que otro alumno no puede comprar.
    * **Membresía con aviso real (30 min)**: la solicitud pasa a `expirada` con
      `comentario_admin=COMENTARIO_EXPIRADA` para que salga de la cola de
      pendientes del admin (no se crea basura que nadie va a aprobar). ⚠️ NO se
      notifica al alumno al expirar (mejora futura: avisar en su campana para
      que pueda volver a intentar el pago).
    * **Membresía `iniciado` (5 min)**: el alumno nunca hizo nada en MP; la
      solicitud nunca fue visible. Se cierra igual como `expirada` para no
      acumular filas; NO es lo que mantiene limpia la cola del admin (esa fila
      jamás entró).

    Un pago aprobado DESPUÉS de esto no revive nada: lo detecta `aplicar_pago`
    y avisa a los admins (ver `_aplicar_beneficio`). Eso incluye un medio
    `ticket` (efectivo), que se acredita días después: la membresía NO excluye
    ese medio en la preferencia (el Bazar sí, `mp.MEDIOS_EXCLUIDOS_BAZAR`), así
    que si esos casos empiezan a aparecer, la salida es excluirlo igual.

    Lo llama `maintenance/reconciliar_pagos.py` y el cron
    `maintenance/expirar_pendientes.py`; es idempotente.
    """
    ahora = ahora_santiago()
    abiertos = db.query(Pago).filter(
        Pago.estado.in_(("iniciado", "pendiente", "en_proceso"))).all()

    contadores = {"expirados": 0, "pedidos_rechazados": 0,
                  "solicitudes_expiradas": 0}
    for pago in abiertos:
        if not pago_vencido(pago, ahora=ahora, minutos_bazar=minutos_bazar,
                            minutos_membresia=minutos_membresia,
                            minutos_intento=minutos_intento):
            continue

        estado_anterior = pago.estado
        # CAS: si el webhook lo aprobó mientras recorríamos la lista, no se toca.
        cerrado = db.execute(
            update(Pago)
            .where(Pago.id == pago.id)
            .where(Pago.estado.in_(("iniciado", "pendiente", "en_proceso")))
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
            comentario = (COMENTARIO_EXPIRADA_INTENTO
                          if estado_anterior == "iniciado"
                          else COMENTARIO_EXPIRADA)
            cambiadas = db.execute(
                update(SolicitudPlan)
                .where(SolicitudPlan.id == pago.referencia_id)
                .where(SolicitudPlan.estado.in_(("iniciado", "pending")))
                .values(estado="expirada",
                        comentario_admin=comentario)
            )
            if cambiadas.rowcount:
                contadores["solicitudes_expiradas"] += 1
            db.commit()

    return contadores
