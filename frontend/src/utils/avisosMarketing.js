// ─── Avisos de marketing: la ÚNICA definición de tipos, colores y rótulos ───
//
// Lo comparten la pantalla Marketing del admin (bloque 2) y el carrusel
// "Novedades del box" del Inicio del alumno (bloque 4). Si el color de
// "Promoción" se cambiara en un solo lado, el botón del admin y la tarjeta del
// alumno dejarían de coincidir: por eso vive acá y no en cada pantalla.
//
// Los `id` son ESPEJO del CHECK `ck_avisos_marketing_tipo` del backend
// (`app/models/aviso_marketing.py`) y los colores, del mockup
// `mockup/carrusel-marketing.html`.
//
// JS PURO (sin JSX) a propósito: `scripts/test-marketing.mjs` lo importa con Node.

// Los 5 tipos que existen. Los 4 primeros son los del selector "Nuevo aviso"
// (el mockup muestra 4 botones); `producto_bazar` NO se elige a mano: lo crea y
// lo mantiene el Bazar cuando el admin publica un producto con días de anuncio.
export const TIPOS_AVISO = [
    {
        id: 'promocion',
        // `label` = botón del admin; `tag` = rótulo de la tarjeta del alumno
        // (el mockup los escribe distinto: "Promoción" / "Promoción").
        label: 'Promoción',
        tag: 'Promoción',
        acento: '#d9472e',
        icono: 'disco',
    },
    {
        id: 'colaboracion',
        label: 'Colaboración',
        tag: 'Colaboración',
        acento: '#2f6b52',
        icono: 'mancuernas',
    },
    {
        id: 'aviso',
        // El del mockup dice "Aviso del box": es el aviso operativo del propio box
        // (mantenciones, cambios de horario), no una promoción.
        label: 'Aviso',
        tag: 'Aviso del box',
        acento: '#e8a93b',
        icono: 'megafono',
    },
    {
        id: 'evento',
        label: 'Evento',
        tag: 'Evento',
        acento: '#7a5fc9',
        icono: 'barra',
    },
    {
        id: 'producto_bazar',
        label: 'Producto del Bazar',
        tag: 'Nuevo en la tienda',
        acento: '#3b72f6',
        icono: 'carrito',
    },
];

// El fallback NUNCA debe ser undefined: un tipo nuevo en la BD (o un dato viejo)
// no puede romper el carrusel del alumno ni la tabla del admin.
export const TIPO_POR_DEFECTO = {
    id: 'promocion',
    label: 'Aviso',
    tag: 'Aviso',
    acento: '#d9472e',
    icono: 'disco',
};

// Los 4 que el admin puede crear/editar (espejo de TIPOS_EDITABLES del backend).
export const TIPOS_EDITABLES = TIPOS_AVISO.filter((tipo) => tipo.id !== 'producto_bazar');
export const IDS_EDITABLES = TIPOS_EDITABLES.map((tipo) => tipo.id);

const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
    'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

// El carrusel del alumno muestra "Nuevo en la tienda" para los productos y los
// avisos del box con su propio rótulo: un solo lugar decide el texto.
export function tipoDe(id) {
    return TIPOS_AVISO.find((tipo) => tipo.id === id) || TIPO_POR_DEFECTO;
}

export function etiquetaTipo(id) {
    return tipoDe(id).tag;
}

export function acentoDeTipo(id) {
    return tipoDe(id).acento;
}

// El mismo acento con alfa, para el tinte del botón activo y de la tarjeta. El
// mockup usa `color-mix(in srgb, ... 18%, fondo)`: acá se arma el `rgba` a mano
// para que funcione igual en cualquier navegador.
export function tinteDeAcento(acento, alfa = 0.18) {
    const hex = String(acento || '').replace('#', '');
    if (!/^[0-9a-fA-F]{6}$/.test(hex)) return TIPO_POR_DEFECTO.acento;
    const numero = parseInt(hex, 16);
    const tonos = [(numero >> 16) & 255, (numero >> 8) & 255, numero & 255];
    return `rgba(${tonos[0]}, ${tonos[1]}, ${tonos[2]}, ${alfa})`;
}

