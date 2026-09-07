"""Validación integrada FASE 2 (alerta de stock bajo) contra BD TEST.

Flujo verificado SIN enviar correos reales (los envíos se mockean):
1. Crear producto con stock=5 y stock_minimo=3.
2. Pedido de 3 unidades → stock queda en 2 (≤ umbral) → el flag
   alerta_stock_enviada debe pasar a True (ciclo avisado).
3. PUT productos (repone stock a 10 > umbral) → alerta_stock_enviada
   debe volver a False (ciclo rearmado).
4. Nuevo pedido de 9 unidades → stock 1 ≤ umbral → vuelve a True
   (segundo ciclo; la alerta se disparó de nuevo).
5. Limpieza: se eliminan pedidos y producto de prueba.
"""
import os
import sys

os.environ["ENVIRONMENT"] = "test"
sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings  # noqa: E402

if "polished-term" not in settings.DATABASE_URL:
    raise SystemExit("ABORT: no es TEST")

import app.services.email_service as ems  # noqa: E402

# ── Mocks: no enviar correos reales durante la validación ──
llamadas_alerta = []
llamadas_pedido = []


def _mock_alerta(producto_nombre, stock_actual, stock_minimo, tenant_id):
    llamadas_alerta.append(
        (producto_nombre, stock_actual, stock_minimo, tenant_id))
    print(f"   [MOCK send_alerta_stock_bajo] producto='{producto_nombre}' "
          f"stock={stock_actual} umbral={stock_minimo} tenant={tenant_id}")
    return True


def _mock_confirmacion(*a, **k):
    llamadas_pedido.append((a, k))
    return True


ems.send_alerta_stock_bajo = _mock_alerta
ems.send_confirmacion_pedido = _mock_confirmacion

from app.api.v1.pedidos import crear_pedido  # noqa: E402
from app.api.v1.productos import actualizar_producto  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.pedido import Pedido  # noqa: E402
from app.models.producto import Producto  # noqa: E402
from app.models.usuario import Usuario, RolUsuario  # noqa: E402
from app.schemas.pedido import PedidoCreate  # noqa: E402
from app.schemas.producto import ProductoUpdate  # noqa: E402

TENANT = 1
db = SessionLocal()
pedidos_creados = []
producto_id = None


try:
    # ── Admin y alumno de prueba del tenant ──
    admin = db.query(Usuario).filter(
        Usuario.tenant_id == TENANT,
        Usuario.rol == RolUsuario.administrador,
        Usuario.activo == True,
    ).order_by(Usuario.id).first()
    alumno = db.query(Usuario).filter(
        Usuario.tenant_id == TENANT,
        Usuario.rol == RolUsuario.alumno,
        Usuario.activo == True,
    ).order_by(Usuario.id).first()
    if not admin or not alumno:
        raise SystemExit("ABORT: no hay admin/alumno en tenant 1")
    current_user = {
        "tenant_id": TENANT, "usuario_id": admin.id, "rol": "administrador",
        "nombre": admin.nombre, "correo": admin.correo,
    }
    print(f"admin id={admin.id} correo={admin.correo} | alumno id={alumno.id}")

    # ── 1) Producto con umbral ──
    producto = Producto(tenant_id=TENANT, nombre="TEST Alerta Stock Fase2",
                        descripcion="producto temporal de validacion",
                        precio=1000.0, stock=5, stock_minimo=3, activo=True)
    db.add(producto)
    db.commit()
    db.refresh(producto)
    producto_id = producto.id
    print(f"1) Producto creado id={producto_id} stock={producto.stock} "
          f"stock_minimo={producto.stock_minimo} flag={producto.alerta_stock_enviada}")

    # ── 2) Pedido de 3 → stock 2 ≤ 3 → dispara alerta ──
    pedido = PedidoCreate(producto_id=producto_id, cantidad=3,
                          alumno_id=alumno.id, tenant_id=TENANT,
                          estado="pendiente")
    db_pedido = crear_pedido(pedido, db, current_user)
    pedidos_creados.append(db_pedido.id)
    db.refresh(producto)
    print(f"2) Tras pedido: stock={producto.stock} flag={producto.alerta_stock_enviada}")
    assert producto.stock == 2, f"stock esperado 2, real {producto.stock}"
    assert producto.alerta_stock_enviada is True, "flag debe ser True tras cruzar umbral"
    assert len(llamadas_alerta) == 1, f"alerta deberia dispararse 1 vez, fue {len(llamadas_alerta)}"
    assert llamadas_alerta[0][1] == 2 and llamadas_alerta[0][2] == 3

    # ── 3) PUT: reponer stock a 10 (> umbral) → flag a False ──
    actualizar_producto(producto_id, ProductoUpdate(stock=10),
                        None, db,
                        {"tenant_id": TENANT, "usuario_id": admin.id,
                         "rol": "administrador", "nombre": admin.nombre,
                         "correo": admin.correo})
    db.refresh(producto)
    print(f"3) Tras PUT stock=10: stock={producto.stock} flag={producto.alerta_stock_enviada}")
    assert producto.alerta_stock_enviada is False, "flag debe resetearse a False al reponer"

    # ── 4) Nuevo pedido de 9 → stock 1 ≤ umbral → dispara de nuevo ──
    pedido2 = PedidoCreate(producto_id=producto_id, cantidad=9,
                           alumno_id=alumno.id, tenant_id=TENANT,
                           estado="pendiente")
    db_pedido2 = crear_pedido(pedido2, db, current_user)
    pedidos_creados.append(db_pedido2.id)
    db.refresh(producto)
    print(f"4) Tras 2º pedido: stock={producto.stock} flag={producto.alerta_stock_enviada}")
    assert producto.stock == 1, f"stock esperado 1, real {producto.stock}"
    assert producto.alerta_stock_enviada is True, "flag debe volver a True en 2º ciclo"
    assert len(llamadas_alerta) == 2, f"alerta deberia dispararse 2 veces, fue {len(llamadas_alerta)}"

    print("\nRESULTADO: OK - Fase 2 validada (umbral, disparo, dedupe por ciclo, reset en PUT)")
    sys.exit(0)
finally:
    # ── Limpieza ──
    try:
        for pid in pedidos_creados:
            db.query(Pedido).filter(Pedido.id == pid).delete()
        if producto_id:
            db.query(Producto).filter(Producto.id == producto_id).delete()
        db.commit()
        print("Limpieza OK: pedidos y producto de prueba eliminados.")
    except Exception as e:
        db.rollback()
        print("Limpieza con avisos:", e)
    db.close()
