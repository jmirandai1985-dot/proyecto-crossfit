/** Iniciales del avatar ("Camila Soto" -> "CS"), máximo 2 letras. */
export const iniciales = (nombre) => {
    const palabras = String(nombre || '').trim().split(/\s+/).filter(Boolean);
    if (!palabras.length) return '?';
    if (palabras.length === 1) return palabras[0].charAt(0).toUpperCase();
    return (palabras[0].charAt(0) + palabras[palabras.length - 1].charAt(0)).toUpperCase();
};
