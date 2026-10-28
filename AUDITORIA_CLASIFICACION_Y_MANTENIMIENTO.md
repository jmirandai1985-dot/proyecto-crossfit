# Auditoría — Clasificación de nivel de atleta y mantenimiento automático

- **Fecha:** 2026-10-26
- **Repo:** `proyecto-crossfit` · rama `main` · commit `36dbd9f`
- **Alcance:** (1) cómo se clasifica hoy a un atleta (Básico / Intermedio / Avanzado y todo lo relacionado con
  RMs) y (2) qué mantenimiento corre solo, hoy, en este producto.
- **Tipo:** auditoría **read-only**. No se modificó código, ni datos, ni configuración. Este archivo es el
  único agregado (queda **sin commitear**).
- **Entornos de datos:** **TEST** `ep-crimson-tooth-akhx7q2s` (us-west-2, `neondb`), la que el propio repo
  declara "espejo de PROD" desde el 2026-10-24 (`docker-compose.yml`, Fase 3) — es la base de casi todo este
  informe; y **PROD** `ep-winter-star-akwis51j` (us-west-2, la misma URL que usa Render), leída **sólo** con
  `count(*)` y agregados, para contrastar. Ver 2.5: además hay dos ramas más en juego.

> **Cómo leer los números.** Hay dos fuentes de datos y se distinguen siempre:
> **(1) PROD** (`ep-winter-star`, 505 alumnos) — lo que ve el box real; **(2) TEST** (`ep-crimson-tooth`,
> 450 alumnos), la rama que el repo declara espejo de PROD, pero que hoy está poblada con copias demo
> (`*@example.com`, 401 filas) más datos sintéticos de una prueba de carga (`carga_k6_*@load.test`, 42
> usuarios / 400 RMs creados el 2026-10-25). Las cifras de *distribución de nivel* de TEST describen el
> **estado del dato**, no la calidad de los atletas del box; los hallazgos de código aplican a ambos porque
> es el mismo `main`. Ver 2.5: hay dos ramas más en juego y cada componente usa una distinta.

---

# Resumen ejecutivo

| # | Hallazgo | Impacto | Severidad |
|---|---|---|---|
| **A1** | El "nivel del atleta" (Básico/Intermedio/Avanzado) **no existe como campo**: no hay columna en `usuarios`, `student_segments` está muerta y el nivel se deriva **en el cliente** como *el menor* de fuerza y gimnasia. | No es auditable, no se puede filtrar en SQL ni usar en reportes/BI; cada pantalla puede derivarlo distinto. | Alta |
| **A2** | `nivel_desde_mejores` toma **el movimiento más débil** de cada grupo y, si falta un eje, usa el otro: **una sola marca** (p. ej. 1 Snatch) lo publica como **Elite**. | 21 de 22 atletas con RM salen "Elite" en TEST; un PR mal cargado define el nivel ante el coach. | Alta |
| **A3** | El nivel depende de `peso_kg` **y** `genero` del atleta. En PROD: **2 de 505** alumnos tienen alguna marca y sólo **6** son clasificables (505 alumnos, 19 RMs). En TEST: 26 de 450 clasificables ⇒ 428 (95,1%) ven "Sin datos". | La funcionalidad es, en la práctica, invisible para casi todo el box. | Alta |
| **A4** | `nivel_calculado` (columna de `historial_rm`) es **write-only**: se escribe en el POST, no se recalcula en el PUT, el cliente puede setearlo y **ninguna consulta lo lee**. | Dos verdades sobre el mismo RM + mass-assignment de una columna de negocio. | Media |
| **A5** | El match entre `movimientos.nombre` y los estándares es **por string exacto**: 67 movimientos de fuerza/gimnasia no tienen estándar y se ignoran **en silencio**; 3 claves de estándar no tienen movimiento. Entre los ignorados están `Strict Pull-up` y `Kipping Pull-up`. | El atleta registra marcas que no mueven su nivel y nadie se entera. | Alta |
| **A6** | La gimnasia se mide con `peso_kg` (columna que en gimnasia transporta **repeticiones** por convención RM-01). El POST usa `repeticiones or peso_kg` y el cálculo vivo usa `peso_kg`: **misma marca, dos niveles posibles**. | Nivel gimnástico poco confiable en cuanto convivan reps reales con `peso_kg=1`. | Media |
| **B1** | El **único** job de mantenimiento que corre en esta máquina falla **5/5 pasos**, desde hace semanas: `box-crossfit-maintenance-1` ejecuta cron **sin `DATABASE_URL`** ⇒ todos los pasos van a `localhost:5432`. | No hay backup, ni vencimientos, ni huérfanas, ni health-check, ni aviso de cuota Neon. Silencioso. | **Crítica** |
| **B2** | Ese job **miente en verde**: en agosto/septiembre reportó `✅ JOB DIARIO COMPLETADO` con el `pg_dump` fallando, y hoy reporta `✅ Alerta enviada` cuando el correo fue **simulado** (`EMAIL_MODO=noop`, forzado porque `ENVIRONMENT` no llega al cron). | Falso positivo en la pieza que avisa de las caídas. | **Crítica** |
| **B3** | El único backup de la BD tiene **1 mes** (2026-09-26 15:44, 1,4 MB) y fue **manual**; `/app/backups` no recibió nada más. | Sin backup automático ni verificado ⇒ pérdida de datos = pérdida total. | **Crítica** |
| **B4** | Los Cron Jobs de PROD (backup a R2, mantenimiento días 1 y 15, watchdog, restore drill, KPIs) **existen sólo en el dashboard de Render**: `render.yaml` declara *únicamente* el web service; y `mantenimiento_cloud.py` trae `DRY_RUN=1` **por defecto** (el dump se hace y no se sube, sin error). | Sin versionado no se puede auditar ni recrear la automatización; y la pieza clave falla abierta. | Alta |
| **B5** | **Cuatro ramas Neon** con cuatro configuraciones distintas: PROD (`winter-star`), TEST (`crimson-tooth`), el backend local en ejecución (`lingering-fog`, 42 usuarios y 400 RMs menos que TEST) y el mantenimiento (`summer-river`, sa-east-1, **credencial revocada**). | Dos personas probando "lo mismo" escriben en bases distintas; y el job de mantenimiento no puede tocar nada ni heredando el entorno. | Alta |
| **B6** | **538 de 2.017 notificaciones fallidas (26,7%)**: 245 por `Configuración SMTP incompleta` en PROD, 107 por `Header values may not contain linefeed`, 20 por conexión. 272 son del flujo de `inactividad` (retención). Nadie monitorea `estado='fallido'`. | El flujo de retención —el de mayor valor comercial— no llega al alumno y no hay alerta. | **Crítica** |
| **B7** | El scheduler in-app **pierde el liderazgo** 121 veces en 48 h (~cada 24 min) por `idle_in_transaction_session_timeout`; recupera con catch-up, pero indica una config de pool/lock incompatible con Neon. | Riesgo de job perdido si el hueco cae en el disparo y el catch-up no aplica. | Media |
| **B8** | Sin retención para `reservas` (23.495), `asistencias` (24.752), `notificaciones` (518), `auditoria`, tokens **expirados** (`password_reset_tokens`: 2 desde 2026-09-26) ni para los 46 usuarios en `baja`. La purga que existe vive en el job de PROD, no acá. | Crecimiento sin techo de las tablas más grandes + datos personales de ex-alumnos sin anonimizar. | Media |
| **B9** | `n8n` está **detenido** en este equipo (`Exited` hace 3 semanas) y sólo 7 de sus 18 workflows están versionados; `fidelizacion y retencion` (cierre mensual **PROD**) no tiene reemplazo en el repo. | Un proceso mensual de PROD quedó sin ejecutor conocido ni rastro auditable. | Media |

**Lo que sí está bien hecho** (para no reescribirlo): el cálculo es una función pura testeable
(`nivel_desde_mejores`), hay **una sola definición** compartida por el endpoint individual y el de lote
(`progreso-lote`), los estándares están versionados con fuentes citadas, y el CRUD de RM tiene candados
reales de tenant + ventana de edición de 24 h + auditoría.


---

# PARTE 1 — Clasificación de nivel

## 1.1 Mapa: qué existe y quién lo lee

| Pieza | Archivo | Qué hace |
|---|---|---|
| Motor | `backend/app/services/nivel_service.py` | Escala `["Principiante","Intermedio","Avanzado","Elite"]` (`:9`), `obtener_nivel_fuerza` (`:13`), `obtener_nivel_gimnastico` (`:63`), `nivel_desde_mejores` (`:152`) — **la única definición de nivel general** —, `calcular_nivel_general` (`:268`), `calcular_niveles_lote` (`:276`). |
| Estándares fuerza | `backend/app/db/crossfit_ratios.py` | 8 movimientos, ratio `peso levantado / peso corporal`, tabla M y F. |
| Estándares gimnasia | `backend/app/db/crossfit_habilidades.py` | 17 habilidades, valor = reps unbroken / metros / logro binario, tabla M y F. |
| API | `backend/app/api/v1/historial_rm.py` | `GET /alumnos/{id}/nivel-general` (`:663`), `/nivel-fuerza` (`:677`), `/nivel-gimnastico` (`:850`), `POST /nivel-fuerza` (`:546`), `POST /nivel-gimnastico` (`:582`), lote `GET /progreso-lote` (`:222`). |
| Derivación en cliente | `frontend/src/utils/niveles.js` | `nivelDeAtleta()` = **el menor** de los dos; `null` sólo si faltan los dos. Chips de filtro y colores. |
| Vista alumno | `frontend/src/pages/alumno/Dashboard.jsx:83-84` | Dos tarjetas independientes ("Fuerza" y "Gimnasia") con su nivel y top-3 RMs. |
| Vista coach | `frontend/src/pages/coach/DashboardCoach.jsx` (tab Progreso) + `hooks/queries.js:1128-1155` | Badge "Nivel estimado" + filtro por nivel, alimentado por `progreso-lote`. |
| **Performance Hub** | `frontend/src/pages/alumno/PerformanceHub.jsx` | **No muestra ningún nivel** (0 apariciones de "nivel" en el archivo). Sólo gráficos de RM, PRs y rachas. |
| Tabla fantasma | `student_segments` (migración 021) | `BASICO / INTERMEDIO / AVANZADO` + scores. **Sin escritores y sin lectores** (ver 1.7). |

