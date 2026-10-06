"""Servicio de alertas de email automáticas (renovación, inactividad, urgencia).

Usado por el scheduler (jobs diarios) y por endpoints admin de disparo manual.
Deduplicación: cada envío se marca en `notificaciones_enviadas` para no repetirlo.

── EL "HOY" DE UN PLAN ES EL DE CHILE (fix 2026-09-29) ────────────────────────
Un plan vale hasta las 23:59:59 del último día, hora de Chile: el día de `fecha_expiracion`
está vigente COMPLETO (el 30/09 un plan de septiembre sigue vigente; recién desde las 00:00
del 01/10 está vencido). Por eso acá NO se usa:
  * `date.today()` — la TZ del proceso, no la de Chile;
  * `fecha_expiracion::date` — la TZ de la sesión de Postgres (UTC en Neon), que entre las
    21:00 y las 23:59 CLT ya es mañana;
  * `fecha_expiracion > now()` — corta el último día a las 20:59 CLT.
El día se cuenta con `hoy_santiago()` y, en el SQL, con `sql_fecha_en_chile()`.
"""
import calendar
from app.core.urls import url_frontend  # B.2
import logging
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.estados import sql_fecha_en_chile, vigente_hoy
from app.utils.santiago import hoy_santiago

logger = logging.getLogger("uvicorn.email")

# CTA "Renovar mi plan" → solicitud de plan del alumno (mismo patrón que las
# demás URLs de correos: settings.FRONTEND_URL, nunca dominios hardcodeados).
LINK_RENOVAR = url_frontend("/alumno/solicitar-plan")


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


def _marcar_enviado(db, alumno_id: int, tipo: str, tenant_id: int = None):
    """Registra el envío en `notificaciones_enviadas` CON el tenant del alumno.

    Antes insertaba sin `tenant_id`, así que esas filas quedaban invisibles para
    GET /notificaciones-enviadas, que filtra por el tenant del token del admin
    (medido: 33/35 de inactividad, 3/3 de renovacion_plan y 1/1 de
    vencimiento_inminente quedaron con tenant_id NULL).

    Mismo patrón que `email_service._registrar_envio`: el llamador puede pasar
    `tenant_id` (lo tiene, porque filtra por tenant) y si no, se resuelve desde
    el alumno.
    """
    from app.models.notificacion_enviada import NotificacionEnviada
    from app.models.usuario import Usuario
    if tenant_id is None and alumno_id:
        alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
        tenant_id = alumno.tenant_id if alumno else None
    db.add(NotificacionEnviada(
        alumno_id=alumno_id, tipo=tipo, estado="enviado",
        fecha_envio=datetime.utcnow(), tenant_id=tenant_id,
    ))


