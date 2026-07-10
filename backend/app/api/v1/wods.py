"""
Router de endpoints para gestión de WODs (Workout of the Day)
"""
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db.database import get_db
from app.models.wod import Wod, EstadoWod
from app.models.wod_movimiento import WodMovimiento
from app.models.movimiento import Movimiento
from app.models.clase import Clase
from app.schemas import wod as schemas
from app.schemas.wod_parse import WodParseRequest, WodParseResponse, MovimientoParseado, DebugInfo, FaseInfo, FaseMovimiento
from datetime import date

router = APIRouter(prefix="/api/v1/wods", tags=["wods"])


# ──────────────────────────────────────────────
# PARSER DE TEXTO PARA WOD (v2 - más flexible)
# ──────────────────────────────────────────────

# Regex FLEXIBLE para múltiples formatos:
#   "Clean 5x3"                      → nombre="Clean", series=5, reps="3"
#   "Clean (Cargada) 5x3 @ 75%"      → nombre="Clean (Cargada)", series=5, reps="3", peso=75
#   "Push Press 3x5"                 → nombre="Push Press", series=3, reps="5"
#   "5 Clean"                        → nombre="Clean", series=5, reps=None  (solo series)
#   "10 cal Air Bike"                → nombre="Air Bike", reps="10 cal"    (solo reps, sin x)
#
# Estructura: todo hasta el primer número que no está entre paréntesis
# Luego: opcional "x" + reps, opcional "@" + peso%
PATRON_MOVIMIENTO = re.compile(
    # Grupo 1: nombre (non-greedy hasta espacios)
    r'^(.+?)\s+'
    r'(\d+)\s*'                         # Grupo 2: series (dígitos)
    # Grupo 3: opcional "x" + reps (ej: "3", "10-12", "AMRAP")
    r'(?:x\s*([\w\-\s\/]+?))?'
    r'(?:\s*@\s*(\d+(?:\.\d+)?)\s*%)?'  # Grupo 4: opcional "@ XX%"
    r'\s*$',
    re.IGNORECASE
)

# Segundo patrón: solo "5 Clean" (series como primer número, sin x)
PATRON_SOLO_SERIES = re.compile(
    r'^(\d+)\s+(.+?)\s*$',  # número seguido de nombre, sin x
    re.IGNORECASE
)

# Patrón: "10 cal Air Bike", "500m Row" - cantidad + unidad + nombre
PATRON_CANTIDAD_UNIDAD = re.compile(
    r'^(\d+)\s*(cal|m|km|round|rep|min|seg)\s+(.+?)\s*$',
    re.IGNORECASE
)

# Patrones para detectar líneas que NO son movimientos (descripciones)
PATRONES_DESCRIPCION = re.compile(
    r'^\s*(\d+\s*(min|minutes|rounds|rondas|rft|emom|amrap|for time|por tiempo|for distance))',
    re.IGNORECASE
)

# Palabras clave que indican que es una descripción, no un movimiento
PALABRAS_DESCRIPCION = [
    "rounds", "rondas", "amrap", "emom", "rft", "for time", "por tiempo",
    "for distance", "then", "luego", "descanso", "rest", "notas", "nota:"
]


def tiene_numeros(texto: str) -> bool:
    """Retorna True si el texto contiene al menos un dígito."""
    return bool(re.search(r'\d', texto))


def es_encabezado(texto: str) -> bool:
    """
    Detecta si una línea es un encabezado (todo mayúsculas sin números).
    Ej: "CALENTAMIENTO", "FUERZA", "WOD", "MOBILITY"
    """
    return (texto.isupper() and len(texto) <= 30 and not tiene_numeros(texto))


