// Consultas y mutaciones compartidas (React Query) de los datos que más se repetían.
//
// Las CLAVES viven acá y sólo acá: invalidar un prefijo (`['solicitudes']`) refresca de
// una vez todas las pantallas que muestran lo mismo, sin que cada página tenga que saber
// quién más usa ese dato.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';
// Los params del padrón de alumnos (rol, limit, skip, buscar) se arman con la misma
// función pura que valida `scripts/test-alumnos.mjs`: el request del escritorio y el de
// la vista móvil del padrón son exactamente el mismo.
import { paramsAlumnos } from '../utils/alumnos';

// Array vacío ESTABLE: es el fallback de las listas que devuelven las consultas. Un
// `|| []` nuevo en cada render invalidaría los `useMemo` que dependen de esos datos.
export const SIN_DATOS = [];

export const claves = {
    solicitudesPendientes: ['solicitudes', 'pendientes'],
    pendientesActivacion: ['alumnos', 'pendientes-activacion'],
    countPendientesActivacion: ['alumnos', 'pendientes-activacion', 'count'],
    stats: (tenantId) => ['reportes', tenantId],
    clasesHoy: ['asistencia', 'clases-hoy'],
    // Misma consulta del backend, pero SIN el filtro de `requiere_coach` que aplica la
    // tarjeta del panel admin (`useClasesHoy`): clave propia para que cada pantalla
    // reciba el dato que necesita sin pisarse.
    clasesAsistenciaHoy: ['asistencia', 'clases-hoy', 'todas'],
    // Detalle de UNA clase para marcar asistencia. Cuelga de `['asistencia']` para que
    // confirmar la asistencia refresque también la clase que está abierta.
    alumnosDeClase: (claseId) => ['asistencia', 'clase', claseId, 'alumnos'],
    churn: (tenantId, buscar) => ['kpis', 'churn', tenantId, buscar || ''],
    segmentacion: (tenantId) => ['segmentacion', tenantId],
    sugerencias: (tenantId, ids) => ['fidelizacion', 'sugerencias', tenantId, ids],
    // ── Bloque ALUMNO (Fase 2): datos que comparten varias pantallas del alumno ──
    // Inicio, Bazar, Mis pedidos, Mis reservas y Mi progreso piden el MISMO catálogo
    // y los mismos datos de base: con una sola queryKey, la segunda pantalla pinta al
    // instante y no vuelve a pedirlos (antes cada una tenía su useEffect).
    publicIdBox: ['tenants', 'me', 'public-id'],
    productos: (activo) => ['productos', activo === undefined ? 'todos' : String(activo)],
    // Avisos del carrusel "Novedades del box". DOS claves porque son DOS vistas del
    // mismo dato: la lista completa del admin (con su filtro) y los vigentes que
    // pinta el Inicio del alumno. Las dos cuelgan de `['marketing']`, así que
    // publicar o borrar un aviso refresca las dos sin que nadie lo recuerde.
    avisosMarketing: (filtro) => ['marketing', 'avisos', 'admin', filtro || 'todos'],
    avisosMarketingVigentes: ['marketing', 'avisos', 'vigentes'],
    configBox: (tenantId) => ['configuracion', tenantId],
    reservasAlumno: ['reservas', 'alumno'],
    miResumen: ['asistencia', 'mi-resumen'],
    misHitos: ['asistencia', 'mis-hitos'],
    misPedidos: ['pedidos', 'alumno'],
    // `['membresia']` = el plan/créditos del alumno (`/planes/membresia-activa`). Se
    // invalida al aprobarse un plan nuevo y al reservar/cancelar (los créditos bajan).
    membresia: ['membresia'],
    // ── Bloque 1 parte 2: marcas (RMs), historial y plan del alumno ──
    // `movimientos` (catálogo de ejercicios) y `rmsAlumno` los piden TRES pantallas
    // (Pizarra de RMs, Evolución y Performance Hub): con la misma clave, la segunda
    // que entra pinta al instante y no vuelve a pedirlos.
    movimientos: ['movimientos'],
    rmsAlumno: (alumnoId) => ['historial-rm', 'rms', alumnoId],
    historialRmTodos: (limite) => ['historial-rm', 'lista', limite],
    progresoDestacado: (alumnoId) => ['historial-rm', 'progreso', alumnoId],
    rmDeMovimiento: (alumnoId, movimientoId) => ['historial-rm', 'movimiento', alumnoId, movimientoId],
    nivelFuerza: (alumnoId) => ['historial-rm', 'nivel-fuerza', alumnoId],
    nivelGimnastico: (alumnoId) => ['historial-rm', 'nivel-gimnastico', alumnoId],
    // `planes/membresia-activa` es el plan/créditos del alumno: usa la MISMA familia
    // `['membresia']` que ya invalidan reservar/cancelar y la aprobación del plan.
    clasesRango: (desde, hasta, limite) => ['clases', 'rango', desde, hasta, limite],
    wodHoy: ['wods', 'hoy'],
    reservasConfirmadas: ['reservas', 'confirmadas'],
    asistenciaMes: ['asistencia', 'mes'],
    asistenciaSemanal: ['asistencia', 'semanal'],
    planesActivos: ['planes', 'activos'],
    miPerfil: ['alumnos', 'me'],
    misBeneficios: (planIds) => ['beneficios', 'mios', planIds],
    panelHistorial: (alumnoId, seccion, pagina, porPagina) =>
        ['historial-alumno', alumnoId || 'me', seccion, pagina, porPagina],
    // ── Bloque 2 (partes B y C): panel del coach ──
    // La Pizarra de WOD, el Dashboard del coach y Gestión de Clases piden LOS MISMOS
    // datos (catálogo de movimientos, clases, WODs, disciplinas y las reservas de una
    // clase). Todo `['clases']` lo mueven ampliar cupo y tomar/soltar; todo `['wods']`
    // lo mueven publicar/editar un WOD; `['reservas']` lo mueve la asistencia.
    clasesCoach: (coachId, desde, hasta) => ['clases', 'coach', coachId, desde, hasta],
    clasesDia: (fecha, limite) => ['clases', 'dia', fecha, limite],
    clasesDetalle: (claseId) => ['clases', 'detalle', claseId],
    clasesDisciplinaSemana: (disciplinaId, desde, hasta) =>
        ['clases', 'disciplina', disciplinaId, desde, hasta],
    wodsTodos: ['wods', 'todos'],
    wodsFecha: (fecha) => ['wods', 'fecha', fecha],
    wodDetalle: (wodId) => ['wods', 'detalle', wodId],
    // El backend acota las relaciones coach↔disciplina por el token e IGNORA cualquier
    // `coach_id` de la query (todos los coaches del box reciben la misma lista): por eso
    // la clave no lleva coachId y las dos pantallas comparten la MISMA entrada.
    coachDisciplinas: ['coach-disciplinas'],
    disciplinas: ['disciplinas'],
    alumnosCoach: (coachId) => ['fidelizacion', 'coach', coachId, 'alumnos'],
    alumnosCoachEnRiesgo: (coachId) => ['fidelizacion', 'coach', coachId, 'en-riesgo'],
    // Los DOS modales que monta el Dashboard del coach (Bloque 6): la ficha acotada del
    // alumno (P2) y el preview del correo de inactividad (P1). Cuelgan de `['fidelizacion']`,
    // la familia de las dos listas de arriba, así que refrescar la familia las alcanza.
    fichaAlumnoCoach: (coachId, alumnoId) =>
        ['fidelizacion', 'coach', coachId, 'alumno', alumnoId, 'ficha'],
    previewContactoCoach: (coachId, alumnoId) =>
        ['fidelizacion', 'coach', coachId, 'contactar', alumnoId, 'preview'],
    progresoAlumnosCoach: (ids) => ['historial-rm', 'progreso-lote', ids],
    reservasPorClase: (claseId) => ['reservas', 'por-clase', claseId],
    // ── Bloque 3 (parte A): catálogos y CRUD del panel admin ─────────────────
    // `usuariosRol` la piden Coaches y el modal de clase (los DOS llamaban a
    // `GET /usuarios/?rol=coach`): misma clave = una sola entrada y una sola llamada.
    // El rol va en la clave porque cambia la lista; el tenant lo pone el token.
    usuariosRol: (rol) => ['usuarios', 'rol', rol],
    // Grid semanal de horarios base: cuelga de `['horarios']` porque el CRUD de esa
    // pantalla es el único que lo mueve.
    gridSemanalHorarios: ['horarios', 'grid-semanal'],
    // Listado de clases del admin (`GET /clases/`). Cuelga de `['clases']`, el prefijo
    // que ya invalidan ampliar cupo, tomar/soltar y las acciones de clase.
    clasesAdmin: (disciplinaId) => ['clases', 'admin', disciplinaId || 'todas'],
    // TODOS los planes (activos e inactivos): los administra el admin. Comparte la
    // familia `['planes']` con `planesActivos`, así que invalidar el prefijo refresca
    // la vista del alumno y la del admin a la vez.
    planesTodos: ['planes', 'todos'],
    // Datos del box (`GET /tenants/me`): los usa "Mi QR" (public_id + nombre). Cuelga
    // de `['tenants','me']`, igual que el `public_id` que ya cachea `usePublicIdBox`.
    tenantMe: ['tenants', 'me'],
    // ── Bloque 3 (parte B): Reportes & Analytics ──────────────────────────────
    // El reporte en sí NO lleva clave nueva: `stats` (arriba) es la misma llamada
    // (`GET /reportes/?tenant_id=`) que ya comparten el Dashboard y esta pantalla.
    // Lo propio de Reportes son los movimientos de finanzas: un GET (plural) para
    // el detalle y un POST (singular) para registrar uno nuevo.
    // La clave NO lleva tenantId: el endpoint lo saca del token, igual que
    // `coachDisciplinas` y `productos` (todos los tenants reciben sólo lo suyo).
    transaccionesFinanzas: ['finanzas', 'transacciones'],
    // ── A5: padrón de alumnos (misma tabla en escritorio y en móvil) ─────────
    // El padrón paginado cuelga de `['usuarios']`, el prefijo que YA invalidan
    // `useGuardarUsuario` y `useDesactivarUsuario`: crear, editar o dar de baja un
    // alumno refresca la tabla sin que la pantalla vuelva a pedirla a mano. El rol,
    // el tamaño de página, la página y el término de búsqueda van en la clave porque
    // cambian el resultado; el tenant lo pone el token.
    alumnosPaginados: (rol, porPagina, pagina, buscar) =>
        ['usuarios', 'alumnos', rol, porPagina, pagina, buscar || ''],
    // Suscripciones ACTIVAS del box (`GET /suscripciones?estado=activo`): de acá salen
    // la columna "Plan Activo", los créditos de cada fila y el "¿ya tiene plan?" del
    // comprobante. Familia propia `['suscripciones']` (distinta de `['membresia']`,
    // que es la puerta del propio alumno).
    suscripcionesActivas: ['suscripciones', 'activas'],
    // Las de UN alumno: la consulta que hace el comprobante al abrirse.
    suscripcionesAlumno: (usuarioId) => ['suscripciones', 'alumno', usuarioId],
    // Descuento vigente del alumno y precio final de cada plan (lo calcula el backend).
    // Cuelga de `['beneficios']`, la familia que ya usa `useMisBeneficios`.
    beneficiosAlumno: (alumnoId, planIds) => ['beneficios', 'alumno', alumnoId, planIds],
};

