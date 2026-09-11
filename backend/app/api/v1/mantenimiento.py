"""Endpoints n8n para disparar el mantenimiento (diario / mensual).

Protegidos con el header `X-N8N-API-Key` (= settings.N8N_API_KEY). Pensados para
que n8n dispare por HTTP los jobs que normalmente corre el contenedor
`maintenance` vía cron (`maintenance/run_daily.py` y `maintenance/run_monthly.py`).

Nota: los imports de `maintenance.*` son PEREZOSOS (dentro del handler) para no
arrastrar sus efectos colaterales (configuración de logging / sys.path) al
importar la app.
"""
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.config import settings

router = APIRouter(prefix="/api/v1/mantenimiento", tags=["Mantenimiento"])


def _verificar_api_key_n8n(
    x_n8n_api_key: str = Header(default="", alias="X-N8N-API-Key"),
) -> bool:
    """Valida `X-N8N-API-Key` contra settings.N8N_API_KEY.

    Se exige que N8N_API_KEY esté configurada (si está vacía NO se permite el
    acceso, para evitar el bypass de `compare_digest("", "")`).
    """
    esperada = settings.N8N_API_KEY
    if not esperada or not secrets.compare_digest(esperada, x_n8n_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida para el endpoint de n8n",
        )
    return True


@router.post("/n8n/ejecutar-diario")
def n8n_ejecutar_diario(_auth: bool = Depends(_verificar_api_key_n8n)):
    """Dispara el job DIARIO de mantenimiento (`maintenance.run_daily.run`).

    Ejecuta: backup + planes vencidos + huérfanas + health + Neon usage.
    `run()` no devuelve valor; se responde un resumen del disparo.
    """
    from maintenance.run_daily import run as run_daily
    run_daily()
    return {"status": "ok", "resultado": {"job": "diario", "ejecutado": True}}


@router.post("/n8n/ejecutar-mensual")
def n8n_ejecutar_mensual(_auth: bool = Depends(_verificar_api_key_n8n)):
    """Dispara el job MENSUAL de mantenimiento (`maintenance.run_monthly.run`).

    Ejecuta: todo lo diario + integridad + estadísticas + rotación.
    `run()` no devuelve valor; se responde un resumen del disparo.
    """
    from maintenance.run_monthly import run as run_monthly
    run_monthly()
    return {"status": "ok", "resultado": {"job": "mensual", "ejecutado": True}}
