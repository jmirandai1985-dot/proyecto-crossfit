"""Anti-divergencia entre Reportes (vivo) y el BI (persistido).

Contexto: MRR, ingresos del mes, ocupacion promedio y retencion/churn se
calculaban dos veces (una en vivo en `reportes.py`, otra en `kpis_populate.py`)
con SQL duplicado que podia divergir. Desde el refactor ambos consumen
`app/services/metricas_service.py`.

Este test fija lo que DEBE seguir siendo igual, para el MES EN CURSO:

  1. Integridad del guardado: lo que devuelve POST /kpis/populate/monthly es lo
     que queda en `monthly_kpis` (GET /kpis/mensual).
  2. Anti-divergencia entre pantallas: el valor vivo de GET /reportes/ coincide
     con el persistido para las metricas con el MISMO periodo
     - ingresos del mes  -> reportes.ingresoMensual   == monthly_kpis.ingresos_total
     - ocupacion promedio -> reportes.asistenciaPromedio == monthly_kpis.ocupacion_promedio
  3. Rango de la retencion: cohorte -> None o 0-100 (el bug viejo daba 7600%).

El MRR NO se compara entre pantallas a proposito: Reportes lo calcula "hasta
hoy" y el populate "al cierre del mes", asi que difieren por PERIODO (por
diseno, documentado en metricas_service). Su integridad si se verifica en (1).

Correr:
  API_BASE=http://localhost:8001/api/v1 N8N_API_KEY=<clave test> pytest tests/test_metricas_compartidas.py
  (o con run_tests.bat, que ya apunta a localhost:8000)
"""
import os
from datetime import date

import pytest
import requests

API_BASE = os.environ.get("API_BASE", "http://localhost:8000/api/v1")
TENANT_ID = 1
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")


def _token_admin():
    from app.core.security import create_access_token
    return create_access_token({
        "usuario_id": 1, "tenant_id": TENANT_ID,
        "rol": "administrador", "correo": "admin@test.com",
    })


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_token_admin()}"}


def test_reportes_y_populate_no_divergen(admin_headers):
    if not N8N_API_KEY:
        pytest.skip("N8N_API_KEY no esta en el entorno de tests")

    hoy = date.today()
    periodo = f"year={hoy.year}&month={hoy.month}"

    # 1) el populate calcula y persiste
    pop = requests.post(f"{API_BASE}/kpis/populate/monthly?{periodo}",
                        headers={"X-N8N-API-Key": N8N_API_KEY}, timeout=120)
    assert pop.status_code == 200, pop.text
    valores = pop.json()["valores"]

    # 2) la fila persistida
    mensual = requests.get(f"{API_BASE}/kpis/mensual?{periodo}",
                           headers=admin_headers, timeout=60)
    assert mensual.status_code == 200, mensual.text
    fila = mensual.json()

    # 3) la vista viva de Reportes
    viv = requests.get(f"{API_BASE}/reportes/?tenant_id={TENANT_ID}",
                       headers=admin_headers, timeout=60)
    assert viv.status_code == 200, viv.text
    reportes = viv.json()

    # (1) integridad del guardado (incluye MRR)
    assert float(fila["ingresos_total"]) == float(valores["ingresos_total"])
    assert float(fila["ocupacion_promedio"]) == float(valores["ocupacion_promedio"])
    assert float(fila["mrr"]) == float(valores["mrr"])

    # (2) anti-divergencia: mismo numero en las dos pantallas
    assert float(reportes["ingresoMensual"]) == float(valores["ingresos_total"]), (
        "ingresos del mes diverge: Reportes="
        f"{reportes['ingresoMensual']} vs populate={valores['ingresos_total']}")
    assert float(reportes["asistenciaPromedio"]) == float(valores["ocupacion_promedio"]), (
        "ocupacion diverge: Reportes="
        f"{reportes['asistenciaPromedio']} vs populate={valores['ocupacion_promedio']}")

    # (3) la retencion es de cohorte: acotada, nunca un 7600%
    assert reportes["retencion"] is None or 0 <= reportes["retencion"] <= 100, (
        f"retencion de Reportes fuera de rango: {reportes['retencion']}")
    ret_pop = valores.get("retencion_pct")
    assert ret_pop is None or 0 <= ret_pop <= 100, (
        f"retencion del populate fuera de rango: {ret_pop}")
