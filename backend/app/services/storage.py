"""
Capa ÚNICA de almacenamiento de archivos (dev/TEST en disco, PROD en Cloudflare R2).

POR QUÉ EXISTE: hasta ahora cada router armaba su propio path y escribía con
`open()` (upload.py, productos.py) y el guard de lectura privada resolvía rutas a
disco (documentos_privados.py). En PROD el disco del contenedor es EFÍMERO
(Render sin disco persistente): cada deploy borraba los comprobantes, los
certificados y las imágenes. Ahora hay UN solo lugar que guarda y lee, elegido
por `STORAGE_BACKEND`:

  * "local" (dev y TEST): `app/private_uploads/` (privado) y
    `app/static/uploads/` (público), exactamente como antes.
  * "r2" (PROD): bucket S3-compatible de Cloudflare, con dos prefijos:
    `privado/` (solo se lee por el endpoint autenticado) y `publico/` (el único
    con acceso público, sólo para imágenes del Bazar).

CONTRATO DE URLs (lo que se guarda en la BD cambia lo mínimo posible):
  * privado (voucher de plan, certificado, comprobante de pedido):
    `/privado/vouchers/<archivo>` — MISMA forma en los dos backends, y se sirve
    SIEMPRE por streaming desde el endpoint autenticado (nunca URL prefirmada ni
    bucket público).
  * público (imagen de producto): en local `/static/uploads/<archivo>` y en R2 la
    URL absoluta `STORAGE_R2_PUBLIC_BASE_URL/publico/<archivo>`.

Los archivos que quedaron en el disco efímero y ya no existen responden con un
error CLARO (`ArchivoNoDisponible`) para que la UI pida volver a subirlos.
"""
from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from app.core.config import settings

log = logging.getLogger("app.services.storage")

# Carpeta `app/`: ahí viven `static/uploads/` (público) y `private_uploads/`.
_APP_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))

UPLOAD_DIR = os.path.join(_APP_DIR, "static", "uploads")
PRIVATE_DIR = os.path.join(_APP_DIR, "private_uploads")
STATIC_DIR = os.path.join(_APP_DIR, "static")

# Forma de la URL que se guarda en la BD.
PRIVATE_PREFIX = "/privado/vouchers/"
STATIC_PREFIX = "/static/"
PUBLIC_PREFIX = "/static/uploads/"

# Prefijos DENTRO del bucket de R2.
PRIVATE_KEY_PREFIX = "privado/vouchers/"
PUBLIC_KEY_PREFIX = "publico/"

BACKENDS = ("local", "r2")


class ErrorAlmacenamiento(Exception):
    """Falla de la capa de almacenamiento (no se pudo guardar/leer el archivo)."""


class ArchivoNoDisponible(ErrorAlmacenamiento):
    """El archivo que referencia la BD ya no está (deploy anterior / borrado)."""


class OrigenNoSoportado(ErrorAlmacenamiento):
    """La URL guardada no apunta a un origen conocido (/privado/ o /static/)."""


class RutaNoPermitida(ErrorAlmacenamiento):
    """La URL intenta salirse de su carpeta base (path traversal)."""


def _mensaje_perdido(etiqueta: str) -> str:
    """Mensaje ÚNICO de archivo perdido (disco efímero de Render, deploy anterior).

    Es lo que ve el alumno/staff en el panel: ni un 404 mudo ni un stacktrace.
    """
    return (f"El archivo de {etiqueta} ya no está disponible en el servidor "
            "(se perdió en un despliegue). Pídele al alumno que lo vuelva a subir.")


@dataclass
class DocumentoAbierto:
    """Documento privado listo para servir.

    `nombre`: nombre del archivo (define el media type de la respuesta).
    `ruta`: backend local -> archivo en disco (FileResponse, sin copiar a memoria).
    `flujo`: backend R2 -> cuerpo de la respuesta S3 (se transmite por streaming).
    """
    nombre: str
    ruta: Optional[str] = None
    flujo: Any = None


# ── Backend activo ───────────────────────────────────────────────────────────

def backend() -> str:
    """Backend de almacenamiento en uso: "local" o "r2" (según STORAGE_BACKEND).

    FAIL-SAFE: un valor desconocido es ERROR, no se asume "local". Asumir local
    en PROD escribiría en el disco efímero y perdería archivos sin avisar.
    """
    valor = (getattr(settings, "STORAGE_BACKEND", "") or "").strip().lower() or "local"
    if valor not in BACKENDS:
        raise ErrorAlmacenamiento(
            f"STORAGE_BACKEND={valor!r} no soportado (usar 'local' o 'r2')")
    return valor


