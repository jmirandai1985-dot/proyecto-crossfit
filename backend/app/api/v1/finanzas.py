"""
Router de endpoints para transacciones financieras.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from datetime import date, datetime, timezone, timedelta
from pydantic import BaseModel, Field
from typing import Optional, List

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


@router.get("/transacciones")
def listar_transacciones(
    tenant_id: int = Query(...),
    mes: Optional[int] = None,
    anio: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Lista todas las transacciones financieras del mes."""
    ahora = datetime.now(timezone.utc)
    mes = mes or ahora.month
    anio = anio or ahora.year
    inicio = date(anio, mes, 1)
    if mes == 12:
        fin = date(anio + 1, 1, 1) - timedelta(days=1)
    else:
        fin = date(anio, mes + 1, 1) - timedelta(days=1)

    rows = db.execute(sql_text("""
        SELECT id, tenant_id, tipo, categoria, monto, descripcion,
               referencia_tipo, referencia_id, fecha, created_at
        FROM transacciones_financieras
        WHERE tenant_id = :tid AND fecha >= :ini AND fecha <= :fin
        ORDER BY fecha DESC, created_at DESC
    """), {"tid": tenant_id, "ini": inicio, "fin": fin}).fetchall()

    return [
        {
            "id": r.id,
            "tipo": r.tipo,
            "categoria": r.categoria,
            "monto": float(r.monto),
            "descripcion": r.descripcion,
            "referencia_tipo": r.referencia_tipo,
            "referencia_id": r.referencia_id,
            "fecha": str(r.fecha),
            "created_at": str(r.created_at) if r.created_at else None,
        }
        for r in rows
    ]
