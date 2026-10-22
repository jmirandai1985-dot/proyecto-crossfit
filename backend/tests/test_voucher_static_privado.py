"""
Voucher de una solicitud: SOLO por el endpoint autenticado.

HALLAZGO (auditoría): `/static/uploads/` lo sirve StaticFiles SIN token. Los
comprobantes NUEVOS ya se guardan en `/privado/vouchers/`, pero los HISTÓRICOS
(voucher_url = `/static/uploads/...`) seguían accesibles por su URL pública: el
UUID no es autenticación.

CONTRATO QUE SE FIJA ACÁ:
  1. GET /solicitudes/{id}/voucher SIN token -> 401 (nunca 200);
  2. GET /static/uploads/<comprobante> SIN token -> 404 (no se sirve el archivo);
  3. una imagen pública de /static/uploads SIGUE respondiendo 200 (el Bazar y los
     flyers no se rompen);
  4. el endpoint autenticado sigue sirviendo el voucher (200 + bytes reales).

Requiere la API corriendo contra el branch TEST (igual que el resto de tests).
Todo el escenario es un box TEMPORAL que se borra al final; los archivos se crean
en UPLOAD_DIR y también se borran.
"""
import base64
import os
import uuid
import warnings
from datetime import UTC, datetime

import pytest
import requests
from sqlalchemy import text

from app.api.v1.upload import UPLOAD_DIR
from app.core.security import create_access_token
from app.db.database import SessionLocal
from tests.conftest import BASE

RAIZ = BASE.replace("/api/v1", "")

# PNG 1x1 real (el guard de subida valida magic bytes, no la extensión).
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg==")


def _url_static(nombre):
    return f"{RAIZ}/static/uploads/{nombre}"


def _escribir(nombre):
    """Deja un archivo real en la carpeta pública y devuelve su ruta."""
    ruta = os.path.join(UPLOAD_DIR, nombre)
    with open(ruta, "wb") as f:
        f.write(PNG_1x1)
    return ruta


