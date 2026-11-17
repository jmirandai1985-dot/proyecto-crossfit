"""Expira pagos online que nunca se cobraron — Cron Job de Render (horario).

`app/services/pagos.expirar_pendientes` cierra los cobros abandonados (membresía:
5 min para el intento `iniciado` sin ningún aviso de MP y 30 min para un pago
REAL `pendiente`/`en_proceso`; Bazar: 30 min), pero vive en la APP (SQLAlchemy) y
no puede correr en la imagen de cron (`Dockerfile.cron` es mínima). Este módulo
replica la MISMA regla en SQL y habla con la base por `psql` (igual que
`mantenimiento_cloud`).

⚠️ El cron corre cada HORA (`render.yaml`: `schedule: "0 * * * *"`), así que con
el umbral de 5 min para el intento el cierre efectivo ocurre dentro de la hora
siguiente a vencer (hasta ~60 min). El guard que ve el alumno (`iniciado_vigente`,
en la app) es en TIEMPO REAL y no depende del cron. El camino rápido para el
alumno que SÍ vuelve a la app es el botón "Cancelar"
(`POST /pagos/{id}/cancelar`), que cierra al toque.

Qué hace (UNA transacción, idempotente):
  * Membresía con aviso real (30 min): pago abierto viejo → `expirado` +
    solicitud `pending` → `expirada`.
    ⚠️ NO se notifica al alumno al expirar (mejora futura: aviso en su campana).
  * Membresía `iniciado` (5 min): el alumno nunca hizo nada en MP; se cierra
    igual (housekeeping) y la solicitud oculta pasa a `expirada`. El admin nunca
    la vio; NO es lo que mantiene limpia su cola.
  * Bazar (30 min): pago abierto viejo → `expirado` + pedido `pendiente` → `rechazado`
    + stock devuelto UNA sola vez (vía `RETURNING`).

SEGURIDAD:
  * `DRY_RUN` obligatorio y explícito (fail-closed): `1` sólo cuenta (no escribe);
    `0` aplica. Otro valor o ausencia ⇒ exit 2.
  * La URL sale de `DIRECT_URL` (directa de Neon, sin `-pooler`); si no, `DATABASE_URL`.
  * `psql` se invoca con lista de argumentos (nunca un shell).

Uso:
    py -3.12 -m maintenance.expirar_pendientes            (DRY_RUN=1)
    DRY_RUN=0 py -3.12 -m maintenance.expirar_pendientes  (aplica)
"""
import argparse
import os
import subprocess
import sys

# Regla de expiración (misma que `MINUTOS_BAZAR`/`MINUTOS_MEMBRESIA`/
# `MINUTOS_GUARD_MEMBRESIA` y los `COMENTARIO_EXPIRADA*` en
# app/services/pagos.py). Va en MINUTOS. **Dos umbrales de membresía**:
#   • `MINUTOS_GUARD_MEMBRESIA` (5): intento `iniciado` sin ningún aviso de MP.
#   • `MINUTOS_MEMBRESIA` (30): pago REAL `pendiente`/`en_proceso` (ya hubo aviso).
# El Bazar conserva 30 min porque reserva stock.
MINUTOS_GUARD_MEMBRESIA = 5
MINUTOS_MEMBRESIA = 30
MINUTOS_BAZAR = 30
COMENTARIO_EXPIRADA = f"Expirada: pago online no completado en {MINUTOS_MEMBRESIA} min"
COMENTARIO_EXPIRADA_INTENTO = (
    "Expirada: intento de pago no completado en "
    f"{MINUTOS_GUARD_MEMBRESIA} min"
)

