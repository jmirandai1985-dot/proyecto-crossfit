"""Endpoints de KPIs / Data Marts (BI) para el panel admin.

Consumen las tablas analíticas (daily_kpis, monthly_kpis, predictions_churn,
predictions_forecast) + `churn_gestion` (dato de NEGOCIO: la gestión del riesgo
vive en tabla propia para que el full refresh de la data mart no la borre).

Todos filtran por `tenant_id` del token JWT (nunca por query/body).
"""
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.dependencies import get_current_admin, get_current_user
from app.models.churn_gestion import ChurnGestion
from app.models.daily_kpis import DailyKpi
from app.models.monthly_kpis import MonthlyKpi
from app.models.notificacion_enviada import NotificacionEnviada
from app.models.predictions_churn import PredictionsChurn
from app.models.predictions_forecast import PredictionsForecast
from app.models.usuario import Usuario
from app.services.auditoria_service import registrar_auditoria

router = APIRouter(prefix="/api/v1/kpis", tags=["KPIs"])

# ── Gestión del riesgo de abandono (dato de negocio en `churn_gestion`) ──────
# Un alumno SIN fila en churn_gestion se considera PENDIENTE (no se crea fila
# hasta que un admin lo gestione con el PUT).
ESTADO_GESTION_DEFAULT = "PENDIENTE"


class EstadoGestionUpdate(BaseModel):
    """Body del PUT: un label inválido responde 422 (validación de Pydantic)."""

    estado_gestion: Literal["PENDIENTE", "CONTACTADO", "RECUPERADO"]


def _gestion_por_alumno(db: Session, tenant_id: int, ids: list) -> dict:
    """{usuario_id: estado_gestion} de los alumnos que YA tienen fila."""
    if not ids:
        return {}
    filas = db.query(ChurnGestion).filter(
        ChurnGestion.tenant_id == tenant_id,
        ChurnGestion.usuario_id.in_(ids),
    ).all()
    return {g.usuario_id: g.estado_gestion for g in filas}


def _ultimo_contacto_por_alumno(db: Session, tenant_id: int, ids: list) -> dict:
    """{usuario_id: {tipo, fecha, hace_dias}} del último correo ENVIADO.

    Una sola query (ORDER BY desc + "el primero gana"), sin N+1. Los correos
    automáticos de retención quedan registrados en `notificaciones_enviadas`.

    ⚠️ NO se filtra por `notificaciones_enviadas.tenant_id`: ese campo quedó
    NULL en los envíos del scheduler (el registro de envío no lo setea) y
    filtrarlo escondería TODAS las filas. `ids` ya viene scopeado al tenant
    (son los `usuario_id` de `predictions_churn` del token) y un usuario
    pertenece a un solo tenant, así que el filtro por alumno_id alcanza.
    """
    if not ids:
        return {}
    recientes = db.query(NotificacionEnviada).filter(
        NotificacionEnviada.alumno_id.in_(ids),
        NotificacionEnviada.estado == "enviado",
    ).order_by(
        NotificacionEnviada.alumno_id,
        NotificacionEnviada.fecha_envio.desc(),
        NotificacionEnviada.id.desc(),
    ).all()

    ultimo = {}
    for n in recientes:
        ultimo.setdefault(n.alumno_id, n)   # el 1º de cada alumno = el más reciente

    hoy = date.today()
    return {
        uid: {
            "tipo": n.tipo,
            "fecha": n.fecha_envio.date().isoformat(),
            "hace_dias": (hoy - n.fecha_envio.date()).days,
        }
        for uid, n in ultimo.items() if n.fecha_envio
    }


def _fila_churn(p, nombre, correo, estado_gestion, ultimo_contacto) -> dict:
    """Formato de fila que consume el frontend (GET y PUT responden igual)."""
    return {
        "usuario_id": p.usuario_id,
        "alumno_nombre": nombre,
        "alumno_correo": correo,
        "probabilidad_churn": float(p.probabilidad_churn),
        "riesgo_nivel": p.riesgo_nivel,
        "motivo": p.motivo,
        "recomendacion": p.recomendacion,
        "recomendacion_codigo": p.recomendacion_codigo,
        "estado_gestion": estado_gestion,
        "fecha_proxima_renovacion": p.fecha_proxima_renovacion,
        "ultimo_contacto_automatico": ultimo_contacto,
    }


