"""
Endpoint para corregir fechas de suscripciones existentes (solo admin)
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from app.db.database import engine
from app.core.dependencies import get_current_admin
from app.utils.santiago import fin_de_mes_chile

router = APIRouter()


@router.post("/corregir-fechas")
def corregir_fechas_membresias(
    current_user: dict = Depends(get_current_admin),
):
    """Corrige fecha_expiracion de todas las suscripciones activas al último día del mes actual. Solo admin.

    El valor es 23:59:59 del último día del mes **en hora de Chile** (`fin_de_mes_chile()`): antes
    se guardaba `23:59 UTC`, que en Chile son las 20:59 y le robaba las últimas 3 horas al último
    día del plan.
    """
    from app.db.database import SessionLocal
    from app.models.suscripcion import Suscripcion

    db = SessionLocal()
    try:
        fecha_correcta = fin_de_mes_chile()

        suscripciones = db.query(Suscripcion).filter(
            Suscripcion.estado == 'activo'
        ).all()

        resultados = []
        for s in suscripciones:
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
