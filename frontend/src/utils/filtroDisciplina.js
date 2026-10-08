// Filtro por disciplina, compartido por "Mis Reservas" y "Clases disponibles"
// del Inicio móvil (<768px).
//
// POR QUÉ EXISTE: las dos pantallas pintan los MISMOS chips ("Todas" + cada
// disciplina), recuerdan lo último elegido durante la sesión y aplican el mismo
// criterio de coincidencia. Antes vivía copiado dentro de MisReservas; acá está
// una sola vez (util = cálculo; components/FiltroDisciplina = pintado;
// hooks/useFiltroDisciplina = estado + memoria de sesión).
//
// La disciplina SIEMPRE sale del `disciplina_nombre` que ya devuelve el backend
// (`GET /reservas` y `GET /clases`): no hay catálogo propio ni datos inventados.

export const TODAS = 'Todas';

// Fila sin disciplina informada (dato incompleto del backend).
export const SIN_DISCIPLINA = 'Sin disciplina';

// Claves de sesión: cada pantalla recuerda SU última elección por separado
// (elegir "CrossFit" en el Inicio no cambia el filtro de Mis Reservas).
export const CLAVE_FILTRO_INICIO = 'ub-inicio.disciplina';
export const CLAVE_FILTRO_RESERVAS = 'misReservas.disciplina';

export const disciplinaDe = (fila) => fila?.disciplina_nombre || SIN_DISCIPLINA;

// Disciplinas presentes en las filas: deduplicadas y ordenadas alfabéticamente
// (es-CL, para que "Á" no caiga al final).
export const disciplinasDe = (filas) => Array.from(new Set((filas || []).map(disciplinaDe)))
    .sort((a, b) => a.localeCompare(b, 'es'));

// Los chips sólo aportan con más de una disciplina: con una sola, "Todas" y esa
// disciplina devolverían exactamente la misma lista.
export const hayQueFiltrar = (disciplinas) => (disciplinas || []).length > 1;

// Lo recordado se ignora si ya no existe entre las disciplinas de la pantalla
// (p. ej. cambió el día elegido): en ese caso cae a "Todas".
export const filtroEfectivo = (recordado, disciplinas) => (
    recordado === TODAS || (disciplinas || []).includes(recordado) ? recordado : TODAS
);

export const coincideDisciplina = (fila, filtro) => (
    filtro === TODAS || disciplinaDe(fila) === filtro
);

export const filtrarPorDisciplina = (filas, filtro) => (
    (filas || []).filter((fila) => coincideDisciplina(fila, filtro))
);

// ── Memoria de la sesión (sessionStorage) ────────────────────────────────────
export const leerRecordado = (clave) => {
    try {
        return sessionStorage.getItem(clave) || TODAS;
    } catch {
        return TODAS;   // sessionStorage no disponible: se arranca en "Todas"
    }
};

export const recordar = (clave, valor) => {
    try {
        sessionStorage.setItem(clave, valor);
    } catch {
        // Sin sessionStorage el filtro sigue funcionando; sólo no se recuerda.
    }
};
