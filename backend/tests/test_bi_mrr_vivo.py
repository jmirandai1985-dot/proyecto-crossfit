"""KPIs → Inteligencia de Negocio: la tarjeta "Ingresos recurrentes mensuales" quedó en "— CLP".

Regresión reportada en PROD (2026-09-29) por el commit af77de2: ese commit cambió la fuente
del MRR de la tarjeta —que antes se leía del data mart MENSUAL (`GET /kpis/mensual`)— por la
fila del mes por defecto del índice `GET /kpis/mensual/periodos`. Si esa fila no existe (el
mes en curso todavía no cerró, el backfill no corrió) o el índice falla, la tarjeta se queda
sin número ("— CLP") aunque el ingreso recurrente VIGENTE HOY lo calcula el backend en vivo:
`metricas_service.mrr(db, tenant, hoy)` — la MISMA definición que muestran el dashboard y
Reportes.jsx (precio de lista de los planes con suscripción vigente hoy).

El arreglo: el MRR del BI es el de HOY y sale de `GET /reportes/` (una request que la pestaña
ya hacía para el ARPU), así que no depende de `monthly_kpis`.

Lo que fija este archivo:
  A. GUARD de `reportes.py`: el MRR se calcula EN VIVO en la request con
     `metricas.mrr(db, tenant_id, ahora.date())` y se expone como `"mrr"`; el módulo no
     consulta `monthly_kpis` (el MRR del BI no puede depender del data mart mensual).
  B. GUARD de `frontend/src/pages/admin/Kpis.jsx`: el cargador de la pestaña BI toma el MRR
     de `/api/v1/reportes/` y NO de `/api/v1/kpis/mensual/periodos` (se miran sólo las líneas
     de CÓDIGO: los comentarios del arreglo nombran la fuente vieja a propósito).
  C. IN-PROCESS (espía + sesión TEST): el endpoint devuelve EXACTAMENTE el valor de
     `metricas.mrr` y lo pide con la fecha de HOY en Chile; en el mismo momento, el MRR del
     mes que devuelve `/kpis/mensual` sigue siendo el de `monthly_kpis`: las dos fuentes son
     independientes (si el data mart mensual estuviera vacío, el BI igual tiene número).
  D. INTEGRACIÓN (TEST, puerto 8001): `GET /reportes/` devuelve el mismo número que
     `metricas.mrr` con la fecha de hoy, y `GET /kpis/mensual/periodos` sigue mostrando el
     MRR del mes cerrado (otra fuente, otro período) — se reportan ambos valores.

Ninguna prueba escribe en la base: las partes C/D sólo leen (y C pisa `metricas.mrr` en
memoria, con `monkeypatch`).

Correr (API de TEST en 8001; `--noconftest` porque este archivo no usa el servidor de 8000):
    ENVIRONMENT=test API_BASE=http://localhost:8001/api/v1 ^
      py -3.12 -m pytest tests/test_bi_mrr_vivo.py -q --noconftest
"""
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402
import requests  # noqa: E402

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api/v1")
HOST = API_BASE.replace("/api/v1", "")
TENANT_ID = 1
KPI_JSX = REPO / "frontend" / "src" / "pages" / "admin" / "Kpis.jsx"
REPORTES_PY = BACKEND / "app" / "api" / "v1" / "reportes.py"

VALOR_VIVO_FALSO = 424242.0     # lo que devuelve el espía de `metricas.mrr` en C


