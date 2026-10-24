"""reservas: una sola reserva VIVA por (clase, alumno)

Revision ID: 057_reserva_unica_viva
Revises: 056_aviso_promocion
Create Date: 2026-10-24

QUÉ RESUELVE
------------
`POST /reservas` valida los duplicados con un `SELECT` y después INSERTA: entre
la lectura y el INSERT hay una ventana en la que dos requests del MISMO alumno
(doble clic, dos pestañas, reintento del móvil) ven "no hay duplicado", los dos
descuentan un crédito y los dos crean la reserva. La app ya se protege con el
lock de la suscripción y con un UPDATE condicional de créditos (ver
`app/api/v1/reservas.py`), pero la regla de negocio —"un alumno no puede tener
dos reservas vivas de la misma clase"— tiene que estar también en la BD: es la
única capa que no se puede saltar (un script, n8n o un endpoint nuevo).

  * Índice ÚNICO **PARCIAL** `uq_reservas_clase_alumno_viva` sobre
    (clase_id, alumno_id) `WHERE estado NOT IN ('cancelled', 'cancelada')`.
    Parcial a propósito: el alumno puede volver a reservar la clase después de
    cancelar (y el histórico conserva todas sus cancelaciones). El predicado es
    el MISMO de `shared.estados.ESTADOS_CANCELADA` (`lista_sql()`); si esa lista
    cambia, cambia el `NOT IN` de acá y el del modelo (`app/models/reserva.py`
    declara el mismo índice para que `create_all` y las migraciones coincidan).

Backfill (antes de crear el índice, si no la creación falla)
------------------------------------------------------------
Si una base ya tiene duplicados vivos (creados por la carrera), se deja UNA
sola reserva viva por (clase, alumno) —la de **id más bajo**, la original— y
las demás pasan a `cancelada`. Como cada duplicado había consumido un asiento,
se devuelve ese asiento al aforo (`clases.asistentes_confirmados`, con
`GREATEST(..., 0)` para no quedar en negativo): sin esto, la clase quedaría con
un cupo fantasma ocupado para siempre. No se tocan créditos: devolverlos exige
decidir cuál reserva se cobró y eso es un cuadre de negocio (mantenimiento A.3),
no una migración de esquema.

downgrade(): borra el índice. Las reservas que el backfill canceló NO se
reactivan (volver a crearlas sería recrear el duplicado que la regla prohíbe).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '057_reserva_unica_viva'
down_revision: Union[str, None] = '056_aviso_promocion'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = 'reservas'
INDICE = 'uq_reservas_clase_alumno_viva'
# Espejo EXACTO de `shared/estados.ESTADOS_CANCELADA` (las migraciones no
# importan la app: son un contrato congelado con el esquema de ese momento).
ESTADOS_CANCELADA = ('cancelled', 'cancelada')
PREDICADO = "estado NOT IN ({})".format(
    ", ".join(f"'{e}'" for e in ESTADOS_CANCELADA))


def _indice_existe(nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(i['name'] == nombre
               for i in inspector.get_indexes(TABLA))


def sql_dedupe() -> str:
    """El SQL del backfill (público: se puede EXPLAIN-ear sin ejecutar nada)."""
    return f"""
        WITH vivas AS (
            SELECT id,
                   clase_id,
                   ROW_NUMBER() OVER (PARTITION BY clase_id, alumno_id
                                      ORDER BY id) AS orden
            FROM {TABLA}
            WHERE {PREDICADO}
        ), sobrantes AS (
            SELECT id, clase_id FROM vivas WHERE orden > 1
        ), canceladas AS (
            UPDATE {TABLA} r
               SET estado = 'cancelada', updated_at = now()
              FROM sobrantes s
             WHERE r.id = s.id
            RETURNING s.clase_id
        )
        UPDATE clases c
           SET asistentes_confirmados =
                   GREATEST(COALESCE(c.asistentes_confirmados, 0) - t.cuantas, 0)
          FROM (SELECT clase_id, COUNT(*) AS cuantas
                  FROM canceladas GROUP BY clase_id) t
         WHERE c.id = t.clase_id
    """


def _cancelar_duplicados_vivos() -> None:
    """Deja UNA reserva viva por (clase, alumno) y devuelve el aforo sobrante."""
    op.execute(sql_dedupe())


def upgrade() -> None:
    # Idempotente (una base de TEST puede haberse creado con
    # `Base.metadata.create_all`, que ya trae el índice del modelo).
    if _indice_existe(INDICE):
        return
    _cancelar_duplicados_vivos()
    op.create_index(INDICE, TABLA, ['clase_id', 'alumno_id'],
                    unique=True, postgresql_where=sa.text(PREDICADO))


def downgrade() -> None:
    if _indice_existe(INDICE):
        op.drop_index(INDICE, table_name=TABLA)
