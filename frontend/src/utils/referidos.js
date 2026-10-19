// Utilidades PURAS del Sistema de Referidos (Fase 4, frontend).
//
// Todo lo que se puede probar sin navegador ni API vive acá: normalizar el
// código que escribe el invitado, validar los porcentajes del admin, armar el
// texto para compartir y traducir el error del backend a un mensaje humano.
// Así `CampoReferido`, `InvitaYGana` y el panel de Marketing quedan finos y
// `scripts/test-referidos.mjs` puede cubrir las reglas con Node.

// Mismo tope que `CodigoReferido.codigo` en el backend.
export const LARGO_MAXIMO_CODIGO = 20;

// El backend hace `strip().upper()` antes de buscar; replicarlo acá evita que
// el alumno vea "no existe" por un espacio que él mismo escribió en el celular.
export function normalizarCodigoIngresado(codigo) {
    return String(codigo ?? '').trim().toUpperCase();
}

export function validarCodigoIngresado(codigo) {
    const normalizado = normalizarCodigoIngresado(codigo);
    if (!normalizado) {
        return { valido: false, codigo: normalizado, error: 'Ingresa un código de invitación.' };
    }
    if (normalizado.length > LARGO_MAXIMO_CODIGO) {
        return {
            valido: false,
            codigo: normalizado,
            error: `El código no puede superar los ${LARGO_MAXIMO_CODIGO} caracteres.`,
        };
    }
    return { valido: true, codigo: normalizado, error: '' };
}

// Porcentaje del admin: 0–100, hasta 2 decimales. Se acepta coma decimal
// ("12,5") porque es lo natural en teclados en español.
export function validarPorcentajeReferido(valor) {
    const texto = String(valor ?? '').trim();
    if (!texto) {
        return { valido: false, valor: null, error: 'Ingresa un porcentaje entre 0 y 100.' };
    }

    const normalizado = texto.replace(',', '.');
    if (!/^\d+(\.\d{1,2})?$/.test(normalizado)) {
        return { valido: false, valor: null, error: 'Usa un número entre 0 y 100, con hasta 2 decimales.' };
    }

    const numero = Number(normalizado);
    if (!Number.isFinite(numero) || numero < 0 || numero > 100) {
        return { valido: false, valor: null, error: 'El porcentaje debe estar entre 0 y 100.' };
    }

    return { valido: true, valor: numero, error: '' };
}

export function formatearPorcentajeReferido(valor) {
    const numero = Number(valor);
    if (!Number.isFinite(numero)) return '0 %';
    const texto = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 2 }).format(numero);
    return `${texto} %`;
}

export function textoCompartirReferido(codigo, enlace = '') {
    const limpio = normalizarCodigoIngresado(codigo);
    const mensaje = `¡Únete a entrenar conmigo! Usa mi código de referido ${limpio} cuando compres tu primer plan.`;
    return enlace ? `${mensaje}\n${enlace}` : mensaje;
}

// `navigator.share` no existe en la mayoría de los escritorios y el portapapeles
// moderno sólo está en contextos seguros (HTTPS/localhost). El fallback con
// `execCommand` mantiene funcionando la app servida por IP en la red del box.
export async function copiarAlPortapapeles(texto) {
    const valor = String(texto ?? '');

    if (typeof navigator !== 'undefined' && navigator.clipboard
        && (typeof window === 'undefined' || window.isSecureContext)) {
        await navigator.clipboard.writeText(valor);
        return true;
    }

    if (typeof document === 'undefined') {
        throw new Error('No se puede copiar en este entorno.');
    }

    const area = document.createElement('textarea');
    area.value = valor;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '-1000px';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, area.value.length);

    try {
        if (!document.execCommand('copy')) {
            throw new Error('El navegador no permitió copiar.');
        }
        return true;
    } finally {
        document.body.removeChild(area);
    }
}

// FastAPI devuelve `detail` como string (404/400 de negocio) o como lista de
// errores de Pydantic (422). El admin y el alumno merecen el mensaje del backend,
// no un "Network Error" en inglés.
export function mensajeDeError(error, porDefecto = 'No pudimos completar la operación. Intenta nuevamente.') {
    const detalle = error?.response?.data?.detail;

    if (typeof detalle === 'string' && detalle.trim()) return detalle;

    if (Array.isArray(detalle) && detalle.length > 0) {
        const primero = detalle[0];
        if (typeof primero === 'string' && primero.trim()) return primero;
        if (primero?.msg) {
            return String(primero.msg).replace(/^Value error,\s*/i, '');
        }
    }

    return porDefecto;
}
