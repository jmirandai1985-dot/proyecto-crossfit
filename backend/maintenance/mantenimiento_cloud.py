"""Mantenimiento de PROD 2× al mes (días 1 y 15) — Cron Job de Render.

Por qué existe este módulo
--------------------------
Los 5 scripts de mantenimiento (`marcar_plan_vencido`, `transacciones_huerfanas`,
`verificar_integridad`, `neon_usage_alerts`, `reporte_estadisticas`) sólo corren cuando la
laptop de Jebbus está encendida (contenedor local, contra la rama de TEST) y lo hacen con
la app cargada (SQLAlchemy + `settings.DATABASE_URL`). En PROD no corría nada: no había
trabajo de datos programado, ni reporte mensual, ni alerta de uso de Neon.
Este módulo es el mecanismo de **nube** para PROD: corre en un Cron Job de Render los días
**1 y 15**, contra la conexión DIRECTA del rol dedicado `maint_rw`, y avisa por email.

Principios
----------
1. **Nada de la app**: no se importa `app.*` (ni FastAPI ni SQLAlchemy). `Dockerfile.cron`
   no copia `app/`, y ésa es la razón por la que se habla con la base por `psql`. La ÚNICA
   excepción es `shared.estados` (2026-09-27): un paquete neutral, sin un solo import, donde vive
   la definición de "reserva cancelada" que **también** usa la app (`app/core/estados.py`). Se
   importa para que la lista sea UNA: antes el job usaba `ILIKE '%cancel%'` y la app el literal
   `'cancelled'`, dos criterios que podían divergir (README §Fase 7).
2. **Un solo rol, con la escritura mínima**: `maint_rw` tiene `SELECT` en 5 tablas y
   `UPDATE` **a nivel de columna** en 3 (`suscripciones.estado/updated_at`,
   `solicitudes_planes.estado/comentario_admin/updated_at`, `usuarios.estado/activo`).
   No hay `INSERT`, ni `DELETE`, ni DDL (el SQL del rol está en el README). `backup_ro`
   sigue siendo de sólo lectura: son dos roles distintos a propósito.
3. **Una sola transacción**: los 4 `UPDATE` van en un único `psql` (`BEGIN … ROLLBACK|COMMIT`).
   Antes cada script commiteaba por su cuenta: un fallo a mitad dejaba el trabajo a medias.
4. **DRY_RUN=1 por defecto** (igual que `backup_cloud`): la transacción completa se ejecuta
   y termina en `ROLLBACK`, así el mail dice **exactamente** qué filas habrían cambiado
   (no una estimación). Se apaga (`DRY_RUN=0`) recién cuando el log da verde.
5. **Guardas de volumen por regla**: no alcanza con un único tope global. La regla de negocio
   dice que **todo plan vence el ÚLTIMO día del mes**, así que el run del día 1 marca vencidos a
   todos los que no renovaron: ese volumen es ESPERABLE. Las huérfanas, en cambio, tienen que
   ser pocas (si hay muchas, es una anomalía). Por eso hay tres reglas y se evalúan todas en
   `evaluar_limites()` (función pura: conteos + config → reglas, sin base ni entorno):
   `MAX_VENCIDOS_PCT` (% máximo de las suscripciones activas que pueden vencer en un run),
   `MAX_HUERFANAS` (máximo **por cada** lista: suscripciones, solicitudes, usuarios) y
   `MAX_CAMBIOS` (tope global de respaldo del run, default 500). Si CUALQUIERA se pasa, el
   mantenimiento **no se aplica**: en REAL las guardas abortan la transacción *desde el SQL*
   (`DO $$ … RAISE EXCEPTION … $$`), así que no dependen del código Python; en DRY-RUN no
   abortan: informan (con la lista completa y el número de cada regla) y el run queda rojo
   (exit 6).
6. **El éxito se verifica**: después de la transacción se vuelven a correr las mismas
   consultas. En REAL deben dar 0 (se aplicó) y en DRY-RUN el mismo número de antes
   (no se aplicó nada).
7. **Todo sale saneado**: ninguna credencial puede quedar impresa. La URL sólo se muestra
   como `host_de(url)` y todo texto externo pasa por `sanear()` (`://***@`).
8. **Avisa sólo si hay algo que revisar**: el email sale por Gmail SMTP (`maintenance/alertas.py`,
   el mismo camino del watchdog y del drill) **sólo** si el run quedó rojo (exit ≠ 0: config,
   lectura, escritura, verificación, guarda de volumen o integridad) **o** si Neon pasó el umbral
   de espacio (`NEON_UMBRAL_PCT`). Un día normal —"APLICADO n cambios" verificado en 0— deja
   **sólo el log** en Render: el mail es una alerta, no un informe. El asunto arranca con
   `[ALERTA]` y dice qué job corrió y qué pasó.

Qué NO hace (a propósito)
-------------------------
No hace backup (`backup_cloud`), no hace drill (`restore_drill`), no purga logs
(`cleanup_logs` del contenedor), no pingea a la API (`health_check` apuntaría a
`localhost:8000`, donde en un Cron Job no hay nada) y no rota credenciales
(`rotar_credenciales` sólo avisa por log). Tampoco toca TEST ni el contenedor local.

Variables de entorno (env group `mantenimiento-prod` + `alertas` de Render)
--------------------------------------------------------------------------
  * `MAINT_DB_URL`  — conexión **directa** (host sin `-pooler`) del rol `maint_rw` de PROD
  * `ENVIRONMENT`   — tiene que ser `production` (guarda dura: el job escribe en PROD)
  * `MAX_CAMBIOS`   — tope global de respaldo del run (default 500)
  * `MAX_VENCIDOS_PCT` — % máximo de suscripciones activas que pueden vencer (default 80)
  * `MAX_HUERFANAS` — máximo **por cada** lista de huérfanas (default 10, `0` = ninguna)
  * `DIAS_PENDIENTE`— antigüedad de las huérfanas (default 7)
  * `NEON_LIMITE_MB`— límite del free tier de Neon (default 512 = 0,5 GB por proyecto)
  * `NEON_UMBRAL_PCT`— alerta de uso (default 80 %)
  * `DRY_RUN`       — `1` (default de la imagen) no aplica nada
  * `GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`, `ALERT_EMAIL` — del env group `alertas`

Fase 7 (2026-09-27): detecciones, límites de Neon, consistencia y reporte
-------------------------------------------------------------------------
Sobre la base de la Fase 6, el mismo run agrega cuatro bloques, sin scripts nuevos:
  * **A — detecciones de sólo lectura** (A.1–A.6): `estado` de usuario desconocido, aforo de
    las clases desincronizado con sus reservas, reservas vivas duplicadas, sobrecupo,
    descuadre de créditos, reservas sin auditoría de asistencia y clases futuras sin coach.
    A.5(a)/(b) miran **sólo** las disciplinas que exigen coach (`disciplinas.requiere_coach`:
    "Musculación" y "Open Box" son self-service y no son un hallazgo) y **nunca** comparan por
    nombre: el nombre sólo aparece en el backfill que destilda la disciplina (pantalla
    Disciplinas del admin). El conteo que viaja al log y al mail es el **total real** de cada
    consulta (`count(*) OVER ()`, la ventana se calcula antes del `LIMIT 25`), así que el mail
    puede decir "63 fila(s)" y listar sólo 25: antes el tope se confundía con el conteo.
    Nada de esto escribe: lo que encuentra viaja en el mail y pone el run rojo (**exit 9**),
    igual que la integridad (exit 4) — el mantenimiento se aplica igual (en DRY-RUN, donde no
    se aplicó nada, el motivo lo dice con esas palabras).
  * **B — límites del free tier de Neon** (B.6 CU-horas y B.7 ramas): se leen de la API v2
    con `NEON_API_KEY`/`NEON_PROJECT_ID` (env group `neon-api`, el mismo del drill) y son
    opcionales: sin esas variables el job corre igual y lo deja dicho en el mail.
    `GET /projects/{id}` trae `compute_time_seconds` (⇒ CU-horas del mes) y
    `GET /projects/{id}/branches` da el cupo de ramas. La API de consumo histórico sólo
    existe en planes pagos (en Free contesta 403), así que no se usa.
  * **C — consistencia con escritura controlada** (C.8–C.10): cierra la asistencia de las
    reservas de clases ya terminadas (sólo `asistencia_marcada_at` + `asistencia_via`,
    **sin** tocar `estado`: se conservan los KPIs de asistencia), resincroniza
    `clases.asistentes_confirmados` con el conteo real de reservas vivas y purga tokens de
    reset y notificaciones viejas. Van en **dos transacciones propias** con sus propios
    topes (`MAX_CIERRE`, `MAX_PURGA`), porque crecen con el volumen acumulado.
  * **E — reporte**: además de lo de la Fase 6, el MRR (misma definición que
    `app/services/metricas_service.py`: precio de lista de los planes vigentes), su
    variación contra el mes anterior, el churn/retención de la cohorte de 30 días (con
    `MIN_BASE_RETENCION`, el mismo umbral del BI) y las bajas del mes.
  * **F** (fuera de este módulo): el asunto del correo del watchdog de backups arranca con
    `[ALERTA]`, igual que el de este job.

Variables de entorno NUEVAS de la Fase 7 (todas con default, todas validadas antes de
tocar la base; los textos pasan por un charset seguro, así que no pueden cambiar el SQL):
`MAX_CIERRE` (500) · `MAX_PURGA` (5000) · `DIAS_CIERRE_RESERVAS` (7) ·
`DIAS_PURGA_TOKENS` (30) · `DIAS_PURGA_NOTIF` (180) · `CREDITOS_DESCUADRE_TOLERANCIA` (0) ·
`PROD_PERMITIDOS` (`demo.prod.%@example.com`) · `TENANT_ID` (1) · `MIN_BASE_RETENCION` (5) ·
`NEON_CU_HORAS_LIMITE` (100) · `NEON_CU_UMBRAL_PCT` (80) · `NEON_RAMAS_LIMITE` (10) ·
`NEON_API_BASE` (misma variable que usa `restore_drill.py`).
Además, `A5_NOTA_HASTA` (**opcional**, fecha ISO `AAAA-MM-DD`, sin default): mientras
`hoy <= A5_NOTA_HASTA` el log y el correo agregan junto a A.5(a) la nota "esperado en esta
etapa: aún no hay coaches asignados (desarrollo)", **sin silenciar la alerta** — el run sigue
rojo y el correo sigue saliendo. Pasada esa fecha (o sin la variable, o con la variable vacía)
la nota no se muestra y la detección queda exactamente como estaba. Una fecha inválida ⇒
`ConfigError` (exit 2).
Los dos roles siguen igual: `SELECT` de más tablas y `UPDATE`/`DELETE` **sólo** de las
columnas/tablas que la Fase 7 necesita (el SQL exacto está en el README).

Exit codes
----------
0 OK · 2 config (falta variable, URL con `-pooler`, usuario que no es `maint_rw`,
`ENVIRONMENT` ≠ production, entero fuera de rango) · 3 un `SELECT` de lectura falló ·
4 la integridad encontró problemas (run rojo; la escritura NO se aborta) · 9 las detecciones A.1–A.6 o el chequeo de Neon que
no pudo correr (rojo; la escritura NO se aborta) · 6 guarda de
volumen (en DRY-RUN informa y no aplica; en REAL aborta y no se aplica nada) ·
7 la transacción de escritura falló (nada quedó aplicado) · 8 la verificación posterior no
cuadró.

Uso:
    python -m maintenance.mantenimiento_cloud
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from maintenance.alertas import VARS_ALERTA, enviar_email  # Gmail SMTP (compartido)
from maintenance.backup_cloud import (  # helpers existentes: no se duplican
    correr,
    host_de,
    limpiar_valor,
    sanear,
)
# Paquete neutral (sin imports) compartido con la app: la lista de estados "cancelada" es UNA.
# `app/` sigue sin importarse: `shared/estados.py` no arrastra nada (lo copia Dockerfile.cron).
from shared.estados import (lista_sql, sql_fecha_en_chile, sql_plan_comercial,
                            sql_suscripcion_vigente)

# ── Códigos de salida (Render marca fallido el run si != 0) ──
EXIT_OK = 0
EXIT_CONFIG = 2        # falta variable / URL con -pooler / rol equivocado / ENVIRONMENT
EXIT_LECTURA = 3       # un SELECT falló (permisos, red, base)
EXIT_INTEGRIDAD = 4    # la integridad encontró problemas (rojo, sin abortar la escritura)
EXIT_GUARDA = 6        # se superó MAX_CAMBIOS ⇒ no se aplica nada
EXIT_ESCRITURA = 7     # la transacción de escritura falló (nada aplicado)
EXIT_VERIFICACION = 8  # la verificación posterior no cuadró
EXIT_DIAGNOSTICO = 9   # las detecciones A/B encontraron algo (rojo, sin abortar la escritura)

# Qué pasó, para el ASUNTO del correo (el detalle va en el cuerpo). El asunto arranca con
# `[ALERTA]` + el nombre del job: la notificación del teléfono ya dice qué pasó sin abrir el
# correo. Se usa `datos["estado"]` cuando la rama sabe más (números de la guarda, integridad).
TITULOS_EXIT = {
    EXIT_CONFIG: "configuración inválida",
    EXIT_LECTURA: "no se pudo leer la base",
    EXIT_INTEGRIDAD: "problemas de integridad",
    EXIT_GUARDA: "excede MAX_CAMBIOS",
    EXIT_ESCRITURA: "falló la transacción de escritura",
    EXIT_DIAGNOSTICO: "los chequeos nuevos encontraron algo",
    EXIT_VERIFICACION: "la verificación posterior no cuadró",
}

VARS_OBLIGATORIAS = (
    "MAINT_DB_URL",
    "ENVIRONMENT",
    *VARS_ALERTA,      # GMAIL_SMTP_USER + GMAIL_SMTP_APP_PASSWORD + ALERT_EMAIL
)

USUARIO_ROL = "maint_rw"           # el único rol con UPDATE sobre estas columnas
ENTORNO_ESPERADO = "production"    # guarda dura: este job escribe en PROD
TZ_CLT = "America/Santiago"        # mismo huso que el contenedor (Dockerfile.cron)
MAX_CAMBIOS_DEFECTO = 500           # tope GLOBAL de respaldo (las reglas finas están abajo)
MAX_CAMBIOS_RANGO = (1, 1000)      # el único camino por el que un número llega al SQL
# ── Guardas de volumen por regla (2026-09-27) ────────────────────────────────
# Un único tope global bloqueaba justo el día en que el volumen es esperable: los planes vencen
# el ÚLTIMO día del mes, así que el run del día 1 marca vencidos a TODOS los que no renovaron.
# Las huérfanas, en cambio, son pocas por definición: muchas = anomalía. Cada regla tiene su
# tope, `evaluar_limites()` las evalúa todas y `MAX_CAMBIOS` queda como respaldo del run.
MAX_VENCIDOS_PCT_DEFECTO = 80      # % máximo de las suscripciones activas que pueden vencer
MAX_VENCIDOS_PCT_RANGO = (1, 100)  # entero: la comparación se hace con enteros (sin floats)
MAX_HUERFANAS_DEFECTO = 10         # máximo POR CADA lista de huérfanas (0 = ninguna)
MAX_HUERFANAS_RANGO = (0, 1_000_000)
DIAS_PENDIENTE_DEFECTO = 7
NEON_LIMITE_MB_DEFECTO = 512       # free tier de Neon: 0,5 GB por proyecto
NEON_UMBRAL_PCT_DEFECTO = 80.0
# ── Fase 7 (2026-09-27) ──────────────────────────────────────────────────────
# Detecciones A (sólo lectura), límites del free tier de Neon (B), consistencia con
# escritura controlada C (cada paso con su propio tope, porque crecen con el volumen) y
# reporte E. Todo entra por env var validada: un número nunca llega al SQL sin pasar por
# `_entero()`/`_flotante()` y un texto nunca pasa si no es un patrón del charset seguro.
MAX_CIERRE_DEFECTO = 500            # pasos 8-9 (cierre de asistencia + aforo)
MAX_CIERRE_RANGO = (1, 100_000)
MAX_PURGA_DEFECTO = 5000            # paso 10 (tokens de reset + notificaciones)
MAX_PURGA_RANGO = (1, 1_000_000)
DIAS_CIERRE_RESERVAS_DEFECTO = 7    # antigüedad mínima de la clase para cerrar su asistencia
DIAS_PURGA_TOKENS_DEFECTO = 30      # retención de password_reset_tokens
DIAS_PURGA_NOTIF_DEFECTO = 180      # retención de notificaciones_enviadas
CREDITOS_TOLERANCIA_DEFECTO = 0     # descuadres tolerados por alumno (A.3)
PROD_PERMITIDOS_DEFECTO = "demo.prod.%@example.com"   # datos de demo intencionales (D-3)
TENANT_ID_DEFECTO = 1               # el box es uno: fija las consultas de MRR/churn (E)
MIN_BASE_RETENCION_DEFECTO = 5      # mismo umbral que app/services/metricas_service.py
NEON_CU_HORAS_DEFECTO = 100         # CU-horas del mes del plan Free (confirmar en Neon)
NEON_CU_UMBRAL_DEFECTO = 80.0
NEON_RAMAS_LIMITE_DEFECTO = 10      # ramas por proyecto en el plan Free
NEON_API_BASE_DEFECTO = "https://console.neon.tech/api/v2"   # igual que restore_drill
# Estados de `usuarios.estado` que el código escribe hoy (el modelo y `alumnos.py`). Cualquier
# otro valor es un hallazgo (A.1b): la columna es un `String(20)`, no un enum, así que la base
# no lo impide.
ESTADOS_USUARIO = ("activo", "pendiente_activacion", "rechazado", "baja")
# Regla ESPEJO de `app/api/v1/reservas.py` (DELETE /reservas/{id}): el crédito se devuelve
# sólo si faltan >= 6 h para la clase. Se repite acá porque el job no importa `app.*`.
HORAS_DEVOLUCION = 6
# ── Detecciones A: conteo REAL y nota de contexto de A.5(a) (2026-09-27) ──────
# Tope de filas de cada `modo="lista"`. El tope NO es el conteo: `detecciones()` lee el total real
# con `count(*) OVER ()` (la ventana se calcula después del WHERE y ANTES del LIMIT), así que el
# mail dice "63 fila(s)" y lista las primeras 25. Sin eso, A.5(a) y A.5(b) —que son complementarios
# por definición— se veían igual en 25/25 y no había forma de ver la magnitud real.
LIMITE_LISTA = 25
# Los dos topes que NO son de una detección A pero se leen igual (2026-09-27): el detalle de
# duplicados de `integridad()` y las suscripciones vigentes que evalúa A.3. El tope NO es el
# conteo: los dos se piden con `sql_con_total()` y, si recortan, el texto dice cuántas se muestran.
LIMITE_DUP = 10        # detalle de duplicados que viaja al correo (integridad)
LIMITE_A3 = 200        # suscripciones vigentes que evalúa A.3 en cada corrida
# A.5(a) marca en rojo las clases futuras sin coach de disciplinas que NO tienen ningún coach
# activo. En esta etapa (desarrollo) eso es ESPERABLE, así que `A5_NOTA_HASTA` (fecha ISO,
# opcional) agrega una nota visible al log y al correo JUNTO a A.5(a) mientras `hoy <= la fecha`.
# La alerta NO se silencia: el run sigue rojo y el correo sigue saliendo; la nota se quita sola.
A5_NOTA_TEXTO = ("Esperado en esta etapa: aún no hay coaches asignados a estas clases (desarrollo). "
                 "Asígnalos en la pantalla Coaches. Esta nota se quita sola el {fecha}.")


class ConfigError(RuntimeError):
    """Configuración inválida: se aborta ANTES de tocar la base (exit 2)."""


class LecturaError(RuntimeError):
    """Un SELECT de lectura falló (exit 3)."""


# ── Log (una sola implementación del saneo: la de backup_cloud) ──────────────
def log(msg: str) -> None:
    """Único punto de salida de texto: `sanear()` + prefijo propio del job.

    Se reutiliza `sanear()` de `backup_cloud` (misma red de seguridad para que ninguna
    credencial llegue al log) pero con el prefijo `[maint]`, para no confundir este run
    con el del backup en el log de Render.
    """
    print(f"[maint] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {sanear(msg)}", flush=True)


# ── Configuración (validada entera ANTES de tocar la base) ───────────────────
def _entero(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    """Lee una env var como entero VALIDADO. Es el único camino por el que un número de
    configuración se interpola en el SQL: nunca se pega texto crudo de una variable."""
    crudo = limpiar_valor(os.getenv(nombre) or "")
    if not crudo:
        return defecto
    try:
        valor = int(crudo)
    except ValueError:
        raise ConfigError(f"{nombre}={crudo!r} no es un entero") from None
    if not minimo <= valor <= maximo:
        raise ConfigError(f"{nombre}={valor} fuera de rango ({minimo}..{maximo})")
    return valor


def _flotante(nombre: str, defecto: float, minimo: float, maximo: float) -> float:
    crudo = limpiar_valor(os.getenv(nombre) or "")
    if not crudo:
        return defecto
    try:
        valor = float(crudo)
    except ValueError:
        raise ConfigError(f"{nombre}={crudo!r} no es un número") from None
    if not minimo <= valor <= maximo:
        raise ConfigError(f"{nombre}={valor} fuera de rango ({minimo}..{maximo})")
    return valor


def patron_like(patron: str) -> str:
    """Patrón para `LIKE ... ESCAPE '\\'`: `_` (comodín de UN carácter en LIKE) se escapa y
    `%` queda como comodín. `_allowlist()` ya garantizó que no hay comillas, así que el
    resultado no puede cerrar el literal SQL ni agregar tokens."""
    return patron.replace("_", "\\_")


def _allowlist(nombre: str, defecto: str) -> tuple:
    """Lee una env var de TEXTO con forma de lista de patrones LIKE separados por coma.

    Es el ÚNICO camino por el que texto de configuración llega al SQL. El charset es
    deliberadamente mínimo (ni comilla simple, ni backslash, ni punto y coma, ni paréntesis),
    así que por más que alguien escriba cualquier cosa en la variable, la cadena no puede
    cerrar el literal ni cambiar la consulta. Cualquier otra cosa ⇒ ConfigError (exit 2,
    antes de tocar la base).
    """
    crudo = limpiar_valor(os.getenv(nombre) or "")
    if not crudo:
        crudo = defecto
    patrones = tuple(p.strip() for p in crudo.split(",") if p.strip())
    for patron in patrones:
        if not re.fullmatch(r"[A-Za-z0-9._%@-]{3,120}", patron):
            raise ConfigError(
                f"{nombre}={patron!r} no es un patrón válido: sólo letras, números y . _ % @ -")
    return patrones


def _url_https(nombre: str, defecto: str) -> str:
    """URL https validada (`NEON_API_BASE`), con el mismo charset seguro de `_allowlist()`."""
    crudo = limpiar_valor(os.getenv(nombre) or "") or defecto
    if not re.fullmatch(r"https://[A-Za-z0-9._:/-]{3,120}", crudo):
        raise ConfigError(f"{nombre}={crudo!r} no es una URL https válida")
    return crudo.rstrip("/")


def _texto(nombre: str, defecto: str = "") -> str:
    """Lee una env var de TEXTO que NO se interpola en el SQL (hoy: las de la API de Neon).

    Mismo saneo que el resto (`limpiar_valor`): se limpian los espacios y el salto de línea
    que se pega al copiar la variable en el dashboard. El valor nunca se imprime (los errores
    de la API pasan por `sanear()`) y el que decide si está configurado es `neon_api_limites`.
    """
    return limpiar_valor(os.getenv(nombre) or "") or defecto


def _fecha_iso(nombre: str) -> date | None:
    """Lee una env var de FECHA ISO (`AAAA-MM-DD`) **opcional**: ausente o vacía ⇒ `None`.

    Es el único camino por el que una fecha de configuración llega al reporte, y es estricta a
    propósito: `date.fromisoformat()` acepta más formas desde Python 3.11 (p. ej. `20260927`),
    así que primero se exige el patrón `AAAA-MM-DD`. Cualquier otra cosa ⇒ `ConfigError` (exit 2)
    antes de tocar la base.
    """
    crudo = limpiar_valor(os.getenv(nombre) or "")
    if not crudo:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", crudo):
        raise ConfigError(f"{nombre}={crudo!r} no es una fecha ISO (AAAA-MM-DD)")
    try:
        return date.fromisoformat(crudo)
    except ValueError:
        raise ConfigError(f"{nombre}={crudo!r} no es una fecha válida") from None


def dry_run_activo() -> bool:
    """DRY_RUN=1 (o cualquier valor que no sea "0"/"false"/"no") ⇒ no se aplica nada.

    Misma regla y mismo default que `backup_cloud.py` (y `DRY_RUN=1` está también en la
    imagen `Dockerfile.cron`).
    """
    return (os.getenv("DRY_RUN", "1").strip().lower() not in ("0", "false", "no"))


def validar_url_maint(url: str) -> str:
    """Valida `MAINT_DB_URL`. Devuelve el MOTIVO del rechazo ('' = OK).

    Mismo criterio que `backup_cloud.validar_url()` pero para el rol de mantenimiento: el
    motivo describe la regla incumplida, nunca el valor del secreto. `backup_ro` NO se acepta
    acá a propósito: es sólo lectura y no puede escribir estas columnas.
    """
    if not url:
        return "está vacía"
    if not url.startswith("postgresql://"):
        return "no empieza con postgresql://"
    if url.count("@") != 1:
        return "no tiene exactamente un '@'"
    try:
        p = urlsplit(url)
        host, usuario = p.hostname, p.username
    except Exception:  # noqa: BLE001
        return "no se pudo parsear la URL"
    if not host:
        return "no se pudo parsear el host"
    if "-pooler." in host:
        return "incluye '-pooler' (se exige la conexión DIRECTA)"
    if usuario != USUARIO_ROL:
        return f"el usuario no es {USUARIO_ROL}"
    return ""


def leer_config() -> dict:
    """Config completa y validada. Lanza ConfigError (exit 2) antes de tocar la base.

    Es el **único** lugar del módulo que lee variables de entorno (directamente o por
    `_entero`/`_flotante`/`_allowlist`/`_url_https`/`_texto`): el resto del código recibe este
    dict, así que un número o un texto de configuración no puede llegar al SQL sin haber pasado
    por acá. Un valor no numérico, negativo o fuera de rango ⇒ exit 2 sin leer ni escribir nada.
    """
    falta = [v for v in VARS_OBLIGATORIAS if not limpiar_valor(os.getenv(v) or "")]
    if falta:
        raise ConfigError(f"faltan variables de entorno: {', '.join(falta)}")

    url = limpiar_valor(os.environ["MAINT_DB_URL"])
    motivo = validar_url_maint(url)
    if motivo:
        raise ConfigError(f"MAINT_DB_URL inválida: {motivo}")

    entorno = limpiar_valor(os.environ["ENVIRONMENT"]).lower()
    if entorno != ENTORNO_ESPERADO:
        raise ConfigError(
            f"ENVIRONMENT={entorno!r}: este job escribe en PROD y sólo corre con "
            f"{ENTORNO_ESPERADO!r}")

    return {
        "url": url,
        "entorno": entorno,
        "dry_run": dry_run_activo(),
        "max_cambios": _entero("MAX_CAMBIOS", MAX_CAMBIOS_DEFECTO, *MAX_CAMBIOS_RANGO),
        "max_vencidos_pct": _entero("MAX_VENCIDOS_PCT", MAX_VENCIDOS_PCT_DEFECTO,
                                    *MAX_VENCIDOS_PCT_RANGO),
        "max_huerfanas": _entero("MAX_HUERFANAS", MAX_HUERFANAS_DEFECTO, *MAX_HUERFANAS_RANGO),
        "dias_pendiente": _entero("DIAS_PENDIENTE", DIAS_PENDIENTE_DEFECTO, 1, 365),
        "neon_limite_mb": _entero("NEON_LIMITE_MB", NEON_LIMITE_MB_DEFECTO, 1, 1_000_000),
        "neon_umbral_pct": _flotante("NEON_UMBRAL_PCT", NEON_UMBRAL_PCT_DEFECTO, 1.0, 100.0),
        # ── Fase 7: topes propios de la consistencia (C), detecciones (A) y Neon (B) ──
        "max_cierre": _entero("MAX_CIERRE", MAX_CIERRE_DEFECTO, *MAX_CIERRE_RANGO),
        "max_purga": _entero("MAX_PURGA", MAX_PURGA_DEFECTO, *MAX_PURGA_RANGO),
        "dias_cierre": _entero("DIAS_CIERRE_RESERVAS", DIAS_CIERRE_RESERVAS_DEFECTO, 1, 3650),
        "dias_purga_tokens": _entero("DIAS_PURGA_TOKENS", DIAS_PURGA_TOKENS_DEFECTO, 1, 3650),
        "dias_purga_notif": _entero("DIAS_PURGA_NOTIF", DIAS_PURGA_NOTIF_DEFECTO, 1, 3650),
        "creditos_tolerancia": _entero("CREDITOS_DESCUADRE_TOLERANCIA",
                                       CREDITOS_TOLERANCIA_DEFECTO, 0, 100),
        # Nota de contexto de A.5(a) (opcional: sin la variable no hay nota ni se toca la alerta).
        "a5_nota_hasta": _fecha_iso("A5_NOTA_HASTA"),
        "permitidos": _allowlist("PROD_PERMITIDOS", PROD_PERMITIDOS_DEFECTO),
        "tenant_id": _entero("TENANT_ID", TENANT_ID_DEFECTO, 1, 100_000),
        "min_base_retencion": _entero("MIN_BASE_RETENCION",
                                      MIN_BASE_RETENCION_DEFECTO, 0, 10_000),
        "neon_cu_horas": _entero("NEON_CU_HORAS_LIMITE", NEON_CU_HORAS_DEFECTO, 1, 100_000),
        "neon_cu_umbral_pct": _flotante("NEON_CU_UMBRAL_PCT", NEON_CU_UMBRAL_DEFECTO, 1.0, 100.0),
        "neon_ramas_limite": _entero("NEON_RAMAS_LIMITE", NEON_RAMAS_LIMITE_DEFECTO, 1, 100),
        "neon_api_base": _url_https("NEON_API_BASE", NEON_API_BASE_DEFECTO),
        # Credenciales de la API de Neon (env group `neon-api`, opcional: sin ellas B.6/B.7
        # quedan "no configurados"). Entran por acá y no dentro de `neon_api_get()`: después de
        # esta función no queda ningún `os.getenv` suelto en el módulo.
        "neon_api_key": _texto("NEON_API_KEY"),
        "neon_project_id": _texto("NEON_PROJECT_ID"),
    }


# ── psql (lectura y escritura) ───────────────────────────────────────────────
SET_TZ = f"SET TIME ZONE '{TZ_CLT}'"
# Tags de comando que psql imprime en stdout y que NO son resultados de una consulta
# (`SET`, `BEGIN`, …). Se ignoran al parsear: así el módulo no depende de que `-q` los
# silencie ni de que `-tA` los saque (no lo hace: `-t` sólo apaga encabezados/footers).
TAGS_PSQL = frozenset({"SET", "BEGIN", "COMMIT", "ROLLBACK", "CREATE TABLE", "DO"})


def psql_leer(url: str, sql: str) -> list:
    """SELECT por `psql -tA -F '|'` ⇒ lista de filas (cada fila = lista de columnas).

    La zona horaria se fija en la MISMA sesión que la consulta (`SET TIME ZONE`), así
    `current_date` y `now() - interval` se calculan en hora de Chile igual que lo hacía el ORM
    del contenedor (`TZ=America/Santiago`): el servidor de Neon corre en UTC.
    """
    r = correr(["psql", url, "-tA", "-F", "|", "-c", f"{SET_TZ}; {sql}"])
    if r.returncode != 0:
        # sanear() acá y no sólo en log(): psql devuelve la URI COMPLETA (con password) en
        # el stderr cuando el connection string viene malformado.
        raise LecturaError(f"psql rc={r.returncode}: {sanear(r.stderr or '')[:300]}")
    filas = []
    for linea in (r.stdout or "").splitlines():
        texto = linea.strip()
        if texto == "" or texto in TAGS_PSQL or texto.startswith("INSERT 0 "):
            continue                                   # tag de comando, no un resultado
        filas.append([col.strip() for col in linea.split("|")])
    return filas


def psql_escalar(url: str, sql: str) -> str:
    """Primer valor de la primera fila ('' si no hay filas)."""
    filas = psql_leer(url, sql)
    return filas[0][0] if filas and filas[0] else ""


def psql_entero(url: str, sql: str) -> int:
    """Primer valor como int (0 si viene vacío). LecturaError si no es numérico."""
    crudo = psql_escalar(url, sql)
    try:
        return int(crudo or 0)
    except ValueError:
        raise LecturaError(f"esperaba un número y vino {crudo!r}") from None


def psql_script(url: str, script: str):
    """Corre un script SQL (UNA transacción) en un solo psql, con ON_ERROR_STOP.

    Nunca por un shell (`correr()` usa lista) y el archivo temporal se borra siempre. Se a
    propósito NO se usa `-q` (no hay que depender de que silencie los tags de comando): los
    tags que imprime psql (`BEGIN`, `SET`, `CREATE TABLE`, `INSERT 0 n`, `DO`, `ROLLBACK`…)
    no llevan `|`, así que `parsear_resumen()` los ignora y sólo lee las líneas `paso|n` del
    SELECT de resumen.
    """
    ruta = Path(tempfile.gettempdir()) / f"maint_cambios_{os.getpid()}.sql"
    try:
        ruta.write_text(script, encoding="utf-8")
        return correr(["psql", url, "-tA", "-F", "|", "-v", "ON_ERROR_STOP=1", "-f", str(ruta)])
    finally:
        try:
            ruta.unlink()
        except OSError:
            pass


def parsear_resumen(salida: str) -> dict:
    """Convierte las líneas `paso|n` del SELECT de resumen en {paso: n}.

    Ignora cualquier línea sin `|` (los tags de comando de psql, por ejemplo), así que
    funciona con o sin `-q`.
    """
    conteo = {}
    for linea in (salida or "").splitlines():
        linea = linea.strip()
        if "|" not in linea:
            continue
        paso, _, n = linea.partition("|")
        try:
            conteo[paso.strip()] = int((n or "0").strip() or 0)
        except ValueError:
            continue
    return conteo


# ── Consultas: las 4 listas de filas que cambiarían (y con las que se verifica) ──
def consultas_lista(dias_pendiente: int) -> list:
    """Las 4 listas del mantenimiento (id / alumno / plan / fecha / estado actual).

    Son la ÚNICA definición de "qué hay para cambiar": con estas mismas consultas se arma la
    lista del mail, se cuentan las filas y se verifica después de la transacción (se espera
    el mismo número en DRY-RUN y 0 en REAL), así que no puede pasar que el SQL de escritura
    y el de verificación se desincronicen. `dias_pendiente` es un entero ya validado.
    """
    dias = int(dias_pendiente)
    return [
        {
            "clave": "vencidos",
            "titulo": "Suscripciones activas con el plan vencido",
            "destino": "vencido",
            "cabeceras": ("id", "alumno", "plan", "fecha expiración", "estado actual"),
            "sql": (
                "SELECT s.id::text, COALESCE(u.nombre, '(sin usuario)'), "
                "COALESCE(p.nombre, '(sin plan)'), to_char(s.fecha_expiracion, 'YYYY-MM-DD'), "
                "s.estado::text "
                "FROM suscripciones s "
                "LEFT JOIN usuarios u ON u.id = s.usuario_id "
                "LEFT JOIN planes p ON p.id = s.plan_id "
                # El ÚLTIMO día del plan (hora de Chile) está vigente COMPLETO: se marca recién
                # desde el día siguiente. El cast es el MISMO de `sql_suscripcion_vigente()`, de la
                # guarda y del UPDATE, así que los cuatro no pueden divergir.
                "WHERE s.estado = 'activo' AND " + sql_fecha_en_chile("s.fecha_expiracion")
                + " < current_date "
                "ORDER BY s.fecha_expiracion, s.id"
            ),
        },
        {
            "clave": "huerfanas_suscripciones",
            "titulo": "Suscripciones pendientes hace más de los días de corte",
            "destino": "rechazado",
            "cabeceras": ("id", "alumno", "plan", "creada", "estado actual"),
            "sql": (
                "SELECT s.id::text, COALESCE(u.nombre, '(sin usuario)'), "
                "COALESCE(p.nombre, '(sin plan)'), to_char(s.created_at, 'YYYY-MM-DD'), "
                "s.estado::text "
                "FROM suscripciones s "
                "LEFT JOIN usuarios u ON u.id = s.usuario_id "
                "LEFT JOIN planes p ON p.id = s.plan_id "
                f"WHERE s.estado = 'pendiente' AND s.created_at < now() - interval '{dias} days' "
                "ORDER BY s.created_at, s.id"
            ),
        },
        {
            "clave": "huerfanas_solicitudes",
            "titulo": "Solicitudes de plan (comprobantes) pendientes viejas",
            "destino": "rejected",
            "cabeceras": ("id", "alumno", "plan", "creada", "estado actual"),
            "sql": (
                "SELECT sp.id::text, COALESCE(u.nombre, '(sin usuario)'), "
                "COALESCE(p.nombre, '(sin plan)'), to_char(sp.created_at, 'YYYY-MM-DD'), "
                "sp.estado "
                "FROM solicitudes_planes sp "
                "LEFT JOIN usuarios u ON u.id = sp.alumno_id "
                "LEFT JOIN planes p ON p.id = sp.plan_id "
                f"WHERE sp.estado = 'pending' AND sp.created_at < now() - interval '{dias} days' "
                "ORDER BY sp.created_at, sp.id"
            ),
        },
        {
            "clave": "huerfanas_usuarios",
            "titulo": "Usuarios que nunca completaron la activación",
            "destino": "rechazado (activo=false)",
            "cabeceras": ("id", "usuario", "correo", "creado", "estado actual"),
            "sql": (
                "SELECT u.id::text, u.nombre, u.correo, to_char(u.created_at, 'YYYY-MM-DD'), "
                "u.estado "
                "FROM usuarios u "
                "WHERE u.estado = 'pendiente_activacion' "
                f"AND u.created_at < now() - interval '{dias} days' "
                "ORDER BY u.created_at, u.id"
            ),
        },
    ]


# ── Consultas de integridad (las mismas de verificar_integridad.py, en SQL) ──
# Las dos primeras terminan en `LIMITE_DUP`: ese tope NO es el conteo (2026-09-27). Se leen con
# `sql_con_total()` y el hallazgo dice el total real + "(mostrando N de M)" si el tope recortó.
SQL_DUP_RUT = (
    "SELECT rut, count(*)::text FROM usuarios GROUP BY rut "
    f"HAVING count(*) > 1 ORDER BY count(*) DESC LIMIT {LIMITE_DUP}"
)
SQL_DUP_CORREO = (
    "SELECT correo, count(*)::text FROM usuarios GROUP BY correo "
    f"HAVING count(*) > 1 ORDER BY count(*) DESC LIMIT {LIMITE_DUP}"
)
SQL_SUSC_SIN_USUARIO = (
    "SELECT count(*)::text FROM suscripciones s "
    "LEFT JOIN usuarios u ON u.id = s.usuario_id WHERE u.id IS NULL"
)
SQL_SUSC_SIN_PLAN = (
    "SELECT count(*)::text FROM suscripciones s "
    "LEFT JOIN planes p ON p.id = s.plan_id WHERE p.id IS NULL"
)
SQL_FECHAS_INVALIDAS = (
    "SELECT count(*)::text FROM suscripciones WHERE fecha_expiracion < fecha_inicio"
)

# ── Consultas de Neon y del reporte mensual ──────────────────────────────────
SQL_USUARIOS = "SELECT count(*)::text FROM usuarios"
SQL_ALEMBIC = "SELECT version_num FROM alembic_version"
# Universo del paso de vencidos: las suscripciones que están en el estado que el paso evalúa
# ('activo'), ANTES de aplicarlo. Una sola definición, usada por (a) la lectura previa del job,
# (b) el reporte del mes y (c) la guarda del SQL: así los vencidos son un subconjunto de este
# universo y el % de MAX_VENCIDOS_PCT no puede pasar de 100.
SUSCRIPCIONES_ACTIVAS = "suscripciones WHERE estado = 'activo'"
SQL_SUSCRIPCIONES_ACTIVAS = f"SELECT count(*)::text FROM {SUSCRIPCIONES_ACTIVAS}"
SQL_TAMANO = "SELECT pg_database_size(current_database())::text"
SQL_TABLAS_TOP = (
    "SELECT relname, n_live_tup::text FROM pg_stat_user_tables "
    "ORDER BY n_live_tup DESC LIMIT 8"
)

# ══ Fase 7: SQL de las detecciones (A), la consistencia (C) y el reporte (E) ══
# Regla del proyecto que se repite en todo este bloque: el SQL es CONSTANTE salvo por
# números ya validados (`_entero`/`_flotante`) y patrones de allowlist del charset seguro.
# Ningún texto libre de una env var llega al SQL.
# ── Predicado "reserva viva" (2026-09-27) ────────────────────────────────────
# `reservas.estado` es un `character varying(20)` (default 'reserved') y en los datos conviven DOS
# formas de "cancelada": `'cancelled'` (la que escribe la app en el DELETE de
# `app/api/v1/reservas.py`) y `'cancelada'` (la del enum viejo `estado_reserva`). Comparar contra
# el literal `'cancelled'` dejaba a la otra pasando por viva: el paso 8 le escribiría
# `asistencia_marcada_at` **y `updated_at`** (el dato en el que se apoya toda la reconstrucción de
# A.3) y el paso 9 la contaría en el aforo.
# La lista es UNA sola y vive en `shared/estados.py` (`ESTADOS_CANCELADA`), la misma que usa la
# app: antes el job comparaba con `ILIKE '%cancel%'` y la app contra el literal, así que una
# variante nueva se comportaba distinto en cada lado. Lo que el `ILIKE` tapaba "por parecido"
# ahora lo vigila la detección **A.6** (rojo) contra esta misma lista. El dump de PROD del
# 24/09/2026 sólo tiene `'cancelled'` y `'confirmada'`: el cambio es equivalente, y es la red para
# la otra variante.
def sql_viva(alias: str = "r") -> str:
    """Predicado de "la reserva está viva": `estado NOT IN (ESTADOS_CANCELADA)`."""
    return f"{alias}.estado NOT IN ({lista_sql()})"


def sql_cancelada(alias: str = "r") -> str:
    """Predicado de "la reserva está cancelada" (la MISMA lista, en positivo)."""
    return f"{alias}.estado IN ({lista_sql()})"


def sql_demo(permitidos: tuple) -> str:
    """Predicado (alias `u`) de los correos de DEMO declarados en `PROD_PERMITIDOS`."""
    if not permitidos:
        return "false"
    return " OR ".join(f"u.correo LIKE '{patron_like(p)}' ESCAPE '\\'" for p in permitidos)


def sql_requiere_coach(alias: str = "d") -> str:
    """Predicado: "la disciplina de la clase EXIGE coach asignado" ⇒ `disciplinas.requiere_coach`.

    Es la columna la que decide, **nunca el nombre** de la disciplina (el nombre sólo aparece en
    el backfill que destilda la disciplina desde la pantalla Disciplinas del admin): las que no
    requieren coach —hoy "Musculación" y "Open Box", self-service— quedan fuera de A.5(a) y de
    A.5(b) por dato, no por texto. El `LEFT JOIN` deja la columna en NULL cuando la clase no tiene
    disciplina; eso se trata como "requiere" (= true), porque una clase sin disciplina tampoco
    tiene a quién asignarle un coach.
    """
    return f"COALESCE({alias}.requiere_coach, true)"


def sql_con_total(sql: str) -> str:
    """Prefija `count(*) OVER ()::text` a una consulta de lista: el TOTAL real del conjunto.

    La ventana se calcula **después del WHERE y antes del LIMIT**, así que el primer valor de la
    primera fila es el tamaño completo del hallazgo aunque la lista del mail traiga sólo
    `LIMITE_LISTA` filas. Sin esto, `n` era el tope (25) y dos conjuntos de 25 y de 2000 filas se
    reportaban igual (el 25/25 de A.5(a) vs A.5(b)).
    """
    if not sql.lstrip().upper().startswith("SELECT "):
        raise ValueError("sólo se puede pedir el total de un SELECT")
    return re.sub(r"^(\s*)SELECT ", r"\1SELECT count(*) OVER ()::text, ", sql, count=1)


def nota_a5(cfg: dict, hoy: date | None = None) -> str:
    """Nota de contexto de A.5(a); `""` si no corresponde mostrarla.

    **Pura**: sólo mira `cfg["a5_nota_hasta"]` y la fecha de hoy (inyectable para los tests). Se
    muestra mientras `hoy <= A5_NOTA_HASTA` (el mismo día incluido); con la variable ausente o ya
    pasada la fecha devuelve `""`, o sea la alerta queda exactamente como estaba. No silencia
    nada: el run sigue rojo y el correo sigue saliendo.
    """
    hasta = cfg.get("a5_nota_hasta")
    if not hasta:
        return ""
    if (hoy or date.today()) > hasta:
        return ""
    return A5_NOTA_TEXTO.format(fecha=hasta.isoformat())


def detecciones_sql(cfg: dict) -> tuple:
    """A.1–A.6 declaradas como datos (para el mail) + SQL. `modo`:
      * `escalar`: un conteo ⇒ hallazgo si ≠ 0.
      * `lista`:   filas ⇒ hallazgo si hay alguna (y van COMPLETAS al mail).
    `sev`: `rojo` (pone el run rojo, exit 9) o `info` (sólo informa, nunca cambia el exit).
    """
    estados = ", ".join(f"'{e}'" for e in ESTADOS_USUARIO)
    demo = sql_demo(cfg["permitidos"])
    dias = int(cfg["dias_cierre"])
    return (
        {
            "clave": "a1a_par_activo_estado",
            "titulo": "A.1(a) usuarios con el par `activo`/`estado` inconsistente",
            "sev": "rojo", "modo": "escalar",
            "detalle": ("usuario(s) donde `activo` no coincide con `(estado = 'activo')`. El "
                        "CHECK `ck_usuarios_activo_estado` de la 034 lo hace imposible: si sale "
                        "≠ 0, esa base no tiene el CHECK"),
            "sql": "SELECT count(*)::text FROM usuarios WHERE activo <> (estado = 'activo')",
        },
        {
            "clave": "a1b_estados_desconocidos",
            "titulo": "A.1(b) usuarios con un `estado` desconocido",
            "sev": "rojo", "modo": "lista",
            "cabeceras": ("id", "correo", "estado", "activo"),
            "detalle": ("usuario(s) con un `estado` fuera de la lista conocida "
                        f"({', '.join(ESTADOS_USUARIO)}): la columna es un String(20) y el "
                        "código sólo escribe esos cuatro valores"),
            "sql": ("SELECT id::text, COALESCE(correo, ''), estado, activo::text FROM usuarios "
                    f"WHERE estado NOT IN ({estados}) ORDER BY id LIMIT {LIMITE_LISTA}"),
        },
        {
            "clave": "a1c_demo",
            "titulo": "A.1(c) usuarios de DEMO en PROD (intencionales, D-3)",
            "sev": "info", "modo": "escalar",
            "detalle": (f"usuario(s) que matchean PROD_PERMITIDOS ({len(cfg['permitidos'])} "
                        "patrón(es)). Son los datos de demo de `seed_ml_data_prod.py`: "
                        "informativo, no es un problema de datos. Tras la defensa (6/10/2026) se "
                        "limpian y la allowlist queda vacía (README)"),
            "sql": f"SELECT count(*)::text FROM usuarios u WHERE {demo}",
        },
        {
            "clave": "a2a_aforo_desincronizado",
            "titulo": "A.2(a) clases con `asistentes_confirmados` distinto del conteo real",
            "sev": "rojo", "modo": "lista",
            "cabeceras": ("id", "fecha", "asistentes_confirmados", "reservas_vivas"),
            "detalle": ("clase(s) cuyo aforo publicado no coincide con sus reservas vivas: lo "
                        "resincroniza el paso 9 en esta misma corrida"),
            "sql": ("SELECT c.id::text, c.fecha::text, c.asistentes_confirmados::text, "
                    "(SELECT count(*) FROM reservas r WHERE r.clase_id = c.id "
                    f" AND {sql_viva()})::text "
                    "FROM clases c WHERE c.asistentes_confirmados <> "
                    "(SELECT count(*) FROM reservas r WHERE r.clase_id = c.id "
                    f" AND {sql_viva()}) ORDER BY c.fecha DESC, c.id LIMIT {LIMITE_LISTA}"),
        },
        {
            "clave": "a2b_reservas_duplicadas",
            "titulo": "A.2(b) reservas vivas duplicadas (mismo alumno y clase)",
            "sev": "rojo", "modo": "lista",
            "cabeceras": ("alumno_id", "clase_id", "reservas"),
            "detalle": "alumno(s) con más de una reserva viva en la misma clase (aforo inflado)",
            "sql": ("SELECT alumno_id::text, clase_id::text, count(*)::text FROM reservas r "
                    f"WHERE {sql_viva()} GROUP BY alumno_id, clase_id "
                    f"HAVING count(*) > 1 ORDER BY count(*) DESC LIMIT {LIMITE_LISTA}"),
        },
        {
            "clave": "a2c_sobrecupo",
            "titulo": "A.2(c) clases por encima del cupo",
            "sev": "rojo", "modo": "lista",
            "cabeceras": ("id", "fecha", "asistentes_confirmados", "cupo_maximo"),
            "detalle": "clase(s) con más asistentes confirmados que `cupo_maximo`",
            "sql": ("SELECT id::text, fecha::text, asistentes_confirmados::text, "
                    "cupo_maximo::text FROM clases WHERE cancelada = false "
                    f"AND asistentes_confirmados > cupo_maximo ORDER BY fecha DESC, id "
                    f"LIMIT {LIMITE_LISTA}"),
        },
        {
            "clave": "a4a_asistencia_pendiente",
            "titulo": "A.4(a) reservas de clases terminadas sin asistencia marcada",
            "sev": "info", "modo": "escalar",
            "detalle": (f"reserva(s) vivas de clases terminadas hace más de {dias} día(s) sin "
                        "`asistencia_marcada_at`: es normal que existan y el paso 8 las cierra "
                        "en esta misma corrida (informativo, NO pone el run rojo)"),
            "sql": (f"SELECT count(*)::text FROM reservas r WHERE {sql_viva()} "
                    f"AND r.asistencia_marcada_at IS NULL AND EXISTS (SELECT 1 FROM clases c "
                    f"WHERE c.id = r.clase_id AND (c.fecha + c.hora_fin) AT TIME ZONE '{TZ_CLT}' "
                    f"< now() - interval '{dias} days')"),
        },
        {
            "clave": "a4b_asistio_sin_auditoria",
            "titulo": "A.4(b) reservas con `asistio = true` sin registro de quién lo marcó",
            "sev": "rojo", "modo": "lista",
            "cabeceras": ("id", "clase_id", "alumno_id", "asistio"),
            "detalle": ("reserva(s) marcadas como asistidas sin `asistencia_marcada_at`: falta "
                        "el dato de auditoría de quién y cuándo"),
            "sql": ("SELECT id::text, clase_id::text, alumno_id::text, asistio::text FROM reservas "
                    f"WHERE asistio = true AND asistencia_marcada_at IS NULL ORDER BY id "
                    f"LIMIT {LIMITE_LISTA}"),
        },
        {
            "clave": "a5a_sin_coach_posible",
            "titulo": ("A.5(a) clases futuras sin coach de una disciplina que exige coach y sin "
                       "NINGÚN coach activo en ella"),
            "sev": "rojo", "modo": "lista",
            "cabeceras": ("id", "fecha", "hora_inicio", "disciplina"),
            "detalle": (f"clase(s) futuras con `coach_id` NULL de una disciplina que exige coach "
                        f"({sql_requiere_coach()}: las self-service —«Musculación», «Open Box»— "
                        "quedan fuera por dato) y que no tiene ningún coach activo en "
                        "`coach_disciplinas`: no hay a quién asignárselas"),
            "sql": ("SELECT c.id::text, c.fecha::text, c.hora_inicio::text, "
                    "COALESCE(d.nombre, '(sin disciplina)') FROM clases c "
                    "LEFT JOIN disciplinas d ON d.id = c.disciplina_id "
                    "WHERE c.coach_id IS NULL AND c.cancelada = false AND c.fecha >= current_date "
                    f"AND {sql_requiere_coach()} "
                    "AND NOT EXISTS (SELECT 1 FROM coach_disciplinas cd "
                    "  JOIN usuarios u ON u.id = cd.coach_id "
                    "  WHERE cd.disciplina_id = c.disciplina_id AND cd.activo = true "
                    "    AND u.rol::text = 'coach' AND u.activo = true) "
                    f"ORDER BY c.fecha, c.hora_inicio LIMIT {LIMITE_LISTA}"),
        },
        {
            "clave": "a5b_sin_coach_asignable",
            "titulo": "A.5(b) clases futuras sin coach, pero con coach disponible en la disciplina",
            "sev": "info", "modo": "lista",
            "cabeceras": ("id", "fecha", "hora_inicio", "disciplina"),
            "detalle": (f"clase(s) futuras con `coach_id` NULL de una disciplina que exige coach "
                        f"({sql_requiere_coach()}) y que SÍ tiene coach activo: falta asignarla "
                        "(informativo; D-2 lo sacó del rojo)"),
            "sql": ("SELECT c.id::text, c.fecha::text, c.hora_inicio::text, "
                    "COALESCE(d.nombre, '(sin disciplina)') FROM clases c "
                    "LEFT JOIN disciplinas d ON d.id = c.disciplina_id "
                    "WHERE c.coach_id IS NULL AND c.cancelada = false AND c.fecha >= current_date "
                    f"AND {sql_requiere_coach()} "
                    "AND EXISTS (SELECT 1 FROM coach_disciplinas cd "
                    "  JOIN usuarios u ON u.id = cd.coach_id "
                    "  WHERE cd.disciplina_id = c.disciplina_id AND cd.activo = true "
                    "    AND u.rol::text = 'coach' AND u.activo = true) "
                    f"ORDER BY c.fecha, c.hora_inicio LIMIT {LIMITE_LISTA}"),
        },
        {
            "clave": "a5c_coach_invalido",
            "titulo": "A.5(c) clases futuras con un coach que no es coach activo",
            "sev": "rojo", "modo": "lista",
            "cabeceras": ("id", "fecha", "coach_id", "rol", "activo"),
            "detalle": ("clase(s) futuras asignadas a un usuario que no es `coach` o que está "
                        "inactivo: la clase queda sin nadie que la tome"),
            "sql": ("SELECT c.id::text, c.fecha::text, c.coach_id::text, u.rol::text, "
                    "u.activo::text FROM clases c JOIN usuarios u ON u.id = c.coach_id "
                    "WHERE c.cancelada = false AND c.fecha >= current_date "
                    "AND (u.rol::text <> 'coach' OR u.activo = false) "
                    f"ORDER BY c.fecha, c.id LIMIT {LIMITE_LISTA}"),
        },
        # A.6 (2026-09-27): red que reemplaza al `ILIKE '%cancel%'` que tenía el predicado. Comparar
        # contra ESTADOS_CANCELADA es EXACTO (a propósito: nada de adivinar por parecido), así que
        # una variante que el job no conoce tiene que VERSE. Es rojo porque significa que el paso 8
        # le va a escribir `updated_at` a una reserva que en realidad estaba cancelada (el dato de
        # A.3) y el paso 9 la va a contar en el aforo, y porque el correo sólo sale cuando el run es
        # rojo: como `info` no se vería nunca.
        {
            "clave": "a6_cancelaciones_no_previstas",
            "titulo": "A.6 variantes de cancelación que el predicado no conoce",
            "sev": "rojo", "modo": "lista",
            "cabeceras": ("estado", "reservas"),
            "detalle": ("estado(s) de reserva que contienen \"cancel\" y NO están en "
                        f"ESTADOS_CANCELADA ({lista_sql()}): el predicado los trata como vivos "
                        "(el paso 8 les escribiría `updated_at` y el paso 9 los contaría en el "
                        "aforo). Se agrega el valor a `shared/estados.ESTADOS_CANCELADA` —y con "
                        "eso al SQL del job y a la app— o se corrige la fila: la lista es EXACTA "
                        "a propósito (no hay `LIKE` que adivine)"),
            "sql": (f"SELECT estado, count(*)::text FROM reservas r "
                    f"WHERE r.estado ILIKE '%cancel%' AND r.estado NOT IN ({lista_sql()}) "
                    f"GROUP BY estado ORDER BY count(*) DESC LIMIT {LIMITE_LISTA}"),
        },
    )


def sql_descuadre_creditos(cfg: dict) -> str:
    """A.3 — descuadre de créditos por suscripción VIGENTE (una sola por alumno).

    Cómo se verificó (2026-09-27) que `tokens_gastados` NO sirve como consumo: el DELETE de
    `app/api/v1/reservas.py` sólo escribe `estado='cancelled'` y `updated_at=now()` (nunca
    devuelve `tokens_gastados` a 0 — el dump de PROD tiene la reserva 1 `cancelled` con
    `tokens_gastados=1`), así que esa columna queda siempre en 1. Lo que SÍ refleja el consumo
    es `creditos_totales - creditos_disponibles`, y la devolución se puede reconstruir porque
    `updated_at` es el momento de la cancelación:

        consumo_esperado = reservas vivas de la ventana
                         + cancelaciones TARDÍAS (< {h} h antes de la clase: no hubo devolución)

    Las cancelaciones con >= {h} h se devolvieron (no consumen), así que restar las tardías evita
    el falso positivo que daba contar sólo reservas vivas. Se exige UNA sola suscripción vigente
    por alumno: con dos, el crédito pudo salir de la otra y la comparación no tendría sentido.
    Los dos conteos usan `sql_viva()`/`sql_cancelada()` (cualquier variante de "cancelada").

    **Limitación conocida (README §A.3)**: `updated_at` es a la vez el momento de la cancelación y
    el de cualquier otra edición de esa fila. Si alguien edita a mano una reserva ya cancelada, la
    cancelación "se mueve" y A.3 puede dar un descuadre falso (por eso la tolerancia es SIMÉTRICA).
    La solución de fondo es `reservas.cancelada_at`: está propuesta en el README, no implementada.

    **Tope y conteo (2026-09-27)**: la consulta termina en `LIMITE_A3` y ordena por `s.id`, así que
    el subconjunto evaluado es determinista. `descuadre_creditos()` la lee con `sql_con_total()`:
    `revisadas` es el total real de vigentes y `escaneadas` lo que entró por el tope. Antes el tope
    se leía como conteo ("revisadas 200" con 2000 vigentes).
    """
    h = int(HORAS_DEVOLUCION)
    return (
        "SELECT s.id::text, COALESCE(u.correo, ''), s.creditos_totales::text, "
        "s.creditos_disponibles::text, (s.creditos_totales - s.creditos_disponibles)::text, "
        "vivas.n::text, tardias.n::text "
        "FROM suscripciones s JOIN usuarios u ON u.id = s.usuario_id "
        "JOIN LATERAL (SELECT count(*) AS n FROM reservas r JOIN clases c ON c.id = r.clase_id "
        f"  WHERE r.alumno_id = s.usuario_id AND {sql_viva()} "
        "    AND c.fecha BETWEEN s.fecha_inicio::date AND s.fecha_expiracion::date) vivas ON true "
        "JOIN LATERAL (SELECT count(*) AS n FROM reservas r JOIN clases c ON c.id = r.clase_id "
        f"  WHERE r.alumno_id = s.usuario_id AND {sql_cancelada()} "
        "    AND c.fecha BETWEEN s.fecha_inicio::date AND s.fecha_expiracion::date "
        f"    AND r.updated_at > ((c.fecha + c.hora_inicio) AT TIME ZONE '{TZ_CLT}' "
        f"                        - interval '{h} hours')) tardias ON true "
        f"WHERE s.tenant_id = {int(cfg['tenant_id'])} AND s.estado = 'activo' "
        "  AND s.creditos_totales IS NOT NULL AND s.creditos_disponibles IS NOT NULL "
        "  AND s.fecha_inicio::date <= current_date AND s.fecha_expiracion::date >= current_date "
        "  AND (SELECT count(*) FROM suscripciones s2 WHERE s2.usuario_id = s.usuario_id "
        "       AND s2.estado = 'activo' AND s2.fecha_inicio::date <= current_date "
        "       AND s2.fecha_expiracion::date >= current_date) = 1 "
        f"ORDER BY s.id LIMIT {LIMITE_A3}"
    )


def consultas_cierre(cfg: dict) -> list:
    """Las 2 listas del paso 8-9 (se leen antes y se verifican después de su transacción).

    La del paso 9 lleva `"total": True`: es la única lista del correo que termina en
    `LIMITE_LISTA` (la del paso 8 va completa), así que su `n` se lee con `count(*) OVER ()` para
    que el tope no se confunda con el tamaño del conjunto (2026-09-27).
    """
    dias = int(cfg["dias_cierre"])
    return [
        {
            "clave": "cierre_asistencia",
            "titulo": "Reservas de clases terminadas sin asistencia marcada (paso 8)",
            "destino": "asistencia_marcada_at + asistencia_via='cierre' (el estado NO se toca)",
            "cabeceras": ("id", "clase", "fecha", "alumno", "estado actual"),
            "sql": ("SELECT r.id::text, c.id::text, c.fecha::text, "
                    "COALESCE(u.nombre, '(sin alumno)'), r.estado "
                    "FROM reservas r JOIN clases c ON c.id = r.clase_id "
                    "LEFT JOIN usuarios u ON u.id = r.alumno_id "
                    f"WHERE {sql_viva()} AND r.asistencia_marcada_at IS NULL "
                    f"AND (c.fecha + c.hora_fin) AT TIME ZONE '{TZ_CLT}' "
                    f"< now() - interval '{dias} days' ORDER BY c.fecha, r.id"),
        },
        {
            "clave": "aforo_resync",
            "titulo": "Clases con el aforo desincronizado de sus reservas (paso 9)",
            "destino": "asistentes_confirmados = reservas vivas",
            "cabeceras": ("id", "fecha", "asistentes_confirmados", "cupo_maximo",
                          "reservas_vivas"),
            "total": True,          # `n` = total real (la lista se corta en LIMITE_LISTA)
            "sql": ("SELECT c.id::text, c.fecha::text, c.asistentes_confirmados::text, "
                    "c.cupo_maximo::text, (SELECT count(*) FROM reservas r "
                    f"  WHERE r.clase_id = c.id AND {sql_viva()})::text "
                    "  AS reservas_vivas "
                    "FROM clases c WHERE c.asistentes_confirmados <> (SELECT count(*) "
                    f"  FROM reservas r WHERE r.clase_id = c.id AND {sql_viva()}) "
                    f"ORDER BY c.id LIMIT {LIMITE_LISTA}"),
        },
    ]


def consultas_purga(cfg: dict) -> list:
    """Las 2 listas del paso 10 (purga). Son las ÚNICAS tablas donde el rol tiene DELETE."""
    dias_tokens = int(cfg["dias_purga_tokens"])
    dias_notif = int(cfg["dias_purga_notif"])
    return [
        {
            "clave": "tokens_reset",
            "titulo": "Tokens de reset de contraseña vencidos o ya usados (paso 10)",
            "destino": f"DELETE (retención {dias_tokens} días)",
            "cabeceras": ("id", "usuario_id", "vence", "usado"),
            "sql": ("SELECT id::text, usuario_id::text, expires_at::text, "
                    "COALESCE(used_at::text, '-') FROM password_reset_tokens "
                    f"WHERE expires_at < now() - interval '{dias_tokens} days' "
                    f"   OR (used_at IS NOT NULL AND used_at < now() - interval '{dias_tokens} days') "
                    "ORDER BY id LIMIT 5000"),
        },
        {
            "clave": "notificaciones",
            "titulo": "Notificaciones enviadas viejas (paso 10)",
            "destino": f"DELETE (retención {dias_notif} días)",
            "cabeceras": ("id", "alumno_id", "tipo", "enviada", "estado"),
            "sql": ("SELECT id::text, alumno_id::text, tipo, fecha_envio::text, estado "
                    "FROM notificaciones_enviadas "
                    f"WHERE fecha_envio < now() - interval '{dias_notif} days' "
                    "ORDER BY fecha_envio LIMIT 5000"),
        },
    ]


# Mismo criterio que reporte_estadisticas.py. El corte del mes se arma en Python como
# 'YYYY-MM-DD'::date (nunca texto que venga de afuera) y se evalúa en la TZ de Chile.
SQL_REPORTE = {
    "total_alumnos": "SELECT count(*)::text FROM usuarios WHERE rol = 'alumno'",
    "alumnos_activos": "SELECT count(*)::text FROM usuarios WHERE rol = 'alumno' AND activo = true",
    "planes_activos": SQL_SUSCRIPCIONES_ACTIVAS,
    "planes_vencidos_mes": (
        "SELECT count(*)::text FROM suscripciones "
        "WHERE estado = 'vencido' AND updated_at >= '{ini}'::date"
    ),
    "nuevos_alumnos_mes": (
        "SELECT count(*)::text FROM usuarios "
        "WHERE rol = 'alumno' AND created_at >= '{ini}'::date"
    ),
    "ingresos_mes": (
        "SELECT COALESCE(sum(monto), 0)::text FROM transacciones_financieras "
        "WHERE tipo = 'ingreso' AND fecha >= '{ini}'::date"
    ),
    "ingresos_mes_anterior": (
        "SELECT COALESCE(sum(monto), 0)::text FROM transacciones_financieras "
        "WHERE tipo = 'ingreso' AND fecha >= '{ini_ant}'::date AND fecha < '{ini}'::date"
    ),
    # ── Fase 7 (E): MRR, retención/churn de la cohorte de 30 días y bajas del mes ──
    # Las MISMAS definiciones de `app/services/metricas_service.py` (una sola fórmula por
    # métrica): MRR = precio de lista de los planes con suscripción vigente EN LA FECHA;
    # retención = de los vigentes hace 30 días, cuántos siguen vigentes hoy (churn = 100 −
    # retención). El predicado de vigencia es `shared.estados.sql_suscripcion_vigente()` (el mismo
    # que usa la app): la vigencia la deciden las FECHAS, no `estado = 'activo'`.
    #
    # Fix 2026-09-27: antes estas 5 consultas filtraban por `estado = 'activo'`, que es el estado
    # de HOY. Vencida una suscripción hoy, el MRR del mes anterior y la cohorte de hace 30 días
    # perdían esa suscripción aunque estuviera vigente en esa fecha: la variación de MRR y el churn
    # del correo cambiaban solos con cada vencimiento. El estado ahora sólo descarta lo que NUNCA
    # estuvo vigente (`pendiente`/`rechazado`): una `vencido` SÍ cuenta para los meses en los que
    # estuvo vigente y una rechazada no suma nunca.
    # El alias de cada consulta (`AS mrr_hoy`, …) es el marcador que el doble de psql usa en
    # los tests para responderle a cada una: no se toca sin tocar el test.
    "mrr": (
        "SELECT COALESCE(sum(p.precio_clp), 0)::text AS mrr_hoy "
        "FROM suscripciones s JOIN planes p ON p.id = s.plan_id "
        "WHERE s.tenant_id = {tid} AND " + sql_suscripcion_vigente("s", "current_date") +
        " AND " + sql_plan_comercial("p")
    ),
    "mrr_mes_anterior": (
        "SELECT COALESCE(sum(p.precio_clp), 0)::text AS mrr_mes_anterior "
        "FROM suscripciones s JOIN planes p ON p.id = s.plan_id "
        "WHERE s.tenant_id = {tid} AND " + sql_suscripcion_vigente("s", "'{fin_ant}'::date") +
        " AND " + sql_plan_comercial("p")
    ),
    "alumnos_vigentes": (
        "SELECT count(*)::text AS alumnos_vigentes FROM usuarios u "
        "WHERE u.tenant_id = {tid} AND u.rol = 'alumno' AND u.activo = true "
        "AND EXISTS (SELECT 1 FROM suscripciones s "
        "  JOIN planes p ON p.id = s.plan_id WHERE s.usuario_id = u.id "
        "  AND s.tenant_id = {tid} AND " + sql_suscripcion_vigente("s", "current_date") +
        "  AND " + sql_plan_comercial("p") + ")"
    ),
    "bajas_mes": (
        "SELECT count(*)::text AS bajas_mes FROM usuarios WHERE tenant_id = {tid} "
        "AND rol = 'alumno' AND fecha_baja IS NOT NULL AND fecha_baja >= '{ini}'::date"
    ),
    "retencion_base": (
        "SELECT count(*)::text AS retencion_base FROM usuarios u "
        "WHERE u.tenant_id = {tid} AND u.rol = 'alumno' AND u.activo = true "
        "AND EXISTS (SELECT 1 FROM suscripciones s "
        "  JOIN planes p ON p.id = s.plan_id WHERE s.usuario_id = u.id "
        "  AND s.tenant_id = {tid} AND " + sql_suscripcion_vigente("s", "'{hace30}'::date") +
        "  AND " + sql_plan_comercial("p") + ")"
    ),
    "retencion_siguen": (
        "SELECT count(*)::text AS retencion_siguen FROM usuarios u "
        "WHERE u.tenant_id = {tid} AND u.rol = 'alumno' AND u.activo = true "
        "AND EXISTS (SELECT 1 FROM suscripciones s "
        "  JOIN planes p ON p.id = s.plan_id WHERE s.usuario_id = u.id "
        "  AND s.tenant_id = {tid} AND " + sql_suscripcion_vigente("s", "'{hace30}'::date") +
        "  AND " + sql_plan_comercial("p") + ") "
        "AND EXISTS (SELECT 1 FROM suscripciones s2 "
        "  JOIN planes p2 ON p2.id = s2.plan_id WHERE s2.usuario_id = u.id "
        "  AND s2.tenant_id = {tid} AND " + sql_suscripcion_vigente("s2", "current_date") +
        "  AND " + sql_plan_comercial("p2") + ")"
    ),
}


# ── Lecturas: listas, integridad, uso de Neon y reporte del mes ──────────────
def leer_listas(url: str, consultas: list) -> list:
    """Las listas de UNA fase, leídas ANTES de su transacción (es lo que muestra el mail).

    Se le pasan las consultas hechas (`consultas_lista`, `consultas_cierre`,
    `consultas_purga`): así el SQL de escritura, el de la lista del mail y el de la
    verificación posterior salen SIEMPRE de la misma definición y no pueden divergir.

    Si la consulta declara `"total": True`, el `n` es el **total real** del conjunto
    (`count(*) OVER ()`, la ventana se calcula ANTES del `LIMIT`) y `mostradas` dice cuántas filas
    vinieron en la lista: el tope no es el conteo (2026-09-27). `verificar()` sigue releyendo
    `consulta["sql"]` sin la ventana y con el mismo tope, así que la comparación de después
    (0 en REAL / el mismo número en DRY-RUN) no cambia.
    """
    listas = []
    for consulta in consultas:
        if consulta.get("total"):
            crudas = psql_leer(url, sql_con_total(consulta["sql"]))
            # La 1ª columna es el total del conjunto; NO es una columna de la lista (las cabeceras
            # del correo no la llevan). Sin filas no hay total que leer ⇒ 0.
            total = _int_o_cero(crudas[0][0]) if crudas else 0
            filas = [f[1:] for f in crudas]
            limpia = {k: v for k, v in consulta.items() if k != "total"}
            listas.append({**limpia, "filas": filas, "n": total, "mostradas": len(filas)})
            continue
        filas = psql_leer(url, consulta["sql"])
        listas.append({**consulta, "filas": filas, "n": len(filas)})
    return listas


def _duplicados(url: str, sql: str, etiqueta: str) -> str | None:
    """Hallazgo de duplicados con el TOTAL real, o `None` si no hay ninguno.

    `SQL_DUP_RUT`/`SQL_DUP_CORREO` cortan en `LIMITE_DUP`, así que contar las filas devueltas era
    reportar el tope (2026-09-27: el mismo defecto que tenía A.5). Con `count(*) OVER ()`
    (`sql_con_total`) el texto dice el total y, si el tope recortó, cuántas filas se muestran:
    "RUT duplicados (37) (mostrando 10 de 37): …". Sin recorte el texto es el de antes.
    """
    crudas = psql_leer(url, sql_con_total(sql))
    total = _int_o_cero(crudas[0][0]) if crudas else 0
    if not total:
        return None
    filas = [f[1:] for f in crudas]
    detalle = ", ".join(f"{r[0]} x{r[1]}" for r in filas[:LIMITE_DUP])
    corte = f" (mostrando {len(filas)} de {total})" if len(filas) < total else ""
    return f"{etiqueta} ({total}){corte}: {detalle}"


def integridad(url: str) -> list:
    """Los 5 chequeos de `verificar_integridad.py`, contra PROD. Devuelve los hallazgos.

    Un hallazgo NO aborta el mantenimiento (decisión del 2026-09-27): pone el run en rojo
    (exit 4) y lo cuenta en el mail. Los datos no se tocan por un problema detectado.
    """
    hallazgos = []

    for etiqueta, sql in (("RUT duplicados", SQL_DUP_RUT),
                          ("Correos duplicados", SQL_DUP_CORREO)):
        if hallazgo := _duplicados(url, sql, etiqueta):
            hallazgos.append(hallazgo)

    for etiqueta, sql in (
        ("Suscripciones con usuario inexistente", SQL_SUSC_SIN_USUARIO),
        ("Suscripciones con plan inexistente", SQL_SUSC_SIN_PLAN),
        ("Suscripciones con expiración anterior al inicio", SQL_FECHAS_INVALIDAS),
    ):
        n = psql_entero(url, sql)
        if n:
            hallazgos.append(f"{etiqueta}: {n}")
    return hallazgos


def descuadre_creditos(url: str, cfg: dict) -> dict:
    """A.3: compara los créditos gastados con el consumo reconstruido desde las reservas.

    Es hallazgo si el descuadre es NEGATIVO (se gastaron más créditos de los que pudieron
    gastarse: eso sólo se explica por una escritura de créditos que no corresponde) o si
    supera `CREDITOS_DESCUADRE_TOLERANCIA` (se gastaron menos: devoluciones de más, o
    cancelaciones en plazo que la app no devolvió porque el plan ya estaba vencido al
    cancelar). La tolerancia existe para el segundo caso: si una corrida reporta descuadres
    hacia arriba por ediciones de staff sobre reservas ya canceladas (`updated_at` se corre y
    la cancelación parece tardía), se sube la variable y listo.

    `revisadas` es el **total real** de vigentes evaluadas (`count(*) OVER ()`, sin el tope) y
    `escaneadas` las que entraron por `LIMITE_A3`: cuando son distintos, el informe del correo lo
    dice (2026-09-27).
    """
    crudas = psql_leer(url, sql_con_total(sql_descuadre_creditos(cfg)))
    # 1ª columna = total del conjunto (la ventana se calcula ANTES del LIMIT): es `revisadas`.
    revisadas = _int_o_cero(crudas[0][0]) if crudas else 0
    filas = [f[1:] for f in crudas]
    tol = int(cfg["creditos_tolerancia"])
    hallazgos, detalle = [], []
    for fila in filas:
        fila = (list(fila) + [""] * 7)[:7]
        sid, correo, totales, disponibles, consumidos, vivas, tardias = fila
        esperados = _int_o_cero(vivas) + _int_o_cero(tardias)
        descuadre = _int_o_cero(consumidos) - esperados
        if abs(descuadre) <= tol:
            continue
        sentido = ("gastó MÁS créditos de los que justifican sus reservas" if descuadre > 0
                   else "gastó MENOS (devolución de más)")
        hallazgos.append(
            f"A.3 suscripción {sid} ({correo or '(sin correo)'}) {sentido}: "
            f"{consumidos} de {totales} (esperados {esperados} = {vivas} reservas vivas + "
            f"{tardias} cancelaciones tardías), quedan {disponibles}")
        detalle.append(fila)
    return {
        "hallazgos": hallazgos,
        "tabla": {
            "clave": "a3_creditos_descuadre",
            "titulo": "A.3 descuadre de créditos por suscripción vigente",
            "cabeceras": ("suscripción", "correo", "totales", "disponibles", "gastados",
                          "reservas_vivas", "cancelaciones_tardias"),
            "destino": "", "filas": detalle, "n": len(detalle), "mostradas": len(detalle),
            "detalle": f"descuadre fuera de 0..{tol}",
        },
        "revisadas": revisadas, "escaneadas": len(filas), "tolerancia": tol,
    }


def detecciones(url: str, cfg: dict) -> dict:
    """A.1–A.6 en marcha: lee cada consulta y separa hallazgos (rojo) de informes (info).

    Devuelve `{"hallazgos", "informes", "listas", "nota_a5"}`. Un hallazgo NO aborta el
    mantenimiento (igual que la integridad): pone el run rojo (exit 9) y viaja al mail con la
    lista completa. Los informes sólo aparecen en el mail y NO cambian el exit code.

    El `n` de cada lista es el **total real** de la consulta (`count(*) OVER ()`, que se calcula
    antes del `LIMIT`), no el número de filas que viajan al mail: por eso `mostradas` existe. El
    tope de la lista (`LIMITE_LISTA`, 25) capaba el conteo y hacía invisibles los conjuntos
    grandes (el 25/25 de A.5(a) vs A.5(b), que son complementarios por construcción).

    `nota_a5` es la nota de contexto de A.5(a) (`A5_NOTA_HASTA`), y sólo se calcula cuando esa
    detección tiene filas: si no hay nada que explicar, no hay nota.
    """
    hallazgos, informes, listas = [], [], []
    for chequeo in detecciones_sql(cfg):
        if chequeo["modo"] == "escalar":
            n = psql_entero(url, chequeo["sql"])
            if n:
                texto = f"{chequeo['titulo']}: {n} — {chequeo['detalle']}"
                (hallazgos if chequeo["sev"] == "rojo" else informes).append(texto)
            continue
        crudas = psql_leer(url, sql_con_total(chequeo["sql"]))
        # La 1ª columna es el total del conjunto; NO es una columna de la lista (las cabeceras del
        # mail no la llevan). Sin filas no hay total que leer ⇒ 0.
        total = _int_o_cero(crudas[0][0]) if crudas else 0
        filas = [f[1:] for f in crudas]
        listas.append({"clave": chequeo["clave"], "titulo": chequeo["titulo"],
                       "cabeceras": chequeo["cabeceras"], "destino": "", "sev": chequeo["sev"],
                       "detalle": chequeo["detalle"], "filas": filas, "n": total,
                       "mostradas": len(filas)})
        if total:
            texto = f"{chequeo['titulo']}: {total} fila(s) — {chequeo['detalle']}"
            (hallazgos if chequeo["sev"] == "rojo" else informes).append(texto)

    creditos = descuadre_creditos(url, cfg)
    # `revisadas` es el total real; si el tope de A.3 dejó vigentes afuera, se dice (el subconjunto
    # evaluado es siempre el mismo: la consulta ordena por `s.id`).
    corte_a3 = (f" (se evaluaron {creditos['escaneadas']}: el tope de A.3 ({LIMITE_A3}) deja el "
                "resto para la próxima corrida)"
                if creditos["revisadas"] > creditos["escaneadas"] else "")
    informes.append(f"A.3 suscripciones vigentes revisadas: {creditos['revisadas']}{corte_a3} "
                    f"(tolerancia {creditos['tolerancia']})")
    hallazgos.extend(creditos["hallazgos"])
    if creditos["tabla"]["n"]:
        listas.append(creditos["tabla"])
    con_a5a = any(c["clave"] == "a5a_sin_coach_posible" and c["n"] for c in listas)
    return {"hallazgos": hallazgos, "informes": informes, "listas": listas,
            "nota_a5": nota_a5(cfg) if con_a5a else ""}


def neon_api_get(cfg: dict, ruta: str, timeout: int = 20) -> dict:
    """GET a la API v2 de Neon (sólo lectura, con `urllib` de la stdlib).

    No se importa `restore_drill`: cada Cron Job tiene que poder fallar sin arrastrar al otro
    (el drill crea y borra ramas; este job lee dos endpoints y nada más). La base y la API key
    vienen en el `cfg` validado (nada de `os.getenv` acá) y la key no se imprime ni se devuelve:
    los errores pasan por `sanear()`.
    Devuelve `{"ok": bool, "status": int, "datos": dict, "error": str}`.
    """
    base = cfg["neon_api_base"]
    api_key = cfg["neon_api_key"]
    req = urllib.request.Request(
        f"{base}{ruta}", method="GET",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo = r.read().decode("utf-8", "replace")
            return {"ok": True, "status": r.status,
                    "datos": (json.loads(crudo) if crudo.strip() else {}), "error": ""}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "datos": {},
                "error": f"HTTP {e.code}: {sanear(e.reason or '')}"}
    except Exception as e:  # noqa: BLE001 (red, DNS, TLS, JSON roto: todo se reporta igual)
        return {"ok": False, "status": 0, "datos": {},
                "error": f"{type(e).__name__}: {sanear(e)}"[:300]}


def neon_api_limites(cfg: dict) -> dict:
    """B.6 (CU-horas del mes) y B.7 (cupo de ramas) contra la API v2 de Neon.

    Sin `NEON_API_KEY`/`NEON_PROJECT_ID` (env group `neon-api`, el mismo que usa el drill) los
    dos chequeos quedan "no configurados": el job corre igual y lo deja dicho en el mail. Con
    las variables puestas y la API caída, en cambio, ES un hallazgo (exit 9): un chequeo
    configurado que no corre tiene que verse, no callarse.

    Los dos AVISOS (CU-horas arriba del umbral y ramas en el tope) no abortan nada y no cambian
    el exit code: igual que la alerta de almacenamiento de la Fase 6, son un correo para mirar
    antes de que Neon corte el servicio. `compute_time_seconds` son los segundos de CPU del
    mes ⇒ CU-horas = segundos / 3600 (1 CU-hora = 3600 s de CPU a 1 CU). Si la API no trae ese
    campo se usa `cpu_used_sec` (mismo significado, nombre viejo) en vez de informar 0.
    """
    api_key = cfg["neon_api_key"]
    proyecto = cfg["neon_project_id"]
    faltan = [n for n, v in (("NEON_API_KEY", api_key),
                             ("NEON_PROJECT_ID", proyecto)) if not v]
    if faltan:
        return {"configurado": False, "alerta": False, "hallazgos": [], "avisos": [],
                "nota": f"no configurado (faltan {', '.join(faltan)}): B.6/B.7 no se chequean"}
    if not re.fullmatch(r"[a-z0-9-]{1,60}", proyecto):
        return {"configurado": True, "alerta": True, "avisos": [],
                "hallazgos": ["B.6/B.7 NEON_PROJECT_ID no tiene forma de id de proyecto"]}

    datos = {"configurado": True, "alerta": False, "hallazgos": [], "avisos": [],
             "proyecto": proyecto}
    r = neon_api_get(cfg, f"/projects/{proyecto}")
    if not r["ok"]:
        datos["alerta"] = True
        datos["hallazgos"].append(
            f"B.6/B.7 no se pudo leer el proyecto en la API de Neon: {r['error']}")
        return datos

    j = r["datos"].get("project") or {}
    segundos = j.get("compute_time_seconds")
    fuente = "compute_time_seconds"
    if segundos is None:
        segundos, fuente = j.get("cpu_used_sec"), "cpu_used_sec"
    limite = float(cfg["neon_cu_horas"])
    if segundos is None:
        datos["cu"] = {"horas": None, "limite": limite, "pct": None, "alerta": False,
                       "nota": "la API no devolvió compute_time_seconds ni cpu_used_sec"}
    else:
        horas = round(float(segundos) / 3600.0, 2)
        pct = round(horas / limite * 100.0, 2) if limite else 0.0
        en_alerta = pct >= float(cfg["neon_cu_umbral_pct"])
        datos["cu"] = {"horas": horas, "limite": limite, "pct": pct, "fuente": fuente,
                       "alerta": en_alerta}
        if en_alerta:
            datos["alerta"] = True
            datos["avisos"].append(
                f"B.6 CU-horas del mes al {pct}% ({horas} de {limite:.0f} h, umbral "
                f"{cfg['neon_cu_umbral_pct']}%): revisar Neon → Projects → Usage")

    # Lo que viene en el MISMO JSON, sin pedir nada extra: tipo de plan y bytes del mes.
    datos["plan"] = (j.get("owner") or {}).get("subscription_type")
    datos["bytes"] = {k: j.get(k) for k in
                      ("data_transfer_bytes", "written_data_bytes", "data_storage_bytes_hour")}

    r = neon_api_get(cfg, f"/projects/{proyecto}/branches")
    if not r["ok"]:
        datos["alerta"] = True
        datos["hallazgos"].append(f"B.7 no se pudo listar las ramas del proyecto: {r['error']}")
        return datos
    ramas = r["datos"].get("branches") or []
    tope = int(cfg["neon_ramas_limite"])
    en_alerta = len(ramas) >= tope
    datos["ramas"] = {"n": len(ramas), "limite": tope, "alerta": en_alerta,
                      "nombres": [b.get("name") or "?" for b in ramas]}
    if en_alerta:
        datos["alerta"] = True
        datos["avisos"].append(
            f"B.7 el proyecto tiene {len(ramas)} ramas (tope del plan Free: {tope}): el drill "
            "mensual no va a poder crear la suya hasta liberar una")
    return datos


def _int_o_cero(crudo: str) -> int:
    try:
        return int((crudo or "0").strip() or 0)
    except ValueError:
        return 0


def neon_uso(url: str, limite_mb: int, umbral_pct: float) -> dict:
    """Tamaño real de la base + top de tablas, contra `NEON_LIMITE_MB` (free: 0,5 GB).

    Es el mismo cálculo de `neon_usage_alerts.py` pero con el límite correcto del plan Free
    (por proyecto, no los 3 GB que decía la versión vieja) y en MB, que es la unidad en la
    que Neon factura el almacenamiento.
    """
    bytes_bd = psql_entero(url, SQL_TAMANO)
    mb = bytes_bd / (1024 * 1024)
    pct = (mb / limite_mb * 100.0) if limite_mb else 0.0
    top = [(f[0], _int_o_cero(f[1] if len(f) > 1 else "0"))
           for f in psql_leer(url, SQL_TABLAS_TOP)]
    return {"mb": round(mb, 2), "pct": round(pct, 2), "limite_mb": limite_mb,
            "umbral_pct": umbral_pct, "top": top, "alerta": pct >= umbral_pct}


# Fase 7: además del reporte de la Fase 6, el MISMO run agrega MRR, variación de MRR,
# retención/churn de la cohorte de 30 días y bajas del mes (bloque E del diseño).
def reporte_mes(url: str, cfg: dict) -> dict:
    """Las mismas métricas de `reporte_estadisticas.py` (sin escribir el JSON local).

    No se escribe ningún archivo: en un Cron Job de Render el filesystem es efímero, así
    que el "reporte" es el mail (y el log).
    """
    hoy = date.today()
    ini = hoy.replace(day=1)
    ini_ant = (ini - timedelta(days=1)).replace(day=1)
    fin_ant = ini - timedelta(days=1)      # último día del mes anterior (MMR de referencia)
    hace30 = hoy - timedelta(days=30)      # cohorte de retención: igual que el BI
    datos = {}
    for clave, plantilla in SQL_REPORTE.items():
        crudo = psql_escalar(url, plantilla.format(
            ini=ini.isoformat(), ini_ant=ini_ant.isoformat(), fin_ant=fin_ant.isoformat(),
            hace30=hace30.isoformat(), tid=int(cfg["tenant_id"])))
        datos[clave] = (float(crudo or 0)
                        if clave.startswith(("ingresos", "mrr")) else _int_o_cero(crudo))

    previo = datos["ingresos_mes_anterior"]
    datos["variacion_ingresos_pct"] = (
        round((datos["ingresos_mes"] - previo) / previo * 100, 2) if previo else None)
    mrr_previo = datos["mrr_mes_anterior"]
    datos["variacion_mrr_pct"] = (
        round((datos["mrr"] - mrr_previo) / mrr_previo * 100, 2) if mrr_previo else None)

    # Retención/churn con el MISMO umbral de base que el BI (`MIN_BASE_RETENCION`): con una
    # base chica el porcentaje no representa al box (el bug del 7600 % del 2026-09), así que
    # se publica "sin dato" en vez de un número que no significa nada.
    base = datos.pop("retencion_base")
    siguen = datos.pop("retencion_siguen")
    minimo = int(cfg["min_base_retencion"])
    if base >= minimo:
        datos["retencion_30d_pct"] = round(siguen / base * 100)
        datos["churn_30d_pct"] = round(100 - datos["retencion_30d_pct"], 2)
    else:
        datos["retencion_30d_pct"] = None
        datos["churn_30d_pct"] = None
        datos["churn_nota"] = f"sin dato: base {base} < MIN_BASE_RETENCION {minimo}"
    datos["mes"] = ini.isoformat()
    return datos


# ── Escritura: UNA transacción con los 4 UPDATE ──────────────────────────────
MARCA_GUARDA = "GUARDA DE VOLUMEN"


# ── Reglas de volumen: evaluación PURA (conteos + config → reglas) ────────────
# El freno no puede ser un único tope global: el día 1 vencen los planes de todos los que no
# renovaron (volumen ESPERABLE: todo plan vence el último día del mes) y las huérfanas tienen
# que ser pocas (volumen ANÓMALO). Todo se decide acá, sin base, sin reloj y sin entorno, así
# que las reglas se testean sin dobles de psql.
HUERFANAS = ("huerfanas_suscripciones", "huerfanas_solicitudes", "huerfanas_usuarios")


def evaluar_limites(conteos: dict, cfg: dict) -> list:
    """TODAS las reglas de volumen, en orden fijo, con su conteo, su tope y si se pasaron.

    `conteos` son los números del run:

        {"vencidos": n, "huerfanas_suscripciones": n, "huerfanas_solicitudes": n,
         "huerfanas_usuarios": n, "total": n, "suscripciones_activas": n}

    `cfg` es la config YA validada de `leer_config()`: de acá sólo se leen `max_vencidos_pct`,
    `max_huerfanas` y `max_cambios` (los números no se vuelven a leer del entorno).

    Devuelve las 5 reglas SIEMPRE (no sólo las que se pasaron) porque el log y el correo tienen
    que mostrar cada una con su conteo y su tope; las excedidas se obtienen con
    `limites_excedidos()`. Cada regla es `{regla, variable, conteo, limite, detalle, excedido}`.

    El % se compara con ENTEROS (`vencidos * 100 > activas * pct`) para no depender del redondeo
    de un float, y el denominador es el universo del propio paso de vencidos (`suscripciones` en
    el estado que ese paso evalúa, ANTES de aplicar) ⇒ los vencidos son un subconjunto y el
    porcentaje nunca pasa de 100 (con `MAX_VENCIDOS_PCT=100` no hay forma de que corte).
    """
    activas = int(conteos.get("suscripciones_activas") or 0)
    pct = int(cfg["max_vencidos_pct"])
    vencidos = int(conteos.get("vencidos") or 0)
    max_huerfanas = int(cfg["max_huerfanas"])
    total = int(conteos.get("total") or 0)
    max_cambios = int(cfg["max_cambios"])

    reglas = []
    for clave in HUERFANAS:
        n = int(conteos.get(clave) or 0)
        reglas.append({
            "regla": f"MAX_HUERFANAS:{clave}", "variable": "MAX_HUERFANAS",
            "conteo": n, "limite": max_huerfanas,
            "detalle": f"{n} huérfana(s) en {clave.replace('huerfanas_', '')}",
            "excedido": n > max_huerfanas,
        })
    reglas.append({
        "regla": "MAX_VENCIDOS_PCT", "variable": "MAX_VENCIDOS_PCT",
        "conteo": vencidos, "limite": activas * pct // 100,
        "detalle": (f"{vencidos} de {activas} suscripción(es) activa(s) "
                    f"({round(vencidos * 100 / activas) if activas else 0} % · tope {pct} %)"),
        "excedido": vencidos * 100 > activas * pct,
    })
    reglas.append({
        "regla": "MAX_CAMBIOS", "variable": "MAX_CAMBIOS", "conteo": total,
        "limite": max_cambios,
        "detalle": f"{total} cambio(s) en el run (tope global de respaldo)",
        "excedido": total > max_cambios,
    })
    return reglas


def limites_excedidos(evaluacion: list) -> list:
    """Sólo las reglas que se pasaron del tope (filtro puro sobre `evaluar_limites()`)."""
    return [r for r in (evaluacion or []) if r["excedido"]]


def linea_limites(evaluacion: list) -> str:
    """Una línea con TODAS las reglas (`conteo/tope`), marcando la que se pasó.

    Es lo que va al log del run y al resumen del correo: se lee de un vistazo cuánto se movió
    cada regla respecto de su tope y cuál fue la que cortó.
    """
    return " · ".join(f"{r['regla']}={r['conteo']}/{r['limite']}"
                      + (" EXCEDE" if r["excedido"] else "") for r in (evaluacion or []))


def texto_excedidos(excedidos: list) -> str:
    """`excede MAX_VENCIDOS_PCT (130 > 120)` — y con más de una, las une con " y ".

    Es lo que va a `datos["estado"]` (y de ahí al asunto y al cuerpo del correo): dice **cuál**
    límite se superó, no sólo que se superó uno. Cadena vacía si no se pasó ninguno.
    """
    if not excedidos:
        return ""
    return "excede " + " y ".join(f"{r['variable']} ({r['conteo']} > {r['limite']})"
                                  for r in excedidos)


def guarda_vencidos(max_vencidos_pct: int) -> str:
    """Guarda del % de vencidos: va ANTES del paso 1, cuando `estado = 'activo'` sigue siendo el
    universo previo (después del paso 1 esa fila ya es 'vencido').

    Cuenta el universo y los que el paso 1 va a tocar con EXACTAMENTE los mismos predicados de
    `SQL_SUSCRIPCIONES_ACTIVAS` y del propio `UPDATE` (mismo `current_date` —la sesión ya fijó
    `SET LOCAL TIME ZONE`— y mismo cast del DÍA en hora de Chile: el día de vencimiento está
    vigente completo y recién se marca desde el día siguiente). `max_vencidos_pct` viene validado
    como entero (1..100), así que no hay forma de inyectar texto por esta vía. `%%` imprime un `%`
    literal en el RAISE.
    """
    pct = int(max_vencidos_pct)
    return f"""DO $$
