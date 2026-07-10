"""
Router de endpoints para gestión de Tenants (Boxes)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate, TenantResponse

router = APIRouter()


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def crear_tenant(
    tenant_data: TenantCreate,
    db: Session = Depends(get_db)
):
    """
    Crea un nuevo tenant (box) en el sistema

    - **nombre**: Nombre del box
    - **subdomain**: Subdominio único para acceder al box
    """
    # Verificar si el subdominio ya existe
    existing_subdomain = db.query(Tenant).filter(
        Tenant.subdomain == tenant_data.subdomain
    ).first()

    if existing_subdomain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El subdominio '{tenant_data.subdomain}' ya está en uso"
        )

    # Crear el nuevo tenant
    db_tenant = Tenant(
        nombre=tenant_data.nombre,
        subdomain=tenant_data.subdomain,
        activo=True
    )

    db.add(db_tenant)
    db.commit()
    db.refresh(db_tenant)

    return db_tenant


@router.get("/{tenant_id}", response_model=TenantResponse)
def obtener_tenant(
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Obtiene un tenant por su ID

    - **tenant_id**: ID del tenant a consultar
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant con ID {tenant_id} no encontrado"
        )

    return tenant


@router.get("/", response_model=List[TenantResponse])
def listar_tenants(
    skip: int = 0,
    limit: int = 100,
    activo: bool = None,
    db: Session = Depends(get_db)
):
    """
    Lista todos los tenants con paginación

    - **skip**: Número de registros a saltar (paginación)
    - **limit**: Número máximo de registros a devolver
    - **activo**: Filtrar por tenants activos/inactivos (opcional)
    """
    query = db.query(Tenant)

    if activo is not None:
        query = query.filter(Tenant.activo == activo)

    tenants = query.offset(skip).limit(limit).all()

    return tenants


@router.get("/subdomain/{subdomain}", response_model=TenantResponse)
def obtener_tenant_por_subdominio(
    subdomain: str,
    db: Session = Depends(get_db)
):
    """
    Obtiene un tenant por su subdominio

    - **subdomain**: Subdominio del tenant
    """
    tenant = db.query(Tenant).filter(Tenant.subdomain == subdomain).first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant con subdominio '{subdomain}' no encontrado"
        )

    return tenant
