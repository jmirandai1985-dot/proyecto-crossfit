"""D5 — movimientos faltantes y alias de nombre (decisión de negocio 2026-10-28).

QUÉ FIJA ESTE ARCHIVO
---------------------
1. Los ALIAS explícitos resuelven los nombres que el catálogo de la BD y las tablas escribieron
   distinto. Sin alias, `Split Jerk`, `Squat Clean`, `Squat Snatch`, `Rope Climb (Trepada)` y
   `Bear Crawl (Caminata)` NUNCA clasificaban (el match es por string exacto).
2. Los estándares nuevos existen y clasifican: Strict / Kipping Pull-up, Power Clean / Snatch,
   Split Jerk (alias del Jerk), Push Press, Ring Dips, Wall Ball Shot y Kettlebell Swing.
3. Fuente: los estándares nuevos están marcados como **estimados** (derivados de las reglas de
   extrapolación del propio archivo y del doc §5.2/§5.3/§5.5), salvo los que el doc declara.
4. D2: la gimnasia NO se clasifica sin género (antes se usaba la tabla masculina por defecto).
5. `movimiento_categoria.categoria_por_nombre` resuelve los alias (importa para D4: la categoría
   decide si el valor del RM son reps o kg).

Correr (aislado, sin DB):
    cd backend && py -3.12 -m pytest tests/test_nivel_alias.py -q --noconftest
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
RAIZ = BACKEND.parent
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


ALIAS = {
    "Split Jerk": "Jerk (Envión)",
    "Squat Clean": "Clean (Cargada)",
    "Squat Snatch": "Snatch (Arrancada)",
    "Rope Climb (Trepada)": "Rope Climb (Subida de cuerda usando los pies)",
    "Bear Crawl (Caminata)": "Bear Crawl (Caminata de oso)",
}


def test_los_alias_resuelven_a_la_clave_canonica():
    from app.services.nivel_service import clave_estandar

    for nombre, canonico in ALIAS.items():
        assert clave_estandar(nombre) == canonico
    # Un nombre sin alias se devuelve tal cual (no hay heurística de texto).
    assert clave_estandar("Back Squat (Sentadilla Trasera)") == "Back Squat (Sentadilla Trasera)"


def test_split_jerk_clasifica_con_la_tabla_del_jerk():
    from app.services.nivel_service import obtener_nivel_fuerza

    # 120 kg / 80 kg = 1.5 -> Elite en la tabla de Jerk (M: 0.5/0.9/1.2/1.5).
    r = obtener_nivel_fuerza("Split Jerk", 120, 80, "M")
    assert r["clasificable"] is True
    assert r["nivel"] == "Elite"


def test_squat_clean_y_squat_snatch_clasifican_como_los_lifts_completos():
    from app.services.nivel_service import obtener_nivel_fuerza

    # Squat Clean 120/80 = 1.5 -> Avanzado (Clean M: 0.6/1.0/1.3/1.6).
    assert obtener_nivel_fuerza("Squat Clean", 120, 80, "M")["nivel"] == "Avanzado"
    assert obtener_nivel_fuerza("Squat Snatch", 72, 80, "M")["nivel"] == "Intermedio"


def test_rope_climb_y_bear_crawl_clasifican_con_su_nombre_de_bd():
    from app.services.nivel_service import obtener_nivel_gimnastico

    # Rope Climb M: 0/1/3/5 -> 3 ascensos = Avanzado.
    assert obtener_nivel_gimnastico(
        "Rope Climb (Trepada)", 3, "M")["nivel"] == "Avanzado"
    # Bear Crawl M: 5/15/25/50 metros -> 15 m = Intermedio.
    assert obtener_nivel_gimnastico(
        "Bear Crawl (Caminata)", 15, "M")["nivel"] == "Intermedio"


# ── Estándares nuevos ─────────────────────────────────────────────────────────
NUEVOS_FUERZA = ("Power Clean", "Power Snatch", "Push Jerk", "Push Press")
NUEVOS_GIMNASIA = (
    "Strict Pull-up", "Kipping Pull-up", "Ring Dips",
    "Wall Ball Shot", "Kettlebell Swing",
)


def test_los_estandares_nuevos_estan_en_las_tablas():
    from app.db.crossfit_habilidades import CROSSFIT_HABILIDADES
    from app.db.crossfit_ratios import CROSSFIT_RATIOS

    for nombre in NUEVOS_FUERZA:
        assert nombre in CROSSFIT_RATIOS, f"falta {nombre} en CROSSFIT_RATIOS"
    for nombre in NUEVOS_GIMNASIA:
        assert nombre in CROSSFIT_HABILIDADES, f"falta {nombre} en CROSSFIT_HABILIDADES"


@pytest.mark.parametrize("nombre,valor,esperado", [
    # M: 1 / 5 / 10 / 15
    ("Strict Pull-up", 5, "Intermedio"),
    ("Strict Pull-up", 10, "Avanzado"),
    # M: 1 / 10 / 20 / 30
    ("Kipping Pull-up", 20, "Avanzado"),
    # M: 0 / 5 / 12 / 20
    ("Ring Dips", 5, "Intermedio"),
    # M: 5 / 20 / 40 / 60 (peso fijo, reps unbroken)
    ("Wall Ball Shot", 20, "Intermedio"),
    # M: 10 / 25 / 50 / 75
    ("Kettlebell Swing", 50, "Avanzado"),
])
def test_los_estandares_gimnasticos_clasifican(nombre, valor, esperado):
    from app.services.nivel_service import obtener_nivel_gimnastico

    r = obtener_nivel_gimnastico(nombre, valor, "M")
    assert r["clasificable"] is True
    assert r["nivel"] == esperado


@pytest.mark.parametrize("nombre,peso,esperado", [
    # Power Clean M: 0.40 / 0.80 / 1.05 / 1.35 (80 kg de peso corporal)
    ("Power Clean", 80, "Intermedio"),
    # Power Snatch M: 0.32 / 0.64 / 0.80 / 1.05
    ("Power Snatch", 56, "Intermedio"),
    # Push Jerk M: 0.45 / 0.81 / 1.08 / 1.35
    ("Push Jerk", 40, "Principiante"),
    # Push Press M: 0.40 / 0.72 / 0.96 / 1.20
    ("Push Press", 60, "Intermedio"),
])
def test_los_estandares_de_fuerza_clasifican(nombre, peso, esperado):
    from app.services.nivel_service import obtener_nivel_fuerza

    assert obtener_nivel_fuerza(nombre, peso, 80, "M")["nivel"] == esperado


def test_los_estandares_nuevos_declaran_su_origen_estimado():
    ratios = _fuente("backend/app/db/crossfit_ratios.py")
    habilidades = _fuente("backend/app/db/crossfit_habilidades.py")
    assert "ESTIMADO, no medido" in ratios
    assert "ESTIMADO, no medido" in habilidades
    # La decisión de puntuar peso fijo queda documentada (el doc recomendaba no hacerlo).
    assert "decisión D5 del dueño del producto" in habilidades


# ── Integración con el cálculo general ───────────────────────────────────────
def test_los_alias_cuentan_en_el_eje_correcto_y_conservan_el_nombre():
    from app.services.nivel_service import nivel_desde_mejores

    resultado = nivel_desde_mejores(
        [(1, 120.0, "Split Jerk"), (2, 120.0, "Squat Clean")], 80, "M")
    assert resultado["nivel_fuerza"] == "Avanzado"     # min(Elite, Avanzado)
    assert resultado["movs_fuerza"] == 2
    assert {d["movimiento"] for d in resultado["detalle_fuerza"]} == {"Split Jerk", "Squat Clean"}


def test_sin_genero_no_se_clasifica_gimnasia():
    from app.services.nivel_service import obtener_nivel_gimnastico

    # Todas las tablas gimnásticas actuales declaran M/F: sin género NO hay tabla que aplicar.
    r = obtener_nivel_gimnastico("Pull-ups (Dominadas)", 10, None)
    assert r["aplica"] is True
    assert r["clasificable"] is False
    assert "género" in r["mensaje"].lower()


def test_la_categoria_por_nombre_resuelve_los_alias():
    from app.services.movimiento_categoria import categoria_por_nombre

    # Rope Climb / Bear Crawl son gimnasia (importa para D4: valor = reps, no kg).
    assert categoria_por_nombre("Rope Climb (Trepada)") == "gimnastico"
    assert categoria_por_nombre("Bear Crawl (Caminata)") == "gimnastico"
    assert categoria_por_nombre("Split Jerk") == "fuerza"