def parsear_linea_movimiento(linea: str):
    """
    Analiza una línea de texto y extrae nombre_movimiento, series, reps, peso.
    Soporta:
      - "Clean 5x3"                → series=5, reps="3"
      - "Push Press 3x5 @ 80%"     → series=3, reps="5", peso=80
      - "Clean (Cargada) 5x3"      → series=5, reps="3"  (nombre con paréntesis)
      - "5 Clean"                  → series=5, reps=None
      - "10 cal Air Bike"          → nombre="Air Bike", reps="10 cal"
      - "CALENTAMIENTO"            → None (encabezado)
      - "Pull-ups"                 → nombre="Pull-ups", series=None, reps=None
      - "10 Pull-ups"              → nombre="Pull-ups", series=None, reps="10"
      - "15 Box Jumps"             → nombre="Box Jumps", series=None, reps="15"
      - "5 Clean (Cargada)"        → nombre="Clean (Cargada)", series=5
    Retorna None si la línea es descripción o encabezado.
    """
    linea = linea.strip()
    if not linea:
        return None

    # Detectar ENCABEZADOS (solo letras mayúsculas, sin números)
    if es_encabezado(linea):
        return {"tipo": "encabezado", "nombre": linea}

    # Detectar palabras clave de descripción
    linea_lower = linea.lower()
    for palabra in PALABRAS_DESCRIPCION:
        if linea_lower.startswith(palabra):
            return {"tipo": "descripcion", "nombre": linea}

    # Saltar líneas de descripción (AMRAP, EMOM, etc.)
    if PATRONES_DESCRIPCION.search(linea):
        return {"tipo": "descripcion", "nombre": linea}

    # 1. Intentar "10 cal Air Bike" (cantidad + unidad + nombre)
    match3 = PATRON_CANTIDAD_UNIDAD.match(linea)
    if match3:
        cantidad = int(match3.group(1))
        unidad = match3.group(2).strip()
        nombre = match3.group(3).strip()
        if tiene_numeros(nombre):
            return None  # Si el "nombre" aún tiene números, no es válido
        return {
            "tipo": "movimiento",
            "nombre": nombre,
            "series": None,
            "repeticiones": f"{cantidad} {unidad}",
            "peso": None
        }

    # 2. Intentar patrón principal: "Nombre XxY @ Z%"
    #    Nota: el % se captura en grupo 4, pero NO se guarda el simbolo.
    #    Si el texto original tenia "@ 80%", es porcentaje de 1RM, no kg.
    #    En ese caso, guardamos en notas "Peso: 80%" y peso=None.
    match = PATRON_MOVIMIENTO.match(linea)
    if match:
        nombre = match.group(1).strip()
        series = int(match.group(2))
        repeticiones = match.group(3)
        peso_raw = match.group(4)

        if repeticiones:
            repeticiones = repeticiones.strip()
        else:
            repeticiones = None

        # Detectar si era % (porcentaje) mirando la línea original
        peso = None
        notas_porcentaje = None
        if peso_raw:
            # Verificar si la línea ORIGINAL tenía "%" después del número
            # El regex ya validó que el patrón es @ X%, pero solo capturó el número
            if '%' in linea:
                # Es un porcentaje - NO guardar en peso, guardar en notas
                notas_porcentaje = f"Peso: {peso_raw}%"
            else:
                peso = float(peso_raw)

        return {
            "tipo": "movimiento",
            "nombre": nombre,
            "series": series,
            "repeticiones": repeticiones,
            "peso": peso,
            "notas": notas_porcentaje
        }

    # 3. Intentar "5 Clean" (solo series, sin reps) - PERO con paréntesis
    #    También captura "5 Clean (Cargada)" → nombre="Clean (Cargada)", series=5
    match2 = PATRON_SOLO_SERIES.match(linea)
    if match2:
        segundo = match2.group(2).strip().lower()
        if not any(segundo.startswith(p) for p in ["min", "round", "rest", "descanso"]):
            nombre = match2.group(2).strip()
            # Verificar que el nombre sea válido (tenga letras)
            if re.search(r'[a-zA-Z]', nombre):
                series = int(match2.group(1))
                return {
                    "tipo": "movimiento",
                    "nombre": nombre,
                    "series": series,
                    "repeticiones": None,
                    "peso": None
                }

    # 4. Intentar NOMBRE SOLO (sin números, sin series, sin reps)
    #    Ej: "Pull-ups", "Box Jumps", "Handstand Push-ups"
    #    Solo letras, espacios, paréntesis, guiones
    match_nombre_solo = re.match(
        r'^([a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ\s\-\/\(\)]+)$', linea)
    if match_nombre_solo:
        nombre = match_nombre_solo.group(1).strip()
        # Ignorar si es muy corto o es palabra genérica
        if len(nombre) >= 3 and not es_encabezado(nombre):
            return {
                "tipo": "movimiento",
                "nombre": nombre,
                "series": None,
                "repeticiones": None,
                "peso": None
            }

    # 5. Intentar "10 nombre" (solo reps, sin series)
    #    Ej: "10 Pull-ups" → nombre=Pull-ups, reps="10"
    #    pero NO si podría ser "10 cal" (ya capturado arriba)
    match_reps_solo = re.match(r'^(\d+)\s+(.+)$', linea)
    if match_reps_solo:
        cantidad = int(match_reps_solo.group(1))
        nombre = match_reps_solo.group(2).strip()
        # Verificar que el nombre sea válido (tenga letras y no sea palabra de descripción)
        if re.search(r'[a-zA-Z]', nombre):
            nombre_lower = nombre.lower()
            if not any(nombre_lower.startswith(p) for p in ["min", "round", "rest", "descanso", "cal", "m ", "km"]):
                return {
                    "tipo": "movimiento",
                    "nombre": nombre,
                    "series": None,
                    "repeticiones": str(cantidad),
                    "peso": None
                }

    # No coincide con ningún patrón conocido
    return None


