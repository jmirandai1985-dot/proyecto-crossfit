"""
Validación de archivos por MAGIC BYTES (firma real), no solo extensión.

Previene subir archivos disfrazados (ej. un ejecutable renombrado a .jpg).
Solo usa la librería estándar. Se usa en upload.py (vouchers) y productos.py
(imágenes de la tienda).
"""
from typing import Optional


def detectar_tipo_real(content: bytes) -> Optional[str]:
    """
    Detecta el tipo real de un archivo por sus primeros bytes.

    Returns:
        Extensión canónica (".jpg", ".png", ".gif", ".webp", ".pdf")
        o None si no coincide con ningún formato permitido.
    """
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return ".gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if content.startswith(b"%PDF"):
        return ".pdf"
    return None


# Tipos MIME aceptables por extensión (el header content-type lo declara el
# cliente y es spoofeable; se usa solo como chequeo adicional, nunca como único).
MIME_POR_EXTENSION = {
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".gif": {"image/gif"},
    ".webp": {"image/webp"},
    ".pdf": {"application/pdf"},
}

# Extensiones permitidas para comprobantes (vouchers)
EXTENSIONES_VOUCHER = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}

# Extensiones permitidas para imágenes de productos
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def validar_archivo(
    extension: str,
    content: bytes,
    content_type: Optional[str] = None,
    permitidas: Optional[set] = None,
) -> bool:
    """
    Valida que la extensión declarada esté permitida y que el contenido
    coincida con la firma real (magic bytes).

    Args:
        extension: Extensión del archivo en minúsculas (ej. ".jpg").
        content: Contenido completo del archivo.
        content_type: Content-Type declarado por el cliente (opcional).
        permitidas: Set de extensiones permitidas; por defecto usa
                    EXTENSIONES_VOUCHER.

    Returns:
        True si el archivo es válido, False en caso contrario.
    """
    ext = extension.lower()
    permitidas = permitidas or EXTENSIONES_VOUCHER

    if ext not in permitidas:
        return False

    if content_type and ext in MIME_POR_EXTENSION:
        if content_type.lower() not in MIME_POR_EXTENSION[ext]:
            return False

    real = detectar_tipo_real(content)
    if real is None:
        return False

    # .jpg y .jpeg son intercambiables a nivel de firma
    if real in (".jpg", ".jpeg") and ext in (".jpg", ".jpeg"):
        return True

    return real == ext
