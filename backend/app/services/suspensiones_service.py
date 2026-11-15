"""
Suspensión de plan por salud (la crea y la cancela SÓLO el admin).

El alumno ya NO puede autogestionar suspensiones: el self-service (pedir/cancelar su
propia suspensión, con el tope de 14 días/año y el cupo de cancelación) se retiró.

Reglas vigentes:

  1. La crea el admin desde la ficha del alumno indicando `fecha_inicio` y
     `fecha_fin` (el `dias` lo calcula `dias_entre`): sin tope ni cupo.
  2. El `origen` queda en `admin_salud` y el `motivo` es libre (p. ej. "cirugía").
  3. Al confirmar: se crea el registro, `fecha_expiracion += dias` y se cancelan
     las reservas vivas del rango con el estado `cancelada_por_suspension`.
  4. Al cancelar: se marca cancelada y `fecha_expiracion` vuelve a la original
     EXACTA (sin cupo anual ni ventana de "activa hoy").
"""
from datetime import date, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.estados import ESTADO_CANCELADA_POR_SUSPENSION, no_cancelada, vigente_hoy
from app.models.clase import Clase
from app.models.reserva import Reserva
from app.models.suscripcion import Suscripcion
from app.models.suspension_plan import SuspensionPlan
from app.models.usuario import Usuario
from app.services.reservas_service import reembolsar_credito_reserva, ReembolsoTransitorio
from app.utils.santiago import (
    SANTIAGO,
    ahora_santiago,
    fin_del_dia_chile,
    inicio_del_dia_chile,
)

# ── Origen de la suspensión ───────────────────────────────────────────────────
# `admin_salud`: la crea/cancela el admin (sin tope ni cupo). `alumno` se conserva
# sólo para identificar las suspensiones históricas del antiguo self-service.
ORIGEN_ALUMNO = "alumno"
ORIGEN_ADMIN_SALUD = "admin_salud"

# Textos de los rechazos que viajan al cliente (el resto del copy propio del
# self-service del alumno se retiró junto con esos endpoints).
MOTIVO_SIN_PLAN = "No tienes un plan activo para suspender."

# ── Cancelación (la hace el admin, sin cupo anual) ───────────────────────────
MOTIVO_SUSPENSION_NO_EXISTE = "La suspensión no existe."
MOTIVO_SUSPENSION_YA_CANCELADA = "Esta suspensión ya fue cancelada."


# ── Helpers puros ────────────────────────────────────────────────────────────
def _a_date(valor) -> date:
    """Normaliza `datetime`/`date` a `date` (los tests pueden pasar cualquiera)."""
    return valor.date() if isinstance(valor, datetime) else valor


def dias_entre(fecha_inicio, fecha_fin) -> int:
    """Días INCLUSIVOS entre dos fechas (una suspensión del 01 al 03 son 3 días).

    Es la fórmula de la suspensión por salud del admin: el admin define inicio y
    vuelta (no una cantidad de días como la del alumno), y `dias` se calcula acá
    como `(fecha_fin - fecha_inicio).days + 1`, inclusivo en ambos extremos.
    """
    fi = _a_date(fecha_inicio)
    ff = _a_date(fecha_fin)
    return (ff - fi).days + 1


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
    Chile). La usa la suspensión por salud del admin, con el MISMO efecto sobre las
    reservas que la cancelación manual. No hace commit.
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


