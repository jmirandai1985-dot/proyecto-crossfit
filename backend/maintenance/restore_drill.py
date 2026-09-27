"""Drill de restore mensual — Cron Job de Render (0 13 1 * * UTC).

Qué valida
----------
Que el backup que está en R2 **realmente se pueda restaurar** y que el rol de backup
siga siendo de solo lectura. Es la única prueba que demuestra que el respaldo sirve
(el dump puede estar íntegro y aun así no restaurar).

Flujo
-----
1. Baja el objeto más nuevo de `daily/` y lo descomprime.
2. Lee del PROPIO dump lo que hay que esperar: cantidad de `CREATE TABLE` y
   `alembic_version` (nada hardcodeado).
3. Crea una rama TEMPORAL en Neon: `POST /projects/{id}/branches` con
   `init_source="parent-schema"` (schema del padre SIN datos) + un endpoint chico.
   Doc (verificado en el OpenAPI v2, `BranchCreateRequest.init_source` y en
   https://neon.com/docs/reference/api/branches/create-project-branch.md):
   "parent-schema copies schema only from the parent branch". Ojo: `parent-data` es el
   *default* (esquema + datos), así que el campo hay que mandarlo explícito. `init_source`
   NO está detrás de Early Access (eso es sólo `expires_at`).
   ⚠️ En Free NO se puede setear `suspend_timeout_seconds` (lo dice la doc), así que
   sólo se fijan los límites de autoscaling (mínimo 0.25 CU).
4. Crea una **BASE NUEVA Y VACÍA** en esa rama:
   `POST /projects/{id}/branches/{branch_id}/databases` con
   `{"database": {"name": "drill_restore", "owner_name": "<rol de la rama>"}}`.
   Por qué: restaurar en `neondb` (la base que ya trae el schema copiado del padre)
   fallaría con "already exists" en cada CREATE TABLE. Se restaura en una base vacía.
   Antes de restaurar se COMPRUEBA que esté vacía (0 tablas en `public`); si no lo
   está, se aborta sin tocar nada (no se hace DROP de nada).
5. Restaura con `psql -v ON_ERROR_STOP=1 -f dump.sql` contra el URI de ESA base.
6. Verifica: `usuarios` con count > 0, cantidad de tablas == la del dump, y
   `alembic_version` == la del dump.
7. Prueba negativa con PROD (`PROD_DB_DIRECT_URL`, rol `backup_ro`):
   `BEGIN; CREATE TABLE _drill_no_debe_poder (i int); ROLLBACK;` con ON_ERROR_STOP.
   Debe fallar con "permission denied" (la transacción aborta sola; el ROLLBACK no
   deja nada). Si NO falla: alerta CRÍTICA y abort — no se intenta "arreglar" nada.
8. Borra la rama temporal en `finally` (pase lo que pase) y manda el resultado por
   Gmail SMTP **siempre** (OK o FALLA + motivo), usando `maintenance/alertas.py` (el
   mismo helper del watchdog: nada de duplicar el envío ni otro proveedor de correo).

Guardas
-------
* Antes de crear nada se cuentan las ramas del proyecto: el plan Free permite **10**
  (`MAX_RAMAS`), y "Branch creation fails once you reach 10 branches per project"
  (https://neon.com/docs/introduction/plans). Si está lleno ⇒ exit 2 sin crear rama.
* La rama se crea con `init_source="parent-schema"` (NO `schema-only`): así **no** gasta
  el cupo de root branches del plan Free (3 root branches,
  https://neon.com/docs/guides/branching-schema-only) y cuelga del padre, por lo que se
  puede borrar sin dejar rastro. Lo dice la propia API: `schema-only` "creates a new root
  branch containing schema only, using `parent_id` as the source", mientras que
  `parent-schema` "copies schema only from the parent branch" (OpenAPI v2,
  `BranchCreateRequest.init_source`).
* La base destino se comprueba vacía ANTES de restaurar; si no lo está, se aborta sin
  hacer ningún DROP (no se toca nada existente).
* **Neon es asíncrono:** cada `POST` de rama/base devuelve `operations` que siguen corriendo y,
  si se encadena otra llamada, la API contesta `HTTP 423 "project already has running
  conflicting operations, scheduling of new ones is prohibited"` (bug visto en el run real del
  2026-09-27: la rama se creaba OK y el drill moría con exit 9 en la llamada siguiente). Por eso,
  tras crear la rama y tras crear la base se consulta `GET /projects/{id}/operations/{op_id}`
  (polling cada `DRILL_POLL_S`, timeout `DRILL_OPS_TIMEOUT_S`) hasta que TODAS queden en
  `finished`; `failed`/`error`/`cancelled` ⇒ exit 9 con el motivo. Además TODA llamada a la API
  reintenta el 423 con backoff (2, 4, 8 s; hasta `DRILL_INTENTOS_423` intentos) y el DELETE del
  `finally` espera lo pendiente (`DRILL_BORRADO_TIMEOUT_S`) para no dejar la rama viva.

Exit codes
----------
0 OK · 2 config (falta variable o cupo de ramas agotado) · 8 descarga/dump ilegible ·
9 API Neon (crear rama/base) · 10 restore/verificación (incluye "base destino no vacía") ·
11 la prueba negativa NO falló (crítico) · 12 inesperado.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from maintenance.alertas import VARS_ALERTA, enviar_email  # reporte compartido (Gmail SMTP)
from maintenance.backup_cloud import (  # helpers existentes: no se duplican
    cliente_s3,
    limpiar_valor,
    listar,
    log,
    sanear,
    verificar_dump,
)

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_DESCARGA = 8
EXIT_API = 9
EXIT_RESTORE = 10
EXIT_PERMISOS = 11
EXIT_INESPERADO = 12

VARS_REQUERIDAS = (
    "R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
    *VARS_ALERTA,   # GMAIL_SMTP_USER + GMAIL_SMTP_APP_PASSWORD + ALERT_EMAIL
    "NEON_API_KEY", "NEON_PROJECT_ID",
    "PROD_DB_DIRECT_URL",   # para la prueba negativa (rol backup_ro, solo lectura)
)

NEON_API = (os.getenv("NEON_API_BASE") or "https://console.neon.tech/api/v2").rstrip("/")
PREFIJO = (os.getenv("BACKUP_PREFIX") or "daily/").strip()
DB_DESTINO = os.getenv("DRILL_DB_NAME") or "drill_restore"
ROL_PREFERIDO = os.getenv("DRILL_OWNER_ROLE") or "neondb_owner"
TABLA_SONDA = "_drill_no_debe_poder"
# Cupo de ramas del plan (Free: 10 por proyecto). Configurable por si el plan cambia: el
# guard existe para NO crear una rama que después la API rechace a mitad del drill.
MAX_RAMAS = int(os.getenv("MAX_RAMAS") or "10")
# SMTP_HOST/SMTP_PORT y el armado del mail viven en maintenance/alertas.py (compartido).
USER_AGENT = "urban-box-restore-drill/1.0"

# ── Concurrencia de Neon (HTTP 423) ────────────────────────────────────────────────────
# Neon ejecuta las operaciones de rama/base de forma ASÍNCRONA. Si se encadena otra llamada
# mientras una sigue corriendo, la API contesta HTTP 423 "project already has running
# conflicting operations, scheduling of new ones is prohibited" (bug del run real del
# 2026-09-27: la rama se creó y el drill murió con exit 9 en la llamada siguiente).
# 1) Después de cada POST se esperan las `operations` de la respuesta hasta `finished`.
# 2) Además, toda llamada a la API reintenta el 423 con backoff (red de seguridad).
POLL_OPS = float(os.getenv("DRILL_POLL_S") or "2")                  # polling cada 2 s
TIMEOUT_OPS = float(os.getenv("DRILL_OPS_TIMEOUT_S") or "120")      # 120 s por operación
TIMEOUT_BORRADO = float(os.getenv("DRILL_BORRADO_TIMEOUT_S") or "60")   # espera antes del DELETE
INTENTOS_423 = int(os.getenv("DRILL_INTENTOS_423") or "5")          # máx. 5 intentos
ESPERAS_423 = (2.0, 4.0, 8.0)     # el resto de los intentos repite la última (8 s)
ESTADOS_OK = ("finished", "skipped")              # terminó (skipped: no había nada que hacer)
ESTADOS_MALOS = ("failed", "error", "cancelled")  # falló: el drill corta con ese motivo


def faltantes() -> list:
    return [v for v in VARS_REQUERIDAS if not limpiar_valor(os.getenv(v) or "")]


def http_json(method: str, url: str, body: dict = None, headers: dict = None) -> tuple:
    """(status, payload). Los errores se devuelven para poder reportarlos."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            crudo = r.read().decode("utf-8", errors="replace")
            return r.status, (json.loads(crudo) if crudo.strip() else {})
    except urllib.error.HTTPError as e:
        crudo = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        return e.code, {"error": crudo[:400]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": f"{type(e).__name__}: {e}"}


def _neon_headers() -> dict:
    return {"Authorization": f"Bearer {limpiar_valor(os.environ['NEON_API_KEY'])}"}


def neon_json(method: str, url: str, body: dict = None, headers: dict = None) -> tuple:
    """`http_json` + reintentos con backoff ante HTTP 423.

    423 = "project already has running conflicting operations, scheduling of new ones is
    prohibited": Neon NO ejecutó nada (por eso reintentar es seguro: no duplica ramas ni
    bases), sólo avisa que hay operaciones corriendo. Se reintenta 2, 4, 8, 8… s hasta
    `INTENTOS_423` intentos; si sigue en 423 se devuelve el último resultado tal cual para
    que el llamador lo reporte con su propio exit code. Todo log sale por `log()` (ya
    aplica `sanear`).
    """
    for intento in range(1, INTENTOS_423 + 1):
        status, data = http_json(method, url, body=body, headers=headers)
        if status != 423:
            if intento > 1:
                log(f"{method} {url}: OK en el intento {intento} (venía de HTTP 423)")
            return status, data
        if intento >= INTENTOS_423:
            log(f"AVISO: {method} {url} sigue en HTTP 423 tras {intento} intentos")
            return status, data
        espera = ESPERAS_423[min(intento - 1, len(ESPERAS_423) - 1)]
        log(f"{method} {url}: HTTP 423 (operaciones en curso en el proyecto) -> "
            f"reintento {intento + 1}/{INTENTOS_423} en {espera:.0f} s")
        time.sleep(espera)
    return 423, {"error": "sin respuesta de la API de Neon"}   # inalcanzable


def operaciones_de(data: dict) -> list:
    """ids de las `operations` (asíncronas) que devuelve una respuesta de la API."""
    ops = (data or {}).get("operations") or []
    return [op.get("id") for op in ops if isinstance(op, dict) and op.get("id")]


def _esperar_una_operacion(op_id: str, que: str, timeout: float = None) -> str:
    """Polling de `GET /projects/{id}/operations/{op_id}` hasta que la operación termine.

    Devuelve el estado final. Lanza RuntimeError si queda en failed/error/cancelled o si no
    termina dentro de `timeout` (por defecto `TIMEOUT_OPS`). HTTP 404 ⇒ Neon ya no la lista
    (las purga): se toma como terminada, con el backoff del 423 como red de seguridad.
    """
    pid = limpiar_valor(os.environ["NEON_PROJECT_ID"])
    total = TIMEOUT_OPS if timeout is None else timeout
    limite = time.monotonic() + total
    while True:
        status, data = neon_json("GET", f"{NEON_API}/projects/{pid}/operations/{op_id}",
                                 headers=_neon_headers())
        if status == 404:
            log(f"  operación {op_id} ({que}): HTTP 404 (Neon ya no la lista) -> terminada")
            return "finished"
        if status != 200:
            raise RuntimeError(f"no pude consultar la operación {op_id} ({que}): "
                               f"HTTP {status} {data.get('error')}")
        op = (data or {}).get("operation") or {}
        estado = str(op.get("status") or "").lower()
        if estado in ESTADOS_OK:
            return estado
        if estado in ESTADOS_MALOS:
            raise RuntimeError(f"la operación {op_id} ({que}) quedó en estado '{estado}'"
                               + (f" [{op.get('action')}]" if op.get("action") else ""))
        if time.monotonic() >= limite:
            raise RuntimeError(f"timeout: la operación {op_id} ({que}) sigue en "
                               f"'{estado or 'desconocido'}' después de {total:.0f} s")
        time.sleep(POLL_OPS)


def esperar_operaciones(data: dict, que: str, pendientes: dict = None) -> int:
    """Espera a que TODAS las `operations` de la respuesta estén terminadas (lo pide Neon).

    Devuelve cuántas esperó (0 si la respuesta no traía `operations`). Si se pasa
    `pendientes` (dict op_id -> qué es), cada operación se anota ahí y se desanota al
    terminar: el `finally` usa eso para esperar lo que quedó vivo antes del DELETE.
    """
    ids = operaciones_de(data)
    if not ids:
        return 0
    log(f"esperando {len(ids)} operación(es) de Neon ({que})")
    for op_id in ids:
        if pendientes is not None:
            pendientes[op_id] = que
        estado = _esperar_una_operacion(op_id, que)
        if pendientes is not None:
            pendientes.pop(op_id, None)
        log(f"  operación {op_id} ({que}): {estado}")
    return len(ids)


def branch_default() -> str:
    """branch_id de la rama por defecto del proyecto (la de PROD)."""
    pid = limpiar_valor(os.environ["NEON_PROJECT_ID"])
    status, data = neon_json("GET", f"{NEON_API}/projects/{pid}/branches", headers=_neon_headers())
    if status != 200:
        raise RuntimeError(f"list branches HTTP {status}: {data.get('error')}")
    ramas = data.get("branches", [])
    for b in ramas:
        if b.get("default"):
            return b["id"]
    for b in ramas:
        if b.get("name") in ("main", "production"):
            return b["id"]
    raise RuntimeError("no pude identificar la rama por defecto del proyecto")


def crear_rama(nombre: str, parent_id: str) -> dict:
    """Rama temporal con SOLO el schema del padre (sin datos) + endpoint 0.25 CU."""
    pid = limpiar_valor(os.environ["NEON_PROJECT_ID"])
    body = {
        "branch": {"name": nombre, "parent_id": parent_id, "init_source": "parent-schema"},
        # El campo es `endpoints` (array). NO se manda suspend_timeout_seconds:
        # la doc de Neon dice que en Free no se puede configurar.
        "endpoints": [{
            "type": "read_write",
            "autoscaling_limit_min_cu": 0.25,
            "autoscaling_limit_max_cu": 0.25,
        }],
    }
    status, data = neon_json("POST", f"{NEON_API}/projects/{pid}/branches",
                             body=body, headers=_neon_headers())
    if status not in (200, 201):
        raise RuntimeError(f"create branch HTTP {status}: {data.get('error')}")
    return data


def crear_base(branch_id: str, nombre: str, owner: str) -> dict:
    pid = limpiar_valor(os.environ["NEON_PROJECT_ID"])
    status, data = neon_json(
        "POST", f"{NEON_API}/projects/{pid}/branches/{branch_id}/databases",
        body={"database": {"name": nombre, "owner_name": owner}}, headers=_neon_headers())
    if status not in (200, 201):
        raise RuntimeError(f"create database HTTP {status}: {data.get('error')}")
    return data


def borrar_rama(branch_id: str) -> bool:
    """DELETE de la rama. `neon_json` reintenta 423 (si quedó algo corriendo)."""
    pid = limpiar_valor(os.environ["NEON_PROJECT_ID"])
    status, data = neon_json("DELETE", f"{NEON_API}/projects/{pid}/branches/{branch_id}",
                             headers=_neon_headers())
    ok = status in (200, 202, 204)
    log(f"borrar rama {branch_id}: HTTP {status}" + ("" if ok else f" -> {data.get('error')}"))
    return ok


def rol_de_la_rama(data_rama: dict) -> str:
    """Rol con password de la rama nueva (preferimos neondb_owner)."""
    roles = data_rama.get("roles") or []
    for r in roles:
        if r.get("name") == ROL_PREFERIDO:
            return ROL_PREFERIDO
    for r in roles:
        if r.get("authentication_method") == "password":
            return r["name"]
    return ROL_PREFERIDO


def uri_para(data_rama: dict, dbname: str) -> str:
    """URI de conexión para OTRA base de la misma rama (cambia el path de la URI)."""
    uris = data_rama.get("connection_uris") or []
    for u in uris:
        uri = u.get("connection_uri") or ""
        if not uri:
            continue
        cabeza, _, cola = uri.partition("?")
        base = cabeza.rsplit("/", 1)[0]
        return f"{base}/{dbname}" + (f"?{cola}" if cola else "")
    raise RuntimeError("la respuesta de create branch no trajo connection_uris")

def contar_ramas() -> int:
    """Cuántas ramas tiene el proyecto (Free: 10/proyecto — ver MAX_RAMAS).

    Doc: "Branches 10/project" y "Branch creation fails once you reach 10 branches per
    project" (https://neon.com/docs/introduction/plans).
    """
    pid = limpiar_valor(os.environ["NEON_PROJECT_ID"])
    status, data = neon_json("GET", f"{NEON_API}/projects/{pid}/branches", headers=_neon_headers())
    if status != 200:
        raise RuntimeError(f"list branches HTTP {status}: {data.get('error')}")
    return len(data.get("branches") or [])


# ── Descarga del backup desde R2 ───────────────────────────────────────────
def bajar_ultimo(destino_gz) -> tuple:
    """(clave, bytes) del objeto más nuevo de daily/. Lanza FileNotFoundError si no hay."""
    cli = cliente_s3()
    objetos = listar(cli, PREFIJO)
    if not objetos:
        raise FileNotFoundError(f"no hay objetos en {PREFIJO!r}")
    nuevo = max(objetos, key=lambda o: o["LastModified"])
    cli.download_file(os.environ["R2_BUCKET"], nuevo["Key"], str(destino_gz))
    return nuevo["Key"], nuevo["Size"]


def descomprimir(gz_path, sql_path) -> None:
    with gzip.open(gz_path, "rb") as fi, open(sql_path, "wb") as fo:
        shutil.copyfileobj(fi, fo)


def esperar_del_dump(sql_path) -> tuple:
    """(tablas, alembic) leídos del PROPIO dump: el drill no hardcodea nada.

    Reusa `verificar_dump` de backup_cloud, o sea el MISMO criterio que valida el backup
    diario (tamaño, `CREATE TABLE`, footer y `COPY public.alembic_version`): si el dump
    que está en R2 no pasa esos controles, el drill no arranca.
    """
    info = verificar_dump(Path(sql_path))
    if info["problemas"]:
        raise RuntimeError("el dump no pasó los controles: " + "; ".join(info["problemas"]))
    if not info["alembic"]:
        raise RuntimeError("no pude leer alembic_version del dump")
    return info["tablas"], info["alembic"]


# ── psql ───────────────────────────────────────────────────────────────────
def psql_sql(url: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-tAc", sql],
                          capture_output=True, text=True)


def psql_restore(url: str, sql_path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(sql_path)],
                          capture_output=True, text=True)


