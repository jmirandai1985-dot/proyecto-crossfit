"""Historial del alumno — el panel completo en UNA definición (servicio).

Qué es
------
Una sola vista del alumno a lo largo de su vida en el box: desde el alta hasta hoy. Antes esa
información estaba repartida en 6 pantallas/endpoints (reservas, suscripciones, pedidos, RMs,
niveles, hitos) y cada una armaba sus propios números y sus propios bordes: un alumno sin
asistencias, una suscripción vencida, una clase que suspendió el box.

El router (`app/api/v1/historial_alumno.py`) NO calcula nada: elige la sección, aplica el ACL
y devuelve el dict. Todo lo demás vive acá.

Contrato
--------
    panel(db, alumno_id, tenant_id, seccion=..., pagina=..., por_pagina=..., incluir_privado=...)

devuelve SIEMPRE la misma envoltura:

    {
      "alumno":    {...ficha...},
      "seccion":   "asistencia",
      "secciones": [{"id", "label", "disponible", "motivo"}],   # el menú de pestañas
      "datos":     {...}                                        # depende de la sección
    }

y `None` si el alumno no existe en el tenant (el router lo traduce a 404).

`incluir_privado=False` (el PROPIO alumno mirándose) omite los campos derivados del ML
(`arquetipo`, `riesgo_nivel`, `riesgo_probabilidad`, `estado_gestion`, `dias_sin_asistir`):
son insumo de gestión del box, no información del alumno.

Reglas de negocio (UNA definición por número, todas acá)
--------------------------------------------------------
 1. `estado_asistencia` tiene 5 valores: asistio | falto | cancelada | cancelada_tarde |
    reservada. `cancelada_tarde` = cancelada a MENOS de 6 h del inicio de la clase: el MISMO
    umbral de A.3 del mantenimiento (`interval '6 hours'`), que es el que decide si esa
    cancelación gastó el crédito del alumno.
 2. `% de asistencia` = asistidas / (asistidas + faltadas + canceladas_tarde). Las canceladas a
    tiempo y las reservas futuras (`reservada`) NO ensucian el porcentaje.
 3. `promedio_semanal` = asistencias / semanas desde el alta (`usuarios.created_at`), con piso
    de 1 semana: un alumno de 3 días no divide por 0 ni infla el número.
 4. `total_pagado` = membresías COBRADAS + Bazar. Las membresías salen de las transacciones
    REALES (`transacciones_financieras` de la suscripción: el ingreso suma y una devolución
    —egreso— resta), NO del precio de lista: el historial tiene que mostrar lo que el alumno
    pagó de verdad, con su descuento si el box se lo hizo. Qué suscripciones se listan lo
    decide el mismo criterio que `metricas_service.mrr` (alguna vez vigentes: ni `pendiente`
    ni `rechazado`). Bazar por el `total` real de los pedidos `validado`/`entregado` (un
    pedido `pendiente` no es plata cobrada). La lista de esos dos estados es la COMPARTIDA
    (`shared.estados.ESTADOS_PAGO_BAZAR`: la misma que usan el BI y el Excel de Reportes a través
    de `metricas_service.ventas_bazar`), así que "venta del Bazar" significa lo mismo en las tres
    pantallas. La sección Membresías, en cambio, sigue mostrando
    el PRECIO DE LISTA del plan: ahí la pregunta es cuánto VALE su plan, no cuánto entró (y el
    `precio_lista_clp` de cada pago deja ver el descuento sin mezclar las dos cosas).
 5. "mes con plan" = mes calendario con una suscripción vigente. Mismo criterio que
    `shared.estados.sql_suscripcion_vigente()`: lo deciden las FECHAS (`fecha_inicio` dentro o
    antes del mes y `fecha_expiracion` dentro o después) y el estado sólo descarta lo que NUNCA
    estuvo vigente (`pendiente`/`rechazado`). Las fechas se leen en hora de CHILE, igual que
    `hoy_santiago()`: con la TZ del servidor (UTC) un mes empezado de noche caería en el mes
    siguiente.
 6. Las clases que canceló el BOX (`clases.cancelada = true`) no cuentan ni como falta ni como
    asistencia: se informan aparte en `clases_suspendidas`. Castigar al alumno por una clase
    que suspendió el box sería un dato falso.
 7. `bazar` es el detalle de los pedidos (fecha, producto, cantidad, total, estado, código de
    retiro y quién/cuándo entregó), NO una segunda lista de plata: muestra también los `pendiente`
    y los `cancelado`, y marca con `cobrado` los que suman (la lista compartida). Lo que suma
    coincide con el "Bazar" de la pestaña Pagos, con el BI y con el Excel.
 8. `beneficios` (la última sección) está declarada pero NO se anuncia en el menú de pestañas hasta la
    Fase 2 de Fidelización: una pestaña deshabilitada es ruido (y una promesa vacía) para el
    alumno. El id sigue existiendo —se puede pedir `?seccion=beneficios` y devuelve el
    motivo— porque es la sección que va a llenar la Fase 2.
"""
import calendar
from collections import Counter
from datetime import date, datetime, time as _time, timedelta, timezone
from typing import Final

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.estados import es_cancelada, pago_bazar
from app.models.beneficio import Beneficio, EstadoBeneficio, TipoBeneficio
from app.models.churn_gestion import ChurnGestion
from app.models.clase import Clase
from app.models.disciplina import Disciplina
from app.models.historial_rm import HistorialRM
from app.models.hito_alumno import HitoAlumno
from app.models.pedido import Pedido
from app.models.plan import Plan
from app.models.predictions_churn import PredictionsChurn
from app.models.producto import Producto
from app.models.reserva import Reserva
from app.models.segmentacion_alumno import SegmentacionAlumno
from app.models.suscripcion import Suscripcion
from app.models.transaccion_financiera import TransaccionFinanciera
from app.models.usuario import Usuario
from app.services.beneficios_service import esta_vivo as beneficio_esta_vivo
from app.services.beneficios_service import etiqueta as beneficio_etiqueta
from app.services.rms_service import mejor_rm_por_movimiento
from app.utils.santiago import SANTIAGO, ahora_santiago, fecha_chile, hoy_santiago
from shared.estados import ESTADOS_PAGO_BAZAR, ESTADOS_SUSCRIPCION_NUNCA_VIGENTES

