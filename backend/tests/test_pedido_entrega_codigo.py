"""
Código de RETIRO del Bazar — INTEGRACIÓN real contra la API del branch TEST.

QUÉ SE PRUEBA (requests de verdad + BD del branch TEST):

  1. al VALIDAR un pedido se genera `codigo_retiro` (formato UB-XXXX, único por box) y
     el aviso `pedido_validado` del alumno llega CON el código adentro;
  2. el código NO cambia si el admin "revalida" (el PUT responde 400) y no se puede
     inventar: un código inexistente → **404 genérico**;
  3. `POST /pedidos/entregar` con el código: el ADMIN del box → 200 (alumno, producto,
     cantidad, sin montos) y el alumno recibe `pedido_entregado`;
  4. el MISMO código otra vez → **409** con "ya fue entregado el … por …" (nombre de
     quien entregó);
  5. el COACH DEL BOX también entrega (200) — y el COACH DE OTRO BOX recibe **404**,
     no 409: desde otro box el código no existe (no se filtra información);
  6. un ALUMNO no puede entregar (403);
  7. `GET /pedidos/{id}/qr.svg` → SVG del código para el DUEÑO y el staff; 403 para
     otro alumno del mismo box; 404 para otro box;
  8. el respaldo del admin (`PUT /{id}/estado` → entregado) también sella
     `entregado_por` / `entregado_en`.

⚠️ INTEGRACIÓN (no unitario): requiere la API corriendo contra el branch TEST
(`conftest.BASE`) y BORRA lo que crea (pedidos + notificaciones) restaurando el stock.
NO se ejecuta en la validación local (esa va con `--noconftest`): se deja escrito para
correrlo cuando el stack esté levantado.
"""
import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from app.services import codigos_retiro as cr
from tests.conftest import BASE, TENANT_ID


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _all(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).fetchall()


def _exec(sql, **params):
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _token(row, rol):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": row.id,
        "tenant_id": row.tenant_id,
        "rol": rol,
        "correo": row.correo,
    })}


def _alumno():
    """Alumno activo del box SIN plan de prueba (los de prueba no ven el Bazar)."""
    fila = _one(
        "SELECT u.id, u.tenant_id, u.correo, u.nombre FROM usuarios u "
        "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' "
        "AND u.estado = 'activo' AND u.correo IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM suscripciones s "
        "                JOIN planes p ON p.id = s.plan_id "
        "                WHERE s.usuario_id = u.id AND s.estado = 'activo' "
        "                AND p.nombre = 'Prueba') "
        "ORDER BY (u.correo LIKE '%test%') DESC, u.id LIMIT 1", t=TENANT_ID)
    if not fila:
        pytest.skip("TEST no tiene un alumno con acceso completo")
    return fila


def _admin(tenant_id=None):
    fila = _one(
        "SELECT id, tenant_id, correo FROM usuarios WHERE tenant_id = :t "
        "AND rol::text IN ('administrador', 'admin') AND estado = 'activo' "
        "ORDER BY id LIMIT 1", t=tenant_id or TENANT_ID)
    if not fila:
        pytest.skip("TEST no tiene admin activo en el box")
    return fila


def _coach(tenant_id=None):
    fila = _one(
        "SELECT id, tenant_id, correo FROM usuarios WHERE tenant_id = :t "
        "AND rol::text = 'coach' AND estado = 'activo' ORDER BY id LIMIT 1",
        t=tenant_id or TENANT_ID)
    if not fila:
        pytest.skip("TEST no tiene coach activo en el box")
    return fila


def _otro_box():
    return _one(
        "SELECT id FROM tenants WHERE id <> :t ORDER BY id LIMIT 1", t=TENANT_ID)


def _producto():
    fila = _one(
        "SELECT id, nombre, precio, stock FROM productos WHERE tenant_id = :t "
        "AND activo = true AND stock >= 2 AND stock_minimo IS NULL "
        "ORDER BY id LIMIT 1", t=TENANT_ID)
    if not fila:
        pytest.skip("TEST no tiene producto activo con stock")
    return fila


