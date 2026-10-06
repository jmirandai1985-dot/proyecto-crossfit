"""Barra final: Coaches y Supervisión llaman a la ruta CANÓNICA (sin redirect 307).

Qué fija este archivo (guard de fuente del FRONTEND + del BACKEND, sin red y sin base):

  A. Los routers `usuarios`, `disciplinas` y `clases` definen el LISTADO como `"/"`, así que
     la ruta canónica lleva barra final (`/api/v1/usuarios/`). Pedirla sin la barra hace
     que FastAPI conteste 307 y el navegador repita la request.
  B. `Coaches.jsx` (listado de coaches, alta de coach, disciplinas) y `SupervisionClases.jsx`
     (disciplinas) llaman a la ruta CON barra: no queda ninguna llamada que dependa del 307.
  C. `coach-disciplinas` es la excepción: su listado se define como `""` (sin barra), así que
     ahí la ruta correcta es SIN barra y se deja como está.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_rutas_sin_redirect_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
COACHES = "frontend/src/pages/admin/Coaches.jsx"
SUPERVISION = "frontend/src/pages/admin/SupervisionClases.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_a_el_backend_define_estos_listados_con_barra_final():
    for archivo in ("app/api/v1/usuarios.py", "app/api/v1/disciplinas.py",
                    "app/api/v1/clases.py"):
        assert '@router.get("/"' in _fuente(f"backend/{archivo}"), archivo
    main = _fuente("backend/app/main.py")
    for prefijo in ('prefix="/api/v1/usuarios"', 'prefix="/api/v1/disciplinas"',
                    'prefix="/api/v1/clases"', 'prefix="/api/v1/coach-disciplinas"'):
        assert prefijo in main, prefijo
    # `coach-disciplinas` es el caso opuesto: su listado NO lleva barra.
    assert '@router.get("", response_model=List[CoachDisciplinaListItem])' in \
        _fuente("backend/app/api/v1/coach_disciplinas.py")


def test_b_coaches_llama_a_las_rutas_canonicas():
    fuente = _fuente(COACHES)
    assert "api.get('/api/v1/usuarios/', { params: { rol: 'coach' } })" in fuente
    assert "api.post('/api/v1/usuarios/', {" in fuente
    assert "api.get('/api/v1/disciplinas/')" in fuente
    # Ninguna llamada puede quedar sin la barra (sería el 307).
    assert "'/api/v1/usuarios'" not in fuente
    assert "'/api/v1/disciplinas'" not in fuente
    # La excepción sigue SIN barra: el listado de coach-disciplinas es `""`.
    assert "api.get('/api/v1/coach-disciplinas', { params: { limit: 500 } })" in fuente
    assert "api.put('/api/v1/coach-disciplinas/reemplazar', {" in fuente


def test_c_supervision_llama_al_listado_de_disciplinas_con_barra():
    fuente = _fuente(SUPERVISION)
    assert "api.get(`${API_BASE}/disciplinas/`)" in fuente
    assert "${API_BASE}/disciplinas`" not in fuente
    # El resto de las llamadas de la pantalla ya eran canónicas.
    assert "api.get(`${API_BASE}/clases/`, { params })" in fuente
    assert "api.get(`${API_BASE}/supervision/grilla`, { params })" in fuente