# ── Umbrales / criterios ──────────────────────────────────────────────────────
# Mismo valor que la LATERAL de A.3 del mantenimiento (`interval '6 hours'`).
HORAS_CANCELACION_TARDIA: Final[int] = 6
# Un pedido del Bazar cuenta como plata cobrada sólo en estos estados. La lista NO se define
# acá: vive en `shared.estados.ESTADOS_PAGO_BAZAR` (importada arriba), porque es la MISMA que
# usan el BI (`daily_kpis.ingresos_bazar`) y el Excel de Reportes
# (`metricas_service.ventas_bazar`). Antes cada pantalla tenía la suya y el Excel contaba
# también los pendientes.
# Tipos de una transacción financiera y su efecto en "lo que se pagó": el ingreso suma y una
# devolución (egreso) resta. Cualquier otro tipo no mueve la aguja (se ignora, no se adivina).
TIPO_INGRESO: Final[str] = "ingreso"
TIPO_EGRESO: Final[str] = "egreso"
# Meses que viajan en `por_mes` (el historial completo sigue en `items`).
MESES_EN_PAYLOAD: Final[int] = 12

# ── Los 5 estados de una reserva en el historial ──────────────────────────────
ESTADO_ASISTIO: Final[str] = "asistio"
ESTADO_FALTO: Final[str] = "falto"
ESTADO_CANCELADA: Final[str] = "cancelada"
ESTADO_CANCELADA_TARDIA: Final[str] = "cancelada_tarde"
ESTADO_RESERVADA: Final[str] = "reservada"
ESTADOS_ASISTENCIA: Final[tuple] = (
    ESTADO_ASISTIO, ESTADO_FALTO, ESTADO_CANCELADA, ESTADO_CANCELADA_TARDIA,
    ESTADO_RESERVADA,
)
# Los que "cuentan" para el % de asistencia: cancelar a tiempo no ensucia el número.
ESTADOS_QUE_CUENTAN: Final[tuple] = (
    ESTADO_ASISTIO, ESTADO_FALTO, ESTADO_CANCELADA_TARDIA)

# ── Las 7 secciones del panel ─────────────────────────────────────────────────
SECCIONES: Final[tuple] = (
    ("resumen", "Resumen"),
    ("asistencia", "Asistencia"),
    ("pagos", "Pagos"),
    ("membresias", "Membresías"),
    ("bazar", "Bazar"),
    ("rms", "RMs"),
    ("beneficios", "Beneficios"),
)
# La sección de beneficios dejó de estar reservada: la F2 la implementa, así que se anuncia como
# las demás (el id sigue siendo el mismo y el menú se arma de `SECCIONES`).
SECCIONES_RESERVADAS: Final[tuple] = ()

DEFAULT_SECCION: Final[str] = "resumen"
DEFAULT_POR_PAGINA: Final[int] = 25
MAX_POR_PAGINA: Final[int] = 100


# ── Helpers de fecha ──────────────────────────────────────────────────────────
def _tz(dt: datetime) -> datetime:
    """El instante de la BD como tz-aware (las columnas son timestamptz; por si acaso)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# `fecha_chile` NO se define acá: es la de `app.utils.santiago` (una sola definición,
# compartida con las plantillas de Fidelización). Se importa arriba con el mismo nombre.


def inicio_clase(clase) -> datetime:
    """Instante de inicio de una clase, en hora de Chile (tz-aware)."""
    return datetime.combine(clase.fecha, clase.hora_inicio, tzinfo=SANTIAGO)


def _fin_del_dia(dia: date) -> datetime:
    return datetime.combine(dia, _time.max, tzinfo=SANTIAGO)


def _inicio_del_dia(dia: date) -> datetime:
    return datetime.combine(dia, _time.min, tzinfo=SANTIAGO)


def _rango_mes(anio: int, mes: int) -> tuple:
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


# ── Predicados puros (se testean sin BD) ──────────────────────────────────────
def estado_asistencia(reserva, clase, ahora: datetime = None) -> str:
    """Los 5 estados del historial para UNA reserva.

    * cancelada por el alumno → `cancelada` (a tiempo) o `cancelada_tarde` (a menos de 6 h del
      inicio; usa `reserva.updated_at`, que es el momento de la cancelación y el mismo dato con
      el que A.3 reconstruye la devolución del crédito);
    * `asistio = true` → `asistio`;
    * clase ya empezada → `falto`;
    * clase futura → `reservada`.
    """
    ahora = ahora or ahora_santiago()
    if es_cancelada(reserva.estado):
        if reserva.updated_at is None:
            # Sin timestamp de cancelación no se puede saber si fue tarde: no se inventa.
            return ESTADO_CANCELADA
        limite = inicio_clase(clase) - timedelta(hours=HORAS_CANCELACION_TARDIA)
        return (ESTADO_CANCELADA_TARDIA if _tz(reserva.updated_at) > limite
                else ESTADO_CANCELADA)
    if reserva.asistio:
        return ESTADO_ASISTIO
    return ESTADO_RESERVADA if inicio_clase(clase) > ahora else ESTADO_FALTO


def suscripcion_del_mes(suscripciones: list, anio: int, mes: int):
    """La suscripción VIGENTE en ese mes calendario, o None.

    Espejo en Python de `shared.estados.sql_suscripcion_vigente()` (mismas dos reglas: fechas
    inclusivas y estado distinto de los que nunca estuvieron vigentes). Si el alumno tuvo dos
    planes en el mes (un cambio en el medio), devuelve el que empezó más tarde: es el que
    corresponde a la mayor parte del mes.
    """
    primero, ultimo = _rango_mes(anio, mes)
    vigentes = [
        s for s in suscripciones
        if s.estado not in ESTADOS_SUSCRIPCION_NUNCA_VIGENTES
        and fecha_chile(s.fecha_inicio) <= ultimo
        and fecha_chile(s.fecha_expiracion) >= primero
    ]
    if not vigentes:
        return None
    return max(vigentes, key=lambda s: _tz(s.fecha_inicio))


def _meses_entre(desde: tuple, hasta: tuple) -> list:
    """[(anio, mes)] de `desde` a `hasta`, ambos inclusive."""
    meses = []
    a, m = desde
    while (a, m) <= hasta:
        meses.append((a, m))
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return meses


# ── "Alumno desde" y promedio semanal (predicados PUROS: se testean sin BD) ──────────
def _mes_anterior(anio: int, mes: int) -> tuple:
    """`(anio, mes)` del mes ANTERIOR. Puro (se testea sin BD)."""
    return (anio - 1, 12) if mes == 1 else (anio, mes - 1)


def _como_fecha(valor):
    """`date` del valor: acepta un `date` (Clase.fecha) o un `datetime` tz-aware.

    `Clase.fecha` es `date` y `Suscripcion.fecha_inicio` / `usuarios.created_at` son
    `timestamptz`: los helpers puros tienen que aceptar los dos sin asumir la TZ del
    servidor (ver `fecha_chile`). `None` entra, `None` sale.
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return fecha_chile(valor)
    return valor


