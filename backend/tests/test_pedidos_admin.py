"""
Pedidos del Bazar (panel admin): listado por tenant, comprobante y cambio de estado.

HALLAZGOS (auditoría PROD):
  * el comprobante del pedido se subía a la carpeta privada (`?privado=1`) y NADIE
    podía verlo: no existía endpoint que lo sirviera (el admin no podía revisar el
    pago de un pedido);
  * el endpoint de cambio de estado existía pero no tenía consumidor: no había
    pantalla de Pedidos en el admin (por eso existe /admin/pedidos en el front).

CONTRATO QUE SE PRUEBA ACÁ:
  GET /pedidos
    * solo devuelve los pedidos del TENANT del token (un admin de otro box no ve
      nada del box ajeno);
    * trae los NOMBRES (alumno / producto) para la tabla del panel;
    * el filtro `?estado=` filtra de verdad.
  GET /pedidos/{id}/voucher
    * 200 para el staff del box y para el alumno DUEÑO (attachment / inline);
    * 403 para otro alumno del mismo box (IDOR);
    * 404 para otro tenant (no se revela que el id existe) y para un id inexistente;
    * 401 sin token.
  PUT /pedidos/{id}/estado
    * 200 avanzando pendiente → validado → entregado;
    * 400 si intenta saltar (pendiente → entregado);
    * 403 para un alumno (es de admin).

Requiere la API corriendo contra el branch TEST. Todo el escenario vive en un box
TEMPORAL que se borra al final.
"""
import base64
import os
import uuid
import warnings
from datetime import datetime, timezone

import pytest
import requests
from sqlalchemy import text

from app.api.v1.upload import PRIVATE_DIR
from app.core.security import create_access_token
from app.db.database import SessionLocal
from tests.conftest import BASE, get_admin_token

# PNG 1x1 real (el guard de subida valida la firma del archivo, no la extensión).
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg==")


def _get(ruta, headers=None, **params):
    return requests.get(f"{BASE}{ruta}", headers=headers, params=params or None, timeout=30)


def _staff_de_otro_box():
    """Header del admin del box 1 del seed (OTRO box). Skip si TEST no lo tiene."""
    h = {"Authorization": f"Bearer {get_admin_token()}"}
    if requests.get(f"{BASE}/alumnos/me", headers=h, timeout=30).status_code != 200:
        pytest.skip("TEST no tiene el admin del box 1")
    return h


