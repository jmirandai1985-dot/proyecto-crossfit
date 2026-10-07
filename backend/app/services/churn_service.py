"""Recalculo de la fila de churn de UN alumno, en segundo plano (sin bloquear la respuesta).

Por que existe
--------------
`predictions_churn` es un DATA MART: `POST /kpis/populate/predictions` lo reescribe COMPLETO en
cada corrida (cron). Hasta el proximo poblado, la fila de un alumno es la del dia del poblado:
si HOY aprueba un plan (o registra una asistencia, o cambia de creditos) su `riesgo` y su
`recomendacion` quedan viejos — la SITUACION ya se sirve en vivo (`plan_vencimiento`), pero el
riesgo/probabilidad/arquetipo siguen siendo del snapshot hasta el proximo cron. Este modulo
recalcula SOLO ese alumno y reemplaza sus filas por una fresca.

Reglas
------
  * Se dispara con `BackgroundTasks` (no bloquea) y abre su PROPIA sesion (`SessionLocal`): la
    del request ya cerro cuando el task corre.
  * La probabilidad/nivel reproducen EXACTAMENTE `populate_predictions` (heuristica):
    `probabilidad_heuristica` y `nivel_de_riesgo` viven aca y el populate las reusa. El `motivo`
    sale de `plan_vencimiento.motivo_situacion` y la recomendacion de `recomendacion_churn`, que
    AHORA vive aca: es la MISMA regla que usa el populate (que la importa) y tambien el servido
    en vivo de `GET /kpis/churn`. UNA sola definicion => el snapshot y la pantalla no divergen.
  * Un fallo NUNCA debe tumbar la operacion que lo disparo: se loguea y se descarta.

`es_plan_sin_usar` / `plan_sin_usar(_lote)`
-------------------------------------------
SITUACION aparte del churn: el alumno COMPRO un plan vigente y todavia no estreno ninguna clase
(nunca asistio DESDE que arranco el plan, y ya paso el margen minimo). No es "abandono" ni "sin
plan": es un plan pago esperando. Es una categoria propia de `recomendacion_churn`
("plan_sin_usar") y de las plantillas de Fidelizacion. La definicion vive UNA vez
(`es_plan_sin_usar`) y la usan tanto el populate como la pantalla en vivo.
"""
import logging
from datetime import timedelta

from sqlalchemy import func

from app.core.estados import plan_comercial, vigente_hoy
from app.db.database import SessionLocal
from app.models.asistencia import Asistencia
from app.models.plan import Plan
from app.models.predictions_churn import PredictionsChurn
from app.models.suscripcion import Suscripcion
from app.models.usuario import Usuario
from app.services import plan_vencimiento
from app.utils.santiago import fecha_chile, hoy_santiago

logger = logging.getLogger("uvicorn")


# ── Recomendacion de accion (texto empatico + codigo para la UI) ─────────────
# Los textos viven aca (un solo lugar) y el codigo es estable para que el frontend
# pueda colorear/filtrar sin parsear el texto. ANTES vivian en `kpis_populate`; se
# movieron aca para que la pantalla en vivo (GET /kpis/churn) y el recalculo por
# alumno usen EXACTAMENTE la misma regla que el populate.
RECO_SIN_PLAN = (
    "Alumno sin actividad y sin plan vigente. Te recomendamos contactarlo "
    "personalmente para indagar qué está pasando —podría ser tiempo, motivación "
    "o un tema económico. Si es económico, considera ofrecerle una alternativa "
    "(clase de cortesía, descuento temporal) para facilitar que vuelva."
)
RECO_PLAN_SIN_USAR = (
    "El alumno activó un plan pero todavía no vino a ninguna clase: tiene el plan "
    "pagado y sin estrenar. Contáctalo para ayudarlo a agendar su primera sesión "
    "—suele ser un tema de agenda o de no saber por dónde empezar, no falta de "
    "interés."
)
RECO_CRITICO_CON_PLAN = (
    "Su plan está activo pero las señales de riesgo son críticas. Contáctalo con "
    "prioridad: no lo trates como un recordatorio más —preguntale cómo está de "
    "verdad y si algo del box (horario, clima, precio, lesión) le está jugando "
    "en contra."
)
RECO_CAIDA_RECIENTE = (
    "Su asistencia bajó fuerte aunque su plan sigue activo. Es un buen momento "
    "para un mensaje cercano preguntando cómo está y si el horario le sigue "
    "acomodando —a veces alcanza con ajustar la rutina."
)
RECO_ALTO_SIN_CAUSA = (
    "El modelo detecta un riesgo alto para este alumno, aunque no hay una señal "
    "específica clara (como caída de asistencia o vencimiento próximo). Vale la "
    "pena un chequeo preventivo: preguntale cómo va todo, por las dudas."
)
RECO_RENOVACION_PROXIMA = (
    "Su plan vence pronto y sigue entrenando con normalidad. Es buen momento "
    "para mandarle el recordatorio de renovación antes de que se le pase la fecha."
)
RECO_MEDIO_SIN_SENALES = (
    "El modelo marca un riesgo medio para este alumno, sin una señal puntual "
    "(ni caída de asistencia ni vencimiento próximo). No es urgente, pero "
    "conviene un seguimiento amable: preguntale cómo va y si necesita algo."
)
RECO_SIN_ACCION = "Todo en orden, sin acción necesaria."

