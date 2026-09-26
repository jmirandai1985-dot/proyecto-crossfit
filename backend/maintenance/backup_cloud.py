"""Backup diario de la base REAL de PROD a Cloudflare R2 (Cron Job de Render).

Por qué existe este módulo
-------------------------
El backup vivía en el contenedor `maintenance` local, que solo corre cuando la PC
de Jebbus está encendida (los logs existentes son de 4 días sueltos) y además, por
default, apunta a la rama de TEST. Este módulo es el mecanismo de nube: corre en un
Cron Job de Render, contra `PROD_DB_DIRECT_URL`, y guarda el dump en R2 (bucket
privado, retención 90 días).

Principios
----------
1. **Ninguna credencial en el repo**: todo se lee de variables de entorno (el
   Environment Group `backups-prod` de Render). Nunca se loguea la URL completa
   ni las keys.
2. **Solo lectura**: la única operación contra la base es `pg_dump`. El rol de Neon
   (`backup_ro`, `GRANT pg_read_all_data`) no puede escribir.
3. **Conexión DIRECTA**: se rechaza una URL con `-pooler` (Neon desaconseja pg_dump
   a través del pooler) — falla con mensaje claro en vez de escribir un dump dudoso.
4. **Cliente pg_dump de la misma major que el servidor**: se compara contra
   `SHOW server_version` y se aborta si difieren (el bug del 26/09 fue exactamente
   esto: cliente 17 contra servidor 18.6 ⇒ "aborting because of server version mismatch").
5. **Asserts del contenido, no solo del exit code**: tamaño mínimo, `CREATE TABLE`
   >= MIN_TABLAS, footer `PostgreSQL database dump complete`, `COPY public.alembic_version`.
   Un dump vacío o truncado no pasa.
6. **El éxito se verifica**: tras subir se hace `head_object` y se compara el tamaño
   con el archivo local; y al final se RE-LISTA el bucket para confirmar que el
   objeto está ahí. Nada de "✅ completado" cuando en realidad falló.
7. **DRY_RUN=1 por defecto**: el primer disparo hace dump + asserts + lista el bucket
   y termina SIN SUBIR NADA. Se apaga (`DRY_RUN=0`) recién cuando el log da verde.

Cualquier fallo termina con exit != 0 ⇒ el run del Cron Job queda marcado como
fallido en Render (y lo detecta el watchdog).

Uso:
    python -m maintenance.backup_cloud
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

# Salida UTF-8 explícita: en Windows (cp1252) los ✅/❌ de los mensajes rompen el
# print cuando la salida se redirige a un archivo. En Linux/Render es no-op.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# ── Códigos de salida (Render marca fallido el run si != 0) ──
EXIT_OK = 0
EXIT_CONFIG = 2      # falta una variable / URL con -pooler / major distinta
EXIT_DUMP = 3        # pg_dump falló
EXIT_ASSERTS = 4     # el dump no pasó los controles de contenido
EXIT_S3 = 5          # error hablando con R2

VARS_OBLIGATORIAS = (
    "PROD_DB_DIRECT_URL",
    "R2_ENDPOINT",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
)

PREFIJO = (os.getenv("BACKUP_PREFIX") or "daily/").strip()
RETENCION_DIAS = int(os.getenv("RETENTION_DAYS") or "90")
MIN_TABLAS = int(os.getenv("MIN_TABLAS") or "30")
MIN_BYTES = int(os.getenv("MIN_BYTES") or str(200 * 1024))
# DRY_RUN=1 (o cualquier valor que no sea "0"/"false"/"no") = no sube nada.
DRY_RUN = (os.getenv("DRY_RUN", "1").strip().lower() not in ("0", "false", "no"))


class ConfigError(RuntimeError):
    pass


class DumpError(RuntimeError):
    pass


class S3Error(RuntimeError):
    pass


def log(msg: str) -> None:
    # flush=True: sin esto la salida queda bufferizada y en Render el log se ve
    # desordenado ("Cron job run finished successfully" antes que las líneas del dump).
    # sanear(): red de seguridad final para que ninguna credencial llegue al log.
    print(f"[backup] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {sanear(msg)}", flush=True)


def sanear(texto) -> str:
    """ÚNICO punto de saneo de credenciales para todo lo que se imprime.

    Por qué existe: en Render el log filtró dos veces la contraseña de `backup_ro`.
    Cuando el connection string llega con un espacio/salto/BOM, psql y pg_dump
    devuelven en stderr la URI completa (con password) y boto3 puede incluir la URL
    firmada en el error. Todo texto que venga de afuera pasa por acá antes de salir.
    """
    t = texto if isinstance(texto, str) else str(texto)
    t = re.sub(r"://[^@\s]*@", "://***@", t)
    return re.sub(r"password=[^\s&]+", "password=***", t)


def limpiar_valor(valor: str) -> str:
    """strip() + BOM/CR/LF fuera: lo que se cuela al pegar un secreto en un panel."""
    return (valor or "").strip().lstrip("\ufeff").strip()


def host_de(url: str) -> str:
    """hostname + dbname, SIN credenciales (lo único que se loguea de la URL)."""
    try:
        p = urlsplit(url)
    except Exception:  # noqa: BLE001
        return "<URL inválida>"
    if not p.hostname:
        return "<URL inválida>"
    return f"{p.hostname}{p.path or ''}"


def es_directa(url: str) -> bool:
    """False si la URL pasa por el pooler de Neon (host con `-pooler.`)."""
    try:
        return "-pooler." not in (urlsplit(url).hostname or "")
    except Exception:  # noqa: BLE001
        return False


def usuario_de(url: str) -> str:
    try:
        return urlsplit(url).username or ""
    except Exception:  # noqa: BLE001
        return ""


def validar_url(url: str) -> str:
    """Valida PROD_DB_DIRECT_URL. Devuelve el MOTIVO del rechazo ('' = OK).

    El motivo describe la regla incumplida, nunca el valor del secreto.
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
    if usuario != "backup_ro":
        return "el usuario no es backup_ro"
    return ""


