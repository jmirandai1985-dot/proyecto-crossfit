"""Edición del padrón de BoxMagic (`PUT /migracion-boxmagic/candidatos/{id}`) — AISLADO.

Cubre SIN BD ni red (app mínima con el router REAL, `get_db` falsa y dependencias
overrideadas):
  * edita nombre + correo y normaliza el correo;
  * 422 para un correo con formato inválido;
  * 400 claro si el correo choca con otro candidato del box (UNIQUE);
  * 400 si el candidato ya tiene cuenta real y se intenta cambiar el correo
    (rompería el LEFT JOIN); el nombre sí se puede editar;
  * 404 fuera del box/inexistente y 403 para no-admin.

    cd backend && py -3.12 -m pytest tests/test_migracion_candidato_edicion.py -q --noconftest
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
from app.models.usuario import Usuario  # noqa: E402

TENANT = 1
ADMIN_ID = 7
RUTA = "/api/v1/migracion-boxmagic"


class _Candidato:
    def __init__(self, id_, nombre, correo, grupo="recuperacion", tenant_id=TENANT):
        self.id = id_
        self.tenant_id = tenant_id
        self.nombre = nombre
        self.correo = correo
        self.grupo = grupo


class _Usuario:
    def __init__(self, id_, correo, tenant_id=TENANT):
        self.id = id_
        self.tenant_id = tenant_id
        self.correo = correo
        self.rol = "alumno"
        self.estado = "activo"


class _Consulta:
    def __init__(self, filas=None):
        self._filas = list(filas or [])

    def filter(self, *criterios):
        return self

    def order_by(self, *criterios):
        return self

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFalsa:
    """Devuelve las filas que el test le da; los filtros se prueban en integración."""

    def __init__(self, candidatos=None, usuarios=None):
        self._candidatos = candidatos or []
        self._usuarios = usuarios or []
        self.commits = 0

    def query(self, *modelos):
        primero = modelos[0] if modelos else None
        if primero is CandidatoBoxmagic:
            return _Consulta(self._candidatos)
        if primero is Usuario:
            return _Consulta(self._usuarios)
        return _Consulta([])

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


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


def _cuerpo(nombre="Juan Miranda", correo="juan.miranda@test.com"):
    return {"nombre": nombre, "correo": correo}


def test_edita_nombre_y_correo_normalizado(monkeypatch):
    candidato = _Candidato(201, "j.miranday1985", "j.miranday1985@test.com",
                           grupo="activacion")
    sesion = _SesionFalsa()
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)

    r = _cliente(sesion).put(
        f"{RUTA}/candidatos/201",
        json=_cuerpo(nombre="  Juan   Miranda  ", correo=" JUAN.MIRANDA@Test.COM "))

    assert r.status_code == 200, r.text
    assert r.json() == {
        "candidato_id": 201,
        "nombre": "Juan Miranda",
        "correo": "juan.miranda@test.com",
    }
    assert candidato.nombre == "Juan Miranda"
    assert candidato.correo == "juan.miranda@test.com"
    assert sesion.commits == 1


def test_correo_invalido_422(monkeypatch):
    candidato = _Candidato(201, "Juan", "juan@test.com")
    sesion = _SesionFalsa()
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)

    r = _cliente(sesion).put(
        f"{RUTA}/candidatos/201",
        json=_cuerpo(correo="j.miranday1985"))

    assert r.status_code == 422, r.text
    assert candidato.correo == "juan@test.com"
    assert sesion.commits == 0


def test_correo_duplicado_400_claro(monkeypatch):
    candidato = _Candidato(201, "Juan", "juan@test.com")
    otro = _Candidato(202, "Otro", "ocupado@test.com")
    sesion = _SesionFalsa(candidatos=[otro])
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)

    r = _cliente(sesion).put(
        f"{RUTA}/candidatos/201",
        json=_cuerpo(correo="ocupado@test.com"))

    assert r.status_code == 400, r.text
    assert "Ya existe un candidato con ese correo" in r.json()["detail"]
    assert candidato.correo == "juan@test.com"
    assert sesion.commits == 0


def test_con_cuenta_real_bloquea_correo_pero_permite_nombre(monkeypatch):
    candidato = _Candidato(201, "Juan", "real@test.com")
    sesion = _SesionFalsa(usuarios=[_Usuario(9, "real@test.com")])
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)
    cliente = _cliente(sesion)

    r = cliente.put(f"{RUTA}/candidatos/201",
                    json=_cuerpo(correo="nuevo@test.com"))
    assert r.status_code == 400, r.text
    assert "cuenta real" in r.json()["detail"]
    assert candidato.correo == "real@test.com"

    r = cliente.put(f"{RUTA}/candidatos/201",
                    json=_cuerpo(nombre="Juan Pérez", correo="real@test.com"))
    assert r.status_code == 200, r.text
    assert candidato.nombre == "Juan Pérez"
    assert candidato.correo == "real@test.com"


def test_candidato_inexistente_404():
    sesion = _SesionFalsa()
    r = _cliente(sesion).put(f"{RUTA}/candidatos/999", json=_cuerpo())
    assert r.status_code == 404, r.text
    assert "no encontrado" in r.json()["detail"].lower()


def test_no_admin_403(monkeypatch):
    candidato = _Candidato(201, "Juan", "juan@test.com")
    sesion = _SesionFalsa()
    monkeypatch.setattr(migracion_boxmagic, "_candidato_del_box",
                        lambda db, tenant, id_: candidato)

    r = _cliente(sesion, rol="alumno").put(
        f"{RUTA}/candidatos/201", json=_cuerpo())

    assert r.status_code == 403, r.text
    assert candidato.correo == "juan@test.com"
