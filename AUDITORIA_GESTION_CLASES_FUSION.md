# Auditoría — "Gestión de Clases" sale del menú y su vista semanal queda en la pestaña Clases

Fecha: 2026-10-16 · Autor: sesión de implementación
**Estado: implementado en el working tree, SIN commit y SIN push** (esperando el OK de Jebbus).
Reporta también **lo que queda huérfano antes de borrar nada** (punto 5 del pedido): ver §4.

## 1. El pedido, punto por punto

| # | Pedido | Resultado |
|---|---|---|
| 1 | "Mis clases de hoy" (Resumen): tocar una clase abre DIRECTO `ModalPublicarWod` con esa clase como `claseDestino`, sin pantalla intermedia | ✅ hecho (con un matiz reportado en §4.1) |
| 2 | "Gestión de Clases" fuera del menú lateral del coach | ✅ hecho (`config/menu.js`) |
| 3 | La vista semanal (grilla Lun→Dom + filtro "Ver todas / Ver solo con WOD publicado") se mantiene, fusionada en la pestaña **Clases** | ✅ ya estaba fusionada; verificado y limpiado el link muerto |
| 4 | El lápiz/horario de esa vista semanal abre el MISMO `ModalPublicarWod` | ✅ verificado intacto (Bloque 1) |
| 5 | Revisar rutas/links muertos y reportar lo huérfano ANTES de borrar | ✅ ver §4 (no se borró ni una línea de la pantalla vieja) |

**No se tocó**: el endpoint de publicación (`POST /wods/batch-create`,
`/wods/programar-semana`, `/marketing/aviso-rapido`), la lógica de "semana programada" ni
`ModalPublicarWod` (ni una línea: no hizo falta para recibir `claseDestino`, ya la recibía).

## 2. Qué cambió (4 archivos + 1 test nuevo)

| Archivo | Cambio |
|---|---|
| `frontend/src/config/menu.js` | se quita el ítem `Gestión de Clases` de `MENU_BY_ROL.coach` (quedan Dashboard y Entregar pedido) + comentario con el motivo y dónde vive la vista semanal |
| `frontend/src/pages/coach/DashboardCoach.jsx` | `irAGestionClases()` (navegaba a `?fecha=…&clase=…`) se reemplaza por `abrirPublicarWod(clase)` y `abrirClaseDeHoy(clase)`: las entradas abren el modal en la MISMA ruta. Se quita el botón `📋 Gestionar Clases` de la pestaña Clases. La única puerta que queda a la pantalla vieja (editar un WOD publicado) queda marcada `⚠️ PENDIENTE DE DECISIÓN` |
| `frontend/src/components/CampanaNotificaciones.jsx` | los 3 avisos de clase del coach (`clase_asignada` / `clase_reasignada` / `clase_liberada`) apuntan a `/coach/dashboard?tab=clases` (antes a la pantalla retirada) |
| `frontend/scripts/test-clases-sin-gestion.mjs` (**nuevo**) | fija las 6 invariantes del retiro (menú, sub-pestaña, modal en la misma pantalla, grilla+filtro, campana, pantalla que NO se borra). `npm run test:clases-coach` |
| `frontend/scripts/capturas-bloque2.mjs` | escenario nuevo `PANTALLA=fusion-clases` (4 tomas + mediciones) y **fecha del fixture dinámica** (ver §5) |

