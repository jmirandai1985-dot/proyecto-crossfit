"""Pestaña KPIs -> Mensual: el mes CON fila respondía 500 y la UI decía "Sin datos para el período".

Diagnóstico medido en TEST (2026-09-29): `monthly_kpis` tenía UNA fila (2026-08) y
`GET /kpis/mensual?year=2026&month=8` respondía **HTTP 500**:

    File "/app/app/api/v1/kpis.py", line 336, in get_kpis_mensual
        "churn_rate": float(kpi.churn_rate),
    TypeError: float() argument must be a string or a real number, not 'NoneType'

`monthly_kpis.churn_rate` es NULLABLE a propósito (migración 027: None = la cohorte
del mes no llega a la base mínima ⇒ "sin dato", que NO es lo mismo que 0% de churn).
La pestaña pedía los últimos 6 meses con `Promise.allSettled`, descartaba el rechazo
del 500 y, con la serie vacía, mostraba "Sin datos para el período" aunque el mes
existiera.

Lo que fija este archivo:
  A. UNIT (sin red): `get_kpis_mensual` serializa `churn_rate = NULL` como `None`
     (antes: TypeError => 500) y sigue devolviendo los números cuando hay valor.
  B. INTEGRACIÓN: TODOS los meses de `/kpis/mensual/periodos` responden 200 y, si su
     churn_rate es null, la clave viene null (no ausente, no 0).
  C. `/kpis/mensual/periodos`: lista ascendente sin duplicados, `parcial` sólo en el
     MES EN CURSO (Chile) y `default` = último mes CERRADO con datos.
  D. BACKFILL idempotente: `POST /kpis/populate/monthly?backfill=12` deja los 12 meses
     (lo que falta después de un seed de 12 meses) y correrlo DOS veces recalcula los
     MISMOS valores sobre las MISMAS filas (upsert por tenant/año/mes).
  E. Validaciones de la API del backfill (422).

Requiere la API en TEST (el `/debug/db-url` tiene que decir `is_safe: true`) y
`N8N_API_KEY` para las partes que escriben/populate.

Correr:
    API_BASE=http://localhost:8001/api/v1 N8N_API_KEY=<clave> ^
      py -3.12 -m pytest tests/test_kpis_mensual_periodos.py -q
"""
import os
from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests

API_BASE = os.environ.get("API_BASE", "http://localhost:8000/api/v1")
HOST = API_BASE.replace("/api/v1", "")
TENANT_ID = 1
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")


def _token_admin():
    """Token de admin (el endpoint exige rol administrador y tenant del token)."""
    from app.core.security import create_access_token
    return create_access_token({
        "usuario_id": 1, "tenant_id": TENANT_ID,
        "rol": "administrador", "correo": "admin@test.com",
    })


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_token_admin()}"}


@pytest.fixture(scope="module")
def n8n_headers():
    if not N8N_API_KEY:
        pytest.skip("N8N_API_KEY no está en el entorno de tests")
    return {"X-N8N-API-KEY": N8N_API_KEY}


@pytest.fixture(scope="module", autouse=True)
def _guardia_test():
    """Falla CERRADO: si el API no confirma que está en TEST, estos tests no corren.

    Mismo criterio que `conftest.py` (que mira `/debug/db-url`): acá además `fail`
    en vez de seguir, porque el backfill ESCRIBE en `monthly_kpis`.
    """
    try:
        r = requests.get(f"{HOST}/debug/db-url", timeout=5)
    except requests.RequestException as e:
        pytest.skip(f"API no disponible en {HOST}: {e}")
    if r.status_code != 200 or not r.json().get("is_safe"):
        pytest.fail(f"El API en {HOST} NO es TEST ({r.status_code}): {r.text[:150]}")



# ── A. UNIT: el 500 del mes con `churn_rate` NULL (la causa raíz) ────────────
class _ConsultaFalsa:
    """Imita `db.query(MonthlyKpi).filter(...).first()` devolviendo una fila fija."""

    def __init__(self, fila):
        self._fila = fila

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._fila


class _SesionFalsa:
    """Sesión mínima: sólo lo que usa `get_kpis_mensual` (query().filter().first())."""

    def __init__(self, fila):
        self._fila = fila

    def query(self, *args, **kwargs):
        return _ConsultaFalsa(self._fila)