def enviar_alertas_renovacion(db, tenant_id: int = 1, dias_aviso: int = 3) -> dict:
    """EMAIL 3 (send_renovacion_plan): planes que vencen en `dias_aviso` días.

    El día objetivo es el DÍA CHILENO de vencimiento (hoy + `dias_aviso`, en hora de Chile), así
    que el aviso sale siempre `dias_aviso` días antes del último día del plan.
    """
    from sqlalchemy import text
    from app.services.email_service import send_renovacion_plan
    target = (hoy_santiago() + timedelta(days=dias_aviso)).isoformat()
    rows = db.execute(text(f"""
        SELECT u.id, u.nombre, u.correo, s.fecha_expiracion
        FROM suscripciones s
        JOIN usuarios u ON u.id = s.usuario_id
        WHERE s.tenant_id = :tid
          AND s.estado = 'activo'
          AND u.estado = 'activo'
          AND {sql_fecha_en_chile("s.fecha_expiracion")} = :target
    """), {"tid": tenant_id, "target": target}).fetchall()

    enviados, fallidos = [], []
    for r in rows:
        if _ya_enviado(db, r.id, "renovacion_plan", dias=2):
            continue
        fecha_es = _formatear_fecha_es(r.fecha_expiracion)
        ok = send_renovacion_plan(r.nombre, r.correo, fecha_es, LINK_RENOVAR)
        if ok:
            _marcar_enviado(db, r.id, "renovacion_plan", tenant_id=tenant_id)
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
          AND u.estado = 'activo'
    """), {"tid": tenant_id}).fetchall()

    limite = hoy_santiago() - timedelta(days=umbral_dias)
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
            _marcar_enviado(db, r.id, "inactividad", tenant_id=tenant_id)
            enviados.append(r.correo)
        else:
            fallidos.append(r.correo)
    db.commit()
    logger.info(f"[alertas] inactividad: {len(enviados)} enviados, {len(fallidos)} fallidos")
    return {"tipo": "inactividad", "enviados": len(enviados), "fallidos": len(fallidos),
            "detalle_enviados": enviados, "detalle_fallidos": fallidos}


def enviar_alertas_urgencia(db, tenant_id: int = 1) -> dict:
    """EMAIL 5 (send_alerta_urgencia_renovacion): planes cuyo ÚLTIMO DÍA es hoy (1 envío/día).

    ⚠️ El job corre a las 06:00 CLT: el plan que "vence HOY" sigue VIGENTE hasta las 23:59, así
    que el correo avisa de un vencimiento que todavía no ocurrió (antes el texto decía "tu plan
    ha expirado" con el plan vigente: el bug reportado del 30/09). El día objetivo es el día
    chileno de vencimiento, no el `date.today()` del proceso ni el `::date` de la sesión.
    """
    from sqlalchemy import text
    from app.services.email_service import send_alerta_urgencia_renovacion
    target = hoy_santiago().isoformat()
    rows = db.execute(text(f"""
        SELECT u.id, u.nombre, u.correo
        FROM suscripciones s
        JOIN usuarios u ON u.id = s.usuario_id
        WHERE s.tenant_id = :tid
          AND s.estado = 'activo'
          AND u.estado = 'activo'
          AND {sql_fecha_en_chile("s.fecha_expiracion")} = :target
    """), {"tid": tenant_id, "target": target}).fetchall()

    enviados, fallidos = [], []
    for r in rows:
        if _ya_enviado(db, r.id, "vencimiento_inminente", dias=1):
            continue
        ok = send_alerta_urgencia_renovacion(r.nombre, r.correo)
        if ok:
            _marcar_enviado(db, r.id, "vencimiento_inminente", tenant_id=tenant_id)
            enviados.append(r.correo)
        else:
            fallidos.append(r.correo)
    db.commit()
    logger.info(f"[alertas] urgencia: {len(enviados)} enviados, {len(fallidos)} fallidos")
    return {"tipo": "urgencia_renovacion", "enviados": len(enviados), "fallidos": len(fallidos),
            "detalle_enviados": enviados, "detalle_fallidos": fallidos}


# ═════════════════════════════════════════════════════════════════════════════
# ALERTAS DE CRÉDITOS (fidelización) — últimas 2
# ═════════════════════════════════════════════════════════════════════════════
def _dias_restantes_mes() -> int:
    """Días que faltan hasta el último día del mes actual (0 si hoy es el último).

    El mes es el de CHILE (`hoy_santiago()`): de noche, en UTC el mes ya puede ser otro.
    """
    hoy = hoy_santiago()
    ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
    return ultimo_dia - hoy.day


def enviar_alertas_ultimo_credito(db, tenant_id: int = 1) -> dict:
    """EMAIL (último crédito): alumnos con EXACTAMENTE 1 crédito y días restantes
    del mes > 0. Dedupe 7 días. Tipo registrado: 'ultimo_credito'."""
    from sqlalchemy import text
    from app.services.email_service import send_alerta_ultimo_credito

    dias_restantes = _dias_restantes_mes()
    if dias_restantes <= 0:
        return {"tipo": "ultimo_credito", "enviados": 0, "fallidos": 0,
                "detalle_enviados": [], "detalle_fallidos": [],
                "motivo": "Es el último día del mes (días_restantes=0)"}

    rows = db.execute(text(f"""
        SELECT DISTINCT ON (u.id) u.id, u.nombre, u.correo, s.creditos_disponibles
        FROM suscripciones s
        JOIN usuarios u ON u.id = s.usuario_id
        WHERE s.tenant_id = :tid
          AND s.estado = 'activo'
          AND u.estado = 'activo'
          AND u.rol = 'alumno'
          AND s.creditos_disponibles = 1
          AND {sql_fecha_en_chile("s.fecha_expiracion")} >= :hoy
        ORDER BY u.id
    """), {"tid": tenant_id, "hoy": hoy_santiago()}).fetchall()

    enviados, fallidos = [], []
    for r in rows:
        if _ya_enviado(db, r.id, "ultimo_credito", dias=7):
            continue
        ok = send_alerta_ultimo_credito(r.nombre, r.correo,
                                        r.creditos_disponibles, dias_restantes)
        if ok:
            _marcar_enviado(db, r.id, "ultimo_credito", tenant_id=tenant_id)
            enviados.append(r.correo)
        else:
            fallidos.append(r.correo)
    db.commit()
    logger.info(f"[alertas] ultimo_credito: {len(enviados)} enviados, {len(fallidos)} fallidos")
    return {"tipo": "ultimo_credito", "enviados": len(enviados), "fallidos": len(fallidos),
            "dias_restantes_mes": dias_restantes,
            "detalle_enviados": enviados, "detalle_fallidos": fallidos}


def enviar_alertas_sin_creditos(db, tenant_id: int = 1) -> dict:
    """EMAIL (sin créditos): alumnos con 0 créditos disponibles y suscripción
    activa. Dedupe 7 días. Tipo registrado: 'sin_creditos'."""
    from sqlalchemy import text
    from app.services.email_service import send_alerta_sin_creditos

    rows = db.execute(text(f"""
        SELECT DISTINCT ON (u.id) u.id, u.nombre, u.correo
        FROM suscripciones s
        JOIN usuarios u ON u.id = s.usuario_id
        WHERE s.tenant_id = :tid
          AND s.estado = 'activo'
          AND u.estado = 'activo'
          AND u.rol = 'alumno'
          AND s.creditos_disponibles = 0
          AND {sql_fecha_en_chile("s.fecha_expiracion")} >= :hoy
        ORDER BY u.id
    """), {"tid": tenant_id, "hoy": hoy_santiago()}).fetchall()

    enviados, fallidos = [], []
    for r in rows:
        if _ya_enviado(db, r.id, "sin_creditos", dias=7):
            continue
        ok = send_alerta_sin_creditos(r.nombre, r.correo)
        if ok:
            _marcar_enviado(db, r.id, "sin_creditos", tenant_id=tenant_id)
            enviados.append(r.correo)
        else:
            fallidos.append(r.correo)
    db.commit()
    logger.info(f"[alertas] sin_creditos: {len(enviados)} enviados, {len(fallidos)} fallidos")
    return {"tipo": "sin_creditos", "enviados": len(enviados), "fallidos": len(fallidos),
            "detalle_enviados": enviados, "detalle_fallidos": fallidos}
