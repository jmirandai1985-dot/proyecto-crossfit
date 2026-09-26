# Auditoría Panel Coach — FASE 1 (diagnóstico, solo lectura)

Fecha: 2026-09-23 · Autor: sesión de auditoría · **Estado: NO se tocó código, NO hay commits.**
Alcance: `/coach/dashboard` (tabs Resumen, Clases, Alumnos & RMs, Asistencia, Progreso, Riesgo) +
`/coach/gestion-clases`, más las rutas huérfanas `/coach/pizarra` y `/coach/generar-clases`.

## Cómo se auditó (evidencia)
- Lectura de código frontend + backend (los 7 criterios de la auditoría de admin).
- 2 probes **read-only**: token de coach contra TEST (`:8001`) y contra la **PROD real**
  (uvicorn local `ENVIRONMENT=production --lifespan off` en `:8002`, solo GETs).
- **Se evitó a propósito `GET /api/v1/clases`**: ese GET ESCRIBE (ver H-01). No se llamó ni en TEST ni en PROD.
- Sanity de datos: `clases.asistentes_confirmados` vs `count(reservas)` reales → 8/8 coinciden (TEST).
- `git grep` de hosts/credenciales Neon en el código del panel → **0 resultados**.

## Resumen ejecutivo (7 🔴 / 11 🟡 / 8 🟢)

