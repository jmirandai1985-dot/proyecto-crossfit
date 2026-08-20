"""
Verifica los invariantes del Escenario D DESPUÉS de correr k6:
  1. Stock NUNCA negativo: stock final == 0 (vendidas exactamente las 30).
  2. EXACTAMENTE stock_inicial pedidos creados (sin overbook/oversell).
  3. Suma de cantidades == stock vendido == 30.
  4. Total de cada pedido correcto (precio × cantidad) y un pedido por alumno.
Solo lectura. Lee k6-tests/load_config.json.
"""
import json
import os
import sys
from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402

K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))
with open(os.path.join(K6_DIR, "load_config.json"), encoding="utf-8") as f:
    cfg = json.load(f)
TENANT = cfg["tenant_id"]
PRODUCTO = cfg["product_id"]
STOCK_INI = cfg["stock_inicial"]


def main():
    ok = True
    with engine.connect() as conn:
        stock, precio = conn.execute(sa_text(
            "SELECT stock, precio FROM productos WHERE id=:p"),
            {"p": PRODUCTO}).fetchone()
        n_pedidos = conn.execute(sa_text(
            "SELECT COUNT(*) FROM pedidos WHERE producto_id=:p AND tenant_id=:t"),
            {"p": PRODUCTO, "t": TENANT}).scalar()
        sum_cant = conn.execute(sa_text(
            "SELECT COALESCE(SUM(cantidad),0) FROM pedidos WHERE producto_id=:p AND tenant_id=:t"),
            {"p": PRODUCTO, "t": TENANT}).scalar()
        por_alumno = conn.execute(sa_text(
            "SELECT alumno_id, COUNT(*) FROM pedidos WHERE producto_id=:p AND tenant_id=:t "
            "GROUP BY alumno_id HAVING COUNT(*) > 1"),
            {"p": PRODUCTO, "t": TENANT}).fetchall()
        totales = conn.execute(sa_text(
            "SELECT COUNT(*) FROM pedidos WHERE producto_id=:p AND tenant_id=:t "
            "AND total != cantidad * :precio"),
            {"p": PRODUCTO, "t": TENANT, "precio": float(precio)}).scalar()
        estados = set(r[0] for r in conn.execute(sa_text(
            "SELECT DISTINCT estado FROM pedidos WHERE producto_id=:p AND tenant_id=:t"),
            {"p": PRODUCTO, "t": TENANT}).fetchall())

    r1 = stock == 0 and stock >= 0
    ok &= r1
    print(f"[1] stock final: {stock} (nunca negativo): {'PASS' if r1 else 'FAIL'}")

    r2 = n_pedidos == STOCK_INI
    ok &= r2
    print(f"[2] pedidos creados: {n_pedidos} (esperados {STOCK_INI}): "
          f"{'PASS' if r2 else 'FAIL'}")

    r3 = sum_cant == STOCK_INI
    ok &= r3
    print(f"[3] unidades vendidas: {sum_cant} (esperadas {STOCK_INI}): "
          f"{'PASS' if r3 else 'FAIL'}")

    r4 = len(por_alumno) == 0 and totales == 0
    ok &= r4
    print(f"[4] 1 pedido por alumno y total correcto: "
          f"{'PASS' if r4 else 'FAIL dupes=' + str(por_alumno[:3]) + ' totales_mal=' + str(totales)}")

    r5 = estados <= {"pendiente"}
    ok &= r5
    print(f"[5] estados de pedido (esperado solo 'pendiente'): {estados}: "
          f"{'PASS' if r5 else 'FAIL'}")

    print(f"\nRESULTADO: {'OK - Escenario D verificado' if ok else 'FALLÓ'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
