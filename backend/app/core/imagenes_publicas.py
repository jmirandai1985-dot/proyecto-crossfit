"""
Subida de imágenes PÚBLICAS: la foto de un producto del Bazar y el flyer de un
aviso de marketing.

Vivía dentro de `app/api/v1/productos.py` (`_guardar_imagen_publica`). Cuando
apareció el segundo consumidor (los flyers de `avisos_marketing`) se movió acá:
DOS rutas con el MISMO camino de guardado es exactamente donde una se relaja y la
otra no. Acá los chequeos son uno solo:

  1. tipo declarado en la lista blanca (el `content-type` lo declara el cliente y
     es spoofeable),
  2. tamaño máximo (5 MB),
  3. contenido REAL por magic bytes (`validar_archivo`: rechaza un ejecutable
     disfrazado de .png),
  4. nombre irrepetible (uuid4: la URL no se puede adivinar),
  5. guardado por la capa ÚNICA de almacenamiento (`app/services/storage.py`):
     `/static/uploads/<archivo>` en dev/TEST y el prefijo `publico/` del bucket
     público de R2 en PROD (con URL absoluta).

Si el guardado falla (R2 inaccesible, disco lleno) se responde 503 y NO se
devuelve una URL que apuntaría a un archivo inexistente.
"""
import os
import uuid

from fastapi import HTTPException, UploadFile, status

from app.core.file_validation import validar_archivo, EXTENSIONES_IMAGEN
from app.services import storage

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


async def guardar_imagen_publica(file: UploadFile) -> str:
    """Valida la imagen subida y la guarda como archivo PÚBLICO. Devuelve su URL."""
    # Validar tipo de contenido declarado (chequeo primario)
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de archivo no permitido: {file.content_type}. "
                   "Use JPG, PNG, WEBP o GIF."
        )

    # Leer contenido y validar tamaño
    contenido = await file.read()
    if len(contenido) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo supera el tamaño máximo permitido de 5 MB."
        )

    extension = os.path.splitext(file.filename or "")[1].lower()
    if not validar_archivo(
        extension, contenido,
        content_type=file.content_type, permitidas=EXTENSIONES_IMAGEN
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El contenido del archivo no coincide con una imagen válida "
                   "(JPG, PNG, WEBP o GIF)."
        )

    # Nombre único: evita colisiones y no se puede adivinar la URL
    nombre_archivo = f"{uuid.uuid4().hex}{extension}"
    try:
        return storage.guardar_publico(contenido, nombre_archivo)
    except storage.ErrorAlmacenamiento:
        # Guardado fallido (p. ej. R2 inaccesible): mejor un error claro que guardar
        # una URL que apunte a un archivo que no existe.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo guardar la imagen. Vuelve a intentarlo en unos "
                   "segundos.")
