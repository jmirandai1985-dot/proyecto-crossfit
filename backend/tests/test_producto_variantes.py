"""Tallas/variantes por producto del Bazar (migración 083) — integración REAL contra TEST.

Qué fija este archivo (API en :8000 + branch TEST `ep-crimson-tooth-...`):

  1. **Alta con tallas** (`POST /productos` multipart + `variantes_json`): las filas
     se crean en la misma transacción, `productos.stock` queda congelado en 0 y el
     `stock` de la respuesta es la SUMA de las tallas activas.
  2. **Talla duplicada case-insensitive** ('S' y 's') → 400 con el mensaje del
     admin ("Ya existe la talla 'S' para este producto."), nunca un 500.
  3. **Edición** (`PUT /productos/{id}` JSON): la lista reemplaza el set completo
     (agrega, actualiza stock y borra las que ya no están).
  4. **Pedido con talla**: descuenta SÓLO `producto_variantes.stock` de esa talla,
     guarda `pedidos.talla` (snapshot) y NO toca `productos.stock`. Sin talla → 400.
  5. **Devolución**: rechazar y eliminar un pedido devuelven el stock a la talla.
  6. **Concurrencia**: dos compras simultáneas de la última unidad de una talla →
     sólo una pasa (mismo test de esfuerzo que `productos.stock`).
  7. **Regresión**: un producto SIN variantes funciona exactamente como antes.

Se saltea sola si la API no está arriba o si el proceso no corre con
`ENVIRONMENT=test`.

    $env:ENVIRONMENT='test'
    py -3.12 -m pytest tests/test_producto_variantes.py -q
"""
import json
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

if os.getenv("ENVIRONMENT") != "test":
    pytest.skip("variantes: exige ENVIRONMENT=test (escribe en TEST)",
                allow_module_level=True)

from sqlalchemy import create_engine, text                       # noqa: E402

from app.core.config import is_test_db_url, settings             # noqa: E402
from app.core.security import create_access_token                # noqa: E402

BASE = "http://localhost:8000/api/v1"
TENANT = 1
TIMEOUT = 30
# `requests` sólo manda multipart/form-data si hay `files`; un campo sin archivo
# fuerza ese content type (el endpoint declara `Form` + `File`).
MULTIPART = {"__multipart": (None, "1")}


@pytest.fixture(scope="module")
def engine():
    """Engine de la base TEST, o skip si la API no está arriba."""
    try:
        r = requests.get("http://localhost:8000/health", timeout=5)
        if r.status_code != 200:
            pytest.skip("API no disponible en :8000")
    except requests.RequestException:
        pytest.skip("API no disponible en :8000")

    url = settings.DIRECT_URL or settings.DATABASE_URL
    if not is_test_db_url(url):
        pytest.fail("la URL configurada NO es TEST: aborto (exporta ENVIRONMENT=test)")
    return create_engine(url)


def headers(usuario_id, rol="alumno"):
    """Token firmado igual que `tests/conftest.py` (no hace falta login)."""
    token = create_access_token({
        "usuario_id": usuario_id, "tenant_id": TENANT, "rol": rol,
        "correo": f"{rol}{usuario_id}@test.local",
    })
    return {"Authorization": f"Bearer {token}"}


def en_paralelo(acciones):
    """Corre las acciones en hilos distintos arrancando juntas (Barrera)."""
    barrera = threading.Barrier(len(acciones))

    def correr(accion):
        barrera.wait(timeout=10)
        return accion()

    with ThreadPoolExecutor(max_workers=len(acciones)) as pool:
        futuros = [pool.submit(correr, accion) for accion in acciones]
        return [f.result(timeout=TIMEOUT) for f in futuros]