RECO_CODIGOS = ("sin_plan", "plan_sin_usar", "critico_con_plan", "caida_reciente",
                "alto_sin_causa_clara", "renovacion_proxima",
                "medio_sin_senales", "sin_accion")


def recomendacion_churn(nivel, tiene_suscripcion, dias_para_vencer,
                        asis_30, asis_90, es_plan_sin_usar=False) -> tuple:
    """(texto, código) de la recomendación (gana la PRIMERA regla que aplica).

      1. CRITICO/ALTO/MEDIO sin plan vigente -> contacto personal (posible tema económico)
      2. Plan vigente SIN USAR               -> ayudar a agendar la primera clase
      3. CRITICO con plan vigente            -> contacto prioritario (plan activo, señales fuertes)
      4. ALTO/MEDIO con plan y caída fuerte  -> mensaje cercano (revisar rutina/horario)
      5. ALTO con plan, sin señales claras   -> chequeo preventivo (nunca "todo en orden")
      6. Vence en <=7 días y BAJO/MEDIO      -> recordatorio de renovación
      7. MEDIO con plan, sin señales claras  -> seguimiento amable (no urgente)
      8. Resto                               -> "Todo en orden..." (sólo BAJO)

    "Caída fuerte" = asistencias 30d < asistencias 90d / 3 (ritmo reciente por
    debajo de un tercio del histórico trimestral). Proxy explícito, sin queries.

    "Plan sin usar" (`es_plan_sin_usar`) = compró un plan vigente y todavía no
    estrenó ninguna clase (ver `es_plan_sin_usar`). Va ANTES que las señales del
    modelo: un plan pago esperando es la acción más concreta y barata de todas.

    Orden de prioridad: las reglas con señal accionable concreta van primero
    (#4 caída, #6 vencimiento próximo) y recién después los "sin señal clara"
    (#5 ALTO, #7 MEDIO): así un MEDIO que vence en 7 días recibe el recordatorio
    de renovación y no el mensaje genérico.

    Cobertura: la #1 agarra a TODO no-BAJO sin plan vigente, la #2 a todo plan
    sin estrenar, la #3/#5 a todo ALTO/CRITICO con plan y la #7 a todo MEDIO con
    plan -> la #8 ("Todo en orden") sólo puede contener alumnos BAJO.

    ⚠️ BORDE CONOCIDO (regla literal a propósito, ver consigna):
      - Con asistencias_90d == 0 el proxy de la #4 da `0 < 0` = False -> no la
        dispara: un ALTO con plan cae a la #5 y un MEDIO con plan a la #7.
    """
    if nivel in ("CRITICO", "ALTO", "MEDIO") and not tiene_suscripcion:
        return RECO_SIN_PLAN, "sin_plan"

    if es_plan_sin_usar:
        return RECO_PLAN_SIN_USAR, "plan_sin_usar"

    if nivel == "CRITICO" and tiene_suscripcion:
        return RECO_CRITICO_CON_PLAN, "critico_con_plan"

    caida_reciente = asis_30 < (asis_90 / 3)
    if nivel in ("ALTO", "MEDIO") and tiene_suscripcion and caida_reciente:
        return RECO_CAIDA_RECIENTE, "caida_reciente"

    # Un ALTO con plan activo nunca debe leerse como "todo en orden": si no hubo
    # caída de asistencia (#4) ni vencimiento próximo, se recomienda chequeo
    # preventivo ("sin causa clara").
    if nivel == "ALTO" and tiene_suscripcion:
        return RECO_ALTO_SIN_CAUSA, "alto_sin_causa_clara"

    if (dias_para_vencer is not None and dias_para_vencer <= 7
            and nivel in ("BAJO", "MEDIO")):
        return RECO_RENOVACION_PROXIMA, "renovacion_proxima"

    # Un MEDIO con plan activo, sin caída (#4) ni vencimiento próximo (#6) -las
    # señales accionables ya se evaluaron- tampoco es "todo en orden".
    if nivel == "MEDIO" and tiene_suscripcion:
        return RECO_MEDIO_SIN_SENALES, "medio_sin_senales"

    return RECO_SIN_ACCION, "sin_accion"