# Diccionario de sinónimos/variantes para matching mejorado
SINONIMOS_MOVIMIENTOS = {
    "run": ["Remo", "Row", "Rowing Machine", "Correr", "Running"],
    "row": ["Remo", "Rowing Machine", "Run"],
    "remo": ["Row", "Rowing Machine", "Run"],
    "air bike": ["Air Bike", "Bike", "Bicicleta", "Assault Bike"],
    "bike": ["Air Bike", "Assault Bike", "Bicicleta"],
    "bicicleta": ["Air Bike", "Assault Bike", "Bike"],
    "ski": ["Ski Erg", "SkiErg"],
    "skierg": ["Ski Erg", "SkiErg"],
    "du": ["Double Unders", "Double Under", "DU"],
    "double under": ["Double Unders", "Double Under", "DU"],
    "su": ["Single Unders", "Single Under", "SU"],
    "muscle up": ["Bar Muscle-up", "Muscle-up", "Ring Muscle-up"],
    "hspu": ["Handstand Push-ups", "Handstand Push-up", "HSPU"],
    "handstand push": ["Handstand Push-ups", "HSPU"],
    "t2b": ["Toes to Bar", "T2B"],
    "toes to bar": ["Toes to Bar", "T2B"],
    "c2b": ["Chest to Bar", "C2B"],
    "chest to bar": ["Chest to Bar", "C2B"],
    "bmu": ["Bar Muscle-up", "BMU"],
    "rmu": ["Ring Muscle-up", "RMU"],
    "pull up": ["Pull-ups", "Pull-up", "Pull Ups"],
    "push up": ["Push-ups", "Push-up", "Push Ups"],
    "burpee": ["Burpees", "Burpee"],
    "wall ball": ["Wall Balls", "Wall Ball"],
    "box jump": ["Box Jumps", "Box Jump", "Box Jump Over"],
    "deadlift": ["Deadlift", "Deadlift (Peso Muerto)"],
    "dl": ["Deadlift", "Deadlift (Peso Muerto)"],
    "clean": ["Clean", "Clean (Cargada)"],
    "snatch": ["Snatch", "Snatch (Arrancada)"],
    "squat": ["Back Squat", "Front Squat", "Overhead Squat", "Air Squat"],
    "press": ["Push Press", "Press", "Shoulder Press", "Strict Press"],
    "thruster": ["Thruster"],
    "kb swing": ["Kettlebell Swing", "Kettlebell"],
    "kettlebell": ["Kettlebell Swing"],
}


def buscar_variante_movimiento(db: Session, nombre_buscado: str, tenant_id: int):
    """
    Si no encuentra el nombre exacto, prueba variantes/sinónimos.
    Ej: "run" → busca "Remo", "Row", "Rowing Machine"
    Retorna (Movimiento | None, variante_encontrada | None).
    """
    nombre_lower = nombre_buscado.strip().lower()

    # Buscar en diccionario de sinónimos
    for clave, variantes in SINONIMOS_MOVIMIENTOS.items():
        if clave in nombre_lower or nombre_lower in clave:
            for variante in variantes:
                mov = db.query(Movimiento).filter(
                    Movimiento.tenant_id == tenant_id,
                    Movimiento.nombre.ilike(f'%{variante}%'),
                    Movimiento.activo == True
                ).first()
                if mov:
                    print(
                        f"[PARSER] Synonym match: '{nombre_buscado}' -> '{clave}' -> '{variante}' ID={mov.id}")
                    return mov, variante
            break  # Ya probamos todas las variantes de esta clave

    # Si el nombre tiene abreviaturas comunes, buscar palabra por palabra
    palabras = nombre_lower.split()
    if len(palabras) == 1 and len(palabras[0]) <= 4:
        # Es una abreviatura corta (ej: "du", "su", "t2b")
        # Buscar movimientos que CONTENGAN esta abreviatura
        mov = db.query(Movimiento).filter(
            Movimiento.tenant_id == tenant_id,
            Movimiento.nombre.ilike(f'%{nombre_buscado}%'),
            Movimiento.activo == True
        ).first()
        if mov:
            print(
                f"[PARSER] Abbreviation match: '{nombre_buscado}' -> ID={mov.id} '{mov.nombre}'")
            return mov, mov.nombre

    return None, None