class Escenario:
    """Filas propias de un test, con limpieza garantizada (`finally`)."""

    def __init__(self, engine):
        self.engine = engine
        self.usuarios = []
        self.suscripciones = []
        self.productos = []
        with engine.connect() as c:
            self.plan = c.execute(text(
                "select id from planes where tenant_id = :t order by id limit 1"),
                {"t": TENANT}).scalar()
        if not self.plan:
            pytest.skip("TEST sin planes: nada que escenificar")

    # ── alta ────────────────────────────────────────────────────────────────
    def usuario(self, rol="alumno"):
        sufijo = uuid.uuid4().hex[:10]
        with self.engine.begin() as c:
            uid = c.execute(text("""
                insert into usuarios
                    (tenant_id, rut, nombre, correo, password_hash, rol, activo, estado)
                values (:t, :rut, :nom, :mail, 'x', :rol, true, 'activo')
                returning id"""), {
                "t": TENANT, "rut": f"8{sufijo[:7]}",
                "nom": f"Variantes {sufijo}",
                "mail": f"variantes-{sufijo}@test.local",
                "rol": rol,
            }).scalar()
            self.usuarios.append(uid)
            sid = c.execute(text("""
                insert into suscripciones
                    (tenant_id, usuario_id, plan_id, estado, creditos_totales,
                     creditos_disponibles, fecha_inicio, fecha_expiracion)
                values (:t, :u, :p, 'activo', 5, 5, now(), now() + interval '30 days')
                returning id"""), {"t": TENANT, "u": uid, "p": self.plan}).scalar()
            self.suscripciones.append(sid)
        return uid

    def alumno(self):
        return self.usuario(rol="alumno")

    def admin(self):
        return self.usuario(rol="administrador")

    # ── API ─────────────────────────────────────────────────────────────────
    def crear_producto(self, admin, *, variantes=None, stock=0, nombre=None,
                       precio=10000):
        """POST /productos (multipart). Devuelve la respuesta cruda."""
        datos = {
            "nombre": nombre or f"Producto variantes {uuid.uuid4().hex[:8]}",
            "precio": str(precio),
            "stock": str(stock),
            "tiene_variantes": "true" if variantes is not None else "false",
        }
        if variantes is not None:
            datos["variantes_json"] = json.dumps(variantes)
        r = requests.post(f"{BASE}/productos", data=datos, files=MULTIPART,
                          headers=headers(admin, rol="administrador"),
                          timeout=TIMEOUT)
        if r.status_code == 201:
            self.productos.append(r.json()["id"])
        return r

    def comprar(self, alumno, producto_id, *, variante_id=None, cantidad=1):
        payload = {
            "tenant_id": TENANT, "alumno_id": alumno,
            "producto_id": producto_id, "cantidad": cantidad,
            "voucher_url": "https://test.local/voucher.png",
        }
        if variante_id is not None:
            payload["variante_id"] = variante_id
        return requests.post(f"{BASE}/pedidos", json=payload,
                             headers=headers(alumno), timeout=TIMEOUT)

    # ── consultas directas (la verdad está en la BD) ────────────────────────
    def stock_producto(self, producto_id):
        with self.engine.connect() as c:
            return c.execute(text("select stock from productos where id = :id"),
                             {"id": producto_id}).scalar()

    def stock_talla(self, variante_id):
        with self.engine.connect() as c:
            return c.execute(text(
                "select stock from producto_variantes where id = :id"),
                {"id": variante_id}).scalar()

    def tallas(self, producto_id):
        with self.engine.connect() as c:
            return c.execute(text(
                "select talla, stock from producto_variantes where producto_id = :id "
                "order by id"), {"id": producto_id}).fetchall()

    # ── baja ────────────────────────────────────────────────────────────────
    def limpiar(self):
        ids_u = self.usuarios or [0]
        ids_p = self.productos or [0]
        ids_s = self.suscripciones or [0]
        with self.engine.begin() as c:
            # Avisos del panel/correo que disparan POST /pedidos y el rechazo.
            c.execute(text("delete from notificaciones_enviadas "
                           "where alumno_id = any(:u)"), {"u": ids_u})
            c.execute(text("delete from notificaciones "
                           "where alumno_id = any(:u)"), {"u": ids_u})
            # Pedidos primero: `pedidos.variante_id` apunta a las tallas.
            c.execute(text("delete from pedidos where alumno_id = any(:u) "
                           "or producto_id = any(:p)"),
                      {"u": ids_u, "p": ids_p})
            c.execute(text("delete from transacciones_financieras "
                           "where referencia_tipo = 'suscripcion' and referencia_id in "
                           "(select id from suscripciones where usuario_id = any(:u) "
                           " or id = any(:s))"), {"u": ids_u, "s": ids_s})
            c.execute(text("delete from suscripciones where usuario_id = any(:u) "
                           "or id = any(:s)"), {"u": ids_u, "s": ids_s})
            # Borrar el producto se lleva sus tallas (CASCADE) y su galería.
            c.execute(text("delete from productos where id = any(:p)"), {"p": ids_p})
            c.execute(text("delete from usuarios where id = any(:u)"), {"u": ids_u})