Escala real: **Principiante / Intermedio / Avanzado / Elite**. Las palabras "Básico / Intermedio / Avanzado"
sólo existen en `student_segments`; el "Básico" que se haya visto en pantalla viene de esa tabla vieja o de
una versión anterior del código, no del motor actual.

## 1.2 El algoritmo, paso a paso

```
mejores = [ (movimiento_id, max(peso_kg) por movimiento, nombre) ]   -- nivel_service.py:236
nivel_fuerza     = MIN( nivel de cada movimiento en CROSSFIT_RATIOS )       -- :175-196
nivel_gimnastico = MIN( nivel de cada movimiento en CROSSFIT_HABILIDADES )  -- :198-214
nivel_de_atleta  = MIN( nivel_fuerza, nivel_gimnastico )   -- se calcula en el FRONTEND (utils/niveles.js)
```

Consecuencias directas del diseño:

1. **Gana el más débil.** Con Back Squat Elite y Thruster Principiante, el nivel de fuerza es *Principiante*.
   Es deliberado ("el nivel más bajo entre todos los movimientos") pero no está explicado en la UI: el alumno
   ve "Principiante" aunque tenga marcas élite.
2. **Falta de datos ≠ falta de nivel.** Sin `peso_kg` o `genero`, la fuerza devuelve `"Sin datos"`
   (`:173-186`) aunque el atleta tenga 8 RMs cargados.
3. **Un eje ausente no neutraliza al otro.** `nivelDeAtleta` filtra los que no son nivel válido y hace `min`
   de lo que quede: con un solo eje presente, ese eje **es** el nivel del atleta.
4. **Se recalcula en vivo, siempre.** Los RMs se leen como `max(peso_kg)` por movimiento, así que el nivel
   puede **bajar** al cargar una marca peor en otro movimiento (no hay "progreso" congelado).

### Tabla de estándares (extracto)

Fuerza — ratio sobre peso corporal, masculino (`crossfit_ratios.py`):

| Movimiento | Principiante | Intermedio | Avanzado | Elite |
|---|---|---|---|---|
| Back Squat | 0,80 | 1,50 | 2,00 | 2,50 |
| Front Squat | 0,60 | 1,20 | 1,60 | 2,00 |
| Overhead Squat | 0,40 | 0,80 | 1,10 | 1,40 |
| Snatch | 0,40 | 0,80 | 1,00 | 1,30 |

Gimnasia — valor = reps unbroken / metros (`crossfit_habilidades.py`), masculino:

| Movimiento | Principiante | Intermedio | Avanzado | Elite |
|---|---|---|---|---|
| Pull-ups | 1 | 10 | 20 | 30 |
| Chest to Bar | 0 | 5 | 15 | 25 |
| Toes to Bar | 0 | 10 | 20 | 30 |
| Bar Muscle-up | 0 | 1 | 5 | 12 |
| HSPU | 0 | 3 | 10 | 15 |
| Double Unders | 1 | 20 | 50 | 100 |
| Handstand Walk (m) | 0 | 5 | 15 | 25 |

> `Double Unders` con 10 reps sigue siendo **Principiante** (Intermedio = 20), mientras que `Chest to Bar`
> con 10 reps ya es **Intermedio**. El mismo número de "valor" significa cosas distintas según el movimiento:
> por eso el campo genérico `peso_kg` ("el valor del RM") es un contrato demasiado laxo para clasificar.

## 1.3 Qué dicen los datos hoy (TEST y PROD, 2026-10-26)

Población:

| Métrica | Valor |
|---|---|
| Usuarios totales | 458 |
| Alumnos (`rol='alumno'`, todos en tenant 1) | 450 |
| Correos `@example.com` (copias demo) | 401 |
| Usuarios de carga `carga_k6_*@load.test` | 42 |
| Alumnos con `peso_kg` **y** `genero` (requisito del nivel de fuerza) | **26 (5,8%)** |
| Alumnos con al menos 1 RM | **22 (4,9%)** |
| Alumnos sin ningún RM | **428 (95,1%)** |
| Filas en `historial_rm` | 419 |
| Asistencias registradas | 24.752 (401 alumnos, 2025-10-02 → 2026-10-05) |
| Usuarios con `cambiar_password_al_login` | 20 |

RMs por movimiento (los 8 movimientos con marcas, de 103 existentes):

| Movimiento | Filas | Alumnos | Rango de fechas |
|---|---|---|---|
| Snatch (Arrancada) | **402** | 22 | 2026-06-14 → 2026-10-25 |
| Air Runner | 6 | 1 | 2026-07-08 → 2026-07-11 |
| Clean (Cargada) | 4 | 2 | 2026-07-08 → 2026-09-27 |
| Sled Push | 3 | 1 | 2026-07-11 |
| Strict Pull-up | 1 | 1 | 2026-07-10 |
| Chest to Bar (C2B) | 1 | 1 | 2026-07-08 |
| Hang Clean | 1 | 1 | 2026-10-19 |
| Kipping Pull-up | 1 | 1 | 2026-07-11 |

**402 de 419 filas (96%) son el mismo movimiento (Snatch)**, y 400 de ellas son 20 RMs × 20 usuarios
`carga_k6_*` creados hoy por una prueba de carga. Es decir: **el historial de RM del box, hoy, es
esencialmente ruido de test**. Sólo 2 alumnos no-sintéticos tienen marcas, y uno de ellos es el alumno 5
(3 movimientos gimnásticos + otros).

Distribución de nivel, **replicando el servicio real** (`nivel_desde_mejores` importado del repo) sobre los
22 alumnos con marcas:

| Nivel | Fuerza | Gimnasia | "Nivel de atleta" que pinta el frontend (`min`) |
|---|---|---|---|
| Principiante | 0 | 0 | 0 |
| Intermedio | 1 | 1 | 1 |
| Avanzado | 0 | 0 | 0 |
| Elite | **21** | 0 | **21** |
| Sin datos | 0 | **21** | — |

Extendido a los 450 alumnos:

| Nivel mostrado | Alumnos | % |
|---|---|---|
| Sin datos | 428 | 95,1% |
| Elite | 21 | 4,7% |
| Intermedio | 1 | 0,2% |
| Principiante / Avanzado | 0 | 0% |

Los 21 "Elite" no son atletas de élite: son usuarios de carga con un único Snatch aleatorio de 80–160 kg
sobre un peso corporal de 60–85 kg, que supera el umbral Elite de 1,3×. Es exactamente el escenario A2.

**Contraste con PROD** (misma función, rama `ep-winter-star`): 505 alumnos, **sólo 2 con alguna marca**,
**6 clasificables** (peso + género), **19 filas** en `historial_rm`. Resultado:
**503 de 505 "Sin datos"**, 1 Intermedio y 1 Elite:

| Alumno | Peso / género | RMs | Nivel fuerza | Nivel gimnasia | Nivel final |
|---|---|---|---|---|---|
| 5 | 105 kg / M | 7 | Intermedio (Clean **Avanzado**, Snatch Intermedio ⇒ gana el más bajo) | Intermedio | **Intermedio** |
| 9 | 75 kg / F | 3 | **Elite** (Clean 100 kg = 1,33× en la escala femenina) | Sin datos | **Elite** |

Dos lecturas: (1) **en el box real la función no tiene datos con los que trabajar** (503/505 vacíos);
(2) el `min` interno sí funciona cuando hay varios movimientos (alumno 5 baja de Avanzado a Intermedio por
su Snatch), pero **no se aplica entre ejes** cuando falta uno: el alumno 9 queda Elite sin una sola marca de
gimnasia. Ese es CL-02 en una línea.

Columna `nivel_calculado` almacenada en `historial_rm` (la que escribe el POST):

| Valor | Filas |
|---|---|
| `NULL` | 414 |
| `Elite` (Snatch) | 1 |
| `Elite` (Clean) | 1 |
| `Avanzado` (Clean) | 3 |
| **Total** | 419 |

De las 419 filas, **400 son de la prueba de carga** (usuarios `carga_k6_*`, insertadas por SQL, y las 400
con `nivel_calculado` en `NULL`) y **19 llegaron por la API** (2 alumnos reales). De esas 19, **14 quedaron en
`NULL`**: el POST solo escribe `nivel_calculado` si el alumno tiene `peso_kg` + `genero` y el movimiento
clasifica (ver CL-05), lo que confirma que el campo depende del perfil y no del RM.

## 1.4 Qué ve cada rol

