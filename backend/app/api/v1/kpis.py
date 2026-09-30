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
from app.utils.santiago import hoy_santiago

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

    hoy = hoy_santiago()
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

    hoy = hoy_santiago()
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
    limite = hoy_santiago() + timedelta(days=7)
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
        fecha = hoy_santiago()

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
        # `churn_rate` es NULLABLE a propósito (migración 027): None = la cohorte
        # del mes no tiene base mínima y NO se publica retención; es un "sin dato",
        # no un 0% de churn real. Antes se hacía `float(kpi.churn_rate)` y el mes
        # con la columna en NULL respondía HTTP 500 (TypeError): la pestaña Mensual
        # lo descartaba y mostraba "Sin datos para el período" aunque el mes
        # existiera. La UI ya sabe mostrar "—" para null.
        "churn_rate": float(kpi.churn_rate) if kpi.churn_rate is not None else None,
        "mrr": float(kpi.mrr),
        "ingresos_total": float(kpi.ingresos_total),
        "asistencia_promedio": float(kpi.asistencia_promedio),
        "frecuencia_semanal": float(kpi.frecuencia_semanal),
        "ocupacion_promedio": float(kpi.ocupacion_promedio),
    }


# ── 2b) GET /api/v1/kpis/mensual/periodos (selector de la pestaña MENSUAL) ───
@router.get("/mensual/periodos")
def get_kpis_mensual_periodos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Meses del tenant que tienen fila en `monthly_kpis`, con su `default`.

    POR QUÉ EXISTE: la pestaña Mensual pedía a ciegas los últimos 6 meses; los
    meses sin fila responden 404 y la UI los descartaba, así que mostraba "Sin
    datos para el período" aunque SÍ hubiera meses con datos (basta que estén
    fuera de esa ventana, o que el único mes con fila haya fallado). Con esta
    lista la UI pide sólo meses que existen y sabe cuál mostrar por defecto.

    Criterio de los campos (no se recalcula nada acá: es un índice de la tabla):
      - `parcial`: el período es el MES EN CURSO en Chile, así que sus números son
        de un mes a medias (se publican recién al cierre del mes).
      - `default`: el ÚLTIMO MES CERRADO con datos; si no hay ninguno cerrado, el
        más reciente de la lista. Sin filas => null.
      - `actual.tiene_fila`: si el mes en curso ya tiene fila (populate corrido a
        mitad de mes o backfill que incluyó el mes en curso).

    Orden ASCENDENTE por período (más viejo primero): la serie del gráfico se
    arma tomando los últimos N sin reordenar.
    """
    tenant_id = current_user["tenant_id"]
    hoy = hoy_santiago()

    filas = db.query(MonthlyKpi).filter(
        MonthlyKpi.tenant_id == tenant_id,
    ).order_by(MonthlyKpi.year.asc(), MonthlyKpi.month.asc()).all()

    periodos = [{
        "year": f.year,
        "month": f.month,
        "parcial": (f.year, f.month) == (hoy.year, hoy.month),
        "mrr": float(f.mrr),
        "ingresos_total": float(f.ingresos_total),
        "alumnos_activos_inicio": f.alumnos_activos_inicio,
        "churn_rate": float(f.churn_rate) if f.churn_rate is not None else None,
    } for f in filas]

    mes_actual = (hoy.year, hoy.month)
    cerrados = [p for p in periodos if (p["year"], p["month"]) < mes_actual]
    elegido = cerrados[-1] if cerrados else (periodos[-1] if periodos else None)

    return {
        "hoy": hoy,
        "periodos": periodos,
        "default": ({"year": elegido["year"], "month": elegido["month"],
                     "parcial": elegido["parcial"]} if elegido else None),
        "actual": {"year": hoy.year, "month": hoy.month,
                   "tiene_fila": any(p["parcial"] for p in periodos),
                   "parcial": True},
    }


# ── 2c) GET /api/v1/kpis/estacionalidad (BI: perfil del año) ─────────────────
# Meses CERRADOS con fila en `monthly_kpis` que hacen falta para publicar el
# índice: con menos, cada mes del calendario se observa a lo sumo una vez y el
# "perfil" es el ruido de unos pocos meses, no una estacionalidad.
MESES_MIN_ESTACIONALIDAD = 12
# Rótulos de mes: los MISMOS que usa la pestaña Mensual en el eje de sus gráficos.
MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic")


def _indice_estacional(filas: list) -> dict:
    """Índice estacional por mes del calendario: valor del mes / promedio.

    PURA (sin base ni HTTP): recibe `[{"month", "valor"}]` —sólo meses CERRADOS— y
    devuelve SIEMPRE las 12 filas (ene..dic), con `None` en los meses sin
    observaciones: así el gráfico tiene 12 puntos fijos y los huecos SE VEN (no se
    interpolan como si hubiera dato).

    Cómo se calcula:
      1. Se agrupa por mes del calendario (1..12) sobre TODA la historia cargada.
      2. `valor` de cada mes = promedio de sus observaciones (con un año de historia
         es UNA: el valor de ese mes) y `muestras` dice cuántas hay.
      3. `promedio` = promedio de TODAS las observaciones.
      4. `indice` = valor / promedio: 1.00 es un mes igual al promedio del período,
         > 1 un mes fuerte y < 1 un mes flojo. Con promedio 0 el índice es None
         ("sin dato" NO es "0", mismo criterio que `churn_rate`).

    `disponible`: False cuando NINGUNA observación es distinta de 0. Existe por un
    hallazgo concreto: `alumnos_activos_inicio` viene en 0 en todos los meses
    cerrados (el populate la llena con el estado de HOY de la suscripción), y sin
    esta bandera el gráfico dibujaría una línea plana en 0 que PARECE un dato.
    """
    por_mes = {m: [] for m in range(1, 13)}
    for f in filas:
        valor = f.get("valor")
        if valor is None:
            continue
        por_mes[f["month"]].append(float(valor))

    todas = [v for valores in por_mes.values() for v in valores]
    promedio = (sum(todas) / len(todas)) if todas else None
    disponible = any(v != 0 for v in todas)

    meses = []
    for m in range(1, 13):
        valores = por_mes[m]
        media = (sum(valores) / len(valores)) if valores else None
        meses.append({
            "mes": m,
            "label": MESES_CORTOS[m - 1],
            "valor": round(media, 2) if media is not None else None,
            "muestras": len(valores),
            "indice": (round(media / promedio, 3)
                       if media is not None and promedio and disponible else None),
        })

    return {
        "meses": meses,
        "promedio": round(promedio, 2) if promedio is not None else None,
        "observaciones": len(todas),
        "disponible": disponible,
    }


def _meta_serie(serie: dict) -> dict:
    """Sólo los metadatos de una serie (los 12 meses van en `filas`)."""
    return {k: serie[k] for k in ("promedio", "observaciones", "disponible")}


@router.get("/estacionalidad")
def get_estacionalidad(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Perfil estacional del box: índice por mes del año (ene..dic) de ingresos y alumnos.

    POR QUÉ EXISTE: el BI ya mostraba el mes a mes (series) y el pronóstico, pero no
    respondía la pregunta con la que se planifican campañas, profes y horarios:
    "¿cuáles son MIS meses fuertes y cuáles los flojos?". El índice estacional pone
    los meses en la MISMA escala (1.00 = promedio del período) aunque ingresos y
    alumnos se midan en unidades distintas: es lo que se mira para adelantar una
    campaña en el mes flojo y reforzar personal en el fuerte.

    Fuente: `monthly_kpis` (meses CERRADOS del tenant). El mes EN CURSO se EXCLUYE
    a propósito: son números de un mes a medias y ensuciarían el perfil (el
    `parcial` lo decide el calendario chileno, no el navegador).

    Honestidad del dato (todo viaja en la respuesta):
      · `suficiente`: sólo con >= `MESES_MIN_ESTACIONALIDAD` (12) meses cerrados;
        con menos, la UI avisa que todavía no hay historia suficiente.
      · `nota_historia`: con 12 meses cada mes del calendario se observa UNA vez,
        así que es el perfil de ESA ventana, no una tendencia de varios años.
      · `alumnos_activos.disponible` + `motivo`: `alumnos_activos_inicio` se llena
        con el estado de HOY de la suscripción (`estado = 'activo'`), así que los
        meses ya cerrados quedan en 0 (medido en TEST: los 12 meses del backfill
        dan 0). La serie se publica con su valor crudo y marcada como NO
        disponible: no se dibuja una línea plana que parezca un dato.

    Respuesta: `filas` = 12 filas (ene..dic) con el índice de las dos series, más
    `promedios`, `suficiente`, `meses_con_datos`, `ventana` y `nota_historia`.
    """
    tenant_id = current_user["tenant_id"]
    hoy = hoy_santiago()

    filas_bd = db.query(MonthlyKpi).filter(
        MonthlyKpi.tenant_id == tenant_id,
    ).order_by(MonthlyKpi.year.asc(), MonthlyKpi.month.asc()).all()

    # Sólo meses CERRADOS: el mes en curso no cerró y sus números son parciales.
    cerradas = [f for f in filas_bd
                if (f.year, f.month) != (hoy.year, hoy.month)]

    ingresos = _indice_estacional(
        [{"month": f.month, "valor": float(f.ingresos_total)} for f in cerradas])
    alumnos = _indice_estacional(
        [{"month": f.month, "valor": f.alumnos_activos_inicio} for f in cerradas])

    suficiente = len(cerradas) >= MESES_MIN_ESTACIONALIDAD
    motivo_alumnos = None if alumnos["disponible"] else (
        "Todavía no hay serie histórica de alumnos activos: de cada suscripción se "
        "guarda sólo su estado actual, así que los meses ya cerrados quedan en 0 y "
        "la línea no se dibuja (parecería un dato). Se completa cuando se "
        "reconstruya el histórico.")

    return {
        "suficiente": suficiente,
        "minimo_meses": MESES_MIN_ESTACIONALIDAD,
        "meses_con_datos": len(cerradas),
        "ventana": {
            "desde": ({"year": cerradas[0].year, "month": cerradas[0].month}
                      if cerradas else None),
            "hasta": ({"year": cerradas[-1].year, "month": cerradas[-1].month}
                      if cerradas else None),
        },
        "excluye_mes_en_curso": {"year": hoy.year, "month": hoy.month},
        "fuente": "monthly_kpis (meses cerrados)",
        "nota_historia": (
            "Es 1 año de historia: el perfil de ese período (cada mes del año se "
            "mira una sola vez), no una tendencia de varios años."
            if suficiente else
            f"Todavía no hay un año completo: {len(cerradas)} de "
            f"{MESES_MIN_ESTACIONALIDAD} meses cerrados con datos."),
        "ingresos": {
            "etiqueta": "Ingresos del mes (netos)",
            "columna": "monthly_kpis.ingresos_total",
            **_meta_serie(ingresos),
        },
        "alumnos_activos": {
            "etiqueta": "Alumnos activos (inicio del mes)",
            "columna": "monthly_kpis.alumnos_activos_inicio",
            **_meta_serie(alumnos),
            "motivo": motivo_alumnos,
        },
        "promedios": {"ingresos": ingresos["promedio"],
                      "alumnos_activos": alumnos["promedio"]},
        "filas": [{
            "mes": a["mes"], "label": a["label"], "muestras": a["muestras"],
            "alumnos_activos": a["valor"], "indice_alumnos": a["indice"],
            "ingresos": i["valor"], "indice_ingresos": i["indice"],
        } for a, i in zip(alumnos["meses"], ingresos["meses"])],
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
                "promedio de días desde el alta hasta la baja (o hasta hoy) de los "
                "alumnos del box, pasado a meses"),
            "limitaciones": (
                "los alumnos que siguen activos sólo aportan el tiempo que llevan "
                "hasta hoy, así que la vida real de los más antiguos queda "
                "subestimada"),
        },
        "ltv_formula": (
            "LTV = ARPU mensual (el de Reportes) × vida promedio en meses"),
        "nota_cac": (
            "No se calcula el costo de adquisición (CAC): no hay registro de ese "
            "gasto, así que tampoco se puede estimar en cuánto tiempo se recupera "
            "lo invertido por alumno."),
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
                "Las asistencias todavía no quedan asociadas a su clase, así que el "
                "promedio de asistencias por bloque se activará más adelante. Por "
                "ahora se muestra la oferta real (clases y cupo)."),
        },
        "bloques": bloques,
        "por_hora": por_hora,
    }