# ── 1. Alta con tallas: stock = suma, productos.stock congelado ──────────────
def test_01_alta_con_tallas_suma_el_stock_y_congela_el_plano(engine):
    esc = Escenario(engine)
    try:
        admin = esc.admin()
        r = esc.crear_producto(admin, variantes=[{"talla": "S", "stock": 3},
                                                 {"talla": "M", "stock": 5}])
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["tiene_variantes"] is True
        assert data["stock"] == 8, f"el stock debe ser la suma de las tallas: {data}"
        assert [(v["talla"], v["stock"]) for v in data["variantes"]] == [
            ("S", 3), ("M", 5)]
        pid = data["id"]

        # `productos.stock` queda CONGELADO en 0: el número sale de las tallas.
        assert esc.stock_producto(pid) == 0

        detalle = requests.get(f"{BASE}/productos/{pid}",
                               headers=headers(admin, rol="administrador"),
                               timeout=TIMEOUT).json()
        assert detalle["stock"] == 8

        lista = requests.get(f"{BASE}/productos", params={"limit": 1000},
                             headers=headers(admin, rol="administrador"),
                             timeout=TIMEOUT).json()
        fila = next(p for p in lista if p["id"] == pid)
        assert fila["stock"] == 8, "el listado también devuelve la suma"
        assert len(fila["variantes"]) == 2
    finally:
        esc.limpiar()


# ── 2. Talla duplicada (case-insensitive) → 400 con mensaje claro ───────────
def test_02_talla_duplicada_case_insensitive_es_400(engine):
    esc = Escenario(engine)
    try:
        admin = esc.admin()
        # 'S' y 's' son la MISMA talla para el admin.
        r = esc.crear_producto(admin, variantes=[{"talla": "S", "stock": 1},
                                                 {"talla": "s", "stock": 2}])
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "Ya existe la talla 'S' para este producto."

        creado = esc.crear_producto(admin, variantes=[{"talla": "S", "stock": 1}])
        assert creado.status_code == 201, creado.text
        pid = creado.json()["id"]

        r_put = requests.put(
            f"{BASE}/productos/{pid}",
            json={"tiene_variantes": True,
                  "variantes": [{"talla": "M", "stock": 1},
                                {"talla": "m", "stock": 4}]},
            headers=headers(admin, rol="administrador"), timeout=TIMEOUT)
        assert r_put.status_code == 400, r_put.text
        assert r_put.json()["detail"] == "Ya existe la talla 'M' para este producto."
        # El PUT inválido no dejó nada a medio guardar.
        assert [(t, s) for t, s in esc.tallas(pid)] == [("S", 1)]
    finally:
        esc.limpiar()


