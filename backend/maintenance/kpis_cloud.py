"""KPIs y ML de PROD en la nube — Cron Job de Render (Fase 8, 2026-09-29).

Por qué existe este módulo
--------------------------
Los KPIs (diarios y mensuales), las predicciones y el reentrenamiento de los modelos
de ML se disparaban desde **n8n** (workflows `Populate Daily KPIs [PROD]`,
`Populate Monthly KPIs [PROD]`, `Populate Predictions [PROD]` y `Reentrenar Modelo
ML`, apuntando a `https://box-crossfit.onrender.com` con el header `X-N8N-API-Key`).
Las notificaciones a alumnos NO se tocan (siguen en n8n): lo que se migra es el
GRUPO 1, el trabajo de DATOS que no habla con nadie.

Inventario de lo que reemplaza (medido en la instancia de n8n, 2026-09-29; los JSON
del repo son copias de referencia y pueden estar viejos):

| Workflow (instancia) | Cron (CLT) | Llamada |
|---|---|---|
| `Populate Daily KPIs [PROD]` | `0 30 2 * * *` → 02:30 diario | POST /api/v1/kpis/populate/daily |
| `Populate Monthly KPIs [PROD]` | `0 0 3 1 * *` → día 1, 03:00 | POST /api/v1/kpis/populate/monthly |
| `Populate Predictions [PROD]` | `45 3 1 * *` → día 1, 03:45 | POST /api/v1/kpis/populate/predictions |
| `Reentrenar Modelo ML` | `0 30 3 1 * *` → día 1, 03:30 | POST /api/v1/ml/reentrenar y, ENCADENADO, POST /api/v1/kpis/populate/predictions |

⚠️ Dos diferencias REALES contra lo que se suele decir de este último workflow:
1. `Reentrenar Modelo ML` **no tiene nodo de segmentación** (la instancia lo confirma:
   sólo `POST /ml/reentrenar` + `POST /kpis/populate/predictions` encadenado). La
   segmentación K-Means (`POST /api/v1/segmentacion/reentrenar`) **hoy no la corre
   ningún workflow**: es manual. Este job la agrega a los días 15 y último del mes.
2. El reentrenamiento pasaba el **día 1**; acá pasa a los **días 15 y último** (según
   lo pedido) y, como el workflow viejo refrescaba las predicciones justo después de
   entrenar, este job hace lo mismo: `reentrenar → segmentación → predicciones`.

Qué hace (un solo Cron Job DIARIO; el "día 1 / 15 / último" lo decide este script, no
el cron, porque un cron de Render no sabe expresar "último día del mes"):
  * **todos los días**   → POST /kpis/populate/daily (con `fecha=ayer` en hora de Chile)
  * **día 1**            → + POST /kpis/populate/monthly (último mes CERRADO) + predictions
  * **días 15 y último** → + POST /ml/reentrenar + POST /segmentacion/reentrenar + predictions

Principios
----------
1. **Nada de la app**: no se importa `app.*` (ni FastAPI ni SQLAlchemy) y no se toca la
   base: TODO pasa por la API pública con el header `X-N8N-API-Key`. `Dockerfile.cron`
   ya copia lo que hace falta (`alertas` → `backup_cloud` → `sanear`).
2. **La clave nunca se imprime**: viaja en un header (no en la URL) y todo texto
   externo pasa por `sanear()` + el tachado explícito de la clave (`_ocultar`).
3. **El "día" es el de Chile** (`TZ`, default `America/Santiago`): el cron de Render
   va en UTC y el día del mes se decide con el calendario local del box.
4. **Reintentos acotados**: los 5xx, los timeouts y los cortes de red se reintentan
   (`REINTENTOS`, con espera que se duplica); un **4xx NO se reintenta** (una clave
   mal puesta no se arregla sola) y se reporta con su código.
5. **Un fallo no aborta el resto**: si la segmentación falla, las predicciones igual
   se corren; al final se sale != 0 y se manda UN correo con todo lo que falló.
6. **Correo = algo que revisar**: sólo se manda si hubo un fallo (exit 3) o si el
   reentrenamiento volvió `parcial` —HTTP 200 pero con un modelo sin entrenar, que en
   n8n pasaba como verde y acá deja el run rojo (exit 5)—. Un run verde NO manda nada.
7. **`DRY_RUN=1` por defecto** (igual que el resto de la imagen): imprime el plan y NO
   llama a nada. Se apaga con `DRY_RUN=0` en el env group del Cron Job.

Exit codes
----------
0 OK (sin correo) · 2 config (falta o es inválida una variable) · 3 alguna llamada
falló tras los reintentos · 5 el reentrenamiento volvió `parcial` · 4 inesperado.

Uso:
    python -m maintenance.kpis_cloud

Env (env group `kpis-prod`, ver maintenance/README.md §Fase 8):
    KPIS_API_URL, CRON_API_KEY|N8N_API_KEY, DRY_RUN, [TIMEOUT_SEG, REINTENTOS,
    ESPERA_REINTENTO_SEG, DIA_ML, TZ] + el env group `alertas` para el correo.
"""
from __future__ import annotations