DECLARE v integer; a integer;
BEGIN
  SELECT count(*) INTO a FROM {SUSCRIPCIONES_ACTIVAS};
  SELECT count(*) INTO v FROM {SUSCRIPCIONES_ACTIVAS} AND {sql_fecha_en_chile('fecha_expiracion')} < current_date;
  IF v * 100 > a * {pct} THEN
    RAISE EXCEPTION '{MARCA_GUARDA}: MAX_VENCIDOS_PCT: % vencido(s) > {pct}%% de % activa(s) (no se aplica nada)', v, a;
  END IF;
END $$;"""


def guarda_huerfanas(max_huerfanas: int) -> str:
    """Guarda POR CADA lista de huérfanas: suscripciones, solicitudes y usuarios, una por paso.

    Cuenta `_maint_cambios` (lo que la transacción REALMENTE tocó), no lo que se leyó antes: si
    hubiera una carrera, manda esto. Las huérfanas son pocas por definición, así que cualquiera
    de las tres que se pase del tope es una anomalía.
    """
    tope = int(max_huerfanas)
    chequeos = "\n".join(
        f"""  SELECT count(*) INTO h FROM _maint_cambios WHERE paso = '{clave}';
  IF h > {tope} THEN
    RAISE EXCEPTION '{MARCA_GUARDA}: MAX_HUERFANAS: % huérfana(s) en {clave} > {tope} (no se aplica nada)', h;
  END IF;""" for clave in HUERFANAS)
    return f"""DO $$
