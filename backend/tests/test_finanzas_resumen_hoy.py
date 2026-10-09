"""Caja del DÍA (KPI "Ingresos de hoy" del panel admin móvil): cálculo puro + contrato.

Qué fija este archivo (sin red y sin base de datos):

  A. `app.utils.caja.resumir_dia` — la aritmética del día: ingresos, egresos, neto y
     CUÁNTOS pagos (los egresos no son pagos; un día sin movimientos da ceros, no None).
     Un `tipo` desconocido se IGNORA (nunca se inventa un número).
  B. El endpoint `GET /finanzas/resumen-hoy` suma la MISMA tabla que alimenta los KPIs
     (`transacciones_financieras`) y filtra por el día de CHILE (`hoy_santiago`), no por
     el día del servidor (que corre en UTC). Y no toca ningún KPI existente.
  C. Los TRES caminos que escriben caja cargan `fecha=hoy_santiago()`: si alguno usara
     `date.today()` (UTC), el ingreso de la noche caería en el "mañana" de Chile y la
     tarjeta mostraría 0 con la plata ya cobrada.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_finanzas_resumen_hoy.py -q --noconftest
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.utils.caja import resumir_dia   # noqa: E402  (después del sys.path)

RAIZ = Path(__file__).resolve().parents[2]


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


# ── A. Cálculo ───────────────────────────────────────────────────────────────

def test_a1_suma_ingresos_egresos_y_pagos():
    r = resumir_dia([("ingreso", 186000, 4), ("egreso", 20000, 2)])
    assert r["ingresos"] == 186000.0
    assert r["egresos"] == 20000.0
    assert r["neto"] == 166000.0
    assert r["pagos"] == 4, "pagos = cantidad de INGRESOS del día"


def test_a2_dia_sin_movimientos_devuelve_ceros_no_none():
    r = resumir_dia([])
    assert r == {"ingresos": 0.0, "egresos": 0.0, "neto": 0.0, "pagos": 0}


def test_a3_los_egresos_no_cuentan_como_pagos():
    r = resumir_dia([("egreso", 5000, 3)])
    assert r["pagos"] == 0 and r["ingresos"] == 0.0 and r["egresos"] == 5000.0


def test_a4_neto_puede_ser_negativo_no_se_recorta():
    r = resumir_dia([("ingreso", 1000, 1), ("egreso", 4000, 1)])
    assert r["neto"] == -3000.0


def test_a5_tipo_desconocido_se_ignora():
    r = resumir_dia([("ingreso", 1000, 1), ("ajuste", 99999, 7)])
    assert r["ingresos"] == 1000.0 and r["pagos"] == 1 and r["egresos"] == 0.0


def test_a6_valores_nulos_o_vacios_no_rompen_la_suma():
    # Las filas vienen de un GROUP BY: `total` puede ser None si la columna es NULL y
    # `n` (COUNT) nunca lo es, pero un float raro no debe tumbar la tarjeta.
    r = resumir_dia([("ingreso", None, None), ("ingreso", 5000, 1)])
    assert r["ingresos"] == 5000.0 and r["pagos"] == 1


# ── B. El endpoint: misma tabla de los KPIs + día de Chile ───────────────────

def test_b1_el_endpoint_existe_y_suma_la_tabla_de_los_kpis():
    fuente = _fuente("backend/app/api/v1/finanzas.py")
    assert '@router.get("/resumen-hoy")' in fuente
    assert "def resumen_caja_hoy(" in fuente
    assert "FROM transacciones_financieras" in fuente
    assert "current_user: dict = Depends(get_current_admin)" in fuente


def test_b2_el_filtro_del_dia_es_el_dia_de_chile():
    fuente = _fuente("backend/app/api/v1/finanzas.py")
    assert "from app.utils.santiago import hoy_santiago" in fuente
    assert "hoy = hoy_santiago()" in fuente
    assert "fecha = :hoy" in fuente
    # El día del servidor (UTC) cortaría mal toda la tarde/noche de Chile.
    assert "date.today()" not in fuente


def test_b3_no_se_tocan_los_kpis_existentes():
    fuente = _fuente("backend/app/api/v1/finanzas.py")
    # Nada de KPIs en este router: el nuevo endpoint es aditivo.
    assert "monthly_kpis" not in fuente
    assert "/kpis/" not in fuente
    # El bloque nuevo solo LEE (GET); no toca las tablas del data mart.
    bloque = fuente.split('@router.get("/resumen-hoy")')[1]
    assert "INSERT" not in bloque.upper()


def test_b4_el_tenant_sale_del_token_y_no_del_query():
    fuente = _fuente("backend/app/api/v1/finanzas.py")
    assert 'tenant_id = current_user["tenant_id"]' in fuente
    # El endpoint nuevo NO acepta tenant_id por query (patrón del resto de la API).
    bloque = fuente.split('@router.get("/resumen-hoy")')[1]
    assert "tenant_id: Optional[int]" not in bloque


# ── C. Los escritores de caja usan el mismo día (Chile) ──────────────────────

def test_c1_aprobar_solicitud_registra_la_caja_de_hoy_en_chile():
    fuente = _fuente("backend/app/api/v1/solicitudes_planes.py")
    assert "fecha=hoy_santiago()," in fuente


def test_c2_alta_de_suscripcion_registra_la_caja_de_hoy_en_chile():
    fuente = _fuente("backend/app/api/v1/suscripciones.py")
    assert "fecha=hoy_santiago()," in fuente
