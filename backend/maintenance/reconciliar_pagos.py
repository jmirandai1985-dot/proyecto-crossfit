"""Reconciliación de pagos online (Mercado Pago): webhooks perdidos y expirados.

POR QUÉ EXISTE
--------------
Los webhooks se pierden (deploy justo cuando MP notificaba, timeout, un 503
nuestro). Si el único camino para aplicar un pago fuera el webhook, un alumno que
pagó podría quedarse sin plan y nadie se enteraría. Este job hace dos cosas:

1. **Expira** los pagos que nunca se cobraron (`services/pagos.expirar_pendientes`):
   a los **30 min** un pedido del Bazar se rechaza y su stock vuelve; a las
   **24 h** una solicitud de membresía sale de la cola de pendientes. Sin esto,
   un pedido abandonado deja stock bloqueado para siempre.
2. **Reconcilia** los pagos `pendiente`/`en_proceso` con más de 15 min: le
   pregunta a MP por `external_reference` y, si hay un pago real, lo aplica con
   la MISMA función del webhook (`services/pagos.aplicar_pago`). El evento
   sintético se registra en `pagos_eventos` (`notificacion_id = reconciliacion-<id>`),
   así que un webhook que llegue tarde después no duplica nada.

SEGURIDAD
---------
Corre con `--dry-run` por DEFAULT: sólo informa lo que haría. Para aplicar de
verdad hay que pasar `--aplicar`. Es dinero: el default nunca escribe.

Uso:
    py -3.12 -m maintenance.reconciliar_pagos            (informe)
    py -3.12 -m maintenance.reconciliar_pagos --aplicar  (aplica)
"""
import argparse
import logging
import sys
from datetime import timedelta

from sqlalchemy import or_

from app.db.database import SessionLocal
from app.models.pago import Pago
from app.services import mercadopago_cliente as mp
from app.services import pagos as servicio_pagos
from app.utils.santiago import ahora_santiago

logger = logging.getLogger(__name__)

# Un pago recién creado puede tardar en recibir su webhook: se espera antes de
# consultar a MP (evita duplicar trabajo con el webhook que viene en camino).
MINUTOS_ANTES_DE_RECONCILIAR = 15
LIMITE_POR_CORRIDA = 50


def expirar(db, aplicar: bool) -> dict:
    """Cierra los pagos vencidos (o sólo los cuenta, en dry-run)."""
    ahora = ahora_santiago()
    abiertos = db.query(Pago).filter(
        Pago.estado.in_(("pendiente", "en_proceso"))).all()
    candidatos = {"bazar": 0, "membresia": 0}
    for pago in abiertos:
        if pago.created_at is None:
            continue
        if (pago.concepto == "bazar"
                and pago.created_at <= ahora - timedelta(minutes=30)):
            candidatos["bazar"] += 1
        elif (pago.concepto == "membresia"
                and pago.created_at <= ahora - timedelta(hours=24)):
            candidatos["membresia"] += 1

    if not aplicar:
        return {"candidatos": candidatos, "resultado": None}
    resultado = servicio_pagos.expirar_pendientes(db)
    return {"candidatos": candidatos, "resultado": resultado}


def reconciliar(db, aplicar: bool) -> dict:
    """Busca en MP los pagos que nunca recibieron webhook."""
    corte = ahora_santiago() - timedelta(minutes=MINUTOS_ANTES_DE_RECONCILIAR)
    pendientes = db.query(Pago).filter(
        or_(Pago.estado == "pendiente", Pago.estado == "en_proceso"),
        Pago.created_at <= corte,
    ).order_by(Pago.created_at).limit(LIMITE_POR_CORRIDA).all()

    informe = {"revisados": len(pendientes), "encontrados": 0,
               "aplicados": 0, "sin_pago": 0, "errores": 0}
    for pago in pendientes:
        try:
            resultados = mp.buscar_pagos(pago.external_reference)
        except mp.ErrorMercadoPago as error:
            logger.warning("Reconciliación: no se pudo consultar el pago %s: %s",
                           pago.id, error)
            informe["errores"] += 1
            continue
        # Se prefiere el pago aprobado; si no hay, el último que MP reporte.
        aprobados = [r for r in resultados if r.get("status") == "approved"]
        elegido = (aprobados or resultados or [None])[0]
        if not elegido:
            informe["sin_pago"] += 1
            continue
        informe["encontrados"] += 1
        if not aplicar:
            continue

        evento = servicio_pagos.registrar_evento(
            db,
            notificacion_id=f"reconciliacion-{elegido.get('id')}",
            tipo="payment", recurso_id=str(elegido.get("id")),
            firma_valida=False,
        )
        if evento is None:      # ya reconciliado o ya llegó el webhook
            continue
        try:
            servicio_pagos.procesar_notificacion(db, evento, elegido)
            informe["aplicados"] += 1
        except Exception as error:  # noqa: BLE001 - una fila no frena el resto
            db.rollback()
            logger.error("Reconciliación: fallo al aplicar el pago %s: %s",
                         pago.id, error)
            informe["errores"] += 1
    return informe


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aplicar", action="store_true",
                        help="escribe los cambios (por defecto sólo informa)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    aplicar = bool(args.aplicar)
    logger.info("Reconciliación de pagos MP — modo %s",
                "APLICAR" if aplicar else "DRY-RUN")

    db = SessionLocal()
    try:
        expirados = expirar(db, aplicar)
        informe = reconciliar(db, aplicar)
        logger.info("Vencidos: %s", expirados)
        logger.info("Reconciliación: %s", informe)
        return 0
    except Exception as error:  # pragma: no cover - proceso operativo
        db.rollback()
        logger.exception("Reconciliación abortada: %s", error)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