// ── Colas de revisión del admin (las miran el Dashboard Y Pendientes de revisión) ──
// `refetchInterval` NO corre con la pestaña oculta (React Query pausa el intervalo
// solo): el mismo efecto que el `setInterval` + `visibilitychange` que había a mano.
export function useSolicitudesPendientes({ autoRefrescoMs = 0, staleTime = 15_000 } = {}) {
    return useQuery({
        queryKey: claves.solicitudesPendientes,
        queryFn: async () => (await api.get('/api/v1/solicitudes/pendientes')).data || [],
        staleTime,
        refetchInterval: autoRefrescoMs || false,
    });
}

export function usePendientesActivacion({ autoRefrescoMs = 0, staleTime = 15_000 } = {}) {
    return useQuery({
        queryKey: claves.pendientesActivacion,
        queryFn: async () => (await api.get('/api/v1/alumnos/pendientes-activacion')).data || [],
        staleTime,
        refetchInterval: autoRefrescoMs || false,
    });
}

export function useCountPendientesActivacion() {
    return useQuery({
        queryKey: claves.countPendientesActivacion,
        queryFn: async () =>
            (await api.get('/api/v1/alumnos/pendientes-activacion/count')).data?.count || 0,
        staleTime: 30_000,
    });
}

export function useStatsDashboard(tenantId) {
    return useQuery({
        queryKey: claves.stats(tenantId),
        queryFn: async () => (await api.get(`/api/v1/reportes/?tenant_id=${tenantId}`)).data,
        // Las tarjetas del dashboard cambian lento: 1 min de staleTime evita pedirlas
        // otra vez al ir a otra pantalla y volver.
        staleTime: 60_000,
        enabled: Boolean(tenantId),
    });
}

export function useClasesHoy({ autoRefrescoMs = 45_000 } = {}) {
    return useQuery({
        queryKey: claves.clasesHoy,
        queryFn: async () => {
            const res = await api.get('/api/v1/asistencia/clases-hoy');
            // Sólo las clases que exigen coach: el filtro que aplicaba el Dashboard.
            return (res.data || []).filter((c) => c.requiere_coach);
        },
        staleTime: 30_000,
        refetchInterval: autoRefrescoMs || false,
    });
}

// ── Asistencia del día (pestaña Asistencia: coach + admin) ───────────────────
// La MISMA consulta del backend, pero con la lista pelada: la pestaña muestra todas las
// clases del día de sus disciplinas. (El filtro de `requiere_coach` de `useClasesHoy` es
// una decisión de la tarjeta del panel admin, no del dato.)
export function useClasesAsistenciaHoy({ autoRefrescoMs = 0 } = {}) {
    return useQuery({
        queryKey: claves.clasesAsistenciaHoy,
        queryFn: async () => (await api.get('/api/v1/asistencia/clases-hoy')).data || [],
        staleTime: 30_000,
        refetchInterval: autoRefrescoMs || false,
    });
}

// Detalle de una clase: sus reservas y si la asistencia ya fue marcada.
export function useAlumnosDeClase(claseId) {
    return useQuery({
        queryKey: claves.alumnosDeClase(claseId),
        queryFn: async () => (await api.get(
            `/api/v1/asistencia/clases/${claseId}/alumnos`,
        )).data || {},
        staleTime: 30_000,
        enabled: Boolean(claseId),
    });
}

// Confirmar la asistencia de una clase: mueve la lista del día Y el detalle de la clase
// (las dos viven bajo `['asistencia']`), así que el panel del admin ve lo mismo al toque.
export function useConfirmarAsistenciaClase() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ claseId, asistencias }) => api.post(
            `/api/v1/asistencia/clases/${claseId}/confirmar`, { asistencias },
        ).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['asistencia'] }),
    });
}

// Ampliar el cupo de una clase (el backend valida permisos y el tope de +10). Cambia el
// cupo tanto en la lista de clases como en la del día que se está mostrando.
export function useAmpliarCupo() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ claseId, extra }) => api.post(
            `/api/v1/clases/${claseId}/ampliar-cupo`, { cupos_extra: extra },
        ).then((r) => r.data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['clases'] });
            qc.invalidateQueries({ queryKey: ['asistencia'] });
        },
    });
}

// Entregar un pedido del Bazar con el código de retiro. Lo usan el mesón del coach y el
// panel del admin (mismo modal): invalidar `['pedidos']` deja la lista del admin al día
// apenas el coach entrega.
export function useEntregarPedido() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (codigo) => api.post('/api/v1/pedidos/entregar', { codigo }).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['pedidos'] }),
    });
}

