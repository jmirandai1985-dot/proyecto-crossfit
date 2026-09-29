"""Gráfico de estacionalidad de la pestaña Inteligencia de Negocio (KPIs).

Qué se publica: el ÍNDICE ESTACIONAL por mes del año (ene..dic) = valor del mes /
promedio del período, para ingresos y alumnos activos, calculado con los meses
CERRADOS de `monthly_kpis` (la pestaña Mensual poblada con el backfill de 12 meses).

Por qué el índice (y no los valores crudos): ingresos y alumnos se miden en unidades
distintas; el índice los pone en la MISMA escala (1.00 = un mes igual al promedio),
que es lo que se necesita para ver los meses fuertes y flojos y planificar campañas.

Lo que fija este archivo:
  A/B/C/D/E. UNIT (sin base ni red) de `_indice_estacional`, la función pura del
     endpoint: 12 meses completos, dos observaciones del mismo mes del calendario
     (promedio + `muestras`), sin datos, todos los valores en 0 (el caso REAL de
     `alumnos_activos_inicio`) y meses faltantes (el hueco se VE, no se interpola).
  F. INTEGRACIÓN: `GET /kpis/estacionalidad` responde 200 con 12 filas y el índice
     de cada mes es EXACTAMENTE valor / promedio (la fórmula publicada se recalcula
     en el test, así que un cambio de criterio se cae acá).
  G. El mes EN CURSO queda EXCLUIDO (es parcial) y la ventana termina en el mismo
     mes que el `default` de `/kpis/mensual/periodos`.
  H. La serie de alumnos se publica con `disponible` y `motivo` COHERENTES con los
     datos: si la columna tiene valores (distintos de 0) está disponible y sin
     motivo; si no, queda marcada como no disponible CON motivo (hoy está en 0 en
     todos los meses cerrados: el test lo documenta sin fijar el 0).
  I. Los valores crudos por mes son los del data mart: la fila de enero de la
     respuesta coincide con `alumnos_activos_inicio`/`ingresos_total` de enero
     (GET /kpis/mensual del mes que corresponda).

Requiere la API en TEST (el `/debug/db-url` tiene que decir `is_safe: true`). Solo
LEE: no escribe ni puebla nada.

Correr (API de TEST en 8001):
    API_BASE=http://localhost:8001/api/v1 ^
      py -3.12 -m pytest tests/test_kpis_estacionalidad.py -q
"""
import os

import pytest
import requests

API_BASE = os.environ.get("API_BASE", "http://localhost:8000/api/v1")
HOST = API_BASE.replace("/api/v1", "")
TENANT_ID = 1


def _token_admin():
    from app.core.security import create_access_token
    return create_access_token({
        "usuario_id": 1, "tenant_id": TENANT_ID,
        "rol": "administrador", "correo": "admin@test.com",
    })


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_token_admin()}"}


@pytest.fixture(scope="module", autouse=True)
def _guardia_test():
    """Falla CERRADO: sin confirmación de que la API es TEST, no se corre nada."""
    try:
        r = requests.get(f"{HOST}/debug/db-url", timeout=5)
    except requests.RequestException as e:
        pytest.skip(f"API no disponible en {HOST}: {e}")
    if r.status_code != 200 or not r.json().get("is_safe"):
        pytest.fail(f"El API en {HOST} NO es TEST ({r.status_code}): {r.text[:150]}")


