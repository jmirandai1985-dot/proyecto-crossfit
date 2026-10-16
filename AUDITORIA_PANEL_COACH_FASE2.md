# Auditoría Panel Coach — FASE 2 (los 10 bloques, diagnóstico solo lectura)

Fecha: 2026-10-15 · Autor: sesión de auditoría
**Estado: NO se tocó código de la aplicación.** El único archivo nuevo es este informe.
Precedente: `AUDITORIA_PANEL_COACH.md` (2026-07-13) y `AUDITORIA_PANEL_COACH_FASE1.md` (2026-09-23).
Alcance: los 10 bloques reportados sobre `/coach/dashboard` (+ `/coach/gestion-clases`, `/coach/entregar-pedido`) y los endpoints que los alimentan (`fidelizacion.py`, `historial_rm.py`, `reportes.py`, `nivel_service.py`).

## Cómo se auditó (evidencia)

- Lectura de código con `Select-String` (cada línea citada es una línea real del archivo, con su número; nada de paráfrasis).
- **Se re-ejecutaron los 5 tests que ya fijan estos flujos**, todos verdes ANTES de proponer nada:

  | comando | resultado |
  |---|---|
  | `npm run test:walkin` | `TODO OK` (todos los PASS) |
  | `npm run test:publicar-wod` | `TODO OK` |
  | `npm run test:coach-subtabs` | `TODO OK` |
  | `npm run test:asistencia-franjas` | `Todos los chequeos pasaron` |
  | `npm run test:boton-volver` | `Todos los chequeos pasaron` |

- NO se tocó la BD, no se hicieron POST/PUT/DELETE, y **no se llamó a `GET /api/v1/clases`** (ese GET escribe clases faltantes — H-01 de FASE 1).
- Donde el veredicto depende de **datos** del box (Bloques 3 y 9) el informe deja el SQL exacto **y lo ejecutó, solo lectura**, contra la BD de producción, pegando la salida en cada bloque:
  - Conexión por el engine propio del backend (`app.db.database.engine`) con `ENVIRONMENT=production` → host `ep-nameless-sound-b6km6wyi-pooler.c-2.sa-east-1.aws.neon.tech`, base `neondb`, usuario `neondb_owner`.
  - **Sólo `SELECT`** (nada de INSERT/UPDATE/DELETE/DDL) y **sin datos personales**: las consultas devuelven conteos, `tenant_id`/`coach_id` y etiquetas (`BASICO`), nunca nombres ni correos.
  - Nota operativa: sin `ENVIRONMENT=production` la config asume TEST y carga `.env.test` → falla el login con *"password authentication failed for user 'neondb_owner'"*. Por eso el SQL se corrió con la variable puesta de forma explícita.

## Resumen ejecutivo

| # | Bloque | Sev | Veredicto (con la evidencia) |
|---|---|---|---|
| 1 | Unificar "Publicar WOD" (3→1) | 🔴 | Confirmado: hoy hay **2 publicadores vivos** (modal del Resumen + panel inline de Gestión de Clases) y **1 huérfano** (`Pizarra.jsx`, sin ruta). El modal único **no sabe editar** un WOD existente (`modoEdicion` + `PUT /wods/{id}` viven sólo en Gestión de Clases). Fusionar exige paridad de 4 cosas antes de borrar nada. |
| 2 | Confirmar antes de descontar token | 🔴 | Confirmado: **un clic** en el nombre del alumno ejecuta la cadena que descuenta (crea reserva + lo deja presente). No hay segundo paso. |
| 3 | "En Riesgo" muestra **0** | 🔴 | **Causa raíz CONFIRMADA con datos**: `/coach/{id}/en-riesgo` filtra **sólo** por `Clase.coach_id` (`fidelizacion.py:296`), su hermano `/coach/{id}/alumnos` incluye además las **disciplinas** del coach (`:409-416`). En prod: 2 de los 3 coaches con disciplina tienen **0 alumnos** por `coach_id` y **305 / 297** por disciplina; ninguna clave está mal escrita (`DashboardCoach:250` lee `alumnos_alerta`, que es lo que el backend devuelve). |
| 4 | Asistencia por franjas | 🟡 | El corte por franja ya existe (<768px). Lo que **no** existe es **elegir** franja: `IDS_FRANJAS` y `franjaActual` están exportados en el util y **sin consumir** en esa pestaña (sólo los usa el Inicio móvil del admin). |
| 5 | "Alumnos & RMs" | 🟡 | La lista SÍ es coach-scoped (403 si se pide otro `coach_id`), pero los RMs llegan con **1 GET por alumno** (hasta 50). El perfil del alumno tiene **2 implementaciones** (modal del coach vs. pestaña). |
| 6 | Botón "atrás" | 🟡 | Sí existe la función: `navegacion.js:17` `VOLVER_ATRAS = -1` → `navigate(-1)` vía `destinoVolver` (no hay un `navigate(-1)` escrito a mano, está centralizado con test). Lo que **no** existe es flecha en escritorio: `BotonVolver` es `md:hidden` y las raíces (el Dashboard del coach) no la llevan. Falta precisar cuál de las 3 lecturas es el pedido. |
| 7 | Avisos | ⏳ | **Sin requisito**. Hay un camino vivo (aviso rápido, con test propio) y el admin es quien elige tipo/vigencia. Necesito el enunciado del bloque. |
| 8 | Reporte | ⏳ | **Sin requisito**. `reportes.py` hoy expone 2 GET (`GET /`, `GET /monthly-sales`) y la "Duda 1" (columnas del reporte descargable) sigue abierta en `PENDIENTE_DECISION_USUARIO.md`. |
| 9 | "nivel de atleta" en BD | 🟢 | **No hay columna de nivel en el alumno**: el nivel se **calcula** en vivo (`nivel_service.py:9,13,63,152`) y sólo lo consumen 3 endpoints de `historial_rm.py`. La tabla `student_segments.nivel` (migración 021) no tiene **ningún** importador: su propio modelo lo dice (*"quedó sin usarse"*). No hay nada que cambiar; sólo decidir si se elimina la tabla huérfana. |
| 10 | Diagnóstico / rendimiento | 🟠 | `useProgresoAlumnosCoach` (`queries.js:942-979`) hace **N GET** (1 por alumno, hasta 50 en `Promise.all`) contra un backend que **no tiene endpoint de lote**; el propio comentario admite que antes eran "50 GET EN SERIE". Además `useRmsAlumno` repite el mismo `/rms` para el alumno ya traído en el lote. |

