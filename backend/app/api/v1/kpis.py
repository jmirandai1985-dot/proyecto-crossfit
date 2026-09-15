"""Endpoints de KPIs / Data Marts (BI) para el panel admin.

Consumen las tablas analíticas (daily_kpis, monthly_kpis, predictions_churn,
predictions_forecast) + `churn_gestion` (dato de NEGOCIO: la gestión del riesgo
vive en tabla propia para que el full refresh de la data mart no la borre).

Todos filtran por `tenant_id` del token JWT (nunca por query/body).
"""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.dependencies import get_current_admin, get_current_user
from app.models.asistencia import Asistencia
from app.models.churn_gestion import ChurnGestion
from app.models.daily_kpis import DailyKpi
from app.models.monthly_kpis import MonthlyKpi
from app.models.notificacion_enviada import NotificacionEnviada
from app.models.predictions_churn import PredictionsChurn
from app.models.predictions_forecast import PredictionsForecast
from app.models.segmentacion_alumno import SegmentacionAlumno
from app.models.usuario import Usuario
from app.services.auditoria_service import registrar_auditoria

router = APIRouter(prefix="/api/v1/kpis", tags=["KPIs"])

# ── Bloques de la pestaña BI ─────────────────────────────────────────────────
# Días por mes promedio (365.25 / 12): base para pasar días a meses en la vida
# promedio de un alumno (insumo del LTV).
DIAS_POR_MES = 30.44

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


def _arquetipo_por_alumno(db: Session, tenant_id: int, ids: list) -> dict:
    """{usuario_id: {arquetipo, cluster_id, perfil, modelo_fecha}} de la segmentación.

    Una sola query (sin N+1), mismo patrón que `_ultimo_contacto_por_alumno`.
    `segmentacion_alumnos` es un full refresh: un alumno tiene 1 fila o NINGUNA
    (si el reentrenamiento todavía no corrió) -> .get() devuelve None y el panel
    lo muestra como "Sin segmentar". Un `perfil_json` corrupto no rompe la fila:
    la etiqueta es lo importante.
    """
    if not ids:
        return {}
    filas = db.query(SegmentacionAlumno).filter(
        SegmentacionAlumno.tenant_id == tenant_id,
        SegmentacionAlumno.usuario_id.in_(ids),
    ).all()
    salida = {}
    for f in filas:
        perfil = None
        if f.perfil_json:
            try:
                perfil = json.loads(f.perfil_json)
            except (TypeError, ValueError):
                perfil = None
        salida[f.usuario_id] = {
            "arquetipo": f.arquetipo,
            "cluster_id": f.cluster_id,
            "perfil": perfil,
            "modelo_fecha": (f.modelo_fecha.isoformat()
                             if f.modelo_fecha else None),
        }
    return salida


def _fila_churn(p, nombre, correo, estado_gestion, ultimo_contacto,
                arquetipo=None) -> dict:
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
        "arquetipo": arquetipo,
        "fecha_proxima_renovacion": p.fecha_proxima_renovacion,
        "ultimo_contacto_automatico": ultimo_contacto,
    }


# ── Insights automáticos (resumen ejecutivo del churn) ───────────────────────
# Pool fijo de reglas DETERMINISTAS (sin NLP ni modelos nuevos): agrupan datos
# que el data mart ya tiene y devuelven 1-2 frases accionables. Se incluyen las
# métricas que originan cada frase (auditable) y, si nada supera las guardas,
# un mensaje neutral.
INSIGHT_NEUTRAL = "Sin alertas relevantes esta semana."

# Buckets de inactividad (días sin asistir) para la concentración del crítico.
INSIGHT_BUCKETS = (
    (0, 30, "0-30", "hasta 1 mes"),
    (31, 60, "31-60", "entre 1 y 2 meses"),
    (61, 90, "61-90", "entre 2 y 3 meses"),
    (91, None, "+90", "más de 3 meses"),
)
# Guardas: sin estos mínimos el dato no es representativo (evita "insights"
# construidos sobre 1-2 alumnos).
INSIGHT_MIN_CRITICOS = 3
INSIGHT_MIN_PCT = 40


def _dias_inactividad_por_alumno(db: Session, tenant_id: int, ids: list) -> dict:
    """{usuario_id: días sin asistir} con UNA query agregada (sin N+1).

    Misma fórmula que `kpis_populate._dias_inactividad` y `ml.features`:
    días desde la última asistencia y, si nunca asistió, desde el registro.
    """
    if not ids:
        return {}
    referencia = func.coalesce(
        func.max(Asistencia.fecha), func.date(Usuario.created_at))
    filas = db.query(Usuario.id, referencia).outerjoin(
        Asistencia,
        (Asistencia.usuario_id == Usuario.id)
        & (Asistencia.tenant_id == Usuario.tenant_id),
    ).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.id.in_(ids),
    ).group_by(Usuario.id, Usuario.created_at).all()

    hoy = date.today()
    return {uid: max(0, (hoy - ref).days) for uid, ref in filas if ref}