| Rol | Dónde | Qué ve |
|---|---|---|
| Alumno | `Dashboard.jsx` | Dos tarjetas: "Fuerza: <nivel o 'SIN DATOS'>" + top-3 RMs; "Gimnasia: <nivel o 'SIN DATOS'>" + top-3. **No hay nivel único.** |
| Alumno | `PerformanceHub.jsx` | Ningún nivel. Gráficos de evolución de RM, PRs, rachas. |
| Alumno | `PizarraRMs.jsx` | Registro/edición/borrado de RMs; no muestra nivel. |
| Coach | Tab Progreso (`DashboardCoach.jsx`) | Badge "Nivel estimado" (el `min` de los dos) y chips de filtro: Todos / Principiante / Intermedio / Avanzado / Elite / Sin datos. |
| Admin | — | No hay ningún campo de nivel editable en la ficha del alumno. |

Dos inconsistencias de copy menores pero visibles: el endpoint de fuerza/gimnasia devuelve `"SIN DATOS"`
(mayúsculas, `historial_rm.py:894`) mientras `nivel-general` y el lote devuelven `"Sin datos"`
(`nivel_service.py:217-218`), y `utils/niveles.js` normaliza a `Sin datos`. En pantalla convive "SIN DATOS"
con "Sin datos".


## 1.5 Hallazgos de clasificación (uno por uno)

### CL-01 · El nivel de gimnasia depende de una columna que significa otra cosa
- **Dónde:** `nivel_service.py:156-158` (docstring) y `:200` (`obtener_nivel_gimnastico(nombre, max_peso, genero)`).
- **Qué pasa:** el cálculo vivo usa `max(peso_kg)` como "valor" gimnástico. Por convención **RM-01**, en
  gimnasia `peso_kg` **es** el número de repeticiones (`PizarraRMs.jsx:49-54`, `valorDelFormRM()`), así que
  "funciona"… siempre que el cliente lo llene bien. Pero:
  - `valorDelFormRM` cae a `|| 1` cuando el campo viene vacío o 0 ⇒ se puede guardar `peso_kg=1` con
    `repeticiones=0`;
  - el POST calcula el nivel guardado con `repeticiones or peso_kg` (`historial_rm.py:181`) y el cálculo vivo
    con `peso_kg` a secas ⇒ **dos fórmulas para el mismo dato**;
  - `HistorialRMUpdate` permite cambiar `peso_kg` o `repeticiones` sin recalcular nada (ver CL-05).
- **Impacto medido:** hoy el error está **latente**, no activo: de los 3 RMs gimnásticos existentes, 2
  (`Chest to Bar` 10, `Kipping Pull-up` 1) traen el valor en `peso_kg` y en `repeticiones`, y `Strict Pull-up`
  (15) ni siquiera tiene estándar. Cambiar el criterio a `repeticiones` **no mueve a ningún atleta hoy**, pero
  sí en cuanto el uso real mande reps con `peso_kg=1`.
- **Prueba concreta** (`obtener_nivel_gimnastico` invocado con el módulo real del repo):

  | Movimiento | valor = 1 | valor = 10 |
  |---|---|---|
  | Chest to Bar | Principiante | Intermedio |
  | Toes to Bar | Principiante | Intermedio |
  | Bar Muscle-up | Intermedio | Avanzado |
  | HSPU | Principiante | Avanzado |
  | Double Unders | Principiante | **Principiante** |

### CL-02 · Un solo RM (o uno mal cargado) define el nivel del atleta
- **Dónde:** `utils/niveles.js` (`nivelDeAtleta`) + `nivel_service.py:173-214`.
- **Qué pasa:** si falta un eje, el otro se usa tal cual. Con **una** Snatch de 120 kg y peso 80 kg (ratio
  1,5 ⇒ Elite), el coach ve "Elite" y el filtro de nivel lo pone en el grupo de élite, aunque el atleta no
  tenga ni una dominada registrada.
- **Evidencia:** 21 de 22 alumnos con marcas salen Elite **sólo** por la Snatch, y 21 de ellos tienen gimnasia
  "Sin datos": el `min` los deja en Elite.
- **Agrava:** no hay mínimo de cobertura (p. ej. "≥ 3 movimientos y ambos ejes") ni marca de confianza.

### CL-03 · El nivel no está persistido: no se puede consultar, filtrar ni reportar
- **Dónde:** `usuarios` no tiene columna de nivel (18 columnas, ninguna equivalente); no existe el enum
  `nivelescale`; `student_segments` no tiene consumidores.
- **Qué pasa:** el único cálculo es on-the-fly (3 endpoints + 1 de lote). No hay `WHERE nivel = 'Elite'` en
  SQL, no hay histórico de "en qué nivel estaba en marzo", y no se puede cruzar nivel con asistencia o
  retención sin recalcular en Python para toda la base.
- **Consecuencia de negocio:** el BI (`metricas_service`) no puede segmentar por nivel; el coach no puede
  "subir de grupo" a nadie porque la noción de grupo no existe.

### CL-04 · Los estándares cubren 24 de 103 movimientos; el resto se ignora en silencio
- **Dónde:** `crossfit_ratios.py` (8 claves) y `crossfit_habilidades.py` (17 claves) vs. tabla `movimientos`
  (103 filas: 42 fuerza, 49 gimnástico, 9 cardio, 3 metabólico).
- **Medido** (match por nombre exacto, sin normalizar, sobre la rama que usa el backend local):

  | | Claves de estándar | Claves con movimiento | Filas de `movimientos` que matchean |
  |---|---|---|---|
  | Fuerza | 8 | **7** | 7 |
  | Gimnasia | 17 | **15** | 17 (hay nombres duplicados: `Chest to Bar`, `HSPU`, `Box Jump(s)`) |

  - Clave **sin** ningún movimiento: `Jerk (Envión)` (fuerza). Y dos claves de gimnasia
    (`Bear Crawl (Caminata de oso)`, `Rope Climb (Subida de cuerda usando los pies)`) no matchean porque en
    la BD el nombre es otro (`Bear Crawl (Caminata)`, `Rope Climb (Trepada)`): dos estándares que existen y
    nunca se aplican.
  - **67 movimientos de fuerza/gimnasia no tienen estándar** y se descartan al calcular (no suman, no
    restan, no avisan). Entre ellos: `Strict Pull-up`, `Kipping Pull-up`, `Ring Dip`, `Dip`, `Hang Clean`,
    `Hang Snatch`, `Power Clean`, `Power Snatch`, `Split Jerk`, `Push Press`, `Bench Press`, `Wall Ball`,
    `Kettlebell Swing`, `Dumbbell Snatch`, `Box Jump Over`, `Burpee Box Jump`…
  - Los dos movimientos gimnásticos **más usados del CrossFit** (strict y kipping pull-up) están fuera de la
    tabla: el estándar sólo conoce `Pull-ups (Dominadas)`. Un alumno que registre 20 kipping consecutivas no
    mueve su nivel de gimnasia.

### CL-05 · `nivel_calculado`: dato huérfano y modificable por el cliente
- **Dónde:** `models/historial_rm.py:44`, escrito en `historial_rm.py:191-194`, expuesto en
  `schemas/historial_rm.py:51-52` como campo **de entrada** del `PUT`.
- **Qué pasa:**
  1. Se escribe una vez, en el POST, con la foto del momento.
  2. `PUT /historial-rm/{id}` hace `setattr` de todo lo que venga (`:469-472`) → el cliente puede mandar
     `{"nivel_calculado": "Elite"}` o simplemente editar `peso_kg` dejando el nivel viejo.
  3. **Nadie lo lee**: no aparece en ninguna consulta, ni en el frontend (grep de `nivel_calculado` devuelve
     sólo escritura + modelo + schema).
- **Veredicto:** o se usa (recalculado en cada escritura y leído por el BI) o se elimina. Hoy es una tercera
  fuente de verdad que nadie consulta y que puede contradecir a las otras dos.

### CL-06 · Validaciones del RM: pocas y sin topes
- **Dónde:** `schemas/historial_rm.py:13-30` y `:38-52`.
- **Qué falta:**
  - `peso_kg` es `gt=0` y **sin techo** → 530 kg es un registro válido;
  - `tipo_rm` es **string libre** (no hay whitelist `peso|tiempo|reps|altura|distancia`) y por defecto
    `"peso"`, incluso para un Sled Push o un Air Runner;
  - `fecha` no valida futuro ni antigüedad → un RM de 2030 entra igual;
  - `repeticiones`/`series` aceptan 0 (`ge=0`) pero la gimnasia necesita `>= 1` para clasificar;
  - no hay unicidad `(alumno_id, movimiento_id, fecha)`: hoy hay **23 pares alumno+movimiento con más de un
    registro**, legítimo para historial pero no modelado a propósito (el nivel toma el `max`, no el último).
- **Impacto:** un dato absurdo (o mal tipeado) contamina el nivel, porque el cálculo usa el máximo por
  movimiento y luego el mínimo entre movimientos.

### CL-07 · Calibración y explicabilidad de los umbrales
- **Dónde:** `crossfit_ratios.py`, `crossfit_habilidades.py`.
- **Observaciones:** los estándares están documentados con fuentes y son defendibles, pero:
  - el "min entre movimientos" **castiga la especialización**: un levantador con Snatch 1,4× y Thruster 0,9×
    queda en el nivel del Thruster;
  - `Elite` de Snatch masculino (1,3×) equivale a un atleta competitivo regional; con autoregistro (sin juez)
    es fácil de alcanzar y difícil de verificar;
  - no hay separación por edad (`usuarios.fecha_nacimiento` existe y no se usa) ni ajuste por peso corporal en
    gimnasia (una dominada en un atleta de 100 kg no vale lo mismo que en uno de 60);
  - el nivel de gimnasia ignora `series` (3×10 y 1×10 dan lo mismo) aunque el estándar dice "unbroken".

