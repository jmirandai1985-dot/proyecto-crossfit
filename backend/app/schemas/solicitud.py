"""
Schema para Solicitud de Plan
"""
from pydantic import BaseModel, Field
from typing import Optional


class SolicitudPlanCreate(BaseModel):
    tenant_id: int = Field(..., gt=0)
    alumno_id: int = Field(..., gt=0)
    plan_id: int = Field(..., gt=0)
    voucher_url: Optional[str] = None
