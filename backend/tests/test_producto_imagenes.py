"""
Galería de fotos del producto del Bazar (migración 055).

CONTRATO QUE SE PRUEBA — /productos/{id}/imagenes:
  * GET lista la galería ordenada (orden=0 es la portada) y la ve el alumno;
  * POST agrega 1..n fotos, respeta el tope de 5 y deja la primera como portada;
  * PUT .../orden reordena la galería completa y actualiza la portada;
  * DELETE quita una foto, renumera 0..n-1 y NUNCA permite borrar la última;
  * toda mutación mantiene `productos.imagen_url` = URL de la foto orden=0, que
    es lo que siguen leyendo el carrusel "Novedades del box" y las tarjetas;
  * crear un producto con `file` (legacy) o con varios `files` crea su galería
    completa y deja la primera foto como portada;
  * PUT /productos/{id} con imagen_url=null quita la portada y PROMUEVE la
    siguiente foto (el producto no queda apuntando a un archivo borrado);
  * 401 sin token, 403 con alumno en rutas de admin, 404 si es de otro box.

Todo el escenario vive en un box TEMPORAL que se borra al final y no depende del
seed. Los archivos locales subidos también se eliminan.
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

# PNG 1x1 real: el guard de subida valida magic bytes, no la extensión.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg==")

RAIZ_API = BASE.replace("/api/v1", "")


def _token(usuario_id, tenant_id, rol):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": usuario_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"galeria{usuario_id}@test.local"})}


def _crear(headers, nombre, con_foto=False):
    files = ({"file": ("portada.png", PNG_1X1, "image/png")}
             if con_foto else None)
    return requests.post(
        f"{BASE}/productos", headers=headers,
        data={"nombre": nombre, "precio": "12000", "stock": "9"},
        files=files, timeout=30)


def _agregar(producto_id, headers, cantidad=1):
    files = [("files", (f"foto{i}.png", PNG_1X1, "image/png"))
             for i in range(cantidad)]
    return requests.post(f"{BASE}/productos/{producto_id}/imagenes",
                         headers=headers, files=files, timeout=30)


def _galeria(producto_id, headers):
    return requests.get(f"{BASE}/productos/{producto_id}/imagenes",
                        headers=headers, timeout=30)


def _detalle(producto_id, headers):
    return requests.get(f"{BASE}/productos/{producto_id}",
                        headers=headers, timeout=30)


def _anotar_archivo(box, url):
    if url and url.startswith("/static/uploads/"):
        box["archivos"].append(os.path.join(UPLOAD_DIR, os.path.basename(url)))


@pytest.fixture(scope="module")
def box():
    """Box temporal: tenant + admin + alumno (se borra entero al final)."""
    db = SessionLocal()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alta = datetime.now(timezone.utc)
    tenant = None
    archivos = []
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Galeria TEST {sufijo}", "s": f"box-galeria-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()

        ids = {}
        for i, rol in enumerate(("administrador", "alumno")):
            ids[rol] = db.execute(text("""
                INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                                      rol, activo, estado, created_at)
                VALUES (:t, :rut, :nom, :c, 'x', :rol, true, 'activo', :alta)
                RETURNING id"""),
                {"t": tenant, "rut": f"{sufijo[-7:]}{i}-{sufijo[-1]}", "rol": rol,
                 "nom": f"{rol.capitalize()} Galeria TEST",
                 "c": f"galeria.{rol}.{sufijo}@test.local", "alta": alta}).scalar()
        db.commit()
        yield {"tenant": tenant, "archivos": archivos,
               "admin": _token(ids["administrador"], tenant, "administrador"),
               "alumno": _token(ids["alumno"], tenant, "alumno")}
    finally:
        for ruta in archivos:
            try:
                os.remove(ruta)
            except OSError:
                pass
        db.rollback()
        if tenant is not None:
            # producto_imagenes se va por CASCADE desde productos/tenant.
            db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
            db.commit()
        db.close()


@pytest.fixture(scope="module")
def producto(box):
    """Producto del box temporal, SIN foto: la galería arranca vacía."""
    r = _crear(box["admin"], f"Polera Galeria {uuid.uuid4().hex[:8]}")
    assert r.status_code == 201, r.text[:300]
    return r.json()


# ═══════════════════════════════════════════════════════════════════
# Alta múltiple y portada
# ═══════════════════════════════════════════════════════════════════

def test_01_sin_fotos_y_alta_multiple(box, producto):
    vacia = _galeria(producto["id"], box["admin"])
    assert vacia.status_code == 200, vacia.text[:300]
    assert vacia.json() == []

    r = _agregar(producto["id"], box["admin"], cantidad=2)
    assert r.status_code == 201, r.text[:300]
    fotos = r.json()
    assert len(fotos) == 2
    assert [f["orden"] for f in fotos] == [0, 1]
    for foto in fotos:
        _anotar_archivo(box, foto["url"])

    detalle = _detalle(producto["id"], box["admin"])
    assert detalle.status_code == 200, detalle.text[:300]
    assert detalle.json()["imagen_url"] == fotos[0]["url"], \
        "la portada derivada no apunta a la foto orden=0"
    assert [f["id"] for f in detalle.json()["imagenes"]] == [f["id"] for f in fotos]

    # Las fotos son PÚBLICAS: se descargan sin token (el alumno las ve).
    if fotos[0]["url"].startswith("/static/uploads/"):
        publica = requests.get(f"{RAIZ_API}{fotos[0]['url']}", timeout=30)
        assert publica.status_code == 200
        assert publica.content == PNG_1X1


def test_02_tope_de_cinco_fotos(box, producto):
    # Ya hay 2; se agregan 3 y queda justo en el tope.
    completo = _agregar(producto["id"], box["admin"], cantidad=3)
    assert completo.status_code == 201, completo.text[:300]
    assert len(completo.json()) == 5
    for foto in completo.json():
        _anotar_archivo(box, foto["url"])

    excedido = _agregar(producto["id"], box["admin"], cantidad=1)
    assert excedido.status_code == 400, excedido.text[:300]
    assert "Máximo 5" in excedido.json()["detail"]

    # El intento rechazado no agregó filas.
    assert len(_galeria(producto["id"], box["admin"]).json()) == 5


def test_03_reordenar_actualiza_la_portada(box, producto):
    fotos = _galeria(producto["id"], box["admin"]).json()
    ids_invertidos = [f["id"] for f in reversed(fotos)]

    r = requests.put(f"{BASE}/productos/{producto['id']}/imagenes/orden",
                     headers=box["admin"],
                     json={"imagen_ids": ids_invertidos}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    reordenadas = r.json()
    assert [f["id"] for f in reordenadas] == ids_invertidos
    assert [f["orden"] for f in reordenadas] == [0, 1, 2, 3, 4]

    detalle = _detalle(producto["id"], box["admin"]).json()
    assert detalle["imagen_url"] == reordenadas[0]["url"]
    assert [f["id"] for f in detalle["imagenes"]] == ids_invertidos

    # Orden incompleto o con repetidos: 400 y nada cambia.
    incompleto = requests.put(
        f"{BASE}/productos/{producto['id']}/imagenes/orden",
        headers=box["admin"], json={"imagen_ids": ids_invertidos[:2]}, timeout=30)
    assert incompleto.status_code == 400

    repetido = requests.put(
        f"{BASE}/productos/{producto['id']}/imagenes/orden",
        headers=box["admin"],
        json={"imagen_ids": [ids_invertidos[0]] * 5}, timeout=30)
    assert repetido.status_code == 400


def test_04_borrar_renumera_y_protege_la_ultima(box, producto):
    fotos = _galeria(producto["id"], box["admin"]).json()
    a_borrar = fotos[2]
    r = requests.delete(
        f"{BASE}/productos/{producto['id']}/imagenes/{a_borrar['id']}",
        headers=box["admin"], timeout=30)
    assert r.status_code == 204, r.text[:300]

    restantes = _galeria(producto["id"], box["admin"]).json()
    assert len(restantes) == 4
    assert [f["orden"] for f in restantes] == [0, 1, 2, 3]
    assert a_borrar["id"] not in [f["id"] for f in restantes]

    if a_borrar["url"].startswith("/static/uploads/"):
        assert requests.get(f"{RAIZ_API}{a_borrar['url']}",
                            timeout=30).status_code == 404

    # Se borran hasta quedar una sola.
    for foto in restantes[1:]:
        borrado = requests.delete(
            f"{BASE}/productos/{producto['id']}/imagenes/{foto['id']}",
            headers=box["admin"], timeout=30)
        assert borrado.status_code == 204, borrado.text[:300]

    ultima = _galeria(producto["id"], box["admin"]).json()
    assert len(ultima) == 1 and ultima[0]["orden"] == 0

    # La última NO se puede borrar: el producto conserva al menos una foto.
    impedido = requests.delete(
        f"{BASE}/productos/{producto['id']}/imagenes/{ultima[0]['id']}",
        headers=box["admin"], timeout=30)
    assert impedido.status_code == 400, impedido.text[:300]
    assert "al menos una foto" in impedido.json()["detail"]

    assert _detalle(producto["id"], box["admin"]).json()["imagen_url"] == ultima[0]["url"]


# ═══════════════════════════════════════════════════════════════════
# Compatibilidad con el flujo de UNA foto (041)
# ═══════════════════════════════════════════════════════════════════

def test_05_crear_con_file_crea_la_fila_orden_cero(box):
    r = _crear(box["admin"], f"Short Galeria {uuid.uuid4().hex[:8]}",
               con_foto=True)
    assert r.status_code == 201, r.text[:300]
    creado = r.json()
    _anotar_archivo(box, creado["imagen_url"])

    galeria = _galeria(creado["id"], box["admin"]).json()
    assert len(galeria) == 1
    assert galeria[0]["orden"] == 0
    assert galeria[0]["url"] == creado["imagen_url"]
    assert creado["imagenes"][0]["id"] == galeria[0]["id"]


def test_06_put_null_promueve_la_siguiente_foto(box):
    r = _crear(box["admin"], f"Gorra Galeria {uuid.uuid4().hex[:8]}")
    assert r.status_code == 201
    producto_id = r.json()["id"]

    agregadas = _agregar(producto_id, box["admin"], cantidad=2).json()
    for foto in agregadas:
        _anotar_archivo(box, foto["url"])
    portada_vieja = agregadas[0]["url"]

    # El botón "Quitar imagen" del flujo viejo quita SÓLO la portada: la
    # siguiente queda como portada y el archivo viejo se borra.
    quitada = requests.put(f"{BASE}/productos/{producto_id}",
                           headers=box["admin"],
                           json={"imagen_url": None}, timeout=30)
    assert quitada.status_code == 200, quitada.text[:300]
    assert quitada.json()["imagen_url"] == agregadas[1]["url"]

    galeria = _galeria(producto_id, box["admin"]).json()
    assert len(galeria) == 1
    assert galeria[0]["orden"] == 0
    assert galeria[0]["url"] == agregadas[1]["url"]

    if portada_vieja.startswith("/static/uploads/"):
        assert requests.get(f"{RAIZ_API}{portada_vieja}",
                            timeout=30).status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Permisos
# ═══════════════════════════════════════════════════════════════════

def test_07_permisos(box, producto):
    producto_id = producto["id"]

    # El alumno SÍ puede ver la galería (detalle del Bazar)...
    assert _galeria(producto_id, box["alumno"]).status_code == 200
    # ...pero no subir, borrar ni reordenar.
    assert _agregar(producto_id, box["alumno"], cantidad=1).status_code == 403
    assert _agregar(producto_id, {}, cantidad=1).status_code == 401

    una = _galeria(producto_id, box["admin"]).json()[0]
    assert requests.delete(
        f"{BASE}/productos/{producto_id}/imagenes/{una['id']}",
        headers=box["alumno"], timeout=30).status_code == 403
    assert requests.put(
        f"{BASE}/productos/{producto_id}/imagenes/orden",
        headers=box["alumno"], json={"imagen_ids": [una["id"]]},
        timeout=30).status_code == 403


def test_08_producto_de_otro_box_es_404(box, producto):
    h_otro_box = {"Authorization": f"Bearer {get_admin_token()}"}
    if requests.get(f"{BASE}/alumnos/me", headers=h_otro_box,
                    timeout=30).status_code != 200:
        pytest.skip("TEST no tiene el admin del box 1")

    assert _galeria(producto["id"], h_otro_box).status_code == 404
    assert _agregar(producto["id"], h_otro_box, cantidad=1).status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Alta atómica: producto + galería en una sola petición
# ═══════════════════════════════════════════════════════════════════

def test_09_crear_con_varios_files_en_una_sola_peticion(box):
    nombre = f"Jockey Galeria {uuid.uuid4().hex[:8]}"
    archivos = [("files", (f"foto{i}.png", PNG_1X1, "image/png"))
                for i in range(3)]
    r = requests.post(
        f"{BASE}/productos", headers=box["admin"],
        data={"nombre": nombre, "precio": "15000", "stock": "4"},
        files=archivos, timeout=30)
    assert r.status_code == 201, r.text[:300]
    creado = r.json()

    assert len(creado["imagenes"]) == 3
    assert [foto["orden"] for foto in creado["imagenes"]] == [0, 1, 2]
    assert creado["imagen_url"] == creado["imagenes"][0]["url"]
    for foto in creado["imagenes"]:
        _anotar_archivo(box, foto["url"])

    galeria = _galeria(creado["id"], box["admin"]).json()
    assert [foto["id"] for foto in galeria] == [foto["id"] for foto in creado["imagenes"]]

    # Seis fotos en el alta se rechazan ANTES de crear el producto.
    demasiadas = [("files", (f"extra{i}.png", PNG_1X1, "image/png"))
                  for i in range(6)]
    excedido = requests.post(
        f"{BASE}/productos", headers=box["admin"],
        data={"nombre": f"{nombre} extra", "precio": "15000", "stock": "4"},
        files=demasiadas, timeout=30)
    assert excedido.status_code == 400, excedido.text[:300]
    assert "Máximo 5" in excedido.json()["detail"]


def test_10_listado_repara_producto_legacy_sin_filas(box):
    """Un producto con `imagen_url` pero sin filas (dato externo a la 055) recibe
    su portada al listar, así el modal de edición ya tiene un id para reordenar."""
    db = SessionLocal()
    nombre = f"Legacy Galeria {uuid.uuid4().hex[:8]}"
    url = "/static/uploads/legacy-galeria.png"
    try:
        producto_id = db.execute(text("""
            INSERT INTO productos (tenant_id, nombre, precio, stock,
                                   alerta_stock_enviada, imagen_url,
                                   dias_anuncio, activo, created_at, updated_at)
            VALUES (:t, :n, 1000, 1, false, :url, 0, true, now(), now())
            RETURNING id"""),
            {"t": box["tenant"], "n": nombre, "url": url}).scalar()
        db.commit()
        assert db.execute(text(
            "SELECT count(*) FROM producto_imagenes WHERE producto_id = :p"),
            {"p": producto_id}).scalar() == 0

        listado = requests.get(f"{BASE}/productos?activo=true&limit=100",
                               headers=box["admin"], timeout=30)
        assert listado.status_code == 200, listado.text[:300]
        creado = next(p for p in listado.json() if p["id"] == producto_id)
        assert len(creado["imagenes"]) == 1
        assert creado["imagenes"][0]["url"] == url
        assert creado["imagenes"][0]["orden"] == 0
        assert creado["imagen_url"] == url

        # Idempotente: el segundo listado no duplica la portada.
        otra_vez = requests.get(f"{BASE}/productos?activo=true&limit=100",
                                headers=box["admin"], timeout=30).json()
        de_nuevo = next(p for p in otra_vez if p["id"] == producto_id)
        assert [f["id"] for f in de_nuevo["imagenes"]] == \
            [creado["imagenes"][0]["id"]]
    finally:
        db.rollback()
        db.close()
