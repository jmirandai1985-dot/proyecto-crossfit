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
// describe el formulario: qué se elige, cómo se llama la cantidad, un valor inicial
// razonable y el RANGO que acepta el backend (el formulario no deja mandar otro).
//
// `dias_gratis` se llama así por historia, pero son CLASES, no días de calendario: el
// rango es el de Fidelización (`beneficios_service.CLASES_MIN/MAX`). El tipo
// `descuento_monto` ya NO se ofrece (no tiene equivalente en el sistema de cobro); las
// filas históricas se siguen mostrando con `textoBeneficio`.
export const CLASES_MIN = 1;
export const CLASES_MAX = 15;

export const TIPOS_BENEFICIO = [
    {
        key: 'dias_gratis',
        label: 'Días gratis',
        etiquetaCantidad: 'Clases gratis (1 a 15)',
        ayuda: 'Clases de regalo, no días de calendario: se suman a su plan o le abren un pase.',
        defecto: 5,
        min: CLASES_MIN,
        max: CLASES_MAX,
    },
    {
        key: 'descuento_porcentaje',
        label: 'Descuento %',
        etiquetaCantidad: 'Descuento (%)',
        ayuda: 'Porcentaje sobre su próximo plan.',
        defecto: 20,
        min: 1,
        max: 100,
    },
];

export const TIPO_BENEFICIO_DESCONOCIDO = {
    key: 'desconocido',
    label: 'Beneficio',
    etiquetaCantidad: 'Cantidad',
    ayuda: '',
    defecto: 1,
    min: 1,
    max: Number.POSITIVE_INFINITY,
};

export function tipoBeneficioDe(key) {
    return TIPOS_BENEFICIO.find((t) => t.key === key) || TIPO_BENEFICIO_DESCONOCIDO;
}

// (tipo_beneficio, cantidad) -> texto humano, para MOSTRAR en pantalla:
//   'dias_gratis' + 5           -> '5 clases gratis'
//   'descuento_porcentaje' + 20 -> '20% de descuento'
//   'descuento_monto' + 10000   -> '$10.000 de descuento' (LEGADO: filas históricas)
// Es el MISMO formato que el correo (`email_service._beneficio_promocion_humano`), pero
// esto no es lógica de negocio: la oferta la decide el backend y el correo lo arma él.
// Acá sólo se pinta lo que ya se guardó.
export function textoBeneficio(tipoBeneficio, cantidad) {
    const n = Number(cantidad || 0);
    if (tipoBeneficio === 'dias_gratis') {
        return `${n} clase${n === 1 ? '' : 's'} gratis`;
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

// ── ¿Se puede pedir la vista previa del correo? ───────────────────────────────
// Los TRES datos del formulario: tipo, cantidad y vencimiento. El tipo y la fecha
// arrancan con un valor, pero la cantidad la escribe el admin: a mitad de tipeo puede
// quedar vacía ("" o "2,"), y con un dato incompleto no hay oferta que previsualizar.
// La cantidad tiene que ser un entero DENTRO DEL RANGO del tipo (clases 1-15, % 1-100),
// la misma regla que valida el backend, para no pedir un preview que respondería 422.
export function promocionCompleta({ tipo = '', cantidad = '', vence = '' } = {}) {
    if (!tipo || !vence) return false;
    const entrada = tipoBeneficioDe(tipo);
    const n = Number(cantidad);
    return Number.isInteger(n) && n >= entrada.min && n <= entrada.max;
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
// Sin acentos, sin mayúsculas y sin espacios de sobra (mismo criterio que
// `utils/membresiasMes.js`): "NUÑEZ" y "nunez" encuentran a la misma persona.
const normalizarTexto = (texto) => String(texto ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();

// ¿La fila coincide con el texto buscado? Coincidencia PARCIAL contra el NOMBRE **o** el
// CORREO, sin distinguir mayúsculas ni acentos. Un término vacío no filtra nada.
export function coincideBusqueda(alumno, termino) {
    const buscado = normalizarTexto(termino);
    if (!buscado) return true;
    return normalizarTexto(alumno && alumno.nombre).includes(buscado)
        || normalizarTexto(alumno && alumno.correo).includes(buscado);
}

// ¿Hay algún filtro puesto? (para mostrar u ocultar el "Ver todos"). El texto buscado
// CUENTA: con algo escrito la tabla ya no muestra todos los inactivos.
export function hayFiltro({ estado = null, busqueda = '' } = {}) {
    return Boolean(estado) || normalizarTexto(busqueda) !== '';
}

// Los dos criterios se COMBINAN (el estado de la tarjeta que se clickeó + el texto del
// buscador) y ninguno es excluyente: el estado se prende y se apaga con el mismo clic y el
// texto se borra. Filtrar es SÓLO en memoria: la respuesta ya trae la lista completa.
export function filtrarAlumnos(alumnos, { estado = null, busqueda = '' } = {}) {
    const lista = Array.isArray(alumnos) ? alumnos : [];
    return lista.filter((alumno) => {
        if (estado && alumno.estado !== estado) return false;
        return coincideBusqueda(alumno, busqueda);
    });
}

// ── Listado por bloques (no se pintan los ~712 de una) ─────────────────────────
// La respuesta ya trae la lista completa, pero dibujar cientos de filas (o tarjetas, en
// el teléfono) de golpe congela el scroll. Se pinta el primer bloque y "Cargar 25 más"
// AGREGA el siguiente: lo que el admin ya está mirando no se reemplaza.
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

// ── Qué acción ofrece cada fila ────────────────────────────────────────────────
// OJO (2026-12): la lista son los CANDIDATOS del padrón de BoxMagic. `id` es el id de la
// cuenta REAL en el SaaS y viene en `null` mientras esa cuenta no exista (crear cuentas
// es un paso posterior, el día de la migración real). La oferta se cuelga del candidato
// (migración 080), así que esas cuentas NO son requisito para ofrecer ni para marcar.
// `tieneCuenta` queda sólo como dato informativo para la fila (mostrar "sin cuenta").
export function tieneCuenta(alumno) {
    return Boolean(alumno) && alumno.id !== null && alumno.id !== undefined;
}

// La oferta se configura cuando NO hay una vigente (sin oferta o con la ventana vencida).
// El requisito es el ESTADO, no tener cuenta: los desertores de BoxMagic todavía no
// tienen login y igual se les manda la oferta a su correo del padrón.
export function puedeConfigurarPromocion(alumno) {
    if (!alumno) return false;
    const estado = alumno.estado;
    return estado === 'sin_contactar' || estado === 'vencida';
}

// "Recuperado" sólo se marca con una oferta VIGENTE (el backend responde 404 si no la
// hay), así el panel no ofrece un botón que va a fallar. Tampoco exige cuenta.
export function puedeMarcarRecuperado(alumno) {
    if (!alumno) return false;
    return alumno.estado === 'promocion_enviada';
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
