/**
 * alumnos — reglas PURAS del padrón de alumnos del box (FUENTE ÚNICA).
 *
 * Por qué existe: estas reglas vivían dentro de `pages/admin/Alumnos.jsx` (componente
 * de 690 líneas). El rediseño móvil del padrón (A5) monta una SEGUNDA vista sobre los
 * MISMOS datos, así que "¿la suscripción está vigente hoy?", "¿qué plan es?" y "¿qué
 * tramo está mostrando la tabla?" tienen que responder lo mismo en las dos. Acá se
 * copian TAL CUAL estaban (mismos textos, mismas clases y mismas fórmulas): el
 * escritorio no cambia de comportamiento, y el móvil no puede divergir.
 *
 * Todo es puro (sin React ni fetch), así que se valida sin navegador:
 * `node scripts/test-alumnos.mjs` (`npm run test:alumnos`).
 */
import { hoyChileStr, toChileFechaStr } from './fecha.js';

/**
 * ¿La suscripción sigue vigente HOY? Se compara por DÍA CHILENO (el día de
 * vencimiento vale completo) y con el MISMO criterio que el backend
 * (`vigente_el_dia`): no depende de la hora del navegador ni de su zona.
 * Una fecha de vencimiento vacía nunca está vigente.
 */
export const suscripcionVigenteHoy = (fechaExpiracion) =>
    Boolean(fechaExpiracion) && toChileFechaStr(fechaExpiracion) >= hoyChileStr();

/**
 * De una lista de suscripciones, la que está VIGENTE con el vencimiento más
 * lejano (la que "manda" hoy), o `null` si ninguna lo está. Mismo criterio que
 * el listado del backend (`/alumnos?con_membresia`): vencimiento desc y la
 * primera vigente.
 */
export const suscripcionVigente = (lista = []) => {
    const vigentes = (lista || []).filter((s) => suscripcionVigenteHoy(s?.fecha_expiracion));
    if (vigentes.length === 0) return null;
    return vigentes.reduce((a, b) =>
        new Date(b.fecha_expiracion) > new Date(a.fecha_expiracion) ? b : a);
};

/**
 * La suscripción de UN alumno dentro de la lista de activas del box, o `null`.
 * Se busca por `usuario_id` (no por `id`, que es el de la suscripción).
 */
export const suscripcionDeAlumno = (lista = [], alumnoId) =>
    (lista || []).find((s) => s.usuario_id === alumnoId) || null;

/**
 * Nombre del plan de una suscripción. Si el plan no está en el catálogo (borrado,
 * inactivo o todavía sin cargar) se muestra el id en vez de un hueco vacío: es lo
 * que ya hacían la columna "Plan Activo" y el aviso del comprobante.
 */
export const nombrePlan = (planes = [], planId) => {
    const plan = (planes || []).find((p) => p.id === planId);
    return plan ? plan.nombre : `Plan ID ${planId}`;
};

/**
 * Clave del estado REAL del registro: `estado` es la fuente de verdad (el flag
 * `activo` es derivado y el backend garantiza que no se desincronicen). La usa la
 * vista móvil para elegir el tinte de la tarjeta, sin volver a decidir nada.
 */
export const estadoDe = (usuario) =>
    usuario?.estado || (usuario?.activo ? 'activo' : 'baja');

/**
 * Badge del estado: el texto y las clases son las que pinta el panel desde siempre.
 * Es la misma píldora en la tabla de escritorio y en las tarjetas del teléfono.
 */
export const badgeEstado = (usuario) => {
    const est = estadoDe(usuario);
    return {
        texto: est === 'pendiente_activacion' ? 'pendiente' : est,
        clase: est === 'activo' ? 'bg-green-100 text-green-800'
            : est === 'pendiente_activacion' ? 'bg-amber-100 text-amber-800'
                : est === 'rechazado' ? 'bg-red-100 text-red-800'
                    : 'bg-zinc-700 text-zinc-300',
    };
};

/**
 * Parámetros del padrón paginado (`GET /usuarios/`): la búsqueda es SERVER-SIDE
 * (`buscar`) porque con paginación filtrar en el cliente sólo alcanzaría la página
 * actual. Sin término, `buscar` viaja `undefined` para que axios no mande el param
 * (mismo request que hacía la pantalla).
 */
export const paramsAlumnos = ({
    rol = 'alumno', porPagina = 25, pagina = 1, buscar = '', estado = '',
} = {}) => ({
    rol,
    limit: porPagina,
    skip: (Math.max(1, pagina) - 1) * porPagina,
    buscar: String(buscar || '').trim() || undefined,
    // `estado` es el filtro server-side del padrón (`GET /usuarios/?estado=`).
    // Sin filtro viaja `undefined` para no cambiar el request de siempre.
    estado: String(estado || '').trim() || undefined,
});

/** Cuántas páginas tiene el padrón (el total viene del header X-Total-Count). */
export const totalPaginas = (total, porPagina) =>
    Math.max(1, Math.ceil((Number(total) || 0) / porPagina));

/**
 * ¿La página pedida quedó FUERA DE RANGO? (p. ej. se borró el último de la última, o
 * el patrón de búsqueda encogió el total): en ese caso la pantalla retrocede al
 * último tramo válido en vez de mostrar una tabla vacía.
 */
export const paginaFueraDeRango = (pagina, total, porPagina) =>
    pagina > totalPaginas(total, porPagina);

/** La página pedida acotada al rango válido (1..totalPaginas). Dentro de rango no cambia. */
export const paginaValida = (pagina, total, porPagina) =>
    Math.min(Math.max(1, pagina), totalPaginas(total, porPagina));

/**
 * Tramo que está mostrando la tabla: `A-B de total`. Misma fórmula que tenía la
 * pantalla (`enPagina` = filas realmente pintadas, que pueden ser menos que
 * `porPagina` en la última página). Con el padrón vacío devuelve `0-0`.
 */
export const rangoMostrado = ({ total = 0, porPagina = 25, pagina = 1, enPagina = 0 } = {}) => {
    const t = Number(total) || 0;
    return {
        totalPaginas: totalPaginas(t, porPagina),
        desde: t === 0 ? 0 : (pagina - 1) * porPagina + 1,
        hasta: (pagina - 1) * porPagina + enPagina,
    };
};
