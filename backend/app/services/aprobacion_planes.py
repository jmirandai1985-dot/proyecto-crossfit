"""
Aprobación de una solicitud de plan: UNA sola función para los dos caminos.

Antes esta lógica vivía dentro de `PUT /solicitudes/{id}/aprobar`. Con Mercado
Pago hay dos formas de que una solicitud quede aprobada (el admin con el
comprobante, o el webhook con el pago `approved`) y **no puede haber dos
verdades**: si cada camino creara su propia suscripción, un pago online podría
terminar con el plan duplicado o con dos ingresos en `transacciones_financieras`.

Qué hace `activar_plan` (en este orden, que importa):

1. `UPDATE ... WHERE estado='pending'` — candado atómico: de dos aprobaciones
   simultáneas (dos admins, o admin + webhook) sólo una obtiene `rowcount=1`.
   El check "leí y estaba pendiente" NO era seguro bajo MVCC.
2. Crea la `Suscripcion` activa (vigencia en hora de Chile, créditos de la regla
   compartida) y la notificación del alumno.
3. Expira las suscripciones activas del plan "Prueba" (upgrade).
4. Convierte el referido pendiente (F3b) — salvo que la compra traiga ya un
   descuento de fidelización; si el precio venía congelado (Mercado Pago o el
   monto de la transferencia), el descuento se mide contra lo cobrado.
5. Registra la `TransaccionFinanciera` (una sola vez), la auditoría y el correo.

`actor_id=None` es un valor VÁLIDO: significa "lo aprobó la pasarela".
`solicitudes_planes.aprobado_por` y `auditoria.usuario_id` son nullable, así que
una aprobación automática se distingue de una humana sin inventar un usuario
"sistema". `origen` queda en `origen_pago` y en el detalle de auditoría.
"""
import logging
from typing import Optional

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.models.notificacion import Notificacion
from app.models.pago import Pago
from app.models.plan import Plan
from app.models.solicitud_plan import SolicitudPlan
from app.models.suscripcion import Suscripcion
from app.models.transaccion_financiera import TransaccionFinanciera
from app.models.usuario import Usuario
from app.core.urls import url_frontend
from app.core.estados import vigente_hoy
from app.services import beneficios_service as beneficios  # noqa: F401
from app.services import churn_service
from app.services import referidos_service as referidos
from app.services.auditoria_service import registrar_auditoria
from app.utils.planes import creditos_de_plan
from app.utils.santiago import ahora_santiago, fin_de_plan_chile, hoy_santiago

logger = logging.getLogger(__name__)

ORIGEN_MANUAL = "manual"
ORIGEN_MERCADOPAGO = "mercadopago"


class SolicitudNoProcesable(Exception):
    """La solicitud no existe (en ese box) o ya fue aprobada/rechazada.

    El endpoint la traduce a 404 / 400 con los mensajes de siempre; el webhook
    la trata como "duplicado" y no hace nada más.
    """

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


class PlanNoEncontrado(Exception):
    """La solicitud apunta a un plan que ya no existe (404 en el endpoint)."""


class PagoOnlineNoConfirmado(Exception):
    """La solicitud es de pago online pero su cobro todavía no está confirmado.

    El admin no puede aprobarla a mano: la aprobación de una solicitud online la
    hace el webhook cuando Mercado Pago deja `pagos.estado='aprobado'`. Se traduce
    a 409 (el pago online no está confirmado).
    """

    def __init__(self, solicitud_id: int):
        super().__init__(str(solicitud_id))
        self.solicitud_id = solicitud_id


def precio_lista(solicitud, plan) -> int:
    """Precio de LISTA de la compra: el snapshot (P0-4) o el precio del plan.

    Es la base sobre la que se calcula cualquier descuento. Nunca el precio
    final: un % aplicado sobre otro % sería un descuento inventado.
    """
    valor = (solicitud.precio_clp_snapshot
             if solicitud.precio_clp_snapshot is not None
             else (plan.precio_clp if plan is not None else 0))
    return int(valor or 0)


