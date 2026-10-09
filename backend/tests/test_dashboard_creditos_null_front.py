"""Créditos del alumno con el cupo en NULL — guard de fuente del FRONT.

Qué fija este archivo (sin red y sin base: se inspecciona el código del front):

  A. La tarjeta "Créditos Restantes" del Dashboard (la de ≥768px) ya no pinta el
     valor crudo: con `clases_disponibles` en NULL se muestra "—" —el rótulo del
     Historial, la ficha del coach y el Inicio móvil— en vez de quedar en blanco.
  B. La regla vive en UN solo módulo (`frontend/src/utils/rotuloCreditos.js`) y
     las dos pantallas lo consumen: no pueden divergir ni volver a duplicarse.
  C. NULL sigue siendo "desconocido" y el 0 sigue siendo un cupo REAL: el
     `Number(NULL) || 0` que convertía un cupo no cargado en "0 créditos" no
     puede reaparecer.
  D. El resto de la tarjeta no se toca: sigue bajo `membresia?.activa` y conserva
     el "Sin plan activo" y el rótulo del plan ilimitado.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_dashboard_creditos_null_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
DASHBOARD = "frontend/src/pages/alumno/Dashboard.jsx"
INICIO = "frontend/src/pages/alumno/InicioMobile.jsx"
UTIL = "frontend/src/utils/rotuloCreditos.js"
HISTORIAL = "frontend/src/components/historial/PanelHistorial.jsx"
FICHA_COACH = "frontend/src/components/AlumnoFichaCoach.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_a_la_tarjeta_del_dashboard_ya_no_pinta_el_cupo_crudo():
    d = _fuente(DASHBOARD)
    assert "rotuloCupo(membresia.clases_disponibles)" in d, \
        "el cupo NULL se pinta con el rótulo compartido, no vacío"
    # El bug: el valor crudo. Con NULL quedaba el hueco en blanco.
    assert "{membresia.clases_disponibles}" not in d
    assert ": membresia.clases_disponibles}" not in d
    assert "Créditos Restantes" in d


def test_b_las_dos_pantallas_consumen_la_misma_regla():
    assert "import { rotuloCupo } from '../../utils/rotuloCreditos';" in _fuente(DASHBOARD)
    assert "import { rotuloCreditos } from '../../utils/rotuloCreditos';" in _fuente(INICIO)
    util = _fuente(UTIL)
    for exportado in ("ROTULO_ILIMITADO", "ROTULO_SIN_CUPO", "cupoDesconocido",
                      "rotuloCupo", "rotuloCreditos"):
        assert f"export const {exportado} =" in util
    # Ni una copia de la regla en las pantallas (se borró la de InicioMobile).
    assert "cupoDesconocido" not in _fuente(INICIO)
    assert "cupoDesconocido" not in _fuente(DASHBOARD)


def test_c_null_es_desconocido_y_el_0_es_un_cupo_real():
    util = _fuente(UTIL)
    assert "valor === null || valor === undefined || valor === ''" in util
    assert "ROTULO_SIN_CUPO = '—';" in util, "el rótulo del cupo desconocido es la raya"
    assert "ROTULO_ILIMITADO = '∞';" in util
    # El feo: `Number(NULL) || 0` convertía un cupo desconocido en "0 créditos".
    assert "Number(" not in util and "|| 0" not in util


def test_d_el_resto_de_la_tarjeta_no_se_toca():
    d = _fuente(DASHBOARD)
    assert "membresia?.activa ? (" in d
    assert "Sin plan activo" in d
    assert "membresia.es_ilimitado ? 'Plan Ilimitado'" in d


def test_e_el_rotulo_es_el_mismo_que_ya_usa_el_resto_del_panel():
    """Los mismos caracteres que ya pintaban el Historial y la ficha del coach."""
    assert "actual.es_ilimitado ? '∞'" in _fuente(HISTORIAL)
    assert "creditos === null || creditos === undefined ? '—' : creditos" in _fuente(FICHA_COACH)
    assert "rotuloCreditos(ilimitado, activa ? membresia?.clases_disponibles : 0)" in _fuente(INICIO)