// ── Fidelización: el churn lo publica un job del BI (corre de noche) ──
export function useChurn(tenantId, buscar) {
    return useQuery({
        queryKey: claves.churn(tenantId, buscar),
        queryFn: async () => (await api.get('/api/v1/kpis/churn', {
            params: { buscar: buscar || undefined },
        })).data,
        // 5 min: buscar un término y volver no cuesta otra request, y la pantalla no
        // parpadea al cambiar el filtro (`keepPreviousData` deja la tabla anterior).
        staleTime: 5 * 60_000,
        placeholderData: keepPreviousData,
        enabled: Boolean(tenantId),
    });
}

export function useSugerenciasChurn(tenantId, ids) {
    const lista = (ids || []).slice(0, 300);
    return useQuery({
        queryKey: claves.sugerencias(tenantId, lista.join(',')),
        queryFn: async () => (await api.post('/api/v1/fidelizacion/sugerencias', {
            alumno_ids: lista,
        })).data?.sugerencias || {},
        // Sin sugerencias la tabla sigue (esa columna queda en "—"): no reintentar.
        retry: 0,
        staleTime: 5 * 60_000,
        enabled: Boolean(tenantId) && lista.length > 0,
    });
}

export function useSegmentacion(tenantId) {
    return useQuery({
        queryKey: claves.segmentacion(tenantId),
        queryFn: async () => (await api.get('/api/v1/segmentacion')).data || null,
        // Si el modelo todavía no se entrenó esto responde 0 elementos: no insistir.
        retry: 0,
        staleTime: 10 * 60_000,
        enabled: Boolean(tenantId),
    });
}

// ── Bloque ALUMNO (Fase 2): catálogo y datos compartidos ─────────────────────
// Las claves están arriba; acá van los hooks. Frescura por dato: el catálogo y los
// datos del box casi no cambian (60 s / 5 min); las reservas del alumno sí (15 s,
// y se invalidan al reservar/cancelar).
export function usePublicIdBox() {
    return useQuery({
        queryKey: claves.publicIdBox,
        queryFn: async () => (await api.get('/api/v1/tenants/me/public-id')).data?.public_id || null,
        staleTime: 5 * 60_000,
    });
}

export function useProductos({ activo } = {}) {
    return useQuery({
        queryKey: claves.productos(activo),
        queryFn: async () => (await api.get('/api/v1/productos', {
            params: activo === undefined ? undefined : { activo },
        })).data || [],
        staleTime: 60_000,
    });
}

export function useConfiguracionBancaria(tenantId) {
    return useQuery({
        queryKey: claves.configBox(tenantId),
        queryFn: async () => (await api.get('/api/v1/configuracion', {
            params: { tenant_id: tenantId },
        })).data,
        staleTime: 5 * 60_000,
        enabled: Boolean(tenantId),
    });
}

export function useReservasAlumno() {
    return useQuery({
        queryKey: claves.reservasAlumno,
        queryFn: async () => (await api.get('/api/v1/reservas')).data || [],
        staleTime: 15_000,
    });
}

export function useMiResumenAsistencia() {
    return useQuery({
        queryKey: claves.miResumen,
        queryFn: async () => (await api.get('/api/v1/asistencia/mi-resumen')).data || null,
        staleTime: 60_000,
    });
}

export function useMisHitos() {
    return useQuery({
        queryKey: claves.misHitos,
        queryFn: async () => (await api.get('/api/v1/asistencia/mis-hitos')).data || null,
        staleTime: 60_000,
    });
}

export function useMisPedidos() {
    return useQuery({
        queryKey: claves.misPedidos,
        queryFn: async () => (await api.get('/api/v1/pedidos')).data || [],
        staleTime: 30_000,
    });
}

// ── Mutaciones: mueven las DOS colas, así que invalidan por prefijo ──
function useInvalidarColas() {
    const qc = useQueryClient();
    return () => {
        // `['alumnos','pendientes-activacion']` cubre la lista y su conteo.
        qc.invalidateQueries({ queryKey: ['alumnos', 'pendientes-activacion'] });
        qc.invalidateQueries({ queryKey: ['solicitudes'] });
        qc.invalidateQueries({ queryKey: ['reportes'] });
    };
}

export function useAprobarSolicitud() {
    const invalidar = useInvalidarColas();
    return useMutation({
        mutationFn: (id) => api.put(`/api/v1/solicitudes/${id}/aprobar`).then((r) => r.data),
        onSuccess: invalidar,
    });
}

export function useRechazarSolicitud() {
    const invalidar = useInvalidarColas();
    return useMutation({
        mutationFn: ({ id, motivo }) => api.put(
            `/api/v1/solicitudes/${id}/rechazar?motivo=${encodeURIComponent(motivo || 'Rechazado')}`,
        ).then((r) => r.data),
        onSuccess: invalidar,
    });
}

export function useAccionAlumnoPendiente() {
    const invalidar = useInvalidarColas();
    return useMutation({
        mutationFn: ({ alumnoId, accion }) =>
            api.put(`/api/v1/alumnos/${alumnoId}/${accion}`).then((r) => r.data),
        onSuccess: invalidar,
    });
}

export function useMarcarGestionChurn() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ usuarioId, estado }) => api.put(
            `/api/v1/kpis/churn/${usuarioId}/estado`, { estado_gestion: estado },
        ).then((r) => r.data),
        // Cambia la fila de la tabla del churn y los contadores de gestión: se refresca
        // la familia entera de esa pantalla, no sólo el término buscado de turno.
        onSuccess: () => qc.invalidateQueries({ queryKey: ['kpis', 'churn'] }),
    });
}

// ── Mutaciones del ALUMNO ─────────────────────────────────────────────────────
// Cancelar una reserva mueve la MISMA caché que la lista de reservas (compartida
// por Inicio y Mis reservas) y los créditos del plan: se invalida por prefijo.
export function useCancelarReserva() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (reservaId) => api.delete(`/api/v1/reservas/${reservaId}`).then((r) => r.data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['reservas'] });
            // Bajar de cupo mueve el plan/créditos del alumno.
            qc.invalidateQueries({ queryKey: claves.membresia });
        },
    });
}

export function useCrearPedidoBazar() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/pedidos', payload).then((r) => r.data),
        // \"Mis pedidos\" se vuelve a pintar al crear uno (misma queryKey).
        onSuccess: () => qc.invalidateQueries({ queryKey: ['pedidos'] }),
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// BLOQUE 1 parte 2 — MARCAS (RMs), HISTORIAL Y PLAN DEL ALUMNO
// ══════════════════════════════════════════════════════════════════════════════
// Las pantallas de marcas (Pizarra de RMs, Evolución y Performance Hub) pedían con
// `useEffect` + `useState` los MISMOS tres datos: el catálogo de movimientos, los PRs
// del alumno y su historial. Al ser rutas `lazy`, cada navegación entre ellas volvía a
// pedir todo; acá comparten `queryKey`, así que la segunda pinta al instante.
//
// `staleTime`: el catálogo cambia cuando el box lo edita (5 min); los PRs y el
// historial los mueve el propio alumno desde la app, así que valen 30 s (y las
// mutaciones invalidan `['historial-rm']`). Los niveles/plan/beneficios cambian lento.

export function useMovimientos() {
    return useQuery({
        queryKey: claves.movimientos,
        queryFn: async () => (await api.get('/api/v1/movimientos')).data || [],
        staleTime: 300_000,
    });
}

export function useRmsAlumno(alumnoId) {
    return useQuery({
        queryKey: claves.rmsAlumno(alumnoId),
        queryFn: async () => (await api.get(`/api/v1/historial-rm/alumnos/${alumnoId}/rms`)).data || [],
        staleTime: 30_000,
        enabled: Boolean(alumnoId),
    });
}

