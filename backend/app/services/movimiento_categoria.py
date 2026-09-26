"""Categoría de un movimiento — FUENTE ÚNICA del backend (H-03).

Antes el criterio estaba repartido: `Movimiento.categoria` (BD) en unas consultas,
`movimiento_nombre in CROSSFIT_HABILIDADES / CROSSFIT_RATIOS` en el cálculo de
niveles, y heurísticas por nombre en el frontend (3 implementaciones distintas).

Acá queda el criterio del backend: la categoría de la BD manda; si falta (o trae un
alias), se normaliza y, como último recurso, se deriva del nombre usando las tablas
de niveles. El frontend tiene el mismo criterio en `frontend/src/utils/rm.js`.
"""
CATEGORIAS = ("fuerza", "gimnastico", "cardio", "metabolico")

_ALIAS = {
    "fuerza": "fuerza",
    "gimnastico": "gimnastico",
    "gimnástico": "gimnastico",
    "cardio": "cardio",
    "metabolico": "metabolico",
    "metabólico": "metabolico",
    "maquinas": "metabolico",
    "máquinas": "metabolico",
}


def normalizar_categoria(valor) -> str | None:
    """Normaliza una categoría cruda (BD/API) a una de CATEGORIAS. None si no aplica."""
    if not valor:
        return None
    c = _ALIAS.get(str(valor).strip().lower())
    return c if c in CATEGORIAS else None


def categoria_por_nombre(movimiento_nombre: str) -> str | None:
    """Deriva la categoría del nombre con las tablas de niveles (fallback)."""
    if not movimiento_nombre:
        return None
    from app.db.crossfit_ratios import CROSSFIT_RATIOS
    from app.db.crossfit_habilidades import CROSSFIT_HABILIDADES

    if movimiento_nombre in CROSSFIT_RATIOS:
        return "fuerza"
    if movimiento_nombre in CROSSFIT_HABILIDADES:
        tabla = CROSSFIT_HABILIDADES[movimiento_nombre] or {}
        return normalizar_categoria(tabla.get("categoria")) or "gimnastico"
    return None


def categoria_de(movimiento) -> str:
    """Categoría de un movimiento (objeto con .categoria/.nombre) o de un nombre str.

    Orden: categoría de la BD -> normalización -> heurística por nombre -> 'fuerza'.
    """
    if movimiento is None:
        return "fuerza"
    if isinstance(movimiento, str):
        return categoria_por_nombre(movimiento) or "fuerza"
    de_db = normalizar_categoria(getattr(movimiento, "categoria", None))
    if de_db:
        return de_db
    return categoria_por_nombre(getattr(movimiento, "nombre", None)) or "fuerza"
