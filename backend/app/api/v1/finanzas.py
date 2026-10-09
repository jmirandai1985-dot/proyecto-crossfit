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
from app.core.dependencies import get_current_admin
from app.utils.caja import resumir_dia          # el CÁLCULO (puro, testeable aislado)
from app.utils.santiago import hoy_santiago      # HOY en Chile (el proceso corre en UTC)

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
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Registra un ingreso o egreso manual. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (el body se ignora).
    data.tenant_id = current_user["tenant_id"]
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
    tenant_id: Optional[int] = Query(None),
    mes: Optional[int] = None,
    anio: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Lista todas las transacciones financieras del mes. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
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


@router.get("/resumen-hoy")
def resumen_caja_hoy(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Caja del DÍA en curso (hora de Chile) sumando `transacciones_financieras`.

    POR QUÉ: el panel móvil necesita "Ingresos de hoy" con el dinero REAL del día. No
    existía endpoint que sumara el día (el único total diario vive en el data mart BI,
    `daily_kpis`, que puede no estar publicado). Acá se reutiliza la MISMA tabla que
    alimenta los KPIs (`kpis_populate`), sin tocar ningún KPI existente.

    - `fecha` es una columna DATE que los escritores llenan con `hoy_santiago()` (aprobar
      una solicitud de plan, alta manual de suscripción, carga manual de Caja): el
      filtro usa el mismo día chileno, no el día UTC del servidor.
    - La carga manual (`POST /finanzas/transaccion`) sí acepta una fecha del pasado en
      el body; esas filas NO entran en "hoy" (es lo correcto: caja del día).
    - Solo admin, y el `tenant_id` sale del token (no de un query param).
    """
    # 🔒 SEGURIDAD: tenant_id del token JWT.
    tenant_id = current_user["tenant_id"]
    hoy = hoy_santiago()

    # GROUP BY tipo: una fila por tipo (máximo 2) en vez de traer todos los movimientos
    # del día solo para sumarlos en Python.
    filas = db.execute(sql_text("""
        SELECT tipo, COALESCE(SUM(monto), 0) AS total, COUNT(*) AS cantidad
        FROM transacciones_financieras
        WHERE tenant_id = :tid AND fecha = :hoy
        GROUP BY tipo
    """), {"tid": tenant_id, "hoy": hoy}).fetchall()

    resumen = resumir_dia([(r.tipo, r.total, r.cantidad) for r in filas])
    return {"fecha": str(hoy), **resumen}