def calcular_score_matching(nombre_buscado: str, nombre_bd: str) -> int:
    """
    Calcula un score de similitud entre el nombre buscado y el nombre en BD.
    Premia:
    - Coincidencia exacta: 100 pts
    - Coincidencia exacta de palabras completas (en orden): 50 pts
    - Coincidencia de cada palabra: 10 pts
    - Coincidencia de caracteres: 1 pt
    Penaliza si el nombre en BD es mucho mas largo (da mas falsos positivos).
    """
    buscado_lower = nombre_buscado.lower().strip()
    bd_lower = nombre_bd.lower().strip()

    score = 0

    # 1. Coincidencia exacta
    if buscado_lower == bd_lower:
        return 100

    # 2. Coincidencia exacta de TODAS las palabras (en cualquier orden)
    palabras_buscado = buscado_lower.split()
    palabras_bd = bd_lower.split()
    palabras_comunes = [p for p in palabras_buscado if p in palabras_bd]
    score += len(palabras_comunes) * 10

    # Bonus si las palabras coinciden en orden exacto
    if len(palabras_buscado) >= 2 and len(palabras_buscado) == len(palabras_comunes):
        # Verificar que aparecen en orden en la BD
        idx = 0
        orden_ok = True
        for pal in palabras_buscado:
            found = False
            for j in range(idx, len(palabras_bd)):
                if pal == palabras_bd[j]:
                    idx = j + 1
                    found = True
                    break
            if not found:
                orden_ok = False
                break
        if orden_ok:
            score += 20

    # Bonus si el nombre buscado esta CONTENIDO en el nombre BD (sin ser demasiado largo)
    if buscado_lower in bd_lower:
        # Penalizar si el nombre en BD es mucho mas largo que el buscado
        # (ej: "Push" en "Handstand Push-ups" -> el nombre es mucho mas largo)
        if len(bd_lower) <= len(buscado_lower) * 2:
            score += 15
        else:
            score += 3  # coincidencia contenida pero con mucha diferencia de longitud

    # 3. Penalizar si el nombre BD tiene palabras extra que no estan en buscado
    palabras_extra = [
        p for p in palabras_bd if p not in palabras_buscado and len(p) >= 3]
    score -= len(palabras_extra) * 2

    return max(score, 0)


