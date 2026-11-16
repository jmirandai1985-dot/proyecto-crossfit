"""Disciplinas: familia de formulario (`tipo_formulario`) en el CRUD del admin.

Por qué existe: el ModalPublicarWod decide qué formulario mostrar según la
disciplina. El admin elige una de las 6 familias fijas al crear/editar y el
valor tiene que persistir y volver en el listado.

También cubre un hallazgo del camino: `POST/PUT /disciplinas` declaraba los
campos como query params y el panel manda JSON body. El endpoint acepta ahora
el body (y conserva el fallback por query para clientes viejos).

Requiere la API/BD de TEST (TestClient contra `app.main`). Todo el escenario
vive en un box TEMPORAL que se borra al final.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_disciplina_tipo_formulario_api.py -q
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import SessionLocal

API = "/api/v1"


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def box():
    """Box temporal: tenant + admin. Se borra completo al final."""
    db = SessionLocal()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alta = datetime.now(timezone.utc)
    tenant = None
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Disciplinas TEST {sufijo}",
             "s": f"box-disciplinas-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        admin = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Admin Disciplinas TEST', :c, 'x', 'administrador',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": f"7{sufijo[-7:]}-1",
             "c": f"disciplinas.admin.{sufijo}@test.local", "alta": alta}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        raise

    datos = {
        "db": db, "tenant_id": tenant, "sufijo": sufijo,
        "admin": {"Authorization": "Bearer " + create_access_token({
            "usuario_id": admin, "tenant_id": tenant, "rol": "administrador",
            "correo": "disciplinas@test.local"})},
    }
    try:
        yield datos
    finally:
        db.rollback()
        for tabla in ("auditoria", "coach_disciplinas", "disciplinas", "usuarios"):
            try:
                with db.begin_nested():
                    db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"),
                               {"t": tenant})
            except Exception:
                pass
        try:
            with db.begin_nested():
                db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
        except Exception:
            pass
        db.commit()
        db.close()


def test_crear_editar_y_listar_tipo_formulario(box, cliente):
    """El body JSON persiste la familia elegida y el listado la devuelve."""
    nombre = f"Fuerza TEST {box['sufijo']}"

    r = cliente.post(f"{API}/disciplinas/", headers=box["admin"],
                     json={"nombre": nombre, "tipo_formulario": "fuerza"})
    assert r.status_code == 201, r.text[:300]
    creada = r.json()
    assert creada["nombre"] == nombre
    assert creada["tipo_formulario"] == "fuerza"

    r_lista = cliente.get(f"{API}/disciplinas/", headers=box["admin"])
    assert r_lista.status_code == 200, r_lista.text[:300]
    en_lista = next((d for d in r_lista.json() if d["id"] == creada["id"]), None)
    assert en_lista is not None
    assert en_lista["tipo_formulario"] == "fuerza"

    # Editar SÓLO la familia: el resto de los campos no se toca.
    r_put = cliente.put(f"{API}/disciplinas/{creada['id']}", headers=box["admin"],
                        json={"tipo_formulario": "intervalos"})
    assert r_put.status_code == 200, r_put.text[:300]
    assert r_put.json()["tipo_formulario"] == "intervalos"
    assert r_put.json()["nombre"] == nombre


def test_tipo_formulario_invalido_o_faltante_es_422(box, cliente):
    """La API rechaza una familia fuera de las 6 y un create sin nombre."""
    r = cliente.post(f"{API}/disciplinas/", headers=box["admin"],
                     json={"nombre": f"Inválida {box['sufijo']}",
                           "tipo_formulario": "no_existe"})
    assert r.status_code == 422, r.text[:300]

    r_sin_nombre = cliente.post(f"{API}/disciplinas/", headers=box["admin"],
                                json={"tipo_formulario": "fuerza"})
    assert r_sin_nombre.status_code == 422, r_sin_nombre.text[:300]


def test_el_default_es_wod_metcon_para_las_disciplinas_existentes(box, cliente):
    """Una fila insertada SIN la columna (dato histórico) queda en `wod_metcon`."""
    db = box["db"]
    nombre = f"Histórica TEST {box['sufijo']}"
    disciplina_id = db.execute(text("""
        INSERT INTO disciplinas (tenant_id, nombre, es_open_box, requiere_coach, activo)
        VALUES (:t, :n, false, true, true) RETURNING id"""),
        {"t": box["tenant_id"], "n": nombre}).scalar()
    db.commit()

    r = cliente.get(f"{API}/disciplinas/", headers=box["admin"])
    assert r.status_code == 200, r.text[:300]
    fila = next((d for d in r.json() if d["id"] == disciplina_id), None)
    assert fila is not None
    assert fila["tipo_formulario"] == "wod_metcon", (
        "el default de la migración debe cubrir las disciplinas que ya existían")


def test_put_json_persiste_activo_y_las_tres_acciones_quedan_auditadas(box, cliente):
    """Regresión del bug real: el PUT con body JSON SÍ aplica `activo` y `requiere_coach`.

    Además comprueba que crear, editar y desactivar dejan su fila de auditoría
    con el valor anterior/nuevo.
    """
    db = box["db"]
    nombre = f"Auditoría TEST {box['sufijo']}"

    r = cliente.post(f"{API}/disciplinas/", headers=box["admin"], json={
        "nombre": nombre, "activo": True, "requiere_coach": True,
        "tipo_formulario": "fuerza",
    })
    assert r.status_code == 201, r.text[:300]
    disciplina_id = r.json()["id"]
    assert r.json()["activo"] is True

    # El bug original: estos dos campos viajaban en el JSON y el backend los
    # leía como query params (None) => no guardaba nada, sin error.
    r_put = cliente.put(f"{API}/disciplinas/{disciplina_id}", headers=box["admin"],
                        json={"activo": False, "requiere_coach": False})
    assert r_put.status_code == 200, r_put.text[:300]
    assert r_put.json()["activo"] is False
    assert r_put.json()["requiere_coach"] is False
    assert r_put.json()["nombre"] == nombre

    r_lista = cliente.get(f"{API}/disciplinas/", headers=box["admin"])
    assert r_lista.status_code == 200, r_lista.text[:300]
    persistida = next(d for d in r_lista.json() if d["id"] == disciplina_id)
    assert persistida["activo"] is False, "el PUT no persistió `activo`"
    assert persistida["requiere_coach"] is False

    r_del = cliente.delete(f"{API}/disciplinas/{disciplina_id}", headers=box["admin"])
    assert r_del.status_code == 204, r_del.text[:300]

    # La auditoría se escribe en la misma sesión de BD del test.
    db.rollback()
    filas = db.execute(text(
        "SELECT accion, detalle FROM auditoria "
        "WHERE entidad = 'disciplina' AND entidad_id = :i ORDER BY id"),
        {"i": disciplina_id}).fetchall()
    assert [f.accion for f in filas] == [
        "crear_disciplina", "actualizar_disciplina", "desactivar_disciplina"]
    cambios = next(f.detalle for f in filas
                   if f.accion == "actualizar_disciplina")["cambios"]
    assert cambios["activo"] == {"antes": True, "despues": False}
    assert cambios["requiere_coach"] == {"antes": True, "despues": False}