DECLARE h integer;
BEGIN
{chequeos}
END $$;"""


def guarda_volumen(maximo: int, variable: str = "MAX_CAMBIOS", tabla: str = "_maint_cambios",
                   que: str = "cambios") -> str:
    """Guarda del tope GLOBAL de una transacción: aborta si se pasa de `maximo` filas tocadas.

    Es el respaldo de las reglas finas (el % de vencidos y las huérfanas tienen la suya):
    cuenta `_maint_cambios` (lo que la transacción REALMENTE tocó), no lo que se leyó antes:
    si hubiera una carrera, manda esto. `maximo` ya viene validado como entero
    (1..1000), así que no hay forma de inyectar texto por esta vía.
    """
    tope = int(maximo)
    return f"""DO $$
DECLARE n integer;
BEGIN
  SELECT count(*) INTO n FROM {tabla};
  IF n > {tope} THEN
    RAISE EXCEPTION '{MARCA_GUARDA}: % {que} > {variable}={tope} (no se aplica nada)', n;
  END IF;
END $$;"""


def script_cambios(max_cambios: int, dias_pendiente: int, dry_run: bool,
                   max_vencidos_pct: int = MAX_VENCIDOS_PCT_DEFECTO,
                   max_huerfanas: int = MAX_HUERFANAS_DEFECTO) -> str:
    """Script de UNA transacción con los 4 UPDATE del mantenimiento.

    `DRY_RUN=1` ⇒ termina en `ROLLBACK` y **no** lleva ninguna guarda: el objetivo es medir
    exactamente lo que cambiaría y que la alerta (si hay que darla) muestre la lista completa
    (el "excede" lo decide Python con `evaluar_limites()` y lo informa, no aborta). `DRY_RUN=0`
    ⇒ termina en `COMMIT` y las tres guardas viajan adentro:
      * `guarda_vencidos()` **antes** del paso 1 (es el único momento en el que `estado =
        'activo'` sigue siendo el universo previo al cambio);
      * al final, `guarda_volumen()` (tope global de respaldo) y `guarda_huerfanas()` (una por
        cada lista de huérfanas), sobre `_maint_cambios`, o sea lo que la transacción
        REALMENTE tocó.
    Si se pasa cualquiera de las tres, la transacción aborta y no se aplica NADA.

    `max_vencidos_pct`/`max_huerfanas` tienen como default los MISMOS valores que `leer_config()`
    (constantes del módulo, no números sueltos): `main()` pasa siempre los ya validados.

    **Idempotente**: los 4 pasos filtran por estado (`activo`→`vencido`, `pendiente`→`rechazado`,
    `pending`→`rejected`, `pendiente_activacion`→`rechazado`) y por antigüedad, así que una segunda
    corrida no encuentra nada que cambiar; y no hay INSERT (sólo a la tabla temporal), así que nada
    se puede duplicar. Escribe en tablas que no toca ninguna de las otras 2 transacciones.
    """
    dias = int(dias_pendiente)
    cierre = "ROLLBACK;" if dry_run else "COMMIT;"
    guarda_vencidos_tx = "" if dry_run else "\n" + guarda_vencidos(max_vencidos_pct) + "\n"
    guarda_resto = ("" if dry_run
                    else "\n" + guarda_volumen(max_cambios) + "\n"
                    + guarda_huerfanas(max_huerfanas) + "\n")
    return f"""-- mantenimiento PROD: todo en UNA transacción (BEGIN … {cierre})