SQL_EXPIRAR = f"""
WITH vencidos AS (
    SELECT id, concepto, referencia_id, estado
    FROM pagos
    WHERE (
        (estado = 'iniciado' AND concepto = 'membresia'
         AND created_at <= now() - interval '{MINUTOS_GUARD_MEMBRESIA} minutes')
        OR (estado IN ('pendiente', 'en_proceso')
            AND (
                (concepto = 'membresia' AND created_at <= now() - interval '{MINUTOS_MEMBRESIA} minutes')
                OR (concepto = 'bazar' AND created_at <= now() - interval '{MINUTOS_BAZAR} minutes')
            ))
    )
),
cerrados AS (
    UPDATE pagos p
    SET estado = 'expirado'
    FROM vencidos v
    WHERE p.id = v.id
    RETURNING p.id, v.concepto, v.referencia_id, v.estado AS estado_anterior
),
solicitudes_cerradas AS (
    UPDATE solicitudes_planes s
    SET estado = 'expirada',
        comentario_admin = CASE
            WHEN c.estado_anterior = 'iniciado' THEN '{COMENTARIO_EXPIRADA_INTENTO}'
            ELSE '{COMENTARIO_EXPIRADA}'
        END
    FROM cerrados c
    WHERE c.concepto = 'membresia'
      AND s.id = c.referencia_id
      AND s.estado IN ('iniciado', 'pending')
    RETURNING s.id
),
rechazados AS (
    UPDATE pedidos pe
    SET estado = 'rechazado'
    FROM cerrados c
    WHERE c.concepto = 'bazar'
      AND pe.id = c.referencia_id
      AND pe.estado = 'pendiente'
    RETURNING pe.producto_id, pe.cantidad
),
sumados AS (
    SELECT producto_id, sum(cantidad) AS cantidad
    FROM rechazados
    GROUP BY producto_id
)
UPDATE productos pr
SET stock = pr.stock + s.cantidad
FROM sumados s
WHERE pr.id = s.producto_id;
"""

SQL_CONTEO = f"""
SELECT
  (SELECT count(*) FROM pagos
   WHERE (estado = 'iniciado' AND concepto = 'membresia'
          AND created_at <= now() - interval '{MINUTOS_GUARD_MEMBRESIA} minutes')
      OR (estado IN ('pendiente', 'en_proceso')
          AND ((concepto = 'membresia' AND created_at <= now() - interval '{MINUTOS_MEMBRESIA} minutes')
            OR (concepto = 'bazar' AND created_at <= now() - interval '{MINUTOS_BAZAR} minutes')))) AS pagos,
  (SELECT count(*) FROM solicitudes_planes s
   JOIN pagos p ON p.referencia_id = s.id AND p.concepto = 'membresia'
   WHERE (p.estado = 'iniciado'
          AND p.created_at <= now() - interval '{MINUTOS_GUARD_MEMBRESIA} minutes'
          AND s.estado = 'iniciado')
      OR (p.estado IN ('pendiente', 'en_proceso')
          AND p.created_at <= now() - interval '{MINUTOS_MEMBRESIA} minutes'
          AND s.estado = 'pending')) AS solicitudes,
  (SELECT count(*) FROM pedidos pe
   JOIN pagos p ON p.referencia_id = pe.id AND p.concepto = 'bazar'
   WHERE p.estado IN ('pendiente', 'en_proceso')
     AND p.created_at <= now() - interval '{MINUTOS_BAZAR} minutes'
     AND pe.estado = 'pendiente') AS pedidos;
"""



class ConfigError(Exception):
    """Falta o está mal una variable de entorno (exit 2, fail-closed)."""


def _url() -> str:
    return (os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL") or "").strip()


def _dry_run() -> bool:
    valor = os.environ.get("DRY_RUN", "").strip()
    if valor == "1":
        return True
    if valor == "0":
        return False
    raise ConfigError("DRY_RUN tiene que ser 0 o 1 (fail-closed)")


def _psql(url: str, sql: str) -> str:
    """Corre `psql` con lista de argumentos (nunca un shell) y devuelve stdout."""
    resultado = subprocess.run(
        ["psql", url, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, encoding="utf-8",
    )
    if resultado.returncode != 0:
        raise ConfigError(f"psql rc={resultado.returncode}: {resultado.stderr.strip()}")
    return resultado.stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    try:
        url = _url()
        if not url:
            raise ConfigError("falta DIRECT_URL (o DATABASE_URL)")
        dry = _dry_run()
    except ConfigError as error:
        print(f"[expirar_pendientes] ERROR: {error}", file=sys.stderr)
        return 2

    print(f"[expirar_pendientes] DRY_RUN={'1 (no se escribe nada)' if dry else '0 (APLICA cambios)'}")

    if dry:
        salida = _psql(url, SQL_CONTEO)
        print("[expirar_pendientes] cambiaría:" + salida.strip())
        return 0

    # Una SOLA llamada a psql: cada `_psql` es un proceso aparte y no puede
    # compartir una transacción. Con `ON_ERROR_STOP=1`, si una sentencia falla,
    # psql corta antes del COMMIT y la conexión se cierra (Postgres hace rollback).
    transaccion = "BEGIN;\n" + SQL_EXPIRAR + "\nCOMMIT;"
    _psql(url, transaccion)
    print("[expirar_pendientes] cambios aplicados (COMMIT)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

