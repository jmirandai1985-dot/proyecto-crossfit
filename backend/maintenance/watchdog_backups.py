"""Watchdog de frescura del backup diario en R2 — Cron Job de Render (0 12 * * * UTC).

Por qué existe
--------------
El 26/09 el backup estuvo días sin correr y nadie se enteró (el job logueaba
"✅ Backup completado" con el dump fallando). Este watchdog es **independiente** del job
de backup: si el backup no corre, este avisa igual.

Reglas (umbrales por env, con defaults)
--------------------------------------
  * no hay objetos en `daily/`                          -> ALERTA
  * el más nuevo tiene más de MAX_EDAD_HORAS (36 h)     -> ALERTA
  * el más nuevo pesa menos de MIN_BYTES (50 KB)        -> ALERTA

Con alerta: manda email por **Gmail SMTP** (el helper `maintenance/alertas.py`, el mismo
camino que usa la app: `smtp.gmail.com:465` + `SMTP_SSL`) y sale con **exit 6** ⇒ el run
queda rojo en Render. Sin alerta: una línea de log y exit 0, **sin email**.

Alcance mínimo
--------------
Sólo LEE R2 (token de **solo lectura**, env group `r2-lectura`) y **no** necesita
`PROD_DB_DIRECT_URL` ni ninguna credencial de escritura. Todo lo que imprime pasa por
`log()`, que sanea con el helper de `backup_cloud` (nunca credenciales en el log).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# Helpers existentes: no se duplican (sanear/log/cliente_s3/listar + limpiar_valor).
from maintenance.alertas import VARS_ALERTA, enviar_email
from maintenance.backup_cloud import cliente_s3, limpiar_valor, listar, log

EXIT_OK = 0
EXIT_CONFIG = 2    # falta una variable / R2 inaccesible
EXIT_ALERTA = 6    # el watchdog tiene algo que avisar (run ROJO en Render)
EXIT_INESPERADO = 7  # error inesperado (igual: run rojo)

# OJO: NO incluye PROD_DB_DIRECT_URL ni variables de escritura (mínimo privilegio).
VARS_REQUERIDAS = (
    "R2_ENDPOINT",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    # GMAIL_SMTP_USER + GMAIL_SMTP_APP_PASSWORD + ALERT_EMAIL (una sola definición).
    *VARS_ALERTA,
)

PREFIJO = (os.getenv("BACKUP_PREFIX") or "daily/").strip()
MAX_EDAD_HORAS = float(os.getenv("MAX_EDAD_HORAS") or "36")
MIN_BYTES = int(os.getenv("MIN_BYTES") or str(50 * 1024))
# SMTP_HOST/SMTP_PORT y el armado del mensaje viven en maintenance/alertas.py (compartido).


def faltantes() -> list:
    return [v for v in VARS_REQUERIDAS if not limpiar_valor(os.getenv(v) or "")]


def evaluar(objetos: list, ahora: datetime = None) -> tuple:
    """PURA (testeable sin R2): (alerta: bool, motivo: str, detalle: dict).

    `objetos` = items de list_objects_v2 (Key, Size, LastModified).
    """
    ahora = ahora or datetime.now(timezone.utc)
    if not objetos:
        return True, "sin_objetos", {"cantidad": 0}

    nuevo = max(objetos, key=lambda o: o["LastModified"])
    edad_horas = (ahora - nuevo["LastModified"]).total_seconds() / 3600.0
    detalle = {
        "clave": nuevo["Key"],
        "bytes": nuevo["Size"],
        "edad_horas": round(edad_horas, 2),
        "fecha_utc": nuevo["LastModified"].strftime("%Y-%m-%d %H:%M"),
        "cantidad": len(objetos),
    }
    if edad_horas > MAX_EDAD_HORAS:
        return True, "viejo", detalle
    if nuevo["Size"] < MIN_BYTES:
        return True, "chico", detalle
    return False, "ok", detalle


def enviar_alerta(motivo: str, detalle: dict, ultimas: list) -> bool:
    """Email por Gmail SMTP. Nunca imprime credenciales (los errores se sanean)."""
    titulos = {
        "sin_objetos": "no hay NINGÚN backup en R2",
        "viejo": f"el backup más nuevo tiene {detalle.get('edad_horas')} h "
                 f"(límite {MAX_EDAD_HORAS:.0f} h)",
        "chico": f"el backup más nuevo pesa {detalle.get('bytes', 0)/1024:.1f} KB "
                 f"(mínimo {MIN_BYTES/1024:.0f} KB)",
    }
    # Asunto con el MISMO prefijo que el mantenimiento (`[ALERTA] <job>: <qué pasó>`): la
    # notificación del teléfono ya dice qué job falló sin abrir el correo.
    asunto = f"[ALERTA] Watchdog backups PROD: {titulos.get(motivo, motivo)}"
    filas = "".join(
        f"<li><code>{o['Key']}</code> — {o['Size']/1024:.1f} KB — "
        f"{o['LastModified'].strftime('%Y-%m-%d %H:%M')} UTC</li>" for o in ultimas)
    html = (
        "<h3>Watchdog de backups (R2)</h3>"
        f"<p><b>Motivo:</b> {titulos.get(motivo, motivo)}</p>"
        f"<p><b>Prefijo:</b> <code>{PREFIJO}</code> · <b>Objetos:</b> {detalle.get('cantidad', 0)}"
        f" · <b>Criterio:</b> máx {MAX_EDAD_HORAS:.0f} h / mín {MIN_BYTES/1024:.0f} KB</p>"
        f"<p><b>Últimos objetos:</b></p><ul>{filas or '<li>(ninguno)</li>'}</ul>"
        "<p>Este run del Cron Job queda con exit 6 (rojo en Render). Revisar el job de"
        " backup: <i>Cron Job proyecto-crossfit → Runs</i>.</p>"
    )
    return enviar_email(asunto, html)


def _ultimos(objetos: list, n: int = 5) -> list:
    return sorted(objetos, key=lambda o: o["LastModified"], reverse=True)[:n]


def main() -> int:
    log("=== watchdog de backups (R2) ===")
    log(f"prefijo={PREFIJO!r} | límites: {MAX_EDAD_HORAS:.0f} h / {MIN_BYTES/1024:.0f} KB")

    falta = faltantes()
    if falta:
        log(f"FATAL (config): faltan variables de entorno: {', '.join(falta)}")
        return EXIT_CONFIG

    try:
        cli = cliente_s3()
        objetos = listar(cli, PREFIJO)
    except Exception as e:  # noqa: BLE001
        log(f"FATAL: no se pudo listar R2: {type(e).__name__}: {e}")
        return EXIT_CONFIG

    alerta, motivo, detalle = evaluar(objetos)
    if not alerta:
        log(f"OK: {detalle['cantidad']} objeto(s); el más nuevo {detalle['clave']} "
            f"({detalle['bytes']/1024:.1f} KB, {detalle['edad_horas']} h)")
        return EXIT_OK

    log(f"ALERTA ({motivo}): {detalle}")
    enviado = enviar_alerta(motivo, detalle, _ultimos(objetos))
    if not enviado:
        # El run queda rojo igual por el exit code, pero se deja constancia.
        log("AVISO: la alerta no salió por Gmail; el run queda rojo igual (exit 6)")
    return EXIT_ALERTA


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        log(f"FATAL inesperado: {type(e).__name__}: {e}")
        sys.exit(EXIT_INESPERADO)

