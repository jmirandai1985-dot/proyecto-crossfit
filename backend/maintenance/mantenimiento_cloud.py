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
   no copia `app/`, y ésa es la razón por la que se habla con la base por `psql`.
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
5. **Guarda de volumen**: si la corrida afecta más de `MAX_CAMBIOS` filas (default 20, rango
   1..1000), el mantenimiento **no se aplica**. En REAL la guarda aborta la transacción
   *desde el SQL* (`DO $$ … RAISE EXCEPTION … $$`), así que no depende del código Python; en
   DRY-RUN no aborta: informa (con la lista completa) y el run queda rojo (exit 6).
6. **El éxito se verifica**: después de la transacción se vuelven a correr las mismas
   consultas. En REAL deben dar 0 (se aplicó) y en DRY-RUN el mismo número de antes
   (no se aplicó nada).
7. **Todo sale saneado**: ninguna credencial puede quedar impresa. La URL sólo se muestra
   como `host_de(url)` y todo texto externo pasa por `sanear()` (`://***@`).
8. **Avisa siempre**: el email sale por Gmail SMTP (`maintenance/alertas.py`, el mismo camino
   del watchdog y del drill) pase lo que pase, incluso si no hay nada que hacer.

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
  * `MAX_CAMBIOS`   — guarda de volumen (default 20)
  * `DIAS_PENDIENTE`— antigüedad de las huérfanas (default 7)
  * `NEON_LIMITE_MB`— límite del free tier de Neon (default 512 = 0,5 GB por proyecto)
  * `NEON_UMBRAL_PCT`— alerta de uso (default 80 %)
  * `DRY_RUN`       — `1` (default de la imagen) no aplica nada
  * `GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`, `ALERT_EMAIL` — del env group `alertas`

Exit codes
----------
0 OK · 2 config (falta variable, URL con `-pooler`, usuario que no es `maint_rw`,
`ENVIRONMENT` ≠ production, entero fuera de rango) · 3 un `SELECT` de lectura falló ·
4 la integridad encontró problemas (run rojo; la escritura NO se aborta) · 6 guarda de
volumen (en DRY-RUN informa y no aplica; en REAL aborta y no se aplica nada) ·
7 la transacción de escritura falló (nada quedó aplicado) · 8 la verificación posterior no
cuadró.

Uso:
    python -m maintenance.mantenimiento_cloud