def contar_tablas(url: str) -> int:
    r = psql_sql(url, "SELECT count(*) FROM information_schema.tables "
                      "WHERE table_schema='public'")
    if r.returncode != 0:
        raise RuntimeError(f"no pude contar tablas: {sanear(r.stderr or '')[:200]}")
    return int((r.stdout or "0").strip() or 0)


def verificar_restore(url: str, esperado_tablas: int, esperado_alembic: str) -> tuple:
    """(ok, detalle). Compara contra lo que dice EL PROPIO DUMP (nada hardcodeado)."""
    tablas = contar_tablas(url)
    r_usr = psql_sql(url, "SELECT count(*) FROM usuarios")
    usuarios = int((r_usr.stdout or "0").strip() or 0) if r_usr.returncode == 0 else -1
    r_alb = psql_sql(url, "SELECT version_num FROM alembic_version")
    alembic = (r_alb.stdout or "").strip()
    ok = (tablas == esperado_tablas and usuarios > 0 and alembic == esperado_alembic)
    return ok, {"tablas": tablas, "tablas_esperadas": esperado_tablas,
                "usuarios": usuarios, "alembic": alembic,
                "alembic_esperado": esperado_alembic}


def probar_solo_lectura_prod() -> tuple:
    """(ok, detalle): con el rol de backup, crear una tabla en PROD DEBE fallar.

    Se manda `BEGIN; CREATE TABLE …; ROLLBACK;`: si el rol escribiera, el ROLLBACK
    deshace la tabla (no queda basura y no se hace ningún DROP "para arreglar").
    """
    url = limpiar_valor(os.environ["PROD_DB_DIRECT_URL"])
    sql = f"BEGIN; CREATE TABLE {TABLA_SONDA} (i int); ROLLBACK;"
    r = psql_sql(url, sql)
    err = (r.stderr or "").lower()
    if r.returncode != 0 and "permission denied" in err:
        return True, "permission denied (correcto: el rol de backup no puede escribir)"
    if r.returncode == 0:
        return False, ("EL ROL DE BACKUP PUDO CREAR UNA TABLA EN PROD "
                       "(el ROLLBACK la deshizo). Revisar GRANT/rol en Neon.")
    return False, f"rc={r.returncode} sin 'permission denied': {sanear(r.stderr or '')[:200]}"


