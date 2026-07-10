"""
Router de endpoints para gestión de Horarios
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.models.horario_base import HorarioBase

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_horario(
    tenant_id: int,
    disciplina_id: int,
    dia_semana: int,
    hora_inicio: str,
    hora_fin: str,
    cupo_maximo: int = 16,
    db: Session = Depends(get_db)
):
    db_horario = HorarioBase(
        tenant_id=tenant_id,
        disciplina_id=disciplina_id,
        dia_semana=dia_semana,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        cupo_maximo=cupo_maximo,
        activo=True
    )
    db.add(db_horario)
    db.commit()
    db.refresh(db_horario)
    return db_horario


@router.get("")
def listar_horarios(
    tenant_id: int,
    dia_semana: Optional[int] = None,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(HorarioBase).filter(HorarioBase.tenant_id == tenant_id)
    if dia_semana is not None:
        query = query.filter(HorarioBase.dia_semana == dia_semana)
    if activo is not None:
        query = query.filter(HorarioBase.activo == activo)
    return query.order_by(HorarioBase.dia_semana, HorarioBase.hora_inicio).all()


@router.get("/{horario_id}")
def obtener_horario(
    horario_id: int,
    db: Session = Depends(get_db)
):
    horario = db.query(HorarioBase).filter(
        HorarioBase.id == horario_id).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado"
        )
    return horario


@router.put("/{horario_id}")
def actualizar_horario(
    horario_id: int,
    dia_semana: Optional[int] = None,
    hora_inicio: Optional[str] = None,
    hora_fin: Optional[str] = None,
    cupo_maximo: Optional[int] = None,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    horario = db.query(HorarioBase).filter(
        HorarioBase.id == horario_id).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado"
        )
    if dia_semana is not None:
        horario.dia_semana = dia_semana
    if hora_inicio is not None:
        horario.hora_inicio = hora_inicio
    if hora_fin is not None:
        horario.hora_fin = hora_fin
    if cupo_maximo is not None:
        horario.cupo_maximo = cupo_maximo
    if activo is not None:
        horario.activo = activo
    db.commit()
    db.refresh(horario)
    return horario


@router.delete("/{horario_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_horario(
    horario_id: int,
    db: Session = Depends(get_db)
):
    horario = db.query(HorarioBase).filter(
        HorarioBase.id == horario_id).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado"
        )
    horario.activo = False
    db.commit()
    return None


@router.post("/generar-clases-dia")
def generar_clases_dia(
    tenant_id: int,
    fecha: str,
    db: Session = Depends(get_db)
):
    """
    Genera clases en la tabla 'clases' a partir de los horarios_base
    del día de semana correspondiente a la 'fecha' indicada (YYYY-MM-DD).
    NO duplica si ya existen clases con el mismo (horario_base_id, fecha).
    """
    from datetime import date, datetime
    from app.models.clase import Clase

    try:
        fecha_date = datetime.strptime(fecha, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Formato de fecha inválido. Use YYYY-MM-DD"
        )

    dia_semana = fecha_date.weekday()  # 0=Lun ... 6=Dom
    if dia_semana == 6:
        return {"message": "Domingo: no hay horarios base programados", "creadas": 0}

    horarios = db.query(HorarioBase).filter(
        HorarioBase.tenant_id == tenant_id,
        HorarioBase.dia_semana == dia_semana,
        HorarioBase.activo == True
    ).all()

    if not horarios:
        return {"message": f"No hay horarios base activos para el día {dia_semana}", "creadas": 0}

    creadas = 0
    omitidas = 0
    for h in horarios:
        existe = db.query(Clase).filter(
            Clase.tenant_id == tenant_id,
            Clase.horario_base_id == h.id,
            Clase.fecha == fecha_date
        ).first()
        if existe:
            omitidas += 1
            continue

        clase = Clase(
            tenant_id=tenant_id,
            horario_base_id=h.id,
            disciplina_id=h.disciplina_id,
            fecha=fecha_date,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            cupo_maximo=h.cupo_maximo,
            asistentes_confirmados=0,
            cancelada=False,
        )
        db.add(clase)
        creadas += 1

    db.commit()

    return {
        "message": f"{creadas} clases generadas para {fecha}",
        "creadas": creadas,
        "omitidas": omitidas,
        "total_horarios": len(horarios),
        "fecha": fecha,
        "dia_semana": dia_semana,
    }