"""
from __future__ import annotations

import html
import os
import sys
import tempfile
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

# ── Códigos de salida (Render marca fallido el run si != 0) ──
EXIT_OK = 0
EXIT_CONFIG = 2        # falta variable / URL con -pooler / rol equivocado / ENVIRONMENT
EXIT_LECTURA = 3       # un SELECT falló (permisos, red, base)
EXIT_INTEGRIDAD = 4    # la integridad encontró problemas (rojo, sin abortar la escritura)
EXIT_GUARDA = 6        # se superó MAX_CAMBIOS ⇒ no se aplica nada
EXIT_ESCRITURA = 7     # la transacción de escritura falló (nada aplicado)
EXIT_VERIFICACION = 8  # la verificación posterior no cuadró

VARS_OBLIGATORIAS = (
    "MAINT_DB_URL",
    "ENVIRONMENT",
    *VARS_ALERTA,      # GMAIL_SMTP_USER + GMAIL_SMTP_APP_PASSWORD + ALERT_EMAIL
)

USUARIO_ROL = "maint_rw"           # el único rol con UPDATE sobre estas columnas
ENTORNO_ESPERADO = "production"    # guarda dura: este job escribe en PROD
TZ_CLT = "America/Santiago"        # mismo huso que el contenedor (Dockerfile.cron)
MAX_CAMBIOS_DEFECTO = 20
MAX_CAMBIOS_RANGO = (1, 1000)      # el único camino por el que un número llega al SQL
DIAS_PENDIENTE_DEFECTO = 7
NEON_LIMITE_MB_DEFECTO = 512       # free tier de Neon: 0,5 GB por proyecto
NEON_UMBRAL_PCT_DEFECTO = 80.0


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
    """Config completa y validada. Lanza ConfigError (exit 2) antes de tocar la base."""
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
        "dias_pendiente": _entero("DIAS_PENDIENTE", DIAS_PENDIENTE_DEFECTO, 1, 365),
        "neon_limite_mb": _entero("NEON_LIMITE_MB", NEON_LIMITE_MB_DEFECTO, 1, 1_000_000),
        "neon_umbral_pct": _flotante("NEON_UMBRAL_PCT", NEON_UMBRAL_PCT_DEFECTO, 1.0, 100.0),
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
                "WHERE s.estado = 'activo' AND s.fecha_expiracion < current_date "
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
SQL_DUP_RUT = (
    "SELECT rut, count(*)::text FROM usuarios GROUP BY rut "
    "HAVING count(*) > 1 ORDER BY count(*) DESC LIMIT 10"
)
SQL_DUP_CORREO = (
    "SELECT correo, count(*)::text FROM usuarios GROUP BY correo "
    "HAVING count(*) > 1 ORDER BY count(*) DESC LIMIT 10"
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
SQL_TAMANO = "SELECT pg_database_size(current_database())::text"
SQL_TABLAS_TOP = (
    "SELECT relname, n_live_tup::text FROM pg_stat_user_tables "
    "ORDER BY n_live_tup DESC LIMIT 8"
)
# Mismo criterio que reporte_estadisticas.py. El corte del mes se arma en Python como
# 'YYYY-MM-DD'::date (nunca texto que venga de afuera) y se evalúa en la TZ de Chile.
SQL_REPORTE = {
    "total_alumnos": "SELECT count(*)::text FROM usuarios WHERE rol = 'alumno'",
    "alumnos_activos": "SELECT count(*)::text FROM usuarios WHERE rol = 'alumno' AND activo = true",
    "planes_activos": "SELECT count(*)::text FROM suscripciones WHERE estado = 'activo'",
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
}


# ── Lecturas: listas, integridad, uso de Neon y reporte del mes ──────────────
def leer_listas(url: str, dias_pendiente: int) -> list:
    """Las 4 listas, leídas ANTES de la transacción (es lo que muestra el mail)."""
    listas = []
    for consulta in consultas_lista(dias_pendiente):
        filas = psql_leer(url, consulta["sql"])
        listas.append({**consulta, "filas": filas, "n": len(filas)})
    return listas


def integridad(url: str) -> list:
    """Los 5 chequeos de `verificar_integridad.py`, contra PROD. Devuelve los hallazgos.

    Un hallazgo NO aborta el mantenimiento (decisión del 2026-09-27): pone el run en rojo
    (exit 4) y lo cuenta en el mail. Los datos no se tocan por un problema detectado.
    """
    hallazgos = []

    dup = psql_leer(url, SQL_DUP_RUT)
    if dup:
        detalle = ", ".join(f"{r[0]} x{r[1]}" for r in dup[:10])
        hallazgos.append(f"RUT duplicados ({len(dup)}): {detalle}")

    dup = psql_leer(url, SQL_DUP_CORREO)
    if dup:
        detalle = ", ".join(f"{r[0]} x{r[1]}" for r in dup[:10])
        hallazgos.append(f"Correos duplicados ({len(dup)}): {detalle}")

    for etiqueta, sql in (
        ("Suscripciones con usuario inexistente", SQL_SUSC_SIN_USUARIO),
        ("Suscripciones con plan inexistente", SQL_SUSC_SIN_PLAN),
        ("Suscripciones con expiración anterior al inicio", SQL_FECHAS_INVALIDAS),
    ):
        n = psql_entero(url, sql)
        if n:
            hallazgos.append(f"{etiqueta}: {n}")
    return hallazgos


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


def reporte_mes(url: str) -> dict:
    """Las mismas métricas de `reporte_estadisticas.py` (sin escribir el JSON local).

    No se escribe ningún archivo: en un Cron Job de Render el filesystem es efímero, así
    que el "reporte" es el mail (y el log).
    """
    ini = date.today().replace(day=1)
    ini_ant = (ini - timedelta(days=1)).replace(day=1)
    datos = {}
    for clave, plantilla in SQL_REPORTE.items():
        crudo = psql_escalar(url, plantilla.format(
            ini=ini.isoformat(), ini_ant=ini_ant.isoformat()))
        datos[clave] = float(crudo or 0) if clave.startswith("ingresos") else _int_o_cero(crudo)

    previo = datos["ingresos_mes_anterior"]
    datos["variacion_ingresos_pct"] = (
        round((datos["ingresos_mes"] - previo) / previo * 100, 2) if previo else None)
    datos["mes"] = ini.isoformat()
    return datos


# ── Escritura: UNA transacción con los 4 UPDATE ──────────────────────────────
MARCA_GUARDA = "GUARDA DE VOLUMEN"


def guarda_volumen(max_cambios: int) -> str:
    """Guarda de volumen evaluada EN EL SQL: aborta la transacción si se pasa del tope.

    Cuenta `_maint_cambios` (lo que la transacción REALMENTE tocó), no lo que se leyó antes:
    si hubiera una carrera, manda esto. `max_cambios` ya viene validado como entero
    (1..1000), así que no hay forma de inyectar texto por esta vía.
    """
    tope = int(max_cambios)
    return f"""DO $$
