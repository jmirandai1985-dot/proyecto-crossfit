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

from app.core.estados import ESTADO_CANCELADA_POR_SUSPENSION, no_cancelada
from app.models.clase import Clase
from app.models.reserva import Reserva
from app.models.suscripcion import Suscripcion
from app.models.suspension_plan import SuspensionPlan
from app.models.usuario import Usuario
from app.services.reservas_service import reembolsar_credito_reserva, ReembolsoTransitorio
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

# El texto EXACTO que se le muestra al alumno (regla del prompt: el `motivo` es el
# copy de pantalla, no un código interno). Los dos primeros llevan el número REAL
# interpolado con `.format(n=...)` en `calcular_elegibilidad`.
MOTIVO_SIN_PLAN = "No tienes un plan activo para suspender."
MOTIVO_CREDITOS = "No disponible — te quedan solo {n} créditos, necesitas al menos 4"
MOTIVO_VENCIMIENTO = "No disponible — faltan {n} días para poder suspender"
MOTIVO_SALDO = "Ya usaste los 14 días de suspensión de este ciclo."
MOTIVO_PERIODOS = "Ya usaste los 2 períodos de suspensión permitidos en este ciclo."


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
    """Suma los días de las suspensiones que caen dentro del ciclo vigente.

    "Cae dentro" = `fecha_inicio` está en `[ciclo_inicio, ciclo_fin)`. Se atribuye
    por la fecha de INICIO (no se prorratea una suspensión que cruce el borde del
    ciclo): es la regla más simple y la que usa el saldo del alumno.
    """
    total = 0
    for s in suspensiones:
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


def calcular_elegibilidad(suscripcion, usuario, suspensiones_del_ciclo: list, hoy) -> dict:
    """Aplica las reglas 3a y 3b (más saldo y tope de períodos) y arma la respuesta.

    `suspensiones_del_ciclo` ya viene filtrado al ciclo vigente (lo hace el router);
    acá sólo se suman sus días. Devuelve `motivo` con el texto EXACTO de pantalla
    (no un código), `saldo_disponible` (días que le quedan del ciclo) y
    `dias_para_vencimiento` (días hasta la expiración del plan).
    """
    dias_usados = sum(int(getattr(s, "dias", 0) or 0) for s in suspensiones_del_ciclo)
    periodos_usados = len(suspensiones_del_ciclo)
    saldo_disponible = max(0, DIAS_ANUALES - dias_usados)
    dias_para_vencimiento = _dias_hasta(suscripcion.fecha_expiracion, hoy)

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


# ── Escritura (transacción atómica) ──────────────────────────────────────────
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
        reservas_canceladas=0,
    )
    db.add(suspension)
    db.flush()  # asigna id sin cerrar la transacción

    # Regla 4b: extiende la expiración (misma fórmula para ambos tipos de plan).
    suscripcion.fecha_expiracion = suscripcion.fecha_expiracion + timedelta(days=dias)

    # Regla 4c: cancela las reservas vivas del rango.
    reservas_vivas = (
        db.query(Reserva, Clase)
        .join(Clase, Reserva.clase_id == Clase.id)
        .filter(
            Reserva.tenant_id == tenant_id,
            Reserva.alumno_id == usuario_id,
            no_cancelada(Reserva.estado),
            Clase.fecha >= fecha_inicio,
            Clase.fecha <= fecha_inicio + timedelta(days=dias - 1),
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

    suspension.reservas_canceladas = canceladas
    db.commit()
    db.refresh(suspension)
    return suspension


