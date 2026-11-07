/**
 * Filtro del selector de movimiento con buscador (Pizarra de RMs).
 *
 * POR QUÉ EXISTE: el selector de "Registrar Nueva Marca" / editar PR era un
 * `<select>` nativo con optgroups por categoría y, con 8+ movimientos solo en
 * Fuerza, el scroll se hacía interminable. Acá se separa la lógica de filtrado
 * (texto + categoría combinados con AND) para poder testearla SIN navegador.
 *
 * H-03: la categoría NO se adivina acá: sale de `utils/rm.js` con la MISMA
 * normalización que usa el resto de la app (`normalizarCategoria`), de modo que
 * una categoría cruda como "Fuerza" o "máquinas" cae en el mismo grupo que
 * `getCategoriaMovimiento`.
 */
import { normalizarCategoria } from './rm.js';

// Valor del chip "Todas": no filtra por categoría.
export const TODAS_CATEGORIAS = 'todas';

/** Categoría normalizada de un movimiento (fallback a `fuerza`, igual que el form). */
export function categoriaDeMovimiento(m) {
    return normalizarCategoria(m?.categoria) || 'fuerza';
}

/**
 * Filtra movimientos por texto de búsqueda (case-insensitive sobre `m.nombre`)
 * y por categoría (una key de CATEGORIA_META o `TODAS_CATEGORIAS`). Ambos
 * criterios se combinan con AND.
 */
export function filtrarMovimientos(movimientos, texto = '', categoria = TODAS_CATEGORIAS) {
    const q = String(texto || '').trim().toLowerCase();
    return (movimientos || []).filter((m) => {
        if (q && !String(m?.nombre || '').toLowerCase().includes(q)) return false;
        if (categoria !== TODAS_CATEGORIAS && categoriaDeMovimiento(m) !== categoria) return false;
        return true;
    });
}
