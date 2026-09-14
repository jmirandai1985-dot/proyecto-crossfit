"""Tests unitarios de la escalera de etiquetado de segmentación.

Puros (sin BD ni servidor): validan `ml/segmentacion.etiquetar_cluster` y
`_metricas_cluster` contra los perfiles REALES de PROD (K=5, semilla 42) y
contra los casos de frontera de cada regla.
"""
import pandas as pd
import pytest

import ml.segmentacion as seg


def perfil(dias, a30, a90, ant, susc, n=10):
    """Perfil de cluster sintético (medianas + % de suscripción)."""
    return {
        "n_alumnos": n,
        "pct_suscripcion_activa": susc,
        "medianas": {
            "dias_desde_ultima_asistencia": dias,
            "asistencias_ultimos_30_dias": a30,
            "asistencias_ultimos_90_dias": a90,
            "antiguedad_dias": ant,
            "tiene_suscripcion_activa": 1.0 if susc >= 0.5 else 0.0,
        },
    }


# ── Los 5 clusters REALES de PROD (106 alumnos, K=5, semilla 42) ────────────
@pytest.mark.parametrize("caso,esperado", [
    ((100.0, 0.0, 0.0, 213.0, 0.0), "ABANDONADO_PERDIDO"),     # n=11
    ((51.0, 0.0, 7.0, 137.0, 0.0), "ABANDONADO_RECUPERABLE"),  # n=18
    ((2.0, 14.0, 34.5, 158.0, 1.0), "ACTIVO_FIEL"),            # n=42
    ((2.0, 12.0, 14.0, 30.0, 1.0), "NUEVO"),                   # n=17
    ((10.5, 2.0, 9.0, 153.0, 1.0), "ACTIVO_EN_DECLIVE"),       # n=18
])
def test_clusters_reales_de_prod(caso, esperado):
    assert seg.etiquetar_cluster(perfil(*caso))[0] == esperado


# ── Fronteras de cada regla ─────────────────────────────────────────────────
@pytest.mark.parametrize("caso,esperado,regla", [
    # Umbral de abandono (45 días, el MISMO del label de churn):
    # 45 NO es abandono; 46 sí.
    ((45.0, 0.0, 2.0, 100.0, 0.0), "EN_RIESGO", "L3"),
    ((46.0, 0.0, 0.0, 100.0, 0.0), "ABANDONADO_PERDIDO", "L1"),
    # Split recuperable/perdido: med(a90) > 0 -> recuperable.
    ((46.0, 0.0, 0.5, 100.0, 0.0), "ABANDONADO_RECUPERABLE", "L2"),
    # % de suscripción: 0.49 es minoría sin plan; 0.50 NO.
    ((46.0, 0.0, 0.0, 100.0, 0.49), "ABANDONADO_PERDIDO", "L1"),
    ((46.0, 0.0, 0.0, 100.0, 0.50), "EN_RIESGO", "L3"),
    # Con plan activo nunca cae en abandono (misma lógica que el churn).
    ((100.0, 0.0, 0.0, 200.0, 1.0), "EN_RIESGO", "L3"),
    # NUEVO: antigüedad <= 60 y días <= 10 (ambos deben cumplirse).
    ((2.0, 12.0, 14.0, 60.0, 1.0), "NUEVO", "L4"),
    ((2.0, 12.0, 14.0, 61.0, 1.0), "ACTIVO_FIEL", "L6"),
    ((10.0, 12.0, 14.0, 30.0, 1.0), "NUEVO", "L4"),
    ((11.0, 12.0, 14.0, 30.0, 1.0), "ACTIVO_FIEL", "L6"),
    # Declive: menos de 8 asistencias en 30 días.
    ((5.0, 7.9, 20.0, 100.0, 1.0), "ACTIVO_EN_DECLIVE", "L5"),
    ((5.0, 8.0, 20.0, 100.0, 1.0), "ACTIVO_FIEL", "L6"),
])
def test_fronteras(caso, esperado, regla):
    arquetipo, regla_usada = seg.etiquetar_cluster(perfil(*caso))
    assert (arquetipo, regla_usada) == (esperado, regla)


def test_metricas_cluster():
    df = pd.DataFrame({
        "dias_desde_ultima_asistencia": [1, 3],
        "asistencias_ultimos_30_dias": [8, 12],
        "asistencias_ultimos_90_dias": [20, 30],
        "antiguedad_dias": [100, 200],
        "tiene_suscripcion_activa": [1, 0],
    })
    m = seg._metricas_cluster(df)
    assert m["n_alumnos"] == 2
    assert m["pct_suscripcion_activa"] == 0.5
    assert m["medianas"]["asistencias_ultimos_30_dias"] == 10.0
    assert m["medianas"]["dias_desde_ultima_asistencia"] == 2.0


def test_arquetipos_alineados_con_descripciones():
    """La escalera tiene EXACTAMENTE 6 tramos (los que persiste la tabla)."""
    assert len(seg.ARQUETIPOS) == 6
    assert set(seg.ARQUETIPOS) == set(seg.DESCRIPCIONES)
    assert len(set(seg.ARQUETIPOS)) == 6


def test_configuracion_del_modelo():
    assert seg.K_CLUSTERS == 5
    assert seg.RANDOM_STATE == 42
    assert seg.FEATURES_SEGMENTACION == [
        "dias_desde_ultima_asistencia",
        "asistencias_ultimos_30_dias",
        "asistencias_ultimos_90_dias",
        "antiguedad_dias",
        "tiene_suscripcion_activa",
    ]
    # El umbral se reusa del label de churn (una sola fuente de verdad).
    assert seg.UMBRAL_ABANDONO_DIAS == 45
