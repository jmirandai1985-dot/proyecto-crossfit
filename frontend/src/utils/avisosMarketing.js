// ─── Avisos de marketing: la ÚNICA definición de tipos, colores y rótulos ───
//
// Lo comparten la pantalla Marketing del admin (bloque 2) y el carrusel
// "Novedades del box" del Inicio del alumno (bloque 4). Si el color de
// "Promoción" se cambiara en un solo lado, el botón del admin y la tarjeta del
// alumno dejarían de coincidir: por eso vive acá y no en cada pantalla.
//
// El TERCER consumidor es el aviso rápido del coach (bloque 3, Gestión de Clases):
// reusa de acá la validación del mensaje y la vista previa del título (sección del
// final), pero NO elige tipo ni vigencia — eso lo fija el backend.
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
        // Tokens visuales de la tarjeta del carrusel (mockup, 145deg).
        fondo: 'linear-gradient(145deg, #2c1410, #1a0e0c)',
        tagFondo: '#d9472e',
        tagTexto: '#fff',
        titulo: '#f6e8e5',
        detalle: '#e8a08f',
    },
    {
        id: 'colaboracion',
        label: 'Colaboración',
        tag: 'Colaboración',
        acento: '#2f6b52',
        icono: 'mancuernas',
        fondo: 'linear-gradient(145deg, #1a2420, #101715)',
        tagFondo: '#2f6b52',
        tagTexto: '#eafff2',
        titulo: '#e9f3ee',
        // El verde de la marca del aliado.
        detalle: '#6fbf98',
    },
    {
        id: 'aviso',
        // El del mockup dice "Aviso del box": es el aviso operativo del propio box
        // (mantenciones, cambios de horario), no una promoción.
        label: 'Aviso',
        tag: 'Aviso del box',
        acento: '#e8a93b',
        icono: 'megafono',
        fondo: 'linear-gradient(145deg, #231f14, #15130d)',
        tagFondo: '#e8a93b',
        // Ámbar: el texto de la etiqueta va OSCURO (contraste del mockup).
        tagTexto: '#1a1608',
        titulo: '#f4edd8',
        detalle: '#e8a93b',
    },
    {
        id: 'evento',
        label: 'Evento',
        tag: 'Evento',
        acento: '#7a5fc9',
        icono: 'barra',
        fondo: 'linear-gradient(145deg, #1c1824, #111017)',
        tagFondo: '#7a5fc9',
        tagTexto: '#f2eeff',
        titulo: '#ece8f5',
        detalle: '#b9a3f5',
    },
    {
        id: 'producto_bazar',
        label: 'Producto del Bazar',
        tag: 'Nuevo en la tienda',
        acento: '#3b72f6',
        icono: 'carrito',
        fondo: 'linear-gradient(145deg, #1a1d26, #101217)',
        tagFondo: '#3b72f6',
        tagTexto: '#eaf0ff',
        titulo: '#e8ecfa',
        // El azul del precio y del "Ver todo en el Bazar".
        detalle: '#6f95ff',
    },
];

// ── La tarjeta FIJA de "Invita y Gana" (siempre la última del carrusel) ──────
// NO es un aviso de la BD ni la crea el admin: es una tarjeta propia del Inicio
// del alumno, con los mismos tokens visuales del carrusel. Va APARTE de
// `TIPOS_AVISO` a propósito: así no aparece en Marketing (el admin no la puede
// editar ni borrar) y `TIPOS_EDITABLES` sigue siendo espejo del backend.
export const TIPO_REFERIDOS = {
    id: 'referidos',
    label: 'Invita y Gana',
    tag: 'Trae a un amigo',
    acento: '#e6b54e',
    icono: 'regalo',
    fondo: 'linear-gradient(145deg, #3a2c10, #1a1408 62%)',
    tagFondo: '#e6b54e',
    // Dorado claro: el texto de la etiqueta va OSCURO (mismo criterio que el
    // ámbar de "Aviso del box").
    tagTexto: '#231a05',
    titulo: '#f8eed7',
    detalle: '#f3cf82',
};

