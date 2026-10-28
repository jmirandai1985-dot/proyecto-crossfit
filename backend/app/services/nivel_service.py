"""
Servicio de cálculo de nivel de atleta.
Usa las tablas crossfit_ratios.py (fuerza) y crossfit_habilidades.py (gimnástico)
para determinar el nivel de un alumno en cada movimiento.
"""
import os
from datetime import datetime, timedelta, timezone

from app.db.crossfit_ratios import CROSSFIT_RATIOS
from app.db.crossfit_habilidades import CROSSFIT_HABILIDADES

NIVELES = ["Principiante", "Intermedio", "Avanzado", "Elite"]

# D1 (decisión de negocio 2026-10-28): un eje NO publica nivel con una sola marca.
# El mínimo de muestra por eje es 2 movimientos clasificables; con menos, el eje queda
# "Sin datos" aunque haya 1 marca (era lo que producía los falsos "Elite": la alumna 9
# tenía 2 marcas de fuerza, 0 de gimnasia, y su badge global salía Elite).
# Configurable por entorno para poder bajarlo a 1 sin tocar código si el box lo pide.
NIVEL_MIN_MOVS_EJE = int(os.getenv("NIVEL_MIN_MOVS_EJE", "2"))

# D3 (2026-10-28): versión de la REGLA de cálculo. Cambiarla invalida las filas persistidas
# (todas se recalculan en el siguiente acceso o en el job nocturno) sin migración de datos.
#   d3-v1 = D1 (>=2 movimientos por eje) + gimnasia por repeticiones (D4) + estándares D5.
NIVEL_VERSION = "d3-v1"
# Anti-staleness: una fila con más de 24 h se recalcula al leer (auto-sanación) y el job
# nocturno la repasa igual. Así un cambio de ratios o un job caído no mienten para siempre.
NIVEL_STALENESS_HORAS = 24
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


def nivel_desde_mejores(mejores, peso_corporal, genero, min_movs_eje=None) -> dict:
    """
    Nivel de UN alumno a partir de sus mejores RMs por movimiento. FUNCIÓN PURA (sin DB).

    `mejores` son `(movimiento_id, mejor peso_kg del movimiento, nombre del movimiento)`: el
    `max(peso_kg)` por movimiento, que es la columna donde vive el RM también en gimnasia (ahí
    el valor es la repetición, pero el orden sigue siendo por `peso_kg` — el criterio de siempre).

    Es la ÚNICA definición de "nivel general": la usan el cálculo de a UN alumno
    (`calcular_nivel_general`) y el de TODA la página del coach (`calcular_niveles_lote`), así
    que las dos pantallas no pueden divergir.

    D1 (2026-10-28): cada eje publica nivel solo si tiene `min_movs_eje` movimientos
    clasificables (default 2). Con menos, el eje devuelve "Sin datos" aunque haya 1 marca.
    `nivel_atleta` es el minimo de los ejes publicados y `nivel_confianza` resume cuanta
    evidencia hay (alta/media/baja/sin_datos).

    - nivel_fuerza: el nivel más bajo entre todos los movimientos de Grupo A, recalculado con el
      peso_kg y genero ACTUAL del usuario
    - nivel_gimnastico: el nivel más bajo entre todos los movimientos de Grupo B, recalculado en
      vivo
    """
    nivel_fuerza = None
    nivel_gimnastico = None
    # D1: cuántos movimientos CLASIFICARON en cada eje (no cuántos hay). El eje publica
    # nivel solo si llega a `min_movs_eje`; si no, queda "Sin datos" aunque haya una marca.
    movs_fuerza = 0
    movs_gimnasia = 0
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
                movs_fuerza += 1
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
                movs_gimnasia += 1
                idx = NIVELES_ORDEN.get(nivel, -1)
                if nivel_gimnastico is None or idx < NIVELES_ORDEN.get(nivel_gimnastico, 99):
                    nivel_gimnastico = nivel
                detalle_gimnastico.append(
                    {"movimiento": nombre, "movimiento_id": mov_id, "nivel": nivel})
            else:
                detalle_gimnastico.append(
                    {"movimiento": nombre, "nivel": "Sin datos"})

    # D1: publicar el eje exige `min_movs_eje` movimientos clasificables. Con menos, el eje
    # queda "Sin datos" (no se publica un nivel sostenido por una sola marca).
    minimo = NIVEL_MIN_MOVS_EJE if min_movs_eje is None else max(1, int(min_movs_eje))
    publica_fuerza = movs_fuerza >= minimo
    publica_gimnasia = movs_gimnasia >= minimo
    nivel_fuerza = nivel_fuerza if publica_fuerza else None
    nivel_gimnastico = nivel_gimnastico if publica_gimnasia else None

    # Badge global (D3): MISMA regla que el front tenía en `utils/niveles.js` — el MENOR de
    # los ejes publicados. Se calcula en el backend para que el front lo LEA de la columna
    # `usuarios.nivel_atleta` en vez de volver a derivarlo.
    publicados = [n for n in (nivel_fuerza, nivel_gimnastico) if n]
    nivel_atleta = (min(publicados, key=lambda n: NIVELES_ORDEN.get(n, 99))
                    if publicados else None)

    # Confianza de la clasificación: alta = los dos ejes publican; media = los dos ejes
    # tienen alguna marca clasificable pero a alguno le falta muestra; baja = un solo eje
    # con evidencia; sin_datos = ninguna marca clasificable.
    if publica_fuerza and publica_gimnasia:
        confianza = "alta"
    elif movs_fuerza >= 1 and movs_gimnasia >= 1:
        confianza = "media"
    elif movs_fuerza or movs_gimnasia:
        confianza = "baja"
    else:
        confianza = "sin_datos"

    return {
        "nivel_fuerza": nivel_fuerza or "Sin datos",
        "nivel_gimnastico": nivel_gimnastico or "Sin datos",
        "nivel_atleta": nivel_atleta or "Sin datos",
        "movs_fuerza": movs_fuerza,
        "movs_gimnasia": movs_gimnasia,
        "min_movs_eje": minimo,
        "nivel_confianza": confianza,
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


# ── D3: persistencia del nivel en `usuarios` ───────────────────────────────────
# Regla de oro: la ÚNICA definición del nivel sigue siendo `nivel_desde_mejores`. Estas
# funciones solo guardan/leen su resultado; nunca calculan distinto.

def _usuario_nivel(db, alumno_id, tenant_id):
    """Fila de `usuarios` del alumno (para leer/escribir las columnas de nivel)."""
    from app.models.usuario import Usuario

    return db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == tenant_id,
    ).first()