def inicio_actividad(created_at=None, primera_suscripcion=None, primera_asistencia=None):
    """Primer día REAL del alumno en el box (la fecha "alumno desde", regla 3).

    Es la fecha MÁS ANTIGUA entre la primera suscripción (vigente alguna vez) y la primera
    asistencia; la creación del usuario (`created_at`) sólo se usa como RESPALDO cuando no
    hay ninguna de las dos —un alumno recién creado, sin plan ni clase—: nunca compite por
    ser "la más antigua" (un alta vieja sin actividad no adelanta el "alumno desde").
    Devuelve `(fecha, fuente)` con `fuente` in `{"suscripcion", "asistencia", "alta"}`, o
    `(None, None)` sin datos.

    Antes se mostraba directamente `usuarios.created_at`: un alumno dado de alta en
    diciembre y activado en marzo contaba "alumno desde diciembre" con 0 asistencias.
    Puro: recibe fechas ya resueltas (se testea sin BD).
    """
    candidatos = []
    for valor, fuente in ((primera_suscripcion, "suscripcion"),
                          (primera_asistencia, "asistencia")):
        fecha = _como_fecha(valor)
        if fecha is not None:
            candidatos.append((fecha, fuente))
    if candidatos:
        return min(candidatos, key=lambda c: c[0])
    alta = _como_fecha(created_at)
    return (alta, "alta") if alta is not None else (None, None)


def promedio_semanal(asistidas: int, inicio, hoy: date) -> float:
    """Asistencias por SEMANA REAL del período (`inicio` → `hoy`), con piso de 1 semana.

    Antes el denominador eran las semanas desde el ALTA del usuario: un alumno dado de alta
    y activado meses después arrastraba todas esas semanas vacías y su promedio se
    desplomaba. El denominador es el período en el que DE VERDAD fue alumno. Puro.
    """
    desde = _como_fecha(inicio)
    if desde is None:
        return 0.0
    semanas = max(1.0, (hoy - desde).days / 7)
    return round(asistidas / semanas, 1)


def _paginado(items: list, pagina: int, por_pagina: int) -> dict:
    """Lista recortada a la página pedida + los metadatos de paginación."""
    total = len(items)
    paginas = max(1, (total + por_pagina - 1) // por_pagina if por_pagina else 1)
    inicio = max(0, (pagina - 1) * por_pagina)
    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": paginas,
        "items": items[inicio:inicio + por_pagina],
    }


def secciones_disponibles() -> list:
    """El menú de pestañas del panel: SÓLO las secciones listas para usarse.

    Las reservadas (`SECCIONES_RESERVADAS`) no se anuncian: una pestaña deshabilitada con "llega
    más adelante" es ruido y una promesa que el alumno no pidió. Hoy la lista está vacía (la sección
    `beneficios` se anunció al implementarse la F2) y el filtro sigue siendo de MENÚ, no de servicio:
    el id sigue siendo válido para quien lo pida.
    """
    return [
        {
            "id": sid,
            "label": label,
            "disponible": True,
            "motivo": None,
        }
        for sid, label in SECCIONES
        if sid not in SECCIONES_RESERVADAS
    ]


# ── Asistencia: carga + agregados (una sola pasada, un solo criterio) ─────────
def _filas_asistencia(db: Session, alumno_id: int, tenant_id: int) -> tuple:
    """(filas vivas, cantidad de clases suspendidas por el box) de las reservas del alumno.

    Fila = `(Reserva, Clase, disciplina_nombre, coach_nombre)`. Las clases que canceló el BOX
    se separan en el origen: no son responsabilidad del alumno (regla 6) y no deben entrar ni al
    listado ni a los porcentajes.
    """
    filas = (
        db.query(Reserva, Clase, Disciplina.nombre, Usuario.nombre)
        .join(Clase, Reserva.clase_id == Clase.id)
        .outerjoin(Disciplina, Clase.disciplina_id == Disciplina.id)
        .outerjoin(Usuario, Clase.coach_id == Usuario.id)
        .filter(Reserva.tenant_id == tenant_id, Reserva.alumno_id == alumno_id)
        .order_by(Clase.fecha.desc(), Clase.hora_inicio.desc(), Reserva.id.desc())
        .all()
    )
    vivas = [f for f in filas if not f[1].cancelada]
    return vivas, len(filas) - len(vivas)


def _agregados_asistencia(filas: list, alumno, ahora: datetime, hoy: date,
                          inicio=None) -> dict:
    """Totales, promedio semanal y desglose por mes de las reservas vivas.

    `inicio` es el `(fecha, fuente)` de `inicio_actividad`: el período REAL del alumno.
    Sin él (o sin fechas) se cae al alta del usuario, para no cambiar el resto de la API.
    """
    conteo = {estado: 0 for estado in ESTADOS_ASISTENCIA}
    por_mes = {}
    ultima_asistencia = None

    for reserva, clase, _disc, _coach in filas:
        estado = estado_asistencia(reserva, clase, ahora)
        conteo[estado] += 1
        clave = (clase.fecha.year, clase.fecha.month)
        fila_mes = por_mes.setdefault(clave, {
            "anio": clase.fecha.year,
            "mes": clase.fecha.month,
            **{e: 0 for e in ESTADOS_ASISTENCIA},
        })
        fila_mes[estado] += 1
        if estado == ESTADO_ASISTIO and (ultima_asistencia is None
                                         or clase.fecha > ultima_asistencia):
            ultima_asistencia = clase.fecha

    asistidas = conteo[ESTADO_ASISTIO]
    cuentan = sum(conteo[e] for e in ESTADOS_QUE_CUENTAN)
    pct = round(asistidas / cuentan * 100) if cuentan else 0

    # "Alumno desde" = primeras suscripción/asistencia (regla 3): el promedio por semana y
    # los días como alumno se miden sobre ESE período, no desde el alta del usuario.
    desde = _como_fecha(inicio[0]) if inicio else None
    if desde is None:
        desde = _como_fecha(getattr(alumno, "created_at", None))
    dias_como_alumno = (hoy - desde).days if desde is not None else None
    promedio = promedio_semanal(asistidas, desde, hoy)

    meses = []
    for clave in sorted(por_mes, reverse=True)[:MESES_EN_PAYLOAD]:
        fila_mes = por_mes[clave]
        cuentan_mes = sum(fila_mes[e] for e in ESTADOS_QUE_CUENTAN)
        fila_mes["cuentan"] = cuentan_mes
        fila_mes["pct"] = round(fila_mes[ESTADO_ASISTIO] / cuentan_mes * 100) if cuentan_mes else 0
        meses.append(fila_mes)

    return {
        "conteo": conteo,
        "total": len(filas),
        "pct": pct,
        "promedio_semanal": promedio,
        "dias_como_alumno": dias_como_alumno,
        "ultima_asistencia": ultima_asistencia,
        "dias_sin_asistir": (hoy - ultima_asistencia).days if ultima_asistencia else None,
        "por_mes": meses,
    }


