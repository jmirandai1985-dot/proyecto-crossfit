"""Promociones de recuperación para candidatos SIN cuenta real — integración TEST.

QUÉ CUBRE (con TestClient y la rama TEST de verdad, migración 080 aplicada)
---------------------------------------------------------------------------
1. ESQUEMA: `promociones_recuperacion.usuario_id` es NULLABLE y `candidato_id` existe,
   nullable, con FK a `candidatos_boxmagic` y el CHECK de "al menos un destinatario".
   Sin esto el bug vuelve: la base rechaza toda oferta sin cuenta.
2. PREVIEW: se puede ver el correo de un candidato del padrón que NO tiene `usuarios`,
   sin escribir nada (ni promoción ni notificación).
3. POST: crea la oferta colgada de `candidato_id`, con `usuario_id` NULL, y registra
   el envío simulado (`EMAIL_MODO=noop`) con el correo del padrón y sin `alumno_id`.
4. GET panel: ese candidato sale `promocion_enviada` aunque siga sin cuenta (`id` null).
5. PUT: marca `recuperado` la oferta vigente sin necesitar cuenta real.

Escribe SOLO filas propias (correo único con uuid) y las BORRA en el `finally` del
fixture, incluso si un test falla. Falla cerrado si la URL no es de TEST (nunca PROD).

    cd backend && $env:ENVIRONMENT='test'
    py -3.12 -m pytest tests/test_migracion_promociones_candidato_integracion.py -q --noconftest
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_test_db_url, settings                  # noqa: E402
from app.core.security import create_access_token                     # noqa: E402
from app.models.candidato_boxmagic import CandidatoBoxmagic           # noqa: E402
from app.models.notificacion_enviada import NotificacionEnviada       # noqa: E402
from app.models.promocion_recuperacion import (                       # noqa: E402
    ESTADO_PROMO_RECUPERADO, PromocionRecuperacion,
)
from app.services import email_service                                # noqa: E402

TENANT = 1
RUTA = "/api/v1/migracion-boxmagic/recuperacion"
VENCE = datetime.now(timezone.utc) + timedelta(days=10)


@pytest.fixture(scope="module", autouse=True)
def _sin_correo_real():
    """El correo NO sale a la red: se registra como simulado, igual que en run_tests."""
    parche = pytest.MonkeyPatch()
    parche.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)
    yield
    parche.undo()


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
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
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def admin_headers(db):
    """Token REAL de un admin activo del box 1 (mismo camino que el navegador)."""
    from sqlalchemy import text

    fila = db.execute(text(
        "SELECT id, correo, rol FROM usuarios WHERE tenant_id = :t "
        "AND rol = 'administrador' AND estado = 'activo' ORDER BY id LIMIT 1"
    ), {"t": TENANT}).first()
    if fila is None:
        pytest.skip("TEST no tiene un administrador activo en el box 1")
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": int(fila.id), "tenant_id": TENANT,
        "rol": fila.rol, "correo": fila.correo,
    })}


@pytest.fixture(scope="module")
def candidato(db):
    """Un candidato Inactivo del padrón SIN cuenta real, con correo único del test."""
    sufijo = uuid.uuid4().hex[:12]
    fila = CandidatoBoxmagic(
        tenant_id=TENANT,
        nombre=f"Desertor Integración {sufijo}",
        correo=f"promo.migracion.{sufijo}@test.local",
        estado_boxmagic="Inactivo",
        grupo="recuperacion",
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)

    yield fila

    # Limpieza: promociones del candidato, el correo simulado y la fila del padrón.
    db.rollback()
    db.query(PromocionRecuperacion).filter(
        PromocionRecuperacion.candidato_id == fila.id
    ).delete(synchronize_session=False)
    db.query(NotificacionEnviada).filter(
        NotificacionEnviada.destinatario_correo == fila.correo
    ).delete(synchronize_session=False)
    db.query(CandidatoBoxmagic).filter(
        CandidatoBoxmagic.id == fila.id
    ).delete(synchronize_session=False)
    db.commit()


def _cuerpo(vence=VENCE):
    return {
        "tipo_beneficio": "dias_gratis",
        "cantidad": 5,
        "vence_en": vence.isoformat(),
    }


def _params_preview():
    return {
        "tipo_beneficio": "dias_gratis",
        "cantidad": 5,
        "vence_en": VENCE.isoformat(),
    }


def test_esquema_acepta_oferta_sin_cuenta(db):
    """La base tiene que permitir `usuario_id NULL` + `candidato_id` (migración 080)."""
    from sqlalchemy import inspect

    insp = inspect(db.get_bind())
    columnas = {c["name"]: c for c in insp.get_columns("promociones_recuperacion")}
    assert columnas["usuario_id"]["nullable"] is True
    assert columnas["candidato_id"]["nullable"] is True

    fks = insp.get_foreign_keys("promociones_recuperacion")
    fk = next(f for f in fks if f["constrained_columns"] == ["candidato_id"])
    assert fk["referred_table"] == "candidatos_boxmagic"
    assert (fk.get("options") or {}).get("ondelete") == "CASCADE"

    checks = {c["name"] for c in insp.get_check_constraints("promociones_recuperacion")}
    assert "ck_promociones_recuperacion_destinatario" in checks


def test_flujo_completo_de_un_candidato_sin_cuenta(cliente, db, admin_headers, candidato):
    """Preview -> POST -> GET panel -> PUT, todo por `candidato_id` y sin cuenta."""
    # 1. PREVIEW: el correo se ve antes de confirmar y NO escribe nada.
    antes = db.query(PromocionRecuperacion).filter(
        PromocionRecuperacion.tenant_id == TENANT).count()

    r = cliente.get(f"{RUTA}/{candidato.id}/promocion/preview",
                    params=_params_preview(), headers=admin_headers)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert "5 días gratis de clases" in preview["asunto"]
    assert "5 días gratis de clases" in preview["html"]
    assert candidato.nombre.split()[0] in preview["asunto"]

    db.expire_all()
    assert db.query(PromocionRecuperacion).filter(
        PromocionRecuperacion.tenant_id == TENANT).count() == antes

    # 2. POST: la oferta queda guardada y el correo simulado registrado.
    r = cliente.post(f"{RUTA}/{candidato.id}/promocion",
                     json=_cuerpo(), headers=admin_headers)
    assert r.status_code == 201, r.text
    creada = r.json()
    assert creada["candidato_id"] == candidato.id
    assert creada["usuario_id"] is None
    assert creada["estado"] == "enviada"
    assert creada["correo_enviado"] is True
    assert creada["notificacion_id"]

    db.expire_all()
    promo = (db.query(PromocionRecuperacion)
             .filter(PromocionRecuperacion.candidato_id == candidato.id)
             .order_by(PromocionRecuperacion.id.desc()).first())
    assert promo is not None
    assert promo.tenant_id == TENANT
    assert promo.usuario_id is None
    assert promo.notificacion_id == creada["notificacion_id"]

    notif = (db.query(NotificacionEnviada)
             .filter(NotificacionEnviada.id == promo.notificacion_id).first())
    assert notif is not None
    assert notif.alumno_id is None                    # no existe la cuenta real
    assert notif.destinatario_correo == candidato.correo
    assert notif.tenant_id == TENANT
    assert notif.tipo == "migracion_promocion"

    # 3. GET del panel: el candidato deja de estar `sin_contactar` aunque siga sin login.
    r = cliente.get(RUTA, headers=admin_headers)
    assert r.status_code == 200, r.text
    fila = next(f for f in r.json()["alumnos"] if f["candidato_id"] == candidato.id)
    assert fila["id"] is None
    assert fila["estado"] == "promocion_enviada"
    assert fila["promocion"]["id"] == promo.id

    # 4. PUT: se marca recuperado sin necesitar cuenta.
    r = cliente.put(f"{RUTA}/{candidato.id}/marcar-recuperado", headers=admin_headers)
    assert r.status_code == 200, r.text
    marcada = r.json()
    assert marcada["id"] == promo.id
    assert marcada["candidato_id"] == candidato.id
    assert marcada["usuario_id"] is None
    assert marcada["estado"] == ESTADO_PROMO_RECUPERADO

    db.expire_all()
    db.refresh(promo)
    assert promo.estado == ESTADO_PROMO_RECUPERADO

    # Una segunda marca ya no encuentra oferta vigente (dato real, no error de red).
    r = cliente.put(f"{RUTA}/{candidato.id}/marcar-recuperado", headers=admin_headers)
    assert r.status_code == 404, r.text


def test_candidato_inexistente_404(cliente, admin_headers):
    """El id que no está en el padrón del box se rechaza en los tres endpoints."""
    inexistente = 999_999_999
    assert cliente.get(f"{RUTA}/{inexistente}/promocion/preview",
                       params=_params_preview(),
                       headers=admin_headers).status_code == 404
    assert cliente.post(f"{RUTA}/{inexistente}/promocion",
                        json=_cuerpo(), headers=admin_headers).status_code == 404
    assert cliente.put(f"{RUTA}/{inexistente}/marcar-recuperado",
                       headers=admin_headers).status_code == 404