def probabilidad_heuristica(dias_inactivo: int, dias_para_vencer) -> float:
    """Probabilidad (0-100) de la heuristica: inactividad + ausencia/vencimiento del plan."""
    prob = min(dias_inactivo, 60) / 60 * 70
    if dias_para_vencer is None:
        prob += 20
    elif dias_para_vencer <= plan_vencimiento.DIAS_PLAN_POR_VENCER:
        prob += 10
    return round(min(prob, 100), 2)


def nivel_de_riesgo(prob: float) -> str:
    """CRITICO/ALTO/MEDIO/BAJO: los MISMOS umbrales en el populate y en el recalculo."""
    if prob >= 70:
        return "CRITICO"
    if prob >= 50:
        return "ALTO"
    if prob >= 30:
        return "MEDIO"
    return "BAJO"


def _ultima_asistencia(db, tenant_id, usuario_id):
    """Fecha de la ultima asistencia del alumno (o `None` si nunca asistio)."""
    return db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == usuario_id,
    ).scalar()


def _dias_inactividad(db, tenant_id, usuario_id, created_at, hoy) -> int:
    """Dias desde la ultima asistencia y, si nunca asistio, desde el alta (COALESCE)."""
    ultima = _ultima_asistencia(db, tenant_id, usuario_id)
    referencia = ultima or (created_at.date() if created_at else None)
    if referencia is None:
        return 0
    return max(0, (hoy - referencia).days)


def _conteos(db, tenant_id, usuario_id, dias, hoy) -> int:
    """Asistencias del alumno en la ventana [hoy - dias, hoy]."""
    return db.query(func.count(Asistencia.id)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == usuario_id,
        Asistencia.fecha >= hoy - timedelta(days=dias),
        Asistencia.fecha <= hoy,
    ).scalar() or 0


# ── "Plan sin usar": plan vigente COMPRADO y todavia sin estrenar ─────────────
# Margen minimo desde el inicio del plan para considerar que "no lo uso": evita marcar a
# alguien que compro HOY/ayer (todavia no tuvo tiempo de ir). Una semana de clases tipica.
DIAS_MINIMOS_PLAN_SIN_USAR = 5


def es_plan_sin_usar(tiene_suscripcion: bool, fecha_inicio, ultima_asistencia,
                     hoy=None) -> bool:
    """True si el alumno tiene un plan vigente y NO asistio DESDE que arranco.

    FUNCION PURA (sin DB): recibe si tiene plan, la fecha de inicio del plan y su ultima
    asistencia (`None` = nunca asistio). Es la UNICA definicion de "plan sin usar": la
    comparten el populate, el recalculo, el servido en vivo y las plantillas de Fidelizacion.

      * Sin plan vigente o sin fecha de inicio -> False (dato incompleto: no afirmamos nada).
      * Margen `DIAS_MINIMOS_PLAN_SIN_USAR`: si el plan arranco hace menos de eso, todavia no
        es "sin usar" (puede ir a su primera clase).
      * "No lo uso" = nunca asistio, o su ultima asistencia es ANTERIOR al inicio del plan
        (venia de otro plan/gimnasio y no estreno este).
    """
    if not tiene_suscripcion or fecha_inicio is None:
        return False
    hoy = hoy or hoy_santiago()
    if (hoy - fecha_inicio).days < DIAS_MINIMOS_PLAN_SIN_USAR:
        return False
    return ultima_asistencia is None or ultima_asistencia < fecha_inicio


def plan_sin_usar(db, alumno, hoy=None, solo_comercial: bool = True):
    """`(Suscripcion, Plan)` del plan vigente SIN USAR del alumno, o `None`.

    Reusa la vigencia de `plan_vencimiento.suscripcion_vigente` (vence mas tarde primero) y
    la MISMA definicion de "sin usar" (`es_plan_sin_usar`). `solo_comercial=True` por defecto
    (BI/churn); las plantillas de Fidelizacion pasan `False` (su criterio 5).
    """
    hoy = hoy or hoy_santiago()
    fila = plan_vencimiento.suscripcion_vigente(
        db, alumno, hoy, solo_comercial=solo_comercial)
    if fila is None:
        return None
    suscripcion, plan = fila
    ultima = _ultima_asistencia(db, suscripcion.tenant_id, alumno.id)
    if es_plan_sin_usar(True, fecha_chile(suscripcion.fecha_inicio), ultima, hoy):
        return suscripcion, plan
    return None


