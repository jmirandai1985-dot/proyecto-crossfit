"""
Router de endpoints para gestión de Disciplinas
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.models.disciplina import Disciplina
from app.core.dependencies import get_current_admin, get_current_user
# Auditoría 1.1: un choque de UNIQUE/FK/CHECK es un 400/409 del cliente, no un 500.
from app.utils.db_commit import commit_o_4xx

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
def crear_disciplina(
    tenant_id: Optional[int] = None,
    nombre: str = None,
    descripcion: Optional[str] = None,
    es_open_box: bool = False,
    requiere_coach: bool = True,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    existing = db.query(Disciplina).filter(
        Disciplina.tenant_id == tenant_id,
        Disciplina.nombre == nombre
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe la disciplina '{nombre}' en este box"
        )

    db_disciplina = Disciplina(
        tenant_id=tenant_id,
        nombre=(nombre or "").strip(),
        descripcion=(descripcion or "").strip() or None,
        es_open_box=es_open_box,
        requiere_coach=requiere_coach,
        activo=True
    )
    db.add(db_disciplina)
    commit_o_4xx(
        db,
        "No se pudo crear la disciplina: revisa el nombre.",
        unico=f"Ya existe la disciplina '{nombre}' en este box.",
        contexto="crear_disciplina",
    )
    db.refresh(db_disciplina)
    return db_disciplina


@router.get("/")
def listar_disciplinas(
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    query = db.query(Disciplina).filter(Disciplina.tenant_id == tenant_id)
    if activo is not None:
        query = query.filter(Disciplina.activo == activo)
    return query.offset(skip).limit(limit).all()


@router.get("/{disciplina_id}")
def obtener_disciplina(
    disciplina_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 🔒 SEGURIDAD: scoping por tenant del token.
    tenant_id = current_user["tenant_id"]
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id,
        Disciplina.tenant_id == tenant_id,
    ).first()
    if not disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disciplina {disciplina_id} no encontrada"
        )
    return disciplina


@router.put("/{disciplina_id}")
def actualizar_disciplina(
    disciplina_id: int,
    nombre: Optional[str] = None,
    descripcion: Optional[str] = None,
    es_open_box: Optional[bool] = None,
    requiere_coach: Optional[bool] = None,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id,
        Disciplina.tenant_id == tenant_id,
    ).first()
    if not disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disciplina {disciplina_id} no encontrada"
        )
    if nombre is not None:
        disciplina.nombre = nombre.strip()
    if descripcion is not None:
        disciplina.descripcion = descripcion.strip() or None
    if es_open_box is not None:
        disciplina.es_open_box = es_open_box
    if requiere_coach is not None:
        disciplina.requiere_coach = requiere_coach
    if activo is not None:
        disciplina.activo = activo

    commit_o_4xx(
        db,
        "No se pudo actualizar la disciplina: revisa los datos enviados.",
        unico=f"Ya existe otra disciplina llamada '{nombre}' en este box.",
        contexto="actualizar_disciplina",
    )
    db.refresh(disciplina)
    return disciplina


@router.delete("/{disciplina_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_disciplina(
    disciplina_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id,
        Disciplina.tenant_id == tenant_id,
    ).first()
    if not disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disciplina {disciplina_id} no encontrada"
        )
    # 🔒 Verificar que la disciplina pertenezca al tenant del admin
    if disciplina.tenant_id != current_user.get("tenant_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esta disciplina",
        )
    disciplina.activo = False
    commit_o_4xx(
        db,
        "No se pudo desactivar la disciplina. Intenta de nuevo.",
        contexto="eliminar_disciplina",
    )
    return None