import calendar
import html
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from maintenance.alertas import VARS_ALERTA, enviar_email
from maintenance.backup_cloud import limpiar_valor, sanear

try:  # `zoneinfo` viene con Python 3.9+ (la imagen del cron es 3.12).
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - sólo por si el intérprete es muy viejo
    ZoneInfo = None

PREFIJO = "[kpis]"

# ── Códigos de salida (Render marca fallido el run si != 0) ──
EXIT_OK = 0
EXIT_CONFIG = 2        # falta una variable / URL inválida / entero fuera de rango
EXIT_LLAMADA = 3       # una llamada falló tras los reintentos
EXIT_INESPERADO = 4    # un error que no contemplamos
EXIT_PARCIAL = 5       # el reentrenamiento volvió "parcial" (HTTP 200, un modelo sin entrenar)

# Qué pasó, para el ASUNTO del correo (el detalle va en el cuerpo).
TITULOS_EXIT = {
    EXIT_CONFIG: "configuración inválida",
    EXIT_LLAMADA: "llamadas con error",
    EXIT_PARCIAL: "reentrenamiento parcial",
}

VARS_OBLIGATORIAS = ("KPIS_API_URL",)
# La key de automatización: `CRON_API_KEY` (Cron Job de Render) si está definida, si no
# `N8N_API_KEY` (n8n). Mismo criterio que `settings.automation_api_key` del backend.
VARS_API_KEY = ("CRON_API_KEY", "N8N_API_KEY")
TZ_CLT = "America/Santiago"

# Rutas de la API (una sola definición: la usan el plan y los tests).
RUTA_DAILY = "/api/v1/kpis/populate/daily"
RUTA_MONTHLY = "/api/v1/kpis/populate/monthly"
RUTA_PREDICTIONS = "/api/v1/kpis/populate/predictions"
RUTA_ML = "/api/v1/ml/reentrenar"
RUTA_SEGMENTACION = "/api/v1/segmentacion/reentrenar"

# Hosts donde SÍ se permite http:// (el stack de TEST corre en la laptop). Contra
# cualquier otro host la clave tiene que viajar por https: si no, se aborta (exit 2).
HOSTS_LOCALES = ("localhost", "127.0.0.1", "::1", "[::1]")

# Topes/defectos de los enteros de config (el rango es lo que llega al uso).
TIMEOUT_DEFECTO, TIMEOUT_RANGO = 300, (10, 3600)
REINTENTOS_DEFECTO, REINTENTOS_RANGO = 2, (0, 5)
ESPERA_DEFECTO, ESPERA_RANGO = 20, (1, 600)
# Día del mes del reentrenamiento (además del último): 2..28 para que exista en
# TODOS los meses (el 29/30/31 no existe en febrero y nunca dispararía).
DIA_ML_DEFECTO, DIA_ML_RANGO = 15, (2, 28)