def _fila_mensual(**overrides):
    """Fila de `monthly_kpis` con TODOS los campos que serializa el endpoint."""
    base = dict(
        year=2026, month=8, alumnos_prueba=10,
        alumnos_clase_prueba_ejecutada=6, alumnos_plan_comprado=3,
        conversion_rate=Decimal("30.00"), alumnos_activos_inicio=0,
        alumnos_baja=0, churn_rate=None, mrr=Decimal("2439000"),
        ingresos_total=Decimal("4262000"), asistencia_promedio=Decimal("88.50"),
        frecuencia_semanal=Decimal("2.10"), ocupacion_promedio=Decimal("64.30"),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _get_kpis_mensual(fila):
    """Llama al endpoint REAL de `kpis.py` con una sesión falsa (sin red ni BD)."""
    from app.api.v1.kpis import get_kpis_mensual
    return get_kpis_mensual(
        year=fila.year, month=fila.month, db=_SesionFalsa(fila),
        current_user={"tenant_id": TENANT_ID, "rol": "administrador"})


def test_a_churn_null_no_rompe_el_endpoint_mensual():
    """`churn_rate` NULL (cohorte sin base) => null en el JSON, NO TypeError/500.

    Antes el `float(None)` tiraba el request completo: la pestaña perdía el mes
    entero (todas sus tarjetas), y con él su único dato => "Sin datos para el período".
    """
    resp = _get_kpis_mensual(_fila_mensual(churn_rate=None))
    assert resp["churn_rate"] is None
    assert resp["year"] == 2026 and resp["month"] == 8
    # El resto del mes sigue llegando (el 500 borraba TODO el payload).
    assert resp["mrr"] == 2439000.0
    assert resp["ingresos_total"] == 4262000.0
    assert resp["ocupacion_promedio"] == 64.30


def test_a2_churn_con_valor_sigue_siendo_numero():
    """Contraprueba: con valor real el campo sigue siendo float (no string ni null)."""
    resp = _get_kpis_mensual(_fila_mensual(churn_rate=Decimal("7.50")))
    assert resp["churn_rate"] == 7.5
    assert isinstance(resp["churn_rate"], float)


# ── B/C/F. INTEGRACIÓN: índice de períodos ───────────────────────────────────
def _periodos(admin_headers):
    r = requests.get(f"{API_BASE}/kpis/mensual/periodos",
                     headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_b_cada_mes_con_fila_responde_200(admin_headers):
    """NINGÚN mes de la tabla puede responder 500 (el bug: el mes con churn NULL)."""
    datos = _periodos(admin_headers)
    if not datos["periodos"]:
        pytest.skip("monthly_kpis vacía: correr POST /kpis/populate/monthly?backfill=12")

    for p in datos["periodos"]:
        r = requests.get(f"{API_BASE}/kpis/mensual", headers=admin_headers, timeout=60,
                         params={"year": p["year"], "month": p["month"]})
        assert r.status_code == 200, \
            f"{p['year']}-{p['month']}: HTTP {r.status_code} {r.text[:120]}"
        fila = r.json()
        # "sin dato" viaja como null (no como 0 % ni como clave ausente).
        assert "churn_rate" in fila
        assert fila["churn_rate"] is None or isinstance(fila["churn_rate"], (int, float))
        # El índice y el detalle del mismo mes dicen el mismo número.
        assert float(fila["mrr"]) == float(p["mrr"]), p


def test_c_periodos_ordenados_sin_duplicados_y_default_cerrado(admin_headers):
    """El índice de meses es lo que la pestaña usa para el selector y el default."""
    datos = _periodos(admin_headers)
    periodos = datos["periodos"]
    if not periodos:
        pytest.skip("monthly_kpis vacía")

    claves = [(p["year"], p["month"]) for p in periodos]
    assert claves == sorted(claves), "los períodos se listan del más viejo al más nuevo"
    assert len(claves) == len(set(claves)), "una fila por (año, mes): el upsert no duplica"

    # `parcial` sólo puede estar en el MES EN CURSO (el mes todavía no cerró).
    hoy = datos["hoy"]                      # 'YYYY-MM-DD' del calendario chileno
    actual = (int(hoy[:4]), int(hoy[5:7]))
    for p in periodos:
        assert p["parcial"] == ((p["year"], p["month"]) == actual), p
    assert (datos["actual"]["year"], datos["actual"]["month"]) == actual
    assert datos["actual"]["tiene_fila"] == any(p["parcial"] for p in periodos)

    # `default` = último mes CERRADO con datos (o el más nuevo si no hay cerrados).
    default = datos["default"]
    assert default is not None, "con filas en la tabla tiene que haber default"
    cerrados = [c for c in claves if c < actual]
    esperado = cerrados[-1] if cerrados else claves[-1]
    assert (default["year"], default["month"]) == esperado

    # El mes del default existe de verdad (200): es el que muestra la pestaña.
    r = requests.get(f"{API_BASE}/kpis/mensual", headers=admin_headers, timeout=60,
                     params={"year": default["year"], "month": default["month"]})
    assert r.status_code == 200, r.text


def test_f_periodos_exige_token():
    """Sin token no se filtra por tenant: 401 (mismo criterio que el resto de /kpis)."""
    r = requests.get(f"{API_BASE}/kpis/mensual/periodos", timeout=30)
    assert r.status_code == 401, r.text


# ── D. BACKFILL: 12 meses de una vez, idempotente ────────────────────────────
def _backfill(n8n_headers, **params):
    return requests.post(f"{API_BASE}/kpis/populate/monthly", params=params,
                         headers=n8n_headers, timeout=300)


def test_d_backfill_de_12_meses_es_idempotente(admin_headers, n8n_headers):
    """`?backfill=12` completa los meses que el job mensual nunca pobló (tras el seed
    de 12 meses la tabla tenía UN mes) y re-ejecutarlo recalcula los MISMOS valores
    sobre las MISMAS filas: upsert por (tenant, año, mes), sin duplicar."""
    r1 = _backfill(n8n_headers, backfill=12)
    assert r1.status_code == 200, r1.text
    cuerpo1 = r1.json()
    assert cuerpo1["status"] == "ok"
    assert cuerpo1["accion"] == "monthly_kpis upsert (backfill)"
    assert cuerpo1["meses_calculados"] == 12
    assert len(cuerpo1["resultados"]) == 12

    # Los 12 meses son consecutivos y terminan en el último mes CERRADO.
    claves = [(m["year"], m["month"]) for m in cuerpo1["resultados"]]
    assert claves == sorted(claves), claves
    for (a, m), (b, n) in zip(claves, claves[1:]):
        assert (b * 12 + n) - (a * 12 + m) == 1, f"salto entre {a}-{m} y {b}-{n}"

    # 2ª corrida: mismos meses y MISMOS valores (idempotencia real).
    r2 = _backfill(n8n_headers, backfill=12)
    assert r2.status_code == 200, r2.text
    assert r2.json()["resultados"] == cuerpo1["resultados"]

    # Quedaron EN LA TABLA: el índice las lista sin duplicados y sin huecos.
    despues = _periodos(admin_headers)
    claves_final = [(p["year"], p["month"]) for p in despues["periodos"]]
    assert len(claves_final) == len(set(claves_final)), "el backfill duplicó filas"
    ventana = [c for c in claves_final if claves[0] <= c <= claves[-1]]
    assert ventana == claves, f"el backfill dejó huecos: {claves} vs {ventana}"
    assert len(claves_final) >= 12, claves_final
    # Y el default sigue apuntando a un mes con datos.
    assert (despues["default"]["year"], despues["default"]["month"]) in claves_final


# ── E. Validaciones de la API del backfill ───────────────────────────────────
def test_e_validaciones_del_populate(n8n_headers):
    """Pedidos inválidos => 422 y NINGÚN mes calculado (no escribe nada)."""
    casos = {
        "year sin month": {"year": 2026},
        "backfill + mes puntual": {"backfill": 3, "year": 2026, "month": 8},
        "rango incompleto": {"desde_year": 2026, "desde_month": 8, "hasta_year": 2026},
        "rango invertido": {"desde_year": 2026, "desde_month": 8,
                            "hasta_year": 2026, "hasta_month": 7},
        "backfill 0": {"backfill": 0},
        "backfill 40 (> MAX)": {"backfill": 40},
        "rango de 45 meses (> MAX)": {"desde_year": 2023, "desde_month": 1,
                                      "hasta_year": 2026, "hasta_month": 9},
    }
    for nombre, params in casos.items():
        r = _backfill(n8n_headers, **params)
        assert r.status_code == 422, f"{nombre}: HTTP {r.status_code} {r.text[:120]}"