| ID | Sev | Pantalla | Hallazgo |
|---|---|---|---|
| H-01 | 🔴 | Clases / global | `GET /clases` tiene **escrituras**: auto-genera las clases faltantes del rango consultado. Un GET no debería mutar datos (es también la razón por la que `/health` se chequea con `--lifespan off`). |
| H-02 | 🔴 | Clases | `POST /clases` (`crear_clase`) **no** llama `verificar_coach_disciplina`: un coach puede crear clases de **otra disciplina** y a nombre de **otro coach** (`clase.coach_id` sin validar). |
| H-03 | 🔴 | Gestión de Clases / Clases | `DELETE /wods/{id}` (`eliminar_wod`) **no** valida disciplina ni autoría: cualquier coach puede borrar el WOD de otra disciplina/coach del box. |
| H-04 | 🔴 | Dashboard (todas las tabs) | `fetchAllData` usa `Promise.all` con 5 GET: si **uno** falla, el dashboard entero queda vacío y el error sólo va a `console.error` (sin banner ni Reintentar). Mismo patrón que ya corregimos en Admin con `allSettled`. |
| H-05 | 🟡 | Resumen/Alumnos/Riesgo | `fidelizacion.py` sigue filtrando `usuarios` por **`activo`** (líneas 68, 155, **303**, **419**, 457); 303/419 son `/coach/{id}/en-riesgo` y `/coach/{id}/alumnos` (los endpoints del panel). Criterio 1 de la 034. |
| H-06 | 🟡 | Resumen | Tarjeta **"Alumnos Activos"** = `alumnos.length` (depende de `activo`, ver H-05); el copy no distingue estado real. |
| H-07 | 🟡 | Resumen / Alumnos & RMs | `GET /historial-rm?limit=5` **no está scopeado al coach**: muestra los últimos RM de **todo el box** (y los pinta sólo con `alumno_id`). Además `historial_rm._verificar_acceso_alumno` trata `coach` como **staff del box**: un coach puede leer/escribir RMs de cualquier alumno, incluso de otra disciplina. |
| H-08 | 🟡 | Resumen | "WODs esta semana: **X/Y publicados**" cuenta `c.wod_id != null` (clases con WOD asignado), no `estado === 'publicado'`: un borrador cuenta como publicado. |
| H-09 | 🟡 | Gestión de Clases | Tras crear el WOD multi-día: `setTimeout(() => navigate('/coach?tab=clases'), 1200)` → `/coach` cae en `*` → `/coach/dashboard` y **se pierde `?tab=clases`** (el coach vuelve a Resumen). |
| H-10 | 🟡 | Gestión de Clases | Catches **silenciosos**: `catch { wodsSemana[f] = [] }`, `.catch(() => setCoachDisciplinas([]))`, `toggleAsistencia → catch { console.error(e) }` (el coach no se entera del fallo; en disciplinas el modo emergencia queda desactivado en silencio). |
| H-11 | 🟡 | Clases (tab) | "Marcar todos" hace **N `PUT /reservas/{id}/asistencia` en serie** (no atómico). El tab Asistencia ya usa el batch atómico `POST /asistencia/clases/{id}/confirmar`: hay 2 implementaciones del mismo flujo en el panel. |
| H-12 | 🟡 | Dashboard | `clasesFiltradas` usa el **state** `coachDisciplinas` inmediatamente después de `setCoachDisciplinas(...)`: en la 1ª carga el state todavía es `[]` → el filtro por disciplina se saltea (stale state). |
| H-13 | 🟡 | Progreso/Riesgo/Gestión | Copys engañosos: columna **"Estado"** que en realidad es progreso por cantidad de RMs (`activo/iniciando/sin_datos`, calculado en el cliente); "¡Excelente! Todos tus alumnos **están activos**" (quería decir "sin riesgo"); "Llevan más de **7** días sin entrenar" hardcodeado (el backend tiene `UMBRAL_ALERTA_DIAS = 7`); `'...no se pudo cargar **its datos**'`. |
| H-14 | 🟡 | Datos | Dato sucio en PROD: coach activo llamado **`string`** (`id=6`, tenant 1); parece usuario de prueba en producción. |
| H-15 | 🟡 | Pizarra / GenerarClases | Rutas **huérfanas** (no están en el sidebar). `Pizarra.jsx` está **rota para coaches**: su `POST /api/v1/wods` no manda `disciplina_id` y el backend lo exige para coaches (→ 400). `GenerarClases.jsx` llama `POST /horarios/generar-clases-dia`, ejecutable por cualquier coach para **cualquier fecha del box** (escritura global) con `fecha` string sin validar. |
| H-16 | 🟡 | Código | `pages/coach/Dashboard.jsx` **muerto**: no lo importa nadie y llama a `GET /api/v1/coach/dashboard`, endpoint que **no existe** (`main.py` sólo monta `/api/v1/coach-disciplinas`). |
| H-17 | 🟢 | Código | Dead code dentro de las pantallas: array `statsCards` (30 líneas, nunca renderizado), función `getEstadoColor` (nunca usada), alias `activeTab === 'wods'` conservado por compatibilidad. |
| H-18 | 🟢 | Todo el panel | Sin hosts/credenciales Neon hardcodeados en el panel coach. |
| H-19 | 🟢 | Asistencia (tab) | **"+ cupo"** y **acordeón** sanos: `POST /clases/{id}/ampliar-cupo` valida `coach_id == usuario_id` **o** pertenencia a la disciplina, con tope +10; `AsistenciaClases` agrupa por disciplina con acordeón local, `variant='light'` por defecto y usa el **confirm batch atómico**. |
| H-20 | 🟢 | Todo el panel | Probes read-only: **TEST 200** en `asistencia/clases-hoy`, `fidelizacion/coach/{id}/alumnos|en-riesgo`, `coach-disciplinas`, `movimientos`, `wods`, `historial-rm`; cruce de disciplina → **403**; `/usuarios?rol=alumno` como coach → **403**. Contra la **PROD real (:8002)**: los mismos endpoints → **200**. La migración de Neon **no** afectó al panel. |

## Detalle por pantalla (los 7 criterios)

### 1. Dashboard / Resumen (`DashboardCoach.jsx` tab `resumen`)
1. **activo vs estado**: H-05/H-06 (los endpoints base filtran `activo`). La UI no muestra el lifecycle del alumno.
2. **Fechas**: OK. Tiene helper propio `toLocalDateStr` (línea 57) que usa la hora **local** del navegador, no el
   helper compartido `utils/fecha.js`; igual el resto del archivo, así que no hay bug hoy para un coach en Chile,
   pero es un duplicado (criterio 7).