# Claves del JSON de respuesta que van al log (una línea por llamada).
CLAVES_RESUMEN = ("status", "accion", "fecha", "year", "month", "meses_calculados",
                  "n_alumnos", "silhouette", "k", "modelos_vigentes")


class ConfigError(RuntimeError):
    pass


# Seam de la espera entre reintentos: los tests lo doblan para no dormir de verdad.
DORMIR = time.sleep


def log(msg: str) -> None:
    """Línea de log con el prefijo del job y saneada (nunca sale una credencial)."""
    print(f"{PREFIJO} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {sanear(msg)}",
          flush=True)


# ── Config (todos los `os.getenv` del módulo viven en estos lectores) ──────────
def _texto(nombre: str, defecto: str = "") -> str:
    return limpiar_valor(os.getenv(nombre) or defecto)


def _entero(nombre: str, defecto: int, rango: tuple) -> int:
    """Entero de env con rango CERRADO: fuera de rango ⇒ ConfigError (exit 2).

    El rango es lo que evita que un `DIA_ML=999` o un `REINTENTOS=-1` lleguen al
    uso (y a un bucle infinito de reintentos).
    """
    crudo = _texto(nombre)
    if not crudo:
        return defecto
    try:
        valor = int(crudo)
    except ValueError:
        raise ConfigError(f"{nombre}='{crudo}' no es un entero")
    minimo, maximo = rango
    if not (minimo <= valor <= maximo):
        raise ConfigError(f"{nombre}={valor} está fuera del rango {minimo}-{maximo}")
    return valor


def dry_run_activo() -> bool:
    """`DRY_RUN=1` (o cualquier valor que no sea 0/false/no) = NO se llama a nada."""
    return _texto("DRY_RUN", "1").lower() not in ("0", "false", "no")


def validar_url_api(url: str) -> str:
    """La URL base de la API, sin barra final y con https (o http sólo si es local).

    Por qué: la petición lleva la `N8N_API_KEY` de PROD en un header; por http a un
    host remoto la clave viajaría EN CLARO. Sólo se acepta http sin TLS contra el
    stack local de TEST (localhost/127.0.0.1), que es donde se prueba a mano.
    """
    limpio = limpiar_valor(url).rstrip("/")
    partes = urllib.parse.urlsplit(limpio)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise ConfigError(
            f"KPIS_API_URL='{limpio}' no es una URL http(s) válida "
            "(ej. https://box-crossfit.onrender.com)")
    if partes.scheme == "http" and partes.hostname not in HOSTS_LOCALES:
        raise ConfigError(
            f"KPIS_API_URL='{limpio}' usa http contra un host remoto: la "
            "N8N_API_KEY viajaría sin cifrar. Usá https (o localhost para TEST)")
    return limpio


def leer_config() -> dict:
    """Config completa y validada. Cualquier problema ⇒ ConfigError (exit 2)."""
    faltan = [v for v in VARS_OBLIGATORIAS if not _texto(v)]
    if faltan:
        raise ConfigError(f"faltan variables de entorno: {', '.join(faltan)}")
    # La key de automatización: CRON_API_KEY si está, si no N8N_API_KEY (mismo criterio que
    # settings.automation_api_key del backend). Sin ninguna de las dos no se llama a nada.
    api_key = _texto("CRON_API_KEY") or _texto("N8N_API_KEY")
    if not api_key:
        raise ConfigError(
            "falta la API key: define CRON_API_KEY (recomendado) o N8N_API_KEY")
    return {
        "api_url": validar_url_api(_texto("KPIS_API_URL")),
        "api_key": api_key,
        "tz": _texto("TZ", TZ_CLT) or TZ_CLT,
        "timeout": _entero("TIMEOUT_SEG", TIMEOUT_DEFECTO, TIMEOUT_RANGO),
        "reintentos": _entero("REINTENTOS", REINTENTOS_DEFECTO, REINTENTOS_RANGO),
        "espera": _entero("ESPERA_REINTENTO_SEG", ESPERA_DEFECTO, ESPERA_RANGO),
        "dia_ml": _entero("DIA_ML", DIA_ML_DEFECTO, DIA_ML_RANGO),
        "dry_run": dry_run_activo(),
    }


