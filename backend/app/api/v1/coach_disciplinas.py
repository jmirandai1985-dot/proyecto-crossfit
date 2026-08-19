"""
Router de endpoints para gestión de Coach-Disciplinas
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.database import get_db
from app.models.coach_disciplina import CoachDisciplina
from app.schemas.coach_disciplina import (
    CoachDisciplinaCreate, CoachDisciplinaUpdate, CoachDisciplinaResponse, CoachDisciplinaListItem, CoachDisciplinaReplaceRequest
)
from app.core.dependencies import get_current_admin, get_current_coach

router = APIRouter()


@router.post("", response_model=CoachDisciplinaResponse, status_code=status.HTTP_201_CREATED)
def crear_coach_disciplina(
    coach_disciplina_data: CoachDisciplinaCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea una nueva relación coach-disciplina (tenant del token)"""
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    coach_disciplina_data.tenant_id = current_user["tenant_id"]

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
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Obtiene una relación coach-disciplina por su ID (coach/admin, tenant del token)"""
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    coach_disciplina = db.query(CoachDisciplina).filter(
        CoachDisciplina.id == coach_disciplina_id,
        CoachDisciplina.tenant_id == tenant_id,
    ).first()

    if not coach_disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coach-Disciplina con ID {coach_disciplina_id} no encontrada"
        )

    return coach_disciplina


@router.get("", response_model=List[CoachDisciplinaListItem])
def listar_coach_disciplinas(
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    activo: bool = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Lista relaciones coach-disciplina del tenant (derivado del token) con paginación"""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    query = db.query(CoachDisciplina).filter(
        CoachDisciplina.tenant_id == tenant_id)

    if activo is not None:
        query = query.filter(CoachDisciplina.activo == activo)

    coach_disciplinas = query.offset(skip).limit(limit).all()

    return coach_disciplinas


@router.put("/reemplazar", response_model=List[CoachDisciplinaResponse])
def reemplazar_coach_disciplinas(
    data: CoachDisciplinaReplaceRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Reemplaza TODAS las asignaciones de disciplinas de un coach.
    - Las disciplinas en disciplina_ids se marcan activo=true (upsert)
    - Las que ya no están se marcan activo=false (no se borran)
    """
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    data.tenant_id = current_user["tenant_id"]
    # Obtener asignaciones actuales
    actuales = db.query(CoachDisciplina).filter(
        CoachDisciplina.tenant_id == data.tenant_id,
        CoachDisciplina.coach_id == data.coach_id
    ).all()

    ids_actuales = {cd.disciplina_id for cd in actuales if cd.activo}
    ids_nuevos = set(data.disciplina_ids)

    # Desactivar las que ya no están
    for cd in actuales:
        if cd.disciplina_id not in ids_nuevos and cd.activo:
            cd.activo = False

    # Crear o reactivar las nuevas
    for disc_id in ids_nuevos:
        existing = None
        for cd in actuales:
            if cd.disciplina_id == disc_id:
                existing = cd
                break
        if existing:
            if not existing.activo:
                existing.activo = True
        else:
            nueva = CoachDisciplina(
                tenant_id=data.tenant_id,
                coach_id=data.coach_id,
                disciplina_id=disc_id,
                activo=True
            )
            db.add(nueva)

    db.commit()

    # Retornar asignaciones activas resultantes
    resultado = db.query(CoachDisciplina).filter(
        CoachDisciplina.tenant_id == data.tenant_id,
        CoachDisciplina.coach_id == data.coach_id,
        CoachDisciplina.activo == True
    ).all()
    return resultado


@router.put("/{coach_disciplina_id}", response_model=CoachDisciplinaResponse)
def actualizar_coach_disciplina(
    coach_disciplina_id: int,
    coach_disciplina_data: CoachDisciplinaUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Actualiza una relación coach-disciplina existente (tenant del token)"""
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    coach_disciplina = db.query(CoachDisciplina).filter(
        CoachDisciplina.id == coach_disciplina_id,
        CoachDisciplina.tenant_id == tenant_id,
    ).first()

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
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Desactiva una relación coach-disciplina (soft delete, tenant del token)"""
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    coach_disciplina = db.query(CoachDisciplina).filter(
        CoachDisciplina.id == coach_disciplina_id,
        CoachDisciplina.tenant_id == tenant_id,
    ).first()

    if not coach_disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coach-Disciplina con ID {coach_disciplina_id} no encontrada"
        )

    coach_disciplina.activo = False
    db.commit()

    return None