def faltantes() -> list:
    return [v for v in VARS_OBLIGATORIAS if not limpiar_valor(os.getenv(v) or "")]


def correr(cmd: list) -> subprocess.CompletedProcess:
    """subprocess con lista: la URL y las credenciales NO pasan por un shell."""
    return subprocess.run(cmd, capture_output=True, text=True)


def major(version: str) -> str:
    m = re.search(r"(\d+)(?:\.\d+)?", version or "")
    return m.group(1) if m else ""


def pg_dump_version() -> str:
    return (correr(["pg_dump", "--version"]).stdout or "").strip()


def psql(url: str, sql: str) -> str:
    r = correr(["psql", url, "-tAc", sql])
    if r.returncode != 0:
        # sanear() acá y no sólo en log(): psql devuelve la URI COMPLETA (con
        # password) en el stderr cuando el connection string es inválido.
        raise ConfigError(f"psql falló: {sanear(r.stderr or '')[:300]}")
    return (r.stdout or "").strip()


def server_version(url: str) -> str:
    return psql(url, "SHOW server_version")


# ── Dump ────────────────────────────────────────────────────────────────────
def hacer_dump(url: str, destino: Path) -> None:
    """pg_dump plano, sin owner ni ACL (así se restaura en cualquier rama/rol)."""
    cmd = ["pg_dump", "--no-owner", "--no-privileges", "--format=plain",
           "-f", str(destino), url]
    r = correr(cmd)
    if r.returncode != 0:
        # sanear(): pg_dump también echoa la URI completa en stderr si el
        # connection string viene malformado (espacio/salto/BOM).
        raise DumpError(f"pg_dump rc={r.returncode}: {sanear(r.stderr or '')[:600]}")
    if not destino.exists() or destino.stat().st_size == 0:
        raise DumpError("pg_dump terminó con rc=0 pero el archivo quedó vacío")


