"""307 restantes: las pantallas que faltaban llaman a la ruta CANÓNICA (sin redirect).

Qué fija este archivo (guard de fuente del FRONTEND + del BACKEND, sin red y sin base):

  Los routers `usuarios`, `disciplinas` y `clases` definen el LISTADO como `"/"` (y el alta
  con POST `"/"`), así que la ruta canónica lleva BARRA final (`/api/v1/usuarios/`). Pedirla
  sin la barra hace que FastAPI conteste 307 y el navegador repita la request (una vuelta de
  red gratis por cada listado). `horarios`, `planes`, `suscripciones` y `coach-disciplinas`
  son la excepción: sus listados se definen `""` (SIN barra) y se dejan como están.

  Este archivo es el hermano de `test_rutas_sin_redirect_front.py` (T6): allí quedaron
  Coaches.jsx y SupervisionClases.jsx; acá se cierran las pantallas que faltaban —
  Alumnos, Clases, Disciplinas, Horarios, ModalClase y el panel del coach—. (La antigua
  `GestionClases.jsx` del coach se retiró por completo: la reemplazan DashboardCoach y los
  componentes que se portaron, que se verifican abajo.)

  OJO CON LA MIGRACIÓN A REACT QUERY: esas pantallas ya no llaman con axios, así que una
  assertion sobre el `api.get(...)` LITERAL dentro del .jsx quedaría en rojo (o, peor,
  pasaría por accidente sobre un archivo que ya no pide nada). El patrón real es:

      pantalla  ->  hook de `hooks/queries.js`  ->  `api.get('/api/v1/clases/', ...)`

  y por eso el guard se parte en dos exigencias que juntas cubren lo mismo que antes:
    1. la pantalla usa el hook y NO tiene ni una llamada propia a la API (sin axios en la
       pantalla no hay dónde volver a escribir la ruta, ni con barra ni sin ella);
    2. la ruta canónica CON barra vive en el hook correspondiente (acá se verifica hook por
       hook), y en TODO `hooks/queries.js` no puede quedar un listado sin la barra final.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_rutas_sin_redirect_restantes_front.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

ALUMNOS = "frontend/src/pages/admin/Alumnos.jsx"
CLASES = "frontend/src/pages/admin/Clases.jsx"
DISCIPLINAS = "frontend/src/pages/admin/Disciplinas.jsx"
HORARIOS = "frontend/src/pages/admin/Horarios.jsx"
MODAL_CLASE = "frontend/src/components/ModalClase.jsx"
DASHBOARD = "frontend/src/pages/coach/DashboardCoach.jsx"
QUERIES = "frontend/src/hooks/queries.js"

# Ruta del listado SIN la barra final, escrita como ruta COMPLETA (`/api/v1/clases?`) y no
# como base de un path con id (`/api/v1/clases/${id}`): es la única que hace 307.
SIN_BARRA = re.compile(r"/api/v1/(?:usuarios|clases|disciplinas)(?=[?`'\"]|$)", re.M)
# Una llamada propia al cliente HTTP: lo que una pantalla migrada no puede volver a tener.
AXIOS_A_MANO = re.compile(r"\bapi\.(?:get|post|put|patch|delete)\(")


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _bloque_hook(fuente: str, hook: str) -> str:
    """El cuerpo de `export function <hook>(` hasta el próximo `export function`."""
    assert f"export function {hook}(" in fuente, f"falta el hook {hook} en queries.js"
    return fuente.split(f"export function {hook}(")[1].split("\nexport function")[0]


def _sin_llamadas_a_mano(relativa: str) -> str:
    """La pantalla migrada: devuelve su fuente y falla si volvió a pedir con axios."""
    f = _fuente(relativa)
    assert not AXIOS_A_MANO.search(f), f"{relativa}: {AXIOS_A_MANO.search(f).group(0)}"
    assert "services/api" not in f and "API_BASE" not in f, relativa
    return f


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


def test_b_alumnos_consume_los_hooks_y_los_hooks_usan_la_barra():
    f = _sin_llamadas_a_mano(ALUMNOS)
    # El padrón paginado y el alta salen de la caché compartida (React Query, A5).
    assert "useAlumnosPaginados(" in f and "useGuardarUsuario()" in f
    q = _fuente(QUERIES)
    assert "api.get('/api/v1/usuarios/', {" in _bloque_hook(q, "useAlumnosPaginados")
    assert "api.post('/api/v1/usuarios/', payload)" in _bloque_hook(q, "useGuardarUsuario")


def test_c_clases_disciplinas_y_horarios_consumen_los_hooks_canonicos():
    clases = _sin_llamadas_a_mano(CLASES)
    assert "useClasesAdmin(" in clases and "useDisciplinas()" in clases
    disc = _sin_llamadas_a_mano(DISCIPLINAS)
    assert "useDisciplinas()" in disc and "useGuardarDisciplina()" in disc
    hor = _sin_llamadas_a_mano(HORARIOS)
    assert "useDisciplinas()" in hor and "useGridSemanalHorarios()" in hor

    q = _fuente(QUERIES)
    assert "api.get('/api/v1/clases/', {" in _bloque_hook(q, "useClasesAdmin")
    assert "api.post('/api/v1/clases/', payload)" in _bloque_hook(q, "useGuardarClase")
    assert "api.get('/api/v1/disciplinas/')" in _bloque_hook(q, "useDisciplinas")
    assert "api.post('/api/v1/disciplinas/', payload)" in _bloque_hook(q, "useGuardarDisciplina")
    # Excepción: el grid de horarios se lista SIN barra (el router lo define `""`).
    assert "api.get('/api/v1/horarios/grid-semanal')" in _bloque_hook(
        q, "useGridSemanalHorarios")


def test_d_modal_clase_consume_los_hooks_canonicos():
    f = _sin_llamadas_a_mano(MODAL_CLASE)
    assert "from '../hooks/queries'" in f
    # Los dos catálogos del modal y el guardado de la clase: hooks, no `api.*`.
    assert "useUsuariosPorRol('coach')" in f and "useDisciplinas()" in f
    assert "useGuardarClase()" in f
    q = _fuente(QUERIES)
    # El `?rol=coach` de antes ahora viaja como param del hook (mismo request).
    bloque_usuarios = _bloque_hook(q, "useUsuariosPorRol")
    assert "api.get('/api/v1/usuarios/', {" in bloque_usuarios
    assert "params: { rol }" in bloque_usuarios
    assert "api.post('/api/v1/clases/', payload)" in _bloque_hook(q, "useGuardarClase")


def test_e_el_panel_del_coach_usa_las_rutas_canonicas_con_barra():
    # Las pantallas del coach ya no piden con axios: las URLs viven en los hooks
    # compartidos (`hooks/queries.js`), que es donde se guarda la ruta canónica. La barra
    # final importa: sin ella FastAPI contesta 307 y el navegador repite la request.
    q = _fuente(QUERIES)
    assert "api.get('/api/v1/disciplinas/')" in _bloque_hook(q, "useDisciplinas")
    for hook in ("useClasesCoach", "useClasesDia", "useClasesDisciplinaSemana"):
        assert "api.get('/api/v1/clases/'" in _bloque_hook(q, hook), (
            f"{hook} pide el listado de clases sin la barra final (307)")
    # Y el panel del coach consume los hooks, sin llamadas a mano. (Antes este chequeo
    # apuntaba a `GestionClases.jsx`: se retiró y sus funciones viven en el panel/componentes.)
    f = _sin_llamadas_a_mano(DASHBOARD)
    assert "useDisciplinas(" in f and "useClasesCoach(" in f and "useTodosLosWods(" in f


def test_f_ningun_listado_de_queries_js_quedo_sin_la_barra():
    """El barrido que cierra la CLASE de bug: como ahora todas las rutas viven en el módulo
    de hooks, un listado sin barra (`/api/v1/clases?...`) tiene que hacerse visible acá."""
    q = _fuente(QUERIES)
    hallazgo = SIN_BARRA.search(q)
    assert hallazgo is None, f"listado sin barra final: {hallazgo.group(0)}"
