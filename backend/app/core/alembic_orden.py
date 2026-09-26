"""Compara dos revisiones de Alembic usando el grafo de migraciones.

Existe para el guardrail de `scripts/sync_test_from_prod.py`: TEST y PROD pueden
estar en revisiones distintas y NO todas las diferencias son un problema.

Reglas (decididas 2026-09-26):
  * TEST == PROD                         -> "igual"     (seguir)
  * TEST ADELANTE de PROD (PROD es
    ancestro de TEST)                    -> "adelante"  (WARNING y seguir: es el
                                                         flujo normal mientras se
                                                         desarrolla una migración)
  * TEST ATRÁS de PROD                   -> "atras"     (abortar: faltan migraciones)
  * ramas distintas / revisión ilegible  -> "distintas" (abortar)

Es una función PURA sobre el `script_dir` (duck-typed: sólo necesita
`get_revision(id)` devolviendo algo con `.down_revision`), así que se puede
testear sin base de datos y sin Alembic.
"""
from __future__ import annotations

from typing import Tuple


def _ancestros(script_dir, revision: str) -> set:
    """Revisiones alcanzables bajando por `down_revision` (incluye la propia).

    Soporta merges: `down_revision` puede ser tupla.
    """
    vistos: set = set()
    pila = [revision]
    while pila:
        rev = pila.pop()
        if not rev or rev in vistos:
            continue
        vistos.add(rev)
        script = script_dir.get_revision(rev)
        if script is None:
            continue
        down = getattr(script, "down_revision", None)
        if isinstance(down, (tuple, list)):
            pila.extend(down)
        elif down:
            pila.append(down)
    return vistos


def comparar_revisiones(script_dir, ver_test: str, ver_prod: str) -> Tuple[str, str]:
    """Devuelve (estado, detalle) con estado en {igual, adelante, atras, distintas}."""
    if ver_test and ver_prod and ver_test == ver_prod:
        return "igual", f"ambas en {ver_test}"

    try:
        rev_test = script_dir.get_revision(ver_test) if ver_test else None
        rev_prod = script_dir.get_revision(ver_prod) if ver_prod else None
    except Exception as e:  # noqa: BLE001
        return "distintas", f"no se pudo leer una revisión ({type(e).__name__})"

    if rev_test is None or rev_prod is None:
        faltan = [n for n, r in (("TEST", rev_test), ("PROD", rev_prod)) if r is None]
        return "distintas", f"revisión inexistente en el script directory ({', '.join(faltan)})"

    if ver_prod in _ancestros(script_dir, ver_test):
        return "adelante", f"PROD ({ver_prod}) es ancestro de TEST ({ver_test})"

    if ver_test in _ancestros(script_dir, ver_prod):
        return "atras", f"TEST ({ver_test}) es ancestro de PROD ({ver_prod})"

    return "distintas", "las revisiones no están en la misma cadena (ramas distintas)"
