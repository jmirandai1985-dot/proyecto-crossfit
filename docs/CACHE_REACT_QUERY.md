# Caché de datos del frontend (React Query)

> Documento de SOLO LECTURA del código. Explica por qué las pantallas de admin ya no piden
> sus datos con `useEffect` + `useState`, qué comparte la caché y qué frescura tiene cada
> dato (`staleTime`). Fuentes: `frontend/src/services/queryClient.js`,
> `frontend/src/hooks/queries.js` y las pantallas `Dashboard`, `Fidelizacion` y
> `AdminAlumnosPendientes`.

## 1. El problema (diagnóstico 2026-10)

Cada pantalla pedía sus datos así:

```js
useEffect(() => { cargar(); }, []);
```

...y guardaba el resultado en `useState`. Como las páginas de rol se cargan en **lazy**
(React Router 7 desmonta la ruta al salir), **cada navegación volvía a montar la pantalla y
a pedir todo de nuevo**, aunque el dato tuviera 5 segundos. Había 48 archivos con ese
patrón y, peor, datos compartidos por dos pantallas se pedían **dos veces por vuelta**:

| dato que se repetía | pantallas que lo pedían |
|---|---|
| `GET /api/v1/solicitudes/pendientes` | Dashboard y "Pendientes de revisión" |
| `GET /api/v1/alumnos/pendientes-activacion` | Dashboard (conteo) y "Pendientes de revisión" |
| `GET /api/v1/reportes/?tenant_id=` | Dashboard (tarjetas y panel BI) |

## 2. Qué hace la caché

`QueryClientProvider` envuelve toda la app (`main.jsx`) con **una sola** instancia
(`services/queryClient.js`). Dos pantallas que usan la **misma queryKey** comparten la misma
entrada: la segunda pinta al instante con lo ya traído y, dentro de `staleTime`, ni toca la
red.

Default global: `staleTime: 30 s`, `gcTime: 5 min`, `refetchOnWindowFocus: false`,
`retry: 1`, y las mutaciones **sin** reintento (repetir un PUT no siempre es inocuo).

## 3. Frescura por dato (`hooks/queries.js`)

| hook | clave | staleTime | auto-refresco |
|---|---|---|---|
| `useSolicitudesPendientes` | `['solicitudes','pendientes']` | 15 s | 30 s en Pendientes |
| `usePendientesActivacion` | `['alumnos','pendientes-activacion']` | 15 s | 30 s en Pendientes |
| `useCountPendientesActivacion` | `['alumnos','pendientes-activacion','count']` | 30 s | — |
| `useStatsDashboard` | `['reportes', tenant]` | 60 s | — |
| `useClasesHoy` | `['asistencia','clases-hoy']` | 30 s | 45 s (pausado en pestaña oculta) |
| `useChurn` | `['kpis','churn', tenant, buscar]` | 5 min | — |
| `useSugerenciasChurn` | `['fidelizacion','sugerencias', tenant, ids]` | 5 min | — |
| `useSegmentacion` | `['segmentacion', tenant]` | 10 min | — |

`refetchInterval` **no** corre con la pestaña oculta (React Query pausa el intervalo solo):
es el mismo efecto que el `setInterval` + `visibilitychange` que se quitó del Dashboard.

## 4. Cómo se refresca después de escribir

Las mutaciones (`useAprobarSolicitud`, `useRechazarSolicitud`, `useAccionAlumnoPendiente`,
`useMarcarGestionChurn`) **invalidan por prefijo**:
`['alumnos','pendientes-activacion']`, `['solicitudes']`, `['reportes']` y `['kpis','churn']`.

`invalidateQueries` con prefijo alcanza lista **y** conteo a la vez, y refresca TODAS las
pantallas montadas que muestren ese dato: ya no hay `cargarX()` a mano después de cada
acción (que era la fuente de que una pantalla quedara con datos viejos mientras la otra no).

## 5. Por qué NO se migró todo

Fase 1 migró 3 pantallas (las que compartían datos y más se notaban al navegar) más el
provider y los hooks compartidos. Quedan ~45 archivos con el patrón viejo; en orden de dolor
medido: `Alumnos`, `Clases`/`SupervisionClases`, `Reportes`, `Notificaciones` (campana) y las
pantallas de alumno. `Layout` y `CampanaNotificaciones` quedan intactos a propósito: la
campana tiene su propio refresco por eventos y no comparte queryKey con estas pantallas.

## 6. Cómo se ejecuta y se verifica

```bash
cd frontend
npm install          # trae @tanstack/react-query (^5.104.2; peer react ^18 || ^19)
npm run dev          # la app con el provider en main.jsx
npm run lint         # oxlint: 0 warnings en los archivos migrados
npm run build        # valida imports/JSX del bundle (chunks por ruta)
```

Verificación manual del objetivo: entrar al Dashboard y después a "Pendientes de revisión"
(o al revés) y mirar la pestaña Network: `solicitudes/pendientes` y
`alumnos/pendientes-activacion` **no** se vuelven a pedir dentro de los 15 s; antes se pedían
en cada navegación.