export function useHistorialRmTodos(limite = 500) {
    return useQuery({
        // Sin filtro de alumno: el backend acota por JWT (el alumno recibe SÓLO los suyos).
        queryKey: claves.historialRmTodos(limite),
        queryFn: async () => (await api.get(`/api/v1/historial-rm?limit=${limite}`)).data || [],
        staleTime: 30_000,
    });
}

export function useProgresoDestacado(alumnoId) {
    return useQuery({
        queryKey: claves.progresoDestacado(alumnoId),
        queryFn: async () => (await api.get(
            `/api/v1/historial-rm/alumnos/${alumnoId}/progreso-destacado`,
        )).data || {},
        staleTime: 60_000,
        enabled: Boolean(alumnoId),
    });
}

export function useRmDeMovimiento(alumnoId, movimientoId) {
    return useQuery({
        queryKey: claves.rmDeMovimiento(alumnoId, movimientoId),
        queryFn: async () => (await api.get(
            `/api/v1/historial-rm/alumnos/${alumnoId}/movimiento/${movimientoId}`,
        )).data || [],
        staleTime: 30_000,
        // Sin movimiento elegido no se consulta nada (misma condición que el useEffect).
        enabled: Boolean(alumnoId) && Boolean(movimientoId),
    });
}

// Nivel de atleta: las DOS consultas son del mismo bloque y la pantalla las pide
// juntas; si una falla se trata aparte (Promise.allSettled en el Dashboard).
export function useNivelFuerza(alumnoId) {
    return useQuery({
        queryKey: claves.nivelFuerza(alumnoId),
        queryFn: async () => (await api.get(
            `/api/v1/historial-rm/alumnos/${alumnoId}/nivel-fuerza`,
        )).data || null,
        staleTime: 60_000,
        enabled: Boolean(alumnoId),
    });
}

export function useNivelGimnastico(alumnoId) {
    return useQuery({
        queryKey: claves.nivelGimnastico(alumnoId),
        queryFn: async () => (await api.get(
            `/api/v1/historial-rm/alumnos/${alumnoId}/nivel-gimnastico`,
        )).data || null,
        staleTime: 60_000,
        enabled: Boolean(alumnoId),
    });
}

// ── Clases, WOD del día y reservas del alumno ────────────────────────────────
export function useClasesRango(desde, hasta, limite = 500) {
    return useQuery({
        // Sin `solo_con_cupo`: el Dashboard del alumno muestra TODAS las clases del rango.
        queryKey: claves.clasesRango(desde, hasta, limite),
        // El backend puede envolver la lista (`{clases: [...]}`) o mandarla pelada: se
        // acepta lo mismo que aceptaba el Dashboard al leerla.
        queryFn: async () => {
            const data = (await api.get(
                `/api/v1/clases/?fecha_desde=${desde}&fecha_hasta=${hasta}&limit=${limite}`,
            )).data;
            const lista = data?.clases || data || [];
            return Array.isArray(lista) ? lista : [];
        },
        // El horario cambia poco; el cupo lo refresca la invalidación al reservar.
        staleTime: 60_000,
        enabled: Boolean(desde) && Boolean(hasta),
    });
}

export function useWodHoy() {
    return useQuery({
        queryKey: claves.wodHoy,
        queryFn: async () => (await api.get('/api/v1/wods/hoy')).data || null,
        staleTime: 5 * 60_000,
    });
}

export function useReservasConfirmadas() {
    return useQuery({
        queryKey: claves.reservasConfirmadas,
        queryFn: async () => {
        const data = (await api.get('/api/v1/reservas?estado=confirmada')).data;
        // Lista pelada (como la leía el Dashboard); si el backend la envuelve, la pantalla
        // no se llena de basura.
        return Array.isArray(data) ? data : [];
    },
        staleTime: 30_000,
    });
}

// Plan/créditos del alumno. Comparte la familia `['membresia']`: aprobar un plan,
// reservar o cancelar ya la invalidan (el cupo baja), sin código extra acá.
export function useMembresiaActiva() {
    return useQuery({
        queryKey: claves.membresia,
        queryFn: async () => (await api.get('/api/v1/planes/membresia-activa')).data || null,
        staleTime: 30_000,
    });
}

// ── Asistencia (tarjetas del Dashboard del alumno y gráfico de Evolución) ────
export function useAsistenciaMes() {
    return useQuery({
        queryKey: claves.asistenciaMes,
        queryFn: async () => (await api.get('/api/v1/reservas/asistencia-mes')).data || null,
        staleTime: 60_000,
    });
}

export function useAsistenciaSemanal() {
    return useQuery({
        queryKey: claves.asistenciaSemanal,
        queryFn: async () => (await api.get('/api/v1/reservas/asistencia-semanal')).data || [],
        staleTime: 60_000,
    });
}

// ── Planes, perfil y beneficios (Solicitar plan) ─────────────────────────────
export function usePlanesActivos() {
    return useQuery({
        queryKey: claves.planesActivos,
        // El backend puede envolver la lista (`{planes: [...]}`) o mandarla pelada:
        // se acepta lo mismo que aceptaba la pantalla.
        queryFn: async () => {
            const data = (await api.get('/api/v1/planes?activo=true')).data;
            const lista = data?.planes || data || [];
            return Array.isArray(lista) ? lista : [];
        },
        staleTime: 300_000,
    });
}

export function useMiPerfil() {
    return useQuery({
        queryKey: claves.miPerfil,
        queryFn: async () => (await api.get('/api/v1/alumnos/me')).data || null,
        staleTime: 60_000,
    });
}

export function useMisBeneficios(planIds) {
    return useQuery({
        queryKey: claves.misBeneficios(planIds),
        queryFn: async () => (await api.get('/api/v1/beneficios/mios', {
            params: { plan_ids: planIds },
        })).data || null,
        // El descuento no cambia mientras el alumno elige plan.
        staleTime: 300_000,
        enabled: Boolean(planIds),
    });
}

// ── Historial del alumno (`PanelHistorial`) ──────────────────────────────────
// Lo montan el alumno (`/alumno/mi-historial`) y la ficha del box con `alumnoId`.
export function usePanelHistorial({
    alumnoId = null, seccion = 'resumen', pagina = 1, porPagina = 10,
} = {}) {
    // Sin `alumnoId` se usa la puerta del propio alumno (nunca trae la gestión del box).
    const url = alumnoId
        ? `/api/v1/alumnos/${alumnoId}/historial`
        : '/api/v1/alumnos/me/historial';
    return useQuery({
        queryKey: claves.panelHistorial(alumnoId, seccion, pagina, porPagina),
        queryFn: async () => (await api.get(url, {
            params: { seccion, pagina, por_pagina: porPagina },
        })).data,
        staleTime: 30_000,
        // Al cambiar de sección/página se deja el panel anterior en pantalla hasta que
        // llega el nuevo (mismo criterio que la tabla de churn): sin parpadeo en blanco.
        placeholderData: keepPreviousData,
    });
}

// ── Mutaciones del alumno (Bloque 1 parte 2) ─────────────────────────────────
// Reservar mueve la MISMA caché que las listas de reservas (Dashboard e Inicio
// móvil), el cupo de las clases y los créditos del plan.
export function useCrearReserva() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/reservas', payload).then((r) => r.data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['reservas'] });
            qc.invalidateQueries({ queryKey: ['clases'] });
            qc.invalidateQueries({ queryKey: claves.membresia });
            qc.invalidateQueries({ queryKey: ['asistencia'] });
        },
    });
}

// Alta/edición/borrado de un PR: todo cuelga de `['historial-rm']`, que es de donde
// salen los PRs, el historial y las series del gráfico.
export function useCrearRm() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/historial-rm', payload).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['historial-rm'] }),
    });
}

export function useEditarRm() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...payload }) =>
            api.put(`/api/v1/historial-rm/${id}`, payload).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['historial-rm'] }),
    });
}

