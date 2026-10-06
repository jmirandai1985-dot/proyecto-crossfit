"""
Router de endpoints para Solicitudes de Planes (flujo admin)
"""
from app.core.urls import url_frontend  # B.2
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from sqlalchemy import update
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.db.database import get_db
from app.models.solicitud_plan import SolicitudPlan
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan
from app.models.usuario import Usuario
from app.models.notificacion import Notificacion
from app.models.transaccion_financiera import TransaccionFinanciera
from app.schemas.solicitud import SolicitudPlanCreate
from app.core.dependencies import get_current_admin, get_current_user
# Servido de comprobantes (voucher de plan / certificado de estudiante): la
# resolución del path dentro de su carpeta base, el media type real y la respuesta
# viven en un helper común (mismo guard para ambos documentos).
from app.core.documentos_privados import (
    puede_ver_documento, respuesta_documento,
)
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.core.config import settings
# El fin de mes de un plan se escribe EN HORA DE CHILE (23:59:59 del último día, ver la regla en
# `app/utils/santiago.py`): una sola definición para este flujo y la compra de emergencia.
from app.utils.santiago import ahora_santiago, fin_de_plan_chile, hoy_santiago
from app.services.auditoria_service import registrar_auditoria
from app.services import churn_service
# F2: el descuento vigente del alumno se aplica al SOLICITAR un plan. La aritmética (`desglose`)
# y el ciclo de vida del beneficio (`vigente`/`usar`) viven en su servicio, no acá.
from app.services import beneficios_service as beneficios
# Avisos del PANEL (la campana): un solo módulo decide A QUIÉN y CÓMO se avisa
# (best-effort: un aviso nunca tumba la solicitud). Ver docs/NOTIFICACIONES_PANEL.md.
from app.services.notificaciones_panel import notificar_admins_del_tenant
from datetime import timedelta

router = APIRouter()

logger = logging.getLogger(__name__)


def _solicitud_con_guard(solicitud_id: int, db: Session, current_user: dict,
                         etiqueta: str):
    """Carga la solicitud y aplica el guard de documentos.

    404 si la solicitud no existe; 403 si quien pide no es el alumno dueño ni
    staff del mismo box (convención del proyecto: no silenciar la autorización).
    """
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    visible = puede_ver_documento(
        usuario_id=current_user["usuario_id"],
        tenant_id=current_user["tenant_id"],
        alumno_id=solicitud.alumno_id,
        tenant_documento=solicitud.tenant_id,
        rol=current_user.get("rol", ""),
    )
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No puedes descargar {etiqueta} de esta solicitud",
        )
    return solicitud


