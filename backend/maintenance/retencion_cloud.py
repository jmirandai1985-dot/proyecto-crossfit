"""Retención de datos (B8) — archivar, purgar y anonimizar por plazo

Qué hace (docs/RETENCION_DATOS_Y_N8N.md §1, bloque B8)
-----------------------------------------------------
Tres trabajos independientes, uno por Cron Job (`render.yaml`), con un solo
`dockerCommand` de este módulo:

  * `archivar`      — mueve a las tablas de archivo `asistencias` y `reservas` con
                      más de **5 años**. Copia → respalda en R2 → recién ahí borra.
  * `auditoria`     — borra `auditoria` con más de **2 años** (no se archiva: la
                      auditoría vieja no se consulta).
  * `anonimizar`    — a los **12 meses** de la baja reemplaza nombre, correo,
                      teléfono y RUT del alumno por valores anónimos y sella
                      `usuarios.anonimizado_en`. Las fechas, conteos y el historial
                      se conservan (son las estadísticas que pide el negocio).

Por qué NO usa la app
---------------------
Mismo criterio que `mantenimiento_cloud.py` y `backup_cloud.py`: el contenedor de
cron no incluye `app/` (ni SQLAlchemy, ni el modelo de settings). Todo el SQL va
por `psql` con `ON_ERROR_STOP=1` en procesos con lista de argumentos (sin shell),
y los números que llegan al SQL se validan antes como enteros en rango — nunca se
pega texto de una variable de entorno.

Por qué el borrado es en dos pasos (respaldo ANTES del DELETE)
--------------------------------------------------------------
El archivado no es un `DELETE`: las filas se copian a `*_archivo`, después se
exportan a CSV.gz y se suben a R2 **verificando el sha256 del objeto que quedó
guardado**, y sólo entonces se borran del origen, siempre que dentro de la misma
transacción se compruebe (a) que el archivo tiene las N filas y (b) que el `md5`
del contenido archivado es igual al del origen. Cualquier falla deja las filas en
el origen (se reintenta la próxima corrida; la copia es idempotente con
`ON CONFLICT (id) DO NOTHING`).

El bloqueo (`lock_de_job`)
--------------------------
`app/services/scheduler_lock.py` usa `pg_try_advisory_lock` sobre una conexión
larga. Acá no hay conexión larga: cada `psql` es un proceso de un comando, así que
el bloqueo vive en la tabla `retencion_bloqueos` (una fila por trabajo con `token`
y `expira_en`): un doble disparo no corre dos veces y, si un run se cae sin
liberar, el siguiente lo toma al vencer.

Correo
------
Gmail SMTP por `alertas.enviar_email` (nunca otro proveedor). Sale correo si el
run falló **o si movió/purgó/anonimizó algo** (en DRY_RUN, si "habría" movido
algo): un trabajo irreversible tiene que dejar constancia. Un run sin nada que
hacer sólo deja log.

Uso
---
    python -m maintenance.retencion_cloud archivar
    python -m maintenance.retencion_cloud auditoria
    python -m maintenance.retencion_cloud anonimizar

Exit codes: 0 OK · 2 config · 3 lectura · 4 respaldo · 5 guarda de volumen ·
6 escritura · 7 verificación posterior.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from maintenance.alertas import VARS_ALERTA, enviar_email        # noqa: E402
from maintenance.backup_cloud import (                           # noqa: E402
    ConfigError, S3Error, cliente_s3, host_de, limpiar_valor, sanear,
)

# ── Exit codes (mismo criterio que mantenimiento/backup, sin solaparse) ─────
EXIT_OK = 0
EXIT_CONFIG = 2        # falta variable / URL de otro entorno / -pooler / número fuera de rango
EXIT_LECTURA = 3       # un SELECT/COPY falló (permisos, red, esquema sin migrar)
EXIT_RESPALDO = 4      # el CSV no se generó o no quedó verificado en R2 ⇒ NO se borra nada
EXIT_GUARDA = 5        # el volumen supera el tope por corrida o los conteos son incoherentes
EXIT_ESCRITURA = 6     # la transacción de copia o de borrado falló (no se aplicó)
EXIT_VERIFICACION = 7  # la verificación posterior no cuadró

TITULOS_EXIT = {
    EXIT_OK: "ok",
    EXIT_CONFIG: "configuración",
    EXIT_LECTURA: "lectura",
    EXIT_RESPALDO: "respaldo",
    EXIT_GUARDA: "guarda de volumen",
    EXIT_ESCRITURA: "escritura",
    EXIT_VERIFICACION: "verificación",
}

TRABAJOS = ("archivar", "auditoria", "anonimizar")

USUARIO_ROL = "retencion_rw"   # el único rol que escribe en PROD (ver README, Fase 12)
TABLA_BLOQUEOS = "retencion_bloqueos"

# ── Guardas TEST/PROD: espejo de app/core/config.py ────────────────────────
# El contenedor de cron no tiene `app/`, así que no puede importar `is_test_db_url`.
# Estas tuplas son una COPIA literal de app/core/config.py; si cambia la rama se
# actualizan en los dos lugares, y `tests/test_retencion_unit.py` (que sí importa
# `app.core.config`) falla si dejan de coincidir.
TEST_BRANCH_IDS = (
    "ep-crimson-tooth-akhx7q2s",
)
PROD_BRANCH_IDS = (
    "ep-winter-star-akwis51j",
    "ep-bitter-cloud-arat6wil",
)
ENDPOINTS_RETIRADOS = (
    "ep-lingering-fog-arywdnbg",
    "ep-damp-base-b6mpe739",
    "ep-winter-boat-b6zpvtxu",
    "ep-summer-river-b6c8fj2f",
    "ep-jolly-butterfly-b6ty2z89",
    "ep-nameless-sound-b6km6wyi",
    "ep-withered-silence-acly7gq5",
)

VARS_BASE = ("RETENCION_DB_URL", "ENVIRONMENT", "DRY_RUN")
VARS_R2 = ("R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


class LecturaError(RuntimeError):
    pass


class RespaldoError(RuntimeError):
    pass


class GuardaError(RuntimeError):
    pass


class EscrituraError(RuntimeError):
    pass


class VerificacionError(RuntimeError):
    pass


def log(msg: str) -> None:
    """Log del job. `flush=True` para que Render muestre las líneas en orden y
    `sanear()` para que ninguna credencial pueda llegar al log del run."""
    print(f"[retencion] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
          f"{sanear(msg)}", flush=True)


# ── Configuración: TODO se valida antes de tocar la base ───────────────────
def _texto(env: dict, nombre: str, defecto: str = "") -> str:
    return limpiar_valor(env.get(nombre) or defecto)


def _entero(env: dict, nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    """Entero validado: el ÚNICO camino por el que un número llega al SQL."""
    crudo = _texto(env, nombre) or str(defecto)
    if not re.fullmatch(r"\d{1,9}", crudo):
        raise ConfigError(f"{nombre} tiene que ser un entero (llegó {crudo!r})")
    valor = int(crudo)
    if not minimo <= valor <= maximo:
        raise ConfigError(
            f"{nombre} fuera de rango ({minimo}..{maximo}): {valor}")
    return valor


def _booleano(env: dict, nombre: str, defecto: bool) -> bool:
    crudo = (_texto(env, nombre) or ("1" if defecto else "0")).lower()
    if crudo in ("1", "true", "si", "sí", "yes", "on"):
        return True
    if crudo in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{nombre} tiene que ser 0/1 (llegó {crudo!r})")


def clasificar_url(url: str) -> str:
    """`test` | `prod` | `retirada` | `desconocida` (fail-closed: ante la duda,
    desconocida). Espejo de `app/core/config.is_test_db_url()`."""
    u = url or ""
    if any(b in u for b in ENDPOINTS_RETIRADOS):
        return "retirada"
    if any(b in u for b in PROD_BRANCH_IDS):
        return "prod"
    if any(b in u for b in TEST_BRANCH_IDS):
        return "test"
    return "desconocida"


def validar_url(url: str, entorno: str) -> str:
    """Motivo del rechazo ('' = OK). Nunca devuelve el valor del secreto."""
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

    clase = clasificar_url(url)
    if clase == "retirada":
        return "apunta a un endpoint RETIRADO que todavía tiene datos reales"
    if entorno == "production":
        if clase == "test":
            return "apunta a una rama TEST (¿se copió .env.test?)"
        if clase == "desconocida":
            return ("no es el endpoint de PROD conocido (si la rama cambió, "
                    "actualizar PROD_BRANCH_IDS en este módulo y en app/core/config.py)")
        if usuario != USUARIO_ROL:
            return f"el usuario no es {USUARIO_ROL}"
    else:
        if clase != "test":
            return ("ENVIRONMENT=test pero la URL no es la rama TEST conocida "
                    "(TEST_BRANCH_IDS)")
    return ""


def cargar_config(trabajo: str, env: dict | None = None) -> dict:
    """Lee y VALIDA la configuración completa. Cualquier anomalía ⇒ ConfigError
    (exit 2) antes de abrir una sola conexión."""
    if trabajo not in TRABAJOS:
        raise ConfigError(
            f"trabajo desconocido: {trabajo!r} (usar {' | '.join(TRABAJOS)})")
    env = dict(os.environ) if env is None else dict(env)

    faltan = [v for v in VARS_BASE if not _texto(env, v)]
    respaldo_local = _texto(env, "RETENCION_RESPALDO_LOCAL")
    if trabajo == "anonimizar" and not _texto(env, "ANONIMIZACION_PEPPER"):
        faltan.append("ANONIMIZACION_PEPPER")
    if trabajo == "archivar" and not respaldo_local:
        faltan += [v for v in VARS_R2 if not _texto(env, v)]
    if faltan:
        raise ConfigError("faltan variables obligatorias: "
                          + ", ".join(sorted(set(faltan))))

    entorno = _texto(env, "ENVIRONMENT").lower()
    if entorno not in ("production", "test"):
        raise ConfigError("ENVIRONMENT tiene que ser 'production' o 'test' "
                          f"(llegó {entorno!r})")
    url = _texto(env, "RETENCION_DB_URL")
    motivo = validar_url(url, entorno)
    if motivo:
        raise ConfigError(f"RETENCION_DB_URL rechazada: {motivo}")

    dry_run = _booleano(env, "DRY_RUN", True)
    if entorno == "test" and not dry_run and _texto(env, "RETENCION_TEST_OK") != "1":
        raise ConfigError("escribir de verdad contra TEST exige "
                          "RETENCION_TEST_OK=1 (guarda anti-PROD)")

    pepper = _texto(env, "ANONIMIZACION_PEPPER")
    if trabajo == "anonimizar" and len(pepper) < 16:
        raise ConfigError("ANONIMIZACION_PEPPER tiene que tener al menos 16 "
                          "caracteres (es la sal del hash del RUT)")

    return {
        "trabajo": trabajo,
        "entorno": entorno,
        "clase_url": clasificar_url(url),
        "url": url,
        "host": host_de(url),
        "dry_run": dry_run,
        "anios_archivo": _entero(env, "ANIOS_RETENCION_ARCHIVO", 5, 1, 50),
        "anios_auditoria": _entero(env, "ANIOS_RETENCION_AUDITORIA", 2, 1, 50),
        "meses_anonimizar": _entero(env, "MESES_RETENCION_ANONIMIZAR", 12, 1, 120),
        "lote": _entero(env, "TAM_LOTE", 5000, 1, 50_000),
        "max_archivar": _entero(env, "MAX_ARCHIVAR", 20_000, 1, 1_000_000),
        "max_auditoria": _entero(env, "MAX_BORRAR_AUDITORIA", 100_000, 1, 5_000_000),
        "max_anonimizar": _entero(env, "MAX_ANONIMIZAR", 1_000, 1, 100_000),
        "lock_horas": _entero(env, "RETENCION_LOCK_HORAS", 12, 1, 72),
        "pepper": pepper,
        "respaldo_local": respaldo_local,
        "prefijo": (_texto(env, "RETENCION_PREFIJO") or "retencion/").strip("/") + "/",
        "alertas": all(_texto(env, v) for v in VARS_ALERTA),
    }


# ── Qué tablas toca cada trabajo ───────────────────────────────────────────
# `columnas` es la lista EXACTA de columnas de la tabla de origen (incluidas las
# que el archivo no tiene: `archivado_en` sólo existe en el destino). Se usa para
# copiar, para exportar a CSV y para comparar por md5; si una columna nueva se
# agrega a `asistencias`/`reservas`, hay que sumarla acá (el test del modelo lo
# detecta).
TABLAS_ARCHIVO = {
    "asistencias": {
        "archivo": "asistencias_archivo",
        "columna_fecha": "fecha",
        "tipo_fecha": "date",
        "columnas": ("id", "tenant_id", "usuario_id", "fecha", "clase",
                     "clase_id", "presente", "created_at"),
    },
    "reservas": {
        "archivo": "reservas_archivo",
        "columna_fecha": "fecha_reserva",
        "tipo_fecha": "timestamp",
        "columnas": ("id", "tenant_id", "clase_id", "alumno_id",
                     "fecha_reserva", "asistio", "tokens_gastados",
                     "suscripcion_id", "estado", "asistencia_marcada_por",
                     "asistencia_marcada_at", "asistencia_via", "created_at",
                     "updated_at"),
    },
}

# Zona fija en TODAS las sesiones: el md5 de `ROW(...)::text` compara texto y un
# timestamp se imprime distinto según el TimeZone del server. Con esto, origen y
# archivo se comparan siempre igual.
PROLOGO = "SET TIME ZONE 'UTC';\nSET client_min_messages = warning;\n"

SQL_ESQUEMA = (
    "SELECT coalesce(string_agg(o.nombre, ', '), '') FROM (VALUES\n"
    "  ('asistencias_archivo', to_regclass('public.asistencias_archivo') IS NOT NULL),\n"
    "  ('reservas_archivo', to_regclass('public.reservas_archivo') IS NOT NULL),\n"
    "  ('retencion_bloqueos', to_regclass('public.retencion_bloqueos') IS NOT NULL),\n"
    "  ('usuarios.anonimizado_en', (SELECT count(*) > 0 FROM "
    "information_schema.columns WHERE table_schema = 'public' AND "
    "table_name = 'usuarios' AND column_name = 'anonimizado_en'))\n"
    ") AS o(nombre, presente) WHERE NOT o.presente;\n"
)


# ── psql: un proceso por comando, lista de argumentos (nunca un shell) ──────
def kwargs_texto() -> dict:
    """kwargs de subprocess para decodificar SIEMPRE en UTF-8.

    `text=True` a secas usa la codificación del sistema (cp1252 en Windows) y las
    tildes de cualquier error de Postgres rompen la lectura. En Linux coincide.
    """
    return {"text": True, "encoding": "utf-8", "errors": "replace"}


def _psql(url: str, argumentos: list) -> str:
    """Corre psql y devuelve stdout. Cualquier rc ≠ 0 ⇒ LecturaError con stderr
    saneado (es el único lugar donde puede aparecer la URL con credenciales)."""
    r = subprocess.run(["psql", url, "-X", "-q", "-t", "-A", "-v",
                        "ON_ERROR_STOP=1"] + argumentos,
                       capture_output=True, **kwargs_texto())
    if r.returncode != 0:
        raise LecturaError(f"psql rc={r.returncode}: "
                           f"{(r.stderr or '').strip()[:800]}")
    return (r.stdout or "").strip()


def script(url: str, texto: str, transaccion: bool = True) -> str:
    """Corre un script .sql desde un archivo temporal (evita el infierno de
    comillas de Windows) envuelto en UNA transacción (`--single-transaction`)."""
    fd, ruta = tempfile.mkstemp(prefix="retencion_", suffix=".sql")
    os.close(fd)
    try:
        Path(ruta).write_text(texto, encoding="utf-8")
        args = ["-f", ruta]
        if transaccion:
            args = ["--single-transaction"] + args
        return _psql(url, args)
    finally:
        try:
            os.unlink(ruta)
        except OSError:
            pass


def consulta(url: str, sql: str) -> str:
    return _psql(url, ["-c", PROLOGO + sql])


def consulta_entero(url: str, sql: str) -> int:
    crudo = consulta(url, sql)
    try:
        return int(crudo.splitlines()[-1].strip() or 0)
    except (ValueError, IndexError):
        raise LecturaError(f"se esperaba un entero y llegó {crudo!r}")


def verificar_esquema(url: str) -> None:
    """Falla con un mensaje claro si falta la migración 065 (nada de un SQL que
    revienta a mitad de camino)."""
    faltan = consulta(url, SQL_ESQUEMA)
    if faltan:
        raise LecturaError("falta la migración 065_retencion_datos: no existe "
                           f"{faltan} (aplicar `alembic upgrade head`)")


# ── SQL del archivado ──────────────────────────────────────────────────────
def corte(columna: str, tipo: str, anios: int) -> str:
    """Corte de retención: `fecha < corte` = "más viejo que N años"."""
    base = "CURRENT_DATE" if tipo == "date" else "now()"
    return f"({base} - INTERVAL '{int(anios)} years')"


def sql_pendientes(tabla: str, cfg: dict) -> str:
    meta = TABLAS_ARCHIVO[tabla]
    return (f"SELECT count(*) FROM {tabla} t WHERE t.{meta['columna_fecha']} "
            f"< {corte(meta['columna_fecha'], meta['tipo_fecha'], cfg['anios_archivo'])};\n")


def sql_lote(tabla: str, cfg: dict, limite: int) -> str:
    meta = TABLAS_ARCHIVO[tabla]
    return (f"SELECT id FROM {tabla} t WHERE t.{meta['columna_fecha']} "
            f"< {corte(meta['columna_fecha'], meta['tipo_fecha'], cfg['anios_archivo'])} "
            f"ORDER BY t.id LIMIT {int(limite)};\n")


def sql_md5(tabla: str, meta: dict, ids: list, alias: str = "t") -> str:
    """md5 del contenido de esas filas, con las columnas compartidas y en UTC."""
    fila = "ROW(" + ", ".join(f"{alias}.{c}" for c in meta["columnas"]) + ")::text"
    return (f"(SELECT md5(coalesce(string_agg({fila}, '|' ORDER BY {alias}.id), '')) "
            f"FROM {tabla} {alias} WHERE {alias}.id = ANY({lista_ids(ids)}))")


def lista_ids(ids: list) -> str:
    """Array de enteros: cada id pasa por int() (nunca texto de afuera)."""
    return "ARRAY[" + ",".join(str(int(i)) for i in ids) + "]::int[]"


def script_copiar(tabla: str, ids: list) -> str:
    """Paso 1: copia el lote al archivo y COMPRUEBA que quedó idéntico.

    Idempotente: si el id ya está en el archivo no se toca (`DO NOTHING`), así una
    corrida cortada se puede repetir. Si el origen cambió desde que se leyó el
    lote (otra corrida, un DELETE manual) aborta en vez de copiar de menos.
    """
    meta = TABLAS_ARCHIVO[tabla]
    dest = meta["archivo"]
    cols = ", ".join(meta["columnas"])
    ids_sql = lista_ids(ids)
    n = len(ids)
    return (
        PROLOGO
        + "DO $retencion$\n"
        "DECLARE n int; m_src text; m_dst text;\n"
        "BEGIN\n"
        f"  SELECT count(*) INTO n FROM {tabla} t WHERE t.id = ANY({ids_sql});\n"
        f"  IF n <> {n} THEN\n"
        f"    RAISE EXCEPTION 'EL ORIGEN CAMBIÓ: % de {n} filas de {tabla} ya no "
        "están (¿otra corrida en paralelo?)', n;\n"
        "  END IF;\n"
        f"  INSERT INTO {dest} ({cols}) SELECT {cols} FROM {tabla} t "
        f"WHERE t.id = ANY({ids_sql}) ON CONFLICT (id) DO NOTHING;\n"
        f"  SELECT count(*) INTO n FROM {dest} a WHERE a.id = ANY({ids_sql});\n"
        f"  IF n <> {n} THEN\n"
        f"    RAISE EXCEPTION 'COPIA INCOMPLETA: % de {n} filas quedaron en {dest}', n;\n"
        "  END IF;\n"
        f"  m_src := {sql_md5(tabla, meta, ids)};\n"
        f"  m_dst := {sql_md5(dest, meta, ids, 'a')};\n"
        "  IF m_src IS DISTINCT FROM m_dst THEN\n"
        f"    RAISE EXCEPTION 'COPIA DISTINTA: el md5 de {dest} no coincide con {tabla}';\n"
        "  END IF;\n"
        "END $retencion$;\n"
    )


def script_borrar(tabla: str, ids: list) -> str:
    """Paso 3: borra del origen SÓLO si el archivo tiene las N filas y coincide.

    Todo en una transacción: si algo falla no se borra nada, y el reintento de la
    próxima corrida encuentra el trabajo hecho (el archivo ya tiene las filas).
    """
    meta = TABLAS_ARCHIVO[tabla]
    dest = meta["archivo"]
    ids_sql = lista_ids(ids)
    n = len(ids)
    return (
        PROLOGO
        + "DO $retencion$\n"
        "DECLARE n int; m_src text; m_dst text;\n"
        "BEGIN\n"
        f"  SELECT count(*) INTO n FROM {dest} a WHERE a.id = ANY({ids_sql});\n"
        f"  IF n <> {n} THEN\n"
        f"    RAISE EXCEPTION 'NO SE BORRA: {dest} tiene % de {n} filas', n;\n"
        "  END IF;\n"
        f"  m_src := {sql_md5(tabla, meta, ids)};\n"
        f"  m_dst := {sql_md5(dest, meta, ids, 'a')};\n"
        "  IF m_src IS DISTINCT FROM m_dst THEN\n"
        f"    RAISE EXCEPTION 'NO SE BORRA: {dest} no coincide con {tabla}';\n"
        "  END IF;\n"
        f"  DELETE FROM {tabla} t WHERE t.id = ANY({ids_sql});\n"
        "  GET DIAGNOSTICS n = ROW_COUNT;\n"
        f"  IF n <> {n} THEN\n"
        f"    RAISE EXCEPTION 'BORRADO INCOMPLETO: % de {n} filas en {tabla}', n;\n"
        "  END IF;\n"
        "END $retencion$;\n"
    )


# ── SQL de auditoría (no se archiva: la auditoría vieja no se consulta) ────
def sql_pendientes_auditoria(cfg: dict) -> str:
    return ("SELECT count(*) FROM auditoria WHERE fecha < "
            f"(now() - INTERVAL '{int(cfg['anios_auditoria'])} years');\n")


def sql_borrar_auditoria(cfg: dict, limite: int) -> str:
    """Borra hasta `limite` filas y DEVUELVE cuántas borró.

    El conteo vuelve como una fila (`SELECT count(*)` sobre el `RETURNING`), no
    como el tag `DELETE n` de psql: con `-q` psql no imprime tags, así que
    parsearlos funcionaría en un cliente y no en otro. Todo en una transacción.
    """
    return (
        "WITH viejas AS (\n"
        "  SELECT id FROM auditoria\n"
        f"   WHERE fecha < (now() - INTERVAL '{int(cfg['anios_auditoria'])} years')\n"
        f"   ORDER BY id LIMIT {int(limite)}\n"
        "), borradas AS (\n"
        "  DELETE FROM auditoria a USING viejas v WHERE a.id = v.id RETURNING a.id\n"
        ")\n"
        "SELECT count(*) FROM borradas;\n"
    )


# ── SQL de anonimización ───────────────────────────────────────────────────
ALFABETO_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def rut_anonimo(pepper: str, id_usuario: int, rut: str) -> str:
    """RUT anónimo determinista de 12 caracteres (`ANON` + 8 en base36).

    Sin el pepper no se puede volver al valor original y el mismo (id, rut)
    siempre produce el mismo valor, así que repetir la corrida no cambia nada.
    Con 8 caracteres base36 (~2,8e12 combinaciones) la colisión es despreciable
    para una tabla de alumnos; si igual ocurriera, la transacción aborta sin
    tocar nada (nunca se guarda un RUT duplicado dentro del tenant).
    """
    crudo = f"{int(id_usuario)}|{(rut or '').strip().upper()}"
    digest = hashlib.sha256(f"{pepper}|{crudo}".encode("utf-8")).digest()
    numero = int.from_bytes(digest[:8], "big")
    salida = []
    for _ in range(8):
        numero, resto = divmod(numero, len(ALFABETO_B36))
        salida.append(ALFABETO_B36[resto])
    return "ANON" + "".join(salida)


def _rut_validado(rut_anon: str) -> str:
    """Los RUT anónimos se interpolan en el SQL: sólo base36 con prefijo ANON."""
    if not re.fullmatch(r"ANON[0-9a-z]{8}", rut_anon or ""):
        raise EscrituraError(f"RUT anónimo con formato inesperado: {rut_anon!r}")
    return rut_anon


def sql_pendientes_anonimizar(cfg: dict) -> str:
    return ("SELECT count(*) FROM usuarios\n"
            " WHERE rol = 'alumno' AND fecha_baja IS NOT NULL\n"
            f"   AND fecha_baja <= (now() - INTERVAL '{int(cfg['meses_anonimizar'])} months')\n"
            "   AND anonimizado_en IS NULL;\n")


def sql_lote_anonimizar(cfg: dict) -> str:
    return ("SELECT id, rut FROM usuarios\n"
            " WHERE rol = 'alumno' AND fecha_baja IS NOT NULL\n"
            f"   AND fecha_baja <= (now() - INTERVAL '{int(cfg['meses_anonimizar'])} months')\n"
            "   AND anonimizado_en IS NULL\n"
            f" ORDER BY id LIMIT {int(cfg['lote'])};\n")


def script_anonimizar(cfg: dict, pares: list) -> str:
    """Reemplaza nombre/correo/teléfono/RUT y sella `anonimizado_en`.

    Los RUT anónimos llegan calculados desde Python (el pepper nunca entra al
    SQL). Fechas, clases, asistencias y tokens quedan intactos: son los datos
    estadísticos que el negocio sigue necesitando.
    """
    valores = ", ".join(
        f"({int(i)}, '{_rut_validado(r)}')" for i, r in pares)
    ids_sql = lista_ids([i for i, _ in pares])
    n = len(pares)
    meses = int(cfg["meses_anonimizar"])
    return (
        PROLOGO
        + "DO $retencion$\n"
        "DECLARE n int; m int;\n"
        "BEGIN\n"
        "  SELECT count(*) INTO n FROM usuarios u\n"
        f"   WHERE u.id = ANY({ids_sql}) AND u.rol = 'alumno'\n"
        f"     AND u.fecha_baja <= (now() - INTERVAL '{meses} months')\n"
        "     AND u.anonimizado_en IS NULL;\n"
        f"  IF n <> {n} THEN\n"
        f"    RAISE EXCEPTION 'CANDIDATOS DISTINTOS: % de {n} filas ya no son bajas "
        "pendientes de anonimizar', n;\n"
        "  END IF;\n"
        "  UPDATE usuarios u SET\n"
        "      nombre = 'Alumno anonimizado ' || u.id::text,\n"
        "      correo = 'anonimo+' || u.id::text || '@anonimizado.invalid',\n"
        "      telefono = NULL,\n"
        "      rut = v.rut,\n"
        "      anonimizado_en = now()\n"
        f"    FROM (VALUES {valores}) AS v(id, rut)\n"
        "   WHERE u.id = v.id AND u.rol = 'alumno'\n"
        "     AND u.anonimizado_en IS NULL;\n"
        "  GET DIAGNOSTICS n = ROW_COUNT;\n"
        f"  IF n <> {n} THEN\n"
        f"    RAISE EXCEPTION 'ANONIMIZADAS % de {n} filas', n;\n"
        "  END IF;\n"
        "  SELECT count(*) INTO m FROM usuarios u\n"
        f"   WHERE u.id = ANY({ids_sql}) AND u.anonimizado_en IS NULL;\n"
        "  IF m <> 0 THEN\n"
        "    RAISE EXCEPTION 'QUEDARON % SIN ANONIMIZAR', m;\n"
        "  END IF;\n"
        "  SELECT count(*) INTO m FROM usuarios u\n"
        f"   WHERE u.id = ANY({ids_sql}) AND EXISTS (\n"
        "     SELECT 1 FROM usuarios v WHERE v.tenant_id = u.tenant_id\n"
        "       AND v.rut = u.rut AND v.id <> u.id);\n"
        "  IF m > 0 THEN\n"
        "    RAISE EXCEPTION 'RUT ANÓNIMO DUPLICADO en % fila(s): se aborta sin "
        "tocar nada (rotar ANONIMIZACION_PEPPER)', m;\n"
        "  END IF;\n"
        "  SELECT count(*) INTO m FROM usuarios u\n"
        f"   WHERE u.id = ANY({ids_sql}) AND EXISTS (\n"
        "     SELECT 1 FROM usuarios v WHERE v.tenant_id = u.tenant_id\n"
        "       AND v.correo = u.correo AND v.id <> u.id);\n"
        "  IF m > 0 THEN\n"
        "    RAISE EXCEPTION 'CORREO ANÓNIMO DUPLICADO en % fila(s): se aborta "
        "sin tocar nada', m;\n"
        "  END IF;\n"
        "END $retencion$;\n"
    )


# ── Respaldo: CSV.gz al bucket, con sha256 verificado en el objeto guardado ──
def sha256_archivo(archivo: Path) -> str:
    h = hashlib.sha256()
    with open(archivo, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _contar_csv(ruta: Path, columnas: list) -> int:
    """Cuenta filas y exige la cabecera exacta (un CSV cortado no pasa)."""
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        lector = csv.reader(f)
        cabecera = next(lector, None)
        if list(cabecera or []) != list(columnas):
            raise RespaldoError(f"cabecera del CSV inesperada: {cabecera}")
        return sum(1 for _ in lector)


def exportar_csv(url: str, tabla: str, ids: list, destino: Path) -> dict:
    """Paso 2: el lote a un CSV.gz, validando contenido y cantidad de filas.

    `COPY ... TO STDOUT` se escribe al archivo en BINARIO a propósito: con
    `text=True` Python traduce `\\n` → `\\r\\n` en Windows y el CSV cambiaría byte a
    byte según el sistema donde corre el job.
    """
    meta = TABLAS_ARCHIVO[tabla]
    cols = ", ".join(meta["columnas"])
    sql = (PROLOGO + f"COPY (SELECT {cols} FROM {tabla} t WHERE t.id = ANY("
           f"{lista_ids(ids)}) ORDER BY t.id) TO STDOUT WITH (FORMAT csv, "
           "HEADER true);\n")
    fd, ruta_sql = tempfile.mkstemp(prefix=f"retencion_{tabla}_", suffix=".sql")
    os.close(fd)
    datos = Path(str(destino) + ".csv")
    try:
        Path(ruta_sql).write_text(sql, encoding="utf-8")
        with open(datos, "wb") as salida:
            r = subprocess.run(["psql", url, "-X", "-q", "-v", "ON_ERROR_STOP=1",
                                "-f", ruta_sql], stdout=salida,
                               stderr=subprocess.PIPE)
        if r.returncode != 0:
            error = (r.stderr or b"").decode("utf-8", "replace")
            raise RespaldoError(f"COPY a CSV falló (rc={r.returncode}): "
                                f"{sanear(error)[:600]}")
        filas = _contar_csv(datos, list(meta["columnas"]))
        if filas != len(ids):
            raise RespaldoError(f"el CSV tiene {filas} fila(s) y se van a borrar "
                                f"{len(ids)}: no se borra nada")
        with open(datos, "rb") as fi, gzip.open(destino, "wb", compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)
        return {"filas": filas, "bytes": destino.stat().st_size,
                "sha256": sha256_archivo(destino)}
    finally:
        for ruta in (ruta_sql, datos):
            try:
                os.unlink(ruta)
            except OSError:
                pass


def clave_respaldo(cfg: dict, tabla: str, filas: int) -> str:
    """`retencion/asistencias/2026-10-29_031500_1200f.csv.gz` (ordena por fecha)."""
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    return f"{cfg['prefijo']}{tabla}/{sello}_{filas}f.csv.gz"


def subir_respaldo(clave: str, destino: Path, info: dict) -> None:
    """Sube y VERIFICA: tamaño + el sha256 que quedó guardado en los metadatos.

    No se usa `subir_y_verificar()` de `backup_cloud` porque ése compara sólo el
    tamaño; acá hace falta además el sha256, que es lo que se cita en el correo y
    lo que permite volver a comprobar el objeto meses después.
    """
    cli = cliente_s3()
    bucket = os.environ["R2_BUCKET"]
    sha = info["sha256"]
    try:
        cli.upload_file(str(destino), bucket, clave,
                        ExtraArgs={"Metadata": {"sha256": sha,
                                                "origen": "retencion_cloud"}})
        cab = cli.head_object(Bucket=bucket, Key=clave)
    except Exception as e:  # noqa: BLE001
        raise S3Error(f"no se pudo subir/verificar {clave}: "
                      f"{type(e).__name__}: {sanear(e)}")
    if cab["ContentLength"] != destino.stat().st_size:
        raise S3Error(f"{clave} pesa {cab['ContentLength']} bytes en R2 y "
                      f"{destino.stat().st_size} en local")
    guardado = (cab.get("Metadata") or {}).get("sha256", "")
    if guardado != sha:
        raise S3Error(f"sha256 de {clave} no coincide (R2={guardado or 'vacío'} "
                      f"local={sha})")
    log(f"Respaldo verificado en R2: s3://{bucket}/{clave} "
        f"({info['bytes'] / 1024:.1f} KB, sha256={sha[:12]}…)")


# ── Bloqueo por trabajo (tabla `retencion_bloqueos`, no advisory locks) ─────
def tomar_bloqueo(cfg: dict) -> str:
    """Toma el bloqueo del trabajo y devuelve el TOKEN ('' = ya hay otra corrida).

    `ON CONFLICT ... WHERE expira_en < now()`: si la fila existe y NO venció no se
    actualiza nada y `RETURNING` no devuelve filas ⇒ otra corrida está viva. Si
    venció (el proceso anterior murió sin liberar) se toma igual.
    """
    token = uuid.uuid4().hex
    sql = (
        f"INSERT INTO {TABLA_BLOQUEOS} AS b (job, token, tomado_en, expira_en)\n"
        f"VALUES ('{cfg['trabajo']}', '{token}', now(),\n"
        f"        now() + INTERVAL '{int(cfg['lock_horas'])} hours')\n"
        "ON CONFLICT (job) DO UPDATE\n"
        "   SET token = EXCLUDED.token, tomado_en = EXCLUDED.tomado_en,\n"
        "       expira_en = EXCLUDED.expira_en\n"
        " WHERE b.expira_en < now()\n"
        "RETURNING token;\n"
    )
    if consulta(cfg["url"], sql).strip() != token:
        return ""
    log(f"Bloqueo tomado por {cfg['lock_horas']} h (job={cfg['trabajo']}, "
        f"token={token[:8]}…)")
    return token


def liberar_bloqueo(cfg: dict, token: str) -> None:
    """Libera SÓLO si el token sigue siendo nuestro (nunca el de otra corrida)."""
    if not token:
        return
    try:
        consulta(cfg["url"],
                 f"DELETE FROM {TABLA_BLOQUEOS} WHERE job = '{cfg['trabajo']}' "
                 f"AND token = '{token}';\n")
    except LecturaError as e:  # el trabajo ya terminó: no cambia el exit code
        log(f"AVISO: no se pudo liberar el bloqueo ({e})")



# ── Trabajos ───────────────────────────────────────────────────────────────
def filas_a_ids(texto: str) -> list:
    """`105\\n106` → [105, 106]. Un id no entero aborta (nunca se interpola texto)."""
    try:
        return [int(linea) for linea in (texto or "").splitlines()
                if linea.strip()]
    except ValueError:
        raise LecturaError(f"la consulta devolvió ids no numéricos: {texto!r}")


def script_escritura(url: str, texto: str, que: str) -> str:
    """`script()` para escrituras: cualquier falla ⇒ EscrituraError (exit 6)."""
    try:
        return script(url, texto)
    except LecturaError as e:
        raise EscrituraError(f"{que}: no se aplicó nada ({e})")


def r2_disponible() -> bool:
    return all(_texto(os.environ, v) for v in VARS_R2)


def job_archivar(cfg: dict, res: dict | None = None) -> dict:
    """Archiva `asistencias` y `reservas` con más de N años, lote por lote.

    Orden por lote (y nunca al revés): copiar al archivo → exportar el CSV →
    subirlo y verificar el sha256 → borrar del origen. Si algo falla, el lote
    queda en el origen y la próxima corrida lo reintenta.

    `res` se puede pasar desde afuera para que `main()` conserve lo hecho hasta
    una falla (y lo pueda contar en el correo).
    """
    res = {"tablas": {}, "respaldos": [], "movidas": 0} if res is None else res
    with tempfile.TemporaryDirectory(prefix="retencion_") as tmp:
        for tabla in ("asistencias", "reservas"):
            pendientes = consulta_entero(cfg["url"], sql_pendientes(tabla, cfg))
            detalle = {"pendientes": pendientes, "movidas": 0}
            res["tablas"][tabla] = detalle
            log(f"{tabla}: {pendientes} fila(s) con más de "
                f"{cfg['anios_archivo']} año(s)")
            if pendientes > cfg["max_archivar"]:
                raise GuardaError(
                    f"{tabla}: {pendientes} fila(s) superan MAX_ARCHIVAR="
                    f"{cfg['max_archivar']}; no se tocó nada (subir el tope si el "
                    "volumen es esperado)")
            if not pendientes:
                continue
            if cfg["dry_run"]:
                detalle["habria_movido"] = pendientes
                log(f"{tabla}: DRY_RUN=1 -> se moverían {pendientes} fila(s); "
                    "no se copia, no se sube y no se borra nada")
                continue
            vueltas = 0
            while detalle["movidas"] < pendientes:
                vueltas += 1
                if vueltas > 1 + pendientes // max(1, cfg["lote"]):
                    raise VerificacionError(
                        f"{tabla}: el lote no avanzó ({detalle['movidas']} de "
                        f"{pendientes}); se corta para no repetir el mismo lote")
                faltan = pendientes - detalle["movidas"]
                ids = filas_a_ids(consulta(
                    cfg["url"], sql_lote(tabla, cfg, min(cfg["lote"], faltan))))
                if not ids:
                    break
                script_escritura(cfg["url"], script_copiar(tabla, ids),
                                 f"copia de {tabla} a su tabla de archivo")
                destino = Path(tmp) / f"{tabla}_{vueltas:04d}.csv.gz"
                info = exportar_csv(cfg["url"], tabla, ids, destino)
                clave = clave_respaldo(cfg, tabla, len(ids))
                if cfg["respaldo_local"]:
                    respaldar_local(cfg, clave, destino, info)
                if r2_disponible():
                    subir_respaldo(clave, destino, info)
                elif not cfg["respaldo_local"]:
                    raise ConfigError("no hay R2 configurado ni "
                                      "RETENCION_RESPALDO_LOCAL")
                res["respaldos"].append(clave)
                script_escritura(cfg["url"], script_borrar(tabla, ids),
                                 f"borrado de {tabla} ya archivada")
                detalle["movidas"] += len(ids)
                res["movidas"] += len(ids)
                log(f"{tabla}: {len(ids)} fila(s) archivadas y borradas del origen "
                    f"(respaldo {clave})")
            if detalle["movidas"] != pendientes:
                raise VerificacionError(
                    f"{tabla}: se movieron {detalle['movidas']} de {pendientes} "
                    f"fila(s) pendientes; revisar el log del run")
    return res


def respaldar_local(cfg: dict, clave: str, destino: Path, info: dict) -> None:
    """Copia el .csv.gz a `RETENCION_RESPALDO_LOCAL` (modo ensayo / sin R2).

    Es el mismo archivo que se subiría al bucket: se verifica que la copia tenga
    el tamaño exacto y se deja el sha256 en el log para poder compararlo a mano.
    """
    carpeta = Path(cfg["respaldo_local"])
    carpeta.mkdir(parents=True, exist_ok=True)
    copia = carpeta / clave.replace("/", "_")
    shutil.copy2(destino, copia)
    if copia.stat().st_size != info["bytes"]:
        raise RespaldoError(f"la copia local {copia} quedó incompleta "
                            f"({copia.stat().st_size} de {info['bytes']} bytes)")
    log(f"Respaldo local: {copia} ({info['bytes'] / 1024:.1f} KB, "
        f"sha256={info['sha256'][:12]}…)")


def job_auditoria(cfg: dict, res: dict | None = None) -> dict:
    """Borra `auditoria` con más de N años (no se archiva: es sólo rastro).

    Se cuenta ANTES y se compara con MAX_BORRAR_AUDITORIA: si el volumen no es el
    esperado no se borra nada (una purga masiva se decide a mano, mirando el log).
    """
    res = {"pendientes": 0, "purgadas": 0} if res is None else res
    pendientes = consulta_entero(cfg["url"], sql_pendientes_auditoria(cfg))
    res["pendientes"] = pendientes
    log(f"auditoria: {pendientes} fila(s) con más de "
        f"{cfg['anios_auditoria']} año(s)")
    if pendientes > cfg["max_auditoria"]:
        raise GuardaError(
            f"auditoria: {pendientes} fila(s) superan MAX_BORRAR_AUDITORIA="
            f"{cfg['max_auditoria']}; no se borró nada")
    if not pendientes:
        return res
    if cfg["dry_run"]:
        res["habria_purgado"] = pendientes
        log(f"auditoria: DRY_RUN=1 -> se borrarían {pendientes} fila(s)")
        return res
    vueltas = 0
    while res["purgadas"] < pendientes:
        vueltas += 1
        if vueltas > 1 + pendientes // max(1, cfg["lote"]):
            raise VerificacionError(
                f"auditoria: la purga no avanzó ({res['purgadas']} de {pendientes})")
        limite = min(cfg["lote"], pendientes - res["purgadas"])
        salida = script_escritura(cfg["url"],
                                  sql_borrar_auditoria(cfg, limite),
                                  "purga de auditoria")
        borradas = int((salida or "0").strip().splitlines()[-1] or 0)
        if borradas <= 0:
            break
        res["purgadas"] += borradas
    if res["purgadas"] != pendientes:
        raise VerificacionError(f"auditoria: se borraron {res['purgadas']} de "
                                f"{pendientes} fila(s); revisar el log del run")
    log(f"auditoria: {res['purgadas']} fila(s) borradas")
    return res


def pares_anonimos(crudo: str, pepper: str) -> list:
    """`5|12.345.678-9` → [(5, "ANONab12cd34"), …] (id + RUT anónimo)."""
    pares = []
    for linea in (crudo or "").splitlines():
        if not linea.strip():
            continue
        partes = linea.split("|", 1)
        try:
            id_usuario = int(partes[0])
        except ValueError:
            raise LecturaError(f"id no numérico en el lote: {partes[0]!r}")
        rut = partes[1] if len(partes) > 1 else ""
        pares.append((id_usuario, rut_anonimo(pepper, id_usuario, rut)))
    return pares


def job_anonimizar(cfg: dict, res: dict | None = None) -> dict:
    """Anonimiza a los alumnos dados de baja hace más de N meses.

    Sólo se tocan las filas de `rol = 'alumno'` con `fecha_baja` vencida y
    `anonimizado_en IS NULL`: el sello es lo que hace idempotente la corrida (y
    lo que deja constancia de CUÁNDO se anonimizó).
    """
    res = {"pendientes": 0, "anonimizadas": 0, "lotes": 0} if res is None else res
    pendientes = consulta_entero(cfg["url"], sql_pendientes_anonimizar(cfg))
    res["pendientes"] = pendientes
    log(f"anonimizar: {pendientes} baja(s) con más de "
        f"{cfg['meses_anonimizar']} mes(es) sin anonimizar")
    if pendientes > cfg["max_anonimizar"]:
        raise GuardaError(
            f"anonimizar: {pendientes} fila(s) superan MAX_ANONIMIZAR="
            f"{cfg['max_anonimizar']}; no se tocó nada")
    if not pendientes:
        return res
    if cfg["dry_run"]:
        res["habria_anonimizado"] = pendientes
        log(f"anonimizar: DRY_RUN=1 -> se anonimizarían {pendientes} fila(s) "
            "(no hay respaldo posible: esto es irreversible)")
        return res
    vueltas = 0
    while res["anonimizadas"] < pendientes:
        vueltas += 1
        if vueltas > 1 + pendientes // max(1, cfg["lote"]):
            raise VerificacionError(
                f"anonimizar: el lote no avanzó ({res['anonimizadas']} de "
                f"{pendientes})")
        pares = pares_anonimos(consulta(cfg["url"], sql_lote_anonimizar(cfg)),
                               cfg["pepper"])
        if not pares:
            break
        script_escritura(cfg["url"], script_anonimizar(cfg, pares),
                         "anonimización de bajas")
        res["anonimizadas"] += len(pares)
        res["lotes"] += 1
        log(f"anonimizar: {len(pares)} fila(s) anonimizadas (lote {res['lotes']})")
    if res["anonimizadas"] != pendientes:
        raise VerificacionError(f"anonimizar: se anonimizaron "
                                f"{res['anonimizadas']} de {pendientes} fila(s); "
                                "revisar el log del run")
    log(f"anonimizar: {res['anonimizadas']} fila(s) anonimizadas en "
        f"{res['lotes']} lote(s)")
    return res


TRABAJOS_FUNCIONES = {
    "archivar": job_archivar,
    "auditoria": job_auditoria,
    "anonimizar": job_anonimizar,
}


def res_inicial(trabajo: str) -> dict:
    """Resultado vacío de cada trabajo (dicts NUEVOS: no se comparten entre runs)."""
    if trabajo == "archivar":
        return {"tablas": {}, "respaldos": [], "movidas": 0}
    if trabajo == "auditoria":
        return {"pendientes": 0, "purgadas": 0}
    return {"pendientes": 0, "anonimizadas": 0, "lotes": 0}


VERBOS = {"archivar": "archivadas", "auditoria": "purgadas",
          "anonimizar": "anonimizadas"}


def movidas(trabajo: str, res: dict) -> int:
    """Cuántas filas se movieron/purgaron/anonimizaron (en DRY_RUN: cuántas se habrían).

    Es lo que decide si el correo sale o no (`correo = algo que revisar`) y lo que
    va en el asunto: un run sin filas y sin errores sólo deja log.
    """
    if trabajo == "archivar":
        return int(res.get("movidas") or 0) + sum(
            int(d.get("habria_movido") or 0)
            for d in (res.get("tablas") or {}).values())
    if trabajo == "auditoria":
        return int(res.get("purgadas") or 0) + int(res.get("habria_purgado") or 0)
    return int(res.get("anonimizadas") or 0) + int(res.get("habria_anonimizado") or 0)


def lineas_resumen(trabajo: str, res: dict) -> list:
    """Escalares del run para el log (el detalle completo va en el HTML del correo)."""
    if trabajo == "archivar":
        lineas = [f"{tabla}: {d.get('pendientes', 0)} pendiente(s), "
                  f"{d.get('movidas', 0)} movida(s)"
                  + (f", {d['habria_movido']} se habrían movido"
                     if "habria_movido" in d else "")
                  for tabla, d in (res.get("tablas") or {}).items()]
        return lineas + [f"respaldos verificados: {len(res.get('respaldos') or [])}"]
    if trabajo == "auditoria":
        return [f"auditoria: {res.get('pendientes', 0)} pendiente(s), "
                f"{res.get('purgadas', 0)} borrada(s)"
                + (f", {res['habria_purgado']} se habrían borrado"
                   if "habria_purgado" in res else "")]
    return [f"bajas: {res.get('pendientes', 0)} pendiente(s), "
            f"{res.get('anonimizadas', 0)} anonimizada(s) en "
            f"{res.get('lotes', 0)} lote(s)"
            + (f", {res['habria_anonimizado']} se habrían anonimizado"
               if "habria_anonimizado" in res else "")]


# ── Correo: mismo Gmail SMTP y mismo criterio que el resto del mantenimiento ─
def _e(valor) -> str:
    """Escapa lo que se muestra en el HTML (nombres de tabla y claves de R2)."""
    return html.escape(str(valor if valor is not None else ""))


def _lista_html(titulo: str, pares) -> str:
    items = "".join(f"<li><b>{_e(k)}</b>: {_e(v)}</li>" for k, v in pares)
    return (f"<p style='margin:10px 0 2px'><b>{_e(titulo)}</b></p>"
            f"<ul>{items or '<li>(sin datos)</li>'}</ul>")


def construir_html(trabajo: str, cfg: dict, res: dict, code: int, motivo: str,
                   inicio: datetime, segundos: float) -> str:
    """HTML del aviso: qué hizo el run, con qué umbrales y qué respaldos quedaron.

    Nunca muestra la URL (lleva credenciales): sólo el host y el entorno.
    """
    modo = ("DRY-RUN: no se escribió nada en la base"
            if cfg["dry_run"] else "REAL: los cambios quedaron confirmados (COMMIT)")
    config = [
        ("Job", f"{trabajo} ({TITULOS_EXIT.get(code, code)})"),
        ("Base", f"{cfg['host']} [{cfg['entorno']}]"),
        ("Modo", modo),
        ("Umbrales", f"archivo {cfg['anios_archivo']} año(s) · auditoría "
                     f"{cfg['anios_auditoria']} año(s) · bajas "
                     f"{cfg['meses_anonimizar']} mes(es)"),
        ("Lote y topes", f"{cfg['lote']} fila(s) por lote · MAX_ARCHIVAR="
                         f"{cfg['max_archivar']} · MAX_BORRAR_AUDITORIA="
                         f"{cfg['max_auditoria']} · MAX_ANONIMIZAR="
                         f"{cfg['max_anonimizar']}"),
        ("Cuándo", f"{inicio.strftime('%Y-%m-%d %H:%M:%S')} UTC ({segundos:.0f} s)"),
    ]
    doc = ("<html><body style='font-family:system-ui,Arial,sans-serif;"
           "font-size:13px'>")
    doc += (f"<p><b>{'OK ✅' if code == EXIT_OK else 'FALLA ❌'}</b> — {_e(motivo)}"
            "</p>")
    doc += _lista_html("Configuración del run", config)
    doc += _lista_html("Qué pasó", [("resumen", linea)
                                    for linea in lineas_resumen(trabajo, res)])
    if res.get("respaldos"):
        doc += _lista_html("Respaldos verificados",
                           [("clave", c) for c in res["respaldos"]])
    if trabajo == "anonimizar" and movidas(trabajo, res):
        doc += ("<p>🔒 La anonimización es <b>irreversible</b>: no hay respaldo de "
                "los datos personales que se reemplazaron (el RUT anónimo es un "
                "hash con ANONIMIZACION_PEPPER).</p>")
    if cfg["dry_run"] and movidas(trabajo, res):
        doc += ("<p>ℹ️ DRY_RUN: esto es lo que <b>haría</b>. Para aplicarlo: "
                "DRY_RUN=0 (en TEST además RETENCION_TEST_OK=1).</p>")
    return doc + "</body></html>"


def asunto_email(trabajo: str, cfg: dict, res: dict, code: int) -> str:
    """`[ALERTA]` si hay algo que revisar; si el run salió bien, el conteo delante."""
    if code != EXIT_OK:
        return (f"[ALERTA] Retención {cfg['entorno'].upper()}: {trabajo} falló "
                f"({TITULOS_EXIT.get(code, code)})")
    n = movidas(trabajo, res)
    que = f"{n} fila(s) {VERBOS[trabajo]}" if n else "sin filas"
    return (f"[retención] {cfg['entorno'].upper()} {trabajo} · "
            f"{'DRY_RUN · ' if cfg['dry_run'] else ''}{que}")


def reportar(code: int, trabajo: str, cfg: dict | None, res: dict,
             inicio: datetime, motivo: str) -> int:
    """Único punto de salida de `main()`: log + correo SÓLO si hay algo que revisar
    + exit code. Que el correo no salga NUNCA cambia el exit code."""
    segundos = (datetime.now(timezone.utc) - inicio).total_seconds()
    log(f"OK: {motivo}" if code == EXIT_OK
        else f"FALLA ({TITULOS_EXIT.get(code, code)}): {motivo}")
    for linea in lineas_resumen(trabajo, res):
        log(f"  {linea}")
    if code == EXIT_OK and movidas(trabajo, res) == 0:
        log("MAIL: no se envía (todo OK y sin filas movidas)")
        return code
    if cfg is None:
        log("MAIL: no se envía (el run no llegó a leer la configuración)")
        return code
    if not cfg.get("alertas"):
        log("MAIL: no se envía (faltan GMAIL_SMTP_USER / "
            "GMAIL_SMTP_APP_PASSWORD / ALERT_EMAIL)")
        return code
    if not enviar_email(asunto_email(trabajo, cfg, res, code),
                        construir_html(trabajo, cfg, res, code, motivo, inicio,
                                       segundos), logger=log):
        log("AVISO: el aviso no salió por Gmail; el exit code no cambia")
    return code


# ── main ───────────────────────────────────────────────────────────────────
def main(argv: list | None = None) -> int:
    """Un trabajo por corrida (`archivar` | `auditoria` | `anonimizar`).

    Cualquier error se convierte en exit code + correo: un Cron Job que sale en
    rojo sin explicación obliga a abrir el log de Render para nada. Un error
    inesperado se reporta como lectura (exit 3) — nunca se sale sin avisar.
    """
    inicio = datetime.now(timezone.utc)
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in TRABAJOS:
        log("uso: python -m maintenance.retencion_cloud "
            f"{{{ ' | '.join(TRABAJOS) }}}")
        return EXIT_CONFIG
    trabajo = args[0]
    log(f"=== retención de datos: {trabajo} ===")

    try:
        cfg = cargar_config(trabajo)
    except ConfigError as e:
        log(f"FATAL (config): {e}")
        return reportar(EXIT_CONFIG, trabajo, None, res_inicial(trabajo), inicio,
                        f"config: {e}")

    log(f"DRY_RUN={'1 (no se escribe nada)' if cfg['dry_run'] else '0 (APLICA cambios)'}"
        f" | ENVIRONMENT={cfg['entorno']}"
        f" | umbrales: archivo={cfg['anios_archivo']}a · "
        f"auditoría={cfg['anios_auditoria']}a · bajas={cfg['meses_anonimizar']}m"
        f" | lote={cfg['lote']}"
        f" | respaldo={'R2' if r2_disponible() else cfg['respaldo_local']}")
    log(f"Origen: {cfg['host']}")      # host + base, SIN credenciales

    res = res_inicial(trabajo)
    token = ""
    try:
        verificar_esquema(cfg["url"])
        token = tomar_bloqueo(cfg)
        if not token:
            log("Otra corrida del mismo trabajo tiene el bloqueo vigente: "
                "esta corrida no hace nada")
            return EXIT_OK
        TRABAJOS_FUNCIONES[trabajo](cfg, res)
        n = movidas(trabajo, res)
        code = EXIT_OK
        motivo = (f"{n} fila(s) {VERBOS[trabajo]}" if n
                  else "sin filas fuera de retención: nada que hacer")
    except ConfigError as e:
        code, motivo = EXIT_CONFIG, f"config: {e}"
    except S3Error as e:
        code, motivo = EXIT_RESPALDO, f"respaldo en R2: {e}"
    except RespaldoError as e:
        code, motivo = EXIT_RESPALDO, f"respaldo: {e}"
    except GuardaError as e:
        code, motivo = EXIT_GUARDA, f"guarda de volumen: {e}"
    except EscrituraError as e:
        code, motivo = EXIT_ESCRITURA, f"escritura: {e}"
    except VerificacionError as e:
        code, motivo = EXIT_VERIFICACION, f"verificación: {e}"
    except LecturaError as e:
        code, motivo = EXIT_LECTURA, f"lectura: {e}"
    except Exception as e:  # noqa: BLE001 (un Cron Job no puede morir sin avisar)
        code, motivo = EXIT_LECTURA, f"inesperado: {type(e).__name__}: {e}"
    finally:
        liberar_bloqueo(cfg, token)
    return reportar(code, trabajo, cfg, res, inicio, motivo)


if __name__ == "__main__":
    sys.exit(main())
