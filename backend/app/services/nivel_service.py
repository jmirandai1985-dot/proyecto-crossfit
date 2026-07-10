"""
Servicio de cálculo de nivel de atleta.
Usa las tablas crossfit_ratios.py (fuerza) y crossfit_habilidades.py (gimnástico)
para determinar el nivel de un alumno en cada movimiento.
"""
from app.db.crossfit_ratios import CROSSFIT_RATIOS
from app.db.crossfit_habilidades import CROSSFIT_HABILIDADES

NIVELES = ["Principiante", "Intermedio", "Avanzado", "Elite"]
NIVELES_ORDEN = {n: i for i, n in enumerate(NIVELES)}


def obtener_nivel_fuerza(movimiento_nombre, peso_rm, peso_corporal, genero):
    """
    Calcula el nivel de fuerza para un movimiento.

    Args:
        movimiento_nombre: nombre exacto del movimiento
        peso_rm: peso levantado en kg
        peso_corporal: peso del alumno en kg
        genero: "M" o "F"

    Returns:
        dict con {"aplica": bool, "clasificable": bool, "nivel": str|None, ...}
    """
    if movimiento_nombre not in CROSSFIT_RATIOS:
        return {"aplica": False}

    if not peso_corporal or not genero:
        return {
            "aplica": True,
            "clasificable": False,
            "mensaje": "Completa tu peso corporal y género en tu perfil"
        }

    genero = genero.upper()
    if genero not in ("M", "F"):
        return {
            "aplica": True,
            "clasificable": False,
            "mensaje": "Género no válido. Usa M o F"
        }

    ratio = peso_rm / peso_corporal
    tabla = CROSSFIT_RATIOS[movimiento_nombre]
    niveles = tabla[genero]

    nivel_actual = _encontrar_nivel(ratio, niveles)
    sig_nivel_info = _siguiente_nivel(
        ratio, niveles, tabla["unidad"], peso_corporal)

    return {
        "aplica": True,
        "clasificable": True,
        "nivel": nivel_actual,
        "ratio": round(ratio, 3),
        "siguiente_nivel": sig_nivel_info["nivel"],
        "valor_faltante": sig_nivel_info["faltante"],
        "unidad": tabla["unidad"]
    }


def obtener_nivel_gimnastico(movimiento_nombre, valor, genero=None):
    """
    Calcula el nivel gimnástico para un movimiento.

    Args:
        movimiento_nombre: nombre exacto del movimiento
        valor: reps, metros, o lo que corresponda
        genero: "M" o "F" (si aplica)

    Returns:
        dict con {"aplica": bool, "clasificable": bool, "nivel": str|None, ...}
    """
    if movimiento_nombre not in CROSSFIT_HABILIDADES:
        return {"aplica": False}

    tabla = CROSSFIT_HABILIDADES[movimiento_nombre]
    tipo = tabla["tipo"]

    # Determinar qué tabla usar
    if "M" in tabla and isinstance(tabla["M"], dict) and "Principiante" in tabla["M"]:
        # Tiene género
        if genero and genero.upper() in ("M", "F"):
            niveles = tabla[genero.upper()]
        else:
            # Usar M como default
            niveles = tabla["M"]
    else:
        niveles = tabla

    nivel_actual = _encontrar_nivel(valor, niveles)
    sig_nivel_info = _siguiente_nivel_gimnastico(valor, niveles, tipo)

    return {
        "aplica": True,
        "clasificable": True,
        "nivel": nivel_actual,
        "tipo": tipo,
        "valor": valor,
        "siguiente_nivel": sig_nivel_info["nivel"],
        "valor_faltante": sig_nivel_info["faltante"]
    }


def _encontrar_nivel(valor, niveles):
    """Encuentra el nivel máximo que el valor supera."""
    nivel_actual = NIVELES[0]
    for nivel in NIVELES:
        if valor >= niveles[nivel]:
            nivel_actual = nivel
        else:
            break
    return nivel_actual


