"""reservas: QUÉ suscripción pagó el crédito de cada reserva

Revision ID: 059_reserva_suscripcion_id
Revises: 058_tarjeta_referidos
Create Date: 2026-10-25

QUÉ RESUELVE
------------
`reservas.tokens_gastados` dice CUÁNTOS créditos se gastaron, pero no DE QUIÉN
salieron. Al cancelar, `DELETE /reservas/{id}` busca "la membresía vigente del
alumno" con un `ORDER BY creditos_disponibles DESC, fecha_expiracion DESC`: si
el alumno tiene (o tuvo) dos suscripciones —una renovación, un "Pase de
regreso", una compra de emergencia— el crédito puede volver a una membresía
que NO lo pagó. El saldo total del alumno queda igual, pero el cuadre por plan
no: A.3 de `mantenimiento_cloud.py` reconstruye el consumo por suscripción y ve
un descuadre que no existe.

Esta migración registra el dato que faltaba:

  * `suscripcion_id` (nullable) = la suscripción que pagó el crédito.
    `ON DELETE SET NULL` como el resto de las trazas: borrar el plan no puede
    borrar la reserva (el alumno sí fue a la clase).
  * Índice `ix_reservas_suscripcion_id`: `DELETE /reservas/{id}` resuelve la
    membresía por esta columna en cada cancelación (y el mantenimiento la
    puede cruzar para auditar los reembolsos).

**NULL es un valor con significado**: "no se sabe / no había plan" — una
presencia sin cargo (`POST /asistencia/clases/{id}/sin-reserva`, que crea la
reserva con `tokens_gastados = 0`) o una reserva anterior a esta migración que
el backfill no pudo atribuir con certeza. El endpoint de cancelación trata el
NULL como siempre (ORDER BY de respaldo) y lo registra en `auditoria`, así que
se puede medir cuántas cancelaciones siguen cayendo en el camino viejo.

Backfill conservador (sólo cuando NO hay duda)
----------------------------------------------
Se rellena únicamente donde la heurística de imputación de A.3
(`maintenance/mantenimiento_cloud.py: sql_reserva_imputable()`) deja **un
único candidato** para esa reserva:

  1. la suscripción es del mismo alumno y del mismo box;
  2. su ventana cubre la fecha de la CLASE y no es `pendiente`/`rechazado`
     (esos estados nunca dieron acceso: no pudieron cobrar nada);
  3. `sql_reserva_imputable()`: la reserva se creó dentro de la vida de esa
     suscripción, o —si se creó antes— no existía otra suscripción anterior que
     pudiera haberla cobrado (ver el docstring de A.3: es el caso 2250→2251 del
     seed).

Si dos suscripciones empatan, la reserva queda en NULL a propósito: adivinar
sería escribir un dato FALSO en el registro que se usa para devolver dinero.
Los candidatos se agrupan por reserva y sólo entra el grupo de `count(*) = 1`.

El día se calcula en hora de Chile (`SET LOCAL TIME ZONE`), igual que el job
(`SET_TZ = SET TIME ZONE 'America/Santiago'`), porque `fecha_inicio::date` y
`fecha_expiracion::date` dependen de la TZ de la sesión y en Neon la sesión
arranca en UTC.

Idempotente (una base de TEST puede haberse creado con
`Base.metadata.create_all`, que ya trae la columna y el índice del modelo).

downgrade(): borra índice, FK y columna. Las reservas que el backfill atribuyó
pierden el dato (no hay otra tabla donde guardarlo); el resto del esquema queda
como estaba.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "059_reserva_suscripcion_id"
down_revision: Union[str, None] = "058_tarjeta_referidos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "reservas"
TABLA_SUSCRIPCIONES = "suscripciones"
COLUMNA = "suscripcion_id"
INDICE = "ix_reservas_suscripcion_id"
NOMBRE_FK = "fk_reservas_suscripcion_id"
TZ_CLT = "America/Santiago"
# Espejo EXACTO de `shared.estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES` (las
# migraciones no importan la app: son un contrato congelado con el esquema de
# ese momento).
ESTADOS_NUNCA_VIGENTES = ("pendiente", "rechazado")
NUNCA_VIGENTES_SQL = ", ".join(f"'{e}'" for e in ESTADOS_NUNCA_VIGENTES)


def _columnas(tabla: str = TABLA) -> set:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(tabla)}


def _indices(tabla: str = TABLA) -> set:
    inspector = sa.inspect(op.get_bind())
    return {i["name"] for i in inspector.get_indexes(tabla)}


def _foraneas(tabla: str = TABLA) -> set:
    inspector = sa.inspect(op.get_bind())
    return {f["name"] for f in inspector.get_foreign_keys(tabla) if f.get("name")}


def sql_imputable(reserva: str = "r", suscripcion: str = "s",
                  clase: str = "c") -> str:
    """Predicado de A.3: ¿esta reserva pudo cobrarse de ESTA suscripción?

    Espejo LITERAL de `maintenance/mantenimiento_cloud.py: sql_reserva_imputable()`
    (misma condición, mismas expresiones): la migración no importa
    `maintenance/` porque tiene que valer para el esquema de HOY y no para el
    código de mañana, pero el SQL es el mismo para que el backfill y el job no
    discrepen.

    Una reserva creada ANTES de la suscripción no se le imputa si existía otra
    suscripción anterior que pudo cobrarla: creada antes de la reserva y con la
    fecha de la reserva **y** la de la clase dentro de su ventana. Los
    `::date` se resuelven en la TZ de la sesión, que acá se fija con
    `SET LOCAL TIME ZONE` igual que el job con `SET TIME ZONE` (línea 465).
    """
    return (
        f"({reserva}.fecha_reserva >= {suscripcion}.created_at OR NOT EXISTS ("
        f"SELECT 1 FROM suscripciones sp "
        f"WHERE sp.usuario_id = {suscripcion}.usuario_id AND sp.id <> {suscripcion}.id "
        f"AND sp.tenant_id = {suscripcion}.tenant_id "
        f"AND sp.created_at <= {reserva}.fecha_reserva "
        f"AND sp.estado NOT IN ({NUNCA_VIGENTES_SQL}) "
        f"AND ({reserva}.fecha_reserva AT TIME ZONE '{TZ_CLT}')::date "
        "BETWEEN sp.fecha_inicio::date AND sp.fecha_expiracion::date "
        f"AND {clase}.fecha BETWEEN sp.fecha_inicio::date AND sp.fecha_expiracion::date))"
    )


def sql_backfill() -> str:
    """El SQL del backfill (público: se puede EXPLAIN-ear sin ejecutar nada).

    Un `GROUP BY r.id` con `count(*)`: sólo se escribe la reserva que tiene UN
    candidato. `min(s.id)` es determinista y, con `total = 1`, el único valor
    posible.
    """
    return f"""
        WITH candidatas AS (
            SELECT r.id AS reserva_id,
                   count(*) AS total,
                   min(s.id) AS suscripcion_id
              FROM {TABLA} r
              JOIN clases c ON c.id = r.clase_id
              JOIN {TABLA_SUSCRIPCIONES} s
                ON s.usuario_id = r.alumno_id
               AND s.tenant_id = r.tenant_id
             WHERE r.{COLUMNA} IS NULL
               AND s.estado NOT IN ({NUNCA_VIGENTES_SQL})
               AND c.fecha BETWEEN s.fecha_inicio::date AND s.fecha_expiracion::date
               AND {sql_imputable()}
             GROUP BY r.id
        )
        UPDATE {TABLA} r
           SET suscripcion_id = k.suscripcion_id
          FROM candidatas k
         WHERE r.id = k.reserva_id
           AND r.{COLUMNA} IS NULL
           AND k.total = 1
    """


def _backfill() -> None:
    """Atribuye sólo las reservas con UN candidato (el resto queda en NULL)."""
    # `LOCAL` = sólo esta transacción, como el `SET TIME ZONE` del job pero sin
    # arrastrar la TZ a la sesión que sigue usando alembic.
    op.execute(f"SET LOCAL TIME ZONE '{TZ_CLT}'")
    op.execute(sql_backfill())


def upgrade() -> None:
    if COLUMNA not in _columnas():
        op.add_column(
            TABLA,
            sa.Column(COLUMNA, sa.Integer(),
                      sa.ForeignKey(f"{TABLA_SUSCRIPCIONES}.id",
                                    ondelete="SET NULL", name=NOMBRE_FK),
                      nullable=True),
        )
        # Sólo se rellena cuando la columna nace acá: en una base de TEST creada
        # con `create_all` no hay historia que reconstruir.
        _backfill()
    if INDICE not in _indices():
        op.create_index(INDICE, TABLA, [COLUMNA])


def downgrade() -> None:
    if INDICE in _indices():
        op.drop_index(INDICE, table_name=TABLA)
    if NOMBRE_FK in _foraneas():
        op.drop_constraint(NOMBRE_FK, TABLA, type_="foreignkey")
    if COLUMNA in _columnas():
        op.drop_column(TABLA, COLUMNA)
