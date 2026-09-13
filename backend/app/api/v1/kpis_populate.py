"""Endpoints n8n para POBLAR los data marts de KPIs (BI).

Protegidos con header `X-N8N-API-Key` (= settings.N8N_API_KEY). Calculan y
persisten desde las tablas transaccionales:
  - POST /populate/daily        -> daily_kpis            (día anterior, o ?fecha=)
  - POST /populate/monthly      -> monthly_kpis          (mes anterior, o ?year=&month=)
  - POST /populate/predictions  -> predictions_churn + predictions_forecast

NOTA: `tenant_id` fijo en 1 (hoy hay un solo box). Parametrizable luego.
NOTA 2: la consigna venía truncada; los cálculos se completaron con el esquema real.
"""
import calendar
import logging
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.daily_kpis import DailyKpi
from app.models.monthly_kpis import MonthlyKpi
from app.models.predictions_churn import PredictionsChurn
from app.models.predictions_forecast import PredictionsForecast
from app.models.usuario import Usuario, RolUsuario
from app.models.suscripcion import Suscripcion
from app.models.reserva import Reserva
from app.models.clase import Clase
from app.models.plan import Plan
from app.models.asistencia import Asistencia
from app.models.transaccion_financiera import TransaccionFinanciera

router = APIRouter(prefix="/api/v1/kpis", tags=["KPIs - Populate"])

logger = logging.getLogger(__name__)

TENANT_ID = 1
ESTADOS_CANCELADA = ("cancelled", "cancelada")
PLAN_PRUEBA = "Prueba"


def _verificar_api_key_n8n(
    x_n8n_api_key: str = Header(default="", alias="X-N8N-API-Key"),
) -> bool:
    """Valida `X-N8N-API-Key` contra settings.N8N_API_KEY (401 si no coincide)."""
    esperada = settings.N8N_API_KEY
    if not esperada or not secrets.compare_digest(esperada, x_n8n_api_key):
        raise HTTPException(
            status_code=401, detail="API key inválida para el endpoint de n8n")
    return True


def _sum_ingresos(db, tenant_id, desde, hasta, categoria=None):
    """SUM de `transacciones_financieras` (tipo=ingreso) en un rango de fechas."""
    q = db.query(func.coalesce(func.sum(TransaccionFinanciera.monto), 0)).filter(
        TransaccionFinanciera.tenant_id == tenant_id,
        TransaccionFinanciera.tipo == "ingreso",
        TransaccionFinanciera.fecha >= desde,
        TransaccionFinanciera.fecha <= hasta,
    )
    if categoria:
        q = q.filter(TransaccionFinanciera.categoria == categoria)
    return float(q.scalar() or 0)


def _sum_egresos(db, tenant_id, desde, hasta):
    """SUM de `transacciones_financieras` (tipo=egreso) en un rango de fechas."""
    return float(db.query(
        func.coalesce(func.sum(TransaccionFinanciera.monto), 0)
    ).filter(
        TransaccionFinanciera.tenant_id == tenant_id,
        TransaccionFinanciera.tipo == "egreso",
        TransaccionFinanciera.fecha >= desde,
        TransaccionFinanciera.fecha <= hasta,
    ).scalar() or 0)


def _ultima_asistencia(db, tenant_id, usuario_id):
    """Fecha de la última asistencia registrada (tabla `asistencias`)."""
    return db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == usuario_id,
    ).scalar()


def _dias_inactividad(hoy, ultima, created_at):
    """
    Días de inactividad de un alumno, para el cálculo de churn.

    BUGFIX (999 días): antes se devolvía el valor fijo 999 cuando `ultima` era
    None, lo que marcaba como CRITICO a un alumno recién inscrito que todavía no
    tomó ninguna clase, igual que a alguien que abandonó hace meses. Son casos
    distintos, así que si no hay asistencias se mide desde la fecha de registro
    del alumno. Equivale a COALESCE(max(asistencias.fecha), usuarios.created_at).

    - Con asistencias  -> días desde la última asistencia real (como antes).
    - Sin asistencias  -> días desde `created_at` (riesgo bajo/normal si es nuevo).
    """
    referencia = ultima or (created_at.date() if created_at else None)
    if referencia is None:
        return 0
    return max(0, (hoy - referencia).days)


