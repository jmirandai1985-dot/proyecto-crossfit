"""
Servido de documentos PRIVADOS (comprobantes de pago y certificados).

Los comprobantes tienen DOS orígenes históricos:
  - `/static/uploads/...`   -> comprobantes VIEJOS (carpeta pública de StaticFiles)
  - `/privado/vouchers/...` -> comprobantes NUEVOS (private_uploads/, fuera de
                              static/, NO servida por StaticFiles)

Ambos se sirven SOLO por endpoints autenticados (con guard de dueño/box) y
resolviendo el path DENTRO de su carpeta base (anti path-traversal).

POR QUÉ EXISTE: el voucher de un plan y el certificado de estudiante se sirven
igual. Con la resolución de path y la respuesta en un solo lugar, un endpoint
nuevo (p. ej. el certificado) no puede olvidarse del guard ni del chequeo de
traversal, y no hay dos copias que se desincronicen.
"""
import mimetypes
import os

from fastapi import HTTPException
from fastapi.responses import FileResponse

# Las URLs que se guardan en BD para los comprobantes PRIVADOS / PÚBLICOS.
PRIVATE_PREFIX = "/privado/vouchers/"
STATIC_PREFIX = "/static/"

# Roles del box que pueden ver los comprobantes de sus alumnos (staff).
ROLES_STAFF = ("coach", "admin", "administrador")


def base_app() -> str:
    """Carpeta `app/`: ahí viven `static/uploads/` y `private_uploads/`."""
    return os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))


def resolver_documento(url_documento: str, etiqueta: str) -> str:
    """
    Traduce la URL guardada en BD al path real del archivo, DENTRO de su base.

    400 = origen no soportado (no es /static/ ni /privado/),
    403 = el path resuelto se sale de la carpeta base (path traversal),
    404 = el archivo no está en el servidor.
    """
    if url_documento.startswith("/privado/"):
        base_dir = os.path.join(base_app(), "private_uploads")
        rel = url_documento.replace(PRIVATE_PREFIX, "")
    elif url_documento.startswith(STATIC_PREFIX):
        base_dir = os.path.join(base_app(), "static")
        rel = url_documento.replace(STATIC_PREFIX, "")
    else:
        raise HTTPException(
            status_code=400, detail=f"Origen de {etiqueta} no soportado")

    base_dir = os.path.realpath(base_dir)
    ruta = os.path.realpath(os.path.join(base_dir, rel.lstrip("/")))

    # El archivo resuelto debe quedar DENTRO de su carpeta base
    # (evita '../../../etc/passwd').
    if not ruta.startswith(base_dir + os.sep):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    if not os.path.exists(ruta):
        raise HTTPException(
            status_code=404,
            detail=f"Archivo de {etiqueta} no encontrado en el servidor")

    return ruta


def respuesta_documento(ruta: str, inline: bool) -> FileResponse:
    """FileResponse con el tipo REAL del archivo (adjunto, o inline al previsualizar).

    El media_type depende de la extensión: los comprobantes pueden ser
    JPG/PNG/GIF/WEBP o PDF (ver upload.py: ALLOWED_EXTENSIONS). Forzar
    "image/jpeg" hacía que un PDF se sirviera con el tipo equivocado (y el
    <iframe> del panel no lo renderizaba).
    """
    nombre = os.path.basename(ruta)
    media_type = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    disposicion = "inline" if inline else "attachment"

    # attachment = descarga forzada; inline = previsualización en el panel
    return FileResponse(
        path=ruta,
        media_type=media_type,
        headers={"Content-Disposition": f"{disposicion}; filename={nombre}"},
    )


def puede_ver_documento(usuario_id: int, tenant_id: int, alumno_id: int,
                        tenant_documento: int, rol: str) -> bool:
    """True si quien pide puede ver el documento de ESE alumno/box.

    Solo (a) el alumno dueño del documento, o (b) staff del MISMO box. Sin esto,
    cualquier usuario autenticado podía leer comprobantes ajenos de cualquier
    tenant con solo cambiar el id (IDOR).
    """
    es_dueno = usuario_id == alumno_id
    es_staff_mismo_box = rol in ROLES_STAFF and tenant_id == tenant_documento
    return es_dueno or es_staff_mismo_box
