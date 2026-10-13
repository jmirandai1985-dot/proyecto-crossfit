/**
 * cuposClase — la regla del cupo ampliable, en UN solo lugar.
 *
 * POR QUÉ EXISTE: "ampliar cupo" tiene un techo de **+10 sobre el cupo ORIGINAL de la
 * clase** (`clases.cupo_original`, el snapshot que se guarda al generar la clase desde el
 * horario base). Lo valida el backend (`app/api/v1/clases.py`: `original = cupo_original or
 * cupo_maximo`, `tope = original + 10`) y lo pintan tres pantallas del panel: la Asistencia
 * (acordeón + la lista móvil por franja) y la Supervisión de clases del admin. La cuenta
 * estaba copiada en cada una; el día que cambie el tope, la copia que quede vieja manda al
 * coach a un 409. Acá viven las funciones puras que usan todas —y su test aislado—.
 *
 * Reglas (espejo del backend):
 *   · `cupo_original` nulo/0 se lee como `cupo_maximo` (el backend hace `or`, así que un 0
 *     no es un techo de 10: es "usa el cupo actual").
 *   · Sin ningún cupo cargado el tope es +10 sobre 0 (nunca NaN, nunca negativo).
 *   · `extra` es lo que se le SUMA al cupo actual, entre 1 y 10, y no puede pasarse del tope.
 */

export const MAX_CUPOS_EXTRA = 10;

/** Cupo original de la clase (el techo se mide desde acá), con el fallback del backend. */
export const cupoOriginal = (clase) => {
    const original = Number(clase?.cupo_original);
    if (Number.isFinite(original) && original > 0) return original;
    const maximo = Number(clase?.cupo_maximo);
    return Number.isFinite(maximo) && maximo > 0 ? maximo : 0;
};

/** Techo absoluto del cupo de esa clase: original + 10. */
export const cupoTope = (clase) => cupoOriginal(clase) + MAX_CUPOS_EXTRA;

/** Cupo que se está mostrando: el que el coach/admin amplió en esta visita, o el de la BD. */
export const cupoActual = (clase, cuposAmpliados) => {
    const visto = Number(cuposAmpliados?.[clase?.id]);
    if (Number.isFinite(visto) && visto > 0) return visto;
    const maximo = Number(clase?.cupo_maximo);
    return Number.isFinite(maximo) && maximo > 0 ? maximo : 0;
};

/** Cuántos cupos extra quedan antes del tope (0 = ya está en el tope). */
export const extraDisponible = (clase, cuposAmpliados) => (
    Math.max(0, cupoTope(clase) - cupoActual(clase, cuposAmpliados))
);

/** Máximo que acepta el input de "cupos extra": el menor entre 10 y lo que queda del tope. */
export const extraMaximo = (clase, cuposAmpliados) => (
    Math.min(MAX_CUPOS_EXTRA, extraDisponible(clase, cuposAmpliados))
);

/**
 * Deja `valor` dentro de lo permitido (1..extraMaximo). Si el usuario escribe cualquier cosa
 * (vacío, letras, un número gigante) cae a un valor válido: el botón nunca queda fuera de rango.
 * Si no queda cupo libre devuelve 1 (el botón de confirmar se deshabilita igual).
 */
export const acotarExtra = (valor, clase, cuposAmpliados) => {
    const max = extraMaximo(clase, cuposAmpliados);
    const n = parseInt(valor, 10);
    if (!Number.isFinite(n)) return 1;
    return Math.max(1, Math.min(max > 0 ? max : 1, n));
};
