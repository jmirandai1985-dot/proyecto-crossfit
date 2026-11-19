// ── Familias de formulario de entrenamiento ────────────────────────────────
// Las 6 familias son FIJAS (agregar una nueva requiere código en el modal).
// El admin elige la familia de cada disciplina; el modal del coach usa ese valor
// para decidir qué formulario mostrar. Sin React ni imports de Vite: este módulo
// también lo consumen los tests unitarios de Node.
export const TIPOS_FORMULARIO = [
    { valor: 'wod_metcon', etiqueta: 'WOD / Metcon' },
    { valor: 'fuerza', etiqueta: 'Fuerza (series x repeticiones)' },
    { valor: 'secuencia', etiqueta: 'Secuencia de bloques' },
    { valor: 'rounds_tecnica', etiqueta: 'Rounds + técnica' },
    { valor: 'intervalos', etiqueta: 'Intervalos' },
    { valor: 'libre', etiqueta: 'Libre' },
];

export const TIPO_FORMULARIO_DEFAULT = 'wod_metcon';
const VALORES = new Set(TIPOS_FORMULARIO.map((tipo) => tipo.valor));

export const normalizarTipoFormulario = (valor) => (
    VALORES.has(valor) ? valor : TIPO_FORMULARIO_DEFAULT
);

export const etiquetaTipoFormulario = (valor) => (
    TIPOS_FORMULARIO.find((tipo) => tipo.valor === valor)?.etiqueta || 'WOD / Metcon'
);

// `tipo_metcon` es texto libre en la BD. Para las familias nuevas usamos una
// etiqueta estable (la misma que se muestra en los badges del alumno/coach).
export const ETIQUETA_METCON_FAMILIA = {
    fuerza: 'Fuerza',
    secuencia: 'Secuencia',
    rounds_tecnica: 'Rounds + técnica',
    intervalos: 'Intervalos',
    libre: 'Libre',
};

/** Familia a partir del `tipo_metcon` que guardó el WOD (para editar). */
export const familiaDeEtiqueta = (etiqueta) => {
    const normalizado = String(etiqueta || '').trim().toLowerCase();
    if (normalizado === 'fuerza') return 'fuerza';
    if (normalizado === 'secuencia') return 'secuencia';
    if (normalizado.startsWith('rounds')) return 'rounds_tecnica';
    if (normalizado === 'intervalos') return 'intervalos';
    if (normalizado === 'libre') return 'libre';
    return null;
};

// ── Filas vacías de cada formulario ────────────────────────────────────────
export const filaFuerzaVacia = () => ({
    nombre: '', series: '', repeticiones: '', cargaTipo: 'peso', carga: '',
});

export const filaSecuenciaVacia = () => ({ nombre: '', descripcion: '' });
export const filaIntervalosVacia = () => ({ distancia: '', tiempo: '', ritmo: '' });

/**
 * Estado inicial de TODAS las familias (el modal guarda una copia por familia,
 * así cambiar de disciplina no borra lo que el coach ya había escrito).
 */
export const estadoFamiliasVacio = () => ({
    fuerza: { ejercicios: [filaFuerzaVacia()] },
    secuencia: { bloques: [filaSecuenciaVacia()] },
    rounds_tecnica: { rounds: '', duracion: '', foco: '' },
    intervalos: { series: [filaIntervalosVacia()] },
    libre: { titulo: '', descripcion: '' },
});

// ── Parseo de los bloques guardados (para precargar la edición) ────────────
const lineas = (texto) => String(texto || '')
    .split('\n').map((linea) => linea.trim()).filter(Boolean);

const valorDeEtiqueta = (texto, etiqueta) => {
    const prefijo = `${etiqueta.toLowerCase()}:`;
    const linea = lineas(texto).find((item) => item.toLowerCase().startsWith(prefijo));
    return linea ? linea.slice(etiqueta.length + 1).trim() : '';
};

const textoDespuesDeEtiqueta = (texto, etiqueta) => {
    const prefijo = `${etiqueta.toLowerCase()}:`;
    const filas = lineas(texto);
    const indice = filas.findIndex((item) => item.toLowerCase().startsWith(prefijo));
    if (indice < 0) return '';
    const primera = filas[indice].slice(etiqueta.length + 1).trim();
    return [primera, ...filas.slice(indice + 1)].filter(Boolean).join('\n');
};