def buscar_movimiento_bd(db: Session, nombre: str, tenant_id: int):
    """
    Busca un movimiento por nombre en BD usando ILIKE.
    Estrategia progresiva con SCORE de similitud para evitar falsos positivos
    como "Push Press" → "Handstand Push-ups" (comparten "push" pero son distintos).

    Retorna (Movimiento | None, error_msg | None, debug_str | None).
    """
    import re as re_mod
    palabras_buscado = nombre.split()

    # Obtener TODOS los movimientos candidatos del tenant
    # (esto es mas lento pero necesario para hacer scoring correcto)
    candidatos = db.query(Movimiento).filter(
        Movimiento.tenant_id == tenant_id,
        Movimiento.activo == True
    ).all()

    if not candidatos:
        # No hay movimientos en BD, intentar sinonimos directamente
        mov_variante, variante_nombre = buscar_variante_movimiento(
            db, nombre, tenant_id)
        if mov_variante:
            print(
                f"[PARSER] Synonym match (no candidates): '{nombre}' -> '{variante_nombre}' ID={mov_variante.id}")
            return mov_variante, None, f"encontrado por sinónimo '{variante_nombre}' ID={mov_variante.id}"
        return None, f"Movimiento '{nombre}' no encontrado en la base de datos", f"no encontrado: '{nombre}'"

    # Calcular score para cada candidato
    scored = []
    for cand in candidatos:
        s = calcular_score_matching(nombre, cand.nombre)
        if s > 0:
            scored.append((s, cand))

    if scored:
        # Ordenar por score descendente, luego por longitud de nombre (mas corto mejor)
        scored.sort(key=lambda x: (-x[0], len(x[1].nombre)))
        mejor_score, mejor_mov = scored[0]

        if mejor_score >= 15:  # Umbral minimo para considerar match
            print(
                f"[PARSER] Score match: '{nombre}' -> score={mejor_score} -> ID={mejor_mov.id} '{mejor_mov.nombre}'")
            return mejor_mov, None, f"encontrado por score={mejor_score} ID={mejor_mov.id}"
        else:
            print(
                f"[PARSER] Score too low: '{nombre}' -> best score={mejor_score} (umbral=15)")

    # Fallback: sinonimos
    mov_variante, variante_nombre = buscar_variante_movimiento(
        db, nombre, tenant_id)
    if mov_variante:
        print(
            f"[PARSER] Synonym match: '{nombre}' -> '{variante_nombre}' ID={mov_variante.id}")
        return mov_variante, None, f"encontrado por sinónimo '{variante_nombre}' ID={mov_variante.id}"

    # No encontrado
    print(f"[PARSER] NOT FOUND: '{nombre}'")
    return None, f"Movimiento '{nombre}' no encontrado en la base de datos", f"no encontrado: '{nombre}'"


# ──────────────────────────────────────────────
# DETECCIÓN DE FASES (CALENTAMIENTO, FUERZA, WOD)
# ──────────────────────────────────────────────

# Palabras clave para detectar fases (en minúsculas)
FASE_PALABRAS = [
    # CALENTAMIENTO
    (["calentamiento", "warm up", "warmup", "warm-up", "mobilidad",
     "mobility", "activacion", "activation"], "CALENTAMIENTO"),
    # FUERZA / SKILL
    (["fuerza", "strength", "skill", "gimnastica", "gymnastics",
     "tecnic", "technique", "pesado", "heavy"], "FUERZA"),
    # WOD / METCON
    (["wod", "metcon", "trabajo", "entrenamiento",
     "for time", "amrap", "rft", "emom"], "WOD"),
]


def detectar_fase(linea: str):
    """
    Detecta si una línea indica el inicio de una fase.
    Retorna el nombre de la fase (CALENTAMIENTO, FUERZA, WOD) o None.
    """
    linea_lower = linea.strip().lower()
    for palabras, nombre_fase in FASE_PALABRAS:
        for palabra in palabras:
            if linea_lower == palabra or linea_lower.startswith(palabra) or linea_lower.endswith(palabra):
                return nombre_fase
    # También detectar si es encabezado mayúscula con palabra clave
    if es_encabezado(linea):
        linea_lower = linea.lower()
        for palabras, nombre_fase in FASE_PALABRAS:
            for palabra in palabras:
                if palabra in linea_lower:
                    return nombre_fase
    return None


