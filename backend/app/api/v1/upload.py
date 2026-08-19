"""
Router para subida de archivos (vouchers, imágenes)
"""
import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends, Request
from fastapi.responses import JSONResponse
from app.core.dependencies import get_current_user
from app.core.file_validation import validar_archivo
from app.core.rate_limit import limiter, LIMIT_CRITICO

router = APIRouter()

# __file__ está en backend/app/api/v1/ -> subir 3 niveles: .., .., ../static/uploads
UPLOAD_DIR = os.path.join(os.path.dirname(
    __file__), "..", "..", "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/voucher", status_code=status.HTTP_201_CREATED)
@limiter.limit(LIMIT_CRITICO)
async def upload_voucher(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Sube un archivo de voucher y devuelve la URL pública.
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
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    # Guardar archivo
    with open(file_path, "wb") as f:
        f.write(content)

    # Devolver URL pública
    public_url = f"/static/uploads/{unique_name}"
    return {"url": public_url, "filename": unique_name}

