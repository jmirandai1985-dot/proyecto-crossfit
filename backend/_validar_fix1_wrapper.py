"""Validación FIX 1: el wrapper de errores de BD en pedidos.py devuelve 503.

Unit test: llama a crear_pedido con un db fake cuyo execute() lanza
OperationalError (simula deadlock/timeout) y verifica que el endpoint
devuelve HTTPException 503 "Alta demanda" y hace rollback.
No toca BD real.
"""
import sys
import sqlalchemy.exc
from fastapi import HTTPException
from app.api.v1.pedidos import crear_pedido
from app.schemas.pedido import PedidoCreate


class FakeProducto:
    id = 999
    tenant_id = 1
    stock = 10
    precio = 1000.0


class FakeQuery:
    def filter(self, *a, **k):
        return self

    def first(self):
        return FakeProducto()


class FakeDB:
    def __init__(self):
        self.rolled = False

    def query(self, *a, **k):
        return FakeQuery()

    def execute(self, *a, **k):
        raise sqlalchemy.exc.OperationalError(
            "UPDATE productos", {}, Exception("deadlock detected"))

    def rollback(self):
        self.rolled = True


def main():
    data = PedidoCreate(producto_id=999, cantidad=1, alumno_id=5, tenant_id=1)
    current_user = {"tenant_id": 1, "usuario_id": 5, "rol": "alumno"}
    db = FakeDB()
    try:
        crear_pedido(data, db, current_user)
        print("FAIL: no lanzó HTTPException")
        sys.exit(1)
    except HTTPException as e:
        ok = e.status_code == 503 and "Alta demanda" in str(e.detail) and db.rolled
        print(f"HTTPException {e.status_code}: {e.detail} | rollback={db.rolled}")
        print(f"RESULTADO: {'PASS - wrapper 503 funciona' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)
    except Exception as e:
        print(f"FAIL: excepción inesperada {type(e).__name__}: {str(e)[:100]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
