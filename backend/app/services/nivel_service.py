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


def nivel_desde_mejores(mejores, peso_corporal, genero) -> dict:
    """
    Nivel de UN alumno a partir de sus mejores RMs por movimiento. FUNCIÓN PURA (sin DB).

    `mejores` son `(movimiento_id, mejor peso_kg del movimiento, nombre del movimiento)`: el
    `max(peso_kg)` por movimiento, que es la columna donde vive el RM también en gimnasia (ahí
    el valor es la repetición, pero el orden sigue siendo por `peso_kg` — el criterio de siempre).

    Es la ÚNICA definición de "nivel general": la usan el cálculo de a UN alumno
    (`calcular_nivel_general`) y el de TODA la página del coach (`calcular_niveles_lote`), así
    que las dos pantallas no pueden divergir.

    - nivel_fuerza: el nivel más bajo entre todos los movimientos de Grupo A, recalculado con el
      peso_kg y genero ACTUAL del usuario
    - nivel_gimnastico: el nivel más bajo entre todos los movimientos de Grupo B, recalculado en
      vivo
    """
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
                detalle_fuerza.append(
                    {"movimiento": nombre, "movimiento_id": mov_id, "nivel": nivel})
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
                    {"movimiento": nombre, "movimiento_id": mov_id, "nivel": nivel})
            else:
                detalle_gimnastico.append(
                    {"movimiento": nombre, "nivel": "Sin datos"})

    return {
        "nivel_fuerza": nivel_fuerza or "Sin datos",
        "nivel_gimnastico": nivel_gimnastico or "Sin datos",
        "detalle_fuerza": detalle_fuerza,
        "detalle_gimnastico": detalle_gimnastico
    }


def _peso_y_genero(db, alumno_id, tenant_id):
    """`(peso_kg, genero)` ACTUALES del alumno: lo único que el nivel necesita de su perfil."""
    from app.models.usuario import Usuario

    usuario = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == tenant_id
    ).first()
    return (usuario.peso_kg if usuario else None,
            usuario.genero if usuario else None)


def _mejores_rms_lote(db, alumno_ids, tenant_id) -> dict:
    """`{alumno_id: [(movimiento_id, max_peso, nombre), ...]}` en UNA consulta.

    Es el `max(peso_kg)` por movimiento de SIEMPRE (el que usaba `calcular_nivel_general`), pero
    para todo el lote: lo único que cambia es el `IN (...)` y que `alumno_id` viaja y agrupa.
    """
    from app.models.historial_rm import HistorialRM
    from app.models.movimiento import Movimiento
    from sqlalchemy import func

    ids = [int(i) for i in (alumno_ids or []) if i is not None]
    if not ids:
        return {}

    filas = db.query(
        HistorialRM.alumno_id,
        HistorialRM.movimiento_id,
        func.max(HistorialRM.peso_kg).label('max_peso'),
        Movimiento.nombre
    ).filter(
        HistorialRM.alumno_id.in_(ids),
        HistorialRM.tenant_id == tenant_id
    ).join(Movimiento, HistorialRM.movimiento_id == Movimiento.id).group_by(
        HistorialRM.alumno_id, HistorialRM.movimiento_id, Movimiento.nombre
    ).all()

    por_alumno: dict = {}
    for alumno_id, mov_id, max_peso, nombre in filas:
        por_alumno.setdefault(alumno_id, []).append((mov_id, max_peso, nombre))
    return por_alumno


def calcular_nivel_general(alumno_id, db, tenant_id):
    """Calcula el nivel general del alumno EN VIVO (fuerza y gimnástico). Propio o staff."""
    peso_corporal, genero = _peso_y_genero(db, alumno_id, tenant_id)
    return nivel_desde_mejores(
        _mejores_rms_lote(db, [alumno_id], tenant_id).get(alumno_id, []),
        peso_corporal, genero)


def calcular_niveles_lote(db, alumno_ids, tenant_id) -> dict:
    """`calcular_nivel_general` para VARIOS alumnos en DOS consultas (sin N+1).

    Lo usa `GET /historial-rm/progreso-lote`: el tab Progreso del coach enriquece su página
    visible (25 alumnos) con UNA request y 2 consultas, en vez de 2 requests y 2 consultas por
    alumno. El nivel de cada alumno sale del MISMO `nivel_desde_mejores` que el de a uno, así que
    el valor no puede divergir entre la tabla y el endpoint individual.

    Un alumno sin marcas (o sin peso/género) sale igual, con "Sin datos": es un valor del nivel,
    no una ausencia de fila.
    """
    from app.models.usuario import Usuario

    ids = [int(i) for i in (alumno_ids or []) if i is not None]
    if not ids:
        return {}

    # 1) Peso y género de todos (un alumno de otro box / inexistente -> (None, None)).
    personas = {fila[0]: (fila[1], fila[2]) for fila in db.query(
        Usuario.id, Usuario.peso_kg, Usuario.genero
    ).filter(
        Usuario.id.in_(ids), Usuario.tenant_id == tenant_id
    ).all()}
    # 2) Los mejores RMs por movimiento de todos (una sola consulta agregada).
    mejores = _mejores_rms_lote(db, ids, tenant_id)

    return {alumno_id: nivel_desde_mejores(
        mejores.get(alumno_id, []),
        *personas.get(alumno_id, (None, None)),
    ) for alumno_id in ids}
