"""Endpoints de ML: reentrenamiento automático de los modelos (churn/forecast).

PROTEGIDO con el MISMO mecanismo que `app/api/v1/kpis_populate.py`: header
`X-N8N-API-Key` (= settings.N8N_API_KEY). Lo llama **n8n** automáticamente
(una vez al mes) — NO un admin logueado, por eso no usa `get_current_admin`.

Los modelos se guardan en la tabla `ml_modelos` (BD, no disco) para que
sobrevivan a los reinicios/redeploys de Render.
"""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db

router = APIRouter(prefix="/api/v1/ml", tags=["ML"])

TENANT_ID = 1   # hoy hay un solo box; parametrizable luego (igual que kpis_populate)


def _verificar_api_key_n8n(
    x_n8n_api_key: str = Header(default="", alias="X-N8N-API-Key"),
) -> bool:
    """Valida `X-N8N-API-Key` contra settings.N8N_API_KEY (401 si no coincide).

    Mismo mecanismo (copiado a propósito) que
    `kpis_populate._verificar_api_key_n8n`.
    """
    esperada = settings.N8N_API_KEY
    if not esperada or not secrets.compare_digest(esperada, x_n8n_api_key):
        raise HTTPException(
            status_code=401, detail="API key inválida para el endpoint de n8n")
    return True


@router.post("/reentrenar")
def reentrenar_modelos(
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Reentrena churn + forecast y los persiste en `ml_modelos` (upsert).

    Devuelve las métricas de ambos para que n8n pueda loguearlas.
    """
    # Import perezoso: si falta scikit-learn o `ml/`, la app arranca igual y
    # sólo falla este endpoint (503) en vez de romper el router entero.
    try:
        from ml.entrenar import entrenar_churn, entrenar_forecast
        from ml.persistencia import guardar_modelo, info_modelos
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"ML no disponible: {e}")

    tenant_id = TENANT_ID
    try:
        modelo_churn, meta_churn = entrenar_churn(db, tenant_id)
        guardado_churn = guardar_modelo(
            db, tenant_id, "churn", modelo_churn, meta_churn)

        modelo_forecast, meta_forecast = entrenar_forecast(db, tenant_id)
        guardado_forecast = guardar_modelo(
            db, tenant_id, "forecast", modelo_forecast, meta_forecast)

        db.commit()
    except RuntimeError as e:      # falta scikit-learn
        db.rollback()
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:        # datos insuficientes
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Datos insuficientes: {e}")
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error entrenando: {e}")

    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "entrenado_en": datetime.now(timezone.utc).isoformat(),
        "churn": {
            "n_alumnos": meta_churn["n_alumnos"],
            "n_abandonados": meta_churn["n_abandonados"],
            **meta_churn["metricas_test"],
            # Métricas más estables (media ± std de 5 folds); ver ml/entrenar.py
            "cross_validation": meta_churn.get("cross_validation", {}),
        },
        "forecast": {
            "n_meses": meta_forecast["n_meses"],
            **meta_forecast["metricas_train"],
        },
        "persistidos": [guardado_churn, guardado_forecast],
        "modelos_vigentes": info_modelos(db, tenant_id),
    }