BEGIN;
SET LOCAL TIME ZONE '{TZ_CLT}';
CREATE TEMP TABLE _maint_cambios (paso text NOT NULL, id integer NOT NULL) ON COMMIT DROP;
{guarda_vencidos_tx}
-- 1) suscripciones activas con el plan vencido → 'vencido' (antes marcar_plan_vencido.py).
--    El día de `fecha_expiracion` (hora de Chile) está vigente COMPLETO: se marca desde el
--    día siguiente, no la mañana del último día.
WITH up AS (
  UPDATE suscripciones AS s SET estado = 'vencido', updated_at = now()
  WHERE s.estado = 'activo' AND {sql_fecha_en_chile('s.fecha_expiracion')} < current_date
  RETURNING s.id)
INSERT INTO _maint_cambios SELECT 'vencidos', id FROM up;

-- 2) suscripciones pendientes viejas → 'rechazado' (antes transacciones_huerfanas.py)
WITH up AS (
  UPDATE suscripciones AS s SET estado = 'rechazado', updated_at = now()
  WHERE s.estado = 'pendiente' AND s.created_at < now() - interval '{dias} days'
  RETURNING s.id)
INSERT INTO _maint_cambios SELECT 'huerfanas_suscripciones', id FROM up;

-- 3) solicitudes de plan pendientes viejas → 'rejected' (antes transacciones_huerfanas.py)
WITH up AS (
  UPDATE solicitudes_planes AS sp
     SET estado = 'rejected',
         comentario_admin = 'Expirada automáticamente por antigüedad (> {dias} días)',
         updated_at = now()
  WHERE sp.estado = 'pending' AND sp.created_at < now() - interval '{dias} days'
  RETURNING sp.id)
