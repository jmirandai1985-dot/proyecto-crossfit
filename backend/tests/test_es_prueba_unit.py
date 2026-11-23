"""Filtro de cuentas de prueba en las métricas (unit, SIN base de datos).

Cubre:
- `sql_usuario_real(alias)` devuelve el predicado `NOT alias.es_prueba`.
- `_vigente_sql()` (base de `alumnos_vigentes` y `retencion_cohorte`) incluye el filtro.
- El modelo `Usuario` tiene la columna `es_prueba` NOT NULL default false.
- `mrr()` arma el SQL con JOIN a usuarios y el filtro (fake session; no se conecta).

Correr:
    cd backend
    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_es_prueba_unit.py -q --noconftest
"""
import sys
from datetime import date
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import app.models  # noqa: E402,F401  (registra todos los mappers)
from app.models.usuario import Usuario  # noqa: E402
from app.services import metricas_service as metricas  # noqa: E402
from shared.estados import ESTADOS_USUARIO_SIN_MRR  # noqa: E402


def test_sql_usuario_real_devuelve_el_predicado():
    assert metricas.sql_usuario_real("u") == "NOT u.es_prueba"
    assert metricas.sql_usuario_real("usuarios") == "NOT usuarios.es_prueba"


def test_sql_transaccion_real_resuelve_las_tres_referencias():
    predicado = metricas.sql_transaccion_real("t")
    assert "t.referencia_tipo IS NULL" in predicado
    assert "t.referencia_id IS NULL" in predicado
    assert "suscripciones s" in predicado
    assert "solicitudes_planes sp" in predicado
    assert "sp.alumno_id" in predicado
    assert "pedidos p" in predicado
    assert "p.alumno_id" in predicado
    assert predicado.count("NOT EXISTS") == 3
    assert predicado.count("u.es_prueba = true") == 3


def test_constante_de_estados_excluidos_del_mrr():
    assert ESTADOS_USUARIO_SIN_MRR == ("rechazado",)


def test_vigente_sql_incluye_el_filtro_de_prueba():
    predicado = metricas._vigente_sql(":desde")
    assert "NOT u.es_prueba" in predicado
    assert "u.rol = 'alumno'" in predicado
    assert "u.estado = 'activo'" in predicado


def test_modelo_usuario_tiene_es_prueba():
    columna = Usuario.__table__.c.es_prueba
    assert columna.nullable is False
    assert columna.default is not None
    assert columna.default.arg is False
    assert columna.server_default is not None


class _ResultadoFalso:
    def scalar(self):
        return 0

    def first(self):
        return (0, 0)


class _SesionFalsa:
    """Captura el SQL que la función intenta ejecutar, sin abrir conexión."""

    def __init__(self):
        self.sql = ""
        self.params = {}

    def execute(self, statement, params=None):
        self.sql = str(statement)
        self.params = params or {}
        return _ResultadoFalso()


def test_mrr_arma_sql_solo_con_alumnos_reales():
    db = _SesionFalsa()
    assert metricas.mrr(db, 1, date(2026, 11, 22)) == 0.0
    assert "JOIN usuarios u" in db.sql
    assert "u.rol = 'alumno'" in db.sql
    assert "NOT u.es_prueba" in db.sql
    assert "u.estado NOT IN ('rechazado')" in db.sql
    assert "JOIN planes p" in db.sql


def test_ingresos_netos_filtra_transacciones_de_prueba():
    db = _SesionFalsa()
    metricas.ingresos_netos(db, 1, date(2026, 10, 1), date(2026, 10, 31))
    assert "FROM transacciones_financieras" in db.sql
    assert "NOT EXISTS" in db.sql
    assert "u.es_prueba = true" in db.sql


def test_ventas_bazar_filtra_pedidos_de_prueba():
    db = _SesionFalsa()
    metricas.ventas_bazar_detalle(db, 1, date(2026, 10, 1), date(2026, 10, 31))
    assert "FROM pedidos p" in db.sql
    assert "u.id = p.alumno_id" in db.sql
    assert "u.es_prueba = true" in db.sql
