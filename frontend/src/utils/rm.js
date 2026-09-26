/**
 * Categoría y valor de un RM — FUENTE ÚNICA (H-03).
 *
 * Antes había 3 implementaciones distintas del mismo criterio:
 *   1. `PerformanceHub.jsx`  → inferirCategoria/getValorNumerico/getUnidad (heurística por nombre)
 *   2. `Evolucion.jsx`       → categoría + valor + etiqueta + unidad inline
 *   3. `PizarraRMs.jsx`      → getCategoriaMovimiento + formatResultado
 * Cada una podía divergir (por ejemplo en qué campo usar para gimnástico: reps vs peso).
 *
 * Ahora la verdad es `movimientos.categoria` (lo que devuelve la API en `rm.categoria`);
 * el fallback por nombre queda acá y es el mismo para todas las pantallas.
 */
export const CATEGORIAS_RM = ['fuerza', 'gimnastico', 'cardio', 'metabolico'];

const ALIAS = {
  fuerza: 'fuerza',
  gimnastico: 'gimnastico',
  gimnástico: 'gimnastico',
  cardio: 'cardio',
  metabolico: 'metabolico',
  metabólico: 'metabolico',
  maquinas: 'metabolico',
  máquinas: 'metabolico',
};

/** Normaliza una categoría cruda (BD/API) a una de CATEGORIAS_RM. null si no aplica. */
export function normalizarCategoria(valor) {
  if (!valor) return null;
  const c = ALIAS[String(valor).trim().toLowerCase()];
  return c && CATEGORIAS_RM.includes(c) ? c : null;
}

/** Categoría de un RM: primero la de la BD, si no la heurística por nombre. */
export function inferirCategoriaRM(rm) {
  const deDb = normalizarCategoria(rm?.categoria);
  if (deDb) return deDb;
  const n = (rm?.movimiento_nombre || '').toLowerCase();
  // Keywords por categoría (orden: más específico primero)
  if (/sled|air.?runner|sandbag|farmer|carry/.test(n)) return 'metabolico';
  if (/run|row|ski.?erg|bike|assault/.test(n)) return 'cardio';
  if (/clean|snatch|jerk|deadlift|squat|press|thruster|dumbbell|kettlebell/.test(n)) return 'fuerza';
  if (/pull.?up|push.?up|burpee|muscle.?up|toes?.?to?.?bar|t2b|chest?.?to?.?bar|c2b|handstand|hspu|rope.?climb|pistol|doble.?under|double.?under|box.?jump|wall.?ball|bear.?crawl|kip|strict|ring|walk/.test(n)) return 'gimnastico';
  return normalizarCategoria(rm?.tipo_rm) || 'fuerza';
}

/** Valor numérico del RM según su categoría (el mismo criterio para todas las pantallas). */
export function valorRM(rm) {
  const cat = inferirCategoriaRM(rm);
  if (cat === 'gimnastico') return Number(rm?.repeticiones || rm?.peso_kg || 0);
  if (cat === 'cardio') return Number(rm?.minutos || rm?.km || rm?.vueltas || rm?.peso_kg || 0);
  if (cat === 'metabolico') return Number(rm?.calorias || rm?.km || rm?.vueltas || rm?.peso_kg || 0);
  return Number(rm?.peso_kg || 0);
}

/** Etiqueta del eje/valor según categoría (para gráficos y tarjetas). */
export function etiquetaValorRM(rm) {
  const cat = inferirCategoriaRM(rm);
  if (cat === 'gimnastico') return 'Repeticiones';
  if (cat === 'cardio') {
    return rm?.minutos ? 'Minutos' : rm?.km ? 'Km' : rm?.vueltas ? 'Vueltas' : 'Valor';
  }
  if (cat === 'metabolico') {
    return rm?.calorias ? 'Calorías' : rm?.km ? 'Km' : rm?.vueltas ? 'Vueltas' : 'Valor';
  }
  return 'Peso (kg)';
}

/** Unidad corta del valor (para ejes y tablas). */
export function unidadRM(rm) {
  const cat = inferirCategoriaRM(rm);
  if (cat === 'gimnastico') return 'reps';
  if (cat === 'cardio') return rm?.minutos ? 'min' : rm?.km ? 'km' : rm?.vueltas ? 'vueltas' : '';
  if (cat === 'metabolico') return rm?.calorias ? 'cal' : rm?.km ? 'km' : rm?.vueltas ? 'vueltas' : '';
  return 'kg';
}

/** Texto del resultado de un RM ("80 kg x 3 reps", "10 reps x 3 series", "5 km, 20 min").
 *  `categoriaForzada` permite forzar la categoría cuando el objeto todavía no la trae
 *  (p. ej. un movimiento recién elegido en el formulario). */
export function formatResultadoRM(rm, categoriaForzada) {
  const cat = normalizarCategoria(categoriaForzada) || inferirCategoriaRM(rm);
  const partes = [];
  if (cat === 'gimnastico') {
    if (rm?.repeticiones) partes.push(`${rm.repeticiones} reps`);
    if (rm?.series) partes.push(`${rm.series} series`);
  } else if (cat === 'cardio') {
    if (rm?.km) partes.push(`${rm.km} km`);
    if (rm?.minutos) partes.push(`${rm.minutos} min`);
    if (rm?.vueltas) partes.push(`${rm.vueltas} vueltas`);
  } else if (cat === 'metabolico') {
    if (rm?.calorias) partes.push(`${rm.calorias} cal`);
    if (rm?.km) partes.push(`${rm.km} km`);
    if (rm?.vueltas) partes.push(`${rm.vueltas} vueltas`);
  } else {
    if (rm?.peso_kg) partes.push(`${rm.peso_kg} kg`);
    if (rm?.repeticiones) partes.push(`${rm.repeticiones} reps`);
    if (rm?.series) partes.push(`${rm.series} series`);
  }
  if (partes.length) return partes.join(cat === 'fuerza' || cat === 'gimnastico' ? ' x ' : ', ');
  return `${rm?.peso_kg ?? '?'} ${unidadRM(rm)}`;
}