def _item_asistencia(reserva, clase, disciplina, coach, ahora: datetime) -> dict:
    """Una reserva tal como la muestra el historial (con su estado de 5 valores)."""
    return {
        "reserva_id": reserva.id,
        "clase_id": clase.id,
        "fecha": clase.fecha,
        "hora_inicio": clase.hora_inicio.strftime("%H:%M"),
        "hora_fin": clase.hora_fin.strftime("%H:%M"),
        "disciplina": disciplina,
        "coach": coach,
        "estado_asistencia": estado_asistencia(reserva, clase, ahora),
        "estado_reserva": reserva.estado,
        "asistio": bool(reserva.asistio),
        "creditos_gastados": reserva.tokens_gastados or 0,
    }


def _seccion_asistencia(db, alumno, tenant_id, pagina, por_pagina, inicio=None, **_kw) -> dict:
    ahora = ahora_santiago()
    vivas, suspendidas = _filas_asistencia(db, alumno.id, tenant_id)
    agg = _agregados_asistencia(vivas, alumno, ahora, ahora.date(), inicio=inicio)
    items = [
        _item_asistencia(reserva, clase, disc, coach, ahora)
        for reserva, clase, disc, coach in vivas
    ]
    paginado = _paginado(items, pagina, por_pagina)
    return {
        "totales": {
            **agg["conteo"],
            "clases_suspendidas": suspendidas,
            "total": agg["total"],
            "cuentan": sum(agg["conteo"][e] for e in ESTADOS_QUE_CUENTAN),
            "pct_asistencia": agg["pct"],
            "promedio_semanal": agg["promedio_semanal"],
            "dias_como_alumno": agg["dias_como_alumno"],
            "ultima_asistencia": agg["ultima_asistencia"],
            "dias_sin_asistir": agg["dias_sin_asistir"],
        },
        "por_mes": agg["por_mes"],
        "paginado": {k: v for k, v in paginado.items() if k != "items"},
        "items": paginado["items"],
    }


# ── Membresías ────────────────────────────────────────────────────────────────
def _valor(estado):
    """`estado` como texto (el ORM devuelve el miembro del enum nativo `estado_suscripcion`)."""
    if estado is None:
        return None
    return getattr(estado, "value", None) or str(estado)


def _suscripciones(db: Session, alumno_id: int, tenant_id: int) -> list:
    """Todas las suscripciones del alumno (las más nuevas primero), incluidas las que nunca
    estuvieron vigentes: la sección Membresías las muestra, pero no cuentan como mes con plan."""
    return (
        db.query(Suscripcion)
        .filter(Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == alumno_id)
        .order_by(Suscripcion.fecha_inicio.desc(), Suscripcion.id.desc())
        .all()
    )


def _planes_por_id(db: Session, tenant_id: int, ids) -> dict:
    """{plan_id: Plan} de una sola query (sin N+1 al armar la lista de meses)."""
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    planes = db.query(Plan).filter(Plan.tenant_id == tenant_id,
                                   Plan.id.in_(ids)).all()
    return {p.id: p for p in planes}


def _primer_mes(alumno, suscripciones: list):
    """Mes más viejo entre el alta y la primera suscripción (ahí arranca el historial)."""
    candidatos = []
    if getattr(alumno, "created_at", None):
        f = fecha_chile(alumno.created_at)
        candidatos.append((f.year, f.month))
    for s in suscripciones:
        f = fecha_chile(s.fecha_inicio)
        candidatos.append((f.year, f.month))
    return min(candidatos) if candidatos else None


def _membresia_actual(db: Session, alumno_id: int, tenant_id: int, hoy: date):
    """Plan vigente HOY, o None. Regla 5: lo deciden las fechas (hora de Chile) y el estado."""
    fila = (
        db.query(Suscripcion, Plan)
        .join(Plan, Suscripcion.plan_id == Plan.id)
        .filter(Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == alumno_id,
                Suscripcion.estado.notin_(ESTADOS_SUSCRIPCION_NUNCA_VIGENTES),
                Suscripcion.fecha_inicio <= _fin_del_dia(hoy),
                Suscripcion.fecha_expiracion >= _inicio_del_dia(hoy))
        .order_by(Suscripcion.fecha_inicio.desc())
        .first()
    )
    if fila is None:
        return None
    suscripcion, plan = fila
    vence = fecha_chile(suscripcion.fecha_expiracion)
    return {
        "suscripcion_id": suscripcion.id,
        "plan_id": plan.id,
        "plan": plan.nombre,
        "estado": _valor(suscripcion.estado),
        "precio_clp": plan.precio_clp,
        "es_ilimitado": bool(plan.es_ilimitado),
        "creditos_totales": suscripcion.creditos_totales,
        "creditos_disponibles": suscripcion.creditos_disponibles,
        "fecha_inicio": fecha_chile(suscripcion.fecha_inicio),
        "fecha_expiracion": vence,
        "dias_restantes": (vence - hoy).days,
    }


