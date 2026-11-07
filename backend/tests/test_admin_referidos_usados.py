"""Endpoint admin `GET /api/v1/admin/alumnos/{usuario_id}/referidos-usados` — AISLADO.

Cubre, SIN BD y SIN red (app mínima con el router REAL de `admin.py` y una
`get_db` falsa — mismo patrón que `test_admin_codigo_referido.py`):

  * 200 con la lista de quién usó el código (invitado: nombre/correo + fechas/estado).
  * 200 con lista vacía cuando el alumno no tiene referidos aplicados.
  * 404 cuando el `usuario_id` no es de un alumno del box del token.

    cd backend && py -3.12 -m pytest tests/test_admin_referidos_usados.py -q --noconftest
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
from app.models.referidos import ReferidoAplicado  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402

TENANT = 1
ADMIN_ID = 7
ALUMNO_ID = 123
AHORA = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


class _FilaAlumno:
    """Lo mínimo que el guard necesita: el alumno existe en el box del token."""

    def __init__(self, usuario_id=ALUMNO_ID, tenant_id=TENANT):
        self.id = usuario_id
        self.tenant_id = tenant_id


class _Estado:
    def __init__(self, value):
        self.value = value


class _FilaReferido:
    """La fila de `referidos_aplicados` + el invitado (nombre/correo)."""

    def __init__(self, invitado_id=555, fecha_ingreso=AHORA, estado="pendiente",
                 fecha_conversion=None):
        self.id = 1
        self.usuario_invitado_id = invitado_id
        self.fecha_ingreso_codigo = fecha_ingreso
        self.estado = _Estado(estado)
        self.fecha_conversion = fecha_conversion


class _FilaInvitado:
    def __init__(self, nombre="Invitado", correo="invitado@test.com"):
        self.nombre = nombre
        self.correo = correo


class _Consulta:
    def __init__(self, fila=None, filas=None):
        self._fila = fila
        self._filas = filas

    def filter(self, *criterios):
        return self

    def first(self):
        return self._fila

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self._filas or []


class _SesionFalsa:
    """Session mínima: `query(Usuario)` valida al alumno y `query(ReferidoAplicado,
    Usuario)` devuelve la lista de referidos ya junta con su invitado."""

    def __init__(self, alumno=None, referidos=None):
        self._alumno = alumno
        self._referidos = referidos  # lista de tuplas (aplicado, invitado)

    def query(self, *modelos):
        if modelos and modelos[0] is Usuario and len(modelos) == 1:
            return _Consulta(fila=self._alumno)
        if modelos and modelos[0] is ReferidoAplicado:
            return _Consulta(filas=self._referidos)
        return _Consulta()

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
    return f"/api/v1/admin/alumnos/{alumno_id}/referidos-usados"


def test_admin_lista_quien_uso_el_codigo():
    invitado = _FilaInvitado()
    referido = _FilaReferido(
        invitado_id=555, fecha_ingreso=AHORA, estado="convertido",
        fecha_conversion=AHORA,
    )
    sesion = _SesionFalsa(alumno=_FilaAlumno(), referidos=[(referido, invitado)])
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["usuario_invitado_id"] == 555
    assert body[0]["nombre"] == "Invitado"
    assert body[0]["correo"] == "invitado@test.com"
    assert body[0]["estado"] == "convertido"
    assert body[0]["fecha_ingreso_codigo"] == AHORA.isoformat()
    assert body[0]["fecha_conversion"] == AHORA.isoformat()


def test_alumno_sin_referidos_responde_lista_vacia():
    sesion = _SesionFalsa(alumno=_FilaAlumno(), referidos=[])
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 200, r.text
    assert r.json() == []


def test_referido_pendiente_sin_fecha_conversion():
    invitado = _FilaInvitado(nombre="Pendiente", correo="p@test.com")
    referido = _FilaReferido(invitado_id=556, estado="pendiente")
    sesion = _SesionFalsa(alumno=_FilaAlumno(), referidos=[(referido, invitado)])
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 200, r.text
    assert r.json()[0]["estado"] == "pendiente"
    assert r.json()[0]["fecha_conversion"] is None


def test_alumno_de_otro_box_responde_404():
    sesion = _SesionFalsa(alumno=None, referidos=[])
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta())

    assert r.status_code == 404, r.text
