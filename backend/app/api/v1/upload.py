"""
Router para subida de archivos (vouchers, imágenes)
"""
import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.responses import JSONResponse

router = APIRouter()

# __file__ está en backend/app/api/v1/ -> subir 3 niveles: .., .., ../static/uploads
UPLOAD_DIR = os.path.join(os.path.dirname(
    __file__), "..", "..", "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/voucher", status_code=status.HTTP_201_CREATED)
async def upload_voucher(file: UploadFile = File(...)):
    """
    Sube un archivo de voucher y devuelve la URL pública.
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

    # Generar nombre único
    unique_name = f"voucher_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    # Guardar archivo
    with open(file_path, "wb") as f:
        f.write(content)

    # Devolver URL pública
    public_url = f"/static/uploads/{unique_name}"
    return {"url": public_url, "filename": unique_name}