### CL-08 · Cobertura del dato: el nivel es invisible para el 95%
- **Dónde:** `usuarios.peso_kg`, `usuarios.genero`.
- **Medido:** 26/450 alumnos con ambos campos ⇒ 428 no pueden tener nivel de fuerza **por más RMs que carguen**.
  El perfil no obliga a completarlos y la UI de registro de RM no los pide.
- **Efecto combinado con CL-04:** incluso un atleta con peso y género puede quedar "Sin datos" si sus
  movimientos no están en los estándares.

### CL-09 · El "nivel" no se puede usar como criterio de programación
- **Qué pasa:** como no hay nivel persistido (CL-03) y el cálculo depende de datos personales incompletos
  (CL-08), hoy no existe forma de responder "¿a qué grupo mando a este alumno?" con el sistema. La decisión
  sigue siendo del coach a ojo y el badge del tab Progreso es informativo.
- **Consecuencia:** no hay clases ni WODs filtrados por nivel, ni recomendaciones automáticas por nivel (el
  `RecomendacionModal` de KPIs usa riesgo de churn, no nivel).

## 1.6 `student_segments`: la tabla que explica el "todos Básico"

- Creada en la migración `021_student_segments.py`, con `nivel VARCHAR` + `fuerza_score`, `gimnasia_score`,
  `consistencia_score`, `motor_version`, `calculado_en`.
- **Estado:** 0 referencias desde `app/` (sin imports, sin `SELECT`, sin `INSERT`). Se conserva en la BD, con
  datos viejos.
- **Qué implica:** cualquier reporte, dashboard o export que haya leído `nivel` de esa tabla sigue mostrando
  `BASICO` para todo el mundo, aunque el motor nuevo calcule otra cosa. Es la explicación más probable del
  síntoma "todos los atletas aparecen como Básico".
- **Recomendación:** dropear la tabla (o al menos marcarla `deprecated` en un comentario de migración) y, si se
  necesita nivel persistido, crearlo con el vocabulario **del motor** (`Principiante…Elite`), no con el viejo
  (`BASICO…AVANZADO`).


## 1.7 Ciclo de vida del RM (creación → nivel)

| Fase | Endpoint / función | Reglas aplicadas |
|---|---|---|
| Crear | `POST /historial-rm` (`historial_rm.py:130`) | `alumno_id` forzado al del token; `movimiento_id` debe existir; valida el valor contra el tipo de movimiento; escribe `nivel_calculado` con `calcular_nivel_general` (`:181-194`); inserta en `auditoria`. |
| Leer | `GET /historial-rm`, `GET /historial-rm/alumno/{id}` | Filtro por tenant + permiso (alumno ve sólo lo suyo; coach/admin su box; superadmin todo). |
| Editar | `PUT /historial-rm/{id}` (`:425`) | Sólo dentro de **24 h** desde `creado_en` (`VENTANA_EDICION_HORAS`), sólo el dueño (o superadmin); **no recalcula** `nivel_calculado`. |
| Borrar | `DELETE /historial-rm/{id}` (`:470+`) | Sólo el dueño/superadmin, **sin ventana**: se puede borrar un PR histórico en cualquier momento y eso **baja el nivel** si era el máximo. Queda en `auditoria`. |
| Mejores | `nivel_service.obtener_mejores_por_movimiento` (`:236`) | `MAX(peso_kg)` por movimiento del alumno; ignora `repeticiones` y `series`. |
| Clasificar | `nivel_desde_mejores` (`:152`) | Ver 1.2. |
| Graficar | `GET /historial-rm/progreso/{alumno_id}` | Serie temporal por movimiento para `PerformanceHub`. |

Observaciones del ciclo:

- La ventana de 24 h protege la **edición** pero no el **borrado**: un alumno puede borrar su PR de hace un
  año y reescribirlo, sin rastro visible para el coach (sólo en `auditoria`).
- El POST valida el valor contra el tipo de movimiento, pero **no** contra un máximo razonable ni contra el
  histórico del atleta (no avisa "esto es 30% más que tu PR anterior").
- **No hay endpoint para que el coach cargue o corrija un RM de un alumno.** El coach puede leer, pero la
  escritura vive en la sesión del alumno (o en superadmin): una marca mal cargada no se puede arreglar desde
  el panel del coach.

## 1.8 Recomendaciones — Parte 1 (priorizadas)

| Prio | Acción | Por qué | Esfuerzo |
|---|---|---|---|
| **P0** | Decidir e implementar **una** fuente de verdad del nivel: columna `usuarios.nivel` (+ `nivel_fuerza`, `nivel_gimnastico`, `nivel_calculado_en`, `nivel_version`) recalculada al escribir un RM y por un job nocturno, y que el frontend **lea** en vez de derivar. | CL-03, CL-09. Sin esto no hay reportes, ni grupos, ni auditoría. | M |
| **P0** | Exigir `peso_kg` + `genero` en el flujo de registro de RM (o en el onboarding) y mostrar un banner "completá tu perfil para ver tu nivel". Backfill de los 424 alumnos sin datos desde la ficha del coach. | CL-08: hoy 95% ve "Sin datos". Es la mejora de mayor impacto por peso. | S |
| **P0** | Regla de confianza mínima: no publicar "Elite"/"Avanzado" con **un solo** movimiento. Exigir ≥ 2 movimientos por eje o marcar el badge como "provisional" / "sin datos suficientes". | CL-02: 21/22 atletas "Elite" por una sola Snatch. | S |
| **P1** | Unificar el valor gimnástico: usar **`repeticiones`** como fuente (migrando `peso_kg` en filas de gimnasia) y dejar de leer `peso_kg` en `obtener_nivel_gimnastico`; alinear el POST (`repeticiones or peso_kg`) con el cálculo vivo. | CL-01: dos fórmulas para el mismo dato. | M |
| **P1** | Normalizar el match de nombres (slug/fuzzy + `movimientos.estandar_key`) y **loguear warning** cuando un movimiento no tiene estándar. Añadir los 8-10 movimientos que faltan (strict/kipping pull-up, power clean, power snatch, split jerk, push press, ring dip, wall ball, kettlebell swing). | CL-04: 67 movimientos ignorados en silencio, incluidos los pull-ups. | M |
| **P1** | Sanear `nivel_calculado`: quitarlo de `HistorialRMUpdate` (mass-assignment) y recalcularlo en POST y PUT, o eliminarlo si el nivel pasa a `usuarios`. | CL-05. | S |
| **P2** | Endurecer validaciones del RM: techo por movimiento, `tipo_rm` con whitelist/enum, fecha no futura, `repeticiones >= 1` en gimnasia, y aviso si el nuevo PR difiere >25% del anterior. | CL-06. | S |
| **P2** | Permitir que el coach cree/corrija RMs de sus alumnos (auditado), y añadir borrado lógico (`deleted_at`) en lugar de `DELETE` físico. | 1.7: hoy el coach no puede corregir nada. | M |
| **P2** | Explicar el nivel en la UI: "tu nivel es el **más bajo** entre fuerza y gimnasia; te falta X para subir" (siguiente umbral concreto por movimiento). | CL-07: el `min` castiga la especialización pero el usuario no lo sabe. | S |
| **P3** | Evaluar separar "nivel de fuerza" y "nivel gimnástico" como dos atributos ciudadanos de primera clase (no un `min`), con un "nivel competitivo" derivado y explícito. | CL-07/CL-09. | L |
| **P3** | Drops de `student_segments` (o documentarla como obsoleta) para que nadie vuelva a leer `BASICO`. | 1.6. | S |

---

# PARTE 2 — Mantenimiento automático: qué corre de verdad

## 2.1 Inventario de ejecutores

| Ejecutor | Dónde vive | Qué corre | ¿Versionado? | Estado verificado hoy |
|---|---|---|---|---|
| **Render Cron Jobs** (PROD) | Sólo en el **dashboard de Render** (`render.yaml` declara *únicamente* el web service: 1 solo `services:`/`type: web`) | Backup a R2 (`mantenimiento_cloud.py backup`), mantenimiento días 1 y 15 (`mantenimiento_cloud.py mantenimiento`), watchdog, restore drill, KPIs diarios/mensuales, predicciones | ❌ **No** | Activo con evidencia indirecta: `daily_kpis` tiene 43 filas hasta 2026-10-25 (falta 10-24 y 10-26); `predictions_churn` 460 filas creadas hoy 10:01 UTC |
| **Contenedor `box-crossfit-maintenance-1`** | `backend/Dockerfile.cron` + `backend/maintenance/crontab` | Diario 02:30 CLT (`run_daily.py`, 5 pasos) y mensual día 1 03:00 CLT (`run_monthly.py`, 9 pasos) | ✅ Sí | ❌ **Falla 5/5 pasos, todos los días** desde 2026-10-02 (ver 2.2) |
| **Scheduler in-app** (`app/services/scheduler.py`) | Proceso del backend (PROD y local) | Notificaciones diarias de renovación/inactividad/último crédito/créditos agotados, por tenant, con `CronTrigger` + catch-up y lock de liderazgo | ✅ Sí | Activo en PROD: `notificaciones_enviadas` con 574 envíos hoy y 257 el 10-18. Inestable en local (ver 2.6) |
| **n8n** | `docker-compose.yml` (`box-crossfit-n8n-1`) | Flujos de notificaciones legacy + `fidelizacion y retencion` (PROD) | Parcial: **7 de 18** workflows en el repo | Contenedor **`Exited` hace 3 semanas** en este equipo (ver 2.7) |
| Celery / colas | — | — | — | **No existe**. Todo es cron + `AsyncIOScheduler` |

