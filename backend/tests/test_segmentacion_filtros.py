"""Filtros de usuarios reales en la segmentación (sin BD).

Valida que la consulta que alimenta el reentrenamiento y el resumen del panel
excluya cuentas de prueba y estados sin MRR, sin filtrar a las bajas.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _fuente(rel):
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_features_carga_solo_alumnos_reales_y_sin_estados_sin_mrr():
    texto = _fuente("ml/features.py")
    assert "ESTADOS_USUARIO_SIN_MRR" in texto
    assert "Usuario.es_prueba.is_(False)" in texto
    assert "Usuario.estado.notin_(ESTADOS_USUARIO_SIN_MRR)" in texto
    # Las bajas siguen formando parte del universo de segmentación.
    assert "Usuario.estado == \"activo\"" not in texto.split("def cargar_alumnos", 1)[1].split("def ", 1)[0]


def test_resumen_segmentacion_filtra_por_usuario_real():
    texto = _fuente("app/api/v1/segmentacion.py")
    bloque = texto.split("def resumen_segmentacion", 1)[1]
    assert "join(" in bloque
    assert "Usuario.es_prueba.is_(False)" in bloque
    assert "Usuario.estado.notin_(ESTADOS_USUARIO_SIN_MRR)" in bloque
    assert "Usuario.rol == RolUsuario.alumno" in bloque