@pytest.fixture(scope="module")
def estacionalidad(admin_headers):
    r = requests.get(f"{API_BASE}/kpis/estacionalidad", headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def _idx(filas):
    from app.api.v1.kpis import _indice_estacional
    return _indice_estacional(filas)


# ── A. UNIT: 12 meses, un valor por mes (el caso del backfill de 12 meses) ────
def test_a_doce_meses_da_un_indice_por_mes_del_calendario():
    # 10, 20, ..., 120: promedio 65. El índice de cada mes es valor / 65.
    filas = [{"month": m, "valor": m * 10} for m in range(1, 13)]
    r = _idx(filas)

    assert [x["mes"] for x in r["meses"]] == list(range(1, 13))
    assert [x["label"] for x in r["meses"]] == [
        "ene", "feb", "mar", "abr", "may", "jun",
        "jul", "ago", "sep", "oct", "nov", "dic"]
    assert r["promedio"] == 65.0 and r["observaciones"] == 12 and r["disponible"]
    assert all(x["muestras"] == 1 for x in r["meses"])
    assert r["meses"][0]["indice"] == round(10 / 65, 3)      # ene: flojo
    assert r["meses"][11]["indice"] == round(120 / 65, 3)    # dic: fuerte
    # La suma de los índices de un período completo es 12 (cada mes aporta 1/12
    # del promedio): es la propiedad que hace comparable el índice entre series.
    assert round(sum(x["indice"] for x in r["meses"]), 6) == 12.0


# ── B. UNIT: dos años del mismo mes => promedio de las observaciones ──────────
def test_b_dos_anios_del_mismo_mes_promedian_sus_observaciones():
    filas = ([{"month": 1, "valor": 100}, {"month": 1, "valor": 300}]   # ene: 200
             + [{"month": 2, "valor": 100}])                            # feb: 100
    r = _idx(filas)

    ene, feb = r["meses"][0], r["meses"][1]
    assert (ene["valor"], ene["muestras"]) == (200.0, 2)
    assert (feb["valor"], feb["muestras"]) == (100.0, 1)
    # Promedio de las 3 observaciones (no de los meses): (100+300+100)/3 = 166.67
    assert r["promedio"] == 166.67
    assert ene["indice"] == round(200 / (500 / 3), 3)
    assert r["meses"][2]["valor"] is None and r["meses"][2]["muestras"] == 0


# ── C. UNIT: sin datos => 12 filas vacías y NADA dividido por cero ───────────
def test_c_sin_datos_devuelve_doce_filas_vacias_y_sin_indice():
    r = _idx([])

    assert len(r["meses"]) == 12
    assert all(x["valor"] is None and x["indice"] is None for x in r["meses"])
    assert r["promedio"] is None and r["observaciones"] == 0
    assert r["disponible"] is False


# ── D. UNIT: todos los valores en 0 => NO disponible (el caso de los alumnos) ─
def test_d_todos_en_cero_queda_no_disponible_y_sin_indice():
    """`alumnos_activos_inicio` viene en 0 en los meses cerrados: publicar un índice
    ahí daría una línea PLANA que parece un dato. `disponible=False` lo dice."""
    r = _idx([{"month": m, "valor": 0} for m in range(1, 13)])

    assert r["disponible"] is False
    assert r["promedio"] == 0.0            # el dato crudo se informa igual
    assert all(x["valor"] == 0.0 for x in r["meses"])
    assert all(x["indice"] is None for x in r["meses"])


# ── E. UNIT: meses faltantes => huecos visibles (no se interpolan) ───────────
def test_e_los_meses_sin_observaciones_quedan_en_none():
    r = _idx([{"month": 3, "valor": 50}, {"month": 8, "valor": 150}])

    assert r["meses"][2]["valor"] == 50.0 and r["meses"][2]["indice"] == 0.5
    assert r["meses"][7]["valor"] == 150.0 and r["meses"][7]["indice"] == 1.5
    assert [x["mes"] for x in r["meses"] if x["valor"] is None] == \
        [1, 2, 4, 5, 6, 7, 9, 10, 11, 12]   # sólo marzo (3) y agosto (8) tienen dato


# ── F. INTEGRACIÓN: 12 filas y la fórmula publicada (valor / promedio) ───────
def test_f_el_indice_publicado_es_valor_sobre_promedio(estacionalidad):
    assert estacionalidad["fuente"] == "monthly_kpis (meses cerrados)"
    assert len(estacionalidad["filas"]) == 12
    assert estacionalidad["minimo_meses"] == 12
    assert estacionalidad["suficiente"] is True, (
        "TEST tiene los 12 meses del backfill; si no, correr "
        "POST /kpis/populate/monthly?backfill=12")
    assert estacionalidad["meses_con_datos"] >= 12

    promedio = estacionalidad["promedios"]["ingresos"]
    assert estacionalidad["ingresos"]["promedio"] == promedio
    for fila in estacionalidad["filas"]:
        if fila["ingresos"] is None:
            assert fila["indice_ingresos"] is None
            continue
        assert fila["indice_ingresos"] == pytest.approx(
            round(fila["ingresos"] / promedio, 3)), fila
        assert fila["indice_ingresos"] > 0
    # Con un año de historia (un solo perfil) la suma de los índices da 12.
    assert sum(f["indice_ingresos"] for f in estacionalidad["filas"]) == \
        pytest.approx(12, abs=0.05)


# ── G. El mes EN CURSO (parcial) queda fuera y la ventana es la del mart ─────
def test_g_excluye_el_mes_en_curso_y_termina_en_el_ultimo_mes_cerrado(
        estacionalidad, admin_headers):
    from app.utils.santiago import hoy_santiago

    hoy = hoy_santiago()
    assert estacionalidad["excluye_mes_en_curso"] == {"year": hoy.year, "month": hoy.month}

    p = requests.get(f"{API_BASE}/kpis/mensual/periodos", headers=admin_headers, timeout=60)
    assert p.status_code == 200, p.text[:300]
    default = p.json()["default"]
    assert estacionalidad["ventana"]["hasta"] == {"year": default["year"],
                                                  "month": default["month"]}
    # Un mes PARCIAL no puede ser el fin de la ventana de meses cerrados.
    assert estacionalidad["ventana"]["hasta"] != estacionalidad["excluye_mes_en_curso"]


# ── H. Alumnos: `disponible`/`motivo` COHERENTES con la columna del mart ────
def test_h_la_serie_de_alumnos_declara_si_esta_disponible(estacionalidad):
    serie = estacionalidad["alumnos_activos"]
    valores = [f["alumnos_activos"] for f in estacionalidad["filas"]]
    hay_dato = any(v not in (None, 0) for v in valores)

    assert serie["columna"] == "monthly_kpis.alumnos_activos_inicio"
    assert serie["observaciones"] == estacionalidad["meses_con_datos"]
    assert serie["disponible"] is hay_dato
    if hay_dato:
        assert serie["motivo"] is None
        assert any(f["indice_alumnos"] is not None for f in estacionalidad["filas"])
    else:
        # Hoy la columna está en 0 en TODOS los meses cerrados (el populate la llena
        # con el estado de HOY): se publica el 0 crudo con el motivo, sin índice.
        assert all(v == 0 for v in valores)
        assert serie["motivo"] and "estado de HOY" in serie["motivo"]
        assert all(f["indice_alumnos"] is None for f in estacionalidad["filas"])


# ── I. Los valores crudos por mes son los de `monthly_kpis` ──────────────────
def test_i_los_valores_por_mes_son_los_del_data_mart(estacionalidad, admin_headers):
    """Cruza la fila del último mes cerrado con el KPI de ESE mes (misma tabla, otra API)."""
    ventana = estacionalidad["ventana"]
    filas = {f["mes"]: f for f in estacionalidad["filas"]}
    mes = ventana["hasta"]["month"]

    if filas[mes]["muestras"] != 1:
        pytest.skip("la ventana tiene más de un año: la fila es el promedio de esos "
                    "meses del calendario, no el valor de un mes suelto")

    r = requests.get(f"{API_BASE}/kpis/mensual",
                     params={"year": ventana["hasta"]["year"], "month": mes},
                     headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text[:300]
    kpi = r.json()
    assert filas[mes]["ingresos"] == pytest.approx(kpi["ingresos_total"])
    assert filas[mes]["alumnos_activos"] == pytest.approx(kpi["alumnos_activos_inicio"])