## 2.2 El job diario local: qué hace y por qué nunca funciona

Crontab real del contenedor (2 líneas activas, TZ `America/Santiago`):

```
30 2 * * *  boxapp  cd /app && python -m maintenance.run_daily   >> /app/logs/cron.log 2>&1
0  3 1 * *  boxapp  cd /app && python -m maintenance.run_monthly >> /app/logs/cron.log 2>&1
```

Los 5 pasos de `run_daily.py`: `1/5 backup_neon` · `2/5 marcar_plan_vencido` · `3/5 transacciones_huerfanas`
· `4/5 health_check` · `5/5 neon_usage_alerts`. Cada paso devuelve `bool` y `_paso()` lo evalúa (`:24-43`),
así que el resumen final es honesto **desde que se corrigió en septiembre**.

Resultado real por día (extraído de `/app/logs/maintenance_daily_*.log`):

| Día | Pasos OK | Resultado del log |
|---|---|---|
| 2026-08-22 | 5/5 | `✅ JOB DIARIO COMPLETADO` — **con el `pg_dump` fallando** (falso verde, ver 2.3) |
| 2026-09-11 | 5/5 | `✅ JOB DIARIO COMPLETADO` |
| 2026-09-24 | 5/5 | `✅ JOB DIARIO COMPLETADO` |
| 2026-09-25 | 5/5 | `✅ JOB DIARIO COMPLETADO` |
| 2026-09-26 (15:44) | 12 líneas OK | corrida **manual** (fuera de cron) — es la que produjo el único backup |
| 2026-09-27 (04:04) | 5/5 | `✅ JOB DIARIO COMPLETADO` |
| 2026-09-28 | 5/5 | `✅ JOB DIARIO COMPLETADO` |
| 2026-09-29 | 5/5 | `✅ JOB DIARIO COMPLETADO` |
| 2026-09-30 | 5/5 | `✅ JOB DIARIO COMPLETADO` |
| **2026-10-02** | 0/5 | `❌ JOB DIARIO TERMINADO CON 5 FALLO(S) de 5 pasos` |
| **2026-10-06 → 10-12** (7 días) | 0/5 | `❌ ... CON 5 FALLO(S) de 5 pasos` |
| **2026-10-20 → 10-26** (7 días) | 0/5 | `❌ ... CON 5 FALLO(S) de 5 pasos` |
| 2026-10-01, 10-03..10-05, 10-13..10-19 | — | **sin log**: el cron no corrió (contenedor detenido), no hay reintento ni catch-up |

Balance: **15 corridas fallidas consecutivas** registradas (10-02 → 10-26) y **12 días sin ejecución** en los
últimos 25. El patrón coincide con el reinicio del contenedor ("Up 2 days" el día del cambio de configuración).

### Causa raíz (verificada, no inferida)

El log de cada corrida fallida arranca así:

```
app.core.config - WARNING - [config] ENVIRONMENT=None no reconocido: se asume TEST (se carga .env.test)
pg_dump: pg_dump (PostgreSQL) 18.6 | destino: /app/backups | origen: localhost/dbname
pg_dump error (rc=1): connection to server at "localhost" ... port 5432 failed: Connection refused
```

1. **`cron` no hereda el entorno del contenedor.** `docker exec ... env` muestra
   `ENVIRONMENT=test`, `EMAIL_MODO=noop` y `DATABASE_URL=...`; el proceso del cron los ve como `None`.
2. Sin `ENVIRONMENT`, `app/core/config.py` cae al fail-safe y **carga `.env.test`**, cuya `DATABASE_URL`
   apunta a `localhost:5432` (el Postgres de docker-compose, que no existe dentro de este contenedor). De ahí
   los 5 fallos: los 4 pasos que usan la BD y el health-check (que además busca el backend en `localhost:8000`).
3. **Aun heredando el entorno, fallaría:** la `DATABASE_URL` del contenedor de mantenimiento apunta a
   `ep-summer-river-b6c8fj2f.c-2.sa-east-1...` y esa credencial **está revocada** — verificado:
   `psycopg2.OperationalError: password authentication failed for user 'neondb_owner'`.

**Impacto real:** desde el 2026-10-02 no hay backup automático, no se marcan planes vencidos, no se limpian
transacciones huérfanas, no hay health-check y no hay aviso de cuota de Neon. Todo con salida 0 para el
sistema operativo: **nadie se enteró**.


## 2.3 Los dos falsos verdes (este sí es el hallazgo grave)

**(a) Falso verde histórico — "backup OK" con `pg_dump` roto.** Log del 2026-08-22:

```
maintenance.backup_neon - ERROR - pg_dump error: connection to server at "localhost" ... Connection refused
__main__                - INFO  - ✅ Backup completado
__main__                - INFO  - ✅ JOB DIARIO COMPLETADO
```

Ese comportamiento **ya está corregido** (`backup_neon.ejecutar_backup()` devuelve `False` y `run_daily` lo
evalúa). Se documenta porque demuestra el patrón: durante agosto el sistema decía "todo bien" con la base
inaccesible, y nadie lo notó hasta revisar los logs a mano.

**(b) Falso verde actual — "alerta enviada" que no se envió.** Log de hoy (2026-10-26):

```
health_check - WARNING - 📧 ALERTA [Backend DOWN] -> jmirandai1985@gmail.com: ...
uvicorn.email - INFO   - [EMAIL_MODO=noop] correo SIMULADO a 'jmirandai1985@gmail.com'
uvicorn.email - WARNING - No se pudo registrar envio: (psycopg2.OperationalError) ...
health_check - INFO    - ✅ Alerta enviada a jmirandai1985@gmail.com
```

`email_service._enviar()` **devuelve `True` en modo `noop`** (`email_service.py:390`) y `health_check`
interpreta `True` como "enviado" (`health_check.py:61-63`). Resultado: el health-check reporta éxito de una
alerta simulada, y encima falla el registro del envío. Si el backend se cae de verdad, **no llega ningún
correo y el log dice que sí**.

**(c) Y en PROD los correos tampoco salen** (ver 2.8): 245 de los 538 fallos de `notificaciones_enviadas` son
literalmente `Configuración SMTP incompleta: GMAIL_SMTP_USER y/o GMAIL_SMTP_APP_PASS`.

## 2.4 El único backup que existe

```
/app/backups$ ls -la
-rw-r--r-- 1 boxapp boxapp 1473675 Sep 26 15:44 neon_backup_20260926_154426.sql
```

- **Un** archivo, de **1,4 MB**, del **2026-09-26 15:44** (hora de la corrida manual, no del cron).
- La retención de `backup_neon` (borra `neon_backup_*.sql` > 30 días) nunca se activó porque no hay nada que
  borrar.
- No hay verificación de restauración, ni checksum, ni copia off-site (eso lo hace `mantenimiento_cloud.py`
  a R2, y corre en Render, no acá).

## 2.5 Ramas Neon: hay cuatro y cada componente usa una distinta

Medido hoy (conexión real, sólo `count(*)`):

| Rama | Host | La usa | usuarios | alumnos | `historial_rm` | Estado |
|---|---|---|---|---|---|---|
| `ep-winter-star-akwis51j-pooler` | us-west-2 | `backend/.env` → **PROD** (Render) | 511 | 505 | 19 | ✅ conecta |
| `ep-crimson-tooth-akhx7q2s-pooler` | us-west-2 | `backend/.env.test` → **TEST** (declarada espejo de PROD) | 458 | 450 | 419 | ✅ conecta |
| `ep-lingering-fog-arywdnbg-pooler` | us-west-2 | **`box-crossfit-backend-1` en ejecución** (config vieja) | 416 | 410 | 19 | ✅ conecta |
| `ep-summer-river-b6c8fj2f` | **sa-east-1** | **`box-crossfit-maintenance-1`** | — | — | — | ❌ `password authentication failed` |

Consecuencias:

1. **El backend local no apunta a TEST.** Cualquier prueba manual contra la app local (incluidos los datos
   que se carguen por la UI) escribe en `lingering-fog`, que tiene 42 usuarios menos y **400 RMs menos** que
   `crimson-tooth`. Dos personas probando "lo mismo" ven cosas distintas.
2. **El contenedor de mantenimiento no puede tocar ninguna base.** Ni siquiera si el cron heredara el
   entorno: su credencial está revocada. Y apunta a otra región (sa-east-1), lo que sugiere una rama creada a
   mano y olvidada.
3. **PROD tiene 19 RMs en 505 alumnos** (ver 2.8): el volumen real de uso del módulo de RM es mínimo, así que
   los "402 RMs" de TEST son **ruido de la prueba de carga** del 2026-10-25, no actividad del box.


## 2.6 Scheduler in-app (notificaciones)

- Registra jobs con `scheduler.add_job(..., trigger=CronTrigger(...))` (`scheduler.py:150-210`), TZ
  `America/Santiago`, con **lock de liderazgo en BD** y **catch-up** de ventanas perdidas.