export function esTipoEditable(id) {
    return IDS_EDITABLES.includes(id);
}

export function formatearFechaCorta(valor) {
    // Se parte del día CHILENO en texto ('YYYY-MM-DD'): un 'YYYY-MM-DD' pelado
    // (la fecha de un evento) no se corre, y un instante con hora se lee en
    // America/Santiago.
    const iso = aInputFecha(valor);
    if (!iso) return '';
    const [, mes, dia] = iso.split('-');
    return `${Number(dia)} ${MESES_CORTOS[Number(mes) - 1]}`;
}

// La fecha GRANDE del evento ("25 / OCT"): día y mes por separado.
export function formatearFechaEvento(valor) {
    const iso = aInputFecha(valor);
    if (!iso) return null;
    const [, mes, dia] = iso.split('-');
    return {
        dia: String(Number(dia)),
        mes: MESES_CORTOS[Number(mes) - 1].toUpperCase(),
    };
}

// Acepta un ISO del backend ("2026-10-31T23:59:59-03:00") o un "YYYY-MM-DD" de
// un <input type="date">. Devuelve null si no hay fecha usable (nunca un
// "Invalid Date" que se dibujaría como "NaN NaN").
export function aFecha(valor) {
    if (!valor) return null;
    const fecha = valor instanceof Date ? valor : new Date(valor);
    return Number.isNaN(fecha.getTime()) ? null : fecha;
}

// ── Vigencia ───────────────────────────────────────────────────────────────
// El "día de Chile" es el del backend (`vigente_desde`/`vigente_hasta` se guardan
// como 00:00 / 23:59:59 hora de Chile). El navegador puede estar en otra zona,
// así que el día se recorta con Intl en America/Santiago y no con la TZ local.
const FMT_CHILE = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Santiago', year: 'numeric', month: '2-digit', day: '2-digit',
});
const SOLO_FECHA = /^\d{4}-\d{2}-\d{2}$/;

function _diaChile(fecha) {
    const partes = FMT_CHILE.formatToParts(fecha);
    const parte = (tipo) => (partes.find((p) => p.type === tipo) || {}).value || '';
    return `${parte('year')}-${parte('month')}-${parte('day')}`;
}

// "YYYY-MM-DD" del día chileno: es el valor de un <input type="date"> y también
// lo que compara la validación del formulario.
export function aInputFecha(valor) {
    if (typeof valor === 'string' && SOLO_FECHA.test(valor)) return valor;
    const fecha = aFecha(valor);
    return fecha ? _diaChile(fecha) : '';
}

export function estadoVigencia(aviso, ahora = new Date()) {
    const desde = aFecha(aviso?.vigente_desde);
    const hasta = aFecha(aviso?.vigente_hasta);
    if (!desde || !hasta) return 'programado';
    if (ahora < desde) return 'programado';
    if (ahora > hasta) return 'vencido';
    return 'vigente';
}

export function estaVigente(aviso, ahora = new Date()) {
    return estadoVigencia(aviso, ahora) === 'vigente';
}

