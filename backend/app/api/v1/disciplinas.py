"""
Router de endpoints para gestión de Disciplinas
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.models.disciplina import Disciplina

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
def crear_disciplina(
    tenant_id: int,
    nombre: str,
    descripcion: Optional[str] = None,
    es_open_box: bool = False,
    db: Session = Depends(get_db)
):
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
        nombre=nombre,
        descripcion=descripcion,
        es_open_box=es_open_box,
        activo=True
    )
    db.add(db_disciplina)
    db.commit()
    db.refresh(db_disciplina)
    return db_disciplina


@router.get("/")
def listar_disciplinas(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Disciplina).filter(Disciplina.tenant_id == tenant_id)
    if activo is not None:
        query = query.filter(Disciplina.activo == activo)
    return query.offset(skip).limit(limit).all()


@router.get("/{disciplina_id}")
def obtener_disciplina(
    disciplina_id: int,
    db: Session = Depends(get_db)
):
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id
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
    activo: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id
    ).first()
    if not disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disciplina {disciplina_id} no encontrada"
        )
    if nombre is not None:
        disciplina.nombre = nombre
    if descripcion is not None:
        disciplina.descripcion = descripcion
    if es_open_box is not None:
        disciplina.es_open_box = es_open_box
    if activo is not None:
        disciplina.activo = activo

    db.commit()
    db.refresh(disciplina)
    return disciplina


@router.delete("/{disciplina_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_disciplina(
    disciplina_id: int,
    db: Session = Depends(get_db)
):
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id
    ).first()
    if not disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disciplina {disciplina_id} no encontrada"
        )
    disciplina.activo = False
    db.commit()
    return None
