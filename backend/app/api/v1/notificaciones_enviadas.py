"""Endpoints para registrar y reenviar correos enviados (log de notificaciones)."""
import hashlib
from app.core.urls import url_frontend  # B.2
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
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
    # Base con los filtros "de contenido" (tenant + tipo + alumno). El resumen
    # por estado se calcula sobre ESTA base (ignora el filtro `estado`): si no,
    # al filtrar por fallidos la tarjeta de enviados quedaria en 0.
    base = db.query(NotificacionEnviada).filter(
        NotificacionEnviada.tenant_id == tenant_id)
    if tipo:
        base = base.filter(NotificacionEnviada.tipo == tipo)
    if alumno_id:
        base = base.filter(NotificacionEnviada.alumno_id == alumno_id)

    resumen = {
        "enviado": base.filter(NotificacionEnviada.estado == "enviado").count(),
        "fallido": base.filter(NotificacionEnviada.estado == "fallido").count(),
    }

    q = base
    if estado:
        q = q.filter(NotificacionEnviada.estado == estado)
    total = q.count()
    rows = q.order_by(NotificacionEnviada.fecha_envio.desc()).offset(skip).limit(limit).all()
    result = []
    for r in rows:
        alumno = (db.query(Usuario).filter(Usuario.id == r.alumno_id).first()
                  if r.alumno_id else None)
        # FIX cobertura: hay filas cuyo destinatario es el admin del box o un lead
        # (alumno_id NULL). Se muestra el destinatario real en vez de "Alumno #None".
        if alumno:
            nombre = alumno.nombre
        elif r.destinatario_nombre or r.destinatario_correo:
            nombre = r.destinatario_nombre or r.destinatario_correo
        elif r.alumno_id:
            nombre = f"Alumno #{r.alumno_id}"
        else:
            nombre = "(sin destinatario)"
        result.append({
            "id": r.id,
            "alumno_id": r.alumno_id,
            "alumno_nombre": nombre,
            "destinatario_correo": r.destinatario_correo,
            "destinatario_nombre": r.destinatario_nombre,
            "destinatario_rol": r.destinatario_rol,
            "tipo": r.tipo,
            "fecha_envio": str(r.fecha_envio),
            "estado": r.estado,
            "detalle_error": r.detalle_error,
        })
    return {"total": total, "items": result, "skip": skip, "limit": limit,
            "resumen": resumen}


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
            # Días REALES de inactividad (antes: 7 fijo, mentía en el correo).
            # Mismo criterio que el resto del proyecto: última asistencia y, si
            # nunca asistió, la fecha de alta. Mínimo 1 para no decir "0 días".
            from app.models.asistencia import Asistencia
            ultima = db.query(func.max(Asistencia.fecha)).filter(
                Asistencia.tenant_id == alumno.tenant_id,
                Asistencia.usuario_id == alumno.id,
            ).scalar()
            referencia = ultima or (
                alumno.created_at.date() if alumno.created_at else None)
            dias = max(1, (date.today() - referencia).days) if referencia else 1
            exito = enviar_email_fidelizacion(alumno.nombre, alumno.correo, dias)
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


# ═════════════════════════════════════════════════════════════════════════════
# Reenvío de notificaciones
#
# ── FIX BUG 3 ──
# El mapeo original entendía SÓLO `bienvenida`, `vencimiento` e `inactividad`.
# Reenviar cualquier otro tipo REAL del sistema (confirmacion_renovacion,
# confirmacion_plan, confirmacion_pedido, activacion, bienvenida_activacion,
# renovacion_plan, vencimiento_inminente, ultimo_credito, sin_creditos,
# reset_password, cumplimiento, acompanamiento, hito_racha_N, reactivacion)
# devolvía `400 tipo no soportado` y además dejaba la fila marcada como
# `fallido` con ese texto (así quedó la fila 22 de fanny carrasco en PROD),
# como si el correo original hubiera fallado cuando en realidad nunca se
# intentó reenviar.
#
# Los tipos que NO pueden tener fila propia (su destinatario es el admin o un
# lead sin cuenta: se registran con alumno_id=None, y esta tabla/pantalla exige
# alumno) quedan con un error explícito: `solicitud_registro`,
# `solicitud_prueba_clase`, `alerta_stock_bajo`, `emergencia_cobertura`.
# ═════════════════════════════════════════════════════════════════════════════

