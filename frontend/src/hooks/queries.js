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
