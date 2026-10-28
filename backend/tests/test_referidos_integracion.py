"""
Sistema de REFERIDOS (Fase 2) — integración contra la MISMA rama TEST.

Qué cubre, visto desde HTTP (la app real, sin levantar servidor):

  * AUTO-REGISTRO público (`POST /api/v1/alumnos/registro/alumno-nuevo`): el
    alumno creado recibe EXACTAMENTE una fila en `codigos_referido`, con el
    formato del servicio y el prefijo derivado del nombre completo (tildes, ñ y
    apellido compuesto incluidos).
  * ALTA DEL ADMIN (`POST /api/v1/usuarios/`): el alumno recibe código y el
    coach NO. La regla "sólo alumnos" se verifica en el camino real, no sólo en
    el servicio.
  * ATOMICIDAD: si la generación falla, el alta responde 500 y NO queda usuario,
    suscripción ni código (rollback de la transacción completa), en los DOS
    caminos de creación.

Reglas de test del proyecto: se escribe y se BORRA en TEST (nunca PROD); el
escenario se crea solo y no depende de datos previos, salvo un admin activo del
box 1 para firmar el token (si no existe, se salta). `EMAIL_MODO=noop` no manda
correo real. El auto-registro tiene rate limit de 5/hour: este archivo hace 2
llamadas (alta + rollback).

    cd backend && py -3.12 -m pytest tests/test_referidos_integracion.py -q
"""
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                                    # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.services.referidos_service import PATRON_CODIGO                # noqa: E402

TENANT_ID = 1
BASE_USUARIOS = "/api/v1/usuarios"
BASE_REGISTRO = "/api/v1/alumnos/registro/alumno-nuevo"


# ── Infraestructura de test (mismo patrón que test_beneficios_api) ───────────

@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def admin_headers(db):
    """Token REAL de un admin activo del box 1 (mismo camino que el navegador)."""
    fila = db.execute(text(
        "SELECT id, correo FROM usuarios WHERE tenant_id = :t "
        "AND rol = 'administrador' AND estado = 'activo' ORDER BY id LIMIT 1"),
        {"t": TENANT_ID}).first()
    if fila is None:
        pytest.skip("TEST no tiene un administrador activo en el box 1")
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": int(fila.id), "tenant_id": TENANT_ID,
        "rol": "administrador", "correo": fila.correo})}


# ── Datos únicos y limpieza ──────────────────────────────────────────────────

def _sufijo() -> str:
    return f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"


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
    """Lista de correos del test; al final borra TODO lo que el alta creó.

    Se limpia por correo (no por "id devuelto") a propósito: si el test de
    atomicidad falla y el usuario SÍ quedó creado, igual se borra.
    """
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
            # Avisos in-app del alta (el mensaje incluye el correo) y correos.
            db.execute(text("DELETE FROM notificaciones WHERE mensaje LIKE :p"),
                       {"p": f"%{correo}%"})
            db.execute(text("DELETE FROM notificaciones_enviadas "
                            "WHERE destinatario_correo = :c"), {"c": correo})
        db.commit()
    except Exception as error:      # la limpieza no debe tapar el fallo real
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de referidos: {error}")


# ── Helpers de escenario ─────────────────────────────────────────────────────

def _codigos_de(db, correo: str):
    """Filas de `codigos_referido` del usuario con ese correo, en orden de id."""
    db.rollback()
    return db.execute(text("""
        SELECT cr.codigo, cr.activo
        FROM codigos_referido cr
        JOIN usuarios u ON u.id = cr.usuario_id
        WHERE u.correo = :c AND u.tenant_id = :t
        ORDER BY cr.id
    """), {"c": correo, "t": TENANT_ID}).all()


def _payload_registro(correo: str) -> dict:
    return {
        "nombre": "Ana María Ñuñez de la Fuente",
        "correo": correo,
        "rut": _rut_valido(),
        "tenant_id": TENANT_ID,
        # D2: el alta exige peso y género (validación real en el endpoint).
        "sexo": "F",
        "peso": 60,
    }


def _payload_usuario(correo: str, nombre: str, rol: str) -> dict:
    return {
        "rut": _rut_valido(),
        "nombre": nombre,
        "correo": correo,
        "rol": rol,
        "tenant_id": TENANT_ID,
        "password": "Temporal123",
        "estado": "activo",
    }


def _fallar_generacion(db, usuario):
    raise RuntimeError("fallo simulado de generación")


# ── Camino feliz: auto-registro ──────────────────────────────────────────────