const cargaDesdeTexto = (texto) => {
    const valor = String(texto || '').trim();
    const porcentaje = valor.match(/^([\d.,]+)\s*%\s*(?:RM)?$/i);
    if (porcentaje) return { cargaTipo: 'porcentaje', carga: porcentaje[1] };
    const kilos = valor.match(/^([\d.,]+)\s*(?:kg)?$/i);
    if (kilos) return { cargaTipo: 'peso', carga: kilos[1] };
    return { cargaTipo: 'peso', carga: valor };
};

const fuerzaDesdeBloque = (bloque) => ({
    nombre: bloque.titulo || '',
    series: valorDeEtiqueta(bloque.descripcion, 'Series'),
    repeticiones: valorDeEtiqueta(bloque.descripcion, 'Repeticiones'),
    ...cargaDesdeTexto(valorDeEtiqueta(bloque.descripcion, 'Carga')),
});

const intervaloDesdeBloque = (bloque) => ({
    distancia: valorDeEtiqueta(bloque.descripcion, 'Distancia'),
    tiempo: valorDeEtiqueta(bloque.descripcion, 'Tiempo'),
    ritmo: valorDeEtiqueta(bloque.descripcion, 'Ritmo'),
});

/**
 * Precarga las familias desde un WOD ya publicado. Usa las filas de
 * `wod_bloques` (estructura existente) y el `tipo_metcon` para saber a qué
 * familia pertenece. Un WOD de metcon no llena ninguna de estas familias.
 */
export const familiasDesdeWod = (wod) => {
    const estado = estadoFamiliasVacio();
    const familia = familiaDeEtiqueta(wod?.tipo_metcon);
    if (!familia) return estado;

    const bloques = [...(wod?.bloques || [])]
        .sort((a, b) => (a.orden || 0) - (b.orden || 0));

    if (familia === 'fuerza') {
        const ejercicios = bloques.map(fuerzaDesdeBloque);
        if (ejercicios.length) estado.fuerza.ejercicios = ejercicios;
    } else if (familia === 'secuencia') {
        const filas = bloques.map((bloque) => ({
            nombre: bloque.titulo || '',
            descripcion: bloque.descripcion || '',
        }));
        if (filas.length) estado.secuencia.bloques = filas;
    } else if (familia === 'rounds_tecnica') {
        const bloque = bloques[0];
        if (bloque) {
            estado.rounds_tecnica = {
                rounds: valorDeEtiqueta(bloque.descripcion, 'Rounds'),
                duracion: valorDeEtiqueta(bloque.descripcion, 'Duración por round'),
                foco: textoDespuesDeEtiqueta(bloque.descripcion, 'Foco técnico'),
            };
        }
    } else if (familia === 'intervalos') {
        const series = bloques.map(intervaloDesdeBloque);
        if (series.length) estado.intervalos.series = series;
    } else if (familia === 'libre') {
        estado.libre = {
            titulo: wod?.titulo || '',
            descripcion: wod?.wod_principal || '',
        };
    }
    return estado;
};

// ── Mapeo familia -> columnas existentes del WOD ───────────────────────────
// No se agregan columnas a `wods`: el detalle estructurado va en `wod_bloques`
// (titulo/tipo_metcon/descripcion) y `wod_principal` guarda un resumen legible.
const textoFuerza = (ejercicio) => {
    const filas = [];
    if (ejercicio.series) filas.push(`Series: ${ejercicio.series}`);
    if (ejercicio.repeticiones) filas.push(`Repeticiones: ${ejercicio.repeticiones}`);
    if (ejercicio.carga) {
        filas.push(`Carga: ${ejercicio.carga}${ejercicio.cargaTipo === 'porcentaje' ? ' % RM' : ' kg'}`);
    }
    return filas.join('\n');
};

const textoIntervalo = (serie) => [
    serie.distancia ? `Distancia: ${serie.distancia}` : '',
    serie.tiempo ? `Tiempo: ${serie.tiempo}` : '',
    serie.ritmo ? `Ritmo: ${serie.ritmo}` : '',
].filter(Boolean).join('\n');

