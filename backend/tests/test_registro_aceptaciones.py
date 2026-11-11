"""Aceptaciones del alta pública (`POST /api/v1/alumnos/registro/alumno-nuevo`).

Cubre los consentimientos obligatorios que se introducen junto con la
declaración de salud:

  * 400 si `acepta_tyc=False` o `acepta_salud=False` (validación ANTES de
    construir el `Usuario`, así que no se escribe nada);
  * 201 con ambos en True y PERSISTE fecha + versión de cada aceptación
    (`acepta_tyc_en` / `acepta_tyc_version` / `acepta_salud_en` /
    `acepta_salud_version`), ligados al usuario (dato sensible: por eso este
    test es de INTEGRACIÓN contra la app real vía TestClient + DB TEST);
  * 422 si falta `acepta_tyc` o `acepta_salud` (validación del body).

Reglas de test del proyecto: se escribe y se BORRA en TEST (nunca PROD). El
escenario se crea solo. `EMAIL_MODO=noop` no manda correo real.

El auto-registro tiene rate limit de 5/hour por IP (`testclient`). Este archivo
hace 3 llamadas que llegan al rate limiter (los dos 400 y el 201 exitoso); las
dos de 422 fallan ANTES del decorador `@limiter.limit`, así que no suman.

    cd backend && py -3.12 -m pytest tests/test_registro_aceptaciones.py -q
"""
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                                    # noqa: E402

TENANT_ID = 1
BASE_REGISTRO = "/api/v1/alumnos/registro/alumno-nuevo"


# ── Infraestructura de test (mismo patrón que test_registro_alumno_nuevo) ───

@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


# ── Datos únicos y limpieza ──────────────────────────────────────────────────

def _sufijo() -> str:
    import datetime as _dt
    return f"{_dt.datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"


def _rut_valido() -> str:
    """RUT chileno válido y único (módulo 11), sin depender de datos de TEST."""
    cuerpo = str(10_000_000 + uuid.uuid4().int % 90_000_000)
    suma, multiplo = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1
    resto = 11 - suma % 11
    dv = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    return f"{cuerpo}-{dv}"


def _borrar_usuario(db, usuario_id: int) -> None:
    """Borra lo que crea un alta, en orden de dependencias (FKs NO ACTION)."""
    for tabla, columna in (("notificaciones", "alumno_id"),
                           ("notificaciones_enviadas", "alumno_id"),
                           ("codigos_referido", "usuario_id"),
                           ("suscripciones", "usuario_id")):
        db.execute(text(f"DELETE FROM {tabla} WHERE {columna} = :u"),
                   {"u": usuario_id})
    db.execute(text("DELETE FROM auditoria WHERE entidad = 'usuario' "
                    "AND entidad_id = :u"), {"u": usuario_id})
    db.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": usuario_id})


@pytest.fixture
def escenario(db):
    """Lista de correos del test; al final borra TODO lo que el alta creó."""
    correos = []
    yield correos

    db.rollback()
    try:
        for correo in correos:
            fila = db.execute(text(
                "SELECT id FROM usuarios WHERE correo = :c AND tenant_id = :t"),
                {"c": correo, "t": TENANT_ID}).first()
            if fila is not None:
                _borrar_usuario(db, int(fila.id))
            db.execute(text("DELETE FROM notificaciones WHERE mensaje LIKE :p"),
                       {"p": f"%{correo}%"})
            db.execute(text("DELETE FROM notificaciones_enviadas "
                            "WHERE destinatario_correo = :c"), {"c": correo})
        db.commit()
    except Exception as error:      # la limpieza no debe tapar el fallo real
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de registro: {error}")


# ── Helpers de escenario ─────────────────────────────────────────────────────

def _payload(correo: str, **extra) -> dict:
    base = {
        "nombre": "Alumno de prueba (aceptaciones)",
        "correo": correo,
        "rut": _rut_valido(),
        "tenant_id": TENANT_ID,
        "sexo": "F",
        "peso": 62.5,
        "telefono": "+56 9 1234 5678",
        "fecha_nacimiento": "1995-06-15",
        "acepta_tyc": True,
        "acepta_salud": True,
    }
    base.update(extra)
    return base


def _sin(payload: dict, *campos: str) -> dict:
    """Copia del payload sin los campos indicados (para probar los 422)."""
    copia = dict(payload)
    for campo in campos:
        copia.pop(campo, None)
    return copia


# ── 400: consentimientos rechazados ──────────────────────────────────────────

def test_400_si_no_acepta_tyc(cliente):
    correo = f"reg.notyc.{_sufijo()}@registro-test.com"
    respuesta = cliente.post(BASE_REGISTRO,
                             json=_payload(correo, acepta_tyc=False))
    assert respuesta.status_code == 400, respuesta.text
    assert "Términos y Condiciones" in respuesta.text


def test_400_si_no_acepta_salud(cliente):
    correo = f"reg.nosalud.{_sufijo()}@registro-test.com"
    respuesta = cliente.post(BASE_REGISTRO,
                             json=_payload(correo, acepta_salud=False))
    assert respuesta.status_code == 400, respuesta.text
    assert "declaración de salud" in respuesta.text


# ── 201: persiste fecha + versión de cada aceptación ────────────────────────

def test_registro_guarda_aceptaciones(cliente, db, escenario):
    correo = f"reg.ok-accept.{_sufijo()}@registro-test.com"
    escenario.append(correo)

    respuesta = cliente.post(BASE_REGISTRO, json=_payload(correo))

    assert respuesta.status_code == 201, respuesta.text
    fila = db.execute(text(
        "SELECT acepta_tyc_en, acepta_tyc_version, "
        "       acepta_salud_en, acepta_salud_version "
        "FROM usuarios WHERE correo = :c AND tenant_id = :t"),
        {"c": correo, "t": TENANT_ID}).first()
    assert fila is not None, "el alta no creó el usuario"
    assert fila.acepta_tyc_en is not None
    assert fila.acepta_tyc_version == "v1"
    assert fila.acepta_salud_en is not None
    assert fila.acepta_salud_version == "v1"


# ── 422: campos obligatorios ─────────────────────────────────────────────────

def test_422_si_falta_acepta_tyc(cliente):
    correo = f"reg.falta-tyc.{_sufijo()}@registro-test.com"
    respuesta = cliente.post(BASE_REGISTRO,
                             json=_sin(_payload(correo), "acepta_tyc"))
    assert respuesta.status_code == 422, respuesta.text
    assert "acepta_tyc" in respuesta.text


def test_422_si_falta_acepta_salud(cliente):
    correo = f"reg.falta-salud.{_sufijo()}@registro-test.com"
    respuesta = cliente.post(BASE_REGISTRO,
                             json=_sin(_payload(correo), "acepta_salud"))
    assert respuesta.status_code == 422, respuesta.text
    assert "acepta_salud" in respuesta.text
