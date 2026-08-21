"""
Servicio del Ranking de Asistencia por Plan (pantalla TV pública, sin login).

Reglas de negocio (diseño confirmado, Fase 1):
- Agrupar planes del box por CANTIDAD DE CLASES (`creditos`), fusionando el plan
  normal + el plan estudiante del mismo tramo. NUNCA agrupar por nombre de
  marketing.
- Columna aparte para planes ilimitados (`es_ilimitado = True`). Nunca filtrar
  por `creditos IS NULL`: en producción los ilimitados tienen `creditos=0` +
  flag `es_ilimitado=True`.
- Encabezado de columna: los 2 nombres de marketing MÁS USADOS del tramo (por
  conteo de suscripciones). Si hay más de 2 nombres activos en el tramo, los
  excluidos se loguean (logger.warning) — no se pierden en el aire.
- Métrica por fila: "asistencias reales del mes cerrado" / "clases contratadas
  del plan" (ej. 8/8). Es un cálculo DISTINTO al de racha (que usa % sobre
  reservas): acá el numerador son asistencias y el denominador es nominal
  (creditos del plan).
- Mes: SIEMPRE el mes cerrado (hoy es agosto → el ranking muestra julio).
- Plan Full/ilimitado: el máximo no-ilimitado se lee de la BD
  (MAX(creditos) WHERE NOT es_ilimitado AND activo), nunca hardcodeado. Quien
  en el mes superó ese máximo en asistencias gana el sello SELLO_MONSTRUO.
  Las estrellas de la columna ilimitado son relativas a ese mismo máximo
  (sin denominador fijo).
- Sello "100% PERFECTO" (SELLO_PERFECTO): solo si asistencias == creditos.
- Top 10 por columna: asistencias desc; empate → racha activa desc (reusa
  asistencia_service.calcular_racha tal cual, sin reimplementar).
- Nombres: "Nombre + inicial ap. paterno + inicial ap. materno" desde el string
  único `usuarios.nombre`. NUNCA nombre completo ni datos de contacto.

Plan del alumno en el mes cerrado (decisión confirmada):
- Se resuelve por SOLAPAMIENTO de fechas de `suscripciones`
  (fecha_inicio <= fin_del_mes AND fecha_expiracion >= inicio_del_mes),
  aceptando estado IN ('activo','vencido') — así no se pierde el histórico de
  meses ya vencidos (el job marcar_plan_vencido.py marca 'vencido').
- Si un alumno tiene varias suscripciones que cubren el mes (upgrade a mitad
  de mes, ej. Alumno Demo plan Prueba→Alpha), gana la de `fecha_inicio` MÁS
  reciente (el plan con el que terminó el mes).
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.constants import (
    RANKING_TOP,
    SELLO_MONSTRUO,
    SELLO_PERFECTO,
    ESTRELLAS_POR_RANGO,
)
from app.models.plan import Plan
from app.models.suscripcion import Suscripcion
from app.models.usuario import Usuario
from app.services.asistencia_service import (
    _rango_mes,
    _reservas_mes,
    calcular_racha,
)
from app.utils.santiago import hoy_santiago

logger = logging.getLogger("uvicorn")

# Estados de suscripción válidos para el mes cerrado (ver docstring).
ESTADOS_SUSCRIPCION_VALIDOS = ("activo", "vencido")

# Máximo de nombres de marketing por encabezado de columna.
MAX_NOMBRES_ENCABEZADO = 2


# ── Formato de nombres (nunca nombre completo ni contacto) ───────────────────
def _titular(token: str) -> str:
    """Normaliza un token a 'Primera letra mayúscula + resto en minúscula'.
    Conserva tildes (p. ej. 'GONZÁLEZ' → 'González')."""
    return token[:1].upper() + token[1:].lower()


def formatear_nombre_alumno(nombre: str) -> str:
    """'María González Pérez' → 'María G. P.'
       'Pedro Soto'          → 'Pedro S.'
       'Alumno'              → 'Alumno'   (token único, se muestra tal cual).

    El string único `usuarios.nombre` se parsea por tokens: el primero es el
    nombre; el 2° y 3° son apellido paterno y materno (solo iniciales).
    """
    tokens = [t for t in (nombre or "").strip().split() if t]
    if not tokens:
        return ""
    resultado = _titular(tokens[0])
    iniciales = []
    for token in tokens[1:3]:
        if token:
            iniciales.append(f"{token[0].upper()}.")
    if not iniciales:
        return resultado
    return f"{resultado} {' '.join(iniciales)}"


# ── Escala de estrellas ───────────────────────────────────────────────────────
def _estrellas(pct: int) -> int:
    """Estrellas según % de cumplimiento (piso inclusive, constantes.py)."""
    for umbral, estrellas in ESTRELLAS_POR_RANGO:
        if pct >= umbral:
            return estrellas
    return 0


# ── Resolución del plan del mes cerrado ──────────────────────────────────────
def _planes_por_tramo(db: Session, tenant_id: int) -> Dict[Optional[int], List[Plan]]:
    """Planes activos del box agrupados por tramo.

    Clave: `creditos` (int) para planes limitados; `None` para la columna
    ilimitada (es_ilimitado=True). Fusiona plan normal + estudiante del tramo.
    """
    planes = db.query(Plan).filter(
        Plan.tenant_id == tenant_id,
        Plan.activo == True,
    ).all()

    tramos: Dict[Optional[int], List[Plan]] = {}
    for plan in planes:
        clave: Optional[int] = None if plan.es_ilimitado else (plan.creditos or 0)
        tramos.setdefault(clave, []).append(plan)

    # Tramo ilimitado al final; el resto ascendente por cantidad de clases.
    orden = sorted((c for c in tramos if c is not None), key=lambda c: (c or 0))
    orden.append(None)
    return {clave: tramos[clave] for clave in orden if clave in tramos}

def _conteo_suscripciones_por_plan(db: Session, tenant_id: int) -> Dict[int, int]:
    """Nº de suscripciones históricas por plan (para "los 2 nombres más usados")."""
    filas = db.query(Suscripcion.plan_id, func.count(Suscripcion.id)).filter(
        Suscripcion.tenant_id == tenant_id,
    ).group_by(Suscripcion.plan_id).all()
    return {plan_id: conteo for plan_id, conteo in filas}


def _encabezado_tramo(db: Session, tenant_id: int, planes: List[Plan]) -> List[str]:
    """Los MAX_NOMBRES_ENCABEZADO nombres de marketing más usados del tramo.

    Si hay más nombres activos que el máximo, los excluidos se loguean.
    Desempate por conteo desc y luego por id de plan asc (determinista).
    """
    conteos = _conteo_suscripciones_por_plan(db, tenant_id)
    ordenados = sorted(planes, key=lambda p: (-conteos.get(p.id, 0), p.id))
    nombres = [p.nombre for p in ordenados]
    elegidos = nombres[:MAX_NOMBRES_ENCABEZADO]
    if len(nombres) > MAX_NOMBRES_ENCABEZADO:
        logger.warning(
            "ranking_asistencia: el tramo con planes %s tiene %d nombres activos; "
            "se muestran %s y se omiten %s",
            [p.id for p in planes], len(nombres), elegidos,
            nombres[MAX_NOMBRES_ENCABEZADO:],
        )
    return elegidos


def _plan_del_mes(db: Session, tenant_id: int, anio: int, mes: int) -> Dict[int, Plan]:
    """Alumno → plan del mes cerrado (decisión confirmada; ver docstring)."""
    desde, hasta = _rango_mes(anio, mes)

    subs = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.fecha_inicio <= hasta,
        Suscripcion.fecha_expiracion >= desde,
        Suscripcion.estado.in_(ESTADOS_SUSCRIPCION_VALIDOS),
    ).order_by(Suscripcion.fecha_inicio.asc()).all()

    if not subs:
        return {}

    planes_map = {p.id: p for p in db.query(Plan).filter(
        Plan.id.in_([s.plan_id for s in subs])).all()}

    mejor_sus: Dict[int, Suscripcion] = {}
    for s in subs:
        prev = mejor_sus.get(s.usuario_id)
        if prev is None or s.fecha_inicio > prev.fecha_inicio:
            mejor_sus[s.usuario_id] = s

    plan_por_alumno: Dict[int, Plan] = {}
    for alumno_id, s in mejor_sus.items():
        plan = planes_map.get(s.plan_id)
        if plan is not None:
            plan_por_alumno[alumno_id] = plan
    return plan_por_alumno



# ── Construcción del ranking ─────────────────────────────────────────────────
def construir_ranking(db: Session, tenant_id: int, anio: int, mes: int) -> dict:
    """Arma las 5 columnas del ranking para un tenant + mes cerrado.

    Reglas y fuentes de datos documentadas en el docstring del módulo.
    Punto de enganche futuro de n8n: este resultado es el que un cache-refresh
    recalculará (# TODO(n8n) cache-refresh — fase de Dockerización, NO construir).
    """
    # Máximo no-ilimitado leído de BD (nunca hardcodeado).
    max_no_ilimitado = db.query(func.max(Plan.creditos)).filter(
        Plan.tenant_id == tenant_id,
        Plan.es_ilimitado == False,
        Plan.activo == True,
    ).scalar() or 0

    tramos = _planes_por_tramo(db, tenant_id)

    # Alumno → plan del mes cerrado (por solapamiento de fechas).
    plan_por_alumno = _plan_del_mes(db, tenant_id, anio, mes)
    alumnos_ids = list(plan_por_alumno.keys())

    usuarios_map: Dict[int, Usuario] = {}
    if alumnos_ids:
        usuarios_map = {u.id: u for u in db.query(Usuario).filter(
            Usuario.id.in_(alumnos_ids)).all()}

    # Fila por alumno: asistencias reales del mes + racha para desempate.
    fila_por_alumno = {}
    for alumno_id, plan in plan_por_alumno.items():
        reservas = _reservas_mes(db, alumno_id, tenant_id, anio, mes)
        asistidas = sum(1 for r in reservas if r.asistio)
        racha = calcular_racha(db, alumno_id, tenant_id, anio, mes)
        fila_por_alumno[alumno_id] = {
            "alumno_id": alumno_id,
            "plan": plan,
            "asistencias": asistidas,
            "racha": racha,
        }

    columnas = []
    for clave, planes in tramos.items():
        es_ilimitado = clave is None
        creditos_tramo = None if es_ilimitado else clave

        # Filas de alumnos cuyo plan del mes pertenece a este tramo.
        filas_tramo = [
            f for f in fila_por_alumno.values()
            if (f["plan"].es_ilimitado if es_ilimitado else
                (f["plan"].creditos or 0) == clave)
        ]

        top = []
        for f in filas_tramo:
            alumno = usuarios_map.get(f["alumno_id"])
            plan = f["plan"]
            asistidas = f["asistencias"]
            racha = f["racha"]

            if es_ilimitado:
                contratadas = None
                pct = (round(asistidas / max_no_ilimitado * 100)
                       if max_no_ilimitado else 0)
                sello = SELLO_MONSTRUO if asistidas > max_no_ilimitado else None
            else:
                contratadas = plan.creditos or 0
                pct = (round(asistidas / contratadas * 100)
                       if contratadas else 0)
                sello = (SELLO_PERFECTO if contratadas and asistidas == contratadas
                         else None)

            # PERFECTO reemplaza las estrellas; MONSTRUO (supera el máximo)
            # llega a 5 estrellas.
            if sello == SELLO_PERFECTO:
                estrellas = 0
            elif sello == SELLO_MONSTRUO:
                estrellas = 5
            else:
                estrellas = _estrellas(min(pct, 100))

            top.append({
                "alumno_id": alumno_id,
                "nombre": formatear_nombre_alumno(alumno.nombre) if alumno else "",
                "plan_nombre": plan.nombre,
                "asistencias": asistidas,
                "contratadas": contratadas,
                "racha": racha,
                "estrellas": estrellas,
                "sello": sello,
            })

        # Top RANKING_TOP: asistencias desc, empate → racha desc, luego nombre.
        top.sort(key=lambda r: (-r["asistencias"], -r["racha"], r["nombre"]))

        columnas.append({
            "tramo_clases": creditos_tramo,
            "es_ilimitado": es_ilimitado,
            "nombres_marketing": _encabezado_tramo(db, tenant_id, planes),
            "incluye_estudiante": any(p.es_estudiante for p in planes),
            "alumnos_activos": len(filas_tramo),
            "top": top[:RANKING_TOP],
        })

    return {
        "anio": anio,
        "mes_numero": mes,
        "max_no_ilimitado": max_no_ilimitado,
        "columnas": columnas,
    }


def mes_cerrado_por_defecto() -> tuple:
    """(anio, mes) del mes cerrado más reciente respecto a hoy en Santiago."""
    hoy = hoy_santiago()
    if hoy.month == 1:
        return hoy.year - 1, 12
    return hoy.year, hoy.month - 1
