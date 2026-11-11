"""
Suspensión de plan self-service (vacaciones / fuerza mayor).

Reglas de negocio (cerradas, ver el prompt de la feature):

  1. Tope: 14 días por año, divisibles en hasta 2 períodos.
  2. El "año" es el ANIVERSARIO DE INSCRIPCIÓN (`Usuario.created_at`), no el año
     calendario: el saldo de 14 días se resetea en esa fecha cada año.
  3. Elegibilidad: el alumno sólo puede suspender si tiene al menos 4 créditos
     (plan limitado) y le quedan al menos 10 días hasta `fecha_expiracion`.
  4. Al confirmar: se crea el registro, `fecha_expiracion += dias` y se cancelan
     las reservas vivas del rango con el estado `cancelada_por_suspension`.
  5. El backend valida `dias_pedidos <= saldo_disponible` como última barrera.

Las funciones puras (sin BD) de este módulo son la ÚNICA definición de las reglas:
`ciclo_vigente`, `dias_usados_en_ciclo` y `calcular_elegibilidad`. `crear_suspension`
es la que escribe (transacción atómica) y re-valida todo por defensa en profundidad.
"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.estados import ESTADO_CANCELADA_POR_SUSPENSION, no_cancelada, vigente_hoy
from app.models.clase import Clase
from app.models.reserva import Reserva
from app.models.suscripcion import Suscripcion
from app.models.suspension_plan import SuspensionPlan
from app.models.usuario import Usuario
from app.services.reservas_service import reembolsar_credito_reserva, ReembolsoTransitorio
# Aviso in-app para la campana del admin: la suspensión self-service también avisa al box.
from app.services.notificaciones_panel import notificar_admins_del_tenant
from app.utils.santiago import (
    SANTIAGO,
    ahora_santiago,
    fecha_chile,
    fin_del_dia_chile,
    hoy_santiago,
    inicio_del_dia_chile,
)

# ── Reglas del negocio (una sola definición) ─────────────────────────────────
DIAS_ANUALES = 14          # tope por ciclo (regla 1)
MAX_PERIODOS = 2           # hasta 2 períodos por ciclo (regla 1)
MIN_CREDITOS = 4           # mínimo de créditos para un plan limitado (regla 3a)
MIN_DIAS_HASTA_VENCER = 10  # mínimo de días hasta `fecha_expiracion` (regla 3b)

# ── Origen de la suspensión ───────────────────────────────────────────────────
ORIGEN_ALUMNO = "alumno"             # self-service (14 días/año + cupo de cancelación)
ORIGEN_ADMIN_SALUD = "admin_salud"   # la crea/cancela el admin (sin tope ni cupo)

# El texto EXACTO que se le muestra al alumno (regla del prompt: el `motivo` es el
# copy de pantalla, no un código interno). Los dos primeros llevan el número REAL
# interpolado con `.format(n=...)` en `calcular_elegibilidad`.
MOTIVO_SIN_PLAN = "No tienes un plan activo para suspender."
MOTIVO_CREDITOS = "No disponible — te quedan solo {n} créditos, necesitas al menos 4"
MOTIVO_VENCIMIENTO = "No disponible — faltan {n} días para poder suspender"
MOTIVO_SALDO = "Ya usaste los 14 días de suspensión de este ciclo."
MOTIVO_PERIODOS = "Ya usaste los 2 períodos de suspensión permitidos en este ciclo."

# ── Cancelación anticipada (fix del abuso en plan ilimitado) ─────────────────
# Cupo: 1 cancelación por ciclo (el mismo ciclo del aniversario de inscripción).
MOTIVO_SUSPENSION_NO_EXISTE = "La suspensión no existe."
MOTIVO_SUSPENSION_YA_CANCELADA = "Esta suspensión ya fue cancelada."
MOTIVO_SUSPENSION_NO_ACTIVA = "La suspensión no está activa hoy: no se puede cancelar."
MOTIVO_CANCELACION_USADA = ("Ya cancelaste una suspensión este año: "
                            "solo puedes cancelar una vez por ciclo.")
# No se puede crear una suspensión si YA hay una activa hoy (fix de visibilidad):
# antes el alumno podía solapar dos suspensiones y quedarse con el doble beneficio.
MOTIVO_SUSPENSION_ACTIVA = "Ya tienes una suspensión activa."


# ── Helpers puros ────────────────────────────────────────────────────────────
def _a_date(valor) -> date:
    """Normaliza `datetime`/`date` a `date` (los tests pueden pasar cualquiera)."""
    return valor.date() if isinstance(valor, datetime) else valor


def _aniversario(mes: int, dia: int, anio: int) -> date:
    """El aniversario (mes/día) en el año `anio`; 29-feb cae a 28-feb en año no bisiesto."""
    try:
        return date(anio, mes, dia)
    except ValueError:
        return date(anio, 2, 28)


def dias_entre(fecha_inicio, fecha_fin) -> int:
    """Días INCLUSIVOS entre dos fechas (una suspensión del 01 al 03 son 3 días).

    Es la fórmula de la suspensión por salud del admin: el admin define inicio y
    vuelta (no una cantidad de días como la del alumno), y `dias` se calcula acá
    como `(fecha_fin - fecha_inicio).days + 1` — la misma relación que el
    `fecha_fin = fecha_inicio + (dias - 1)` de la suspensión self-service.
    """
    fi = _a_date(fecha_inicio)
    ff = _a_date(fecha_fin)
    return (ff - fi).days + 1


def _es_alumno(s) -> bool:
    """True si la suspensión es del alumno (self-service).

    Las `origen='admin_salud'` NO cuentan para el saldo de 14 días/año ni para el
    cupo de 1 cancelación/año. Se usa `getattr(..., ORIGEN_ALUMNO)` para que los
    fakes de los tests puros (que no traen la columna nueva) sigan contando como
    'alumno'.
    """
    return getattr(s, "origen", ORIGEN_ALUMNO) == ORIGEN_ALUMNO


# ── Reglas puras (testeables sin BD) ─────────────────────────────────────────
def ciclo_vigente(fecha_inscripcion: datetime, hoy: datetime) -> tuple[datetime, datetime]:
    """Inicio y fin del ciclo anual vigente de 365 días, anclado al aniversario.

    El ciclo empieza el ANIVERSARIO de inscripción (mes/día de `fecha_inscripcion`)
    más reciente a `hoy` y dura 365 días (`fin = inicio + 365 días`). No es el año
    calendario: un alumno que se inscribió el 15/03 resetea su saldo el 15/03, no
    el 01/01. La fecha se lee en días de Chile (`fecha_chile`), igual que el resto
    de las reglas de vencimiento del proyecto.
    """
    inscripcion_dia = fecha_chile(fecha_inscripcion)
    hoy_dia = _a_date(hoy)
    inicio_dia = _aniversario(inscripcion_dia.month, inscripcion_dia.day, hoy_dia.year)
    if inicio_dia > hoy_dia:
        # Todavía no llegó el aniversario de este año: el ciclo vigente arrancó el año pasado.
        inicio_dia = _aniversario(inscripcion_dia.month, inscripcion_dia.day, hoy_dia.year - 1)
    inicio = datetime.combine(inicio_dia, time.min, tzinfo=SANTIAGO)
    fin = inicio + timedelta(days=365)
    return inicio, fin


def dias_usados_en_ciclo(suspensiones: list, ciclo_inicio: datetime, ciclo_fin: datetime) -> int:
    """Suma los días de las suspensiones NO canceladas que caen dentro del ciclo.

    "Cae dentro" = `fecha_inicio` está en `[ciclo_inicio, ciclo_fin)`. Se atribuye
    por la fecha de INICIO (no se prorratea una suspensión que cruce el borde del
    ciclo). Una suspensión CANCELADA (`cancelada=True`) NO cuenta: al cancelar, el
    alumno recupera esos días del saldo anual de 14.
    """
    total = 0
    for s in suspensiones:
        if not _es_alumno(s):
            continue
        if bool(getattr(s, "cancelada", False)):
            continue
        fi = getattr(s, "fecha_inicio", None)
        if fi is None:
            continue
        if ciclo_inicio <= fi < ciclo_fin:
            total += int(getattr(s, "dias", 0) or 0)
    return total


def _dias_hasta(fecha_expiracion, hoy) -> int:
    """Días (de Chile) entre `hoy` y `fecha_expiracion`; sin fecha => -1 (ya venció)."""
    if fecha_expiracion is None:
        return -1
    return (fecha_chile(fecha_expiracion) - _a_date(hoy)).days


def suspension_activa(suspensiones: list, hoy):
    """La suspensión NO cancelada cuyo rango cubre `hoy` (o `None`).

    Fix de visibilidad: el alumno no puede tener dos suspensiones solapadas, así
    que antes de crear una nueva hay que mirar si ya hay una viva hoy. Devuelve el
    objeto (o `None`); el llamador decide si es error o sólo deshabilita el botón.
    """
    hoy_dia = _a_date(hoy)
    for s in suspensiones:
        if not _es_alumno(s):
            continue
        if bool(getattr(s, "cancelada", False)):
            continue
        inicio = fecha_chile(getattr(s, "fecha_inicio", None))
        fin = fecha_chile(getattr(s, "fecha_fin", None))
        if inicio is not None and fin is not None and inicio <= hoy_dia <= fin:
            return s
    return None


def motivo_suspension_activa(s) -> str:
    """El `motivo` exacto que ve el alumno: la suspensión activa y su fecha de fin."""
    fin = fecha_chile(getattr(s, "fecha_fin", None))
    if fin is None:
        return MOTIVO_SUSPENSION_ACTIVA
    return f"Ya tienes una suspensión activa hasta {fin.strftime('%d/%m/%Y')}"



def calcular_elegibilidad(suscripcion, usuario, suspensiones_del_ciclo: list, hoy) -> dict:
    """Aplica las reglas 3a y 3b (más saldo y tope de períodos) y arma la respuesta.

    `suspensiones_del_ciclo` ya viene filtrado al ciclo vigente (lo hace el router);
    acá sólo se suman sus días. Devuelve `motivo` con el texto EXACTO de pantalla
    (no un código), `saldo_disponible` (días que le quedan del ciclo) y
    `dias_para_vencimiento` (días hasta la expiración del plan).
    """
    # Las `admin_salud` no cuentan para el saldo de 14 días ni para el tope de
    # períodos: se descartan antes de sumar (regla de la suspensión por salud).
    suspensiones_del_ciclo = [s for s in suspensiones_del_ciclo if _es_alumno(s)]
    dias_usados = sum(
        int(getattr(s, "dias", 0) or 0)
        for s in suspensiones_del_ciclo
        if not bool(getattr(s, "cancelada", False))
    )
    periodos_usados = len(suspensiones_del_ciclo)
    saldo_disponible = max(0, DIAS_ANUALES - dias_usados)
    dias_para_vencimiento = _dias_hasta(suscripcion.fecha_expiracion, hoy)

    # Fix (Fanny): si YA hay una suspensión activa hoy, no se puede pedir otra. Va
    # ANTES de cualquier otra regla para que el botón del frontend salga
    # deshabilitado con el motivo correcto, sin esperar el rechazo del POST.
    activa = suspension_activa(suspensiones_del_ciclo, hoy)
    if activa is not None:
        return {
            "elegible": False,
            "motivo": motivo_suspension_activa(activa),
            "saldo_disponible": saldo_disponible,
            "dias_para_vencimiento": dias_para_vencimiento,
            "periodos_usados": periodos_usados,
        }

    elegible = True
    motivo = None

    creditos = suscripcion.creditos_disponibles
    if creditos is not None and creditos < MIN_CREDITOS:
        # Regla 3a: plan limitado con menos de 4 créditos.
        elegible = False
        motivo = MOTIVO_CREDITOS.format(n=creditos)
    elif dias_para_vencimiento < MIN_DIAS_HASTA_VENCER:
        # Regla 3b: menos de 10 días hasta el vencimiento (ambos tipos de plan).
        elegible = False
        motivo = MOTIVO_VENCIMIENTO.format(n=dias_para_vencimiento)
    elif saldo_disponible <= 0:
        elegible = False
        motivo = MOTIVO_SALDO
    elif periodos_usados >= MAX_PERIODOS:
        elegible = False
        motivo = MOTIVO_PERIODOS

    return {
        "elegible": elegible,
        "motivo": motivo,
        "saldo_disponible": saldo_disponible,
        "dias_para_vencimiento": dias_para_vencimiento,
        "periodos_usados": periodos_usados,
    }


# ── Cancelación anticipada (regla pura + escritura) ──────────────────────────
def puede_cancelar(suspensiones_del_ciclo: list) -> bool:
    """¿El alumno todavía tiene su cupo de cancelación en este ciclo?

    La cancelación anticipada se puede usar UNA vez por ciclo (el del aniversario
    de inscripción), NO una vez por suspensión. Devuelve False si ya hay alguna
    suspensión `cancelada=True` en `suspensiones_del_ciclo` (ya filtrado al ciclo
    vigente por el llamador). No cuenta lo que esté fuera del ciclo: una
    cancelación del año pasado no bloquea la de este año.
    """
    return not any(
        _es_alumno(s) and bool(getattr(s, "cancelada", False))
        for s in suspensiones_del_ciclo
    )


# ── Escritura (transacción atómica) ──────────────────────────────────────────
def _suscripcion_activa(db: Session, tenant_id: int, usuario_id: int):
    """La membresía vigente del alumno (misma regla que `/planes/membresia-activa`)."""
    return (
        db.query(Suscripcion)
        .filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id == usuario_id,
            Suscripcion.estado == "activo",
            vigente_hoy(Suscripcion.fecha_expiracion),
        )
        .order_by(
            Suscripcion.creditos_disponibles.desc().nulls_last(),
            Suscripcion.fecha_expiracion.desc(),
        )
        .first()
    )


def _cancelar_reservas_del_rango(db: Session, tenant_id: int, usuario_id: int,
                                 fecha_inicio: date, fecha_fin: date) -> int:
    """Cancela las reservas VIVAS con `clase.fecha` en [fecha_inicio, fecha_fin].

    Misma lógica que la cancelación manual: pasa el estado a
    `cancelada_por_suspension`, baja el aforo atómico (`-1` con `WHERE > 0`) y
    devuelve el crédito (`reembolsar_credito_reserva`, con su ventana P0-3 de
    Chile). La comparten la suspensión self-service y la de salud del admin, para
    que el efecto sobre las reservas sea EXACTAMENTE el mismo. No hace commit.
    """
    reservas_vivas = (
        db.query(Reserva, Clase)
        .join(Clase, Reserva.clase_id == Clase.id)
        .filter(
            Reserva.tenant_id == tenant_id,
            Reserva.alumno_id == usuario_id,
            no_cancelada(Reserva.estado),
            Clase.fecha >= fecha_inicio,
            Clase.fecha <= fecha_fin,
        )
        .all()
    )

    canceladas = 0
    ahora = ahora_santiago()
    for reserva, clase in reservas_vivas:
        # Transición de estado (reserva que estaba viva pasa a la causa nueva).
        reserva.estado = ESTADO_CANCELADA_POR_SUSPENSION

        # Aforo atómico (mismo patrón que `_cancelar_reserva`): `- 1` en la base
        # sobre la fila bloqueada y `WHERE > 0` para no bajar de cero.
        db.execute(
            update(Clase)
            .where(Clase.id == clase.id)
            .where(Clase.asistentes_confirmados > 0)
            .values(asistentes_confirmados=Clase.asistentes_confirmados - 1)
            .execution_options(synchronize_session=False)
        )

        # Devolución del crédito: MISMA lógica que la cancelación manual (P0-3 de
        # Chile para la ventana de 6h + reembolso por `suscripcion_id`).
        hora_inicio = clase.hora_inicio
        inicio_clase = datetime(
            clase.fecha.year, clase.fecha.month, clase.fecha.day,
            hora_inicio.hour, hora_inicio.minute, tzinfo=SANTIAGO,
        )
        horas_restantes = (inicio_clase - ahora).total_seconds() / 3600
        try:
            reembolsar_credito_reserva(
                db, tenant_id=tenant_id, reserva=reserva,
                horas_restantes=horas_restantes,
            )
        except ReembolsoTransitorio:
            # La devolución hizo rollback de TODO el request: la suspensión no se
            # confirma a medias. El llamador traduce esta excepción a un 503.
            db.rollback()
            raise
        canceladas += 1

    return canceladas


def crear_suspension(db: Session, suscripcion, usuario, fecha_inicio: date,
                     dias: int) -> SuspensionPlan:
    """Crea la suspensión y aplica todos sus efectos en UNA transacción.

    Re-valida elegibilidad + tope (defensa en profundidad, regla 5) y luego, en una
    sola transacción (todo o nada):

      1. crea el registro `suspensiones_plan`;
      2. `suscripcion.fecha_expiracion += dias` (misma fórmula para limitado/ilimitado);
      3. cancela las reservas vivas del alumno con `clase.fecha` en
         `[fecha_inicio, fecha_fin]` con `estado = 'cancelada_por_suspension'`,
         bajando el aforo y devolviendo el crédito con la MISMA lógica de la
         cancelación manual (`reembolsar_credito_reserva`);
      4. guarda cuántas canceló en `reservas_canceladas`.

    El commit es UNO solo al final: si algo falla, `rollback` deja todo como estaba.
    """
    tenant_id = suscripcion.tenant_id
    usuario_id = usuario.id

    # ── Serialización: dos requests simultáneos del mismo alumno no pueden gastar
    # el saldo dos veces. `FOR UPDATE` sobre el usuario hace que el segundo espere
    # y, al entrar, vea la suspensión que el primero ya commiteó (mismo patrón que
    # `POST /suscripciones`).
    db.query(Usuario).filter(
        Usuario.id == usuario_id,
        Usuario.tenant_id == tenant_id,
    ).with_for_update().first()

    # Re-lee la suscripción bloqueada (por si cambió entre el GET y este POST).
    sus = db.query(Suscripcion).filter(
        Suscripcion.id == suscripcion.id,
    ).with_for_update().first()
    if sus is None:
        raise ValueError("La suscripción ya no existe")
    suscripcion = sus

    hoy = hoy_santiago()
    ciclo_inicio, ciclo_fin = ciclo_vigente(usuario.created_at, hoy)
    suspensiones = (
        db.query(SuspensionPlan)
        .filter(SuspensionPlan.usuario_id == usuario_id,
                SuspensionPlan.tenant_id == tenant_id)
        .all()
    )

    # Fix: no se puede crear una suspensión si YA hay una activa hoy (defensa en
    # profundidad: el frontend ya la deshabilita vía `calcular_elegibilidad`, pero
    # acá se valida sobre TODAS las suspensiones del usuario, no sólo las del ciclo).
    activa = suspension_activa(suspensiones, hoy)
    if activa is not None:
        raise ValueError(motivo_suspension_activa(activa))

    suspensiones_del_ciclo = [
        s for s in suspensiones if ciclo_inicio <= s.fecha_inicio < ciclo_fin
    ]
    elegibilidad = calcular_elegibilidad(suscripcion, usuario, suspensiones_del_ciclo, hoy)

    if not elegibilidad["elegible"]:
        raise ValueError(elegibilidad["motivo"])
    if dias < 1:
        raise ValueError("El período debe ser de al menos 1 día.")
    if dias > elegibilidad["saldo_disponible"]:
        # Regla 5: nunca confiar sólo en el frontend.
        raise ValueError(
            f"Solo puedes suspender {elegibilidad['saldo_disponible']} día(s) "
            f"en este ciclo (pediste {dias})."
        )

    fecha_inicio_dt = inicio_del_dia_chile(fecha_inicio)
    fecha_fin_dt = fin_del_dia_chile(fecha_inicio + timedelta(days=dias - 1))

    suspension = SuspensionPlan(
        tenant_id=tenant_id,
        usuario_id=usuario_id,
        suscripcion_id=suscripcion.id,
        fecha_inicio=fecha_inicio_dt,
        fecha_fin=fecha_fin_dt,
        dias=dias,
        # El original se captura ANTES de extender (la línea de abajo hace el `+= dias`).
        # Es lo que permite revertir exacto si el alumno cancela antes de tiempo.
        fecha_expiracion_original=suscripcion.fecha_expiracion,
        reservas_canceladas=0,
    )
    db.add(suspension)
    db.flush()  # asigna id sin cerrar la transacción

    # Regla 4b: extiende la expiración (misma fórmula para ambos tipos de plan).
    suscripcion.fecha_expiracion = suscripcion.fecha_expiracion + timedelta(days=dias)

    # Regla 4c: cancela las reservas vivas del rango (helper compartido con la
    # suspensión por salud del admin: el efecto sobre reservas es el mismo).
    canceladas = _cancelar_reservas_del_rango(
        db, tenant_id, usuario_id, fecha_inicio,
        fecha_inicio + timedelta(days=dias - 1))

    suspension.reservas_canceladas = canceladas

    # Campana del ADMIN: el alumno suspendió su plan. Aviso in-app para los admins
    # del box en la MISMA transacción (commit=False: el commit lo hace esta función).
    notificar_admins_del_tenant(
        db, tenant_id, tipo="suspension_creada",
        mensaje=f"{usuario.nombre} suspendió su plan ({dias} día(s), desde {fecha_inicio_dt.strftime('%d/%m/%Y')}).",
        commit=False,
    )

    db.commit()
    db.refresh(suspension)
    return suspension


def cancelar_suspension(db: Session, suspension, suscripcion) -> Suscripcion:
    """Cancela una suspensión activa y revierte `fecha_expiracion` a la original.

    Fix del abuso en plan ILIMITADO: si el alumno vuelve antes de que termine su
    suspensión, con esto puede revertir la extensión y no quedarse con días de
    regalo. Reglas:

      * la suspensión debe estar ACTIVA hoy (`fecha_inicio <= hoy <= fecha_fin`) y
        no haber sido cancelada ya;
      * cupo anual: UNA sola cancelación por ciclo (`puede_cancelar`);
      * `fecha_expiracion = fecha_expiracion_original` (exacto, no proporcional).

    NO revierte las reservas que ya se cancelaron automáticamente al suspender: es
    una limitación conocida (documentada), no un bug. Transacción atómica.
    """
    tenant_id = suspension.tenant_id
    usuario_id = suspension.usuario_id
    hoy = hoy_santiago()

    # Serialización (mismo patrón que `crear_suspension`): un doble click no puede
    # cancelar dos veces ni gastar el cupo anual dos veces.
    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id,
        Usuario.tenant_id == tenant_id,
    ).with_for_update().first()
    if usuario is None:
        raise ValueError(MOTIVO_SUSPENSION_NO_EXISTE)

    susp = db.query(SuspensionPlan).filter(
        SuspensionPlan.id == suspension.id,
        SuspensionPlan.tenant_id == tenant_id,
    ).with_for_update().first()
    if susp is None:
        raise ValueError(MOTIVO_SUSPENSION_NO_EXISTE)
    suspension = susp

    # Seguridad: la ruta self-service del alumno sólo cancela suspensiones propias
    # (`origen='alumno'`). Las de salud (`admin_salud`) las gestiona el admin, y no
    # se pueden cancelar armando el request a mano por esta ruta.
    if getattr(suspension, "origen", ORIGEN_ALUMNO) != ORIGEN_ALUMNO:
        raise ValueError("Esta suspensión es por salud y la gestiona el box.")

    if suspension.cancelada:
        raise ValueError(MOTIVO_SUSPENSION_YA_CANCELADA)

    inicio = fecha_chile(suspension.fecha_inicio)
    fin = fecha_chile(suspension.fecha_fin)
    if not (inicio <= hoy <= fin):
        raise ValueError(MOTIVO_SUSPENSION_NO_ACTIVA)

    sus = db.query(Suscripcion).filter(
        Suscripcion.id == suscripcion.id,
        Suscripcion.tenant_id == tenant_id,
    ).with_for_update().first()
    if sus is None:
        raise ValueError(MOTIVO_SUSPENSION_NO_EXISTE)
    suscripcion = sus

    # Cupo anual: sólo se puede cancelar UNA vez por ciclo (no por suspensión).
    ciclo_inicio, ciclo_fin = ciclo_vigente(usuario.created_at, hoy)
    suspensiones = (
        db.query(SuspensionPlan)
        .filter(SuspensionPlan.usuario_id == usuario_id,
                SuspensionPlan.tenant_id == tenant_id)
        .all()
    )
    del_ciclo = [s for s in suspensiones if ciclo_inicio <= s.fecha_inicio < ciclo_fin]
    if not puede_cancelar(del_ciclo):
        raise ValueError(MOTIVO_CANCELACION_USADA)

    # Reversión exacta: la fecha vuelve a la que tenía antes de la extensión.
    suscripcion.fecha_expiracion = suspension.fecha_expiracion_original
    suspension.cancelada = True
    suspension.cancelada_en = ahora_santiago()

    # Campana del ADMIN: el alumno canceló su suspensión. Aviso in-app (misma transacción).
    notificar_admins_del_tenant(
        db, tenant_id, tipo="suspension_cancelada",
        mensaje=f"{usuario.nombre} canceló su suspensión activa.",
        commit=False,
    )

    db.commit()
    db.refresh(suscripcion)
    return suscripcion


# ── Suspensión por salud (admin) ─────────────────────────────────────────────
def crear_suspension_salud(db: Session, usuario_id: int, admin_id: int,
                           fecha_inicio: date, fecha_fin: date,
                           motivo: str | None = None) -> SuspensionPlan:
    """Crea una suspensión por salud (la crea SOLO el admin, desde la ficha).

    A diferencia de la self-service del alumno, NO tiene tope de días, ni mínimo de
    créditos, ni mínimo de 10 días hasta el vencimiento, ni el límite de períodos:
    el admin define `fecha_inicio`/`fecha_fin` y el sistema calcula `dias` a partir
    de esas dos fechas (`dias_entre`). Sólo valida:

      * `fecha_fin > fecha_inicio`;
      * que el alumno tenga una suscripción activa.

    El EFECTO sobre la suscripción y las reservas es EL MISMO que el de la del
    alumno: `fecha_expiracion += dias`, se guarda `fecha_expiracion_original` para
    revertir exacto, y las reservas vivas del rango pasan a
    `cancelada_por_suspension` (helper compartido). Transacción atómica.
    """
    fi = _a_date(fecha_inicio)
    ff = _a_date(fecha_fin)
    if ff <= fi:
        raise ValueError("La fecha de vuelta debe ser posterior a la de inicio.")
    dias = dias_entre(fi, ff)

    # Serialización: bloquea el usuario para que dos suspensiones simultáneas no se
    # pisen. El tenant se saca del propio usuario (scoping implícito).
    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id,
    ).with_for_update().first()
    if usuario is None:
        raise ValueError("El alumno no existe.")
    tenant_id = usuario.tenant_id

    suscripcion = _suscripcion_activa(db, tenant_id, usuario_id)
    if suscripcion is None:
        raise ValueError(MOTIVO_SIN_PLAN)

    # Re-lee la suscripción bloqueada (por si cambió entre la lectura y el POST).
    sus = db.query(Suscripcion).filter(
        Suscripcion.id == suscripcion.id,
    ).with_for_update().first()
    if sus is None:
        raise ValueError("La suscripción ya no existe")
    suscripcion = sus

    fecha_inicio_dt = inicio_del_dia_chile(fi)
    fecha_fin_dt = fin_del_dia_chile(ff)

    suspension = SuspensionPlan(
        tenant_id=tenant_id,
        usuario_id=usuario_id,
        suscripcion_id=suscripcion.id,
        fecha_inicio=fecha_inicio_dt,
        fecha_fin=fecha_fin_dt,
        dias=dias,
        fecha_expiracion_original=suscripcion.fecha_expiracion,
        reservas_canceladas=0,
        origen=ORIGEN_ADMIN_SALUD,
        motivo=motivo,
        creada_por_usuario_id=admin_id,
    )
    db.add(suspension)
    db.flush()

    # Mismo efecto que la self-service: extiende la expiración y cancela reservas.
    suscripcion.fecha_expiracion = suscripcion.fecha_expiracion + timedelta(days=dias)
    canceladas = _cancelar_reservas_del_rango(db, tenant_id, usuario_id, fi, ff)
    suspension.reservas_canceladas = canceladas

    db.commit()
    db.refresh(suspension)
    return suspension


def cancelar_suspension_salud(db: Session, suspension_id: int,
                              admin_id: int) -> Suscripcion:
    """Cancela una suspensión por salud y revierte `fecha_expiracion` exacta.

    El admin cancela cuando quiera y las veces que quiera: SIN cupo anual y SIN la
    ventana de "activa hoy" de la self-service. Sólo valida que exista, que sea
    `origen='admin_salud'` y que no esté ya cancelada. `admin_id` queda en la firma
    por consistencia/auditoría (el llamador ya validó el rol admin por el token).
    """
    suspension = db.query(SuspensionPlan).filter(
        SuspensionPlan.id == suspension_id,
    ).with_for_update().first()
    if suspension is None:
        raise ValueError(MOTIVO_SUSPENSION_NO_EXISTE)
    if getattr(suspension, "origen", ORIGEN_ALUMNO) != ORIGEN_ADMIN_SALUD:
        raise ValueError("Esta suspensión no es por salud.")
    if suspension.cancelada:
        raise ValueError(MOTIVO_SUSPENSION_YA_CANCELADA)

    sus = db.query(Suscripcion).filter(
        Suscripcion.id == suspension.suscripcion_id,
    ).with_for_update().first()
    if sus is None:
        raise ValueError("La suscripción ya no existe")

    # Reversión exacta: sin el límite de 1 cancelación/año de la self-service.
    sus.fecha_expiracion = suspension.fecha_expiracion_original
    suspension.cancelada = True
    suspension.cancelada_en = ahora_santiago()

    db.commit()
    db.refresh(sus)
    return sus


