"""
Endpoint para compra de emergencia de planes
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from calendar import monthrange
from pydantic import BaseModel

from app.db.database import get_db
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan

router = APIRouter()


class CompraEmergenciaRequest(BaseModel):
    tenant_id: int
    alumno_id: int
    plan_id: int


@router.post("/comprar-emergencia")
def comprar_emergencia(
    data: CompraEmergenciaRequest,
    db: Session = Depends(get_db)
):
    """
    Compra de emergencia cuando el alumno agotó sus clases.
    - 1ra vez al año: acumula tokens sobrantes al mes siguiente
    - 2da vez al año: NO acumula, vence fin de mes
    """
    # Verificar plan
    plan = db.query(Plan).filter(
        Plan.id == data.plan_id,
        Plan.tenant_id == data.tenant_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    # Buscar suscripción activa actual
    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == data.tenant_id,
        Suscripcion.usuario_id == data.alumno_id,
        Suscripcion.estado == 'activo',
        Suscripcion.fecha_expiracion > datetime.now(timezone.utc)
    ).order_by(Suscripcion.fecha_expiracion.desc()).first()

    if not suscripcion:
        raise HTTPException(
            status_code=400, detail="No tienes una membresía activa. Compra un plan normal.")

    # Verificar que tenga 0 clases disponibles
    if (suscripcion.creditos_disponibles or 0) > 0:
        raise HTTPException(
            status_code=400, detail=f"Todavía tienes {suscripcion.creditos_disponibles} clases disponibles. No necesitas compra de emergencia.")

    # Verificar si puede comprar emergencia (1 vez por año)
    puede_comprar = True
    if suscripcion.fecha_compra_emergencia:
        anio_compra = suscripcion.fecha_compra_emergencia.year
        anio_actual = datetime.now(timezone.utc).year
        if anio_compra == anio_actual:
            puede_comprar = False

    if not puede_comprar:
        raise HTTPException(
            status_code=400, detail="Ya usaste tu compra de emergencia este año. Vuelve en enero.")

    # Calcular fin de mes actual
    hoy = datetime.now(timezone.utc)
    ultimo_dia = monthrange(hoy.year, hoy.month)[1]
    fin_mes = hoy.replace(day=ultimo_dia, hour=23,
                          minute=59, second=59, microsecond=0)

    # Guardar tokens sobrantes antes de actualizar (0 o los que tenga)
    tokens_sobrantes = suscripcion.creditos_disponibles or 0

    # Actualizar suscripción existente como compra emergencia
    suscripcion.es_compra_emergencia = True
    suscripcion.puede_comprar_emergencia = False
    suscripcion.fecha_compra_emergencia = hoy
    suscripcion.fecha_expiracion = fin_mes
    suscripcion.creditos_totales = plan.creditos or 999
    suscripcion.creditos_disponibles = plan.creditos or 999

    db.commit()

    # Si es primera compra y tiene tokens sobrantes (deberían ser 0 pero por si acaso)
    acumula = tokens_sobrantes > 0

    return {
        "status": "ok",
        "mensaje": "Compra de emergencia activada",
        "plan_nombre": plan.nombre,
        "clases_compradas": plan.creditos or 999,
        "fecha_vencimiento": fin_mes,
        "acumula_tokens": acumula,
        "tokens_sobrantes": tokens_sobrantes,
    }
