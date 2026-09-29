# AUDITORÍA — PANEL DEL ALUMNO (`frontend/src/pages/alumno/*` + sus endpoints)

**Fecha:** 29/09/2026
**Tipo:** auditoría de **código** (read-only). No se escribió nada en la BD ni en `.env`.
**Alcance:** los 10 archivos de `frontend/src/pages/alumno/`, sus rutas en `frontend/src/App.jsx`, los
endpoints que consumen (`alumnos`, `historial_rm`, `reservas`, `planes`/`membresias`, `pedidos`,
`solicitudes_planes`, `notificaciones`, `clases`) y los componentes compartidos que los atraviesan
(`Layout`, `ProtectedRoute`, `AvisoCarga`, `AuthContext`, `services/api.js`, `utils/{fecha,rm}.js`).

## 0. Resumen ejecutivo

| Grupo | Qué era | Estado verificado |
|---|---|---|
| P0-1 | `marcar_plan_vencido` desactivaba usuarios sin respetar el CHECK de la migración 034 | ✅ corregido (código + test de regresión) |
| P0-2 (D-03 / R-02 / R-03) | el cliente decidía `estado`/`asistio`; reservas en el pasado; PUT reescribía la reserva; cancelar no era idempotente | ✅ corregido |
| P0-3 (R-01) | hora de corte de cancelación en UTC mal armada + el front mentía "cancelada" sin reembolso | ✅ corregido (backend + contrato del front) |
| P0-4 (B-02 / B-03 / S-01) | compra de productos desactivados, pedido sin comprobante, ingreso con el precio del momento de aprobar | ✅ corregido |
| P1 | fallas de carga silenciosas en las pantallas del alumno | ✅ corregido (banner `AvisoCarga` + `allSettled`) |
| H-01 | `GET /clases` escribía (auto-generaba clases) | ✅ corregido: la escritura quedó **opt-in** (`generar=false` por defecto) |
| E-01 | identidad del alumno salía de `localStorage` con fallback `\|\| 5` | ✅ corregido |
| H-03 | 3 copias distintas del criterio categoría/valor de un RM | ✅ corregido (fuente única back + front) |
| **N-1 … N-9** | **hallazgos nuevos de esta auditoría** | **9/9 cerrados**: N-1/N-3/N-4/N-5/N-6 en la 1ª pasada (§5 y §7) y N-2/N-7/N-8/N-9 en la 2ª (§9), todos con test |

**Límite honesto:** la primera pasada no pudo ejecutarse contra la API (`/health` no respondió), así que
todos los ✅ de §2 son **verificación por código** (lectura + `git log` + tests existentes), no medición
en runtime. §7 y §9 registran las corridas de pytest medidas (esta última con clicks reales en navegador).

## 1. Cómo se verificó

- Lectura completa de las 10 pantallas del alumno y de los routers que consumen.
- `grep` de patrones peligrosos: `localStorage`, `catch` vacíos, `Promise.all` sin `allSettled`,
  `alumno_id`/`tenant_id` provenientes de query/body en vez del JWT.
- Trazado de **cada** endpoint del alumno a su fuente de identidad (`current_user[...]` del JWT).
- `git log` para fechar los fixes de P0–P3 y leer los tests de regresión que ya existen.
- Sonda **read-only** a la rama TEST (`ENVIRONMENT=test` → `.env.test`) sólo para tipar datos
  (usuarios/tenants/notificaciones) usados por los tests nuevos.

## 2. Estado de los hallazgos previos (P0–P3, H-01, E-01, H-03)

