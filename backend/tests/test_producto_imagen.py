"""
Imagen del producto (Bazar): se guarda, se devuelve y se ve en los dos paneles.

QUÉ CAMBIÓ (2026-04-10): el POST /productos recibía la imagen, la escribía en el
disco EFÍMERO del contenedor y DESCARTABA la URL (no existía la columna): el Bazar
mostraba sólo un emoji. Ahora `productos.imagen_url` (migración 041) guarda la URL
pública, que administra `app/services/storage.py` (disco en dev/TEST, R2 en PROD).

CONTRATO QUE SE PRUEBA — POST /productos (con archivo) y POST /productos/{id}/imagen:
  * la imagen queda PÚBLICA y se descarga por su URL SIN token, con su tipo real;
  * GET /productos (listado) y GET /productos/{id} devuelven `imagen_url`;
  * POST /productos/{id}/imagen REEMPLAZA la foto (URL nueva y vigente) y BORRA la
    anterior del almacenamiento;
  * PUT /productos/{id} con imagen_url=null la QUITA (el producto vuelve al emoji)
    y también borra el archivo;
  * sin archivo, el producto queda con imagen_url=null;
  * 401 sin token, 403 con token de alumno, 404 si el producto es de OTRO box.

Todo el escenario vive en un box TEMPORAL que se borra al final (no depende del seed
y no deja archivos en app/static/uploads).
"""
import base64
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from sqlalchemy import text

from app.api.v1.upload import UPLOAD_DIR
from app.core.security import create_access_token
from app.db.database import SessionLocal
from tests.conftest import BASE, get_admin_token

# PNG 1x1 de verdad: el guard de subida valida la FIRMA (magic bytes), no la extensión.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg==")

# El archivo estático lo sirve el backend FUERA de /api/v1 (mount /static).
RAIZ_API = BASE.replace("/api/v1", "")


def _token(usuario_id, tenant_id, rol):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": usuario_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"imagen{usuario_id}@test.local"})}


def _crear_con_foto(headers, nombre):
    return requests.post(
        f"{BASE}/productos", headers=headers,
        data={"nombre": nombre, "precio": "15000", "stock": "3"},
        files={"file": ("polera.png", PNG_1X1, "image/png")}, timeout=30)


def _crear_sin_foto(headers, nombre):
    return requests.post(
        f"{BASE}/productos", headers=headers,
        data={"nombre": nombre, "precio": "9000", "stock": "1"}, timeout=30)


def _subir_foto(producto_id, headers, nombre="foto_nueva.png"):
    return requests.post(
        f"{BASE}/productos/{producto_id}/imagen", headers=headers,
        files={"file": (nombre, PNG_1X1, "image/png")}, timeout=30)


def _anotar_archivo(box, imagen_url):
    """Recuerda el archivo del backend local para borrarlo al final del módulo."""
    box["archivos"].append(os.path.join(UPLOAD_DIR, os.path.basename(imagen_url)))


@pytest.fixture(scope="module")
def box():
    """Box temporal: tenant + admin + 1 alumno (y su borrado total al final).

    Los usuarios son filas REALES del box nuevo, así los tokens pasan el mismo
    camino que el navegador (get_current_user lee la fila).
    """
    db = SessionLocal()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alta = datetime.now(timezone.utc)
    tenant = None
    archivos = []
    productos = []
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Imagen TEST {sufijo}", "s": f"box-imagen-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        ids = {}
        # `uq_rut_por_tenant`: el rut es único DENTRO del box → uno distinto por usuario.
        for i, rol in enumerate(("administrador", "alumno")):
            ids[rol] = db.execute(text("""
                INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                                      rol, activo, estado, created_at)
                VALUES (:t, :rut, :nom, :c, 'x', :rol, true, 'activo', :alta)
                RETURNING id"""),
                {"t": tenant, "rut": f"{sufijo[-7:]}{i}-{sufijo[-1]}", "rol": rol,
                 "nom": f"{rol.capitalize()} Imagen TEST",
                 "c": f"img.{rol}.{sufijo}@test.local", "alta": alta}).scalar()
        db.commit()
        yield {"tenant": tenant, "archivos": archivos, "productos": productos,
               "admin": _token(ids["administrador"], tenant, "administrador"),
               "alumno": _token(ids["alumno"], tenant, "alumno")}
    finally:
        # Los archivos subidos quedan en el disco del backend local: se borran.
        for ruta in archivos:
            try:
                os.remove(ruta)
            except OSError:
                pass
        # Si el setup falló a mitad de camino la transacción quedó abortada: se
        # revierte ANTES de borrar (si no, el DELETE falla y tapa el error real).
        db.rollback()
        if tenant is not None:
            # Los productos se van con el box (productos.tenant_id ON DELETE CASCADE).
            db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
            db.commit()
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 201/200 — la imagen se guarda, se devuelve y se ve
# ═══════════════════════════════════════════════════════════════════