def _plural_dias(n) -> str:
    """'día' si n == 1, 'días' en cualquier otro caso (motivos legibles)."""
    return "día" if n == 1 else "días"


# ── Recomendación de acción (texto empático + código para la UI) ─────────────
# Los textos viven acá (un solo lugar) y el código es estable para que el
# frontend pueda colorear/filtrar sin parsear el texto.
RECO_SIN_PLAN = (
    "Alumno sin actividad y sin plan vigente. Te recomendamos contactarlo "
    "personalmente para indagar qué está pasando —podría ser tiempo, motivación "
    "o un tema económico. Si es económico, considerá ofrecerle una alternativa "
    "(clase de cortesía, descuento temporal) para facilitar que vuelva."
)
RECO_CRITICO_CON_PLAN = (
    "Su plan está activo pero las señales de riesgo son críticas. Contactalo con "
    "prioridad: no lo trates como un recordatorio más —preguntale cómo está de "
    "verdad y si algo del box (horario, clima, precio, lesión) le está jugando "
    "en contra."
)
RECO_CAIDA_RECIENTE = (
    "Su asistencia bajó fuerte aunque su plan sigue activo. Es un buen momento "
    "para un mensaje cercano preguntando cómo está y si el horario le sigue "
    "acomodando —a veces alcanza con ajustar la rutina."
)
RECO_RENOVACION_PROXIMA = (
    "Su plan vence pronto y sigue entrenando con normalidad. Es buen momento "
    "para mandarle el recordatorio de renovación antes de que se le pase la fecha."
)
RECO_SIN_ACCION = "Todo en orden, sin acción necesaria."

RECO_CODIGOS = ("sin_plan", "critico_con_plan", "caida_reciente",
                "renovacion_proxima", "sin_accion")


def _recomendacion_churn(nivel, tiene_suscripcion, dias_para_vencer,
                         asis_30, asis_90) -> tuple:
    """(texto, código) de la recomendación (gana la PRIMERA regla que aplica).

      1. CRITICO/ALTO/MEDIO sin plan vigente -> contacto personal (posible tema económico)
      2. CRITICO con plan vigente            -> contacto prioritario (plan activo, señales fuertes)
      3. ALTO/MEDIO con plan y caída fuerte  -> mensaje cercano (revisar rutina/horario)
      4. Vence en <=7 días y BAJO/MEDIO      -> recordatorio de renovación
      5. Resto                               -> "Todo en orden..."

    "Caída fuerte" = asistencias 30d < asistencias 90d / 3 (ritmo reciente por
    debajo de un tercio del histórico trimestral). Proxy explícito, sin queries.

    La #1 cubre CUALQUIER nivel no-BAJO sin plan vigente: así ningún alumno "en
    riesgo y sin plan" queda con la recomendación neutra de la #5 (antes un
    MEDIO sin plan caía en "Todo en orden", que era engañoso).

    ⚠️ BORDE CONOCIDO (regla literal a propósito, ver consigna):
      - Con asistencias_90d == 0 el proxy de la #3 da `0 < 0` = False -> no la
        dispara (un ALTO/MEDIO con plan y 90d en cero cae a la #5).
    """
    if nivel in ("CRITICO", "ALTO", "MEDIO") and not tiene_suscripcion:
        return RECO_SIN_PLAN, "sin_plan"

    if nivel == "CRITICO" and tiene_suscripcion:
        return RECO_CRITICO_CON_PLAN, "critico_con_plan"

    caida_reciente = asis_30 < (asis_90 / 3)
    if nivel in ("ALTO", "MEDIO") and tiene_suscripcion and caida_reciente:
        return RECO_CAIDA_RECIENTE, "caida_reciente"

    if (dias_para_vencer is not None and dias_para_vencer <= 7
            and nivel in ("BAJO", "MEDIO")):
        return RECO_RENOVACION_PROXIMA, "renovacion_proxima"

    return RECO_SIN_ACCION, "sin_accion"


