"""Endpoint admin `GET /api/v1/admin/alumnos/{usuario_id}/codigo-referido` — AISLADO.

Cubre, SIN BD y SIN red (app mínima con el router REAL de `admin.py` y una
`get_db` falsa — mismo patrón que `test_configuracion_validacion.py`):

  * 200 con `codigo` + `activo` cuando el alumno (ajeno al admin) tiene código.
  * 200 con `codigo: null` / `activo: false` cuando el alumno NO tiene fila en
    `codigos_referido` (sin 404/500: es un estado normal del dato, no un error).
  * 404 cuando el `usuario_id` no es de un alumno del box del token.

    cd backend && py -3.12 -m pytest tests/test_admin_codigo_referido.py -q --noconftest
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1.admin import router  # noqa: E402
from app.core.dependencies import get_current_admin, get_db  # noqa: E402
from app.models.referidos import CodigoReferido  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402

TENANT = 1
ADMIN_ID = 7
ALUMNO_ID = 123
AHORA = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


class _FilaAlumno:
    """Lo mínimo que la ficha necesita: el alumno existe en el box del token."""

    def __init__(self, usuario_id=ALUMNO_ID, tenant_id=TENANT):
        self.id = usuario_id
        self.tenant_id = tenant_id


class _FilaCodigo:
    """La fila de `codigos_referido` que devolvería `_codigo_propio`."""

    def __init__(self, codigo="JPERE234", activo=True, fecha_creacion=AHORA):
        self.codigo = codigo
        self.activo = activo
        self.fecha_creacion = fecha_creacion


class _Consulta:
    def __init__(self, fila):
        self._fila = fila

    def filter(self, *criterios):
        return self

    def first(self):
        return self._fila


class _SesionFalsa:
    """Session mínima: `query(Usuario)` y `query(CodigoReferido)` devuelven lo que
    el test configuró, sin abrir ninguna BD."""

    def __init__(self, alumno=None, codigo=None):
        self._alumno = alumno
        self._codigo = codigo

    def query(self, modelo):
        if modelo is Usuario:
            return _Consulta(self._alumno)
        if modelo is CodigoReferido:
            return _Consulta(self._codigo)
        return _Consulta(None)

    def add(self, obj):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


async def _admin_falso():
    return {
        "usuario_id": ADMIN_ID,
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
    app.include_router(router, prefix="/api/v1/admin")
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[get_current_admin] = _admin_falso
    return TestClient(app)


def _ruta(alumno_id=ALUMNO_ID):
    return f"/api/v1/admin/alumnos/{alumno_id}/codigo-referido"


def test_admin_ve_codigo_de_alumno_ajeno():
    sesion = _SesionFalsa(alumno=_FilaAlumno(), codigo=_FilaCodigo())
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["codigo"] == "JPERE234"
    assert body["activo"] is True
    assert "fecha_creacion" in body


def test_alumno_sin_codigo_responde_200_con_null():
    sesion = _SesionFalsa(alumno=_FilaAlumno(), codigo=None)
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 200, r.text
    assert r.json() == {
        "codigo": None,
        "activo": False,
        "fecha_creacion": None,
    }


def test_alumno_de_otro_box_responde_404():
    sesion = _SesionFalsa(alumno=None, codigo=_FilaCodigo())
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 404, r.text