3. **Fallas silenciosas**: H-04 (el más grave), H-07, H-13.
4. **IDOR**: H-07 (`/historial-rm?limit=5` sin scope). `/fidelizacion/coach/{id}/...` **sí** valida
   `usuario_id != coach_id → 403` (probado por código; no testeable en TEST porque hay 1 solo coach).
5. **Datos sucios / copys**: H-06, H-08, H-13 ("Todos activos" en la tarjeta de riesgo).
6. **Código muerto**: H-17 (`statsCards`, `getEstadoColor`).
7. **Consistencia con Admin**: falta el patrón `allSettled` + banner "Reintentar" (H-04) y el helper de fecha
   compartido (criterio 2). El fetch de alumnos ya está aislado en su propio try/catch (buen precedente a propagar).

### 2. Clases (grid del día / semana) — tab `clases` (+ alias `wods`)
1. **activo vs estado**: usa `w.activo !== false` para el WOD de hoy (tabla `wods`, correcto, no es `usuarios`).
2. **Fechas**: OK (`new Date(fecha + 'T12:00:00')` como ancla anti-TZ).
3. **Fallas silenciosas**: H-11 (el "marcar todos"), H-04.
4. **IDOR**: H-01 (el GET que escribe), H-02 (`POST /clases` sin validar disciplina/coach_id).
   `PUT /reservas/{id}/asistencia` **sí** valida disciplina + ventana del mismo día.
5. **Datos sucios**: "N/M alumnos" sale de `asistentes_confirmados` → **verificado**: coincide con las reservas
   reales (8/8 en TEST) → copy correcto.
6. **Código muerto**: alias `wods` (H-17).
7. **Consistencia**: la tab Asistencia usa el batch; esta tab no (H-11).

### 3. Alumnos & RMs — tab `alumnos`
1. **activo vs estado**: la lista viene de `/fidelizacion/coach/{id}/alumnos` (filtra `activo`, H-05).
2. **Fechas**: OK.
3. **Fallas silenciosas**: si falla el fetch de RMs → `setAlumnoRMs([])` + `console.error` (la UI dice
   "Sin RMs registrados" como si el alumno no tuviera, sin distinguir error de vacío) → mismo patrón que H-10.
4. **IDOR**: H-07 (el endpoint de RMs no está scopeado por disciplina).
5. **Datos sucios**: "Sin RMs registrados" también cuando falló la carga (copy que miente por omisión).
6. **Código muerto**: ninguno nuevo.
7. **Consistencia**: el modal de ficha del alumno (Admin) ya tiene manejo de errores por bloque; acá no.

### 4. Asistencia — tab `asistencia` (`<AsistenciaClases />` compartido con Admin)
1. **activo vs estado**: no aplica (no lista usuarios por estado).
2. **Fechas**: OK — el backend usa `hoy_santiago()`/`ahora_santiago()`; el frontend formatea horas como string.
3. **Fallas silenciosas**: **buen manejo**: `error` state + banner visible, `mensaje` con tipo éxito/error y la
   cantidad real de confirmados (`r.data.confirmados`). Sin catches mudos.
4. **IDOR**: bien. `GET /asistencia/clases-hoy` filtra por las disciplinas del coach y sólo lo que resta del día;
   `GET /asistencia/clases/{id}/alumnos` y `POST /asistencia/clases/{id}/confirmar` llaman
   `verificar_coach_disciplina` (**probado**: cruce de disciplina → 403). `+ cupo` idem.
5. **Datos sucios**: copys honestos; no pre-marca alumnos si la clase nunca fue marcada (evita confirmar de más).
6. **Código muerto**: ninguno.
7. **Consistencia**: es el **patrón a replicar** en el resto del panel (batch atómico + error visible).

### 5. Progreso — tab `progreso`
1. **activo vs estado**: usa `estado` para **otra cosa**: progreso por cantidad de RMs calculado en el cliente
   (`rms.length >= 5 ? 'activo' : ...`) → H-13.
