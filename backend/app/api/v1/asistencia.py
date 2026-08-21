"""
Router del sistema de Asistencia + Hitos (Fase 1 y 2).

Coach (marcado de asistencia):
  GET  /clases-hoy                 — clases del día (Santiago) desde la hora actual
  GET  /clases/{clase_id}/alumnos  — reservas de la clase con datos del alumno
  POST /clases/{clase_id}/confirmar— confirmación BATCH (1 click) con auditoría

Alumno:
  GET  /mi-resumen                 — racha actual + % del mes en curso + próximo hito
  GET  /mis-hitos                  — logros alcanzados

n8n (webhook mensual, API key dedicada):
  POST /n8n/evaluar-mes            — cierra el mes, genera hitos y dispara los correos

Seguridad: tenant_id SIEMPRE del token JWT (patrón del resto de la API).
"""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.config import settings
from app.core.dependencies import (
    get_current_user, get_current_coach, verificar_coach_disciplina,
)
from app.models.clase import Clase
from app.models.reserva import Reserva
from app.models.usuario import Usuario, RolUsuario
from app.models.coach_disciplina import CoachDisciplina
from app.models.disciplina import Disciplina
from app.utils.santiago import ahora_santiago, hoy_santiago
from app.schemas.asistencia import ConfirmarAsistenciaRequest
from app.services import asistencia_service as svc

router = APIRouter()


