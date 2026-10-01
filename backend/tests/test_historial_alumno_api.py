"""Historial del alumno (API): las dos puertas del panel y quién puede entrar por cada una.

  * `GET /api/v1/alumnos/me/historial`           → el propio alumno, sin la gestión del box.
  * `GET /api/v1/alumnos/{alumno_id}/historial`  → admin del box; el propio alumno también,
                                                    pero sin la gestión.

Lo que fija este archivo (permisos = "tests completos del caso"):

  A. ORDEN de las rutas: `me` está registrada antes que `{alumno_id}` (si no, "me" se intenta
     parsear como int y la ruta del alumno da 422). Se comprueba en el router Y de punta a punta
     con un request real a `/alumnos/me/historial`.
  B. ACL: admin entra a cualquier alumno del box; el alumno entra a la suya (y NO a la de otro);
     el COACH recibe 403 (el panel trae plata); el staff no puede usar la puerta del alumno.
  C. 404 de un alumno que no existe en el tenant del token, 422 de una sección/página inválida y
     200 de la sección `beneficios` (existe, responde y YA se anuncia: la F2 le dio contenido).
  D. FIX 1: con plan de prueba, la sección `rms` responde 403 y las otras siguen abiertas.

Corre con `TestClient` (httpx ya está en requirements): no levanta servidor, pero pega contra la
MISMA rama TEST por la dependencia `get_db`. El guard `is_test_db_url` falla CERRADO.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_historial_alumno_api.py -q
"""
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1 import historial_alumno                                # noqa: E402
from app.core.security import create_access_token                      # noqa: E402