def _columnas_desde_nivel(resultado) -> dict:
    """Resultado puro -> columnas de `usuarios`. 'Sin datos' se guarda como NULL."""
    def valor(clave):
        v = resultado.get(clave)
        return None if v in (None, "Sin datos") else v

    return {
        "nivel_fuerza": valor("nivel_fuerza"),
        "nivel_gimnastico": valor("nivel_gimnastico"),
        "nivel_atleta": valor("nivel_atleta"),
        "nivel_movs_fuerza": resultado.get("movs_fuerza", 0),
        "nivel_movs_gimnasia": resultado.get("movs_gimnasia", 0),
        "nivel_confianza": resultado.get("nivel_confianza", "sin_datos"),
        "nivel_calculado_en": datetime.now(timezone.utc),
        "nivel_version": NIVEL_VERSION,
    }


def _nivel_desde_columnas(usuario) -> dict:
    """Columnas de `usuarios` -> MISMO contrato que `nivel_desde_mejores`, sin detalle.

    El detalle (qué nivel dio cada movimiento) no se persiste: lo piden solo los endpoints
    individuales de nivel, que calculan en vivo con `calcular_nivel_general`.
    """
    return {
        "nivel_fuerza": usuario.nivel_fuerza or "Sin datos",
        "nivel_gimnastico": usuario.nivel_gimnastico or "Sin datos",
        "nivel_atleta": usuario.nivel_atleta or "Sin datos",
        "movs_fuerza": usuario.nivel_movs_fuerza or 0,
        "movs_gimnasia": usuario.nivel_movs_gimnasia or 0,
        "min_movs_eje": NIVEL_MIN_MOVS_EJE,
        "nivel_confianza": usuario.nivel_confianza or "sin_datos",
        "detalle_fuerza": [],
        "detalle_gimnastico": [],
    }


