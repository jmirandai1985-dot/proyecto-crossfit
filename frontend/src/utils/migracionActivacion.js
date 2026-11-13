// Reglas del panel de ACTIVACIÓN de la migración BoxMagic (TEMPORAL): etapas, badges,
// conteos y filtros de la tabla. Vive aparte del componente y es JS PURO para que
// `scripts/test-migracion-activacion.mjs` lo pruebe sin navegador (mismo patrón que
// `utils/avisosMarketing.js` con `test-marketing.mjs`).
//
// Los `key` son EXACTAMENTE los que devuelve el backend
// (`GET /api/v1/migracion-boxmagic/activacion`, Fase 1). Si el backend agrega una etapa,
// se agrega acá y las tarjetas, los filtros y los badges la toman solos.

// Un color por etapa (el orden es el del embudo, del menos al más avanzado):
//   rojo    = sin_invitar        (no se le mandó el correo de activación)
//   amarillo= correo_enviado     (tiene el correo, falta que cambie la contraseña)
//   azul    = password_cambiada / registro_completo (ya entró / ya completó el alta)
//   verde   = plan_comprado      (la meta)
// `badge` es la clase del badge (color + borde) y `color` la del borde izquierdo de la
// tarjeta del KPI, igual que las tarjetas de Fidelización.
export const ETAPAS_ACTIVACION = [
    {
        key: 'sin_invitar',
        label: 'Sin invitar',
        badge: 'bg-red-500/15 text-red-300 border-red-500/30',
        color: 'border-red-500',
    },
    {
        key: 'correo_enviado',
        label: 'Correo enviado',
        badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
        color: 'border-amber-500',
    },
    {
        key: 'password_cambiada',
        label: 'Contraseña cambiada',
        badge: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
        color: 'border-blue-500',
    },
    {
        key: 'registro_completo',
        label: 'Registro completo',
        badge: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
        color: 'border-blue-500',
    },
    {
        key: 'plan_comprado',
        label: 'Plan comprado',
        badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
        color: 'border-emerald-500',
    },
];

export const ETAPA_PLAN_COMPRADO = 'plan_comprado';

// Fallback para un `etapa` que este build no conoce (backend más nuevo que el front):
// un badge gris "Sin dato" es más honesto que inventar una etapa del embudo.
export const ETAPA_DESCONOCIDA = {
    key: 'desconocida',
    label: 'Sin dato',
    badge: 'bg-zinc-700/40 text-zinc-300 border-zinc-600',
    color: 'border-zinc-600',
};

export function etapaDe(key) {
    return ETAPAS_ACTIVACION.find((e) => e.key === key) || ETAPA_DESCONOCIDA;
}

// { texto, clase } listo para pintar el badge de la tabla.
export function badgeEtapa(key) {
    const etapa = etapaDe(key);
    return { texto: etapa.label, clase: etapa.badge };
}

// Los CINCO contadores, siempre completos: el backend ya los manda así, pero un panel no
// puede dibujar `undefined` si la respuesta viene recortada o vacía.
export function conteoPorEtapa(resumen) {
    const porEtapa = (resumen && resumen.por_etapa) || {};
    const salida = {};
    for (const etapa of ETAPAS_ACTIVACION) {
        salida[etapa.key] = Number(porEtapa[etapa.key] || 0);
    }
    return salida;
}

// Total del padrón migrado. Se prefiere el `total` del backend; si faltara, se suma.
export function totalAlumnos(resumen) {
    const declarado = Number(resumen && resumen.total);
    if (Number.isFinite(declarado) && declarado > 0) return declarado;
    return Object.values(conteoPorEtapa(resumen)).reduce((suma, n) => suma + n, 0);
}

// "Pendientes por activar" = los que TODAVÍA no compraron plan (la meta del panel).
export function pendientesPorActivar(resumen) {
    const restantes = totalAlumnos(resumen) - conteoPorEtapa(resumen)[ETAPA_PLAN_COMPRADO];
    return Math.max(0, restantes);   // nunca negativo, aunque la data venga rara
}