export function useEliminarRm() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/historial-rm/${id}`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['historial-rm'] }),
    });
}

// Enviar la solicitud de plan mueve la cola del admin (`['solicitudes']`) y, cuando
// la aprueben, el plan del alumno (`['membresia']`).
export function useSolicitarPlan() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v1/solicitudes/solicitar', payload).then((r) => r.data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['solicitudes'] });
            qc.invalidateQueries({ queryKey: claves.membresia });
        },
    });
}

// Subir un documento del alumno (comprobante de pago, certificado de estudiante) es una
// ORDEN, no un dato cacheable: devuelve la URL privada que la solicitud manda después.
// `privado=1` => el archivo va a la carpeta privada y sólo lo sirve el endpoint
// autenticado del backend (nunca la URL pública de /static/uploads/).
export function useSubirArchivoPrivado() {
    return useMutation({
        mutationFn: (archivo) => {
            const formData = new FormData();
            formData.append('file', archivo);
            return api.post('/api/v1/upload/voucher?privado=1', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            }).then((r) => r.data?.url || r.data?.voucher_url || '');
        },
    });
}

// ── Bloque 3 (alumno): Ajustes (perfil propio y contraseña) ───────────────────
// Los dos PUT que quedaban a mano en Ajustes. Guardar el perfil mueve
// `['alumnos','me']`, la MISMA clave que `useMiPerfil` comparte con Solicitar plan:
// al guardar, la otra pantalla deja de mostrar el dato viejo sin que nadie tenga que
// acordarse de refrescarla.
export function useGuardarMiPerfil() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.put('/api/v1/alumnos/me', payload).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: claves.miPerfil }),
    });
}

// Cambiar la contraseña es una ORDEN (no mueve ningún dato cacheado), así que no
// invalida ninguna clave: mismo criterio que `useParsearWod`.
export function useCambiarPassword() {
    return useMutation({
        mutationFn: (payload) =>
            api.put('/api/v1/usuarios/cambiar-password', payload).then((r) => r.data),
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// BLOQUE 2 parte B — PIZARRA DE WOD (panel del coach)
// ══════════════════════════════════════════════════════════════════════════════
// El catálogo de movimientos lo comparte con el Dashboard del coach y las pantallas de
// marcas del alumno (`useMovimientos`, arriba). Lo que faltaba eran las mutaciones:
// antes, crear un movimiento a mano RELEÍA el catálogo con otro `api.get` para
// refrescar el combo; invalidando `['movimientos']` eso lo resuelve React Query.

// Publicar/editar un WOD mueve la lista de WODs, el "WOD de hoy" del alumno y las
// clases que el backend vincula en la misma transacción: las dos familias juntas.
function invalidarWodsYClases(qc) {
    qc.invalidateQueries({ queryKey: ['wods'] });
    qc.invalidateQueries({ queryKey: ['clases'] });
}

export function useCrearMovimiento() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/movimientos', payload).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: claves.movimientos }),
    });
}

// El parser de texto libre devuelve una PROPUESTA de movimientos (no guarda nada):
// es una orden, no un dato cacheable, así que no invalida ninguna clave.
export function useParsearWod() {
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/wods/parse', payload).then((r) => r.data),
    });
}

export function useCrearWod() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/wods', payload).then((r) => r.data),
        onSuccess: () => invalidarWodsYClases(qc),
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// BLOQUE 2 parte C — DASHBOARD DEL COACH + GESTIÓN DE CLASES
// ══════════════════════════════════════════════════════════════════════════════
// Las dos pantallas pedían sus datos con `useEffect` + `useState` (el Dashboard, en un
// solo `fetchAllData` de 5 GET más una consulta de RMs POR alumno). Como las rutas son
// `lazy`, cada navegación entre ellas lo volvía a pedir TODO; acá comparten queryKey.

// Clases de la semana del coach (`coach_id` = el coach logueado).
export function useClasesCoach(coachId, desde, hasta) {
    return useQuery({
        queryKey: claves.clasesCoach(coachId, desde, hasta),
        queryFn: async () => {
            const data = (await api.get('/api/v1/clases/', {
                params: { coach_id: coachId, fecha_desde: desde, fecha_hasta: hasta },
            })).data;
            const lista = data?.clases || data || [];
            return Array.isArray(lista) ? lista : [];
        },
        // El coach de una clase lo mueve tomar/soltar y el cupo, ampliar cupo (las dos
        // invalidan `['clases']`); el horario en sí cambia poco.
        staleTime: 30_000,
        enabled: Boolean(coachId) && Boolean(desde) && Boolean(hasta),
    });
}

// Clases de UN día (panel del coach: la vista del día y el detalle de la clase abierta).
export function useClasesDia(fecha, limite = 200) {
    return useQuery({
        queryKey: claves.clasesDia(fecha, limite),
        queryFn: async () => {
            const data = (await api.get('/api/v1/clases/', {
                params: { fecha_desde: fecha, fecha_hasta: fecha, limit: limite },
            })).data;
            const lista = data?.clases || data || [];
            return Array.isArray(lista) ? lista : [];
        },
        staleTime: 30_000,
        enabled: Boolean(fecha),
    });
}

// UNA clase por id: es la que llega en `?clase=ID` desde una tarjeta del Dashboard.
export function useClaseDetalle(claseId) {
    return useQuery({
        queryKey: claves.clasesDetalle(claseId),
        queryFn: async () => (await api.get(`/api/v1/clases/${claseId}`)).data || null,
        staleTime: 30_000,
        enabled: Boolean(claseId),
    });
}

// Clases de la semana de UNA disciplina (calendario multi-día y alcance al publicar).
// Clave propia porque el `disciplina_id` cambia la respuesta: `useClasesRango` no lo lleva.
export function useClasesDisciplinaSemana(disciplinaId, desde, hasta) {
    return useQuery({
        queryKey: claves.clasesDisciplinaSemana(disciplinaId, desde, hasta),
        queryFn: async () => {
            const data = (await api.get('/api/v1/clases/', {
                params: {
                    disciplina_id: disciplinaId,
                    fecha_desde: desde,
                    fecha_hasta: hasta,
                    limit: 500,
                },
            })).data;
            const lista = data?.clases || data || [];
            return Array.isArray(lista) ? lista : [];
        },
        staleTime: 30_000,
        enabled: Boolean(disciplinaId) && Boolean(desde) && Boolean(hasta),
    });
}

// Listado completo de WODs del box (`GET /wods/` sin fecha): el Dashboard saca de acá
// el WOD de hoy, "WODs esta semana" y el detalle que abre cada tarjeta.
export function useTodosLosWods() {
    return useQuery({
        queryKey: claves.wodsTodos,
        queryFn: async () => (await api.get('/api/v1/wods/')).data || [],
        staleTime: 60_000,
    });
}

// WODs de un día concreto (`GET /wods/?fecha=`): el calendario de la semana pide 7.
export function useWodsDeFecha(fecha) {
    return useQuery({
        queryKey: claves.wodsFecha(fecha),
        queryFn: async () => (await api.get('/api/v1/wods/', { params: { fecha } })).data || [],
        staleTime: 60_000,
        enabled: Boolean(fecha),
    });
}

// Detalle de UN WOD: lo leen el modal de solo lectura y el formulario que se pre-carga
// al entrar a Gestión de Clases con ?clase=ID.
export function useWodDetalle(wodId) {
    return useQuery({
        queryKey: claves.wodDetalle(wodId),
        queryFn: async () => (await api.get(`/api/v1/wods/${wodId}`)).data || null,
        staleTime: 60_000,
        enabled: Boolean(wodId),
    });
}

// Catálogo de disciplinas del box (admin: Clases, Horarios, Coaches; coach: Gestión de
// Clases): su propio filtro (ocultar Gap/Open Box, por ejemplo) lo pone cada pantalla.
export function useDisciplinas() {
    return useQuery({
        queryKey: claves.disciplinas,
        queryFn: async () => (await api.get('/api/v1/disciplinas/')).data || [],
        staleTime: 300_000,
    });
}

// Relaciones coach↔disciplina del box (ver la nota de la clave: el backend ignora
// `coach_id`). Cada pantalla filtra lo suyo: el Dashboard por `coach_id === usuario_id`
// y Gestión de Clases por `activo`. Antes eran DOS GET iguales con dos códigos distintos.
export function useCoachDisciplinas() {
    return useQuery({
        queryKey: claves.coachDisciplinas,
        queryFn: async () => (await api.get('/api/v1/coach-disciplinas')).data || [],
        staleTime: 300_000,
    });
}

// Alumnos del coach (scoped en el backend: 403 si se pide otro coach_id).
export function useAlumnosDeCoach(coachId) {
    return useQuery({
        queryKey: claves.alumnosCoach(coachId),
        queryFn: async () => (await api.get(
            `/api/v1/fidelizacion/coach/${coachId}/alumnos`,
        )).data?.alumnos || [],
        staleTime: 60_000,
        enabled: Boolean(coachId),
    });
}

// Alumnos en riesgo de abandono + el umbral que aplicó el backend (para el texto).
export function useAlumnosCoachEnRiesgo(coachId) {
    return useQuery({
        queryKey: claves.alumnosCoachEnRiesgo(coachId),
        queryFn: async () => (await api.get(
            `/api/v1/fidelizacion/coach/${coachId}/en-riesgo`,
        )).data || {},
        staleTime: 60_000,
        enabled: Boolean(coachId),
    });
}

// Progreso del tab Alumnos: para cada alumno, sus RMs (máximo 50). Antes eran 50 GET
// EN SERIE en CADA navegación al panel; ahora van en paralelo y quedan en caché con la
// lista de alumnos dentro de la clave (si cambia el listado, se recalcula).
export function useProgresoAlumnosCoach(alumnos) {
    const lista = (alumnos || []).slice(0, 50);
    const ids = lista.map((a) => a.id).join(',');
    return useQuery({
        queryKey: claves.progresoAlumnosCoach(ids),
        queryFn: async () => Promise.all(lista.map(async (alumno) => {
            try {
                const rms = (await api.get(`/api/v1/historial-rm/alumnos/${alumno.id}/rms`)).data || [];
                return {
                    id: alumno.id,
                    nombre: alumno.nombre,
                    correo: alumno.correo,
                    telefono: alumno.telefono,
                    total_rms: rms.length,
                    rms,
                    estado: rms.length >= 5 ? 'activo' : rms.length > 0 ? 'iniciando' : 'sin_datos',
                };
            } catch {
                // Un alumno sin RMs (o con la consulta caída) no rompe el resto: se
                // lista como "sin_datos", igual que hacía el for con await.
                return {
                    id: alumno.id,
                    nombre: alumno.nombre,
                    correo: alumno.correo,
                    telefono: alumno.telefono,
                    total_rms: 0,
                    rms: [],
                    estado: 'sin_datos',
                };
            }
        })),
        staleTime: 60_000,
        enabled: lista.length > 0,
    });
}

// Reservas de UNA clase: la misma lista la miran las DOS pantallas del coach (la
// tarjeta expandible del Dashboard y "Tomar Asistencia" en Gestión de Clases).
export function useReservasPorClase(claseId) {
    return useQuery({
        queryKey: claves.reservasPorClase(claseId),
        queryFn: async () => (await api.get(`/api/v1/reservas/por-clase/${claseId}`)).data || [],
        // Corta: la asistencia se marca y se desmarca todo el rato desde el panel.
        staleTime: 15_000,
        enabled: Boolean(claseId),
    });
}

// Marcar/desmarcar la asistencia de UNA reserva. Mueve el detalle de la clase y los
// contadores de asistencia: se invalidan las dos familias que lo alimentan.
export function useMarcarAsistenciaReserva() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ reservaId, asistio }) => api.put(
            `/api/v1/reservas/${reservaId}/asistencia`, { asistio },
        ).then((r) => r.data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['reservas'] });
            qc.invalidateQueries({ queryKey: ['asistencia'] });
        },
    });
}

// Editar el WOD de una clase (`PUT /wods/{id}`): mueve el WOD, su "WOD del día" y las
// clases que lo comparten.
export function useGuardarWod() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ wodId, payload, params }) => api.put(
            `/api/v1/wods/${wodId}`, payload, { params },
        ).then((r) => r.data),
        onSuccess: () => invalidarWodsYClases(qc),
    });
}

// Publicar el WOD de VARIOS días en una transacción (`POST /wods/batch-create`): el
// backend crea un WOD por fecha y vincula sus clases de una sola vez.
export function useCrearWodsBatch() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ body, params }) => api.post(
            '/api/v1/wods/batch-create', body, { params },
        ).then((r) => r.data),
        onSuccess: () => invalidarWodsYClases(qc),
    });
}

// Tomar/soltar una clase (`alcance`: sólo esa clase o las futuras del mismo horario;
// `modo_emergencia` para disciplinas que el coach no dicta — queda auditado).
export function useAccionClase() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ claseId, accion, params }) => api.post(
            `/api/v1/clases/${claseId}/${accion}`, null, { params },
        ).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['clases'] }),
    });
}

// ── Bloque 6: los dos modales del Dashboard del coach ────────────────────────
// Los dos pedían su dato en un `useEffect` con `api.get` a mano: cada apertura del modal
// volvía a pedirlo. Ahora viven en la caché compartida (una entrada por alumno).

// Ficha acotada del alumno (P2): UN endpoint coach-scoped con los 4 datos que el coach
// puede ver (teléfono, alta, plan y créditos). No se reusa la del admin porque aquella
// pega a endpoints admin-only: un coach recibiría 403.
export function useFichaAlumnoCoach(coachId, alumnoId) {
    return useQuery({
        queryKey: claves.fichaAlumnoCoach(coachId, alumnoId),
        queryFn: async () => (await api.get(
            `/api/v1/fidelizacion/coach/${coachId}/alumno/${alumnoId}/ficha`,
        )).data || null,
        // Igual que el useEffect que reemplaza: la ficha se pide cuando hay alumno elegido.
        // Sin `staleTime` (el default 0) cada apertura revalida, y la caché sirve para
        // pintar la última ficha al instante mientras llega la respuesta nueva.
        enabled: Boolean(alumnoId),
    });
}

// Vista previa del correo de inactividad ANTES de mandarlo: el asunto y el HTML los
// renderiza el BACKEND con la MISMA función del envío real (`render_email_fidelizacion`),
// así que es un GET sin efectos secundarios (no registra ni manda nada) y se puede cachear
// por alumno. El envío (`useContactarAlumnoCoach`) no invalida a propósito: sólo escribe en
// notificaciones_enviadas y auditoría, no mueve ninguno de los datos que estas claves miran.
export function usePreviewContactoCoach(coachId, alumnoId) {
    return useQuery({
        queryKey: claves.previewContactoCoach(coachId, alumnoId),
        queryFn: async () => (await api.get(
            `/api/v1/fidelizacion/coach/${coachId}/contactar/${alumnoId}/preview`,
        )).data || null,
        enabled: Boolean(alumnoId),
    });
}

// Correo de contacto a un alumno en riesgo: es una ORDEN (queda en
// notificaciones_enviadas y en auditoría), no un dato que se cachee.
export function useContactarAlumnoCoach() {
    return useMutation({
        mutationFn: ({ coachId, alumnoId }) => api.post(
            `/api/v1/fidelizacion/coach/${coachId}/contactar/${alumnoId}`,
        ).then((r) => r.data),
    });
}


// ── Bloque 3 (parte A): catálogos y CRUD del panel admin ─────────────────────
// Acá viven las consultas y las mutaciones del CRUD del admin (disciplinas, horarios
// base, planes, usuarios/coaches, clases, bazar y la configuración del box). Poner la
// mutación junto a su clave evita el bug de siempre: guardar en una pantalla y que la
// otra siga mostrando lo viejo (que es de dónde salían los `fetchX()` a mano).

// Padrón por rol (`GET /usuarios/?rol=`): el rol va en la clave porque cambia la lista;
// el tenant lo deriva el backend del token (el query param se ignora).
export function useUsuariosPorRol(rol) {
    return useQuery({
        queryKey: claves.usuariosRol(rol),
        queryFn: async () => (await api.get('/api/v1/usuarios/', {
            params: { rol },
        })).data || [],
        staleTime: 60_000,
        enabled: Boolean(rol),
    });
}

// Grid semanal de horarios base (lunes a domingo) del box.
export function useGridSemanalHorarios() {
    return useQuery({
        queryKey: claves.gridSemanalHorarios,
        queryFn: async () => (await api.get('/api/v1/horarios/grid-semanal')).data || [],
        staleTime: 300_000,
    });
}

// Clases del admin (`GET /clases/`, hasta 500). El filtro por disciplina lo aplica el
// backend (va en la clave); el recorte por turno lo hace la pantalla en memoria.
export function useClasesAdmin(disciplinaId = '') {
    return useQuery({
        queryKey: claves.clasesAdmin(disciplinaId),
        queryFn: async () => (await api.get('/api/v1/clases/', {
            params: disciplinaId ? { limit: 500, disciplina_id: disciplinaId } : { limit: 500 },
        })).data || [],
        staleTime: 60_000,
    });
}

// TODOS los planes (activos e inactivos) para administrarlos.
export function usePlanes() {
    return useQuery({
        queryKey: claves.planesTodos,
        // Igual que `usePlanesActivos`: sirve envuelto (`{planes: [...]}`) o pelado.
        queryFn: async () => {
            const data = (await api.get('/api/v1/planes')).data;
            const lista = data?.planes || data || [];
            return Array.isArray(lista) ? lista : [];
        },
        staleTime: 300_000,
    });
}

// Datos del box (`GET /tenants/me`): public_id, nombre y subdominio.
export function useTenantMe() {
    return useQuery({
        queryKey: claves.tenantMe,
        queryFn: async () => (await api.get('/api/v1/tenants/me')).data || null,
        staleTime: 300_000,
    });
}

// ── Bloque 3 (parte A): mutaciones del CRUD del admin ────────────────────────
// Contrato común: `{ id, payload }` -> con `id` es PUT (editar) y sin `id` es POST
// (crear). El payload lo arma la pantalla, que es la que conoce su formulario.

// Disciplinas: las miran Clases, Horarios, Coaches y el modal de clase -> por prefijo.
export function useGuardarDisciplina() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ id, payload }) => (id
            ? api.put(`/api/v1/disciplinas/${id}`, payload)
            : api.post('/api/v1/disciplinas/', payload)).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: claves.disciplinas }),
    });
}

export function useEliminarDisciplina() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/disciplinas/${id}`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: claves.disciplinas }),
    });
}