---

## Bloque 1 — Unificar "Publicar WOD" (3 entradas → 1 modal)

### Evidencia (lo que hay hoy)

**(a) Modal del Resumen — el único "modal único" que existe**
- `DashboardCoach.jsx:17` lo importa y `:1077` lo renderiza; el estado que lo abre es `modalWod` (`:37`). **Es el único lugar del repo que lo monta** (verificado con búsqueda de `ModalPublicarWod` en `frontend/src`).
- `ModalPublicarWod.jsx:32-42`: props `{ clase, onCerrar, onPublicado }` y estado `modo` (`'manual' | 'archivo'`), `alcance` (`'hora' | 'dia' | 'semana'`), `form`.
- `ModalPublicarWod.jsx:36-39`: campos `calentamiento`, `musculacion`, `wod_nombre`, `wod_tipo` (default `'For Time'`), `wod_descripcion`, `aviso`.
- `ModalPublicarWod.jsx:49`: `TIPOS = ['For Time', 'AMRAP', 'EMOM', 'Otro']` → **lista fija**.
- `ModalPublicarWod.jsx:72-80`: el body que publica:
  `titulo: form.wod_nombre` · `fuerza_habilidad: form.musculacion` · `wod_principal: form.wod_descripcion` · `tipo_metcon: form.wod_tipo || 'Otro'` · `estado: 'publicado'`.
- `ModalPublicarWod.jsx:44-47`: usa `useCrearWodsBatch`, `usePrevisualizarSemana`, `useProgramarSemana`, `usePublicarAvisoRapido`. **No** usa `useGuardarWod` ni manda `wodId`.
- `:170`/`:305`/`:354-359`: `data-testid="modal-publicar-wod"`, `"publicar-wod"`, `"programar-semana"`.

**(b) Panel inline de Gestión de Clases — el segundo publicador vivo**
- `GestionClases.jsx:117` `modoEdicion`; `:125` `wodForm { titulo, calentamiento, fuerza_habilidad, wod_principal, tipo_metcon, estado: 'publicado' }`.
- `GestionClases.jsx:145` `diasSeleccionados` (**Set** de días, arranca con hoy) y `:150` `alcance`.
- `GestionClases.jsx:174-175` `guardarWodMut = useGuardarWod()` + `crearWodsBatch = useCrearWodsBatch()`.
- `GestionClases.jsx:341-348`: **si `wod.id` existe → `guardarWodMut` (`PUT /wods/{id}`)** y el mensaje es "WOD actualizado".
- `GestionClases.jsx:326-339`: **modo emergencia** (`params.modo_emergencia = true`) cuando el coach publica en una disciplina que no es suya, con confirmación previa.
- `GestionClases.jsx:353-376`: multi-día (`diasMarcados`) + alcance `'hora'`/`'dia'` (`clase_ids` o sin él).
- `GestionClases.jsx:794-815`: inputs (incl. **`tipo_metcon` como texto libre**, `:810`) y el botón `data-testid="guardar-wod"` cuyo label cambia a **"💾 Actualizar WOD"** (`:815`). El CTA de entrada es `:883` "📝 Publicar WOD".

**(c) `Pizarra.jsx` — el publicador huérfano**
- `Pizarra.jsx:86` `HORARIOS_SEMANA` (grilla Lun–Dom hardcodeada), `:108` `publicarWod = useCrearWod()` (endpoint viejo, **no** batch), `:351` `crearWod(estado)`, `:789`/`:796` botones `'draft'`/`'publicado'`, `:800` "Publicar WOD".
- **Sin ruta**: `App.jsx:153-163` declara sólo `dashboard`, `gestion-clases` y `entregar-pedido` bajo `/coach/*`; `:160-162` comenta que las retiradas "ya no tienen ruta" y `:163` manda el comodín a `/coach/dashboard`. El test `test-boton-volver.mjs` lo fija: *"App.jsx tiene las 3 pantallas del coach (vistas: 3; Bloque 5: Pizarra y Generar Clases se retiraron)"*.

### Hallazgo

El "3 → 1" real es **2 vivos + 1 huérfano**, y el modal único **no tiene paridad** con el panel de Gestión de Clases. Estas 4 piezas viven **sólo** en el inline:

| Pieza | Gestión de Clases (inline) | `ModalPublicarWod` |
|---|---|---|
| **Editar** un WOD existente | sí (`modoEdicion` + `useGuardarWod` → `PUT`) | **no** |
| Elegir **días sueltos** (varios) | sí (`diasSeleccionados`) | sólo este horario / todo el día / la semana completa |
| `tipo_metcon` **libre** | sí (`<input>`) | lista fija `TIPOS` (`:49`) |
| **Modo emergencia** (clase de disciplina ajena) | sí (`:326-339`) | **no** |