2. **Fechas**: OK.
3. **Fallas silenciosas**: el progreso usa `Promise.all` por alumno con try/catch individual (resiliente), pero el
   alumno que falla queda como `sin_datos` → indistinguible de "no tiene RMs" (copy que miente).
4. **IDOR**: H-07 (los RMs de cualquier alumno del box).
5. **Datos sucios**: columna "Estado" (debería ser "Progreso"); leyenda "Progresando (5+ RMs)" vs el texto
   "N/10+" de la barra → dos escalas distintas en la misma fila.
6. **Código muerto**: ninguno.
7. **Consistencia**: `getProgresoColor`/`getProgresoIcon` repiten el mismo mapeo dos veces.

### 6. Riesgo — tab `riesgo`
1. **activo vs estado**: los alumnos vienen de `/fidelizacion/coach/{id}/en-riesgo` (filtra `activo`, H-05).
2. **Fechas**: `ultima_asistencia` y `dias_ausente` los calcula el backend (Chile). OK.
3. **Fallas silenciosas**: H-04; el botón "Contactar" abre WhatsApp/mailto y usa `alert()` si faltan datos.
4. **IDOR**: el endpoint valida `coach_id == usuario_id` para coaches → OK.
5. **Datos sucios**: "¡Excelente! Todos tus alumnos **están activos**" cuando significa "sin riesgo"; "Llevan más
   de **7** días sin entrenar" hardcodeado (debería leer `UMBRAL_ALERTA_DIAS`).
6. **Código muerto**: ninguno.
7. **Consistencia**: usa `alert()` mientras el resto del panel usa banners.

### 7. Gestión de Clases — `/coach/gestion-clases` (foco pedido)
**Los 2 items de la ronda anterior: APLICADOS** ✅
- **Fechas**: no queda ningún `toISOString().split`. Importa `hoyChileStr as hoyStr` y `toChileFechaStr as
  toLocalFechaStr` de `utils/fecha.js` y los usa (líneas 6, 32, 63, 81, 180).
- **WOD multi-día**: **1 sola llamada** `POST /wods/batch-create` (líneas 284-296) y el backend la ejecuta en
  **una transacción atómica** (`wods.py` 1161-1240: docstring explícito, un solo `try` con rollback completo si
  un día falla, `verificar_coach_disciplina` para coaches, bloqueo de `coach_id` ajeno, dedupe de fechas
  repetidas, y el frontend valida `wods_creados == dias_seleccionados`). `POST /wods/batch` quedó sólo para
  "vincular este WOD a esta clase" (1 llamada, no por día).

Criterios:
1. **activo vs estado**: `cd.activo` es de `coach_disciplinas` (tabla correcta). `Usuario.activo` sólo en backend (H-05).
2. **Fechas**: OK salvo `ahora.getHours()` (línea 181) para marcar "clase en curso" (hora del navegador, no la de
   Chile) y comparaciones mixtas: `c.fecha === fechaPlanif` (213, sin `split('T')[0]`) vs otras que sí normalizan (223).
3. **Fallas silenciosas**: H-10 (`wodsSemana[f] = []` y `setCoachDisciplinas([])` mudos; `toggleAsistencia` sólo
   `console.error`). El guardado del WOD sí propaga el error del backend (bien).
4. **IDOR**: H-02 (crear), H-03 (borrar WOD), H-15 (generar-clases-dia). Los que **sí** validan: `PUT /wods/{id}`,
   `POST /wods/batch-create`, `POST /wods/batch`, `POST /clases/{id}/ampliar-cupo`, `PUT /reservas/{id}/asistencia`,
   `GET /reservas/por-clase/{id}`.
5. **Datos sucios**: H-09 (navegación que miente), `'...no se pudo cargar its datos'`. Los mensajes de éxito del WOD
   son honestos (incluyen la cantidad de clases vinculadas).
6. **Código muerto**: `clasesDiaVista`/`claseEnCurso`/`modoEmergencia`/`confirmarEmergencia` se usan.
7. **Consistencia**: `GET /coach-disciplinas?coach_id=` → el backend **no tiene** ese parámetro: devuelve todas las
   relaciones del tenant y el filtro es del lado del cliente (parámetro muerto + mini-leak: un coach ve el mapa
   coach↔disciplina completo del box).