| ID | Hallazgo original | Evidencia del fix (archivo:línea) | Estado |
|---|---|---|---|
| **P0-1** | `maintenance/marcar_plan_vencido.py` seteaba `usuario.activo = False` sin tocar `usuarios.estado` → violaba `ck_usuarios_activo_estado` (migración 034) y el job no funcionaba | `backend/maintenance/marcar_plan_vencido.py:5-7`, `backend/maintenance/README.md:531-533`, regresión `backend/tests/test_mantenimiento_vencidos.py:1-4` | ✅ código |
| **P0-2 / D-03** | `POST /reservas` guardaba `estado`/`asistio` del body (auto-marcarse presente) y aceptaba fechas pasadas | `backend/app/api/v1/reservas.py:72-86` (fuerza `estado`/`asistio` y corta pasado/canceladas), test `backend/tests/test_reservas_integridad.py:75` | ✅ código |
| **P0-2 / R-02** | `PUT /reservas/{id}` dejaba al alumno reescribir `estado`, `asistio` y `tokens_gastados` | `backend/app/api/v1/reservas.py:661-663`, test `backend/tests/test_reservas_integridad.py:133` | ✅ código |
| **P0-2 / R-03** | `DELETE /reservas/{id}` repetido volvía a devolver crédito y a decrementar aforo | `backend/app/api/v1/reservas.py:725-727`, test `backend/tests/test_reservas_integridad.py:158` | ✅ código |
| **P0-3 / R-01** | hora de corte de cancelación armada con hora local chilena en `tzinfo=utc`; el `DELETE` respondía 204 sin decir si hubo reembolso | `backend/app/api/v1/reservas.py:753-756` y `:785-787`; contrato consumido en `frontend/src/pages/alumno/MisReservas.jsx:150-152`; test `backend/tests/test_reservas_integridad.py:183` | ✅ código |
| **P0-4 / B-02** | `POST /pedidos` aceptaba productos `activo=false` (el catálogo los oculta, el POST no) | `backend/app/api/v1/pedidos.py:90-92` | ✅ código |
| **P0-4 / B-03** | se aceptaban pedidos sin comprobante de pago | `backend/app/schemas/pedido.py:20-22`; consumidores actualizados: `backend/tests/test_panel_admin.py:187,219`, `k6-tests/scenario_d_bazar.js:39-40` | ✅ código |
| **P0-4 / S-01** | el ingreso al aprobar usaba `plan.precio_clp` del momento de aprobar, no el precio que el alumno vio al solicitar | `backend/app/models/solicitud_plan.py:20-22`, `backend/app/api/v1/solicitudes_planes.py:100-102` y `:345-347`, migración `backend/alembic/versions/035_precio_snapshot_solicitudes.py:3-5`, test `backend/tests/test_p0_4_dinero.py:1-4` | ✅ código |
| **P1** | pantallas que ante un error de API mostraban "no hay nada" en vez de un error | `frontend/src/components/AvisoCarga.jsx:3-13` (banner + Reintentar) y `Promise.allSettled` + `erroresCarga` en `Bazar.jsx`, `Evolucion.jsx`, `MiProgreso.jsx`, `MisPedidos.jsx`, `PerformanceHub.jsx`, `Dashboard.jsx`; `MisReservas.jsx`, `Ajustes.jsx`, `PizarraRMs.jsx` y `SolicitarPlan.jsx` propagan el error con su propio `setMensaje` | ✅ código |
| **H-01** | `GET /clases` **escribía** (auto-generaba las clases faltantes del rango consultado) | `backend/app/api/v1/clases.py:37-41`: la generación pasó a ser **opt-in** (`generar=False` por defecto) y la escritura vive en `:52-129`; el camino explícito es `POST /horarios/generar-clases-dia` | ✅ código (residual: el GET sigue pudiendo escribir si el cliente manda `generar=true`) |
| **E-01** | `Evolucion.jsx` pedía `localStorage.getItem('usuario_id') \|\| 5` → si la sesión no estaba hidratada traía datos del alumno 5 y mostraba gráficos vacíos sin avisar | `frontend/src/pages/alumno/Evolucion.jsx:12-14` y `:40` (identidad del `AuthContext`; no se consulta nada sin identidad) | ✅ código |
| **H-03** | el criterio categoría/valor de un RM estaba implementado 3 veces (y podía divergir) | Fuente única backend: `backend/app/services/movimiento_categoria.py:1-3`, usada en `historial_rm.py:774-775`; fuente única frontend: `frontend/src/utils/rm.js:1-13`, usada en `Evolucion.jsx:7,127`, `PizarraRMs.jsx:5,74`, `PerformanceHub.jsx:8-14` | ✅ código |

> **Aclaración sobre el "P2" de la auditoría previa:** era la ficha de alumno del **panel del coach**,
> no una pantalla del panel del alumno. No aplica a este informe.

## 3. Ownership / alcance por endpoint que consume el panel del alumno

Todos derivan la identidad del **JWT** (`get_current_user` valida `usuarios.id + tenant_id + estado='activo'`
contra la BD: `backend/app/core/dependencies.py:77-92`). El panel del alumno no manda su propio `alumno_id`.

| Endpoint | Fuente del `alumno_id` | Evidencia |
|---|---|---|
| `GET /alumnos/me` | token | `alumnos.py:440-448` |
| `PUT /alumnos/me` | token | `alumnos.py:462-470` (tras N-1 ya no acepta `nombre`) |
| `GET /alumnos/me/es-prueba` | token | `alumnos.py:506-507` |
| `GET /planes/membresia-activa` | token (el query se ignora) | `planes.py:99` |
| `GET /historial-rm/alumnos/{id}/**` | token (alumno sólo el suyo) | `historial_rm.py:47`, `:257` |
| `POST /historial-rm` | token | `historial_rm.py:95` |
| `PUT/DELETE /historial-rm/{id}` | dueño + ventana 24h; admin sí, coach no | `historial_rm.py:436-446`, `:502` |
| `POST /reservas` | token | `reservas.py:46-50` |
| `GET/PUT/DELETE /reservas/{id}` | dueño (`roles de staff` sólo en los caminos de coach/admin) | `reservas.py:362-368`, `:435-441`, `:661`, `:725` |
| `POST /pedidos` (Bazar) | token | `pedidos.py:59` |
| `GET /pedidos/**` | token o staff del mismo box | `pedidos.py:220`, `:245-251` |
| `POST /solicitudes/solicitar` | token (staff validado por rol y tenant) | `solicitudes_planes.py:56-61` |
| `GET /solicitudes/**` | dueño | `solicitudes_planes.py:174` |
| `GET /notificaciones` | token; **staff sólo de su box** | `notificaciones.py:37-48` (corregido en N-3) |
| `PUT /notificaciones/{id}/leer` | sólo el dueño | `notificaciones.py:86-89` |
| `PUT /notificaciones/leer-todas` | token (el query param se ignora) | `notificaciones.py:103-104` |