def test_01_crear_con_imagen_la_deja_publica(box):
    """El producto se crea con su foto y la imagen se sirve SIN token."""
    r = _crear_con_foto(box["admin"], f"Polera TEST {uuid.uuid4().hex[:8]}")
    assert r.status_code == 201, r.text[:300]

    producto = r.json()
    box["productos"].append(producto["id"])
    imagen_url = producto["imagen_url"]
    assert imagen_url, "el producto se creó SIN imagen_url (se descartó la foto)"
    _anotar_archivo(box, imagen_url)

    if not imagen_url.startswith("/static/uploads/"):
        pytest.skip("backend de almacenamiento no local: la URL pública la cubre test_storage_r2")

    # PÚBLICA de verdad: se descarga sin token, con el tipo real y el mismo contenido.
    img = requests.get(f"{RAIZ_API}{imagen_url}", timeout=30)
    assert img.status_code == 200, f"la imagen no es pública: {img.status_code}"
    assert img.headers["content-type"].startswith("image/png")
    assert img.content == PNG_1X1


def test_02_el_listado_y_el_detalle_devuelven_la_imagen(box):
    """El Bazar (listado) y el detalle traen la foto: es lo que consumen los paneles."""
    producto_id = box["productos"][-1]

    listado = requests.get(f"{BASE}/productos", headers=box["admin"], timeout=30)
    assert listado.status_code == 200, listado.text[:200]
    fila = next((p for p in listado.json() if p["id"] == producto_id), None)
    assert fila is not None, "el producto recién creado no aparece en el listado"
    assert fila["imagen_url"], "el listado NO trae imagen_url (el Bazar no podría mostrarla)"

    detalle = requests.get(f"{BASE}/productos/{producto_id}", headers=box["admin"], timeout=30)
    assert detalle.status_code == 200, detalle.text[:200]
    assert detalle.json()["imagen_url"] == fila["imagen_url"]


def test_03_reemplazar_la_imagen_cambia_la_url(box):
    """POST /productos/{id}/imagen (el PUT es JSON: no puede llevar archivo)."""
    producto_id = box["productos"][-1]
    antes = requests.get(f"{BASE}/productos/{producto_id}", headers=box["admin"],
                         timeout=30).json()["imagen_url"]

    r = _subir_foto(producto_id, box["admin"])
    assert r.status_code == 200, r.text[:300]

    despues = r.json()["imagen_url"]
    assert despues and despues != antes, "la imagen no se reemplazó"
    _anotar_archivo(box, despues)

    if despues.startswith("/static/uploads/"):
        assert requests.get(f"{RAIZ_API}{despues}", timeout=30).status_code == 200

    # La foto VIEJA ya no está: reemplazar no deja archivos huérfanos.
    if antes.startswith("/static/uploads/"):
        assert requests.get(f"{RAIZ_API}{antes}", timeout=30).status_code == 404, \
            "la imagen anterior quedó huérfana en el almacenamiento"


def test_04_put_con_null_quita_la_imagen(box):
    """El admin puede dejar el producto sin foto (vuelve el placeholder del Bazar).

    Y la foto que tenía se BORRA del almacenamiento (botón "Quitar imagen").
    """
    producto_id = box["productos"][-1]
    antes = requests.get(f"{BASE}/productos/{producto_id}", headers=box["admin"],
                         timeout=30).json()["imagen_url"]

    r = requests.put(f"{BASE}/productos/{producto_id}", headers=box["admin"],
                     json={"imagen_url": None}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    assert r.json()["imagen_url"] is None

    detalle = requests.get(f"{BASE}/productos/{producto_id}", headers=box["admin"], timeout=30)
    assert detalle.json()["imagen_url"] is None

    if antes and antes.startswith("/static/uploads/"):
        assert requests.get(f"{RAIZ_API}{antes}", timeout=30).status_code == 404, \
            "al quitar la imagen el archivo quedó huérfano"


def test_05_sin_foto_queda_en_null(box):
    """Sin archivo la columna queda NULL (antes: la URL se armaba y se perdía)."""
    r = _crear_sin_foto(box["admin"], f"Shaker TEST {uuid.uuid4().hex[:8]}")
    assert r.status_code == 201, r.text[:300]
    assert r.json()["imagen_url"] is None


# ═══════════════════════════════════════════════════════════════════
# 401 / 403 / 404
# ═══════════════════════════════════════════════════════════════════

def test_06_sin_token_401_y_con_alumno_403(box):
    producto_id = box["productos"][-1]
    assert _subir_foto(producto_id, {}).status_code == 401
    assert _subir_foto(producto_id, box["alumno"]).status_code == 403


def test_07_producto_de_otro_box_es_404(box):
    """El tenant sale del token: un producto de OTRO box no existe para este admin."""
    h_otro_box = {"Authorization": f"Bearer {get_admin_token()}"}
    if requests.get(f"{BASE}/alumnos/me", headers=h_otro_box, timeout=30).status_code != 200:
        pytest.skip("TEST no tiene el admin del box 1")

    assert _subir_foto(box["productos"][-1], h_otro_box).status_code == 404

