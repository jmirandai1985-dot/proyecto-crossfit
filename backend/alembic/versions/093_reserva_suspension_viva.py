"""reservas: la reserva cancelada por SUSPENSIÓN libera el cupo

Revision ID: 093_reserva_suspension_viva
Revises: 092_usuarios_es_prueba
Create Date: 2026-11-26

QUÉ RESUELVE
-----------
La suspensión de un plan cancela las reservas del alumno con el estado
`cancelada_por_suspension` (`shared.estados.ESTADO_CANCELADA_POR_SUSPENSION`),
que desde entonces forma parte de `ESTADOS_CANCELADA`. El índice único parcial
`uq_reservas_clase_alumno_viva` de la migración 057 se creó con el predicado
viejo —sólo `'cancelled'` y `'cancelada'`—, así que una reserva cancelada por la
suspensión seguía contando como VIVA para la base:

  * el alumno no podía volver a reservar esa clase (el índice la veía ocupada);
  * la base no liberaba el cupo que la propia app acababa de liberar.

La app y el modelo (`app/models/reserva.py`) ya leen la lista compartida, que
incluye el estado nuevo. Esta migración pone el índice a la par: recrea el MISMO
índice (mismas columnas, único, parcial) con el predicado que agrega
`'cancelada_por_suspension'` a los estados excluidos.

POR QUÉ SE RECREA (y no se edita la 057)
----------------------------------------
Una migración aplicada es un contrato congelado con el esquema de ese momento:
editar la 057 cambiaría el pasado y las bases que ya la corrieron no verían el
cambio. Por eso nace una migración nueva que reemplaza el índice.

`CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY` no pueden correr dentro
de una transacción, así que van dentro de `op.get_context().autocommit_block()`.

Además del predicado, el `CONCURRENTLY` evita bloquear la tabla `reservas`
mientras se reconstruye el índice en una base con tráfico.

downgrade(): restaurar EXACTAMENTE el índice original de la 057 (predicado de
dos estados, mismo nombre y columnas). Las reservas canceladas por suspensión NO
se reactivan: volver a crearlas sería recrear la reserva que la regla prohíbe.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "093_reserva_suspension_viva"
down_revision: Union[str, None] = "092_usuarios_es_prueba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "reservas"
INDICE = "uq_reservas_clase_alumno_viva"
COLUMNAS = "clase_id, alumno_id"

# Espejo EXACTO del predicado de la 057 (contrato congelado de esa migración).
ESTADOS_CANCELADA_057 = ("cancelled", "cancelada")
# Espejo de `shared.estados.ESTADOS_CANCELADA`: la cancelación por suspensión
# también deja la reserva NO viva (libera el cupo).
ESTADOS_CANCELADA = ESTADOS_CANCELADA_057 + ("cancelada_por_suspension",)


def _predicado(estados: tuple) -> str:
    return "estado NOT IN ({})".format(", ".join(f"'{e}'" for e in estados))


PREDICADO_057 = _predicado(ESTADOS_CANCELADA_057)
PREDICADO = _predicado(ESTADOS_CANCELADA)


def _recrear_indice(predicado: str) -> None:
    """DROP + CREATE del índice fuera de transacción (lo exige CONCURRENTLY).

    El DROP es `IF EXISTS` para tolerar una base creada con
    `Base.metadata.create_all` o un intento anterior que dejó el índice
    inválido; el nombre no cambia, así que `es_reserva_duplicada()` sigue
    reconociendo la violación.
    """
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}")
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY {INDICE} "
            f"ON {TABLA} ({COLUMNAS}) WHERE {predicado}"
        )


def upgrade() -> None:
    _recrear_indice(PREDICADO)


def downgrade() -> None:
    _recrear_indice(PREDICADO_057)
