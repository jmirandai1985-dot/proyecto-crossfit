"""
Router de endpoints para el Dashboard
"""
from app.schemas.dashboard import DashboardStats
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case, text
from datetime import datetime, timedelta, date
from app.db.database import get_db
from app.models.usuario import Usuario
from app.core.dependencies import get_current_admin, get_current_user

router = APIRouter()


@router.get("/{tenant_id}/ocupacion-hoy")
def ocupacion_hoy(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Devuelve las clases de HOY de CrossFit/Levantamiento Olimpico con coach.
    Requiere usuario autenticado."""
    hoy = date.today()
    rows = db.execute(text("""
        SELECT c.id, c.hora_inicio::text, d.nombre as disciplina,
               u.nombre as coach, c.cupo_maximo, c.asistentes_confirmados
        FROM clases c
        JOIN disciplinas d ON c.disciplina_id = d.id
        LEFT JOIN usuarios u ON c.coach_id = u.id
        WHERE c.fecha = :hoy
          AND c.tenant_id = :tid
          AND (d.nombre = 'CrossFit' OR d.nombre LIKE 'Levantamiento%')
          AND c.coach_id IS NOT NULL
        ORDER BY c.hora_inicio
    """), {"hoy": hoy, "tid": tenant_id}).fetchall()
    result = []
    for r in rows:
        ocupados = r[5] or 0
        cupo = r[4] or 1
        pct = round(ocupados / cupo * 100)
        if pct >= 100:
            estado = "Completo"
            color = "red"
        elif pct >= 80:
            estado = "Alta demanda"
            color = "amber"
        else:
            estado = "Disponibilidad"
            color = "green"
        result.append({
            "id": r[0], "hora": r[1][:5], "disciplina": r[2],
            "coach": r[3], "cupo": cupo, "ocupados": ocupados,
            "porcentaje": pct, "estado": estado, "color": color
        })
    return result


@router.get("/{tenant_id}", response_model=DashboardStats)
def obtener_estadisticas_dashboard(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: el admin solo puede ver su propio tenant
    if current_user.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes acceder al dashboard de otro tenant",
        )
    total_alumnos = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == 'alumno',
        Usuario.activo == True
    ).scalar() or 0

    total_suscripciones_activas = 0
    recaudacion_mes = 0
    asistencia_promedio = 0

    hace_una_semana = datetime.now() - timedelta(days=7)
    nuevos_alumnos_semana = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == 'alumno',
        Usuario.created_at >= hace_una_semana
    ).scalar() or 0

    return {
        "total_alumnos": total_alumnos,
        "total_suscripciones_activas": total_suscripciones_activas,
        "recaudacion_mes": recaudacion_mes,
        "asistencia_promedio": asistencia_promedio,
        "nuevos_alumnos_semana": nuevos_alumnos_semana
    }