El `navigate` que queda en `DashboardCoach.jsx:1117` es el del detalle del WOD ("✏️ Editar en
Gestión de Clases"): apunta a la ruta viva, no a un 404 — es el huérfano de §4.1.

## 3. Evidencia

### 3.1 Capturas (`mockup/_audit/fusion-clases/`, `PANTALLA=fusion-clases`)

```
capturas: 4/4   ·   errores de consola: 0
RESULTADO: OK
```

| Toma | Medición (números del harness, no del ojo) |
|---|---|
| `01-movil-toque-clase-abre-modal.png` | `url="/coach/dashboard"` (**no cambió la ruta**), `modal_publicar=true`, encabezado "📝 Publicar WOD", subtítulo "18:00 · CrossFit · 12 inscritos" |
| `02-movil-pestana-clases-grilla.png` | `celdas_publicar=1`, `filtro_ver_solo_con_wod=true`, `boton_gestionar_clases=false` |
| `03-escritorio-pestana-clases-grilla.png` | igual que la anterior en 1280×900 (la grilla de escritorio sigue) |
| `04-movil-menu-sin-gestion.png` | `menu_items=["Dashboard","📊 Resumen","📅 Clases","👥 Alumnos & RMs","📋 Asistencia","📈 Progreso","⚠️ Riesgo","Entregar pedido"]`, `menu_tiene_gestion=false` |

Reproducir:

```
cd frontend
npm run dev                     # la app real (el harness sirve la API con fixtures)
$env:PANTALLA='fusion-clases'; node scripts/capturas-bloque2.mjs
```

### 3.2 Suites

- `node scripts/test-clases-sin-gestion.mjs` → `TODO OK` (24 PASS).
- Las 36 suites `scripts/test-*.mjs` corren con **exit code 0** (verificadas una por una).
- `oxlint` sobre los 3 archivos tocados: **0 errores** (1 warning pre-existente:
  `isToday` sin uso en la grilla de escritorio, ya estaba).
- Escenario `walkin` del harness re-corrido: `capturas: 10/10 · errores de consola: 0 · RESULTADO: OK`.
- UTF-8 sin mojibake en los 7 archivos tocados (chequeo por bytes, no por consola).
- Backend: **sin cambios**, no se re-corrieron sus tests.

## 4. Lo que queda huérfano — REPORTADO ANTES DE BORRAR (punto 5)

No se borró ninguna línea de `GestionClases.jsx` ni su ruta. Inventario de lo que vive SÓLO ahí:

| Función de la pantalla vieja | ¿Dónde queda hoy? | Veredicto |
|---|---|---|
| **Editar un WOD ya publicado** (`modoEdicion` + `wodForm` + `useGuardarWod`) | Sólo en `GestionClases.jsx`, y se llega por UNA puerta: el detalle del WOD de la grilla (`DashboardCoach.jsx:1101-1120`) | ⚠️ **DECISIÓN 1** |
| **Tomar / soltar una clase** + confirmación de **cobertura de emergencia** (409 del backend, auditado) — `useAccionClase` sólo se usa acá | Sólo en `GestionClases.jsx` (pestaña "Clases de Hoy") | ⚠️ **DECISIÓN 2** |
| **Aviso rápido del día** (`ModalAvisoRapido`) | Sólo ahí como botón propio. **Parcialmente cubierto**: el campo "aviso" del modal unificado pega al MISMO endpoint (`POST /marketing/aviso-rapido`) al publicar | ⚠️ DECISIÓN 2 (menor) |
| **Tomar asistencia** de una clase (marcar todos / por alumno) | **Cubierto** por la pestaña Asistencia: `AsistenciaClases.jsx` usa los mismos hooks (`useConfirmarAsistenciaClase`, `useMarcarAsistenciaReserva`) | ✅ no se pierde |
| **Calendario multi-día** del formulario de publicar + alcance ("solo esta hora / todas las horas del día") | **Reemplazado** por el modal unificado (pasos "Días donde publicar" + horarios por franja) desde el Bloque 1 | ✅ no se pierde |
| Vista semanal con grilla + filtro | **Fusionada** en `?tab=clases` | ✅ no se pierde |

### 4.1 Matiz del punto 1 (el único desvío del pedido literal)

El pedido dice "al tocar una clase, debe abrir directo el modal de Publicar WOD". Se implementó
así **salvo cuando esa clase YA tiene un WOD publicado**: en ese caso abre el **detalle del WOD**
(modal de solo lectura, instantáneo, sin red nueva).

Por qué: `POST /wods/batch-create` **no actualiza** el WOD existente: crea uno NUEVO y
re-apunta `clase.wod_id` (`backend/app/api/v1/wods.py:1322`). Publicar sobre una clase que ya
tiene WOD dejaría el anterior huérfano en la tabla `wods` (y la tarjeta "WOD del día" del
Resumen lo elige con un `find` sobre la lista del box → podría mostrar el viejo). Tocar la fila
dos veces crearía un WOD por toque. Es exactamente la misma regla que ya seguía la grilla con
una celda publicada (abre el detalle, no el formulario).

Si Jebbus quiere el literal (modal siempre, aunque ya haya WOD), es una línea:
`abrirClaseDeHoy` deja de mirar `wod` y llama a `abrirPublicarWod(clase)`.

### 4.2 DECISIÓN 1 — dónde vive "editar un WOD ya publicado"

El formulario viejo quedó "solo para editar" (`{claseDestino && modoEdicion && …}` en
`GestionClases.jsx`, con `useGuardarWod`). `ModalPublicarWod` sólo CREA (batch-create /
programar-semana / aviso). Opciones:

1. **Dejarlo como está** (recomendado si se quiere cero riesgo hoy): la ruta y la pantalla
   siguen vivas, sin ítem de menú; la única entrada es el botón del detalle del WOD.
   Contras: es una pantalla "escondida" (a la que se llega sólo desde ahí) y la barra lateral
   ya no la anuncia.
2. **Portar la edición al modal unificado** (modo edición cuando la clase ya tiene WOD):
   borra la dependencia de la pantalla vieja y permite después retirar la ruta y el archivo.
   Es trabajo real (prefill + `PUT /wods/{id}` + invalidaciones) y toca `ModalPublicarWod`,
   que el pedido pidió NO tocar más allá de `claseDestino`.
3. **Borrar la edición**: se pierde la corrección de un WOD ya publicado (hoy se puede).

Mientras no se decida, **no se borró nada**: la ruta sigue declarada en `App.jsx` y la
pantalla sigue en el repo (el test nuevo lo fija explícitamente).

### 4.3 DECISIÓN 2 — tomar/soltar clase y cobertura de emergencia

Esa función (con su auditoría de emergencia y el 409 del backend) vive SÓLO en la pantalla
retirada. El coach ya no tiene un lugar obvio para "tomar" una clase libre del día. Opciones:
(a) dejarlo accesible desde el detalle del WOD / la celda de la grilla, (b) agregarlo a la
pestaña Clases (junto al horario), (c) dejarlo ahí (sin menú) hasta que aparezca el pedido.

## 5. Hallazgos colaterales (2, ambos pre-existentes, arreglados de paso)

1. **`scripts/test-coach-sin-api.mjs` estaba ROJO antes de esta sesión** (no por este cambio):
   su regex exigía `import { useFichaAlumnoCoach } from '../hooks/queries'` con UNA sola llave,
   y `AlumnoFichaCoach.jsx` importa dos hooks desde el commit `09b5ed7` (Bloque 5). Se aflojó
   la regex a `import \{[^}]*\b<hook>\b[^}]*\}` (el hook tiene que estar, no ser el único).
2. **El harness de capturas tenía la fecha del fixture fija en `2026-10-15`**: al día siguiente
   "Mis clases de hoy" quedaba vacío y el escenario `walkin` (que usa
   `resumen-agregar-sin-reserva`) fallaba sin que nadie hubiera tocado nada. Ahora la clase del
   fixture es **HOY** (`hoyISO()`, fecha local, sin `toISOString()`), así que el harness no se
   pudre al cambiar el día. Re-verificado: `walkin` 10/10 OK.

## 6. Notas / riesgos residuales

- `Pizarra.jsx` (retirada) sigue diciendo en un comentario "Usar `/coach/gestion-clases`": es
  documentación de código retirado, sin link navegable.
- El link de los avisos de clase ahora apunta a `?tab=clases`; si el coach abre la campana en
  otro rol, la fila no navega (`ROLES_POR_TIPO` ya lo impedía) — sin cambios de comportamiento.
- Nada de esto se puede romper por caché: `menu.js` es JS puro y el menú se recalcula por rol.
- **Push: NO se hizo** (lo hace el usuario). Los commits de esta tanda van por tema y quedan
  locales — ver §7.

## 7. PARTE 0 EJECUTADA — las 4 decisiones del usuario (sesión siguiente)

El usuario respondió las tres decisiones abiertas y sumó una cuarta. Todo se ejecutó:

| # | Decisión | Cómo quedó |
|---|----------|------------|
| 1 | Portar "editar un WOD publicado" al mismo modal y **retirar la pantalla por completo** | `ModalPublicarWod` gana `wodEdicion` (pre-carga el formulario y guarda con `PUT /wods/{id}`); `GestionClases.jsx` **borrado**, su `lazy` y su `<Route>` fuera de `App.jsx` |
| 2 | Subir tomar/soltar + cobertura a la pestaña Clases y renombrar "Modo Emergencia" → **"Cubrir Suplencia"** | `components/AccionesClaseCoach.jsx` (nuevo, portado tal cual: mismos endpoints y alcances). El rótulo visible es "Cubrir suplencia"; el parámetro `modo_emergencia` y la auditoría NO cambian |
| 3 | Dejar el desvío del punto 1 original (si la clase ya tiene WOD se abre el detalle) | Sin cambios: `abrirClaseDeHoy` sigue igual |
| 4 | Botón "+ Cargar WODs de la semana (Excel)" en la pestaña Clases reusando la carga masiva | Botón `cargar-excel-semana` → el MISMO modal con `soloArchivo` (arranca en la rama del archivo y pide la disciplina, que el backend exige para `programar-semana`) |

Además, para que el retiro **no se llevara ninguna función**:
- el **aviso rápido del día** (que vivía sólo en esa pantalla) ahora es un botón de la pestaña
  Clases (`aviso-rapido-clases`) con el mismo `ModalAvisoRapido`;
- la grilla semanal suma **✏️ Editar** en cada celda con WOD y las **acciones del coach**
  (de quién es la clase + tomar/soltar/suplencia) debajo de cada clase, en la lista móvil y en
  la grilla de escritorio;
- el detalle del WOD ofrece **"✏️ Editar WOD"** en vez de navegar a la pantalla vieja.

Commits de esta tanda (locales, por tema): `refactor(coach): Gestión de Clases se retira…`,
`fix(campana): los avisos de clase…`, `test(coach): el retiro… queda fijado por los guards`.
Verificación: 31/31 suites `test-*.mjs`, `test-clases-sin-gestion.mjs` (24→30 PASS) reescrito,
guards de backend en verde, `vite build` OK, capturas `fusion-clases` 4/4 con 0 errores de
consola.

