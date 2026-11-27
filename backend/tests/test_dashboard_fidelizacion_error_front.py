"""Dashboard admin: las tarjetas de retención avisan el fallo y ofrecen Reintentar.

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. El riesgo sale del resumen compartido (`useResumenAdmin`, snapshot de churn) y la
     carga propia de la pantalla sólo pide vencimientos: dos fuentes independientes, así
     el fallo de una no tumba la otra (ya no hay un `Promise.all` que las ate).
  B. Las DOS tarjetas muestran el motivo cuando su fuente falla, en vez del "0" falso
     (un panel de churn que dice 0 cuando no pudo leer es una mentira): riesgo con
     `'n/d'` + `riesgoPendiente`, vencimientos con el `detail` del error.
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
    # El riesgo vive en el resumen compartido; la carga local sólo pide vencimientos.
    assert "useResumenAdmin(" in fuente
    assert "await api.get(`/api/v1/fidelizacion/tenant/${tenant_id}/vencimientos`)" in fuente
    assert "Promise.all(" not in fuente, (
        "un Promise.all ataría las dos tarjetas: el fallo de una dejaría la otra vacía")


def test_b_las_tarjetas_muestran_el_error_y_no_un_cero_falso():
    fuente = _fuente("frontend/src/pages/admin/Dashboard.jsx")
    # Riesgo: sale del snapshot y, si todavía no se pudo leer, dice 'n/d' (nunca 0).
    assert "resumenAdmin.alumnosRiesgo ?? 'n/d'" in fuente
    assert "resumenAdmin.riesgoPendiente" in fuente
    # Vencimientos: el motivo se pregunta ANTES de pintar el número.
    assert "fidelizacionError.vencimientos ? (" in fuente, (
        "la tarjeta tiene que preguntar por el error ANTES de pintar el número")
    assert "{fidelizacionError.vencimientos}" in fuente
    assert "setFidelizacionError" in fuente
    assert "vencimientos: error?.response?.data?.detail" in fuente


def test_c_el_bloque_ofrece_reintentar():
    fuente = _fuente("frontend/src/pages/admin/Dashboard.jsx")
    assert "from '../../components/AvisoCarga'" in fuente
    assert 'testid="aviso-fidelizacion"' in fuente
    assert "onReintentar={cargarFidelizacion}" in fuente, (
        "el Reintentar tiene que volver a pedir AMBAS listas")


def test_d_no_hay_admin_id_hardcodeado():
    fuente = _fuente("frontend/src/pages/admin/Dashboard.jsx")
    assert "admin_id" not in fuente
