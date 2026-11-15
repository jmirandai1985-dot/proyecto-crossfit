"""API de SUSCRIPCIONES: edición manual (`PUT /suscripciones/{id}`).

Hasta ahora la única forma de tocar una membresía era darla de baja y crear otra
(`POST /suscripciones`, botón "Aprobar Pago"). Este endpoint AJUSTA la existente:
plan, vencimiento y créditos.

Cubre, contra la app real (TestClient) y la rama TEST:
  * edición exitosa de cada campo y body PARCIAL (sólo lo que viene);
  * `fecha_expiracion` como 'YYYY-MM-DD' = fin del día CHILENO (23:59:59);
  * 409 si la suscripción está vinculada a Mercado Pago (`mp_preapproval_id`);
  * 404 si no existe, si es de OTRO box o si el `plan_id` es de otro box;
  * 400 si `creditos_disponibles > creditos_totales` (plan NO ilimitado);
  * el plan ILIMITADO no aplica la regla de créditos;
  * queda el registro de auditoría con los campos que cambiaron (antes/después).

REQUISITO PREVIO: migraciones 067/068 (`pago_id`, `mp_preapproval_id`) aplicadas en
la rama TEST, y ENVIRONMENT=test (el fixture falla cerrado si no).

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suscripciones_editar_api.py -q
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

BASE_SUSCRIPCIONES = "/api/v1/suscripciones"


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


def _insertar_tenant(db, sufijo, etiqueta):
    return db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
        VALUES (:n, :s, :pub, true, now()) RETURNING id"""),
        {"n": f"Box {etiqueta} {sufijo}", "s": f"box-{etiqueta}-{sufijo}".lower(),
         "pub": str(uuid.uuid4())}).scalar()


def _insertar_usuario(db, tenant_id, rol, correo):
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, :nom, :c, 'x', :rol, true, 'activo', now())
        RETURNING id"""),
        {"t": tenant_id, "r": uuid.uuid4().hex[:10],
         "nom": f"Usuario {rol} {correo}", "c": correo, "rol": rol}).scalar()


def _insertar_plan(db, tenant_id, nombre, creditos=20, ilimitado=False):
    return db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                            duracion_dias, activo, es_comercial)
        VALUES (:t, :n, :c, :i, 40000, 30, true, true) RETURNING id"""),
        {"t": tenant_id, "n": nombre, "c": creditos, "i": ilimitado}).scalar()


def _insertar_suscripcion(db, tenant_id, usuario_id, plan_id, *, expiracion,
                          totales=20, disponibles=20, mp_preapproval_id=None):
    return db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                   creditos_totales, creditos_disponibles,
                                   fecha_inicio, fecha_expiracion,
                                   mp_preapproval_id)
        VALUES (:t, :u, :p, 'activo', :ct, :cd, now(), :exp, :mp)
        RETURNING id"""),
        {"t": tenant_id, "u": usuario_id, "p": plan_id, "ct": totales,
         "cd": disponibles, "exp": expiracion,
         "mp": mp_preapproval_id}).scalar()


@pytest.fixture
def escenario(db):
    """Dos boxes propios (el del token y OTRO) con admin, alumnos y planes.

    Todo se crea desde cero y se borra al final (aunque el test falle), así el
    archivo no depende del seed de TEST ni deja residuo.
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    expiracion = fin_del_dia_chile(hoy_santiago() + timedelta(days=30))

    ids = {"tenant": None, "otro_tenant": None, "admin": None, "alumno": None,
           "alumno_otro": None, "plan": None, "plan_ilimitado": None,
           "plan_otro": None}
    try:
        ids["tenant"] = _insertar_tenant(db, sufijo, "Susc")
        ids["otro_tenant"] = _insertar_tenant(db, f"{sufijo}b", "Otro")
        ids["admin"] = _insertar_usuario(
            db, ids["tenant"], "administrador", f"susc.admin.{sufijo}@test.local")
        ids["alumno"] = _insertar_usuario(
            db, ids["tenant"], "alumno", f"susc.alumno.{sufijo}@test.local")
        ids["alumno_otro"] = _insertar_usuario(
            db, ids["otro_tenant"], "alumno", f"susc.otro.{sufijo}@test.local")
        ids["plan"] = _insertar_plan(db, ids["tenant"], f"Plan Susc {sufijo}", 20)
        ids["plan_ilimitado"] = _insertar_plan(
            db, ids["tenant"], f"Plan Ilim {sufijo}", creditos=None, ilimitado=True)
        ids["plan_otro"] = _insertar_plan(
            db, ids["otro_tenant"], f"Plan Otro {sufijo}", 10)
        db.commit()
    except Exception:
        db.rollback()
        raise

    headers = {"Authorization": "Bearer " + create_access_token({
        "usuario_id": ids["admin"], "tenant_id": ids["tenant"],
        "rol": "administrador", "correo": f"susc.admin.{sufijo}@test.local"})}

    yield {"db": db, "ids": ids, "headers": headers, "expiracion": expiracion}

    # ── limpieza (siempre, aunque el test falle) ──
    db.rollback()
    try:
        for tabla in ("auditoria", "suscripciones", "usuarios", "planes"):
            for clave in ("tenant", "otro_tenant"):
                db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"),
                           {"t": ids[clave]})
        for clave in ("tenant", "otro_tenant"):
            db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": ids[clave]})
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de suscripciones: {e}")


