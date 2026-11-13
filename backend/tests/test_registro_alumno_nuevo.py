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
        # Consentimientos del alta: el endpoint los exige desde que se agregaron
        # (`RegistroAlumnoNuevo`), y sin ellos TODO el archivo daba 422.
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


# ── Recuperación (migración BoxMagic): el alta aplica la oferta enviada ──────
# `promociones_recuperacion` guardaba la promesa del correo ("4 clases gratis hasta el
# 31/12") pero el regalo no existía en el sistema: el alumno volvía y no había nada que
# usar. Ahora el alta liga la oferta a la cuenta nueva, crea el `Beneficio` real y marca
# la oferta como `recuperado`.

@pytest.fixture
def oferta_de_recuperacion(db):
    """Candidato del padrón + oferta `enviada` (4 clases) para un correo SIN cuenta.

    4 es a propósito: la lista fija vieja del Beneficio (1/2/3/5) lo rechazaba.
    """
    correo = f"reg.promo.{_sufijo()}@registro-test.com"
    candidato_id = db.execute(text(
        "INSERT INTO candidatos_boxmagic "
        "(tenant_id, nombre, correo, estado_boxmagic, grupo) "
        "VALUES (:t, :n, :c, 'Inactivo', 'recuperacion') RETURNING id"),
        {"t": TENANT_ID, "n": "Desertor de prueba", "c": correo}).scalar()
    promo_id = db.execute(text(
        "INSERT INTO promociones_recuperacion "
        "(tenant_id, candidato_id, tipo_beneficio, cantidad, vence_en, estado) "
        "VALUES (:t, :c, 'dias_gratis', 4, now() + interval '10 days', 'enviada') "
        "RETURNING id"), {"t": TENANT_ID, "c": candidato_id}).scalar()
    db.commit()

    yield {"correo": correo, "candidato_id": int(candidato_id),
           "promocion_id": int(promo_id)}

    # La oferta y el padrón se van con el candidato; el Beneficio y el usuario los borra
    # el fixture `escenario` (beneficios.alumno_id es ON DELETE CASCADE).
    db.rollback()
    db.execute(text("DELETE FROM promociones_recuperacion WHERE candidato_id = :c"),
               {"c": candidato_id})
    db.execute(text("DELETE FROM candidatos_boxmagic WHERE id = :c"),
               {"c": candidato_id})
    db.commit()


def test_registro_aplica_la_oferta_de_recuperacion(cliente, db, escenario,
                                                    oferta_de_recuperacion):
    """El alta hace REAL el regalo que el correo de recuperación había prometido.

    Es la MISMA puerta a la que apunta el CTA de ese correo: `/landing` envía este POST
    (`/alumnos/registro/alumno-nuevo`). No importa por dónde entró el alumno —la oferta se
    engancha por el CORREO, no por la pantalla—; por eso el botón puede llevarlo directo
    al formulario de alumno nuevo en vez de a `/login`, donde no tiene cuenta todavía.
    """
    correo = oferta_de_recuperacion["correo"]
    escenario.append(correo)

    respuesta = cliente.post(BASE_REGISTRO, json=_payload(correo))

    assert respuesta.status_code == 201, respuesta.text
    usuario_id = db.execute(text(
        "SELECT id FROM usuarios WHERE correo = :c AND tenant_id = :t"),
        {"c": correo, "t": TENANT_ID}).scalar()
    assert usuario_id is not None, "el alta no creó el usuario"

    promo = db.execute(text(
        "SELECT usuario_id, estado FROM promociones_recuperacion WHERE id = :p"),
        {"p": oferta_de_recuperacion["promocion_id"]}).first()
    assert promo.usuario_id == usuario_id, \
        "la oferta quedó ligada a la cuenta nueva (usuario_id)"
    assert promo.estado == "recuperado", \
        "el panel de Recuperación no la sigue mostrando como 'enviada'"

    beneficio = db.execute(text(
        "SELECT tipo::text AS tipo, valor FROM beneficios WHERE alumno_id = :u"),
        {"u": usuario_id}).first()
    assert beneficio is not None, "el alta no creó el Beneficio real"
    assert beneficio.tipo == "clases_gratis"
    assert beneficio.valor == 4


def test_registro_sin_oferta_no_crea_ningun_beneficio(cliente, db, escenario):
    """El caso normal (correo que no está en el padrón) sigue sin regalar nada."""
    correo = f"reg.promo.no.{_sufijo()}@registro-test.com"
    escenario.append(correo)

    respuesta = cliente.post(BASE_REGISTRO, json=_payload(correo))

    assert respuesta.status_code == 201, respuesta.text
    usuario_id = db.execute(text(
        "SELECT id FROM usuarios WHERE correo = :c AND tenant_id = :t"),
        {"c": correo, "t": TENANT_ID}).scalar()
    beneficio = db.execute(text(
        "SELECT id FROM beneficios WHERE alumno_id = :u"), {"u": usuario_id}).first()
    assert beneficio is None