def _siguiente_nivel(ratio, niveles, unidad, peso_corporal):
    """Calcula cuánto falta para el siguiente nivel en fuerza."""
    nivel_actual = _encontrar_nivel(ratio, niveles)
    idx = NIVELES_ORDEN.get(nivel_actual, 0)

    if idx >= 3:  # Ya es Elite
        return {"nivel": None, "faltante": None}

    sig_nivel = NIVELES[idx + 1]
    sig_ratio = niveles[sig_nivel]

    if unidad == "ratio":
        peso_necesario = sig_ratio * peso_corporal
        faltante = round(peso_necesario - ratio * peso_corporal, 1)
    else:
        faltante = round(sig_ratio - ratio, 1)

    return {"nivel": sig_nivel, "faltante": faltante}


def _siguiente_nivel_gimnastico(valor, niveles, tipo):
    """Calcula cuánto falta para el siguiente nivel en gimnástico."""
    nivel_actual = _encontrar_nivel(valor, niveles)
    idx = NIVELES_ORDEN.get(nivel_actual, 0)

    if idx >= 3:  # Ya es Elite
        return {"nivel": None, "faltante": None}

    sig_nivel = NIVELES[idx + 1]
    sig_valor = niveles[sig_nivel]
    faltante = max(0, sig_valor - valor)

    return {"nivel": sig_nivel, "faltante": faltante}


def calcular_nivel_general(alumno_id, db, tenant_id):
    """
    Calcula el nivel general del alumno EN VIVO:
    - nivel_fuerza: el nivel más bajo entre todos los movimientos de Grupo A,
      recalculado con el peso_kg y genero ACTUAL del usuario
    - nivel_gimnastico: el nivel más bajo entre todos los movimientos de Grupo B,
      recalculado en vivo
    """
    from app.models.historial_rm import HistorialRM
    from app.models.movimiento import Movimiento
    from app.models.usuario import Usuario
    from sqlalchemy import func

    # 1. Obtener datos actuales del usuario
    usuario = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == tenant_id
    ).first()

    peso_corporal = usuario.peso_kg if usuario else None
    genero = usuario.genero if usuario else None

    # 2. Obtener el mejor RM (mayor peso_kg) por movimiento
    mejores = db.query(
        HistorialRM.movimiento_id,
        func.max(HistorialRM.peso_kg).label('max_peso'),
        Movimiento.nombre
    ).filter(
        HistorialRM.alumno_id == alumno_id,
        HistorialRM.tenant_id == tenant_id
    ).join(Movimiento, HistorialRM.movimiento_id == Movimiento.id).group_by(
        HistorialRM.movimiento_id, Movimiento.nombre
    ).all()

    nivel_fuerza = None
    nivel_gimnastico = None
    detalle_fuerza = []
    detalle_gimnastico = []
    tiene_fuerza = peso_corporal is not None and genero is not None

    for mov_id, max_peso, nombre in mejores:
        if nombre in CROSSFIT_RATIOS:
            # Grupo A - recalcular en vivo
            if tiene_fuerza:
                result = obtener_nivel_fuerza(
                    nombre, max_peso, peso_corporal, genero)
                if result.get("clasificable"):
                    nivel = result["nivel"]
                else:
                    nivel = None
            else:
                nivel = None

            if nivel:
                idx = NIVELES_ORDEN.get(nivel, -1)
                if nivel_fuerza is None or idx < NIVELES_ORDEN.get(nivel_fuerza, 99):
                    nivel_fuerza = nivel
                detalle_fuerza.append({"movimiento": nombre, "nivel": nivel})
            else:
                detalle_fuerza.append(
                    {"movimiento": nombre, "nivel": "Sin datos"})

        elif nombre in CROSSFIT_HABILIDADES:
            # Grupo B - recalcular en vivo
            result = obtener_nivel_gimnastico(nombre, max_peso, genero)
            if result.get("clasificable"):
                nivel = result["nivel"]
            else:
                nivel = None

            if nivel:
                idx = NIVELES_ORDEN.get(nivel, -1)
                if nivel_gimnastico is None or idx < NIVELES_ORDEN.get(nivel_gimnastico, 99):
                    nivel_gimnastico = nivel
                detalle_gimnastico.append(
                    {"movimiento": nombre, "nivel": nivel})
            else:
                detalle_gimnastico.append(
                    {"movimiento": nombre, "nivel": "Sin datos"})

    return {
        "nivel_fuerza": nivel_fuerza or "Sin datos",
        "nivel_gimnastico": nivel_gimnastico or "Sin datos",
        "detalle_fuerza": detalle_fuerza,
        "detalle_gimnastico": detalle_gimnastico
    }