@pytest.fixture(scope="module")
def escenario():
    """Box temporal (tenant + admin + alumno + plan + solicitud con voucher static)."""
    db = SessionLocal()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alta = datetime.now(UTC)
    archivos = []
    tenant = admin = alumno = plan = solicitud = None
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Voucher Static TEST {sufijo}", "s": f"box-voucher-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        admin = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Admin Voucher TEST', :c, 'x', 'administrador',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": f"21{sufijo[-7:]}-1",
             "c": f"voucher.admin.{sufijo}@test.local", "alta": alta}).scalar()
        alumno = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Alumno Voucher TEST', :c, 'x', 'alumno',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": f"22{sufijo[-7:]}-2",
             "c": f"voucher.alumno.{sufijo}@test.local", "alta": alta}).scalar()
        plan = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 10, false, 40000, 30, true, true) RETURNING id"""),
            {"t": tenant, "n": f"Plan Voucher TEST {sufijo}"}).scalar()

        nombre = f"voucher_static_{uuid.uuid4().hex}.png"
        archivos.append(_escribir(nombre))
        solicitud = db.execute(text("""
            INSERT INTO solicitudes_planes
                (tenant_id, alumno_id, plan_id, estado, voucher_url, created_at)
            VALUES (:t, :a, :p, 'pending', :v, :alta) RETURNING id"""),
            {"t": tenant, "a": alumno, "p": plan,
             "v": f"/static/uploads/{nombre}", "alta": alta}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        for ruta in archivos:
            try:
                os.remove(ruta)
            except OSError:
                pass
        db.close()
        raise

    datos = {
        "db": db, "tenant_id": tenant, "solicitud_id": solicitud, "nombre": nombre,
        "archivos": archivos,
        "admin": {"Authorization": "Bearer " + create_access_token({
            "usuario_id": admin, "tenant_id": tenant, "rol": "administrador",
            "correo": "voucher.admin@test.local"})},
    }
    try:
        yield datos
    finally:
        for ruta in archivos:
            try:
                os.remove(ruta)
            except OSError:
                pass
        db.rollback()
        try:
            db.execute(text("DELETE FROM solicitudes_planes WHERE tenant_id = :t"),
                       {"t": tenant})
            db.execute(text("DELETE FROM planes WHERE tenant_id = :t"), {"t": tenant})
            db.execute(text("DELETE FROM usuarios WHERE tenant_id = :t"), {"t": tenant})
            db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
            db.commit()
        except Exception as exc:  # noqa: BLE001 - se reporta como warning visible
            db.rollback()
            warnings.warn(f"[residuo] box de voucher {tenant}: {exc}", stacklevel=2)
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 1) El endpoint del voucher exige token
# ═══════════════════════════════════════════════════════════════════

def test_voucher_01_endpoint_sin_token_es_401():
    """Sin Authorization -> 401 (NO se llega a mirar la solicitud)."""
    r = requests.get(f"{BASE}/solicitudes/1/voucher", timeout=30)
    assert r.status_code == 401, f"status {r.status_code}: {r.text[:200]}"


# ═══════════════════════════════════════════════════════════════════
# 2) /static/uploads ya no expone comprobantes
# ═══════════════════════════════════════════════════════════════════

def test_voucher_02_static_uploads_no_expone_comprobante(escenario):
    """El voucher histórico en /static/uploads responde 404 SIN token.

    Antes respondía 200 con el archivo: la URL (UUID) era la única "protección".
    Ahora StaticFiles consulta la BD y niega el archivo; el documento sólo se
    obtiene por GET /solicitudes/{id}/voucher con Bearer.
    """
    r = requests.get(_url_static(escenario["nombre"]), timeout=30)
    assert r.status_code == 404, f"status {r.status_code}: {r.text[:200]}"
    assert PNG_1x1 not in r.content, "el archivo NO debe viajar en la respuesta"


def test_voucher_03_static_uploads_sigue_sirviendo_publicos(escenario):
    """Una imagen pública (no referenciada como comprobante) se sirve igual que antes."""
    nombre = f"producto_{uuid.uuid4().hex}.png"
    escenario["archivos"].append(_escribir(nombre))
    r = requests.get(_url_static(nombre), timeout=30)
    assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
    assert r.content == PNG_1x1, "la imagen pública debe llegar intacta"


# ═══════════════════════════════════════════════════════════════════
# 3) El camino autenticado sigue funcionando
# ═══════════════════════════════════════════════════════════════════

def test_voucher_04_endpoint_autenticado_lo_sirve(escenario):
    """El admin del box baja el voucher histórico por el endpoint autenticado."""
    r = requests.get(f"{BASE}/solicitudes/{escenario['solicitud_id']}/voucher",
                     headers=escenario["admin"], timeout=30)
    assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
    assert r.content == PNG_1x1, "el voucher debe llegar intacto por el endpoint"
    assert "attachment" in r.headers.get("content-disposition", "").lower()


def test_voucher_05_huerfano_voucher_no_se_sirve(escenario):
    """Un `voucher_*` sin fila que lo respalde (huérfano) tampoco es público.

    Al borrar la solicitud/pedido el archivo quedaba en disco para siempre y se
    seguía sirviendo por su URL. Ahora se niega por el prefijo legacy, salvo que
    esté referenciado como imagen pública (foto/galería/flyer).
    """
    nombre = f"voucher_huerfano_{uuid.uuid4().hex}.png"
    escenario["archivos"].append(_escribir(nombre))
    r = requests.get(_url_static(nombre), timeout=30)
    assert r.status_code == 404, f"status {r.status_code}: {r.text[:200]}"
    assert PNG_1x1 not in r.content


def test_voucher_06_static_absoluta_tambien_se_bloquea(escenario):
    """Una URL vieja ABSOLUTA (https://host/static/uploads/...) tampoco se sirve."""
    nombre = f"voucher_abs_{uuid.uuid4().hex}.png"
    escenario["archivos"].append(_escribir(nombre))
    db, sid = escenario["db"], escenario["solicitud_id"]
    try:
        db.execute(text(
            "UPDATE solicitudes_planes SET voucher_url = :u WHERE id = :i"),
            {"u": f"https://panel.example/static/uploads/{nombre}", "i": sid})
        db.commit()
        r = requests.get(_url_static(nombre), timeout=30)
        assert r.status_code == 404, f"status {r.status_code}: {r.text[:200]}"
        assert PNG_1x1 not in r.content
    finally:
        db.execute(text(
            "UPDATE solicitudes_planes SET voucher_url = :u WHERE id = :i"),
            {"u": f"/static/uploads/{escenario['nombre']}", "i": sid})
        db.commit()