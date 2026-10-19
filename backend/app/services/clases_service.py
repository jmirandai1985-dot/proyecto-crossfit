"""Definición ÚNICA de "clase realizada" (y el estado de una clase) para todo el sistema.

Bug que motivó este módulo (2026-10): la tarjeta "Clases Impartidas" del Dashboard mostraba
559 y "Ocupación promedio" 2.11% para el mes EN CURSO, ambas infladas porque contaban TODAS
las clases del mes — incluidas las que todavía no habían empezado y las canceladas. Había al
menos cuatro rutas de cálculo (`api/v1/reportes.py`, `services/metricas_service.py`,
`api/v1/kpis_populate.py` diario y mensual, `services/reportes_service.py`) y ninguna descontaba
el futuro; cada una definía "impartida" a su manera (o no la definía).

Acá vive UNA sola definición, expresada de DOS formas que deben decir siempre lo mismo:

  * `estado_clase()` / `es_realizada()` — en Python (lo usa la API y lo cubren los tests).
  * `sql_clase_realizada()`            — en SQL (lo usan los KPIs, Reportes y el BI).

Regla (hora de CHILE, `America/Santiago`; nunca la TZ del proceso ni la de UTC):

  * "realizada"  = **NO cancelada** y la clase **ya TERMINÓ**:
                   `fecha < hoy`  ó  (`fecha = hoy` Y `hora_fin <= ahora`).
  * "en curso"   = hoy, `hora_inicio <= ahora < hora_fin`.
  * "próxima"    = el resto (hoy y todavía no empieza, o un día futuro).
  * "cancelada"  = `cancelada = true` (cualquier fecha); NUNCA cuenta como realizada.

Para un día o un mes YA CERRADOS (todas las fechas < hoy) la definición se reduce a
"no cancelada": por eso los meses cerrados no cambian de número al aplicar este criterio.

El módulo también aloja las OTRAS dos definiciones que varios endpoints tienen que compartir:

  * **"MIS clases"** (`condicion_mis_clases` / `es_mi_clase`, las TRES vías por las que una
    clase puede ser de un coach). Está acá por el mismo motivo: si cada endpoint la escribe
    a su manera, el panel del coach y la pestaña Asistencia dejan de decir lo mismo.
  * **"MIS alumnos"** (`alumnos_del_coach`, los `alumno_id` del coach). Mismo motivo y mismo
    bug, un día después (2026-10-15): `/fidelizacion/coach/{id}/en-riesgo` definía "alumno
    del coach" mirando SÓLO `clases.coach_id`, así que un coach que dicta POR DISCIPLINA
    veía su pestaña "En Riesgo" vacía (total_alumnos = 0) mientras la pestaña de al lado
    (Alumnos) le mostraba cientos: las dos pantallas del MISMO panel se contradecían.
"""

from sqlalchemy import distinct, exists, or_, select

from shared.estados import ZONA_CHILE, sql_hoy_chile
from app.core.estados import no_cancelada
from app.models.clase import Clase
from app.models.coach_disciplina import CoachDisciplina
from app.models.horario_coach import HorarioCoach
from app.models.reserva import Reserva
from app.utils.santiago import SANTIAGO, ahora_santiago

# Etiquetas del estado de una clase (una sola lista para la API y el frontend).
REALIZADA = "realizada"
EN_CURSO = "en_curso"
PROXIMA = "proxima"
CANCELADA = "cancelada"


def estado_clase(fecha, hora_inicio, hora_fin, cancelada=False, ahora=None) -> str:
    """Estado de UNA clase según la regla del módulo (hora de Chile).

    `fecha` es un `date`, `hora_inicio`/`hora_fin` son `time` (columnas de `clases`).
    `cancelada` gana siempre: una clase cancelada es "cancelada" aunque ya haya pasado.
    `ahora` (dt tz-aware) se puede inyectar para fijar el instante de referencia en los
    tests; por defecto es la hora actual de Chile (`ahora_santiago()`).
    """
    if cancelada:
        return CANCELADA
    local = (ahora or ahora_santiago()).astimezone(SANTIAGO)
    hoy, hora = local.date(), local.time()
    if fecha < hoy:
        return REALIZADA
    if fecha > hoy:
        return PROXIMA
    if hora_fin <= hora:
        return REALIZADA
    if hora_inicio <= hora:
        return EN_CURSO
    return PROXIMA


def es_realizada(fecha, hora_inicio, hora_fin, cancelada=False, ahora=None) -> bool:
    """"La clase YA TERMINÓ y no está cancelada" — el corazón de la definición única."""
    return estado_clase(fecha, hora_inicio, hora_fin, cancelada, ahora) == REALIZADA


def sql_clase_realizada(alias: str = "c") -> str:
    """Predicado SQL de "la clase ya terminó (hora de Chile) y no está cancelada".

    Espejo EXACTO de `estado_clase() == REALIZADA`, para no dejar la definición duplicada en
    las consultas de KPIs/Reportes/BI. Devuelve, por ejemplo:

        NOT c.cancelada
          AND (c.fecha < (now() AT TIME ZONE 'America/Santiago')::date
               OR (c.fecha = (now() AT TIME ZONE 'America/Santiago')::date
                   AND c.hora_fin <= (now() AT TIME ZONE 'America/Santiago')::time))

    `clases.fecha` es `date` y `hora_fin` es `time` (sin zona), así que compararlas contra el
    día/hora de Chile (`now() AT TIME ZONE 'America/Santiago'`) es una comparación de manzanas
    con manzanas, sin depender de la TZ de la sesión de Postgres (UTC en Neon).

    ⚠️ `alias` se interpola en el SQL: es una constante del código (`"c"`, `"clases"`), **nunca**
    texto de un request.
    """
    hoy = sql_hoy_chile()                              # (now() AT TIME ZONE 'America/Santiago')::date
    ahora = f"(now() AT TIME ZONE '{ZONA_CHILE}')::time"
    return (f"NOT {alias}.cancelada"
            f" AND ({alias}.fecha < {hoy}"
            f"      OR ({alias}.fecha = {hoy} AND {alias}.hora_fin <= {ahora}))")