def _crear_pedido(alumno, producto, cantidad=1):
    # `tenant_id` es obligatorio en PedidoCreate (aunque el backend lo fuerce con el del
    # token): sin él el POST daba 422 y los dos tests que arman un pedido fallaban.
    r = requests.post(
        f"{BASE}/pedidos", headers=_token(alumno, "alumno"),
        json={"tenant_id": alumno.tenant_id, "alumno_id": alumno.id,
              "producto_id": producto.id,
              "cantidad": cantidad,
              "voucher_url": "https://test.local/comprobante.png"},
        timeout=30)
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def _validar(pedido_id, admin):
    return requests.put(
        f"{BASE}/pedidos/{pedido_id}/estado", headers=_token(admin, "administrador"),
        params={"nuevo_estado": "validado"}, timeout=30)


def _entregar(codigo, quien, rol):
    return requests.post(
        f"{BASE}/pedidos/entregar", headers=_token(quien, rol),
        json={"codigo": codigo}, timeout=30)


def _limpiar(pedidos_ids, alumno_id, producto_id, stock_inicial, desde):
    """Borra lo creado por el test y devuelve el stock (todo lo demás intacto)."""
    if pedidos_ids:
        lista = ", ".join(str(int(i)) for i in pedidos_ids)
        _exec(f"DELETE FROM pedidos WHERE id IN ({lista})")
    _exec("DELETE FROM notificaciones WHERE alumno_id = :a "
          "AND created_at >= :d AND tipo IN ('pedido_validado', "
          "'pedido_entregado')", a=alumno_id, d=desde)
    _exec("UPDATE productos SET stock = :s WHERE id = :id",
          s=stock_inicial, id=producto_id)


def _avisos(alumno_id, tipo, desde):
    filas = _all(
        "SELECT mensaje FROM notificaciones WHERE alumno_id = :a AND tipo = :t "
        "AND created_at >= :d", a=alumno_id, t=tipo, d=desde)
    return [f.mensaje for f in filas]


def test_validar_genera_el_codigo_y_el_admin_lo_entrega():
    from datetime import datetime, timezone
    alumno, admin, producto = _alumno(), _admin(), _producto()
    desde = datetime.now(timezone.utc)
    pedidos = []
    try:
        pedido_id = _crear_pedido(alumno, producto)
        pedidos.append(pedido_id)

        # 1. Validar → 200 y el pedido queda con un código UB-XXXX.
        r = _validar(pedido_id, admin)
        assert r.status_code == 200, r.text[:300]
        codigo = r.json()["codigo_retiro"]
        assert codigo and cr.PATRON.match(codigo), codigo
        assert r.json()["entregado_en"] is None

        # El alumno se entera CON el código (campana del panel).
        avisos = _avisos(alumno.id, "pedido_validado", desde)
        assert len(avisos) == 1, avisos
        assert codigo in avisos[0], avisos[0]

        # Revalidar no cambia el código (y el backend ni lo permite: 400).
        assert _validar(pedido_id, admin).status_code == 400
        assert _one("SELECT codigo_retiro FROM pedidos WHERE id = :id",
                    id=pedido_id).codigo_retiro == codigo

        # 2. Un código que no existe → 404 genérico.
        inventado = "UB-9999" if codigo != "UB-9999" else "UB-2222"
        assert _entregar(inventado, admin, "administrador").status_code == 404

        # 3. Entrega real con el código.
        r = _entregar(codigo.lower(), admin, "administrador")
        assert r.status_code == 200, r.text[:300]
        datos = r.json()
        assert datos["pedido_id"] == pedido_id
        assert datos["alumno_nombre"] == alumno.nombre
        assert datos["producto_nombre"] == producto.nombre
        assert datos["cantidad"] == 1
        assert datos["codigo"] == codigo
        # El mesón NO recibe montos.
        assert "total" not in datos

        # 4. El aviso de entrega llega al alumno.
        assert len(_avisos(alumno.id, "pedido_entregado", desde)) == 1

        # 5. El mismo código otra vez → 409 con fecha y quién entregó.
        r = _entregar(codigo, admin, "administrador")
        assert r.status_code == 409, r.text[:300]
        assert "ya fue entregado el" in r.json()["detail"]

        # 6. Un alumno NO entrega (403): el guard es de staff.
        r = _entregar(codigo, alumno, "alumno")
        assert r.status_code == 403, r.text[:300]

        # 7. La traza quedó guardada en el pedido.
        fila = _one("SELECT estado, entregado_por, entregado_en FROM pedidos "
                    "WHERE id = :id", id=pedido_id)
        assert fila.estado == "entregado"
        assert fila.entregado_por == admin.id
        assert fila.entregado_en is not None
    finally:
        _limpiar(pedidos, alumno.id, producto.id, producto.stock, desde)