### Rutas huérfanas (ruteadas pero fuera del sidebar)
- `/coach/pizarra` (`Pizarra.jsx`, 41 KB): guarda WODs con `POST /wods` **sin `disciplina_id`** → para un coach el
  backend responde **400** ("disciplina_id es obligatorio para coaches") → **feature rota** si se entra por URL.
  Usa `POST /wods/parse` (abierto a cualquier autenticado) y `POST /movimientos` (coach/admin).
- `/coach/generar-clases` (`GenerarClases.jsx`): `POST /horarios/generar-clases-dia?fecha=` — cualquier coach puede
  generar clases de **cualquier fecha del box** (escritura global) y el backend recibe `fecha` como string sin validar.

### Extra — impacto de la migración de Neon de hoy
- **Código**: 0 hosts/credenciales hardcodeadas en el panel (frontend y backend del panel).
- **Conexiones/permisos**: probes read-only **200** en TEST y en la **PROD nueva** (sin errores de permisos ni de
  tablas faltantes). Tablas que usa el panel: `clases`, `reservas`, `usuarios`, `coach_disciplinas`, `wods`,
  `movimientos`, `historial_rm` + el servicio de asistencias.
- **Datos**: coherentes en PROD (100 movimientos, 3 coaches). `clases.asistentes_confirmados` coincide con las
  reservas reales (8/8 en TEST) → el "N/M alumnos" del panel es confiable.
- **Riesgo residual**: no viene de la migración, pero **H-01** (un GET que escribe) conviene tenerlo presente en
  cualquier smoke: una consulta de `/clases` con rango puede crear clases.

## Ronda de verificación 2026-09-26 — reconciliación de los hallazgos 7 y 8

Antes de implementar cualquier cosa se revisó el estado **actual** de los dos hallazgos (el
audit es del 2026-09-23 y después hubo varios cambios):

- **H-07 (🟡 Resumen / Alumnos & RMs) — `GET /historial-rm?limit=5` sin scope de coach +
  `historial_rm._verificar_acceso_alumno` trata `coach` como staff del box.**
  **Estado: DECISIÓN CERRADA, no se implementa** (FASE 2 de este mismo informe): es una
  decisión de producto (el coach ve/edita RM de cualquier alumno del box, no sólo de sus
  disciplinas). Sigue vigente tal cual; no se toca sin una decisión nueva y explícita.
  *No "arreglar" esto en el futuro sin esa decisión.*

- **H-08 (🟡 Resumen) — "WODs esta semana: X/Y publicados" contaba `c.wod_id != null`
  (un borrador contaba como publicado).**
  **Estado: YA RESUELTO** (no quedaba nada por hacer). En
  `frontend/src/pages/coach/DashboardCoach.jsx`:
  ```js
  // H-08: X/Y publicados debe contar los WODs realmente publicados (no los borradores)
  const wodsPublicados = new Set((wods || []).filter(w => w.estado === 'publicado').map(w => w.id));
  const clasesConWodPublicado = clasesSemana.filter(c => c.wod_id && wodsPublicados.has(c.wod_id)).length;
  ```
  y la tarjeta muestra `{clasesConWodPublicado}/{clasesSemana.length} con WOD publicado`.
  Cualquier corrección futura del conteo debe seguir usando `estado === 'publicado'`.

Conclusión de la ronda: **no hay nada que implementar por H-07/H-08**; quedan documentados
para que no se reintenten.

---