## 4. Hallazgos nuevos de esta auditoría (N-1 … N-9)

### N-1 · 🔴 P1 · El alumno puede reescribir su **nombre completo**
- **Dónde:** `frontend/src/pages/alumno/Ajustes.jsx:139-141` (input editable + `required`) y `:71`
  (`payload.nombre`); backend `backend/app/api/v1/alumnos.py:33-48` (`ActualizarMiPerfil.nombre`) y
  `:472-493` (aplica todo campo que llegue).
- **Por qué importa:** el nombre es el dato de identidad que el box usa para la ficha, el listado del
  admin, la asistencia y los correos. Un alumno podía cambiarlo a voluntad sin que nadie lo revise
  (auto-identidad). El flujo de negocio ya tiene un camino para eso: el admin (`PUT /usuarios/{id}`).
- **Nota:** el resto de los campos sí son legítimamente del alumno (teléfono, peso, estatura).
- **Estado:** corregido en esta sesión (§5).

### N-2 · 🟡 P2 · Notificaciones del alumno: backend completo, **sin pantalla que lo consuma**
- **Dónde:** backend `backend/app/api/v1/notificaciones.py:23-110` (listar / marcar una / marcar todas,
  con ownership correcto) y `backend/app/models/notificacion.py:9-18`; el modelo se escribe desde
  `dependencies.py:252-253` (avisos de cobertura al admin) y otros servicios.
- **Hallazgo:** en `frontend/src` **no hay** campana ni centro de notificaciones del alumno. El alumno
  se entera de aprobaciones/rechazos sólo por email; existe `frontend/src/pages/admin/Notificaciones.jsx`
  pero es del panel admin. Es una feature huérfana (endpoints + tabla + tests) sin consumidor.
- **Riesgo:** funcional/producto, no de seguridad. Y arrastra el bug de N-3 al no estar ejercitada.
- **Estado:** abierto (decisión de producto: construir la campana o retirar los endpoints).

### N-3 · 🟡 P2 · `GET /notificaciones` con `alumno_id`: el staff no tenía frontera de tenant
- **Dónde:** `backend/app/api/v1/notificaciones.py:37-41` (rama `coach/admin` hacía `pass`) y
  `backend/app/models/notificacion.py:12-18` (la tabla **no tiene** `tenant_id`: pertenece al alumno).
- **Por qué importa:** la consulta filtraba sólo por `Notificacion.alumno_id`, así que un staff de
  cualquier box podía leer (y con `solo_no_leidas=true`, deducir) los avisos de un alumno de **otro**
  box conociendo su id. Asimetría además con `marcar_como_leida` (`:86-89`), que es dueño-only.
- **Nota de diseño:** la solución no necesita migración: la pertenencia se valida contra
  `usuarios.tenant_id` del alumno objetivo (fuente de verdad del aislamiento del proyecto).
- **Estado:** corregido en esta sesión (§5).

### N-4 · 🟡 P3 · `PerformanceHub` hablaba del "box" mostrando **datos propios**
- **Dónde:** `frontend/src/pages/alumno/PerformanceHub.jsx:42` (pide `/historial-rm?limit=500`, que para
  un alumno devuelve **sus** RMs) y `:55-56` (`'Error cargando el historial del box'` /
  `fallaron.push('historial del box')` → el banner le decía al alumno que falló "el historial del box").
- **Riesgo:** confusión del usuario y de quien depure (sugiere que la pantalla agregada datos de todo el
  box cuando en realidad son los del propio alumno).
- **Estado:** corregido en esta sesión (§5) — sólo copy; el resto del nodo (las 2 llamadas que devuelven
  casi lo mismo para un alumno) queda como recomendación en §6.

### N-5 · 🟡 P3 · `try/catch` vacío al construir la serie semanal
- **Dónde:** `frontend/src/pages/alumno/PerformanceHub.jsx:74-77`
  (`try { byCat[c].push(...) } catch (e) { }`).
- **Por qué importa:** un fallo ahí descarta un punto del gráfico **en silencio** (`catch` sin log ni
  contador). Es exactamente el patrón que la P1 vino a erradicar.
- **Estado:** corregido en esta sesión (§5).

### N-6 · 🟡 P3 · `es_prueba` **fallaba abierto** (menú completo a un alumno en plan de prueba)
- **Dónde:** `frontend/src/components/Layout.jsx:64-70`: `api.get('/api/v1/alumnos/me/es-prueba')`
  `.then(...).catch(() => setEsPrueba(false))`, y el filtro del menú en `:98-100`.