def plan_sin_usar_lote(db, tenant_id: int, ids, hoy=None,
                       solo_comercial: bool = True) -> set:
    """IDs (de `ids`) con plan vigente SIN USAR, en pocas queries para todo el box.

    Mismo criterio que `plan_sin_usar` pero batcheado (sin N+1): lo usan el populate y el
    servido en vivo de `GET /kpis/churn`.
    """
    ids = list(ids or [])
    if not ids:
        return set()
    hoy = hoy or hoy_santiago()

    # 1) El plan vigente que vence MAS TARDE de cada alumno (gana la mas tardia, igual que
    #    `suscripcion_vigente`): la primera fila que aparece por alumno es la que queda.
    consulta = (
        db.query(Suscripcion.usuario_id, Suscripcion.fecha_inicio)
        .join(Plan, Suscripcion.plan_id == Plan.id)
        .filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id.in_(ids),
            Suscripcion.estado == plan_vencimiento.ESTADO_SUSCRIPCION_ACTIVO,
            vigente_hoy(Suscripcion.fecha_expiracion, hoy=hoy),
        )
    )
    if solo_comercial:
        consulta = consulta.filter(plan_comercial(Plan.es_comercial))
    consulta = consulta.order_by(
        Suscripcion.usuario_id, Suscripcion.fecha_expiracion.desc(), Suscripcion.id.desc())

    inicio_por_alumno: dict = {}
    for usuario_id, fecha_inicio in consulta.all():
        inicio_por_alumno.setdefault(usuario_id, fecha_inicio)

    # 2) Ultima asistencia de cada alumno (una sola query agregada).
    ultimas = dict(
        db.query(Asistencia.usuario_id, func.max(Asistencia.fecha))
        .filter(Asistencia.tenant_id == tenant_id, Asistencia.usuario_id.in_(ids))
        .group_by(Asistencia.usuario_id).all())

    return {uid for uid, inicio in inicio_por_alumno.items()
            if es_plan_sin_usar(True, fecha_chile(inicio), ultimas.get(uid), hoy)}


def recalcular_alumno(tenant_id: int, usuario_id: int) -> None:
    """Recalcula la fila de churn de UN alumno (sesion propia; nunca lanza)."""
    db = SessionLocal()
    try:
        alumno = db.query(Usuario).filter(
            Usuario.id == usuario_id, Usuario.tenant_id == tenant_id).first()
        if alumno is None:
            return
        hoy = hoy_santiago()
        dias_inactivo = _dias_inactividad(db, tenant_id, usuario_id, alumno.created_at, hoy)
        fila_plan = plan_vencimiento.suscripcion_vigente(db, alumno, hoy, solo_comercial=True)
        proxima = fila_plan[0].fecha_expiracion if fila_plan else None
        proxima_date = fecha_chile(proxima) if proxima else None
        dias_para_vencer = plan_vencimiento.dias_hasta(proxima, hoy)
        asis_30 = _conteos(db, tenant_id, usuario_id, 30, hoy)
        asis_90 = _conteos(db, tenant_id, usuario_id, 90, hoy)
        # "Plan sin usar": compro un plan vigente y no lo estreno (MISMA definicion que el
        # populate y el servido en vivo). Sólo consulta si tiene plan vigente.
        es_psu = (plan_sin_usar(db, alumno, hoy, solo_comercial=True) is not None)

        prob = probabilidad_heuristica(dias_inactivo, dias_para_vencer)
        nivel = nivel_de_riesgo(prob)
        motivo = plan_vencimiento.motivo_situacion(dias_inactivo, dias_para_vencer)
        # La recomendacion es la MISMA funcion que el populate y el servido en vivo (vive aca).
        recomendacion, reco_codigo = recomendacion_churn(
            nivel, dias_para_vencer is not None, dias_para_vencer, asis_30, asis_90,
            es_plan_sin_usar=es_psu)

        # Reemplaza las filas del alumno (el data mart guarda UNA fila por alumno tras el refresh).
        db.query(PredictionsChurn).filter(
            PredictionsChurn.tenant_id == tenant_id,
            PredictionsChurn.usuario_id == usuario_id,
        ).delete()
        db.add(PredictionsChurn(
            tenant_id=tenant_id, usuario_id=usuario_id,
            probabilidad_churn=prob, riesgo_nivel=nivel, motivo=motivo,
            recomendacion=recomendacion, recomendacion_codigo=reco_codigo,
            fecha_proxima_renovacion=proxima_date,
        ))
        db.commit()
    except Exception as e:   # nunca romper la operacion que lo disparo
        db.rollback()
        logger.warning("recalculo de churn del alumno #%s fallo: %s", usuario_id, e)
    finally:
        db.close()


def programar_recalculo(background_tasks, tenant_id: int, usuario_id: int) -> None:
    """Encola el recalculo en segundo plano (no bloquea). Sin `background_tasks`, no hace nada."""
    if background_tasks is None or usuario_id is None:
        return
    background_tasks.add_task(recalcular_alumno, tenant_id, usuario_id)