# ── Reporte por email (compartido con el watchdog: maintenance/alertas.py) ──
def enviar_reporte(ok: bool, motivo: str, detalle: dict, inicio: datetime) -> bool:
    """Email SIEMPRE (OK o FALLA + motivo). Nada de credenciales: todo pasa por log/sanear."""
    segundos = (datetime.now(timezone.utc) - inicio).total_seconds()
    asunto = f"[Box CrossFit] drill de restore PROD — {'OK' if ok else 'FALLA'}: {motivo}"
    filas = "".join(f"<li><b>{k}</b>: {v}</li>" for k, v in sorted((detalle or {}).items())
                    if v not in (None, ""))
    html = (
        "<h3>Drill de restore (backup de R2 → rama temporal de Neon)</h3>"
        f"<p><b>Resultado:</b> {'OK ✅' if ok else 'FALLA ❌'}<br>"
        f"<b>Motivo:</b> {motivo}<br>"
        f"<b>Duración:</b> {segundos:.0f} s · <b>Inicio (UTC):</b> "
        f"{inicio.strftime('%Y-%m-%d %H:%M')}</p>"
        f"<ul>{filas or '<li>(sin detalle)</li>'}</ul>"
        "<p>La rama temporal se borra SIEMPRE (en el <code>finally</code>), aunque el drill"
        " falle. Si el run quedó rojo en Render, revisar el log del Cron Job "
        "<i>box-crossfit-restore-drill → Runs</i>.</p>"
    )
    return enviar_email(asunto, html)


