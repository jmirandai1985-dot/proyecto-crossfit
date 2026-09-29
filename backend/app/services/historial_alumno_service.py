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
 4. `total_pagado` = membresías + Bazar. Membresías al PRECIO DE LISTA del plan de cada
    suscripción que alguna vez estuvo vigente —mismo criterio que `metricas_service.mrr`, que
    es "ingreso recurrente por precio de lista", no flujo cobrado—; Bazar por el `total` real
    de los pedidos `validado`/`entregado` (un pedido `pendiente` no es plata cobrada).
 5. "mes con plan" = mes calendario con una suscripción vigente. Mismo criterio que
    `shared.estados.sql_suscripcion_vigente()`: lo deciden las FECHAS (`fecha_inicio` dentro o
    antes del mes y `fecha_expiracion` dentro o después) y el estado sólo descarta lo que NUNCA
    estuvo vigente (`pendiente`/`rechazado`). Las fechas se leen en hora de CHILE, igual que
    `hoy_santiago()`: con la TZ del servidor (UTC) un mes empezado de noche caería en el mes
    siguiente.
 6. Las clases que canceló el BOX (`clases.cancelada = true`) no cuentan ni como falta ni como
    asistencia: se informan aparte en `clases_suspendidas`. Castigar al alumno por una clase
    que suspendió el box sería un dato falso.
 7. `beneficios` (6ª sección) queda declarada y NO disponible: llega con la Fase 2 de
    Fidelización.
"""
import calendar
from collections import Counter
from datetime import date, datetime, time as _time, timedelta, timezone
from typing import Final

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.estados import es_cancelada
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
from app.models.usuario import Usuario
from app.services.rms_service import mejor_rm_por_movimiento
from app.utils.santiago import SANTIAGO, ahora_santiago, hoy_santiago
from shared.estados import ESTADOS_SUSCRIPCION_NUNCA_VIGENTES

# ── Umbrales / criterios ──────────────────────────────────────────────────────
# Mismo valor que la LATERAL de A.3 del mantenimiento (`interval '6 hours'`).
HORAS_CANCELACION_TARDIA: Final[int] = 6
# Un pedido del Bazar cuenta como plata cobrada sólo en estos estados.
ESTADOS_PAGO_BAZAR: Final[tuple] = ("validado", "entregado")
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

# ── Las 6 secciones del panel ─────────────────────────────────────────────────
SECCIONES: Final[tuple] = (
    ("resumen", "Resumen"),
    ("asistencia", "Asistencia"),
    ("pagos", "Pagos"),
    ("membresias", "Membresías"),
    ("rms", "RMs"),
    ("beneficios", "Beneficios"),
)
SECCIONES_RESERVADAS: Final[tuple] = ("beneficios",)
MOTIVO_BENEFICIOS: Final[str] = (
    "Llega con la Fase 2 de Fidelización (beneficios por correo y su seguimiento).")

DEFAULT_SECCION: Final[str] = "resumen"
DEFAULT_POR_PAGINA: Final[int] = 25
MAX_POR_PAGINA: Final[int] = 100


# ── Helpers de fecha ──────────────────────────────────────────────────────────
def _tz(dt: datetime) -> datetime:
    """El instante de la BD como tz-aware (las columnas son timestamptz; por si acaso)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fecha_chile(dt: datetime) -> date:
    """Fecha CHILENA de un timestamp del box (mismo criterio que `hoy_santiago()`)."""
    return _tz(dt).astimezone(SANTIAGO).date()


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
    """El menú de pestañas del panel (con las reservadas marcadas como no disponibles)."""
    return [
        {
            "id": sid,
            "label": label,
            "disponible": sid not in SECCIONES_RESERVADAS,
            "motivo": MOTIVO_BENEFICIOS if sid in SECCIONES_RESERVADAS else None,
        }
        for sid, label in SECCIONES
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


def _agregados_asistencia(filas: list, alumno, ahora: datetime, hoy: date) -> dict:
    """Totales, promedio semanal y desglose por mes de las reservas vivas."""
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

    # promedio/semana = asistencias / semanas desde el alta, con piso de 1 semana (regla 3).
    alta = getattr(alumno, "created_at", None)
    dias_como_alumno = (hoy - fecha_chile(alta)).days if alta else None
    semanas = max(1.0, dias_como_alumno / 7) if dias_como_alumno is not None else None
    promedio = round(asistidas / semanas, 1) if semanas else 0.0

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


def _seccion_asistencia(db, alumno, tenant_id, pagina, por_pagina, **_kw) -> dict:
    ahora = ahora_santiago()
    vivas, suspendidas = _filas_asistencia(db, alumno.id, tenant_id)
    agg = _agregados_asistencia(vivas, alumno, ahora, ahora.date())
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
def _items_pagos(db: Session, alumno_id: int, tenant_id: int) -> list:
    """Membresías + Bazar, del más nuevo al más viejo (regla 4).

    `fecha` es SIEMPRE `date`: mezclar `datetime` y `date` en el mismo `sort` es un TypeError
    en Python (y `fecha_pedido`/`fecha_inicio` son timestamptz).
    """
    items = []

    filas = (
        db.query(Suscripcion, Plan)
        .join(Plan, Suscripcion.plan_id == Plan.id)
        .filter(Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == alumno_id)
        .all()
    )
    for suscripcion, plan in filas:
        if suscripcion.estado in ESTADOS_SUSCRIPCION_NUNCA_VIGENTES:
            continue        # nunca contó: no es un pago (ni un mes con plan)
        items.append({
            "tipo": "membresia",
            "referencia_id": suscripcion.id,
            "fecha": fecha_chile(suscripcion.fecha_inicio),
            "detalle": plan.nombre,
            "monto_clp": plan.precio_clp,
            "estado": _valor(suscripcion.estado),
        })

    pedidos = (
        db.query(Pedido, Producto.nombre)
        .outerjoin(Producto, Pedido.producto_id == Producto.id)
        .filter(Pedido.tenant_id == tenant_id,
                Pedido.alumno_id == alumno_id,
                Pedido.estado.in_(ESTADOS_PAGO_BAZAR))
        .all()
    )
    for pedido, producto in pedidos:
        items.append({
            "tipo": "bazar",
            "referencia_id": pedido.id,
            "fecha": fecha_chile(pedido.fecha_pedido),
            "detalle": f"{pedido.cantidad or 1}x {producto or 'producto'}",
            "monto_clp": round(pedido.total or 0),
            "estado": pedido.estado,
        })

    items.sort(key=lambda i: (i["fecha"], i["tipo"]), reverse=True)
    return items


def _seccion_pagos(db, alumno, tenant_id, pagina, por_pagina, **_kw) -> dict:
    items = _items_pagos(db, alumno.id, tenant_id)

    membresias = sum(i["monto_clp"] for i in items if i["tipo"] == "membresia")
    bazar = sum(i["monto_clp"] for i in items if i["tipo"] == "bazar")

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
            "pagos": len(items),
            "ultimo_pago": items[0]["fecha"] if items else None,
        },
        "por_anio": [por_anio[a] for a in sorted(por_anio, reverse=True)],
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


