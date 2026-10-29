"""CORS endurecido (auditoría 1.2): métodos/cabeceras explícitos y validación al arrancar.

Qué cubre
---------
1. `validar_cors_origins` (app/core/config.py): sanea la barra final y los duplicados,
   descarta `*` y las entradas rotas, y en PRODUCCIÓN **aborta el arranque** en vez de
   dejar el frontend mudo con un "CORS policy" en la consola del navegador.
2. El middleware real (la MISMA app que sirve el navegador): el preflight que manda
   axios (Authorization + Content-Type, POST/PUT/PATCH/DELETE) responde 200; una cabecera
   o un método que el API no usa responde 400; `*` ya no se anuncia; una respuesta simple
   al origen permitido lleva su `Origin` exacto (necesario con `allow_credentials`).

No toca la base de datos: `/health` es liveness puro y el preflight no llega al router.
"""
import logging
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import (                                    # noqa: E402
    problemas_cors_origins,
    validar_cors_origins,
)

LOCAL = "http://localhost:5173"
PROD = "https://app.boxcrossfit.cl"
AJENO = "https://sitio-ajeno.example.com"


# ── 1. Saneado y validación de la lista (función pura) ──────────────────────

def test_sanea_barra_final_espacios_y_duplicados():
    """`https://app.cl/` NUNCA coincide con el `Origin` del navegador (que va sin `/`)."""
    limpios = validar_cors_origins(
        [f"{PROD}/", f"  {PROD}  ", "", PROD], entorno="production")
    assert limpios == [PROD]


def test_el_asterisco_nunca_queda_en_la_lista():
    """Con `allow_credentials=True` el comodín abriría el API a cualquier sitio."""
    assert validar_cors_origins(["*", LOCAL], entorno="test") == [LOCAL]
    assert validar_cors_origins(["*"], entorno="test") == []


def test_descarta_entradas_rotas_y_conserva_las_buenas():
    limpios = validar_cors_origins(
        ["localhost:5173", "https://app.cl/login", LOCAL], entorno="test")
    assert limpios == [LOCAL]


def test_produccion_con_https_valido_pasa():
    assert validar_cors_origins([PROD, f"{PROD}/"], entorno="production") == [PROD]


@pytest.mark.parametrize("origins", [
    ["http://app.boxcrossfit.cl"],         # sin TLS en producción
    ["http://localhost:5173"],             # localhost en producción
    ["http://127.0.0.1:5173"],             # idem
    ["*"],                                 # comodín
    ["app.boxcrossfit.cl"],                # sin esquema
    ["https://app.boxcrossfit.cl/login"],  # con path: el navegador manda sólo el origen
    [],                                    # vacío
])
def test_produccion_aborta_el_arranque_si_algo_no_sirve(origins):
    """Fail-fast: mejor un deploy que no levanta que un frontend mudo (sin log en el backend)."""
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validar_cors_origins(origins, entorno="production")


def test_test_no_aborta_pero_avisa(caplog):
    """En TEST/dev la suite no se puede romper por un `.env.test` imperfecto."""
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        limpios = validar_cors_origins(["*", LOCAL], entorno="test")
    assert limpios == [LOCAL]
    assert "CORS_ORIGINS" in caplog.text


def test_localhost_es_valido_fuera_de_produccion():
    assert validar_cors_origins([LOCAL, "http://localhost:3000"], entorno="test") == [
        LOCAL, "http://localhost:3000"]


def test_problemas_de_un_origen_suelto():
    assert problemas_cors_origins(PROD, entorno="production") == []
    assert any("path" in p for p in problemas_cors_origins(f"{PROD}/admin", "production"))
    assert any("localhost" in p for p in problemas_cors_origins(LOCAL, "production"))
    assert any("*" in p for p in problemas_cors_origins("*", "production"))


# ── 2. El middleware de verdad (preflight del navegador) ────────────────────

@pytest.fixture(scope="module")
def cliente():
    """TestClient de la app real (sin levantar servidor ni correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def origen():
    """Un origen permitido de los que quedan configurados (`.env.test`)."""
    from app.main import _cors_origins
    assert _cors_origins, "CORS_ORIGINS/.env.test no dejó ningún origen válido"
    return _cors_origins[0]


def _preflight(cliente, origin, metodo="POST",
               cabeceras="authorization,content-type"):
    return cliente.options(
        "/api/v1/reservas/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": metodo,
            "Access-Control-Request-Headers": cabeceras,
        },
    )


def test_el_preflight_que_manda_el_frontend_pasa(cliente, origen):
    """axios manda `Authorization` + `Content-Type`; el 200 es lo que ya ocurre hoy."""
    r = _preflight(cliente, origen)
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == origen
    assert r.headers.get("access-control-allow-credentials") == "true"

    metodos = r.headers["access-control-allow-methods"].lower()
    for metodo in ("get", "post", "put", "patch", "delete"):
        assert metodo in metodos, f"falta {metodo} en {metodos}"
    assert "authorization" in r.headers["access-control-allow-headers"].lower()


def test_ya_no_se_anuncia_comodin_de_metodos_ni_cabeceras(cliente, origen):
    """Antes era `allow_methods=["*"]` / `allow_headers=["*"]` (auditoría 1.2)."""
    r = _preflight(cliente, origen)
    assert "*" not in r.headers["access-control-allow-methods"]
    assert "*" not in r.headers["access-control-allow-headers"]


def test_patch_sigue_permitido(cliente, origen):
    """`/api/v1/supervision/cupo-disciplina` es el único PATCH del API."""
    r = _preflight(cliente, origen, metodo="PATCH", cabeceras="authorization")
    assert r.status_code == 200, r.text


def test_una_cabecera_que_el_api_no_usa_se_rechaza(cliente, origen):
    r = _preflight(cliente, origen, cabeceras="x-cabecera-inventada")
    assert r.status_code == 400, r.text
    assert "header" in r.text.lower()


def test_un_metodo_que_el_api_no_usa_se_rechaza(cliente, origen):
    r = _preflight(cliente, origen, metodo="TRACE", cabeceras="authorization")
    assert r.status_code == 400, r.text
    assert "method" in r.text.lower()


def test_un_origen_ajeno_se_rechaza(cliente):
    r = _preflight(cliente, AJENO)
    assert r.status_code == 400, r.text
    assert "origin" in r.text.lower()


def test_respuesta_simple_lleva_el_origen_exacto_y_el_header_expuesto(cliente, origen):
    """Con credenciales el navegador exige el origin literal (nunca `*`)."""
    r = cliente.get("/health", headers={"Origin": origen})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origen
    assert r.headers.get("access-control-allow-credentials") == "true"
    assert "X-Total-Count" in r.headers.get("access-control-expose-headers", "")

