"""Endpoints de ML: reentrenamiento automático de los modelos (churn/forecast).

PROTEGIDO con el MISMO mecanismo que `app/api/v1/kpis_populate.py`: header
`X-N8N-API-Key` (= settings.N8N_API_KEY). Lo llama **n8n** automáticamente
(una vez al mes) — NO un admin logueado, por eso no usa `get_current_admin`.

Los modelos se guardan en la tabla `ml_modelos` (BD, no disco) para que
sobrevivan a los reinicios/redeploys de Render.

INDEPENDENCIA (churn / forecast): cada modelo se entrena y persiste en su
PROPIO bloque try/except con su propio `commit`. Si uno falla (p. ej. en PROD
todavía no hay >= 6 meses de transacciones y el forecast no puede entrenar),
el otro se guarda igual y el HTTP sigue siendo 200. Sólo se responde con error
(409/500/503) cuando fallan los DOS.
"""
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db

router = APIRouter(prefix="/api/v1/ml", tags=["ML"])

logger = logging.getLogger(__name__)

TENANT_ID = 1   # hoy hay un solo box; parametrizable luego (igual que kpis_populate)

# Severidad a reportar cuando fallan los DOS modelos (se usa el más grave).
# 500 (error inesperado, a investigar) > 503 (falta scikit-learn) > 409 (datos).
_SEVERIDAD = {409: 1, 503: 2, 500: 3}


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


def _clasificar_error(e: Exception) -> tuple:
    """Mapea la excepción del entrenamiento a `(status_http, detalle)`.

    Mismos códigos que usaba el endpoint antes del rediseño (compatibilidad):
    `RuntimeError` -> 503 (falta scikit-learn); `ValueError` -> 409 (datos
    insuficientes); cualquier otra -> 500.
    """
    if isinstance(e, RuntimeError):
        return 503, str(e)
    if isinstance(e, ValueError):
        return 409, f"Datos insuficientes: {e}"
    return 500, f"{type(e).__name__}: {e}"


def _resumen_churn(meta: dict) -> dict:
    """Métricas del churn para la respuesta (mismas claves que antes)."""
    return {
        "n_alumnos": meta["n_alumnos"],
        "n_abandonados": meta["n_abandonados"],
        **meta["metricas_test"],
        # Métricas más estables (media ± std de 5 folds); ver ml/entrenar.py
        "cross_validation": meta.get("cross_validation", {}),
    }


def _resumen_forecast(meta: dict) -> dict:
    """Métricas del forecast para la respuesta (mismas claves que antes)."""
    return {"n_meses": meta["n_meses"], **meta["metricas_train"]}


def _entrenar_y_guardar(db, tenant_id, tipo, entrenar, guardar,
                        resumen) -> tuple:
    """Entrena + persiste UN modelo de forma AISLADA (no propaga excepciones).

    Devuelve `(bloque, codigo_error)`:
      - éxito   -> `codigo_error = None`; ya está COMMITEADO en `ml_modelos`.
      - fracaso -> `codigo_error` = HTTP sugerido (409/500/503) y la
                   transacción quedó revertida (sin restos a medias).

    El `db.rollback()` del fracaso es lo que da la independencia: limpia la
    transacción fallida para que el OTRO modelo no herede una sesión rota, y
    NO deshace lo que el otro ya commiteó (p. ej. churn).
    """
    try:
        modelo, meta = entrenar(db, tenant_id)
        persistido = guardar(db, tenant_id, tipo, modelo, meta)
        db.commit()   # commit PROPIO de este modelo (ver docstring del módulo)
    except Exception as e:
        db.rollback()
        codigo, detalle = _clasificar_error(e)
        logger.warning("reentrenar: %s falló (HTTP %s): %s", tipo, codigo, e)
        return {"status": "error", "codigo": codigo, "detail": detalle}, codigo

    logger.info("reentrenar: %s ok (%s bytes, %s)",
                tipo, persistido["bytes"], persistido["fecha_entrenamiento"])
    return {"status": "ok", **resumen(meta), "persistido": persistido}, None


@router.post("/reentrenar")
def reentrenar_modelos(
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Reentrena churn + forecast y los persiste en `ml_modelos` (upsert).

    Los dos modelos son INDEPENDIENTES: cada uno entrena y commitea por su
    lado, así que si uno falla el otro se guarda igual y el HTTP sigue siendo
    200. Sólo si fallan los DOS se devuelve error (el más grave entre
    409/503/500) con el detalle de cada uno en `detail`.

    Respuesta 200: `{"status": "ok" | "parcial", "churn": {..}, "forecast": {..}}`
    donde cada bloque es `{"status": "ok", ...métricas, "persistido": {..}}` o
    `{"status": "error", "codigo": <http>, "detail": "<motivo>"}`.
    """
    # Import perezoso: si falta scikit-learn o `ml/`, la app arranca igual y
    # sólo falla este endpoint (503) en vez de romper el router entero.
    try:
        from ml.entrenar import entrenar_churn, entrenar_forecast
        from ml.persistencia import guardar_modelo, info_modelos
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"ML no disponible: {e}")

    tenant_id = TENANT_ID

    # ── Cada modelo, en su propio try/except + commit ────────────────────────
    # Si el forecast falla (ej. PROD sin 6 meses de transacciones) el churn ya
    # quedó commiteado en `ml_modelos` y sobrevive.
    churn, error_churn = _entrenar_y_guardar(
        db, tenant_id, "churn", entrenar_churn, guardar_modelo, _resumen_churn)
    forecast, error_forecast = _entrenar_y_guardar(
        db, tenant_id, "forecast", entrenar_forecast, guardar_modelo,
        _resumen_forecast)

    exitos = [b for b in (churn, forecast) if b["status"] == "ok"]
    payload = {
        "status": "ok" if len(exitos) == 2 else "parcial",
        "tenant_id": tenant_id,
        "entrenado_en": datetime.now(timezone.utc).isoformat(),
        "churn": churn,
        "forecast": forecast,
        "modelos_vigentes": info_modelos(db, tenant_id),
    }

    # Sólo se falla si NINGUNO de los dos pudo entrenar/guardarse.
    if not exitos:
        codigo = max((error_churn, error_forecast),
                     key=lambda c: _SEVERIDAD.get(c, 3))
        payload["status"] = "error"
        logger.error("reentrenar: churn Y forecast fallaron (HTTP %s)", codigo)
        # El detalle va completo en `detail` para que n8n loguee ambos motivos.
        raise HTTPException(status_code=codigo, detail=payload)

    if len(exitos) == 1:
        logger.warning("reentrenar: resultado PARCIAL (churn=%s, forecast=%s)",
                       churn["status"], forecast["status"])

    return payload