DECLARE n integer;
BEGIN
  SELECT count(*) INTO n FROM _maint_cambios;
  IF n > {tope} THEN
    RAISE EXCEPTION '{MARCA_GUARDA}: % cambios > MAX_CAMBIOS={tope} (no se aplica nada)', n;
  END IF;
END $$;"""


def script_cambios(max_cambios: int, dias_pendiente: int, dry_run: bool) -> str:
    """Script de UNA transacción con los 4 UPDATE del mantenimiento.

    `DRY_RUN=1` ⇒ termina en `ROLLBACK` y **no** lleva la guarda de volumen: el objetivo es
    que el mail muestre la lista completa de lo que habría cambiado (el "excede" lo decide
    Python y lo informa, no aborta). `DRY_RUN=0` ⇒ termina en `COMMIT` y la guarda va antes
    del cierre: si se pasa del tope la transacción aborta y no se aplica NADA.
    """
    dias = int(dias_pendiente)
    cierre = "ROLLBACK;" if dry_run else "COMMIT;"
    guarda = "" if dry_run else "\n" + guarda_volumen(max_cambios) + "\n"
    return f"""-- mantenimiento PROD: todo en UNA transacción (BEGIN … {cierre})
BEGIN;
SET LOCAL TIME ZONE '{TZ_CLT}';
CREATE TEMP TABLE _maint_cambios (paso text NOT NULL, id integer NOT NULL) ON COMMIT DROP;

