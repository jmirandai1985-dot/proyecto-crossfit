"""
Endpoint para consultar membresía activa con tokens del alumno
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from calendar import monthrange
from app.db.database import get_db
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan

router = APIRouter()


@router.get("/mi-membresia")
def obtener_mi_membresia(
    tenant_id: int,
    alumno_id: int,
    db: Session = Depends(get_db)
):
    """Devuelve la membresía activa con tokens del alumno"""
    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id == alumno_id,
        Suscripcion.estado == 'activo',
        Suscripcion.fecha_expiracion > datetime.now(timezone.utc)
    ).order_by(Suscripcion.fecha_expiracion.desc()).first()

    if not suscripcion:
        return {
            "activa": False,
            "plan_nombre": None,
            "clases_totales": 0,
            "clases_disponibles": 0,
            "clases_usadas": 0,
            "dias_restantes": 0,
            "es_ilimitado": False,
            "fecha_vencimiento": None,
            "puede_comprar_emergencia": False,
        }

    plan = db.query(Plan).filter(Plan.id == suscripcion.plan_id).first()
    usadas = (suscripcion.creditos_totales or 0) - \
        (suscripcion.creditos_disponibles or 0)

    # Calcular días hasta el último día del MES ACTUAL
    hoy = datetime.now(timezone.utc)
    ultimo_dia = monthrange(hoy.year, hoy.month)[1]
    fecha_ultimo_dia = hoy.replace(
        day=ultimo_dia, hour=23, minute=59, second=59, microsecond=0)
    dias_restantes = (fecha_ultimo_dia - hoy).days
    if dias_restantes < 0:
        dias_restantes = 0

    # Determinar si puede comprar emergencia
    puede_comprar = True
    if suscripcion.fecha_compra_emergencia:
        anio_compra = suscripcion.fecha_compra_emergencia.year
        anio_actual = datetime.now(timezone.utc).year
        if anio_compra == anio_actual:
            puede_comprar = False

    return {
        "activa": True,
        "plan_nombre": plan.nombre if plan else "Plan",
        "clases_totales": suscripcion.creditos_totales or (16 if plan and not plan.es_ilimitado else 999),
        "clases_disponibles": suscripcion.creditos_disponibles or (16 if plan and not plan.es_ilimitado else 999),
        "clases_usadas": usadas,
        "es_ilimitado": plan.es_ilimitado if plan else False,
        "dias_restantes": dias_restantes,
        "fecha_vencimiento": suscripcion.fecha_expiracion,
        "puede_comprar_emergencia": puede_comprar,
        "es_compra_emergencia": suscripcion.es_compra_emergencia,
    }