def test_auto_registro_asigna_un_codigo_valido_y_unico(cliente, db, escenario):
    correo = f"ref.auto.{_sufijo()}@referidos-test.com"
    escenario.append(correo)

    respuesta = cliente.post(BASE_REGISTRO, json=_payload_registro(correo))

    assert respuesta.status_code == 201, respuesta.text
    assert db.execute(text(
        "SELECT rol FROM usuarios WHERE correo = :c AND tenant_id = :t"),
        {"c": correo, "t": TENANT_ID}).scalar() == "alumno"

    filas = _codigos_de(db, correo)
    assert len(filas) == 1, "el alumno debe tener EXACTAMENTE un código"
    assert filas[0].activo is True
    codigo = filas[0].codigo
    assert PATRON_CODIGO.match(codigo), codigo
    assert codigo.startswith("AMARIA"), (
        f"el prefijo sale del nombre completo normalizado (Ana + María): {codigo}")
    assert db.execute(text(
        "SELECT count(*) FROM codigos_referido WHERE codigo = :c"),
        {"c": codigo}).scalar() == 1, "el código es único en toda la tabla"
    print(f"\n[CODIGO] auto-registro {correo} -> {codigo}")


# ── Camino feliz: alta del admin (alumno sí, coach no) ───────────────────────

def test_el_alta_del_admin_asigna_al_alumno_y_no_al_coach(
        cliente, db, admin_headers, escenario):
    sufijo = _sufijo()
    correo_alumno = f"ref.admin.alumno.{sufijo}@referidos-test.com"
    correo_coach = f"ref.admin.coach.{sufijo}@referidos-test.com"
    escenario.extend([correo_alumno, correo_coach])

    alta_alumno = cliente.post(
        BASE_USUARIOS + "/",
        json=_payload_usuario(correo_alumno, "Juan Pérez Soto", "alumno"),
        headers=admin_headers)
    assert alta_alumno.status_code == 201, alta_alumno.text

    alta_coach = cliente.post(
        BASE_USUARIOS + "/",
        json=_payload_usuario(correo_coach, "Carla Rojas", "coach"),
        headers=admin_headers)
    assert alta_coach.status_code == 201, alta_coach.text

    filas_alumno = _codigos_de(db, correo_alumno)
    assert len(filas_alumno) == 1
    assert filas_alumno[0].activo is True
    codigo = filas_alumno[0].codigo
    assert PATRON_CODIGO.match(codigo), codigo
    assert codigo.startswith("JPEREZ"), codigo

    assert _codigos_de(db, correo_coach) == [], \
        "un coach NO es alumno: no debe recibir código de referido"
    print(f"\n[CODIGO] alta admin {correo_alumno} -> {codigo}")


# ── Atomicidad: si la generación falla, el alta entera se revierte ───────────

def test_si_falla_la_generacion_el_auto_registro_no_deja_nada(
        cliente, db, escenario, monkeypatch):
    correo = f"ref.auto.fallo.{_sufijo()}@referidos-test.com"
    escenario.append(correo)
    monkeypatch.setattr("app.api.v1.alumnos.asignar_codigo_referido",
                        _fallar_generacion)

    respuesta = cliente.post(BASE_REGISTRO, json=_payload_registro(correo))

    assert respuesta.status_code == 500, respuesta.text
    assert "código de referido" in respuesta.json()["detail"]
    assert db.execute(text(
        "SELECT id FROM usuarios WHERE correo = :c AND tenant_id = :t"),
        {"c": correo, "t": TENANT_ID}).first() is None, \
        "el alumno NO debe quedar creado si falló su código"
    assert _codigos_de(db, correo) == []


def test_si_falla_la_generacion_el_alta_admin_no_deja_nada(
        cliente, db, admin_headers, escenario, monkeypatch):
    correo = f"ref.admin.fallo.{_sufijo()}@referidos-test.com"
    escenario.append(correo)
    monkeypatch.setattr("app.api.v1.usuarios.asignar_codigo_referido",
                        _fallar_generacion)

    respuesta = cliente.post(
        BASE_USUARIOS + "/",
        json=_payload_usuario(correo, "Juan Pérez Soto", "alumno"),
        headers=admin_headers)

    assert respuesta.status_code == 500, respuesta.text
    assert "código de referido" in respuesta.json()["detail"]
    assert db.execute(text(
        "SELECT id FROM usuarios WHERE correo = :c AND tenant_id = :t"),
        {"c": correo, "t": TENANT_ID}).first() is None, \
        "el alta del admin debe revertirse completa si falla el código"
    assert _codigos_de(db, correo) == []
