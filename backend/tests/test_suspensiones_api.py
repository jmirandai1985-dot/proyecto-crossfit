"""API del listado de Suspensión de plan del ADMIN (sólo lectura).

El autoservicio del alumno (elegibilidad / pedir / cancelar / historial propio) se
retiró: esos 4 endpoints ya no existen. Lo que queda acá es lo que usan la pantalla
de supervisión (`/admin/suspensiones`) y la ficha del alumno.

Cubre:
  * `cancelada_en` viaja en el payload del listado (auditoría de la ficha).

REQUISITO PREVIO: la migración `073_suspensiones_plan` debe estar aplicada en la
rama TEST (la tabla `suspensiones_plan`), y el servidor/BD apuntando a TEST.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suspensiones_api.py -q
"""
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.security import create_access_token                    # noqa: E402
from app.utils.santiago import (SANTIAGO, fecha_chile, fin_del_dia_chile,  # noqa: E402
                                hoy_santiago)


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin levantar servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _insertar_alumno(db, tenant_id, correo, creado):
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, :nom, :c, 'x', 'alumno', true, 'activo', :alta)
        RETURNING id"""),
        {"t": tenant_id, "r": uuid.uuid4().hex[:10], "nom": f"Alumno Susp {correo}",
         "c": correo, "alta": creado}).scalar()


@pytest.fixture
def escenario(db):
    """Un box propio con alumno y membresía activa.

    Crea todo desde cero (no depende de datos que ya estén en TEST) y lo borra al
    final. Es el mínimo que necesita el listado de suspensiones del admin.
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    hoy = hoy_santiago()
    creado = datetime.combine(hoy - timedelta(days=200), datetime.min.time(),
                              tzinfo=SANTIAGO)
    expiracion = fin_del_dia_chile(hoy + timedelta(days=30))

    ids = {"tenant": None, "alumno": None, "plan": None, "suscripcion": None}
    try:
        ids["tenant"] = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, now()) RETURNING id"""),
            {"n": f"Box Susp TEST {sufijo}", "s": f"box-susp-{sufijo}",
             "pub": str(uuid.uuid4())}).scalar()
        t = ids["tenant"]
        ids["alumno"] = _insertar_alumno(db, t, f"susp.{sufijo}@test.local", creado)
        ids["plan"] = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 20, false, 40000, 30, true, true) RETURNING id"""),
            {"t": t, "n": f"Plan Susp TEST {sufijo}"}).scalar()
        ids["suscripcion"] = db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, 'activo', 20, 20, now(), :exp) RETURNING id"""),
            {"t": t, "u": ids["alumno"], "p": ids["plan"], "exp": expiracion}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        raise

    yield {"db": db, "ids": ids, "hoy": hoy}

    # ── limpieza (siempre, aunque el test falle) ──
    db.rollback()
    t = ids["tenant"]
    try:
        for tabla in ("reservas", "suspensiones_plan", "clases", "horarios",
                      "suscripciones", "usuarios", "disciplinas", "planes"):
            db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"), {"t": t})
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": t})
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de suspensiones: {e}")


def _insertar_admin(db, tenant_id):
    """Admin del MISMO box: `GET /admin/suspensiones` exige rol administrador."""
    sufijo = uuid.uuid4().hex[:10]
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, 'Admin Susp TEST', :c, 'x', 'administrador', true, 'activo',
                now())
        RETURNING id"""),
        {"t": tenant_id, "r": sufijo,
         "c": f"susp.admin.{sufijo}@test.local"}).scalar()


def test_admin_suspensiones_expone_cancelada_en(escenario, cliente):
    """`cancelada_en` viaja en el payload del listado que usa la ficha del alumno.

    Antes el listado devolvía sólo `cancelada: true`, así que el bloque "solo
    lectura" no podía decir CUÁNDO se canceló aunque el dato ya existía en
    `suspensiones_plan.cancelada_en` (migración 074). Cuando NO está cancelada
    el campo va en `None`.
    """
    ids = escenario["ids"]
    db = escenario["db"]

    # La cancelada: instante conocido (mediodía de ayer en Chile).
    cancelada_en = datetime.combine(
        escenario["hoy"] - timedelta(days=1), datetime.min.time(),
        tzinfo=SANTIAGO) + timedelta(hours=12)
    cancelada = db.execute(text("""
        INSERT INTO suspensiones_plan (tenant_id, usuario_id, suscripcion_id,
                                       fecha_inicio, fecha_fin, dias, origen,
                                       fecha_expiracion_original, cancelada,
                                       cancelada_en, reservas_canceladas)
        VALUES (:t, :u, :s, now() - interval '5 days', now() + interval '2 days',
                2, 'alumno', now(), true, :cen, 0)
        RETURNING id"""),
        {"t": ids["tenant"], "u": ids["alumno"], "s": ids["suscripcion"],
         "cen": cancelada_en}).scalar()
    # La NO cancelada: mismo listado, `cancelada_en` en NULL.
    vigente = db.execute(text("""
        INSERT INTO suspensiones_plan (tenant_id, usuario_id, suscripcion_id,
                                       fecha_inicio, fecha_fin, dias, origen,
                                       fecha_expiracion_original, cancelada,
                                       cancelada_en, reservas_canceladas)
        VALUES (:t, :u, :s, now() + interval '10 days', now() + interval '12 days',
                2, 'alumno', now(), false, NULL, 0)
        RETURNING id"""),
        {"t": ids["tenant"], "u": ids["alumno"], "s": ids["suscripcion"]}).scalar()
    admin = _insertar_admin(db, ids["tenant"])
    db.commit()

    headers = {"Authorization": "Bearer " + create_access_token({
        "usuario_id": admin, "tenant_id": ids["tenant"], "rol": "administrador",
        "correo": "susp.admin@test.local"})}
    resp = cliente.get(f"/api/v1/admin/suspensiones?usuario_id={ids['alumno']}",
                       headers=headers)
    assert resp.status_code == 200, resp.text
    por_id = {s["id"]: s for s in resp.json()}

    fila = por_id[cancelada]
    assert fila["cancelada"] is True
    assert fila["cancelada_en"], "la fecha de cancelación tiene que viajar en el payload"
    # Mismo instante que el guardado; serializado como el resto (str de la BD).
    instante = datetime.fromisoformat(fila["cancelada_en"])
    assert instante == cancelada_en
    assert fecha_chile(instante) == fecha_chile(cancelada_en)

    assert por_id[vigente]["cancelada"] is False
    assert por_id[vigente]["cancelada_en"] is None

