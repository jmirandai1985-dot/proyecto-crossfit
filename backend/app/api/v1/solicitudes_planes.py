"""
Router de endpoints para Solicitudes de Planes (flujo admin)
"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
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
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.services.auditoria_service import registrar_auditoria
from datetime import timedelta

router = APIRouter()

logger = logging.getLogger(__name__)


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

    solicitud = SolicitudPlan(
        tenant_id=data.tenant_id,
        alumno_id=data.alumno_id,
        plan_id=data.plan_id,
        estado="pending",
        voucher_url=data.voucher_url,
        certificado_estudiante_url=data.certificado_estudiante_url
    )
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)

    return {"status": "pending", "message": "Solicitud enviada. El admin la revisará en 24h", "id": solicitud.id}


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
            "plan_precio": plan.precio_clp if plan else 0,
            "voucher_url": s.voucher_url,
            "certificado_estudiante_url": s.certificado_estudiante_url,
            "estado": s.estado,
            "created_at": s.created_at,
        })
    return results


@router.get("/{solicitud_id}/voucher")
def descargar_voucher(
    solicitud_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Descarga el voucher de pago de una solicitud (usuario autenticado).
    Retorna el archivo como attachment (descarga forzada).
    """
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    # ── FIX S1 (seguridad): control de propiedad/tenant ──
    # El voucher es un comprobante de pago sensible. Solo pueden descargarlo:
    # (a) el alumno dueño de la solicitud, o (b) un admin/coach del MISMO box
    # al que pertenece la solicitud. Sin esto, cualquier usuario autenticado
    # podía leer vouchers ajenos de cualquier tenant con solo cambiar el id (IDOR).
    rol = current_user.get("rol", "")
    es_dueno = current_user["usuario_id"] == solicitud.alumno_id
    es_staff_mismo_box = (
        rol in ("coach", "admin", "administrador")
        and current_user["tenant_id"] == solicitud.tenant_id
    )
    if not (es_dueno or es_staff_mismo_box):
        # 403 explícito (convención del proyecto: no silenciar la autorización)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes descargar el voucher de esta solicitud",
        )

    if not solicitud.voucher_url:
        raise HTTPException(status_code=404, detail="Sin voucher disponible")

    # ── SEGURIDAD: prevenir path traversal ──
    # La URL guardada es como "/static/uploads/voucher_xxx.jpg".
    # Se resuelve contra el directorio estático y se valida que el archivo
    # resultante quede DENTRO de static/ (evita '../../../etc/passwd').
    static_dir = os.path.realpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "static"))
    rel = solicitud.voucher_url.replace("/static/", "").lstrip("/")
    voucher_path = os.path.realpath(os.path.join(static_dir, rel))

    if not voucher_path.startswith(static_dir + os.sep):
        raise HTTPException(
            status_code=403, detail="Acceso denegado")

    if not os.path.exists(voucher_path):
        raise HTTPException(
            status_code=404, detail="Archivo de voucher no encontrado en el servidor")

    # Obtener nombre del archivo para el filename
    voucher_filename = os.path.basename(voucher_path)

    # Devolver como attachment para forzar descarga
    return FileResponse(
        path=voucher_path,
        media_type="image/jpeg",
        headers={"Content-Disposition": f"attachment; filename={voucher_filename}"}
    )


@router.put("/{solicitud_id}/aprobar")
@limiter.limit(LIMIT_CRITICO)
def aprobar_solicitud(
    request: Request,
    solicitud_id: int,
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
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id,
        SolicitudPlan.tenant_id == current_user["tenant_id"],
    ).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    solicitud.estado = "approved"
    solicitud.aprobado_por = admin_id
    solicitud.comentario_admin = "Aprobado"

    # Crear suscripción activa
    plan = db.query(Plan).filter(Plan.id == solicitud.plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    from datetime import datetime, timezone
    from calendar import monthrange
    hoy = datetime.now(timezone.utc)
    ultimo_dia = monthrange(hoy.year, hoy.month)[1]
    expiracion = hoy.replace(day=ultimo_dia, hour=23,
                             minute=59, second=59, microsecond=0)

    suscripcion = Suscripcion(
        tenant_id=solicitud.tenant_id,
        usuario_id=solicitud.alumno_id,
        plan_id=solicitud.plan_id,
        estado="activo",
        creditos_totales=plan.creditos if plan.creditos else 999,
        creditos_disponibles=plan.creditos if plan.creditos else 999,
        fecha_inicio=hoy,
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

    # ── FIX 4: registrar la transacción financiera del pago aprobado ──
    # Mismo formato que POST /suscripciones (suscripciones.py) para mantener
    # consistencia. No debe impedir la aprobación si falla.
    try:
        from datetime import date
        tx = TransaccionFinanciera(
            tenant_id=suscripcion.tenant_id,
            tipo="ingreso",
            categoria="membresia",
            monto=plan.precio_clp if plan.precio_clp else 0,
            descripcion=(
                f"Suscripcion plan {plan.nombre} (usuario #{solicitud.alumno_id})"
            ),
            referencia_tipo="suscripcion",
            referencia_id=suscripcion.id,
            fecha=date.today(),
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
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id,
        SolicitudPlan.tenant_id == current_user["tenant_id"],
    ).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    solicitud.estado = "rejected"
    solicitud.aprobado_por = admin_id
    solicitud.comentario_admin = motivo
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
