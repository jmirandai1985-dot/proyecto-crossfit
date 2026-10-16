# Auditoría — Dashboard del coach: rediseño del Resumen (Parte 1) + Progreso/QR (Parte 2)

Sesión en modo autónomo (el usuario durmiendo): se investigó primero, se decidió lo razonable y
se avanzó sin bloquear. Todo lo ambiguo queda listado en §5 (PENDIENTES) y **no se hizo push**.

---

## 1. PARTE 1 — Resumen rediseñado ("energético")

Referencia: `mockup/mockup-dashboard-energetico.html` (abierto y leído antes de construir).

### 1.1 Qué se construyó (`components/ResumenCoach.jsx`, reescrito)

De arriba a abajo, como el mockup:

1. **"Asistencia de hoy"** + fecha corta + cuántas clases hay programadas.
2. **Tarjeta grande de la clase EN CURSO** (o la próxima): donut SVG propio (`Donut`, marcados vs
   cupo, sin librerías), nombre (`hh:mm · disciplina`), los 3 números apilados y centrados
   (*con reserva / ya marcaron / faltan*), botón **"Marcar asistencia"** (lleva a la pestaña
   Asistencia) y, dentro de la misma tarjeta, el walk-in **"+ Agregar alumno sin reserva"**.
3. **Tarjeta "WOD del día"**: estado (Publicado / Sin publicar) + **"+ Publicar WOD"** (el mismo
   `ModalPublicarWod` del panel, con la próxima clase del día como destino) + "Ver el WOD completo"
   cuando ya hay uno.
4. **"Avisos para alumnos"** (ver §1.2) con **"+ Nuevo aviso"**.
5. **Fila horizontal** con el resto de las clases de hoy, cada una con **mini-donut** y su badge
   de estado; al tocar una, se abre el modal unificado con ESA clase.
6. **Ocupación por horario**: una barra por clase con su % (helper `ocupacion()` compartido).

Lo que se fue: el grid 2x2 de KPIs (Clases hoy · Alumnos activos · WOD del día · En riesgo) y sus
accesos directos. Esos datos siguen existiendo, cada uno en su pestaña (`Alumnos & RMs`,
`Progreso`, `Riesgo`), y el Resumen ahora responde una sola pregunta: *¿cómo va la clase que tengo
ahora?*. El 0 sigue explicándose cuando al coach no le asignaron disciplinas ni horarios.

Los números y los estados salen de `utils/franjasAsistencia` (los mismos de la pestaña
Asistencia) y el Resumen **no llama a la API**: todo llega por props del Dashboard.

### 1.2 Avisos — investigación pedida (Bloque 10)

**Dónde vive hoy el sistema de avisos** (todo verificado en el código):

| Pieza | Archivo / ruta |
|-------|----------------|
| Tabla + servicio (ventana, orden, validación) | `backend/app/services/avisos_marketing.py` (`rango_vigencia`, `ventana_de_hoy`, `titulo_desde_texto`, `payload_aviso_rapido`, `payload_aviso_de_fecha`) |
| Endpoints | `backend/app/api/v1/marketing.py`: `GET /marketing` (lista, **solo admin**), `GET /marketing/vigentes` (**cualquier sesión**), `POST /marketing` (admin, con flyer), `POST /marketing/aviso-rapido` (**coach o admin**, tipo `aviso` + ventana HOY fijados por el backend), `PUT/{id}`, `POST|DELETE /{id}/imagen`, `DELETE /{id}` (admin; `_solo_manuales` bloquea los de producto del Bazar) |
| Carrusel que los consume | `components/CarruselMarketing.jsx` (usa `useAvisosMarketingVigentes()`), montado en `pages/alumno/InicioMobile.jsx` (~línea 325). Sin avisos vigentes no dibuja nada |
| UI del coach | `components/ModalAvisoRapido.jsx` (una caja de texto; tipo, ventana y título los fija el backend) |

