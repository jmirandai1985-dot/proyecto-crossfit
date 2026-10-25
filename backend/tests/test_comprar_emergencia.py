"""Compra de emergencia: los créditos sobrantes se SUMAN, no se pisan.

`POST /comprar-emergencia` dice "1ra vez al año: acumula tokens sobrantes al mes
siguiente". Calculaba `tokens_sobrantes`… y después guardaba `creditos_de_plan(plan)` a
secas, así que lo que le quedaba al alumno se perdía (se devolvía en la respuesta, pero
la base quedaba sin él). Acá se fija la regla (`app/utils/planes.creditos_de_emergencia`)
y que el endpoint la use.

Tests puros: no tocan base de datos ni red.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.utils.planes import creditos_de_emergencia, creditos_de_plan   # noqa: E402

ENDPOINT = BACKEND / "app" / "api" / "v1" / "comprar_emergencia.py"


def _plan(creditos, es_ilimitado=False):
    return SimpleNamespace(creditos=creditos, es_ilimitado=es_ilimitado)


def _codigo(relativa):
    """La fuente sin las líneas de comentario (los comentarios CITAN el bug)."""
    texto = relativa.read_text(encoding="utf-8-sig")
    return "\n".join(linea for linea in texto.splitlines()
                     if not linea.strip().startswith("#"))


# ── La regla ────────────────────────────────────────────────────────────────────
def test_los_sobrantes_se_suman_al_plan_comprado():
    """5 clases de plan + 3 sobrantes = 8: es "acumular", no reemplazar."""
    assert creditos_de_emergencia(_plan(5), 3) == 8


def test_meta_la_regla_vieja_pisaba_los_sobrantes():
    """Guarda de sensibilidad: `creditos_de_plan(plan)` a secas ES el bug.

    Antes el endpoint guardaba exactamente eso. Si `creditos_de_emergencia` volviera a
    implementarse así, este test (y el de arriba) lo delatan.
    """
    plan = _plan(5)
    assert creditos_de_plan(plan) == 5
    assert creditos_de_emergencia(plan, 3) != creditos_de_plan(plan)


def test_sin_sobrantes_el_resultado_es_el_del_plan():
    """El caso de todos los días: el guard exige 0 clases, así que sobrantes = 0."""
    assert creditos_de_emergencia(_plan(10), 0) == 10
    assert creditos_de_emergencia(_plan(0), 0) == 0


def test_plan_ilimitado_sigue_sin_numero():
    """`None` = "∞" en el front: no hay número que sumar (ni 999 ni 0 + sobrantes)."""
    assert creditos_de_emergencia(_plan(0, True), 3) is None


def test_sin_plan_no_se_inventan_creditos():
    assert creditos_de_emergencia(None, 3) is None


def test_un_saldo_negativo_no_se_arrastra_como_deuda():
    """Un "sobrante" `None` o negativo vale 0: la emergencia no puede RESTAR."""
    assert creditos_de_emergencia(_plan(5), None) == 5
    assert creditos_de_emergencia(_plan(5), -2) == 5


# ── El endpoint ────────────────────────────────────────────────────────────────
def test_el_endpoint_suma_los_sobrantes_y_no_los_pisa():
    codigo = _codigo(ENDPOINT)

    assert "creditos_de_emergencia(plan, tokens_sobrantes)" in codigo
    assert "creditos_disponibles = creditos" in codigo      # guarda el TOTAL
    assert "creditos_totales = creditos" in codigo
    # El bug: pisar con las clases del plan e ignorar `tokens_sobrantes`.
    assert "creditos = creditos_de_plan(plan)" not in codigo
    assert "creditos_de_plan(" not in codigo


def test_los_sobrantes_se_leen_ANTES_de_escribir_los_creditos():
    """Si se leen después, ya valen lo del plan nuevo: la cuenta sale sin sobrantes."""
    codigo = _codigo(ENDPOINT)

    lectura = codigo.index("tokens_sobrantes = ")
    escritura = codigo.index("creditos_disponibles = creditos")
    assert lectura < escritura