# ── 1) GET /api/v1/kpis/diario (pestaña DIARIA) ──────────────────────────────
@router.get("/diario")
def get_kpis_diario(
    fecha: date = Query(None, description="Fecha específica (YYYY-MM-DD); default: hoy"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """KPIs del día para la pestaña DIARIA."""
    tenant_id = current_user["tenant_id"]
    if not fecha:
        fecha = date.today()

    kpi = db.query(DailyKpi).filter(
        DailyKpi.tenant_id == tenant_id,
        DailyKpi.fecha == fecha,
    ).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI diario no encontrado")

    return {
        "fecha": kpi.fecha,
        "alumnos_activos": kpi.alumnos_activos,
        "alumnos_nuevos": kpi.alumnos_nuevos,
        "clases_ejecutadas": kpi.clases_ejecutadas,
        "asistentes_totales": kpi.asistentes_totales,
        "ocupacion_promedio": float(kpi.ocupacion_promedio),
        "ingresos_membresia": float(kpi.ingresos_membresia),
        "ingresos_bazar": float(kpi.ingresos_bazar),
        "ingresos_total": float(kpi.ingresos_total),
        "reservas_confirmadas": kpi.reservas_confirmadas,
        "cancellaciones": kpi.cancellaciones,
    }


# ── 2) GET /api/v1/kpis/mensual (pestaña MENSUAL) ────────────────────────────
@router.get("/mensual")
def get_kpis_mensual(
    year: int = Query(..., description="Año (YYYY)"),
    month: int = Query(..., description="Mes (1-12)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """KPIs del mes para la pestaña MENSUAL."""
    tenant_id = current_user["tenant_id"]

    kpi = db.query(MonthlyKpi).filter(
        MonthlyKpi.tenant_id == tenant_id,
        MonthlyKpi.year == year,
        MonthlyKpi.month == month,
    ).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI mensual no encontrado")

    return {
        "year": kpi.year,
        "month": kpi.month,
        "alumnos_prueba": kpi.alumnos_prueba,
        "alumnos_clase_prueba_ejecutada": kpi.alumnos_clase_prueba_ejecutada,
        "alumnos_plan_comprado": kpi.alumnos_plan_comprado,
        "conversion_rate": float(kpi.conversion_rate),
        "alumnos_activos_inicio": kpi.alumnos_activos_inicio,
        "alumnos_baja": kpi.alumnos_baja,
        "churn_rate": float(kpi.churn_rate),
        "mrr": float(kpi.mrr),
        "ingresos_total": float(kpi.ingresos_total),
        "asistencia_promedio": float(kpi.asistencia_promedio),
        "frecuencia_semanal": float(kpi.frecuencia_semanal),
        "ocupacion_promedio": float(kpi.ocupacion_promedio),
    }


# ── 3) GET /api/v1/kpis/churn (BI - CHURN) ───────────────────────────────────
@router.get("/churn")
def get_predictions_churn(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Predicciones de CHURN del box (array + conteos por nivel).

    - `alumno_nombre`/`alumno_correo`: join con `usuarios` (None si el alumno ya
      no existe) para que el panel no muestre el `usuario_id` crudo.
    - `estado_gestion`: se resuelve contra la tabla propia `churn_gestion`
      (dato de negocio que el refresh del data mart NO toca). Si el alumno
      todavía no tiene fila, se devuelve 'PENDIENTE' sin crearla.
    - `ultimo_contacto_automatico`: último correo automático ENVIADO (o None).
    """
    tenant_id = current_user["tenant_id"]

    # outerjoin: si el alumno fue borrado, la predicción igual se devuelve
    # (con nombre None) en vez de desaparecer de la lista.
    filas = db.query(
        PredictionsChurn, Usuario.nombre, Usuario.correo,
    ).outerjoin(
        Usuario, Usuario.id == PredictionsChurn.usuario_id,
    ).filter(
        PredictionsChurn.tenant_id == tenant_id,
    ).all()

    ids = [p.usuario_id for p, _n, _c in filas]
    gestion = _gestion_por_alumno(db, tenant_id, ids)
    contactos = _ultimo_contacto_por_alumno(db, tenant_id, ids)

    criticos = sum(1 for p, _n, _c in filas if p.riesgo_nivel == "CRITICO")
    altos = sum(1 for p, _n, _c in filas if p.riesgo_nivel == "ALTO")
    medios = sum(1 for p, _n, _c in filas if p.riesgo_nivel == "MEDIO")

    return {
        "predicciones": [
            _fila_churn(
                p, nombre, correo,
                gestion.get(p.usuario_id, ESTADO_GESTION_DEFAULT),
                contactos.get(p.usuario_id),
            )
            for p, nombre, correo in filas
        ],
        "total": len(filas),
        "criticos": criticos,
        "altos": altos,
        "medios": medios,
    }


# ── 3b) PUT /api/v1/kpis/churn/{usuario_id}/estado (gestión del riesgo) ──────
@router.put("/churn/{usuario_id}/estado")
def actualizar_estado_gestion_churn(
    usuario_id: int,
    data: EstadoGestionUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Marca la GESTIÓN del riesgo de un alumno (solo admin logueado).

    - Auth: JWT de administrador (`get_current_admin`), NO la API key de n8n.
    - UPSERT en la tabla propia `churn_gestion` (al refrescar el data mart NO se
      pierde) guardando `actualizado_por` (del token) y `actualizado_en=now()`.
    - Audita SOLO si el estado cambió.
    - 404 si el alumno no tiene predicción de churn en este box.
    Devuelve la fila del churn (mismo formato que el GET) + `estado_anterior`.
    """
    tenant_id = current_user["tenant_id"]
    admin_id = current_user["usuario_id"]

    pred = db.query(
        PredictionsChurn, Usuario.nombre, Usuario.correo,
    ).outerjoin(
        Usuario, Usuario.id == PredictionsChurn.usuario_id,
    ).filter(
        PredictionsChurn.tenant_id == tenant_id,
        PredictionsChurn.usuario_id == usuario_id,
    ).first()
    if not pred:
        raise HTTPException(
            status_code=404,
            detail=(f"No hay predicción de churn para el alumno "
                    f"#{usuario_id} en este box"),
        )
    p, nombre, correo = pred

    # Estado anterior real (sin fila => el efectivo es el default).
    fila_gestion = db.query(ChurnGestion).filter(
        ChurnGestion.tenant_id == tenant_id,
        ChurnGestion.usuario_id == usuario_id,
    ).first()
    estado_anterior = (fila_gestion.estado_gestion if fila_gestion
                       else ESTADO_GESTION_DEFAULT)

    # UPSERT contra el UNIQUE (tenant_id, usuario_id) -> sin carrera posible.
    ahora = datetime.now(timezone.utc)
    db.execute(
        pg_insert(ChurnGestion).values(
            tenant_id=tenant_id,
            usuario_id=usuario_id,
            estado_gestion=data.estado_gestion,
            actualizado_por=admin_id,
            actualizado_en=ahora,
        ).on_conflict_do_update(
            index_elements=["tenant_id", "usuario_id"],
            set_={
                "estado_gestion": data.estado_gestion,
                "actualizado_por": admin_id,
                "actualizado_en": ahora,
            },
        )
    )
    db.commit()

    if estado_anterior != data.estado_gestion:
        registrar_auditoria(
            db,
            tenant_id=tenant_id,
            usuario_id=admin_id,
            accion="UPDATE",
            entidad="churn_gestion",
            entidad_id=usuario_id,
            detalle={
                "alumno_id": usuario_id,
                "antes": estado_anterior,
                "despues": data.estado_gestion,
            },
        )

    contactos = _ultimo_contacto_por_alumno(db, tenant_id, [usuario_id])
    fila = _fila_churn(p, nombre, correo, data.estado_gestion,
                       contactos.get(usuario_id))
    fila["estado_anterior"] = estado_anterior
    return fila


# ── 4) GET /api/v1/kpis/forecast (BI - FORECAST) ─────────────────────────────
@router.get("/forecast")
def get_predictions_forecast(
    meses: int = Query(3, description="Cuántos meses proyectar (default 3)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Pronóstico de ingresos para los próximos N meses."""
    tenant_id = current_user["tenant_id"]

    proyecciones = db.query(PredictionsForecast).filter(
        PredictionsForecast.tenant_id == tenant_id
    ).order_by(PredictionsForecast.mes_prediccion).limit(meses).all()

    return {
        "proyecciones": [
            {
                "mes_prediccion": p.mes_prediccion,
                "ingresos_predicho": float(p.ingresos_predicho),
                "intervalo_confianza": float(p.intervalo_confianza),
                "alumnos_predicho": p.alumnos_predicho,
                "tasa_crecimiento": float(p.tasa_crecimiento),
                "notas": p.notas,
            }
            for p in proyecciones
        ]
    }
