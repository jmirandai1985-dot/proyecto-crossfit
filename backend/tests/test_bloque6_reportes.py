"""Hallazgos del Bloque 6: datos de prueba fuera de ventas y meses parciales."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def _fuente(rel):
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_pedidos_referencian_producto_y_no_guardan_nombre_texto():
    modelo = _fuente("backend/app/models/pedido.py")
    assert "producto_id = Column(" in modelo
    assert '"productos.id"' in modelo
    assert "producto_nombre" not in modelo.split("class Pedido", 1)[1]


def test_ventas_bazar_excluyen_cuentas_de_prueba_en_todas_las_vistas():
    metricas = _fuente("backend/app/services/metricas_service.py")
    assert "u.es_prueba = true" in metricas.split("def ventas_bazar_detalle", 1)[1]
    service = _fuente("backend/app/services/reportes_service.py")
    assert "AND NOT u.es_prueba" in service
    assert "AND NOT EXISTS (" in service.split("def _pedidos_bazar_pendientes_mes", 1)[1]


def test_churn_filtra_usuarios_reales_y_estados_sin_mrr():
    kpis = _fuente("backend/app/api/v1/kpis.py")
    bloque = kpis.split("consulta = db.query(", 1)[1].split("todas = consulta.all()", 1)[0]
    assert "Usuario.es_prueba.is_(False)" in bloque
    assert "ESTADOS_USUARIO_SIN_MRR" in bloque


def test_historico_marca_mes_parcial_y_bazar_exige_base_de_5_pedidos():
    reportes = _fuente("backend/app/api/v1/reportes.py")
    assert '"parcial": (ini.year, ini.month) == (hoy.year, hoy.month)' in reportes
    assert 'bazar_mes_ant_det["pedidos"] >= 5' in reportes
    front = _fuente("frontend/src/pages/admin/Reportes.jsx")
    assert ".filter((item) => !item.parcial)" in front
    assert "El mes en curso (parcial) no se grafica." in front