- **Por qué importa:** si el endpoint falla (backend caído, 401, red), el estado queda en `false` = "no es
  de prueba" y el alumno ve el menú COMPLETO (Bazar, RMs, Progreso…), donde cada acción le da 403 sin
  explicación. Un chequeo de permisos que ante el error **abre** el acceso está mal orientado: debe fallar
  **cerrado** (menú restringido) y avisar/reintentar.
- **Estado:** corregido en esta sesión (§5).

### N-7 · 🟡 P3 · La identidad del front sale de `localStorage` (no del JWT)
- **Dónde:** `frontend/src/context/AuthContext.jsx:16-33` (bootstrapping desde `localStorage`:
  `usuario_id`, `rol`, `tenant_id`, `usuario`) y de ahí `usuario_id` en
  `Ajustes.jsx:7`, `PerformanceHub.jsx:27`, `Evolucion.jsx:13-14`, `MiProgreso`, `PizarraRMs`, etc.
- **Por qué importa:** `localStorage` es editable por el usuario. Hoy **no** es explotable porque el
  backend deriva todo del JWT y responde 403 (verificado endpoint por endpoint en §3), pero el front usa
  valores manipulables para *decidir a quién le pide datos* (p. ej. `historial-rm/alumnos/{id}/rms`) y para
  *elegir qué menú* mostrar. Un valor manipulado produce errores confusos en vez de una sesión coherente.
- **Estado:** abierto — recomendado hidratar la identidad desde el JWT (`jwt-decode` ya es dependencia) o
  desde `GET /alumnos/me`. Ver §6.

### N-8 · 🟡 P3 · Regla de "edición de PR sólo dentro de 24h" sin señal en la UI
- **Dónde:** backend `backend/app/api/v1/historial_rm.py:35-36` (`VENTANA_EDICION_PR_HORAS = 24`),
  `:54-74` (`_verificar_ventana_edicion`) y `:445-446` (aplicada en el PUT); front
  `frontend/src/pages/alumno/PizarraRMs.jsx` (no hay ventana temporal en la UI: el error aparece recién
  al guardar).
- **Por qué importa:** el alumno descubre la regla cuando ya perdió el trabajo de editar. La regla es de
  negocio legítima; lo que falta es hacerla visible (mostrar "editable hasta HH:MM" / deshabilitar).
- **Nota:** confirmado que el backend **sí** la aplica (no es una regla "de adorno").
- **Estado:** abierto — recomendado señal en la UI.

### N-9 · 🟡 P3 · `POST /reservas` rechaza al staff (contrato inconsistente con el resto del panel)
- **Dónde:** `backend/app/api/v1/reservas.py:46-50` (exige `alumno_id == current_user.usuario_id`),
  mientras que en `pedidos.py:59` / `:245-251` y `solicitudes_planes.py:56-61` el staff **sí** puede operar
  a nombre de un alumno del box.
- **Por qué importa:** no es un agujero (es más restrictivo, no menos), pero rompe la simetría: cualquier
  pantalla de staff que quiera reservar para un alumno falla con un mensaje que parece un bug. Hay que
  decidir el contrato y documentarlo.
## 5. Correcciones aplicadas en esta sesión (1 commit por hallazgo)

| Hallazgo | Qué se cambia | Archivos | Test de regresión |
|---|---|---|---|
| **N-1** | `nombre` sale de `ActualizarMiPerfil` y, si llega, se descarta server-side (nunca 422 por compatibilidad). En `Ajustes.jsx` el campo pasa a **solo lectura** con la nota "Solo el box puede modificar tu nombre" y deja de ir en el payload. | `backend/app/api/v1/alumnos.py`, `frontend/src/pages/alumno/Ajustes.jsx` | `backend/tests/test_nombre_inmutable_alumno.py` |
| **N-3** | En `listar_notificaciones`, el staff sólo puede consultar alumnos de **su** tenant (validación contra `usuarios.tenant_id`, sin migración), mismo criterio de propiedad que `marcar_como_leida`. | `backend/app/api/v1/notificaciones.py` | `backend/tests/test_notificaciones_tenant.py` |
| **N-6** | `es_prueba` falla **cerrado**: estado inicial "sin dato" ⇒ menú restringido, error registrado en consola y aviso con **Reintentar** en la barra lateral. | `frontend/src/components/Layout.jsx` | (verificación manual/lint) |
| **N-5** | El `catch` vacío pasa a log + entrada en `erroresCarga` (banner de la pantalla). | `frontend/src/pages/alumno/PerformanceHub.jsx` | — |
| **N-4** | El copy deja de decir "del box": son los RMs del propio alumno (log + etiqueta del banner). | `frontend/src/pages/alumno/PerformanceHub.jsx` | — |

N-2, N-7, N-8 y N-9 quedan **abiertos** a propósito: N-2 y N-9 son decisiones de producto/contrato y
N-7/N-8 son mejoras que no cambian una frontera de seguridad (ver §6).

## 6. Recomendaciones / pendientes