# ── Calendario en hora de Chile (el cron de Render va en UTC) ────────────────
def zona(tz_nombre: str):
    """`ZoneInfo` del huso pedido; si no existe (o falta zoneinfo) ⇒ None (UTC/local)."""
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_nombre)
    except Exception:  # noqa: BLE001 (huso mal escrito: se sigue con UTC, no se cae)
        return None


def ahora_local(cuando: datetime | None = None, tz_nombre: str = TZ_CLT) -> datetime:
    """`datetime` local del box (Chile por defecto) del instante indicado."""
    z = zona(tz_nombre)
    if cuando is None:
        return datetime.now(z) if z else datetime.now()
    if cuando.tzinfo is None:
        cuando = cuando.astimezone()
    return cuando.astimezone(z) if z else cuando


def hoy_local(cuando: datetime | None = None, tz_nombre: str = TZ_CLT) -> date:
    return ahora_local(cuando, tz_nombre).date()


def ultimo_dia_del_mes(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def es_ultimo_dia(d: date) -> bool:
    return d.day == ultimo_dia_del_mes(d)


def mes_anterior(d: date) -> tuple:
    """(año, mes) del mes ANTERIOR: en el día 1 es el último mes CERRADO."""
    return (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)


def plan_del_dia(hoy: date, dia_ml: int = DIA_ML_DEFECTO) -> list:
    """Las llamadas del día, EN ORDEN. PURA (sin base, sin red y sin reloj).

    Por qué es una función pura: el "calendario" del job (qué corre cada día) es la
    parte que más fácil se rompe y la que no se puede probar contra PROD; así los
    tests fijan día 1, día 15, último día (incluido febrero) y un día cualquiera.

    Reglas (mismas que los 4 workflows de n8n que reemplaza):
      · todos los días: el KPI del día anterior (`fecha=ayer` en hora de Chile);
      · día 1: además el KPI del mes anterior (ya cerrado) y las predicciones;
      · día `dia_ml` (15) y ÚLTIMO del mes: reentrenar modelos, reentrenar la
        segmentación y refrescar las predicciones con el modelo nuevo (el orden
        importa: entrenar antes de predecir).

    Los `params` viajan explícitos para que el resultado NO dependa del huso del
    servidor: el día/mes lo decide este proceso, con el calendario de Chile.
    """
    pasos = [{
        "nombre": "KPIs diarios",
        "metodo": "POST",
        "ruta": RUTA_DAILY,
        "params": {"fecha": (hoy - timedelta(days=1)).isoformat()},
        "porque": "el día ya cerró: es el KPI que mira la pestaña Diario",
    }]

    if hoy.day == 1:
        anio, mes = mes_anterior(hoy)
        pasos.append({
            "nombre": "KPIs mensuales",
            "metodo": "POST",
            "ruta": RUTA_MONTHLY,
            "params": {"year": anio, "month": mes},
            "porque": f"el mes anterior ({anio}-{mes:02d}) ya cerró: es el KPI mensual",
        })
        pasos.append({
            "nombre": "Predicciones (churn + forecast)",
            "metodo": "POST",
            "ruta": RUTA_PREDICTIONS,
            "params": {},
            "porque": "el workflow mensual de n8n actualizaba las predicciones el día 1",
        })

    if hoy.day == dia_ml or es_ultimo_dia(hoy):
        pasos.append({
            "nombre": "Reentrenar modelos ML",
            "metodo": "POST",
            "ruta": RUTA_ML,
            "params": {},
            "porque": f"día de reentrenamiento ({dia_ml} y último del mes): churn + forecast",
        })
        pasos.append({
            "nombre": "Reentrenar segmentación (arquetipos)",
            "metodo": "POST",
            "ruta": RUTA_SEGMENTACION,
            "params": {},
            "porque": "en n8n la segmentación K-Means no la corría ningún workflow",
        })
        pasos.append({
            "nombre": "Predicciones (con el modelo recién entrenado)",
            "metodo": "POST",
            "ruta": RUTA_PREDICTIONS,
            "params": {},
            "porque": "el workflow viejo encadenaba predicciones después de entrenar",
        })

    return pasos


# ── Llamadas HTTP (con doble en los tests: ningún test toca la red) ───────────
def url_de(cfg: dict, paso: dict) -> str:
    """URL completa del paso (los params van en el query; la clave NO va en la URL)."""
    url = cfg["api_url"] + paso["ruta"]
    if paso["params"]:
        url += "?" + urllib.parse.urlencode(paso["params"])
    return url


def _http(req, timeout: int):
    """SEAM de red: el ÚNICO lugar donde se abre una conexión (los tests lo doblan)."""
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _ocultar(texto, secreto) -> str:
    """`sanear()` + tachado explícito del secreto (la clave viaja en un header)."""
    t = sanear(texto)
    s = (secreto or "").strip()
    return t.replace(s, "***") if s else t


def _resumen(cuerpo: str, tope: int = 400) -> str:
    """Resumen de una respuesta para el log (una línea, sin volcar todo el payload)."""
    try:
        datos = json.loads(cuerpo)
    except (TypeError, ValueError):
        return _ocultar(cuerpo[:tope], "")
    if isinstance(datos, dict):
        elegido = {k: datos[k] for k in CLAVES_RESUMEN if k in datos} or datos
        return sanear(json.dumps(elegido, ensure_ascii=False, default=str)[:tope])
    return sanear(str(datos)[:tope])


def llamar(cfg: dict, paso: dict, dormir=None) -> dict:
    """Hace la llamada del paso con reintentos ACOTADOS. Nunca levanta por red.

    Devuelve `{"ok", "http", "detalle", "intentos", "parcial"}`:
      · ok=True  → 2xx (el detalle dice si la API devolvió `status: parcial`);
      · ok=False → falló (5xx/timeout/red tras agotar los reintentos, o CUALQUIER 4xx).

    Los 4xx NO se reintentan: una clave inválida o una ruta mal escrita no se arreglan
    esperando; reintentarlas sólo ensucia el log y demora la alerta.

    `dormir` es el seam de la espera (los tests lo doblan para no dormir de verdad).
    """
    dormir = dormir or DORMIR
    intentos_max = cfg["reintentos"] + 1
    espera = cfg["espera"]
    ultimo = (None, "sin respuesta")
    for intento in range(1, intentos_max + 1):
        try:
            req = urllib.request.Request(url_de(cfg, paso), method=paso["metodo"])
            req.add_header("X-N8N-API-Key", cfg["api_key"])
            req.add_header("Accept", "application/json")
            status, cuerpo = _http(req, cfg["timeout"])
            if not 200 <= status < 300:
                # urllib levanta HTTPError con los >= 400, pero el chequeo explícito
                # cubre un 3xx (o un doble de test): EL STATUS MANDA. Se normaliza a
                # HTTPError para que entre por la MISMA rama (4xx sin reintento,
                # 5xx con reintento).
                raise urllib.error.HTTPError(
                    url_de(cfg, paso), status, "", None,
                    io.BytesIO((cuerpo or "").encode("utf-8")))
        except urllib.error.HTTPError as e:
            try:
                detalle = _ocultar(e.read().decode("utf-8", "replace"), cfg["api_key"])
            except Exception:  # noqa: BLE001 (cuerpo ilegible: queda el motivo HTTP)
                detalle = ""
            ultimo = (e.code, detalle[:300])
            if e.code < 500:
                log(f"FALLA {paso['nombre']}: HTTP {e.code} (4xx: sin reintento) {detalle[:200]}")
                return {"ok": False, "http": e.code, "detalle": ultimo[1],
                        "intentos": intento, "parcial": False}
            log(f"intento {intento}/{intentos_max} {paso['nombre']}: HTTP {e.code} {detalle[:200]}")
        except Exception as e:  # noqa: BLE001 (URLError, timeout, DNS, TLS...)
            detalle = _ocultar(f"{type(e).__name__}: {e}", cfg["api_key"])
            ultimo = (None, detalle)
            log(f"intento {intento}/{intentos_max} {paso['nombre']}: {detalle[:200]}")
        else:
            resumen = _resumen(cuerpo)
            # `parcial` (200 con un modelo sin entrenar) NO es un verde: n8n lo daba
            # por bueno y acá deja el run rojo (ver EXIT_PARCIAL).
            try:
                datos = json.loads(cuerpo)
                parcial = isinstance(datos, dict) and datos.get("status") == "parcial"
            except (TypeError, ValueError):
                parcial = False
            log(f"OK {paso['nombre']}: HTTP {status} {resumen}")
            return {"ok": True, "http": status, "detalle": resumen,
                    "intentos": intento, "parcial": parcial}

        if intento < intentos_max:
            log(f"  reintento en {espera}s...")
            dormir(espera)
            espera *= 2

    return {"ok": False, "http": ultimo[0], "detalle": ultimo[1],
            "intentos": intentos_max, "parcial": False}


# ── Correo: SÓLO si hay algo que revisar (fallo o reentrenamiento parcial) ────
def _fila(paso: dict, r: dict | None = None) -> str:
    """Una línea del reporte: la llamada y cómo salió (o "no ejecutada")."""
    url = paso["ruta"] + (f"?{urllib.parse.urlencode(paso['params'])}"
                          if paso["params"] else "")
    if r is None:
        return f"<li><code>{paso['metodo']} {url}</code> — <b>no ejecutada</b></li>"
    if r["ok"]:
        estado = "parcial" if r["parcial"] else "ok"
        return (f"<li><code>{paso['metodo']} {url}</code> — <b>{estado}</b> "
                f"(HTTP {r['http']}, {r['intentos']} intento/s) {r['detalle']}</li>")
    http = f"HTTP {r['http']}" if r["http"] else "sin respuesta"
    return (f"<li><code>{paso['metodo']} {url}</code> — <b>FALLA</b> "
            f"({http}, {r['intentos']} intento/s) {r['detalle']}</li>")


def construir_html(hoy: date, resultados: list, segundos: float,
                   titulo: str, motivo: str = "") -> str:
    """Cuerpo del correo: qué corrió, qué falló, POR QUÉ y por qué el run quedó rojo."""
    filas = "".join(_fila(p, r) for p, r in resultados)
    detalle = (f"<p><b>Motivo:</b> {html.escape(str(motivo))}</p>" if motivo else "")
    return (
        f"<h2>{PREFIJO} KPIs y ML de PROD</h2>"
        f"<p><b>{titulo}</b> — run del {hoy.isoformat()} (hora de Chile), "
        f"{round(segundos, 1)}s.</p>"
        f"{detalle}"
        f"<p>Estas son las llamadas del día (todas con <code>X-N8N-API-Key</code>):</p>"
        f"<ul>{filas}</ul>"
        "<p>Un run VERDE no manda correo: este aviso sale sólo si alguna llamada falló "
        "o si el reentrenamiento volvió <code>parcial</code> (un modelo sin entrenar).</p>"
    )


def enviar_reporte(code: int, hoy: date, resultados: list, segundos: float,
                   motivo: str = "") -> bool:
    """Manda el correo con `alertas.enviar_email` (Gmail SMTP, el único camino).

    Que el correo falle NUNCA cambia el exit code del run.
    """
    titulo = TITULOS_EXIT.get(code, "algo salió mal")
    asunto = f"[ALERTA] KPIs y ML PROD: {titulo}"
    return enviar_email(asunto, construir_html(hoy, resultados, segundos, titulo,
                                               motivo), logger=log)


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    inicio = datetime.now(timezone.utc)
    log("KPIs y ML de PROD — Cron Job de Render")

    try:
        cfg = leer_config()
    except ConfigError as e:
        log(f"FATAL (config): {e}")
        # Un job que no corre tampoco puede ser silencioso: avisa igual, y con el
        # MOTIVO (si no, el correo dice "configuración inválida" y no qué falta).
        enviar_reporte(EXIT_CONFIG, hoy_local(), [], 0.0, motivo=str(e))
        return EXIT_CONFIG

    # Aviso (no aborta): sin las 3 variables de `alertas` el correo no va a poder salir.
    faltan_alerta = [v for v in VARS_ALERTA if not _texto(v)]
    if faltan_alerta:
        log(f"AVISO (config): faltan {', '.join(faltan_alerta)}: si el run falla, "
            "el correo de alerta NO va a poder salir (el job corre igual)")

    hoy = hoy_local(tz_nombre=cfg["tz"])
    pasos = plan_del_dia(hoy, cfg["dia_ml"])
    log(f"hoy (Chile) = {hoy.isoformat()} · {len(pasos)} llamada(s) al API "
        f"{cfg['api_url']}")

    resultados = []
    if cfg["dry_run"]:
        # Sin llamadas: se imprime el plan completo y se sale verde (no hay nada que
        # revisar). ⚠️ Hay que poner DRY_RUN=0 en el env group para que actúe.
        for paso in pasos:
            log(f"  · [DRY_RUN] {paso['metodo']} "
                f"{url_de(cfg, paso).replace(cfg['api_url'], '')} — {paso['porque']}")
        log("DRY_RUN=1: NO se llamó a ningún endpoint (poné DRY_RUN=0 para que corra)")
        return EXIT_OK

    for paso in pasos:
        log(f"→ {paso['nombre']} ({paso['porque']})")
        resultados.append((paso, llamar(cfg, paso)))

    segundos = (datetime.now(timezone.utc) - inicio).total_seconds()
    fallos = [p for p, r in resultados if not r["ok"]]
    parciales = [p for p, r in resultados if r["ok"] and r["parcial"]]
    ok = [p for p, r in resultados if r["ok"]]
    log(f"fin: {len(ok)}/{len(resultados)} llamada(s) ok, {len(fallos)} con error, "
        f"{len(parciales)} parcial(es) · {round(segundos, 1)}s")

    if fallos:
        motivo = "; ".join(f"{p['nombre']}: HTTP {r['http'] or 'sin HTTP'} — {r['detalle']}"
                           for p, r in resultados if not r["ok"])
        log("FALLA: " + motivo)
        enviar_reporte(EXIT_LLAMADA, hoy, resultados, segundos, motivo=motivo)
        return EXIT_LLAMADA

    if parciales:
        motivo = ("La API respondió HTTP 200 con status=parcial: al menos un modelo "
                  "quedó sin entrenar. " + "; ".join(p["nombre"] for p in parciales))
        log("PARCIAL: " + motivo)
        enviar_reporte(EXIT_PARCIAL, hoy, resultados, segundos, motivo=motivo)
        return EXIT_PARCIAL

    log("todo ok: sin correo (no hay nada que revisar)")
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 (último cinturón: el run no puede morir mudo)
        log(f"FATAL (inesperado): {type(e).__name__}: {sanear(e)}")
        try:
            enviar_reporte(EXIT_INESPERADO, hoy_local(), [], 0.0, motivo=str(e))
        except Exception:  # noqa: BLE001
            pass
        sys.exit(EXIT_INESPERADO)
