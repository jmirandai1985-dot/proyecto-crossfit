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
4. Convierte el referido pendiente (F3b) — sólo si la compra no traía ya un
   descuento o un precio final congelado.
5. Registra la `TransaccionFinanciera` (una sola vez), la auditoría y el correo.

`actor_id=None` es un valor VÁLIDO: significa "lo aprobó la pasarela".
`solicitudes_planes.aprobado_por` y `auditoria.usuario_id` son nullable, así que
una aprobación automática se distingue de una humana sin inventar un usuario
"sistema". `origen` queda en `origen_pago` y en el detalle de auditoría.
"""
import logging
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.notificacion import Notificacion
from app.models.plan import Plan
from app.models.solicitud_plan import SolicitudPlan
from app.models.suscripcion import Suscripcion
from app.models.transaccion_financiera import TransaccionFinanciera
from app.models.usuario import Usuario
from app.core.urls import url_frontend
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


def precio_lista(solicitud, plan) -> int:
    """Precio de LISTA de la compra: el snapshot (P0-4) o el precio del plan.

    Es la base sobre la que se calcula cualquier descuento. Nunca el precio
    final: un % aplicado sobre otro % sería un descuento inventado.
    """
    valor = (solicitud.precio_clp_snapshot
             if solicitud.precio_clp_snapshot is not None
             else (plan.precio_clp if plan is not None else 0))
    return int(valor or 0)



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
    valores = {
        "estado": "approved",
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

    # ── Crear la suscripción activa ──
    plan = db.query(Plan).filter(Plan.id == solicitud.plan_id).first()
    if not plan:
        db.rollback()
        raise PlanNoEncontrado(solicitud_id)

    # ── Vigencia del plan EN HORA DE CHILE: `inicio + plan.duracion_dias` días
    # SEGUIDOS (regla 2026-10-06), hasta el fin de ese último día. UNA
    # definición: `fin_de_plan_chile()` (app/utils/santiago.py), compartida con
    # la compra de emergencia, `fix_fechas` y POST /suscripciones.
    ahora = ahora_santiago()
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
    # Si la solicitud YA trae un descuento de fidelización (`beneficio_id`) o un
    # precio final congelado (pago online), no se toca nada: no se apilan
    # descuentos y el referido queda pendiente.
    descuento_referido = None
    if solicitud.beneficio_id is None and solicitud.precio_final_clp is None:
        db.flush()  # asigna el id de la suscripción sin commitear
        descuento_referido = referidos.confirmar_compra(
            db,
            tenant_id=solicitud.tenant_id,
            usuario_id=solicitud.alumno_id,
            precio_lista_clp=precio_lista(solicitud, plan),
            suscripcion_id=suscripcion.id,
            ahora=ahora,
        )
        if (descuento_referido is not None
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