@pytest.fixture(scope="module")
def box():
    """Box temporal: tenant + admin + 2 alumnos (y su borrado total al final)."""
    db = SessionLocal()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alta = datetime.now(timezone.utc)
    ids = []
    tenant = admin = None
    archivos = []
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Pedidos TEST {sufijo}", "s": f"box-pedidos-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        admin = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, '33333333-3', 'Admin Pedidos TEST', :c, 'x', 'administrador',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "c": f"pedidos.admin.{sufijo}@test.local", "alta": alta}).scalar()
        for n in (1, 2):
            ids.append(db.execute(text("""
                INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                      activo, estado, created_at)
                VALUES (:t, :r, :nom, :c, 'x', 'alumno', true, 'activo', :alta)
                RETURNING id"""),
                {"t": tenant, "r": f"4{n}{sufijo[-7:]}-{n}",
                 "nom": f"Alumno Pedidos TEST {n}",
                 "c": f"pedidos.alumno{n}.{sufijo}@test.local", "alta": alta}).scalar())
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        raise

    def token(usuario_id, rol):
        return {"Authorization": "Bearer " + create_access_token({
            "usuario_id": usuario_id, "tenant_id": tenant, "rol": rol,
            "correo": "pedidos@test.local"})}

    datos = {"db": db, "tenant_id": tenant, "admin_id": admin,
             "alumno_id": ids[0], "otro_id": ids[1],
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
        # referencia al pedido y al alumno) NO se revierte el box entero; el resto se
        # limpia igual y lo que quede se reporta como warning VISIBLE (no un residuo
        # silencioso: la primera versión dejaba el box completo en la BD de TEST).
        pendientes = ["notificaciones_enviadas", "pedidos", "solicitudes_planes",
                      "productos", "usuarios"]
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
            warnings.warn(f"[residuo] box de pedidos {tenant}: no se pudo borrar "
                          f"{pendientes} (revisar FKs)", stacklevel=2)
        db.commit()
        db.close()


@pytest.fixture(scope="module")
def pedido(box):
    """Un producto del box + un comprobante PRIVADO + el pedido del alumno 1.

    Devuelve el id del pedido y los ids usados (los tests no dependen del seed).
    """
    # Producto del box (admin del box) para poder pedirlo.
    r = requests.post(f"{BASE}/productos", headers=box["admin"],
                      data={"nombre": "Producto Pedidos TEST", "precio": 5000,
                            "stock": 10, "activo": "true"}, timeout=30)
    if r.status_code != 201:
        pytest.skip(f"no se pudo crear el producto: {r.status_code} {r.text[:120]}")
    producto_id = r.json()["id"]

    # Comprobante privado, como lo sube el alumno en el Bazar.
    r = requests.post(f"{BASE}/upload/voucher", params={"privado": "1"},
                      headers=box["alumno"],
                      files={"file": ("comprobante.png", PNG_1x1, "image/png")},
                      timeout=30)
    if r.status_code != 201:
        pytest.skip(f"no se pudo subir el comprobante: {r.status_code} {r.text[:120]}")
    url = r.json()["url"]
    assert url.startswith("/privado/vouchers/"), f"el comprobante no quedó privado: {url}"
    box["archivos"].append(os.path.join(PRIVATE_DIR, os.path.basename(url)))

    # Pedido: el alumno compra para sí mismo (tenant y alumno salen del token).
    r = requests.post(f"{BASE}/pedidos", headers=box["alumno"],
                      json={"tenant_id": box["tenant_id"], "alumno_id": box["alumno_id"],
                            "producto_id": producto_id, "cantidad": 1,
                            "voucher_url": url}, timeout=30)
    if r.status_code != 201:
        pytest.skip(f"no se pudo crear el pedido: {r.status_code} {r.text[:120]}")

    datos = dict(box)
    datos["pedido_id"] = r.json()["id"]
    datos["producto_id"] = producto_id
    datos["comprobante_url"] = url
    return datos


# ═══════════════════════════════════════════════════════════════════
# GET /pedidos — listado por tenant + nombres + filtro
# ═══════════════════════════════════════════════════════════════════

def test_ped_01_listado_solo_del_propio_tenant(pedido):
    """El admin del box ve su pedido (con nombres); el de OTRO box no lo ve."""
    r = _get("/pedidos", headers=pedido["admin"])
    assert r.status_code == 200, r.text[:200]
    items = r.json()
    assert isinstance(items, list), items
    mio = next((p for p in items if p["id"] == pedido["pedido_id"]), None)
    assert mio is not None, "el admin no ve el pedido de su propio box"
    # Los nombres vienen resueltos del backend (la tabla del panel los muestra).
    assert mio["alumno_nombre"] == "Alumno Pedidos TEST 1", mio
    assert mio["producto_nombre"] == "Producto Pedidos TEST", mio
    assert mio["alumno_email"], mio

    # Otro box: su listado NO puede contener el pedido (aislamiento por tenant).
    r2 = _get("/pedidos", headers=_staff_de_otro_box())
    assert r2.status_code == 200, r2.text[:200]
    assert all(p["id"] != pedido["pedido_id"] for p in r2.json()), \
        "un admin de otro box vio un pedido ajeno"


def test_ped_02_filtro_por_estado(pedido):
    """`?estado=pendiente` trae el pedido recién creado; `?estado=entregado` no."""
    r = _get("/pedidos", headers=pedido["admin"], estado="pendiente")
    assert r.status_code == 200, r.text[:200]
    assert any(p["id"] == pedido["pedido_id"] for p in r.json())

    r2 = _get("/pedidos", headers=pedido["admin"], estado="entregado")
    assert r2.status_code == 200, r2.text[:200]
    assert all(p["estado"] == "entregado" for p in r2.json())


# ═══════════════════════════════════════════════════════════════════
# GET /pedidos/{id}/voucher — comprobante privado
# ═══════════════════════════════════════════════════════════════════

def test_ped_03_staff_y_dueno_ven_el_comprobante(pedido):
    """El admin del box y el alumno dueño lo ven (attachment e inline) con su tipo."""
    ruta = f"/pedidos/{pedido['pedido_id']}/voucher"
    r = _get(ruta, headers=pedido["admin"])
    assert r.status_code == 200, r.text[:200]
    assert r.headers["content-type"].startswith("image/png"), r.headers.get("content-type")
    assert "attachment" in r.headers.get("content-disposition", ""), r.headers

    r2 = _get(ruta, headers=pedido["admin"], inline=1)
    assert r2.status_code == 200, r2.text[:200]
    assert "inline" in r2.headers.get("content-disposition", ""), r2.headers

    r3 = _get(ruta, headers=pedido["alumno"])
    assert r3.status_code == 200, r3.text[:200]


def test_ped_04_otro_alumno_no_ve_el_comprobante(pedido):
    """Otro alumno del box no es el dueño del pedido: 403 (IDOR)."""
    r = _get(f"/pedidos/{pedido['pedido_id']}/voucher", headers=pedido["otro_alumno"])
    assert r.status_code == 403, f"status {r.status_code}: {r.text[:200]}"


def test_ped_05_otro_box_e_inexistente_son_404(pedido):
    """Un admin de otro box recibe 404 (no se revela que el id existe)."""
    r = _get(f"/pedidos/{pedido['pedido_id']}/voucher", headers=_staff_de_otro_box())
    assert r.status_code == 404, f"status {r.status_code}: {r.text[:200]}"

    r2 = _get("/pedidos/999999999/voucher", headers=pedido["admin"])
    assert r2.status_code == 404, f"status {r2.status_code}: {r2.text[:200]}"


def test_ped_06_sin_token_es_401(pedido):
    assert _get(f"/pedidos/{pedido['pedido_id']}/voucher").status_code == 401


# ═══════════════════════════════════════════════════════════════════
# PUT /pedidos/{id}/estado — avanzar el estado
# ═══════════════════════════════════════════════════════════════════

def _cambiar_estado(pedido_id, estado, headers):
    return requests.put(f"{BASE}/pedidos/{pedido_id}/estado",
                        params={"nuevo_estado": estado}, headers=headers, timeout=30)


def test_ped_07_admin_avanza_el_estado(pedido):
    """pendiente → validado → entregado (solo hacia adelante)."""
    pid = pedido["pedido_id"]

    r = _cambiar_estado(pid, "entregado", pedido["admin"])
    assert r.status_code == 400, f"salto de estado permitido: {r.status_code} {r.text[:200]}"

    r2 = _cambiar_estado(pid, "validado", pedido["admin"])
    assert r2.status_code == 200, r2.text[:200]
    assert r2.json()["estado"] == "validado"

    r3 = _cambiar_estado(pid, "entregado", pedido["admin"])
    assert r3.status_code == 200, r3.text[:200]
    assert r3.json()["estado"] == "entregado"


def test_ped_08_alumno_no_puede_cambiar_el_estado(pedido):
    """El cambio de estado es de admin: un alumno recibe 403."""
    r = _cambiar_estado(pedido["pedido_id"], "validado", pedido["alumno"])
    assert r.status_code == 403, f"status {r.status_code}: {r.text[:200]}"
