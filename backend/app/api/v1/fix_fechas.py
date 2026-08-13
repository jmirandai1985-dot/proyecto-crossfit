"""
Endpoint para corregir fechas de suscripciones existentes (solo admin)
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from app.db.database import engine
from datetime import datetime, timezone
from calendar import monthrange
from app.core.dependencies import get_current_admin

router = APIRouter()


@router.post("/corregir-fechas")
def corregir_fechas_membresias(
    current_user: dict = Depends(get_current_admin),
):
    """Corrige fecha_expiracion de todas las suscripciones activas al último día del mes actual. Solo admin."""
    from app.db.database import SessionLocal
    from app.models.suscripcion import Suscripcion

    db = SessionLocal()
    try:
        hoy = datetime.now(timezone.utc)
        ultimo_dia = monthrange(hoy.year, hoy.month)[1]
        fecha_correcta = hoy.replace(
            day=ultimo_dia, hour=23, minute=59, second=59, microsecond=0)

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