Y al revés, dos cosas sólo viven en el modal: el **archivo .xlsx de la semana** y el **aviso del día dentro del mismo formulario** (el inline usa el `ModalAvisoRapido` aparte, con su test `test-aviso-rapido.mjs`).

**Riesgo de borrar el inline sin migrar primero:** se pierde "Actualizar WOD" (hoy no hay ninguna otra forma de editar un WOD ya publicado) y el modo emergencia. Eso es lo que hay que mover antes de eliminar nada.

### Propuesta (NO ejecutada)

1. **Paso A — paridad**: agregar al modal props opcionales para editar (`wod`), multi-día, `tipo_metcon` libre y modo emergencia, sin cambiar su comportamiento actual cuando no se pasan (así `test:publicar-wod` sigue verde).
2. **Paso B — retirar duplicados**: en `GestionClases` reemplazar el panel inline por un botón que abra el mismo modal (con la clase del día); en `Pizarra`, borrar el formulario viejo (el archivo ya no tiene ruta).
3. Mantener el aviso rápido como está (`test-aviso-rapido.mjs` ya lo fija).

### Verificación
`npm run test:publicar-wod` + `npm run test:aviso-rapido` + `npm run test:walkin` (los tres leen el modal y su backend) + captura de pantalla de "Actualizar WOD" desde el modal unificado.

---

## Bloque 2 — Confirmar antes de descontar token 🔴

### Evidencia

- `ModalAgregarSinReserva.jsx:153-169`: cada alumno de la lista **es un `<button>`**, con `onClick={() => agregar(a)}` (`:159`) y `data-testid="agregar-alumno-{id}"` (`:160`). La pista que anticipa el cargo (`pista(a)`, `:62-68`: *"se descuenta 1"* / *"queda sin cargo"*) se pinta **dentro del mismo botón** (`:169`).
- `ModalAgregarSinReserva.jsx:71-95`: un solo clic ejecuta la cadena completa que **descuenta**:
  - `if (alumno.puede_reservar)` (`:76`) → `crearReserva.mutateAsync({ tenant_id, alumno_id, clase_id, estado: 'confirmada' })` (`:77-80`) + `marcarAsistencia.mutateAsync({ reservaId: reserva.id, asistio: true })` (`:81`) → `cargo: 'credito'` (`:82`).
  - si no → `presenteSinReserva.mutateAsync(...)` (`:84-87`) → `cargo: 'sin_cargo'`.
- No hay ningún paso intermedio entre el `onClick` y el `mutateAsync`. Cerrar el modal después no revierte nada (no hay "deshacer" en el panel del coach).
- El botón existe sólo para el coach: la prop `permitirSinReserva` nace en `false` y **una sola pantalla** la pasa (`DashboardCoach:1019` → `<AsistenciaClases franjas permitirSinReserva />`), fijado por `test-walkin.mjs`: *"sólo UNA pantalla (el coach) pide el walk-in"*.
- Descartado como parte de este bloque: `EntregarPedido.jsx:28-80` (coach) **no** descuenta tokens — entrega por código con `ModalEntregarPedido`, sin clic sobre un alumno.

### Hallazgo

Es una acción que **toca dinero** (créditos del alumno) y se dispara con **un clic sobre una fila**, sin segundo paso. La pista existe pero está pegada al mismo botón que ejecuta: el coach lee y ejecuta en el mismo gesto, y un toque accidental en el teléfono ya consumió el crédito.

### Propuesta (NO ejecutada)

- Tarjeta de confirmación **dentro** del mismo modal (2º paso): muestra alumno, clase, hora y el texto exacto de `pista(a)` ("se descuenta 1" / "queda sin cargo") con **Cancelar / Confirmar** (`disabled` mientras `agregandoId`).
- Nuevo `data-testid` para el confirmar, y el test `.mjs` (patrón `test-walkin.mjs`, que ya lee la fuente) agrega: *"el clic en la fila NO llama a `crearReserva.mutateAsync`"* y *"sólo el confirmar dispara el descuento"*.
- Decisión: ¿la confirmación se pide **siempre**, o sólo cuando `puede_reservar` (el camino sin cargo no toca dinero)?

### Verificación
`npm run test:walkin` + captura del 2º paso (antes/después) + prueba manual de los dos caminos (con crédito y sin cargo).

---

## Bloque 3 — "En Riesgo" muestra 0 🔴 (causa raíz CONFIRMADA con datos)

### Evidencia

**El endpoint del KPI/lista del tab Riesgo** — `backend/app/api/v1/fidelizacion.py`:
- `:269-270` `@router.get("/coach/{coach_id}/en-riesgo")` → `def alumnos_coach_en_riesgo(`.
- `:280` (docstring) *"donde clases.coach_id coincide con ese coach"*; `:286` candado `403` si un coach pide otro `coach_id`.
- `:294-297` — **el único filtro sobre las clases**:
  ```python
  Clase, Reserva.clase_id == Clase.id
  ...
  Clase.coach_id == coach_id,
  Clase.tenant_id == tenant_id,
  ```
- `:428` cuando no hay alumnos devuelve `{"total_alumnos": 0, "alumnos": []}`.

**Su hermano `alumnos_de_coach`** (el del tab Alumnos, misma base):
- `:387-388` `@router.get("/coach/{coach_id}/alumnos")` → `def alumnos_de_coach(`; `:395` el mismo `403`.
- `:381-384` comentario que explica el criterio: *"en una clase donde el coach es el asignado (clases.coach_id) O en una clase \[de sus disciplinas] ... las clases pueden no tener coach_id explícito y aun así pertenecer al coach por \[disciplina]"*.
- `:401-405` `disc_ids` desde `CoachDisciplina` (`tenant_id`, `coach_id`, `activo == True`).
- `:409-416`:
  ```python
  filtro_clase = [Clase.tenant_id == tenant_id]
  if disc_ids:
      filtro_clase.append(or_(Clase.coach_id == coach_id, Clase.disciplina_id.in_(disc_ids)))
  else:
      filtro_clase.append(Clase.coach_id == coach_id)
  ```