// Avance del embudo: % del padrón migrado que ya compró plan (0-100, redondeado).
// Con total 0 devuelve 0 (la barra vacía, no una división por cero).
export function porcentajeComprado(resumen) {
    const total = totalAlumnos(resumen);
    if (!total) return 0;
    return Math.round((conteoPorEtapa(resumen)[ETAPA_PLAN_COMPRADO] / total) * 100);
}

// Cuántos alcanzaron su hito en las últimas 24 h (lo calcula el backend).
export function activadosHoy(resumen) {
    return Number((resumen && resumen.activados_hoy) || 0);
}

// ── Buscador por nombre o correo ───────────────────────────────────────────────
// Sin acentos, sin mayúsculas y sin espacios de sobra (mismo criterio que
// `utils/membresiasMes.js`): "PERÉZ" y "perez" encuentran a la misma persona y una
// tilde tipeada de más no deja la tabla vacía.
const normalizarTexto = (texto) => String(texto ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();

// ¿La fila coincide con el texto buscado? Coincidencia PARCIAL contra el NOMBRE **o** el
// CORREO ("ana" encuentra a "Ana Soto" y a "ana@box.cl"; "soto" también). Un término
// vacío no filtra nada (la tabla completa).
export function coincideBusqueda(alumno, termino) {
    const buscado = normalizarTexto(termino);
    if (!buscado) return true;
    return normalizarTexto(alumno && alumno.nombre).includes(buscado)
        || normalizarTexto(alumno && alumno.correo).includes(buscado);
}

// ¿Hay algún filtro puesto? (para mostrar u ocultar el "Ver todos"). El texto buscado
// CUENTA: con algo escrito la tabla ya no muestra el padrón completo.
export function hayFiltro(
    { etapa = null, soloActivadosHoy = false, busqueda = '' } = {},
) {
    return Boolean(etapa) || Boolean(soloActivadosHoy) || normalizarTexto(busqueda) !== '';
}

// Filtro de la tabla. Los criterios se COMBINAN entre sí (etapa + "se activaron hoy" +
// texto buscado) y ninguno es excluyente: los dos de las tarjetas se prenden y se apagan
// con el mismo clic, y el texto se borra. Filtrar es SÓLO en memoria: la respuesta del
// backend ya trae el padrón completo.
export function filtrarAlumnos(
    alumnos, { etapa = null, soloActivadosHoy = false, busqueda = '' } = {},
) {
    const lista = Array.isArray(alumnos) ? alumnos : [];
    return lista.filter((alumno) => {
        if (etapa && alumno.etapa !== etapa) return false;
        if (soloActivadosHoy && alumno.activado_hoy !== true) return false;
        if (!coincideBusqueda(alumno, busqueda)) return false;
        return true;
    });
}

// ── Listado por bloques (no se pintan los ~712 de una) ─────────────────────────
// El padrón completo llega en una sola respuesta, pero dibujar cientos de filas (o
// tarjetas, en el teléfono) de golpe congela el scroll. La tabla/las tarjetas pintan el
// primer bloque y "Cargar 25 más" AGREGA el siguiente: lo que el admin ya está mirando
// no se reemplaza.
export const BLOQUE_ALUMNOS = 25;

// Lo que se pinta y los números del footer. `faltan` es cuántos quedan fuera de la
// pantalla y `hayMas` decide si existe el botón "Cargar 25 más". Un `limite` inválido
// (0, negativo, NaN) vuelve al bloque por defecto en vez de recortar la lista entera.
export function paginaAlumnos(alumnos, limite = BLOQUE_ALUMNOS) {
    const lista = Array.isArray(alumnos) ? alumnos : [];
    const pedido = Math.floor(Number(limite));
    const tope = Number.isFinite(pedido) && pedido > 0 ? pedido : BLOQUE_ALUMNOS;
    const mostrados = lista.slice(0, tope);
    return {
        mostrados,
        total: lista.length,
        faltan: Math.max(0, lista.length - mostrados.length),
        hayMas: lista.length > mostrados.length,
    };
}