def _seccion_membresias(db, alumno, tenant_id, pagina, por_pagina, **_kw) -> dict:
    hoy = hoy_santiago()
    suscripciones = _suscripciones(db, alumno.id, tenant_id)
    planes = _planes_por_id(db, tenant_id, {s.plan_id for s in suscripciones})

    primer_mes = _primer_mes(alumno, suscripciones)
    meses = _meses_entre(primer_mes, (hoy.year, hoy.month)) if primer_mes else []

    items = []
    for anio, mes in reversed(meses):        # del más nuevo al más viejo
        suscripcion = suscripcion_del_mes(suscripciones, anio, mes)
        plan = planes.get(suscripcion.plan_id) if suscripcion else None
        items.append({
            "anio": anio,
            "mes": mes,
            "con_plan": suscripcion is not None,
            "plan_id": suscripcion.plan_id if suscripcion else None,
            "plan": plan.nombre if plan else None,
            "precio_clp": plan.precio_clp if plan else 0,
            "estado": _valor(suscripcion.estado) if suscripcion else None,
            "suscripcion_id": suscripcion.id if suscripcion else None,
        })

    con_plan = sum(1 for i in items if i["con_plan"])
    paginado = _paginado(items, pagina, por_pagina)
    return {
        "resumen": {
            "meses_como_alumno": len(items),
            "meses_con_plan": con_plan,
            "meses_sin_plan": len(items) - con_plan,
            "primer_mes": ({"anio": primer_mes[0], "mes": primer_mes[1]}
                           if primer_mes else None),
        },
        "membresia_actual": _membresia_actual(db, alumno.id, tenant_id, hoy),
        "suscripciones": [
            {
                "id": s.id,
                "plan_id": s.plan_id,
                "plan": planes[s.plan_id].nombre if s.plan_id in planes else None,
                "estado": _valor(s.estado),
                "fecha_inicio": fecha_chile(s.fecha_inicio),
                "fecha_expiracion": fecha_chile(s.fecha_expiracion),
                "precio_clp": planes[s.plan_id].precio_clp if s.plan_id in planes else None,
                "creditos_totales": s.creditos_totales,
                "creditos_disponibles": s.creditos_disponibles,
                "es_compra_emergencia": bool(s.es_compra_emergencia),
                "cuenta_como_vigente": s.estado not in ESTADOS_SUSCRIPCION_NUNCA_VIGENTES,
            }
            for s in suscripciones
        ],
        "paginado": {k: v for k, v in paginado.items() if k != "items"},
        "items": paginado["items"],
    }


# ── Pagos (membresías + Bazar) ────────────────────────────────────────────────
# La referencia con la que se ata una transacción financiera a una suscripción (mismo valor que
# escriben `suscripciones.py` y `solicitudes_planes.py` al cobrar).
REFERENCIA_SUSCRIPCION: Final[str] = "suscripcion"


def signo_transaccion(tipo) -> int:
    """Cuánto mueve una transacción financiera en "lo que se pagó": +1 ingreso, -1 devolución.

    Un `tipo` desconocido devuelve 0: no se adivina a favor ni en contra del alumno.
    """
    if tipo == TIPO_INGRESO:
        return 1
    if tipo == TIPO_EGRESO:
        return -1
    return 0


def monto_cobrado(transacciones) -> int:
    """Lo REALMENTE cobrado por una membresía: sus ingresos menos sus devoluciones (regla 4).

    Es la razón por la que el historial no puede usar el precio de lista: con un descuento (o
    con un reembolso) el precio de lista miente sobre lo que entró a la caja del box.
    """
    return sum(signo_transaccion(t.tipo) * round(t.monto or 0) for t in transacciones)


def _transacciones_por_suscripcion(db: Session, tenant_id: int, ids) -> dict:
    """`{suscripcion_id: [TransaccionFinanciera]}` en UNA query (nada de N+1 por membresía)."""
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    filas = (
        db.query(TransaccionFinanciera)
        .filter(TransaccionFinanciera.tenant_id == tenant_id,
                TransaccionFinanciera.referencia_tipo == REFERENCIA_SUSCRIPCION,
                TransaccionFinanciera.referencia_id.in_(ids))
        .order_by(TransaccionFinanciera.fecha, TransaccionFinanciera.id)
        .all()
    )
    por_suscripcion = {}
    for tx in filas:
        por_suscripcion.setdefault(tx.referencia_id, []).append(tx)
    return por_suscripcion


def _items_pagos(db: Session, alumno_id: int, tenant_id: int) -> list:
    """Membresías (por lo COBRADO, regla 4) + Bazar, del más nuevo al más viejo.

    `fecha` es SIEMPRE `date`: mezclar `datetime` y `date` en el mismo `sort` es un TypeError
    en Python (y `fecha_pedido`/`fecha_inicio` son timestamptz). La fecha del pago de una
    membresía es el INICIO de la membresía (el monto, en cambio, es el de sus transacciones).
    """
    items = []

    filas = (
        db.query(Suscripcion, Plan)
        .join(Plan, Suscripcion.plan_id == Plan.id)
        .filter(Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == alumno_id)
        .all()
    )
    contaron = [(s, p) for s, p in filas
                if s.estado not in ESTADOS_SUSCRIPCION_NUNCA_VIGENTES]
    transacciones = _transacciones_por_suscripcion(
        db, tenant_id, [s.id for s, _ in contaron])

    for suscripcion, plan in contaron:
        # Nunca contó (pendiente/rechazado) => no es un pago ni un mes con plan.
        txs = transacciones.get(suscripcion.id, [])
        cobrado = monto_cobrado(txs)
        lista = round(plan.precio_clp or 0)
        items.append({
            "tipo": "membresia",
            "referencia_id": suscripcion.id,
            "fecha": fecha_chile(suscripcion.fecha_inicio),
            "detalle": plan.nombre,
            "monto_clp": cobrado,
            # Lo que VALE el plan, para que el descuento se vea sin inventar un número.
            "precio_lista_clp": lista,
            "descuento_clp": max(0, lista - cobrado),
            "transacciones": len(txs),
            "estado": _valor(suscripcion.estado),
        })

    pedidos = (
        db.query(Pedido, Producto.nombre)
        .outerjoin(Producto, Pedido.producto_id == Producto.id)
        .filter(Pedido.tenant_id == tenant_id,
                Pedido.alumno_id == alumno_id,
                # "Venta del Bazar cobrada": predicado COMPARTIDO con el BI y con el Excel de
                # Reportes (misma lista `shared.estados.ESTADOS_PAGO_BAZAR`).
                pago_bazar(Pedido.estado))
        .all()
    )
    for pedido, producto in pedidos:
        items.append({
            "tipo": "bazar",
            "referencia_id": pedido.id,
            "fecha": fecha_chile(pedido.fecha_pedido),
            "detalle": f"{pedido.cantidad or 1}x {producto or 'producto'}",
            "monto_clp": round(pedido.total or 0),
            # El Bazar ya se cobra por su total real: no tiene precio de lista ni descuento.
            "precio_lista_clp": None,
            "descuento_clp": 0,
            "transacciones": None,
            "estado": pedido.estado,
        })

    items.sort(key=lambda i: (i["fecha"], i["tipo"]), reverse=True)
    return items