def comprimir(origen: Path) -> Path:
    destino = Path(str(origen) + ".gz")
    with open(origen, "rb") as fi, gzip.open(destino, "wb", compresslevel=9) as fo:
        shutil.copyfileobj(fi, fo)
    return destino


def verificar_dump(archivo: Path) -> dict:
    """Asserts de CONTENIDO del dump (no alcanza con que rc == 0)."""
    texto = archivo.read_text(encoding="utf-8", errors="replace")
    tablas = len(re.findall(r"(?m)^CREATE TABLE", texto))
    copies = len(re.findall(r"(?m)^COPY ", texto))
    footer = "PostgreSQL database dump complete" in texto
    m = re.search(r"(?m)^COPY public\.alembic_version.*?\n([^\n\\]+)", texto)
    tamano = archivo.stat().st_size

    problemas = []
    if tamano < MIN_BYTES:
        problemas.append(f"el dump pesa {tamano/1024:.1f} KB y el mínimo es {MIN_BYTES/1024:.0f} KB")
    if tablas < MIN_TABLAS:
        problemas.append(f"el dump tiene {tablas} CREATE TABLE y el mínimo es {MIN_TABLAS}")
    if not footer:
        problemas.append("falta el footer 'PostgreSQL database dump complete' (dump truncado)")
    if not m:
        problemas.append("no aparece COPY public.alembic_version (¿dump de otra base?)")

    return {"tablas": tablas, "copies": copies, "footer": footer, "size": tamano,
            "alembic": (m.group(1).strip() if m else None), "problemas": problemas}


# ── Cloudflare R2 (API compatible con S3) ──────────────────────────────────
def cliente_s3():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4",
                      retries={"max_attempts": 3, "mode": "standard"}),
    )


def listar(cli, prefijo: str) -> list:
    bucket = os.environ["R2_BUCKET"]
    objetos = []
    for page in cli.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefijo):
        objetos += page.get("Contents", [])
    return objetos


def subir_y_verificar(cli, clave: str, archivo: Path) -> None:
    """Sube y DESPUÉS compara con head_object que en R2 quedó el mismo tamaño."""
    bucket = os.environ["R2_BUCKET"]
    local = archivo.stat().st_size
    cli.upload_file(str(archivo), bucket, clave)
    cab = cli.head_object(Bucket=bucket, Key=clave)
    if cab["ContentLength"] != local:
        raise S3Error(f"el objeto en R2 pesa {cab['ContentLength']} bytes y el local {local}")


def _retencion_es_informativa() -> str:
    """La retención la aplica R2, no este runner.

    Antes había un `purgar()` que borraba objetos > RETENCION_DIAS. Se eliminó a
    propósito (2026-09-26): el bucket ya tiene la regla de lifecycle
    `borrar-90-dias` y así el runner queda **sin ninguna operación destructiva**
    (sólo lista, sube y verifica). RETENCION_DIAS queda como dato informativo.
    """
    return f"retención {RETENCION_DIAS} días (la aplica el lifecycle del bucket en R2)"