def _nueva_suscripcion(escenario, *, plan_id=None, expiracion=None, totales=20,
                       disponibles=20, mp_preapproval_id=None, otro_box=False):
    """Suscripción NUEVA por test: los tests la mutan, así que NO se comparten."""
    db = escenario["db"]
    ids = escenario["ids"]
    sid = _insertar_suscripcion(
        db,
        ids["otro_tenant"] if otro_box else ids["tenant"],
        ids["alumno_otro"] if otro_box else ids["alumno"],
        plan_id or (ids["plan_otro"] if otro_box else ids["plan"]),
        expiracion=expiracion or escenario["expiracion"],
        totales=totales, disponibles=disponibles,
        mp_preapproval_id=mp_preapproval_id,
    )
    db.commit()
    return sid


def _fila(escenario, suscripcion_id):
    """Los campos editables tal como quedaron en la BD (sin pasar por el ORM)."""
    return escenario["db"].execute(text(
        "SELECT plan_id, creditos_totales, creditos_disponibles, fecha_expiracion "
        "FROM suscripciones WHERE id = :i"), {"i": suscripcion_id}).first()


# ── Edición exitosa ──────────────────────────────────────────────────────────
def test_edita_el_plan(escenario, cliente):
    ids = escenario["ids"]
    sid = _nueva_suscripcion(escenario)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"plan_id": ids["plan_ilimitado"]},
                       headers=escenario["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_id"] == ids["plan_ilimitado"]
    assert _fila(escenario, sid).plan_id == ids["plan_ilimitado"]


def test_edita_la_fecha_de_vencimiento_como_dia_chileno(escenario, cliente):
    sid = _nueva_suscripcion(escenario)
    nuevo_dia = hoy_santiago() + timedelta(days=45)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"fecha_expiracion": str(nuevo_dia)},
                       headers=escenario["headers"])
    assert resp.status_code == 200, resp.text
    instante = datetime.fromisoformat(resp.json()["fecha_expiracion"])
    # El día elegido es el de CHILE y el plan vale hasta las 23:59:59 de ese día.
    assert fecha_chile(instante) == nuevo_dia
    local = instante.astimezone(SANTIAGO)
    assert (local.hour, local.minute, local.second) == (23, 59, 59)


def test_edita_ambos_creditos(escenario, cliente):
    sid = _nueva_suscripcion(escenario, totales=20, disponibles=20)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_totales": 30, "creditos_disponibles": 25},
                       headers=escenario["headers"])
    assert resp.status_code == 200, resp.text
    fila = _fila(escenario, sid)
    assert (fila.creditos_totales, fila.creditos_disponibles) == (30, 25)


def test_body_parcial_no_toca_lo_que_no_viene(escenario, cliente):
    sid = _nueva_suscripcion(escenario)
    antes = _fila(escenario, sid)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_disponibles": 5},
                       headers=escenario["headers"])
    assert resp.status_code == 200, resp.text
    despues = _fila(escenario, sid)
    assert despues.creditos_disponibles == 5
    assert despues.plan_id == antes.plan_id
    assert despues.fecha_expiracion == antes.fecha_expiracion


# ── Mercado Pago: la edición manual queda BLOQUEADA ─────────────────────────
def test_409_si_esta_vinculada_a_mercado_pago(escenario, cliente):
    sid = _nueva_suscripcion(
        escenario, mp_preapproval_id=f"preapproval-{uuid.uuid4().hex[:12]}")
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_disponibles": 3},
                       headers=escenario["headers"])
    assert resp.status_code == 409, resp.text
    assert "Mercado Pago" in resp.json()["detail"]
    assert _fila(escenario, sid).creditos_disponibles == 20   # no se tocó nada


# ── 404: no existe / otro box / plan de otro box ────────────────────────────
def test_404_si_no_existe(escenario, cliente):
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/999999999",
                       json={"creditos_disponibles": 3},
                       headers=escenario["headers"])
    assert resp.status_code == 404


