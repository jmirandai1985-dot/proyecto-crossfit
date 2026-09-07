"""Validación FASE 3: contrato de productos con stock_minimo (POST/PUT) contra TEST.

Replica exactamente lo que envía ModalProducto.jsx pero invocando las funciones
del router directamente (TestClient no disponible: starlette 0.35 + httpx 0.28):
- POST crear_producto(nombre, precio, stock, stock_minimo, activo, ...) → entero.
- PUT actualizar_producto(id, ProductoUpdate(stock_minimo=...)) → entero o null.
Al final borra físicamente el producto de prueba.
"""
import os
import sys
import asyncio

os.environ["ENVIRONMENT"] = "test"
sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings  # noqa: E402

if "polished-term" not in settings.DATABASE_URL:
    raise SystemExit("ABORT: no es TEST")

from app.api.v1.productos import crear_producto, actualizar_producto  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.producto import Producto  # noqa: E402
from app.schemas.producto import ProductoUpdate  # noqa: E402

ADMIN = {"usuario_id": 1, "tenant_id": 1, "nombre": "Admin Test",
         "correo": "admin@test.cl", "rol": "administrador", "activo": True}

db = SessionLocal()
producto_id = None

try:
    # ── 1) POST con stock_minimo (como lo manda el frontend en FormData) ──
    producto = asyncio.run(crear_producto(
        nombre="TEST Fase3 Stock Min",
        precio=15000.0,
        stock=10,
        tenant_id=None,
        descripcion="producto temporal",
        stock_minimo=3,
        activo=True,
        file=None,
        db=db,
        current_user=ADMIN,
    ))
    producto_id = producto.id
    print(f"1) POST crear_producto: id={producto_id} stock_minimo={producto.stock_minimo}")
    assert producto.stock_minimo == 3, "POST debe guardar stock_minimo=3"

    # ── 2) GET: el campo se devuelve en la respuesta ──
    db.refresh(producto)
    assert producto.stock_minimo == 3
    print(f"2) GET (refresh) OK: stock_minimo={producto.stock_minimo}")

    # ── 3) PUT con stock_minimo = 8 (JSON, edición normal) ──
    actualizar_producto(producto_id, ProductoUpdate(stock_minimo=8), None, db, ADMIN)
    db.refresh(producto)
    print(f"3) PUT stock_minimo=8: {producto.stock_minimo}")
    assert producto.stock_minimo == 8

    # ── 4) PUT con stock_minimo = null (frontend envía null cuando vacío) ──
    actualizar_producto(producto_id, ProductoUpdate(stock_minimo=None), None, db, ADMIN)
    db.refresh(producto)
    print(f"4) PUT stock_minimo=null: {producto.stock_minimo}")
    assert producto.stock_minimo is None

    print("\nRESULTADO: OK - contrato Fase 3 validado (POST y PUT con stock_minimo entero/null)")
    sys.exit(0)
finally:
    if producto_id:
        try:
            db.query(Producto).filter(Producto.id == producto_id).delete()
            db.commit()
            print("Limpieza OK: producto de prueba eliminado.")
        except Exception as e:
            db.rollback()
            print("Limpieza con avisos:", e)
    db.close()

