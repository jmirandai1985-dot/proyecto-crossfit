"""Correo puntual del padrón (`PATCH /migracion-boxmagic/candidato/{id}/correo`) — AISLADO.

SIN BD ni red: app mínima con el router REAL, `get_db` falsa y `_candidato_del_box`
monkeypatcheado (mismo patrón que `test_migracion_candidato_edicion.py`). Cubre:
  * guarda el correo NORMALIZADO (sin espacios, minúsculas);
  * 422 para un correo con formato inválido;
  * 409 si ese correo ya pertenece a otro candidato del mismo box (UNIQUE);
  * 404 fuera del box/inexistente y 403 para no-admin.

    cd backend && py -3.12 -m pytest tests/test_migracion_candidato_correo.py -q --noconftest
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import migracion_boxmagic  # noqa: E402
from app.core.dependencies import (  # noqa: E402
    get_current_admin, get_current_user, get_db,
)
from app.models.candidato_boxmagic import CandidatoBoxmagic  # noqa: E402

TENANT = 1
ADMIN_ID = 7
RUTA = "/api/v1/migracion-boxmagic"


class _Consulta:
    def __init__(self, filas=None):
        self._filas = list(filas or [])

    def filter(self, *criterios):
        return self

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFalsa:
    def __init__(self, duplicados=None):
        self._duplicados = duplicados or []
        self.commits = 0

    def query(self, modelo):
        if modelo is CandidatoBoxmagic:
            return _Consulta(self._duplicados)
        return _Consulta([])

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def refresh(self, obj):
        pass


def _candidato(id_=201, nombre="Sin Correo", correo=""):
    return CandidatoBoxmagic(
        id=id_, tenant_id=TENANT, nombre=nombre, correo=correo,
        estado_boxmagic="Activo", grupo="activacion",
    )


async def _admin_falso():
    return {"usuario_id": ADMIN_ID, "tenant_id": TENANT, "rol": "admin"}


def _cliente(sesion, rol="admin"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(migracion_boxmagic.router, prefix=RUTA)
    app.dependency_overrides[get_db] = lambda: sesion
    if rol == "admin":
        app.dependency_overrides[get_current_admin] = _admin_falso
    else:
        async def _no_admin():
            return {"usuario_id": 1, "tenant_id": TENANT, "rol": rol}
        app.dependency_overrides[get_current_user] = _no_admin
    return TestClient(app)


def test_guarda_el_correo_normalizado(monkeypatch):
    candidato = _candidato()
    sesion = _SesionFalsa()
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)

    r = _cliente(sesion).patch(
        f"{RUTA}/candidato/201/correo",
        json={"correo": "  ANA.SOTO@Test.COM "})

    assert r.status_code == 200, r.text
    assert r.json() == {
        "candidato_id": 201,
        "nombre": "Sin Correo",
        "correo": "ana.soto@test.com",
    }
    assert candidato.correo == "ana.soto@test.com"
    assert sesion.commits == 1


def test_correo_invalido_422(monkeypatch):
    candidato = _candidato(correo="viejo@test.com")
    sesion = _SesionFalsa()
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)

    r = _cliente(sesion).patch(
        f"{RUTA}/candidato/201/correo", json={"correo": "no-es-un-correo"})

    assert r.status_code == 422, r.text
    assert candidato.correo == "viejo@test.com"
    assert sesion.commits == 0


def test_correo_duplicado_409(monkeypatch):
    candidato = _candidato()
    otro = _candidato(id_=202, nombre="Otro", correo="ocupado@test.com")
    sesion = _SesionFalsa(duplicados=[otro])
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)

    r = _cliente(sesion).patch(
        f"{RUTA}/candidato/201/correo", json={"correo": "ocupado@test.com"})

    assert r.status_code == 409, r.text
    assert "ese correo" in r.json()["detail"]
    assert candidato.correo == ""
    assert sesion.commits == 0


def test_candidato_inexistente_404():
    sesion = _SesionFalsa()

    r = _cliente(sesion).patch(
        f"{RUTA}/candidato/999/correo", json={"correo": "ana@test.com"})

    assert r.status_code == 404, r.text
    assert "no encontrado" in r.json()["detail"].lower()


def test_no_admin_403(monkeypatch):
    candidato = _candidato()
    sesion = _SesionFalsa()
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)

    r = _cliente(sesion, rol="alumno").patch(
        f"{RUTA}/candidato/201/correo", json={"correo": "ana@test.com"})

    assert r.status_code == 403, r.text
    assert candidato.correo == ""