def _generar_insight(filas: list, dias_por_alumno: dict) -> dict:
    """Resumen ejecutivo (1-2 frases) con reglas deterministas.

    `filas`: filas ya armadas por `_fila_churn` (usa riesgo_nivel y
    fecha_proxima_renovacion). `dias_por_alumno`: ver _dias_inactividad_por_alumno.

    Reglas (en orden; se agrega la frase sólo si pasa su guarda):
      A. concentracion_critico: dónde se concentra el riesgo CRITICO por rango de
         inactividad (requiere >= 3 críticos con dato y un bucket top >= 40%).
      B. riesgo_con_plan: cuántos ALTO/CRITICO tienen plan vigente y cuántos
         vencen en <= 7 días (basta con 1).
    Sin reglas activas -> mensaje neutral.
    """
    mensajes, reglas = [], []
    criticos = [f for f in filas if f.get("riesgo_nivel") == "CRITICO"]

    # ── Métricas base (siempre, para que el payload sea auditable) ──
    buckets = {clave: 0 for _lo, _hi, clave, _txt in INSIGHT_BUCKETS}
    conocidos = 0
    for f in criticos:
        dias = dias_por_alumno.get(f["usuario_id"])
        if dias is None:
            continue
        conocidos += 1
        for lo, hi, clave, _txt in INSIGHT_BUCKETS:
            if dias >= lo and (hi is None or dias <= hi):
                buckets[clave] += 1
                break

    con_plan = [f for f in filas
                if f.get("riesgo_nivel") in ("ALTO", "CRITICO")
                and f.get("fecha_proxima_renovacion")]
    limite = date.today() + timedelta(days=7)
    vencen = [f for f in con_plan if f["fecha_proxima_renovacion"] <= limite]

    metricas = {
        "criticos": len(criticos),
        "criticos_con_dato": conocidos,
        "buckets": buckets,
        "alto_critico_con_plan": len(con_plan),
        "vencen_7d": len(vencen),
    }

    # ── A) Concentración del riesgo crítico por inactividad ──
    if conocidos >= INSIGHT_MIN_CRITICOS:
        # Desempate determinista: más alumnos y, si empatan, el rango mayor.
        orden = [b[2] for b in INSIGHT_BUCKETS]
        top_clave, top_n = max(
            buckets.items(), key=lambda kv: (kv[1], orden.index(kv[0])))
        pct = round(top_n / conocidos * 100)
        metricas["top_bucket"] = top_clave
        metricas["top_pct"] = pct
        if top_n > 0 and pct >= INSIGHT_MIN_PCT:
            rango_txt = next(t for _lo, _hi, c, t in INSIGHT_BUCKETS
                             if c == top_clave)
            mensajes.append(
                f"El {pct}% del riesgo crítico ({top_n} de {conocidos}) "
                f"lleva {rango_txt} sin asistir.")
            reglas.append("concentracion_critico")

    # ── B) Riesgo alto/crítico con plan vigente ──
    if con_plan:
        n, m = len(con_plan), len(vencen)
        texto = (f"Hay {n} {'alumno' if n == 1 else 'alumnos'} con plan activo "
                 f"y riesgo alto o crítico")
        if vencen:
            texto += (f": {m} {'vence' if m == 1 else 'vencen'} en 7 días o "
                      f"menos — conviene revisarlos antes de que venza el plan.")
        else:
            texto += " — conviene revisarlos antes de que venza su plan."
        mensajes.append(texto)
        reglas.append("riesgo_con_plan")

    if not mensajes:
        mensajes = [INSIGHT_NEUTRAL]

    return {"mensajes": mensajes, "reglas": reglas, "metricas": metricas}


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
    - `arquetipo`: segmentación vigente del alumno (tabla
      `segmentacion_alumnos`), o None si el reentrenamiento no corrió.
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
    dias_inactivo = _dias_inactividad_por_alumno(db, tenant_id, ids)
    arquetipos = _arquetipo_por_alumno(db, tenant_id, ids)

    criticos = sum(1 for p, _n, _c in filas if p.riesgo_nivel == "CRITICO")
    altos = sum(1 for p, _n, _c in filas if p.riesgo_nivel == "ALTO")
    medios = sum(1 for p, _n, _c in filas if p.riesgo_nivel == "MEDIO")

    predicciones = [
        _fila_churn(
            p, nombre, correo,
            gestion.get(p.usuario_id, ESTADO_GESTION_DEFAULT),
            contactos.get(p.usuario_id),
            arquetipos.get(p.usuario_id),
        )
        for p, nombre, correo in filas
    ]

    return {
        "predicciones": predicciones,
        "total": len(filas),
        "criticos": criticos,
        "altos": altos,
        "medios": medios,
        # Resumen ejecutivo (1-2 frases + métricas que lo originan).
        "insight": _generar_insight(predicciones, dias_inactivo),
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
    arquetipos = _arquetipo_por_alumno(db, tenant_id, [usuario_id])
    fila = _fila_churn(p, nombre, correo, data.estado_gestion,
                       contactos.get(usuario_id),
                       arquetipos.get(usuario_id))
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



# ── 6.b) Bloques horarios (pico vs valle) ────────────────────────────────────
# Los turnos los define el HORARIO REAL del box (07-10, 11-15, 16-21); se evita
# inventar franjas que el box no usa.
BLOQUES_HORARIOS = (
    ("Mañana (07:00-10:59)", 7, 10),
    ("Mediodía (11:00-15:59)", 11, 15),
    ("Tarde-noche (16:00-21:59)", 16, 21),
)


# ── 6) GET /api/v1/kpis/financiero (BI - bloque financiero) ──────────────────
# ⚠️ ARPU NO se calcula acá A PROPÓSITO: ya existe en `GET /api/v1/reportes/`
# (ingresos netos del mes / alumnos activos; la misma definición que muestra
# Reportes.jsx) y se reusa desde el frontend, que compone el LTV:
#     LTV = ARPU × vida_promedio_meses
@router.get("/financiero")
def get_financiero(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Bloque financiero del BI: ticket promedio por plan + vida promedio.

    - `ticket_promedio`: avg(monto) de las transacciones REALES de membresía
      (`transacciones_financieras`: tipo=ingreso, categoria=membresia,
      referencia_tipo=suscripcion) agrupadas por el plan de la suscripción, más
      el global. Se usan las transacciones y no el precio de lista para capturar
      descuentos/compras de emergencia si algún día existen.
    - `vida`: promedio de (fecha_baja o hoy - created_at) de los alumnos del
      tenant, en días y en meses -> insumo del LTV.
    - NO se calcula CAC: la base no tiene costo de adquisición (no se inventa).
    """
    tenant_id = current_user["tenant_id"]

    planes = db.execute(sql_text("""
        SELECT p.nombre,
               p.precio_clp,
               COUNT(DISTINCT s.id) AS suscripciones,
               COUNT(t.id) AS n_transacciones,
               COALESCE(ROUND(AVG(t.monto)), 0) AS ticket,
               COALESCE(SUM(t.monto), 0) AS ingreso_total
        FROM planes p
        LEFT JOIN suscripciones s
               ON s.plan_id = p.id AND s.tenant_id = :tid
        LEFT JOIN transacciones_financieras t
               ON t.referencia_id = s.id
              AND t.referencia_tipo = 'suscripcion'
              AND t.categoria = 'membresia'
              AND t.tipo = 'ingreso'
              AND t.tenant_id = :tid
        WHERE p.tenant_id = :tid
        GROUP BY p.id, p.nombre, p.precio_clp
        ORDER BY ingreso_total DESC, suscripciones DESC
    """), {"tid": tenant_id}).fetchall()

    global_tx = db.execute(sql_text("""
        SELECT COUNT(*),
               COALESCE(ROUND(AVG(monto)), 0),
               COALESCE(SUM(monto), 0)
        FROM transacciones_financieras
        WHERE tenant_id = :tid AND tipo = 'ingreso' AND categoria = 'membresia'
    """), {"tid": tenant_id}).first()

    # Vida del alumno: fecha_baja si está dado de baja; si no, hoy (censura a la
    # derecha, documentada en `limitaciones`).
    vida = db.execute(sql_text("""
        SELECT COUNT(*) AS n_alumnos,
               COUNT(*) FILTER (WHERE fecha_baja IS NOT NULL) AS n_con_baja,
               COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM (
                   COALESCE(fecha_baja::timestamptz, NOW()) - created_at
               )) / 86400.0)), 0) AS vida_dias
        FROM usuarios
        WHERE tenant_id = :tid AND rol = 'alumno'
    """), {"tid": tenant_id}).first()

    vida_dias = int(vida[2] or 0)
    return {
        "moneda": "CLP",
        "ticket_promedio": {
            "global": float(global_tx[1] or 0),
            "n_transacciones": int(global_tx[0] or 0),
            "ingreso_total": float(global_tx[2] or 0),
            "criterio": (
                "avg(monto) de transacciones_financieras (tipo=ingreso, "
                "categoria=membresia, referencia_tipo=suscripcion) agrupado por "
                "el plan de la suscripción"),
            "por_plan": [
                {
                    "plan": r[0],
                    "precio_lista": int(r[1] or 0),
                    "suscripciones": int(r[2] or 0),
                    "n_transacciones": int(r[3] or 0),
                    "ticket_promedio": float(r[4] or 0),
                    "ingreso_total": float(r[5] or 0),
                }
                for r in planes
            ],
        },
        "vida": {
            "vida_promedio_dias": vida_dias,
            "vida_promedio_meses": round(vida_dias / DIAS_POR_MES, 2),
            "n_alumnos": int(vida[0] or 0),
            "n_con_baja": int(vida[1] or 0),
            "formula": (
                "promedio de (fecha_baja o hoy - created_at) de los alumnos del "
                f"tenant, en días / {DIAS_POR_MES}"),
            "limitaciones": (
                "censura a la derecha: los alumnos activos aportan su antigüedad "
                "actual, así que la vida real de quien dure más queda subestimada"),
        },
        "ltv_formula": (
            "LTV = ARPU mensual (GET /api/v1/reportes/) × vida_promedio_meses"),
        "nota_cac": (
            "No se calcula CAC: la base no tiene costo de adquisición. Sin CAC no "
            "hay payback ni ratio LTV/CAC."),
    }



# ── 7) GET /api/v1/kpis/bloques-horarios (BI - pico vs valle) ────────────────
@router.get("/bloques-horarios")
def get_bloques_horarios(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Oferta y asistencia por bloque horario (pico vs valle).

    - `clases` y `cupo_promedio` son REALES (tabla `clases`).
    - `asistencias` / `asistencias_por_clase` salen del join REAL
      `asistencias.clase_id -> clases.hora_inicio`.
      ⚠️ Hoy `asistencias.clase_id` es NULL en el 100% de las filas (el propio
      modelo lo documenta: "se poblarán desde reservas en una limpieza futura"),
      así que dan 0. `cobertura` expone el alcance para que la UI distinga
      "0 asistencias" de "sin datos": cuando el backfill corra, el promedio se
      activa solo, sin tocar código.
    """
    tenant_id = current_user["tenant_id"]

    filas = db.execute(sql_text("""
        SELECT EXTRACT(HOUR FROM c.hora_inicio)::int AS hora,
               COUNT(DISTINCT c.id) AS clases,
               ROUND(AVG(c.cupo_maximo), 1) AS cupo_promedio,
               COUNT(a.id) AS asistencias
        FROM clases c
        LEFT JOIN asistencias a
               ON a.clase_id = c.id
              AND a.tenant_id = c.tenant_id
              AND a.presente = true
        WHERE c.tenant_id = :tid AND c.cancelada = false
        GROUP BY 1 ORDER BY 1
    """), {"tid": tenant_id}).fetchall()

    cobertura = db.execute(sql_text("""
        SELECT COUNT(*) AS total, COUNT(clase_id) AS con_clase
        FROM asistencias WHERE tenant_id = :tid
    """), {"tid": tenant_id}).first()

    por_hora = [
        {
            "hora": int(r[0]),
            "clases": int(r[1] or 0),
            "cupo_promedio": float(r[2] or 0),
            "asistencias": int(r[3] or 0),
            "asistencias_por_clase": round((r[3] or 0) / r[1], 2) if r[1] else 0.0,
        }
        for r in filas
    ]

    bloques = []
    for nombre, desde, hasta in BLOQUES_HORARIOS:
        horas = [h for h in por_hora if desde <= h["hora"] <= hasta]
        clases = sum(h["clases"] for h in horas)
        asis = sum(h["asistencias"] for h in horas)
        cupo = (round(sum(h["cupo_promedio"] * h["clases"] for h in horas) / clases, 1)
                if clases else 0.0)
        bloques.append({
            "bloque": nombre,
            "horas": [h["hora"] for h in horas],
            "clases": clases,
            "cupo_promedio": float(cupo or 0),
            "asistencias": asis,
            "asistencias_por_clase": round(asis / clases, 2) if clases else 0.0,
            "ocupacion_pct": round(asis / (cupo * clases) * 100, 1)
                             if (clases and cupo) else 0.0,
        })

    total_asis = int(cobertura[0] or 0)
    con_clase = int(cobertura[1] or 0)
    return {
        "criterio": (
            "clases/cupo reales de `clases` (no canceladas); asistencias por el "
            "join `asistencias.clase_id -> clases.hora_inicio`"),
        "cobertura": {
            "asistencias_total": total_asis,
            "con_clase": con_clase,
            "pct": round(con_clase / total_asis * 100, 1) if total_asis else 0.0,
            "nota": (
                "Las asistencias todavía no están asociadas a su clase "
                "(`asistencias.clase_id` nulo): el promedio por bloque se activa "
                "cuando se corra el backfill desde reservas. Mientras tanto se "
                "muestra la oferta real (clases y cupo)."),
        },
        "bloques": bloques,
        "por_hora": por_hora,
    }