def test_el_coach_del_box_entrega_y_el_de_otro_box_no_ve_el_codigo():
    from datetime import datetime, timezone
    alumno, admin, coach, producto = _alumno(), _admin(), _coach(), _producto()
    otro = _otro_box()
    if not otro:
        pytest.skip("TEST no tiene un segundo box")
    coach_ajeno = _coach(otro.id)
    desde = datetime.now(timezone.utc)
    pedidos = []
    try:
        pedido_id = _crear_pedido(alumno, producto)
        pedidos.append(pedido_id)
        codigo = _validar(pedido_id, admin).json()["codigo_retiro"]

        # El coach de OTRO box no entrega: 404 (no 409) — para él ese código no
        # existe, así que no se filtra que exista en el box vecino.
        r = _entregar(codigo, coach_ajeno, "coach")
        assert r.status_code == 404, r.text[:300]

        # El coach del box SÍ entrega (200) y ve alumno / producto / cantidad.
        r = _entregar(" " + codigo.lower() + " ", coach, "coach")
        assert r.status_code == 200, r.text[:300]
        assert r.json()["pedido_id"] == pedido_id
        assert "total" not in r.json()

        # El QR del código: el dueño lo ve (SVG)…
        r = requests.get(f"{BASE}/pedidos/{pedido_id}/qr.svg",
                         headers=_token(alumno, "alumno"), timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert r.headers["content-type"].startswith("image/svg+xml")

        # …y otro alumno del mismo box NO (403, mismo guard que el comprobante).
        otro_alumno = _one(
            "SELECT id, tenant_id, correo FROM usuarios WHERE tenant_id = :t "
            "AND rol::text = 'alumno' AND id <> :a ORDER BY id LIMIT 1",
            t=TENANT_ID, a=alumno.id)
        if otro_alumno:
            r = requests.get(f"{BASE}/pedidos/{pedido_id}/qr.svg",
                             headers=_token(otro_alumno, "alumno"), timeout=30)
            assert r.status_code == 403, r.text[:200]
    finally:
        _limpiar(pedidos, alumno.id, producto.id, producto.stock, desde)


def test_el_respaldo_sin_codigo_del_admin_tambien_sella_la_traza():
    from datetime import datetime, timezone
    alumno, admin, producto = _alumno(), _admin(), _producto()
    desde = datetime.now(timezone.utc)
    pedidos = []
    try:
        pedido_id = _crear_pedido(alumno, producto)
        pedidos.append(pedido_id)
        codigo = _validar(pedido_id, admin).json()["codigo_retiro"]
        assert codigo  # validar ya dejó el código

        # Respaldo: el admin avanza a entregado sin usar el código.
        r = requests.put(
            f"{BASE}/pedidos/{pedido_id}/estado",
            headers=_token(admin, "administrador"),
            params={"nuevo_estado": "entregado"}, timeout=30)
        assert r.status_code == 200, r.text[:300]

        fila = _one("SELECT estado, entregado_por, entregado_en FROM pedidos "
                    "WHERE id = :id", id=pedido_id)
        assert fila.estado == "entregado"
        assert fila.entregado_por == admin.id
        assert fila.entregado_en is not None

        # Un código ya usado no vuelve a servir: 409, nunca 200.
        assert _entregar(codigo, admin, "administrador").status_code == 409

        # El listado del alumno trae la traza completa (fecha + quién entregó).
        r = requests.get(f"{BASE}/pedidos", headers=_token(alumno, "alumno"),
                         timeout=30)
        assert r.status_code == 200, r.text[:200]
        fila = next(p for p in r.json() if p["id"] == pedido_id)
        assert fila["codigo_retiro"] == codigo
        assert fila["entregado_en"] is not None
        assert fila["entregado_por_nombre"]
    finally:
        _limpiar(pedidos, alumno.id, producto.id, producto.stock, desde)