// Horarios base: crean/borran el grid semanal del box.
export function useGuardarHorarioBase() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ id, payload }) => (id
            ? api.put(`/api/v1/horarios/${id}`, payload)
            : api.post('/api/v1/horarios', payload)).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['horarios'] }),
    });
}

export function useEliminarHorarioBase() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/horarios/${id}`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['horarios'] }),
    });
}

// Clases: crear/editar/eliminar desde el modal. `['clases']` es el prefijo que comparten
// el listado del admin, el del coach y las clases por rango: todo lo montado se refresca.
export function useGuardarClase() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ id, payload }) => (id
            ? api.put(`/api/v1/clases/${id}`, payload)
            : api.post('/api/v1/clases/', payload)).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['clases'] }),
    });
}

export function useEliminarClase() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/clases/${id}`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['clases'] }),
    });
}

// Planes: lo que guarda el admin es lo que ve el alumno al solicitar plan.
export function useGuardarPlan() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ id, payload }) => (id
            ? api.put(`/api/v1/planes/${id}`, payload)
            : api.post('/api/v1/planes', payload)).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['planes'] }),
    });
}

export function useEliminarPlan() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/planes/${id}`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['planes'] }),
    });
}

// Usuarios del box (coaches y alumnos): un hook para crear y editar. Invalida
// `['usuarios']` entero, que es el prefijo del padrón que miran Coaches y el modal de clase.
export function useGuardarUsuario() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ id, payload }) => (id
            ? api.put(`/api/v1/usuarios/${id}`, payload)
            : api.post('/api/v1/usuarios/', payload)).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['usuarios'] }),
    });
}

// Baja de un usuario (soft delete en el backend: queda con `estado = baja`).
export function useDesactivarUsuario() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/usuarios/${id}`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['usuarios'] }),
    });
}