# ── 3. PUT: la lista reemplaza el set completo de tallas ────────────────────
def test_03_put_reemplaza_el_set_de_tallas(engine):
    esc = Escenario(engine)
    try:
        admin = esc.admin()
        creado = esc.crear_producto(admin, variantes=[{"talla": "S", "stock": 3},
                                                      {"talla": "M", "stock": 5}])
        assert creado.status_code == 201, creado.text
        pid = creado.json()["id"]

        r = requests.put(
            f"{BASE}/productos/{pid}",
            json={"tiene_variantes": True,
                  "variantes": [{"talla": "S", "stock": 7},
                                {"talla": "L", "stock": 2}]},
            headers=headers(admin, rol="administrador"), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["stock"] == 9
        assert sorted((v["talla"], v["stock"]) for v in data["variantes"]) == [
            ("L", 2), ("S", 7)]
        # M se borró del set; S se ACTUALIZÓ (no se duplicó); L se creó.
        assert sorted((t, s) for t, s in esc.tallas(pid)) == [("L", 2), ("S", 7)]
        assert esc.stock_producto(pid) == 0

        # Encender el switch sin ninguna talla → 400 (quedaría agotado para siempre).
        r_vacio = requests.put(
            f"{BASE}/productos/{pid}",
            json={"tiene_variantes": True, "variantes": []},
            headers=headers(admin, rol="administrador"), timeout=TIMEOUT)
        assert r_vacio.status_code == 400, r_vacio.text
    finally:
        esc.limpiar()


# ── 4. Pedido con talla: descuenta SÓLO esa talla ────────────────────────────
def test_04_pedido_descuenta_solo_la_talla_y_guarda_el_snapshot(engine):
    esc = Escenario(engine)
    try:
        admin, alumno = esc.admin(), esc.alumno()
        creado = esc.crear_producto(admin, variantes=[{"talla": "S", "stock": 1},
                                                      {"talla": "M", "stock": 5}])
        assert creado.status_code == 201, creado.text
        data = creado.json()
        pid = data["id"]
        talla_s = next(v for v in data["variantes"] if v["talla"] == "S")
        talla_m = next(v for v in data["variantes"] if v["talla"] == "M")

        # El producto tiene variantes: sin talla no se puede comprar.
        r_sin = esc.comprar(alumno, pid)
        assert r_sin.status_code == 400, r_sin.text
        assert r_sin.json()["detail"] == "Debes elegir una talla"

        r = esc.comprar(alumno, pid, variante_id=talla_s["id"])
        assert r.status_code == 201, r.text
        pedido = r.json()
        assert pedido["talla"] == "S", "el pedido guarda el TEXTO de la talla"
        assert pedido["variante_id"] == talla_s["id"]

        assert esc.stock_talla(talla_s["id"]) == 0
        assert esc.stock_talla(talla_m["id"]) == 5, "la otra talla no se toca"
        assert esc.stock_producto(pid) == 0, "productos.stock queda congelado"

        # Esa talla quedó agotada: la segunda compra rebota con 400.
        r_agotada = esc.comprar(alumno, pid, variante_id=talla_s["id"])
        assert r_agotada.status_code == 400, r_agotada.text
        assert "Stock insuficiente" in r_agotada.json()["detail"]
    finally:
        esc.limpiar()


# ── 5. Rechazar / eliminar devuelven el stock a la TALLA ────────────────────
def test_05_rechazar_y_eliminar_devuelven_el_stock_a_la_talla(engine):
    esc = Escenario(engine)
    try:
        admin, alumno = esc.admin(), esc.alumno()
        creado = esc.crear_producto(admin, variantes=[{"talla": "S", "stock": 2}])
        assert creado.status_code == 201, creado.text
        data = creado.json()
        pid = data["id"]
        talla = data["variantes"][0]
        admin_headers = headers(admin, rol="administrador")

        # ── Rechazo (el camino del admin y el de la expiración de MP) ──
        pedido = esc.comprar(alumno, pid, variante_id=talla["id"]).json()
        assert esc.stock_talla(talla["id"]) == 1
        r = requests.post(f"{BASE}/pedidos/{pedido['id']}/rechazar",
                          json={"motivo": "prueba de talla"},
                          headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert esc.stock_talla(talla["id"]) == 2, "el rechazo devuelve la talla"
        assert esc.stock_producto(pid) == 0, "productos.stock sigue congelado"

        # ── Eliminación de un pedido pendiente ──
        pedido2 = esc.comprar(alumno, pid, variante_id=talla["id"]).json()
        assert esc.stock_talla(talla["id"]) == 1
        r2 = requests.delete(f"{BASE}/pedidos/{pedido2['id']}",
                             headers=admin_headers, timeout=TIMEOUT)
        assert r2.status_code == 204, r2.text
        assert esc.stock_talla(talla["id"]) == 2, "el DELETE devuelve la talla"
        assert esc.stock_producto(pid) == 0
    finally:
        esc.limpiar()


# ── 6. Concurrencia: la última unidad de una talla no se vende dos veces ────
def test_06_ultima_unidad_de_una_talla_no_se_vende_dos_veces(engine):
    esc = Escenario(engine)
    try:
        admin = esc.admin()
        alumno_a, alumno_b = esc.alumno(), esc.alumno()
        creado = esc.crear_producto(admin, variantes=[{"talla": "UNICA", "stock": 1}])
        assert creado.status_code == 201, creado.text
        data = creado.json()
        pid = data["id"]
        talla = data["variantes"][0]

        r_a, r_b = en_paralelo([
            lambda: esc.comprar(alumno_a, pid, variante_id=talla["id"]),
            lambda: esc.comprar(alumno_b, pid, variante_id=talla["id"]),
        ])
        assert sorted([r_a.status_code, r_b.status_code]) == [201, 400], (
            f"esperaba 201 + 400, llegaron {r_a.status_code}/{r_b.status_code}: "
            f"{r_a.text[:200]} | {r_b.text[:200]}")

        assert esc.stock_talla(talla["id"]) == 0, "la talla no puede quedar negativa"
        assert esc.stock_producto(pid) == 0
        with engine.connect() as c:
            pedidos = c.execute(text(
                "select count(*) from pedidos where producto_id = :id"),
                {"id": pid}).scalar()
        assert pedidos == 1, "dos compras de la última unidad no pueden pasar"
    finally:
        esc.limpiar()


# ── 7. Regresión: producto SIN variantes, flujo de siempre ──────────────────
def test_07_producto_sin_variantes_sigue_igual(engine):
    esc = Escenario(engine)
    try:
        admin, alumno = esc.admin(), esc.alumno()
        creado = esc.crear_producto(admin, stock=2)
        assert creado.status_code == 201, creado.text
        data = creado.json()
        assert data["tiene_variantes"] is False
        assert data["variantes"] == []
        assert data["stock"] == 2
        pid = data["id"]

        r = esc.comprar(alumno, pid, cantidad=2)
        assert r.status_code == 201, r.text
        pedido = r.json()
        assert pedido["talla"] is None, "sin tallas no se guarda snapshot"
        assert pedido["variante_id"] is None
        assert esc.stock_producto(pid) == 0, "el stock plano sí se descuenta"
        with engine.connect() as c:
            tallas = c.execute(text(
                "select count(*) from producto_variantes where producto_id = :id"),
                {"id": pid}).scalar()
        assert tallas == 0
    finally:
        esc.limpiar()


# ── 8. Switch APAGADO: `variantes_json` se ignora (producto sin tallas) ─────
def test_08_switch_apagado_ignora_las_tallas(engine):
    esc = Escenario(engine)
    try:
        admin = esc.admin()
        datos = {
            "nombre": f"Producto sin tallas {uuid.uuid4().hex[:8]}",
            "precio": "5000",
            "stock": "4",
            "tiene_variantes": "false",
            # Un cliente podría mandar la lista igual; con el switch apagado el
            # producto nace SIN variantes y usa el stock plano (decisión 083).
            "variantes_json": json.dumps([{"talla": "S", "stock": 9}]),
        }
        r = requests.post(f"{BASE}/productos", data=datos, files=MULTIPART,
                          headers=headers(admin, rol="administrador"),
                          timeout=TIMEOUT)
        assert r.status_code == 201, r.text
        data = r.json()
        esc.productos.append(data["id"])
        assert data["tiene_variantes"] is False
        assert data["variantes"] == [], "con el switch apagado no se crean tallas"
        assert data["stock"] == 4, "el stock plano se respeta tal cual"
    finally:
        esc.limpiar()





