"""
Router de endpoints para Solicitudes de Planes (flujo admin)
"""
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from sqlalchemy import update
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.models.solicitud_plan import SolicitudPlan
from app.models.plan import Plan
from app.models.usuario import Usuario
from app.models.notificacion import Notificacion
from app.schemas.solicitud import SolicitudPlanCreate
from app.core.dependencies import get_current_admin, get_current_user
# Servido de comprobantes (voucher de plan / certificado de estudiante): la
# resolución del path dentro de su carpeta base, el media type real y la respuesta
# viven en un helper común (mismo guard para ambos documentos).
from app.core.documentos_privados import (
    puede_ver_documento, respuesta_documento,
)
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.services.auditoria_service import registrar_auditoria
# F2: el descuento vigente del alumno se aplica al SOLICITAR un plan. La aritmética (`desglose`)
# y el ciclo de vida del beneficio (`vigente`/`usar`) viven en su servicio, no acá.
from app.services import beneficios_service as beneficios
# F3b: el descuento del programa de referidos tiene que conocerse ANTES de cobrar
# (el alumno transfiere el precio final, no el de lista). El servicio es el mismo
# que después CONVIERTE el referido al aprobar: una sola regla para las dos cosas.
from app.services import referidos_service as referidos
# Avisos del PANEL (la campana): un solo módulo decide A QUIÉN y CÓMO se avisa
# (best-effort: un aviso nunca tumba la solicitud). Ver docs/NOTIFICACIONES_PANEL.md.
from app.services.notificaciones_panel import notificar_admins_del_tenant
# La aprobación (suscripción + ingreso + auditoría + correo) vive en UN servicio:
# el webhook de Mercado Pago llama a la MISMA función con `actor_id=None`. Ver
# `services/aprobacion_planes.py`.
from app.services import aprobacion_planes

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

    # ── Fase 3b: el descuento del REFERIDO también se congela AL SOLICITAR ──
    # Antes se resolvía al aprobar: el alumno transfería el precio de lista y el
    # admin veía otro monto en la misma pantalla. `previsualizar_compra` NO
    # convierte el referido ni consume el crédito (eso sigue pasando al aprobar,
    # en `confirmar_compra`): sólo fija el número que se cobra. Sin apilar: si ya
    # hay un beneficio F2, el referido espera su turno (la misma regla que aplica
    # la aprobación).
    if not descuento and isinstance(lista, int) and not isinstance(lista, bool) \
            and lista > 0:
        premio = referidos.previsualizar_compra(
            db, tenant_id=data.tenant_id, usuario_id=data.alumno_id,
            precio_lista_clp=lista)
        if premio is not None and premio["descuento_clp"] > 0:
            descuento = {
                # `descuento_pct` es Integer en la solicitud: el % del programa se
                # guarda redondeado para mostrarlo; el monto que manda es el final.
                "descuento_pct": int(round(premio["porcentaje"])),
                "precio_final_clp": premio["precio_final_clp"],
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
    # ── Sin N+1 (era N+N): plan y alumno vienen en la MISMA consulta ────────
    # ANTES: 1 SELECT de `solicitudes_planes` + 2 por CADA fila (Plan y Usuario),
    # o sea 1+2N: con 20 pendientes eran 41 consultas.
    # AHORA: 1 SELECT con LEFT JOIN a `planes` y `usuarios` por `id` — el mismo
    # criterio de antes (el nombre se resolvía por id, sin filtro de tenant), así
    # que una solicitud huérfana sigue mostrando "Desconocido" en vez de romper.
    filas = db.query(
        SolicitudPlan, Plan.nombre, Plan.precio_clp, Usuario.nombre, Usuario.correo,
    ).outerjoin(
        Plan, Plan.id == SolicitudPlan.plan_id,
    ).outerjoin(
        Usuario, Usuario.id == SolicitudPlan.alumno_id,
    ).filter(
        SolicitudPlan.tenant_id == tenant_id,
        SolicitudPlan.estado == "pending"
    ).order_by(SolicitudPlan.created_at.desc()).all()

    results = []
    for s, plan_nombre, plan_precio_clp, alumno_nombre, alumno_correo in filas:
        precio_lista = plan_precio_clp if plan_precio_clp is not None else 0
        results.append({
            "id": s.id,
            "alumno_nombre": alumno_nombre or "Desconocido",
            "alumno_email": alumno_correo or "",
            "plan_nombre": plan_nombre or "Desconocido",
            "plan_precio": (s.precio_clp_snapshot
                            if s.precio_clp_snapshot is not None
                            else precio_lista),
            # ── F2: el descuento que se le aplicó al precio de lista (NULL = sin beneficio) ──
            # El precio de lista ya viaja en `plan_precio`: acá van el % y lo que hay que cobrar.
            "descuento_pct": s.descuento_pct,
            "precio_final": (s.precio_final_clp if s.precio_final_clp is not None
                             else (s.precio_clp_snapshot
                                   if s.precio_clp_snapshot is not None
                                   else precio_lista)),
            "beneficio_id": s.beneficio_id,
            "voucher_url": s.voucher_url,
            "certificado_estudiante_url": s.certificado_estudiante_url,
            # ── Pago online (migración 067) ──
            # `origen_pago='mercadopago'` ⇒ NO hay comprobante: el panel muestra
            # el badge "Pagado online ✓" en vez de un enlace al voucher (que
            # respondería 404). `pago_id` queda para la trazabilidad.
            "origen_pago": s.origen_pago or "manual",
            "pago_id": s.pago_id,
            "estado": s.estado,
            "created_at": s.created_at,
        })
    return results


@router.get("/alumno/{alumno_id}")
def listar_solicitudes_de_alumno(
    alumno_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Solicitudes de plan de UN alumno (para revisar SU comprobante).

    POR QUÉ EXISTE: el padrón (Admin → Alumnos) tiene un botón "Voucher" por fila.
    Ese modal no sabía qué solicitud mostrar —`/pendientes` sólo trae la COLA del box,
    así que la solicitud de un alumno ya aprobado o rechazado no aparecía— y terminaba
    pintando un comprobante INVENTADO (TXN y monto fijos) con un selector de plan: el
    admin creía estar revisando el pago sin haber visto ningún archivo. Con este
    listado el modal pide el comprobante REAL de la solicitud correcta al endpoint
    autenticado (`/{solicitud_id}/voucher`).

    🔒 Guard de documentos (mismo criterio que el voucher suelto): el alumno dueño o
    staff del MISMO box. Un alumno ajeno responde 403 explícito (no se silencia).

    Se ordena de la más nueva a la más vieja: la primera con `voucher_url` es la que
    el modal muestra por defecto (una pendiente primero, ver `solicitudConComprobante`
    en el front).
    """
    alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    visible = puede_ver_documento(
        usuario_id=current_user["usuario_id"],
        tenant_id=current_user["tenant_id"],
        alumno_id=alumno_id,
        tenant_documento=alumno.tenant_id,
        rol=current_user.get("rol", ""),
    )
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes ver los comprobantes de este alumno",
        )

    # El `tenant_id` de la solicitud también se filtra: el guard ya limita a dueño o
    # box, pero así una fila con tenant cruzado nunca se cuela en la respuesta.
    solicitudes = db.query(SolicitudPlan).filter(
        SolicitudPlan.alumno_id == alumno_id,
        SolicitudPlan.tenant_id == current_user["tenant_id"],
    ).order_by(SolicitudPlan.created_at.desc()).limit(50).all()

    # Los planes se traen de una vez (una solicitud vieja puede apuntar a un plan
    # que ya no está activo; `Plan.nombre` sigue siendo el nombre con que se pidió).
    planes_por_id = {}
    if solicitudes:
        ids = {s.plan_id for s in solicitudes}
        planes_por_id = {
            p.id: p for p in db.query(Plan).filter(Plan.id.in_(ids)).all()
        }

    results = []
    for s in solicitudes:
        plan = planes_por_id.get(s.plan_id)
        results.append({
            "id": s.id,
            "estado": s.estado,
            "plan_nombre": plan.nombre if plan else "Desconocido",
            # Precio de LISTA (snapshot) y precio FINAL con descuento: los mismos dos
            # números que muestra la cola de Pendientes, para no inventar un monto.
            "plan_precio": (s.precio_clp_snapshot
                            if s.precio_clp_snapshot is not None
                            else (plan.precio_clp if plan else 0)),
            "descuento_pct": s.descuento_pct,
            "precio_final": (s.precio_final_clp if s.precio_final_clp is not None
                             else (s.precio_clp_snapshot
                                   if s.precio_clp_snapshot is not None
                                   else (plan.precio_clp if plan else 0))),
            "voucher_url": s.voucher_url,
            "certificado_estudiante_url": s.certificado_estudiante_url,
            "comentario_admin": s.comentario_admin,
            # Pago online: el historial del alumno también muestra el badge.
            "origen_pago": s.origen_pago or "manual",
            "pago_id": s.pago_id,
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
    """Admin aprueba solicitud: cambia estado, crea suscripción y activa el plan.

    Además crea una notificación para el alumno y envía el correo de confirmación.

    SEGURIDAD: el admin sale del token JWT (get_current_admin), NO de un
    parámetro enviado por el cliente (elimina el spoofing de admin_id).

    La lógica vive en `services/aprobacion_planes.py::activar_plan` porque hay un
    SEGUNDO camino que también activa planes: el webhook de Mercado Pago cuando
    el pago queda `approved`. Dos copias de esta función serían dos verdades
    (plan duplicado o dos ingresos en `transacciones_financieras`). Este endpoint
    sólo valida, delega y traduce los errores de negocio a los mismos códigos y
    mensajes de siempre.
    """
    try:
        return aprobacion_planes.activar_plan(
            db,
            solicitud_id,
            # ── FIX S2 (seguridad): la solicitud debe ser del tenant del admin ──
            # Un admin del box A ya no puede aprobar solicitudes del box B
            # (cross-tenant). Se responde 404 (no 403) para no revelar que el id
            # existe en otro tenant.
            tenant_id=current_user["tenant_id"],
            actor_id=current_user["usuario_id"],
            origen=aprobacion_planes.ORIGEN_MANUAL,
            background_tasks=background_tasks,
        )
    except aprobacion_planes.SolicitudNoProcesable as error:
        # Distinguir 404 (no existe / otro tenant) de 400 (ya procesada).
        if error.motivo == "no_encontrada":
            raise HTTPException(status_code=404,
                                detail="Solicitud no encontrada")
        raise HTTPException(
            status_code=400,
            detail="La solicitud ya fue procesada (aprobada o rechazada)",
        )
    except aprobacion_planes.PlanNoEncontrado:
        raise HTTPException(status_code=404, detail="Plan no encontrado")


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