TENANT_ID = 1


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST (falla cerrado)."""
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def tokens(db):
    """Tokens REALES (mismo camino que el navegador) para un admin, un alumno y un coach de TEST.

    Se buscan en la base en vez de hardcodear ids: si la rama no tiene alguno de los tres roles,
    el archivo se omite en vez de dar un falso rojo.
    """
    from sqlalchemy import text

    def _buscar(rol):
        fila = db.execute(text(
            "SELECT id FROM usuarios WHERE tenant_id = :t AND rol = :r "
            "AND estado = 'activo' ORDER BY id LIMIT 1"),
            {"t": TENANT_ID, "r": rol}).first()
        return int(fila[0]) if fila else None

    ids = {rol: _buscar(rol) for rol in ("administrador", "alumno", "coach")}
    faltan = [rol for rol, valor in ids.items() if valor is None]
    if faltan:
        pytest.skip(f"TEST no tiene usuarios de estos roles: {', '.join(faltan)}")

    def _token(rol, correo):
        return {"Authorization": "Bearer " + create_access_token({
            "usuario_id": ids[rol], "tenant_id": TENANT_ID, "rol": rol, "correo": correo})}

    return {
        "ids": ids,
        "admin": _token("administrador", "admin@test.com"),
        "alumno": _token("alumno", "alumno@test.com"),
        "coach": _token("coach", "coach@test.com"),
    }


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin levantar servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


BASE = "/api/v1/alumnos"


# ══════════════════════════════════════════════════════════════════════════════
# A. Orden de las rutas
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_la_ruta_me_se_registra_antes_que_la_del_alumno():
    caminos = [r.path for r in historial_alumno.router.routes]

    assert caminos.index("/me/historial") < caminos.index("/{alumno_id}/historial")


def test_a2_alumnos_me_historial_responde_200_y_no_422(cliente, tokens):
    """De punta a punta: si `me` se registrara después, esto sería 422 ("me" no es int)."""
    r = cliente.get(f"{BASE}/me/historial", headers=tokens["alumno"])

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["seccion"] == "resumen"
    assert cuerpo["alumno"]["id"] == tokens["ids"]["alumno"]
    assert cuerpo["incluye_privado"] is False
    assert "gestion" not in cuerpo["datos"]


# ══════════════════════════════════════════════════════════════════════════════
# B. ACL
# ══════════════════════════════════════════════════════════════════════════════
def test_b1_el_admin_ve_el_historial_completo_de_un_alumno(cliente, tokens):
    alumno_id = tokens["ids"]["alumno"]
    r = cliente.get(f"{BASE}/{alumno_id}/historial", headers=tokens["admin"])

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["alumno"]["id"] == alumno_id
    assert cuerpo["incluye_privado"] is True
    assert "gestion" in cuerpo["datos"], "el admin tiene que ver la gestión del box"
    # El menú trae las 6 secciones listas: `beneficios` se sumó al implementarse la F2.
    assert len(cuerpo["secciones"]) == 6
    assert all(s["disponible"] for s in cuerpo["secciones"])


def test_b2_el_coach_recibe_403_en_ambas_puertas(cliente, tokens):
    """El panel trae plata: el coach no entra (su ficha es la acotada, sin datos financieros)."""
    alumno_id = tokens["ids"]["alumno"]

    en_la_del_alumno = cliente.get(f"{BASE}/{alumno_id}/historial", headers=tokens["coach"])
    assert en_la_del_alumno.status_code == 403
    assert "administración" in en_la_del_alumno.json()["detail"]

    en_la_propia = cliente.get(f"{BASE}/me/historial", headers=tokens["coach"])
    assert en_la_propia.status_code == 403


def test_b3_otro_alumno_no_ve_el_historial_ajeno(cliente, tokens):
    """El alumno entra a la SUYA (sin gestión) pero no a la de otro."""
    alumno_id = tokens["ids"]["alumno"]

    propia = cliente.get(f"{BASE}/{alumno_id}/historial", headers=tokens["alumno"])
    assert propia.status_code == 200, propia.text
    assert propia.json()["incluye_privado"] is False
    assert "gestion" not in propia.json()["datos"]

    ajena = cliente.get(f"{BASE}/{alumno_id + 777_000}/historial", headers=tokens["alumno"])
    assert ajena.status_code == 403, ajena.text


def test_b4_el_staff_no_usa_la_puerta_del_alumno(cliente, tokens):
    r = cliente.get(f"{BASE}/me/historial", headers=tokens["admin"])

    assert r.status_code == 403
    assert "/alumnos/{alumno_id}/historial" in r.json()["detail"]


def test_b5_sin_token_es_401(cliente):
    assert cliente.get(f"{BASE}/me/historial").status_code == 401
    assert cliente.get(f"{BASE}/1/historial").status_code == 401


def test_b6_el_router_nuevo_no_tapa_las_rutas_que_ya_existian(cliente, tokens):
    """Se registra ANTES que `alumnos.router`: `/alumnos/me` (y el resto) siguen respondiendo."""
    r = cliente.get("/api/v1/alumnos/me", headers=tokens["alumno"])

    assert r.status_code == 200, r.text
    assert r.json()["id"] == tokens["ids"]["alumno"]


# ══════════════════════════════════════════════════════════════════════════════
# C. 404 / 422 / sección reservada
# ══════════════════════════════════════════════════════════════════════════════
def test_c1_alumno_inexistente_404(cliente, tokens):
    r = cliente.get(f"{BASE}/999999999/historial", headers=tokens["admin"])

    assert r.status_code == 404
    assert "no encontrado" in r.json()["detail"]


def test_c2_seccion_invalida_y_paginacion_invalida_422(cliente, tokens):
    assert cliente.get(f"{BASE}/me/historial?seccion=clases",
                       headers=tokens["alumno"]).status_code == 422
    assert cliente.get(f"{BASE}/me/historial?pagina=0",
                       headers=tokens["alumno"]).status_code == 422
    assert cliente.get(f"{BASE}/me/historial?por_pagina=5000",
                       headers=tokens["alumno"]).status_code == 422


def test_c3_beneficios_se_anuncia_y_responde(cliente, tokens):
    """La sección existe, responde y YA se anuncia (la F2 le dio contenido)."""
    r = cliente.get(f"{BASE}/me/historial?seccion=beneficios", headers=tokens["alumno"])

    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["disponible"] is True and datos["motivo"] is None
    assert set(datos["totales"]) == {"total", "vigentes", "usados", "vencidos", "anulados"}
    secciones = {s["id"]: s for s in r.json()["secciones"]}
    assert len(secciones) == 6
    assert secciones["beneficios"]["disponible"] is True
    assert secciones["asistencia"]["disponible"] is True


def test_c4_la_paginacion_llega_al_servicio(cliente, tokens):
    r = cliente.get(f"{BASE}/me/historial?seccion=asistencia&pagina=1&por_pagina=2",
                    headers=tokens["alumno"])

    assert r.status_code == 200, r.text
    paginado = r.json()["datos"]["paginado"]
    assert paginado["pagina"] == 1 and paginado["por_pagina"] == 2
    assert len(r.json()["datos"]["items"]) <= 2


# ══════════════════════════════════════════════════════════════════════════════
# D. FIX 1: plan de prueba sin RMs
# ══════════════════════════════════════════════════════════════════════════════
def test_d1_con_plan_de_prueba_los_rms_dan_403(cliente, tokens, monkeypatch):
    monkeypatch.setattr(historial_alumno, "es_usuario_prueba", lambda _db, _uid: True)

    con_rms = cliente.get(f"{BASE}/me/historial?seccion=rms", headers=tokens["alumno"])
    assert con_rms.status_code == 403
    assert "plan de prueba" in con_rms.json()["detail"]

    # Las otras secciones siguen abiertas: son su asistencia, su plan y sus pagos.
    for seccion in ("resumen", "asistencia", "pagos", "membresias"):
        r = cliente.get(f"{BASE}/me/historial?seccion={seccion}", headers=tokens["alumno"])
        assert r.status_code == 200, f"{seccion}: {r.text}"


def test_d2_sin_plan_de_prueba_los_rms_se_ven(cliente, tokens, monkeypatch):
    monkeypatch.setattr(historial_alumno, "es_usuario_prueba", lambda _db, _uid: False)

    r = cliente.get(f"{BASE}/me/historial?seccion=rms", headers=tokens["alumno"])
    assert r.status_code == 200, r.text
