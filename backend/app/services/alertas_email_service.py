"""Servicio de alertas de email automáticas (renovación, inactividad, urgencia).

Usado por el scheduler (jobs diarios) y por endpoints admin de disparo manual.
Deduplicación: cada envío se marca en `notificaciones_enviadas` para no repetirlo.
"""
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger("uvicorn.email")

LINK_RENOVAR = "https://app.urbantrainingbox.cl/planes"


def _formatear_fecha_es(fecha) -> str:
    from app.services.email_service import formatear_fecha_es
    return formatear_fecha_es(fecha)


def _ya_enviado(db, alumno_id: int, tipo: str, dias: int = 7) -> bool:
    """True si ya existe un registro del envío en los últimos N días (dedupe)."""
    from app.models.notificacion_enviada import NotificacionEnviada
    desde = datetime.utcnow() - timedelta(days=dias)
    return db.query(NotificacionEnviada).filter(
        NotificacionEnviada.alumno_id == alumno_id,
        NotificacionEnviada.tipo == tipo,
        NotificacionEnviada.fecha_envio >= desde,
    ).first() is not None


def _marcar_enviado(db, alumno_id: int, tipo: str):
    from app.models.notificacion_enviada import NotificacionEnviada
    db.add(NotificacionEnviada(
        alumno_id=alumno_id, tipo=tipo, estado="enviado",
        fecha_envio=datetime.utcnow(),
    ))


def enviar_alertas_renovacion(db, tenant_id: int = 1, dias_aviso: int = 3) -> dict:
    """EMAIL 3 (send_renovacion_plan): planes activos que vencen en `dias_aviso` días."""
    from sqlalchemy import text
    from app.services.email_service import send_renovacion_plan
    target = (date.today() + timedelta(days=dias_aviso)).isoformat()
    rows = db.execute(text("""
        SELECT u.id, u.nombre, u.correo, s.fecha_expiracion
        FROM suscripciones s
        JOIN usuarios u ON u.id = s.usuario_id
        WHERE s.tenant_id = :tid
          AND s.estado = 'activo'
          AND u.activo = true
          AND s.fecha_expiracion::date = :target
    """), {"tid": tenant_id, "target": target}).fetchall()

    enviados, fallidos = [], []
    for r in rows:
        if _ya_enviado(db, r.id, "renovacion_plan", dias=2):
            continue
        fecha_es = _formatear_fecha_es(r.fecha_expiracion)
        ok = send_renovacion_plan(r.nombre, r.correo, fecha_es, LINK_RENOVAR)
        if ok:
            _marcar_enviado(db, r.id, "renovacion_plan")
            enviados.append(r.correo)
        else:
            fallidos.append(r.correo)
    db.commit()
    logger.info(f"[alertas] renovación: {len(enviados)} enviados, {len(fallidos)} fallidos")
    return {"tipo": "renovacion", "enviados": len(enviados), "fallidos": len(fallidos),
            "detalle_enviados": enviados, "detalle_fallidos": fallidos}


def enviar_alertas_inactividad(db, tenant_id: int = 1, umbral_dias: int = 7) -> dict:
    """EMAIL 4 (send_alerta_inactividad): alumnos con 7+ días sin asistencia (1 envío/7 días)."""
    from sqlalchemy import text
    from app.services.email_service import send_alerta_inactividad
    rows = db.execute(text("""
        SELECT u.id, u.nombre, u.correo,
               (SELECT MAX(a.fecha) FROM asistencias a WHERE a.usuario_id = u.id) AS ultima
        FROM usuarios u
        WHERE u.tenant_id = :tid
          AND u.rol = 'alumno'
          AND u.activo = true
          AND u.estado = 'activo'
    """), {"tid": tenant_id}).fetchall()

    limite = date.today() - timedelta(days=umbral_dias)
    enviados, fallidos = [], []
    for r in rows:
        ultima = r.ultima
        if ultima is None:
            continue  # sin asistencia registrada → no aplica alerta aún
        if ultima > limite:
            continue  # asistió dentro del umbral → no está inactivo
        if _ya_enviado(db, r.id, "inactividad", dias=umbral_dias):
            continue
        ok = send_alerta_inactividad(r.nombre, r.correo)
        if ok:
            _marcar_enviado(db, r.id, "inactividad")
            enviados.append(r.correo)
        else:
            fallidos.append(r.correo)
    db.commit()
    logger.info(f"[alertas] inactividad: {len(enviados)} enviados, {len(fallidos)} fallidos")
    return {"tipo": "inactividad", "enviados": len(enviados), "fallidos": len(fallidos),
            "detalle_enviados": enviados, "detalle_fallidos": fallidos}


def enviar_alertas_urgencia(db, tenant_id: int = 1) -> dict:
    """EMAIL 5 (send_alerta_urgencia_renovacion): planes activos que vencen HOY (1 envío/día)."""
    from sqlalchemy import text
    from app.services.email_service import send_alerta_urgencia_renovacion
    target = date.today().isoformat()
    rows = db.execute(text("""
        SELECT u.id, u.nombre, u.correo
        FROM suscripciones s
        JOIN usuarios u ON u.id = s.usuario_id
        WHERE s.tenant_id = :tid
          AND s.estado = 'activo'
          AND u.activo = true
          AND s.fecha_expiracion::date = :target
    """), {"tid": tenant_id, "target": target}).fetchall()

    enviados, fallidos = [], []
    for r in rows:
        if _ya_enviado(db, r.id, "vencimiento_inminente", dias=1):
            continue
        ok = send_alerta_urgencia_renovacion(r.nombre, r.correo)
        if ok:
            _marcar_enviado(db, r.id, "vencimiento_inminente")
            enviados.append(r.correo)
        else:
            fallidos.append(r.correo)
    db.commit()
    logger.info(f"[alertas] urgencia: {len(enviados)} enviados, {len(fallidos)} fallidos")
    return {"tipo": "urgencia_renovacion", "enviados": len(enviados), "fallidos": len(fallidos),
            "detalle_enviados": enviados, "detalle_fallidos": fallidos}
