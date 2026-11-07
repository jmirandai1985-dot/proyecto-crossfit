"""Endpoint `GET /historial-rm/alumnos/{id}/movimiento/{id}` — AISLADO.

Verifica, SIN BD y SIN red, que cada registro del historial por movimiento
incluye `movimiento_id` (además de `movimiento_nombre`/`categoria`). Ese campo es
el que usa el frontend (`evolucionPorMovimiento`) para agrupar; sin él el panel
expandido de Evolución deja "Próximo objetivo" y "Último PR" vacíos.

    cd backend && py -3.12 -m pytest tests/test_historial_movimiento_movimiento_id.py -q --noconftest
"""
import sys
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1.historial_rm import router  # noqa: E402
from app.core.dependencies import get_current_user, get_db, require_full_access  # noqa: E402
from app.models.historial_rm import HistorialRM  # noqa: E402
from app.models.movimiento import Movimiento  # noqa: E402

TENANT = 1
ALUMNO_ID = 123
MOVIMIENTO_ID = 55


class _FilaMovimiento:
    def __init__(self, id_=MOVIMIENTO_ID, nombre="Back Squat", categoria="fuerza"):
        self.id = id_
        self.nombre = nombre
        self.categoria = categoria


class _FilaRegistro:
    def __init__(self, id_=1, peso_kg=100.0, movimiento_id=MOVIMIENTO_ID):
        self.id = id_
        self.fecha = date(2026, 5, 1)
        self.peso_kg = peso_kg
        self.repeticiones = None
        self.series = None
        self.minutos = None
        self.vueltas = None
        self.km = None
        self.calorias = None
        self.notas = None
        self.movimiento_id = movimiento_id


class _Consulta:
    def __init__(self, fila=None, filas=None):
        self._fila = fila
        self._filas = filas

    def filter(self, *criterios):
        return self

    def first(self):
        return self._fila

    def order_by(self, *args):
        return self

    def all(self):
        return self._filas or []


class _SesionFalsa:
    def __init__(self, movimiento=None, registros=None):
        self._movimiento = movimiento
        self._registros = registros or []

    def query(self, *modelos):
        if modelos and modelos[0] is Movimiento:
            return _Consulta(fila=self._movimiento)
        if modelos and modelos[0] is HistorialRM:
            return _Consulta(filas=self._registros)
        return _Consulta()

    def add(self, obj):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


async def _staff_falso():
    return {
        "usuario_id": 7,
        "tenant_id": TENANT,
        "rol": "admin",
        "correo": "admin@test.com",
        "nombre": "Admin",
        "activo": True,
        "estado": "activo",
    }


def _cliente_con(sesion):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/historial-rm")
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[get_current_user] = _staff_falso
    app.dependency_overrides[require_full_access] = lambda: None
    return TestClient(app)


def _ruta(alumno_id=ALUMNO_ID, movimiento_id=MOVIMIENTO_ID):
    return f"/api/v1/historial-rm/alumnos/{alumno_id}/movimiento/{movimiento_id}"


def test_cada_registro_incluye_movimiento_id():
    movimiento = _FilaMovimiento()
    registros = [
        _FilaRegistro(id_=1, peso_kg=80.0, movimiento_id=MOVIMIENTO_ID),
        _FilaRegistro(id_=2, peso_kg=85.0, movimiento_id=MOVIMIENTO_ID),
    ]
    sesion = _SesionFalsa(movimiento=movimiento, registros=registros)
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2
    for item in body:
        assert item["movimiento_id"] == MOVIMIENTO_ID
        assert item["movimiento_nombre"] == "Back Squat"
        assert item["categoria"] == "fuerza"
    assert [item["peso_kg"] for item in body] == [80.0, 85.0]


def test_sin_registros_devuelve_lista_vacia():
    sesion = _SesionFalsa(movimiento=_FilaMovimiento(), registros=[])
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 200, r.text
    assert r.json() == []
