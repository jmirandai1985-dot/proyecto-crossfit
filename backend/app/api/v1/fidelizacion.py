"""
Módulo de Fidelización Inteligente
Analiza asistencias y detecta alumnos en riesgo de abandono
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, or_
from datetime import datetime, date
from typing import List, Optional
import pandas as pd
from app.services.email_service import enviar_email_fidelizacion

from app.db.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.asistencia import Asistencia
from app.models.reserva import Reserva
from app.models.clase import Clase
from app.models.coach_disciplina import CoachDisciplina
from app.core.dependencies import get_current_admin, get_current_coach
from app.services.auditoria_service import registrar_auditoria

router = APIRouter()

UMBRAL_ALERTA_DIAS = 7  # Días sin asistir para considerar alumno en riesgo


def _registros_json(df):
    """DataFrame -> lista de dicts JSON-safe (arregla el 500 por NaN).

    pandas convierte a NaN los `None` numéricos (p.ej. `dias_ausente` de un
    alumno sin historial) y el serializador de FastAPI rechaza NaN con
    "Out of range float values are not JSON compliant" -> el endpoint devolvía
    500 y el frontend lo mostraba como 0 en silencio. Acá se normaliza a None
    (JSON `null`) y se convierten los escalares de numpy a tipos nativos.
    """
    registros = df.to_dict(orient="records")
    for reg in registros:
        for clave, valor in reg.items():
            if hasattr(valor, "item"):       # escalar de numpy -> python
                valor = valor.item()
            try:
                if pd.isna(valor):           # NaN / NaT -> None
                    valor = None
            except (TypeError, ValueError):  # listas/dicts: pd.isna no aplica
                pass
            reg[clave] = valor
    return registros


# ─────────────────────────────────────────
# ENDPOINT 1: Analizar asistencias
# ─────────────────────────────────────────
@router.get("/analizar/{tenant_id}")
def analizar_fidelizacion(
    tenant_id: Optional[int] = None,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Analiza la última asistencia de cada alumno
    y detecta quiénes llevan más de X días sin ir. Solo admin (tenant del token).
    """
    # 🔒 SEGURIDAD: tenant_id del token; el path param se ignora.
    tenant_id = current_user["tenant_id"]
    alumnos = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.estado == "activo"
    ).all()

    if not alumnos:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay alumnos activos en este box"
        )

    ultimas = db.query(
        Asistencia.usuario_id,
        func.max(Asistencia.fecha).label("ultima_fecha")
    ).filter(
        Asistencia.tenant_id == tenant_id
    ).group_by(Asistencia.usuario_id).all()

    mapa_asistencias = {r.usuario_id: r.ultima_fecha for r in ultimas}

    hoy = date.today()
    data = []
    for alumno in alumnos:
        ultima = mapa_asistencias.get(alumno.id)
        # BUGFIX 999: antes, un alumno que nunca asistió quedaba con dias=999 y
        # entraba a la alerta (y a la campaña de email) como si llevara 999 días
        # sin entrenar. Se replica el patrón de /coach/{id}/en-riesgo y
        # /tenant/{id}/en-riesgo: sin historial -> dias=None, tiene_historial=False.
        if ultima:
            dias = (hoy - ultima).days
            tiene_historial = True
            ultima_str = str(ultima)
        else:
            dias = None  # Nunca ha asistido
            tiene_historial = False
            ultima_str = "Nunca"
        data.append({
            "id": alumno.id,
            "nombre": alumno.nombre,
            "correo": alumno.correo,
            "telefono": alumno.telefono,
            "ultima_asistencia": ultima_str,
            "dias_ausente": dias,
            "tiene_historial": tiene_historial
        })

    df = pd.DataFrame(data)
    # Un alumno sin historial NO es un ausente (nunca empezó a entrenar): va a su
    # propio bucket en vez de entrar a la alerta por inactividad.
    df_con_historial = df[df["tiene_historial"] == True].copy()
    df_sin_historial = df[df["tiene_historial"] == False].copy()
    df_alerta = df_con_historial[
        df_con_historial["dias_ausente"] >= umbral_dias].copy()
    df_ok = df_con_historial[
        df_con_historial["dias_ausente"] < umbral_dias].copy()
    df_alerta = df_alerta.sort_values("dias_ausente", ascending=False)

    return {
        "status": "success",
        "fecha_analisis": str(hoy),
        "umbral_dias": umbral_dias,
        "total_alumnos": len(df),
        "total_activos": len(df_ok),
        "total_alerta": len(df_alerta),
        "total_sin_historial": len(df_sin_historial),
        "alumnos_alerta": _registros_json(df_alerta),
        "alumnos_activos": _registros_json(df_ok),
        "alumnos_sin_historial": _registros_json(df_sin_historial)
    }