def _seccion_pagos(db, alumno, tenant_id, pagina, por_pagina, **_kw) -> dict:
    items = _items_pagos(db, alumno.id, tenant_id)

    membresias = sum(i["monto_clp"] for i in items if i["tipo"] == "membresia")
    bazar = sum(i["monto_clp"] for i in items if i["tipo"] == "bazar")
    descuentos = sum(i["descuento_clp"] for i in items)

    por_anio = {}
    for item in items:
        fila = por_anio.setdefault(
            item["fecha"].year,
            {"anio": item["fecha"].year, "membresias": 0, "bazar": 0})
        fila["membresias" if item["tipo"] == "membresia" else "bazar"] += item["monto_clp"]
    for fila in por_anio.values():
        fila["total"] = fila["membresias"] + fila["bazar"]

    paginado = _paginado(items, pagina, por_pagina)
    return {
        "totales": {
            "total_clp": membresias + bazar,
            "membresias_clp": membresias,
            "bazar_clp": bazar,
            "descuentos_clp": descuentos,
            "pagos": len(items),
            "ultimo_pago": items[0]["fecha"] if items else None,
        },
        "por_anio": [por_anio[a] for a in sorted(por_anio, reverse=True)],
        "paginado": {k: v for k, v in paginado.items() if k != "items"},
        "items": paginado["items"],
    }


# ── Bazar (los pedidos del alumno: qué pidió, cuánto y si ya lo retiró) ────────────────────────
def _pedidos_bazar(db: Session, alumno_id: int, tenant_id: int) -> list:
    """Pedidos del alumno, del más nuevo al más viejo, con producto y quién lo entregó.

    Es el HISTORIAL de pedidos (TODOS los estados: incluye los `pendiente` —comprobante sin
    revisar— y los `cancelado`), NO la plata cobrada: `cobrado` marca cuáles suman
    (`ESTADOS_PAGO_BAZAR`, el mismo criterio que la pestaña Pagos, el BI y el Excel).

    `entregado_por` sale de `usuarios` (migración 044, `ON DELETE SET NULL`): si el usuario que
    entregó se dio de baja, queda en `None` y la UI muestra la fecha y el código, no un nombre
    inventado. `entregado_en` es el DÍA CHILENO de la entrega (o `None` si todavía no se entregó).
    """
    filas = (
        db.query(Pedido, Producto.nombre, Usuario.nombre)
        .outerjoin(Producto, Pedido.producto_id == Producto.id)
        .outerjoin(Usuario, Pedido.entregado_por == Usuario.id)
        .filter(Pedido.tenant_id == tenant_id,
                Pedido.alumno_id == alumno_id)
        .all()
    )

    items = []
    for pedido, producto, entregado_por in filas:
        items.append({
            "id": pedido.id,
            "fecha": fecha_chile(pedido.fecha_pedido),
            "producto": producto or f"Producto {pedido.producto_id}",
            "cantidad": pedido.cantidad or 1,
            "total_clp": round(pedido.total or 0),
            "estado": pedido.estado,
            # ¿Es plata cobrada? La MISMA lista compartida que usa el resto del sistema.
            "cobrado": pedido.estado in ESTADOS_PAGO_BAZAR,
            # Código de retiro (migración 044): se genera al validar; NULL mientras no se valide.
            "codigo_retiro": pedido.codigo_retiro,
            "entregado_por": entregado_por,
            "entregado_en": fecha_chile(pedido.entregado_en),
        })
    items.sort(key=lambda i: (i["fecha"], i["id"]), reverse=True)
    return items


def _seccion_bazar(db, alumno, tenant_id, pagina, por_pagina, **_kw) -> dict:
    """Los pedidos del Bazar del alumno, uno por fila.

    Es el detalle del Bazar separado de Pagos: acá se ven TAMBIÉN los pedidos que no son plata
    (`pendiente`, `cancelado`) y los datos del retiro (código, quién y cuándo entregó). El monto
    que suma es sólo el de los pedidos cobrados, así que coincide con el "Bazar" de la pestaña
    Pagos, con el BI y con el Excel de Reportes.
    """
    items = _pedidos_bazar(db, alumno.id, tenant_id)

    cobrados = [i for i in items if i["cobrado"]]
    conteo = Counter(i["estado"] for i in items)
    paginado = _paginado(items, pagina, por_pagina)
    return {
        "totales": {
            "pedidos": len(items),
            "cobrados": len(cobrados),
            "entregados": conteo.get("entregado", 0),
            "pendientes": conteo.get("pendiente", 0),
            # Plata COBRADA por Bazar (mismo criterio que la pestaña Pagos): un pendiente no es
            # un pago todavía.
            "cobrado_clp": sum(i["total_clp"] for i in cobrados),
            "unidades": sum(i["cantidad"] for i in items),
            "ultimo_pedido": items[0]["fecha"] if items else None,
        },
        "paginado": {k: v for k, v in paginado.items() if k != "items"},
        "items": paginado["items"],
    }



# ── RMs ───────────────────────────────────────────────────────────────────────
def _seccion_rms(db, alumno, tenant_id, pagina, por_pagina, **_kw) -> dict:
    """Mejor RM por movimiento (definición única en `rms_service`) + su contexto.

    La evolución fina de UN movimiento ya existe en
    `GET /historial-rm/alumnos/{id}/movimiento/{movimiento_id}` y no se duplica acá.
    """
    items = mejor_rm_por_movimiento(db, alumno.id, tenant_id)

    filas = (
        db.query(HistorialRM.movimiento_id,
                 func.count(HistorialRM.id),
                 func.min(HistorialRM.fecha),
                 func.max(HistorialRM.fecha))
        .filter(HistorialRM.alumno_id == alumno.id,
                HistorialRM.tenant_id == tenant_id)
        .group_by(HistorialRM.movimiento_id)
        .all()
    )
    contexto = {f[0]: {"registros": f[1], "primera_fecha": f[2], "ultima_fecha": f[3]}
                for f in filas}
    for item in items:
        item.update(contexto.get(item["movimiento_id"], {}))

    por_categoria = Counter(i["categoria"] for i in items)
    paginado = _paginado(items, pagina, por_pagina)
    return {
        "totales": {
            "movimientos": len(items),
            "registros": sum(i.get("registros", 0) for i in items),
            "por_categoria": dict(por_categoria),
        },
        "paginado": {k: v for k, v in paginado.items() if k != "items"},
        "items": paginado["items"],
    }