// El texto de la tarjeta. No promete porcentajes: el beneficio depende de la
// configuración de referidos del box (Configuración → Referidos) y la pantalla
// `/alumno/invita-y-gana` es la que lo explica con los datos reales.
export const COPY_REFERIDOS = {
    titulo: 'Invita y Gana',
    texto: 'Comparte tu código con un amigo y que entrene con nosotros.',
    cta: 'Compartir mi código',
};

// El fallback NUNCA debe ser undefined: un tipo nuevo en la BD (o un dato viejo)
// no puede romper el carrusel del alumno ni la tabla del admin.
export const TIPO_POR_DEFECTO = {
    id: 'promocion',
    label: 'Aviso',
    tag: 'Aviso',
    acento: '#d9472e',
    icono: 'disco',
    fondo: 'linear-gradient(145deg, #2c1410, #1a0e0c)',
    tagFondo: '#d9472e',
    tagTexto: '#fff',
    titulo: '#f6e8e5',
    detalle: '#e8a08f',
};

// Los 4 que el admin puede crear/editar (espejo de TIPOS_EDITABLES del backend).
export const TIPOS_EDITABLES = TIPOS_AVISO.filter((tipo) => tipo.id !== 'producto_bazar');
export const IDS_EDITABLES = TIPOS_EDITABLES.map((tipo) => tipo.id);

// El tipo del AVISO RÁPIDO DEL DÍA: el único que publica un coach y el único que le toca ver
// en su Dashboard (Promoción, Colaboración y Evento son contenido del admin en Marketing).
// Espejo del `tipo` que fija el backend en `POST /marketing/aviso-rapido`
// (`app/services/avisos_marketing.py: payload_aviso_rapido`).
export const TIPO_AVISO_RAPIDO = 'aviso';

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

// ── El carrusel del Inicio del alumno (Bloque 4) ────────────────────────────
// El backend ya devuelve los avisos VIGENTES y ordenados (fijados primero y
// después el más nuevo). Acá sólo se decide CÓMO se dibujan:
//   * los avisos que escribió el admin, en ese orden;
//   * y al final las novedades de la tienda: el aviso de un producto suelto si
//     hay uno, o UNA tarjeta que los agrupa si hay varios (el mockup dibuja
//     "Llegaron poleras y polerones" con miniaturas y un "+N" cuando no caben).

export const MAX_MINIATURAS = 3;

export function agruparParaCarrusel(avisos) {
    const lista = avisos || [];
    const manuales = lista.filter((aviso) => aviso?.tipo !== 'producto_bazar');
    const productos = lista.filter((aviso) => aviso?.tipo === 'producto_bazar');

    const tarjetas = manuales.map((aviso) => ({ clase: 'aviso', aviso }));
    if (productos.length === 1) {
        tarjetas.push({ clase: 'producto', aviso: productos[0] });
    } else if (productos.length > 1) {
        tarjetas.push({
            clase: 'productos',
            avisos: productos,
            extra: Math.max(productos.length - MAX_MINIATURAS, 0),
        });
    }
    return tarjetas;
}

export function tituloDeGrupo(cantidad) {
    return `Llegaron ${cantidad} productos nuevos`;
}

// El título de una tarjeta. Un aviso de producto muestra el nombre ACTUAL del
// producto: el que quedó guardado en el aviso puede estar viejo si el admin lo
// renombró en el Bazar (la tarjeta se dibuja desde el JOIN, no desde el título).
export function tituloDeTarjeta(aviso) {
    if (aviso?.tipo === 'producto_bazar') {
        return aviso.producto_nombre || aviso.titulo || '';
    }
    return aviso?.titulo || '';
}

// El párrafo de la tarjeta: los productos no llevan (muestran su precio).
export function textoDeTarjeta(aviso) {
    if (aviso?.tipo === 'producto_bazar') return '';
    return aviso?.texto || '';
}