@router.post("/solicitar", status_code=status.HTTP_201_CREATED)
@limiter.limit(LIMIT_CRITICO)
def solicitar_plan(
    request: Request,
    data: SolicitudPlanCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Crea una solicitud de plan pendiente de aprobación admin.
    NO activa el plan automáticamente.

    🔒 SEGURIDAD: tenant_id y alumno_id se derivan del JWT. Un alumno solo
    puede solicitar para sí mismo; coach/admin pueden hacerlo en nombre de
    un alumno del mismo box.
    """
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    # 🔒 IDOR: un alumno solo puede solicitar para sí mismo.
    #   Si manda un alumno_id ajeno → 403 explícito (no se silencia).
    if rol not in ("coach", "admin", "administrador"):
        if data.alumno_id != current_user["usuario_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes solicitar un plan para otro alumno",
            )
        data.alumno_id = current_user["usuario_id"]
    else:
        # Staff: permitir pedido en nombre de un alumno, pero dentro del box.
        # El alumno destino debe pertenecer al tenant del token.
        alumno_destino = db.query(Usuario).filter(
            Usuario.id == data.alumno_id,
            Usuario.tenant_id == tenant_id
        ).first()
        if not alumno_destino:
            raise HTTPException(
                status_code=403,
                detail="El alumno destino no pertenece a este box",
            )

    # El tenant SIEMPRE sale del token (nunca del body).
    data.tenant_id = tenant_id

    # Verificar que el plan existe
    plan = db.query(Plan).filter(Plan.id == data.plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    # Verificar que no tenga una solicitud pending
    existing = db.query(SolicitudPlan).filter(
        SolicitudPlan.alumno_id == data.alumno_id,
        SolicitudPlan.tenant_id == data.tenant_id,
        SolicitudPlan.estado == "pending"
    ).first()
    if existing:
        raise HTTPException(
            status_code=400, detail="Ya tienes una solicitud pendiente")

    # ── F2: el descuento VIGENTE del alumno se aplica a ESTA compra ──
    # El precio de lista se conserva como snapshot (`precio_clp_snapshot`, P0-4) y la solicitud
    # guarda el % y el precio final: la aprobación cobra el FINAL, no el de lista. La aritmética es
    # del servicio (`desglose`): un `%` calculado en dos lados es un `%` que se desincroniza.
    descuento = {}
    lista = plan.precio_clp
    if isinstance(lista, int) and not isinstance(lista, bool) and lista > 0:
        vigente = beneficios.vigente(db, data.alumno_id, tipo=beneficios.TIPO_DESCUENTO)
        if vigente is not None:
            aritmetica = beneficios.desglose(vigente, lista)
            descuento = {
                "beneficio_id": vigente.id,
                "descuento_pct": aritmetica["descuento_pct"],
                "precio_final_clp": aritmetica["precio_final_clp"],
            }

    solicitud = SolicitudPlan(
        tenant_id=data.tenant_id,
        alumno_id=data.alumno_id,
        plan_id=data.plan_id,
        estado="pending",
        voucher_url=data.voucher_url,
        certificado_estudiante_url=data.certificado_estudiante_url,
        # ── P0-4 (S-01): snapshot del precio vigente AL SOLICITAR ──
        # La aprobación/ingreso NO debe depender de cambios de precio posteriores.
        precio_clp_snapshot=plan.precio_clp,
        **descuento,
    )
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)

    # El beneficio se marca USADO en el mismo movimiento: es la conversión que mide la F4 y ocurre
    # una sola vez (si la solicitud se rechaza, el descuento ya se aplicó a esta compra: volver a
    # usarlo sería el mismo regalo dos veces).
    if descuento.get("beneficio_id"):
        beneficio = beneficios.vigente(db, data.alumno_id, tipo=beneficios.TIPO_DESCUENTO)
        if beneficio is not None and beneficio.id == descuento["beneficio_id"]:
            try:
                beneficios.usar(db, beneficio, precio_lista_clp=plan.precio_clp)
            except beneficios.BeneficioError as e:
                # La solicitud YA está guardada con su descuento: si el uso falla, se dice y no se
                # rompe la solicitud (el panel lo puede ver en la pestaña Beneficios).
                logger.warning(f"No se pudo marcar el beneficio #{beneficio.id} como usado: {e}")

    # ── Campana del ADMIN: la solicitud con voucher también avisa ──
    # Antes la solicitud vivía SÓLO en el Dashboard (/admin/dashboard, GET
    # /solicitudes/pendientes): si el admin no entraba a esa pantalla, el voucher
    # quedaba sin revisar y nada se lo recordaba (la campana sólo tenía avisos para
    # el alumno). El mensaje dice el alumno y el plan —lo que el admin necesita para
    # ubicar el comprobante— y el #id para encontrarla en la lista de pendientes.
    # El `tipo` 'plan_solicitado' entra en la columna (`String(20)`: 14 caracteres).
    alumno_solicitante = db.query(Usuario).filter(
        Usuario.id == data.alumno_id).first()
    nombre_alumno = (
        alumno_solicitante.nombre if alumno_solicitante
        else f"Alumno #{data.alumno_id}")
    notificar_admins_del_tenant(
        db, data.tenant_id, "plan_solicitado",
        f"💳 Nueva solicitud de plan de {nombre_alumno}: "
        f"{plan.nombre} (solicitud #{solicitud.id})")

    return {
        "status": "pending",
        "message": "Solicitud enviada. El admin la revisará en 24h",
        "id": solicitud.id,
        # F2: el frontend muestra el precio de lista tachado y el final (y hasta cuándo valía).
        "precio_lista_clp": plan.precio_clp,
        "descuento_pct": solicitud.descuento_pct,
        "precio_final_clp": solicitud.precio_final_clp,
        "beneficio_id": solicitud.beneficio_id,
    }


@router.get("/pendientes")
def listar_solicitudes_pendientes(
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Lista solicitudes pendientes para el admin (solo admin, tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    solicitudes = db.query(SolicitudPlan).filter(
        SolicitudPlan.tenant_id == tenant_id,
        SolicitudPlan.estado == "pending"
    ).order_by(SolicitudPlan.created_at.desc()).all()

    results = []
    for s in solicitudes:
        plan = db.query(Plan).filter(Plan.id == s.plan_id).first()
        from app.models.usuario import Usuario
        alumno = db.query(Usuario).filter(Usuario.id == s.alumno_id).first()
        results.append({
            "id": s.id,
            "alumno_nombre": alumno.nombre if alumno else "Desconocido",
            "alumno_email": alumno.correo if alumno else "",
            "plan_nombre": plan.nombre if plan else "Desconocido",
            "plan_precio": (s.precio_clp_snapshot
                            if s.precio_clp_snapshot is not None
                            else (plan.precio_clp if plan else 0)),
            # ── F2: el descuento que se le aplicó al precio de lista (NULL = sin beneficio) ──
            # El precio de lista ya viaja en `plan_precio`: acá van el % y lo que hay que cobrar.
            "descuento_pct": s.descuento_pct,
            "precio_final": (s.precio_final_clp if s.precio_final_clp is not None
                             else (s.precio_clp_snapshot
                                   if s.precio_clp_snapshot is not None
                                   else (plan.precio_clp if plan else 0))),
            "beneficio_id": s.beneficio_id,
            "voucher_url": s.voucher_url,
            "certificado_estudiante_url": s.certificado_estudiante_url,
            "estado": s.estado,
            "created_at": s.created_at,
        })
    return results


@router.get("/{solicitud_id}/voucher")
def descargar_voucher(
    solicitud_id: int,
    inline: bool = False,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Devuelve el voucher de pago de una solicitud (usuario autenticado).

    - Por defecto: descarga forzada (Content-Disposition: attachment).
    - ?inline=1: se sirve para previsualizar (Content-Disposition: inline).

    El panel admin consume SIEMPRE este endpoint (con responseType='blob') para
    vista previa y descarga, en vez de la URL pública /static/uploads/... (que
    StaticFiles sirve SIN autenticación).
    """
    solicitud = _solicitud_con_guard(solicitud_id, db, current_user, "el voucher")

    if not solicitud.voucher_url:
        raise HTTPException(status_code=404, detail="Sin voucher disponible")

    # Dos orígenes posibles: comprobantes HISTÓRICOS en /static/uploads/... y los
    # NUEVOS en /privado/vouchers/ (private_uploads/). El helper resuelve el path
    # DENTRO de su carpeta base (anti traversal) y arma la respuesta.
    return respuesta_documento(solicitud.voucher_url, "voucher", inline)


@router.get("/{solicitud_id}/certificado")
def descargar_certificado(
    solicitud_id: int,
    inline: bool = False,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Devuelve el CERTIFICADO DE ESTUDIANTE de una solicitud (usuario autenticado).

    Espejo del endpoint del voucher: mismo guard (alumno dueño o staff del mismo
    box), mismos DOS orígenes de archivo y mismo ?inline=1 para previsualizar.

    Antes el certificado se subía a /static/uploads/ (público) y el panel lo abría
    por su URL: cualquiera con el link veía el documento del alumno. Ahora se sube
    con ?privado=1 y se sirve SOLO por este endpoint autenticado.
    """
    solicitud = _solicitud_con_guard(
        solicitud_id, db, current_user, "el certificado")

    if not solicitud.certificado_estudiante_url:
        raise HTTPException(status_code=404, detail="Sin certificado disponible")

    return respuesta_documento(
        solicitud.certificado_estudiante_url, "certificado", inline)


@router.put("/{solicitud_id}/aprobar")
@limiter.limit(LIMIT_CRITICO)
def aprobar_solicitud(
    request: Request,
    solicitud_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Admin aprueba solicitud: cambia estado, crea suscripción y activa el plan.
    Además crea una notificación para el alumno.
    SEGURIDAD: el admin sale del token JWT (get_current_admin), NO de un
    parámetro enviado por el cliente (elimina el spoofing de admin_id).
    """
    # 🔒 El admin autenticado por token (get_current_admin ya validó el rol)
    admin_id = current_user["usuario_id"]

    # ── FIX S2 (seguridad): la solicitud debe ser del tenant del admin ──
    # Un admin del box A ya no puede aprobar solicitudes del box B (cross-tenant).
    # Se devuelve 404 (no 403) para no revelar que el id existe en otro tenant.
    # ── FIX doble-procesamiento (ATOMICO): una solicitud solo puede aprobarse
    # UNA vez. El UPDATE condicional con estado='pending' garantiza que de dos
    # admins aprobando en paralelo la misma solicitud, solo uno obtenga
    # rowcount=1. El check leído-comprobar previo NO era seguro bajo MVCC.
    result = db.execute(
        update(SolicitudPlan)
        .where(SolicitudPlan.id == solicitud_id)
        .where(SolicitudPlan.tenant_id == current_user["tenant_id"])
        .where(SolicitudPlan.estado == "pending")
        .values(estado="approved", aprobado_por=admin_id, comentario_admin="Aprobado")
    )
    if result.rowcount == 0:
        # Distinguir 404 (no existe / otro tenant) de 400 (ya procesada)
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == solicitud_id,
            SolicitudPlan.tenant_id == current_user["tenant_id"],
        ).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        raise HTTPException(
            status_code=400,
            detail="La solicitud ya fue procesada (aprobada o rechazada)",
        )
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()

    # Crear suscripción activa
    plan = db.query(Plan).filter(Plan.id == solicitud.plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    # ── Vigencia del plan EN HORA DE CHILE: `inicio + plan.duracion_dias` días SEGUIDOS (regla
    # 2026-10-06), hasta el fin de ese último día. UNA definición: `fin_de_plan_chile()`
    # (app/utils/santiago.py), compartida con la compra de emergencia, `fix_fechas` y POST
    # /suscripciones. Antes cada camino usaba el fin de MES: dos reglas sobre dinero que se
    # desincronizaban. Un plan de Prueba cae solo (su `duracion_dias` es 7).
    ahora = ahora_santiago()
    expiracion = fin_de_plan_chile(ahora, plan.duracion_dias)

    suscripcion = Suscripcion(
        tenant_id=solicitud.tenant_id,
        usuario_id=solicitud.alumno_id,
        plan_id=solicitud.plan_id,
        estado="activo",
        creditos_totales=plan.creditos if plan.creditos else 999,
        creditos_disponibles=plan.creditos if plan.creditos else 999,
        fecha_inicio=ahora,
        fecha_expiracion=expiracion,
    )
    db.add(suscripcion)

    # Crear notificación de aprobado
    notificacion = Notificacion(
        alumno_id=solicitud.alumno_id,
        tipo="aprobado",
        mensaje=f"✅ Tu plan {plan.nombre} ha sido aprobado y ya está ACTIVO",
        leida=False,
    )
    db.add(notificacion)

    # ── FIX 3: desbloqueo de acceso completo tras pagar ──
    # Si el alumno aún tiene una suscripción ACTIVA del plan 'Prueba', se
    # expira (estado='vencido') para que es_prueba pase a false y se habiliten
    # las secciones de pago. NO se borra el historial (solo cambia de estado).
    # DECISIÓN: se usa 'vencido' porque el enum estado_suscripcion de la BD
    # solo admite pendiente/activo/vencido/rechazado (un valor
    # 'expirada_por_upgrade' exigiría ALTER TYPE, fuera de alcance).
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
            f"Suscripcion Prueba #{sp.id} del alumno {solicitud.alumno_id} "
            "expirada por upgrade a plan pago"
        )

    db.commit()

    # ── Churn del alumno: al aprobar un plan cambia su situación -> recalc en segundo plano. ──
    churn_service.programar_recalculo(background_tasks, solicitud.tenant_id, solicitud.alumno_id)

    # ── FIX 4: registrar la transacción financiera del pago aprobado ──
    # Mismo formato que POST /suscripciones (suscripciones.py) para mantener
    # consistencia. No debe impedir la aprobación si falla.
    try:
        # ── P0-4 (S-01): el ingreso usa el precio VIGENTE AL SOLICITAR ──
        # (snapshot guardado al crear la solicitud). Antes se usaba
        # `plan.precio_clp` del momento de APROBAR: si el admin cambiaba el
        # precio entre medio, la transacción quedaba por el precio nuevo
        # (reproducido en TEST: 44.000 al solicitar -> ingreso de 99.000).
        # Fallback para solicitudes históricas sin snapshot.
        # ── F2: si la solicitud trae un descuento aplicado, se cobra el PRECIO FINAL ──
        # (`precio_final_clp` lo calculó el beneficio sobre el precio de lista; NULL = sin regalo).
        monto_facturado = (solicitud.precio_final_clp
                           if solicitud.precio_final_clp is not None
                           else (solicitud.precio_clp_snapshot
                                 if solicitud.precio_clp_snapshot is not None
                                 else (plan.precio_clp or 0)))
        tx = TransaccionFinanciera(
            tenant_id=suscripcion.tenant_id,
            tipo="ingreso",
            categoria="membresia",
            monto=monto_facturado,
            descripcion=(
                f"Suscripcion plan {plan.nombre} (usuario #{solicitud.alumno_id})"
            ),
            referencia_tipo="suscripcion",
            referencia_id=suscripcion.id,
            fecha=hoy_santiago(),
        )
        db.add(tx)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"No se pudo registrar transaccion financiera: {e}")

    # ── Auditoría interna: quién, cuándo, qué (aprobación de comprobante) ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="solicitud_plan",
        entidad_id=solicitud.id,
        detalle={
            "estado": "approved",
            "alumno_id": solicitud.alumno_id,
            "plan_id": solicitud.plan_id,
            "voucher_url": solicitud.voucher_url,
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
            # Renovación si existía ≥1 suscripción previa (excluye la recién creada).
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

    return {"status": "approved", "message": "Plan activado exitosamente"}


@router.put("/{solicitud_id}/rechazar")
@limiter.limit(LIMIT_CRITICO)
def rechazar_solicitud(
    request: Request,
    solicitud_id: int,
    motivo: Optional[str] = "Rechazado",
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Admin rechaza solicitud y crea notificación. El admin sale del token JWT."""
    # 🔒 El admin autenticado por token (elimina el spoofing de admin_id)
    admin_id = current_user["usuario_id"]

    # ── FIX S2 (seguridad): la solicitud debe ser del tenant del admin ──
    # Un admin del box A ya no puede rechazar solicitudes del box B (cross-tenant).
    # Se devuelve 404 (no 403) para no revelar que el id existe en otro tenant.
    # ── FIX doble-procesamiento (ATOMICO): igual que aprobar.
    result = db.execute(
        update(SolicitudPlan)
        .where(SolicitudPlan.id == solicitud_id)
        .where(SolicitudPlan.tenant_id == current_user["tenant_id"])
        .where(SolicitudPlan.estado == "pending")
        .values(estado="rejected", aprobado_por=admin_id, comentario_admin=motivo)
    )
    if result.rowcount == 0:
        # Distinguir 404 (no existe / otro tenant) de 400 (ya procesada)
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == solicitud_id,
            SolicitudPlan.tenant_id == current_user["tenant_id"],
        ).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        raise HTTPException(
            status_code=400,
            detail="La solicitud ya fue procesada (aprobada o rechazada)",
        )
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()
    db.commit()

    # ── Auditoría interna: rechazo de comprobante ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="solicitud_plan",
        entidad_id=solicitud.id,
        detalle={
            "estado": "rejected",
            "alumno_id": solicitud.alumno_id,
            "plan_id": solicitud.plan_id,
            "motivo": motivo,
        },
    )

    # Crear notificación de rechazo
    plan = db.query(Plan).filter(Plan.id == solicitud.plan_id).first()
    plan_nombre = plan.nombre if plan else "solicitado"
    notificacion = Notificacion(
        alumno_id=solicitud.alumno_id,
        tipo="rechazado",
        mensaje=f"❌ Tu solicitud para {plan_nombre} fue rechazada. Motivo: {motivo}. Puedes intentar de nuevo",
        leida=False,
    )
    db.add(notificacion)
    db.commit()

    return {"status": "rejected", "message": "Solicitud rechazada"}
