"""
Endpoint para compra de emergencia de planes
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan
from app.core.dependencies import get_current_user
from app.core.estados import vigente_hoy
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.services.auditoria_service import registrar_auditoria
from app.services import churn_service
from app.utils.santiago import ahora_santiago, fecha_chile, fin_de_plan_chile
# Los créditos que se guardan salen de UNA regla compartida: un plan ilimitado queda sin créditos
# (`NULL` = "∞" en el front), un plan con cupo guarda sus clases.
from app.utils.planes import creditos_de_plan

router = APIRouter()


class CompraEmergenciaRequest(BaseModel):
    tenant_id: int
    alumno_id: int
    plan_id: int


@router.post("/comprar-emergencia")
@limiter.limit(LIMIT_CRITICO)
def comprar_emergencia(
    request: Request,
    data: CompraEmergenciaRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Compra de emergencia cuando el alumno agotó sus clases.
    - 1ra vez al año: acumula tokens sobrantes al mes siguiente
    - 2da vez al año: NO acumula, vence fin de mes

    Solo el alumno dueño de la suscripción (o admin/coach) puede ejecutarla.
    """
    # 🔒 IDOR: solo el propio alumno o staff puede comprar emergencia para ese alumno
    rol = current_user.get("rol", "")
    if rol not in ("coach", "admin", "administrador") and data.alumno_id != current_user.get("usuario_id"):
        raise HTTPException(
            status_code=403,
            detail="No puedes comprar emergencia para otro alumno",
        )
    # ── FIX S3 (seguridad): tenant_id SIEMPRE del token JWT ──
    # El body puede traer tenant_id pero se ignora/sobreescribe: un coach/admin
    # del box A no puede operar sobre suscripciones del box B (cross-tenant).
    data.tenant_id = current_user["tenant_id"]
    # Verificar plan
    plan = db.query(Plan).filter(
        Plan.id == data.plan_id,
        Plan.tenant_id == data.tenant_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    # Buscar suscripción vigente actual.
    # Vigencia por DÍA CHILENO (`vigente_hoy`): el plan vale hasta las 23:59:59 del último día,
    # así que el 30/09 un plan de septiembre sigue sirviendo para la compra de emergencia
    # (antes, `fecha_expiracion > datetime.now(timezone.utc)` lo cortaba a las 20:59 CLT).
    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == data.tenant_id,
        Suscripcion.usuario_id == data.alumno_id,
        Suscripcion.estado == 'activo',
        vigente_hoy(Suscripcion.fecha_expiracion)
    ).order_by(Suscripcion.fecha_expiracion.desc()).first()

    if not suscripcion:
        raise HTTPException(
            status_code=400, detail="No tienes una membresía activa. Compra un plan normal.")

    # Verificar que tenga 0 clases disponibles
    if (suscripcion.creditos_disponibles or 0) > 0:
        raise HTTPException(
            status_code=400, detail=f"Todavía tienes {suscripcion.creditos_disponibles} clases disponibles. No necesitas compra de emergencia.")

    # Verificar si puede comprar emergencia (1 vez por año) — el año es el de CHILE
    ahora = ahora_santiago()
    puede_comprar = True
    if suscripcion.fecha_compra_emergencia:
        anio_compra = fecha_chile(suscripcion.fecha_compra_emergencia).year
        anio_actual = ahora.year
        if anio_compra == anio_actual:
            puede_comprar = False

    if not puede_comprar:
        raise HTTPException(
            status_code=400, detail="Ya usaste tu compra de emergencia este año. Vuelve en enero.")

    # Vigencia EN HORA DE CHILE: `inicio + plan.duracion_dias` días seguidos (regla 2026-10-06),
    # hasta el fin de ese último día. Misma función que la aprobación/creación (`fin_de_plan_chile`)
    # — antes se usaba el fin de mes, una segunda regla para el mismo campo.
    vencimiento = fin_de_plan_chile(ahora, plan.duracion_dias)

    # Guardar tokens sobrantes antes de actualizar (0 o los que tenga)
    tokens_sobrantes = suscripcion.creditos_disponibles or 0

    # Actualizar suscripción existente como compra emergencia
    suscripcion.es_compra_emergencia = True
    suscripcion.puede_comprar_emergencia = False
    suscripcion.fecha_compra_emergencia = ahora
    suscripcion.fecha_expiracion = vencimiento
    # Los créditos del plan comprado, con la regla compartida (`creditos_de_plan`): un plan
    # ilimitado (en PROD traen `creditos = 0`) queda SIN créditos (`NULL` = "∞" en el front) en vez
    # del centinela `999` que hacía ver "999 clases" en un plan sin cupo (bug de producción del
    # 2026-10-08, alumno 533).
    creditos = creditos_de_plan(plan)
    suscripcion.creditos_totales = creditos
    suscripcion.creditos_disponibles = creditos

    db.commit()

    # ── La compra de emergencia cambió créditos/vencimiento -> recalc del churn (segundo plano). ──
    churn_service.programar_recalculo(background_tasks, current_user["tenant_id"], data.alumno_id)

    # ── Auditoría interna: compra de emergencia (ajuste de tokens) ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="suscripcion",
        entidad_id=suscripcion.id,
        detalle={
            "tipo": "compra_emergencia",
            "alumno_id": data.alumno_id,
            "plan_id": data.plan_id,
            "creditos_nuevos": suscripcion.creditos_disponibles,
            "tokens_sobrantes": tokens_sobrantes,
        },
    )

    # Si es primera compra y tiene tokens sobrantes (deberían ser 0 pero por si acaso)
    acumula = tokens_sobrantes > 0

    return {
        "status": "ok",
        "mensaje": "Compra de emergencia activada",
        "plan_nombre": plan.nombre,
        "clases_compradas": creditos,
        "fecha_vencimiento": vencimiento,
        "acumula_tokens": acumula,
        "tokens_sobrantes": tokens_sobrantes,
    }
