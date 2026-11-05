import { fechaSolaAInstante, sumarDiasInstante } from './fecha.js';

/**
 * Banner de estado del plan en el Inicio del alumno (móvil).
 *
 * El título muestra los días y/o créditos restantes del plan activo; el detalle
 * muestra la fecha en que se activará el próximo plan en cola (derivada del
 * vencimiento del plan activo) o el llamado a renovar.
 *
 * `membresia` es la respuesta de GET /planes/membresia-activa.
 * Devuelve `null` sin plan activo (no hay un "vence/quedan" que mostrar).
 */
// "31 de diciembre" en el calendario de Chile (para la fecha de activación del
// plan en cola). Mismo criterio que el resto de la app (TZ America/Santiago).
const diaYMesChile = (fecha) => {
    if (!fecha) return '';
    const d = fecha instanceof Date ? fecha : new Date(fecha);
    if (Number.isNaN(d.getTime())) return '';
    return new Intl.DateTimeFormat('es-CL', {
        timeZone: 'America/Santiago', day: 'numeric', month: 'long',
    }).format(d);
};

// Fecha en que se activará el plan en cola: el día SIGUIENTE al vencimiento del
// plan activo. El endpoint (`/planes/membresia-activa`) NO expone una fecha de
// activación del plan en cola (sólo `plan_en_cola` como booleano); la regla
// vigente en la app es "se activa automáticamente al día siguiente", así que se
// deriva de `fecha_vencimiento` en vez de inventar un campo que no existe.
const fechaActivacionPlanCola = (fechaVencimiento) => {
    if (!fechaVencimiento) return null;
    const base = fechaSolaAInstante(fechaVencimiento);
    if (Number.isNaN(base.getTime())) return null;
    return diaYMesChile(sumarDiasInstante(base, 1));
};

export const textoBannerPlan = (membresia) => {
    const activa = Boolean(membresia?.activa);
    if (!activa) return null;

    const ilimitado = Boolean(membresia?.es_ilimitado);
    const dias = Number(membresia?.dias_restantes) || 0;
    const clases = Number(membresia?.clases_disponibles) || 0;
    const planEnCola = Boolean(membresia?.plan_en_cola);

    // Título: días y/o créditos restantes del plan activo (más específico que
    // antes, que sólo mostraba lo que vencía primero).
    const titulo = (() => {
        if (ilimitado) {
            return dias === 0
                ? 'Tu plan vence hoy.'
                : `Tu plan vence en ${dias} ${dias === 1 ? 'día' : 'días'}.`;
        }
        const clasesTxt = clases === 1 ? '1 clase' : `${clases} clases`;
        if (dias === 0) return `Te quedan ${clasesTxt} y vence hoy.`;
        return `Te quedan ${clasesTxt} y ${dias === 1 ? '1 día' : `${dias} días`}.`;
    })();

    const fechaCola = fechaActivacionPlanCola(membresia?.fecha_vencimiento);

    // Detalle: la fecha de activación del plan en cola (o el llamado a renovar).
    const detalle = planEnCola
        ? (fechaCola
            ? `Tu próximo plan ya está pagado y se activa el ${fechaCola}.`
            : 'Tu próximo plan ya está pagado y se activa al día siguiente.')
        : 'Renueva ahora para no quedarte sin clases.';

    return {
        titulo,
        detalle,
        // `asegurado` activa el ícono de candado en vez del botón "Renovar".
        asegurado: planEnCola,
    };
};
