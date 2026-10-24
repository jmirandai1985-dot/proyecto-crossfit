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

// ── Fase 5: promociones por volumen ─────────────────────────────────────────
// Los ids son los del enum `TipoPremio` del backend: el panel no inventa un
// vocabulario paralelo que después haya que traducir a mano.
export const TIPOS_PREMIO = [
    {
        id: 'mes_gratis',
        label: 'Mes gratis',
        ayuda: 'Extiende 30 días la suscripción vigente del alumno.',
        pideValor: false,
    },
    {
        id: 'dias_gratis',
        label: 'Días gratis',
        ayuda: 'Extiende la suscripción vigente los días que indiques.',
        pideValor: true,
        unidad: 'días',
    },
    {
        id: 'descuento_extra',
        label: 'Descuento extra',
        ayuda: 'Crédito de % para la próxima compra del alumno.',
        pideValor: true,
        unidad: '%',
    },
];

export const ETIQUETAS_ESTADO_DETECCION = {
    pendiente_confirmacion: 'Pendiente',
    confirmado: 'Confirmada',
    rechazado: 'Rechazada',
};

export function etiquetaTipoPremio(tipo) {
    return TIPOS_PREMIO.find((opcion) => opcion.id === tipo)?.label || tipo || '—';
}

// Texto del premio con la misma idea que `texto_premio` del backend. La
// autoridad sigue siendo el backend (el componente muestra `premio_texto` en
// las filas detectadas); esto es para el formulario y la vista previa.
export function formatearValorPremio(tipo, valor) {
    if (tipo === 'mes_gratis') return '1 mes gratis (30 días)';
    const numero = Number(valor);
    if (!Number.isFinite(numero)) return '—';
    if (tipo === 'dias_gratis') return `${numero} ${numero === 1 ? 'día' : 'días'} gratis`;
    if (tipo === 'descuento_extra') {
        const texto = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 2 }).format(numero);
        return `${texto} % de descuento extra`;
    }
    return '—';
}

/**
 * Valida el formulario del admin y devuelve el payload EXACTO del backend.
 * `mes_gratis` no manda valor (se normaliza a null); los otros tipos sí.
 */