# ─────────────────────────────────────────
# ENDPOINT 2: Registrar asistencia
# ─────────────────────────────────────────
@router.post("/registrar", status_code=status.HTTP_201_CREATED)
def registrar_asistencia(
    tenant_id: Optional[int] = None,
    usuario_id: int = None,
    clase: Optional[str] = "WOD",
    fecha: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Registra la asistencia de un alumno al box. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id,
        Usuario.tenant_id == tenant_id,
        Usuario.estado == "activo"
    ).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en este box"
        )

    fecha_asistencia = fecha or date.today()

    ya_asistio = db.query(Asistencia).filter(
        Asistencia.usuario_id == usuario_id,
        Asistencia.fecha == fecha_asistencia
    ).first()

    if ya_asistio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{usuario.nombre} ya registró asistencia hoy"
        )

    nueva = Asistencia(
        tenant_id=tenant_id,
        usuario_id=usuario_id,
        fecha=fecha_asistencia,
        clase=clase
    )

    db.add(nueva)
    db.commit()

    return {
        "status": "success",
        "mensaje": f"Asistencia registrada para {usuario.nombre}",
        "fecha": str(fecha_asistencia),
        "clase": clase
    }


# ─────────────────────────────────────────
# ENDPOINT 3: Enviar campaña de emails
# ─────────────────────────────────────────
@router.post("/campana-email/{tenant_id}")
def enviar_campana_email(
    tenant_id: Optional[int] = None,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Envía emails automáticos a alumnos ausentes. Solo admin (tenant del token).

    ── FIX S4 (seguridad) ──
    Se eliminaron los query params gmail_user/gmail_password (credenciales SMTP
    expuestas en URL/logs). Los correos se envían SIEMPRE con las credenciales
    centralizadas del sistema (settings.GMAIL_SMTP_USER / GMAIL_SMTP_APP_PASSWORD),
    igual que el resto de email_service. Los parámetros manuales eran código
    muerto: enviar_email_fidelizacion ya no los usa (migrado a SMTP central).
    """
    # 🔒 SEGURIDAD: tenant_id del token; el path param se ignora.
    tenant_id = current_user["tenant_id"]
    analisis = analizar_fidelizacion(tenant_id, umbral_dias, db, current_user)
    alumnos_alerta = analisis["alumnos_alerta"]

    if not alumnos_alerta:
        return {"status": "success", "mensaje": "No hay alumnos en alerta"}

    enviados = []
    fallidos = []
    omitidos = []

    for alumno in alumnos_alerta:
        # Guard defensivo: a un alumno sin historial (nunca asistió) no se le puede
        # decir "llevas N días sin entrenar" -> no recibe el email de ausencia.
        if not alumno.get("tiene_historial") or alumno.get("dias_ausente") is None:
            omitidos.append(alumno["correo"])
            continue

        exito = enviar_email_fidelizacion(
            nombre=alumno["nombre"],
            correo=alumno["correo"],
            dias_ausente=alumno["dias_ausente"],
        )
        if exito:
            enviados.append(alumno["correo"])
        else:
            fallidos.append(alumno["correo"])

    return {
        "status": "success",
        "emails_enviados": len(enviados),
        "emails_fallidos": len(fallidos),
        "omitidos_sin_historial": omitidos,
        "detalle_enviados": enviados,
        "detalle_fallidos": fallidos
    }


# ─────────────────────────────────────────
# ENDPOINT 4: Alumnos en riesgo de un coach específico
# ─────────────────────────────────────────
@router.get("/coach/{coach_id}/en-riesgo")
def alumnos_coach_en_riesgo(
    coach_id: int,
    tenant_id: Optional[int] = None,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """
    Obtiene alumnos en riesgo (días sin asistir > umbral) para un coach específico.
    Un alumno "es de un coach" si tiene al menos una reserva en una clase 
    donde clases.coach_id coincide con ese coach.
    Coach/admin del box (un coach solo puede consultar su propio coach_id).
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")
    if rol == "coach" and current_user["usuario_id"] != coach_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes consultar los alumnos en riesgo de tus propias clases",
        )
    alumnos_coach = db.query(
        distinct(Reserva.alumno_id)
    ).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Clase.coach_id == coach_id,
        Clase.tenant_id == tenant_id,
    ).all()

    alumno_ids = [r[0] for r in alumnos_coach]

    if not alumno_ids:
        return {
            "status": "success",
            "coach_id": coach_id,
            "total_alumnos": 0,
            "total_alerta": 0,
            "alumnos_alerta": []
        }

    alumnos = db.query(Usuario).filter(
        Usuario.id.in_(alumno_ids),
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.estado == "activo"
    ).all()

    if not alumnos:
        return {
            "status": "success",
            "coach_id": coach_id,
            "total_alumnos": 0,
            "total_alerta": 0,
            "alumnos_alerta": []
        }

    ultimas = db.query(
        Asistencia.usuario_id,
        func.max(Asistencia.fecha).label("ultima_fecha")
    ).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id.in_([a.id for a in alumnos])
    ).group_by(Asistencia.usuario_id).all()

    mapa_asistencias = {r.usuario_id: r.ultima_fecha for r in ultimas}

    hoy = date.today()
    data = []
    for alumno in alumnos:
        ultima = mapa_asistencias.get(alumno.id)
        if ultima:
            dias = (hoy - ultima).days
            tiene_historial = True
            ultima_str = str(ultima)
        else:
            dias = None
            tiene_historial = False
            ultima_str = "Nunca"
        data.append({
            "id": alumno.id,
            "nombre": alumno.nombre,
            "correo": alumno.correo,
            "telefono": alumno.telefono,
            "ultima_asistencia": ultima_str,
            "dias_ausente": dias,
            "tiene_historial": tiene_historial
        })

    df = pd.DataFrame(data)
    df_alerta = df[
        (df["tiene_historial"] == False) | (df["dias_ausente"] >= umbral_dias)
    ].copy()
    df_alerta = df_alerta.sort_values(
        "dias_ausente", ascending=False, na_position="last")

    return {
        "status": "success",
        "coach_id": coach_id,
        "umbral_dias": umbral_dias,  # para que el copy del panel no lo tenga hardcodeado
        "total_alumnos": len(alumnos),
        "total_alerta": len(df_alerta),
        "alumnos_alerta": _registros_json(df_alerta)
    }