INSERT INTO _maint_cambios SELECT 'huerfanas_solicitudes', id FROM up;

-- 4) usuarios sin activar → 'rechazado' + activo=false. El CHECK de la migración 034
--    (`activo = (estado = 'activo')`) obliga a setear LOS DOS campos juntos.
WITH up AS (
  UPDATE usuarios AS u SET estado = 'rechazado', activo = false
  WHERE u.estado = 'pendiente_activacion' AND u.created_at < now() - interval '{dias} days'
  RETURNING u.id)
INSERT INTO _maint_cambios SELECT 'huerfanas_usuarios', id FROM up;
{guarda_resto}
-- resumen: la única línea con `|` que imprime el psql (-tA -F '|'); los tags de comando
-- (BEGIN/SET/CREATE TABLE/INSERT 0 n/DO/ROLLBACK) los ignora `parsear_resumen()`
SELECT paso, count(*) FROM _maint_cambios GROUP BY paso ORDER BY paso;

{cierre}
"""


def script_cierre(max_cierre: int, dias_cierre: int, dry_run: bool) -> str:
    """Transacción de la consistencia (pasos 8-9): asistencia de clases pasadas + aforo.

    Paso 8 (decisión D-6, opción A): se MARCA la asistencia de las reservas de clases ya
    terminadas (`asistencia_marcada_at` + `asistencia_via='cierre'`) y **no** se toca `estado`:
    pasar la reserva a `no_asistio` reescribiría los KPIs de asistencia ya publicados, y esto
    es sólo dejar constancia de que la clase pasó y nadie marcó nada. Es idempotente: el filtro
    es `asistencia_marcada_at IS NULL`, así que una segunda corrida no cambia nada.
    Paso 9: `clases.asistentes_confirmados` vuelve a ser el conteo real de reservas vivas
    (`sql_viva()`), que es lo que la app mantiene con +1/-1 al reservar y cancelar.

    **No toca reservas canceladas en NINGUNA variante** (`sql_viva()` = `NOT ILIKE '%cancel%'`): el
    paso 8 escribe `updated_at`, que es el dato con el que A.3 reconstruye las cancelaciones
    tardías; si le pegara a una cancelada, la "movería" y A.3 daría un descuadre falso.
    **Idempotente**: el paso 8 filtra por `asistencia_marcada_at IS NULL` y el paso 9 sólo toca las
    clases cuyo `asistentes_confirmados` no coincide con el conteo real, así que una segunda corrida
    no cambia nada (y no hay INSERT: nada se duplica). Los 2 pasos comparten la guarda
    `MAX_CIERRE` (cuenta `_maint_cierre`, la suma de los dos) y los 2 se verifican después.
    """
    dias = int(dias_cierre)
    cierre = "ROLLBACK;" if dry_run else "COMMIT;"
    guarda = "" if dry_run else "\n" + guarda_volumen(max_cierre, "MAX_CIERRE", "_maint_cierre",
                                                      "cierres") + "\n"
    return f"""-- mantenimiento PROD (consistencia): UNA transacción (BEGIN … {cierre})