def parse_wod_texto(texto: str, tenant_id: int, db: Session):
    """
    Función principal: recibe texto multilínea, lo parsea,
    detecta fases (CALENTAMIENTO, FUERZA, WOD) y agrupa movimientos.
    Retorna (movimientos_planos, errores, debug_list, fases_agrupadas).
    """
    if not texto or not texto.strip():
        return [], ["El texto está vacío"], [], []

    lineas = texto.strip().split('\n')
    movimientos = []  # legacy plano
    errores = []
    debug_list = []
    fases = []
    orden_global = 0

    # Estado del parseo por fases
    fase_actual = None
    fase_obj = None
    fase_descripcion = None

    print(f"\n[PARSER] ====== INICIANDO PARSEO CON FASES ======")
    print(f"[PARSER] Texto recibido:\n{texto}")
    print(f"[PARSER] Líneas: {len(lineas)}")

    for idx, linea in enumerate(lineas):
        linea = linea.strip()
        if not linea:
            continue

        debug_entry = DebugInfo(
            linea_original=linea,
            tipo="ok"
        )

        # ── 1. Detectar si es una NUEVA FASE ──
        nombre_fase = detectar_fase(linea)
        if nombre_fase:
            # Guardar fase anterior si existe
            if fase_obj is not None and len(fase_obj.movimientos) > 0:
                fases.append(fase_obj)

            # Iniciar nueva fase
            fase_actual = nombre_fase
            fase_obj = FaseInfo(nombre=nombre_fase, descripcion=None)
            fase_descripcion = None

            debug_entry.tipo = "fase"
            debug_entry.resultado_bd = f"inicio de fase: {nombre_fase}"
            print(f"[PARSER] Línea {idx}: FASE -> '{nombre_fase}'")
            debug_list.append(debug_entry)
            continue

        # ── 2. Parsear la línea como movimiento ──
        parsed = parsear_linea_movimiento(linea)

        # Caso: None → línea no parseable
        if parsed is None:
            debug_entry.tipo = "no_match"
            debug_entry.resultado_bd = "no se pudo parsear (formato no reconocido)"
            errores.append(f"Línea no reconocida: '{linea}'")
            print(f"[PARSER] Línea {idx}: NO MATCH -> '{linea}'")
            debug_list.append(debug_entry)
            continue

        # Caso: descripción (AMRAP, rounds, etc.) → guardar como descripción de fase actual
        if parsed.get("tipo") == "descripcion":
            if fase_obj is not None and fase_descripcion is None:
                fase_descripcion = linea
                fase_obj.descripcion = linea
                debug_entry.tipo = "descripcion"
                debug_entry.resultado_bd = f"descripción de fase '{fase_actual}': '{linea}'"
                print(
                    f"[PARSER] Línea {idx}: DESCRIPCIÓN DE FASE -> '{linea}'")
            else:
                debug_entry.tipo = "descripcion"
                debug_entry.resultado_bd = f"ignorado (descripción) - no genera error"
                print(f"[PARSER] Línea {idx}: DESCRIPCIÓN -> '{linea}'")
            debug_list.append(debug_entry)
            continue

        # Caso: encabezado (solo mayúsculas, no detectado como fase)
        if parsed.get("tipo") == "encabezado":
            debug_entry.tipo = "encabezado"
            debug_entry.resultado_bd = "ignorado (encabezado) - no genera error"
            print(f"[PARSER] Línea {idx}: ENCABEZADO -> '{linea}'")
            debug_list.append(debug_entry)
            continue

        # ── 3. Es un MOVIMIENTO → buscar en BD ──
        print(f"[PARSER] Línea {idx}: Buscando '{parsed['nombre']}'...")
        debug_entry.movimiento_buscado = parsed["nombre"]

        mov, error, debug_result = buscar_movimiento_bd(
            db, parsed["nombre"], tenant_id)
        debug_entry.resultado_bd = debug_result

        if error:
            debug_entry.tipo = "error"
            errores.append(error)
            debug_list.append(debug_entry)
            continue

        orden_global += 1
        debug_entry.tipo = "ok"
        debug_list.append(debug_entry)

        mov_parseado = MovimientoParseado(
            movimiento_id=mov.id,
            nombre=mov.nombre,
            orden=orden_global,
            series=parsed["series"],
            repeticiones=parsed["repeticiones"],
            peso=parsed["peso"]
        )
        movimientos.append(mov_parseado)

        # Agregar a la fase actual (o crear fase SIN_CLASIFICAR)
        fase_mov = FaseMovimiento(
            movimiento_id=mov.id,
            nombre=mov.nombre,
            series=parsed["series"],
            repeticiones=parsed["repeticiones"],
            peso=parsed["peso"]
        )

        if fase_obj is None:
            # No hay fase activa → crear fase SIN_CLASIFICAR
            fase_obj = FaseInfo(nombre="SIN_CLASIFICAR", descripcion=None)
            fase_actual = "SIN_CLASIFICAR"

        fase_obj.movimientos.append(fase_mov)
        print(
            f"[PARSER] ✓ Encontrado: '{mov.nombre}' (ID={mov.id}) en fase '{fase_actual}' series={parsed['series']} reps={parsed['repeticiones']}")

    # Guardar última fase si tiene movimientos
    if fase_obj is not None and len(fase_obj.movimientos) > 0:
        fases.append(fase_obj)

    if orden_global == 0 and not errores:
        errores.append("No se encontraron movimientos válidos en el texto")

    print(f"[PARSER] ====== PARSEO COMPLETADO ======")
    print(f"[PARSER] Movimientos encontrados: {orden_global}")
    print(f"[PARSER] Fases detectadas: {len(fases)}")
    for f in fases:
        print(
            f"  - {f.nombre}: {len(f.movimientos)} movimientos (desc: {f.descripcion})")
    print(f"[PARSER] Errores: {len(errores)}")
    print(f"[PARSER] Debug entries: {len(debug_list)}")

    return movimientos, errores, debug_list, fases


