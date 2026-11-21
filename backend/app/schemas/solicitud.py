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
    certificado_estudiante_url: Optional[str] = None


class ActivacionManualPlanRequest(BaseModel):
    """Body de `POST /api/v1/admin/planes/{plan_id}/activar-manual`.

    `motivo` es texto libre para el historial de la solicitud (queda en
    `comentario_admin`): deja por escrito por qué se activó sin el webhook
    (p. ej. "pagó por transferencia", "cobro MP aprobado, webhook no llegó").
    """

    alumno_id: int = Field(..., gt=0)
    motivo: Optional[str] = Field(default=None, max_length=200)
