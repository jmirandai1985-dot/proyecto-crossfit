"""Registro público de alumno (`POST /api/v1/alumnos/registro/alumno-nuevo`) — integración.

Qué cubre, visto desde HTTP (la app real, sin levantar servidor):

  * el alta exitosa PERSISTE `telefono` y `fecha_nacimiento` (antes hardcodeaba
    `telefono=None` y nadie escribía nunca `fecha_nacimiento`);
  * 422 si falta `telefono`;
  * 422 si falta `fecha_nacimiento`;
  * 422 si `fecha_nacimiento` es futura o da una edad fuera de rango (10–100).

Reglas de test del proyecto: se escribe y se BORRA en TEST (nunca PROD); el
escenario se crea solo y no depende de datos previos. `EMAIL_MODO=noop` no manda
correo real.

El auto-registro tiene rate limit de 5/hour por IP (`testclient`). Este archivo
hace UNA llamada que llega al rate limiter (la del alta exitosa); las de
validación fallan con 422 ANTES de ejecutar el endpoint (la validación del body
corre en el handler de FastAPI, previo al decorador `@limiter.limit`), así que
no suman al límite.

    cd backend && py -3.12 -m pytest tests/test_registro_alumno_nuevo.py -q
"""
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                                    # noqa: E402

TENANT_ID = 1
BASE_REGISTRO = "/api/v1/alumnos/registro/alumno-nuevo"


# ── Infraestructura de test (mismo patrón que test_referidos_integracion) ─────

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
        "nombre": "Alumno de prueba (registro)",
        "correo": correo,
        "rut": _rut_valido(),
        "tenant_id": TENANT_ID,
        "sexo": "F",
        "peso": 62.5,
        "telefono": "+56 9 1234 5678",
        "fecha_nacimiento": "1995-06-15",
    }
    base.update(extra)
    return base


def _sin(payload: dict, *campos: str) -> dict:
    """Copia del payload sin los campos indicados (para probar los 422)."""
    copia = dict(payload)
    for campo in campos:
        copia.pop(campo, None)
    return copia


# ── Camino feliz: persiste telefono y fecha_nacimiento ───────────────────────

def test_registro_exitoso_persiste_telefono_y_fecha_nacimiento(cliente, db, escenario):
    correo = f"reg.ok.{_sufijo()}@registro-test.com"
    escenario.append(correo)

    respuesta = cliente.post(BASE_REGISTRO, json=_payload(correo))

    assert respuesta.status_code == 201, respuesta.text
    fila = db.execute(text(
        "SELECT telefono, fecha_nacimiento FROM usuarios "
        "WHERE correo = :c AND tenant_id = :t"),
        {"c": correo, "t": TENANT_ID}).first()
    assert fila is not None, "el alta no creó el usuario"
    assert fila.telefono == "+56 9 1234 5678"
    assert fila.fecha_nacimiento == date(1995, 6, 15)


# ── 422: campos obligatorios ─────────────────────────────────────────────────

def test_422_si_falta_telefono(cliente):
    correo = f"reg.falta-tel.{_sufijo()}@registro-test.com"
    respuesta = cliente.post(BASE_REGISTRO, json=_sin(_payload(correo), "telefono"))
    assert respuesta.status_code == 422, respuesta.text
    assert "telefono" in respuesta.text


def test_422_si_falta_fecha_nacimiento(cliente):
    correo = f"reg.falta-fn.{_sufijo()}@registro-test.com"
    respuesta = cliente.post(BASE_REGISTRO,
                             json=_sin(_payload(correo), "fecha_nacimiento"))
    assert respuesta.status_code == 422, respuesta.text
    assert "fecha_nacimiento" in respuesta.text


# ── 422: fecha de nacimiento inválida ────────────────────────────────────────

def test_422_si_fecha_nacimiento_es_futura(cliente):
    correo = f"reg.futura.{_sufijo()}@registro-test.com"
    futura = date.today() + timedelta(days=1)
    respuesta = cliente.post(BASE_REGISTRO,
                             json=_payload(correo, fecha_nacimiento=str(futura)))
    assert respuesta.status_code == 422, respuesta.text


def test_422_si_fecha_nacimiento_da_edad_fuera_de_rango(cliente):
    muy_viejo = date.today() - timedelta(days=365 * 110)   # ~110 años
    correo = f"reg.viejo.{_sufijo()}@registro-test.com"
    respuesta = cliente.post(
        BASE_REGISTRO, json=_payload(correo, fecha_nacimiento=str(muy_viejo)))
    assert respuesta.status_code == 422, respuesta.text

    muy_joven = date.today() - timedelta(days=365 * 5)     # ~5 años
    correo = f"reg.joven.{_sufijo()}@registro-test.com"
    respuesta = cliente.post(
        BASE_REGISTRO, json=_payload(correo, fecha_nacimiento=str(muy_joven)))
    assert respuesta.status_code == 422, respuesta.text