def nivel_esta_vigente(usuario) -> bool:
    """¿La fila persistida se puede usar sin recalcular? (versión + antigüedad)."""
    if usuario is None or usuario.nivel_calculado_en is None:
        return False
    if (usuario.nivel_version or "") != NIVEL_VERSION:
        return False
    calculado = usuario.nivel_calculado_en
    if calculado.tzinfo is None:            # TIMESTAMP sin TZ (BD de TEST vieja)
        calculado = calculado.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - calculado) < timedelta(hours=NIVEL_STALENESS_HORAS)


def _guardar_nivel(usuario, resultado) -> None:
    for campo, valor in _columnas_desde_nivel(resultado).items():
        setattr(usuario, campo, valor)


def recalcular_nivel(db, alumno_id, tenant_id, commit=True) -> dict:
    """Recalcula y PERSISTE el nivel de un alumno (D3). Es el único camino de escritura.

    Se llama tras cualquier cambio que pueda mover el resultado: crear/editar/borrar un RM,
    cambiar peso o género, el job nocturno. Nunca hace cálculo incremental: relee los mejores
    RMs y el perfil actual, y aplica `nivel_desde_mejores` (la función pura).
    """
    usuario = _usuario_nivel(db, alumno_id, tenant_id)
    resultado = nivel_desde_mejores(
        _mejores_rms_lote(db, [alumno_id], tenant_id).get(alumno_id, []),
        usuario.peso_kg if usuario else None,
        usuario.genero if usuario else None,
    )
    if usuario is not None:
        _guardar_nivel(usuario, resultado)
        if commit:
            db.commit()
    return resultado


def calcular_nivel_general(alumno_id, db, tenant_id):
    """Calcula el nivel general del alumno EN VIVO (fuerza y gimnástico). Propio o staff.

    Devuelve el detalle por movimiento, que usan los endpoints de nivel de fuerza/gimnasia,
    así que el cálculo es en vivo. Además REFRESCA las columnas persistidas si están vencidas
    (24 h, versión distinta o NULL): un GET no escribe en cada request, solo cuando toca.
    """
    usuario = _usuario_nivel(db, alumno_id, tenant_id)
    resultado = nivel_desde_mejores(
        _mejores_rms_lote(db, [alumno_id], tenant_id).get(alumno_id, []),
        usuario.peso_kg if usuario else None,
        usuario.genero if usuario else None,
    )
    if usuario is not None and not nivel_esta_vigente(usuario):
        _guardar_nivel(usuario, resultado)
        db.commit()
    return resultado


def calcular_niveles_lote(db, alumno_ids, tenant_id) -> dict:
    """`calcular_nivel_general` para VARIOS alumnos, leyendo lo PERSISTIDO (D3).

    Lo usa `GET /historial-rm/progreso-lote`: el tab Progreso del coach enriquece su página
    visible (25 alumnos) con UNA request. Antes eran 2 consultas por alumno; ahora, para las
    filas vigentes, es UNA consulta (la de `usuarios`) y ninguna de RMs.

    Las filas vencidas (sin calcular, versión vieja o con más de 24 h) se recalculan con
    `nivel_desde_mejores` —la MISMA función del cálculo individual— y se persisten en la misma
    transacción; así la tabla y el endpoint de a uno no pueden divergir.

    Un alumno sin marcas (o sin peso/género) sale igual, con "Sin datos": es un valor del nivel,
    no una ausencia de fila.
    """
    from app.models.usuario import Usuario

    ids = [int(i) for i in (alumno_ids or []) if i is not None]
    if not ids:
        return {}

    personas = {fila.id: fila for fila in db.query(Usuario).filter(
        Usuario.id.in_(ids), Usuario.tenant_id == tenant_id
    ).all()}

    resultados: dict = {}
    pendientes = []
    for alumno_id in ids:
        usuario = personas.get(alumno_id)
        if usuario is not None and nivel_esta_vigente(usuario):
            resultados[alumno_id] = _nivel_desde_columnas(usuario)
        else:
            pendientes.append(alumno_id)

    if pendientes:
        # Los mejores RMs por movimiento de los que hay que recalcular (una sola consulta).
        mejores = _mejores_rms_lote(db, pendientes, tenant_id)
        for alumno_id in pendientes:
            usuario = personas.get(alumno_id)
            resultado = nivel_desde_mejores(
                mejores.get(alumno_id, []),
                usuario.peso_kg if usuario else None,
                usuario.genero if usuario else None,
            )
            resultados[alumno_id] = resultado
            if usuario is not None:
                _guardar_nivel(usuario, resultado)
        db.commit()

    return resultados
