"""
Bazar -> campana: POST /pedidos avisa a los ADMINS del box y PUT /{id}/estado
avisa al ALUMNO dueño (tabla `notificaciones`, la de la campana; sin correo).

QUÉ SE PRUEBA (integraciones reales contra la API del branch TEST):

  * crear un pedido -> 1 fila `pedido_nuevo` por cada admin ACTIVO del tenant, y
    0 filas para los admins de OTRO box (frontera de tenant);
  * pendiente -> validado -> 1 fila `pedido_validado` en el alumno DUEÑO y 0 en
    otro alumno del mismo box (el aviso es del dueño, no del box);
  * validado -> entregado -> 1 fila `pedido_entregado` en el alumno dueño;
  * el `mensaje` cita el producto y la cantidad.

⚠️ INTEGRACIÓN (no unitario): requiere la API corriendo contra el branch TEST
(conftest.BASE). Crea un pedido REAL (descuenta stock) y RESTAURA todo al
terminar: borra las notificaciones y el pedido creados y devuelve el stock.
NO se ejecuta en la validación local (que va con --noconftest): se dejó escrito
para correrlo contra la API cuando el stack esté levantado.
"""
from datetime import datetime, timezone

import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
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


def _alumno_con_acceso():
    """Alumno ACTIVO del box que NO está en prueba (require_full_access)."""
    return _one(
        "SELECT u.id, u.tenant_id, u.correo, u.nombre FROM usuarios u "
        "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' "
        "AND u.estado = 'activo' AND u.correo IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM suscripciones s "
        "                JOIN planes p ON p.id = s.plan_id "
        "                WHERE s.usuario_id = u.id AND s.estado = 'activo' "
        "                AND p.nombre = 'Prueba') "
        "ORDER BY (u.correo LIKE '%test%') DESC, u.id LIMIT 1",
        t=TENANT_ID)


def _otro_alumno(alumno_id):
    return _one(
        "SELECT id FROM usuarios WHERE tenant_id = :t AND id <> :a "
        "AND rol::text = 'alumno' ORDER BY id LIMIT 1",
        t=TENANT_ID, a=alumno_id)


def _admins(tenant_id):
    return _all(
        "SELECT id FROM usuarios WHERE tenant_id = :t "
        "AND rol::text = 'administrador' AND estado = 'activo' ORDER BY id",
        t=tenant_id)


def _producto():
    """Producto activo con stock de sobra y SIN umbral (no dispara alerta)."""
    return _one(
        "SELECT id, nombre, precio, stock FROM productos WHERE tenant_id = :t "
        "AND activo = true AND stock >= 2 AND stock_minimo IS NULL "
        "ORDER BY id LIMIT 1", t=TENANT_ID)


def _notifs(tipo, alumno_ids, desde):
    """Avisos de ese tipo creados DESPUÉS de `desde` para esos alumnos."""
    if not alumno_ids:
        return []
    ids_sql = ", ".join(str(int(i)) for i in alumno_ids)
    return _all(
        f"SELECT alumno_id, mensaje FROM notificaciones WHERE tipo = :tipo "
        f"AND created_at >= :desde AND alumno_id IN ({ids_sql})",
        tipo=tipo, desde=desde)


def test_crear_pedido_y_cambiar_estado_avisan_en_la_campana():
    alumno = _alumno_con_acceso()
    if alumno is None:
        pytest.skip("TEST no tiene un alumno activo fuera del plan de prueba")
    admins = _admins(TENANT_ID)
    if not admins:
        pytest.skip("TEST no tiene administradores activos en el box 1")
    producto = _producto()
    if producto is None:
        pytest.skip("TEST no tiene un producto activo con stock >= 2")

    otro = _otro_alumno(alumno.id)
    headers_alumno = _token(alumno, "alumno")
    headers_admin = _token(admins[0], "administrador")
    ids_admins = [a.id for a in admins]
    stock_inicial = producto.stock
    inicio = datetime.now(timezone.utc)
    pedido_id = None
    try:
        # ── 1. El alumno crea el pedido (compra para sí mismo) ──
        r = requests.post(f"{BASE}/pedidos", headers=headers_alumno, json={
            "alumno_id": alumno.id,
            "producto_id": producto.id,
            "cantidad": 2,
            "tenant_id": TENANT_ID,
            "voucher_url": "https://example.test/comprobante.png",
        }, timeout=30)
        assert r.status_code in (200, 201), r.text[:300]
        pedido_id = r.json()["id"]

        # 1 aviso 'pedido_nuevo' por admin ACTIVO del box, con el pedido adentro
        avisos = _notifs("pedido_nuevo", ids_admins, inicio)
        assert len(avisos) == len(admins), avisos
        assert {a.alumno_id for a in avisos} == set(ids_admins)
        for aviso in avisos:
            assert producto.nombre in aviso.mensaje, aviso.mensaje
            assert "x2" in aviso.mensaje, aviso.mensaje

        # Y nadie de OTRO box (si TEST tiene un segundo box)
        otros_admins = [a.id for a in _all(
            "SELECT id FROM usuarios WHERE tenant_id <> :t "
            "AND rol::text = 'administrador' AND estado = 'activo' LIMIT 20",
            t=TENANT_ID)]
        if otros_admins:
            assert _notifs("pedido_nuevo", otros_admins, inicio) == []

        # ── 2. El admin valida: aviso al alumno DUEÑO (y a nadie más) ──
        r = requests.put(f"{BASE}/pedidos/{pedido_id}/estado",
                         headers=headers_admin,
                         params={"nuevo_estado": "validado"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        avisos = _notifs("pedido_validado", [alumno.id], inicio)
        assert len(avisos) == 1, avisos
        assert "fue validado" in avisos[0].mensaje, avisos[0].mensaje
        if otro is not None:
            assert _notifs("pedido_validado", [otro.id], inicio) == []

        # ── 3. El admin entrega ──
        r = requests.put(f"{BASE}/pedidos/{pedido_id}/estado",
                         headers=headers_admin,
                         params={"nuevo_estado": "entregado"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        avisos = _notifs("pedido_entregado", [alumno.id], inicio)
        assert len(avisos) == 1, avisos
        assert "fue entregado" in avisos[0].mensaje, avisos[0].mensaje
    finally:
        # ── Limpieza: avisos de esta corrida, pedido y stock (como estaba) ──
        ids_afectados = [alumno.id] + ids_admins
        ids_sql = ", ".join(str(int(i)) for i in ids_afectados)
        _exec(
            "DELETE FROM notificaciones WHERE created_at >= :desde AND tipo IN "
            "('pedido_nuevo', 'pedido_validado', 'pedido_entregado') "
            f"AND alumno_id IN ({ids_sql})", desde=inicio)
        if pedido_id is not None:
            _exec("DELETE FROM pedidos WHERE id = :id", id=pedido_id)
            _exec("UPDATE productos SET stock = :s WHERE id = :id",
                  s=stock_inicial, id=producto.id)