# ─────────────────────────────────────────
# ENDPOINT 4b: Alumnos de un coach (dashboard coach)
# Un alumno "es del coach" si tiene al menos una reserva ACTIVA (no cancelada)
# en una clase donde el coach es el asignado (clases.coach_id) O en una clase
# de alguna de las disciplinas que tiene asignadas (coach_disciplinas activo).
# Esto sigue el mismo enfoque "por disciplina" de la grilla del coach (las
# clases pueden no tener coach_id explícito y aun así pertenecer al coach por
# disciplina). Coach solo su propio id; admin puede consultar cualquiera.
# ─────────────────────────────────────────
@router.get("/coach/{coach_id}/alumnos")
def alumnos_de_coach(
    coach_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")
    if rol == "coach" and current_user["usuario_id"] != coach_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes consultar los alumnos de tus propias clases/disciplinas",
        )

    disc_ids = [
        r[0] for r in db.query(CoachDisciplina.disciplina_id).filter(
            CoachDisciplina.tenant_id == tenant_id,
            CoachDisciplina.coach_id == coach_id,
            CoachDisciplina.activo == True,
        ).all()
    ]

    filtro_clase = [Clase.tenant_id == tenant_id]
    if disc_ids:
        filtro_clase.append(or_(
            Clase.coach_id == coach_id,
            Clase.disciplina_id.in_(disc_ids),
        ))
    else:
        filtro_clase.append(Clase.coach_id == coach_id)

    filas = db.query(distinct(Reserva.alumno_id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.estado != "cancelled",
        *filtro_clase,
    ).all()

    alumno_ids = [r[0] for r in filas]

    if not alumno_ids:
        return {"coach_id": coach_id, "total_alumnos": 0, "alumnos": []}

    alumnos = db.query(Usuario).filter(
        Usuario.id.in_(alumno_ids),
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.estado == "activo",
    ).order_by(Usuario.nombre.asc()).all()

    return {
        "coach_id": coach_id,
        "total_alumnos": len(alumnos),
        "alumnos": [
            {
                "id": a.id,
                "nombre": a.nombre,
                "correo": a.correo,
                "telefono": a.telefono,
                "genero": a.genero,
            }
            for a in alumnos
        ],
    }


# ─────────────────────────────────────────
# ENDPOINT 4c: Contactar por correo a un alumno (panel coach)
# Mismo patron que POST /notificaciones-enviadas/enviar-manual (admin), pero
# coach-scoped: el coach solo puede contactar alumnos de su propio box y usando
# su propio coach_id. Reusa el template de inactividad (enviar_email_fidelizacion).
#
# IMPORTANTE (comportamiento deseado): el envio se registra en
# notificaciones_enviadas con tipo='inactividad', igual que el envio manual del
# admin. Eso hace que la alerta automatica de inactividad NO vuelva a escribirle
# a ese alumno por los proximos 7 dias (dedupe de alertas_email_service), que es
# justo lo que se busca cuando un coach ya lo contacto a mano.
# ─────────────────────────────────────────
def _registrar_notificacion(db: Session, alumno: Usuario, tipo: str,
                            estado: str, detalle_error: str = None) -> None:
    """Registra el envio en notificaciones_enviadas (mismo shape que el admin)."""
    from app.models.notificacion_enviada import NotificacionEnviada
    db.add(NotificacionEnviada(
        alumno_id=alumno.id,
        tenant_id=alumno.tenant_id,
        tipo=tipo,
        estado=estado,
        detalle_error=detalle_error,
        fecha_envio=datetime.utcnow(),
    ))
    db.commit()


@router.post("/coach/{coach_id}/contactar/{alumno_id}")
def contactar_alumno_por_email(
    coach_id: int,
    alumno_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Envia el correo de inactividad a un alumno del box desde el panel coach.

    - Coach: solo su propio `coach_id` (mismo criterio que los otros /coach/...).
    - El alumno debe ser del box del token y tener rol alumno.
    - Sin correo registrado -> 400 con detalle claro (no falla en silencio).
    - Calcula los dias REALES de inactividad (ultima asistencia; si nunca asistio,
      la fecha de alta; minimo 1) y registra el envio con su estado.
    """
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")
    if rol == "coach" and current_user["usuario_id"] != coach_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes contactar alumnos desde tu propio panel",
        )

    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
    ).first()
    if not alumno:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alumno no encontrado en este box",
        )
    if not alumno.correo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El alumno no tiene correo registrado",
        )

    ultima = db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == alumno.id,
    ).scalar()
    referencia = ultima or (alumno.created_at.date() if alumno.created_at else None)
    dias = max(1, (date.today() - referencia).days) if referencia else 1

    exito = False
    detalle_error = None
    try:
        exito = enviar_email_fidelizacion(alumno.nombre, alumno.correo, dias)
    except Exception as e:  # noqa: BLE001 - se reporta al panel, no se traga
        detalle_error = str(e)

    if not exito and not detalle_error:
        try:
            from app.services import email_service
            detalle_error = email_service.ULTIMO_ERROR_SMTP or (
                "No se pudo enviar el correo via Gmail SMTP (revisar credenciales o destinatario).")
        except Exception:
            detalle_error = "No se pudo enviar el correo via Gmail SMTP."

    _registrar_notificacion(
        db, alumno, "inactividad",
        "enviado" if exito else "fallido",
        None if exito else detalle_error)

    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="EMAIL_MANUAL",
        entidad="usuario",
        entidad_id=alumno.id,
        detalle={"tipo": "inactividad", "dias_inactividad": dias,
                 "exito": exito, "origen": "panel_coach"},
    )

    return {
        "exito": exito,
        "estado": "enviado" if exito else "fallido",
        "detalle_error": None if exito else detalle_error,
        "dias_inactividad": dias,
    }


# ─────────────────────────────────────────
# ENDPOINT 4d: Ficha del alumno para el panel coach (P2)
# Datos EXACTOS (pedido confirmado): telefono, antiguedad, plan actual y
# creditos/vencimiento reales. Los endpoints admin (GET /usuarios/{id} y
# GET /suscripciones) son admin-only, asi que el coach necesita esta version
# acotada: no expone datos financieros ni el listado completo de suscripciones.
# ─────────────────────────────────────────
@router.get("/coach/{coach_id}/alumno/{alumno_id}/ficha")
def ficha_alumno_coach(
    coach_id: int,
    alumno_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Ficha acotada de un alumno del box para el panel coach.

    - Coach: solo su propio `coach_id` (mismo criterio que los otros /coach/...).
    - El alumno debe ser del box del token y tener rol alumno.
    - Devuelve telefono + fecha de alta (+ antiguedad en dias) y el plan activo
      con sus creditos disponibles y fecha de vencimiento EXACTAS. Si no tiene
      suscripcion activa, `plan` viene en null (el front muestra Sin plan activo).
    """
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")
    if rol == "coach" and current_user["usuario_id"] != coach_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes ver la ficha de alumnos de tu propio panel",
        )

    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
    ).first()
    if not alumno:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alumno no encontrado en este box",
        )

    from app.models.suscripcion import Suscripcion
    from app.models.plan import Plan

    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.usuario_id == alumno.id,
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
    ).order_by(Suscripcion.fecha_expiracion.desc()).first()

    plan_data = None
    if suscripcion:
        plan = db.query(Plan).filter(
            Plan.id == suscripcion.plan_id,
            Plan.tenant_id == tenant_id,
        ).first()
        plan_data = {
            "plan_id": suscripcion.plan_id,
            "nombre": plan.nombre if plan else None,
            "creditos_disponibles": suscripcion.creditos_disponibles,
            "creditos_totales": suscripcion.creditos_totales,
            "es_ilimitado": bool(plan.es_ilimitado) if plan else None,
            "fecha_expiracion": (suscripcion.fecha_expiracion.isoformat()
                                 if suscripcion.fecha_expiracion else None),
            "estado": suscripcion.estado,
        }

    alta = alumno.created_at.date() if alumno.created_at else None
    return {
        "id": alumno.id,
        "nombre": alumno.nombre,
        "correo": alumno.correo,
        "telefono": alumno.telefono,
        "created_at": alumno.created_at.isoformat() if alumno.created_at else None,
        "antiguedad_dias": (date.today() - alta).days if alta else None,
        "plan": plan_data,
    }