- En 48 h de `app.log` se ven **121 pérdidas de liderazgo** (~cada 24 min) por
  `idle_in_transaction_session_timeout`: ese timeout de Neon corta la sesión que mantiene el lock. El diseño
  se recupera solo (re-adquiere + catch-up), pero es ruido constante y un disparo en el hueco exacto depende
  de que el catch-up lo cubra.
- Lo que sí envía en PROD: `notificaciones_enviadas` con 574 registros hoy (8 tipos) y 257 el 10-18;
  `notificaciones` in-app con 485 de 518 filas creadas hoy.

## 2.7 n8n y los Cron Jobs de Render

- `n8n/workflows/` versiona **7 de los 18** workflows de la instancia (README, línea 102). Desde el
  **2026-09-29** los 4 workflows de KPIs/ML de PROD se retiraron "a favor de un Cron Job de Render"; los de
  **notificaciones** siguen apuntando a n8n.
- En este equipo `box-crossfit-n8n-1` está **`Exited` (0) hace 3 semanas**: cualquier flujo que todavía
  dependa de n8n **no se ejecuta acá**. En PROD la instancia de n8n es otra (externa), por eso
  `fidelizacion y retencion` sí puede correr allí — pero **no hay reemplazo en el repo** ni forma de saber
  desde el código si sigue activo (el único rastro es `n8n/workflows/fidelizacion_y_retencion_prod.json`).
- Los Cron Jobs de Render (backup a R2, mantenimiento 1 y 15, watchdog, restore drill) **no están en
  `render.yaml`**: existen sólo en el dashboard. Si alguien borra uno, el repo no lo delata, y un `render.yaml`
  nuevo no los recrea. Además `mantenimiento_cloud.py` trae `DRY_RUN=1` **por defecto**: sin la variable
  explícita, el dump se genera y **no se sube**, sin error.

## 2.8 Qué corre de verdad en PROD (evidencia indirecta)

| Señal | Dato medido | Lectura |
|---|---|---|
| `daily_kpis` | 43 filas, última 2026-10-25; faltan **10-24** y 10-26 | El job diario de KPIs corre casi todos los días; **una falta en 30 días** y nadie se enteró |
| `monthly_kpis` | 13 filas, una por `(year, month)`, backfill completo el 2026-10-02 | Idempotente por mes (bien); el backfill sugiere que antes no corría |
| `predictions_churn` | 460 filas, **todas** creadas 2026-10-26 10:01 UTC | Una corrida reescribe toda la tabla: sin histórico ni auditoría del modelo |
| `notificaciones_enviadas` | 2.017 filas (1.479 `enviado` / **538 `fallido`** = 26,7%) | La automatización de avisos es real y **falla uno de cada cuatro envíos** |
| `notificaciones` (in-app) | 518 filas, 485 hoy | Ráfaga masiva: el scheduler trabaja |
| `password_reset_tokens` | 2 filas, **ambas expiradas** desde 2026-09-26 | La purga de tokens no está corriendo (o no cubre esta tabla) |
| `student_segments` | **6 filas, todas `BASICO`**, creadas 2026-09-12 21:27 | La foto congelada que explica el "todos Básico" |

Detalle de los 538 fallos de notificación (top):

| Causa registrada | Filas |
|---|---|
| `Configuración SMTP incompleta: GMAIL_SMTP_USER y/o GMAIL_SMTP_APP_PASS` | **245** |
| `Header values may not contain linefeed or carriage return characters` | **107** |
| `Connection unexpectedly closed` | 20 |
| `inactividad FALLIDO -> <correo del alumno>` (detalle individual) | ~166 |

Por tipo: `inactividad` 272 (el flujo de retención, el más valioso), `solicitud_prueba_clase` 90,
`solicitud_registro` 84, `confirmacion_renovacion` 46, `confirmacion_pedido` 37, `renovacion_plan` 4.
Ojo: **166 de los 538 fallos no tienen causa diagnóstica** — su `detalle_error` es literalmente
`inactividad FALLIDO -> <correo>`, es decir el propio mensaje del job, sin el error de SMTP. Los 4 bloques
suman los 538 exactos (245 + 107 + 20 + 166). **Nadie monitorea `estado='fallido'`**: no hay alerta, ni
reintento, ni panel; la única forma de saberlo es esta consulta.

## 2.9 Gaps de retención (con conteos de PROD)

| Tabla | Filas | Tamaño | Antigüedad | Purga hoy | Riesgo |
|---|---|---|---|---|---|
| `reservas` | **23.495** | 9,1 MB | desde 2025-09-28 | ❌ ninguna | Es dato de negocio, pero sin archivado crece ~1.800/mes |
| `asistencias` | **24.752** | 3,0 MB | desde 2025-10-02 | ❌ ninguna | Igual: sin archivado por año |
| `notificaciones_enviadas` | 2.017 | 744 kB | desde 2026-09-14 | ⚠️ sólo >180 d, y sólo en el job de PROD | Contiene 538 fallos que nadie revisa |
| `notificaciones` (in-app) | 518 | 416 kB | desde 2026-07-04 | ❌ ninguna | Bandeja del alumno: crece para siempre |
| `predictions_churn` | 460 | 472 kB | 1 corrida (hoy) | ♻️ se reescribe | Sin histórico ⇒ no se puede medir si el modelo acierta |
| `password_reset_tokens` | 2 | 56 kB | 2026-09-26 | ❌ ninguna acá | Tokens **expirados** vivos >30 días |
| `auditoria` | 68 | 208 kB | — | ❌ ninguna | Traza legal: conviene retener, pero con TTL definido |
| `usuarios` | 511 (465 `activo` / **46 `baja`**) | 328 kB | — | ❌ sin anonimización | Datos personales de ex-alumnos indefinidamente |
| `daily_kpis` / `monthly_kpis` | 43 / 13 | 56 kB c/u | — | ❌ | Chico, sin urgencia |
| `refresh_tokens` / `sesiones` | **no existen** | — | — | N/A | La sesión es JWT sin tabla: no hay nada que purgar |

Nota: la purga que **sí** está implementada (tokens de reseteo > 30 días y notificaciones envíadas > 180 días)
vive en `mantenimiento_cloud.py`, o sea en el cron de **PROD**, no en el job local. Y los 2 tokens expirados
del 2026-09-26 siguen ahí, lo que sugiere que esa corrida no está ocurriendo o no cubre `password_reset_tokens`.


## 2.10 Recomendaciones — Parte 2 (priorizadas)

| Prio | Acción | Por qué | Esfuerzo |
|---|---|---|---|
| **P0** | Hacer que el cron vea el entorno: `ENVIRONMENT` + `DATABASE_URL` en el crontab (o `/etc/environment` + `BASH_ENV`), **y** poner una URL válida de la rama correcta. Verificar al día siguiente que los 5 pasos dan OK y que aparece un `neon_backup_*.sql` nuevo. | B1: 15 corridas fallidas seguidas; hoy no hay backup. | S |
| **P0** | **Alerta de fallo del job** (healthchecks.io / webhook / email real): ping al final de `run_daily` y estado `failed` si `fallos > 0`. Sin esto, el mismo fallo silencioso vuelve. | B1/B2: el job falló 15 días sin que nadie lo supiera. | S |
| **P0** | Corregir el falso verde de `health_check`: `_enviar()` no debe devolver `True` en `noop` (o `health_check` debe distinguir "simulado"). | B2b: "✅ Alerta enviada" de un correo que no salió. | S |
| **P0** | Configurar SMTP en Render (`GMAIL_SMTP_USER` / `GMAIL_SMTP_APP_PASS`) y **monitorear `notificaciones_enviadas.estado='fallido'`** con un panel o alerta diaria. | 245 fallos por SMTP + 272 de `inactividad`: el flujo de retención no llega. | S |
| **P1** | Verificar y revocar la rama `ep-summer-river` (sa-east-1); dejar **un** `DATABASE_URL` por entorno y documentar cuál rama usa cada componente. Recrear los contenedores locales desde `.env.test`. | B5/2.5: 4 ramas, 3 configs distintas, 1 credencial muerta. | S |
| **P1** | Versionar los Cron Jobs de Render en `render.yaml` (`type: cron`, `schedule`, `command`, `envVars`) y quitar el `DRY_RUN=1` por defecto (fail-closed). | B4: automatización invisible y fail-open. | M |
| **P1** | Restore drill real: restaurar el backup en una rama Neon desechable y correr `verificar_integridad`. Un backup que nunca se restauró no es un backup. | B3: el único backup tiene 1 mes y 1,4 MB. | M |
| **P2** | Sanear la causa del `Header values may not contain linefeed` (sanitizar `nombre`/`asunto` antes de `EmailMessage`): 107 fallos y superficie de header injection. | 2.8 | S |
| **P2** | Retención explícita: TTL/anonymización para `notificaciones`, `password_reset_tokens` (borrar expirados), `auditoria` (p. ej. 24 meses), y archivado por año de `reservas`/`asistencias`. | 2.9: 23k + 24k filas sin política. | M |
| **P2** | Job mensual: agregar `maintenance_monthly_*.log` y confirmar que corre (hoy **nunca corrió** en este host). | 2.4: `/app/reportes` vacío, sin logs mensuales. | S |
| **P3** | Reemplazar el patrón de lock del scheduler (advisory lock de Postgres o `pg_try_advisory_lock` en autocommit) para eliminar las 121 pérdidas de liderazgo/48 h. | B7 | M |
| **P3** | Reemplazar `fidelizacion y retencion` (n8n PROD) por un Cron Job versionado, o documentar su existencia y dependencia. | B9 | M |

