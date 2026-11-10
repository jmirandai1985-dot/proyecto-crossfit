"""Invitaciones externas del coach (Parte H): endpoint nuevo + rate limit.

El botón "✉️ Invitar" del Dashboard Coach dejó de navegar al panel de alumnos-en-prueba y ahora
abre un formulario (nombre + correo libre) que manda una invitación genérica con link a `/landing`
(`POST /api/v1/coach/invitaciones-externas`, `coach_id` del token).

QUÉ SE FIJA ACÁ (contra TEST, modo prueba obligatorio):
  A. Envío exitoso: 200 con `exito:true`, `estado=simulado` (EMAIL_MODO=noop) y `ya_es_alumno`
     booleano (no bloquea el envío, sólo avisa si el correo ya existe).
  B. Rate limit: el endpoint usa `@limiter.limit(LIMIT_REGISTRO)` (5/hour); el 6º request del
     mismo cliente devuelve 429.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_invitaciones_externas.py -q
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import settings, is_test_db_url                    # noqa: E402
from app.core.rate_limit import limiter                                 # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.services import email_service                                  # noqa: E402

TENANT_ID = 1
BASE = "/api/v1/coach/invitaciones-externas"


@pytest.fixture(scope="module")
def db():
    from app.db.database import SessionLocal
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST (define ENVIRONMENT=test)")
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def cliente():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def coach_token(db):
    fila = db.execute(text(
        "SELECT id FROM usuarios WHERE tenant_id = :t AND rol = 'coach' "
        "AND estado = 'activo' ORDER BY id LIMIT 1"), {"t": TENANT_ID}).first()
    if fila is None:
        pytest.skip("TEST no tiene un coach activo")
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": int(fila[0]), "tenant_id": TENANT_ID, "rol": "coach",
        "correo": "coach@test.com"})}


def test_a_envio_exitoso(cliente, coach_token, monkeypatch):
    """200 con `exito:true` y `estado=simulado` en modo prueba (no manda de verdad)."""
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)

    r = cliente.post(BASE, json={"nombre": "Ana", "correo": "ana@example.com"},
                     headers=coach_token)

    assert r.status_code == 200, r.text
    d = r.json()
    assert d["exito"] is True
    assert d["estado"] == email_service.ESTADO_SIMULADO
    assert isinstance(d["ya_es_alumno"], bool)
    assert d["detalle_error"] is None


def test_b_rate_limit(cliente, coach_token, monkeypatch):
    """`@limiter.limit(LIMIT_REGISTRO)` (5/hour): el 6º request dispara 429."""
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)
    limiter.reset()
    try:
        codigos = [
            cliente.post(BASE,
                         json={"nombre": "Ana", "correo": f"ana{i}@example.com"},
                         headers=coach_token).status_code
            for i in range(6)
        ]
        assert codigos[:5] == [200] * 5, codigos
        assert codigos[5] == 429, codigos
    finally:
        limiter.reset()
