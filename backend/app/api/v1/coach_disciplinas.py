"""
Router de endpoints para gestión de Coach-Disciplinas
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.coach_disciplina import CoachDisciplina
from app.schemas.coach_disciplina import (
    CoachDisciplinaCreate, CoachDisciplinaUpdate, CoachDisciplinaResponse, CoachDisciplinaListItem
)

router = APIRouter()


@router.post("", response_model=CoachDisciplinaResponse, status_code=status.HTTP_201_CREATED)
def crear_coach_disciplina(
    coach_disciplina_data: CoachDisciplinaCreate,
    db: Session = Depends(get_db)
):
    """Crea una nueva relación coach-disciplina"""

    # Verificar que no exista una relación duplicada
    existing = db.query(CoachDisciplina).filter(
        CoachDisciplina.tenant_id == coach_disciplina_data.tenant_id,
        CoachDisciplina.coach_id == coach_disciplina_data.coach_id,
        CoachDisciplina.disciplina_id == coach_disciplina_data.disciplina_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este coach ya está asignado a esta disciplina"
        )

    db_coach_disciplina = CoachDisciplina(
        tenant_id=coach_disciplina_data.tenant_id,
        coach_id=coach_disciplina_data.coach_id,
        disciplina_id=coach_disciplina_data.disciplina_id,
        activo=coach_disciplina_data.activo
    )

    db.add(db_coach_disciplina)
    db.commit()
    db.refresh(db_coach_disciplina)

    return db_coach_disciplina


@router.get("/{coach_disciplina_id}", response_model=CoachDisciplinaResponse)
def obtener_coach_disciplina(
    coach_disciplina_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene una relación coach-disciplina por su ID"""
    coach_disciplina = db.query(CoachDisciplina).filter(
        CoachDisciplina.id == coach_disciplina_id).first()

    if not coach_disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coach-Disciplina con ID {coach_disciplina_id} no encontrada"
        )

    return coach_disciplina


@router.get("", response_model=List[CoachDisciplinaListItem])
def listar_coach_disciplinas(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    activo: bool = None,
    db: Session = Depends(get_db)
):
    """Lista relaciones coach-disciplina de un tenant con paginación"""
    query = db.query(CoachDisciplina).filter(
        CoachDisciplina.tenant_id == tenant_id)

    if activo is not None:
        query = query.filter(CoachDisciplina.activo == activo)

    coach_disciplinas = query.offset(skip).limit(limit).all()

    return coach_disciplinas


@router.put("/{coach_disciplina_id}", response_model=CoachDisciplinaResponse)
def actualizar_coach_disciplina(
    coach_disciplina_id: int,
    coach_disciplina_data: CoachDisciplinaUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza una relación coach-disciplina existente"""
    coach_disciplina = db.query(CoachDisciplina).filter(
        CoachDisciplina.id == coach_disciplina_id).first()

    if not coach_disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coach-Disciplina con ID {coach_disciplina_id} no encontrada"
        )

    update_data = coach_disciplina_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(coach_disciplina, field, value)

    db.commit()
    db.refresh(coach_disciplina)

    return coach_disciplina


@router.delete("/{coach_disciplina_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_coach_disciplina(
    coach_disciplina_id: int,
    db: Session = Depends(get_db)
):
    """Desactiva una relación coach-disciplina (soft delete)"""
    coach_disciplina = db.query(CoachDisciplina).filter(
        CoachDisciplina.id == coach_disciplina_id).first()

    if not coach_disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coach-Disciplina con ID {coach_disciplina_id} no encontrada"
        )

    coach_disciplina.activo = False
    db.commit()

    return None
