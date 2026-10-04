"""
Certificado de estudiante (y voucher): documentos PRIVADOS solo con autenticación.

HALLAZGO (auditoría PROD): el certificado se subía SIN `?privado=1` a
/static/uploads/ (que StaticFiles sirve SIN token) y el panel admin lo abría por su
URL pública: cualquiera con el link veía el documento del alumno. Además no existía
endpoint autenticado de certificados (solo el de voucher).

CONTRATO QUE SE PRUEBA ACÁ — GET /solicitudes/{id}/certificado:
  * 200 para el alumno DUEÑO y para el staff del MISMO box (attachment e inline),
    y el archivo se sirve con su tipo real (image/png), no forzado a JPEG;
  * 403 para otro alumno del box y para un admin de OTRO box (IDOR / cross-tenant);
  * 401 sin token;
  * 404 si la solicitud no existe o no tiene certificado;
  * sirve los DOS orígenes (nuevos en /privado/vouchers/... y viejos en
    /static/uploads/...) y rechaza el path traversal (403) y un origen
    desconocido (400).

Requiere la API corriendo contra el branch TEST. Todo el escenario vive en un box
TEMPORAL que se borra al final (no depende del seed y no deja rastro).
"""
import base64
import os
import uuid
import warnings
from datetime import datetime, timezone

import pytest
import requests
from sqlalchemy import text

from app.api.v1.upload import PRIVATE_DIR, UPLOAD_DIR
from app.core.security import create_access_token
from app.db.database import SessionLocal
from tests.conftest import BASE, get_admin_token

# PNG 1x1 de verdad: el guard de subida valida la FIRMA (magic bytes), no la extensión.
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg==")


def _get(solicitud_id, documento="certificado", headers=None, **params):
    return requests.get(f"{BASE}/solicitudes/{solicitud_id}/{documento}",
                        headers=headers, params=params or None, timeout=30)


def _set_certificado(db, solicitud_id, url):
    """Escribe la URL del certificado en la fila (para probar los dos orígenes)."""
    db.execute(text(
        "UPDATE solicitudes_planes SET certificado_estudiante_url = :u WHERE id = :i"),
        {"u": url, "i": solicitud_id})
    db.commit()