# ── 8) GET /api/v1/kpis/cohortes (BI - retención por cohorte) ────────────────
@router.get("/cohortes")
def get_cohortes(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Cohortes de retención por MES DE ALTA del alumno (`usuarios.created_at`).

    Definición (documentada a propósito):
      - "Activo a los N días" = el alumno tiene >= 1 ASISTENCIA en la ventana
        [alta, alta + N días]. Es la señal de retención disponible hoy (las
        asistencias todavía no están asociadas a clase, ver /bloques-horarios).
      - Sólo se promedian los alumnos EVALUABLES: los que ya cumplieron el
        horizonte (alta + N <= hoy). Si la cohorte es más joven,
        `retencion_pct` viene en `null` -> NO se inventa un 0% por falta de
        historia.
    """
    tenant_id = current_user["tenant_id"]

    filas = db.execute(sql_text("""
        WITH altas AS (
            SELECT id, tenant_id, created_at::date AS alta
            FROM usuarios
            WHERE tenant_id = :tid AND rol = 'alumno'
        )
        SELECT to_char(date_trunc('month', alta), 'YYYY-MM') AS cohorte,
               COUNT(*) AS n_alumnos,
               COUNT(*) FILTER (WHERE alta + 30 <= (now() AT TIME ZONE 'America/Santiago')::date) AS eval_30,
               COUNT(*) FILTER (WHERE alta + 30 <= (now() AT TIME ZONE 'America/Santiago')::date AND EXISTS (
                   SELECT 1 FROM asistencias a
                   WHERE a.usuario_id = altas.id AND a.tenant_id = altas.tenant_id
                     AND a.fecha BETWEEN altas.alta AND altas.alta + 30)) AS act_30,
               COUNT(*) FILTER (WHERE alta + 60 <= (now() AT TIME ZONE 'America/Santiago')::date) AS eval_60,
               COUNT(*) FILTER (WHERE alta + 60 <= (now() AT TIME ZONE 'America/Santiago')::date AND EXISTS (
                   SELECT 1 FROM asistencias a
                   WHERE a.usuario_id = altas.id AND a.tenant_id = altas.tenant_id
                     AND a.fecha BETWEEN altas.alta AND altas.alta + 60)) AS act_60,
               COUNT(*) FILTER (WHERE alta + 90 <= (now() AT TIME ZONE 'America/Santiago')::date) AS eval_90,
               COUNT(*) FILTER (WHERE alta + 90 <= (now() AT TIME ZONE 'America/Santiago')::date AND EXISTS (
                   SELECT 1 FROM asistencias a
                   WHERE a.usuario_id = altas.id AND a.tenant_id = altas.tenant_id
                     AND a.fecha BETWEEN altas.alta AND altas.alta + 90)) AS act_90
        FROM altas
        GROUP BY 1 ORDER BY 1
    """), {"tid": tenant_id}).fetchall()

    def _h(evaluables, activos):
        evaluables, activos = int(evaluables or 0), int(activos or 0)
        return {
            "evaluables": evaluables,
            "activos": activos,
            "retencion_pct": (round(activos / evaluables * 100, 1)
                              if evaluables else None),
        }

    cohortes = [
        {
            "cohorte": r[0],
            "n_alumnos": int(r[1] or 0),
            "h30": _h(r[2], r[3]),
            "h60": _h(r[4], r[5]),
            "h90": _h(r[6], r[7]),
        }
        for r in filas
    ]

    globales = {}
    for clave, (i_eval, i_act) in (("h30", (2, 3)), ("h60", (4, 5)),
                                   ("h90", (6, 7))):
        globales[clave] = _h(sum(int(r[i_eval] or 0) for r in filas),
                             sum(int(r[i_act] or 0) for r in filas))

    return {
        "hoy": str(hoy_santiago()),
        "definicion": (
            "Cohorte = el mes en que el alumno se dio de alta. Activo a los N días "
            "= tiene al menos 1 asistencia desde su alta hasta N días después; sólo "
            "se promedian los alumnos que ya cumplieron ese plazo (si la cohorte es "
            "más nueva, la celda queda en n/d)"),
        "horizontes_dias": [30, 60, 90],
        "cohortes": cohortes,
        "global": globales,
    }
