// Reglas del panel de RECUPERACIÓN de la migración BoxMagic (TEMPORAL): estados, badges,
// conteos, filtros de la tabla y el texto humano de una oferta. Vive aparte del
// componente y es JS PURO para que `scripts/test-migracion-recuperacion.mjs` lo pruebe
// sin navegador (mismo patrón que `utils/migracionActivacion.js` con su test).
//
// Los `key` son EXACTAMENTE los que devuelve el backend
// (`GET /api/v1/migracion-boxmagic/recuperacion`, Fase 2) y los `tipo_beneficio` los de
// `TIPOS_BENEFICIO_PROMOCION` (`app/models/promocion_recuperacion.py`).
import { fechaSolaAInstante, hoyChileStr, toChileFechaStr } from './fecha.js';

// Un color por estado (el orden es el del embudo de recuperación, del menos al más
// avanzado):
//   rojo   = sin_contactar      (todavía no se le ofreció nada)
//   ámbar  = promocion_enviada  (tiene una oferta con la ventana ABIERTA)
//   gris   = vencida            (se le ofreció algo y la ventana ya pasó)
//   verde  = recuperado         (volvió: la meta del panel)
// `badge` es la clase del badge (color + borde) y `color` la del borde izquierdo de la
// tarjeta del KPI, igual que las tarjetas de Fidelización y del panel de Activación.
export const ESTADOS_RECUPERACION = [
    {
        key: 'sin_contactar',
        label: 'Sin contactar',
        badge: 'bg-red-500/15 text-red-300 border-red-500/30',
        color: 'border-red-500',
    },
    {
        key: 'promocion_enviada',
        label: 'Promoción enviada',
        badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
        color: 'border-amber-500',
    },
    {
        key: 'vencida',
        label: 'Vencida',
        badge: 'bg-zinc-700/40 text-zinc-300 border-zinc-600',
        color: 'border-zinc-500',
    },
    {
        key: 'recuperado',
        label: 'Recuperado',
        badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
        color: 'border-emerald-500',
    },
];

export const ESTADO_RECUPERADO = 'recuperado';

// Fallback para un estado que este build no conoce (backend más nuevo que el front): un
// badge gris "Sin dato" es más honesto que inventar un tramo del embudo.
export const ESTADO_DESCONOCIDO = {
    key: 'desconocido',
    label: 'Sin dato',
    badge: 'bg-zinc-700/40 text-zinc-300 border-zinc-600',
    color: 'border-zinc-600',
};

export function estadoDe(key) {
    return ESTADOS_RECUPERACION.find((e) => e.key === key) || ESTADO_DESCONOCIDO;
}

// { texto, clase } listo para pintar el badge de la tabla.
export function badgeEstado(key) {
    const estado = estadoDe(key);
    return { texto: estado.label, clase: estado.badge };
}

// ── Tipos de beneficio (la unidad de `cantidad` la define el tipo) ──────────────
// Misma lista y mismas claves que el backend (`TIPOS_BENEFICIO_PROMOCION`). Sólo
// describe el formulario: qué se elige, cómo se llama la cantidad y un valor inicial
// razonable.
export const TIPOS_BENEFICIO = [
    {
        key: 'dias_gratis',
        label: 'Días gratis',
        etiquetaCantidad: 'Días de clases',
        ayuda: 'Días de clases sin costo.',
        defecto: 5,
    },
    {
        key: 'descuento_porcentaje',
        label: 'Descuento %',
        etiquetaCantidad: 'Descuento (%)',
        ayuda: 'Porcentaje sobre su próximo plan.',
        defecto: 20,
    },
    {
        key: 'descuento_monto',
        label: 'Descuento en monto',
        etiquetaCantidad: 'Descuento (CLP)',
        ayuda: 'Monto en pesos sobre su próximo plan.',
        defecto: 10000,
    },
];

export const TIPO_BENEFICIO_DESCONOCIDO = {
    key: 'desconocido',
    label: 'Beneficio',
    etiquetaCantidad: 'Cantidad',
    ayuda: '',
    defecto: 1,
};

export function tipoBeneficioDe(key) {
    return TIPOS_BENEFICIO.find((t) => t.key === key) || TIPO_BENEFICIO_DESCONOCIDO;
}

// (tipo_beneficio, cantidad) -> texto humano, para MOSTRAR en pantalla:
//   'dias_gratis' + 5           -> '5 días gratis de clases'
//   'descuento_porcentaje' + 20 -> '20% de descuento'
//   'descuento_monto' + 10000   -> '$10.000 de descuento' (CLP, sin decimales)
// Es el MISMO formato que el correo (`email_service._beneficio_promocion_humano`), pero
// esto no es lógica de negocio: la oferta la decide el backend y el correo lo arma él.
// Acá sólo se pinta lo que ya se guardó.
export function textoBeneficio(tipoBeneficio, cantidad) {
    const n = Number(cantidad || 0);
    if (tipoBeneficio === 'dias_gratis') {
        return `${n} día${n === 1 ? '' : 's'} gratis de clases`;
    }
    if (tipoBeneficio === 'descuento_porcentaje') {
        return `${n}% de descuento`;
    }
    if (tipoBeneficio === 'descuento_monto') {
        // CLP: separador de miles con punto y sin decimales (formato chileno).
        return `$${String(Math.trunc(n)).replace(/\B(?=(\d{3})+(?!\d))/g, '.')} de descuento`;
    }
    // Tipo desconocido: texto genérico, igual que el correo (no se inventa un beneficio).
    return 'un beneficio especial';
}

