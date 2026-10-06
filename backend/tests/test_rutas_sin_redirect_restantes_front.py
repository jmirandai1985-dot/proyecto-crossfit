"""307 restantes: las pantallas que faltaban llaman a la ruta CANÓNICA (sin redirect).

Qué fija este archivo (guard de fuente del FRONTEND + del BACKEND, sin red y sin base):

  Los routers `usuarios`, `disciplinas` y `clases` definen el LISTADO como `"/"` (y el alta
  con POST `"/"`), así que la ruta canónica lleva BARRA final (`/api/v1/usuarios/`). Pedirla
  sin la barra hace que FastAPI conteste 307 y el navegador repita la request (una vuelta de
  red gratis por cada listado). `horarios`, `planes`, `suscripciones` y `coach-disciplinas`
  son la excepción: sus listados se definen `""` (SIN barra) y se dejan como están.

  Este archivo es el hermano de `test_rutas_sin_redirect_front.py` (T6): allí quedaron
  Coaches.jsx y SupervisionClases.jsx; acá se cierran las pantallas que faltaban —
  Alumnos, Clases, Disciplinas, Horarios, ModalClase y GestionClases (coach).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_rutas_sin_redirect_restantes_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

ALUMNOS = "frontend/src/pages/admin/Alumnos.jsx"
CLASES = "frontend/src/pages/admin/Clases.jsx"
DISCIPLINAS = "frontend/src/pages/admin/Disciplinas.jsx"
HORARIOS = "frontend/src/pages/admin/Horarios.jsx"
MODAL_CLASE = "frontend/src/components/ModalClase.jsx"
GESTION = "frontend/src/pages/coach/GestionClases.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_a_el_backend_define_estos_listados_con_barra_final():
    assert '@router.get("/")' in _fuente("backend/app/api/v1/disciplinas.py")
    clases = _fuente("backend/app/api/v1/clases.py")
    assert '@router.get("/", response_model=List[schemas.ClaseListItem])' in clases
    assert '@router.post("/", response_model=schemas.ClaseResponse)' in clases
    usuarios = _fuente("backend/app/api/v1/usuarios.py")
    assert '@router.get("/", response_model=List[UsuarioListItem])' in usuarios
    assert '@router.post("/", response_model=UsuarioResponse' in usuarios
    # La excepción: `horarios` y `planes` listan SIN barra (no se tocan).
    assert '@router.get("")' in _fuente("backend/app/api/v1/horarios.py")
    assert '@router.get("")' in _fuente("backend/app/api/v1/planes.py")


def test_b_alumnos_pide_usuarios_con_barra():
    f = _fuente(ALUMNOS)
    assert "api.get('/api/v1/usuarios/', {" in f
    assert "api.post('/api/v1/usuarios/', {" in f
    assert "api.get('/api/v1/usuarios', {" not in f
    assert "api.post('/api/v1/usuarios', {" not in f


def test_c_clases_y_disciplinas_llaman_con_barra():
    clases = _fuente(CLASES)
    assert "api.get('/api/v1/disciplinas/');" in clases
    assert "api.get('/api/v1/disciplinas');" not in clases
    assert "api.get('/api/v1/clases/', { params })" in clases
    assert "api.get('/api/v1/clases', { params })" not in clases

    disc = _fuente(DISCIPLINAS)
    assert "api.get('/api/v1/disciplinas/');" in disc
    assert "api.get('/api/v1/disciplinas');" not in disc
    assert "api.post('/api/v1/disciplinas/', { ...formData, tenant_id });" in disc
    assert "api.post('/api/v1/disciplinas', { ...formData, tenant_id });" not in disc

    hor = _fuente(HORARIOS)
    assert "api.get('/api/v1/disciplinas/')" in hor
    assert "api.get('/api/v1/disciplinas')" not in hor


def test_d_modal_clase_llama_con_barra():
    f = _fuente(MODAL_CLASE)
    assert "api.get(`/api/v1/usuarios/?rol=coach`)" in f
    assert "api.get(`/api/v1/usuarios?rol=coach`)" not in f
    assert "api.get(`/api/v1/disciplinas/`)" in f
    assert "api.get(`/api/v1/disciplinas`)" not in f
    assert "api.post(`/api/v1/clases/`, payload)" in f
    assert "api.post(`/api/v1/clases`, payload)" not in f


def test_e_gestion_clases_usa_las_rutas_con_barra():
    f = _fuente(GESTION)
    assert "${API_BASE}/disciplinas/`" in f
    assert "${API_BASE}/disciplinas`" not in f
    # Listado de clases: SIEMPRE con barra (los `/clases/{id}` siguen igual).
    assert "${API_BASE}/clases/`" in f
    assert "${API_BASE}/clases`" not in f