def _token_admin(tenant_id: int = TENANT_ID) -> str:
    from app.core.security import create_access_token
    return create_access_token({
        "usuario_id": 1, "tenant_id": tenant_id,
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
def db():
    """Sesión SQLAlchemy contra la MISMA rama TEST que ve la API (falla cerrado).

    Se usa para leer `monthly_kpis` y para llamar los endpoints in-process (C). El
    guard `is_test_db_url` es el mismo criterio de `/debug/db-url`: si el `.env` de
    turno apunta a PROD, el test NO corre (nunca se toca PROD desde los tests).
    """
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(definí ENVIRONMENT=test / revisá .env.test)")
    session = SessionLocal()
    yield session
    session.close()


# ── Código sin comentarios (los guards miran CÓDIGO, no la prosa que explica) ──
def _sin_comentarios(texto: str) -> str:
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return re.sub(r"//[^\n]*", "", texto)


def _bloque(texto: str, inicio: str, fin: str) -> str:
    i = texto.index(inicio)
    return texto[i:texto.index(fin, i)]


# ── A. reportes.py: el MRR es el de HOY y se calcula en la request ────────────
def test_a_reportes_calcula_el_mrr_en_vivo_con_la_fecha_de_hoy():
    codigo = _sin_comentarios(REPORTES_PY.read_text(encoding="utf-8"))

    assert re.search(r"mrr\s*=\s*metricas\.mrr\(\s*db,\s*tenant_id,\s*ahora\.date\(\)\s*\)",
                     codigo), "el MRR tiene que salir de metricas.mrr con la fecha de hoy"
    assert '"mrr": mrr' in codigo, "el endpoint tiene que exponer el MRR como `mrr`"
    assert "MonthlyKpi" not in codigo, (
        "GET /reportes/ no debe leer monthly_kpis: el MRR del BI es el VIVO (de hoy) "
        "y el data mart mensual es otra fuente (otro período)")


# ── B. Kpis.jsx: el MRR del BI sale de /reportes/ (no del índice de períodos) ──
def test_b_el_bi_toma_el_mrr_de_reportes_y_no_del_indice_de_periodos():
    fuente = KPI_JSX.read_text(encoding="utf-8")
    bloque = _sin_comentarios(
        _bloque(fuente, "const cargarBi = useCallback(", "}, [tenant_id]);"))

    assert "/api/v1/reportes/" in bloque, "la pestaña BI tiene que pedir /reportes/"
    assert re.search(r"setMrrBi\(\s*rRep\?\.data\?\.mrr", bloque), (
        "el MRR de la tarjeta tiene que salir de la respuesta de /reportes/")
    assert "mensual/periodos" not in bloque, (
        "el MRR del BI no puede volver a depender de /kpis/mensual/periodos "
        "(era la regresión: sin esa fila, la tarjeta quedaba en '— CLP')")
    assert "periodos" not in bloque, "el cargador del BI no usa el índice de meses"


# ── C. In-process: el valor es el de metricas.mrr(HOY) y el del mes es otro ────
def test_c_el_mrr_del_bi_es_el_de_hoy_y_no_el_del_mes_cerrado(monkeypatch, db):
    from app.api.v1 import kpis, reportes
    from app.models.monthly_kpis import MonthlyKpi
    from app.utils.santiago import hoy_santiago

    hoy = hoy_santiago()
    llamadas = []

    def mrr_espia(sesion, tenant_id, hasta):
        llamadas.append((tenant_id, hasta))
        return VALOR_VIVO_FALSO

    monkeypatch.setattr(reportes.metricas, "mrr", mrr_espia)
    datos = reportes.obtener_reportes_analytics(
        tenant_id=TENANT_ID, db=db,
        current_user={"tenant_id": TENANT_ID, "rol": "administrador"})

    assert datos["mrr"] == VALOR_VIVO_FALSO, "el endpoint devuelve el MRR vivo"
    assert llamadas == [(TENANT_ID, hoy)], (
        f"el MRR se pide UNA vez y con la fecha de HOY en Chile: {llamadas}")

    # El data mart mensual sigue siendo su propia fuente: leer el mes cerrado NO
    # devuelve el valor vivo (por eso el BI no puede depender de esa fila).
    fila = db.query(MonthlyKpi).filter(
        MonthlyKpi.tenant_id == TENANT_ID).order_by(
        MonthlyKpi.year.desc(), MonthlyKpi.month.desc()).first()
    if fila is None:
        pytest.skip("monthly_kpis está vacía en TEST: no hay mes con el que comparar")
    mes = kpis.get_kpis_mensual(year=fila.year, month=fila.month, db=db,
                                current_user={"tenant_id": TENANT_ID,
                                              "rol": "administrador"})
    assert mes["mrr"] == float(fila.mrr)
    assert mes["mrr"] != VALOR_VIVO_FALSO, (
        "monthly_kpis y el MRR vivo son fuentes distintas (períodos distintos)")


# ── D. Integración: la API responde el MRR vivo y el del mes, por separado ─────
def test_d_la_api_devuelve_el_mrr_vivo_y_el_del_mes_por_separado(admin_headers, db):
    from app.services import metricas_service
    from app.utils.santiago import hoy_santiago

    vivo_en_bd = metricas_service.mrr(db, TENANT_ID, hoy_santiago())

    r = requests.get(f"{API_BASE}/reportes/",
                     params={"tenant_id": TENANT_ID}, headers=admin_headers, timeout=60)
    assert r.status_code == 200, r.text[:300]
    mrr_api = r.json().get("mrr")
    assert isinstance(mrr_api, (int, float)), "el MRR tiene que venir numérico"
    assert float(mrr_api) == pytest.approx(vivo_en_bd), (
        f"GET /reportes/ ({mrr_api}) tiene que ser metricas.mrr(HOY) ({vivo_en_bd})")

    p = requests.get(f"{API_BASE}/kpis/mensual/periodos", headers=admin_headers, timeout=60)
    assert p.status_code == 200, p.text[:300]
    default = p.json().get("default")
    fila = next((x for x in p.json().get("periodos", [])
                 if default and x["year"] == default["year"]
                 and x["month"] == default["month"]), None)
    assert fila is not None, "TEST tiene que tener al menos un mes cerrado con datos"
    print(f"\nMRR vivo (hoy) = {mrr_api} · MRR del mes {fila['year']}-{fila['month']} "
          f"= {fila['mrr']} (la tarjeta del BI muestra el primero)")
