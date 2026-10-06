"""
Endpoint para corregir fechas de suscripciones existentes (solo admin)
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from app.db.database import engine
from app.core.dependencies import get_current_admin
from app.utils.santiago import fin_de_plan_chile

router = APIRouter()


@router.post("/corregir-fechas")
def corregir_fechas_membresias(
    current_user: dict = Depends(get_current_admin),
):
    """Corrige `fecha_expiracion` de las suscripciones activas a `inicio + duracion_dias`. Solo admin.

    Regla 2026-10-06: un plan dura `duracion_dias` días SEGUIDOS desde su día de contratación
    (`fecha_inicio`); el valor es 23:59:59 del último día **en hora de Chile** (`fin_de_plan_chile()`).
    Antes se forzaba a fin de MES (otra regla para el mismo campo): ahora cada suscripción usa su
    propio `fecha_inicio` y la `duracion_dias` de SU plan.
    """
    from app.db.database import SessionLocal
    from app.models.plan import Plan
    from app.models.suscripcion import Suscripcion

    db = SessionLocal()
    try:
        # `duracion_dias` de cada plan en UNA query (sin N+1).
        duraciones = dict(db.query(Plan.id, Plan.duracion_dias).all())

        suscripciones = db.query(Suscripcion).filter(
            Suscripcion.estado == 'activo'
        ).all()

        resultados = []
        for s in suscripciones:
            duracion = duraciones.get(s.plan_id) or 30
            fecha_correcta = fin_de_plan_chile(s.fecha_inicio, duracion)
            old = str(s.fecha_expiracion)
            s.fecha_expiracion = fecha_correcta
            resultados.append({
                "id": s.id,
                "usuario_id": s.usuario_id,
                "anterior": old,
                "corregido": str(fecha_correcta)
            })

        db.commit()
        return {
            "status": "ok",
            "registros_corregidos": len(resultados),
            "detalles": resultados
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "mensaje": str(e)}
    finally:
        db.close()
