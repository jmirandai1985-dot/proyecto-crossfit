"""
Módulo de Fidelización Inteligente
Analiza asistencias y detecta alumnos en riesgo de abandono
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from datetime import datetime, date
from typing import List, Optional
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.db.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.asistencia import Asistencia
from app.models.reserva import Reserva
from app.models.clase import Clase

router = APIRouter()

UMBRAL_ALERTA_DIAS = 7  # Días sin asistir para considerar alumno en riesgo


# ─────────────────────────────────────────
# FUNCIÓN INTERNA: Envío de email con Gmail
# ─────────────────────────────────────────
def enviar_email_fidelizacion(
    nombre: str,
    correo: str,
    dias_ausente: int,
    gmail_user: str,
    gmail_password: str
):
    """Envía email de recuperación al alumno ausente"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"¡Te extrañamos en el box, {nombre.split()[0]}! 💪"
        msg["From"] = gmail_user
        msg["To"] = correo

        html = f"""
        <html><body>
        <h2>¡Hola {nombre.split()[0]}! 👋</h2>
        <p>Notamos que llevas <strong>{dias_ausente} días</strong> sin visitarnos.</p>
        <p>Tu progreso te está esperando. ¡Vuelve cuando quieras!</p>
        <p>Si necesitas ayuda o tienes alguna consulta, responde este correo.</p>
        <br>
        <p><strong>El equipo de tu Box CrossFit</strong> 🏋️</p>
        </body></html>
        """
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, correo, msg.as_string())

        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {correo}: {e}")
        return False


# ─────────────────────────────────────────
# ENDPOINT 1: Analizar asistencias
# ─────────────────────────────────────────
@router.get("/analizar/{tenant_id}")
def analizar_fidelizacion(
    tenant_id: int,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    db: Session = Depends(get_db)
):
    """
    Analiza la última asistencia de cada alumno
    y detecta quiénes llevan más de X días sin ir
    """
    alumnos = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.activo == True
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
        dias = (hoy - ultima).days if ultima else 999
        data.append({
            "id": alumno.id,
            "nombre": alumno.nombre,
            "correo": alumno.correo,
            "telefono": alumno.telefono,
            "ultima_asistencia": str(ultima) if ultima else "Nunca",
            "dias_ausente": dias
        })

    df = pd.DataFrame(data)
    df_alerta = df[df["dias_ausente"] >= umbral_dias].copy()
    df_ok = df[df["dias_ausente"] < umbral_dias].copy()
    df_alerta = df_alerta.sort_values("dias_ausente", ascending=False)

    return {
        "status": "success",
        "fecha_analisis": str(hoy),
        "umbral_dias": umbral_dias,
        "total_alumnos": len(df),
        "total_activos": len(df_ok),
        "total_alerta": len(df_alerta),
        "alumnos_alerta": df_alerta.to_dict(orient="records"),
        "alumnos_activos": df_ok.to_dict(orient="records")
    }


# ─────────────────────────────────────────
# ENDPOINT 2: Registrar asistencia
# ─────────────────────────────────────────
@router.post("/registrar", status_code=status.HTTP_201_CREATED)
def registrar_asistencia(
    tenant_id: int,
    usuario_id: int,
    clase: Optional[str] = "WOD",
    fecha: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """Registra la asistencia de un alumno al box"""
    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id,
        Usuario.tenant_id == tenant_id,
        Usuario.activo == True
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
    tenant_id: int,
    gmail_user: str,
    gmail_password: str,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """Envía emails automáticos a alumnos ausentes"""
    analisis = analizar_fidelizacion(tenant_id, umbral_dias, db)
    alumnos_alerta = analisis["alumnos_alerta"]

    if not alumnos_alerta:
        return {"status": "success", "mensaje": "No hay alumnos en alerta"}

    enviados = []
    fallidos = []

    for alumno in alumnos_alerta:
        exito = enviar_email_fidelizacion(
            nombre=alumno["nombre"],
            correo=alumno["correo"],
            dias_ausente=alumno["dias_ausente"],
            gmail_user=gmail_user,
            gmail_password=gmail_password
        )
        if exito:
            enviados.append(alumno["correo"])
        else:
            fallidos.append(alumno["correo"])

    return {
        "status": "success",
        "emails_enviados": len(enviados),
        "emails_fallidos": len(fallidos),
        "detalle_enviados": enviados,
        "detalle_fallidos": fallidos
    }


# ─────────────────────────────────────────
# ENDPOINT 4: Alumnos en riesgo de un coach específico
# ─────────────────────────────────────────
@router.get("/coach/{coach_id}/en-riesgo")
def alumnos_coach_en_riesgo(
    coach_id: int,
    tenant_id: int,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    db: Session = Depends(get_db)
):
    """
    Obtiene alumnos en riesgo (días sin asistir > umbral) para un coach específico.
    Un alumno "es de un coach" si tiene al menos una reserva en una clase 
    donde clases.coach_id coincide con ese coach.
    """
    alumnos_coach = db.query(
        distinct(Reserva.alumno_id)
    ).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Clase.coach_id == coach_id
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
        Usuario.activo == True
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
        "total_alumnos": len(alumnos),
        "total_alerta": len(df_alerta),
        "alumnos_alerta": df_alerta.to_dict(orient="records")
    }


# ─────────────────────────────────────────
# ENDPOINT 5: Alumnos en riesgo del tenant (para admin, sin filtrar por coach)
# ─────────────────────────────────────────
@router.get("/tenant/{tenant_id}/en-riesgo")
def alumnos_tenant_en_riesgo(
    tenant_id: int,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    db: Session = Depends(get_db)
):
    """
    Obtiene TODOS los alumnos activos del tenant que estan en riesgo
    (dias sin asistir > umbral). Version global para admin, sin filtrar por coach.
    """
    alumnos = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.activo == True
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
        "alumnos_alerta": df_alerta.to_dict(orient="records")
    }


# ─────────────────────────────────────────
# ENDPOINT 6: Vencimientos inminentes (proximos 5 dias)
# ─────────────────────────────────────────
@router.get("/tenant/{tenant_id}/vencimientos")
def vencimientos_inminentes(
    tenant_id: int,
    dias_umbral: int = 5,
    db: Session = Depends(get_db)
):
    """
    Devuelve alumnos con membresia activa cuya fecha_expiracion esta
    dentro de los proximos N dias (default 5).
    """
    from app.models.suscripcion import Suscripcion
    from app.models.plan import Plan
    from datetime import timedelta

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
