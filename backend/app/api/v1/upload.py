"""
Router para subida de archivos (vouchers, imágenes)
"""
import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends, Request, Query
from fastapi.responses import JSONResponse
from app.core.dependencies import get_current_user
from app.core.file_validation import validar_archivo
from app.core.rate_limit import limiter, LIMIT_CRITICO

router = APIRouter()

# __file__ está en backend/app/api/v1/ -> subir 3 niveles: .., .., ../static/uploads
UPLOAD_DIR = os.path.join(os.path.dirname(
    __file__), "..", "..", "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# VOUCHERS PRIVADOS: carpeta FUERA de static/ a proposito. Lo que vive bajo static/
# lo sirve StaticFiles SIN autenticacion (y nginx proxea /static/). Los comprobantes
# de pago nuevos se guardan aca y solo se leen por el endpoint autenticado
# GET /solicitudes/{id}/voucher (ver solicitudes_planes.py).
# Los vouchers viejos en /static/uploads quedan como estan (mitigado por el UUID).
PRIVATE_DIR = os.path.join(os.path.dirname(
    __file__), "..", "..", "private_uploads")
PRIVATE_URL_PREFIX = "/privado/vouchers/"
os.makedirs(PRIVATE_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/voucher", status_code=status.HTTP_201_CREATED)
@limiter.limit(LIMIT_CRITICO)
async def upload_voucher(
    request: Request,
    file: UploadFile = File(...),
    privado: bool = Query(
        False,
        description="true = comprobante de pago -> carpeta privada (solo se sirve "
                    "por el endpoint autenticado de la solicitud)"),
    current_user: dict = Depends(get_current_user),
):
    """
    Sube un archivo y devuelve la URL.

    - privado=true (comprobantes de pago): se guarda en app/private_uploads/ (fuera
      de static/) y solo se puede leer por el endpoint autenticado
      GET /solicitudes/{id}/voucher. Devuelve /privado/vouchers/<archivo>.
    - privado=false (default, comportamiento historico: imagenes de productos,
      certificados): se guarda en app/static/uploads/ y se sirve publico.

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

    # Generar nombre único
    unique_name = f"voucher_{uuid.uuid4().hex}{ext}"
    destino = PRIVATE_DIR if privado else UPLOAD_DIR
    file_path = os.path.join(destino, unique_name)

    # Guardar archivo
    with open(file_path, "wb") as f:
        f.write(content)

    # URL privada (solo por endpoint autenticado) o publica (static)
    url = (f"{PRIVATE_URL_PREFIX}{unique_name}" if privado
           else f"/static/uploads/{unique_name}")
    return {"url": url, "filename": unique_name, "privado": privado}

