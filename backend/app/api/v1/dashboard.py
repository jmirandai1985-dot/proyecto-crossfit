"""
Router de endpoints para el Dashboard
"""
from app.schemas.dashboard import DashboardStats
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case, text
from datetime import datetime, timedelta
from app.db.database import get_db
from typing import Optional
from app.models.usuario import Usuario
from app.core.dependencies import get_current_admin, get_current_user
from app.utils.santiago import hoy_santiago   # HOY en Chile (la TZ del proceso es UTC)

router = APIRouter()


@router.get("/{tenant_id}/ocupacion-hoy")
def ocupacion_hoy(
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Devuelve las clases de HOY de CrossFit/Levantamiento Olimpico con coach.
    Requiere usuario autenticado. 🔒 SEGURIDAD: tenant_id del token (el path param se ignora)."""
    # 🔒 SEGURIDAD: tenant_id del token; el path param se ignora.
    tenant_id = current_user["tenant_id"]
    hoy = hoy_santiago()
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
        # T12: `estado` es la fuente de verdad del "habilitado"; `activo` es derivado y el
        # CHECK `ck_usuarios_activo_estado` lo mantiene igual, así que leerlo sería una
        # segunda definición de lo mismo.
        Usuario.estado == "activo"
    ).scalar() or 0

    # ⚠️ `total_suscripciones_activas` y `recaudacion_mes` se ELIMINARON de esta respuesta
    # (2026-10): eran dos constantes en 0 que no consumía nadie (el dashboard admin arma sus
    # tarjetas con GET /reportes/, /dashboard/{id}/ocupacion-hoy y los KPIs). Un campo fijo en 0
    # se lee como un dato del box ("0 suscripciones activas", "0 recaudado") cuando en realidad es
    # "no calculado": devolverlo era peor que no devolverlo. Si alguna vez se necesita, se calcula
    # con la definición COMPARTIDA (`metricas_service.alumnos_vigentes` / `ingresos_netos`), no con
    # un cero escrito a mano.
    # `asistencia_promedio` sigue en 0 por el mismo motivo, pero NO se tocó en este cambio.
    asistencia_promedio = 0
    hace_una_semana = datetime.now() - timedelta(days=7)
    nuevos_alumnos_semana = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == 'alumno',
        Usuario.created_at >= hace_una_semana
    ).scalar() or 0

    return {
        "total_alumnos": total_alumnos,
        "asistencia_promedio": asistencia_promedio,
        "nuevos_alumnos_semana": nuevos_alumnos_semana
    }