// El pie de la tarjeta, tal como lo escribe el mockup:
//   Promoción     -> "Hasta 31 oct"  (la promo muestra su fecha de cierre)
//   Colaboración  -> "Vigente"       (una alianza no muestra fecha de cierre)
//   Aviso del box -> "18 oct"        (la fecha del aviso, pelada)
//   Evento        -> ''              (usa la fecha GRANDE de la esquina)
//   Producto      -> ''              (usa el precio)
export function resumenVigencia(aviso, ahora = new Date()) {
    const estado = estadoVigencia(aviso, ahora);
    const tipo = tipoDe(aviso?.tipo).id;

    if (tipo === 'evento' || tipo === 'producto_bazar') return '';
    if (tipo === 'colaboracion') {
        if (estado === 'vigente') return 'Vigente';
        return estado === 'programado'
            ? `Desde ${formatearFechaCorta(aviso.vigente_desde)}` : 'Vencido';
    }
    // El aviso del box muestra su fecha pelada ("18 oct"); la promoción, hasta
    // cuándo corre ("Hasta 31 oct").
    if (tipo === 'aviso') {
        if (estado === 'vigente') return formatearFechaCorta(aviso.vigente_hasta);
        return estado === 'programado'
            ? `Desde ${formatearFechaCorta(aviso.vigente_desde)}` : 'Vencido';
    }
    if (estado === 'vigente') return `Hasta ${formatearFechaCorta(aviso.vigente_hasta)}`;
    if (estado === 'programado') return `Desde ${formatearFechaCorta(aviso.vigente_desde)}`;
    return 'Vencido';
}

// ── El formulario del admin ────────────────────────────────────────────────
// Todo lo que el modal necesita para armar el payload vive acá, para que las
// reglas del backend (`app/services/avisos_marketing.py: validar`) tengan un
// espejo en el front: la pantalla avisa al instante y el backend sigue siendo
// el que decide.

export function hoyISO(ahora = new Date()) {
    return _diaChile(ahora);
}

export function sumarDiasISO(iso, dias) {
    // Aritmética de CALENDARIO sobre los componentes (UTC de ida y vuelta): si se
    // pasara por `new Date('2026-10-01')` + TZ local, en Chile devolvería el 30
    // de septiembre y el día se comería uno.
    const partes = /^(\d{4})-(\d{2})-(\d{2})$/.exec(aInputFecha(iso));
    if (!partes) return '';
    const fecha = new Date(Date.UTC(
        Number(partes[1]), Number(partes[2]) - 1, Number(partes[3])));
    fecha.setUTCDate(fecha.getUTCDate() + dias);
    return [
        fecha.getUTCFullYear(),
        String(fecha.getUTCMonth() + 1).padStart(2, '0'),
        String(fecha.getUTCDate()).padStart(2, '0'),
    ].join('-');
}

// Ventana por defecto de un aviso nuevo: empieza hoy y dura 30 días (un mes de
// anuncio). El admin la estira o la acorta antes de crear.
export const DIAS_VIGENCIA_POR_DEFECTO = 30;

export function avisoVacio(ahora = new Date()) {
    const desde = hoyISO(ahora);
    return {
        tipo: 'promocion',
        titulo: '',
        texto: '',
        nombre_aliado: '',
        fecha_evento: '',
        vigente_desde: desde,
        vigente_hasta: sumarDiasISO(desde, DIAS_VIGENCIA_POR_DEFECTO),
        fijado_arriba: false,
    };
}

// Un aviso del backend -> el formulario (los días de Chile, no los del navegador).
export function aFormulario(aviso) {
    return {
        tipo: aviso?.tipo || 'promocion',
        titulo: aviso?.titulo || '',
        texto: aviso?.texto || '',
        nombre_aliado: aviso?.nombre_aliado || '',
        fecha_evento: aInputFecha(aviso?.fecha_evento),
        vigente_desde: aInputFecha(aviso?.vigente_desde),
        vigente_hasta: aInputFecha(aviso?.vigente_hasta),
        fijado_arriba: !!aviso?.fijado_arriba,
    };
}

