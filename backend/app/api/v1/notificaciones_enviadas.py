"""Endpoints para registrar y reenviar correos enviados (log de notificaciones)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from app.db.database import get_db
from app.models.notificacion_enviada import NotificacionEnviada
from app.models.usuario import Usuario
from app.core.dependencies import get_current_user, get_current_admin
from app.services.email_service import (
    enviar_email_bienvenida,
    enviar_email_vencimiento_plan,
    enviar_email_fidelizacion,
)

router = APIRouter()

TIPOS_VALIDOS = {"bienvenida", "vencimiento", "inactividad"}
ESTADOS_VALIDOS = {"enviado", "fallido"}


def _registrar(db: Session, alumno_id: int, tipo: str, estado: str, detalle_error: str = None):
    """Crea un registro en notificaciones_enviadas (tenant inferido del alumno)."""
    alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
    reg = NotificacionEnviada(
        alumno_id=alumno_id,
        tenant_id=alumno.tenant_id if alumno else None,
        tipo=tipo,
        estado=estado,
        detalle_error=detalle_error,
        fecha_envio=datetime.utcnow(),
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)
    return reg


@router.post("/registrar")
def registrar_notificacion(
    alumno_id: int,
    tipo: str,
    estado: str,
    detalle_error: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Registra un envío de correo realizado (SÓLO admin).

    ── FIX S6 (seguridad) ──
    Antes aceptaba a cualquier usuario autenticado y permitía forjar registros
    de correos "enviados". Verificado: nadie lo llama (email_service escribe
    directo en la BD; n8n no autentica con JWT de usuario). Se restringe a admin
    + alumno del mismo box en lugar de eliminarlo, por si alguna automatización
    externa depende del endpoint.
    """
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"tipo debe ser uno de {sorted(TIPOS_VALIDOS)}")
    if estado not in ESTADOS_VALIDOS:
        raise HTTPException(400, f"estado debe ser uno de {sorted(ESTADOS_VALIDOS)}")
    # S5: el alumno debe existir y pertenecer al box del admin.
    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == current_user["tenant_id"],
    ).first()
    if not alumno:
        raise HTTPException(404, "Alumno no encontrado en este box")
    reg = _registrar(db, alumno_id, tipo, estado, detalle_error)
    return {"id": reg.id, "alumno_id": reg.alumno_id, "tipo": reg.tipo,
            "estado": reg.estado, "fecha_envio": str(reg.fecha_envio)}