# ── Beneficios (F2 de Fidelización: el regalo y si sirvió) ────────────────────
def _beneficio_item(beneficio) -> dict:
    """Un beneficio como lo lee el historial: qué se regaló, si sigue vivo y si el alumno lo usó.

    El estado lo define `beneficios_service.esta_vivo()` (la MISMA regla que usa el panel): un
    `ofrecido` con la ventana pasada se muestra `vencido` aunque la fila todavía diga `ofrecido`.
    """
    vivo = beneficio_esta_vivo(beneficio)
    estado = ("vigente" if vivo else
              ("vencido" if beneficio.estado == EstadoBeneficio.ofrecido
               else beneficio.estado.value))
    return {
        "id": beneficio.id,
        "tipo": beneficio.tipo.value,
        "tipo_label": beneficio_etiqueta(beneficio.tipo),
        "valor": beneficio.valor,
        "unidad": "pct" if beneficio.tipo == TipoBeneficio.descuento else "clases",
        "estado": estado,
        "created_at": beneficio.created_at,
        "vigente_hasta": beneficio.vigente_hasta,
        "usado_en": beneficio.usado_en,
        "descuento_clp": beneficio.descuento_clp,
        "anulado_motivo": beneficio.anulado_motivo,
        # Si el regalo salió con correo, el historial puede decirlo (el correo NO es obligatorio).
        "avisado_por_correo": beneficio.notificacion_id is not None,
    }


def _seccion_beneficios(db, alumno, tenant_id, pagina, por_pagina, **_kw) -> dict:
    """6ª sección: los regalos del alumno (clases gratis y descuentos) y qué pasó con cada uno.

    Se muestran TODOS —vigentes, usados, vencidos y anulados— porque esta sección es la auditoría
    del gesto: la anulación exige motivo y acá está el motivo. Los números del encabezado son los
    mismos estados que muestra el panel de Fidelización (una sola definición: `esta_vivo`).
    """
    filas = db.query(Beneficio).filter(
        Beneficio.tenant_id == tenant_id,
        Beneficio.alumno_id == alumno.id,
    ).order_by(Beneficio.created_at.desc(), Beneficio.id.desc()).all()
    items = [_beneficio_item(b) for b in filas]
    por_estado = {estado: sum(1 for i in items if i["estado"] == estado)
                  for estado in ("vigente", "usado", "vencido", "anulado")}
    paginado = _paginado(items, pagina, por_pagina)
    return {
        "disponible": True,
        "motivo": None,
        "totales": {
            "total": len(items),
            "vigentes": por_estado["vigente"],
            "usados": por_estado["usado"],
            "vencidos": por_estado["vencido"],
            "anulados": por_estado["anulado"],
        },
        "paginado": {k: paginado[k] for k in ("total", "pagina", "por_pagina", "paginas")},
        "items": paginado["items"],
    }


# ── Datos de gestión (sólo staff) ─────────────────────────────────────────────
def _datos_gestion(db: Session, alumno_id: int, tenant_id: int,
                   dias_sin_asistir) -> dict:
    """Arquetipo (K-Means), riesgo de churn y gestión del riesgo: insumo del BOX.

    `incluir_privado=False` (el PROPIO alumno) no llama a esta función: un arquetipo
    "ABANDONADO_PERDIDO" o una probabilidad de baja no son información para el alumno.
    """
    segmentacion = db.query(SegmentacionAlumno).filter(
        SegmentacionAlumno.tenant_id == tenant_id,
        SegmentacionAlumno.usuario_id == alumno_id).first()
    prediccion = db.query(PredictionsChurn).filter(
        PredictionsChurn.tenant_id == tenant_id,
        PredictionsChurn.usuario_id == alumno_id,
    ).order_by(PredictionsChurn.created_at.desc(),
               PredictionsChurn.id.desc()).first()
    gestion = db.query(ChurnGestion).filter(
        ChurnGestion.tenant_id == tenant_id,
        ChurnGestion.usuario_id == alumno_id).first()
    return {
        "arquetipo": segmentacion.arquetipo if segmentacion else None,
        "cluster_id": segmentacion.cluster_id if segmentacion else None,
        "riesgo_nivel": prediccion.riesgo_nivel if prediccion else None,
        "riesgo_probabilidad": (float(prediccion.probabilidad_churn)
                                if prediccion else None),
        "riesgo_motivo": prediccion.motivo if prediccion else None,
        "estado_gestion": gestion.estado_gestion if gestion else None,
        "dias_sin_asistir": dias_sin_asistir,
    }


def _hitos(db: Session, alumno_id: int, tenant_id: int) -> dict:
    """Hitos de constancia (1/3/6/12 meses al 100%): cuántos y el mayor alcanzado."""
    total, nivel = (
        db.query(func.count(HitoAlumno.id), func.max(HitoAlumno.nivel))
        .filter(HitoAlumno.tenant_id == tenant_id,
                HitoAlumno.alumno_id == alumno_id)
        .first()
    )
    return {
        "alcanzados": int(total or 0),
        "nivel_maximo": int(nivel) if nivel else None,
    }