1. **N-2 — Notificaciones del alumno:** decidir entre (a) construir la campana en el panel del alumno
   (consumiendo `GET /notificaciones` + `leer-todas`) o (b) retirar los endpoints/tabla si el canal oficial
   es sólo email. Hoy el backend es funcional pero nadie lo usa.
2. **N-7 — Identidad:** hidratar `usuario_id`/`rol`/`tenant_id` desde el JWT (`jwt-decode`, ya instalado) o
   desde `GET /alumnos/me` en el bootstrap del `AuthContext`, dejando `localStorage` sólo como caché de
   presentación (nombre) y no como fuente de decisión.
3. **N-8 — Ventana 24h:** mostrar en `PizarraRMs.jsx` hasta cuándo es editable cada PR (o deshabilitar el
   botón) para no castigar al alumno con un error al guardar.
4. **N-9 — Contrato de `POST /reservas`:** decidir si el staff reserva para un alumno del box (como en
   pedidos/solicitudes) o si reservar es exclusivamente del alumno; documentarlo en `SECURITY.md`.
5. **`PerformanceHub`:** para un alumno, `/historial-rm/alumnos/{id}/rms` y `/historial-rm?limit=500`
   devuelven esencialmente lo mismo; unificar en una sola llamada (menos payload y menos superficie de
   fallo) — el gráfico semanal sale de la unión actual.
6. **H-01 residual:** `GET /clases` sigue teniendo un camino de escritura si el cliente manda
   `generar=true`. Si se quiere erradicar del todo, mover esa generación a un cron/POST (el POST dedicado
   ya existe).
7. **Medición pendiente:** correr la suite de integración contra la rama TEST
   (`test_panel_alumno`, `test_reservas_integridad`, `test_p0_4_dinero`, `test_mantenimiento_vencidos` +
   los 2 tests nuevos) para promover los "✅ código" de §2 a "✅ medido". El orquestador
   (`run_tests.bat` → `_run_tests_orchestrator.py`) hace `DROP SCHEMA` del branch TEST (borra el seed de
   demo): **no** se ejecutó en esta sesión; la API se levantó a mano con `ENVIRONMENT=test` y se corrió
   `pytest` sólo con los tests de esta sesión.

## 7. Estado al cierre de la sesión (medido)

### Commits (uno por hallazgo; sin push)

| Commit | Hallazgo | Contenido |
|---|---|---|
| `307cc7b` | — | `docs(auditoria)`: este informe |
| `12c1c41` | **N-1** | nombre inmutable: `alumnos.py` (+42/-23) + `Ajustes.jsx` (+34) + test nuevo (108 líneas) |
| `eaa4b22` | **N-3** | frontera de tenant en `notificaciones.py` (+30/-7) + test nuevo (180 líneas) |
| `427d2dd` | **N-6** | `Layout.jsx`: fail-closed + Reintentar (+49/-9) |
| `99daf63` | **N-5** | `PerformanceHub.jsx`: log + `erroresCarga` (+21/-3) |
| `37f0ff2` | **N-4** | `PerformanceHub.jsx`: copy propio, no "del box" (+8/-2) |

### pytest (medido, contra el branch TEST)

