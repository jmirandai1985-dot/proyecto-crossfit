"""
Router de endpoints para gestión de Tenants (Boxes)
"""
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.config import settings
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate, TenantResponse
from app.core.dependencies import get_current_admin
from app.core.rate_limit import limiter

router = APIRouter()


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def crear_tenant(
    tenant_data: TenantCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
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


# ── /me: tenant del token (admin) — expone public_id para el QR ──────────────
@router.get("/me")
def mi_tenant(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Datos del tenant del token (incluye public_id para el QR del box).

    Solo admin. Devuelve {id, nombre, subdomain, public_id} sin exponer
    más infraestructura.
    """
    tenant = db.query(Tenant).filter(Tenant.id == current_user["tenant_id"]).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    return {
        "id": tenant.id,
        "nombre": tenant.nombre,
        "subdomain": tenant.subdomain,
        "public_id": tenant.public_id,
    }


# ── QR del box (público, rate-limited): el QR en sí no es secreto ────────────
@router.get("/{public_id}/qr.svg")
@limiter.limit("30/minute")
def qr_tenant_svg(
    request: Request,
    public_id: str,
    front: Optional[str] = Query(
        None,
        description="Base URL opcional para el contenido del QR "
                    "(default: settings.FRONTEND_URL). Sirve para pruebas en LAN.",
    ),
    db: Session = Depends(get_db),
):
    """Genera la imagen SVG del QR de check-in del box (sin auth).

    Contenido: {front|FRONTEND_URL}/asistencia/qr/{public_id}.
    public_id inexistente → 404 genérico (no revelar).
    """
    tenant = db.query(Tenant).filter(Tenant.public_id == public_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="No encontrado")

    base = (front or "").strip().rstrip("/") or settings.FRONTEND_URL.rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400, detail="front debe ser una URL http(s) válida")

    contenido = f"{base}/asistencia/qr/{tenant.public_id}"

    # Import diferido: segno es pura Python y solo se necesita aquí.
    from segno import make as qr_make

    qr = qr_make(contenido, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=8)
    return Response(
        content=buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{tenant_id}", response_model=TenantResponse)
def obtener_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Obtiene un tenant por su ID. Solo admin (antes estaba público).
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
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Lista todos los tenants con paginación. Solo admin (antes estaba público).
    """
    query = db.query(Tenant)

    if activo is not None:
        query = query.filter(Tenant.activo == activo)

    tenants = query.offset(skip).limit(limit).all()

    return tenants


@router.get("/subdomain/{subdomain}", response_model=TenantResponse)
def obtener_tenant_por_subdominio(
    subdomain: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Obtiene un tenant por su subdominio. Solo admin (antes estaba público).
    """
    tenant = db.query(Tenant).filter(Tenant.subdomain == subdomain).first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant con subdominio '{subdomain}' no encontrado"
        )

    return tenant
