"""Dashboard admin: las tarjetas de "alumnos en riesgo" avisan el fallo y ofrecen Reintentar.

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. El cargador de fidelización usa `Promise.allSettled` (no `Promise.all`): el fallo de
     un endpoint no puede tumbar el otro.
  B. La tarjeta de "Alumnos en Riesgo" muestra el ERROR cuando la petición falla, en vez
     del "0" falso (un panel de churn que dice 0 cuando no pudo leer es una mentira).
  C. El bloque tiene un `AvisoCarga` con Reintentar (`cargarFidelizacion`), igual que el
     resto de la pantalla: antes, para volver a intentar había que recargar la página.
  D. No hay `admin_id` hardcodeado en la pantalla (el id sale del token).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_dashboard_fidelizacion_error_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_a_el_cargador_de_fidelizacion_no_es_todo_o_nada():
    fuente = _fuente("frontend/src/pages/admin/Dashboard.jsx")
    assert "const cargarFidelizacion" in fuente
    assert "await Promise.allSettled([" in fuente
    assert "Promise.all([" not in fuente, (
        "el dashboard ya no puede usar Promise.all: un fallo dejaría las 2 tarjetas vacías")


def test_b_la_tarjeta_de_riesgo_muestra_el_error_y_no_un_cero_falso():
    fuente = _fuente("frontend/src/pages/admin/Dashboard.jsx")
    assert "fidelizacionError.riesgo ? (" in fuente, (
        "la tarjeta tiene que preguntar por el error ANTES de pintar el número")
    assert "{fidelizacionError.riesgo}" in fuente
    assert "setFidelizacionError" in fuente
    assert "riesgo: riesgoRes.reason?.response?.data?.detail" in fuente
    assert "alumnos_alerta" in fuente


def test_c_el_bloque_ofrece_reintentar():
    fuente = _fuente("frontend/src/pages/admin/Dashboard.jsx")
    assert "from '../../components/AvisoCarga'" in fuente
    assert 'testid="aviso-fidelizacion"' in fuente
    assert "onReintentar={cargarFidelizacion}" in fuente, (
        "el Reintentar tiene que volver a pedir AMBAS listas")


def test_d_no_hay_admin_id_hardcodeado():
    fuente = _fuente("frontend/src/pages/admin/Dashboard.jsx")
    assert "admin_id" not in fuente
