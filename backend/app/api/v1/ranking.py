"""
Router del Ranking de Asistencia por Plan (pantalla TV pública, SIN login).

GET /api/v1/ranking/asistencia/{box_public_id}?mes=YYYY-MM
  - box_public_id: `tenants.public_id` (UUID v4) — identificador NO secuencial
    del box, apto para exponer en una URL sin autenticación.
  - mes: opcional, formato YYYY-MM. Default = mes cerrado más reciente
    (mes anterior a hoy en America/Santiago). NUNCA el mes en curso.
  - SIN JWT. Rate limit por IP (slowapi, mismo patrón que auth.py).
  - Si box_public_id no matchea ningún tenant → 404 genérico (no revelar si
    el ID "casi" existe).

NOTA n8n (fase de Dockerización, NO construir todavía): este endpoint queda
preparado para que n8n dispare un recálculo/cache-refresh con el mismo patrón
de /asistencia/n8n/evaluar-mes (header X-N8N-API-Key + secrets.compare_digest
+ settings.N8N_API_KEY). El punto exacto de enganche está marcado con
"# TODO(n8n) cache-refresh" en ranking_asistencia_service.construir_ranking.
"""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.db.database import get_db
from app.models.tenant import Tenant
from app.services.ranking_asistencia_service import (
    construir_ranking,
    mes_cerrado_por_defecto,
)

router = APIRouter()

# Formato estricto YYYY-MM (evita "2026-13", "2026-0", etc.)
MES_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@router.get("/asistencia/{box_public_id}")
@limiter.limit("30/minute")
def ranking_asistencia_publico(
    request: Request,
    box_public_id: str,
    mes: Optional[str] = Query(
        None,
        description="Mes a mostrar (YYYY-MM). Default: mes cerrado más reciente.",
    ),
    db: Session = Depends(get_db),
):
    """Ranking público de asistencia por plan de un box (pantalla TV, sin login).

    Solo expone datos agregados y nombres formateados con iniciales; NUNCA
    nombre completo ni datos de contacto.
    """
    tenant = db.query(Tenant).filter(Tenant.public_id == box_public_id).first()
    if not tenant:
        # 404 genérico: no revelar si el ID "casi" existe.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No encontrado",
        )

    if mes:
        if not MES_RE.match(mes):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="mes debe tener formato YYYY-MM (ej: 2026-07)",
            )
        anio, mes_num = int(mes[:4]), int(mes[5:7])
    else:
        anio, mes_num = mes_cerrado_por_defecto()

    data = construir_ranking(db, tenant.id, anio, mes_num)

    return {
        "box_public_id": box_public_id,
        "box_nombre": tenant.nombre,
        "mes": f"{anio}-{mes_num:02d}",
        **data,
    }