def _conteos_asistencias(db, tenant_id, ids, dias, fecha_ref) -> dict:
    """{usuario_id: n_asistencias} en la ventana [fecha_ref - dias, fecha_ref].

    Una sola query agregada (mismo criterio que `ml.features.build_features`).
    La necesita la rama heurística, que no calcula las ventanas de asistencia.
    """
    if not ids:
        return {}
    return dict(db.query(
        Asistencia.usuario_id, func.count(Asistencia.id)
    ).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id.in_(ids),
        Asistencia.fecha >= fecha_ref - timedelta(days=dias),
        Asistencia.fecha <= fecha_ref,
    ).group_by(Asistencia.usuario_id).all())


# ── 1) POST /api/v1/kpis/populate/daily ──────────────────────────────────────
@router.post("/populate/daily")
def populate_daily_kpis(
    fecha: date = Query(None, description="Día a calcular (YYYY-MM-DD). Default: ayer"),
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Calcula y hace UPSERT de `daily_kpis` para el día indicado (default: ayer)."""
    tenant_id = TENANT_ID
    objetivo = fecha or (date.today() - timedelta(days=1))

    alumnos_activos = db.query(func.count(Suscripcion.id)).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        Suscripcion.fecha_expiracion >= objetivo,
    ).scalar() or 0

    alumnos_nuevos = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        func.date(Usuario.created_at) == objetivo,
    ).scalar() or 0

    clases = db.query(Clase).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha == objetivo,
        Clase.cancelada == False,  # noqa: E712
    ).all()
    clases_ejecutadas = len(clases)
    cupo_total = sum((c.cupo_maximo or 0) for c in clases)

    asistentes = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Clase.fecha == objetivo,
        Reserva.asistio == True,  # noqa: E712
    ).scalar() or 0

    ocupacion = round((asistentes / cupo_total * 100), 2) if cupo_total else 0

    reservas_confirmadas = db.query(func.count(Reserva.id)).filter(
        Reserva.tenant_id == tenant_id,
        func.date(Reserva.fecha_reserva) == objetivo,
        Reserva.estado == "confirmada",
    ).scalar() or 0

    cancellaciones = db.query(func.count(Reserva.id)).filter(
        Reserva.tenant_id == tenant_id,
        func.date(Reserva.fecha_reserva) == objetivo,
        Reserva.estado.in_(ESTADOS_CANCELADA),
    ).scalar() or 0

    ingresos_membresia = _sum_ingresos(db, tenant_id, objetivo, objetivo, "membresia")
    ingresos_bazar = _sum_ingresos(db, tenant_id, objetivo, objetivo, "bazar")
    ingresos_total = _sum_ingresos(db, tenant_id, objetivo, objetivo)

    row = db.query(DailyKpi).filter(
        DailyKpi.tenant_id == tenant_id, DailyKpi.fecha == objetivo
    ).first()
    if not row:
        row = DailyKpi(tenant_id=tenant_id, fecha=objetivo)
        db.add(row)

    row.alumnos_activos = alumnos_activos
    row.alumnos_nuevos = alumnos_nuevos
    row.clases_ejecutadas = clases_ejecutadas
    row.asistentes_totales = asistentes
    row.ocupacion_promedio = ocupacion
    row.ingresos_membresia = ingresos_membresia
    row.ingresos_bazar = ingresos_bazar
    row.ingresos_total = ingresos_total
    row.reservas_confirmadas = reservas_confirmadas
    row.cancellaciones = cancellaciones
    db.commit()

    return {
        "status": "ok", "tenant_id": tenant_id, "fecha": objetivo,
        "accion": "daily_kpis upsert",
        "valores": {
            "alumnos_activos": alumnos_activos, "alumnos_nuevos": alumnos_nuevos,
            "clases_ejecutadas": clases_ejecutadas, "asistentes_totales": asistentes,
            "ocupacion_promedio": ocupacion, "ingresos_total": ingresos_total,
        },
    }


# ── 2) POST /api/v1/kpis/populate/monthly ────────────────────────────────────
@router.post("/populate/monthly")
def populate_monthly_kpis(
    year: int = Query(None, description="Año (YYYY). Default: mes anterior"),
    month: int = Query(None, description="Mes (1-12). Default: mes anterior"),
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Calcula y hace UPSERT de `monthly_kpis` para el mes indicado (default: anterior)."""
    tenant_id = TENANT_ID
    if year is None or month is None:
        primer_dia_mes = date.today().replace(day=1)
        anterior = primer_dia_mes - timedelta(days=1)
        year, month = anterior.year, anterior.month

    inicio = date(year, month, 1)
    fin = date(year, month, calendar.monthrange(year, month)[1])

    # ── Embudo prueba → plan ──
    alumnos_prueba = db.query(
        func.count(func.distinct(Suscripcion.usuario_id))
    ).join(Plan, Suscripcion.plan_id == Plan.id).filter(
        Suscripcion.tenant_id == tenant_id,
        Plan.nombre == PLAN_PRUEBA,
        func.date(Suscripcion.fecha_inicio) >= inicio,
        func.date(Suscripcion.fecha_inicio) <= fin,
    ).scalar() or 0

    alumnos_clase_prueba_ejecutada = db.query(
        func.count(func.distinct(Asistencia.usuario_id))
    ).join(Suscripcion, Suscripcion.usuario_id == Asistencia.usuario_id).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.fecha >= inicio, Asistencia.fecha <= fin,
        Suscripcion.tenant_id == tenant_id,
        Plan.nombre == PLAN_PRUEBA,
    ).scalar() or 0

    alumnos_plan_comprado = db.query(func.count(Suscripcion.id)).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Plan.precio_clp > 0,
        func.date(Suscripcion.fecha_inicio) >= inicio,
        func.date(Suscripcion.fecha_inicio) <= fin,
    ).scalar() or 0

    conversion_rate = round(
        alumnos_plan_comprado / alumnos_prueba * 100, 2) if alumnos_prueba else 0

    # ── Actividad / churn ──
    alumnos_activos_inicio = db.query(
        func.count(func.distinct(Suscripcion.usuario_id))
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        func.date(Suscripcion.fecha_inicio) <= inicio,
        func.date(Suscripcion.fecha_expiracion) >= inicio,
    ).scalar() or 0

    alumnos_baja = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        func.date(Usuario.fecha_baja) >= inicio,
        func.date(Usuario.fecha_baja) <= fin,
    ).scalar() or 0

    churn_rate = round(
        alumnos_baja / alumnos_activos_inicio * 100, 2) if alumnos_activos_inicio else 0

    # ── Finanzas ──
    # MRR: mismo criterio que /reportes (planes con suscripción vigente al fin del mes)
    mrr = db.query(func.coalesce(func.sum(Plan.precio_clp), 0)).join(
        Suscripcion, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        func.date(Suscripcion.fecha_inicio) <= fin,
        func.date(Suscripcion.fecha_expiracion) >= fin,
    ).scalar() or 0

    # Ingresos netos del mes (ingreso - egreso), igual que /reportes
    ingresos_total = _sum_ingresos(db, tenant_id, inicio, fin) - _sum_egresos(
        db, tenant_id, inicio, fin)

    # ── Asistencia ──
    asistentes_mes = db.query(
        func.coalesce(func.sum(Clase.asistentes_confirmados), 0)
    ).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha >= inicio, Clase.fecha <= fin,
    ).scalar() or 0

    cupo_mes = db.query(func.coalesce(func.sum(Clase.cupo_maximo), 0)).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha >= inicio, Clase.fecha <= fin,
    ).scalar() or 0

    reservas_mes = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Clase.fecha >= inicio, Clase.fecha <= fin,
        Reserva.estado == "confirmada",
    ).scalar() or 0

    ocupacion_promedio = round(asistentes_mes / cupo_mes * 100, 2) if cupo_mes else 0
    asistencia_promedio = round(
        asistentes_mes / reservas_mes * 100, 2) if reservas_mes else 0

    semanas = ((fin - inicio).days + 1) / 7.0
    frecuencia_semanal = round(
        asistentes_mes / (alumnos_activos_inicio * semanas), 2
    ) if (alumnos_activos_inicio and semanas) else 0

    row = db.query(MonthlyKpi).filter(
        MonthlyKpi.tenant_id == tenant_id,
        MonthlyKpi.year == year, MonthlyKpi.month == month,
    ).first()
    if not row:
        row = MonthlyKpi(tenant_id=tenant_id, year=year, month=month)
        db.add(row)

    row.alumnos_prueba = alumnos_prueba
    row.alumnos_clase_prueba_ejecutada = alumnos_clase_prueba_ejecutada
    row.alumnos_plan_comprado = alumnos_plan_comprado
    row.conversion_rate = conversion_rate
    row.alumnos_activos_inicio = alumnos_activos_inicio
    row.alumnos_baja = alumnos_baja
    row.churn_rate = churn_rate
    row.mrr = mrr
    row.ingresos_total = ingresos_total
    row.asistencia_promedio = asistencia_promedio
    row.frecuencia_semanal = frecuencia_semanal
    row.ocupacion_promedio = ocupacion_promedio
    db.commit()

    return {
        "status": "ok", "tenant_id": tenant_id, "year": year, "month": month,
        "accion": "monthly_kpis upsert",
        "valores": {
            "alumnos_prueba": alumnos_prueba,
            "alumnos_clase_prueba_ejecutada": alumnos_clase_prueba_ejecutada,
            "alumnos_plan_comprado": alumnos_plan_comprado,
            "conversion_rate": conversion_rate,
            "alumnos_activos_inicio": alumnos_activos_inicio,
            "alumnos_baja": alumnos_baja, "churn_rate": churn_rate,
            "mrr": float(mrr), "ingresos_total": ingresos_total,
            "asistencia_promedio": asistencia_promedio,
            "frecuencia_semanal": frecuencia_semanal,
            "ocupacion_promedio": ocupacion_promedio,
        },
    }


