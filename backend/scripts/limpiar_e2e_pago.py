"""Limpieza de estado del alumno E2E de pagos (SÓLO rama TEST).

POR QUÉ EXISTE
--------------
El spec `frontend/e2e/tests/pago-membresia.spec.js` necesita un alumno sin
solicitudes `pending` (el guard "Ya tienes una solicitud pendiente" bloquearía
todo) y sin plan pago vigente (si no, la compra quedaría `en_cola` en vez de
activarse). Los usuarios de carga k6 YA vienen con esas dos cosas sembradas, y
si una corrida anterior del test se cortó a mitad puede quedar un pago
`iniciado` invisible que bloquea los 5 minutos del guard.

Esto NO es un mock: es limpieza de datos de TEST, igual que la que hace
`k6-tests/_seed_load_test.py` antes de sembrar. No borra historia: cierra las
filas con el mismo estado que usaría la app.

SEGURIDAD
---------
* Aborta si `ENVIRONMENT != "test"` o si la URL de la base no es la rama TEST
  (`is_test_db_url`), la misma barrera que ya usan los scripts de test.
* Sólo toca el correo indicado (por defecto uno de los usuarios de carga
  `@load.test`); con `--permitir-cualquier-correo` se puede usar otro de TEST.

Uso:
    cd backend
    $env:ENVIRONMENT="test"
    py -3.12 scripts/limpiar_e2e_pago.py --alumno-email carga_k6_alumno0020@load.test
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import text  # noqa: E402

from app.core.config import is_test_db_url, settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402

COMENTARIO_E2E = "E2E: limpieza previa del estado de pago"
COM_TENCION = "E2E: intento de pago abandonado antes de la limpieza"


def _validar_entorno() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() != "test":
        raise SystemExit(
            "ABORTADO: ENVIRONMENT tiene que ser 'test' "
            f"(vale {os.getenv('ENVIRONMENT')!r}).")
    if not is_test_db_url(settings.DATABASE_URL):
        raise SystemExit(
            "ABORTADO: DATABASE_URL no es la rama TEST de Neon "
            f"({settings.DATABASE_URL.split('@')[-1][:60]}).")


def limpiar(alumno_email: str, permitir_cualquier_correo: bool) -> dict:
    email = alumno_email.strip().lower()
    if not email:
        raise SystemExit("Falta --alumno-email")
    if not permitir_cualquier_correo and not email.endswith("@load.test"):
        raise SystemExit(
            "ABORTADO: por seguridad sólo se limpian usuarios @load.test. "
            "Usá --permitir-cualquier-correo si sabés lo que hacés.")

    db = SessionLocal()
    try:
        usuario = db.execute(text(
            "SELECT id FROM usuarios WHERE lower(correo) = :c "
            "AND tenant_id = 1 AND rol::text = 'alumno'"), {"c": email}).first()
        if usuario is None:
            raise SystemExit(f"No existe el alumno {email} en la rama TEST.")

        uid = int(usuario.id)

        # 1. Intentos de pago abiertos: se cierran como la app los cerraría.
        abiertos = db.execute(text(
            "UPDATE pagos SET estado = 'expirado' "
            "WHERE usuario_id = :u AND estado = 'iniciado'"), {"u": uid}).rowcount
        abiertos += db.execute(text(
            "UPDATE pagos SET estado = 'cancelado' "
            "WHERE usuario_id = :u AND estado IN ('pendiente', 'en_proceso')"),
            {"u": uid}).rowcount

        # 2. Solicitudes invisibles / pendientes del alumno: fuera de la cola.
        iniciadas = db.execute(text(
            "UPDATE solicitudes_planes SET estado = 'expirada', "
            "comentario_admin = :c "
            "WHERE alumno_id = :u AND estado = 'iniciado'"),
            {"u": uid, "c": COM_TENCION}).rowcount
        pendientes = db.execute(text(
            "UPDATE solicitudes_planes SET estado = 'rejected', "
            "comentario_admin = :c "
            "WHERE alumno_id = :u AND estado = 'pending'"),
            {"u": uid, "c": COMENTARIO_E2E}).rowcount

        # 3. Planes pagos vigentes: el E2E necesita que la compra ACTIVE ya.
        #    Se marcan `vencido` (no se borran) para no falsear el historial.
        vencidas = db.execute(text(
            "UPDATE suscripciones s SET estado = 'vencido' "
            "FROM planes p "
            "WHERE p.id = s.plan_id AND s.usuario_id = :u "
            "AND s.estado = 'activo' AND p.precio_clp > 0"), {"u": uid}).rowcount

        db.commit()
        return {
            "alumno_id": uid,
            "pagos_abiertos_cerrados": abiertos,
            "solicitudes_iniciadas_cerradas": iniciadas,
            "solicitudes_pendientes_rechazadas": pendientes,
            "suscripciones_pagadas_vencidas": vencidas,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alumno-email", required=True)
    parser.add_argument("--permitir-cualquier-correo", action="store_true")
    args = parser.parse_args()
    _validar_entorno()
    resultado = limpiar(args.alumno_email, args.permitir_cualquier_correo)
    print("[E2E] limpieza OK:", resultado)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
