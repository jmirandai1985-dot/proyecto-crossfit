"""WOD publicado con una familia de formulario nueva: bloques en la BD real.

El mapeo del frontend (`mapearFamiliaAWod`) manda el detalle de fuerza,
secuencia, rounds o intervalos como `bloques` y un resumen en `wod_principal`.
Este test comprueba que el endpoint existente lo acepta y lo devuelve sin tocar
el modelo de datos (no hay columnas nuevas en `wods`).

Requiere la API/BD de TEST (TestClient contra `app.main`). Box temporal.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_wods_familias_api.py -q
"""
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import SessionLocal

API = "/api/v1"


@pytest.fixture(scope="module")
def cliente():
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
            {"n": f"Box WOD Familias TEST {sufijo}",
             "s": f"box-wod-familias-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        admin = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Admin WOD Familias TEST', :c, 'x', 'administrador',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": f"8{sufijo[-7:]}-1",
             "c": f"wod.familias.{sufijo}@test.local", "alta": alta}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        raise

    datos = {
        "db": db, "tenant_id": tenant,
        "admin": {"Authorization": "Bearer " + create_access_token({
            "usuario_id": admin, "tenant_id": tenant, "rol": "administrador",
            "correo": "wod.familias@test.local"})},
    }
    try:
        yield datos
    finally:
        db.rollback()
        for tabla in ("wod_resultados", "wod_bloques", "wods", "usuarios"):
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


def test_crear_y_editar_un_wod_de_fuerza_guarda_sus_bloques(box, cliente):
    """El payload de la familia viaja por las columnas existentes y vuelve igual."""
    fecha = date.today()
    r = cliente.post(f"{API}/wods/", headers=box["admin"],
                     json=_payload_fuerza(fecha))
    assert r.status_code == 200, r.text[:400]
    creado = r.json()
    wod_id = creado["id"]
    assert creado["tipo_metcon"] == "Fuerza"
    assert creado["wod_principal"] == "2 ejercicio(s) de fuerza"
    assert len(creado["bloques"]) == 2
    assert creado["bloques"][0]["titulo"] == "Back Squat"
    assert "Carga: 80 kg" in creado["bloques"][0]["descripcion"]

    # GET por id (lo que usa el modal al editar) devuelve los bloques.
    r_id = cliente.get(f"{API}/wods/{wod_id}", headers=box["admin"])
    assert r_id.status_code == 200, r_id.text[:300]
    assert len(r_id.json()["bloques"]) == 2

    # PUT con un solo bloque: reemplaza la lista (mismo contrato que el WOD de metcon).
    r_put = cliente.put(f"{API}/wods/{wod_id}", headers=box["admin"], json={
        "tipo_metcon": "Fuerza",
        "wod_principal": "1 ejercicio(s) de fuerza",
        "bloques": [
            {"orden": 1, "titulo": "Sentadilla", "tipo_metcon": "Fuerza",
             "descripcion": "Series: 3\nRepeticiones: 10\nCarga: 50 kg"},
        ],
    })
    assert r_put.status_code == 200, r_put.text[:400]
    assert r_put.json()["wod_principal"] == "1 ejercicio(s) de fuerza"
    assert len(r_put.json()["bloques"]) == 1
    assert r_put.json()["bloques"][0]["titulo"] == "Sentadilla"


def _payload_fuerza(fecha):
    return {
        "fecha": str(fecha),
        "titulo": "Fuerza",
        "estado": "publicado",
        "tipo_metcon": "Fuerza",
        "wod_principal": "2 ejercicio(s) de fuerza",
        "calentamiento": "",
        "fuerza_habilidad": "",
        "descripcion": "",
        "bloques": [
            {"orden": 1, "titulo": "Back Squat", "tipo_metcon": "Fuerza",
             "descripcion": "Series: 5\nRepeticiones: 5\nCarga: 80 kg"},
            {"orden": 2, "titulo": "Press banca", "tipo_metcon": "Fuerza",
             "descripcion": "Series: 4\nRepeticiones: 8\nCarga: 60 kg"},
        ],
    }