// Disciplinas asignadas a un coach: reemplaza el set completo (no es un alta suelta), por
// eso es un único PUT con la lista entera.
export function useReemplazarCoachDisciplinas() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.put(
            '/api/v1/coach-disciplinas/reemplazar', payload,
        ).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: claves.coachDisciplinas }),
    });
}

// Configuración bancaria del box: la ESCRIBE esta pantalla y la LEEN el Bazar del alumno y
// Solicitar plan (bloquean la transferencia si el box no tiene datos de pago cargados), así
// que se invalida por prefijo y no por la clave exacta del tenant.
export function useGuardarConfiguracion() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.put('/api/v1/configuracion', payload).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['configuracion'] }),
    });
}

// Productos del bazar. OJO: crear y editar NO son simétricos:
//  - crear  -> POST /productos con FormData (multipart: la foto viaja en `file`).
//  - editar -> PUT /productos/{id} en JSON y, si hay foto nueva, un POST aparte a
//              /productos/{id}/imagen (un PUT JSON no puede llevar archivo). El borrado de
//              la foto es `imagen_url: null` dentro del payload, no una llamada aparte.
export function useGuardarProducto() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, payload, imagen }) => {
            if (id) {
                const res = await api.put(`/api/v1/productos/${id}`, payload);
                if (imagen) {
                    const dataImagen = new FormData();
                    dataImagen.append('file', imagen);
                    await api.post(`/api/v1/productos/${id}/imagen`, dataImagen, {
                        headers: { 'Content-Type': 'multipart/form-data' },
                    });
                }
                return res.data;
            }
            return (await api.post('/api/v1/productos', payload, {
                headers: { 'Content-Type': 'multipart/form-data' },
            })).data;
        },
        onSuccess: () => qc.invalidateQueries({ queryKey: ['productos'] }),
    });
}