def _validar_aprobacion_manual(db: Session, solicitud_id: int,
                               tenant_id: Optional[int]) -> None:
    """Bloquea aprobar a mano una solicitud online cuyo pago no está confirmado.

    `origen_pago='mercadopago'` es la INTENCIÓN de pagar (se setea al crear la
    preferencia), no la confirmación: si el alumno abandonó el checkout, la
    solicitud sigue en Pendientes y un admin podría aprobarla creyendo que está
    pagada. La única aprobación válida de una solicitud online es la del webhook
    (con `pagos.estado='aprobado'`). Acá se permite además el caso límite en que
    el pago YA quedó aprobado pero la activación falló y el admin la remata a mano.
    """
    consulta = db.query(SolicitudPlan).filter(SolicitudPlan.id == solicitud_id)
    if tenant_id is not None:
        consulta = consulta.filter(SolicitudPlan.tenant_id == tenant_id)
    solicitud = consulta.first()
    if solicitud is None:
        raise SolicitudNoProcesable("no_encontrada")
    if solicitud.origen_pago != ORIGEN_MERCADOPAGO:
        return
    pago = None
    if solicitud.pago_id is not None:
        pago = db.query(Pago).filter(Pago.id == solicitud.pago_id).first()
    if pago is None or pago.estado != "aprobado":
        raise PagoOnlineNoConfirmado(solicitud_id)


def _plan_vigente_usable(db: Session, tenant_id: int,
                         usuario_id: int) -> Optional[Suscripcion]:
    """La membresía que HOY está \"corriendo\" (fecha + créditos), o `None`.

    Regla de vencimiento normal (la MISMA del sistema): un plan se termina por lo
    que ocurra PRIMERO —su fecha de vencimiento O que se agoten sus créditos—. Por
    eso \"usable\" = `estado='activo'` + vigente por día chileno + (ilimitado /
    `creditos_disponibles IS NULL`, o `creditos_disponibles > 0`). Si hay más de
    una, gana la que vence más tarde (mismo criterio que
    `plan_vencimiento.suscripcion_vigente`).

    Sólo cuentan los planes PAGADOS (`Plan.precio_clp > 0`): el plan \"Prueba\" del
    alta (gratis, 1 crédito/7 días) y el \"Pase de regreso\" de Fidelización
    (también gratis) NO deben mandar a cola la PRIMERA compra real de un alumno —
    esa compra se activa ya y expira el plan de prueba (el flujo de upgrade de
    siempre).
    """
    return (db.query(Suscripcion)
            .join(Plan, Plan.id == Suscripcion.plan_id)
            .filter(
                Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == usuario_id,
                Suscripcion.estado == "activo",
                Plan.precio_clp > 0,
                vigente_hoy(Suscripcion.fecha_expiracion),
                or_(Suscripcion.creditos_disponibles.is_(None),
                    Suscripcion.creditos_disponibles > 0),
            )
            .order_by(Suscripcion.fecha_expiracion.desc(),
                      Suscripcion.id.desc())
            .first())


