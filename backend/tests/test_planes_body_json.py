"""Los campos del plan viajan en el BODY JSON (POST/PUT /planes).

POR QUÉ EXISTE
--------------
El panel manda `api.post('/planes', payload)` / `api.put('/planes/{id}', payload)`
(body JSON de axios). Con los campos declarados SUELTOS en el endpoint, FastAPI los
leía como QUERY PARAMS:

  * POST  -> 400 ("revisa el nombre, el precio y la duración") con un body válido;
  * PUT   -> 200 SIN APLICAR NADA (edición silenciosa).

Es el mismo bug que se corrigió en `/horarios` (`tests/test_horarios_body_json.py`).
Estos casos fijan el contrato nuevo y, de paso, los campos que agrega el cambio de
planes de larga duración:

  * `es_ilimitado` (toggle del modal);
  * `genero: null` = plan UNISEX (categoría "Larga duración");
  * `plan_referencia_id` = plan mensual contra el que se compara el ahorro, y
    `null` para quitarlo.

Correr:
    cd backend && ENVIRONMENT=test py -3.12 -m pytest tests/test_planes_body_json.py -q
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

import app.models  # noqa: E402,F401
from app.core.config import is_test_db_url, settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models.plan import Plan  # noqa: E402
from app.models.usuario import RolUsuario, Usuario  # noqa: E402


@pytest.fixture(scope="module")
def db():
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _sufijo():
    return f"{datetime.now():%Y%m%d%H%M%S%f}"


def _crear_tenant(db) -> int:
    return db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
        VALUES (:n, :s, :p, true, now()) RETURNING id
    """), {"n": f"Box planes body {_sufijo()}", "s": f"box-plan-body-{_sufijo()}",
           "p": str(uuid.uuid4())}).scalar()


def _crear_admin(db, tenant_id: int) -> Usuario:
    admin = Usuario(
        tenant_id=tenant_id, rut=f"9{uuid.uuid4().hex[:8]}-9",
        nombre="Admin planes body", correo=f"plan.body.{_sufijo()}@test.local",
        password_hash="x", rol=RolUsuario.administrador, activo=True,
        estado="activo")
    db.add(admin)
    db.flush()
    return admin


def _crear_plan(db, tenant_id: int, nombre: str) -> Plan:
    plan = Plan(tenant_id=tenant_id, nombre=nombre, creditos=10,
                es_ilimitado=False, precio_clp=40000, duracion_dias=30,
                activo=True, es_comercial=True, genero="masculino")
    db.add(plan)
    db.flush()
    return plan


def _token(usuario_id: int, tenant_id: int) -> dict:
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": usuario_id, "tenant_id": tenant_id,
        "rol": "administrador", "correo": "admin@test.local"})}


def _limpiar(db, *tenant_ids) -> None:
    db.rollback()
    try:
        for tenant_id in tenant_ids:
            db.execute(text("DELETE FROM tenants WHERE id = :t"),
                       {"t": tenant_id})
        db.commit()
    except Exception as error:  # pragma: no cover
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar {tenant_ids}: {error}\n")


def test_post_lee_el_body_y_guarda_los_campos_nuevos(cliente, db):
    tenant_id = _crear_tenant(db)
    try:
        admin = _crear_admin(db, tenant_id)
        mensual = _crear_plan(db, tenant_id, f"Mensual body {_sufijo()}")
        db.commit()
        headers = _token(admin.id, tenant_id)
        nombre = f"Semestral body {_sufijo()}"

        respuesta = cliente.post("/api/v1/planes", json={
            "nombre": nombre, "precio_clp": 200000, "duracion_dias": 180,
            "creditos": 0, "es_ilimitado": True, "genero": None,
            "es_estudiante": False, "requiere_certificado_estudiante": False,
            "plan_referencia_id": mensual.id, "activo": True,
        }, headers=headers)
        assert respuesta.status_code == 201, respuesta.text
        creado = respuesta.json()
        assert creado["genero"] is None, "null = plan unisex"
        assert creado["es_ilimitado"] is True
        assert creado["plan_referencia_id"] == mensual.id

        db.rollback()
        fila = db.query(Plan).filter(Plan.id == creado["id"]).one()
        assert (fila.nombre, fila.precio_clp, fila.duracion_dias) == (
            nombre, 200000, 180)
        assert fila.genero is None and fila.es_ilimitado is True
        assert fila.plan_referencia_id == mensual.id
    finally:
        _limpiar(db, tenant_id)


def test_put_aplica_los_cambios_del_body(cliente, db):
    tenant_id = _crear_tenant(db)
    try:
        admin = _crear_admin(db, tenant_id)
        mensual = _crear_plan(db, tenant_id, f"Mensual ref {_sufijo()}")
        largo = _crear_plan(db, tenant_id, f"Trimestral {_sufijo()}")
        db.commit()
        headers = _token(admin.id, tenant_id)

        respuesta = cliente.put(f"/api/v1/planes/{largo.id}", json={
            "precio_clp": 99999, "es_ilimitado": True, "duracion_dias": 90,
            "genero": None, "plan_referencia_id": mensual.id,
        }, headers=headers)
        assert respuesta.status_code == 200, respuesta.text

        db.rollback()
        fila = db.query(Plan).filter(Plan.id == largo.id).one()
        assert fila.precio_clp == 99999, \
            "el PUT tiene que APLICAR el body (antes respondía 200 sin tocar nada)"
        assert fila.es_ilimitado is True
        assert fila.duracion_dias == 90
        assert fila.genero is None
        assert fila.plan_referencia_id == mensual.id

        # `null` explícito = quitar la comparación (el plan sigue existiendo).
        quitada = cliente.put(f"/api/v1/planes/{largo.id}",
                              json={"plan_referencia_id": None}, headers=headers)
        assert quitada.status_code == 200, quitada.text
        db.rollback()
        fila = db.query(Plan).filter(Plan.id == largo.id).one()
        assert fila.plan_referencia_id is None
    finally:
        _limpiar(db, tenant_id)


def test_put_rechaza_referencias_invalidas(cliente, db):
    tenant_id = _crear_tenant(db)
    otro_tenant = _crear_tenant(db)
    try:
        admin = _crear_admin(db, tenant_id)
        plan = _crear_plan(db, tenant_id, f"Largo propio {_sufijo()}")
        ajeno = _crear_plan(db, otro_tenant, f"Mensual ajeno {_sufijo()}")
        db.commit()
        headers = _token(admin.id, tenant_id)

        consigo = cliente.put(f"/api/v1/planes/{plan.id}",
                              json={"plan_referencia_id": plan.id},
                              headers=headers)
        assert consigo.status_code == 400, consigo.text

        cross = cliente.put(f"/api/v1/planes/{plan.id}",
                            json={"plan_referencia_id": ajeno.id},
                            headers=headers)
        assert cross.status_code == 400, cross.text
    finally:
        _limpiar(db, tenant_id, otro_tenant)


def test_post_sin_body_es_422(cliente, db):
    tenant_id = _crear_tenant(db)
    try:
        admin = _crear_admin(db, tenant_id)
        db.commit()
        respuesta = cliente.post("/api/v1/planes",
                                 headers=_token(admin.id, tenant_id))
        assert respuesta.status_code == 422, \
            "el contrato es body JSON (no query params)"
    finally:
        _limpiar(db, tenant_id)