# Los directorios locales existen desde el arranque (como siempre: los tests y el
# modo local escriben/leen ahí sin tener que crear nada antes).
if backend() == "local":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(PRIVATE_DIR, exist_ok=True)


# ── Guardado ─────────────────────────────────────────────────────────────────

def _tipo_mime(nombre_archivo: str) -> str:
    return mimetypes.guess_type(nombre_archivo)[0] or "application/octet-stream"


def _guardar_local(carpeta: str, nombre_archivo: str, contenido: bytes) -> None:
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, nombre_archivo), "wb") as f:
        f.write(contenido)


def guardar_privado(contenido: bytes, nombre_archivo: str) -> str:
    """Guarda un archivo PRIVADO y devuelve la URL para la BD (`/privado/vouchers/...`).

    Se lee SOLO por el endpoint autenticado (ver app/core/documentos_privados.py):
    el bucket de R2 no expone el prefijo `privado/`.
    """
    if backend() == "local":
        _guardar_local(PRIVATE_DIR, nombre_archivo, contenido)
    else:
        _r2_subir(PRIVATE_KEY_PREFIX + nombre_archivo, contenido)
    return f"{PRIVATE_PREFIX}{nombre_archivo}"


def guardar_publico(contenido: bytes, nombre_archivo: str) -> str:
    """Guarda un archivo PÚBLICO (imagen de producto) y devuelve la URL para la BD.

    En R2 va al bucket PÚBLICO (STORAGE_R2_PUBLIC_BUCKET) y la URL es ABSOLUTA: la
    sirve el dominio público del bucket, así el navegador la carga directo, sin
    pasar por el backend. Los privados NO viven ahí: un bucket público no puede
    filtrar un voucher porque el voucher está en OTRO bucket, sin acceso público.
    """
    if backend() == "local":
        _guardar_local(UPLOAD_DIR, nombre_archivo, contenido)
        return f"{PUBLIC_PREFIX}{nombre_archivo}"
    _r2_subir(PUBLIC_KEY_PREFIX + nombre_archivo, contenido, bucket=_bucket_publico())
    return f"{_url_publica_base()}/{PUBLIC_KEY_PREFIX}{nombre_archivo}"


# ── Lectura (documentos privados) ────────────────────────────────────────────

def _relativo(url_documento: str) -> tuple:
    """(rel, origen) de la URL guardada en la BD. origen ∈ {"privado", "static"}.

    400 OrigenNoSoportado: no empieza con /privado/vouchers/ ni con /static/.
    """
    if url_documento.startswith(PRIVATE_PREFIX):
        return url_documento[len(PRIVATE_PREFIX):], "privado"
    if url_documento.startswith(STATIC_PREFIX):
        return url_documento[len(STATIC_PREFIX):], "static"
    raise OrigenNoSoportado("Origen no soportado")


def _ruta_local(rel: str, origen: str, etiqueta: str) -> str:
    """Path real en disco (backend local), con el chequeo anti path-traversal.

    403 RutaNoPermitida si el archivo resuelto sale de su carpeta base.
    404 ArchivoNoDisponible si no está en el disco.
    """
    base = os.path.realpath(PRIVATE_DIR if origen == "privado" else STATIC_DIR)
    ruta = os.path.realpath(os.path.join(base, rel.lstrip("/")))
    if not ruta.startswith(base + os.sep):
        raise RutaNoPermitida("Acceso denegado")
    if not os.path.isfile(ruta):
        raise ArchivoNoDisponible(_mensaje_perdido(etiqueta))
    return ruta


def _clave_r2(rel: str, origen: str, etiqueta: str) -> str:
    """Clave del objeto en R2 (backend r2), con el mismo chequeo de traversal.

    Los archivos privados se guardan PLANOS (`privado/vouchers/<archivo>`): un
    nombre con separadores o ".." no es un archivo nuestro -> 403.
    Los documentos HISTÓRICOS en /static/... vivían en el disco efímero: no están
    en R2, así que se responde el mensaje claro de archivo perdido.
    """
    if origen == "static":
        raise ArchivoNoDisponible(_mensaje_perdido(etiqueta))
    if not rel or ".." in rel or "/" in rel or "\\" in rel:
        raise RutaNoPermitida("Acceso denegado")
    return PRIVATE_KEY_PREFIX + rel


def abrir_privado(url_documento: str, etiqueta: str) -> DocumentoAbierto:
    """Abre un documento PRIVADO a partir de la URL guardada en BD.

    local -> devuelve la ruta en disco (FileResponse, eficiente).
    r2    -> devuelve el flujo del objeto (streaming, sin copiar a memoria).
    """
    if not url_documento or not isinstance(url_documento, str):
        raise OrigenNoSoportado("Origen no soportado")
    rel, origen = _relativo(url_documento)

    if backend() == "local":
        return DocumentoAbierto(nombre=os.path.basename(rel.rstrip("/")),
                                ruta=_ruta_local(rel, origen, etiqueta))

    clave = _clave_r2(rel, origen, etiqueta)
    return DocumentoAbierto(nombre=os.path.basename(clave),
                            flujo=_r2_leer(clave, etiqueta))


