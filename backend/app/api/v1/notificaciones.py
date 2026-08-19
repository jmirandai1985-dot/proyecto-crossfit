"""
Router de Notificaciones para alumnos
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.db.database import get_db
from app.models.notificacion import Notificacion
from app.core.dependencies import get_current_admin, get_current_user

router = APIRouter()


@router.get("")
def listar_notificaciones(
    alumno_id: Optional[int] = Query(None),
    solo_no_leidas: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Devuelve las notificaciones del alumno autenticado.
    Si solo_no_leidas=True, filtra solo las no leídas.

    🔒 SEGURIDAD: alumno_id se deriva del JWT. Si el cliente envía un
    alumno_id ajeno sin ser coach/admin del box → 403 explícito.
    """
    rol = current_user.get("rol", "")
    if alumno_id is not None:
        if rol in ("coach", "admin", "administrador"):
            # Staff: puede listar notificaciones de cualquier alumno del box
            pass
        elif alumno_id != current_user["usuario_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes ver las notificaciones de otro alumno",
            )
    else:
        alumno_id = current_user["usuario_id"]

    query = db.query(Notificacion).filter(
        Notificacion.alumno_id == alumno_id
    )
    if solo_no_leidas:
        query = query.filter(Notificacion.leida == False)

    notificaciones = query.order_by(
        Notificacion.created_at.desc()
    ).limit(50).all()

    return [
        {
            "id": n.id,
            "alumno_id": n.alumno_id,
            "tipo": n.tipo,
            "mensaje": n.mensaje,
            "leida": n.leida,
            "created_at": n.created_at,
        }
        for n in notificaciones
    ]


@router.put("/{notificacion_id}/leer")
def marcar_como_leida(
    notificacion_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Marca una notificación como leída (solo el dueño)"""
    notif = db.query(Notificacion).filter(
        Notificacion.id == notificacion_id).first()
    if not notif:
        raise HTTPException(
            status_code=404, detail="Notificación no encontrada")

    # 🔒 IDOR: solo el dueño puede marcarla.
    if notif.alumno_id != current_user["usuario_id"]:
        raise HTTPException(
            status_code=403, detail="No puedes marcar notificaciones de otro alumno")

    notif.leida = True
    db.commit()
    return {"status": "ok", "message": "Notificación marcada como leída"}


@router.put("/leer-todas")
def marcar_todas_como_leidas(
    alumno_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Marca todas las notificaciones del alumno autenticado como leídas"""
    # 🔒 SEGURIDAD: alumno_id del token; el query param se ignora.
    alumno_id = current_user["usuario_id"]
    db.query(Notificacion).filter(
        Notificacion.alumno_id == alumno_id,
        Notificacion.leida == False
    ).update({"leida": True})
    db.commit()
    return {"status": "ok", "message": "Todas las notificaciones marcadas como leídas"}


# ═══════════════════════════════════════════════════════════════════════
# ALERTAS AUTOMÁTICAS DE EMAIL — disparo manual (admin)
# Misma lógica que los jobs del scheduler, para probar/forzar sin esperar la hora.
# ═══════════════════════════════════════════════════════════════════════

@router.post("/enviar-alertas-vencimiento")
def disparar_alertas_vencimiento(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Email 3 - Planes que vencen en 3 días (send_renovacion_plan)."""
    from app.services.alertas_email_service import enviar_alertas_renovacion
    return enviar_alertas_renovacion(db)


@router.post("/enviar-alertas-inactividad")
def disparar_alertas_inactividad(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Email 4 - Alumnos con 7+ días sin asistencia (send_alerta_inactividad)."""
    from app.services.alertas_email_service import enviar_alertas_inactividad
    return enviar_alertas_inactividad(db)


@router.post("/enviar-alertas-urgencia")
def disparar_alertas_urgencia(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Email 5 - Planes que vencen HOY (send_alerta_urgencia_renovacion)."""
    from app.services.alertas_email_service import enviar_alertas_urgencia
    return enviar_alertas_urgencia(db)