**Decisión de alcance (implementada, no placeholder):** la sección lista los avisos **vigentes
hoy** con `GET /marketing/vigentes` —el único endpoint de avisos abierto a un coach— con su tipo
(`etiquetaTipo` del util compartido) y su estado vacío explicado; **"+ Nuevo aviso"** abre el
mismo aviso rápido. El copy dice que Promociones, Colaboraciones y Eventos los publica el admin:
el coach puede publicar avisos del día, no contenido con vigencia larga. No se tocó ningún
endpoint.

### 1.3 Evidencia (capturas)

`PANTALLA=resumen-energetico` → `mockup/_audit/panel-energetico/` (carpeta ignorada por git):
`01-movil-resumen-completo.png` (390×1560, pantalla completa) y
`02-escritorio-resumen-completo.png` (1280×1400). 0 errores de consola. El fixture de esa
pantalla trae 3 clases del día (la primera `en_curso`) y dos avisos vigentes, para que la fila, el
mini-donut y las barras tengan contenido. `fusion-clases` y `walkin` re-corridas: 4/4 y 10/10 OK.

---

## 2. PARTE 2.1 — Progreso: buscador + nivel + paginación

### 2.1 Hallazgo pedido (a): ¿por qué sólo traía 50?

No era un `LIMIT` del backend ni una paginación sin usar: era un **`slice(0, 50)` dentro del hook**
`useProgresoAlumnosCoach(alumnos)` (`frontend/src/hooks/queries.js`), que además hacía **una
consulta por alumno** (`GET /historial-rm/alumnos/{id}/rms`). El padrón en sí
(`GET /fidelizacion/coach/{coach_id}/alumnos`) viene **completo** (los 251).

**Qué se hizo:** la tabla ahora **pagina de a 25** con los helpers de `utils/alumnos`
(`rangoMostrado`, `paginaValida`…), el mismo patrón del padrón del admin, y el enriquecimiento se
pide **sólo para la página visible**: los 251 quedan alcanzables y el costo por vista baja de 50 a
25 alumnos.

### 2.2 Hallazgo pedido (b): ¿de dónde sale el campo "nivel"?

**El campo no existe.** Verificado en el código, no por memoria:

- `backend/app/models/usuario.py` **no tiene** columna de nivel (ni `nivel`, ni `nivel_atleta`, ni
  equivalente), y el formulario del admin no lo edita.
- Existe `backend/app/models/student_segments.py` + migración `021` ("nivel de ATLETA"
  BASICO/INTERMEDIO/AVANZADO + scores) pero el propio modelo está documentado como **SIN
  CONSUMIDORES**: nadie la escribe, nadie la lee y **no hay endpoint** que la exponga. (No
  confundir con `segmentacion_alumnos`, que sí se usa para los arquetipos de retención.)
- Lo único real y accesible es el cálculo en vivo `GET /historial-rm/alumnos/{id}/nivel-general`,
  que devuelve `nivel_fuerza` y `nivel_gimnastico` con la escala de `nivel_service.NIVELES`
  (`Principiante < Intermedio < Avanzado < Elite`) o `"Sin datos"`.
- ⚠️ El endpoint se llama "nivel-general" pero **no** devuelve una clave `nivel_general`: sólo los
  dos niveles + detalles. El nivel combinado hay que derivarlo.

**Qué se hizo (asunción documentada, ver §5):** `utils/niveles.js` deriva UN nivel por alumno con
el criterio del propio servicio ("el nivel más bajo" entre los movimientos de cada grupo) = el
**menor** de fuerza/gimnasia; `null` = "Sin datos". Los chips son
**Todos · Principiante · Intermedio · Avanzado · Elite · Sin datos**, **combinables** con el filtro
de estado existente (no lo reemplazan), y cada fila muestra el nivel como badge (con el detalle
fuerza/gimnasia en el `title`). Los conteos de los chips son de la página cargada, y el copy lo
dice: el nivel se pide por alumno al abrir cada página.