@pytest.fixture(scope="module")
def box():
    """Box temporal: tenant + admin + 2 alumnos + plan (y su borrado total al final).

    El admin del box y los alumnos son usuarios REALES del box nuevo, así que los
    tokens pasan el mismo camino que el navegador (get_current_user lee la fila).
    """
    db = SessionLocal()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alta = datetime.now(timezone.utc)
    ids = []
    tenant = admin = plan = None
    archivos = []
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Documentos TEST {sufijo}", "s": f"box-documentos-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        admin = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, '22222222-2', 'Admin Documentos TEST', :c, 'x', 'administrador',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "c": f"docs.admin.{sufijo}@test.local", "alta": alta}).scalar()
        for n in (1, 2):
            ids.append(db.execute(text("""
                INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                      activo, estado, created_at)
                VALUES (:t, :r, :nom, :c, 'x', 'alumno', true, 'activo', :alta)
                RETURNING id"""),
                {"t": tenant, "r": f"3{n}{sufijo[-7:]}-{n}",
                 "nom": f"Alumno Documentos TEST {n}",
                 "c": f"docs.alumno{n}.{sufijo}@test.local", "alta": alta}).scalar())
        plan = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 10, false, 40000, 30, true, true) RETURNING id"""),
            {"t": tenant, "n": f"Plan Documentos TEST {sufijo}"}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        raise

    def token(usuario_id, rol):
        return {"Authorization": "Bearer " + create_access_token({
            "usuario_id": usuario_id, "tenant_id": tenant, "rol": rol,
            "correo": "docs@test.local"})}

    datos = {"db": db, "tenant_id": tenant, "admin_id": admin,
             "alumno_id": ids[0], "otro_id": ids[1], "plan_id": plan,
             "admin": token(admin, "administrador"),
             "alumno": token(ids[0], "alumno"),
             "otro_alumno": token(ids[1], "alumno"),
             "archivos": archivos}
    try:
        yield datos
    finally:
        for ruta in archivos:
            try:
                os.remove(ruta)
            except OSError:
                pass
        db.rollback()
        # Cada tabla se borra en su propia transacción (savepoint) y con 3 pasadas:
        # si una FK inesperada rechaza un DELETE (p.ej. notificaciones_enviadas, que
        # referencia al alumno) NO se revierte el box entero; el resto se limpia igual
        # y lo que quede se reporta como warning VISIBLE (no un residuo silencioso).
        pendientes = ["notificaciones_enviadas", "solicitudes_planes",
                      "planes", "usuarios"]
        for _ in range(3):
            for tabla in list(pendientes):
                try:
                    with db.begin_nested():
                        db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"),
                                   {"t": tenant})
                except Exception:
                    continue            # queda para la pasada siguiente
                pendientes.remove(tabla)
            if not pendientes:
                break
        try:
            with db.begin_nested():
                db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
        except Exception:
            pendientes.append("tenants")
        if pendientes:
            warnings.warn(f"[residuo] box de documentos {tenant}: no se pudo borrar "
                          f"{pendientes} (revisar FKs)", stacklevel=2)
        db.commit()
        db.close()


@pytest.fixture(scope="module")
def escenario(box):
    """Certificado PRIVADO subido por la API (como el front, con ?privado=1) + solicitud.

    Devuelve el id de la solicitud y la URL guardada (/privado/vouchers/...).
    """
    r = requests.post(f"{BASE}/upload/voucher", params={"privado": "1"},
                      headers=box["admin"],
                      files={"file": ("certificado.png", PNG_1x1, "image/png")},
                      timeout=30)
    if r.status_code != 201:
        pytest.skip(f"no se pudo subir el certificado: {r.status_code} {r.text[:120]}")
    url = r.json()["url"]
    assert url.startswith("/privado/vouchers/"), f"el certificado no quedó privado: {url}"
    box["archivos"].append(os.path.join(PRIVATE_DIR, os.path.basename(url)))

    r = requests.post(f"{BASE}/solicitudes/solicitar", headers=box["alumno"],
                      json={"tenant_id": box["tenant_id"],
                            "alumno_id": box["alumno_id"],
                            "plan_id": box["plan_id"],
                            "voucher_url": url,
                            "certificado_estudiante_url": url},
                      timeout=30)
    if r.status_code != 201:
        pytest.skip(f"no se pudo crear la solicitud: {r.status_code} {r.text[:120]}")

    datos = dict(box)
    datos["solicitud_id"] = r.json()["id"]
    datos["certificado_url"] = url
    return datos


def _staff_de_otro_box():
    """Header del admin del box 1 del seed (OTRO box). Skip si TEST no lo tiene."""
    h = {"Authorization": f"Bearer {get_admin_token()}"}
    r = requests.get(f"{BASE}/alumnos/me", headers=h, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"TEST no tiene el admin del box 1 (status {r.status_code})")
    return h


# ═══════════════════════════════════════════════════════════════════
# 200 — el dueño y el staff del MISMO box
# ═══════════════════════════════════════════════════════════════════

def test_cert_01_staff_del_box_lo_ve_con_su_tipo_real(escenario):
    """El admin del box lo descarga (attachment) y lo previsualiza (inline)."""
    sid = escenario["solicitud_id"]

    r = _get(sid, headers=escenario["admin"])
    assert r.status_code == 200, r.text[:200]
    assert r.headers["content-type"].startswith("image/png"), r.headers.get("content-type")
    assert "attachment" in r.headers.get("content-disposition", ""), r.headers

    r2 = _get(sid, headers=escenario["admin"], inline=1)
    assert r2.status_code == 200, r2.text[:200]
    assert "inline" in r2.headers.get("content-disposition", ""), r2.headers


def test_cert_02_el_alumno_dueno_lo_ve(escenario):
    """El alumno dueño de la solicitud puede ver su propio certificado."""
    r = _get(escenario["solicitud_id"], headers=escenario["alumno"])
    assert r.status_code == 200, r.text[:200]
    assert r.headers["content-type"].startswith("image/png")


# ═══════════════════════════════════════════════════════════════════
# 403 — otro alumno y otro box (IDOR / cross-tenant)
# ═══════════════════════════════════════════════════════════════════

def test_cert_03_otro_alumno_del_box_no_lo_ve(escenario):
    """Otro alumno del mismo box no es el dueño: 403 (antes bastaba el id)."""
    r = _get(escenario["solicitud_id"], headers=escenario["otro_alumno"])
    assert r.status_code == 403, f"status {r.status_code}: {r.text[:200]}"


def test_cert_04_admin_de_otro_box_no_lo_ve(escenario):
    """El staff de OTRO box no ve documentos de este box (cross-tenant)."""
    r = _get(escenario["solicitud_id"], headers=_staff_de_otro_box())
    assert r.status_code == 403, f"status {r.status_code}: {r.text[:200]}"


# ═══════════════════════════════════════════════════════════════════
# 401 / 404
# ═══════════════════════════════════════════════════════════════════

def test_cert_05_sin_token_es_401(escenario):
    """Sin token no hay documento (ni certificado ni voucher)."""
    sid = escenario["solicitud_id"]
    assert _get(sid).status_code == 401
    assert _get(sid, documento="voucher").status_code == 401


def test_cert_06_inexistente_es_404(escenario):
    assert _get(999999999, headers=escenario["admin"]).status_code == 404


def test_cert_07_sin_certificado_es_404(escenario):
    """Una solicitud sin certificado responde 404 (y se restaura el valor)."""
    db, sid = escenario["db"], escenario["solicitud_id"]
    url_original = escenario["certificado_url"]
    try:
        _set_certificado(db, sid, None)
        r = _get(sid, headers=escenario["admin"])
        assert r.status_code == 404, f"status {r.status_code}: {r.text[:200]}"
    finally:
        _set_certificado(db, sid, url_original)


# ═══════════════════════════════════════════════════════════════════
# Orígenes soportados y path traversal
# ═══════════════════════════════════════════════════════════════════

def test_cert_08_origen_legacy_y_traversal(escenario):
    """Sirve el certificado HISTÓRICO (/static/uploads) y bloquea el traversal."""
    db, sid = escenario["db"], escenario["solicitud_id"]
    url_original = escenario["certificado_url"]
    nombre = f"certificado_legacy_{uuid.uuid4().hex}.png"
    ruta = os.path.join(UPLOAD_DIR, nombre)
    with open(ruta, "wb") as f:
        f.write(PNG_1x1)
    escenario["archivos"].append(ruta)
    try:
        # (a) certificado viejo, servido por la carpeta pública SIN exponerla
        _set_certificado(db, sid, f"/static/uploads/{nombre}")
        r = _get(sid, headers=escenario["admin"])
        assert r.status_code == 200, f"legacy: {r.status_code} {r.text[:200]}"

        # (b) path traversal: el archivo resuelto sale de la carpeta base -> 403
        _set_certificado(db, sid, "/static/../../../etc/passwd")
        r2 = _get(sid, headers=escenario["admin"])
        assert r2.status_code == 403, f"traversal: {r2.status_code} {r2.text[:200]}"

        # (c) origen desconocido -> 400
        _set_certificado(db, sid, "https://otro-sitio.example/certificado.png")
        r3 = _get(sid, headers=escenario["admin"])
        assert r3.status_code == 400, f"origen: {r3.status_code} {r3.text[:200]}"
    finally:
        _set_certificado(db, sid, url_original)
