/**
 * Banner de estado del plan en el Inicio del alumno (móvil).
 *
 * Reemplaza el copy confuso anterior por un mensaje que depende de DOS cosas:
 *   1. `plan_en_cola` (¿el próximo plan ya está pagado y en cola?).
 *   2. Qué vence primero: la fecha o las clases (la MISMA regla "lo que ocurra
 *      primero" que `_plan_vigente_usable` en el backend).
 *
 * En frontend esa regla es "comparar días restantes vs clases restantes y usar
 * el que esté más cerca de agotarse": con menos días que clases, gana la fecha;
 * con menos clases que días, ganan las clases. Un plan ilimitado nunca se queda
 * sin clases, así que SIEMPRE vence por fecha.
 *
 * `membresia` es la respuesta de GET /planes/membresia-activa.
 * Devuelve `null` sin plan activo (no hay un "vence/quedan" que mostrar).
 */
export const textoBannerPlan = (membresia) => {
    const activa = Boolean(membresia?.activa);
    if (!activa) return null;

    const ilimitado = Boolean(membresia?.es_ilimitado);
    const dias = Number(membresia?.dias_restantes) || 0;
    const clases = Number(membresia?.clases_disponibles) || 0;
    const planEnCola = Boolean(membresia?.plan_en_cola);

    const vencePorFecha = ilimitado || dias <= clases;

    const titulo = vencePorFecha
        ? (dias === 0
            ? 'Tu plan vence hoy.'
            : `Tu plan vence en ${dias} ${dias === 1 ? 'día' : 'días'}.`)
        : (clases === 1
            ? 'Te queda 1 clase.'
            : `Te quedan ${clases} clases.`);

    const detalle = planEnCola
        ? (vencePorFecha
            ? 'Cuando venza, tu próximo plan —ya pagado— se activa automáticamente al día siguiente.'
            : 'Cuando se acaben, tu próximo plan —ya pagado— se activa automáticamente al día siguiente.')
        : 'Renueva ahora para no quedarte sin clases.';

    return { titulo, detalle, mostrarRenovar: !planEnCola };
};
