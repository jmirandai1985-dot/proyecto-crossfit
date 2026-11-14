"""suscripciones: UNA sola fila `pendiente` por (alumno, plan)

Revision ID: 082_suscripcion_pendiente_unica
Revises: 081_wod_resultados
Create Date: 2026-11-14

QUÉ RESUELVE
-----------
`POST /pagos/suscripcion` (`services/suscripciones_mp.crear_suscripcion_mp`)
busca una suscripción previa del alumno+plan con `mp_preapproval_id` guardado y,
si no la encuentra, INSERTA la fila `pendiente` y recién DESPUÉS llama a Mercado
Pago para crear el `preapproval` (el `external_reference` necesita el id de la
fila). Entre ese INSERT y el UPDATE que guarda el id de MP hay una llamada HTTP
real, así que varias solicitudes casi simultáneas del MISMO alumno+plan (doble
clic, dos pestañas, reintento de red) pasan la búsqueda a la vez y cada una crea
su fila `pendiente` + su `preapproval`: dos cobros recurrentes del mismo plan.
Lo encontró el test de carga `k6-tests/scenario_g9_pago_mercadopago.js`.

  * Índice ÚNICO **PARCIAL** `uq_suscripciones_pendiente_por_alumno_plan` sobre
    (usuario_id, plan_id) `WHERE estado = 'pendiente'`.
    Parcial a propósito: el histórico (`activo`, `vencido`, `inactiva`) no
    entra, así el alumno puede volver a comprar el mismo plan cuando el
    anterior termina. La serialización la hace Postgres: la segunda solicitud
    choca ANTES de llamar a Mercado Pago, y el servicio la traduce a un 409
    claro (`es_suscripcion_pendiente_duplicada`, `app/models/suscripcion.py`).
    El modelo declara el MISMO índice para que el `create_all()` de TEST y esta
    migración no dejen objetos distintos para la misma regla.

NO se usa un advisory lock: la función hace varios `commit()` seguidos y el
lock de sesión se perdería si SQLAlchemy toma otra conexión física del pool
entre un commit y el siguiente. La regla vive en la BD, que es la única capa
que no se puede saltar (un script, n8n o un endpoint nuevo).

Antes de aplicar
----------------
Si la base ya tiene filas `pendiente` duplicadas por (alumno, plan) —datos que
deja el propio test de carga— el `CREATE UNIQUE INDEX` fallaría. El upgrade NO
borra ni cambia datos solo: aborta con un mensaje que lista los pares
duplicados para que la limpieza sea una decisión explícita.

downgrade(): borra el índice. No se toca ninguna fila.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "082_suscripcion_pendiente_unica"
down_revision: Union[str, None] = "081_wod_resultados"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "suscripciones"
INDICE = "uq_suscripciones_pendiente_por_alumno_plan"
PREDICADO = "estado = 'pendiente'"


def _existe_tabla() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def _indice_existe(nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(i["name"] == nombre for i in inspector.get_indexes(TABLA))


def _duplicados_pendientes():
    """Pares (usuario_id, plan_id) con más de una fila `pendiente` (read-only)."""
    return op.get_bind().execute(sa.text(f"""
        SELECT usuario_id, plan_id, COUNT(*) AS cuantas,
               array_agg(id ORDER BY id) AS ids
        FROM {TABLA}
        WHERE {PREDICADO}
        GROUP BY usuario_id, plan_id
        HAVING COUNT(*) > 1
        ORDER BY usuario_id, plan_id
    """)).all()


def upgrade() -> None:
    # Idempotente: una base de TEST creada con `Base.metadata.create_all()` ya
    # trae el índice del modelo (mismo nombre, misma regla).
    if not _existe_tabla() or _indice_existe(INDICE):
        return

    duplicados = _duplicados_pendientes()
    if duplicados:
        detalle = "; ".join(
            f"usuario_id={fila.usuario_id}, plan_id={fila.plan_id}, "
            f"ids={list(fila.ids)}"
            for fila in duplicados)
        raise RuntimeError(
            f"No se puede crear {INDICE}: hay suscripciones 'pendiente' "
            f"duplicadas por (alumno, plan): {detalle}. Limpia o cambia de "
            "estado esas filas y vuelve a correr la migración.")

    op.create_index(INDICE, TABLA, ["usuario_id", "plan_id"],
                    unique=True, postgresql_where=sa.text(PREDICADO))


def downgrade() -> None:
    if not _existe_tabla():
        return
    if _indice_existe(INDICE):
        op.drop_index(INDICE, table_name=TABLA)
