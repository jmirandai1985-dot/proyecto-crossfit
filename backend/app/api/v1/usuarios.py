"""
Router de endpoints para gestión de Usuarios
"""
import bcrypt

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate, UsuarioResponse, UsuarioListItem
from app.core.dependencies import get_current_user

router = APIRouter()


# ─── Schema inline para cambio de contraseña ─────────────────────────────
class CambiarPasswordRequest(BaseModel):
    password_actual: str = Field(..., min_length=1,
                                 description="Contraseña actual del usuario")
    nueva_password: str = Field(..., min_length=6,
                                description="Nueva contraseña (mínimo 6 caracteres)")
    confirmar_password: str = Field(..., min_length=6,
                                    description="Confirmación de la nueva contraseña")


def hash_password(password: str) -> str:
    """Hashea una contraseña usando bcrypt directamente"""
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña contra su hash"""
    password_bytes = plain_password.encode('utf-8')[:72]
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


@router.put("/cambiar-password", status_code=status.HTTP_200_OK)
def cambiar_password(
    datos: CambiarPasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cambia la contraseña del usuario autenticado.

    Verifica que la contraseña actual sea correcta antes de actualizar.
    Requiere token JWT válido en el header Authorization.
    """
    usuario_id = current_user["usuario_id"]

    # Obtener el usuario con su password_hash actual
    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id,
        Usuario.activo == True
    ).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )

    # Verificar que la contraseña actual sea correcta
    if not verify_password(datos.password_actual, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual es incorrecta"
        )

    # Verificar que nueva contraseña y confirmación coincidan
    if datos.nueva_password != datos.confirmar_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseña y su confirmación no coinciden"
        )

    # Verificar que la nueva contraseña sea diferente a la actual
    if verify_password(datos.nueva_password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseña debe ser diferente a la actual"
        )

    # Hashear y guardar la nueva contraseña
    usuario.password_hash = hash_password(datos.nueva_password)
    db.commit()

    return {"message": "Contraseña actualizada exitosamente"}


@router.post("/", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    usuario_data: UsuarioCreate,
    db: Session = Depends(get_db)
):
    """Crea un nuevo usuario en el sistema"""

    # Verificar si el RUT ya existe en este tenant
    existing_rut = db.query(Usuario).filter(
        Usuario.tenant_id == usuario_data.tenant_id,
        Usuario.rut == usuario_data.rut
    ).first()

    if existing_rut:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un usuario con el RUT {usuario_data.rut} en este box"
        )

    # Verificar si el correo ya existe en este tenant
    existing_email = db.query(Usuario).filter(
        Usuario.tenant_id == usuario_data.tenant_id,
        Usuario.correo == usuario_data.correo
    ).first()

    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un usuario con el correo {usuario_data.correo} en este box"
        )

    # Crear el nuevo usuario
    db_usuario = Usuario(
        tenant_id=usuario_data.tenant_id,
        rut=usuario_data.rut,
        nombre=usuario_data.nombre,
        telefono=usuario_data.telefono,
        correo=usuario_data.correo,
        password_hash=hash_password(usuario_data.password),
        rol=usuario_data.rol,
        activo=True
    )

    db.add(db_usuario)
    db.commit()
    db.refresh(db_usuario)

    return db_usuario


@router.get("/{usuario_id}", response_model=UsuarioResponse)
def obtener_usuario(
    usuario_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un usuario por su ID"""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {usuario_id} no encontrado"
        )

    return usuario


@router.get("/", response_model=List[UsuarioListItem])
def listar_usuarios(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    activo: bool = None,
    rol: str = None,
    db: Session = Depends(get_db)
):
    """Lista usuarios de un tenant con paginación"""
    query = db.query(Usuario).filter(Usuario.tenant_id == tenant_id)

    if activo is not None:
        query = query.filter(Usuario.activo == activo)

    if rol is not None:
        query = query.filter(Usuario.rol == rol)

    usuarios = query.offset(skip).limit(limit).all()

    return usuarios


@router.put("/{usuario_id}", response_model=UsuarioResponse)
def actualizar_usuario(
    usuario_id: int,
    usuario_data: UsuarioUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza los datos de un usuario existente"""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {usuario_id} no encontrado"
        )

    update_data = usuario_data.model_dump(exclude_unset=True)

    # Si se proporciona nueva contraseña, hashearla
    if "password" in update_data:
        update_data["password_hash"] = hash_password(
            update_data.pop("password"))

    # Si se actualiza el correo, verificar que no exista en el tenant
    if "correo" in update_data and update_data["correo"] != usuario.correo:
        existing_email = db.query(Usuario).filter(
            Usuario.tenant_id == usuario.tenant_id,
            Usuario.correo == update_data["correo"],
            Usuario.id != usuario_id
        ).first()

        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ya existe otro usuario con el correo {update_data['correo']} en este box"
            )

    for field, value in update_data.items():
        setattr(usuario, field, value)

    db.commit()
    db.refresh(usuario)

    return usuario


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db)
):
    """Desactiva un usuario (soft delete)"""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {usuario_id} no encontrado"
        )

    usuario.activo = False
    db.commit()

    return None