- `:419-421` join + `no_cancelada(Reserva.estado)`.

**Frontend** (lo que ve el coach): `DashboardCoach.jsx:961-1010` pinta `alumnosEnRiesgo`; cuando está vacío muestra `:1005-1009` *"🎉 ¡Excelente! Ningún alumno está en riesgo"*. El dato viene de `useAlumnosCoachEnRiesgo` → `hooks/queries.js:931-935` → `GET /api/v1/fidelizacion/coach/{coachId}/en-riesgo` (clave `queries.js:98`).

**Ningún test cubre este endpoint**: `test-fidelizacion-movil.mjs` prueba las **tarjetas móviles del admin** (`src/pages/admin/FidelizacionMovil.jsx`), no el `en-riesgo` del coach. Por eso el bug pudo pasar desapercibido.

### Hallazgo

Los dos endpoints hermanos **no comparten definición de "alumno del coach"**: el de `/alumnos` (que sí llena la lista) usa `coach_id` **o** disciplinas del coach; el de `/en-riesgo` usa **sólo** `Clase.coach_id`. En un coach que dicta por **disciplina** (clases sin `coach_id` explícito) el universo del `en-riesgo` queda **vacío** → el coach ve "Ningún alumno está en riesgo" aunque el tab Alumnos tenga gente. Es exactamente el patrón del bug ya corregido en el commit `3dc8f7b`.

Segunda causa posible (a descartar con la misma query): FASE 1 (H-05) documentó que estos endpoints filtran por **`activo`** mientras la migración 034 dice que la fuente de verdad es **`estado`** (`activo` es derivado). Si además el filtro por `activo` esconde alumnos, hay que corregir las dos cosas juntas.

### Confirmación ejecutada — CAUSA RAÍZ CONFIRMADA con datos de producción

SQL por coach (la forma "de a uno"; abajo está la forma conjunta que realmente se corrió):
SELECT COUNT(DISTINCT r.alumno_id) AS por_coach_id
FROM reservas r JOIN clases c ON r.clase_id = c.id
WHERE c.tenant_id = :t AND c.coach_id = :x;

-- B) Universo del hermano "/alumnos" (coach_id O sus disciplinas)
SELECT COUNT(DISTINCT r.alumno_id) AS por_disciplina
FROM reservas r JOIN clases c ON r.clase_id = c.id
WHERE c.tenant_id = :t
  AND (c.coach_id = :x
       OR c.disciplina_id IN (SELECT disciplina_id FROM coach_disciplinas
                              WHERE tenant_id = :t AND coach_id = :x AND activo = true));

-- C) Sus clases: ¿tienen coach_id o heredan el vínculo por disciplina?
SELECT COUNT(*) FILTER (WHERE c.coach_id = :x) AS con_coach_id,
       COUNT(*) FILTER (WHERE c.coach_id IS DISTINCT FROM :x) AS sin_coach_id
FROM clases c
WHERE c.tenant_id = :t
  AND c.disciplina_id IN (SELECT disciplina_id FROM coach_disciplinas
                          WHERE tenant_id = :t AND coach_id = :x AND activo = true);
```

**Lectura esperada (ya verificada):** si **A = 0 y B > 0** → causa confirmada.

**SQL realmente ejecutado** (forma conjunta: calcula A y B para **todos** los coaches de una sola pasada):

```sql
WITH base AS (
  SELECT d.tenant_id, d.coach_id,
         COUNT(DISTINCT r.alumno_id) FILTER (WHERE c.coach_id = d.coach_id) AS A,
         COUNT(DISTINCT r.alumno_id) AS B
  FROM coach_disciplinas d
  JOIN clases c ON c.tenant_id = d.tenant_id AND c.disciplina_id = d.disciplina_id
  LEFT JOIN reservas r ON r.clase_id = c.id
  WHERE d.activo = true
  GROUP BY d.tenant_id, d.coach_id)
SELECT COUNT(*) AS coaches_con_disciplina,
       COUNT(*) FILTER (WHERE A = 0 AND B > 0) AS A_cero_y_B_positivo,
       COUNT(*) FILTER (WHERE A = B) AS A_igual_B
FROM base;
```

**Salida real (solo lectura, 15-10-2026):**

```
=== 1_clases ===
{'clases': 7136, 'con_coach_id': 1795, 'sin_coach_id': 5341}

=== 2_coach_disciplinas ===
{'filas': 8, 'activas': 7, 'coaches': 3}

=== 3_A_vs_B_por_coach ===
{'tenant_id': 1, 'coach_id': 531, 'clases_con_coach_id': 0, 'clases_por_disciplina': 7136, 'alumnos_A': 0, 'alumnos_B': 305}
{'tenant_id': 1, 'coach_id': 10,  'clases_con_coach_id': 0, 'clases_por_disciplina': 2480, 'alumnos_A': 0, 'alumnos_B': 297}
{'tenant_id': 1, 'coach_id': 7,   'clases_con_coach_id': 1791, 'clases_por_disciplina': 599, 'alumnos_A': 268, 'alumnos_B': 294}