// Baja de producto: el DELETE lo deja en `activo=false` (el registro no se borra). Lo ven el
// inventario del admin y el Bazar del alumno, que comparten el prefijo `['productos']`.
export function useEliminarProducto() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/productos/${id}`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['productos'] }),
    });
}

// ── Bloque 3 (parte B): Reportes & Analytics ─────────────────────────────────
// Movimientos de finanzas que muestra el detalle de Reportes. Se pide UNA vez y se
// invalida al registrar un movimiento (abajo), así que sirve también si otra pantalla
// empieza a mostrar la misma lista.
export function useTransaccionesFinanzas() {
    return useQuery({
        queryKey: claves.transaccionesFinanzas,
        queryFn: async () => (await api.get('/api/v1/finanzas/transacciones')).data || [],
        // 1 min: el detalle cambia sólo cuando alguien registra un movimiento (y eso
        // invalida la clave), así que volver a la pantalla no cuesta otra request.
        staleTime: 60_000,
    });
}

// Alta de un movimiento (ingreso/egreso). El payload lo arma la pantalla tal cual lo
// mandaba antes (`...movForm`, `monto` numérico y `tenant_id`).
// Invalida DOS prefijos: `['finanzas']` (la lista del detalle) y `['reportes']` (un
// movimiento mueve el ingreso neto del mes, el MRR y el ARPU del reporte, y esos
// mismos números son las tarjetas del Dashboard). Antes la pantalla volvía a pedir
// `/reportes/` a mano después de guardar; ahora basta con invalidar el prefijo.
export function useCrearTransaccionFinanzas() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/finanzas/transaccion', payload).then((r) => r.data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['finanzas'] });
            qc.invalidateQueries({ queryKey: ['reportes'] });
        },
    });
}

// Descarga del Excel de ventas del mes (`GET /reportes/monthly-sales`). NO es una
// consulta cacheable: la respuesta es un Blob y, cuando el backend falla, un JSON de
// error con el MISMO content-type de blob — quien llama decide (mira el content-type)
// y muestra el `detail`. Por eso va como mutación y no invalida nada.
export function useDescargarReporteVentas() {
    return useMutation({
        mutationFn: ({ tenantId, mes, anio }) => api({
            method: 'GET',
            url: '/api/v1/reportes/monthly-sales',
            params: { tenant_id: tenantId, mes, anio },
            responseType: 'blob',
            headers: {
                Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            },
        }),
    });
}

// ── A5: padrón de alumnos (tabla del admin, escritorio y móvil) ──────────────
// Devuelve `{ lista, total }`: el total sin paginar viene en el header X-Total-Count y
// es el que alimentan el pie ("Mostrando A-B de N") y el cálculo de páginas.
export function useAlumnosPaginados({
    rol = 'alumno', porPagina = 25, pagina = 1, buscar = '',
} = {}) {
    return useQuery({
        queryKey: claves.alumnosPaginados(rol, porPagina, pagina, buscar),
        queryFn: async () => {
            const resp = await api.get('/api/v1/usuarios/', {
                params: paramsAlumnos({ rol, porPagina, pagina, buscar }),
            });
            return {
                lista: resp.data || [],
                total: Number(resp.headers?.['x-total-count'] ?? 0),
            };
        },
        staleTime: 30_000,
        // Al cambiar de página o al buscar, la tabla anterior se queda en pantalla hasta
        // que llega la nueva (mismo criterio que el historial del alumno y el churn).
        placeholderData: keepPreviousData,
    });
}

// Suscripciones ACTIVAS del box (`GET /suscripciones?estado=activo`).
export function useSuscripcionesActivas() {
    return useQuery({
        queryKey: claves.suscripcionesActivas,
        queryFn: async () => (await api.get('/api/v1/suscripciones', {
            params: { estado: 'activo' },
        })).data || [],
        staleTime: 60_000,
    });
}

// Suscripciones de UN alumno: alimenta el aviso "ya tiene un plan vigente" del
// comprobante, que se consulta al ABRIR el modal (una suscripción pudo crearse desde la
// app mientras el admin miraba otra pantalla). Por eso SIN `staleTime`: cada apertura
// vuelve a preguntar, y el modal se desmonta al cerrarse.
export function useSuscripcionesAlumno(usuarioId) {
    return useQuery({
        queryKey: claves.suscripcionesAlumno(usuarioId),
        queryFn: async () => (await api.get('/api/v1/suscripciones', {
            params: { usuario_id: usuarioId, estado: 'activo' },
        })).data || [],
        staleTime: 0,
        enabled: Boolean(usuarioId),
    });
}

// Beneficios del alumno (`GET /beneficios/alumno/{id}?plan_ids=`): el descuento vigente
// y el precio final de cada plan, calculados por el BACKEND. El comprobante los usa para
// avisar antes de asignar y para precargar lo que hay que cobrar.
// Sin alumno o sin planes en el catálogo la consulta no sale (el modal simplemente no
// muestra el aviso: no se cae la aprobación).
export function useBeneficiosAlumno(alumnoId, planIds) {
    return useQuery({
        queryKey: claves.beneficiosAlumno(alumnoId, planIds),
        queryFn: async () => (await api.get(`/api/v1/beneficios/alumno/${alumnoId}`, {
            params: { plan_ids: planIds },
        })).data || null,
        // El descuento no cambia mientras el admin elige el plan (igual que `useMisBeneficios`).
        staleTime: 300_000,
        enabled: Boolean(alumnoId && planIds),
    });
}

// Aprobación de un comprobante: crea la suscripción del alumno. El payload lo arma la
// pantalla tal cual lo mandaba antes (inicio/expiracion con `sumarDiasInstante`).
// Invalida la lista de activas (el padrón pasa a mostrar el plan nuevo al instante:
// antes esa columna quedaba vieja hasta recargar), `['membresia']` (los créditos de esa
// puerta) y `['reportes']` (un plan nuevo mueve el MRR y el ingreso del reporte, que son
// las tarjetas del Dashboard: mismo criterio que `useCrearTransaccionFinanzas`).
// NO invalida `['suscripciones','alumno',…]` a propósito: el aviso de "plan vigente" es
// la foto del momento en que se abrió el comprobante; refrescarlo en medio de la
// aprobación haría parpadear el aviso justo antes de cerrarse solo.
export function useCrearSuscripcion() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/suscripciones', payload).then((r) => r.data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: claves.suscripcionesActivas });
            qc.invalidateQueries({ queryKey: ['membresia'] });
            qc.invalidateQueries({ queryKey: ['reportes'] });
        },
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// BLOQUE 2 (MARKETING) — los avisos del carrusel "Novedades del box"
// ══════════════════════════════════════════════════════════════════════════════
// Un aviso se publica UNA vez y lo miran DOS pantallas muy distintas: la tabla del
// panel Marketing del admin (con su filtro) y el carrusel del Inicio del alumno.
// Por eso toda mutación invalida el prefijo `['marketing']` completo: no hay que
// acordarse de refrescar ninguna de las dos.
//
// Los helpers de payload (FormData del POST, JSON del PUT, validación espejo del
// backend) viven en `utils/avisosMarketing.js`: es JS puro y `scripts/test-marketing.mjs`
// los prueba sin navegador.

export function useAvisosMarketing(filtro = 'todos') {
    return useQuery({
        queryKey: claves.avisosMarketing(filtro),
        queryFn: async () => (await api.get('/api/v1/marketing', {
            params: { filtro },
        })).data || [],
        staleTime: 30_000,
    });
}

// Lo que pinta el carrusel del Inicio del alumno: SÓLO los vigentes hoy, ya
// ordenados por el backend (fijados primero). Sin avisos, la sección no se dibuja.
export function useAvisosMarketingVigentes({ enabled = true } = {}) {
    return useQuery({
        queryKey: claves.avisosMarketingVigentes,
        queryFn: async () => (await api.get('/api/v1/marketing/vigentes')).data || [],
        staleTime: 5 * 60_000,
        enabled,
    });
}

// Crear y editar NO son simétricos (mismo criterio que los productos del Bazar):
//  - crear  -> POST /marketing multipart (el flyer viaja en `file`).
//  - editar -> PUT /marketing/{id} en JSON y, si hay flyer NUEVO, un POST aparte a
//              /marketing/{id}/imagen (un PUT JSON no puede llevar archivo).
export function useGuardarAvisoMarketing() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, formData, payload, imagen }) => {
            if (id) {
                const res = await api.put(`/api/v1/marketing/${id}`, payload);
                if (imagen) {
                    const dataImagen = new FormData();
                    dataImagen.append('file', imagen);
                    await api.post(`/api/v1/marketing/${id}/imagen`, dataImagen, {
                        headers: { 'Content-Type': 'multipart/form-data' },
                    });
                }
                return res.data;
            }
            return (await api.post('/api/v1/marketing', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            })).data;
        },
        onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing'] }),
    });
}

// Quitar el flyer (la tarjeta vuelve a pintarse con el color de su tipo).
export function useQuitarFlyerAviso() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/marketing/${id}/imagen`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing'] }),
    });
}

// Eliminar el aviso: sale del carrusel al instante (y el backend borra su flyer).
export function useEliminarAviso() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v1/marketing/${id}`).then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing'] }),
    });
}

// El aviso rápido del COACH (publicar desde la Gestión de Clases): la única mutación
// de avisos que NO nace en el panel del admin. Va por JSON y con un payload de un solo
// campo (`{ texto }`): el tipo, la ventana de HOY y el título los fija el backend
// (`app/services/avisos_marketing.py: payload_aviso_rapido`). Invalida el MISMO
// prefijo `['marketing']` que el resto: con eso el carrusel del alumno y la tabla del
// admin se refrescan solos.
export function usePublicarAvisoRapido() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload) => api.post('/api/v1/marketing/aviso-rapido', payload)
            .then((r) => r.data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing'] }),
    });
}

