"""El predicado de "reserva cancelada" tiene que ser UNO (2026-09-27).

Antes: la app comparaba contra el literal `'cancelled'` en 6 módulos y el job de mantenimiento
contra `ILIKE '%cancel%'`. Dos criterios para el mismo dato, así que una variante nueva se
comportaba distinto en cada lado y en silencio: una reserva que el job veía "viva" en el paso 8
recibía `updated_at`, que es el dato con el que A.3 reconstruye la devolución del crédito.

Ahora la lista vive en `shared/estados.py` (paquete neutral: **sin imports**, porque la copia la
imagen del Cron Job, que no tiene SQLAlchemy ni FastAPI) y la importan las dos partes:
`app/core/estados.py` (los predicados de SQLAlchemy) y `maintenance/mantenimiento_cloud.py` (el
SQL). El mantenimiento, además, delata las variantes que la lista no conoce con la detección A.6.
"""
import ast
from pathlib import Path

import pytest

from shared import estados

RAIZ = Path(__file__).resolve().parents[1]         # backend/
APP = RAIZ / "app"
MANTENIMIENTO = RAIZ / "maintenance"
COMPARTIDO = RAIZ / "shared"

MODULOS_APP = (
    "app/api/v1/reservas.py",
    "app/api/v1/asistencia.py",
    "app/api/v1/supervision.py",
    "app/api/v1/kpis_populate.py",
    "app/api/v1/fidelizacion.py",
    "app/api/v1/wods.py",
)


def _fuentes(carpetas) -> list:
    """`(ruta relativa, fuente)` de cada `.py` de esas carpetas (sin `__pycache__`).

    Se lee con `utf-8-sig`: hay archivos del repo guardados con BOM (editores de Windows) y el
    BOM rompe `ast.parse`, no el código.
    """
    salida = []
    for carpeta in carpetas:
        for ruta in sorted(carpeta.rglob("*.py")):
            if "__pycache__" in ruta.parts:
                continue
            salida.append((ruta.relative_to(RAIZ).as_posix(),
                           ruta.read_text(encoding="utf-8-sig")))
    return salida


def _asignados(arbol: ast.Module, nombres: tuple) -> list:
    """Nombres asignados a nivel de módulo (incluye `X: Final[str] = …`)."""
    encontrados = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign):
            encontrados += [t.id for t in nodo.targets if isinstance(t, ast.Name)]
        elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            encontrados.append(nodo.target.id)
    return sorted(n for n in encontrados if n in nombres)