=== 4_veredicto ===
{'coaches_con_disciplina': 3, 'A_cero_y_B_positivo': 2, 'A_igual_B': 0}
```

**Conclusión con datos** (`A` = lo que ve hoy el `en-riesgo`; `B` = lo que ve `/alumnos`):

- **2 de los 3 coaches con disciplina están en el caso patológico** `A = 0` **y** `B > 0` (coach 531: **0 vs 305**; coach 10: **0 vs 297**) → para ellos el tab Riesgo dice *"Ningún alumno está en riesgo"* con certeza, y el tab Alumnos sí les muestra sus ~300 alumnos. **Causa raíz confirmada.**
- **Ningún** coach en el caso `A = B` (0 de 3) → la hipótesis queda sin contraejemplo.
- El coach 7 funciona porque sus clases **sí** tienen `coach_id` (1791 de 2384); aun así pierde 26 alumnos (294 − 268) que sólo lo son por disciplina.
- Por qué pasa: de **7136** clases, **5341 (75%) no tienen `coach_id`** → el vínculo coach↔clase en este box vive sobre todo en `coach_disciplinas`, que es justo lo que el `en-riesgo` ignora.

**Descartadas con la misma corrida:** (a) que el frontend lea una clave que el backend no manda → `DashboardCoach.jsx:250` `riesgoQ.data?.alumnos_alerta` coincide exacto con `fidelizacion.py:308` `"alumnos_alerta": []`; (b) que la respuesta vacía venga de `Usuario.estado == "activo"` (`:315`) — el corte ocurre **antes**, en `:302-309`, sobre la lista vacía de `alumno_ids`.

### Propuesta (NO ejecutada, ya confirmada la causa)

- Extraer el armado de `filtro_clase` de `alumnos_de_coach` (`:401-416`) a **un solo helper** y usarlo también en `alumnos_coach_en_riesgo`, para que "alumno del coach" se defina en un único lugar.
- Alinear `no_cancelada(Reserva.estado)` (que el de `/alumnos` sí usa y `en-riesgo` no) y revisar el filtro por `activo` (H-05).
- Test backend nuevo (patrón `backend/tests/`): un coach **sin** `coach_id` en las clases pero con la disciplina asignada debe ver a sus alumnos en `en-riesgo` (hoy daría 0).

### Verificación
Captura de A/B/C **ya incluida arriba** (2 de 3 coaches en el caso patológico; 0 con `A = B`) + un test de backend que falle con el código actual y pase con el fix. La nota de H-05 (`activo` vs `estado`) sigue en pie como riesgo aparte, pero **no** es la causa de este síntoma: la lista se vacía en `:302-309`, antes de cualquier filtro de estado.

---

## Bloque 4 — Asistencia del coach por franjas 🟡

### Evidencia

**Lo que YA existe (<768px)** — fijado por `test-asistencia-franjas.mjs`:
- `AsistenciaClases` recibe `franjas = false` (prop opcional; el admin no la pasa y su DOM no cambia).
- La lista por franja existe **sólo** en móvil (`md:hidden`) y el corte sale del util compartido `agruparPorFranja`.
- Monta `AsistenciaFranja`, que **no lee el reloj**: el "En curso" lo calcula el backend en hora de Chile; los 3 números de la fila salen de `contadoresClase`.
- Se monta una sola vez: `DashboardCoach.jsx:1018-1019` (`activeTab === 'asistencia'` → `<AsistenciaClases franjas permitirSinReserva />`).

**Lo que NO existe: elegir franja.**
- `utils/franjasAsistencia.js:30` `export const IDS_FRANJAS = FRANJAS.map((f) => f.id)` → **cero consumidores** en todo `frontend/src` (búsqueda de `IDS_FRANJAS` sólo devuelve su propia definición).
- `utils/franjasAsistencia.js:63` `export const franjaActual = (horaHHMM) => franjaDe(horaHHMM)` → su **único** consumidor es el Inicio móvil del **admin** (`InicioMobileAdmin.jsx:49` y `:441 franjaReloj = franjaActual(ahora)`).
- `AsistenciaFranja.jsx:29` (docstring de props): `franja {id,label}, clases[], osc, formatearHora, onAbrir, onAmpliarCupo` → **no recibe** "cuál es la franja de ahora", así que no puede resaltarse ninguna.
- En la pestaña las franjas se apilan (`franjasConClases.map`) y `franjaActual`/`IDS_FRANJAS` no se importan.

### Hallazgo

El *corte* por franjas está hecho y testeado; el *selector* de franja no. El util ya tiene las dos piezas para hacerlo bien (`IDS_FRANJAS` para el orden canónico y `franjaActual` para el default), pero **nadie las usa en la pestaña del coach**: el coach ve Mañana/Tarde/Noche una debajo de la otra, sin chips ni franja activa. Además `franjaActual` es hoy un dato **del admin**; reusarlo acá es el movimiento natural (una sola definición de "qué franja es ahora").

### Propuesta (NO ejecutada)

- Chips Mañana / Tarde / Noche arriba de la lista, con la franja del **reloj** seleccionada por defecto (`franjaActual`) y las 3 siempre visibles (`IDS_FRANJAS`, para no perder la de la madrugada).
- Reusar `franjaActual(resumenFranja(...))` o el `ahora` que ya maneja la pestaña — **sin** volver a escribir el rango horario en el componente.
- Test `.mjs` nuevo (patrón `test-asistencia-franjas.mjs`): *"el default sale del util y no de una constante nueva"* y *"los chips usan IDS_FRANJAS"*.

### Verificación
`npm run test:asistencia-franjas` + captura en <768px con la franja del reloj activa.

---

## Bloque 5 — "Alumnos & RMs" 🟡

### Evidencia

**La pestaña** (`DashboardCoach.jsx:766` `activeTab === 'alumnos'`, hasta `:844`):
- Buscador local (`searchTerm`, `:30`) sobre la lista que trae `useAlumnosDeCoach(usuario_id)` (`:186`) → `GET /api/v1/fidelizacion/coach/{coachId}/alumnos` (`hooks/queries.js:919-924`, con `403` si se pide otro coach).
- Al elegir un alumno, los RMs salen de `useRmsAlumno(selectedAlumno?.id)` (`:189`) → `GET /api/v1/historial-rm/alumnos/{id}/rms` (`queries.js:470-473`).
- El enriquecimiento de progreso de la lista sale de `useProgresoAlumnosCoach(alumnosQ.data)` (`:187`) — ver Bloque 10.
- Últimos RMs del box: `useHistorialRmTodos(5)` (`:188`) — es el endpoint sin scope de coach de FASE 1 (H-07).

**El perfil del alumno tiene DOS implementaciones**:
- El botón "Ver Perfil" del tab Riesgo (`:995`) setea `fichaAlumnoId` (`:114`) y monta el **modal del coach**: `:1036-1041 <AlumnoFichaCoach alumnoId=… onClose=… />`.
- El modal del **admin** (`AlumnoFichaModal`) es otro componente: `AlumnoFichaCoach.jsx` documenta que no lo reusa porque aquél pega a endpoints de admin.

**Endpoints de perfil reutilizables** (para no duplicar lecturas): `GET /api/v1/alumnos/{id}/historial` (`queries.js:645`) y, en `backend/app/api/v1/historial_rm.py`: `:587 /alumnos/{id}/nivel-general`, `:601 /nivel-fuerza`, `:775 /nivel-gimnastico`, `:648 /progreso-destacado`.

### Hallazgo

- La pestaña lista **bien** (scoped al coach) pero cuando el alumno se elige, los RMs son **una consulta más por alumno** dentro de la misma pantalla que ya trae el lote (Bloque 10): el mismo alumno puede pedirse 2 veces por caminos distintos.
- El perfil del alumno existe en dos piezas (modal coach vs. pestaña) con fuentes distintas; hay que decidir cuál es "la" ficha y si el tab Alumnos debería abrir **la misma**.

### Propuesta (NO ejecutada)

- Reusar `AlumnoFichaCoach` desde el tab Alumnos (mismo modal, sin duplicar lectura de RMs) y dejar la lista sólo como índice/buscador.
- Si se quiere el detalle embebido, alimentarlo con el **lote** del Bloque 10 en vez de un GET nuevo.

### Verificación
`npm run test:coach-subtabs` (fija que la pestaña existe y navega) + captura del perfil abierto desde Alumnos.

---

## Bloque 6 — Botón "atrás" del coach 🟡 (hay que precisar el pedido)

### Evidencia

- **La función "volver atrás" existe y está probada.** `utils/navegacion.js:17` `export const VOLVER_ATRAS = -1` (`:16` comenta *"`-1` es lo que entiende el router para 'un paso atrás' (history.back())"*) y `:23` `destinoVolver(key, fallback)` → devuelve `-1` si la pantalla **no** es la primera de la app, o el `fallback` si se abrió la URL directa/recargada. `BotonVolver.jsx:37` lo consume: `navigate(destinoVolver(key, fallback))`.
- Ojo con la búsqueda literal: **no hay un `navigate(-1)` escrito a mano** en el repo, pero ése es exactamente el valor que devuelve `destinoVolver`; la lógica está centralizada a propósito (una sola definición, con test).
- `BotonVolver.jsx:45`: `className="md:hidden …"` → **la flecha sólo existe en <768px**. En escritorio, coach y alumno, no hay flecha (regla de oro: *"en ≥768px el escritorio se ve EXACTAMENTE igual que hoy"*, documentada en `:11-12`).
- `BotonVolver.jsx:29-30`: *"NO lo usan las raíces de cada panel (el Inicio del alumno, el del admin y el Dashboard del coach): ahí no hay 'atrás'"*.
- **Estado real por pantalla del coach** (salida de `test-boton-volver.mjs`, todo PASS):
  - `coach/DashboardCoach.jsx`: *"es la RAÍZ (dashboard) y NO lleva flecha Volver"*.
  - `coach/GestionClases.jsx`: *"dibuja `<BotonVolver fallback="/coach/dashboard" />`"*.
  - `coach/EntregarPedido.jsx`: *"dibuja `<BotonVolver fallback="/coach/dashboard" />`"* (también visible en `EntregarPedido.jsx:28`).
  - `coach/Pizarra.jsx` y `coach/GenerarClases.jsx`: siguen dibujándola, pero **no tienen ruta** (`SIN_RUTA_COACH` en el test; `App.jsx:160-163`).

### Hallazgo

No falta "la función": falta definir qué falta. Sólo quedan 3 lecturas posibles, y cada una choca con algo distinto:

1. **"Quiero flecha también en escritorio"** → hoy `md:hidden` es deliberado y lo fija un test; cambiarlo toca las pantallas de alumno y admin a la vez.
2. **"Quiero flecha en el Dashboard del coach"** → el Dashboard es la raíz; `BotonVolver.jsx:29-30` y el test dicen explícitamente que la raíz no la lleva (ahí `-1` saldría del panel o del sitio según cómo se entró).
3. **"Desde Gestión de Clases / Entregar pedido, en escritorio, no tengo cómo volver al Resumen"** → ésta es la lectura compatible con el código: la navegación de vuelta existe **sólo en móvil**; en escritorio se depende del sidebar.

### Propuesta (NO ejecutada — depende de la respuesta)

- Si es (3): un enlace/botón **visible también en escritorio** ("← Volver al Resumen") en el header de `GestionClases`/`EntregarPedido`, sin tocar `BotonVolver` (que seguiría siendo la flecha móvil) → no rompe la regla de oro ni los tests.
- Si es (1) o (2): es una decisión de UX que cambia pantallas de 3 paneles; se implementa **después** de aceptarla explícitamente.

### Verificación
`npm run test:boton-volver` (fija raíz/`md:hidden`/44px/`aria-label`) + captura en ≥768px y <768px.

---

## Bloque 7 — Avisos ⏳ (falta el enunciado)

**Lo que hay (verificado):**
- Un solo camino para el staff: `POST /api/v1/marketing/aviso-rapido` (`backend/app/api/v1/marketing.py:146-149`), consumido por el hook `usePublicarAvisoRapido` (`frontend/src/hooks/queries.js:1603-1606`) dentro de `components/ModalAvisoRapido.jsx`.
- **El payload del coach es de un solo campo** (`{ texto }`): no elige `tipo`, ni `vigente_desde/hasta`, ni `fijado_arriba`, ni flyer. Lo fija `test-aviso-rapido.mjs` (*"el coach NO elige el tipo"*, *"NO ofrece fechas de vigencia"*, *"NO ofrece flyer"*).
- La ventana (HOY) la arma el backend: `services/avisos_marketing.py` (`payload_aviso_de_fecha` / `rango_vigencia(fecha, fecha)`), citado por `test-publicar-wod.mjs`.
- Entradas vivas: `GestionClases` (barra `data-testid="abrir-aviso-rapido"` + modal) y el campo *"Aviso que verán los alumnos hoy"* dentro de `ModalPublicarWod`.
- El admin sí administra tipo/vigencia/fijado/flyer (`marketing.py:103-245`: `POST /`, `PUT /{id}`, `POST/DELETE /{id}/imagen`, `DELETE /{id}`, `GET /`, `GET /vigentes`).

**Falta**: qué se pide para el coach en este bloque (¿ver los avisos ya publicados? ¿editarlos? ¿avisos por disciplina? ¿programar el de mañana?). Con el enunciado, el informe se completa y se decide si reusa `aviso-rapido` o necesita piezas del admin.

---

## Bloque 8 — Reporte ⏳ (falta el enunciado)

**Lo que hay (verificado):** `backend/app/api/v1/reportes.py` expone hoy **2 GET**: `GET /monthly-sales` (`:47`) y `GET /` (`:92`).
**Lo que bloquea:** la **"Duda 1"** de `PENDIENTE_DECISION_USUARIO.md:4-5` sigue abierta — *"Columnas del reporte descargable (Excel)"* — y es exactamente la decisión que hace falta antes de tocar este bloque.

**Falta**: qué reporte, de qué pantalla y con qué columnas (¿el coach exporta asistencia de sus clases? ¿alumnos? ¿RMs?). Sin eso no se propone endpoint ni pantalla.

---

## Bloque 9 — "Nivel" 🟢 (el código ya resuelve lo que pedía el enunciado)

### Evidencia

- **El nivel NO vive en la base: se calcula al vuelo.** `backend/app/services/nivel_service.py:9` `NIVELES = ["Principiante", "Intermedio", "Avanzado", "Elite"]`; `:13 obtener_nivel_fuerza(...)`, `:63 obtener_nivel_gimnastico(...)`, `:152 calcular_nivel_general(alumno_id, db, tenant_id)`.
- Sus **únicos** consumidores: `backend/app/api/v1/historial_rm.py:20-21, 29` → `:598` (`/alumnos/{id}/nivel-general`), `:617` (`/nivel-fuerza`), `:791` (`/nivel-gimnastico`).
- **La tabla `student_segments` está muerta y su propio modelo lo dice**: `backend/app/models/student_segments.py:1-6` — *"tabla analítica `student_segments` … que quedó sin usarse. NO confundir con `segmentacion_alumnos`"*. Búsqueda de `StudentSegment` en todo `backend/app`: **sólo aparece en su propio archivo** (`:20, :21, :39, :40, :44`); ningún `import`, ningún endpoint, ningún servicio. Su columna `nivel` (`:44`) **no tiene consumidores**.
- **La segmentación que SÍ se usa es otra**: `segmentacion_alumnos` (`models/segmentacion_alumno.py:27-28`) con `arquetipo`/`modelo_fecha` → `kpis.py:115-117`, `segmentacion.py:116-124`, `services/historial_alumno_service.py:939-941`.
- Espejo del mismo par en frontend: `queries.js:587` (`/nivel-general`), `:601` (`/nivel-fuerza`), `:775` (`/nivel-gimnastico`), `:648` (`/progreso-destacado`).

**Confirmado con datos (solo lectura, 15-10-2026):**

```
=== 5_student_segments ===
{'filas': 6}

