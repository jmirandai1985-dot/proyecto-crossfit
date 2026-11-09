"""
Devolución del crédito de una reserva cancelada.

Lógica UNICA compartida por la cancelación manual (`DELETE /reservas/{id}`) y la
cancelación automática por suspensión (`suspensiones_service.crear_suspension`).
Vive en un servicio (y no dentro del router de reservas) para que los dos caminos
llamen a la MISMA función en vez de mantener dos copias del reembolso.
"""
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.estados import da_acceso_hoy
from app.models.suscripcion import Suscripcion


class ReembolsoTransitorio(Exception):
    """La devolución no se pudo aplicar en esta pasada (alta demanda): reintentar.

    Es la excepción de dominio que reemplaza al `HTTPException(503)` que vivía
    inline en `reservas.py`: el servicio no sabe de HTTP (ningún servicio lo sabe),
    así que el llamador traduce esta excepción al status que le corresponde.
    """


def reembolsar_credito_reserva(db: Session, *, tenant_id: int, reserva,
                               horas_restantes: float) -> tuple[bool, dict | None]:
    """Devuelve el crédito de una reserva cancelada a la membresía que lo pagó.

    Misma lógica que `DELETE /reservas/{id}` (antes inline, ahora acá):

      1. la membresía que PAGÓ el crédito se resuelve por `reserva.suscripcion_id`
         (migración 059) con `da_acceso_hoy` y `with_for_update()` — el lock evita
         que el `+ 1` compita con otra cancelación o con un consumo del POST;
      2. red de seguridad: mismo `ORDER BY` de siempre (con `id` como desempate
         determinista) si la original no da acceso, anotando la redirección para
         auditarla después;
      3. devolución ATÓMICA (`+ 1` lo hace la base, `rowcount` dice si de verdad
         se devolvió). `creditos_disponibles IS NOT NULL` = plan ilimitado: no hay
         crédito que devolver.

    NO hace `commit()`: es parte de la transacción del llamador (la cancelación
    manual la commitea al final; la suspensión, en su propio commit atómico).

    La ventana de 6h entra como `horas_restantes` (la calcula cada llamador con la
    misma regla P0-3 de Chile): dentro de la ventana el crédito NO se devuelve,
    igual que en la cancelación manual.

    Devuelve `(reembolsado, redireccion)`; `redireccion` es el dict para auditar
    (None si el crédito volvió a su membresía original o no se devolvió).
    """
    reembolsado = False
    redireccion = None
    if horas_restantes >= 6 and (reserva.tokens_gastados or 0) > 0:
        membresia = None
        if reserva.suscripcion_id is not None:
            membresia = db.query(Suscripcion).filter(
                Suscripcion.id == reserva.suscripcion_id,
                Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == reserva.alumno_id,
                da_acceso_hoy(Suscripcion.estado, Suscripcion.fecha_expiracion)
            ).with_for_update().first()
        if not membresia:
            membresia = db.query(Suscripcion).filter(
                Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id == reserva.alumno_id,
                da_acceso_hoy(Suscripcion.estado, Suscripcion.fecha_expiracion)
            ).order_by(
                Suscripcion.creditos_disponibles.desc().nulls_last(),
                Suscripcion.fecha_expiracion.desc(),
                Suscripcion.id.desc()
            ).first()
            if membresia:
                redireccion = {
                    "motivo": ("sin_registro" if reserva.suscripcion_id is None
                               else "membresia_original_sin_acceso"),
                    "reserva_id": reserva.id,
                    "alumno_id": reserva.alumno_id,
                    "clase_id": reserva.clase_id,
                    "membresia_original_id": reserva.suscripcion_id,
                    "membresia_destino_id": membresia.id,
                }
        if membresia:
            try:
                devolucion = db.execute(
                    update(Suscripcion)
                    .where(Suscripcion.id == membresia.id)
                    .where(Suscripcion.tenant_id == tenant_id)
                    .where(Suscripcion.creditos_disponibles.isnot(None))
                    .values(creditos_disponibles=Suscripcion.creditos_disponibles + 1)
                    .execution_options(synchronize_session=False)
                )
            except DBAPIError:
                db.rollback()
                raise ReembolsoTransitorio("Alta demanda, intenta de nuevo")
            reembolsado = devolucion.rowcount > 0

    return reembolsado, redireccion
