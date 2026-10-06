"""AlumnoFichaModal: cada bloque trae su propio error (nada de todo-o-nada).

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. Las 3 requests (usuario, suscripción, planes) van en `Promise.allSettled`: antes un
     `Promise.all` hacía que el fallo de UNA dejara la ficha entera en blanco.
  B. Hay un error POR BLOQUE (`errores.usuario`, `errores.suscripcion`, `errores.planes`)
     y los 3 se pintan: si el catálogo de planes falla, la membresía lo dice en vez de
     mostrar "Plan ID 7" como si fuera lo normal.
  C. Cuando el usuario no se pudo cargar (ficha vacía) igual se avisan los otros bloques.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_alumno_ficha_modal_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
MODAL = "frontend/src/components/AlumnoFichaModal.jsx"


def _fuente() -> str:
    return (RAIZ / MODAL).read_text(encoding="utf-8")


def test_a_la_carga_es_allSettled_no_todo_o_nada():
    fuente = _fuente()
    assert "await Promise.allSettled([" in fuente
    assert "Promise.all([" not in fuente
    for endpoint in ("`/api/v1/usuarios/${alumnoId}`", "/api/v1/suscripciones",
                     "/api/v1/planes"):
        assert endpoint in fuente


def test_b_hay_un_error_por_bloque_y_se_pintan_los_tres():
    fuente = _fuente()
    assert "useState({ usuario: '', suscripcion: '', planes: '' })" in fuente
    assert "setErrores(prev => ({ ...prev, usuario: detalle(usrRes) }))" in fuente
    assert "setErrores(prev => ({ ...prev, suscripcion: detalle(susRes) }))" in fuente
    assert "setErrores(prev => ({ ...prev, planes: detalle(planesRes) }))" in fuente
    assert "{errores.usuario}" in fuente
    assert "{errores.suscripcion}" in fuente
    assert "{errores.planes}" in fuente, (
        "el fallo del catálogo de planes tiene que verse, no degradar a 'Plan ID N'")


def test_c_el_fallo_del_usuario_no_esconde_los_demas():
    fuente = _fuente()
    inicio = fuente.index("errores.usuario && !data ?")
    fin = fuente.index(") : data ?", inicio)
    bloque = fuente[inicio:fin]
    assert "Membresía: {errores.suscripcion}" in bloque
    assert "Catálogo de planes: {errores.planes}" in bloque