# ── Resumen ───────────────────────────────────────────────────────────────────
def _seccion_resumen(db, alumno, tenant_id, pagina, por_pagina,
                     incluir_privado=True, inicio=None) -> dict:
    """La foto de hoy del alumno. Los bloques de Pagos y RMs se piden a SUS secciones
    (pidiendo 1 item por página: los totales no dependen de la página), así el número del
    Resumen y el de la pestaña son el MISMO por construcción, no por coincidencia."""
    from app.services.asistencia_service import calcular_racha   # racha: definición existente

    ahora = ahora_santiago()
    hoy = ahora.date()

    vivas, suspendidas = _filas_asistencia(db, alumno.id, tenant_id)
    agg = _agregados_asistencia(vivas, alumno, ahora, hoy, inicio=inicio)
    # Racha: SÓLO meses COMPLETOS. El mes en curso todavía no terminó —un mes perfecto a
    # mitad de camino no es "100% en un mes completo"—, así que la caminata arranca en el
    # mes ANTERIOR. Un alumno con actividad sólo en el mes en curso da racha 0 (nada cerrado).
    anio_racha, mes_racha = _mes_anterior(hoy.year, hoy.month)
    racha = calcular_racha(db, alumno.id, tenant_id, anio_racha, mes_racha)

    suscripciones = _suscripciones(db, alumno.id, tenant_id)
    primer_mes = _primer_mes(alumno, suscripciones)
    meses = _meses_entre(primer_mes, (hoy.year, hoy.month)) if primer_mes else []
    meses_con_plan = sum(1 for a, m in meses
                         if suscripcion_del_mes(suscripciones, a, m) is not None)

    datos = {
        "asistencia": {
            "total": agg["total"],
            "asistidas": agg["conteo"][ESTADO_ASISTIO],
            "faltadas": agg["conteo"][ESTADO_FALTO],
            "canceladas": agg["conteo"][ESTADO_CANCELADA],
            "canceladas_tardias": agg["conteo"][ESTADO_CANCELADA_TARDIA],
            "reservadas": agg["conteo"][ESTADO_RESERVADA],
            "pct_asistencia": agg["pct"],
            "promedio_semanal": agg["promedio_semanal"],
            "dias_como_alumno": agg["dias_como_alumno"],
            "ultima_asistencia": agg["ultima_asistencia"],
            "dias_sin_asistir": agg["dias_sin_asistir"],
            "racha_meses_100": racha,
            "clases_suspendidas": suspendidas,
        },
        "membresia": {
            "actual": _membresia_actual(db, alumno.id, tenant_id, hoy),
            "meses_como_alumno": len(meses),
            "meses_con_plan": meses_con_plan,
            "meses_sin_plan": len(meses) - meses_con_plan,
        },
        "pagos": _seccion_pagos(db, alumno, tenant_id, 1, 1)["totales"],
        "rms": _seccion_rms(db, alumno, tenant_id, 1, 1)["totales"],
        "hitos": _hitos(db, alumno.id, tenant_id),
    }
    if incluir_privado:
        datos["gestion"] = _datos_gestion(db, alumno.id, tenant_id,
                                          agg["dias_sin_asistir"])
    return datos


# ── Entrada del panel ─────────────────────────────────────────────────────────
_SECCIONES = {
    "resumen": _seccion_resumen,
    "asistencia": _seccion_asistencia,
    "pagos": _seccion_pagos,
    "membresias": _seccion_membresias,
    "bazar": _seccion_bazar,
    "rms": _seccion_rms,
    "beneficios": _seccion_beneficios,
}


def normalizar_seccion(seccion) -> str:
    """Sección válida o `DEFAULT_SECCION` (`None`/desconocida no rompen el panel)."""
    return seccion if seccion in _SECCIONES else DEFAULT_SECCION


def _inicio_actividad(db: Session, alumno, tenant_id: int):
    """`inicio_actividad` con las fechas resueltas en la BD (una consulta por fuente).

    La primera suscripción ignora las que NUNCA estuvieron vigentes (pendiente/rechazado):
    una solicitud no es actividad. La primera asistencia sale de las reservas con
    `asistio = true` dentro del box del alumno.
    """
    primera_sus = (
        db.query(func.min(Suscripcion.fecha_inicio))
        .filter(Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == alumno.id,
                Suscripcion.estado.notin_(ESTADOS_SUSCRIPCION_NUNCA_VIGENTES))
        .scalar()
    )
    primera_asi = (
        db.query(func.min(Clase.fecha))
        .join(Reserva, Reserva.clase_id == Clase.id)
        .filter(Reserva.tenant_id == tenant_id,
                Reserva.alumno_id == alumno.id,
                Reserva.asistio.is_(True))
        .scalar()
    )
    return inicio_actividad(getattr(alumno, "created_at", None),
                            primera_sus, primera_asi)


def ficha_alumno(alumno, hoy: date = None, inicio=None, fuente: str = None) -> dict:
    """Identidad del alumno: acompaña a CUALQUIER sección (el encabezado del panel).

    `inicio` es la fecha REAL en que empezó a ser alumno (primera suscripción o primera
    asistencia, ver `inicio_actividad`); si no llega, se cae al alta del usuario. La fecha
    visible (`alumno_desde`) y la antigüedad se miden desde ahí; `created_at` se conserva
    como el registro del usuario (dato distinto del "alumno desde").
    """
    hoy = hoy or hoy_santiago()
    alta = getattr(alumno, "created_at", None)
    desde = _como_fecha(inicio) or _como_fecha(alta)
    dias = (hoy - desde).days if desde is not None else None
    return {
        "id": alumno.id,
        "nombre": alumno.nombre,
        "correo": alumno.correo,
        "telefono": alumno.telefono,
        "rut": alumno.rut,
        "genero": alumno.genero,
        "fecha_nacimiento": alumno.fecha_nacimiento,
        "estado": alumno.estado,
        "activo": bool(alumno.activo),
        "created_at": alta,
        # "Alumno desde": la primera suscripción o asistencia (regla 3), nunca el alta.
        "alumno_desde": desde,
        "alumno_desde_fuente": (fuente or "alta") if desde is not None else None,
        "antiguedad_dias": dias,
        "antiguedad_semanas": round(dias / 7, 1) if dias is not None else None,
    }


def panel(db: Session, alumno_id: int, tenant_id: int,
          seccion: str = DEFAULT_SECCION,
          pagina: int = 1,
          por_pagina: int = DEFAULT_POR_PAGINA,
          incluir_privado: bool = True):
    """El panel del Historial (ver el docstring del módulo). `None` si el alumno no existe.

    SIEMPRE devuelve la misma envoltura, así el frontend tiene UN solo cliente para las 6
    secciones. `incluir_privado=False` omite los datos de gestión del box (ver
    `_datos_gestion`).
    """
    seccion = normalizar_seccion(seccion)
    try:
        pagina = max(1, int(pagina or 1))
        por_pagina = min(MAX_POR_PAGINA, max(1, int(por_pagina or DEFAULT_POR_PAGINA)))
    except (TypeError, ValueError):
        pagina, por_pagina = 1, DEFAULT_POR_PAGINA

    alumno = (
        db.query(Usuario)
        .filter(Usuario.id == alumno_id, Usuario.tenant_id == tenant_id)
        .first()
    )
    if alumno is None:
        return None

    # "Alumno desde" (regla 3): primera suscripción o primera asistencia. Se resuelve una
    # vez acá y viaja a la ficha y a las secciones (promedio semanal y días como alumno).
    inicio, fuente_inicio = _inicio_actividad(db, alumno, tenant_id)

    datos = _SECCIONES[seccion](db, alumno, tenant_id, pagina, por_pagina,
                                incluir_privado=bool(incluir_privado), inicio=inicio)
    return {
        "alumno": ficha_alumno(alumno, inicio=inicio[0], fuente=fuente_inicio),
        "seccion": seccion,
        "secciones": secciones_disponibles(),
        "incluye_privado": bool(incluir_privado),
        "datos": datos,
    }
