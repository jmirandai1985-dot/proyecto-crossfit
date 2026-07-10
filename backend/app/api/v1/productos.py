"""
Router de endpoints para gestión de Productos
"""
import os
import uuid
import shutil
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.database import get_db
from app.models.producto import Producto
from app.schemas.producto import (
    ProductoUpdate, ProductoResponse, ProductoListItem
)

router = APIRouter()

# Directorio donde se guardarán las imágenes subidas
UPLOAD_DIR = os.path.join(os.path.dirname(
    __file__), "..", "..", "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("", response_model=ProductoResponse, status_code=status.HTTP_201_CREATED)
async def crear_producto(
    nombre: str = Form(...),
    precio: float = Form(...),
    stock: int = Form(...),
    tenant_id: int = Form(...),
    descripcion: Optional[str] = Form(None),
    activo: bool = Form(True),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """Crea un nuevo producto. Acepta multipart/form-data para soportar imagen opcional."""

    imagen_url = None

    # Procesar imagen si se adjuntó
    if file and file.filename:
        # Validar tipo de contenido
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tipo de archivo no permitido: {file.content_type}. Use JPG, PNG, WEBP o GIF."
            )

        # Leer contenido y validar tamaño
        contenido = await file.read()
        if len(contenido) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo supera el tamaño máximo permitido de 5 MB."
            )

        # Generar nombre único para evitar colisiones
        extension = os.path.splitext(file.filename)[1].lower()
        nombre_archivo = f"{uuid.uuid4().hex}{extension}"
        ruta_destino = os.path.join(UPLOAD_DIR, nombre_archivo)

        # Guardar el archivo en disco
        with open(ruta_destino, "wb") as f:
            f.write(contenido)

        imagen_url = f"/static/uploads/{nombre_archivo}"

    db_producto = Producto(
        tenant_id=tenant_id,
        nombre=nombre,
        descripcion=descripcion or None,
        precio=precio,
        stock=stock,
        activo=activo,
    )

    db.add(db_producto)
    db.commit()
    db.refresh(db_producto)

    return db_producto


@router.get("/{producto_id}", response_model=ProductoResponse)
def obtener_producto(
    producto_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un producto por su ID"""
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.tenant_id == tenant_id
    ).first()

    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID {producto_id} no encontrado"
        )

    return producto


@router.get("", response_model=List[ProductoListItem])
def listar_productos(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    activo: bool = None,
    db: Session = Depends(get_db)
):
    """Lista productos de un tenant con paginación"""
    query = db.query(Producto).filter(Producto.tenant_id == tenant_id)

    if activo is not None:
        query = query.filter(Producto.activo == activo)

    productos = query.offset(skip).limit(limit).all()

    return productos


@router.put("/{producto_id}", response_model=ProductoResponse)
def actualizar_producto(
    producto_id: int,
    producto_data: ProductoUpdate,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Actualiza un producto existente"""
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.tenant_id == tenant_id
    ).first()

    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID {producto_id} no encontrado"
        )

    update_data = producto_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(producto, field, value)

    db.commit()
    db.refresh(producto)

    return producto


@router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_producto(
    producto_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Desactiva un producto (soft delete)"""
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.tenant_id == tenant_id
    ).first()

    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID {producto_id} no encontrado"
        )

    producto.activo = False
    db.commit()

    return None
