from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from app.db.database import get_db
from app.models.suscripcion import Suscripcion
from app.models.transaccion_financiera import TransaccionFinanciera
from app.core.dependencies import get_current_admin
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.services.auditoria_service import registrar_auditoria

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
@limiter.limit(LIMIT_CRITICO)
def crear_suscripcion(
    request: Request,
    data: SuscripcionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (el body se ignora).
    data.tenant_id = current_user["tenant_id"]
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

    # ── FIX P3b (consistencia con aprobar_solicitud): al crear una membresía
    # paga, expirar la suscripción "Prueba" activa del alumno (estado='vencido')
    # para que el gate de modo prueba se desbloquee (es_usuario_prueba → False).
    # Mismo criterio que solicitudes_planes (FIX 3). No aplica si el plan nuevo
    # es "Prueba". Nunca debe impedir la creación si falla.
    try:
        from app.models.plan import Plan
        plan_nuevo = db.query(Plan).filter(Plan.id == data.plan_id).first()
        if plan_nuevo and plan_nuevo.nombre != "Prueba":
            sus_prueba = db.query(Suscripcion).join(
                Plan, Suscripcion.plan_id == Plan.id
            ).filter(
                Suscripcion.usuario_id == data.usuario_id,
                Suscripcion.estado == "activo",
                Plan.nombre == "Prueba",
            ).all()
            for sp in sus_prueba:
                sp.estado = "vencido"
            db.commit()
    except Exception as e:
        import logging
        logging.getLogger("uvicorn").warning(f"No se pudo expirar suscripcion Prueba: {e}")

    # ── Auditoría interna: alta de suscripción (ajuste de tokens) ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="CREATE",
        entidad="suscripcion",
        entidad_id=db_sus.id,
        detalle={
            "usuario_id": data.usuario_id,
            "plan_id": data.plan_id,
            "estado": data.estado,
            "creditos_totales": data.creditos_totales,
            "creditos_disponibles": data.creditos_disponibles,
        },
    )

    # Auto-insertar ingreso en transacciones_financieras
    try:
        from datetime import date
        from app.models.plan import Plan
        plan = db.query(Plan).filter(Plan.id == data.plan_id).first()
        if plan and plan.precio_clp > 0:
            tx = TransaccionFinanciera(
                tenant_id=data.tenant_id,
                tipo='ingreso',
                categoria='membresia',
                monto=plan.precio_clp,
                descripcion=f"Suscripcion plan {plan.nombre} (usuario #{data.usuario_id})",
                referencia_tipo='suscripcion',
                referencia_id=db_sus.id,
                fecha=date.today(),
            )
            db.add(tx)
            db.commit()
    except Exception as e:
        # No debe impedir la creacion de la suscripcion si falla la transaccion
        import logging
        logging.getLogger("uvicorn").warning(
            f"No se pudo registrar transaccion financiera: {e}")

    return db_sus


@router.get("/suscripciones")
def listar_suscripciones(
    tenant_id: Optional[int] = Query(None),
    usuario_id: Optional[int] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    query = db.query(Suscripcion).filter(Suscripcion.tenant_id == tenant_id)
    if usuario_id:
        query = query.filter(Suscripcion.usuario_id == usuario_id)
    if estado:
        query = query.filter(Suscripcion.estado == estado)
    return query.order_by(Suscripcion.created_at.desc()).all()