# ── Beneficios (reservada: Fase 2 de Fidelización) ────────────────────────────
def _seccion_beneficios(db, alumno, tenant_id, pagina, por_pagina, **_kw) -> dict:
    """6ª sección: declarada y VACÍA hasta la Fase 2 de Fidelización (regla 7)."""
    return {
        "disponible": False,
        "motivo": MOTIVO_BENEFICIOS,
        "totales": {"total": 0},
        "paginado": {"total": 0, "pagina": pagina, "por_pagina": por_pagina, "paginas": 1},
        "items": [],
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
                     incluir_privado=True) -> dict:
    """La foto de hoy del alumno. Los bloques de Pagos y RMs se piden a SUS secciones
    (pidiendo 1 item por página: los totales no dependen de la página), así el número del
    Resumen y el de la pestaña son el MISMO por construcción, no por coincidencia."""
    from app.services.asistencia_service import calcular_racha   # racha: definición existente

    ahora = ahora_santiago()
    hoy = ahora.date()

    vivas, suspendidas = _filas_asistencia(db, alumno.id, tenant_id)
    agg = _agregados_asistencia(vivas, alumno, ahora, hoy)
    racha = calcular_racha(db, alumno.id, tenant_id, hoy.year, hoy.month)

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
    "rms": _seccion_rms,
    "beneficios": _seccion_beneficios,
}


def normalizar_seccion(seccion) -> str:
    """Sección válida o `DEFAULT_SECCION` (`None`/desconocida no rompen el panel)."""
    return seccion if seccion in _SECCIONES else DEFAULT_SECCION


def ficha_alumno(alumno, hoy: date = None) -> dict:
    """Identidad del alumno: acompaña a CUALQUIER sección (el encabezado del panel)."""
    hoy = hoy or hoy_santiago()
    alta = getattr(alumno, "created_at", None)
    dias = (hoy - fecha_chile(alta)).days if alta else None
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

    datos = _SECCIONES[seccion](db, alumno, tenant_id, pagina, por_pagina,
                                incluir_privado=bool(incluir_privado))
    return {
        "alumno": ficha_alumno(alumno),
        "seccion": seccion,
        "secciones": secciones_disponibles(),
        "incluye_privado": bool(incluir_privado),
        "datos": datos,
    }