# ──────────────────────────────────────────────
# ENDPOINT DE PARSEO
# ──────────────────────────────────────────────

@router.post("/parse", response_model=WodParseResponse)
def parsear_wod(data: WodParseRequest, db: Session = Depends(get_db)):
    """
    Recibe texto plano de un WOD y devuelve los movimientos parseados,
    agrupados por fases (CALENTAMIENTO, FUERZA, WOD).
    Busca cada movimiento en la base de datos.
    Incluye debug_info con el detalle de cada línea procesada.
    """
    movimientos, errores, debug_list, fases = parse_wod_texto(
        texto=data.texto,
        tenant_id=data.tenant_id,
        db=db
    )
    return WodParseResponse(
        movimientos=movimientos,
        errores=errores,
        debug_info=debug_list,
        fases=fases
    )


@router.post("/", response_model=schemas.WodResponse)
def crear_wod(wod_data: schemas.WodCreate, tenant_id: int = Query(1), db: Session = Depends(get_db)):
    """
    Crea un WOD con movimientos.
    Acepta dos formatos:
      - movimientos[]: formato tradicional plano
      - fases[]: formato agrupado por fases (CALENTAMIENTO, FUERZA, WOD)
    """
    estado_valor = wod_data.estado if wod_data.estado else "draft"
    nueva_wod = Wod(
        tenant_id=tenant_id,
        fecha=wod_data.fecha,
        hora_inicio=wod_data.hora_inicio,
        hora_fin=wod_data.hora_fin,
        titulo=wod_data.titulo,
        descripcion=wod_data.descripcion,
        coach_id=wod_data.coach_id,
        estado=EstadoWod[estado_valor]
    )
    db.add(nueva_wod)
    db.flush()

    # Procesar movimientos: si viene fases[], aplanar a movimientos[] con campo fase
    if wod_data.fases:
        # Formato con fases agrupadas (del parser)
        orden = 1
        for fase in wod_data.fases:
            for mov in fase.movimientos:
                wod_mov = WodMovimiento(
                    wod_id=nueva_wod.id,
                    movimiento_id=mov.movimiento_id,
                    orden=orden,
                    series=mov.series,
                    repeticiones=mov.repeticiones,
                    peso=mov.peso,
                    tiempo=mov.tiempo,
                    notas=mov.notas,
                    fase=fase.nombre  # Guardar nombre de fase
                )
                db.add(wod_mov)
                orden += 1
    else:
        # Formato tradicional plano (puede o no tener fase en cada movimiento)
        for i, mov_data in enumerate(wod_data.movimientos, start=1):
            wod_mov = WodMovimiento(
                wod_id=nueva_wod.id,
                movimiento_id=mov_data.movimiento_id,
                orden=mov_data.orden or i,
                series=mov_data.series,
                repeticiones=mov_data.repeticiones,
                peso=mov_data.peso,
                tiempo=mov_data.tiempo,
                notas=mov_data.notas,
                fase=mov_data.fase or None
            )
            db.add(wod_mov)

    db.commit()
    db.refresh(nueva_wod)
    # Usar from_orm_with_names para incluir nombres de movimientos
    return schemas.WodResponse.from_orm_with_names(nueva_wod)


@router.get("/", response_model=list[schemas.WodResponse])
def listar_wods(tenant_id: int = Query(1), fecha: date = Query(None), estado: str = Query(None), db: Session = Depends(get_db)):
    query = db.query(Wod).filter(
        Wod.tenant_id == tenant_id, Wod.activo == True)
    if fecha:
        query = query.filter(Wod.fecha == fecha)
    if estado:
        query = query.filter(Wod.estado == estado)
    wods = query.order_by(Wod.fecha.desc()).all()
    # Usar from_orm_with_names para incluir nombres de movimientos
    return [schemas.WodResponse.from_orm_with_names(w) for w in wods]