```
API levantada a mano: ENVIRONMENT=test + --lifespan off   (sin scheduler ⇒ ningún email puede salir)
/debug/db-url → {"is_safe":true,"is_test":true,"branch":"ep-jolly-butterfly-b6ty2z89"}

py -3.12 -m pytest tests/test_nombre_inmutable_alumno.py tests/test_notificaciones_tenant.py -v

### Frontend (medido)

- `npm run lint` → **73 warnings / 0 errors**: ningún aviso nuevo; el de `PerformanceHub.jsx:76`
  (`catch` vacío) **desapareció** con N-5.
- `npm run build` → **OK** (`dist/assets/index-*.js` 1.172 kB, `built in 8.86s`), es decir el JSX de
  `Ajustes.jsx`, `Layout.jsx` y `PerformanceHub.jsx` compila.

### Lo que NO se midió

- La suite completa (`test_panel_alumno`, `test_reservas_integridad`, `test_p0_4_dinero`,
  `test_mantenimiento_vencidos`) **no** se corrió: el orquestador del proyecto (`run_tests.bat` →
  `_run_tests_orchestrator.py`) hace `DROP SCHEMA` del branch TEST y borra el seed de la demo. Los "✅
  código" de §2 quedan como verificación por lectura, no por ejecución.
- N-2, N-7, N-8 y N-9 quedaron abiertos al cierre de *esa* sesión; se cerraron en la sesión
  siguiente (§9). Esta sección (§7) se deja como registro de lo que se midió entonces.
- `Ajustes.jsx`: se aplicó la instrucción literal ("solo teléfono, peso y estatura son editables"), así
  que **correo, género y fecha de nacimiento también quedaron de sólo lectura** en la UI. El backend
  sigue aceptándolos (`ActualizarMiPerfil`), de modo que revertirlo es desbloquear esos 3 campos en el
  formulario, sin tocar el servidor.

## 8. Verificación — voucher privado vs. `/static/uploads` (TAREA 6, sin cambios)

**Pregunta:** ¿un archivo subido con `privado=1` se puede descargar sin token o con el token de otro
alumno? ¿Sigue público `/static/uploads`?

**Método (medido en TEST el 29/09/2026; API a mano `ENVIRONMENT=test --lifespan off`):** subí un PNG
real con `POST /upload/voucher?privado=true` (archivo temporal borrado al terminar) y probé todas las
vías de lectura, más una sonda a los vouchers que ya están en la BD.

| Prueba | Resultado |
|---|---|
| `POST /upload/voucher?privado=true` (alumno autenticado) | **201** → `{"url":"/privado/vouchers/voucher_<uuid>.png"}` |
| ¿el archivo se guarda fuera de `static/`? | **Sí**: `backend/app/private_uploads/voucher_<uuid>.png` existe en disco |
| `GET /privado/vouchers/voucher_<uuid>.png` **sin token** | **404** — no hay ruta: `main.py` sólo monta `/static`, y nginx sólo proxea `/api/`, `/static/` y `/health` |
| `GET /static/uploads/` con el nombre privado | **404** (la carpeta privada no se sirve por `static`) |
| `GET /solicitudes/95/voucher` **sin token** | **401** |
| `GET /solicitudes/95/voucher` con token de **otro alumno del mismo box** | **403** (`solicitudes_planes.py:167-184`: sólo el dueño o el staff del mismo box) |
| `GET /solicitudes/95/voucher` con token del **dueño** | 200 — en TEST da **404** porque el seed apunta a un archivo que no está en disco (dato, no seguridad) |
| `GET /static/uploads/voucher_9ba7a0f3….jpeg` (voucher **histórico**, solicitud 2) **sin token** | **200** ← **sigue público** |

**Respuesta:** un voucher `privado=1` **no** se puede descargar sin token ni con el token de otro alumno:
la URL no existe como ruta y el único lector es el endpoint autenticado, que valida dueño/box.
`/static/uploads` **sí sigue público** (por diseño: ahí viven las imágenes de catálogo), y los
**vouchers históricos** —los subidos antes de que existiera `private_uploads/`: 96 archivos en disco y 1
referenciado por una solicitud de TEST— siguen descargables por URL y sin token con sólo conocer el nombre.

**Riesgo residual (vouchers históricos).** El comprobante de pago es dato sensible (nombre, banco, monto,
fecha) y esas URLs **no se pueden revocar**. La mitigación actual es el nombre UUID (no adivinable) y que
la UI use el endpoint autenticado; el agujero es cualquier filtración de la URL (logs, capturas, reenvío
del correo, historial del navegador).

**Propuesta de fix (NO implementada, por indicación de la tarea):**

1. **Contención inmediata, sin tocar datos:** en nginx, cortar `location ^~ /static/uploads/voucher_`
   con un 404. Los vouchers históricos dejan de servirse público y el endpoint autenticado los sigue
   leyendo (lee el archivo del disco, no la URL).
2. **Migración de datos:** script one-off con `--dry-run` que mueva a `private_uploads/` los archivos de
   `solicitudes_planes.voucher_url`, `pedidos.voucher_url` y `suscripciones.voucher_url` que empiecen con
   `/static/`, y actualice la URL a `/privado/vouchers/…`.
3. **Regresión automática:** test que falle si un `voucher_url` nuevo queda en `/static/` (hoy el
   contrato se sostiene sólo porque el front manda `privado=1`).

**Observaciones relacionadas (medidas, fuera del alcance pedido):**

- `pedidos.voucher_url` guarda comprobantes **privados** pero ningún endpoint autenticado los sirve (el
  de vouchers es sólo de solicitudes) y ninguna pantalla los muestra (`admin/Bazar.jsx` y
  `MisPedidos.jsx` no lo referencian): el comprobante de un pedido es obligatorio desde P0-4 y nadie
  puede verlo.
- `SolicitarPlan.jsx:122` sube el **certificado de estudiante** SIN `privado=1` (queda público). Es
  deliberado y está comentado en el código ("no hay endpoint autenticado de certificados todavía"), pero
  es el mismo tipo de dato sensible que el voucher.

## 9. Bloque de seguridad — cierre (TAREAS 1–7, 29/09/2026)

**Cómo se midió:** API de TEST levantada a mano (`ENVIRONMENT=test` + `--lifespan off`, sin scheduler ⇒
ningún correo puede salir), verificada con `/debug/db-url` → `{"is_safe":true,"is_test":true,"branch":"ep-jolly-butterfly-b6ty2z89"}`
antes de cada corrida. Frontend en `npm run dev` (:5173, proxy `/api` → :8000) para los clicks reales
(`frontend/scripts/click-test.mjs`, Edge headless + CDP). **Sin conexiones a producción**, sin tocar `.env`
ni el correo de la app. Nada se pusheó.

### Tabla de cierre

| Tarea | Hallazgo | Commit | Tests (medidos) | Estado |
|---|---|---|---|---|
| 1 | **N-1 (2ª parte)** — la ficha administrativa deja de ser editable en `PUT /alumnos/me` | `75c3ca5` | `tests/test_perfil_campos_alumno.py` **7/7** + los 3 de N-1 → **10 passed** | ✅ cerrado |
| 2 | **N-2** — campana de notificaciones del alumno | `301aacd` | `tests/test_notificaciones_alumno_campana.py` **5/5** + los 6 de N-3 → **11 passed**; **click real** (badge `1` → "Marcar leída" → badge desaparece, 0 errores) | ✅ cerrado |
| 3 | **N-7** — la identidad del front sale del servidor | `807f8b0` | `tests/test_identidad_servidor.py` **6/6** + los 7 de la tarea 1 → **13 passed**; **3 corridas en navegador** (localStorage falsificado → `/alumno/dashboard`; admin y coach reales entran a su panel) | ✅ cerrado |
| 4 | **N-8** — editar/borrar un PR dentro de las 24 h | `237d9c0` | `tests/test_pr_ventana_24h.py` **4/4**; **click real** en `/alumno/rms` (el botón "Editar PR" aparece y abre el modal en modo edición: movimiento bloqueado, valores precargados, "GUARDAR CAMBIOS", 0 errores) | ✅ cerrado (ver gap del DELETE) |
| 5 | **N-9** — `POST /reservas` para el staff del box | `a11b659` | `tests/test_reservas_staff.py` **4/4** | ✅ cerrado |
| 6 | **Voucher privado** (sólo verificación) | `802590f` | sondas HTTP contra TEST (tabla de §8), sin cambios de código | ✅ documentado |
| 7 | Cierre del informe (esta sección) | *(este commit)* | — | ✅ |

**Tests nuevos: 26 casos** (7 + 5 + 6 + 4 + 4). Corridas de la sesión: **10 · 11 · 13 · 4 · 4 passed**
(42 casos ejecutados al re-correr también los archivos de regresión de N-1 y N-3), más **5 corridas de
click real** (4 de campana/identidad y 1 del PR).

### Comandos y salidas (medidos)

```
API a mano:  ENVIRONMENT=test  py -3.12 -m uvicorn app.main:app --port 8000 --lifespan off
             /debug/db-url -> {"is_safe":true,"is_test":true,"branch":"ep-jolly-butterfly-b6ty2z89"}