# ─────────────────────────────────────────
# ENDPOINT 5: Alumnos en riesgo del tenant (para admin, sin filtrar por coach)
# ─────────────────────────────────────────
@router.get("/tenant/{tenant_id}/en-riesgo")
def alumnos_tenant_en_riesgo(
    tenant_id: Optional[int] = None,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Obtiene TODOS los alumnos activos del tenant que estan en riesgo
    (dias sin asistir > umbral). Version global para admin, sin filtrar por coach.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el path param se ignora.
    tenant_id = current_user["tenant_id"]
    alumnos = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.estado == "activo"
    ).all()

    if not alumnos:
        return {
            "status": "success",
            "total_alumnos": 0,
            "total_alerta": 0,
            "alumnos_alerta": []
        }

    ultimas = db.query(
        Asistencia.usuario_id,
        func.max(Asistencia.fecha).label("ultima_fecha")
    ).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id.in_([a.id for a in alumnos])
    ).group_by(Asistencia.usuario_id).all()

    mapa_asistencias = {r.usuario_id: r.ultima_fecha for r in ultimas}

    hoy = date.today()
    data = []
    for alumno in alumnos:
        ultima = mapa_asistencias.get(alumno.id)
        if ultima:
            dias = (hoy - ultima).days
            tiene_historial = True
            ultima_str = str(ultima)
        else:
            dias = None  # Nunca ha asistido
            tiene_historial = False
            ultima_str = "Nunca"
        data.append({
            "id": alumno.id,
            "nombre": alumno.nombre,
            "correo": alumno.correo,
            "telefono": alumno.telefono,
            "ultima_asistencia": ultima_str,
            "dias_ausente": dias,
            "tiene_historial": tiene_historial
        })

    df = pd.DataFrame(data)
    df_alerta = df[
        (df["tiene_historial"] == False) | (df["dias_ausente"] >= umbral_dias)
    ].copy()
    df_alerta = df_alerta.sort_values(
        "dias_ausente", ascending=False, na_position="last")

    return {
        "status": "success",
        "total_alumnos": len(alumnos),
        "total_alerta": len(df_alerta),
        "alumnos_alerta": _registros_json(df_alerta)
    }