### 2.3 Buscador

Filtra el padrón **completo** por nombre o correo, en el cliente (el endpoint ya trae los 251) y
vuelve a la página 1 al escribir. Con paginación, filtrar sólo la página cargada habría escondido
justo al alumno buscado (el mismo criterio que documenta el padrón del admin).

### 2.4 Intacto

El filtro de estado (Todos/Progresando/Iniciando/Sin datos), el endpoint de RMs y la ficha del
alumno. La columna "Ver RMs" sigue llevando al tab Alumnos.

### 2.5 Evidencia

`PANTALLA=progreso-coach` → `mockup/_audit/progreso-coach/`:
`01-movil-buscador-nivel-paginacion.png`, `02-escritorio-filtros-y-rango.png` (chips de estado,
chips de nivel con sus conteos, badges por alumno y paginador "Mostrando 1–25 de 30 · página 1 de
2") y `03-movil-buscando-alumno.png` (el buscador filtrando: "fanny"). 3/3, 0 errores de consola.


---

## 3. PARTE 2.2 — Escanear el QR además de escribir el código

### 3.1 Hallazgos pedidos

1. **¿Ya existe un lector de cámara en el proyecto?** Sí, pero para otro flujo:
   `components/EscanerQR.jsx` (alumno) abre la cámara con `getUserMedia` y lee el QR con la API
   nativa **`BarcodeDetector`** —sin librerías—. No se reusa como componente porque su salida es
   otra: extrae un `public_id` y **navega** a `/asistencia/qr/{id}`. Se copió el patrón (mismos
   estados, mismo bucle de ~250 ms, mismo Reintentar) en un componente hermano que devuelve el
   texto leído.
2. **¿El código de retiro ya es un QR?** **Sí.** `pages/alumno/MisPedidos.jsx` pide
   `GET /api/v1/pedidos/{id}/qr.svg` (SVG autenticado del backend, generado con `segno`) y el
   backend documenta que el contenido es **SÓLO el código ("UB-4827"), no una URL**
   (`pedidos.py: qr_retiro_pedido`). No había nada que generar: sólo leerlo del otro lado.

### 3.2 Qué se hizo

- `components/EscanerCodigoRetiro.jsx` (nuevo): cámara `environment` + `BarcodeDetector`; si el
  navegador no soporta el detector, la cámara igual se abre y se ofrece el teclado; siempre hay
  "Escribir el código a mano" y "Reintentar" cuando falta el permiso.
- `ModalEntregarPedido`: nueva prop **`permitirEscanear`** (false por defecto → **el admin queda
  exactamente igual**), botón **"📷 Escanear"** junto al input y, al leer, completa el input y
  dispara **la misma** función `entregar` (no hay endpoint ni flujo paralelo). El input manual
  sigue siendo el único `<input>` del modal.
- `utils/pedidosEntrega.js`: **`normalizarCodigoRetiro`** para que el texto del QR y lo que un
  humano escribe ("ub 4827") entren igual.
- `pages/coach/EntregarPedido.jsx`: pasa `permitirEscanear` y su copy ya no promete de menos (el
  texto del "Bloque B", que decía que el coach no tenía lector, quedó al día).

### 3.3 Evidencia

`PANTALLA=entrega-escaner` → `mockup/_audit/entrega-escaner/`:
`01-movil-input-manual-y-escanear.png` (input + botón), `02-movil-camara-abierta.png` (cámara con
su marco y el aviso, cámara simulada de Edge) y `03-movil-lectura-y-entrega.png` (lectura de un QR
de prueba `UB-4827` → input completado → **"✅ Pedido entregado: Botella Urban Box x2 a fanny
carrasco"**). 3/3, 0 errores de consola.

Nota honesta sobre la evidencia: la cámara es la **simulada de Edge** (`--use-fake-device`) y la
lectura usa un `BarcodeDetector` de prueba inyectado por el harness (el mismo camino de código, sin
depender de una cámara física apuntando a un QR impreso). No se agregó ninguna librería.

---

## 4. PARTE 3 — "En riesgo = 251" (causa raíz) — ✅ RESUELTO en la Parte 4 (§8)

Con el rediseño del Resumen el KPI "En riesgo" **ya no se muestra** ahí (vive en su pestaña), así
que el número duplicado dejó de estar a la vista; el cálculo **no se tocó**.

**Causa raíz encontrada (verificada en el código):**

- `GET /fidelizacion/coach/{id}/en-riesgo` calcula "días sin asistir" con
  `MAX(asistencias.fecha)` y arma la lista de alerta con
  `(tiene_historial == False) | (dias_ausente >= umbral_dias)` → **todo alumno sin ninguna fila en
  `asistencias` cuenta como EN RIESGO** ("Sin actividad registrada").
- Pero la asistencia que el coach marca hoy se guarda en **`reservas.asistio`**
  (`POST /asistencia/clases/{id}/confirmar`), **no** en `asistencias`. El modelo `Asistencia` dice
  que `clase_id`/`presente` "se poblarán desde `reservas` en una limpieza futura".
- Consecuencia: si el box marca asistencia sólo por reservas, `asistencias` puede quedar vacía y
  **todos** los alumnos del coach caen en "en riesgo" → `251` de `251`. Es exactamente el síntoma.

**Dos caminos posibles (decisión del usuario):** (a) que el cálculo use la misma fuente que el
resto del panel (`reservas.asistio` + fecha de la clase), o (b) que `confirmar_asistencia` escriba
además su fila en `asistencias`. **Se eligió (a)** y quedó implementado en §8; (b) está descartado.


---

## 5. PENDIENTES (para revisar despierto — ninguna bloquea lo entregado)

1. **Nivel de atleta: ¿campo real o estimación?** (Parte 2.1) El "nivel editable en Admin" no
   existe en el código. Hoy el filtro usa una **estimación** con los RMs
   (`nivel-general`, el menor entre fuerza y gimnasia). Si se quiere el campo de verdad hay que
   (i) agregar la columna/formulario en el admin y exponerlo en
   `GET /fidelizacion/coach/{id}/alumnos`, o (ii) decidir si se llena `student_segments` (la tabla
   de nivel de atleta que existe sin consumidores). Ambas son decisiones de producto + BD.
   Consecuencia actual: el filtro de nivel cubre la **página cargada** (el nivel se calcula por
   alumno, una consulta cada uno); el buscador y la paginación sí cubren los 251.
2. ~~**"En riesgo" (§4)**: elegir (a) cambiar la fuente del cálculo o (b) escribir `asistencias`
   al confirmar. Nada se tocó.~~ → **RESUELTO con la opción (a)**: ver §8.1.
3. ~~**Costo del enriquecimiento**: cada página del Progreso hace 2 consultas por alumno (RMs +
   nivel) = 50 requests por página de 25. Si molesta en PROD, la salida correcta es un endpoint
   batch (contadores de RM + nivel por página) en vez de N consultas.~~ → **RESUELTO**: endpoint de
   lote `GET /historial-rm/progreso-lote` (1 request y 5 consultas por página). Ver §8.2.
4. **Editar WOD desde el detalle** ya no sale del panel, pero el alcance de un WOD compartido
   sigue siendo "todas las clases que lo llevan" (`PUT /wods/{id}`): si algún día se quiere editar
   "sólo para esta clase", es un cambio de backend.
5. **Avisos del coach**: puede publicar avisos del día (no Promociones/Eventos, que son del
   admin). Si se quiere que el coach gestione más contenido, hay que abrir permisos en
   `marketing.py` (hoy sólo `POST /marketing/aviso-rapido` es suyo).
6. **`student_segments`**: se deja como está (el modelo pide NO borrarla), pero conviene saber que
   no la escribe nadie cuando alguien toque el tema "nivel".

## 6. Cómo se verificó (todo verde al cierre)

- `frontend`: **31/31** suites `node scripts/test-*.mjs` en verde (incluye las nuevas/actualizadas
  `test-coach-resumen`, `test-clases-sin-gestion`, `test-pedidos-retiro`).
- `backend`: guards de fuente en verde (`test_codigo_retiro_front`, `test_admin_movil_overlays`,
  `test_fechas_chile_front`, `test_react_query_bloque2c_front`,
  `test_rutas_sin_redirect_restantes_front`).
- `oxlint src scripts`: **0 errores** (26 warnings, todos pre-existentes).
- `vite build`: exit 0 (sin chunk de `GestionClases`).
- Capturas: `resumen-energetico` 2/2, `progreso-coach` 3/3, `entrega-escaner` 3/3,
  `fusion-clases` 4/4 y `walkin` 10/10, todas con **0 errores de consola**.

## 7. Commits de esta sesión (locales, por tema — **sin push**)

1. `refactor(coach): Gestión de Clases se retira y todo su panel se fusiona en el Dashboard`
2. `fix(campana): los avisos de clase del coach llevan a la grilla del panel`
3. `test(coach): el retiro de Gestión de Clases queda fijado por los guards`
4. `feat(coach): el Resumen se rediseña alrededor de la asistencia de hoy (mockup energético)`
5. `feat(coach): Progreso con buscador, nivel y paginación real; el mesón escanea el QR`
6. `docs(coach): el informe de las Partes 1-3 (hallazgos, decisiones y pendientes)`

---

## 8. PARTE 4 — Pendientes resueltos (decisiones del usuario)

Las 4 decisiones llegaron desde el usuario. Los puntos **1 y 4 eran confirmaciones** (nada que
construir); **2 y 3 se implementaron**. Esta tanda queda **sin commitear y sin push**.

### 8.1 Punto 2 — "En riesgo" lee la asistencia REAL (opción a) ✅

**Relevamiento pedido antes de cambiar nada** (`git grep` de `Asistencia`/`asistencias` en
`backend/`):

* **Escritores de la tabla en la app:** UNO solo, `POST /fidelizacion/registrar`
  (`fidelizacion.py`)… y **ninguna pantalla lo llama**: no hay `fidelizacion/registrar` en
  `frontend/` ni en los tests (queda como integración manual/n8n). Los seeds/demo
  (`_demo_seed_alertas.py`, `scripts/crear_usuarios_demo.py`, `scripts/seed_anual_prod.py`) son el
  resto. Con la tabla vacía, el filtro de alerta —que incluye a los "sin historial"— metía a TODO
  el padrón: de ahí el "251".
* **Lectores que responden "¿hace cuánto no entrena?" (la familia del bug):** los 3 endpoints de
  riesgo (`/analizar/{tenant_id}`, `/coach/{id}/en-riesgo`, `/tenant/{id}/en-riesgo`) y
  `_dias_inactividad_alumno` (los días que salen en el correo de contacto del coach).
* **Otros lectores de la misma tabla (se reportan, NO se tocaron):**
  * `services/churn_service.py` — `_ultima_asistencia` para el churn y **"plan sin usar"**
    (`plan_sin_usar`, `plan_sin_usar_lote`), que alimentan `predictions_churn` (data mart de BI).
  * `services/fidelizacion_plantillas.py` — "última asistencia" de las plantillas de campaña.
  * `services/alertas_email_service.py` — SQL crudo `MAX(a.fecha) FROM asistencias`.
  * `api/v1/kpis.py` (+ `kpis_populate.py`) — KPIs/BI (`LEFT JOIN asistencias`); el propio código
    ya documenta que `asistencias.clase_id` es NULL en el 100% de las filas.
  * `api/v1/usuarios.py` — orden por última asistencia en el buscador.
  * `services/historial_alumno_service.py` — **ya** leía `reservas.asistio` (correcto desde antes):
    por eso el historial del alumno y el "en riesgo" decían cosas distintas.

**Decisión de alcance (anotada, sin esperar respuesta):** se migra **sólo la familia del bug** (los
3 endpoints de riesgo + los días del correo) porque los cuatro responden la MISMA pregunta con la
MISMA tabla, y con `asistencias` vacía los tres mostraban el padrón completo como "en riesgo" —el
del coach **y los dos del admin**; arreglar uno solo habría dejado las pantallas discrepando (el
bug que fijó `test_coach_alumnos_alcance.py`). Los "otros lectores" quedan como estaban a
propósito: tocarlos mueve **números de BI y de campañas** (churn, plantillas, alertas por email,
dashboards) y eso es una decisión aparte. Consecuencia asumida: si un box no marca asistencia en
`reservas`, esos cinco siguen viendo la tabla histórica vacía.

**Implementado:** un único helper, `services/asistencia_real.py`
(`ultima_asistencia_por_alumno`), que es la ÚNICA definición de "asistió": `MAX(clases.fecha)`
sobre `reservas` con `asistio = true` y la reserva no cancelada — el mismo patrón que
`admin._alumnos_con_asistencia_de_prueba`, `historial_alumno_service._inicio_actividad` y los
contadores "ya marcaron" de `api/v1/asistencia`. Es una consulta agregada por lote (sin N+1).

**El guardado NO se tocó** (pedido explícito): `POST /fidelizacion/registrar` sigue igual (único
`INSERT` de la app en `asistencias`, ya con una advertencia en su docstring) y
`POST /asistencia/clases/{id}/confirmar` sigue escribiendo sólo `reservas.asistio`.

**Cambio de comportamiento visible (a tener presente):** donde sí haya filas en `asistencias`, los
"días sin entrenar" pueden cambiar y, con eso, la lista de "en riesgo" del admin y la campaña de
`POST /fidelizacion/enviar-emails` (que hoy no enviaba nada, porque omitía a todos los "sin
historial") pasarán a incluir a los ausentes reales. Es el comportamiento correcto, pero es un
cambio de DATOS, no sólo de código.

### 8.2 Punto 3 — Progreso: endpoint de lote (RMs + nivel de la página) ✅

**Antes:** la tabla del tab Progreso pedía, por cada alumno de la página (25), DOS requests (sus
RMs + `nivel-general`) = **50 requests** y ~4 consultas cada una (~100 consultas).
**Ahora:** `GET /historial-rm/progreso-lote?alumno_ids=1,2,…` → **1 request y 5 consultas** para
toda la página (1 de pertenencia al box + 2 del lote de RMs + 2 del lote de niveles).

Cómo se logró sin duplicar la lógica (la regla del repo: una sola definición):

* `services/rms_service.py`: nuevo `mejor_rm_por_movimiento_lote()` (2 consultas con `IN (...)` y
  `DISTINCT ON (alumno_id, movimiento_id)`) y **`mejor_rm_por_movimiento()` delega** en él (el de
  un alumno es el lote de un id). El orden relativo de los movimientos de un alumno no cambia.
* `services/nivel_service.py`: se extrajo el reductor PURO `nivel_desde_mejores(mejores, peso,
  genero)` (el bucle de "el más bajo entre movimientos"); `calcular_nivel_general()` = datos +
  reductor, y `calcular_niveles_lote()` hace 2 consultas para todo el lote (peso/género de todos +
  mejores RMs por movimiento de todos) y aplica el MISMO reductor.
* `schemas/historial_rm.py`: `ProgresoAlumnoLote` + `ProgresoLoteResponse` (contrato explícito).
  Por alumno viajan `alumno_id`, `total_rms`, `rms` (mismo schema que el endpoint individual) y los
  dos niveles — **los mismos valores** que `nivel-general`.
* `api/v1/historial_rm.py`: `GET /progreso-lote`. ⚠️ Va **antes** de `GET /{historial_id}`: FastAPI
  resuelve por orden de registro y ese comodín se habría comido "progreso-lote" (422). Queda fijado
  por el guard. Sólo alumnos del box del token, candado por alumno (`_verificar_acceso_alumno`) y
  tope de 100 ids (400 más allá).
* `frontend/src/hooks/queries.js`: `useProgresoAlumnosCoach` hace UNA request al lote y arma las
  MISMAS claves que antes (`total_rms`, `rms`, `nivel`, `nivel_fuerza`, `nivel_gimnastico`,
  `estado`): **la tabla, los chips y el filtro de nivel quedan igual** —buscador, filtro y
  paginación no se tocaron. Si el lote falla, cae al mismo modo degradado de antes (padrón con los
  contadores en 0).
* `frontend/scripts/capturas-bloque2.mjs`: el fixture sirve el lote (la query ahora viaja al
  fixture; `path` sigue siendo sólo el pathname, para no romper los `path === '...'` de siempre).

**Sin cambio visible:** la captura `progreso-coach` (3/3, 0 errores de consola) muestra el mismo
buscador, los mismos chips de nivel y la misma paginación que la versión de 50 requests. Cambia el
tráfico, no la pantalla. Nota de despliegue: el endpoint es nuevo, así que backend y frontend van
juntos.

### 8.3 Puntos 1 y 4 — confirmaciones (nada que construir)

* **Punto 1 (nivel del atleta):** se queda como está. La estimación por RMs (`nivel-general` →
  `utils/niveles` toma el menor entre fuerza y gimnasia) es correcta y consistente con lo que ya ve
  el alumno; **no se crea ningún campo nuevo en Admin** ni se toca `student_segments`.
* **Punto 4 (avisos del coach):** se queda como está. El coach sólo publica el "aviso rápido del
  día" (`POST /marketing/aviso-rapido`); Promociones/Colaboraciones/Eventos siguen siendo del admin.

## 9. Verificación de esta tanda (Parte 4)

* Backend (aisladas, `--noconftest`): `test_riesgo_fuente_real.py` **5 passed + 1 skipped** (la
  parte de integración queda escrita y desactivada) y `test_progreso_lote.py` **12 passed**. Los
  guards relacionados siguen verdes: `test_react_query_bloque{1, 1p2, 1p2b, 2a, 2b, 2c}_front` (24),
  `test_historial_calculos` + `test_rm_categoria_contrato` + `test_historial_panel_inicio` +
  `test_alumno_ficha_modal_front` + `test_historial_admin_acceso_front` +
  `test_tdz_declaracion_antes_de_uso_front` (44) y `test_estados_compartido` +
  `test_pedidos_aviso_preview_failfast` + `test_usuarios_buscador_membresia` (40).
  ⚠️ Los tests que abren conexión a Neon fallan en esta máquina por credenciales del branch TEST
  (`password authentication failed for user 'neondb_owner'`): es el entorno, no los cambios.
* Frontend: **31/32** `node scripts/test-*.mjs` en verde. El único rojo es `test:click`, el humo con
  navegador + frontend levantados (falla igual sin tocar nada).
* `oxlint`: **0 errores** (26 warnings, preexistentes). `vite build`: exit 0.
* Capturas CDP: `progreso-coach` **3/3** con **0 errores de consola** (tabla, buscador, chips de
  nivel y paginación renderizando con el lote).
* Lo que NO se pudo verificar acá: la parte de BD (sin acceso al branch TEST). Lo verificado es la
  fuente + el reductor puro + el render real de la pantalla; la integración de `asistencia_real`
  contra la base queda escrita en el test para correrla contra TEST.