-- 1) suscripciones activas con el plan vencido → 'vencido' (antes marcar_plan_vencido.py)
WITH up AS (
  UPDATE suscripciones AS s SET estado = 'vencido', updated_at = now()
  WHERE s.estado = 'activo' AND s.fecha_expiracion < current_date
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
{guarda}
-- resumen: la única línea con `|` que imprime el psql (-tA -F '|'); los tags de comando
-- (BEGIN/SET/CREATE TABLE/INSERT 0 n/DO/ROLLBACK) los ignora `parsear_resumen()`
SELECT paso, count(*) FROM _maint_cambios GROUP BY paso ORDER BY paso;

{cierre}
"""


def verificar(url: str, listas_antes: list, dias_pendiente: int, dry_run: bool) -> tuple:
    """(ok, detalle): después de la transacción, ¿quedó como tiene que quedar?

    En REAL cada lista tiene que dar 0 (se aplicó) y en DRY-RUN el mismo número de antes
    (no se aplicó nada). Se usan EXACTAMENTE las consultas de `consultas_lista()`.
    """
    ok = True
    detalle = {}
    for consulta, antes in zip(consultas_lista(dias_pendiente), listas_antes):
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


def construir_html(datos: dict, inicio: datetime, segundos: float) -> str:
    """HTML del mail: estado, listas COMPLETAS, integridad, Neon, reporte y verificación."""
    listas = datos.get("listas") or []
    bloques = "".join(
        f"<h4 style='margin:16px 0 4px'>{_e(c['titulo'])} — {c['n']} fila(s) → "
        f"{_e(c['destino'])}</h4>{_tabla_lista(c)}" for c in listas)
    if not bloques:
        bloques = "<p>(sin listas: la corrida no llegó a leer los cambios)</p>"

    hallazgos = datos.get("integridad") or []
    integridad = ("<p>⚠️ <b>Con problemas</b> (los datos NO se tocan por esto; el run queda "
                  "rojo):</p><ul>" + "".join(f"<li>{_e(h)}</li>" for h in hallazgos) + "</ul>"
                  ) if hallazgos else "<p>Sin problemas ✅</p>"

    neon = datos.get("neon") or {}
    alerta = ("🚨 <b>ALERTA: supera el "
              f"{_e(neon.get('umbral_pct'))}% del free tier</b>") if neon.get("alerta") else "✅"
    neon_html = (f"<p><b>Tamaño:</b> {_e(neon.get('mb'))} MB de {_e(neon.get('limite_mb'))} MB "
                 f"({_e(neon.get('pct'))}%) {alerta}</p>")

    pasos = (f"<p><b>Resultado:</b> {'OK ✅' if datos.get('ok', True) else 'FALLA ❌'}<br>"
             f"<b>Motivo:</b> {_e(datos.get('motivo'))}<br>"
             f"<b>Modo:</b> {_e(datos.get('modo'))}<br>"
             f"<b>Base:</b> {_e(datos.get('base'))} · <b>ENVIRONMENT:</b> "
             f"{_e(datos.get('entorno'))}<br>"
             f"<b>alembic:</b> {_e(datos.get('alembic'))} · <b>usuarios:</b> "
             f"{_e(datos.get('usuarios'))}<br>"
             f"<b>MAX_CAMBIOS:</b> {_e(datos.get('max_cambios'))}<br>"
             f"<b>Duración:</b> {segundos:.0f} s · <b>Inicio (UTC):</b> "
             f"{inicio.strftime('%Y-%m-%d %H:%M')}</p>")

    error = datos.get("psql_error")
    error_html = f"<p><b>psql (saneado):</b> <code>{_e(error)}</code></p>" if error else ""

    return (
        "<h3>Mantenimiento PROD (día 1 y 15) — una sola transacción</h3>"
        + pasos
        + (_lista_html("Transacción (filas efectivamente tocadas por el SQL)",
                       sorted((datos.get("resumen_cambios") or {}).items()))
           + _lista_html("Verificación posterior (esperado: 0 en REAL · igual que antes en DRY-RUN)",
                         sorted((datos.get("verificacion") or {}).items())))
        + error_html
        + "<h3>Cambios</h3>" + bloques
        + "<h3>Integridad</h3>" + integridad
        + "<h3>Neon (almacenamiento)</h3>" + neon_html
        + "<h3>Reporte del mes</h3>"
        + _lista_html(f"Mes {datos.get('reporte', {}).get('mes', '')}",
                      sorted((datos.get("reporte") or {}).items()))
        + "<p>Si el run quedó rojo en Render, mirar el log del Cron Job "
        "<i>box-crossfit-mantenimiento-prod → Runs</i>. Nada de lo impreso acá puede contener "
        "credenciales (<code>log()</code> sanea <code>://***@</code>).</p>"
    )


def enviar_reporte(ok: bool, motivo: str, datos: dict, inicio: datetime) -> bool:
    """Email SIEMPRE (OK, EXCEDE o FALLA + motivo). Nada de credenciales: todo pasa por log."""
    segundos = (datetime.now(timezone.utc) - inicio).total_seconds()
    estado = datos.get("estado") or ("OK" if ok else "FALLA")
    asunto = f"[Mantenimiento PROD] {estado} — {motivo}"
    return enviar_email(asunto, construir_html(datos, inicio, segundos))


def reportar(ok: bool, motivo: str, datos: dict, resumen: dict, inicio: datetime, code: int) -> int:
    """Único punto de salida de main(): log + email SIEMPRE + exit code.

    `datos` arma el HTML (listas completas incluidas, por eso no se loguea) y `resumen` son
    los escalares que sí van al log del run.
    """
    datos["ok"] = ok
    datos["motivo"] = motivo
    log(("OK: " if ok else "FALLA: ") + motivo)
    for k, v in sorted((resumen or {}).items()):
        log(f"  {k}: {v}")
    if not enviar_reporte(ok, motivo, datos, inicio):
        log("AVISO: el reporte no salió por Gmail; el exit code no cambia")
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
    log(f"DRY_RUN={'1 (no se aplica nada)' if dry else '0 (APLICA cambios)'} | "
        f"MAX_CAMBIOS={cfg['max_cambios']} | días pendiente={cfg['dias_pendiente']} | "
        f"NEON_LIMITE_MB={cfg['neon_limite_mb']} | ENVIRONMENT={cfg['entorno']}")
    log(f"Origen: {host_de(cfg['url'])}")   # host + base, SIN credenciales

    datos = {
        "base": host_de(cfg["url"]),
        "entorno": cfg["entorno"],
        "max_cambios": cfg["max_cambios"],
        "modo": ("DRY-RUN (la transacción termina en ROLLBACK: no se aplica nada)" if dry
                 else "REAL (la transacción termina en COMMIT)"),
    }
    resumen = {"base": datos["base"], "modo": datos["modo"], "max_cambios": cfg["max_cambios"]}

    # ── 1) Lecturas (incluida la lista de lo que se va a cambiar) ──
    try:
        datos["usuarios"] = psql_entero(cfg["url"], SQL_USUARIOS)
        datos["alembic"] = psql_escalar(cfg["url"], SQL_ALEMBIC)
        listas = leer_listas(cfg["url"], cfg["dias_pendiente"])
        datos["listas"] = listas
        datos["integridad"] = integridad(cfg["url"])
        datos["neon"] = neon_uso(cfg["url"], cfg["neon_limite_mb"], cfg["neon_umbral_pct"])
        datos["reporte"] = reporte_mes(cfg["url"])
    except LecturaError as e:
        log(f"FATAL (lectura): {e}")
        return reportar(False, f"lectura: {e}", datos, resumen, inicio, EXIT_LECTURA)

    cambios = sum(c["n"] for c in listas)
    resumen.update({
        "usuarios": datos["usuarios"], "alembic": datos["alembic"],
        "cambios_a_realizar": cambios, "integridad_hallazgos": len(datos["integridad"]),
        "neon_mb": datos["neon"]["mb"], "neon_pct": datos["neon"]["pct"],
    })
    log(f"Lecturas OK: usuarios={datos['usuarios']} | alembic={datos['alembic']} | "
        f"cambios={cambios} | integridad={len(datos['integridad'])} hallazgo(s) | "
        f"neon={datos['neon']['mb']} MB ({datos['neon']['pct']}% de "
        f"{cfg['neon_limite_mb']} MB)")
    for consulta in listas:
        log(f"  {consulta['clave']}: {consulta['n']} fila(s) → {consulta['destino']}")

    # ── 2) Los 4 UPDATE en UNA transacción (ROLLBACK en DRY_RUN, COMMIT en REAL) ──
    try:
        r = psql_script(cfg["url"],
                        script_cambios(cfg["max_cambios"], cfg["dias_pendiente"], dry))
    except OSError as e:
        log(f"FATAL (escritura): {type(e).__name__}: {e}")
        return reportar(False, f"escritura: {type(e).__name__}", datos, resumen,
                        inicio, EXIT_ESCRITURA)

    resumen_cambios = parsear_resumen(r.stdout or "")
    total = sum(resumen_cambios.values())
    datos["resumen_cambios"] = resumen_cambios

    if r.returncode != 0:
        error = sanear(r.stderr or "")[:600]
        datos["psql_error"] = error
        if MARCA_GUARDA in (r.stderr or ""):
            motivo = (f"guarda de volumen: {total or cambios} > MAX_CAMBIOS="
                      f"{cfg['max_cambios']} ⇒ la transacción abortó y NO se aplicó nada")
            log(f"ABORTADO ({motivo})")
            return reportar(False, motivo, datos, resumen, inicio, EXIT_GUARDA)
        log(f"FATAL (escritura): psql rc={r.returncode}: {error}")
        return reportar(False, f"escritura rc={r.returncode}: {error}", datos, resumen,
                        inicio, EXIT_ESCRITURA)

    # ── 3) Verificación: las mismas 4 listas, después de la transacción ──
    try:
        ok_ver, verificacion = verificar(cfg["url"], listas, cfg["dias_pendiente"], dry)
    except LecturaError as e:
        log(f"FATAL (verificación): {e}")
        return reportar(False, f"verificación: {e}", datos, resumen, inicio, EXIT_VERIFICACION)
    datos["verificacion"] = verificacion
    resumen.update({"cambios_tx": total,
                    "duracion_s": round((datetime.now(timezone.utc) - inicio).total_seconds())})

    if not ok_ver:
        motivo = ("verificación: la base no quedó como debía — "
                  + "; ".join(f"{k} {v}" for k, v in verificacion.items()))
        log(f"FATAL ({motivo})")
        return reportar(False, motivo, datos, resumen, inicio, EXIT_VERIFICACION)

    if dry:
        log(f"DRY_RUN=1: la transacción terminó en ROLLBACK ({total} cambio(s) simulados, "
            "nada aplicado) y la verificación confirma que las 4 listas siguen igual")
    else:
        log(f"Transacción aplicada y verificada: {total} cambio(s); las 4 listas quedaron en 0")

    # ── 4) Guarda de volumen en DRY-RUN: informa (con la lista completa), no aborta ──
    if dry and total > cfg["max_cambios"]:
        datos["estado"] = (f"EXCEDE MAX_CAMBIOS ({total} > {cfg['max_cambios']}): "
                           "no se aplicaría")
        return reportar(False, f"{datos['estado']} — revisar la lista del mail", datos,
                        resumen, inicio, EXIT_GUARDA)

    # ── 5) Integridad: run rojo, sin abortar el mantenimiento ──
    if datos["integridad"]:
        motivo = (f"integridad: {len(datos['integridad'])} problema(s) en PROD "
                  "(los datos se actualizaron igual: la integridad no aborta)")
        log(f"ROJO ({motivo})")
        return reportar(False, motivo, datos, resumen, inicio, EXIT_INTEGRIDAD)

    datos["estado"] = (f"OK (DRY-RUN: {total} cambio(s))" if dry
                       else f"APLICADO ({total} cambio(s))")
    return reportar(True, f"{total} cambio(s) {'simulados' if dry else 'aplicados'} y "
                          "verificados", datos, resumen, inicio, EXIT_OK)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 (el mensaje se sanea al pasar por log())
        log(f"FATAL inesperado: {type(e).__name__}: {e}")
        sys.exit(1)