# ─────────────────────────────────────────
# ENDPOINT 6: Vencimientos inminentes (proximos 5 dias)
# ─────────────────────────────────────────
@router.get("/tenant/{tenant_id}/vencimientos")
def vencimientos_inminentes(
    tenant_id: Optional[int] = None,
    dias_umbral: int = 5,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Devuelve alumnos con membresia activa cuya fecha_expiracion esta
    dentro de los proximos N dias (default 5). Solo admin (tenant del token).
    """
    from app.models.suscripcion import Suscripcion
    from app.models.plan import Plan
    from datetime import timedelta

    # 🔒 SEGURIDAD: tenant_id del token; el path param se ignora.
    tenant_id = current_user["tenant_id"]

    hoy = date.today()
    fecha_limite = hoy + timedelta(days=dias_umbral)

    suscripciones = db.query(Suscripcion, Usuario, Plan).join(
        Usuario, Suscripcion.usuario_id == Usuario.id
    ).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == 'activo',
        Suscripcion.fecha_expiracion >= hoy,
        Suscripcion.fecha_expiracion <= fecha_limite
    ).all()

    resultado = []
    for s, u, p in suscripciones:
        dias_restantes = (s.fecha_expiracion.date() - hoy).days
        resultado.append({
            "id": s.id,
            "usuario_id": u.id,
            "nombre": u.nombre,
            "correo": u.correo,
            "plan_nombre": p.nombre,
            "fecha_expiracion": str(s.fecha_expiracion.date()),
            "dias_restantes": dias_restantes,
            "creditos_disponibles": s.creditos_disponibles
        })

    return {
        "status": "success",
        "total_vencimientos": len(resultado),
        "dias_umbral": dias_umbral,
        "alumnos": resultado
    }