BEGIN;
SET LOCAL TIME ZONE '{TZ_CLT}';
CREATE TEMP TABLE _maint_cierre (paso text NOT NULL, id integer NOT NULL) ON COMMIT DROP;

-- 8) reservas vivas de clases terminadas sin asistencia marcada → auditoría de cierre
WITH up AS (
  UPDATE reservas AS r SET asistencia_marcada_at = now(),
                           asistencia_via = 'cierre',
                           updated_at = now()
  WHERE {sql_viva()} AND r.asistencia_marcada_at IS NULL
    AND EXISTS (SELECT 1 FROM clases c WHERE c.id = r.clase_id
                 AND (c.fecha + c.hora_fin) AT TIME ZONE '{TZ_CLT}'
                     < now() - interval '{dias} days')
  RETURNING r.id)
INSERT INTO _maint_cierre SELECT 'cierre_asistencia', id FROM up;

-- 9) clases con el aforo desincronizado → asistentes_confirmados = reservas vivas
WITH calc AS (
  SELECT c.id AS clase_id,
         (SELECT count(*) FROM reservas r WHERE r.clase_id = c.id
           AND {sql_viva()})::int AS real
  FROM clases c
  WHERE c.asistentes_confirmados <> (SELECT count(*) FROM reservas r
                                      WHERE r.clase_id = c.id AND {sql_viva()})
), up AS (
  UPDATE clases AS c SET asistentes_confirmados = calc.real, updated_at = now()
  FROM calc WHERE c.id = calc.clase_id
  RETURNING c.id)
