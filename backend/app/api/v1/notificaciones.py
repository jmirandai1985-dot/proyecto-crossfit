"""
Router de Notificaciones para alumnos
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.db.database import get_db
from app.models.notificacion import Notificacion

router = APIRouter()


@router.get("")
def listar_notificaciones(
    alumno_id: int = Query(...),
    solo_no_leidas: Optional[bool] = Query(False),
    db: Session = Depends(get_db)
):
    """
    Devuelve todas las notificaciones de un alumno.
    Si solo_no_leidas=True, filtra solo las no leídas.
    """
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
    db: Session = Depends(get_db)
):
    """Marca una notificación como leída"""
    notif = db.query(Notificacion).filter(
        Notificacion.id == notificacion_id).first()
    if not notif:
        raise HTTPException(
            status_code=404, detail="Notificación no encontrada")

    notif.leida = True
    db.commit()
    return {"status": "ok", "message": "Notificación marcada como leída"}


@router.put("/leer-todas")
def marcar_todas_como_leidas(
    alumno_id: int = Query(...),
    db: Session = Depends(get_db)
):
    """Marca todas las notificaciones de un alumno como leídas"""
    db.query(Notificacion).filter(
        Notificacion.alumno_id == alumno_id,
        Notificacion.leida == False
    ).update({"leida": True})
    db.commit()
    return {"status": "ok", "message": "Todas las notificaciones marcadas como leídas"}