TIPOS_SIN_FILA = {"solicitud_registro", "solicitud_prueba_clase",
                  "alerta_stock_bajo", "emergencia_cobertura"}


def _suscripcion_activa(db: Session, alumno_id: int):
    """Suscripción activa más reciente del alumno (para reconstruir el correo)."""
    from app.models.suscripcion import Suscripcion
    return db.query(Suscripcion).filter(
        Suscripcion.usuario_id == alumno_id,
        Suscripcion.estado == "activo",
    ).order_by(Suscripcion.fecha_expiracion.desc()).first()


def _resumen_plan(db: Session, sus) -> tuple:
    """(plan_nombre, creditos, fecha_vigencia 'dd/mm/aaaa') de la suscripción."""
    from app.models.plan import Plan
    nombre, creditos, fecha = "plan", 0, ""
    if sus:
        plan = db.query(Plan).filter(Plan.id == sus.plan_id).first() if sus.plan_id else None
        if plan:
            nombre = plan.nombre or nombre
            if not plan.es_ilimitado:
                creditos = plan.creditos or 0
        if not creditos and sus.creditos_totales:
            creditos = sus.creditos_totales
        if sus.fecha_expiracion:
            fecha = sus.fecha_expiracion.strftime("%d/%m/%Y")
    return nombre, creditos, fecha


def _dias_inactividad(db: Session, alumno) -> int:
    """Días reales sin asistencia (mismo criterio que /enviar-manual y Fidelización)."""
    from app.models.asistencia import Asistencia
    ultima = db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == alumno.tenant_id,
        Asistencia.usuario_id == alumno.id,
    ).scalar()
    referencia = ultima or (alumno.created_at.date() if alumno.created_at else None)
    return max(1, (date.today() - referencia).days) if referencia else 1


def _password_provisional(db: Session, alumno) -> str:
    """Nueva contraseña provisional + cambio forzado en el primer login.

    `activacion` y `bienvenida_activacion` llevan la contraseña en texto y la
    original NO se guarda (sólo el hash): un reenvío tiene que emitir una nueva
    para que el correo sea realmente utilizable.
    """
    from app.api.v1.alumnos import generar_password_provisional
    from app.core.security import get_password_hash
    pwd = generar_password_provisional()
    alumno.password_hash = get_password_hash(pwd)
    if hasattr(alumno, "cambiar_password_al_login"):
        alumno.cambiar_password_al_login = True
    db.flush()
    return pwd


def _token_reset(db: Session, alumno) -> str:
    """Token de un solo uso (1 h) para el link de restablecimiento."""
    from app.models.password_reset_token import PasswordResetToken
    ahora = datetime.now(timezone.utc)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.usuario_id == alumno.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": ahora})
    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        usuario_id=alumno.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=ahora + timedelta(hours=1),
    ))
    db.flush()
    return token


def _ultimo_pedido(db: Session, alumno_id: int):
    """Datos del último pedido del alumno (para reconstruir su confirmación)."""
    from app.models.pedido import Pedido
    from app.models.producto import Producto
    ped = db.query(Pedido).filter(
        Pedido.alumno_id == alumno_id).order_by(Pedido.id.desc()).first()
    if not ped:
        return None
    prod = db.query(Producto).filter(
        Producto.id == ped.producto_id).first() if ped.producto_id else None
    return {"producto": prod.nombre if prod else f"Producto #{ped.producto_id}",
            "cantidad": ped.cantidad or 1, "total": int(ped.total or 0)}