---

# PARTE 3 — Plan de acción sugerido

**Semana 1 — dejar de perder datos y de mentir en verde**

1. Arreglar el entorno del cron + URL válida (P0). Verificar un backup nuevo al día siguiente.
2. Alerta de fallo del job diario (P0).
3. Corregir `noop` → "enviado" (P0) y configurar SMTP en Render (P0); panel de fallidos.
4. Confirmar qué rama es TEST y recrear los contenedores locales apuntando a ella (P1).

**Semana 2 — cerrar los agujeros de la clasificación**

5. Exigir `peso_kg` + `genero` en el onboarding del alumno y backfill desde la ficha del coach (P0 Parte 1).
6. Regla de "confianza mínima" para no publicar Elite con un solo movimiento (P0 Parte 1).
7. Decidir la fuente de verdad del nivel (`usuarios.nivel` persistido) y recálculo en escritura + nightly (P0 Parte 1).
8. Unificar el valor gimnástico en `repeticiones` y normalizar los nombres contra los estándares, con warning
   en el log cuando un movimiento no clasifica (P1 Parte 1).

**Semana 3-4 — higiene y observabilidad**

9. Versionar los cron de Render y quitar el `DRY_RUN` por defecto.
10. Restore drill + retención de tablas + limpieza de tokens expirados.
11. Borrar `student_segments` (o documentarla como obsoleta) para cortar la última fuente del "todos Básico".

---

# Anexo A — Cómo se obtuvo la evidencia (todo read-only)

```powershell
# 1) Clasificación, replicada con el CÓDIGO REAL (importa app.services.nivel_service)
python %TEMP%\audit_env.py        backend/.env.test   # rama TEST (crimson-tooth) -> distribución 1.3
python %TEMP%\audit_prod_nivel.py backend/.env        # rama PROD (winter-star) -> tabla de 1.3
python %TEMP%\audit_cobertura.py                      # cobertura de estándares + impacto CL-01
python %TEMP%\audit_nivel.py                          # RMs, validaciones y histórico (TEST)

# 2) Inventario de tablas, tamaños y conteos exactos
python %TEMP%\audit_tablas.py backend/.env

# 3) Cadencia real de la automatización (daily_kpis, monthly_kpis, predictions_churn...)
python %TEMP%\audit_cadencia.py backend/.env
python %TEMP%\audit_notif.py    backend/.env
python %TEMP%\audit_err.py      backend/.env          # desglose de los 538 fallos

# 4) Estado del mantenimiento local
docker cp box-crossfit-maintenance-1:/app/logs/.  $env:TEMP\mlogs\   # logs diarios
docker exec box-crossfit-maintenance-1 sh -lc "ls -la /app/logs /app/backups; crontab -l"
docker exec box-crossfit-maintenance-1 sh -lc "env | grep -Ei 'environment|database_url'"

# 5) Qué rama usa cada contenedor y si conecta
docker exec box-crossfit-backend-1 sh -lc "env | grep DATABASE_URL"
docker ps -a --format '{{.Names}} | {{.Status}}'     # incluye n8n Exited
```

Ninguna consulta hace `INSERT`/`UPDATE`/`DELETE`; los conteos son `count(*)` y agregados. Los scripts
quedaron **fuera del repo** (`%TEMP%`), y los logs se copiaron a `%TEMP%\mlogs` (copia, no se movió nada).


# Anexo B — Limitaciones de esta auditoría

1. **Los datos de clasificación de TEST no representan al box.** 400 de 419 RMs son de una prueba de carga
   (`carga_k6_*@load.test`, 2026-10-25) y 401 de 458 usuarios son copias demo. Las cifras de "clasificación"
   sirven para demostrar los defectos del algoritmo (y así se usaron), no para describir atletas.
2. **El dato representativo de PROD es otro y es pequeño:** 505 alumnos, **2 con RM**, **6 clasificables**
   (peso + género), 19 filas de `historial_rm`. La conclusión "el nivel es invisible" se sostiene **más** en
   PROD que en TEST.
3. **No se accedió al dashboard de Render ni a la instancia de n8n de PROD.** Lo que corre en PROD se infiere
   de sus efectos en la base (`daily_kpis`, `monthly_kpis`, `predictions_churn`, `notificaciones_enviadas`),
   que es evidencia fuerte pero no prueba la configuración exacta del job (horario, reintentos, alertas).
4. **Las 4 ramas se probaron con `count(*)` y agregados**, sin leer PII. No se probó ninguna operación de
   escritura.
5. **La fecha "hoy" de los logs es 2026-10-26**; el log diario de ese día ya estaba escrito a las 02:30 CLT
   cuando se auditó.
6. **No se auditó** el contenido pedagógico de los WODs, la facturación ni el módulo de referidos: quedan
   fuera de alcance por pedido explícito (clasificación + mantenimiento).

# Anexo C — Índice de hallazgos

| ID | Título | Sev. | Sección |
|---|---|---|---|
| A1 | El nivel no existe como campo (se deriva en el frontend) | Alta | 1.1, CL-03 |
| A2 | Un solo RM define el nivel; "min" + ejes sueltos ⇒ Elite falsos | Alta | 1.2, CL-02 |
| A3 | 95% de los alumnos sin `peso_kg`/`genero` ⇒ "Sin datos" | Alta | 1.3, CL-08 |
| A4 | `nivel_calculado` write-only y mass-assignable | Media | CL-05 |
| A5 | 67 movimientos sin estándar, ignorados en silencio | Alta | CL-04 |
| A6 | Gimnasia mide con `peso_kg` y hay dos fórmulas distintas | Media | CL-01 |
| B1 | Job diario local falla 5/5 desde 2026-10-02 (cron sin entorno) | **Crítica** | 2.2 |
| B2 | Falsos verdes: "Backup completado" (histórico) y "Alerta enviada" (activo) | **Crítica** | 2.3 |
| B3 | Único backup: 1,4 MB, del 2026-09-26, manual | **Crítica** | 2.4 |
| B4 | Cron Jobs de PROD no versionados; `DRY_RUN=1` por defecto | Alta | 2.7 |
| B5 | 4 ramas Neon con 4 configuraciones; una con credencial revocada | Alta | 2.5 |
| B6 | 538/2.017 notificaciones fallidas (26,7%), 245 por SMTP sin configurar | **Crítica** | 2.8 |
| B7 | Scheduler pierde liderazgo 121 veces / 48 h | Media | 2.6 |
| B8 | Sin retención en `reservas`, `asistencias`, `notificaciones`, tokens expirados | Media | 2.9 |
| B9 | `fidelizacion y retencion` (n8n PROD) sin reemplazo ni versión | Media | 2.7 |

---

*Documento generado el 2026-10-26. Read-only: ningún archivo de producto, dato o configuración fue
modificado. Queda sin commitear para revisión.*

---

# Anexo D — B1–B9 al 2026-10-28

Tres commits nuevos en `main` (sin push) cierran o desbloquean 6 de los 9 hallazgos de la Parte 2;
los otros 3 dependen de una decisión de negocio, no de código. Nada de esta tanda se ejecutó
contra PROD: lo que escribe se probó con dobles (`tests/test_mantenimiento_cloud.py`, sin red ni
credenciales) y lo que despliega se declara en el blueprint para que lo aplique Render.

| ID | Hallazgo (§2) | Estado | Dónde quedó |
|---|---|---|---|
| B1 | Job diario local falla 5/5 desde 2026-10-02 | ✅ **Ejecutado** | `19676ff`, ver D.1 |
| B2 | Falsos verdes: "Backup completado" y "Alerta enviada" | ✅ **Ejecutado** | `19676ff` + `bcfc6bf`, ver D.1 |
| B3 | Único backup: 1,4 MB del 2026-09-26, manual | 🟡 **Desbloqueado, sin corrida real** | decisión 1, D.4 |
| B4 | Cron Jobs sin versionar; `DRY_RUN=1` por defecto | ✅ **Ejecutado** | `0f886bd` + `e3973c8`, ver D.2 |
| B5 | 4 ramas Neon, una con credencial revocada | ⛔ **Bloqueado** | decisión 2, D.4 |
| B6 | 538/2.017 notificaciones fallidas (26,7 %) | 🟡 **Código sí; los 538 históricos no se tocaron** | `d032d5b` `654fe05` `eaf8298` `bcfc6bf`, ver D.3 |
| B7 | Scheduler pierde liderazgo 121 veces / 48 h | ✅ **Ya estaba arreglado** (2026-10-11) | `65c1910`, ver D.3 |
| B8 | Sin retención en `reservas`, `asistencias`, `auditoria` y usuarios `baja` | ⛔ **Bloqueado** (falta la política) | decisión 3, D.4 |
| B9 | `fidelizacion y retencion` sin reemplazo ni versión | ⛔ **Bloqueado** + hallazgo nuevo | `017bd65`, ver D.4 |

## D.1 B1/B2 — el job local ya corre con el entorno del contenedor

La causa del falso verde era una sola línea del crontab: `boxapp cd /app && python -m
maintenance.run_daily >> …` con **cron, que no hereda el entorno del contenedor**. `ENVIRONMENT`
llegaba vacío, el fail-safe elegía `.env.test` (localhost:5432), el job moría con "Connection
refused" y el redirect dejaba un log vacío con **salida 0**: indistinguible de un día sin nada
que hacer.