@router.get("/{wod_id}", response_model=schemas.WodResponse)
def obtener_wod(wod_id: int, tenant_id: int = Query(1), db: Session = Depends(get_db)):
    wod = db.query(Wod).filter(
        Wod.id == wod_id, Wod.tenant_id == tenant_id).first()
    if not wod:
        raise HTTPException(status_code=404, detail="WOD no encontrado")
    return schemas.WodResponse.from_orm_with_names(wod)


@router.put("/{wod_id}", response_model=schemas.WodResponse)
def actualizar_wod(wod_id: int, wod_data: schemas.WodUpdate, tenant_id: int = Query(1), db: Session = Depends(get_db)):
    """
    Actualiza un WOD existente.
    Si envía movimientos[] o fases[], reemplaza todos los movimientos previos.
    """
    wod = db.query(Wod).filter(
        Wod.id == wod_id, Wod.tenant_id == tenant_id).first()
    if not wod:
        raise HTTPException(status_code=404, detail="WOD no encontrado")

    # Actualizar campos basicos
    if wod_data.titulo is not None:
        wod.titulo = wod_data.titulo
    if wod_data.descripcion is not None:
        wod.descripcion = wod_data.descripcion
    if wod_data.estado is not None:
        wod.estado = EstadoWod[wod_data.estado]

    # Actualizar horarios
    if wod_data.hora_inicio is not None:
        wod.hora_inicio = wod_data.hora_inicio
    if wod_data.hora_fin is not None:
        wod.hora_fin = wod_data.hora_fin

    # Reemplazar movimientos si se enviaron
    if wod_data.fases or wod_data.movimientos:
        # Borrar movimientos viejos
        db.query(WodMovimiento).filter(
            WodMovimiento.wod_id == wod_id).delete()

        if wod_data.fases:
            # Nuevo formato con fases
            orden = 1
            for fase in wod_data.fases:
                for mov in fase.movimientos:
                    wod_mov = WodMovimiento(
                        wod_id=wod.id,
                        movimiento_id=mov.movimiento_id,
                        orden=orden,
                        series=mov.series,
                        repeticiones=mov.repeticiones,
                        peso=mov.peso,
                        tiempo=mov.tiempo,
                        notas=mov.notas,
                        fase=fase.nombre
                    )
                    db.add(wod_mov)
                    orden += 1
        elif wod_data.movimientos:
            # Formato tradicional plano (con o sin fase)
            for i, mov_data in enumerate(wod_data.movimientos, start=1):
                wod_mov = WodMovimiento(
                    wod_id=wod.id,
                    movimiento_id=mov_data.movimiento_id,
                    orden=mov_data.orden or i,
                    series=mov_data.series,
                    repeticiones=mov_data.repeticiones,
                    peso=mov_data.peso,
                    tiempo=mov_data.tiempo,
                    notas=mov_data.notas,
                    fase=mov_data.fase or None
                )
                db.add(wod_mov)

    db.commit()
    db.refresh(wod)
    return schemas.WodResponse.from_orm_with_names(wod)


@router.delete("/{wod_id}")
def eliminar_wod(wod_id: int, tenant_id: int = Query(1), db: Session = Depends(get_db)):
    wod = db.query(Wod).filter(
        Wod.id == wod_id, Wod.tenant_id == tenant_id).first()
    if not wod:
        raise HTTPException(status_code=404, detail="WOD no encontrado")
    db.delete(wod)
    db.commit()
    return {"detail": "WOD eliminado"}


# ──────────────────────────────────────────────
# ENDPOINT: ASIGNAR WOD A CLASE
# ──────────────────────────────────────────────

@router.post("/clases/{clase_id}/asignar-wod/{wod_id}")
def asignar_wod_a_clase(clase_id: int, wod_id: int, tenant_id: int = Query(1), db: Session = Depends(get_db)):
    """
    Vincula un WOD a una clase especifica.
    La clase debe existir y el WOD debe existir.
    """
    # Verificar que la clase existe
    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()
    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    # Verificar que el WOD existe
    wod = db.query(Wod).filter(
        Wod.id == wod_id,
        Wod.tenant_id == tenant_id
    ).first()
    if not wod:
        raise HTTPException(status_code=404, detail="WOD no encontrado")

    # Asignar WOD a la clase
    clase.wod_id = wod_id
    db.commit()
    db.refresh(clase)

    return {
        "mensaje": "WOD asignado a clase exitosamente",
        "clase_id": clase.id,
        "wod_id": wod.id,
        "fecha": str(clase.fecha),
        "wod_titulo": wod.titulo
    }