def _mes_desplazado(anio, mes, delta):
    """Devuelve (año, mes) desplazado `delta` meses (negativo = hacia atrás)."""
    indice = (anio * 12 + (mes - 1)) + delta
    return indice // 12, indice % 12 + 1


# ── 3) POST /api/v1/kpis/populate/predictions ────────────────────────────────
@router.post("/populate/predictions")
def populate_predictions(
    meses_forecast: int = Query(3, ge=1, le=12, description="Meses a proyectar"),
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Recalcula (full refresh) churn de alumnos + forecast de ingresos."""
    tenant_id = TENANT_ID
    hoy = date.today()

    # Alumnos "vigentes" del box: se filtra por `estado` (string de negocio) en
    # lugar de `activo` (bool). En datos reales de PROD los alumnos vigentes
    # tienen activo=false pero estado='activo', lo que dejaba este loop vacío y
    # por consecuencia predictions_churn sin filas.
    alumnos = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.estado == "activo",
    ).all()

    # ── Modelos ML entrenados (opcionales) ───────────────────────────────────
    # IMPORT PEREZOSO a propósito: si el paquete `ml/` no está disponible (p.ej.
    # no se instaló scikit-learn), el endpoint NO se rompe: cae a la heurística.
    modelo_churn = modelo_forecast = None
    meta_churn, meta_forecast = {}, {}
    ml_features = ml_entrenar = None
    try:
        from ml import entrenar as ml_entrenar
        from ml import features as ml_features
        from ml.persistencia import cargar_modelo
    except ImportError as e:
        logger.warning("ml/ no disponible (%s): se usa la heurística", e)
    else:
        # Carga INDEPENDIENTE por modelo (mismo criterio de independencia que
        # POST /api/v1/ml/reentrenar): si falla la deserialización del churn
        # (pickle incompatible, tabla ausente, etc.) el modelo de forecast se
        # sigue usando, y viceversa.
        try:
            modelo_churn, meta_churn = cargar_modelo(db, tenant_id, "churn")
        except Exception as e:   # pickle incompatible, tabla ausente, etc.
            db.rollback()   # por si el error dejó la sesión a medio usar
            logger.warning("no se pudo cargar el modelo de churn (%s): "
                           "se usa la heurística", e)
            modelo_churn, meta_churn = None, {}

        try:
            modelo_forecast, meta_forecast = cargar_modelo(
                db, tenant_id, "forecast")
        except Exception as e:
            db.rollback()
            logger.warning("no se pudo cargar el modelo de forecast (%s): "
                           "se usa la heurística", e)
            modelo_forecast, meta_forecast = None, {}

    metodo_churn = "ml" if modelo_churn is not None else "heuristica"
    metodo_forecast = "ml" if modelo_forecast is not None else "heuristica"
    logger.info("populate/predictions: metodo_churn=%s metodo_forecast=%s",
                metodo_churn, metodo_forecast)

    # ── 3.1) CHURN ──
    db.query(PredictionsChurn).filter(
        PredictionsChurn.tenant_id == tenant_id).delete()

    criticos = altos = medios = 0
    recos = {codigo: 0 for codigo in RECO_CODIGOS}

    # Con modelo ML se calculan las features de TODOS los alumnos de una vez
    # (`build_features` = 5 queries agregadas; `features_alumno` sería ~6 por
    # alumno) y se predice en lote. Mismas columnas/criterio que el entreno.
    probs_ml = contexto_ml = None
    if modelo_churn is not None:
        df_ml = ml_features.build_features(db, tenant_id, hoy)
        # pandas convierte los nulos de la columna a NaN (float); se normaliza
        # a None para que la rama "sin plan vigente" sea inequívoca.
        contexto_ml = {}
        for r in df_ml.to_dict(orient="records"):
            dpv = r["dias_para_vencer_plan"]
            if isinstance(dpv, float) and dpv != dpv:   # NaN != NaN
                r["dias_para_vencer_plan"] = None
            contexto_ml[r["usuario_id"]] = r
        X_ml = df_ml[ml_features.FEATURE_COLS].copy()
        # Mismas transformaciones que en el entrenamiento:
        # `-1` = no tiene plan vigente (RandomForest no acepta NaN).
        X_ml["dias_para_vencer_plan"] = (
            X_ml["dias_para_vencer_plan"].fillna(-1).astype(int))
        X_ml["tiene_suscripcion_activa"] = (
            X_ml["tiene_suscripcion_activa"].astype(int))
        probs_ml = dict(zip(df_ml["usuario_id"],
                            modelo_churn.predict_proba(X_ml)[:, 1]))

    # Ventanas de asistencia para la recomendación en la rama heurística: la
    # rama ML ya las trae gratis en `contexto_ml` (build_features las calcula),
    # pero la heurística no. Son 2 queries agregadas CONSTANTES (no por alumno).
    conteos_30 = conteos_90 = {}
    if probs_ml is None and alumnos:
        ids_alumnos = [a.id for a in alumnos]
        conteos_30 = _conteos_asistencias(db, tenant_id, ids_alumnos, 30, hoy)
        conteos_90 = _conteos_asistencias(db, tenant_id, ids_alumnos, 90, hoy)

    for alumno in alumnos:
        if probs_ml is not None:
            # ── Método ML: probabilidad de abandono del Random Forest ──
            prob = round(float(probs_ml.get(alumno.id, 0.0)) * 100, 2)
            ctx = contexto_ml.get(alumno.id, {})
            dias_inactivo = int(ctx.get("dias_desde_ultima_asistencia", 0))
            dias_para_vencer = ctx.get("dias_para_vencer_plan")
            # Ventanas de asistencia: ya vienen en `contexto_ml` (features), sin
            # query extra. Habilitan la regla #2 de la recomendación.
            asis_30 = int(ctx.get("asistencias_ultimos_30_dias", 0) or 0)
            asis_90 = int(ctx.get("asistencias_ultimos_90_dias", 0) or 0)
            if dias_para_vencer is None:
                proxima_date = None
                motivo = (f"{dias_inactivo} {_plural_dias(dias_inactivo)} sin "
                          f"asistir · sin plan vigente")
            else:
                dias_para_vencer = int(dias_para_vencer)
                proxima_date = hoy + timedelta(days=dias_para_vencer)
                motivo = (f"{dias_inactivo} {_plural_dias(dias_inactivo)} sin "
                          f"asistir · plan vence en "
                          f"{dias_para_vencer} {_plural_dias(dias_para_vencer)}")
        else:
            # ── Fallback: heurística original (no hay modelo entrenado) ──
            ultima = _ultima_asistencia(db, tenant_id, alumno.id)
            # BUGFIX 999: sin asistencias se mide desde la fecha de registro del
            # alumno (antes un 999 fijo lo marcaba CRITICO aunque fuera nuevo).
            dias_inactivo = _dias_inactividad(hoy, ultima, alumno.created_at)

            # `fecha_expiracion >= hoy` (igual que ml/features.build_features y
            # que populate_daily_kpis): un plan con estado='activo' pero YA
            # VENCIDO no es un plan vigente. Sin este filtro daba un
            # `dias_para_vencer` negativo y contaba como "tiene plan vigente"
            # (motivo, probabilidad y recomendación equivocados).
            proxima = db.query(func.max(Suscripcion.fecha_expiracion)).filter(
                Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == alumno.id,
                Suscripcion.estado == "activo",
                func.date(Suscripcion.fecha_expiracion) >= hoy,
            ).scalar()
            proxima_date = proxima.date() if proxima else None
            dias_para_vencer = (proxima_date - hoy).days if proxima_date else None
            # Ventanas de asistencia (rama heurística: se calculan pre-loop).
            asis_30 = conteos_30.get(alumno.id, 0)
            asis_90 = conteos_90.get(alumno.id, 0)

            # Heurística simple (0-100): inactividad + ausencia de plan vigente
            prob = min(dias_inactivo, 60) / 60 * 70
            if dias_para_vencer is None:
                prob += 20
                motivo = (f"Sin suscripción activa · {dias_inactivo} "
                          f"{_plural_dias(dias_inactivo)} sin asistir")
            elif dias_para_vencer <= 7:
                prob += 10
                motivo = (f"{dias_inactivo} {_plural_dias(dias_inactivo)} sin "
                          f"asistir · plan vence en {dias_para_vencer} "
                          f"{_plural_dias(dias_para_vencer)}")
            else:
                motivo = f"{dias_inactivo} {_plural_dias(dias_inactivo)} sin asistir"
            prob = round(min(prob, 100), 2)

        # ── Mapeo común de nivel de riesgo (mismos umbrales en ambos métodos) ──
        if prob >= 70:
            nivel, criticos = "CRITICO", criticos + 1
        elif prob >= 50:
            nivel, altos = "ALTO", altos + 1
        elif prob >= 30:
            nivel, medios = "MEDIO", medios + 1
        else:
            nivel = "BAJO"

        # Recomendación empática/accionable: MISMA lógica en ambas ramas.
        # `tiene_suscripcion_activa` == `dias_para_vencer is not None`
        # (en ml/features.py: "tiene_suscripcion_activa": vence_date is not None).
        recomendacion, reco_codigo = _recomendacion_churn(
            nivel, dias_para_vencer is not None, dias_para_vencer,
            asis_30, asis_90)
        recos[reco_codigo] += 1

        db.add(PredictionsChurn(
            tenant_id=tenant_id, usuario_id=alumno.id,
            probabilidad_churn=prob, riesgo_nivel=nivel, motivo=motivo,
            recomendacion=recomendacion, recomendacion_codigo=reco_codigo,
            # `estado_gestion` YA NO vive acá: es de-negocio y está en la tabla
            # propia `churn_gestion` (migración 024), que este full refresh NO
            # toca -> la gestión del admin sobrevive a cada re-poblado.
            fecha_proxima_renovacion=proxima_date,
        ))
    db.commit()

    # ── 3.2) FORECAST de ingresos netos ──
    db.query(PredictionsForecast).filter(
        PredictionsForecast.tenant_id == tenant_id).delete()

    alumnos_activos_hoy = db.query(
        func.count(func.distinct(Suscripcion.usuario_id))
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        Suscripcion.fecha_expiracion >= hoy,
    ).scalar() or 0

    if modelo_forecast is not None:
        # ── Método ML: regresión lineal (tendencia t + sin/cos del mes) ──
        serie = ml_entrenar.serie_mensual(db, tenant_id)
        proyeccion = ml_entrenar.proyectar(modelo_forecast, serie,
                                           meses_forecast)
        ultimo_mes = round(float(serie[-1][2])) if serie else 0
        for p in proyeccion:
            ingresos = max(0, round(float(p["ingreso_predicho"])))
            factor = (ingresos / ultimo_mes) if ultimo_mes > 0 else 1.0
            db.add(PredictionsForecast(
                tenant_id=tenant_id,
                mes_prediccion=date(int(p["anio"]), int(p["mes"]), 1),
                ingresos_predicho=ingresos,
                intervalo_confianza=95,
                alumnos_predicho=max(0, round(alumnos_activos_hoy * factor)),
                tasa_crecimiento=round((factor - 1) * 100, 2),
                notas=f"Último mes observado: {ultimo_mes} CLP",
            ))
        db.commit()
        forecast_resp = {
            "meses": meses_forecast, "metodo": metodo_forecast,
            "modelo": meta_forecast.get("modelo"),
            "ultimo_mes_observado_clp": ultimo_mes,
            "r2_train": meta_forecast.get("metricas_train", {}).get("r2"),
        }
    else:
        # ── Fallback: proyección lineal simple (promedio + crecimiento) ──
        mes_actual = hoy.replace(day=1)
        historico = []
        for i in range(6, 0, -1):
            y, m = _mes_desplazado(mes_actual.year, mes_actual.month, -i)
            ini = date(y, m, 1)
            f = date(y, m, calendar.monthrange(y, m)[1])
            neto = _sum_ingresos(db, tenant_id, ini, f) - _sum_egresos(
                db, tenant_id, ini, f)
            historico.append(neto)

        con_datos = [n for n in historico if n > 0]
        base = (sum(con_datos) / len(con_datos)) if con_datos else 0.0

        crecimientos = [(b - a) / a for a, b in zip(con_datos, con_datos[1:])
                        if a > 0]
        g = (sum(crecimientos) / len(crecimientos)) if crecimientos else 0.0
        g = max(min(g, 0.5), -0.5)  # acotar a ±50% mensual

        notas = (f"Proyección lineal: base {round(base)} CLP "
                 f"({len(con_datos)}/{len(historico)} meses con datos), "
                 f"crecimiento {round(g * 100, 2)}%/mes")

        for k in range(1, meses_forecast + 1):
            y, m = _mes_desplazado(mes_actual.year, mes_actual.month, k)
            factor = (1 + g) ** k
            db.add(PredictionsForecast(
                tenant_id=tenant_id, mes_prediccion=date(y, m, 1),
                ingresos_predicho=max(0, round(base * factor)),
                intervalo_confianza=95,
                alumnos_predicho=max(0, round(alumnos_activos_hoy * factor)),
                tasa_crecimiento=round(g * 100, 2), notas=notas,
            ))
        db.commit()
        forecast_resp = {
            "meses": meses_forecast, "metodo": metodo_forecast,
            "base_mensual": round(base),
            "crecimiento_mensual_pct": round(g * 100, 2),
        }

    return {
        "status": "ok", "tenant_id": tenant_id,
        "accion": "predictions_churn + predictions_forecast (full refresh)",
        # Auditable: qué método generó cada bloque (ml | heuristica)
        "metodo_churn": metodo_churn,
        "metodo_forecast": metodo_forecast,
        "modelos_ml": {
            "churn": ({"modelo": meta_churn.get("modelo"),
                       "entrenado": meta_churn.get("fecha_entrenamiento"),
                       "accuracy_cv": meta_churn.get("cross_validation", {})
                       .get("accuracy", {}).get("media")}
                      if meta_churn else None),
            "forecast": ({"modelo": meta_forecast.get("modelo"),
                          "entrenado": meta_forecast.get("fecha_entrenamiento"),
                          "r2": meta_forecast.get("metricas_train", {})
                          .get("r2")}
                         if meta_forecast else None),
        },
        "churn": {"total": len(alumnos), "criticos": criticos,
                  "altos": altos, "medios": medios},
        # Desglose auditable de la recomendación emitida (1 por alumno, por código).
        "recomendaciones": recos,
        "forecast": forecast_resp,
    }
