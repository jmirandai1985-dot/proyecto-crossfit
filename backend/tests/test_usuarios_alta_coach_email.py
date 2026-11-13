"""Alta de COACH desde el panel: el correo de credenciales es best-effort.

Contexto: `crear_usuario` ya forzaba `cambiar_password_al_login=True` para
CUALQUIER rol, pero sólo los alumnos recibían el correo con su contraseña
provisional (el admin tenía que pasársela al coach a mano). Ahora el coach
también la recibe, reusando `enviar_email_activacion_alumno` (su texto es
genérico: "tu cuenta en Urban Training Box fue activada", sin mencionar alumno
ni plan).

Lo que fija este archivo (por HTTP, TestClient de la app real, BD TEST):
  1. Al crear un coach se INTENTA el envío con sus datos reales (id/nombre/
     correo) y la contraseña que escribió el admin.
  2. Si el envío LANZA una excepción, el alta NO falla: responde 201 y el
     usuario queda creado en la BD (mismo patrón best-effort que el correo del
     alumno: el correo nunca revierte la creación).
  3. El coach nace con `cambiar_password_al_login=True` (entra una vez con la
     provisoria y el sistema le exige cambiarla).

Correr (aislado, contra TEST):
    cd backend && py -3.12 -m pytest tests/test_usuarios_alta_coach_email.py -q --noconftest
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                   # noqa: E402
from app.core.security import create_access_token     # noqa: E402

API = "/api/v1/usuarios/"
CLAVE = "Provisoria123"


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
    """TestClient del app real (sin levantar servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def box(db):
    """Box temporal: tenant + admin activo (el alta exige rol administrador)."""
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"
    alta = datetime.now(timezone.utc)
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Alta Coach TEST {sufijo}", "s": f"box-alta-coach-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        admin = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Admin Alta Coach TEST', :c, 'x', 'administrador',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": f"66{sufijo[-6:]}-6",
             "c": f"alta.coach.admin.{sufijo}@test.local", "alta": alta}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        raise

    token = "Bearer " + create_access_token({
        "usuario_id": admin, "tenant_id": tenant, "rol": "administrador",
        "correo": "alta.coach@test.local"})
    datos = {"db": db, "tenant_id": tenant, "admin_id": admin,
             "admin": {"Authorization": token}}
    try:
        yield datos
    finally:
        db.rollback()
        for tabla in ("auditoria", "usuarios"):
            try:
                with db.begin_nested():
                    db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"),
                               {"t": tenant})
            except Exception:
                print(f"\n[WARN] no se pudo limpiar {tabla} del box {tenant}")
        try:
            with db.begin_nested():
                db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
        except Exception:
            print(f"\n[WARN] no se pudo borrar el box {tenant}")
        db.commit()


def _datos_coach(box):
    """Payload único (RUT/correo) para no chocar con altas anteriores."""
    sufijo = uuid.uuid4().hex[:10]
    nombre = f"Coach Alta TEST {sufijo}"
    correo = f"coach.{sufijo}@example.com"
    payload = {
        "tenant_id": box["tenant_id"],
        "rut": f"8{sufijo[:7]}-{sufijo[-1]}",
        "nombre": nombre,
        "correo": correo,
        "password": CLAVE,
        "rol": "coach",
    }
    return payload, nombre, correo


def _en_bd(db, usuario_id):
    """Fila COMMITEADA del usuario (rollback para no leer caché de la sesión)."""
    db.rollback()
    fila = db.execute(text("""
        SELECT rol::text AS rol, estado, activo, cambiar_password_al_login
        FROM usuarios WHERE id = :i
    """), {"i": usuario_id}).first()
    return dict(fila._mapping) if fila else None


# ── 1. El alta del coach SÍ intenta enviarle sus credenciales ────────────────
def test_el_alta_de_coach_intenta_enviar_sus_credenciales(cliente, box,
                                                          monkeypatch):
    llamadas = []

    def _fake(coach, password):
        llamadas.append((coach, password))
        return True

    monkeypatch.setattr(
        "app.services.email_service.enviar_email_activacion_alumno", _fake)

    payload, nombre, correo = _datos_coach(box)
    r = cliente.post(API, headers=box["admin"], json=payload)

    assert r.status_code == 201, r.text
    creado = r.json()

    assert len(llamadas) == 1, "el coach tiene que recibir sus credenciales"
    destino, password = llamadas[0]
    assert destino == {"id": creado["id"], "nombre": nombre, "correo": correo}
    assert password == CLAVE

    fila = _en_bd(box["db"], creado["id"])
    assert fila["rol"] == "coach"
    assert fila["estado"] == "activo"
    assert fila["cambiar_password_al_login"] is True, (
        "el primer login del coach tiene que exigir cambio de contraseña")


# ── 2. Si el correo falla, el coach se crea IGUAL (best-effort) ─────────────
def test_si_el_correo_falla_el_coach_se_crea_igual(cliente, box, monkeypatch):
    def _explota(coach, password):
        raise RuntimeError("SMTP caído a propósito")

    monkeypatch.setattr(
        "app.services.email_service.enviar_email_activacion_alumno", _explota)

    payload, _nombre, correo = _datos_coach(box)
    r = cliente.post(API, headers=box["admin"], json=payload)

    # El envío NO puede tumbar el alta: mismo 201 que sin fallo de correo.
    assert r.status_code == 201, r.text
    creado = r.json()
    assert creado["correo"] == correo
    assert creado["rol"] == "coach"

    fila = _en_bd(box["db"], creado["id"])
    assert fila is not None, "el coach quedó creado aunque el correo falló"
    assert fila["rol"] == "coach"
    assert fila["estado"] == "activo"
    assert fila["cambiar_password_al_login"] is True