def _reenviar_asistencia(db: Session, reg, alumno) -> bool:
    """Reenvía los correos del cierre mensual recalculando los datos del mes de
    la fila (`mes_referencia`) con las mismas funciones del flujo mensual."""
    from app.services import asistencia_service as asis
    from app.services.asistencia_email_service import (
        enviar_email_cumplimiento, enviar_email_acompanamiento, _enviar_racha,
        enviar_email_reactivacion, _nombre_mes,
    )
    mes_ref = reg.mes_referencia or date(date.today().year, date.today().month, 1)
    anio, mes = mes_ref.year, mes_ref.month
    mes_nombre = _nombre_mes(mes)

    if reg.tipo == "reactivacion":
        meses = asis._meses_consecutivos_sin_plan(
            db, alumno.id, alumno.tenant_id, anio, mes)
        return enviar_email_reactivacion(alumno.nombre, alumno.correo, alumno.id,
                                        max(1, meses), mes_nombre, mes_ref)

    if reg.tipo.startswith("hito_racha"):
        sufijo = reg.tipo.replace("hito_racha_", "")
        nivel = int(sufijo) if sufijo.isdigit() else 1
        return _enviar_racha(alumno.nombre, alumno.correo, alumno.id, nivel,
                             mes_nombre, mes_ref)

    calculo = asis.calcular_asistencia_mes(db, alumno.id, alumno.tenant_id, anio, mes)
    if reg.tipo == "cumplimiento":
        racha = asis.calcular_racha(db, alumno.id, alumno.tenant_id, anio, mes)
        return enviar_email_cumplimiento(alumno.nombre, alumno.correo, alumno.id,
                                        mes_nombre, calculo["total_reservadas"],
                                        racha, mes_ref)
    coach = asis._coach_del_box(db, alumno.tenant_id)
    return enviar_email_acompanamiento(alumno.nombre, alumno.correo, alumno.id,
                                       mes_nombre, calculo["asistidas"],
                                       calculo["total_reservadas"], coach, mes_ref)