# ── Coach: clases del día desde la hora actual ───────────────────────────────
@router.get("/clases-hoy")
def clases_hoy(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Clases del día actual (America/Santiago) con hora_inicio >= ahora,
    solo de las disciplinas asignadas al coach. Admin/administrador: todas."""
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")
    hoy = hoy_santiago()
    ahora = ahora_santiago().time()

    query = db.query(Clase).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha == hoy,
        Clase.cancelada == False,
        Clase.hora_inicio >= ahora,
    )

    if rol == "coach":
        disc_ids = [r[0] for r in db.query(CoachDisciplina.disciplina_id).filter(
            CoachDisciplina.coach_id == current_user["usuario_id"],
            CoachDisciplina.tenant_id == tenant_id,
            CoachDisciplina.activo == True,
        ).all()]
        if not disc_ids:
            return []
        query = query.filter(Clase.disciplina_id.in_(disc_ids))

    clases = query.order_by(Clase.hora_inicio.asc()).all()

    ids = [c.id for c in clases]
    if ids:
        counts = dict(db.query(Reserva.clase_id, func.count(Reserva.id)).filter(
            Reserva.clase_id.in_(ids),
            Reserva.estado != "cancelled",
        ).group_by(Reserva.clase_id).all())
    else:
        counts = {}

    disc_ids_set = {c.disciplina_id for c in clases}
    disc_map = {}
    if disc_ids_set:
        disc_map = {d.id: d.nombre for d in db.query(Disciplina).filter(
            Disciplina.id.in_(disc_ids_set)).all()}

    return [
        {
            "id": c.id,
            "fecha": str(c.fecha),
            "hora_inicio": str(c.hora_inicio),
            "hora_fin": str(c.hora_fin),
            "disciplina_id": c.disciplina_id,
            "disciplina_nombre": disc_map.get(c.disciplina_id, "Clase"),
            "cupo_maximo": c.cupo_maximo,
            "asistentes_confirmados": c.asistentes_confirmados,
            "reservas_count": counts.get(c.id, 0),
        }
        for c in clases
    ]


# ── Coach: reservas de una clase para marcar ─────────────────────────────────
@router.get("/clases/{clase_id}/alumnos")
def alumnos_clase(
    clase_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
    modo_emergencia: bool = Query(
        False, description="Modo cobertura de emergencia"),
):
    """Reservas activas de la clase con nombre del alumno y asistio actual.

    El frontend muestra los checks marcados por defecto si la clase aún no
    fue marcada (marcada=False); si ya fue marcada, muestra los valores
    guardados."""
    tenant_id = current_user["tenant_id"]

    clase = db.query(Clase).filter(
        Clase.id == clase_id, Clase.tenant_id == tenant_id).first()
    if not clase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clase no encontrada")

    # 🔒 FIX 2: coach solo ve reservas de clases de disciplinas asignadas.
    if current_user.get("rol") == "coach" and clase.disciplina_id:
        verificar_coach_disciplina(
            coach_id=current_user["usuario_id"],
            disciplina_id=clase.disciplina_id,
            db=db,
            modo_emergencia=modo_emergencia,
            clase_id=clase_id,
            accion="ver_asistencia",
            tenant_id=tenant_id,
        )

    reservas = db.query(Reserva).filter(
        Reserva.clase_id == clase_id,
        Reserva.tenant_id == tenant_id,
        Reserva.estado != "cancelled",
    ).order_by(Reserva.created_at.asc()).all()

    alumno_ids = {r.alumno_id for r in reservas}
    nombres = {}
    if alumno_ids:
        for u in db.query(Usuario).filter(Usuario.id.in_(alumno_ids)).all():
            nombres[u.id] = u.nombre

    return {
        "clase_id": clase_id,
        "fecha": str(clase.fecha),
        "hora_inicio": str(clase.hora_inicio),
        "marcada": any(r.asistencia_marcada_at is not None for r in reservas),
        "reservas": [
            {
                "reserva_id": r.id,
                "alumno_id": r.alumno_id,
                "nombre": nombres.get(r.alumno_id, f"Alumno #{r.alumno_id}"),
                "asistio": bool(r.asistio),
            }
            for r in reservas
        ],
    }



# ── Coach: confirmación BATCH (1 click) ──────────────────────────────────────
@router.post("/clases/{clase_id}/confirmar")
def confirmar_asistencia(
    clase_id: int,
    body: ConfirmarAsistenciaRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
    modo_emergencia: bool = Query(
        False, description="Modo cobertura de emergencia"),
):
    """Confirma la asistencia de TODA la clase en una sola transacción.

    Valida la ventana de corrección (mismo día calendario en Chile, hasta las
    23:59:59) en el BACKEND — no solo ocultando botones en el frontend.
    Escribe reservas.asistio + columnas de auditoría (marcada_por/at/via='batch').
    Idempotente: repetir el mismo body es un no-op."""
    tenant_id = current_user["tenant_id"]

    clase = db.query(Clase).filter(
        Clase.id == clase_id, Clase.tenant_id == tenant_id).first()
    if not clase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clase no encontrada")

    # ── VENTANA DE CORRECCIÓN (backend): mismo día calendario en Chile ──
    if clase.fecha != hoy_santiago():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La asistencia solo se puede marcar o corregir el mismo día de la clase "
                   "(hasta las 23:59 hora de Chile).")

    # 🔒 Coach solo opera en disciplinas asignadas (admin/administrador bypass).
    if current_user.get("rol") == "coach" and clase.disciplina_id:
        verificar_coach_disciplina(
            coach_id=current_user["usuario_id"],
            disciplina_id=clase.disciplina_id,
            db=db,
            modo_emergencia=modo_emergencia,
            clase_id=clase_id,
            accion="confirmar_asistencia",
            tenant_id=tenant_id,
        )

    if not body.asistencias:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se enviaron reservas para confirmar")

    reserva_ids = [i.reserva_id for i in body.asistencias]
    if len(set(reserva_ids)) != len(reserva_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reservas duplicadas en el request")

    reservas = db.query(Reserva).filter(
        Reserva.id.in_(reserva_ids),
        Reserva.clase_id == clase_id,
        Reserva.tenant_id == tenant_id,
        Reserva.estado != "cancelled",
    ).all()

    if len(reservas) != len(set(reserva_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alguna reserva no pertenece a esta clase o fue cancelada")

    rol = current_user.get("rol", "")
    marcada_por = current_user["usuario_id"]
    via = "coach" if rol == "coach" else "admin"
    ahora = ahora_santiago()

    mapa = {r.id: r for r in reservas}
    for item in body.asistencias:
        r = mapa[item.reserva_id]
        r.asistio = item.asistio
        r.asistencia_marcada_por = marcada_por
        r.asistencia_marcada_at = ahora
        r.asistencia_via = "batch"

    db.commit()

    return {
        "status": "ok",
        "clase_id": clase_id,
        "confirmados": len(body.asistencias),
        "via": via,
    }



# ── Alumno: resumen y hitos ──────────────────────────────────────────────────
@router.get("/mi-resumen")
def mi_resumen(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Racha actual, % del mes en curso y próximo hito del alumno autenticado."""
    tenant_id = current_user["tenant_id"]
    usuario_id = current_user["usuario_id"]
    return svc.resumen_alumno(db, usuario_id, tenant_id)


@router.get("/mis-hitos")
def mis_hitos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Logros (hitos) alcanzados por el alumno autenticado."""
    tenant_id = current_user["tenant_id"]
    usuario_id = current_user["usuario_id"]
    return {"hitos": svc.hitos_alumno_list(db, usuario_id, tenant_id)}


# ── n8n: evaluación mensual (webhook protegido con API key) ──────────────────
@router.post("/n8n/evaluar-mes")
def evaluar_mes_n8n(
    db: Session = Depends(get_db),
    x_n8n_api_key: str = Header(default="", alias="X-N8N-API-Key"),
    anio: Optional[int] = Query(None, description="Año a cerrar (default: mes anterior)"),
    mes: Optional[int] = Query(None, description="Mes a cerrar (default: mes anterior)"),
    tenant_id: Optional[int] = Query(None, description="Box a evaluar (default: todos)"),
):
    """Webhook mensual de n8n.

    Cierra el mes indicado (o el mes anterior si no se pasa) para cada alumno
    activo del/los tenant(s): calcula el %, dispara el correo de cumplimiento
    o acompañamiento y genera el hito de racha si corresponde.

    Idempotente: si n8n lo llama 2 veces el mismo mes, los dedupes
    (notificaciones_enviadas.mes_referencia + UNIQUE(alumno_id, nivel))
    evitan re-envíos y duplicados.
    """
    esperada = settings.N8N_API_KEY
    if not esperada or not secrets.compare_digest(esperada, x_n8n_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida para el endpoint de n8n")

    if (anio is None) != (mes is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="anio y mes deben ir juntos (o ninguno para cerrar el mes anterior)")
    if anio is None:
        hoy = hoy_santiago()
        anio, mes = svc._mes_anterior(hoy.year, hoy.month)
    if not (1 <= mes <= 12):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mes fuera de rango (1-12)")

    if tenant_id is not None:
        tenants = [tenant_id]
    else:
        tenants = [r[0] for r in db.query(Usuario.tenant_id).filter(
            Usuario.rol == RolUsuario.alumno,
            Usuario.activo == True,
        ).distinct().all()]

    resultados = []
    for tid in tenants:
        res = svc.evaluar_mes(db, tid, anio, mes)
        resultados.append(res)

    total_hitos = sum(r["hitos_generados"] for r in resultados)
    return {
        "status": "ok",
        "anio": anio,
        "mes": mes,
        "tenants_evaluados": len(resultados),
        "hitos_generados_total": total_hitos,
        "tenants": resultados,
    }

