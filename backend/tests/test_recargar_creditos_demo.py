"""`crear_usuarios_demo.py --recargar-creditos N` (T9) — puro + guard de fuente.

Qué fija este archivo (sin red y sin base de datos):

  A. La recarga suma el MISMO N a `creditos_totales` y a `creditos_disponibles`: la
     diferencia (lo que A.3 compara contra las reservas) no cambia -> invariante intacta.
  B. Es una acción de SOLO créditos: N no se toca la suscripción si es ilimitada, no hay
     plan activo, o N <= 0 (GuardError en los tres casos).
  C. El script tiene el flag, lo trata como acción APARTE (no combina con --borrar ni con
     --extender-plan) y no toca reservas ni contraseña.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_recargar_creditos_demo.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND), str(_BACKEND / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import crear_usuarios_demo as demo                              # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
FUENTE = "backend/scripts/crear_usuarios_demo.py"


class _Resultado:
    def __init__(self, fila):
        self._fila = fila

    def first(self):
        return self._fila


class _FakeDB:
    """Sesión mínima: el SELECT devuelve la fila; los UPDATE se guardan en `updates`."""

    def __init__(self, fila):
        self._fila = fila
        self.updates = []

    def execute(self, sql, params=None):
        if str(sql).strip().upper().startswith("UPDATE"):
            self.updates.append(params)
            return _Resultado(None)
        return _Resultado(self._fila)


def _fila(totales=12, disponibles=5):
    return SimpleNamespace(id=1, creditos_totales=totales, creditos_disponibles=disponibles)


# ── A. A.3 intacta ────────────────────────────────────────────────────────────
def test_a_la_recarga_suma_a_totales_y_disponibles_por_igual():
    db = _FakeDB(_fila(totales=12, disponibles=5))
    res = demo.recargar_creditos(db, alumno_id=42, n=3)

    assert res == {"suscripcion_id": 1, "creditos_totales": 15,
                   "creditos_disponibles": 8}
    # El UPDATE toca LAS DOS columnas con el mismo N (A.3 no se mueve).
    assert len(db.updates) == 1
    assert db.updates[0]["n"] == 3
    assert db.updates[0]["sid"] == 1
    # La diferencia (reservas consumidas) no cambia.
    assert (15 - 8) == (12 - 5)


# ── B. Casos que NO se pueden recargar ────────────────────────────────────────
def test_b_sin_suscripcion_activa_es_guard_error():
    with pytest.raises(demo.GuardError):
        demo.recargar_creditos(_FakeDB(None), alumno_id=42, n=3)


def test_b2_plan_ilimitado_es_guard_error():
    with pytest.raises(demo.GuardError):
        demo.recargar_creditos(_FakeDB(_fila(totales=None, disponibles=0)),
                               alumno_id=42, n=3)


def test_b3_n_no_positivo_es_guard_error():
    for malo in (0, -5, None):
        with pytest.raises(demo.GuardError):
            demo.recargar_creditos(_FakeDB(_fila()), alumno_id=42, n=malo)


# ── C. Guard de fuente ────────────────────────────────────────────────────────
def test_c_el_script_tiene_el_flag():
    fuente = (RAIZ / FUENTE).read_text(encoding="utf-8")
    assert 'add_argument("--recargar-creditos"' in fuente
    # Es acción aparte: los guards lo separan de --borrar y de --extender-plan.
    assert "args.borrar and args.recargar_creditos is not None" in fuente
    assert "args.extender_plan and args.recargar_creditos is not None" in fuente


def test_c2_la_recarga_no_toca_reservas_ni_password():
    fuente = (RAIZ / FUENTE).read_text(encoding="utf-8")
    inicio = fuente.index("def recargar_creditos")
    fin = fuente.index("def extender_plan", inicio)
    cuerpo = fuente[inicio:fin]
    # Sólo un UPDATE a suscripciones; ninguna operación sobre reservas ni password_hash.
    assert "UPDATE suscripciones" in cuerpo
    for tabla in ("FROM reservas", "INTO reservas", "UPDATE reservas", "DELETE FROM reservas"):
        assert tabla not in cuerpo, tabla
    assert "password_hash" not in cuerpo
    assert "creditos_totales = creditos_totales + :n" in cuerpo
    assert "creditos_disponibles = creditos_disponibles + :n" in cuerpo
