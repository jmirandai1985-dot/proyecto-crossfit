"""Borrado seguro de productos de carga K6 del Bazar.

REGLA DE SELECCIÓN (nada más):
  * nombre que EMPIEZA con "TEST CARGA K6"
  * `activo = false`
  * excluye explícitamente "Poleron estampado", "poleras" y "poleron lindo".

Por defecto es SÓLO SIMULACIÓN: imprime cantidad, IDs/nombres y cuántos quedan
excluidos. No borra nada. El borrado real exige `--aplicar` y que el conteo
coincida exactamente con `--esperados N`; si no coincide, aborta antes de tocar
la base.

Uso (desde backend/):
    $env:ENVIRONMENT="test"
    python scripts/borrar_bazar_k6.py --esperados 8
    python scripts/borrar_bazar_k6.py --esperados 8 --aplicar
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PREFIJO = "TEST CARGA K6"
NOMBRES_EXCLUIDOS = {"poleron estampado", "poleras", "poleron lindo"}


def _normalizar(nombre) -> str:
    return " ".join(str(nombre or "").strip().split()).lower()


def es_producto_k6_borrable(nombre, activo) -> bool:
    """True sólo para un K6 inactivo que no esté en la lista de exclusiones."""
    limpio = _normalizar(nombre)
    if not limpio.startswith(PREFIJO.lower()):
        return False
    # "TEST CARGA K6X" NO es del lote K6: exigimos un límite después del prefijo.
    resto = limpio[len(PREFIJO):]
    if resto and resto[0].isalnum():
        return False
    if limpio in NOMBRES_EXCLUIDOS:
        return False
    return not bool(activo)


def seleccionar_borrables(productos) -> list:
    """Filtra en memoria (el mismo criterio que usa el script contra la BD)."""
    return [p for p in (productos or [])
            if es_producto_k6_borrable(p.get("nombre"), p.get("activo"))]


def _fila(producto) -> str:
    return f"  id={producto.get('id')}  {producto.get('nombre')}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aplicar", action="store_true",
                        help="Borra de verdad (sin esto sólo simula).")
    parser.add_argument("--esperados", type=int, required=True,
                        help="Conteo exacto que debe tener la selección.")
    args = parser.parse_args(argv)

    if os.environ.get("ENVIRONMENT") != "test":
        print("ERROR: este script sólo corre con ENVIRONMENT=test.")
        return 2

    backend = Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    from app.db.database import SessionLocal
    from app.models.producto import Producto

    db = SessionLocal()
    try:
        # Candidatos amplios (prefijo + inactivos); el filtro fino se aplica en
        # memoria para que el dry-run y el borrado usen EXACTAMENTE la misma regla.
        candidatos = db.query(Producto).filter(
            Producto.nombre.ilike(f"{PREFIJO}%"),
            Producto.activo.is_(False),
        ).order_by(Producto.id).all()
        filas = [{"id": p.id, "nombre": p.nombre, "activo": p.activo}
                 for p in candidatos]
        seleccion = seleccionar_borrables(filas)
        excluidos = [f for f in filas
                     if not es_producto_k6_borrable(f.get("nombre"), f.get("activo"))]

        print(f"Productos K6 inactivos encontrados: {len(seleccion)}")
        for fila in seleccion:
            print(_fila(fila))
        print(f"Excluidos por regla: {len(excluidos)}")
        for fila in excluidos:
            print(_fila(fila))

        if len(seleccion) != args.esperados:
            print(f"ABORTADO: se esperaban {args.esperados} y hay "
                  f"{len(seleccion)}. No se borró nada.")
            return 1
        if not args.aplicar:
            print("SIMULACIÓN: no se borró nada. Usa --aplicar para ejecutar.")
            return 0

        ids = [f["id"] for f in seleccion]
        try:
            db.query(Producto).filter(Producto.id.in_(ids)).delete(
                synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
            raise
        print(f"Borrados {len(ids)} productos K6 en una transacción.")
        return 0
    except Exception as exc:  # noqa: BLE001 - el script debe mostrar el motivo
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
