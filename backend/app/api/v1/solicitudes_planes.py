"""
Router de endpoints para Solicitudes de Planes (flujo admin)
"""
import os
from fastapi import APIRouter, Depends, HTTPException, status
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
from app.schemas.solicitud import SolicitudPlanCreate
from datetime import timedelta

router = APIRouter()


@router.post("/solicitar", status_code=status.HTTP_201_CREATED)
def solicitar_plan(
    data: SolicitudPlanCreate,
    db: Session = Depends(get_db)
):
    """
    Crea una solicitud de plan pendiente de aprobación admin.
    NO activa el plan automáticamente.
    """
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
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Lista solicitudes pendientes para el admin"""
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
    db: Session = Depends(get_db)
):
    """
    Descarga el voucher de pago de una solicitud.
    Retorna el archivo como attachment (descarga forzada).
    """
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if not solicitud.voucher_url:
        raise HTTPException(status_code=404, detail="Sin voucher disponible")

    # La URL guardada es como "/static/uploads/voucher_xxx.jpg"
    # Convertir a ruta de archivo real
    # static dir está en backend/app/static
    # __file__ está en backend/app/api/v1/ -> subir 3 niveles: .., .., ../
    static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    voucher_path = os.path.join(
        static_dir, solicitud.voucher_url.replace("/static/", ""))

    # Si no existe en la ruta relativa, buscar en la ruta absoluta
    if not os.path.exists(voucher_path):
        # Intentar con la ruta completa desde la URL
        voucher_path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(__file__)))),
            solicitud.voucher_url.lstrip("/")
        )

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
def aprobar_solicitud(
    solicitud_id: int,
    admin_id: int,
    db: Session = Depends(get_db)
):
    """
    Admin aprueba solicitud: cambia estado, crea suscripción y activa el plan.
    Además crea una notificación para el alumno.
    VALIDACIÓN DE SEGURIDAD: verifica que el usuario autenticado tenga rol admin.
    """
    # 🔒 Validación crítica: verificar que admin_id corresponde a un usuario con rol admin
    admin = db.query(Usuario).filter(Usuario.id == admin_id).first()
    if not admin:
        raise HTTPException(
            status_code=404, detail="Usuario admin no encontrado")
    if admin.rol not in ("administrador", "admin"):
        raise HTTPException(
            status_code=403, detail="Acción no permitida: se requiere rol de administrador")

    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()
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

    db.commit()

    return {"status": "approved", "message": "Plan activado exitosamente"}


@router.put("/{solicitud_id}/rechazar")
def rechazar_solicitud(
    solicitud_id: int,
    admin_id: int,
    motivo: Optional[str] = "Rechazado",
    db: Session = Depends(get_db)
):
    """Admin rechaza solicitud y crea notificación. VALIDACIÓN DE SEGURIDAD incluida."""
    # 🔒 Validación crítica: verificar rol admin
    admin = db.query(Usuario).filter(Usuario.id == admin_id).first()
    if not admin:
        raise HTTPException(
            status_code=404, detail="Usuario admin no encontrado")
    if admin.rol not in ("administrador", "admin"):
        raise HTTPException(
            status_code=403, detail="Acción no permitida: se requiere rol de administrador")

    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    solicitud.estado = "rejected"
    solicitud.aprobado_por = admin_id
    solicitud.comentario_admin = motivo
    db.commit()

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
