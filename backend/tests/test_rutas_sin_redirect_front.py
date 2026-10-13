"""Barra final: Coaches y Supervisión llaman a la ruta CANÓNICA (sin redirect 307).

Qué fija este archivo (guard de fuente del FRONTEND + del BACKEND, sin red y sin base):

  A. Los routers `usuarios`, `disciplinas` y `clases` definen el LISTADO como `"/"`, así que
     la ruta canónica lleva barra final (`/api/v1/usuarios/`). Pedirla sin la barra hace
     que FastAPI conteste 307 y el navegador repita la request.
  B. `Coaches.jsx` YA NO pide con axios: sus GET y sus escrituras son hooks de
     `hooks/queries.js` (React Query, Bloque 3 parte A). La barra final no se perdió, se MUDÓ
     con las URLs: ahora el guard la exige EN EL HOOK —el único lugar donde vive la ruta— y
     exige además que la pantalla no vuelva a llamar a la API a mano, así no hay dónde
     volver a escribir una ruta mal (ni con 307 ni sin él).
  C. `SupervisionClases.jsx` no se migró y sigue con sus `api.*` literales: ahí se exige la
     ruta CON barra, como antes.
  D. `coach-disciplinas` es la excepción: su listado se define como `""` (sin barra), así que
     ahí la ruta correcta es SIN barra y el hook la deja así.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_rutas_sin_redirect_front.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
COACHES = "frontend/src/pages/admin/Coaches.jsx"
SUPERVISION = "frontend/src/pages/admin/SupervisionClases.jsx"
QUERIES = "frontend/src/hooks/queries.js"

# Ruta del listado SIN la barra final, escrita como ruta COMPLETA (`/api/v1/clases?`)
# y no como base de un path con id (`/api/v1/clases/${id}`): es la única que hace 307.
SIN_BARRA = re.compile(r"/api/v1/(?:usuarios|clases|disciplinas)(?=[?`'\"]|$)", re.M)
# Una llamada propia al cliente HTTP: lo que la pantalla migrada no puede volver a tener.
AXIOS_A_MANO = re.compile(r"\bapi\.(?:get|post|put|patch|delete)\(")


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _bloque_hook(fuente: str, hook: str) -> str:
    """El cuerpo de `export function <hook>(` hasta el próximo `export function`."""
    assert f"export function {hook}(" in fuente, f"falta el hook {hook} en queries.js"
    return fuente.split(f"export function {hook}(")[1].split("\nexport function")[0]


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


def test_b_coaches_consume_los_hooks_y_no_pide_a_mano():
    """Coaches.jsx (React Query, Bloque 3 parte A): hooks sí, `api.*` no."""
    f = _fuente(COACHES)
    assert "from '../../hooks/queries'" in f
    # Las consultas y las mutaciones que reemplazaron a los `api.*` que había en la pantalla.
    for uso in ("useUsuariosPorRol('coach')", "useDisciplinas()", "useCoachDisciplinas()",
                "useGuardarUsuario()", "useReemplazarCoachDisciplinas()"):
        assert uso in f, uso
    # Y ninguna llamada propia: sin axios en la pantalla no hay dónde volver a escribir la
    # ruta (y con ella, su barra final) mal.
    assert not AXIOS_A_MANO.search(f), AXIOS_A_MANO.search(f).group(0)
    assert "services/api" not in f and "API_BASE" not in f


def test_c_los_hooks_que_usa_coaches_tienen_las_rutas_canonicas():
    """Las URLs (y su barra) viven en `hooks/queries.js`: acá se exigen hook por hook."""
    q = _fuente(QUERIES)
    assert "api.get('/api/v1/usuarios/', {" in _bloque_hook(q, "useUsuariosPorRol")
    assert "api.get('/api/v1/disciplinas/')" in _bloque_hook(q, "useDisciplinas")
    # El alta de coach: POST con barra (el router define el listado Y el alta como `"/"`).
    assert "api.post('/api/v1/usuarios/', payload)" in _bloque_hook(q, "useGuardarUsuario")
    # La excepción `coach-disciplinas` (listado `""`): va SIN barra y se deja así.
    assert "api.get('/api/v1/coach-disciplinas')" in _bloque_hook(q, "useCoachDisciplinas")
    assert "'/api/v1/coach-disciplinas/reemplazar', payload," in _bloque_hook(
        q, "useReemplazarCoachDisciplinas")
    # Y en TODO el módulo de hooks no puede quedar un listado sin su barra: el 307 de
    # siempre ahora se colaría por acá, que es donde están todas las rutas.
    hallazgo = SIN_BARRA.search(q)
    assert hallazgo is None, f"listado sin barra final: {hallazgo.group(0)}"


def test_d_supervision_llama_al_listado_de_disciplinas_con_barra():
    fuente = _fuente(SUPERVISION)
    assert "api.get(`${API_BASE}/disciplinas/`)" in fuente
    assert "${API_BASE}/disciplinas`" not in fuente
    # El resto de las llamadas de la pantalla ya eran canónicas.
    assert "api.get(`${API_BASE}/clases/`, { params })" in fuente
    assert "api.get(`${API_BASE}/supervision/grilla`, { params })" in fuente
