// Cliente de React Query: UNA sola instancia para toda la app.
//
// Por qué existe (diagnóstico 2026-10)
// ------------------------------------
// Las pantallas pedían sus datos así: `useEffect(() => { cargar(); }, [])` + `useState`.
// Como las páginas de rol son `lazy` (React Router 7 desmonta la ruta al salir), cada
// NAVEGACIÓN volvía a montar la pantalla y a pedir todo de nuevo, y los datos que dos
// pantallas comparten se pedían DOS veces por vuelta: `/api/v1/solicitudes/pendientes`
// se pedía en el Dashboard y en Pendientes de revisión (48 archivos con ese patrón).
//
// Con React Query la MISMA `queryKey` se comparte en caché: la segunda pantalla pinta
// al instante con lo ya traído y, dentro de `staleTime`, no toca la red.
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            // 30 s: volver a una pantalla ya visitada NO vuelve a pedir. Es el caso que
            // más se notaba (dashboard <-> pendientes <-> fidelización). Los datos que
            // caducan antes (o deben refrescarse solos) fijan su staleTime en
            // `hooks/queries.js`, no acá.
            staleTime: 30_000,
            // 5 min en memoria después de dejar de usarse: al volver se pinta la última
            // copia y se refresca en segundo plano (sin pantalla en blanco).
            gcTime: 5 * 60_000,
            // El foco de la ventana NO dispara red. Con varias pestañas abiertas, un
            // refetch-on-focus genera ráfagas de requests al ir y volver.
            refetchOnWindowFocus: false,
            // Un reintento y listo: el backend es un servicio externo (Neon) y las
            // pantallas que necesitan frescura ya traen su propio intervalo.
            retry: 1,
            // Al recuperar la conexión sí conviene reintentar solo.
            refetchOnReconnect: true,
        },
        mutations: {
            // Las mutaciones NO se reintentan solas: repetir un PUT no siempre es
            // inocuo (aprobar/rechazar una solicitud, marcar una gestión).
            retry: 0,
        },
    },
});

// Mensaje de error con el MISMO texto que mostraban las pantallas antes de migrar
// (`detail` del backend y, si no viene, `message`): el admin sigue leyendo lo mismo.
export const mensajeError = (err, fallback) =>
    err?.response?.data?.detail || err?.message || fallback;

export default queryClient;