// ── Conteos del resumen (los manda el backend ya calculados) ────────────────────
// Los CUATRO contadores, siempre completos: un panel no puede dibujar `undefined` si la
// respuesta viene recortada o vacía.
export function conteoPorEstado(resumen) {
    const porEstado = (resumen && resumen.por_estado) || {};
    const salida = {};
    for (const estado of ESTADOS_RECUPERACION) {
        salida[estado.key] = Number(porEstado[estado.key] || 0);
    }
    return salida;
}

// Total de inactivos del panel. Se prefiere el `total` del backend; si faltara, se suma.
export function totalAlumnos(resumen) {
    const declarado = Number(resumen && resumen.total);
    if (Number.isFinite(declarado) && declarado > 0) return declarado;
    return Object.values(conteoPorEstado(resumen)).reduce((suma, n) => suma + n, 0);
}

// "Pendientes por recuperar" = todos menos los que YA volvieron (sin_contactar +
// promocion_enviada + vencida). Es el número que importa del panel.
export function pendientesPorRecuperar(resumen) {
    const restantes = totalAlumnos(resumen) - conteoPorEstado(resumen)[ESTADO_RECUPERADO];
    return Math.max(0, restantes);   // nunca negativo, aunque la data venga rara
}

// Avance del embudo: % de los inactivos que ya volvieron (0-100, redondeado). Con total
// 0 devuelve 0 (la barra vacía, no una división por cero).
export function porcentajeRecuperado(resumen) {
    const total = totalAlumnos(resumen);
    if (!total) return 0;
    return Math.round((conteoPorEstado(resumen)[ESTADO_RECUPERADO] / total) * 100);
}

// ── Filtro de la tabla ─────────────────────────────────────────────────────────
// ¿Hay algún filtro puesto? (para mostrar u ocultar el "Ver todos").
export function hayFiltro({ estado = null } = {}) {
    return Boolean(estado);
}

// Un solo criterio (el estado de la tarjeta que se clickeó), igual que Activación: se
// prende y se apaga con el mismo clic.
export function filtrarAlumnos(alumnos, { estado = null } = {}) {
    const lista = Array.isArray(alumnos) ? alumnos : [];
    if (!estado) return lista;
    return lista.filter((alumno) => alumno.estado === estado);
}

// ── Qué acción ofrece cada fila ────────────────────────────────────────────────
// La oferta se configura cuando NO hay una vigente: sin oferta o con la ventana vencida.
export function puedeConfigurarPromocion(alumno) {
    const estado = alumno && alumno.estado;
    return estado === 'sin_contactar' || estado === 'vencida';
}

// "Recuperado" sólo se marca con una oferta VIGENTE (el backend responde 404 si no la
// hay), así el panel no ofrece un botón que va a fallar.
export function puedeMarcarRecuperado(alumno) {
    return Boolean(alumno) && alumno.estado === 'promocion_enviada';
}

// ── Fechas (día chileno, sin que la zona del navegador corra nada) ──────────────
const SOLO_FECHA = /^\d{4}-\d{2}-\d{2}$/;

// 'YYYY-MM-DD' del día chileno de `valor`. Un 'YYYY-MM-DD' pelado (`ultima_asistencia`
// del backend, o lo que elige el admin en el date picker) se devuelve TAL CUAL: ese día
// ya viene resuelto en Chile y pasarlo por `new Date()` lo correría al día anterior.
function aDiaChile(valor) {
    if (!valor) return '';
    const texto = String(valor);
    if (SOLO_FECHA.test(texto)) return texto;
    return toChileFechaStr(texto);   // instante ISO (`vence_en`) -> día chileno
}

// 'dd-mm-aaaa' para mostrar ('' si no hay fecha usable).
export function fechaTexto(valor) {
    const dia = aDiaChile(valor);
    if (!dia) return '';
    const [anio, mes, fecha] = dia.split('-');
    return `${fecha}-${mes}-${anio}`;
}

// 'YYYY-MM-DD' para el <input type="date"> ('' si no hay fecha usable).
export function fechaParaInput(valor) {
    return aDiaChile(valor);
}

// Fecha de HOY + `dias`, como 'YYYY-MM-DD' del calendario chileno. Se ancla a mediodía
// UTC (`fechaSolaAInstante`) para que ni el reloj ni la zona del navegador la corran.
export function fechaEnDias(dias, desde = hoyChileStr()) {
    const base = fechaSolaAInstante(desde);
    return new Date(base.getTime() + (Number(dias) || 0) * 86400000)
        .toISOString().slice(0, 10);
}

// ¿La fecha elegida sirve como vencimiento? El backend rechaza el pasado ("La oferta no
// puede vencer en el pasado"), así que el formulario lo avisa antes de mandar nada. Se
// comparan dos 'YYYY-MM-DD', que ordenan igual como texto.
export function esVencimientoValido(fecha, hoy = hoyChileStr()) {
    const dia = fechaParaInput(fecha);
    if (!dia) return false;
    return dia >= hoy;
}