export function validarAviso(datos) {
    const errores = {};
    if (!esTipoEditable(datos?.tipo)) errores.tipo = 'Elige un tipo de aviso.';

    const titulo = (datos?.titulo || '').trim();
    if (!titulo) errores.titulo = 'El título es obligatorio.';
    else if (titulo.length > 150) errores.titulo = 'Máximo 150 caracteres.';

    const texto = (datos?.texto || '').trim();
    if (!texto) errores.texto = 'El texto es obligatorio.';
    else if (texto.length > 1000) errores.texto = 'Máximo 1000 caracteres.';

    if (!datos?.vigente_desde || !datos?.vigente_hasta) {
        errores.vigencia = 'Elige desde y hasta cuándo se muestra.';
    } else if (datos.vigente_hasta < datos.vigente_desde) {
        // Los dos son "YYYY-MM-DD": comparar como texto ya es comparar fechas.
        errores.vigencia = 'La vigencia no puede terminar antes de empezar.';
    }

    if (datos?.tipo === 'colaboracion' && !(datos.nombre_aliado || '').trim()) {
        errores.nombre_aliado = 'Escribe el nombre del aliado.';
    }
    if (datos?.tipo === 'evento' && !datos.fecha_evento) {
        errores.fecha_evento = 'Elige la fecha del evento.';
    }
    return errores;
}

export function hayErrores(errores) {
    return Object.keys(errores || {}).length > 0;
}

// POST /marketing es multipart: los campos van como texto y el flyer como `file`.
export function construirFormData(datos, archivo) {
    const formData = new FormData();
    formData.append('tipo', datos.tipo);
    formData.append('titulo', (datos.titulo || '').trim());
    formData.append('texto', (datos.texto || '').trim());
    formData.append('vigente_desde', datos.vigente_desde);
    formData.append('vigente_hasta', datos.vigente_hasta);
    formData.append('fijado_arriba', datos.fijado_arriba ? 'true' : 'false');
    // Los campos por tipo viajan sólo cuando aplican: el backend igual los apaga.
    if (datos.tipo === 'colaboracion') {
        formData.append('nombre_aliado', (datos.nombre_aliado || '').trim());
    }
    if (datos.tipo === 'evento') {
        formData.append('fecha_evento', datos.fecha_evento);
    }
    if (archivo) formData.append('file', archivo);
    return formData;
}

// PUT /marketing/{id} es JSON y REEMPLAZA los campos editables (mismo payload).
export function payloadEdicion(datos) {
    return {
        tipo: datos.tipo,
        titulo: (datos.titulo || '').trim(),
        texto: (datos.texto || '').trim(),
        nombre_aliado: datos.tipo === 'colaboracion'
            ? (datos.nombre_aliado || '').trim() : null,
        fecha_evento: datos.tipo === 'evento' ? (datos.fecha_evento || null) : null,
        vigente_desde: datos.vigente_desde,
        vigente_hasta: datos.vigente_hasta,
        fijado_arriba: !!datos.fijado_arriba,
    };
}

// El `detail` de FastAPI puede ser un string (400 con los errores juntos) o una
// lista (422 de validación de Pydantic): la pantalla muestra un solo mensaje.
export function mensajeDeError(error, porDefecto = 'No se pudo guardar el aviso.') {
    const detalle = error?.response?.data?.detail;
    if (Array.isArray(detalle)) {
        return detalle.map((item) => item?.msg || String(item)).join(' ');
    }
    if (typeof detalle === 'string' && detalle) return detalle;
    return porDefecto;
}

// ── Los chips del panel ────────────────────────────────────────────────────
// Cuántos avisos están al aire hoy, cuántos esperan y cuántos ya pasaron: el
// MISMO `estadoVigencia` que pinta cada fila (una sola definición de vigente).
export function contarPorEstado(avisos, ahora = new Date()) {

    const conteo = { total: 0, vigentes: 0, programados: 0, vencidos: 0, fijados: 0 };
    for (const aviso of avisos || []) {
        conteo.total += 1;
        const estado = estadoVigencia(aviso, ahora);
        if (estado === 'vigente') conteo.vigentes += 1;
        else if (estado === 'programado') conteo.programados += 1;
        else conteo.vencidos += 1;
        if (aviso.fijado_arriba) conteo.fijados += 1;
    }
    return conteo;
}