export function validarPromocionReferido(form = {}) {
    const errores = {};
    const nombre = String(form.nombre ?? '').trim();
    if (!nombre) errores.nombre = 'Escribe un nombre para la promoción.';
    else if (nombre.length > 150) errores.nombre = 'El nombre no puede superar los 150 caracteres.';

    const umbralTexto = String(form.umbral_referidos_convertidos ?? '').trim();
    let umbral = null;
    if (!/^\d+$/.test(umbralTexto)) {
        errores.umbral_referidos_convertidos = 'Usa un número entero de referidos.';
    } else {
        umbral = Number(umbralTexto);
        if (umbral < 1 || umbral > 10000) {
            errores.umbral_referidos_convertidos = 'El umbral debe estar entre 1 y 10.000.';
        }
    }

    const tipo = TIPOS_PREMIO.some((opcion) => opcion.id === form.tipo_premio)
        ? form.tipo_premio
        : null;
    if (!tipo) errores.tipo_premio = 'Elige el premio de la promoción.';

    let valor = null;
    if (tipo === 'dias_gratis') {
        const texto = String(form.valor_premio ?? '').trim();
        if (!/^\d+$/.test(texto)) {
            errores.valor_premio = 'Los días gratis deben ser un número entero.';
        } else {
            valor = Number(texto);
            if (valor < 1 || valor > 10000) errores.valor_premio = 'Los días deben estar entre 1 y 10.000.';
        }
    } else if (tipo === 'descuento_extra') {
        const porcentaje = validarPorcentajeReferido(form.valor_premio);
        if (!porcentaje.valido) {
            errores.valor_premio = porcentaje.error;
        } else if (porcentaje.valor <= 0) {
            errores.valor_premio = 'El descuento extra debe ser mayor que 0 %.';
        } else {
            valor = porcentaje.valor;
        }
    }

    if (Object.keys(errores).length > 0) {
        return { valido: false, errores, payload: null };
    }

    return {
        valido: true,
        errores: {},
        payload: {
            nombre,
            umbral_referidos_convertidos: umbral,
            periodo: 'mensual',
            tipo_premio: tipo,
            valor_premio: valor,
            activo: Boolean(form.activo),
        },
    };
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

// ── La tarjeta FIJA del carrusel ("Invita y Gana", migración 058) ───────────
// Los textos los edita el admin desde Marketing → Referidos. Estos máximos son
// ESPEJO de `TARJETA_*_MAX` en `app/schemas/referidos.py` y de las columnas de
// `tarjeta_referidos`: los tres lados tienen que decir lo mismo o el panel
// dejaría escribir algo que el PUT rechaza con 422.
export const MAX_TITULO_TARJETA = 80;
export const MAX_TEXTO_TARJETA = 300;
export const MAX_CTA_TARJETA = 40;

// El copy por defecto, igual que `COPY_REFERIDOS` (`utils/avisosMarketing.js`) y
// `TARJETA_REFERIDOS_*` del backend. El panel lo usa para la vista previa
// mientras el admin no guardó nada.
export const TARJETA_REFERIDOS_POR_DEFECTO = {
    titulo: 'Invita y Gana',
    texto: 'Comparte tu código con un amigo y que entrene con nosotros.',
    cta: 'Compartir mi código',
};

/**
 * Valida el formulario del copy de la tarjeta y devuelve el payload del
 * `PUT /referidos/tarjeta`.
 *
 * Un campo vacío (o sólo espacios) viaja como `null` = "usar el texto por
 * defecto de ese campo": así el botón "Restablecer" se resuelve con el MISMO
 * endpoint, sin uno aparte. Un texto que quedó IGUAL al default también viaja
 * como `null`, para que ese campo siga heredando las mejoras del copy genérico
 * del backend en vez de congelar la versión que había cuando se guardó.
 * `visible` es obligatorio en el backend, por eso se normaliza a booleano acá.
 */
export function validarTarjetaReferidos(form = {}) {
    const errores = {};

    const recortar = (campo, etiqueta, maximo) => {
        const texto = String(form[campo] ?? '').trim();
        if (texto.length > maximo) {
            errores[campo] = `${etiqueta} no puede superar los ${maximo} caracteres.`;
        }
        return texto || null;
    };

    const payload = {
        titulo: recortar('titulo', 'El título', MAX_TITULO_TARJETA),
        texto: recortar('texto', 'El texto', MAX_TEXTO_TARJETA),
        cta: recortar('cta', 'El botón', MAX_CTA_TARJETA),
        visible: form.visible !== false,
    };

    for (const campo of ['titulo', 'texto', 'cta']) {
        if (payload[campo] === TARJETA_REFERIDOS_POR_DEFECTO[campo]) {
            payload[campo] = null;
        }
    }

    return { valido: Object.keys(errores).length === 0, errores, payload };
}

/**
 * Texto sugerido para la tarjeta, según lo que el box REALMENTE ofrece hoy.
 *
 * Reglas (pedido del box):
 *  1. Sin configuración o con el programa apagado no se promete NADA: el
 *     backend no aplicaría ningún beneficio.
 *  2. Con 2+ promociones activas NO se nombra ningún premio: el alumno podría
 *     cumplir cualquiera y la tarjeta hablaría de una sola. Las promociones
 *     puntuales ya tienen su propia tarjeta publicada en el carrusel.
 *  3. Con UNA promoción activa sí se nombra (umbral + premio formateado).
 *
 * Es una SUGERENCIA: el panel la carga en los campos y el admin la edita. Nunca
 * se guarda sola, así un texto no queda congelado cuando cambie la promo.
 */
export function textoSugeridoTarjetaReferidos({ configuracion, promociones } = {}) {
    const porDefecto = { ...TARJETA_REFERIDOS_POR_DEFECTO };

    if (!configuracion?.configurada || configuracion.activo === false) {
        return porDefecto;
    }

    const invitado = Number(configuracion.porcentaje_descuento_invitado ?? 0);
    const activas = (Array.isArray(promociones) ? promociones : [])
        .filter((promo) => promo && promo.activo !== false);

    const partes = [];
    if (Number.isFinite(invitado) && invitado > 0) {
        partes.push(
            `Comparte tu código: tu amigo recibe ${formatearPorcentajeReferido(invitado)}`
            + ' de descuento en su primera compra.',
        );
    }

    if (activas.length === 1) {
        const promo = activas[0];
        const umbral = Number(promo.umbral_referidos_convertidos);
        if (Number.isFinite(umbral) && umbral > 0) {
            const premio = formatearValorPremio(promo.tipo_premio, promo.valor_premio);
            partes.push(
                `Y cuando llegues a ${umbral} ${umbral === 1 ? 'referido' : 'referidos'},`
                + ` tú ganas ${premio}.`,
            );
        }
    }

    if (partes.length === 0) return porDefecto;
    return { ...porDefecto, texto: partes.join(' ') };
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