INSERT INTO _maint_cierre SELECT 'aforo_resync', id FROM up;
{guarda}
SELECT paso, count(*) FROM _maint_cierre GROUP BY paso ORDER BY paso;

{cierre}
"""


def script_purga(max_purga: int, dias_tokens: int, dias_notif: int, dry_run: bool) -> str:
    """Transacción de limpieza (paso 10): tokens de reset y notificaciones viejas.

    Son las DOS ÚNICAS tablas donde `maint_rw` tiene DELETE (decisión D-7): son datos
    operativos que no son historial del box (un token de reset vencido no le sirve a nadie y
    ya no lo puede usar nadie) y no tienen FKs de entrada, así que borrarlos no arrastra nada.
    En el resto de las tablas el rol sigue SIN poder borrar, y la prueba negativa del README lo
    verifica (`DELETE FROM usuarios …` tiene que dar "permission denied").

    **Idempotente**: el filtro es por antigüedad, así que lo que ya se borró no vuelve y una segunda
    corrida sólo borra lo que se haya vencido desde la anterior. No hay UPDATE: no puede "revivir"
    ni reescribir nada. Sólo 2 tablas, ninguna de ellas tocada por las otras 2 transacciones.
    """
    cierre = "ROLLBACK;" if dry_run else "COMMIT;"
    guarda = "" if dry_run else "\n" + guarda_volumen(max_purga, "MAX_PURGA", "_maint_purga",
                                                      "filas purgadas") + "\n"
    return f"""-- mantenimiento PROD (purga): UNA transacción (BEGIN … {cierre})
BEGIN;
SET LOCAL TIME ZONE '{TZ_CLT}';
CREATE TEMP TABLE _maint_purga (paso text NOT NULL, id integer NOT NULL) ON COMMIT DROP;

-- 10a) tokens de reset vencidos o ya usados
WITH del AS (
  DELETE FROM password_reset_tokens
  WHERE expires_at < now() - interval '{int(dias_tokens)} days'
     OR (used_at IS NOT NULL AND used_at < now() - interval '{int(dias_tokens)} days')
  RETURNING id)
INSERT INTO _maint_purga SELECT 'tokens_reset', id FROM del;

-- 10b) notificaciones enviadas viejas
WITH del AS (
  DELETE FROM notificaciones_enviadas
  WHERE fecha_envio < now() - interval '{int(dias_notif)} days'
  RETURNING id)
INSERT INTO _maint_purga SELECT 'notificaciones', id FROM del;
{guarda}
SELECT paso, count(*) FROM _maint_purga GROUP BY paso ORDER BY paso;

