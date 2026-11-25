"""KPIs del MES EN CURSO: `GET /api/v1/kpis/mes-en-curso` (test AISLADO).

QUÉ FIJA Y POR QUÉ:

  * La ventana es el MES EN CURSO en America/Santiago: del día 1 al DÍA DE HOY.
    Las tarjetas "Conversión", "Asistencia real" y "Ocupación" del Dashboard ya no
    muestran el último mes cerrado (éste sigue en la pestaña KPIs).
  * Los tres cálculos salen de las MISMAS funciones del populate
    (`calcular_embudo_conversion`, `calcular_asistencia_mes`,
    `metricas_service.ocupacion_promedio`): el endpoint no reimplementa SQL.
  * El `tenant_id` es el del token; no hay parámetro para pedir otro box.
  * `ids_prueba_mes` es interno del populate y NO se publica.
  * El dashboard NO aplica mínimo de base para publicar la conversión (antes
    ocultaba el porcentaje hasta 5 alumnos de prueba y mostraba "n/d").

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_kpis_mes_en_curso.py -q --noconftest
"""
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import kpis                                  # noqa: E402
from app.core.dependencies import get_current_user            # noqa: E402

RAIZ = BACKEND.parent


def test_usa_el_mes_en_curso_hasta_hoy_y_devuelve_los_conteos(monkeypatch):
    llamadas = {}

    def falso_embudo(db, tenant_id, inicio, fin):
        llamadas["embudo"] = (tenant_id, inicio, fin)
        return {"alumnos_prueba": 3, "alumnos_clase_prueba_ejecutada": 2,
                "alumnos_plan_comprado": 2, "conversion_rate": 66.67,
                "ids_prueba_mes": [1, 2, 3]}

    def falso_asistencia(db, tenant_id, inicio, fin):
        llamadas["asistencia"] = (tenant_id, inicio, fin)
        return {"asistentes": 80, "reservas": 100, "asistencia_promedio": 80.0}

    def falso_ocupacion(db, tenant_id, inicio, fin):
        llamadas["ocupacion"] = (tenant_id, inicio, fin)
        return 62.5

    monkeypatch.setattr(kpis, "calcular_embudo_conversion", falso_embudo)
    monkeypatch.setattr(kpis, "calcular_asistencia_mes", falso_asistencia)
    monkeypatch.setattr(kpis, "ocupacion_promedio", falso_ocupacion)
    monkeypatch.setattr(kpis, "hoy_santiago", lambda: date(2026, 11, 25))

    datos = kpis.get_kpis_mes_en_curso(db=object(), current_user={"tenant_id": 7})

    assert datos["year"] == 2026 and datos["month"] == 11
    assert datos["desde"] == "2026-11-01"
    assert datos["hasta"] == "2026-11-25"
    assert datos["alumnos_prueba"] == 3
    assert datos["alumnos_clase_prueba_ejecutada"] == 2
    assert datos["alumnos_plan_comprado"] == 2
    assert datos["conversion_rate"] == 66.67
    assert datos["asistentes"] == 80
    assert datos["reservas_confirmadas"] == 100
    assert datos["asistencia_promedio"] == 80.0
    assert datos["ocupacion_promedio"] == 62.5
    # Los TRES cálculos comparten ventana y tenant (no se puede colar otro box).
    assert llamadas["embudo"] == (7, date(2026, 11, 1), date(2026, 11, 25))
    assert llamadas["asistencia"] == llamadas["embudo"]
    assert llamadas["ocupacion"] == llamadas["embudo"]
    # Detalle interno del populate: no se filtra al navegador.
    assert "ids_prueba_mes" not in datos


def test_la_ruta_exige_el_token_del_usuario():
    ruta = next(r for r in kpis.router.routes
                if getattr(r, "path", "").endswith("/mes-en-curso"))
    dependencias = [d.call for d in ruta.dependant.dependencies]
    assert get_current_user in dependencias
    assert ruta.methods == {"GET"}, "es sólo lectura: no escribe monthly_kpis"


def test_el_dashboard_no_oculta_la_conversion_por_minimo_de_base():
    fuente = (RAIZ / "frontend" / "src" / "components" / "dashboard"
              / "useResumenAdmin.js").read_text(encoding="utf-8")

    assert "MIN_BASE_CONVERSION" not in fuente, (
        "sin mínimo de base: con 1 alumno en prueba ya se publica la conversión")
    assert "pagaron plan" in fuente, (
        "el texto debe mostrar el conteo (\"2 de 3 pagaron\") además del porcentaje")
    assert "/api/v1/kpis/mes-en-curso" in fuente