@router.get("")
def listar_notificaciones_enviadas(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tipo: str = None,
    estado: str = None,
    alumno_id: int = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Listado paginado con filtros (solo admin, tenant del token)."""
    # ── FIX S5 (seguridad): scoping por tenant del admin ──
    # La columna tenant_id se agrega por migración 011 (backfill desde usuarios).
    tenant_id = current_user["tenant_id"]
    q = db.query(NotificacionEnviada).filter(
        NotificacionEnviada.tenant_id == tenant_id)
    if tipo:
        q = q.filter(NotificacionEnviada.tipo == tipo)
    if estado:
        q = q.filter(NotificacionEnviada.estado == estado)
    if alumno_id:
        q = q.filter(NotificacionEnviada.alumno_id == alumno_id)
    total = q.count()
    rows = q.order_by(NotificacionEnviada.fecha_envio.desc()).offset(skip).limit(limit).all()
    result = []
    for r in rows:
        alumno = db.query(Usuario).filter(Usuario.id == r.alumno_id).first()
        result.append({
            "id": r.id,
            "alumno_id": r.alumno_id,
            "alumno_nombre": alumno.nombre if alumno else f"Alumno #{r.alumno_id}",
            "tipo": r.tipo,
            "fecha_envio": str(r.fecha_envio),
            "estado": r.estado,
            "detalle_error": r.detalle_error,
        })
    return {"total": total, "items": result, "skip": skip, "limit": limit}


@router.post("/enviar-manual")
def enviar_manual(
    alumno_id: int,
    tipo: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Envía correo manual (riesgo→inactividad, vencimiento→vencimiento plan) y registra."""
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"tipo debe ser uno de {sorted(TIPOS_VALIDOS)}")
    # S5: el alumno debe pertenecer al box del admin (evita enviar correos
    # manuales a alumnos de otro tenant).
    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == current_user["tenant_id"],
    ).first()
    if not alumno:
        raise HTTPException(404, "Alumno no encontrado en este box")
    alumno_dict = {"nombre": alumno.nombre, "correo": alumno.correo, "id": alumno.id, "plan_nombre": "plan"}
    exito = False
    try:
        if tipo == "inactividad":
            exito = enviar_email_fidelizacion(alumno.nombre, alumno.correo, 7)
        elif tipo == "vencimiento":
            from app.models.suscripcion import Suscripcion
            sus = db.query(Suscripcion).filter(
                Suscripcion.usuario_id == alumno.id,
                Suscripcion.estado == "activo",
            ).order_by(Suscripcion.fecha_expiracion.desc()).first()
            fecha = sus.fecha_expiracion if sus else None
            exito = enviar_email_vencimiento_plan(alumno_dict, fecha)
        else:
            raise HTTPException(400, f"tipo no soportado para envio manual: {tipo}")
    except Exception as e:
        exito = False
        detalle = str(e)
        _registrar(db, alumno_id, tipo, "fallido", detalle)
        return {"exito": False, "estado": "fallido", "detalle_error": detalle}
    detalle_fallo = None
    if not exito:
        # Gmail SMTP ya no usa Resend: exponer el error SMTP real si existe
        try:
            from app.services import email_service
            detalle_fallo = email_service.ULTIMO_ERROR_SMTP or "No se pudo enviar el correo via Gmail SMTP (revisar credenciales o destinatario)."
        except Exception:
            detalle_fallo = "No se pudo enviar el correo via Gmail SMTP (revisar credenciales o destinatario)."
    _registrar(db, alumno_id, tipo, "enviado" if exito else "fallido",
               None if exito else detalle_fallo)
    return {"exito": exito, "estado": "enviado" if exito else "fallido",
            "detalle_error": None if exito else detalle_fallo}


@router.post("/{notif_id}/reenviar")
def reenviar_notificacion(
    notif_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Reenvía un correo según el tipo registrado y actualiza estado (solo admin)."""
    # S5: el registro y su alumno deben pertenecer al box del admin.
    reg = db.query(NotificacionEnviada).filter(
        NotificacionEnviada.id == notif_id,
        NotificacionEnviada.tenant_id == current_user["tenant_id"],
    ).first()
    if not reg:
        raise HTTPException(404, "Registro no encontrado")

    alumno = db.query(Usuario).filter(
        Usuario.id == reg.alumno_id,
        Usuario.tenant_id == current_user["tenant_id"],
    ).first()
    if not alumno:
        raise HTTPException(404, "Alumno no encontrado en este box")

    alumno_dict = {"nombre": alumno.nombre, "correo": alumno.correo, "plan_nombre": "plan"}
    exito = False
    try:
        if reg.tipo == "bienvenida":
            exito = enviar_email_bienvenida(alumno_dict, token_onboarding="")
        elif reg.tipo == "vencimiento":
            from app.models.suscripcion import Suscripcion
            sus = db.query(Suscripcion).filter(
                Suscripcion.usuario_id == alumno.id,
                Suscripcion.estado == "activo",
            ).order_by(Suscripcion.fecha_expiracion.desc()).first()
            fecha = sus.fecha_expiracion if sus else None
            alumno_dict["plan_nombre"] = getattr(sus, "plan_id", "plan") if sus else "plan"
            exito = enviar_email_vencimiento_plan(alumno_dict, fecha)
        elif reg.tipo == "inactividad":
            exito = enviar_email_fidelizacion(alumno.nombre, alumno.correo, 7)
        else:
            raise HTTPException(400, f"tipo no soportado: {reg.tipo}")
    except Exception as e:
        exito = False
        reg.detalle_error = str(e)

    reg.estado = "enviado" if exito else "fallido"
    reg.fecha_envio = datetime.utcnow()
    db.commit()
    db.refresh(reg)
    return {"id": reg.id, "estado": reg.estado, "fecha_envio": str(reg.fecha_envio)}