// El precio REAL del producto, en pesos ("$12.990"). Vacío en los otros tipos.
export function precioDeTarjeta(aviso) {
    if (aviso?.tipo !== 'producto_bazar' || aviso.producto_precio == null) return '';
    const numero = Number(aviso.producto_precio);
    if (!Number.isFinite(numero)) return '';
    return new Intl.NumberFormat('es-CL', {
        style: 'currency', currency: 'CLP', maximumFractionDigits: 0,
    }).format(numero);
}

// El texto chico bajo el precio (el mockup escribe exactamente esto).
export const PIE_PRODUCTO = 'Disponible en el Bazar';

// La foto del producto (NULL = la tarjeta dibuja el placeholder).
export function fotoDeTarjeta(aviso) {
    if (aviso?.tipo !== 'producto_bazar') return null;
    return aviso.producto_imagen_url || null;
}

// ¿Hay flyer que mostrar en el modal "Toca para ver el flyer"? Sólo los avisos
// manuales lo tienen: el de un producto muestra su foto en la tarjeta.
export function tieneFlyer(aviso) {
    return Boolean(aviso?.imagen_url);
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

// ── El aviso rápido del COACH (bloque 3, Gestión de Clases móvil) ────────────
// El coach escribe UNA caja de texto y publica un aviso que el alumnado ve HOY en su
// Inicio. Tipo (`aviso`), ventana (HOY, día de Chile) y título NO se eligen acá: los
// fija el backend en `POST /marketing/aviso-rapido`
// (`app/services/avisos_marketing.py: payload_aviso_rapido`). Por eso acá sólo hay
// validación espejo (para no mandar un POST vacío) y la vista previa del título.

// ESPEJO del `max_length=1000` del esquema `AvisoRapidoCrear` del backend.
export const MAX_TEXTO_RAPIDO = 1000;
// ESPEJO de `TITULO_RAPIDO_MAX` (`app/services/avisos_marketing.py`).
export const MAX_TITULO_RAPIDO = 60;

export function avisoRapidoVacio() {
    return { texto: '' };
}

export function validarAvisoRapido(datos) {
    const errores = {};
    const texto = (datos?.texto || '').trim();
    if (!texto) {
        errores.texto = 'Escribe el aviso que verán hoy los alumnos.';
    } else if (texto.length > MAX_TEXTO_RAPIDO) {
        errores.texto = `El aviso no puede pasar de ${MAX_TEXTO_RAPIDO} caracteres.`;
    }
    return errores;
}

// El cuerpo del POST: JSON y SÓLO el mensaje. A propósito NO lleva `tipo`,
// `vigente_desde`, `vigente_hasta` ni `fijado_arriba`: si el payload pudiera
// mandarlos, desde el panel del coach se podría publicar una Promoción de un mes o
// un Evento con fecha, que son contenido del admin.
export function payloadAvisoRapido(datos) {
    return { texto: (datos?.texto || '').trim() };
}

// La vista previa del título que va a derivar el backend: MISMA regla que
// `titulo_desde_texto` (primera frase, recorte por palabra y "…"), para que el coach
// vea cómo quedará la tarjeta antes de publicar. Si la regla cambia allá, cambia acá.
export function tituloRapidoDeTexto(texto, tope = MAX_TITULO_RAPIDO) {
    // Saltos de línea y espacios de más no llegan a la tarjeta: se aplanan.
    const plano = (texto || '').split(/\s+/).filter(Boolean).join(' ');
    if (!plano) return '';
    const cortes = ['.', '!', '?', ';']
        .map((signo) => plano.indexOf(signo))
        .filter((posicion) => posicion !== -1);
    let recorte = cortes.length ? plano.slice(0, Math.min(...cortes)).trim() : plano;
    if (recorte.length <= tope) return recorte;
    recorte = recorte.slice(0, tope).replace(/\s+$/, '');
    const ultimoEspacio = recorte.lastIndexOf(' ');
    if (ultimoEspacio > 0) recorte = recorte.slice(0, ultimoEspacio);
    return `${recorte}…`;
}