def test_404_si_es_de_otro_box(escenario, cliente):
    sid = _nueva_suscripcion(escenario, otro_box=True)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_disponibles": 3},
                       headers=escenario["headers"])
    assert resp.status_code == 404
    assert _fila(escenario, sid).creditos_disponibles == 20


def test_404_si_el_plan_es_de_otro_box(escenario, cliente):
    ids = escenario["ids"]
    sid = _nueva_suscripcion(escenario)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"plan_id": ids["plan_otro"]},
                       headers=escenario["headers"])
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Plan no encontrado"
    assert _fila(escenario, sid).plan_id == ids["plan"]


# ── Coherencia de créditos ──────────────────────────────────────────────────
def test_400_si_los_disponibles_del_body_superan_los_totales(escenario, cliente):
    sid = _nueva_suscripcion(escenario, totales=20, disponibles=20)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_disponibles": 25},
                       headers=escenario["headers"])
    assert resp.status_code == 400
    assert "no pueden superar" in resp.json()["detail"]
    assert _fila(escenario, sid).creditos_disponibles == 20


def test_400_si_el_estado_final_deja_disponibles_sobre_totales(escenario, cliente):
    """Bajar SÓLO los totales por debajo de los disponibles también es inconsistente."""
    sid = _nueva_suscripcion(escenario, totales=20, disponibles=20)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_totales": 10},
                       headers=escenario["headers"])
    assert resp.status_code == 400
    assert _fila(escenario, sid).creditos_totales == 20


def test_plan_ilimitado_no_aplica_la_regla_de_creditos(escenario, cliente):
    ids = escenario["ids"]
    sid = _nueva_suscripcion(escenario, totales=20, disponibles=20)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"plan_id": ids["plan_ilimitado"],
                             "creditos_totales": 5, "creditos_disponibles": 9},
                       headers=escenario["headers"])
    assert resp.status_code == 200, resp.text
    fila = _fila(escenario, sid)
    assert (fila.creditos_totales, fila.creditos_disponibles) == (5, 9)


def test_400_si_la_fecha_es_invalida(escenario, cliente):
    sid = _nueva_suscripcion(escenario)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"fecha_expiracion": "no-es-una-fecha"},
                       headers=escenario["headers"])
    assert resp.status_code == 400
    assert "fecha_expiracion" in resp.json()["detail"]


# ── Auditoría ───────────────────────────────────────────────────────────────
def test_auditoria_guarda_los_campos_que_cambiaron(escenario, cliente):
    ids = escenario["ids"]
    sid = _nueva_suscripcion(escenario, totales=20, disponibles=20)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_totales": 30, "creditos_disponibles": 7},
                       headers=escenario["headers"])
    assert resp.status_code == 200, resp.text

    fila = escenario["db"].execute(text(
        "SELECT accion, entidad, entidad_id, usuario_id, detalle FROM auditoria "
        "WHERE entidad = 'suscripcion' AND entidad_id = :i ORDER BY id DESC LIMIT 1"),
        {"i": sid}).first()
    assert fila is not None, "la edición tiene que quedar auditada"
    assert fila.accion == "UPDATE"
    assert fila.entidad == "suscripcion"
    assert fila.entidad_id == sid
    assert fila.usuario_id == ids["admin"]
    assert fila.detalle["usuario_id"] == ids["alumno"]
    assert fila.detalle["cambios"]["creditos_totales"] == {"antes": 20, "despues": 30}
    assert fila.detalle["cambios"]["creditos_disponibles"] == {"antes": 20, "despues": 7}
    # Lo que NO cambió no ensucia el detalle.
    assert "plan_id" not in fila.detalle["cambios"]


def test_sin_cambios_no_escribe_auditoria(escenario, cliente):
    sid = _nueva_suscripcion(escenario, totales=20, disponibles=20)
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_totales": 20, "creditos_disponibles": 20},
                       headers=escenario["headers"])
    assert resp.status_code == 200, resp.text
    n = escenario["db"].execute(text(
        "SELECT count(*) FROM auditoria WHERE entidad = 'suscripcion' "
        "AND entidad_id = :i"), {"i": sid}).scalar()
    assert n == 0


# ── Rol: sólo el admin del box ──────────────────────────────────────────────
def test_requiere_admin(escenario, cliente):
    ids = escenario["ids"]
    sid = _nueva_suscripcion(escenario)
    token_alumno = {"Authorization": "Bearer " + create_access_token({
        "usuario_id": ids["alumno"], "tenant_id": ids["tenant"],
        "rol": "alumno", "correo": "susc.alumno@test.local"})}
    resp = cliente.put(f"{BASE_SUSCRIPCIONES}/{sid}",
                       json={"creditos_disponibles": 3},
                       headers=token_alumno)
    assert resp.status_code == 403
    assert _fila(escenario, sid).creditos_disponibles == 20