# ── Flujo principal ────────────────────────────────────────────────────────
def main() -> int:
    log("=== backup PROD → R2 ===")
    log(f"DRY_RUN={'1 (no se sube NADA)' if DRY_RUN else '0 (subida REAL)'} | "
        f"prefijo={PREFIJO!r} | retención={RETENCION_DIAS} días | mínimo={MIN_TABLAS} tablas")

    falta = faltantes()
    if falta:
        log(f"FATAL: faltan variables de entorno: {', '.join(falta)}")
        return EXIT_CONFIG

    # El secreto puede traer espacios, \r, \n o BOM al pegarse en un panel: se
    # normaliza y se VALIDA antes de usarlo (y antes de que psql/pg_dump lo vean,
    # que es cuando lo devolvían crudo en el stderr y se filtraba al log).
    url = limpiar_valor(os.environ["PROD_DB_DIRECT_URL"])
    motivo = validar_url(url)
    if motivo:
        log("FATAL (config): PROD_DB_DIRECT_URL inválida")
        log(f"  motivo (sin mostrar el valor): {motivo}")
        return EXIT_CONFIG
    os.environ["PROD_DB_DIRECT_URL"] = url  # normalizado, para psql/pg_dump
    log(f"Origen: {host_de(url)}")

    v_dump, v_server = pg_dump_version(), server_version(url)
    log(f"pg_dump: {v_dump} | servidor: {v_server}")
    if major(v_dump) != major(v_server):
        log(f"FATAL: major del cliente ({major(v_dump)}) != major del servidor "
            f"({major(v_server)}). pg_dump aborta en ese caso ⇒ actualizar "
            "postgresql-client en Dockerfile.cron.")
        return EXIT_CONFIG
    log(f"Sanity: usuarios en la base = {psql(url, 'SELECT count(*) FROM usuarios')}")

    crudo = Path(f"/tmp/neon_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql")
    hacer_dump(url, crudo)
    gz = comprimir(crudo)
    log(f"Dump: {crudo.name} ({crudo.stat().st_size/1024:.1f} KB) → "
        f"{gz.name} ({gz.stat().st_size/1024:.1f} KB)")

    info = verificar_dump(crudo)
    if info["problemas"]:
        for p in info["problemas"]:
            log(f"FATAL (assert): {p}")
        return EXIT_ASSERTS
    log(f"Asserts OK: {info['tablas']} CREATE TABLE, {info['copies']} COPY, footer OK, "
        f"alembic={info['alembic']}")

    clave = f"{PREFIJO}{datetime.now().strftime('%Y-%m-%d_%H%M')}_neon_backup.sql.gz"
    cli = cliente_s3()
    previos = listar(cli, PREFIJO)
    if previos:
        ult = max(previos, key=lambda o: o["LastModified"])
        log(f"Bucket: {len(previos)} objeto(s) | último: {ult['Key']} "
            f"({ult['Size']/1024:.1f} KB, {ult['LastModified'].strftime('%Y-%m-%d %H:%M')} UTC)")
    else:
        log(f"Bucket: 0 objetos con prefijo {PREFIJO!r}")

    if DRY_RUN:
        log(f"DRY_RUN=1 -> NO se sube nada. Objeto que se subiría: {clave}")
        log(f"RESULTADO: OK (dry-run) | dump={crudo.stat().st_size/1024:.1f} KB | "
            f"gz={gz.stat().st_size/1024:.1f} KB | tablas={info['tablas']} | "
            f"alembic={info['alembic']}")
        return EXIT_OK

    subir_y_verificar(cli, clave, gz)
    log(f"Subido y verificado (head_object): s3://{os.environ['R2_BUCKET']}/{clave}")
    log(f"Retención: {_retencion_es_informativa()}")
    finales = listar(cli, PREFIJO)
    if not any(o["Key"] == clave for o in finales):
        log("FATAL: el objeto recién subido no aparece al listar el bucket")
        return EXIT_S3
    log(f"RESULTADO: OK | objetos en bucket: {len(finales)} | "
        f"última clave: {max(o['Key'] for o in finales)}")
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as e:
        log(f"FATAL (config): {e}")
        sys.exit(EXIT_CONFIG)
    except DumpError as e:
        log(f"FATAL (dump): {e}")
        sys.exit(EXIT_DUMP)
    except S3Error as e:
        log(f"FATAL (R2): {e}")
        sys.exit(EXIT_S3)
    except Exception as e:  # noqa: BLE001
        log(f"FATAL inesperado: {type(e).__name__}: {e}")
        sys.exit(1)