# ── Cliente de Cloudflare R2 (S3-compatible) ─────────────────────────────────

def _url_publica_base() -> str:
    base = (getattr(settings, "STORAGE_R2_PUBLIC_BASE_URL", "") or "").rstrip("/")
    if not base:
        raise ErrorAlmacenamiento(
            "Falta STORAGE_R2_PUBLIC_BASE_URL: sin la URL pública del bucket no se "
            "puede guardar la imagen de un producto (no se puede armar su URL).")
    return base


def _bucket() -> str:
    bucket = (getattr(settings, "STORAGE_R2_BUCKET", "") or "").strip()
    if not bucket:
        raise ErrorAlmacenamiento(
            "Falta STORAGE_R2_BUCKET (bucket de R2 donde viven los archivos).")
    return bucket


def _bucket_publico() -> str:
    """Bucket de los archivos PÚBLICOS (imágenes). Vacío -> el mismo de los privados.

    En PROD van SIEMPRE separados: el acceso público de Cloudflare es a nivel de
    BUCKET (r2.dev / dominio propio), no de prefijo, así que un bucket público no
    puede contener los comprobantes. Si comparten bucket se avisa por log.
    """
    publico = (getattr(settings, "STORAGE_R2_PUBLIC_BUCKET", "") or "").strip()
    if not publico:
        log.warning(
            "[storage] STORAGE_R2_PUBLIC_BUCKET vacío: las imágenes del Bazar se "
            "guardan en el MISMO bucket que los comprobantes. En PROD poné un bucket "
            "público aparte (el acceso público de R2 es por bucket, no por prefijo).")
        return _bucket()
    return publico


def _variables_faltantes() -> list:
    nombres = ("STORAGE_R2_ENDPOINT", "STORAGE_R2_BUCKET", "STORAGE_R2_ACCESS_KEY_ID",
               "STORAGE_R2_SECRET_ACCESS_KEY")
    return [n for n in nombres if not (getattr(settings, n, "") or "").strip()]


@lru_cache(maxsize=1)
def _cliente_r2():
    """Cliente S3 de R2 (una sola instancia por proceso).

    `import boto3` va DENTRO de la función a propósito: en local/TEST (y en los
    tests, que inyectan un cliente FALSO) boto3 no se importa ni hace falta.
    """
    faltantes = _variables_faltantes()
    if faltantes:
        raise ErrorAlmacenamiento("Faltan variables de R2: " + ", ".join(faltantes))

    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.STORAGE_R2_ENDPOINT,
        aws_access_key_id=settings.STORAGE_R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.STORAGE_R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4",
                      retries={"max_attempts": 3, "mode": "standard"},
                      connect_timeout=5, read_timeout=15),
    )


def _es_no_existe(error: Exception) -> bool:
    """True si el error del cliente S3 significa "ese objeto no está"."""
    codigo = ""
    respuesta = getattr(error, "response", None)
    if isinstance(respuesta, dict):
        codigo = str(respuesta.get("Error", {}).get("Code") or "")
    return codigo in ("NoSuchKey", "NoSuchBucket", "404", "NotFound") \
        or type(error).__name__ in ("NoSuchKey", "NotFound")


def _r2_subir(clave: str, contenido: bytes, bucket: str = None) -> None:
    """Sube un objeto a R2 (bucket privado por defecto) con su Content-Type."""
    cliente = _cliente_r2()
    try:
        cliente.put_object(Bucket=bucket or _bucket(), Key=clave, Body=contenido,
                           ContentType=_tipo_mime(clave))
    except Exception as e:  # botocore: ClientError / EndpointConnectionError / ...
        log.error("[storage] no se pudo subir %s a R2: %s", clave, e)
        raise ErrorAlmacenamiento(f"No se pudo subir el archivo a R2: {e}") from e


def _r2_leer(clave: str, etiqueta: str):
    """Abre el objeto de R2 para transmitirlo por streaming (no se copia a memoria)."""
    cliente = _cliente_r2()
    try:
        return cliente.get_object(Bucket=_bucket(), Key=clave)["Body"]
    except Exception as e:
        if _es_no_existe(e):
            raise ArchivoNoDisponible(_mensaje_perdido(etiqueta)) from e
        log.error("[storage] no se pudo leer %s de R2: %s", clave, e)
        raise ErrorAlmacenamiento(f"No se pudo leer el archivo de R2: {e}") from e