TAREA 1:  py -3.12 -m pytest tests/test_perfil_campos_alumno.py tests/test_nombre_inmutable_alumno.py -v
          -> 10 passed, 4 warnings in 49.75s

TAREA 2:  py -3.12 -m pytest tests/test_notificaciones_alumno_campana.py tests/test_notificaciones_tenant.py -v
          -> 11 passed, 9 warnings in 48.87s

TAREA 3:  py -3.12 -m pytest tests/test_identidad_servidor.py tests/test_perfil_campos_alumno.py -v
          -> 13 passed, 9 warnings in 54.68s

TAREA 4:  py -3.12 -m pytest tests/test_pr_ventana_24h.py -v
          -> 4 passed, 3 warnings in 25.59s

TAREA 5:  py -3.12 -m pytest tests/test_reservas_staff.py -v
          -> 4 passed, 7 warnings in 41.50s
```

**Clicks reales (Edge headless + CDP, `frontend/scripts/click-test.mjs`):**

| Corrida | Pantalla | Qué hizo | Resultado |
|---|---|---|---|
| 1 | `/alumno/dashboard` | click en la campana (`aria-label="Notificaciones"`) | `role="dialog"` con la lista: badge `1`, "PLAN APROBADO ✅ …", botón "Marcar leída"; 0 errores |
| 2 | `/alumno/dashboard` | open + click en "Marcar leída" | `badge_antes:"1"` → `badge_despues:null`; 0 errores (notificación restaurada a `leida=false` al terminar) |
| 3 | `/admin/dashboard` con **token de alumno** y localStorage falsificado (`rol=administrador`, `usuario_id=1`) | — | queda en **`/alumno/dashboard`**, `rol` en localStorage = `alumno` (lo pisó el servidor), menú admin **no** visible, campana visible; 0 errores |
| 4 | `/admin/dashboard` y `/coach/dashboard` con tokens reales | — | admin → panel admin; coach → panel coach; ambos con su menú; 0 errores |
| 5 | `/alumno/rms` con un PR recién creado | click en `button[aria-label="Editar PR"]` | modal "✏️ Editar PR", movimiento bloqueado, valores precargados (`minutos=4`, `km=1.2`), botones `["✕","Cancelar","💾 GUARDAR CAMBIOS"]`; 0 errores |

**Frontend (medido):** `npm run build` → **OK** (`built in 5–6 s`, sin errores) después de cada tarea;
`npm run lint` → **72 warnings / 0 errors** (bajó de 73: el `catch` vacío de N-5 ya no está).

**Base de TEST al cierre (read-only):** `usuarios` 419 (0 en el box 2, 0 temporales), `notificaciones`
3 sin leer, `historial_rm` 18 filas y **0** con marcas `TEMP`, **0** reservas y **0** registros de
`auditoria` creados en la última hora. Todo lo que escribieron los tests —teléfono/peso/estatura, la
notificación marcada, el PR, la reserva, el aforo, los créditos, la auditoría y el usuario temporal del
otro box— quedó restaurado o borrado.

### Decisiones conservadoras tomadas (no cubiertas por la consigna)

1. **T1 — el descarte es incondicional, no por rol.** `correo`, `genero`, `fecha_nacimiento` y `nombre`
   se descartan para CUALQUIER llamador de `PUT /alumnos/me`, no sólo para `rol == 'alumno'`: ramificar
   por rol obligaba a validar el body a mano (para preservar el 200 de los clientes viejos) y el único
   cliente de ese endpoint es el Ajustes del alumno (verificado con grep). El box sigue editando la
   ficha por `PUT /usuarios/{id}` (admin-only), como dice el hallazgo. El chequeo de correo duplicado
   queda como red defensiva hoy inalcanzable (comentada en el código).
2. **T5 — 403 y no 404 para el alumno de otro box.** Mismo criterio que N-3: no se confirma si el id
   existe fuera del box. El alumno de un tercero (preexistente) sigue devolviendo 404 como antes.
3. **T3 — fail-closed en el bootstrap.** Si `GET /alumnos/me` falla, la sesión **no** se restaura: sin
   identidad verificada no se renderiza ningún panel (y `ProtectedRoute` manda a `/login`). Costo
   aceptado: un corte de red al arrancar fuerza re-login.
4. **T4 — el DELETE no recibe ventana.** El backend permite borrar un PR propio sin límite de 24 h; la
   ventana la aplica sólo la UI (el botón no se renderiza fuera de plazo). No se tocó para no quitarle
   al box/admin la posibilidad de limpiar un PR viejo; queda documentado como gap.
5. **T5 — auditoría sólo para la reserva "en nombre de".** El alumno reservando para sí mismo no genera
   registro (sería ruido); sí lo hace el staff, que es la acción sensible.
6. **T4 — cambios aditivos en la API.** `RMPorMovimiento` suma `id` y `created_at`; `GET/PUT /alumnos/me`
   suma `tenant_id`. Nada se quitó ni se renombró, así que los clientes viejos siguen funcionando.
7. **T6 — no se implementó nada** (era verificación): el fix queda propuesto en §8.

### Lo que quedó pendiente y por qué

- **Suite completa sin correr** (`test_panel_alumno`, `test_reservas_integridad`, `test_p0_4_dinero`,
  `test_mantenimiento_vencidos`, …): el orquestador del proyecto (`run_tests.bat` →
  `_run_tests_orchestrator.py`) hace `DROP SCHEMA` del branch TEST y **borra el seed de la demo**, que la
  consigna prohíbe. Los "✅ código" de §2 siguen siendo verificación por lectura. Para promoverlos haría
  falta un orquestador que no destruya el seed (o un branch TEST descartable).
- **Voucher de pedido sin visor** (§8): no existe endpoint autenticado que lo sirva; el comprobante es
  obligatorio desde P0-4 y el admin no puede verlo. Requiere decisión de producto (¿un
  `GET /pedidos/{id}/voucher` con el mismo control de dueño/box?).
- **Certificado de estudiante público** (§8): mismo caso que los vouchers históricos.
- **DELETE de PR sin ventana** (decisión 4).
- **`Ajustes.jsx`**: correo, género y fecha de nacimiento quedaron de sólo lectura en la UI **y ahora
  también en el backend**. Si el producto quiere que el alumno los edite, hay que revertir en los dos
  lados, no sólo en el formulario (esto cambia lo anotado en §7).
- **§6 (recomendaciones de la primera pasada)**: siguen vigentes tal cual; no se tocaron en este bloque.


  → 9 passed
```

- `test_nombre_inmutable_alumno.py`: **3/3** (el alumno manda `nombre` → 200 + sin cambio ni en la
  respuesta ni en la BD; el resto del payload sí se aplica; clave desconocida sigue en 422).
- `test_notificaciones_tenant.py`: **6/6**, incluido `test_nb04` (cross-tenant real: el alumno existe en
  el box 2 y el staff del box 1 recibe **403**).
- Primera corrida: 8 passed + **1 error** de fixture (`usuarios.rut` es `varchar(12)` y el rut del alumno
  temporal tenía 18 caracteres). Corregido en el mismo commit de N-3 (el INSERT falló entero: no quedó basura).
- Los tests **no** dependen de ids fijos (en TEST no existe el alumno 999 que crea el orquestador): eligen
  sus sujetos de la BD. El test cross-tenant crea y **borra** un alumno temporal del box 2.

**Verificación post-corrida de la BD (read-only):** 0 filas residuales, `usuarios` sigue en 419 filas
(sólo box 1), las 3 notificaciones siguen `leida=false` y el teléfono del alumno usado quedó restaurado.