def reportar(ok: bool, motivo: str, detalle: dict, inicio: datetime, code: int) -> int:
    """Único punto de salida de main(): log + email SIEMPRE + exit code."""
    log(("OK: " if ok else "FALLA: ") + motivo)
    for k, v in sorted((detalle or {}).items()):
        log(f"  {k}: {v}")
    if not enviar_reporte(ok, motivo, detalle, inicio):
        log("AVISO: el reporte no salió por Gmail; el exit code no cambia")
    return code


# ── main ───────────────────────────────────────────────────────────────────
def main() -> int:
    log("=== drill de restore (backup de R2 → rama temporal de Neon) ===")
    inicio = datetime.now(timezone.utc)

    falta = faltantes()
    if falta:
        log(f"FATAL (config): faltan variables de entorno: {', '.join(falta)}")
        return EXIT_CONFIG

    detalle = {}
    rama_id = None
    pendientes = {}      # op_id -> qué operación es (lo que quedó corriendo: ver el finally)
    tmp = Path(tempfile.mkdtemp(prefix="drill_"))
    gz, sql = tmp / "backup.sql.gz", tmp / "backup.sql"
    try:
        # 0. Cupo de ramas del plan (Free: 10/proyecto). Si está lleno NO se crea nada.
        try:
            ramas = contar_ramas()
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"no pude listar las ramas del proyecto: {sanear(e)[:300]}",
                            detalle, inicio, EXIT_API)
        detalle["ramas"] = ramas
        log(f"ramas del proyecto: {ramas} (máximo: {MAX_RAMAS})")
        if ramas >= MAX_RAMAS:
            return reportar(False, f"el proyecto ya tiene {ramas} ramas y el plan permite "
                                   f"{MAX_RAMAS}", detalle, inicio, EXIT_CONFIG)

        # 1. El objeto más nuevo de daily/ en R2.
        try:
            clave, bytes_ = bajar_ultimo(gz)
        except FileNotFoundError as e:
            return reportar(False, f"no hay backups en R2: {e}", detalle, inicio, EXIT_DESCARGA)
        except Exception as e:  # noqa: BLE001
            err = sanear(f"{type(e).__name__}: {e}")[:300]
            return reportar(False, f"no pude bajar el backup de R2: {err}",
                            detalle, inicio, EXIT_DESCARGA)
        detalle["backup"] = clave
        log(f"backup: {clave} ({bytes_ / 1024:.1f} KB)")

        # 2. Descomprimir y sacar del PROPIO dump qué hay que esperar.
        try:
            descomprimir(gz, sql)
            esperado_tablas, esperado_alembic = esperar_del_dump(sql)
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"el dump no sirve para el drill: {sanear(e)[:300]}",
                            detalle, inicio, EXIT_DESCARGA)
        detalle["tablas_esperadas"] = esperado_tablas
        detalle["alembic_esperado"] = esperado_alembic
        log(f"el dump dice: {esperado_tablas} CREATE TABLE · alembic {esperado_alembic}")

        # 3. Rama temporal: SOLO el schema del padre (sin datos) + endpoint 0.25 CU.
        try:
            data_rama = crear_rama(f"drill-{inicio.strftime('%Y%m%d-%H%M')}", branch_default())
            rama_id = (data_rama.get("branch") or {}).get("id") or data_rama.get("id")
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"no pude crear la rama temporal: {sanear(e)[:300]}",
                            detalle, inicio, EXIT_API)
        if not rama_id:
            raise RuntimeError("la API no devolvió el id de la rama nueva")
        detalle["rama"] = rama_id
        log(f"rama temporal: {rama_id} (se borra en el finally)")

        # 3b. Neon es asíncrono: el POST devolvió `operations` que siguen corriendo. Si se
        #     encadena el POST de la base sin esperarlas, la API contesta 423 "project
        #     already has running conflicting operations, scheduling of new ones is
        #     prohibited" (bug del run real del 2026-09-27: la rama se creaba OK y el drill
        #     moría con exit 9 en la llamada siguiente). Se espera hasta `finished`.
        try:
            esperadas = esperar_operaciones(data_rama, "la rama temporal", pendientes)
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"no pude esperar la creación de la rama: {sanear(e)[:300]}",
                            detalle, inicio, EXIT_API)

        # 4. Base NUEVA Y VACÍA en esa rama: restaurar sobre `neondb` daría "already exists"
        #    en cada CREATE TABLE (esa base ya trae el schema copiado del padre).
        try:
            data_base = crear_base(rama_id, DB_DESTINO, rol_de_la_rama(data_rama))
            uri = uri_para(data_rama, DB_DESTINO)
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"no pude preparar la base {DB_DESTINO}: {sanear(e)[:300]}",
                            detalle, inicio, EXIT_API)

        # 4b. Igual que en 3b, ahora con la base: el DELETE final también responde 423 si algo
        #     sigue corriendo, así que se espera acá (y no en el finally, que es el último
        #     recurso).
        try:
            esperadas += esperar_operaciones(data_base, f"la base {DB_DESTINO}", pendientes)
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"no pude esperar la creación de la base {DB_DESTINO}: "
                                   f"{sanear(e)[:300]}", detalle, inicio, EXIT_API)
        if esperadas:
            detalle["operaciones_esperadas"] = esperadas

        try:
            tablas_antes = contar_tablas(uri)
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"no pude consultar la base destino: {sanear(e)[:300]}",
                            detalle, inicio, EXIT_RESTORE)
        if tablas_antes != 0:
            detalle["tablas_en_destino"] = tablas_antes
            return reportar(False, f"la base destino {DB_DESTINO} NO está vacía "
                                   f"({tablas_antes} tablas): se aborta sin tocar nada",
                            detalle, inicio, EXIT_RESTORE)

        # 5. Restore real del dump.
        try:
            r = psql_restore(uri, sql)
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"no pude ejecutar psql: {sanear(e)[:300]}",
                            detalle, inicio, EXIT_RESTORE)
        if r.returncode != 0:
            detalle["psql_rc"] = r.returncode
            detalle["psql_error"] = sanear(r.stderr or r.stdout or "")[:400]
            return reportar(False, "el restore falló", detalle, inicio, EXIT_RESTORE)

        # 6. Verificación contra lo que dice el dump (nada hardcodeado).
        try:
            ok_restore, det_restore = verificar_restore(uri, esperado_tablas, esperado_alembic)
        except Exception as e:  # noqa: BLE001
            return reportar(False, f"no pude verificar el restore: {sanear(e)[:300]}",
                            detalle, inicio, EXIT_RESTORE)
        detalle.update(det_restore)
        if not ok_restore:
            return reportar(False, "el restore no coincide con el dump",
                            detalle, inicio, EXIT_RESTORE)

        # 7. Prueba negativa: el rol de backup NO debe poder escribir en PROD.
        try:
            ok_neg, msg_neg = probar_solo_lectura_prod()
        except Exception as e:  # noqa: BLE001
            return reportar(False, "no pude correr la prueba negativa contra PROD: "
                                   f"{sanear(e)[:300]}", detalle, inicio, EXIT_RESTORE)
        detalle["solo_lectura"] = msg_neg
        if not ok_neg:
            return reportar(False, f"CRÍTICO: {msg_neg}", detalle, inicio, EXIT_PERMISOS)

        return reportar(True, f"restore verificado ({detalle.get('tablas')} tablas, "
                              f"{detalle.get('usuarios')} usuarios, alembic "
                              f"{detalle.get('alembic')}) y el rol de backup sigue siendo "
                              "de solo lectura", detalle, inicio, EXIT_OK)
    except Exception as e:  # noqa: BLE001
        err = sanear(f"{type(e).__name__}: {e}")[:300]
        return reportar(False, f"error inesperado: {err}", detalle, inicio, EXIT_INESPERADO)
    finally:
        # Nada de la rama temporal puede quedar vivo: se borra pase lo que pase.
        shutil.rmtree(tmp, ignore_errors=True)
        if rama_id:
            # Antes del DELETE: si quedó alguna operación corriendo, la API contesta 423 y la
            # rama seguiría viva (consume cupo del plan Free y deja basura en Neon). El timeout
            # acá es corto: el DELETE ya reintenta 423 por su cuenta.
            for op_id, que in list(pendientes.items()):
                try:
                    _esperar_una_operacion(op_id, f"{que}, antes del DELETE", TIMEOUT_BORRADO)
                except Exception as e:  # noqa: BLE001
                    log(f"AVISO: no pude confirmar la operación {op_id} antes de borrar la "
                        f"rama: {sanear(e)[:200]}")
            try:
                borrada, error_borrado = borrar_rama(rama_id), None
            except Exception as e:  # noqa: BLE001
                borrada, error_borrado = False, sanear(e)[:200]
            if not borrada:
                log(f"FATAL: la rama temporal {rama_id} quedó viva"
                    + (f" ({error_borrado})" if error_borrado else "")
                    + ": BORRARLA A MANO en la consola de Neon (consume cupo del plan Free)")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        log(f"FATAL inesperado: {type(e).__name__}: {e}")
        sys.exit(EXIT_INESPERADO)


