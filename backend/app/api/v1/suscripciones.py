from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from app.db.database import get_db
from app.models.suscripcion import Suscripcion

router = APIRouter()


class SuscripcionCreate(BaseModel):
    tenant_id: int
    usuario_id: int
    plan_id: int
    estado: str = "activo"
    creditos_totales: Optional[int] = None
    creditos_disponibles: Optional[int] = None
    fecha_inicio: Optional[str] = None
    fecha_expiracion: str


@router.post("/suscripciones", status_code=201)
def crear_suscripcion(data: SuscripcionCreate, db: Session = Depends(get_db)):
    try:
        fecha_exp = datetime.fromisoformat(
            data.fecha_expiracion.replace('Z', '+00:00'))
    except Exception:
        raise HTTPException(
            status_code=400, detail="Formato de fecha_expiracion inválido.")
    db_sus = Suscripcion(
        tenant_id=data.tenant_id,
        usuario_id=data.usuario_id,
        plan_id=data.plan_id,
        estado=data.estado,
        creditos_totales=data.creditos_totales,
        creditos_disponibles=data.creditos_disponibles,
        fecha_inicio=datetime.now(timezone.utc),
        fecha_expiracion=fecha_exp,
    )
    db.add(db_sus)
    db.commit()
    db.refresh(db_sus)
    return db_sus


@router.get("/suscripciones")
def listar_suscripciones(
    tenant_id: int,
    usuario_id: Optional[int] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Suscripcion).filter(Suscripcion.tenant_id == tenant_id)
    if usuario_id:
        query = query.filter(Suscripcion.usuario_id == usuario_id)
    if estado:
        query = query.filter(Suscripcion.estado == estado)
    return query.order_by(Suscripcion.created_at.desc()).all()
