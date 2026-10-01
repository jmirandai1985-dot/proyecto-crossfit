"""planes: índice único (tenant_id, nombre) — el "si no existe, créalo" pasa a ON CONFLICT

Qué resuelve
------------
`planes` nunca tuvo el índice único por `(tenant_id, nombre)` que el modelo ya declaraba
(`models/plan.py`): en el catálogo de un box pueden convivir dos planes con el mismo nombre. Eso
rompía dos cosas:

  * el "si no existe, créalo" del plan del pase (`beneficios_service._crear_plan_del_pase`). Sin
    índice no se puede usar `ON CONFLICT (tenant_id, nombre)` —Postgres exige un índice único que
    lo respalde—, así que la idempotencia se resolvía con un `SELECT … FOR UPDATE` de la fila del
    box: un lock que serializa TODAS las altas de beneficios del box para cuidar una regla que el
    esquema tendría que garantizar solo;
  * la lectura del plan del pase (`_plan_del_pase_guardado`), que ante duplicados se queda con "la
    primera por id" porque no hay forma de saber cuál es la buena.

Cambios:
  - `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS planes_tenant_nombre ON planes (tenant_id,
    nombre)`.

⚠️ CONCURRENTLY: `planes` está viva en PROD y un `CREATE INDEX` normal bloquea las ESCRITURAS de la
tabla mientras construye (los box no pueden crear/editar planes en ese rato). Con CONCURRENTLY el
build no toma ese lock. No puede correr dentro de una transacción, por eso va en
`autocommit_block()`. Si el build falla a mitad de camino deja un índice INVALIDO (no sirve para
`ON CONFLICT`): se limpia con `DROP INDEX CONCURRENTLY IF EXISTS planes_tenant_nombre` y se
reintenta.

⚠️ Antes de crear el índice la migración VERIFICA que no haya duplicados y, si los hay, ABORTA con
la lista de los nombres repetidos y sin tocar el esquema (ver `_verificar_sin_duplicados`). El
veredicto en TEST el 2026-10-01 (revisión 039_contacto_box) fue 0 duplicados.

Nota: el nombre del índice es el MISMO que declara `models/plan.py` — el seed de TEST y los drills
reconstruyen el esquema con `Base.metadata.create_all()` (`run_setup_test_db.py`) y después hacen
`alembic stamp head`, así que un nombre distinto dejaría dos objetos para la misma regla.

downgrade(): dropea el índice. ⚠️ El código de `beneficios_service` NECESITA este índice para su
`ON CONFLICT`: sin él, dar un pase a un alumno de un box que todavía no tiene plan del pase falla
con "there is no unique or exclusion constraint matching the ON CONFLICT specification". Revertir
sólo el esquema (y no el código) deja la creación del plan del pase rota.

Revision ID: 040_planes_nombre_unico
Revises: 039_contacto_box
Create Date: 2026-10-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "040_planes_nombre_unico"
down_revision: Union[str, None] = "039_contacto_box"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "planes"
INDICE = "planes_tenant_nombre"
COLUMNAS = ("tenant_id", "nombre")

# La consulta del chequeo previo: los (tenant_id, nombre) repetidos, con cuántos hay de cada uno.
CONSULTA_DUPLICADOS = """
SELECT tenant_id, nombre, count(*) AS n
FROM planes
GROUP BY tenant_id, nombre
HAVING count(*) > 1
ORDER BY n DESC, tenant_id, nombre
"""

CREAR = (f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {INDICE} "
         f"ON {TABLA} ({', '.join(COLUMNAS)})")
DROPEAR = f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}"


def _verificar_sin_duplicados() -> None:
    """Aborta (sin tocar el esquema) si hay nombres repetidos dentro de un mismo box.

    `CREATE UNIQUE INDEX` sobre una tabla con duplicados falla a mitad de camino y deja un índice
    INVALIDO, que no sirve para `ON CONFLICT` y que hay que limpiar a mano. Mejor no arrancar.

    En el dry-run (`alembic upgrade … --sql`) no hay base que consultar: se omite el chequeo (el DDL
    que se emite es el mismo; la verificación es del momento de aplicar).
    """
    if op.get_context().as_sql:      # modo offline (`--sql`): no hay conexión que consultar
        return
    duplicados = op.get_bind().execute(sa.text(CONSULTA_DUPLICADOS)).fetchall()
    if not duplicados:
        return
    detalle = "; ".join(f"tenant {t}: «{n}» ×{c}" for t, n, c in duplicados)
    raise RuntimeError(
        f"NO se crea {INDICE}: hay {len(duplicados)} nombre(s) de plan repetido(s) dentro del mismo "
        f"box ({detalle}). Dos planes con el mismo nombre en el mismo box es justo lo que este "
        f"índice prohíbe: renombralos (o fusionalos) y volvé a correr la migración. Consulta:\n"
        f"{CONSULTA_DUPLICADOS.strip()}")


def upgrade() -> None:
    _verificar_sin_duplicados()
    # CONCURRENTLY no puede correr dentro de una transacción: de ahí el bloque autocommit.
    with op.get_context().autocommit_block():
        op.execute(CREAR)


def downgrade() -> None:
    # `DROP INDEX CONCURRENTLY` tampoco puede correr dentro de una transacción.
    with op.get_context().autocommit_block():
        op.execute(DROPEAR)
