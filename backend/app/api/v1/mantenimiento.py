"""Endpoints n8n para disparar el mantenimiento (diario / mensual).

Protegidos con el header `X-N8N-API-Key` (= settings.N8N_API_KEY) **y** por una guarda de
entorno: fuera de TEST la ruta no existe (404). Pensados para que n8n dispare por HTTP los
jobs que normalmente corre el contenedor `maintenance` vía cron
(`maintenance/run_daily.py` y `maintenance/run_monthly.py`).

Nota: los imports de `maintenance.*` son PEREZOSOS (dentro del handler) para no
arrastrar sus efectos colaterales (configuración de logging / sys.path) al
importar la app.
"""
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.config import settings

# ── Guarda de entorno (H4) ───────────────────────────────────────────────────
# En PROD la imagen del web service (`Dockerfile.render`) NO copia `maintenance/`, así que
# estos endpoints morían con un 500 al no poder importar el módulo. La guarda lo adelanta y
# lo hace explícito: fuera de TEST se responde 404 —como si la ruta no existiera— ANTES de
# mirar la API key (no se filtra que el endpoint existe) y sin ejecutar nada. Es una
# dependencia de ROUTER a propósito: cubre los 2 endpoints actuales y cualquier endpoint
# nuevo que se agregue abajo (fail-closed).
# Mismo criterio de lectura/normalización que `app/core/config.py` (`_ENVIRONMENT`): sin
# `ENVIRONMENT` definido NO se asume TEST, se niega.
_ENTORNO = (os.getenv("ENVIRONMENT") or "").strip().lower()


def _solo_test() -> None:
    """Permite el paso sólo con ENVIRONMENT=test; si no, 404."""
    if _ENTORNO != "test":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(prefix="/api/v1/mantenimiento", tags=["Mantenimiento"],
                   dependencies=[Depends(_solo_test)])


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
