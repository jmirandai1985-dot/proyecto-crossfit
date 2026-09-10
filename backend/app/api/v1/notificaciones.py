"""
Router de Notificaciones para alumnos
"""
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.db.database import get_db
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario
from app.core.dependencies import get_current_admin, get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.services.asistencia_service import verificar_token_optout

router = APIRouter()


@router.get("")
def listar_notificaciones(
    alumno_id: Optional[int] = Query(None),
    solo_no_leidas: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Devuelve las notificaciones del alumno autenticado.
    Si solo_no_leidas=True, filtra solo las no leídas.

    🔒 SEGURIDAD: alumno_id se deriva del JWT. Si el cliente envía un
    alumno_id ajeno sin ser coach/admin del box → 403 explícito.
    """
    rol = current_user.get("rol", "")
    if alumno_id is not None:
        if rol in ("coach", "admin", "administrador"):
            # Staff: puede listar notificaciones de cualquier alumno del box
            pass
        elif alumno_id != current_user["usuario_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes ver las notificaciones de otro alumno",
            )
    else:
        alumno_id = current_user["usuario_id"]

    query = db.query(Notificacion).filter(
        Notificacion.alumno_id == alumno_id
    )
    if solo_no_leidas:
        query = query.filter(Notificacion.leida == False)

    notificaciones = query.order_by(
        Notificacion.created_at.desc()
    ).limit(50).all()

    return [
        {
            "id": n.id,
            "alumno_id": n.alumno_id,
            "tipo": n.tipo,
            "mensaje": n.mensaje,
            "leida": n.leida,
            "created_at": n.created_at,
        }
        for n in notificaciones
    ]


@router.put("/{notificacion_id}/leer")
def marcar_como_leida(
    notificacion_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Marca una notificación como leída (solo el dueño)"""
    notif = db.query(Notificacion).filter(
        Notificacion.id == notificacion_id).first()
    if not notif:
        raise HTTPException(
            status_code=404, detail="Notificación no encontrada")

    # 🔒 IDOR: solo el dueño puede marcarla.
    if notif.alumno_id != current_user["usuario_id"]:
        raise HTTPException(
            status_code=403, detail="No puedes marcar notificaciones de otro alumno")

    notif.leida = True
    db.commit()
    return {"status": "ok", "message": "Notificación marcada como leída"}


@router.put("/leer-todas")
def marcar_todas_como_leidas(
    alumno_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Marca todas las notificaciones del alumno autenticado como leídas"""
    # 🔒 SEGURIDAD: alumno_id del token; el query param se ignora.
    alumno_id = current_user["usuario_id"]
    db.query(Notificacion).filter(
        Notificacion.alumno_id == alumno_id,
        Notificacion.leida == False
    ).update({"leida": True})
    db.commit()
    return {"status": "ok", "message": "Todas las notificaciones marcadas como leídas"}


# ═══════════════════════════════════════════════════════════════════════
# ALERTAS AUTOMÁTICAS DE EMAIL — disparo manual (admin)
# Misma lógica que los jobs del scheduler, para probar/forzar sin esperar la hora.
# ═══════════════════════════════════════════════════════════════════════

@router.post("/enviar-alertas-vencimiento")
def disparar_alertas_vencimiento(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Email 3 - Planes que vencen en 3 días (send_renovacion_plan)."""
    from app.services.alertas_email_service import enviar_alertas_renovacion
    return enviar_alertas_renovacion(db)


@router.post("/enviar-alertas-inactividad")
def disparar_alertas_inactividad(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Email 4 - Alumnos con 7+ días sin asistencia (send_alerta_inactividad)."""
    from app.services.alertas_email_service import enviar_alertas_inactividad
    return enviar_alertas_inactividad(db)


@router.post("/enviar-alertas-urgencia")
def disparar_alertas_urgencia(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Email 5 - Planes que vencen HOY (send_alerta_urgencia_renovacion)."""
    from app.services.alertas_email_service import enviar_alertas_urgencia
    return enviar_alertas_urgencia(db)


@router.post("/enviar-alertas-ultimo-credito")
def disparar_alertas_ultimo_credito(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Alerta de ÚLTIMO crédito: alumnos con 1 crédito y días restantes del mes."""
    from app.services.alertas_email_service import enviar_alertas_ultimo_credito
    return enviar_alertas_ultimo_credito(db)


@router.post("/enviar-alertas-sin-creditos")
def disparar_alertas_sin_creditos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Alerta de SIN créditos: alumnos con 0 créditos y suscripción activa."""
    from app.services.alertas_email_service import enviar_alertas_sin_creditos
    return enviar_alertas_sin_creditos(db)


# ═════════════════════════════════════════════════════════════════════════════
# OPT-OUT de reactivación (endpoint PÚBLICO, sin JWT)
#   GET /api/v1/notificaciones/reactivacion/optout?token=<token>
# Token HMAC-SHA256 stateless (payload 'alumno_id:reactivacion'), verificado con
# secrets.compare_digest (patrón del proyecto). Responde HTML simple de
# confirmación — no requiere frontend ni login.
# ═════════════════════════════════════════════════════════════════════════════
def _html_optout(ok: bool) -> str:
    if ok:
        titulo, texto = "Preferencia registrada ✅", (
            "Dejaste de recibir los correos de reactivación. "
            "Podés volver a recibirlos hablando con tu coach en el box.")
    else:
        titulo, texto = "Link inválido o expirado ❌", (
            "El link que usaste no es válido. Si sigue pasando, "
            "escribinos y lo resolvemos.")
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f4f4f5;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:480px;margin:40px auto;background:#ffffff;border-radius:12px;padding:32px;text-align:center;border:1px solid #e4e4e7;">
  <h1 style="font-size:20px;color:#09090b;margin:0 0 12px;">{titulo}</h1>
  <p style="color:#3f3f46;font-size:14px;line-height:1.6;margin:0;">{texto}</p>
  <p style="color:#71717a;font-size:11px;margin:24px 0 0;">Urban Training Box</p>
</div>
</body></html>"""


@router.get("/reactivacion/optout")
@limiter.limit(LIMIT_CRITICO)
def reactivacion_optout(
    request: Request,
    token: str = Query(..., description="Token HMAC firmado (alumno_id:reactivacion)"),
    db: Session = Depends(get_db),
):
    """Desuscribe al alumno de los correos de reactivación (sin login).

    Idempotente: si se reutiliza el mismo token (o ya estaba dado de baja), solo
    vuelve a confirmar — no rompe ni duplica nada (flag booleano).
    """
    alumno_id = verificar_token_optout(token)
    if alumno_id is None:
        return HTMLResponse(_html_optout(ok=False),
                            status_code=status.HTTP_400_BAD_REQUEST)
    alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
    if not alumno:
        return HTMLResponse(_html_optout(ok=False),
                            status_code=status.HTTP_404_NOT_FOUND)
    alumno.acepta_correo_reactivacion = False
    db.commit()
    return HTMLResponse(_html_optout(ok=True))


# ═════════════════════════════════════════════════════════════════════════════
# ALERTAS AUTOMÁTICAS — disparo n8n (header X-N8N-API-Key, SIN JWT)
# Misma lógica que los endpoints admin y los jobs del scheduler, pero pensado
# para que n8n las dispare con una API key estática (los JWT expiran).
# Los endpoints admin /enviar-alertas-* (Bearer JWT) siguen intactos.
# ═════════════════════════════════════════════════════════════════════════════
def _verificar_api_key_n8n(
    x_n8n_api_key: str = Header(default="", alias="X-N8N-API-Key"),
):
    """Dependencia n8n: valida `X-N8N-API-Key` contra settings.N8N_API_KEY."""
    esperada = settings.N8N_API_KEY
    if not esperada or not secrets.compare_digest(esperada, x_n8n_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida para el endpoint de n8n",
        )
    return True


@router.post("/n8n/enviar-alertas-urgencia")
def n8n_enviar_alertas_urgencia(
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """n8n — planes que vencen HOY (send_alerta_urgencia_renovacion)."""
    from app.services.alertas_email_service import enviar_alertas_urgencia
    return {"status": "ok", "resultado": enviar_alertas_urgencia(db, tenant_id=1)}


@router.post("/n8n/enviar-alertas-renovacion")
def n8n_enviar_alertas_renovacion(
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """n8n — planes que vencen en 3 días (send_renovacion_plan)."""
    from app.services.alertas_email_service import enviar_alertas_renovacion
    return {"status": "ok", "resultado": enviar_alertas_renovacion(db, tenant_id=1)}


@router.post("/n8n/enviar-alertas-inactividad")
def n8n_enviar_alertas_inactividad(
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """n8n — 7+ días sin asistencia (send_alerta_inactividad)."""
    from app.services.alertas_email_service import enviar_alertas_inactividad
    return {"status": "ok", "resultado": enviar_alertas_inactividad(db, tenant_id=1)}


@router.post("/n8n/enviar-alertas-ultimo-credito")
def n8n_enviar_alertas_ultimo_credito(
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """n8n — 1 crédito y días restantes del mes (send_alerta_ultimo_credito)."""
    from app.services.alertas_email_service import enviar_alertas_ultimo_credito
    return {"status": "ok", "resultado": enviar_alertas_ultimo_credito(db, tenant_id=1)}


@router.post("/n8n/enviar-alertas-sin-creditos")
def n8n_enviar_alertas_sin_creditos(
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """n8n — 0 créditos disponibles (send_alerta_sin_creditos)."""
    from app.services.alertas_email_service import enviar_alertas_sin_creditos
    return {"status": "ok", "resultado": enviar_alertas_sin_creditos(db, tenant_id=1)}
