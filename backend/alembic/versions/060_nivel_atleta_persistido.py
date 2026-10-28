"""usuarios: nivel de atleta PERSISTIDO (D3)

Revision ID: 060_nivel_atleta_persistido
Revises: 059_reserva_suscripcion_id
Create Date: 2026-10-28

QUÉ RESUELVE
------------
Hasta hoy el nivel se calculaba EN VIVO en cada request (`nivel_service.calcular_nivel_general`
y `calcular_niveles_lote`) y el frontend derivaba el badge global con `utils/niveles.js` (el
menor de fuerza/gimnasia). Eso dejaba tres problemas:

  * no se puede filtrar/ordenar por nivel en SQL (el coach filtra en el cliente);
  * no hay una fuente única: el badge lo arma el front y el detalle el backend;
  * cada pantalla paga 2 consultas por alumno para un dato que cambia sólo cuando el alumno
    carga un RM o corrige su peso/género.

D3 agrega las columnas que guardan el resultado del MISMO cálculo (no una regla nueva):

  * `nivel_fuerza` / `nivel_gimnastico` — el nivel publicado de cada eje, o NULL si el eje no
    publica (D1: menos de 2 movimientos clasificables, sin peso/género o sin marcas). NULL es
    "sin datos", no "principiante".
  * `nivel_atleta` — el MENOR de los ejes publicados (la regla que antes vivía en el front).
  * `nivel_movs_fuerza` / `nivel_movs_gimnasia` — cuántos movimientos CLASIFICARON en cada eje
    (permite explicar un badge vacío sin recalcular).
  * `nivel_confianza` — alta / media / baja / sin_datos.
  * `nivel_calculado_en` — cuándo se calculó (anti-staleness: > 24 h se recalcula al leer).
  * `nivel_version` — versión de la REGLA (`nivel_service.NIVEL_VERSION`): cuando cambia, las
    filas viejas se recalculan solas sin migración de datos.

Sin `CHECK` de valores, mismo criterio que `026_segmentacion_alumnos`: la escalera puede crecer
sin migración y la validación vive en Python (`nivel_service.NIVELES`).

QUIÉN ESCRIBE ESTAS COLUMNAS
----------------------------
  * `POST /historial-rm` (crear), `PUT` y `DELETE` (hoy no recalculaban nada);
  * `PUT /alumnos/me`, `PUT /usuarios/{id}` y `PUT .../alumno/{id}/perfil` cuando cambian
    `peso_kg` o `genero` (los dos insumos del cálculo);
  * `backend/maintenance/recalcular_niveles.py` (job nocturno idempotente);
  * auto-sanación en lectura (`calcular_nivel_general` / `calcular_niveles_lote`).

Backfill: NO se hace acá. El cálculo importa `nivel_service` (ratios + tablas) y duplicarlo en
SQL garantiza dos verdades. Las filas nacen en NULL y se completan al primer acceso o con el
job nocturno (`DRY_RUN=0`).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "060_nivel_atleta_persistido"
down_revision = "059_reserva_suscripcion_id"
branch_labels = None
depends_on = None

TABLA = "usuarios"
INDICE = "ix_usuarios_tenant_nivel"

COLUMNAS = (
    ("nivel_fuerza", sa.String(20)),
    ("nivel_gimnastico", sa.String(20)),
    ("nivel_atleta", sa.String(20)),
    ("nivel_movs_fuerza", sa.SmallInteger()),
    ("nivel_movs_gimnasia", sa.SmallInteger()),
    ("nivel_confianza", sa.String(10)),
    ("nivel_calculado_en", sa.TIMESTAMP(timezone=True)),
    ("nivel_version", sa.String(10)),
)


def _columnas() -> set:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(TABLA)}


def _indices() -> set:
    return {i["name"] for i in inspect(op.get_bind()).get_indexes(TABLA)}


def upgrade() -> None:
    existentes = _columnas()
    for nombre, tipo in COLUMNAS:
        if nombre not in existentes:
            op.add_column(TABLA, sa.Column(nombre, tipo, nullable=True))
    # Filtro del coach por nivel dentro del box (cuando pase a SQL) y barrido del job.
    if INDICE not in _indices():
        op.create_index(INDICE, TABLA, ["tenant_id", "nivel_atleta"])


def downgrade() -> None:
    if INDICE in _indices():
        op.drop_index(INDICE, table_name=TABLA)
    existentes = _columnas()
    for nombre, _ in COLUMNAS:
        if nombre in existentes:
            op.drop_column(TABLA, nombre)