# ─────────────────────────────────────────────────────────────────────────────
# "MIS clases" (el alcance de un coach): UNA sola definición para los endpoints
# ─────────────────────────────────────────────────────────────────────────────
def condicion_mis_clases(coach_id: int):
    """Expresión SQLAlchemy de "esta clase ES del coach", por las TRES vías juntas.

    POR QUÉ EXISTE: el filtro `coach_id` miraba SÓLO la vía (3) y el panel del coach
    quedaba en 0 con las requests en 200 OK (bug de PROD, 2026-10-14: una clase que el
    admin le asignaba —o que ella misma tomaba— no aparecía en su propio panel).

    Las TRES vías (mismo orden que el comentario del SQL crudo de `api/v1/clases.py`,
    del que esto es el espejo ORM; un test de integración comprueba que ambos endpoints
    devuelven lo MISMO para el mismo coach):

      1. `clases.coach_id` = yo: me la asignó el admin (Supervisión) o la tomé yo;
      2. `horarios_coach` me tiene VIGENTE en el horario de esa clase y esa fecha (cubre
         las clases ya generadas de un horario recurrente que yo dicto);
      3. es de una disciplina que dicto (`coach_disciplinas.activo`): el "pool" que puedo
         tomar aunque todavía no tenga coach.

    Las dos sub-consultas llevan `tenant_id` para no cruzar boxes.
    """
    disciplinas = select(CoachDisciplina.disciplina_id).where(
        CoachDisciplina.coach_id == coach_id,
        CoachDisciplina.activo.is_(True),
        CoachDisciplina.tenant_id == Clase.tenant_id,
    )
    cubre_el_horario = exists().where(
        HorarioCoach.horario_id == Clase.horario_base_id,
        HorarioCoach.tenant_id == Clase.tenant_id,
        HorarioCoach.coach_id == coach_id,
        HorarioCoach.vigente_desde <= Clase.fecha,
        or_(HorarioCoach.vigente_hasta.is_(None),
            HorarioCoach.vigente_hasta >= Clase.fecha),
    )
    return or_(
        Clase.coach_id == coach_id,
        Clase.disciplina_id.in_(disciplinas),
        cubre_el_horario,
    )


def es_mi_clase(db, tenant_id: int, coach_id: int, clase_id: int) -> bool:
    """¿Esa clase es del coach? (la MISMA `condicion_mis_clases`, para UNA clase).

    La usan los candados de la pestaña Asistencia: el coach puede abrir y marcar
    exactamente las clases que su panel le muestra — ni una más, ni una menos.
    """
    return db.query(Clase.id).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id,
        condicion_mis_clases(coach_id),
    ).first() is not None


# ─────────────────────────────────────────────────────────────────────────────
# "MIS alumnos" (el alcance de un coach en fidelización): UNA sola definición
# ─────────────────────────────────────────────────────────────────────────────
def query_alumnos_del_coach(db, tenant_id: int, coach_id: int):
    """Consulta ORM de los `alumno_id` que son "del coach" (SIN ejecutarla).

    POR QUÉ EXISTE: `/fidelizacion/coach/{id}/alumnos` y `.../en-riesgo` —dos pestañas del
    MISMO panel— definían "alumno del coach" cada una a su manera: la de "en riesgo" miraba
    SÓLO `clases.coach_id`, así que un coach que dicta POR DISCIPLINA (o por horario) veía
    "🎉 Ningún alumno está en riesgo" mientras la pestaña Alumnos le mostraba cientos. Medido
    en la BD de PROD el 2026-10-15 (3 coaches, alumnos activos): coach 531 → 0 en riesgo vs 260
    en Alumnos; coach 10 → 0 vs 251; y hasta un coach CON clases asignadas divergía por las
    que sólo llegan por disciplina/horario: coach 7 → 221 vs 248. Ahora los dos endpoints usan
    ESTA consulta, y como se apoya en `condicion_mis_clases`, el alcance de "mis alumnos" es
    exactamente el de "mis clases" (las TRES vías, no una): los 3 coaches dan A=B.

    Criterio (el que ya usaba la pestaña Alumnos, que era la que funcionaba):

      * la reserva está VIVA — `no_cancelada` (ni `cancelled` ni `cancelada`), y
      * la clase es del coach por alguna de las TRES vías de `condicion_mis_clases`.

    Devuelve la `Query` sin ejecutarla para que un test pueda compilar su SQL sin base de
    datos (y para que el endpoint que la necesite encadenar pueda seguir filtrando).
    """
    return db.query(distinct(Reserva.alumno_id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Clase.tenant_id == tenant_id,
        no_cancelada(Reserva.estado),
        condicion_mis_clases(coach_id),
    )


def alumnos_del_coach(db, tenant_id: int, coach_id: int) -> list:
    """`alumno_id` de los alumnos que son del coach (la consulta de arriba, ejecutada).

    ⚠️ Son ids de QUIÉN RESERVÓ en mis clases, sin filtrar `rol` ni `estado` del usuario: el
    filtro de "alumno activo" lo hace cada endpoint (es idéntico en los dos, y a propósito).
    """
    return [fila[0] for fila in query_alumnos_del_coach(db, tenant_id, coach_id).all()]