## Orden de implementación propuesto (para revisar en la mañana)
1. **H-04** `Promise.all` → `allSettled` + banner "Reintentar" (1 archivo, impacto alto).
2. **H-05 + H-06** `activo` → `estado` en `fidelizacion.py` (68, 155, 303, 419, 457) y `asistencia.py:358`.
3. **H-09 + H-13** copys y navegación (`?tab=clases`, "Progreso", "sin riesgo", `UMBRAL_ALERTA_DIAS`, `its datos`).
4. **H-08 + H-12** métrica real de WODs publicados y filtro de disciplinas con el valor calculado (no el state).
5. **H-10 + H-11** fallas silenciosas y "marcar todos" con el batch `POST /asistencia/clases/{id}/confirmar`.
6. **H-03 + H-02** IDOR de escritura (`DELETE /wods/{id}` y `POST /clases`: validar disciplina y `coach_id` propio).
   Es el punto más delicado: requiere suite + verificación 403 dirigida.
7. **H-07** RMs/`historial-rm` por disciplina: **decisión de producto** primero (hoy "coach = staff del box" es a propósito).
8. **H-01** separar la auto-generación de clases del GET (toca Admin: va después).
9. **H-14, H-15, H-16, H-17** limpieza: usuario `string` en PROD, rutas huérfanas (terminarlas o borrarlas),
   `pages/coach/Dashboard.jsx` y dead code (`statsCards`, `getEstadoColor`).

**Nota de método**: esto es 100% diagnóstico. No se modificó código ni datos; los únicos archivos nuevos son este
informe y (aparte) el re-seed de planes de TEST ya documentado. **No se corrió la suite** en esta sesión para no
resetear TEST antes de la auditoría de mañana.

## FASE 2 — Decisiones y propuesta (2026-09-24)

### H-07 — DECISIÓN CONFIRMADA (no se cambia)
`historial_rm._verificar_acceso_alumno` trata a `coach` como **staff del box**: un coach puede ver/editar los RM de
cualquier alumno del box, no sólo los de sus disciplinas. **Es una decisión de producto, no un bug: se deja como está.**
(El mismo criterio aplica a `GET /historial-rm?limit=5` del Resumen.) *No "arreglar" esto en el futuro sin una
decisión explícita nueva.*

### H-01 — PROPUESTA (no implementada; requiere OK)
`GET /api/v1/clases` **escribe**: si el rango consultado no tiene clases, las genera al vuelo (usa
`app/services/generar_clases.py` + `DIAS_ANTICIPACION = 28`). Evidencia recogida:

- La misma generación ya corre por **3 vías que NO son ese GET**:
  1. `main.py` (startup/lifespan): `generar_clases_para_rango(hoy, hoy + 28)`.
  2. `app/services/scheduler.py` (job diario 00:05 CLT): el mismo rango.
  3. `POST /api/v1/horarios/generar-clases-dia` (`horarios.py:111`) — explícito, y ya usado por
     `pages/coach/GenerarClases.jsx`.
- Consumidores del GET en el frontend (grep de `/api/v1/clases`): `pages/admin/Clases.jsx`,
  `pages/admin/SupervisionClases.jsx` (x2), `pages/coach/DashboardCoach.jsx`,
  `pages/coach/GestionClases.jsx` (x2) y `pages/alumno/Dashboard.jsx` — o sea que el fallback afecta a
  **Admin (Clases + Supervisión), Coach (Dashboard + Gestión) y Alumno (Dashboard)**: sacarlo mal rompe pantallas
  de Admin, por eso va con OK explícito.
- **Riesgo real de sacarlo**: bajo. Sólo se notaría al consultar un rango **más allá de hoy+28** (celdas vacías),
  y para eso ya existe el botón explícito de Generar Clases.

**Propuesta (para que la apruebes):**
1. Dejar el startup + el scheduler como están (son la fuente normal).
2. Quitar la escritura del `GET /clases`. Opción gradual y más conservadora: aceptar `generar=true` (opt-in,
   default `false`) y que las pantallas que hoy dependen del fallback lo pidan explícitamente.
3. Si alguna pantalla necesita generación on-demand, llamar a `POST /horarios/generar-clases-dia` (ya existe).
4. Verificación posterior: pantallas de clases de Admin (rango futuro), dashboard del coach y dashboard del alumno.

No se toca nada de esto hasta que confirmes el plan (afecta Admin).