def _reenviar_por_tipo(db: Session, reg, alumno) -> bool:
    """Despacha el reenvío según el tipo registrado. Devuelve True si el correo salió.

    Cada tipo se reconstruye con los datos ACTUALES del alumno/box (suscripción
    activa, último pedido, meses del cierre, etc.), que es lo más útil para el
    destinatario. Levanta HTTPException si el tipo no es reenviable.
    """
    from app.core.config import settings
    from app.services.email_service import (
        enviar_email_activacion_alumno, send_bienvenida_activacion, send_renovacion_plan,
        send_alerta_urgencia_renovacion, send_alerta_ultimo_credito, send_alerta_sin_creditos,
        send_reset_password, send_confirmacion_renovacion_plan, send_confirmacion_plan,
        send_confirmacion_pedido,
    )

    tipo = reg.tipo or ""
    frontend = url_frontend()
    sus = _suscripcion_activa(db, alumno.id)
    plan_nombre, creditos, fecha_vigencia = _resumen_plan(db, sus)
    alumno_dict = {"id": alumno.id, "nombre": alumno.nombre, "correo": alumno.correo,
                   "plan_nombre": plan_nombre}
    link_panel = url_frontend("/alumno/dashboard")

    if tipo == "bienvenida":
        return enviar_email_bienvenida(alumno_dict, token_onboarding="")
    if tipo == "vencimiento":
        fecha = sus.fecha_expiracion if sus else None
        return enviar_email_vencimiento_plan(alumno_dict, fecha)
    if tipo == "inactividad":
        return enviar_email_fidelizacion(
            alumno.nombre, alumno.correo, _dias_inactividad(db, alumno))
    if tipo == "activacion":
        return enviar_email_activacion_alumno(
            alumno_dict, _password_provisional(db, alumno))
    if tipo == "bienvenida_activacion":
        pwd = _password_provisional(db, alumno)
        return send_bienvenida_activacion(alumno.nombre, alumno.correo, pwd,
                                          plan_nombre, creditos, fecha_vigencia,
                                          url_frontend("/login"))
    if tipo == "renovacion_plan":
        return send_renovacion_plan(alumno.nombre, alumno.correo, fecha_vigencia,
                                    url_frontend("/alumno/solicitar-plan"))
    if tipo == "vencimiento_inminente":
        return send_alerta_urgencia_renovacion(alumno.nombre, alumno.correo)
    if tipo == "ultimo_credito":
        from app.services.alertas_email_service import _dias_restantes_mes
        disponibles = getattr(sus, "creditos_disponibles", None)
        return send_alerta_ultimo_credito(alumno.nombre, alumno.correo,
                                          disponibles if disponibles is not None else 1,
                                          max(1, _dias_restantes_mes()))
    if tipo == "sin_creditos":
        return send_alerta_sin_creditos(alumno.nombre, alumno.correo)
    if tipo == "reset_password":
        link = url_frontend(f"/reset-password?token={_token_reset(db, alumno)}")
        return send_reset_password(alumno.nombre, alumno.correo, link)
    if tipo == "confirmacion_renovacion":
        return send_confirmacion_renovacion_plan(alumno.nombre, alumno.correo,
                                                 plan_nombre, creditos, fecha_vigencia,
                                                 link_panel, alumno.id)
    if tipo == "confirmacion_plan":
        return send_confirmacion_plan(alumno.nombre, alumno.correo, plan_nombre,
                                      creditos, fecha_vigencia, link_panel, alumno.id)
    if tipo == "confirmacion_pedido":
        ped = _ultimo_pedido(db, alumno.id)
        if not ped:
            raise HTTPException(
                400, "El alumno no tiene pedidos: no se puede reconstruir la confirmación")
        return send_confirmacion_pedido(alumno.nombre, alumno.correo, ped["producto"],
                                        ped["cantidad"], ped["total"],
                                        url_frontend("/alumno/mis-pedidos"), alumno.id)
    if (tipo in ("cumplimiento", "acompanamiento", "reactivacion")
            or tipo.startswith("hito_racha")):
        return _reenviar_asistencia(db, reg, alumno)
    if tipo in TIPOS_SIN_FILA:
        raise HTTPException(
            400, f"'{tipo}' se envía al admin o a un lead sin cuenta: "
                 "no tiene destinatario-alumno para reenviar desde acá")
    raise HTTPException(400, f"tipo no soportado: {tipo}")


@router.post("/{notif_id}/reenviar")
def reenviar_notificacion(
    notif_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Reenvía un correo según el tipo registrado y actualiza estado (solo admin).

    FIX BUG 3: el despacho (`_reenviar_por_tipo`) cubre TODOS los tipos reales
    del sistema, no sólo bienvenida/vencimiento/inactividad. Si el tipo no es
    reenviable, la fila conserva su estado original (no se marca `fallido`).
    """
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

    exito = False
    error = None
    try:
        exito = bool(_reenviar_por_tipo(db, reg, alumno))
    except HTTPException as e:
        # Tipo no reenviable: NO se marca la fila como fallida (la fila traza el
        # envío ORIGINAL, no el intento de reenvío) ni se pisa su estado.
        db.rollback()
        raise HTTPException(e.status_code, e.detail)
    except Exception as e:
        exito = False
        error = str(e)

    if not exito and not error:
        # Gmail SMTP no usa Resend: exponer el error real del envío.
        try:
            from app.services import email_service
            error = (email_service.ULTIMO_ERROR_SMTP
                     or "No se pudo enviar el correo via Gmail SMTP "
                        "(revisar credenciales o destinatario).")
        except Exception:
            error = "No se pudo enviar el correo via Gmail SMTP."

    reg.detalle_error = None if exito else error
    reg.estado = "enviado" if exito else "fallido"
    reg.fecha_envio = datetime.utcnow()
    db.commit()
    db.refresh(reg)
    return {"id": reg.id, "estado": reg.estado, "fecha_envio": str(reg.fecha_envio),
            "detalle_error": reg.detalle_error}