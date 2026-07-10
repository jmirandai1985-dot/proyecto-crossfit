from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, date, time, timedelta

from app.db.database import get_db
from app.models.clase import Clase
from app.schemas import clase as schemas

router = APIRouter(tags=["Clases"])


@router.get("/", response_model=List[schemas.ClaseListItem])
def listar_clases(
    db: Session = Depends(get_db),
    tenant_id: int = Query(1),
    coach_id: Optional[int] = Query(None),
    fecha: Optional[date] = Query(
        None, description="Filtrar por fecha (YYYY-MM-DD)"),
    solo_con_cupo: Optional[bool] = Query(
        None, description="Solo clases con cupos disponibles"),
    skip: int = Query(0),
    limit: int = Query(100)
):
    conditions = ["c.tenant_id = :tenant_id"]
    query_params = {"tenant_id": tenant_id, "limit": limit, "skip": skip}
    if coach_id is not None:
        conditions.append("c.coach_id = :coach_id")
        query_params["coach_id"] = coach_id
    if fecha is not None:
        conditions.append("c.fecha = :fecha")
        query_params["fecha"] = fecha
    if solo_con_cupo:
        conditions.append("c.asistentes_confirmados < c.cupo_maximo")
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = text(f"""
        SELECT c.id, c.fecha, c.hora_inicio, c.hora_fin, c.disciplina_id, c.coach_id,
               c.cupo_maximo, c.asistentes_confirmados, c.cancelada,
               c.horario_base_id, c.tenant_id, c.created_at, c.updated_at,
               d.nombre AS disciplina_nombre,
               u.nombre AS coach_nombre
        FROM clases c
        LEFT JOIN disciplinas d ON c.disciplina_id = d.id
        LEFT JOIN usuarios u ON c.coach_id = u.id
        {where_clause}
        ORDER BY c.fecha DESC, c.hora_inicio ASC
        LIMIT :limit OFFSET :skip
    """)
    rows = db.execute(query, query_params).fetchall()
    result = []
    for row in rows:
        result.append({
            "id": row.id,
            "fecha": row.fecha,
            "hora_inicio": row.hora_inicio,
            "hora_fin": row.hora_fin,
            "disciplina_id": row.disciplina_id,
            "coach_id": row.coach_id,
            "cupo_maximo": row.cupo_maximo,
            "asistentes_confirmados": row.asistentes_confirmados,
            "cancelada": row.cancelada,
            "disciplina_nombre": row.disciplina_nombre,
            "coach_nombre": row.coach_nombre,
        })
    return result


@router.get("/{clase_id}", response_model=schemas.ClaseResponse)
def obtener_clase(
    clase_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Query(1)
):
    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    return clase


@router.post("/", response_model=schemas.ClaseResponse)
def crear_clase(
    clase: schemas.ClaseCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Query(1)
):
    nueva_clase = Clase(
        tenant_id=tenant_id,
        horario_base_id=clase.horario_base_id,
        coach_id=clase.coach_id,
        disciplina_id=clase.disciplina_id,
        fecha=clase.fecha,
        hora_inicio=clase.hora_inicio,
        hora_fin=clase.hora_fin,
        cupo_maximo=clase.cupo_maximo,
        asistentes_confirmados=0,
        cancelada=False
    )

    db.add(nueva_clase)
    db.commit()
    db.refresh(nueva_clase)

    return nueva_clase


@router.put("/{clase_id}", response_model=schemas.ClaseResponse)
def actualizar_clase(
    clase_id: int,
    clase_update: schemas.ClaseCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Query(1)
):
    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    clase.hora_inicio = clase_update.hora_inicio
    clase.hora_fin = clase_update.hora_fin
    clase.cupo_maximo = clase_update.cupo_maximo
    clase.fecha = clase_update.fecha

    db.commit()
    db.refresh(clase)

    return clase


@router.delete("/{clase_id}")
def eliminar_clase(
    clase_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Query(1)
):
    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    db.delete(clase)
    db.commit()

    return {"mensaje": "Clase eliminada"}