/**
 * Convierte el estado de una familia al payload que ya acepta
 * `POST /wods/batch-create` / `PUT /wods/{id}`.
 *
 * `bloques` es la estructura existente: un bloque por ejercicio/postura/serie.
 * `wod_principal` queda como resumen corto para las pantallas que muestran una
 * línea; el detalle completo viaja en los bloques (que el alumno ya ve).
 */
export const mapearFamiliaAWod = (tipoFormulario, datos) => {
    const tipo = normalizarTipoFormulario(tipoFormulario);
    const etiqueta = ETIQUETA_METCON_FAMILIA[tipo];
    const base = {
        titulo: etiqueta || null,
        calentamiento: '',
        fuerza_habilidad: '',
        wod_principal: '',
        tipo_metcon: etiqueta || null,
        descripcion: '',
        bloques: [],
    };
    if (!datos || tipo === TIPO_FORMULARIO_DEFAULT) return base;

    if (tipo === 'fuerza') {
        const ejercicios = (datos.ejercicios || []).filter((e) => e.nombre?.trim());
        base.titulo = 'Fuerza';
        base.wod_principal = ejercicios.length
            ? `${ejercicios.length} ejercicio(s) de fuerza`
            : '';
        base.bloques = ejercicios.map((ejercicio, indice) => ({
            orden: indice + 1,
            titulo: ejercicio.nombre.trim(),
            tipo_metcon: 'Fuerza',
            descripcion: textoFuerza(ejercicio) || null,
        }));
    } else if (tipo === 'secuencia') {
        const bloques = (datos.bloques || []).filter((b) => b.nombre?.trim());
        base.titulo = 'Secuencia';
        base.wod_principal = bloques.length ? `${bloques.length} bloque(s) de secuencia` : '';
        base.bloques = bloques.map((bloque, indice) => ({
            orden: indice + 1,
            titulo: bloque.nombre.trim(),
            tipo_metcon: 'Secuencia',
            descripcion: bloque.descripcion?.trim() || null,
        }));
    } else if (tipo === 'rounds_tecnica') {
        const rounds = String(datos.rounds || '').trim();
        const duracion = String(datos.duracion || '').trim();
        const foco = String(datos.foco || '').trim();
        base.titulo = 'Rounds + técnica';
        base.wod_principal = [rounds ? `${rounds} rounds` : '', duracion]
            .filter(Boolean).join(' · ');
        if (rounds || duracion || foco) {
            base.bloques = [{
                orden: 1,
                titulo: rounds ? `${rounds} rounds` : 'Rounds técnicos',
                tipo_metcon: 'Rounds + técnica',
                descripcion: [
                    rounds ? `Rounds: ${rounds}` : '',
                    duracion ? `Duración por round: ${duracion}` : '',
                    foco ? `Foco técnico:\n${foco}` : '',
                ].filter(Boolean).join('\n') || null,
            }];
        }
    } else if (tipo === 'intervalos') {
        const series = (datos.series || []).filter(
            (serie) => serie.distancia?.trim() || serie.tiempo?.trim() || serie.ritmo?.trim(),
        );
        base.titulo = 'Intervalos';
        base.wod_principal = series.length ? `${series.length} serie(s) de intervalos` : '';
        base.bloques = series.map((serie, indice) => ({
            orden: indice + 1,
            titulo: `Serie ${indice + 1}`,
            tipo_metcon: 'Intervalos',
            descripcion: textoIntervalo(serie) || null,
        }));
    } else if (tipo === 'libre') {
        base.titulo = String(datos.titulo || '').trim() || 'Entrenamiento libre';
        base.wod_principal = String(datos.descripcion || '').trim();
    }
    return base;
};

/** Mensaje de error de la familia, o '' si está listo para publicar. */
export const validarFamilia = (tipoFormulario, datos) => {
    const tipo = normalizarTipoFormulario(tipoFormulario);
    if (tipo === TIPO_FORMULARIO_DEFAULT) return '';
    if (!datos) return 'Completa el formulario del entrenamiento.';

    if (tipo === 'fuerza'
        && !(datos.ejercicios || []).some((e) => e.nombre?.trim())) {
        return 'Agrega al menos un ejercicio con nombre.';
    }
    if (tipo === 'secuencia'
        && !(datos.bloques || []).some((b) => b.nombre?.trim())) {
        return 'Agrega al menos un bloque o postura con nombre.';
    }
    if (tipo === 'rounds_tecnica'
        && (!String(datos.rounds || '').trim() || !String(datos.duracion || '').trim())) {
        return 'Indica el número de rounds y la duración por round.';
    }
    if (tipo === 'intervalos'
        && !(datos.series || []).some(
            (serie) => serie.distancia?.trim() || serie.tiempo?.trim() || serie.ritmo?.trim(),
        )) {
        return 'Agrega al menos una serie con distancia, tiempo o ritmo.';
    }
    if (tipo === 'libre' && !String(datos.descripcion || '').trim()) {
        return 'Escribe la descripción del entrenamiento.';
    }
    return '';
};

