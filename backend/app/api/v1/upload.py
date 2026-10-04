"""
Router para subida de archivos (vouchers, imágenes).

Todo pasa por la capa ÚNICA de almacenamiento (`app/services/storage.py`): en
dev/TEST escribe en disco (app/private_uploads y app/static/uploads) y en PROD en
Cloudflare R2 (STORAGE_BACKEND=r2). Los comprobantes van SIEMPRE por el camino
privado (`?privado=1`) y solo se leen por el endpoint autenticado
(ver app/core/documentos_privados.py).
"""
import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends, Request, Query
from app.core.dependencies import get_current_user
from app.core.file_validation import validar_archivo
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.services import storage

router = APIRouter()

# Compatibilidad: directorios del backend LOCAL (dev/TEST). Los usan los tests
# para escribir archivos de prueba; el guardado real lo hace `storage`.
UPLOAD_DIR = storage.UPLOAD_DIR
PRIVATE_DIR = storage.PRIVATE_DIR
PRIVATE_URL_PREFIX = storage.PRIVATE_PREFIX

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/voucher", status_code=status.HTTP_201_CREATED)
@limiter.limit(LIMIT_CRITICO)
async def upload_voucher(
    request: Request,
    file: UploadFile = File(...),
    privado: bool = Query(
        False,
        description="true = comprobante de pago -> se guarda PRIVADO (solo se sirve "
                    "por el endpoint autenticado de la solicitud/pedido)"),
    current_user: dict = Depends(get_current_user),
):
    """
    Sube un archivo y devuelve la URL que se guarda en la BD.

    - privado=true (comprobantes de pago y certificados): devuelve
      /privado/vouchers/<archivo> y solo se puede leer por el endpoint autenticado
      (GET /solicitudes/{id}/voucher, /certificado y /pedidos/{id}/comprobante).
    - privado=false (imágenes de productos): devuelve la URL pública
      (/static/uploads/<archivo> en local; en R2 la URL absoluta del bucket).

    Requiere usuario autenticado.
    """
    # Validar extensión
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido. Permitidos: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Leer contenido
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400, detail="Archivo demasiado grande. Máximo 5MB")

    # Validar contenido real (magic bytes), no solo la extensión.
    # Evita subir ejecutables o archivos disfrazados con extensión .jpg/.pdf.
    if not validar_archivo(ext, content, content_type=file.content_type):
        raise HTTPException(
            status_code=400,
            detail="El contenido del archivo no coincide con su extensión. "
                   "Envía una imagen (JPG, PNG, GIF, WEBP) o PDF válido."
        )

    # Nombre único (evita colisiones; el UUID es lo que impide adivinar el archivo)
    unique_name = f"voucher_{uuid.uuid4().hex}{ext}"

    try:
        url = (storage.guardar_privado(content, unique_name) if privado
               else storage.guardar_publico(content, unique_name))
    except storage.ErrorAlmacenamiento:
        # El guardado FALLÓ (p. ej. R2 inaccesible): se responde claro y NO se
        # devuelve una URL que apuntaría a un archivo inexistente.
        raise HTTPException(
            status_code=503,
            detail="No se pudo guardar el archivo. Vuelve a intentarlo en unos segundos.")

    return {"url": url, "filename": unique_name, "privado": privado}