{cierre}
"""


def verificar(url: str, consultas: list, listas_antes: list, dry_run: bool) -> tuple:
    """(ok, detalle): después de la transacción, ¿quedó como tiene que quedar?

    En REAL cada lista tiene que dar 0 (se aplicó) y en DRY-RUN el mismo número de antes
    (no se aplicó nada). Se usan EXACTAMENTE las consultas de `consultas_lista()`.
    """
    ok = True
    detalle = {}
    for consulta, antes in zip(consultas, listas_antes):
        n_ahora = len(psql_leer(url, consulta["sql"]))
        esperado = len(antes["filas"]) if dry_run else 0
        detalle[consulta["clave"]] = f"{len(antes['filas'])} → {n_ahora} (esperado {esperado})"
        if n_ahora != esperado:
            ok = False
    return ok, detalle


# ── Reporte por email (compartido con el watchdog y el drill: alertas.py) ────
def _e(valor) -> str:
    """Escapa lo que viene de la base antes de meterlo en el HTML del mail.

    Los nombres/correos son datos de usuarios reales: sin escapar, un `nombre` con `<`
    rompería el mail (y con `<script>` sería contenido activo en el cliente de correo).
    """
    return html.escape(str(valor if valor is not None else ""))


def _tabla_lista(consulta: dict) -> str:
    """Una tabla HTML con TODAS las filas de una lista (nada truncado: es el punto del mail)."""
    filas = consulta["filas"]
    if not filas:
        return "<p style='margin:4px 0'>0 filas: nada para cambiar.</p>"
    columnas = len(consulta["cabeceras"])
    cab = "".join(f"<th align='left'>{_e(c)}</th>" for c in consulta["cabeceras"])
    if consulta.get("destino"):
        cab += "<th align='left'>→ nuevo</th>"
    cuerpo = "".join(
        "<tr>" + "".join(f"<td>{_e(v)}</td>" for v in fila[:columnas])
        + f"<td><b>{_e(consulta['destino'])}</b></td></tr>"
        for fila in filas)
    return ("<table border='1' cellpadding='4' cellspacing='0' "
            "style='border-collapse:collapse;font-size:12px'>"
            f"<tr style='background:#f4f4f5'>{cab}</tr>{cuerpo}</table>")


def _lista_html(titulo: str, pares) -> str:
    items = "".join(f"<li><b>{_e(k)}</b>: {_e(v)}</li>" for k, v in pares)
    return f"<p style='margin:10px 0 2px'><b>{_e(titulo)}</b></p><ul>{items or '<li>(sin datos)</li>'}</ul>"


def _bloques_listas(listas: list, vacio: str = "(sin listas)") -> str:
    """Bloques de listas que SÍ cambian algo (`destino` vacío ⇒ la lista sólo informa).

    El conteo es el `n` (el total real cuando la consulta lo pide: paso 9 y A.3) y, si el tope
    recortó la lista, se dice cuántas filas se muestran ("mostrando 25 de 63"): el tope no es el
    tamaño del conjunto (2026-09-27).
    """
    bloques = ""
    for c in listas or []:
        destino = f" → {_e(c['destino'])}" if c.get("destino") else ""
        mostradas = c.get("mostradas", c["n"])
        corte = f" (mostrando {mostradas} de {c['n']})" if mostradas < c["n"] else ""
        bloques += (f"<h4 style='margin:16px 0 4px'>{_e(c['titulo'])} — {c['n']} fila(s){corte}"
                    f"{destino}</h4>{_tabla_lista(c)}")
    return bloques or f"<p>{_e(vacio)}</p>"


def _bloques_detecciones(listas: list, nota_a5: str = "") -> str:
    """Listas de las detecciones A.1–A.6: la severidad va delante y las filas detrás.

    El conteo es el **total** del conjunto; si el `LIMIT` dejó filas afuera se dice cuántas se
    muestran ("mostrando 25 de 63"), para que el tope no se lea como el tamaño del hallazgo.
    `nota_a5`, si viene, se agrega DENTRO del bloque de A.5(a): la alerta no se silencia, es sólo
    el contexto de `A5_NOTA_HASTA`.
    """
    bloques = ""
    for c in listas or []:
        marca = "🔴 rojo (exit 9)" if c.get("sev") == "rojo" else "ℹ️ sólo informativo"
        mostradas = c.get("mostradas", c["n"])
        corte = f" (mostrando {mostradas} de {c['n']})" if mostradas < c["n"] else ""
        nota = (f"<br>ℹ️ <b>Nota A.5(a):</b> {_e(nota_a5)}"
                if nota_a5 and c.get("clave") == "a5a_sin_coach_posible" else "")
        bloques += (f"<p style='margin:10px 0 2px'><b>{_e(c['titulo'])}</b> — {c['n']} "
                    f"fila(s){corte} [{marca}]{nota}<br><i>{_e(c.get('detalle'))}</i></p>"
                    f"{_tabla_lista(c)}")
    return bloques or "<p>(las detecciones no encontraron filas)</p>"


def construir_html(datos: dict, inicio: datetime, segundos: float, titulo: str = "") -> str:
    """HTML de la alerta: qué pasó (repetido del asunto), listas COMPLETAS, integridad, Neon,
    reporte y verificación: todo lo que hace falta para decidir sin abrir el dashboard.
    """
    listas = datos.get("listas") or []
    bloques = "".join(
        f"<h4 style='margin:16px 0 4px'>{_e(c['titulo'])} — {c['n']} fila(s) → "
        f"{_e(c['destino'])}</h4>{_tabla_lista(c)}" for c in listas)
    if not bloques:
        bloques = "<p>(sin listas: la corrida no llegó a leer los cambios)</p>"

    # ── Fase 7: consistencia (C), detecciones (A) y límites de Neon (B) ──
    bloques_cierre = _bloques_listas(datos.get("listas_cierre"),
                                     "(sin nada que cerrar ni resincronizar)")
    bloques_purga = _bloques_listas(datos.get("listas_purga"),
                                    "(sin nada que purgar)")
    detect = datos.get("detecciones") or {}
    nota_a5_txt = detect.get("nota_a5") or ""
    # Sólo las listas CON filas: las 11 vacías serían ruido en un correo que ya es de alerta
    # (el detalle de qué se chequeó va igual en los hallazgos/informes de arriba).
    detect_listas = _bloques_detecciones([c for c in (detect.get("listas") or []) if c["n"]],
                                        nota_a5_txt)
    detect_rojo = ("<ul>" + "".join(
        f"<li>⚠️ {_e(h)}"
        + (f"<br>ℹ️ <b>Nota A.5(a):</b> {_e(nota_a5_txt)}" if nota_a5_txt and "A.5(a)" in h else "")
        + "</li>" for h in detect.get("hallazgos") or [])
        + "</ul>") if detect.get("hallazgos") else "<p>Sin hallazgos rojos ✅</p>"
    detect_info = ("<ul>" + "".join(f"<li>{_e(i)}</li>" for i in detect.get("informes") or [])
                   + "</ul>") if detect.get("informes") else ""
    detecciones_html = detect_rojo + detect_info + detect_listas

    neon_api = datos.get("neon_api") or {}
    if not neon_api.get("configurado"):
        neon_api_html = f"<p>{_e(neon_api.get('nota') or '(sin datos de la API de Neon)')}</p>"
    else:
        cu = neon_api.get("cu") or {}
        ramas = neon_api.get("ramas") or {}
        cu_txt = (f"{_e(cu.get('horas'))} CU-horas de {_e(cu.get('limite'))} "
                  f"({_e(cu.get('pct'))}%) — campo {_e(cu.get('fuente') or 'n/d')}"
                  if cu.get("horas") is not None else _e(cu.get("nota") or "sin dato"))
        neon_api_html = (
            f"<p><b>B.6 CU-horas del mes:</b> {cu_txt} "
            f"{'🚨 sobre el umbral' if cu.get('alerta') else '✅'}</p>"
            f"<p><b>B.7 ramas:</b> {_e(ramas.get('n'))} de {_e(ramas.get('limite'))} "
            f"{'🚨 en el tope (el drill no puede crear la suya)' if ramas.get('alerta') else '✅'}"
            f"<br><i>{_e(', '.join(ramas.get('nombres') or []))}</i></p>"
            f"<p><b>Plan:</b> {_e(neon_api.get('plan'))} · <b>Bytes del mes:</b> "
            f"{_e(neon_api.get('bytes'))}</p>"
        )
        if neon_api.get("hallazgos"):
            neon_api_html += ("<ul>" + "".join(f"<li>⚠️ {_e(h)}</li>"
                                               for h in neon_api["hallazgos"]) + "</ul>")

    hallazgos = datos.get("integridad") or []
    integridad = ("<p>⚠️ <b>Con problemas</b> (los datos NO se tocan por esto; el run queda "
                  "rojo):</p><ul>" + "".join(f"<li>{_e(h)}</li>" for h in hallazgos) + "</ul>"
                  ) if hallazgos else "<p>Sin problemas ✅</p>"

    neon = datos.get("neon") or {}
    alerta = ("🚨 <b>ALERTA: supera el "
              f"{_e(neon.get('umbral_pct'))}% del free tier</b>") if neon.get("alerta") else "✅"
    neon_html = (f"<p><b>Tamaño:</b> {_e(neon.get('mb'))} MB de {_e(neon.get('limite_mb'))} MB "
                 f"({_e(neon.get('pct'))}%) {alerta}</p>")

    alerta_html = f"<b>Alerta:</b> {_e(titulo)}<br>" if titulo else ""
    pasos = (f"<p><b>Resultado:</b> {'OK ✅' if datos.get('ok', True) else 'FALLA ❌'}<br>"
             f"{alerta_html}"
             f"<b>Motivo:</b> {_e(datos.get('motivo'))}<br>"
             f"<b>Modo:</b> {_e(datos.get('modo'))}<br>"
             f"<b>Base:</b> {_e(datos.get('base'))} · <b>ENVIRONMENT:</b> "
             f"{_e(datos.get('entorno'))}<br>"
             f"<b>alembic:</b> {_e(datos.get('alembic'))} · <b>usuarios:</b> "
             f"{_e(datos.get('usuarios'))}<br>"
             f"<b>límites:</b> MAX_CAMBIOS={_e(datos.get('max_cambios'))} · "
             f"MAX_VENCIDOS_PCT={_e(datos.get('max_vencidos_pct'))}% · "
             f"MAX_HUERFANAS={_e(datos.get('max_huerfanas'))}<br>"
             f"<b>Duración:</b> {segundos:.0f} s · <b>Inicio (UTC):</b> "
             f"{inicio.strftime('%Y-%m-%d %H:%M')}</p>")

    # Reglas de volumen: cada una con su conteo y su tope, marcando la que se pasó (así el
    # correo dice cuál límite cortó, no sólo que cortó uno).
    limites = datos.get("limites") or []
    excedidas = [r["variable"] for r in limites if r["excedido"]]
    limites_html = "" if not limites else _lista_html(
        "Límites de volumen" + (f" — se pasó: {', '.join(excedidas)}" if excedidas else ""),
        [(r["regla"], f"{r['conteo']} / {r['limite']} — {r['detalle']}"
                      + (" 🚨 EXCEDE" if r["excedido"] else " ✅")) for r in limites])

    error = datos.get("psql_error")
    error_html = f"<p><b>psql (saneado):</b> <code>{_e(error)}</code></p>" if error else ""

    return (
        "<h3>Mantenimiento PROD (día 1 y 15) — 3 transacciones: cambios, consistencia y purga</h3>"
        + pasos
        + limites_html
        + (_lista_html("Transacción (filas efectivamente tocadas por el SQL)",
                       sorted((datos.get("resumen_cambios") or {}).items()))
           + _lista_html("Verificación posterior (esperado: 0 en REAL · igual que antes en DRY-RUN)",
                         sorted((datos.get("verificacion") or {}).items())))
        + error_html
        + "<h3>Cambios</h3>" + bloques
        + "<h3>Consistencia (pasos 8-9)</h3>" + bloques_cierre
        + "<h3>Purga (paso 10)</h3>" + bloques_purga
        + "<h3>Detecciones (A.1-A.6)</h3>" + detecciones_html
        + "<h3>Integridad</h3>" + integridad
        + "<h3>Neon (API v2: CU-horas y ramas)</h3>" + neon_api_html
        + "<h3>Neon (almacenamiento)</h3>" + neon_html
        + "<h3>Reporte del mes</h3>"
        + _lista_html(f"Mes {datos.get('reporte', {}).get('mes', '')}",
                      sorted((datos.get("reporte") or {}).items()))
        + "<p>Si el run quedó rojo en Render, mirar el log del Cron Job "
        "<i>box-crossfit-mantenimiento-prod → Runs</i>. Nada de lo impreso acá puede contener "
        "credenciales (<code>log()</code> sanea <code>://***@</code>).</p>"
    )


def _motivo_corto(motivo: str, tope: int = 140) -> str:
    """El motivo en UNA línea y sin pasarse: entra en el asunto y se lee en el teléfono."""
    texto = " ".join((motivo or "").split())
    return texto if len(texto) <= tope else texto[:tope - 1].rstrip() + "…"


def titulo_alerta(code: int, datos: dict) -> str:
    """Qué pasó, en corto: encabeza el asunto y queda repetido en el cuerpo de la alerta."""
    neon = datos.get("neon") or {}
    if code == EXIT_OK and neon.get("alerta"):
        return (f"Neon al {neon.get('pct')}% del free tier "
                f"({neon.get('mb')} MB de {neon.get('limite_mb')} MB)")
    if code == EXIT_OK:
        api = datos.get("neon_api") or {}
        cu, ramas = api.get("cu") or {}, api.get("ramas") or {}
        partes = []
        if cu.get("alerta"):
            partes.append(f"CU-horas al {cu.get('pct')}% "
                          f"({cu.get('horas')} de {cu.get('limite')})")
        if ramas.get("alerta"):
            partes.append(f"{ramas.get('n')} de {ramas.get('limite')} ramas")
        if partes:
            return "Neon: " + " y ".join(partes)
    return datos.get("estado") or TITULOS_EXIT.get(code) or "falla"


def codigo_de(texto: str) -> str:
    """Código de la detección que encabeza un texto (`A.5(a)`, `B.7`, …), o `""` si no lo trae.

    Todas las detecciones A/B arrancan su texto con su código, así que esto es lo que permite que
    el log nombre CUÁL puso el run en rojo (antes sólo decía "detecciones=1 hallazgo(s)").
    """
    m = re.match(r"([AB]\.\d+(?:\([a-z]\))?)\s", (texto or "").lstrip())
    return m.group(1) if m else ""


def sin_codigo(texto: str) -> str:
    """El mismo texto sin el código delante (para no repetirlo: `ROJO (A.5(a)): <título>…`)."""
    codigo = codigo_de(texto)
    return (texto or "")[len(codigo):].lstrip() if codigo else (texto or "")


def motivo_no_aborta(dry: bool, que: str) -> str:
    """Motivo del run rojo por algo que NO aborta la escritura, según el modo.

    En REAL el mantenimiento ya se aplicó (las guardas de volumen sí abortan, pero la integridad y
    las detecciones no); en DRY-RUN **no se aplicó nada** (la transacción terminó en `ROLLBACK`),
    así que decir "el mantenimiento se aplicó igual" sería falso: el texto cambia con el modo.
    """
    if dry:
        return f"en DRY-RUN no se aplicó nada (la transacción terminó en ROLLBACK): {que}"
    return f"el mantenimiento se aplicó igual: {que}"


def hay_que_avisar(code: int, datos: dict) -> bool:
    """Regla del proyecto: **correo = algo que revisar**. Si no, sólo log.

    Es rojo (exit ≠ 0: config, lectura, escritura, verificación, guarda de volumen, integridad)
    o un aviso del free tier de Neon (almacenamiento, CU-horas o ramas).
    y verificados— no manda nada: el mail no es un informe, es una alerta.
    """
    if code != EXIT_OK:
        return True
    if (datos.get("neon") or {}).get("alerta"):
        return True
    return bool((datos.get("neon_api") or {}).get("alerta"))


def enviar_reporte(code: int, motivo: str, datos: dict, inicio: datetime) -> bool:
    """Alerta por Gmail SMTP. Se llama SÓLO cuando hay algo que revisar (`hay_que_avisar`).

    Asunto: `[ALERTA] Mantenimiento PROD: <qué pasó> — <motivo>`. Nada de credenciales: todo
    pasa por `log()`/`sanear()`. Se le pasa NUESTRO `log` a `enviar_email` para que los avisos
    del correo salgan con `[maint]` y no con el `[backup]` del módulo compartido.
    """
    segundos = (datetime.now(timezone.utc) - inicio).total_seconds()
    titulo = titulo_alerta(code, datos)
    asunto = f"[ALERTA] Mantenimiento PROD: {titulo}"
    if corto := _motivo_corto(motivo):
        asunto += f" — {corto}"
    return enviar_email(asunto, construir_html(datos, inicio, segundos, titulo), logger=log)


def reportar(ok: bool, motivo: str, datos: dict, resumen: dict, inicio: datetime, code: int) -> int:
    """Único punto de salida de main(): log + alerta SÓLO si hay algo que revisar + exit code.

    `datos` arma el HTML (listas completas incluidas, por eso no se loguea) y `resumen` son
    los escalares que sí van al log del run. El correo no cambia el exit code: que el mail no
    salga (o que salga de más) no altera el resultado del run en Render.
    """
    datos["ok"] = ok
    datos["motivo"] = motivo
    log(("OK: " if ok else "FALLA: ") + motivo)
    for k, v in sorted((resumen or {}).items()):
        log(f"  {k}: {v}")
    if not hay_que_avisar(code, datos):
        log("MAIL: no se envía (todo OK: la regla es 'correo sólo si hay algo que revisar')")
        return code
    if not enviar_reporte(code, motivo, datos, inicio):
        log("AVISO: la alerta no salió por Gmail; el exit code no cambia")
    return code


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    inicio = datetime.now(timezone.utc)
    log("=== mantenimiento PROD (día 1 y 15) ===")

    try:
        cfg = leer_config()
    except ConfigError as e:
        log(f"FATAL (config): {e}")
        return reportar(False, f"config: {e}", {}, {}, inicio, EXIT_CONFIG)

    dry = cfg["dry_run"]
    log(f"DRY_RUN={'1 (no se aplica nada)' if dry else '0 (APLICA cambios)'} | límites: "
        f"MAX_CAMBIOS={cfg['max_cambios']} · MAX_VENCIDOS_PCT={cfg['max_vencidos_pct']}% · "
        f"MAX_HUERFANAS={cfg['max_huerfanas']} | "
        f"días pendiente={cfg['dias_pendiente']} | "
        f"NEON_LIMITE_MB={cfg['neon_limite_mb']} | ENVIRONMENT={cfg['entorno']}")
    log(f"Origen: {host_de(cfg['url'])}")   # host + base, SIN credenciales

    datos = {
        "base": host_de(cfg["url"]),
        "entorno": cfg["entorno"],
        "max_cambios": cfg["max_cambios"],
        "max_vencidos_pct": cfg["max_vencidos_pct"],
        "max_huerfanas": cfg["max_huerfanas"],
        "limites": [],          # reglas de volumen evaluadas (las carga la lectura de abajo)
        "modo": ("DRY-RUN (la transacción termina en ROLLBACK: no se aplica nada)" if dry
                 else "REAL (la transacción termina en COMMIT)"),
    }
    resumen = {"base": datos["base"], "modo": datos["modo"], "max_cambios": cfg["max_cambios"]}

    # ── 1) Lecturas (incluida la lista de lo que se va a cambiar) ──
    # OJO con los nombres: `consultas_cierre`/`consultas_purga` son las FUNCIONES del módulo,
    # así que las variables locales llevan el sufijo `_fase` (si no, Python las trata como
    # locales en todo `main()` y la llamada de la línea de arriba falla con UnboundLocalError).
    consultas_cambios = consultas_lista(cfg["dias_pendiente"])
    consultas_cierre_fase = consultas_cierre(cfg)
    consultas_purga_fase = consultas_purga(cfg)
    try:
        datos["usuarios"] = psql_entero(cfg["url"], SQL_USUARIOS)
        datos["alembic"] = psql_escalar(cfg["url"], SQL_ALEMBIC)
        # Universo del paso de vencidos (misma constante que la guarda del SQL): el % de
        # MAX_VENCIDOS_PCT se mide contra ESTO, no contra el total de usuarios.
        datos["suscripciones_activas"] = psql_entero(cfg["url"], SQL_SUSCRIPCIONES_ACTIVAS)
        listas = leer_listas(cfg["url"], consultas_cambios)
        datos["listas"] = listas
        datos["listas_cierre"] = leer_listas(cfg["url"], consultas_cierre_fase)
        datos["listas_purga"] = leer_listas(cfg["url"], consultas_purga_fase)
        datos["integridad"] = integridad(cfg["url"])
        datos["detecciones"] = detecciones(cfg["url"], cfg)
        datos["neon"] = neon_uso(cfg["url"], cfg["neon_limite_mb"], cfg["neon_umbral_pct"])
        datos["neon_api"] = neon_api_limites(cfg)
        datos["reporte"] = reporte_mes(cfg["url"], cfg)
        datos["resumen_cambios"] = {}     # lo que tocó cada una de las 3 transacciones
        datos["verificacion"] = {}        # la verificación posterior de cada una
    except LecturaError as e:
        log(f"FATAL (lectura): {e}")
        return reportar(False, f"lectura: {e}", datos, resumen, inicio, EXIT_LECTURA)

    cambios = sum(c["n"] for c in listas)
    cierres = sum(c["n"] for c in datos["listas_cierre"])
    purga = sum(c["n"] for c in datos["listas_purga"])
    # Reglas de volumen: PURAS (conteos + config → reglas). Se evalúan acá, antes de las
    # transacciones, así el log y el correo dicen desde el principio cuánto se movió cada regla
    # y cuál se pasó. En REAL las mismas reglas viajan ADENTRO del SQL (`guarda_vencidos()`/
    # `guarda_huerfanas()`): la guarda que aborta no depende de este cálculo.
    conteos = {c["clave"]: c["n"] for c in listas}
    conteos["total"] = cambios
    conteos["suscripciones_activas"] = datos["suscripciones_activas"]
    evaluacion = evaluar_limites(conteos, cfg)
    excedidos = limites_excedidos(evaluacion)
    datos["limites"] = evaluacion
    resumen.update({
        "usuarios": datos["usuarios"], "alembic": datos["alembic"],
        "cambios_a_realizar": cambios, "cierres_a_realizar": cierres,
        "purga_a_realizar": purga, "suscripciones_activas": datos["suscripciones_activas"],
        "limites": linea_limites(evaluacion),
        "integridad_hallazgos": len(datos["integridad"]),
        "detecciones_hallazgos": len(datos["detecciones"]["hallazgos"]),
        "neon_mb": datos["neon"]["mb"], "neon_pct": datos["neon"]["pct"],
    })
    log(f"Lecturas OK: usuarios={datos['usuarios']} | alembic={datos['alembic']} | "
        f"cambios={cambios} | integridad={len(datos['integridad'])} hallazgo(s) | "
        f"neon={datos['neon']['mb']} MB ({datos['neon']['pct']}% de "
        f"{cfg['neon_limite_mb']} MB)")
    detecc = datos["detecciones"]
    # El log nombra CUÁL detección puso el run en rojo (`[A.5(a)]`) y, unas líneas más abajo, cada
    # hallazgo con su código, su título y su conteo (`ROJO (A.5(a)): … — 25 fila(s)`).
    codigos = ", ".join(codigo_de(h) for h in detecc["hallazgos"] if codigo_de(h))
    log(f"Lecturas OK (Fase 7): cierres={cierres} | purga={purga} | "
        f"detecciones={len(detecc['hallazgos'])} hallazgo(s){f' [{codigos}]' if codigos else ''} | "
        f"avisos Neon={len((datos['neon_api'] or {}).get('avisos') or [])}")
    if detecc.get("nota_a5"):
        log(f"NOTA A.5(a) (esperado hasta {cfg['a5_nota_hasta'].isoformat()}): {detecc['nota_a5']}")
    log(f"Límites: {linea_limites(evaluacion)}")
    api = datos["neon_api"] or {}
    if api.get("configurado"):
        cu, ramas = api.get("cu") or {}, api.get("ramas") or {}
        log(f"Neon API: CU-horas={cu.get('horas')} de {cu.get('limite')} "
            f"({cu.get('pct')}%, campo {cu.get('fuente') or 'n/d'}) | ramas={ramas.get('n')} "
            f"de {ramas.get('limite')} | plan={api.get('plan')}")
    else:
        log(f"Neon API: {api.get('nota')}")
    for aviso in api.get("avisos") or []:
        log(f"AVISO (Neon): {aviso}")
    for consulta in datos["listas_cierre"] + datos["listas_purga"]:
        log(f"  {consulta['clave']}: {consulta['n']} fila(s) -> {consulta['destino']}")
    for consulta in listas:
        log(f"  {consulta['clave']}: {consulta['n']} fila(s) → {consulta['destino']}")

    # ── 2-4) Las TRES transacciones, cada una con su tope y su verificación ──
    # En serie y en este orden: primero los 4 UPDATE de la Fase 6, después la consistencia
    # (pasos 8-9) y al final la purga (paso 10). Cada una es UNA transacción independiente: si
    # la guarda de una aborta, las anteriores YA quedaron aplicadas y verificadas y la que
    # sigue no se intenta (run rojo y el mail dice exactamente dónde se cortó).
    fases = (
        {"nombre": "cambios", "clave_tx": "cambios_tx", "tope_var": "MAX_CAMBIOS",
         "que": "cambio(s)", "antes": cambios, "tope": cfg["max_cambios"],
         "excedidos": excedidos,      # las reglas finas (vencidos % y huérfanas)
         "script": script_cambios(cfg["max_cambios"], cfg["dias_pendiente"], dry,
                                  cfg["max_vencidos_pct"], cfg["max_huerfanas"]),
         "consultas": consultas_cambios, "listas": listas},
        {"nombre": "consistencia", "clave_tx": "cierre_tx", "tope_var": "MAX_CIERRE",
         "que": "cierre(s)", "antes": cierres, "tope": cfg["max_cierre"], "excedidos": [],
         "script": script_cierre(cfg["max_cierre"], cfg["dias_cierre"], dry),
         "consultas": consultas_cierre_fase, "listas": datos["listas_cierre"]},
        {"nombre": "purga", "clave_tx": "purga_tx", "tope_var": "MAX_PURGA",
         "que": "fila(s) purgadas", "antes": purga, "tope": cfg["max_purga"], "excedidos": [],
         "script": script_purga(cfg["max_purga"], cfg["dias_purga_tokens"],
                                cfg["dias_purga_notif"], dry),
         "consultas": consultas_purga_fase, "listas": datos["listas_purga"]},
    )
    total_tx = 0
    for fase in fases:
        try:
            r = psql_script(cfg["url"], fase["script"])
        except OSError as e:
            log(f"FATAL (escritura, {fase['nombre']}): {type(e).__name__}: {e}")
            return reportar(False, f"escritura ({fase['nombre']}): {type(e).__name__}",
                            datos, resumen, inicio, EXIT_ESCRITURA)

        resumen_tx = parsear_resumen(r.stdout or "")
        total = sum(resumen_tx.values())
        datos["resumen_cambios"].update(resumen_tx)
        if resumen_tx:
            # paso a paso en el log del run: cuántas filas tocó cada paso (p. ej. `aforo_resync=3`,
            # o sea cuántas CLASES cambió el resync) y no sólo el total de la transacción.
            log(f"  {fase['nombre']}: "
                + ", ".join(f"{paso}={n}" for paso, n in sorted(resumen_tx.items())))

        if r.returncode != 0:
            error = sanear(r.stderr or "")[:600]
            datos["psql_error"] = error
            if MARCA_GUARDA in (r.stderr or ""):
                datos["estado"] = texto_excedidos(fase["excedidos"]) or (
                    f"excede {fase['tope_var']} ({total or fase['antes']} > {fase['tope']})")
                motivo = (f"la transacción de {fase['nombre']} abortó por la guarda de volumen "
                          "y NO se aplicó nada")
                log(f"ABORTADO ({datos['estado']}: {motivo})")
                return reportar(False, motivo, datos, resumen, inicio, EXIT_GUARDA)
            log(f"FATAL (escritura, {fase['nombre']}): psql rc={r.returncode}: {error}")
            return reportar(False, f"escritura rc={r.returncode}: {error}", datos, resumen,
                            inicio, EXIT_ESCRITURA)

        try:
            ok_ver, verificacion = verificar(cfg["url"], fase["consultas"], fase["listas"], dry)
        except LecturaError as e:
            log(f"FATAL (verificación, {fase['nombre']}): {e}")
            return reportar(False, f"verificación ({fase['nombre']}): {e}", datos, resumen,
                            inicio, EXIT_VERIFICACION)
        datos["verificacion"].update(verificacion)
        if not ok_ver:
            motivo = ("verificación: la base no quedó como debía — "
                      + "; ".join(f"{k} {v}" for k, v in verificacion.items()))
            log(f"FATAL ({motivo})")
            return reportar(False, motivo, datos, resumen, inicio, EXIT_VERIFICACION)

        total_tx += total
        resumen.update({fase["clave_tx"]: total,
                        "duracion_s": round(
                            (datetime.now(timezone.utc) - inicio).total_seconds())})
        if dry:
            log(f"DRY_RUN=1 ({fase['nombre']}): la transacción terminó en ROLLBACK "
                f"({total} {fase['que']} simulados, nada aplicado) y la verificación confirma "
                "que la lista sigue igual")
        else:
            log(f"Transacción aplicada y verificada: {total} {fase['que']} "
                f"({fase['nombre']}); la lista quedó en 0")

        # Guardas de volumen en DRY-RUN: informan (con la lista completa en el mail), no abortan.
        # En `cambios` las reglas finas ya se evaluaron en Python (`fase["excedidos"]`); en las
        # otras dos fases el único tope es el global del SQL.
        if dry and (fase["excedidos"] or total > fase["tope"]):
            datos["estado"] = texto_excedidos(fase["excedidos"]) or (
                f"excede {fase['tope_var']} ({total} > {fase['tope']})")
            return reportar(False, "la guarda de volumen no aborta en DRY-RUN: no se aplicaría "
                                   "nada (revisar la lista de este mail antes de decidir si se "
                                   "sube el tope)", datos, resumen, inicio, EXIT_GUARDA)

    # ── 5) Integridad: run rojo, sin abortar el mantenimiento (exit 4) ──
    if datos["integridad"]:
        datos["estado"] = f"integridad con {len(datos['integridad'])} problema(s)"
        motivo = motivo_no_aborta(dry, "la integridad no aborta el mantenimiento")
        log(f"ROJO ({datos['estado']}: {motivo})")
        return reportar(False, motivo, datos, resumen, inicio, EXIT_INTEGRIDAD)

    # ── 6) Detecciones A y chequeos de Neon (B): rojo, sin abortar nada (exit 9) ──
    rojos = list(datos["detecciones"]["hallazgos"]) + list(
        (datos["neon_api"] or {}).get("hallazgos") or [])
    if rojos:
        datos["estado"] = f"los chequeos nuevos encontraron {len(rojos)} problema(s)"
        motivo = motivo_no_aborta(dry, "las detecciones A.1-A.6 y los chequeos de Neon no "
                                       "abortan la escritura")
        log(f"ROJO ({datos['estado']}: {motivo})")
        # Cada hallazgo con SU código delante: es la línea que dice qué puso el run rojo, con el
        # título y el conteo real (no sólo "detecciones=1 hallazgo(s)").
        for hallazgo in rojos:
            log(f"ROJO ({codigo_de(hallazgo) or 'chequeo'}): {sin_codigo(hallazgo)}")
        return reportar(False, motivo, datos, resumen, inicio, EXIT_DIAGNOSTICO)

    return reportar(True, f"mantenimiento {'simulado' if dry else 'aplicado'} y verificado: "
                          f"{total_tx} fila(s) {'habrían cambiado' if dry else 'tocadas'} en "
                          "3 transacciones", datos, resumen, inicio, EXIT_OK)



if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 (el mensaje se sanea al pasar por log())
        log(f"FATAL inesperado: {type(e).__name__}: {e}")
        sys.exit(1)
