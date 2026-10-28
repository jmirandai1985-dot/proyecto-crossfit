"""Job nocturno de repaso del nivel persistido (D3)

QUÉ HACE
--------
Recorre los alumnos del box y recalcula los que tienen la fila de nivel vencida:
`nivel_calculado_en` NULL, `nivel_version` distinta de `nivel_service.NIVEL_VERSION` o más de
24 h sin recalcular. Escribe con `nivel_service.recalcular_nivel` —la MISMA función que usan el
POST/PUT/DELETE de RM y los cambios de peso/género—, así que no puede aparecer un nivel distinto.

POR QUÉ HACE FALTA SI YA HAY AUTO-SANACIÓN AL LEER
--------------------------------------------------
`calcular_nivel_general` / `calcular_niveles_lote` refrescan la fila cuando alguien la pide.
Este job cubre lo que NADIE pide: alumnos sin visitas, filas que quedaron con una versión vieja
de la regla y el backfill inicial de la migración `060` (todas las filas nacen en NULL).

USO
---
    cd backend
    py -3.12 -m maintenance.recalcular_niveles            # dry-run (no escribe)
    py -3.12 -m maintenance.recalcular_niveles --aplicar   # escribe
    py -3.12 -m maintenance.recalcular_niveles --aplicar --alumno-id 123   # uno solo

Es idempotente: correrlo dos veces seguidas deja `recalculados=0` la segunda vez. Pensado para
un Cron Job nocturno (~03:10 CLT) con la imagen de la APP (importa `app.*`, igual que
`maintenance/marcar_plan_vencido.py`; NO corre en `Dockerfile.cron`, que no copia `app/`).
"""
import argparse
import logging
import sys
from pathlib import Path

# Permite `python -m maintenance.recalcular_niveles` desde `backend/` y desde la raíz.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import SessionLocal                      # noqa: E402
from app.models.usuario import RolUsuario, Usuario            # noqa: E402
from app.services.nivel_service import (                      # noqa: E402
    NIVEL_VERSION, nivel_esta_vigente, recalcular_nivel,
)

log = logging.getLogger("recalcular_niveles")

# Lote de lectura: el padrón real son ~410 alumnos; 500 deja el job en una sola página sin
# cargar toda la tabla en memoria si el box crece.
BATCH = 500


def _alumnos(db, alumno_id=None):
    q = db.query(Usuario).filter(Usuario.rol == RolUsuario.alumno)
    if alumno_id:
        q = q.filter(Usuario.id == alumno_id)
    return q.order_by(Usuario.id).yield_per(BATCH)


def run(dry_run=True, alumno_id=None) -> dict:
    """Recalcula (o cuenta, en dry-run) las filas vencidas. Devuelve el resumen del run."""
    db = SessionLocal()
    revisados = recalculados = vigentes = 0
    try:
        for usuario in _alumnos(db, alumno_id):
            revisados += 1
            if nivel_esta_vigente(usuario):
                vigentes += 1
                continue
            if not dry_run:
                recalcular_nivel(db, usuario.id, usuario.tenant_id)
            recalculados += 1
    finally:
        db.close()
    return {
        "version": NIVEL_VERSION,
        "dry_run": dry_run,
        "revisados": revisados,
        "vigentes": vigentes,
        "recalculados": recalculados,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Recalcula el nivel persistido de los alumnos (D3).")
    parser.add_argument("--aplicar", action="store_true",
                        help="escribe los cambios (sin esto es dry-run)")
    parser.add_argument("--alumno-id", type=int, default=None,
                        help="recalcula un solo alumno (pruebas)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    resumen = run(dry_run=not args.aplicar, alumno_id=args.alumno_id)
    print(
        "nivel_version={version} dry_run={dry_run} revisados={revisados} "
        "vigentes={vigentes} recalculados={recalculados}".format(**resumen)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