=== 6_student_segments_nivel ===
{'nivel': 'BASICO', 'alumnos': 6}

=== 7_segmentacion_alumnos ===
{'filas': 409}
```

`student_segments` tiene **6 filas, todas `BASICO`** (residuo de la migración 021, nadie las lee); `segmentacion_alumnos` tiene **409 filas** y es la que sí alimenta el producto (kpis, panel del admin, historial del alumno). Confirma que "nivel de atleta" no se guarda: se calcula.

### Hallazgo

Lo que el enunciado pide ("nivel") **ya existe y es correcto**: se calcula en el momento desde los RMs reales, así que nunca queda "desactualizado" (a diferencia de una columna). El riesgo es de **limpieza**, no de funcionalidad: hay una tabla `student_segments` con una columna `nivel` que *parece* la fuente de verdad y no la usa nadie — un futuro dev la leería por error (los dos modelos comparten vocabulario: `nivel` vs `arquetipo`).

### Propuesta (NO ejecutada)

- **No** mover el nivel a la base: el cálculo en vivo es la decisión correcta.
- Dejar constancia de la tabla huérfana (`student_segments`) en la doc del proyecto / `PENDIENTE_DECISION_USUARIO.md`: eliminar en una migración aparte o marcarla como no usada, con la decisión del usuario.
- Si el tab Alumnos debe mostrar el nivel, usar `useNivelGeneralAlumno` (`queries.js:587`) — nunca `student_segments`.

### Verificación
Sin cambios de código → nada que correr. Los dos respaldos son estáticos y verificados en esta sesión: (a) `StudentSegment` no tiene importadores; (b) en la BD la tabla tiene **6 filas** que nadie lee, frente a **409** en `segmentacion_alumnos`.

---

## Bloque 10 — N+1 de RMs en el tab Alumnos 🟠

### Evidencia

- `frontend/src/hooks/queries.js:942-979` `useProgresoAlumnosCoach(alumnos)`:
  - `:946` `const lista = (alumnos || []).slice(0, 50)` → hasta **50 alumnos**.
  - `:950-952` `queryFn: async () => Promise.all(lista.map(async (alumno) => { const rms = (await api.get('/api/v1/historial-rm/alumnos/${alumno.id}/rms')).data ... }))` → **1 GET por alumno** (hasta 50 peticiones en paralelo).
  - `:976` `staleTime: 60_000` (se repite al minuto o al cambiar el listado, porque `:947` mete los ids en la `queryKey`).
  - El propio comentario `:942-944` reconoce el antecedente: *"Antes eran 50 GET EN SERIE en CADA navegación … ahora van en paralelo y quedan en caché"* → ya se mitigó una vez, pero sigue siendo N+1.
- Duplicación dentro de la misma pantalla: `DashboardCoach.jsx:189` `useRmsAlumno(selectedAlumno?.id)` vuelve a pedir el mismo `/rms` de un alumno que ya vino en el lote; y `:188` `useHistorialRmTodos(5)` es otra lectura aparte del mismo recurso.
- Montaje: `DashboardCoach.jsx:187` `useProgresoAlumnosCoach(alumnosQ.data)` (alimentado por `useAlumnosDeCoach`, `:186`).

### Hallazgo

El backend **no tiene endpoint de lote** para esto, así que el frontend compensa con `Promise.all`. Consecuencias: 50 peticiones por apertura de pestaña (×N alumnos del box), misma información viajando dos veces para el alumno seleccionado, y una `queryKey` que incluye `ids` (cualquier alta/baja de alumno invalida el lote completo). No se midió tiempo de respuesta — **falta la métrica** para priorizar; si el box tiene pocos alumnos, el impacto real es bajo.

### Propuesta (NO ejecutada)

- Endpoint de lote en el backend: `GET /api/v1/historial-rm/coach/{coach_id}/rms-por-alumno` (scope coach, mismo candado `403` que `fidelizacion.py:286`) → 1 petición para los 50. Alinea con el patrón ya usado en `en-riesgo` (`fidelizacion.py:269`).
- Mientras no exista, unificar en el frontend: que el detalle del alumno lea del **lote** (o al menos que `useRmsAlumno` reutilice la caché si el alumno ya está en el lote).
- Medir antes/después (tiempo de la pestaña y nº de peticiones) para decidir si vale la pena.

### Verificación
`npm run test:coach-subtabs` + conteo de peticiones en la pestaña Alumnos (pestaña Network) antes/después.

---

## Cierre — qué está listo para decidir

| Bloque | Estado | Qué falta para arrancar |
|---|---|---|
| 1 · Publicar WOD | 🔴 Listo para planificar | Aceptar el modal unificado (+ retirar `Pizarra.jsx`) |
| 2 · Confirmar token | 🔴 Listo para planificar | Decidir si la confirmación es siempre o sólo con cargo |
| 3 · En Riesgo = 0 | 🔴 Causa raíz **confirmada con datos** | Nada: se puede fixear (2 de 3 coaches en `A=0 ∧ B>0`) |
| 4 · Franjas | 🟡 Listo para planificar | OK con chips + franja del reloj por defecto |
| 5 · Alumnos & RMs | 🟡 Listo para planificar | ¿La ficha es el modal `AlumnoFichaCoach`? |
| 6 · Botón atrás | 🟡 Bloqueado | Elegir lectura (1) escritorio, (2) dashboard o (3) enlace "Volver al Resumen" |
| 7 · Avisos | ⏳ Sin enunciado | El pedido concreto |
| 8 · Reporte | ⏳ Sin enunciado | El pedido + "Duda 1" (columnas) de `PENDIENTE_DECISION_USUARIO.md` |
| 9 · Nivel | 🟢 Nada que cambiar (datos: 6 filas vs 409) | Decidir qué hacer con la tabla huérfana `student_segments` |
| 10 · N+1 RMs | 🟠 Listo para planificar | ¿Se mide primero o se ataca directo? |

**Tests re-corridos en esta fase (todos PASS):** `test-walkin.mjs`, `test-publicar-wod.mjs`, `test-coach-subtabs.mjs`, `test-asistencia-franjas.mjs`, `test-boton-volver.mjs`.

**Orden sugerido de implementación:** 3 (bug real, 1 cambio quirúrgico + test) → 2 (dinero, 1 modal) → 1 (el más grande) → 4 → 6 → 5 → 10 → 9 → 7 y 8 cuando llegue el enunciado.

**Sin cambios de código**: este informe es sólo lectura; nada de lo propuesto se ejecutó. Lo único que se ejecutó contra la BD fueron **`SELECT` de diagnóstico** (documentados y con su salida pegada arriba); ningún INSERT/UPDATE/DELETE/DDL.







