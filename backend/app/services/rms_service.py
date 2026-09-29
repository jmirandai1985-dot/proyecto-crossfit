"""Mejor RM por movimiento — FUENTE ÚNICA (servicio).

Antes esta consulta vivía dentro de `GET /historial-rm/alumnos/{id}/rms` y el Historial del
alumno (sección `rms`) necesita el MISMO dato: dos lugares para el mismo cálculo, que con el
tiempo divergen. Ahora la definición está acá y el endpoint delega.

Criterio (el de siempre, sólo cambió de lugar):
  * FUERZA y GIMNÁSTICO → el registro con mayor `peso_kg` del movimiento. En gimnasia el valor
    del RM es la repetición, pero el ORDEN sigue siendo por `peso_kg` (la columna donde el
    RM vive en ambas categorías): cambiarlo alteraría lo que hoy devuelve el endpoint.
  * CARDIO y METABÓLICO (máquinas) → el registro MÁS RECIENTE (desempate `id` desc): comparar
    por `peso_kg` ahí no tiene sentido, es un dummy.

`categoria` (normalizada con el criterio H-03), `unidad` y `valor_mostrado` se derivan acá para
que la UI no repita la tabla de unidades en cada pantalla.
"""
from types import SimpleNamespace
from typing import Final

from sqlalchemy.orm import Session

from app.models.historial_rm import HistorialRM
from app.models.movimiento import Movimiento
from app.services.movimiento_categoria import categoria_de

# Campos que viajan tal cual al schema `RMPorMovimiento` (sin `categoria`/`unidad`/
# `valor_mostrado`, que son de presentación). El endpoint itera esta tupla en vez de escribir
# la lista a mano.
CAMPOS_SCHEMA: Final[tuple] = (
    "id", "movimiento_id", "movimiento_nombre", "peso_kg", "tipo_rm", "valor_extra",
    "repeticiones", "series", "minutos", "vueltas", "km", "calorias", "fecha", "notas",
    "created_at",
)

# Categorías cuyo "mejor" registro se elige por peso (RM de fuerza/gimnasia).
CATEGORIAS_POR_PESO: Final[tuple] = ("fuerza", "gimnastico")
# Categorías cuyo "mejor" registro es el ÚLTIMO (cardio/máquinas: el peso es dummy).
CATEGORIAS_POR_FECHA: Final[tuple] = ("cardio", "metabolico")


def _columnas() -> list:
    """Columnas del SELECT (una sola lista para las dos consultas)."""
    return [
        HistorialRM.id,
        HistorialRM.movimiento_id,
        Movimiento.nombre.label("movimiento_nombre"),
        Movimiento.categoria.label("categoria_bd"),
        HistorialRM.peso_kg,
        HistorialRM.tipo_rm,
        HistorialRM.valor_extra,
        HistorialRM.repeticiones,
        HistorialRM.series,
        HistorialRM.minutos,
        HistorialRM.vueltas,
        HistorialRM.km,
        HistorialRM.calorias,
        HistorialRM.fecha,
        HistorialRM.notas,
        HistorialRM.created_at,
    ]


def _unidad_y_valor(rm: dict) -> tuple:
    """(unidad, valor_mostrado) del registro, según la categoría del movimiento.

    Misma tabla de unidades que usaban los endpoints de niveles: gimnasia mide reps, cardio
    minutos/km/vueltas, máquinas calorías/km/vueltas y fuerza kg.
    """
    cat = rm["categoria"]
    if cat == "gimnastico":
        reps = rm["repeticiones"] if rm["repeticiones"] is not None else rm["peso_kg"]
        return "reps", f"{reps or 0:.0f} reps"
    if cat == "cardio":
        if rm["minutos"]:
            return "min", f"{rm['minutos']} min"
        if rm["km"]:
            return "km", f"{rm['km']} km"
        if rm["vueltas"]:
            return "vueltas", f"{rm['vueltas']} vueltas"
    if cat == "metabolico":
        if rm["calorias"]:
            return "cal", f"{rm['calorias']} cal"
        if rm["km"]:
            return "km", f"{rm['km']} km"
        if rm["vueltas"]:
            return "vueltas", f"{rm['vueltas']} vueltas"
    return "kg", f"{rm['peso_kg']:.0f} kg"


def _fila_a_dict(fila) -> dict:
    """Fila del SELECT → dict con los campos del schema + presentación."""
    rm = {
        "id": fila[0],
        "movimiento_id": fila[1],
        "movimiento_nombre": fila[2],
        # H-03: la categoría de la BD manda; si falta o es un alias, se normaliza y, como
        # último recurso, se deriva del nombre.
        "categoria": categoria_de(SimpleNamespace(categoria=fila[3], nombre=fila[2])),
        "peso_kg": fila[4],
        "tipo_rm": fila[5] or "peso",
        "valor_extra": fila[6],
        "repeticiones": fila[7],
        "series": fila[8],
        "minutos": fila[9],
        "vueltas": fila[10],
        "km": fila[11],
        "calorias": fila[12],
        "fecha": fila[13],
        "notas": fila[14],
        "created_at": fila[15],
    }
    unidad, valor_mostrado = _unidad_y_valor(rm)
    rm["unidad"] = unidad
    rm["valor_mostrado"] = valor_mostrado
    return rm


def mejor_rm_por_movimiento(db: Session, alumno_id: int, tenant_id: int) -> list[dict]:
    """Un registro por movimiento: el MEJOR (fuerza/gimnasia) o el más reciente (cardio/máquinas).

    Orden del resultado: primero los movimientos de fuerza/gimnasia (por `movimiento_id`) y
    después los de cardio/máquinas: es el orden que ya consumía la Pizarra de RMs.
    """
    base = [HistorialRM.alumno_id == alumno_id, HistorialRM.tenant_id == tenant_id]

    por_peso = (
        db.query(*_columnas())
        .join(Movimiento, HistorialRM.movimiento_id == Movimiento.id)
        .filter(*base, Movimiento.categoria.in_(CATEGORIAS_POR_PESO))
        .order_by(HistorialRM.movimiento_id, HistorialRM.peso_kg.desc())
        .distinct(HistorialRM.movimiento_id)
        .all()
    )
    por_fecha = (
        db.query(*_columnas())
        .join(Movimiento, HistorialRM.movimiento_id == Movimiento.id)
        .filter(*base, Movimiento.categoria.in_(CATEGORIAS_POR_FECHA))
        .order_by(HistorialRM.movimiento_id, HistorialRM.fecha.desc(), HistorialRM.id.desc())
        .distinct(HistorialRM.movimiento_id)
        .all()
    )
    return [_fila_a_dict(f) for f in (list(por_peso) + list(por_fecha))]