// ── Formulario histórico de metcon: campos y PAYLOAD ───────────────────────
// POR QUÉ VIVE ACÁ: el `ModalPublicarWod` y la tarjeta "Publicar WOD" de la pestaña Clases
// del coach publican con el MISMO endpoint (`POST /wods/batch-create`) y tienen que mandar
// la MISMA forma de WOD. El payload se arma en UNA sola función —y no en cada pantalla—
// para que no se desincronicen; el módulo es JS puro (sin React ni Vite) para que el test
// unitario de Node pueda comparar la forma exacta sin navegador.

/** Tipos de metcon del formulario (los mismos valores históricos de `wods.tipo_metcon`). */
export const TIPOS_WOD = ['For Time', 'AMRAP', 'EMOM', 'Otro'];
/** Un bloque puede ser un metcon o un RM final (peso en kg). */
export const TIPOS_BLOQUE = ['For Time', 'AMRAP', 'EMOM', 'RM', 'Otro'];

/** Estado inicial del formulario (o los datos de un WOD ya publicado, para editarlo). */
export const formularioMetconVacio = (wod = null) => ({
    calentamiento: wod?.calentamiento || '',
    musculacion: wod?.fuerza_habilidad || '',
    wod_nombre: wod?.titulo || '',
    wod_tipo: wod?.tipo_metcon || TIPOS_WOD[0],
    wod_descripcion: wod?.wod_principal || '',
});

/** Bloques EDITABLES a partir de los bloques guardados de un WOD (para editarlo). */
export const bloquesDesdeWod = (wod = null) => (wod?.bloques || []).map((bloque) => ({
    titulo: bloque.titulo || '',
    tipo_metcon: bloque.tipo_metcon || TIPOS_BLOQUE[0],
    descripcion: bloque.descripcion || '',
}));

/** Fila vacía del botón "+ Agregar bloque". */
export const bloqueVacio = () => ({
    titulo: '', tipo_metcon: TIPOS_BLOQUE[0], descripcion: '',
});

/**
 * Normaliza la lista de bloques antes de mandarla al backend: descarta las filas totalmente
 * vacías y renumera `orden` 1..N. "Otro" viaja como texto libre, igual que
 * `wods.tipo_metcon`.
 */
export const normalizarBloques = (lista) => (lista || [])
    .map((bloque, indice) => ({
        orden: indice + 1,
        titulo: (bloque?.titulo || '').trim() || null,
        tipo_metcon: bloque?.tipo_metcon || null,
        descripcion: (bloque?.descripcion || '').trim() || null,
    }))
    .filter((bloque) => bloque.titulo || bloque.descripcion);

/**
 * El WOD metcon que viaja en el payload (`POST /wods` · `POST /wods/batch-create`).
 * MISMA forma para el modal y para la tarjeta inline de la pestaña Clases: `titulo`,
 * `calentamiento`, `fuerza_habilidad`, `wod_principal`, `tipo_metcon` y `bloques`.
 */
export const contenidoMetconDesdeFormulario = (form, bloques = []) => ({
    titulo: (form?.wod_nombre || '').trim() || null,
    calentamiento: (form?.calentamiento || '').trim() || null,
    fuerza_habilidad: (form?.musculacion || '').trim() || null,
    wod_principal: (form?.wod_descripcion || '').trim(),
    tipo_metcon: form?.wod_tipo || 'Otro',
    bloques: normalizarBloques(bloques),
});

/** Mensaje de error del formulario de metcon, o '' si está listo para publicar. */
export const validarFormularioMetcon = (form) => (
    (form?.wod_descripcion || '').trim() ? '' : 'La descripción del WOD es obligatoria.'
);
