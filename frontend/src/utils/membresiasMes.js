/**
 * membresiasMes — filtros del modal "Membresías del Mes" (Dashboard del admin).
 *
 * POR QUÉ EXISTE: el modal lista TODAS las suscripciones del mes (263 en un mes
 * normal) sin forma de encontrar a un alumno ni de sacar las cuentas de "Prueba" del
 * medio, que no son ventas. El endpoint del Dashboard ya trae el mes completo, así
 * que los filtros se resuelven en el cliente y este archivo guarda las reglas en JS
 * puro (sin JSX) para poder testearlas con Node.
 */

/** Valor del select: sin filtro por tipo de plan. */
export const FILTRO_PLAN_TODOS = 'todos';
/** Valor del select: todas las membresías salvo las de planes de prueba. */
export const FILTRO_PLAN_SIN_PRUEBA = 'sin-prueba';

/** Sin acentos, sin mayúsculas y sin espacios de sobra (para comparar y buscar). */
const normalizar = (texto) => String(texto ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();

/**
 * ¿Es un plan de prueba? Se compara por el NOMBRE del plan porque es lo único que
 * manda el resumen del Dashboard (`plan_nombre`). Cubre "Prueba", "PRUEBA", "Plan de
 * prueba gratis" y "Clase de prueba"; no matchea "Pruebita" por accidente.
 */
export const esPlanPrueba = (planNombre) => /\bprueba\b/.test(normalizar(planNombre));

/**
 * Nombres de plan presentes en las filas, únicos y ordenados (es-CL), para armar el
 * select "Plan". Ignora vacíos y repeticiones que sólo difieren en mayúsculas.
 */
export function planesDe(filas) {
    const vistos = new Map();
    for (const fila of Array.isArray(filas) ? filas : []) {
        const nombre = String(fila?.plan_nombre ?? '').trim();
        if (!nombre) continue;
        const clave = normalizar(nombre);
        if (!vistos.has(clave)) vistos.set(clave, nombre);
    }
    return [...vistos.values()].sort((a, b) => a.localeCompare(b, 'es'));
}

/**
 * Ordena por `fecha_inicio` SIN mutar la lista original.
 * `reciente` (por defecto) = la fecha más nueva arriba; `antigua` = al revés.
 * Una fila sin fecha válida queda SIEMPRE al final: no se inventa un orden.
 */
export function ordenarMembresias(filas, orden = 'reciente') {
    const lista = Array.isArray(filas) ? [...filas] : [];
    const signo = orden === 'antigua' ? 1 : -1;
    return lista.sort((a, b) => {
        const fechaA = String(a?.fecha_inicio ?? '').slice(0, 10);
        const fechaB = String(b?.fecha_inicio ?? '').slice(0, 10);
        if (!fechaA && !fechaB) return 0;
        if (!fechaA) return 1;
        if (!fechaB) return -1;
        if (fechaA === fechaB) return 0;
        return fechaA < fechaB ? -signo : signo;
    });
}

/**
 * Busca por nombre de alumno (parcial, sin acentos ni mayúsculas), filtra por tipo de
 * plan —`FILTRO_PLAN_SIN_PRUEBA` saca las pruebas, o el nombre exacto de un plan— y
 * deja la lista ordenada por fecha. Acepta `undefined`/`null` (mientras el Dashboard
 * carga) y devuelve siempre un arreglo nuevo.
 */
export function filtrarMembresias(filas, { busqueda = '', plan = FILTRO_PLAN_TODOS, orden = 'reciente' } = {}) {
    const lista = Array.isArray(filas) ? filas : [];
    const texto = normalizar(busqueda);
    const planElegido = String(plan ?? FILTRO_PLAN_TODOS);
    const filtradas = lista.filter((fila) => {
        if (!fila) return false;
        if (texto && !normalizar(fila.alumno_nombre).includes(texto)) return false;
        if (planElegido === FILTRO_PLAN_SIN_PRUEBA) return !esPlanPrueba(fila.plan_nombre);
        if (planElegido !== FILTRO_PLAN_TODOS) {
            return normalizar(fila.plan_nombre) === normalizar(planElegido);
        }
        return true;
    });
    return ordenarMembresias(filtradas, orden);
}
