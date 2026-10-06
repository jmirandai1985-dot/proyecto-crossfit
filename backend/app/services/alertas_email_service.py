"""Servicio de alertas de email automáticas (renovación, inactividad, urgencia).

Usado por el scheduler (jobs diarios) y por endpoints admin de disparo manual.

── UNA fila por envío, sin carrera entre réplicas ────────────────────────────
Cada alerta RECLAMA su envío ANTES de mandarlo con `_reclamar_envio`: inserta la fila
`enviado` con `dia_chile`=hoy y un índice único parcial (`alumno_id, tipo, dia_chile`)
hace que, si DOS réplicas corren el job el mismo día, sólo una obtenga el id y mande el
correo; la otra recibe `None` y se va. Si el correo no sale, `_marcar_fallido` deja la
fila como `fallido` (visible en /admin). El envío pasa `registrar=False` a
`email_service.send_*` para que NO se cree una segunda fila del mismo correo.

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
from datetime import timedelta

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
    """True si este alumno ya recibió ESTE tipo en los últimos `dias` (dedupe por ventana).

    Sólo cuenta `estado = 'enviado'`: una fila `fallido` (el correo NO salió) NO bloquea
    el reintento. El día se mide contra `now()` de Postgres (la columna es TIMESTAMPTZ).
    """
    from sqlalchemy import text
    fila = db.execute(text("""
        SELECT 1 FROM notificaciones_enviadas
         WHERE alumno_id = :alumno_id
           AND tipo = :tipo
           AND estado = 'enviado'
           AND fecha_envio >= now() - make_interval(days => :dias)
         LIMIT 1
    """), {"alumno_id": alumno_id, "tipo": tipo, "dias": dias}).first()
    return fila is not None


def _reclamar_envio(db, alumno_id: int, tipo: str, tenant_id: int = None):
    """Reclama ATÓMICAMENTE el envío de HOY para (alumno, tipo) y devuelve su id.

    Inserta la fila en estado `enviado` con `dia_chile` = hoy (Chile). El índice único
    parcial `uq_notif_alumno_tipo_dia (alumno_id, tipo, dia_chile)` hace que
    `INSERT ... ON CONFLICT DO NOTHING RETURNING id` devuelva el id SÓLO a la instancia
    que ganó la carrera: con DOS réplicas corriendo el mismo job el mismo día, una sola
    manda el correo (antes ambas veían `_ya_enviado()==False` y mandaban las dos).

    El `WHERE` del `ON CONFLICT` es el predicado EXACTO del índice parcial: sin él,
    Postgres no infiere el índice y el `ON CONFLICT` falla.

    Devuelve el id de la fila reclamada, o `None` si otra instancia ya la reclamó hoy.

    Como reclama ANTES de mandar, quien llama debe marcar `fallido` la fila si el correo
    no sale (`_marcar_fallido`); si no, quedaría una fila `enviado` que nunca salió.
    """
    from sqlalchemy import text
    fila = db.execute(text("""
        INSERT INTO notificaciones_enviadas
            (alumno_id, tenant_id, tipo, estado, fecha_envio, dia_chile)
        VALUES (:alumno_id, :tenant_id, :tipo, 'enviado', now(), :dia)
        ON CONFLICT (alumno_id, tipo, dia_chile)
            WHERE alumno_id IS NOT NULL AND dia_chile IS NOT NULL
            DO NOTHING
        RETURNING id
    """), {"alumno_id": alumno_id, "tenant_id": tenant_id, "tipo": tipo,
           "dia": hoy_santiago()})
    db.commit()
    return fila.scalar()


def _marcar_fallido(db, envio_id: int, error: str):
    """Marca `fallido` la fila reclamada (el correo NO salió) y guarda el motivo.

    Sin esto, la fila reclamada antes del envío quedaría como `enviado` aunque el correo
    nunca saliera: /admin/notificaciones mostraría un éxito falso. `error` se recorta a
    500 caracteres (la columna es TEXT, pero el motivo de SMTP no aporta más).
    """
    if not envio_id:
        return
    from sqlalchemy import text
    db.execute(text("""
        UPDATE notificaciones_enviadas
           SET estado = 'fallido', detalle_error = :err
         WHERE id = :id
    """), {"id": envio_id, "err": (error or "")[:500]})
    db.commit()


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
        envio_id = _reclamar_envio(db, r.id, "renovacion_plan", tenant_id=tenant_id)
        if envio_id is None:
            continue  # otra réplica ya lo reclamó hoy (índice único parcial)
        fecha_es = _formatear_fecha_es(r.fecha_expiracion)
        # registrar=False: la fila YA la escribió `_reclamar_envio`; que email_service
        # no inserte una SEGUNDA (antes eran 2 filas por envío, una con tenant NULL).
        ok = send_renovacion_plan(r.nombre, r.correo, fecha_es, LINK_RENOVAR,
                                  registrar=False)
        if ok:
            enviados.append(r.correo)
        else:
            _marcar_fallido(db, envio_id, f"renovacion_plan FALLIDO -> {r.correo}")
            fallidos.append(r.correo)
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
        envio_id = _reclamar_envio(db, r.id, "inactividad", tenant_id=tenant_id)
        if envio_id is None:
            continue  # otra réplica ya lo reclamó hoy
        ok = send_alerta_inactividad(r.nombre, r.correo, registrar=False)
        if ok:
            enviados.append(r.correo)
        else:
            _marcar_fallido(db, envio_id, f"inactividad FALLIDO -> {r.correo}")
            fallidos.append(r.correo)
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
        envio_id = _reclamar_envio(db, r.id, "vencimiento_inminente", tenant_id=tenant_id)
        if envio_id is None:
            continue  # otra réplica ya lo reclamó hoy
        ok = send_alerta_urgencia_renovacion(r.nombre, r.correo, registrar=False)
        if ok:
            enviados.append(r.correo)
        else:
            _marcar_fallido(db, envio_id, f"vencimiento_inminente FALLIDO -> {r.correo}")
            fallidos.append(r.correo)
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
        envio_id = _reclamar_envio(db, r.id, "ultimo_credito", tenant_id=tenant_id)
        if envio_id is None:
            continue  # otra réplica ya lo reclamó hoy
        ok = send_alerta_ultimo_credito(r.nombre, r.correo,
                                        r.creditos_disponibles, dias_restantes,
                                        registrar=False)
        if ok:
            enviados.append(r.correo)
        else:
            _marcar_fallido(db, envio_id, f"ultimo_credito FALLIDO -> {r.correo}")
            fallidos.append(r.correo)
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
        envio_id = _reclamar_envio(db, r.id, "sin_creditos", tenant_id=tenant_id)
        if envio_id is None:
            continue  # otra réplica ya lo reclamó hoy
        ok = send_alerta_sin_creditos(r.nombre, r.correo, registrar=False)
        if ok:
            enviados.append(r.correo)
        else:
            _marcar_fallido(db, envio_id, f"sin_creditos FALLIDO -> {r.correo}")
            fallidos.append(r.correo)
    logger.info(f"[alertas] sin_creditos: {len(enviados)} enviados, {len(fallidos)} fallidos")
    return {"tipo": "sin_creditos", "enviados": len(enviados), "fallidos": len(fallidos),
            "detalle_enviados": enviados, "detalle_fallidos": fallidos}
