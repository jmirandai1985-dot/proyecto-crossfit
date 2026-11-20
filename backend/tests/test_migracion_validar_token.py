"""Validación pública del token de activación (`GET .../validar-token`) — AISLADO.

SIN BD ni red: app mínima con el router REAL, `get_db` falsa y filas construidas
con los modelos reales. Cubre:
  * token vigente y sin usar -> `{nombre, correo}` del candidato;
  * token usado, vencido, inexistente o huérfano -> el MISMO 404 genérico (no se
    revela si el token existió);
  * el endpoint es PÚBLICO: no pide `get_current_admin`.

    cd backend && py -3.12 -m pytest tests/test_migracion_validar_token.py -q --noconftest
"""
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import migracion_boxmagic  # noqa: E402
from app.core.dependencies import get_db  # noqa: E402
from app.models.candidato_boxmagic import CandidatoBoxmagic  # noqa: E402
from app.models.token_migracion_boxmagic import TokenMigracionBoxmagic  # noqa: E402

TENANT = 1
TOKEN = "token-de-prueba-123"
RUTA = "/api/v1/migracion-boxmagic/activacion/validar-token"

AHORA = datetime.now(timezone.utc)
DETALLE_GENERICO = "El link de activación es inválido o expiró."


class _Consulta:
    def __init__(self, filas=None):
        self._filas = list(filas or [])

    def filter(self, *criterios):
        return self

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFalsa:
    def __init__(self, tokens=None, candidatos=None):
        self._tokens = tokens or []
        self._candidatos = candidatos or []

    def query(self, modelo):
        if modelo is TokenMigracionBoxmagic:
            return _Consulta(self._tokens)
        if modelo is CandidatoBoxmagic:
            return _Consulta(self._candidatos)
        return _Consulta([])


def _cliente(sesion):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(migracion_boxmagic.router,
                       prefix="/api/v1/migracion-boxmagic")
    app.dependency_overrides[get_db] = lambda: sesion
    return TestClient(app)


def _hash(token=TOKEN):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _fila_token(*, usado=None, vence=None):
    return TokenMigracionBoxmagic(
        id=1, candidato_id=101, token_hash=_hash(),
        expires_at=vence or (AHORA + timedelta(days=7)), used_at=usado,
    )


def _candidato(id_=101):
    return CandidatoBoxmagic(
        id=id_, tenant_id=TENANT, nombre="Ana Soto",
        correo="ana@test.com", estado_boxmagic="Activo",
        grupo="activacion",
    )


def test_token_vigente_devuelve_nombre_y_correo():
    cliente = _cliente(_SesionFalsa(tokens=[_fila_token()],
                                    candidatos=[_candidato()]))

    r = cliente.get(RUTA, params={"token": TOKEN})

    assert r.status_code == 200, r.text
    assert r.json() == {"nombre": "Ana Soto", "correo": "ana@test.com"}


def test_token_usado_404_generico():
    cliente = _cliente(_SesionFalsa(
        tokens=[_fila_token(usado=AHORA - timedelta(minutes=5))],
        candidatos=[_candidato()]))

    r = cliente.get(RUTA, params={"token": TOKEN})

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == DETALLE_GENERICO


def test_token_vencido_404_generico():
    cliente = _cliente(_SesionFalsa(
        tokens=[_fila_token(vence=AHORA - timedelta(seconds=1))],
        candidatos=[_candidato()]))

    r = cliente.get(RUTA, params={"token": TOKEN})

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == DETALLE_GENERICO


def test_token_inexistente_404_generico():
    cliente = _cliente(_SesionFalsa(tokens=[], candidatos=[_candidato()]))

    r = cliente.get(RUTA, params={"token": TOKEN})

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == DETALLE_GENERICO


def test_token_huerfano_404_generico():
    """Token válido sin candidato (padrón borrado): mismo error, sin filtrar."""
    cliente = _cliente(_SesionFalsa(tokens=[_fila_token()], candidatos=[]))

    r = cliente.get(RUTA, params={"token": TOKEN})

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == DETALLE_GENERICO


def test_los_cuatro_fallos_son_indistinguibles():
    """No se puede deducir si el token existió: misma respuesta en los 4 casos."""
    respuestas = []
    casos = [
        [],
        [_fila_token(usado=AHORA)],
        [_fila_token(vence=AHORA - timedelta(days=1))],
    ]
    for tokens in casos:
        r = _cliente(_SesionFalsa(tokens=tokens,
                                  candidatos=[_candidato()])).get(
            RUTA, params={"token": TOKEN})
        respuestas.append((r.status_code, r.json()["detail"]))
    # + el huérfano
    r = _cliente(_SesionFalsa(tokens=[_fila_token()], candidatos=[])).get(
        RUTA, params={"token": TOKEN})
    respuestas.append((r.status_code, r.json()["detail"]))

    assert len(set(respuestas)) == 1
