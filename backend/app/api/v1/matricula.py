"""Matrícula configurable del box (cobro único al alumno nuevo).

    GET /api/v1/matricula          — admin: config + contador de cobros
    PUT /api/v1/matricula          — admin: activa/desactiva y fija el monto
    GET /api/v1/matricula/mi-estado — cualquier logueado: ¿a MÍ me toca pagarla?

🔒 El `tenant_id` sale SIEMPRE del token (el query se ignora), igual que
`/configuracion`: es plata del box, no un parámetro del cliente.

El cobro lo aplica el backend en los tres flujos de venta
(`services/pagos.crear_pago_membresia`, `api/v1/solicitudes_planes`,
`services/suscripciones_mp`); acá sólo se administra la configuración y se le
cuenta al alumno lo que va a pagar.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin, get_current_user
from app.core.rate_limit import LIMIT_CONFIG_LECTURA, LIMIT_CRITICO, limiter
from app.db.database import get_db
from app.models.tenant import Tenant
from app.services import matricula_service
from app.services.auditoria_service import registrar_auditoria
from app.utils.db_commit import commit_o_4xx
from app.utils.santiago import ahora_santiago

router = APIRouter()


class MatriculaUpdate(BaseModel):
    """Cuerpo del PUT: interruptor + monto fijo del box.

    `ge=0`/`le=10_000_000`: el CHECK de la BD también protege el número, pero un
    monto absurdo se rechaza acá (422) antes de llegar a la base.
    """

    activa: bool
    monto_clp: Optional[int] = Field(None, ge=0, le=10_000_000)

    model_config = ConfigDict(extra="forbid")


def _respuesta(db: Session, tenant_id: int) -> dict:
    cfg = matricula_service.config(db, tenant_id)
    return {
        "activa": cfg["activa"],
        "monto_clp": cfg["monto_clp"],
        "activada_en": (cfg["activada_en"].isoformat()
                        if cfg["activada_en"] else None),
        "alumnos_cobrados": matricula_service.alumnos_cobrados(db, tenant_id),
    }


@router.get("")
@limiter.limit(LIMIT_CONFIG_LECTURA)
def obtener_matricula(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Configuración de la matrícula + cuántas se cobraron (panel de Planes)."""
    return _respuesta(db, current_user["tenant_id"])


@router.put("")
@limiter.limit(LIMIT_CRITICO)
def actualizar_matricula(
    request: Request,
    data: MatriculaUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Activa/desactiva la matrícula y guarda el monto.

    * activarla exige un monto > 0 (una matrícula de $0 no es un cobro);
    * `matricula_activada_en` se escribe al ENCENDERLA y no se borra al apagarla:
      es el "Activa desde el X" del panel;
    * al apagarla el monto se conserva (volver a encenderla parte del último).
    """
    tenant_id = current_user["tenant_id"]
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Tenant no encontrado")

    antes = {"activa": bool(tenant.matricula_activa),
             "monto_clp": tenant.matricula_monto_clp}

    if data.activa:
        if data.monto_clp is None or data.monto_clp <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Para activar la matrícula define un monto mayor a 0.")
        if not tenant.matricula_activa:
            tenant.matricula_activada_en = ahora_santiago()
        tenant.matricula_activa = True
        tenant.matricula_monto_clp = data.monto_clp
    else:
        tenant.matricula_activa = False
        if data.monto_clp is not None:
            tenant.matricula_monto_clp = data.monto_clp

    commit_o_4xx(
        db,
        "No se pudo guardar la matrícula: revisa el monto.",
        contexto="actualizar_matricula",
    )
    db.refresh(tenant)

    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="tenant",
        entidad_id=tenant_id,
        detalle={
            "antes": antes,
            "despues": {"activa": bool(tenant.matricula_activa),
                        "monto_clp": tenant.matricula_monto_clp},
        },
    )
    return _respuesta(db, tenant_id)


@router.get("/mi-estado")
@limiter.limit(LIMIT_CONFIG_LECTURA)
def mi_matricula(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lo que el ALUMNO necesita para el resumen de pago.

    `aplica` ya junta las dos condiciones (matrícula vigente + alumno nuevo) con
    la MISMA función que usan los flujos de venta: la pantalla no recalcula nada.
    Staff (`admin`/`coach`) siempre recibe `aplica=False`: la matrícula es del
    alumno, y así el endpoint no depende de qué rol abrió la pantalla.
    """
    tenant_id = current_user["tenant_id"]
    alumno_id = current_user["usuario_id"]
    cfg = matricula_service.config(db, tenant_id)
    rol = str(current_user.get("rol") or "")
    monto = (matricula_service.monto_para_alumno(db, tenant_id, alumno_id)
             if rol == "alumno" else None)
    return {
        "activa": cfg["activa"],
        "monto_clp": cfg["monto_clp"],
        "aplica": monto is not None,
        "monto_a_cobrar": monto,
    }