def activar_plan(db: Session, solicitud_id: int, *, tenant_id: Optional[int] = None,
                 actor_id: Optional[int] = None,
                 origen: str = ORIGEN_MANUAL,
                 background_tasks=None,
                 pago_id: Optional[int] = None) -> dict:
    """Aprueba la solicitud y activa el plan. Idempotente por el UPDATE condicional.

    `tenant_id` es el filtro de seguridad del endpoint del admin (un admin del
    box A no puede aprobar una solicitud del box B, y se responde 404 para no
    revelar que el id existe). El webhook NO lo pasa: la solicitud se localiza
    por el pago, que ya está atado a un tenant.

    Devuelve el mismo dict que respondía el endpoint (status, message y el
    desglose del cobro), para que el wrapper no cambie el contrato.
    """
    if origen == ORIGEN_MANUAL:
        _validar_aprobacion_manual(db, solicitud_id, tenant_id)

    # ── Decidir ANTES del UPDATE atómico: ¿se activa ya o queda EN COLA? ──
    # Un plan nuevo NO se activa de inmediato si el alumno todavía tiene una
    # membresía "corriendo" (fecha + créditos): se marca en cola y se activa solo
    # cuando la actual termine (por fecha o por créditos, la regla de siempre).
    # El UPDATE atómico (`WHERE estado='pending'`) sigue siendo el candado contra
    # la doble aprobación.
    solicitud_previa = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id)
    if tenant_id is not None:
        solicitud_previa = solicitud_previa.filter(
            SolicitudPlan.tenant_id == tenant_id)
    solicitud_previa = solicitud_previa.first()
    if solicitud_previa is None:
        raise SolicitudNoProcesable("no_encontrada")

    plan = db.query(Plan).filter(
        Plan.id == solicitud_previa.plan_id).first()
    if not plan:
        raise PlanNoEncontrado(solicitud_id)

    en_cola = (_plan_vigente_usable(
        db, solicitud_previa.tenant_id, solicitud_previa.alumno_id) is not None)
    if en_cola:
        # Un alumno no puede tener MÁS de un plan en cola a la vez.
        ya_en_cola = db.query(SolicitudPlan).filter(
            SolicitudPlan.tenant_id == solicitud_previa.tenant_id,
            SolicitudPlan.alumno_id == solicitud_previa.alumno_id,
            SolicitudPlan.estado == "en_cola",
            SolicitudPlan.id != solicitud_id,
        ).first()
        if ya_en_cola is not None:
            raise SolicitudNoProcesable("ya_en_cola")

    valores = {
        "estado": "en_cola" if en_cola else "approved",
        "aprobado_por": actor_id,
        # Lo que el admin ve en el historial: distingue una aprobación humana de
        # un cobro online (que no tiene comprobante que revisar).
        "comentario_admin": ("Pagado online" if origen == ORIGEN_MERCADOPAGO
                             else "Aprobado"),
        "origen_pago": origen,
    }
    if pago_id is not None:
        valores["pago_id"] = pago_id

    consulta = (
        update(SolicitudPlan)
        .where(SolicitudPlan.id == solicitud_id)
        .where(SolicitudPlan.estado == "pending")
    )
    if tenant_id is not None:
        consulta = consulta.where(SolicitudPlan.tenant_id == tenant_id)
    resultado = db.execute(consulta.values(**valores))

    if resultado.rowcount == 0:
        # Distinguir "no existe / otro tenant" de "ya procesada".
        busqueda = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == solicitud_id)
        if tenant_id is not None:
            busqueda = busqueda.filter(SolicitudPlan.tenant_id == tenant_id)
        existente = busqueda.first()
        raise SolicitudNoProcesable(
            "ya_procesada" if existente else "no_encontrada")

    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()

    ahora = ahora_santiago()

    # ── Rama EN COLA: pago confirmado, plan SIN activar todavía ──
    if en_cola:
        return _registrar_plan_en_cola(
            db, solicitud, plan, ahora, actor_id, origen, background_tasks)

    # ── Crear la suscripción activa ──

    # ── Vigencia del plan EN HORA DE CHILE: `inicio + plan.duracion_dias` días
    # SEGUIDOS (regla 2026-10-06), hasta el fin de ese último día. UNA
    # definición: `fin_de_plan_chile()` (app/utils/santiago.py), compartida con
    # la compra de emergencia, `fix_fechas` y POST /suscripciones.
    expiracion = fin_de_plan_chile(ahora, plan.duracion_dias)

    suscripcion = Suscripcion(
        tenant_id=solicitud.tenant_id,
        usuario_id=solicitud.alumno_id,
        plan_id=solicitud.plan_id,
        estado="activo",
        # Los créditos los define UNA regla compartida
        # (`app/utils/planes.creditos_de_plan`): un plan ilimitado queda SIN
        # créditos (`NULL` = "∞" en el front) y un plan con cupo guarda sus clases.
        creditos_totales=creditos_de_plan(plan),
        creditos_disponibles=creditos_de_plan(plan),
        fecha_inicio=ahora,
        fecha_expiracion=expiracion,
    )
    if pago_id is not None:
        suscripcion.pago_id = pago_id
    db.add(suscripcion)

    # Crear notificación de aprobado
    db.add(Notificacion(
        alumno_id=solicitud.alumno_id,
        tipo="aprobado",
        mensaje=f"✅ Tu plan {plan.nombre} ha sido aprobado y ya está ACTIVO",
        leida=False,
    ))

    # ── FIX 3: desbloqueo de acceso completo tras pagar ──
    # Si el alumno aún tiene una suscripción ACTIVA del plan 'Prueba', se
    # expira (estado='vencido') para que es_prueba pase a false. NO se borra el
    # historial: el enum sólo admite pendiente/activo/vencido/rechazado.
    sus_prueba = db.query(Suscripcion).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.usuario_id == solicitud.alumno_id,
        Suscripcion.estado == "activo",
        Plan.nombre == "Prueba",
    ).all()
    for sp in sus_prueba:
        sp.estado = "vencido"
        logger.info(
            "Suscripcion Prueba #%s del alumno %s expirada por upgrade a plan pago",
            sp.id, solicitud.alumno_id)

    # ── Fase 3b: el referido se resuelve al CONFIRMAR la compra ──
    # Si la solicitud YA trae un descuento de fidelización (`beneficio_id`) no se
    # toca nada: no se apilan descuentos y el referido queda pendiente.
    # El precio final puede venir YA CONGELADO (lo fijó la preferencia de Mercado
    # Pago, o es el monto que el alumno vio al transferir): la compra igual
    # CONVIERTE el referido —el invitador gana su crédito— pero el descuento se
    # mide contra ese monto y no contra un `%` recalculado con la configuración de
    # hoy. Antes esta rama se saltaba con cualquier `precio_final_clp`, así que un
    # pago online nunca convertía el referido.
    descuento_referido = None
    if solicitud.beneficio_id is None:
        db.flush()  # asigna el id de la suscripción sin commitear
        descuento_referido = referidos.confirmar_compra(
            db,
            tenant_id=solicitud.tenant_id,
            usuario_id=solicitud.alumno_id,
            precio_lista_clp=precio_lista(solicitud, plan),
            suscripcion_id=suscripcion.id,
            ahora=ahora,
            precio_final_clp=solicitud.precio_final_clp,
        )
        if (descuento_referido is not None
                and solicitud.precio_final_clp is None
                and descuento_referido["descuento_clp"] > 0):
            solicitud.precio_final_clp = descuento_referido["precio_final_clp"]

    db.commit()



    # ── Churn del alumno: al aprobar un plan cambia su situación ──
    churn_service.programar_recalculo(
        background_tasks, solicitud.tenant_id, solicitud.alumno_id)

    # Precio que se cobra: el FINAL con descuento (fidelización, referido o el
    # monto que confirmó la pasarela) o el de lista. Se calcula UNA vez y lo usan
    # el ingreso y la respuesta del endpoint.
    lista = precio_lista(solicitud, plan)
    cobrado = (solicitud.precio_final_clp
               if solicitud.precio_final_clp is not None
               else lista)

    # ── FIX 4: registrar la transacción financiera del pago aprobado ──
    # Mismo formato que POST /suscripciones para mantener consistencia. No debe
    # impedir la aprobación si falla. El monto es el PRECIO VIGENTE AL SOLICITAR
    # (snapshot P0-4), no el precio del plan al momento de aprobar: si el admin
    # lo cambia entre medio, el ingreso no puede quedar por el precio nuevo.
    try:
        db.add(TransaccionFinanciera(
            tenant_id=suscripcion.tenant_id,
            tipo="ingreso",
            categoria="membresia",
            monto=cobrado,
            descripcion=(
                f"Suscripcion plan {plan.nombre} (usuario #{solicitud.alumno_id})"
            ),
            referencia_tipo="suscripcion",
            referencia_id=suscripcion.id,
            fecha=hoy_santiago(),
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"No se pudo registrar transaccion financiera: {e}")

    # ── Auditoría interna: quién, cuándo, qué ──
    # `usuario_id=None` = lo hizo la pasarela (no hay humano que auditar).
    registrar_auditoria(
        db,
        tenant_id=solicitud.tenant_id,
        usuario_id=actor_id,
        accion="UPDATE" if origen == ORIGEN_MANUAL else "PAGO_APROBADO",
        entidad="solicitud_plan",
        entidad_id=solicitud.id,
        detalle={
            "estado": "approved",
            "alumno_id": solicitud.alumno_id,
            "plan_id": solicitud.plan_id,
            "voucher_url": solicitud.voucher_url,
            "origen": origen,
            "pago_id": pago_id,
            "monto_clp": cobrado,
        },
    )



    # ── Correo al alumno: confirmación del plan aprobado (no bloqueante) ──
    # Primera vez vs renovación (mismo criterio que activar_alumno).
    try:
        alumno_obj = db.query(Usuario).filter(
            Usuario.id == solicitud.alumno_id).first()
        if alumno_obj and alumno_obj.correo:
            from app.services.email_service import (
                send_confirmacion_plan, send_confirmacion_renovacion_plan,
                formatear_fecha_es)
            # Renovación si existía ≥1 suscripción previa (sin contar la nueva).
            es_renovacion = db.query(Suscripcion).filter(
                Suscripcion.usuario_id == solicitud.alumno_id,
                Suscripcion.tenant_id == solicitud.tenant_id,
                Suscripcion.id != suscripcion.id,
            ).count() > 0
            fecha_vigencia = (formatear_fecha_es(suscripcion.fecha_expiracion)
                              if suscripcion.fecha_expiracion else "")
            link_app = url_frontend("/alumno/dashboard")
            cant = plan.creditos if plan and plan.creditos else 0
            if es_renovacion:
                send_confirmacion_renovacion_plan(
                    alumno_obj.nombre, alumno_obj.correo, plan.nombre,
                    cant, fecha_vigencia, link_app, alumno_obj.id)
            else:
                send_confirmacion_plan(
                    alumno_obj.nombre, alumno_obj.correo, plan.nombre,
                    cant, fecha_vigencia, link_app, alumno_obj.id)
    except Exception as e:
        logger.warning(f"No se pudo enviar correo de confirmación de plan: {e}")

    return {
        "status": "approved",
        "message": "Plan activado exitosamente",
        # Fase 3b: el desglose real del cobro (auditable desde la respuesta).
        "precio_lista_clp": lista,
        "precio_final_clp": cobrado,
        "descuento_aplicado_clp": lista - cobrado,
        "descuento_referido_origen": (descuento_referido["origen"]
                                      if descuento_referido else None),
        "descuento_referido_pct": (descuento_referido["porcentaje"]
                                   if descuento_referido else None),
    }


def _registrar_plan_en_cola(db: Session, solicitud, plan, ahora, actor_id,
                            origen, background_tasks) -> dict:
    """Registra la compra de un plan que queda EN COLA (sin activar aún).

    El dinero YA entró (se cobró), así que acá se resuelve el referido y se
    registra la transacción financiera y la auditoría; lo que NO se crea es la
    `Suscripcion` activa: se activa sola cuando el plan actual termine (ver
    `activar_planes_en_cola`).
    """
    db.add(Notificacion(
        alumno_id=solicitud.alumno_id,
        tipo="aprobado",
        mensaje=(f"✅ Tu plan {plan.nombre} está pagado y quedó EN COLA: "
                 "se activa automáticamente cuando termine tu plan actual."),
        leida=False,
    ))

    # Fase 3b: el referido se resuelve al CONFIRMAR la compra (el dinero ya entró),
    # aunque la suscripción se cree después. `suscripcion_id=None` porque todavía
    # no hay suscripción que vincular (`creditos_referido.suscripcion_id` es
    # NULL-able).
    descuento_referido = None
    if solicitud.beneficio_id is None:
        descuento_referido = referidos.confirmar_compra(
            db,
            tenant_id=solicitud.tenant_id,
            usuario_id=solicitud.alumno_id,
            precio_lista_clp=precio_lista(solicitud, plan),
            suscripcion_id=None,
            ahora=ahora,
            precio_final_clp=solicitud.precio_final_clp,
        )
        if (descuento_referido is not None
                and solicitud.precio_final_clp is None
                and descuento_referido["descuento_clp"] > 0):
            solicitud.precio_final_clp = descuento_referido["precio_final_clp"]

    db.commit()

    # ── Churn: pagar un plan (aunque quede en cola) cambia la situación ──
    churn_service.programar_recalculo(
        background_tasks, solicitud.tenant_id, solicitud.alumno_id)

    lista = precio_lista(solicitud, plan)
    cobrado = (solicitud.precio_final_clp
               if solicitud.precio_final_clp is not None else lista)

    # ── Ingreso YA (plata cobrada), con referencia a la SOLICITUD ──
    try:
        db.add(TransaccionFinanciera(
            tenant_id=solicitud.tenant_id,
            tipo="ingreso",
            categoria="membresia",
            monto=cobrado,
            descripcion=(
                f"Suscripcion plan {plan.nombre} (usuario #{solicitud.alumno_id})"),
            referencia_tipo="solicitud_plan",
            referencia_id=solicitud.id,
            fecha=hoy_santiago(),
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"No se pudo registrar transaccion financiera: {e}")

    registrar_auditoria(
        db,
        tenant_id=solicitud.tenant_id,
        usuario_id=actor_id,
        accion="UPDATE" if origen == ORIGEN_MANUAL else "PAGO_APROBADO",
        entidad="solicitud_plan",
        entidad_id=solicitud.id,
        detalle={
            "estado": "en_cola",
            "alumno_id": solicitud.alumno_id,
            "plan_id": solicitud.plan_id,
            "origen": origen,
            "pago_id": solicitud.pago_id,
            "monto_clp": cobrado,
        },
    )

    # ── Correo al alumno: su plan quedó EN COLA (no bloqueante) ──
    # Mismo patrón que la confirmación de plan aprobado: en TEST/noop queda
    # registrado como `simulado`; en PROD sale por SMTP.
    try:
        alumno_obj = db.query(Usuario).filter(
            Usuario.id == solicitud.alumno_id).first()
        if alumno_obj and alumno_obj.correo:
            from app.services.email_service import send_confirmacion_plan_en_cola
            send_confirmacion_plan_en_cola(
                alumno_obj.nombre, alumno_obj.correo, plan.nombre,
                url_frontend("/alumno/dashboard"), alumno_obj.id)
    except Exception as e:
        logger.warning(f"No se pudo enviar correo de plan en cola: {e}")

    return {
        "status": "approved",
        "message": "Plan pagado: quedó en cola y se activará automáticamente.",
        "estado": "en_cola",
        "precio_lista_clp": lista,
        "precio_final_clp": cobrado,
        "descuento_aplicado_clp": lista - cobrado,
        "descuento_referido_origen": (descuento_referido["origen"]
                                      if descuento_referido else None),
        "descuento_referido_pct": (descuento_referido["porcentaje"]
                                   if descuento_referido else None),
    }



def activar_planes_en_cola(db: Session) -> list[int]:
    """Activa las solicitudes EN COLA cuyo plan actual ya NO es usable.

    Se llama desde el job diario (después de `marcar_plan_vencido`): un plan en
    cola se activa cuando el plan actual termina por lo que ocurra PRIMERO —su
    fecha de vencimiento O que se agoten sus créditos—, que es exactamente la
    condición que evalúa `_plan_vigente_usable`. Sin admin: la activación es
    automática y arranca sus propios 30 días.

    NO commitea (el llamador —job o test— decide la transacción).
    Devuelve los ids de las suscripciones creadas.
    """
    pendientes = db.query(SolicitudPlan).filter(
        SolicitudPlan.estado == "en_cola").all()

    creadas: list[int] = []
    for solicitud in pendientes:
        if _plan_vigente_usable(
                db, solicitud.tenant_id, solicitud.alumno_id) is not None:
            continue

        plan = db.query(Plan).filter(Plan.id == solicitud.plan_id).first()
        if plan is None:
            logger.warning(
                "Solicitud en cola #%s con plan #%s inexistente: se omite",
                solicitud.id, solicitud.plan_id)
            continue

        ahora = ahora_santiago()
        suscripcion = Suscripcion(
            tenant_id=solicitud.tenant_id,
            usuario_id=solicitud.alumno_id,
            plan_id=solicitud.plan_id,
            estado="activo",
            creditos_totales=creditos_de_plan(plan),
            creditos_disponibles=creditos_de_plan(plan),
            fecha_inicio=ahora,
            fecha_expiracion=fin_de_plan_chile(ahora, plan.duracion_dias),
        )
        if solicitud.pago_id is not None:
            suscripcion.pago_id = solicitud.pago_id
        db.add(suscripcion)
        db.flush()  # asigna el id para la notificación sin commitear

        solicitud.estado = "approved"

        db.add(Notificacion(
            alumno_id=solicitud.alumno_id,
            tipo="aprobado",
            mensaje=(f"✅ Tu plan {plan.nombre} quedó ACTIVO automáticamente: "
                     "empieza hoy."),
            leida=False,
        ))

        creadas.append(suscripcion.id)
        logger.info(
            "Plan en cola activado: solicitud #%s → suscripción #%s (usuario %s)",
            solicitud.id, suscripcion.id, solicitud.alumno_id)

    return creadas

