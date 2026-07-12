"""
Router de endpoints para gestión de Planes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.models.plan import Plan

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_plan(
    tenant_id: int,
    nombre: str,
    precio_clp: int,
    duracion_dias: int = 30,
    creditos: Optional[int] = None,
    es_ilimitado: bool = False,
    genero: Optional[str] = None,
    requiere_certificado_estudiante: bool = False,
    db: Session = Depends(get_db)
):
    """Crea un nuevo plan"""
    existing = db.query(Plan).filter(
        Plan.tenant_id == tenant_id,
        Plan.nombre == nombre
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe el plan '{nombre}' en este box"
        )

    db_plan = Plan(
        tenant_id=tenant_id,
        nombre=nombre,
        precio_clp=precio_clp,
        creditos=creditos,
        es_ilimitado=es_ilimitado,
        genero=genero,
        requiere_certificado_estudiante=requiere_certificado_estudiante,
        duracion_dias=duracion_dias,
        activo=True
    )
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan


@router.get("")
def listar_planes(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    activo: Optional[bool] = None,
    genero: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Lista planes de un tenant"""
    query = db.query(Plan).filter(Plan.tenant_id == tenant_id)
    if activo is not None:
        query = query.filter(Plan.activo == activo)
    if genero is not None:
        query = query.filter(Plan.genero == genero)
    return query.offset(skip).limit(limit).all()


@router.get("/membresia-activa")
def obtener_membresia_activa(
    tenant_id: int,
    alumno_id: int,
    db: Session = Depends(get_db)
):
    """
    Retorna la membresía activa del alumno (suscripción vigente).
    """
    from datetime import datetime, timezone
    from app.models.suscripcion import Suscripcion

    ahora = datetime.now(timezone.utc)

    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id == alumno_id,
        Suscripcion.estado == 'activo',
        Suscripcion.fecha_expiracion > ahora
    ).order_by(Suscripcion.creditos_disponibles.desc().nulls_last(), Suscripcion.fecha_expiracion.desc()).first()

    if not suscripcion:
        return {"activa": False, "plan_nombre": None, "dias_restantes": 0, "clases_disponibles": 0, "es_ilimitado": False, "fecha_vencimiento": None}

    plan = db.query(Plan).filter(Plan.id == suscripcion.plan_id).first()
    dias_restantes = (suscripcion.fecha_expiracion.replace(
        tzinfo=timezone.utc) - ahora).days

    return {
        "activa": True,
        "plan_nombre": plan.nombre if plan else None,
        "dias_restantes": max(dias_restantes, 0),
        "clases_disponibles": suscripcion.creditos_disponibles if hasattr(suscripcion, 'creditos_disponibles') else 0,
        "es_ilimitado": plan.es_ilimitado if plan else False,
        "fecha_vencimiento": suscripcion.fecha_expiracion,
    }


@router.get("/{plan_id}")
def obtener_plan(
    plan_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un plan por su ID"""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {plan_id} no encontrado"
        )
    return plan


@router.put("/{plan_id}")
def actualizar_plan(
    plan_id: int,
    nombre: Optional[str] = None,
    precio_clp: Optional[int] = None,
    creditos: Optional[int] = None,
    es_ilimitado: Optional[bool] = None,
    duracion_dias: Optional[int] = None,
    activo: Optional[bool] = None,
    genero: Optional[str] = None,
    requiere_certificado_estudiante: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """Actualiza un plan existente"""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {plan_id} no encontrado"
        )

    if nombre is not None:
        plan.nombre = nombre
    if precio_clp is not None:
        plan.precio_clp = precio_clp
    if creditos is not None:
        plan.creditos = creditos
    if es_ilimitado is not None:
        plan.es_ilimitado = es_ilimitado
    if duracion_dias is not None:
        plan.duracion_dias = duracion_dias
    if activo is not None:
        plan.activo = activo
    if genero is not None:
        plan.genero = genero
    if requiere_certificado_estudiante is not None:
        plan.requiere_certificado_estudiante = requiere_certificado_estudiante

    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_plan(
    plan_id: int,
    db: Session = Depends(get_db)
):
    """Desactiva un plan (soft delete)"""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {plan_id} no encontrado"
        )
    plan.activo = False
    db.commit()
    return None