def _strings(arbol: ast.Module) -> list:
    return [n.value for n in ast.walk(arbol)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_a_la_constante_se_define_solo_en_shared_estados():
    """Una sola definición en todo el backend: si alguien vuelve a escribir la tupla (en la app o
    en el mantenimiento), el test falla y dice en qué archivo."""
    nombres = ("ESTADOS_CANCELADA", "ESTADO_CANCELADO")
    definiciones = {}
    for rel, fuente in _fuentes((APP, MANTENIMIENTO, RAIZ / "ml", COMPARTIDO)):
        hallados = _asignados(ast.parse(fuente), nombres)
        if hallados:
            definiciones[rel] = hallados

    assert list(definiciones) == ["shared/estados.py"], definiciones
    assert definiciones["shared/estados.py"] == sorted(nombres)
    assert estados.ESTADOS_CANCELADA == ("cancelled", "cancelada")
    assert estados.ESTADO_CANCELADO == "cancelled"
    assert estados.ESTADO_CANCELADO in estados.ESTADOS_CANCELADA


def test_b_shared_no_importa_nada():
    """El paquete neutral no puede arrastrar NADA: la imagen del Cron Job sólo copia
    `maintenance/` y `shared/` (ni SQLAlchemy, ni FastAPI, ni la app)."""
    permitidos = {"typing", "__future__"}
    for rel, fuente in _fuentes((COMPARTIDO,)):
        for nodo in ast.walk(ast.parse(fuente)):
            if isinstance(nodo, ast.Import):
                assert {a.name.split(".")[0] for a in nodo.names} <= permitidos, rel
            elif isinstance(nodo, ast.ImportFrom):
                assert nodo.level == 0, f"{rel}: import relativo"
                assert nodo.module.split(".")[0] in permitidos, f"{rel}: {nodo.module}"

    assert (COMPARTIDO / "__init__.py").exists()
    assert (COMPARTIDO / "estados.py").exists()


def test_c_los_helpers_son_exactos_y_derivan_de_la_constante(monkeypatch):
    """`lista_sql()` es la lista del SQL y `es_cancelada()` el mismo criterio del lado Python:
    **exacto** (nada de `lower()` ni de `LIKE` "por parecido": eso es justamente lo que hacía
    imposible ver una variante nueva)."""
    assert estados.lista_sql() == "'cancelled', 'cancelada'"
    assert estados.es_cancelada("cancelled") is True
    assert estados.es_cancelada("cancelada") is True
    for otro in (None, "", "confirmada", "cancelled_x", "Cancelled", "CANCELADA", "reserved"):
        assert estados.es_cancelada(otro) is False, otro

    # el SQL se ARMA leyendo la constante (no una copia): si la lista cambia, cambia el SQL del job
    from maintenance import mantenimiento_cloud as men
    monkeypatch.setattr(estados, "ESTADOS_CANCELADA", ("muerta",))
    assert estados.lista_sql() == "'muerta'"
    assert estados.es_cancelada("muerta") and not estados.es_cancelada("cancelled")
    assert men.lista_sql() == "'muerta'"
    assert men.sql_viva() == "r.estado NOT IN ('muerta')"
    assert men.sql_cancelada() == "r.estado IN ('muerta')"



@pytest.mark.parametrize("rel", MODULOS_APP)
def test_d_la_app_no_compara_contra_el_literal(rel):
    """Ningún módulo de la app escribe el literal `'cancelled'`: todos usan la lista (o los helpers)
    de `app.core.estados`."""
    fuente = (RAIZ / rel).read_text(encoding="utf-8")
    literales = [s for s in _strings(ast.parse(fuente)) if s in estados.ESTADOS_CANCELADA]

    assert literales == [], f"{rel} quedó con literales sueltos: {literales}"
    assert "from app.core.estados import" in fuente, rel


def test_e_el_predicado_de_la_app_es_el_mismo_que_el_del_job():
    """`no_cancelada()` (SQLAlchemy) y `sql_viva()` (SQL del job) tienen que dar la MISMA lista:
    es el punto entero de tener una sola definición."""
    from sqlalchemy import column

    from app.core.estados import no_cancelada
    from maintenance import mantenimiento_cloud as men

    expr = no_cancelada(column("estado"))
    compilado = str(expr.compile(compile_kwargs={"literal_binds": True}))

    assert compilado == f"(estado NOT IN ({men.lista_sql()}))"
    assert men.sql_viva("r") == f"r.estado NOT IN ({men.lista_sql()})"


def _dockerfile_render() -> str:
    """El Dockerfile del Web Service (raíz del repo) + coherencia con render.yaml.

    `Dockerfile.render` vive FUERA de `backend/`, así que el test lo busca en la raíz y además
    verifica que render.yaml siga apuntándole: si el deploy pasa a otra imagen, la guarda de
    `shared/` tiene que moverse con él (y este test lo avisa).
    """
    raiz_repo = RAIZ.parent
    yaml = (raiz_repo / "render.yaml").read_text(encoding="utf-8-sig")
    assert "dockerfilePath: Dockerfile.render" in yaml, "render.yaml dejó de usar Dockerfile.render"
    assert "dockerContext: ." in yaml, "el contexto del build de Render dejó de ser la raíz"
    return (raiz_repo / "Dockerfile.render").read_text(encoding="utf-8-sig")


def test_f_las_tres_imagenes_docker_copian_shared():
    """Las TRES imágenes importan `shared`: la que no lo copie muere en runtime con
    "No module named 'shared'" (el Web Service al arrancar, el job de noche).

    Las tres dejan el paquete en el MISMO lugar (`shared/` bajo el WORKDIR `/app`), pero la ruta
    de ORIGEN depende del contexto del build:
      * `backend/Dockerfile` y `backend/Dockerfile.cron` → contexto `backend/` (docker-compose /
        build hook) ⇒ `COPY shared/ shared/` y `COPY shared/estados.py`.
      * `Dockerfile.render` (raíz; el del Web Service de Render: render.yaml → `dockerfilePath:
        Dockerfile.render`, `dockerContext: .`) ⇒ `COPY backend/shared/ shared/`.

    Regresión real (2026-09-27): a Dockerfile.render le faltaba esa línea, así que el contenedor de
    PROD no habría arrancado (uvicorn importa `app.main` al iniciar y los routers pasan por
    `app.core.estados`).
    """
    web = (RAIZ / "Dockerfile").read_text(encoding="utf-8-sig")
    cron = (RAIZ / "Dockerfile.cron").read_text(encoding="utf-8-sig")
    render = _dockerfile_render()

    assert "COPY shared/ shared/" in web
    assert "COPY shared/__init__.py" in cron and "COPY shared/estados.py" in cron
    assert "COPY backend/shared/ shared/" in render
    assert "COPY app/" not in cron          # invariante: la imagen del job no lleva la app