- `maintenance/docker-entrypoint.sh` (nuevo `ENTRYPOINT`): vuelca `env_file:` + `environment:`
  —lo que docker-compose ya inyecta— a `/etc/box-maintenance.env` `0600 boxapp`, y hace
  `exec cron -f`. No escribe el archivo si no hay nada que volcar (no inventa un entorno vacío) y
  nunca imprime valores: sólo los nombres de las variables.
- `maintenance/cron_job.sh` (nuevo): lo invoca cada línea del crontab; carga el snapshot con
  `set -a`, hace `cd /app`, verifica que el módulo exista y ejecuta `python -m <módulo>`. Sin
  snapshot sale con **78 (EX_CONFIG)** en vez de arrancar a ciegas.
- `crontab`: `SHELL=/bin/sh` y `PATH=/usr/local/bin:/usr/bin:/bin` explícitos (el `sh` de Debian
  es dash y el PATH mínimo de cron no incluye `/usr/local/bin`).
- `.gitattributes` (nuevo): `*.sh`, `backend/maintenance/crontab` y `Dockerfile*` con `eol=lf`
  aunque el repo se clone en Windows. Un CRLF al final deja el comando con el retorno de carro
  pegado: la misma clase de falla silenciosa, y el repo no tenía ninguna regla de fin de línea.
- B2 (segunda mitad): `bcfc6bf` ya había sacado el "✅ Alerta enviada" cuando el correo era
  simulado; la primera mitad ("Backup completado" sin backup) era justamente B1.

Verificación: `docs/CRON_JOBS_RENDER.md` §5 tiene los 5 comandos (cuántas variables volcó el
entrypoint, el `0600` del snapshot, el crontab con el wrapper, un job leyendo el entorno real
como `boxapp`, y los logs del volumen).

## D.2 B4 — los 5 Cron Jobs y el modo de ejecución explícito

- `render.yaml` declaraba **sólo** el Web Service y decía que el cron de mantenimiento quedaba
  afuera. Ahora tiene 6 servicios: el `web` y los 5 `type: cron` (`proyecto-crossfit` 06:00,
  `box-crossfit-mantenimiento-prod` 08:00 los días 1 y 15, `box-crossfit-watchdog` 12:00,
  `box-crossfit-restore-drill` 13:00 el día 1, `box-crossfit-kpis-ml` 10:00; todo en UTC), con
  `dockerfilePath: backend/Dockerfile.cron`, `dockerContext: backend` y `dockerCommand`
  explícito en cada uno (sin él, Render usaría el `CMD` de la imagen y un job de mantenimiento
  haría un backup).
- `mantenimiento_cloud.dry_run_activo()` era `os.getenv("DRY_RUN", "1")` y `Dockerfile.cron`
  también fijaba `DRY_RUN=1`: un env group incompleto producía runs **verdes que no aplicaban
  nada**. Ahora la lista es cerrada (`0/false/no/off` = REAL, `1/true/si/sí/yes/on` = ROLLBACK) y
  cualquier otra cosa —incluida la variable ausente— es `ConfigError` ⇒ **exit 2 + correo**, sin
  un solo `psql`. Tests nuevos: `test_c2` (ausente), `test_c3` (valor desconocido) y `test_c4`
  (lista cerrada) en `tests/test_mantenimiento_cloud.py` ⇒ **182 passed**.
- Los 2 jobs que aplican cambios (`mantenimiento-prod` y `kpis-ml`) fijan `DRY_RUN: "0"` **en el
  servicio** porque una variable del servicio gana sobre la del env group y `kpis_cloud` cae a
  `1` si falta (fail-open). `backup_cloud` conserva su default `1` en el código: se compensa con
  `DRY_RUN=0` en el grupo `backups-prod` y lo vigila el watchdog (objeto viejo en R2).
- `docs/CRON_JOBS_RENDER.md` (nuevo): tabla de los 5 jobs, inventario de env groups con los
  nombres reales (`PROD_DB_DIRECT_URL`, `R2_*`), orden de sincronización (los grupos primero; el
  sync empareja por nombre y falla si el job no está asociado al blueprint), tabla de `DRY_RUN` y
  precedencia, verificación de B1, lo que sigue sin versionarse y un snippet de validación del
  YAML sin credenciales.

## D.3 B6 y B7 — lo que ya estaba resuelto y lo que no

**B6 (correos).** Los 538 fallos se atacaron por causa, en commits previos a esta auditoría:
`d032d5b` (guarda SMTP + modo failsafe), `654fe05` (reintento del corte de SMTP con conexión
nueva y ráfagas espaciadas), `eaf8298` (alerta **A.7** de correos fallidos dentro del job de
mantenimiento + retención de la bandeja in-app) y `bcfc6bf` (dejar de reportar "alerta enviada"
cuando el correo fue simulado). Lo que **no** se hizo, a propósito: reenviar los 538 históricos.
Es una decisión (muchos son de septiembre y el mensaje ya no aplica), y por eso B6 queda en 🟡.

**B7 (liderazgo).** El arreglo es anterior a esta auditoría: `65c1910` (2026-10-11) commitea al
tomar el lock, verifica contra `pg_locks` (`pg_try_advisory_lock` es re-entrante en la misma
sesión y mentiría) y agrega el latido `job_vigilar_liderazgo` cada 5 min con relevo automático.
La medición de §2.6 (121 pérdidas en 48 h ≈ una cada 24 min) es exactamente la firma de
`idle_in_transaction_session_timeout = 5 min` matando la sesión del líder: lo que falta no es
código, es **evidencia con el arreglo desplegado** — buscar en el log de PROD las 24 h posteriores
al deploy, confirmar que no vuelve a aparecer la pérdida del lock y que
`sincronizar_liderazgo()` devuelve `lider_ok`. Riesgo residual: el latido corre en el mismo
período que el timeout, así que una pérdida justo en el borde depende del catch-up del job.

## D.4 B3, B5, B8, B9 — lo que necesito que decidas

**1) B3 · primer backup real y drill de restauración.** El código está; nadie lo corrió. Alcance
mínimo propuesto: (a) sincronizar el blueprint y disparar `proyecto-crossfit` una vez con
`DRY_RUN=0` en `backups-prod`, comprobando objeto + tamaño en R2; (b) correr
`box-crossfit-restore-drill` **una vez** (crea una rama Neon desechable, restaura ahí y la borra
al terminar: no toca PROD) y leer el reporte; (c) recién ahí decidir si el backup local de
`/app/backups` sigue teniendo sentido o queda sólo R2. Pregunta: **¿autorizás (a) y (b) en el
próximo deploy, o querés que el drill espere?** (el drill consume horas de cómputo de Neon y crea
una rama temporal).

**2) B5 · ramas Neon.** Hay 4 ramas, 4 configuraciones y una (`ep-summer-river`, sa-east-1, la del
contenedor `box-crossfit-maintenance-1`) con la credencial revocada. Pregunta: **¿cuál rama es la
TEST oficial — `crimson-tooth`, la que declara el `.env.test`, o `lingering-fog`, la que usa el
backend local en ejecución?** Con eso: se borra `summer-river`, se alinean `docker-compose` y el
`.env.test`, y se documenta el inventario. No borro ninguna rama sin ese OK.

**3) B8 · retención.** Lo que ya existe en `mantenimiento_cloud` (pasos 10 y 11): tokens de reset
vencidos/usados, `notificaciones_enviadas` > 180 d y bandeja in-app > 365 d. Eso corre **sólo en
PROD** y probablemente nunca corrió: los 2 tokens expirados del 2026-09-26 siguen ahí, lo que es
consistente con que el Cron Job de mantenimiento todavía no exista (D.2 lo crea). Lo que falta es
la política para lo que no es bandeja: `reservas` (23.495 filas), `asistencias` (24.752),
`auditoria` (68) y los 46 usuarios en `baja` (datos personales de ex-alumnos, sin anonimizar).
Propuesta a decidir: **plazo de archivo de `reservas`/`asistencias` (3 / 5 / 7 años), TTL de
`auditoria` (2 años) y anonimización de `usuarios` en `baja` a los 12 meses** (se conserva el `id`
y las FKs; se vacían nombre, email y teléfono). Son migración + pasos nuevos del job + tests, así
que necesito los plazos antes de escribir nada.

**4) B9 · n8n.** Hallazgo nuevo de esta tanda: `n8n/workflows/` está **vacío** desde `017bd65`
(2026-10-02) —el README seguía afirmando "7 de los 18 versionados" y que
`fidelizacion_y_retencion_prod.json` estaba en el repo— y en ese mismo commit se eliminó
`POST /api/v1/asistencia/n8n/evaluar-mes`, que ahora hace el job `cierre_mes` del scheduler
interno. Es decir: **si `fidelizacion y retencion` sigue activo en la instancia de PROD, el día 1
recibe 404 y no manda ningún correo de cumplimiento/hito**. Ya quedaron corregidos el README de
`n8n/` (aviso al principio + las 2 afirmaciones falsas) y el comentario de `N8N_API_KEY` en
`app/core/config.py`. Pregunta: **¿exportamos y apagamos ese workflow, o lo repuntamos a un
endpoint que ya no existe?** Opciones reales: (a) exportar los 18 con
`n8n export:workflow --all`, sanearlos y versionarlos; (b) apagar en la UI los que ya tienen
reemplazo (los 4 de KPIs/ML y `fidelizacion y retencion`) y exportar sólo los de alertas; (c) las
dos cosas. La instancia de n8n de este equipo está `Exited` hace 3 semanas, así que el export
sale de la instancia externa y requiere tus credenciales.
