"""
Salud del servicio — guard de FUENTE (tests AISLADOS, sin red ni BD).

Qué se prueba (Parte 3 del fix 2026-10):

  1. `get_current_user` es `def` (síncrona) y NO `async def`: así FastAPI la
     ejecuta en el threadpool y la consulta síncrona a Neon no bloquea el
     event loop.
  2. `/health` es LIVENESS puro: no abre conexiones ni ejecuta SQL. Puede
     seguir siendo `async def` porque no hace I/O de red.
  3. `/health/db` es READINESS: `def` (threadpool), hace `SELECT 1` y responde
     503 cuando la BD falla.
  4. nginx (imagen combinada de Render) proxya los DOS endpoints.

Se leen los archivos y se parsean con `ast`, sin importar `app.main` (que
arrastra todos los routers y tarda mucho en arrancar).

    cd backend && py -3.12 -m pytest tests/test_salud_liveness_readiness.py --noconftest -q
"""
import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit


def _fuente(relativa: str) -> str:
    # utf-8-sig: main.py/reportes.py traen BOM y `ast.parse` no lo acepta.
    return (RAIZ / relativa).read_text(encoding="utf-8-sig")


def _funcion(arbol: ast.Module, nombre: str):
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"No se encontró la función {nombre!r}")


def _llamadas(funcion) -> list[str]:
    """Nombres/atributos llamados dentro de la función (ignora docstrings)."""
    nombres = []
    for nodo in ast.walk(funcion):
        if isinstance(nodo, ast.Call):
            objetivo = nodo.func
            if isinstance(objetivo, ast.Attribute):
                nombres.append(objetivo.attr)
            elif isinstance(objetivo, ast.Name):
                nombres.append(objetivo.id)
    return nombres


def test_get_current_user_es_sincrona_para_no_bloquear_el_event_loop():
    arbol = ast.parse(_fuente("backend/app/core/dependencies.py"))
    funcion = _funcion(arbol, "get_current_user")

    assert isinstance(funcion, ast.FunctionDef), (
        "get_current_user debe ser `def`: con `async def` el I/O síncrono de "
        "SQLAlchemy corre dentro del event loop y bloquea el resto de requests"
    )
    assert not isinstance(funcion, ast.AsyncFunctionDef)
    # La explicación tiene que quedar en el código para que nadie la revierta.
    assert "threadpool" in ast.get_docstring(funcion)
    assert "event loop" in ast.get_docstring(funcion)


def test_health_es_liveness_sin_io_de_base_de_datos():
    arbol = ast.parse(_fuente("backend/app/main.py"))
    funcion = _funcion(arbol, "health_check")
    llamadas = _llamadas(funcion)

    # Sin engine/conexiones/SQL: es sólo el estado del proceso.
    assert "connect" not in llamadas
    assert "execute" not in llamadas
    doc = ast.get_docstring(funcion) or ""
    assert "Liveness" in doc and "/health/db" in doc

    # La respuesta declara explícitamente que NO se consultó la BD.
    constantes = [
        nodo.value for nodo in ast.walk(funcion)
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)
    ]
    assert "not_checked" in constantes


def test_health_db_es_readiness_con_select_1_y_503():
    arbol = ast.parse(_fuente("backend/app/main.py"))
    funcion = _funcion(arbol, "health_db")

    assert isinstance(funcion, ast.FunctionDef), (
        "/health/db debe ser `def` para que el SELECT 1 corra en el threadpool"
    )
    llamadas = _llamadas(funcion)
    assert "connect" in llamadas and "execute" in llamadas

    fuente_funcion = ast.get_source_segment(_fuente("backend/app/main.py"), funcion)
    assert 'text("SELECT 1")' in fuente_funcion
    assert "status.HTTP_503_SERVICE_UNAVAILABLE" in fuente_funcion
    assert "JSONResponse" in fuente_funcion


def test_nginx_proxya_liveness_y_readiness():
    nginx = _fuente("nginx.render.conf")
    assert "location = /health {" in nginx
    assert "location = /health/db {" in nginx
    # El comentario deja claro cuál usa Render y cuál es para monitoreo externo.
    assert "LIVENESS" in nginx and "READINESS" in nginx
    # /health/db NO debe quedar atrapado por el `location = /health` (son exactos).
    assert nginx.count("proxy_pass http://127.0.0.1:8000;") >= 4
