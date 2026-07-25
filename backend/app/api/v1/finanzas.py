"""
Router de endpoints para transacciones financieras.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date
from pydantic import BaseModel, Field
from typing import Optional

from app.db.database import get_db
from app.models.transaccion_financiera import TransaccionFinanciera

router = APIRouter()


class TransaccionCreate(BaseModel):
    tipo: str = Field(..., pattern="^(ingreso|egreso)$")
    categoria: str = Field(..., min_length=1, max_length=50)
    monto: float = Field(..., gt=0)
    descripcion: Optional[str] = None
    fecha: date
    tenant_id: int = Field(..., gt=0)
    referencia_tipo: Optional[str] = None
    referencia_id: Optional[int] = None


@router.post("/transaccion")
def crear_transaccion(
    data: TransaccionCreate,
    db: Session = Depends(get_db)
):
    """Registra un ingreso o egreso manual."""
    tx = TransaccionFinanciera(
        tenant_id=data.tenant_id,
        tipo=data.tipo,
        categoria=data.categoria,
        monto=data.monto,
        descripcion=data.descripcion,
        referencia_tipo=data.referencia_tipo,
        referencia_id=data.referencia_id,
        fecha=data.fecha,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return {"ok": True, "id": tx.id}
