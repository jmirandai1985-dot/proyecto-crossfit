"""
Router de endpoints para gestión de Retención
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from datetime import datetime, date, timedelta

from app.db.database import get_db
from app.models.retencion import RetencionAlumno
from app.models.usuario import Usuario
from app.schemas.retencion import (
    RetencionAlumnoCreate, RetencionAlumnoUpdate, RetencionAlumnoResponse,
    RetencionAlumnoListItem, AlumnoEnRiesgo, KPICoach
)

router = APIRouter()


@router.post("", response_model=RetencionAlumnoResponse, status_code=status.HTTP_201_CREATED)
def crear_retencion(
    retencion_data: RetencionAlumnoCreate,
    db: Session = Depends(get_db)
):
    """Crea un nuevo registro de retención"""

    db_retencion = RetencionAlumno(
        tenant_id=retencion_data.tenant_id,
        alumno_id=retencion_data.alumno_id,
        coach_id=retencion_data.coach_id,
        proxima_renovacion=retencion_data.proxima_renovacion,
        estado_plan=retencion_data.estado_plan,
        notas=retencion_data.notas
    )

    db.add(db_retencion)
    db.commit()
    db.refresh(db_retencion)

    return db_retencion


@router.get("/{retencion_id}", response_model=RetencionAlumnoResponse)
def obtener_retencion(
    retencion_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un registro de retención por su ID"""
    retencion = db.query(RetencionAlumno).filter(
        RetencionAlumno.id == retencion_id,
        RetencionAlumno.tenant_id == tenant_id
    ).first()

    if not retencion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Retención con ID {retencion_id} no encontrada"
        )

    return retencion


@router.get("", response_model=List[RetencionAlumnoListItem])
def listar_retencion(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    estado_plan: str = None,
    db: Session = Depends(get_db)
):
    """Lista registros de retención con filtros opcionales"""
    query = db.query(RetencionAlumno).filter(
        RetencionAlumno.tenant_id == tenant_id)

    if estado_plan is not None:
        query = query.filter(RetencionAlumno.estado_plan == estado_plan)

    retencion = query.offset(skip).limit(limit).all()

    return retencion


@router.get("/en-riesgo", response_model=List[AlumnoEnRiesgo])
def obtener_alumnos_en_riesgo(
    tenant_id: int,
    dias_alerta: int = 7,
    db: Session = Depends(get_db)
):
    """
    Obtiene alumnos en riesgo de abandono.
    Criterios: proxima_renovacion <= hoy + dias_alerta y estado_plan != inactivo
    """
    hoy = date.today()
    fecha_limite = hoy + timedelta(days=dias_alerta)

    alumnos_riesgo = db.query(
        RetencionAlumno.id,
        RetencionAlumno.alumno_id,
        Usuario.nombre.label('alumno_nombre'),
        RetencionAlumno.coach_id,
        RetencionAlumno.proxima_renovacion,
        RetencionAlumno.estado_plan,
        RetencionAlumno.notas
    ).join(Usuario, RetencionAlumno.alumno_id == Usuario.id).filter(
        RetencionAlumno.tenant_id == tenant_id,
        RetencionAlumno.proxima_renovacion <= fecha_limite,
        RetencionAlumno.estado_plan != "inactivo"
    ).all()

    return [
        AlumnoEnRiesgo(
            id=r[0],
            alumno_id=r[1],
            alumno_nombre=r[2],
            coach_id=r[3],
            proxima_renovacion=r[4],
            dias_para_renovacion=(r[4] - hoy).days,
            estado_plan=r[5],
            notas=r[6]
        )
        for r in alumnos_riesgo
    ]


@router.get("/kpi-coach", response_model=List[KPICoach])
def obtener_kpi_coach(
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Obtiene KPI de retención por coach.
    Retorna: total_alumnos, alumnos_en_riesgo, tasa_retencion (%)
    """
    hoy = date.today()
    fecha_limite = hoy + timedelta(days=7)

    # Obtener todos los coaches con alumnos
    coaches = db.query(
        RetencionAlumno.coach_id,
        Usuario.nombre.label('coach_nombre')
    ).join(Usuario, RetencionAlumno.coach_id == Usuario.id).filter(
        RetencionAlumno.tenant_id == tenant_id,
        RetencionAlumno.coach_id.isnot(None)
    ).distinct().all()

    kpis = []
    for coach_id, coach_nombre in coaches:
        # Total de alumnos asignados al coach
        total_alumnos = db.query(func.count(RetencionAlumno.id)).filter(
            RetencionAlumno.tenant_id == tenant_id,
            RetencionAlumno.coach_id == coach_id
        ).scalar()

        # Alumnos en riesgo
        alumnos_en_riesgo = db.query(func.count(RetencionAlumno.id)).filter(
            RetencionAlumno.tenant_id == tenant_id,
            RetencionAlumno.coach_id == coach_id,
            RetencionAlumno.proxima_renovacion <= fecha_limite,
            RetencionAlumno.estado_plan != "inactivo"
        ).scalar()

        # Tasa de retención
        tasa_retencion = 0.0
        if total_alumnos > 0:
            alumnos_activos = total_alumnos - alumnos_en_riesgo
            tasa_retencion = (alumnos_activos / total_alumnos) * 100

        kpis.append(KPICoach(
            coach_id=coach_id,
            coach_nombre=coach_nombre,
            total_alumnos=total_alumnos,
            alumnos_en_riesgo=alumnos_en_riesgo,
            tasa_retencion=round(tasa_retencion, 2)
        ))

    return kpis


@router.put("/{retencion_id}", response_model=RetencionAlumnoResponse)
def actualizar_retencion(
    retencion_id: int,
    retencion_data: RetencionAlumnoUpdate,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Actualiza un registro de retención existente"""
    retencion = db.query(RetencionAlumno).filter(
        RetencionAlumno.id == retencion_id,
        RetencionAlumno.tenant_id == tenant_id
    ).first()

    if not retencion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Retención con ID {retencion_id} no encontrada"
        )

    update_data = retencion_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(retencion, field, value)

    db.commit()
    db.refresh(retencion)

    return retencion


@router.delete("/{retencion_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_retencion(
    retencion_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Elimina un registro de retención"""
    retencion = db.query(RetencionAlumno).filter(
        RetencionAlumno.id == retencion_id,
        RetencionAlumno.tenant_id == tenant_id
    ).first()

    if not retencion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Retención con ID {retencion_id} no encontrada"
        )

    db.delete(retencion)
    db.commit()

    return None
