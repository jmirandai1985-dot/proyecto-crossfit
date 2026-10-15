# Auditoría Bloque 7 — Caché (React Query + assets en producción)

Fecha: 2026-10-15 · Autor: sesión de auditoría
**Decisión del usuario (15-oct): SIN ACCIÓN.** Los dos hallazgos menores quedan en backlog sin
prioridad. Este informe deja el estado verificado y las dos deudas anotadas.

## Estado verificado (nada que arreglar)

### 1. Configuración de React Query — correcta y documentada

`frontend/src/services/queryClient.js` (coincide con `docs/CACHE_REACT_QUERY.md`):

| ajuste | valor | por qué está bien |
|---|---|---|
| `staleTime` | 30 s (1000×default) | el panel del coach se mira en ráfagas: no re-pide lo que acaba de llegar |
| `gcTime` | 5 min | la vuelta atrás (cerrar y reabrir un modal/pestaña) pinta al instante |
| `refetchOnWindowFocus` | `false` | el coach cambia de app (WhatsApp) y vuelve: no dispara N consultas |
| `retry` (queries) | 1 | un 502 transitorio se reintenta UNA vez y después se muestra el error |
| `retry` (mutaciones) | 0 | un POST no se repite solo (`/reservas` descuenta crédito, `/sin-reserva` etc.) |

`DashboardCoach.jsx` **no define queries propias**: todas salen de `src/hooks/queries.js`, con
clave por recurso (el `qc.invalidateQueries({ queryKey: ['historial-rm'] })` de las mutaciones de
PR mueve todas las pantallas que lo muestran, incluida la ficha del coach que se agregó hoy).

### 2. Headers de la instancia de producción — medidos

| recurso | `Cache-Control` | consecuencia |
|---|---|---|
| `index.html` | `no-cache, must-revalidate` (+ `ETag`) | un deploy nuevo se ve en la primera recarga (no hay index viejo pegado) |
| `/assets/*` (JS/CSS con hash) | `max-age=2592000, public, immutable` | caché de 30 días: correcto, el nombre cambia en cada build |

### 3. H-01 (FASE 1) — cerrado

`GET /clases` escribía clases faltantes (side-effect en un GET). Ya es opt-in:
`backend/app/api/v1/clases.py:44-48` (`generar: bool = Query(False)`) y **ningún** frontend manda
`generar=true` (verificado por búsqueda en `frontend/src`).

## Backlog (2 hallazgos menores, sin prioridad)

1. **`/imgs/*` y `/favicon.svg` sin `Cache-Control`** (sólo `ETag`) → en cada recarga el navegador
   revalida; es un 304, no una descarga completa. Impacto: unos ms, sólo en la primera visita.
2. **No existe `favicon.ico` en el build**: `GET /favicon.ico` devuelve el HTML del `index.html`
   con 200 (fallback de SPA). Es ruido en los logs y hace que el navegador baje ~1 KB de HTML
   para un ícono. Se arreglaría con un `favicon.ico` real o un `location = /favicon.ico { return 204; }`.
3. *(Relacionado, del bloque de incidencias)* `frontend/src/services/api.js` **no define
   `timeout`**. Combinado con `retry: 1`, un cold-start largo de Render se ve como espera larga en
   vez de error. Un `timeout` explícito (p. ej. 20 s) convertiría la espera en un mensaje con
   "Reintentar". **No se tocó** (decisión de no avanzar en caché/red en este turno).
