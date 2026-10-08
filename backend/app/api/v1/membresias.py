"""
Endpoint para consultar membresía activa con tokens del alumno
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.core.dependencies import get_current_user
from app.core.estados import vigente_hoy   # vigencia por DÍA CHILENO (no por instante)
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan
from app.utils.santiago import dias_para_vencer, hoy_santiago

router = APIRouter()


@router.get("/mi-membresia")
def obtener_mi_membresia(
    tenant_id: Optional[int] = None,
    alumno_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Devuelve la membresía activa con tokens del alumno autenticado.

    🔒 SEGURIDAD: tenant_id y alumno_id se derivan del JWT; los parámetros
    de query se ignoran (cerraba IDOR que exponía el saldo de tokens de
    cualquier alumno).
    """
    tenant_id = current_user["tenant_id"]
    alumno_id = current_user["usuario_id"]

    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id == alumno_id,
        Suscripcion.estado == 'activo',
        vigente_hoy(Suscripcion.fecha_expiracion)
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

    # Días que le quedan AL PLAN, contando el día de vencimiento como completo (hora de Chile).
    # Antes se calculaba hasta el último día del MES ACTUAL con `datetime.now(timezone.utc)`:
    # para un plan que vence hoy daba 0 solo de casualidad y de noche en UTC corría el día.
    dias_restantes = dias_para_vencer(suscripcion.fecha_expiracion) or 0

    # Determinar si puede comprar emergencia
    puede_comprar = True
    if suscripcion.fecha_compra_emergencia:
        anio_compra = suscripcion.fecha_compra_emergencia.year
        anio_actual = hoy_santiago().year
        if anio_compra == anio_actual:
            puede_comprar = False

    return {
        "activa": True,
        "plan_nombre": plan.nombre if plan else "Plan",
        # Los valores REALES de la fila, tal cual: pueden ser NULL (el "∞" de los
        # planes ilimitados y el "—" de una fila sin cupo cargado). Antes se
        # inventaban números acá —`or 999` para ilimitados y `or 16` para planes
        # con cupo—, así que un NULL se pintaba como "999 créditos" o "16".
        "clases_totales": suscripcion.creditos_totales,
        "clases_disponibles": suscripcion.creditos_disponibles,
        "clases_usadas": usadas,
        "es_ilimitado": plan.es_ilimitado if plan else False,
        "dias_restantes": dias_restantes,
        "fecha_vencimiento": suscripcion.fecha_expiracion,
        "puede_comprar_emergencia": puede_comprar,
        "es_compra_emergencia": suscripcion.es_compra_emergencia,
    }
