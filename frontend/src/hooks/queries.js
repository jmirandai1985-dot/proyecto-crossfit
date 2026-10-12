// Consultas y mutaciones compartidas (React Query) de los datos que más se repetían.
//
// Las CLAVES viven acá y sólo acá: invalidar un prefijo (`['solicitudes']`) refresca de
// una vez todas las pantallas que muestran lo mismo, sin que cada página tenga que saber
// quién más usa ese dato.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

export const claves = {
    solicitudesPendientes: ['solicitudes', 'pendientes'],
    pendientesActivacion: ['alumnos', 'pendientes-activacion'],
    countPendientesActivacion: ['alumnos', 'pendientes-activacion', 'count'],
    stats: (tenantId) => ['reportes', tenantId],
    clasesHoy: ['asistencia', 'clases-hoy'],
    churn: (tenantId, buscar) => ['kpis', 'churn', tenantId, buscar || ''],
    segmentacion: (tenantId) => ['segmentacion', tenantId],
    sugerencias: (tenantId, ids) => ['fidelizacion', 'sugerencias', tenantId, ids],
    // ── Bloque ALUMNO (Fase 2): datos que comparten varias pantallas del alumno ──
    // Inicio, Bazar, Mis pedidos, Mis reservas y Mi progreso piden el MISMO catálogo
    // y los mismos datos de base: con una sola queryKey, la segunda pantalla pinta al
    // instante y no vuelve a pedirlos (antes cada una tenía su useEffect).
    publicIdBox: ['tenants', 'me', 'public-id'],
    productos: (activo) => ['productos', activo === undefined ? 'todos' : String(activo)],
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
        queryFn: async () => (await api.get(
            `/api/v1/clases?fecha_desde=${desde}&fecha_hasta=${hasta}&limit=${limite}`,
        )).data || [],
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
        queryFn: async () => (await api.get('/api/v1/reservas?estado=confirmada')).data || [],
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

