# PROPUESTA — Clasificación de nivel de atleta

> **Estado:** propuesta de diseño. **No se implementó código**: este archivo es el único
> artefacto nuevo de esta sesión (más el commit del trabajo de mantenimiento que ya estaba
> pendiente en el árbol).
> **Base:** `main` @ `a246538` (2026-10-27), Alembic head `059_reserva_suscripcion_id`.
> **Origen:** es la entrega pendiente de la sesión `1793115939333_ot7no`, que se cortó justo
> antes de escribir este documento. Todos los números se **volvieron a medir** contra PROD el
> 27/10/2026 con `SELECT` de solo lectura sobre `DIRECT_URL` (no se escribió ni una fila).

## Qué decide este documento

1. **Confianza mínima** para publicar un nivel (hoy un alumno con 2 marcas y cero gimnasia
   sale “Elite”).
2. **Perfil obligatorio**: qué hacer con 404 de 410 alumnos sin peso+género.
3. **Nivel persistido**: si el nivel debe vivir en una columna o seguir calculándose en vivo.
4. **Gimnasia**: `peso_kg` vs `repeticiones` (hoy el nivel gimnástico se ordena por una
   columna que no es la que se mide).
5. **Movimientos faltantes**: los 3 movimientos con datos que hoy se descartan, los que no
   matchean por nombre, y los 24 estándares que conviene agregar, con valores propuestos por
   nivel.
6. **`student_segments`**: qué hacer con la tabla de nivel que nunca se usó.

Cada sección cierra con **opciones + recomendación + esfuerzo**, no con una implementación.
Al final hay un checklist de decisiones que necesito de vos y un anexo con el **FIX 4**
(ejecutado en PROD el 2026-10-28, Anexo A.4).

---

## Resumen ejecutivo

- **El nivel existe, pero casi nadie lo tiene.** De 410 alumnos reales, **2 (0,5 %)** muestran
  badge: el alumno demo (`id 5`, Intermedio/Intermedio) y una alumna real (`id 9`, Elite/Sin
  datos). Los otros 408 salen “Sin datos”.
- **El caso que rompe la regla:** la alumna 9 tiene **solo fuerza** (Clean 100 kg, Snatch 85 kg,
  Hang Clean 80 kg), gimnasia **sin una sola marca**, y aun así el panel la publica como
  **“Elite”**. El badge global se arma con el mínimo de los ejes *presentes*
  (`frontend/src/utils/niveles.js:25-30`), y un eje ausente no cuenta como evidencia faltante.
- **No hay datos para clasificar:** toda la base tiene **19 filas** de RM, de **2 alumnos**:
  16 del alumno demo (8–11 jul 2026) y **3 de la única alumna real** (27 sep–19 oct 2026).
  No se creó ninguna RM en los últimos 7 días.
- **El 47 % de esas filas no podría clasificar nunca** (9 de 19 son cardio/metabólico, y está
  bien). Pero **3 de las 10 filas de fuerza/gimnasia se pierden por falta de estándar**
  (`Hang Clean`, `Strict Pull-up`, `Kipping Pull-up`): 30 % del dato útil.
- **El bloqueo de perfil es futuro, no pasado:** 404/410 alumnos no tienen peso+género
  (300 tienen peso sin género, **0** género sin peso, 104 ninguno), pero **ninguno de esos 404
  tiene una sola RM**. El muro aparece en su primera RM, no en el histórico. 256 de esos 404
  tienen suscripción activa hoy.
- **El catálogo tiene 103 movimientos y solo 26 tienen estándar** (8/42 fuerza, 18/49
  gimnasia). De los 77 sin estándar, **24 son deuda real** (§5) y el resto son accesorios o
  movimientos de peso fijo que no deberían clasificar por diseño.
- **`student_segments` está muerta y no es una opción:** 6 filas, todas `BASICO`, 0 lectores,
  0 escritores, 0 FKs, 0 vistas. La propia migración `026` documenta que tiene otra semántica.

---

## Índice

0. [Evidencia medida](#0-evidencia-medida)
1. [Confianza mínima para publicar nivel](#1-confianza-mínima-para-publicar-nivel)
2. [Perfil obligatorio (peso y género)](#2-perfil-obligatorio-peso-y-género)
3. [Nivel persistido o calculado en vivo](#3-nivel-persistido-o-calculado-en-vivo)
4. [Gimnasia: repeticiones vs `peso_kg`](#4-gimnasia-repeticiones-vs-peso_kg)
5. [Movimientos y estándares faltantes](#5-movimientos-y-estándares-faltantes)
6. [`student_segments`: qué hacer](#6-student_segments-qué-hacer)
7. [Roadmap, esfuerzo y tests](#7-roadmap-esfuerzo-y-tests)
8. [Decisiones pendientes](#8-decisiones-pendientes-para-el-dueño-del-producto)
- [Anexo A — FIX 4 (PROD, carga k6): ejecutado](#anexo-a--fix-4-prod-carga-k6-ejecutado-el-2026-10-28-ver-a4)
- [Anexo B — Metodología](#anexo-b--metodología-y-límites-de-las-mediciones)

---

## 0. Evidencia medida

Todo lo de esta sección es **medición**, no propuesta. Universo: `tenant_id = 1`,
`rol = 'alumno'`. Los 95 usuarios de carga (`correo LIKE 'carga_k6_%'`) se separan porque
contaminan el universo (ver Anexo A).

### 0.1 Cobertura de perfil

| Segmento | n | % de 410 |
|---|---:|---:|
| Alumnos totales (tenant 1) | 505 | — |
| Usuarios de carga `carga_k6_%` | 95 | — |
| **Alumnos reales** | **410** | 100 % |
| Perfil completo (peso **y** género) | **6** | 1,5 % |
| Solo peso (sin género) | **300** | 73,2 % |
| Solo género (sin peso) | **0** | 0,0 % |
| Sin peso ni género | **104** | 25,4 % |
| **Incompletos para clasificar fuerza** | **404** | **98,5 %** |
| Incompletos **con suscripción activa** | 256 | 62,4 % de los incompletos |
| Incompletos **con alguna RM** | **0** | 0,0 % |

Lectura: el hueco es **género**, no peso. 300 alumnos ya pesan pero no tienen género, y el
formulario no lo pide (`RegistroAlumnoNuevo.jsx:108-117`) ni el alumno lo puede editar
(`Ajustes.jsx:185`, `genero` deshabilitado). Que **0** de los 404 tenga RMs significa que hoy
no hay ningún nivel mal calculado por este motivo: el problema es que **la primera RM de 256
alumnos activos va a caer en “Sin datos”**.

### 0.2 Las 19 filas de RM (toda la base)

| id | Movimiento | Categoría | Filas | Con `repeticiones` | Rango kg | ¿Tiene estándar? |
|---:|---|---|---:|---:|---|---|
| 2824 | Clean (Cargada) | fuerza | 4 | 2 | 100–160 | sí |
| 2823 | Snatch (Arrancada) | fuerza | 2 | 2 | 85–100 | sí |
| 2830 | Hang Clean | fuerza | 1 | 1 | 80 | **no** |
| 2866 | Strict Pull-up | gimnastico | 1 | 0 | 15 | **no** |
| 2867 | Kipping Pull-up | gimnastico | 1 | 1 | 1 | **no** |
| 2870 | Chest to Bar (C2B) | gimnastico | 1 | 1 | 10 | sí |
| 2918 | Sled Push | cardio | 3 | 0 | 1 | no (por diseño) |
| 2917 | Air Runner | metabolico | 6 | 0 | 1–530 | no (por diseño) |
| | **Total** | | **19** | **7** | | **10 usables / 3 perdidas** |

Dueños de las filas: **16** del alumno demo `id 5` (`alumno@urbantraining.cl`, 2026-07-08 a
07-11) y **3** de la alumna real `id 9` (`jesussport2022@gmail.com`, 2026-09-27 a 10-19).
Es decir: **el nivel de PROD se sostiene con 1 usuario de demo y 1 alumna**.

De las 10 filas de fuerza/gimnasia, **7 clasifican y 3 se descartan** por no tener estándar
(Hang Clean, Strict Pull-up, Kipping Pull-up). Las otras 9 (Sled Push 3 + Air Runner 6) son
cardio/metabólico: no deben clasificar y el motor hace bien en ignorarlas.

### 0.3 Niveles de los 6 alumnos con perfil completo

| id | Alumno | Peso | Gén. | Filas RM | Nivel fuerza | Nivel gimnasia | Badge global hoy |
|---:|---|---:|---|---:|---|---|---|
| 2 | Carlos Pérez | 75 | M | 0 | Sin datos | Sin datos | — |
| 5 | Alumno Demo | 105 | M | 16 | Intermedio | Intermedio | **Intermedio** |
| 9 | fanny carrasco | 75 | F | 3 | **Elite** | Sin datos | **Elite** |
| 533 | Yerko Wladimir Pizarro Pino | 110 | M | 0 | Sin datos | Sin datos | — |
| 534 | Antonia Miranda | 80 | F | 0 | Sin datos | Sin datos | — |
| 535 | Ángel Gabriel Campos Cabezas | 90 | M | 0 | Sin datos | Sin datos | — |

Dos hechos que importan:

- **“Perfil completo” ≠ “clasificable”**: 4 de los 6 completos no tienen ni una RM.
- **Un solo eje produce badge global**: el mínimo se calcula sobre los ejes presentes
  (`niveles.js:25-30`), así que la alumna 9 (fuerza Elite, gimnasia vacía) se publica como
  Elite. Es el 50 % de los alumnos clasificados.

### 0.4 Catálogo de movimientos vs estándares

| Categoría | Movimientos | Con estándar | Sin estándar |
|---|---:|---:|---:|
| fuerza | 42 | 8 | 34 |
| gimnastico | 49 | 18 | 31 |
| cardio | 9 | 0 | 9 |
| metabolico | 3 | 0 | 3 |
| **Total** | **103** | **26 (25 %)** | **77** |

No los 77 son deuda: ver §5.2–5.3, donde se separan accesorios y peso fijo (no deben clasificar)
de los 24 estándares que sí conviene agregar.

**Seis nombres del catálogo no matchean** con las claves de las tablas (el match es por
string exacto, `nivel_service.py:176` y `:198`):

| Movimiento en BD | Clave en el código | Efecto |
|---|---|---|
| `Split Jerk` (2849) y `Push Jerk` (2848) | `Jerk (Envión)` | la clave no existe en BD: 0 matches |
| `Rope Climb (Trepada)` (2883) | `Rope Climb (Subida de cuerda usando los pies)` | nunca matchea |
| `Bear Crawl (Caminata)` (2911) | `Bear Crawl (Caminata de oso)` | nunca matchea |
| `Chest to Bar (C2B)` (2869 y 2870) | `Chest to Bar (C2B)` | duplicado: solo 2870 tiene datos |
| `Handstand Push-ups / HSPU (...)` (2874 y 2875) | misma clave | duplicado: ninguna tiene datos |

### 0.5 `student_segments`

| Comprobación | Resultado |
|---|---|
| Filas | 6 (tenant 1), todas `BASICO` |
| Filas huérfanas (alumno inexistente) | 0 |
| Escritores en el código | 0 (última escritura 2026-09-12 21:27, del seed) |
| Lectores (endpoints/servicios/front) | 0 |
| FKs que la referencian | 0 |
| Vistas / funciones / triggers | 0 |
| DDL | `backend/alembic/versions/021_data_marts_bi.py:124` |
| Nota de la migración siguiente | `026_segmentacion_alumnos.py:10-14`: “tiene OTRA semántica: nivel de ATLETA … es progreso deportivo” |

---

## 1. Confianza mínima para publicar nivel

### 1.1 Cómo funciona hoy

- Por eje, el nivel es el **mínimo** de los movimientos clasificables: `nivel_desde_mejores`
  (`nivel_service.py:152-221`), líneas 188-191 (fuerza) y 206-209 (gimnasia).
- Si un eje no tiene marcas, devuelve el string `"Sin datos"` (líneas 217-218).
- El **badge global lo arma el frontend** con el mínimo de los ejes que sean un nivel real;
  los `"Sin datos"` se filtran y no cuentan (`niveles.js:25-30`).
- No hay mínimo de muestra: **una** marca publica el eje, **un** eje publica el badge.

Consecuencia medida: la alumna 9 tiene 2 movimientos de fuerza y 0 de gimnasia → **Elite**
global. El alumno 5 tiene 2 de fuerza y 1 de gimnasia → **Intermedio**. Los dos únicos badges
de PROD son, respectivamente, un dato incompleto y un dato con n=1 en un eje.

### 1.2 Opciones

| | Regla | Badges hoy | Pros | Contras |
|---|---|---:|---|---|
| **A** | Estado actual: mínimo de los ejes presentes, sin mínimo de muestra | 2/410 | nada que cambiar | publica “Elite” con 2 marcas y 0 gimnasia; no distingue evidencia de ausencia |
| **B** | Badge global **solo con ambos ejes** (≥1 marca por eje). Eje suelto se muestra como “Parcial” | 1/410 | honesto; conserva el mínimo (no infla); el coach ve el eje que falta | 1 badge menos; requiere un tercer estado en la UI |
| **C** | B + **≥2 marcas por eje** para publicar el eje | 0/410 | máxima confiabilidad | hoy no publica nada; el feature queda invisible hasta que crezca la adopción |
| **D** | Cambiar el mínimo por mediana / “segunda mejor” | 2/410 | menos castigo a un accesorio flojo | con n=2 la mediana es el máximo: **infla el eje** (la fuerza del alumno 5 pasaría de Intermedio a Avanzado) |

**Recomendación: B ahora, con los umbrales en configuración para llegar a C sin tocar código.**

- `NIVEL_MIN_MOVS_EJE` (default `1`, objetivo `2` cuando haya ≥50 alumnos con RM).
- `NIVEL_MIN_EJES` (default `2`; `1` reproduce el comportamiento actual si el box lo prefiere).
- El endpoint devuelve, por eje, `nivel`, `movs` (cuántos clasificaron) y
  `confianza`: `alta` (≥2 y ambos ejes), `media` (≥1 y ambos ejes), `baja` (un solo eje o n=1).
- La UI muestra el badge global **solo** si `nivel_atleta != null`; si no, dos chips por eje y
  un texto explícito: *“Fuerza: Elite · gimnasia: sin datos”*. Nunca un nivel global inventado.

**Por qué no D todavía:** con 2 marcas, cualquier estadístico robusto degenera en el máximo.
El mínimo es la regla correcta para muestras chicas; cuando un eje tenga ≥3 marcas, se puede
pasar a “mínimo de las 2 mejores” sin cambiar el contrato (solo la función pura y sus tests).

**Esfuerzo:** 4–6 h (función pura + respuesta del endpoint + badge/estado “Parcial” + 2 tests
nuevos). No requiere migración si no se persiste (§3).

---

## 2. Perfil obligatorio (peso y género)

### 2.1 Por qué falta

| Punto de entrada | Código | Hoy |
|---|---|---|
| Alta de alumno (coach/admin) | `alumnos.py:132-141` (`RegistroAlumnoNuevo`) | `sexo` y `peso` son `Optional` |
| Formulario de alta | `RegistroAlumnoNuevo.jsx:108-117` | `select`/`input` **sin** `required` |
| Ajustes del alumno | `Ajustes.jsx:185` | `genero` deshabilitado |
| `PUT /alumnos/me` | `alumnos.py:78` (`CAMPOS_AUTOEDITABLES`) | solo `telefono`, `peso_kg`, `estatura_cm`; `genero` está en `CAMPOS_SOLO_BOX` (línea 81) |
| `PUT /usuarios/{id}` (admin) | CRUD admin | sí puede editar `genero`, pero nadie lo hizo en 404 casos |

Dato duro: **300 alumnos tienen peso y les falta género; 104 no tienen ninguno; 0 tienen
género sin peso**. El problema no es que el alumno no quiera dar el dato: es que **no se lo
piden y no lo puede corregir**.

### 2.2 Segundo problema: sin género se usan estándares masculinos

`obtener_nivel_gimnastico` hace `niveles = tabla["M"]` cuando `genero` no es `M`/`F`
(`nivel_service.py:82-90`). O sea: una alumna sin género se clasifica con la tabla masculina
(y queda subvalorada, porque los umbrales M son más altos). Peor: `genero='otro'` también cae
en M. En fuerza no pasa porque `tiene_fuerza` exige peso+género (`nivel_service.py:173`).

Recomendación transversal: **sin género no se clasifica gimnasia** (devolver
`clasificable: False`), en vez de asumir M. Es un cambio de 3 líneas + tests, y evita el
“sesgo silencioso” que hoy no se ve porque los 2 alumnos con RM tienen género.

### 2.3 Opciones para cerrar el hueco

| | Estrategia | Alcance | Esfuerzo | Riesgo |
|---|---|---|---:|---|
| **1** | **Bloquear** el alta pública: `sexo` y `peso` requeridos (Pydantic + `required` en UI) | solo altas nuevas | 4–6 h | abandono en el registro; **no arregla los 404** |
| **2** | **No bloquear + completar**: banner persistente “Completa tu perfil para ver tu nivel”, CTA a Ajustes, y **habilitar `genero` como autogestionable** (una vez, auditado) | 300 con peso + 104 sin nada | 1–1,5 d | datos de identidad autogestionados: requiere regla y auditoría |
| **3** | **Backfill por el box**: lista de incompletos en el panel del coach/admin y edición desde la ficha (`PUT /usuarios/{id}` ya existe) | 404 registros (256 activos) | 2–3 d de UI + operación | 404 ediciones manuales; sin UI de lista es inviable |

**Recomendación: 2 + 3, y 1 solo para el alta que hace el coach (no para el landing público).**

- **Fase 2a (código, 4 h):** `genero` entra a `CAMPOS_AUTOEDITABLES` con dos guardas:
  solo valores `M`/`F`, y solo si el campo está vacío (una corrección, no un cambio libre).
  Cada cambio queda en `auditoria` con valor anterior/nuevo. `Ajustes.jsx` deja de estar
  `disabled` cuando `genero` es `null`.
- **Fase 2b (código, 4 h):** `perfil_completo` (bool derivado, no columna) en la respuesta de
  los listados de alumnos + chip “Perfil incompleto” y filtro en el panel. Es el mismo patrón
  que ya usa `nivelDeAtleta` en el front: el backend manda el estado, el front no lo adivina.
- **Fase 3 (operación, no código):** el box prioriza a los **256 activos**; los 148 restantes
  se completan cuando vuelvan. No hace falta tocar los 404 de una vez.
- **Fase 1 acotada:** en el alta del coach, `sexo`/`peso` pasan a requeridos. En el landing
  público se mantienen opcionales pero con un paso posterior obligatorio (banner), para no
  matar la conversión.

**Por qué no bloquear el landing:** el registro público ya crea la suscripción “Prueba” y el
alumno entra de inmediato (`alumnos.py:154-255`): el usuario nace `activo=true` con contraseña
temporal (`:212-228`) y la suscripción nace `activo` con `fecha_inicio` explícita (`:245-255`).
Agregar dos campos obligatorios ahí cambia la conversión sin resolver el 98,5 % que ya está dentro.

**KPI de cierre:** `% de alumnos con peso+género` (hoy: 6/410 = 1,5 %). El subconjunto que
importa primero son los **256 incompletos con suscripción activa**: son los que van a chocar
con el muro en su próxima RM. Objetivo sugerido: 80 % de los activos en 60 días.

---

## 3. Nivel persistido o calculado en vivo

### 3.1 Estado actual

- No existe columna de nivel: `usuarios` solo tiene `peso_kg`, `estatura_cm`, `genero`
  (`models/usuario.py:45-47`).
- El nivel se calcula en cada request con `calcular_nivel_general` /
  `calcular_niveles_lote` (`nivel_service.py:268` y `:276`), que hacen **2 consultas**:
  perfil (`_peso_y_genero`, línea 224) y mejores RMs (`_mejores_rms_lote`, línea 236).
- El coach filtra **en el cliente** con `nivelDeAtleta` (`niveles.js:25-31`) y
  `pasaFiltroNivel` (línea 44); no hay filtro SQL ni orden por nivel.
- `historial_rm.nivel_calculado` (`models/historial_rm.py:44`) es un **snapshot del POST** que
  nadie lee: el cálculo en vivo lo ignora y recalcula con el peso actual. Desde `a246538` el
  PUT ya no permite escribirlo (asignación masiva cerrada), pero sigue siendo una **segunda
  verdad** con otra regla (se congela con el peso de ese día).

### 3.2 ¿Hace falta persistir?

| | Qué implica | Cuándo conviene |
|---|---|---|
| **A. No persistir** | se mantiene el cálculo en vivo; el filtro sigue en el front | 410 alumnos: 2 queries por carga de página, costo despreciable; cero staleness |
| **B. Persistir en `usuarios`** | columnas + recálculo en cada escritura + backfill | cuando se necesite **filtrar/ordenar en SQL**, notificar por nivel, guardar histórico o superar ~1–2 k alumnos |
| **C. Reusar `student_segments`** | — | **descartado**: otra semántica, 6 filas muertas, sin FKs (§6) |

**Recomendación:** **A hoy, B cuando se cumpla un disparador concreto.** El problema actual no
es el costo de cálculo (2 alumnos con RM): es que **no hay datos**. Persistir el nivel de 408
alumnos en “Sin datos” no agrega información, agrega una tabla que se puede desincronizar.
Disparadores para pasar a B, en orden:

1. el coach necesita **filtrar por nivel en el backend** (hoy puede con 410 en el cliente);
2. se quiere **notificar** (“subiste a Intermedio”) o **histórico** de nivel;
3. la página del coach supera ~1–2 k alumnos y el cálculo en vivo deja de ser gratis.

### 3.3 Diseño si se decide B (para tenerlo listo)

Migración `060_nivel_atleta_persistido.py`, `down_revision = "059_reserva_suscripcion_id"`
(único head hoy, verificado sobre las 59 revisiones):

```sql
ALTER TABLE usuarios
    ADD COLUMN nivel_fuerza        varchar(20),
    ADD COLUMN nivel_gimnastico    varchar(20),
    ADD COLUMN nivel_atleta        varchar(20),
    ADD COLUMN nivel_movs_fuerza   smallint,
    ADD COLUMN nivel_movs_gimnasia smallint,
    ADD COLUMN nivel_confianza     varchar(10),
    ADD COLUMN nivel_calculado_en  timestamptz,
    ADD COLUMN nivel_version       varchar(10);

CREATE INDEX ix_usuarios_tenant_nivel ON usuarios (tenant_id, nivel_atleta);
```

- **Sin `CHECK` de valores**: mismo criterio que `ml_modelos.TIPOS_MODELO` y que documenta
  `026` (“la escalera puede crecer sin migración”). La validación vive en Python
  (`nivel_service.NIVELES`).
- **Una sola función de recálculo**: `recalcular_nivel(db, alumno_id, tenant_id)` que llama a
  `nivel_desde_mejores` (la misma función pura del cálculo en vivo). Nunca cálculo
  incremental: se releen las mejores RMs y el perfil actual.
- **Disparadores de recálculo** (los 4 caminos que cambian el resultado):
  1. `POST /historial-rm` (hoy ya calcula, pero solo para el snapshot),
  2. `PUT /historial-rm/{id}` y `DELETE /historial-rm/{id}` (**hoy no recalculan nada**),
  3. `PUT /alumnos/me` y `PUT /usuarios/{id}` cuando cambian `peso_kg` o `genero`,
  4. job nocturno idempotente en `backend/maintenance` (recalcula solo filas con
     `nivel_calculado_en < now() - interval '1 day'`), y script de backfill por lotes de 500
     que **importa `nivel_service`** (no replica ratios en SQL).
- **Anti-staleness:** el endpoint devuelve `nivel_calculado_en` y `nivel_version`; si la fila
  tiene más de 24 h, recalcula al leer (auto-sanación) y actualiza. Así una migración de
  ratios o un job caído no dejan el panel mintiendo para siempre.
- **`historial_rm.nivel_calculado`:** eliminarlo en la misma migración (o en la siguiente).
  Es un snapshot que nadie lee y con regla distinta; mantenerlo garantiza que alguien lo lea
  algún día y compare dos números que no significan lo mismo.
- **Compatibilidad:** durante la transición, los endpoints siguen devolviendo el valor en vivo
  y además el persistido; se comparan en un test de integración antes de que el front lea el
  persistido.

**Esfuerzo:** 2,5–3 d (migración 0,5; servicio + hooks 1; job + backfill 0,5; tests 0,5;
front 0,5). **Riesgo principal:** staleness → mitigado con recálculo al leer y `nivel_version`.

---

## 4. Gimnasia: repeticiones vs `peso_kg`

### 4.1 El problema

La columna donde vive el valor del nivel gimnástico es `peso_kg`, y no debería:

| Pieza | Código | Qué hace |
|---|---|---|
| Modelo | `models/historial_rm.py:30` | `peso_kg = Column(Float, nullable=False)` — obliga a mandar un peso incluso en gimnasia |
| Schema POST | `schemas/historial_rm.py:13` | `peso_kg: float = Field(..., gt=0)` — requerido |
| POST | `historial_rm.py:181` | `valor_para_nivel = repeticiones or peso_kg` (toma reps si vienen) |
| Cálculo en vivo | `nivel_service.py:156-158` | `max(peso_kg)` por movimiento, **también en gimnasia** |
| Mejores RMs | `rms_service.py:150-156` | `DISTINCT ON` ordenado por `peso_kg.desc()` (línea 154) para fuerza **y** gimnasia |
| Presentación | `rms_service.py:73` | muestra reps, con fallback a `peso_kg` |
| Front (según RM-01) | formulario de RM | manda `peso_kg = 1` como dummy en gimnasia |

Mientras el formulario mande `repeticiones == peso_kg`, el `max(peso_kg)` “funciona de
casualidad”. En PROD se ve el patrón: C2B `reps=10, peso=10`; Strict `reps=NULL, peso=15`;
Kipping `reps=1, peso=1`. En cuanto la UI mande `reps=8` con `peso=1` (lo correcto), el
`max(peso_kg)` va a elegir el registro con el dummy más alto, no el mejor set.

### 4.2 Opciones

| | Estrategia | Pros | Contras |
|---|---|---|---|
| **A** | `repeticiones` canónica y `peso_kg` **nullable** en gimnasia | un solo valor por registro; el orden usa la columna correcta | toca modelo, schemas, POST/PUT, `rms_service`, `nivel_service` y front; migración de datos |
| **B** | Mantener `NOT NULL` + forzar `repeticiones == peso_kg` en gimnasia (validator/trigger) | cambio chico; no rompe tipos | sigue habiendo dos columnas para un dato; el dummy sigue vivo |
| **C** | Columna nueva `valor_nivel numeric` calculada por categoría | explícito y único | cambia el contrato de la API y duplica datos otra vez |

**Recomendación: A, en dos fases, con B como red de seguridad temporal.**

**Fase 1 — migración `061_rm_gimnasia_reps.py` (0,5 d)**

```sql
ALTER TABLE historial_rm ALTER COLUMN peso_kg DROP NOT NULL;

UPDATE historial_rm h
SET repeticiones = round(h.peso_kg)::int
FROM movimientos m
WHERE m.id = h.movimiento_id
  AND m.categoria = 'gimnastico'
  AND (h.repeticiones IS NULL OR h.repeticiones = 0)
  AND h.peso_kg IS NOT NULL;

-- No se pone peso_kg en NULL todavía: la UI vieja sigue leyéndolo.
```

Idempotente (el `WHERE` excluye lo ya migrado). `downgrade()`: `UPDATE ... SET peso_kg =
COALESCE(peso_kg, repeticiones, 1)` y volver a `SET NOT NULL` (no se pierde nada: el valor
canónico queda en `repeticiones`).

**Fase 2 — código (1–1,5 d)**

- Modelo: `models/historial_rm.py:30` → `nullable=True` (el `DROP NOT NULL` de la Fase 1 es el
  cambio real; el mapeo tiene que acompañarlo para que ninguna migración autogenerada lo vuelva
  a declarar obligatorio).
- `nivel_service._mejores_rms_lote`: seleccionar
  `CASE WHEN m.categoria = 'gimnastico' THEN COALESCE(h.repeticiones, h.peso_kg::int) ELSE h.peso_kg END`
  y ordenar por ese valor (hoy es `func.max(HistorialRM.peso_kg)`, `nivel_service.py:236-265`).
- `rms_service`: mismo `CASE` en el `DISTINCT ON` para gimnasia (`rms_service.py:150-156`);
  `_unidad_y_valor` deja el fallback solo para filas viejas.
- Schema: `peso_kg: Optional[float]` + `model_validator` por categoría:
  fuerza exige `peso_kg`; gimnasia exige `repeticiones`; cardio/metabólico exige uno de
  `minutos|km|vueltas|calorias`. Rechazar `peso_kg` en gimnasia con 422 (evita el dummy).
- Schemas de **respuesta**: `HistorialRMResponse` hereda de `HistorialRMBase`, así que basta el
  cambio de arriba, pero `HistorialRMListItem.peso_kg` (`schemas/historial_rm.py:73`) y
  `RMPorMovimiento.peso_kg` (`:107`) lo declaran `float` obligatorio: sin tocarlos, la Fase 3
  (filas con `peso_kg = NULL`) responde 500 en el listado y en “RM por movimiento”.
- Front: el formulario deja de mandar `peso_kg = 1`; muestra “reps” para gimnasia.
- Datos existentes: la única fila de gimnasia con `peso_kg` real es C2B (coincide con reps);
  Strict ya tiene `peso=15` y `reps=NULL` → el backfill la corrige a 15 reps.

**Fase 3 — opcional (0,5 d):** poner `peso_kg = NULL` en las filas de gimnasia y borrar el
fallback. Se puede dejar para cuando no queden clientes viejos.

**Tests que lo fijan** (siguiendo el estilo de `test_rm_categoria_contrato.py`, sin DB):
`test_historial_rm_gimnasia_reps.py` con dos filas del mismo movimiento donde `reps` y
`peso_kg` discrepan (8/1 y 20/100): el mejor debe ser 20. Y un test puro de
`nivel_service` que pruebe que el nivel sale de 20, no de 100.

---

## 5. Movimientos y estándares faltantes

### 5.1 Diagnóstico

El motor reconoce un movimiento **solo si el string es exactamente igual** a la clave de
`CROSSFIT_RATIOS` o `CROSSFIT_HABILIDADES` (`nivel_service.py:176` y `:198`). El catálogo de
BD tiene 103 movimientos; 26 tienen estándar. Pero el problema no es solo cuántos faltan:
**hay estándares que existen y no matchean** (§0.4) y **movimientos con datos que se
descartan** (Hang Clean, Strict Pull-up, Kipping Pull-up = 3 de las 10 filas útiles).

Prioridad real, medida por datos en PROD:

| Prioridad | Movimientos | Filas en PROD | Por qué |
|---|---|---:|---|
| **P0 — alias** | `Split Jerk` (2849), `Push Jerk` (2848), `Rope Climb (Trepada)` (2883), `Bear Crawl (Caminata)` (2911) | 0 (hoy) | el estándar existe pero nunca matchea; es la deuda más barata |
| **P1 — datos ya existentes** | `Hang Clean` (2830), `Strict Pull-up` (2866), `Kipping Pull-up` (2867) | **3** | hoy se descartan (1 de fuerza, 2 de gimnasia) |
| **P2 — programación habitual** | Power Clean/Snatch, Hang Snatch, Push Press, Shoulder Press, Butterfly, Chin-up, Dips, Ring Dips, Knees to Elbows, Wall Walk, Handstand Hold, GHD Sit-up | 0 | son los que el box programa y hoy no puntúan |
| **P3 — accesorios / variantes** | Bench Press, Sumo/RDL/Deficit/Trap Bar, L-sit, Triple Under | 0 | valor bajo para nivel; no bloquean nada |
| **Excluidos por diseño** | Wall Ball, KB Swing, Med Ball Clean, Goblet/Air/Bulgarian/Box Squat, Muscle Snatch/Clean, rows, DB press, Good Morning, etc. + los 12 cardio/metabólico | 9 (Sled/Air Runner) | no son 1RM o son peso fijo: `crossfit_ratios.py:12-14` los excluye explícitamente |

Recuento explícito: **24 tablas nuevas** (12 de fuerza + 12 de gimnasia) y **6 alias de nombre**
(`Split Jerk`, `Squat Clean`, `Squat Snatch`, `Rope Climb`, `Bear Crawl`, `Pull-ups` 2865 →
Kipping). Los alias no crean tabla: resuelven a una clave existente (§5.4).

### 5.2 Estándares de fuerza propuestos

Método: aplicar las **mismas reglas de extrapolación que ya declara el archivo**
(`crossfit_ratios.py:9-10`: Snatch ≈ 75 % del Clean, Jerk ≈ 90 % del Clean, OHS ≈ 65 % del
Front Squat). No son percentiles medidos: son derivaciones de las tablas existentes, para
calibrar con el coach antes de escribirlas.

| id | Movimiento | Regla | M: P / I / A / E | F: P / I / A / E |
|---:|---|---|---|---|
| 2830 | **Hang Clean** | 90 % del Clean | 0,45 / 0,90 / 1,15 / 1,50 | 0,35 / 0,70 / 0,90 / 1,15 |
| 2826 | **Power Clean** | 80 % del Clean | 0,40 / 0,80 / 1,05 / 1,35 | 0,32 / 0,64 / 0,80 / 1,05 |
| 2825 | **Power Snatch** | 80 % del Snatch | 0,32 / 0,64 / 0,80 / 1,05 | 0,24 / 0,48 / 0,64 / 0,80 |
| 2829 | **Hang Snatch** | 90 % del Snatch | 0,35 / 0,70 / 0,90 / 1,15 | 0,27 / 0,54 / 0,72 / 0,90 |
| 2849 | **Split Jerk** | = Jerk (renombrar clave) | 0,50 / 0,90 / 1,20 / 1,50 | 0,40 / 0,70 / 0,90 / 1,20 |
| 2848 | **Push Jerk** | 90 % del Split Jerk | 0,45 / 0,81 / 1,08 / 1,35 | 0,36 / 0,63 / 0,81 / 1,08 |
| 2847 | **Push Press** | 80 % del Split Jerk | 0,40 / 0,72 / 0,96 / 1,20 | 0,32 / 0,56 / 0,72 / 0,96 |
| 2850 | **Shoulder Press** | strengthlevel / Rippetoe, a calibrar | 0,40 / 0,65 / 0,85 / 1,05 | 0,25 / 0,45 / 0,60 / 0,75 |
| 2846 | Bench Press (P3) | strengthlevel | 0,75 / 1,00 / 1,25 / 1,50 | 0,45 / 0,60 / 0,80 / 0,95 |

- **`Squat Clean` (2827) y `Squat Snatch` (2828) no llevan tabla nueva**: son el Clean y el
  Snatch completos. Van como **alias** de 2824/2823, no como estándares distintos (si se
  duplican, el mismo atleta puede salir con dos niveles para el mismo lift).
- **`Jerk (Envión)`** no existe en BD: se resuelve con el alias `Split Jerk → Jerk (Envión)`.
  `Push Jerk` sí es otro lift (recibe la barra en fuerza, sin split), así que lleva **su propia
  tabla** (90 % del Split Jerk) en vez de alias.
- Deadlift variants (2842 Sumo, 2843 RDL, 2844 Deficit, 2845 Trap Bar): P3. Si se agregan,
  Sumo = 100 % del Deadlift, RDL = 75 %, Deficit = 90 %, Trap Bar = 105 %, con la misma
  lógica de extrapolación.
- El **peso corporal** que usa el cálculo es el actual del alumno
  (`_peso_y_genero`, `nivel_service.py:224-233`): si el alumno sube 10 kg, su nivel baja sin
  tocar ningún RM. Es correcto para un ratio, pero hay que comunicarlo en la UI (“nivel
  calculado con tu peso actual”).

### 5.3 Estándares gimnásticos propuestos

Unidad: **reps unbroken** salvo que se indique. La columna “Base” cita la fuente: las primeras
salen de los comentarios que ya están en `crossfit_habilidades.py` (que a su vez citan WODprep
y BOXROX); el resto usa la relación de dificultad que el mismo archivo declara
(`crossfit_habilidades.py:11-12`).

| id | Movimiento | Base | M: P / I / A / E | F: P / I / A / E |
|---:|---|---|---|---|
| 2866 | **Strict Pull-up** | comentario `habilidades.py:44-47` (1 / 5 / 10 / 15 strict) | 1 / 5 / 10 / 15 | 1 / 3 / 6 / 8 |
| 2867 | **Kipping Pull-up** | = tabla actual “Pull-ups” | 1 / 10 / 20 / 30 | 1 / 5 / 12 / 20 |
| 2868 | Butterfly Pull-up | mismo volumen que kipping, técnica más exigente | 1 / 8 / 20 / 30 | 1 / 4 / 12 / 20 |
| 2871 | Chin-up | strict + supinación, ~+20 % de volumen | 1 / 6 / 12 / 18 | 1 / 4 / 8 / 12 |
| 2879 | Dips | = volumen de pull-ups | 1 / 10 / 20 / 30 | 1 / 6 / 12 / 20 |
| 2880 | Ring Dips | ~70 % de los dips (anillas) | 0 / 5 / 12 / 20 | 0 / 3 / 8 / 15 |
| 2885 | Knees to Elbows | ~1,5× T2B (progresión) | 0 / 15 / 30 / 45 | 0 / 12 / 22 / 35 |
| 2890 | Wall Walk | reps consecutivas | 0 / 2 / 5 / 8 | 0 / 2 / 5 / 8 |
| 2888 | Handstand Hold | **tipo “tiempo” (segundos)** | 10 / 30 / 60 / 120 | 10 / 30 / 60 / 120 |
| 2901 | GHD Sit-up | `reps_cualquier_forma` | 0 / 20 / 40 / 60 | 0 / 15 / 30 / 50 |
| 2906 | L-sit (P3) | tiempo, segundos | 0 / 10 / 20 / 40 | 0 / 10 / 20 / 40 |
| 2899 | Triple Under (P3) | ~50 % del DU elite | 0 / 5 / 20 / 50 | 0 / 5 / 20 / 50 |

Notas de implementación:

- **`Handstand Hold` y `L-sit` necesitan un tipo nuevo `"tiempo"`** (segundos).
  `obtener_nivel_gimnastico` acepta cualquier `tipo` declarado en la tabla y el nivel se calcula
  igual, pero `_siguiente_nivel_gimnastico` recibe `tipo` y **no lo usa**: devuelve un número
  pelado (`nivel_service.py:137-149`). Hoy ningún consumidor del front lee `valor_faltante`, así
  que no hay bug visible; pero si se va a mostrar “te faltan X”, la unidad (reps / m / s) tiene
  que salir del `tipo` en el mismo cambio.
- **`Handstand Walk` ya usa “distancia”** (metros): no hace falta tocarlo.
- **`Wall Walk` se mide en reps**, no en metros, para no confundirlo con HSW.
- **`Strict Pull-up` vs `Pull-ups (Dominadas)` (2865):** la tabla de 2865 mezcla kipping y
  strict en sus comentarios. Propuesta: 2865 queda como **alias de Kipping** (es lo que el
  alumno carga por defecto) y Strict/Butterfly tienen su propia tabla. Si el box prefiere,
  2865 se elimina del catálogo y quedan los tres específicos.
- **`Wall Ball Shot` (2860) y `Kettlebell Swing` (2859)** están en la categoría `fuerza` de la
  BD, pero son **peso fijo**: no llevan ratio ni nivel (`crossfit_ratios.py:12-14`). No es un
  olvido, es una decisión. Si el box quiere medirlos, va en un benchmark aparte (§5.5), no en
  el nivel.
- **Cardio/metabólico (12 movimientos, ids 2914-2925):** no tienen nivel y no deberían tenerlo
  con el modelo actual (el valor es tiempo/distancia/calorías, no un 1RM). `Sled Push` y
  `Air Runner` ya tienen filas con `peso_kg` dummy (1 y hasta 530): eso es un problema de
  captura, no de estándar.

### 5.4 Cómo evitar que esto vuelva a pasar

1. **Alias explícito** en `nivel_service` (o en `movimiento_categoria.py`, que ya centraliza
   el criterio H-03): `ALIAS_ESTANDAR = { "Split Jerk": "Jerk (Envión)", "Squat Clean":
   "Clean (Cargada)", ... }`, aplicado antes del lookup. No normalizar por heurística de
   texto: los nombres del catálogo son estables y un alias explícito es auditable.
2. **Un test de contrato que falle cuando aparezca un movimiento con RMs sin estándar**
   (o sin entrada en una lista blanca de “no clasifica”). Hoy el silencio es el problema:
   3 filas se pierden y nadie se entera. El test se puede alimentar con una consulta a TEST
   (como `test_rm_categoria_contrato.py`) o con una lista estática de los 103 nombres.
3. **Reporte de mantenimiento** (no bloqueante): “movimientos con RM y sin estándar” y
   “movimientos con estándar y sin filas”, para que el catálogo y las tablas no se separen.
4. **Duplicados 2869/2870 y 2874/2875:** consolidar en un id canónico y dejar el otro como
   alias histórico (no borrar: puede haber FKs). Hoy 2870 tiene el único dato de C2B.

**Esfuerzo:** 0,5 d alias + P1 (3 estándares); 1 d P2 (13 estándares + tipo “tiempo” + tests);
0,5 d P3 (7) y reporte. Total ~2 d.

### 5.5 Peso fijo: `Wall Ball` y `Kettlebell Swing`

Pedido explícito, y la respuesta corta es que **no deben entrar al nivel**: el clasificador es
un ratio 1RM/peso corporal (`crossfit_ratios.py:12-14` los excluye por nombre), y una Wall Ball
de 9 kg no distingue a un Principiante de un Élite. Pero sí son útiles como **benchmark** (una
columna “performance” separada del nivel, o un test de la semana).

Valores de referencia (mismo formato que las tablas, para que se puedan pegar si se decide
usarlos como benchmark). **No medidos**: criterio de coach sobre estándares generales de
CrossFit, se calibran con el box:

| Movimiento | Unidad | M: P / I / A / E | F: P / I / A / E |
|---|---|---|---|
| Wall Ball Shot (9/6 kg, 10/9 ft) | reps unbroken | 5 / 20 / 40 / 60 | 5 / 15 / 30 / 50 |
| Kettlebell Swing (24/16 kg, americano) | reps unbroken | 10 / 25 / 50 / 75 | 10 / 20 / 40 / 60 |

Si se agregan al benchmark, van con su propia tabla (`CROSSFIT_BENCHMARKS`) y **nunca** suman
al `nivel_atleta`, para no romper la comparabilidad del badge.

---

## 6. `student_segments`: qué hacer

### 6.1 Qué es (y qué no)

`student_segments` se creó en `021_data_marts_bi.py:124` como parte de los data marts de BI.
Tiene 6 filas, todas `BASICO`, del tenant 1, escritas una sola vez por el seed
(2026-09-12 21:27). La migración siguiente, `026_segmentacion_alumnos.py:10-14`, aclara que
**“tiene OTRA semántica: nivel de ATLETA … es progreso deportivo”** — o sea, el nombre se usó
para dos cosas distintas y ninguna quedó viva.

Verificado en PROD: **cero lectores** (ni endpoint, ni servicio, ni front), **cero FKs**, cero
vistas/funciones/triggers. Es una tabla muerta con datos de seed.

### 6.2 Opciones

| | Acción | Pros | Contras |
|---|---|---|---|
| **A** | **DROP** en la migración 060/061 (`op.drop_table("student_segments")`) | limpia; elimina la tentación de “reusarla” para el nivel (§3) | irreversible sin backup; si algún día se quiere segmentar de verdad, se rehace |
| **B** | Dejarla y documentar que está muerta | cero riesgo | sigue en el schema, sigue confundiendo (`026` ya se confundió) |
| **C** | Reusarla como tabla de nivel | — | **descartado**: semántica equivocada, sin FK a `usuarios`, 6 filas manuales que se desincronizan del cálculo |

**Recomendación: A, con backup previo del contenido** (6 filas, un `COPY ... TO STDOUT` de
5 líneas en el anexo del script de migración). Un DROP de tabla vacía de uso en el mismo sprint
que se documenta el motivo es más barato que arrastrarla.

**Si el box prefiere B:** agregar un comentario en la tabla
(`COMMENT ON TABLE student_segments IS 'DEPRECATED ...'`) para que el próximo que la vea no
pierda medio día averiguando si se usa.

**Orden recomendado:** hacerlo en la **misma migración** que `061_rm_gimnasia_reps` o en una
propia `062_drop_student_segments`, pero **después** de que §3 esté decidido (si se elige
persistir el nivel, no tocar esta tabla igual: el diseño de §3.3 no la usa).

**Esfuerzo:** 30 min (migración + backup + comentario en el CHANGELOG de migraciones).

---

## 7. Roadmap, esfuerzo y tests

### 7.1 Orden de implementación

| # | Entrega | Depende de | Esfuerzo | Impacto medible |
|---:|---|---|---:|---|
| 1 | **Alias de nombres** (P0) + P1 (Hang Clean, Strict, Kipping) | — | 0,5 d | 3 filas que hoy se pierden empiezan a puntuar |
| 2 | **Confianza mínima (§1)**: `min_ejes`, `min_movs`, `confianza`, badge “Parcial” | — | 0,5–0,75 d | desaparece el “Elite” con 0 gimnasia |
| 3 | **Género sin asumir M (§2.2)** | — | 2 h | deja de haber sesgo silencioso |
| 4 | **Perfil: `genero` autogestionable + chip “incompleto”** (§2.3) | — | 1 d | 300 alumnos pueden completarse solos |
| 5 | **Gimnasia reps vs `peso_kg`** (§4, fases 1–2) | — | 1,5–2 d | el mejor set deja de depender de un dummy |
| 6 | **Estándares P2 + P3** (12 fuerza + 12 gimnasia) + tipo `"tiempo"` | 1 | 1–1,5 d | más movimientos clasifican |
| 7 | **DROP `student_segments`** (§6) | — | 0,5 h | schema limpio |
| 8 | **Nivel persistido** (§3.3) **solo si se cumple un disparador** | 2, 5 | 2,5–3 d | filtro/orden/notificación en backend |
| 9 | **Backfill operativo del perfil** (no código, lo hace el box) | 4 | — | KPI 80 % de activos |

Total de código sin el punto 8: **~5–6 días**. Con el punto 8: **~8–9 días**.

### 7.2 Tests a agregar (estilo del repo: pytest, sin DB cuando se puede)

| Archivo | Qué fija |
|---|---|
| `backend/tests/test_nivel_confianza.py` | matriz de `nivel_atleta`/`confianza` para 0/1/2 ejes y 0/1/2 movimientos; que un eje suelto **no** publique badge |
| `backend/tests/test_nivel_alias.py` | que `Split Jerk`, `Squat Clean`, `Rope Climb (Trepada)` y `Bear Crawl (Caminata)` clasifican (parametrizado) |
| `backend/tests/test_nivel_sin_genero.py` | sin `genero` → gimnasia `clasificable=False` (no cae a tabla M); `genero='otro'` igual |
| `backend/tests/test_historial_rm_gimnasia_reps.py` | el mejor set gimnástico sale de `repeticiones`, no de `peso_kg` (8/1 vs 20/100 → 20) |
| `backend/tests/test_rm_categoria_contrato.py` (extender) | `peso_kg` rechazado en gimnasia (422) tras la fase 2 de §4 |
| `backend/tests/test_perfil_campos_alumno.py` (extender) | `genero` autogestionable solo si está vacío y solo `M`/`F`; `perfil_completo` en el listado |
| `backend/tests/test_nivel_estandares_cobertura.py` | todo movimiento con RM tiene estándar o está en la lista blanca (falla si aparece uno nuevo sin decisión) |

Los cuatro primeros son **funciones puras** (`nivel_service` no toca la DB para decidir el
nivel), así que se escriben con dicts de entrada, sin fixtures.

### 7.3 Cómo se valida en PROD sin escribir

Después de cada entrega, la misma consulta de solo lectura del §0.2 (conteo de badges por nivel
y por eje) debe dar:

- entrega 2: **0** alumnos con badge global y un solo eje;
- entrega 6: las 3 filas hoy descartadas (Hang Clean, Strict Pull-up y Kipping Pull-up)
  empiezan a puntuar para sus dueños;
- entrega 1+5: la alumna 9 debería pasar de “Elite” a “Elite (fuerza) · gimnasia: sin datos”.

---

## 8. Decisiones pendientes (para el dueño del producto)

| # | Decisión | Opciones | Mi recomendación | Bloquea |
|---:|---|---|---|---|
| D1 | Regla de confianza | A / B / C / D (§1.2) | **B** con umbrales en config | entregas 2 y 8 |
| D2 | ¿Se persiste el nivel? | A / B (§3.2) | **A** hasta que se cumpla un disparador | entrega 8 |
| D3 | ¿El alumno puede editar su `genero`? | sí (una vez, auditado) / solo el box | **sí, una vez** | entrega 4 |
| D4 | ¿Se exige `sexo`+`peso` en el alta del coach? | sí / no | **sí**; en el landing público, no | entrega 4 |
| D5 | ¿Se agregan los 12 estándares gimnásticos de §5.3? | todos / solo P1+P2 / ninguno | **P1+P2** | entrega 6 |
| D6 | ¿Wall Ball y KB Swing entran al nivel? | no / benchmark aparte | **benchmark aparte** (§5.5) | nada |
| D7 | ¿Se dropea `student_segments`? | DROP / dejar deprecada | **DROP** con backup | entrega 7 |
| D8 | ¿`Pull-ups (Dominadas)` (2865) queda como alias de Kipping? | sí / se elimina del catálogo | **sí** | entrega 6 |
| D9 | Los ratios propuestos (§5.2–5.3) ¿se calibran con el coach? | tal cual / calibrados | **calibrar P y E** (los extremos) | entrega 6 |
| D10 | `MAINT_DB_URL` (rol `maint_rw`) para poder ejecutar FIX 4 | proveer la cadena | — | **FIX 4** (Anexo A.4) — **resuelta el 2026-10-28**, ejecutada |

Ninguna de las entregas 1–3 y 7 depende de una decisión de negocio: se pueden arrancar ya.

---

## Anexo A — FIX 4 (PROD, carga k6): **EJECUTADO** el 2026-10-28 (ver A.4)

**Tarea autorizada** (texto original): limpiar en PROD los usuarios de carga k6 —
`suscripciones → 'vencido'` y `usuarios → 'rechazado', activo=false` — con dry-run previo,
en una transacción explícita, y después correr el dry-run de `mantenimiento_cloud.py` para
confirmar que A.3 deja de reportar hallazgos.

### A.1 Dry-run ya hecho (solo lectura, vía `DIRECT_URL`)

No hizo falta escribir nada para saber cuántas filas toca cada `UPDATE`. Medido en PROD:

| Dato | Valor |
|---|---|
| Usuarios `correo LIKE 'carga_k6_%'` | **95** (ids 536–630, tenant 1, rol `alumno`) |
| Creados | 2026-10-26 00:46:37 → 01:29:29 UTC (carga de k6) |
| `estado` actual | los 95 `activo`; `activo=true`; `cambiar_password=true` |
| Suscripciones de esos usuarios | **141** → `Prueba/activo` 49, `Prueba/vencido` 46, `Baby Chimp/activo` 46 |
| **UPDATE 1 afectaría** (`estado IN ('activo','pendiente')`) | **95** filas (49 + 46) |
| **UPDATE 2 afectaría** (`estado <> 'rechazado'`) | **95** filas |
| `historial_rm` de esos usuarios | **0** → FIX 4 no toca ningún dato de nivel |

Filas dependientes (para dimensionar el efecto, no se modifican): `reservas` 123,
`notificaciones` 120, `notificaciones_enviadas` 132, `codigos_referido` 95,
`predictions_churn` 95, `pedidos` 37, `solicitudes_planes` 46, `referidos_aplicados` 17+17,
`creditos_referido` 15, `promociones_referidos_detectadas` 4. No hay FK en cascada desde
`suscripciones` ni tablas hijas en `usuarios` que se borren: el cambio es de estado, no un
DELETE.

### A.2 Por qué no se ejecutó el 2026-10-27 (histórico, resuelto)

`MAINT_DB_URL` (rol `maint_rw`, host directo sin `-pooler`) **no está definida en ningún
`.env` del repo** (revisados `backend/.env*` y `.env*` de la raíz; solo aparece en
`mantenimiento_cloud.py` y en el `README.md` como variable esperada). Sin esa cadena no se
pueden hacer los dos `UPDATE`, y tampoco el paso 3 (el dry-run de mantenimiento valida
`MAINT_DB_URL` y aborta con `ConfigError` si falta — `mantenimiento_cloud.py:441-444`).

### A.3 Plan de ejecución (el que se usó, tal cual)

Los `UPDATE` son los de la tarea, sin cambios. `rowcount` impreso por cada uno para comparar
con el dry-run (95 / 95); si alguno no coincide, `ROLLBACK` en vez de `COMMIT`:

```python
# backend/maintenance/_fix4_k6.py  (temporal, no commiteado)
import os, psycopg2
conn = psycopg2.connect(os.environ["MAINT_DB_URL"])
conn.autocommit = False                    # BEGIN explícito, no autocommit
try:
    with conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '120s'")
        cur.execute("""
            UPDATE suscripciones s SET estado = 'vencido', updated_at = now()
            WHERE s.estado IN ('activo','pendiente')
              AND s.usuario_id IN (SELECT id FROM usuarios WHERE correo LIKE 'carga_k6_%')
        """)
        subs = cur.rowcount
        cur.execute("""
            UPDATE usuarios SET estado = 'rechazado', activo = false
            WHERE correo LIKE 'carga_k6_%' AND estado <> 'rechazado'
        """)
        users = cur.rowcount
        print(f"suscripciones={subs} (esperado 95)  usuarios={users} (esperado 95)")
        if (subs, users) != (95, 95):
            raise RuntimeError("dry-run no coincide: ROLLBACK")
    conn.commit()
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
```

Verificación posterior (paso 3), con la variable ya cargada:

```powershell
cd backend
$env:DRY_RUN = "1"; $env:ENVIRONMENT = "production"
python -m maintenance.mantenimiento_cloud
```

Criterio de aceptación: la sección **A.3** no reporta hallazgos para `carga_k6_%` y el proceso
termina con exit 0 (o con los códigos ya conocidos por otros hallazgos, sin A.3).

**Reversión:** los dos `UPDATE` son reversibles con el estado anterior
(`activo` + `suscripciones: Prueba/activo 49, Baby Chimp/activo 46, Prueba/vencido 46`), pero el
`updated_at` no. Si se ejecuta y hay que revertir, es un `UPDATE` por id con la lista de los 95
ids (536–630) — guardar esa lista antes de ejecutar.

### A.4 Ejecutado — 2026-10-28 (resultado)

Credencial provista por el dueño (`MAINT_DB_URL` de `maint_rw`, endpoint directo
`ep-winter-star-…us-west-2`, sin `-pooler`). Secuencia real: dry-run → backup → 2 `UPDATE` en
**una** transacción → `COMMIT` → verificación independiente → dry-run del mantenimiento.

| Paso | Resultado |
|---|---|
| Dry-run previo (solo lectura) | 95 usuarios (ids 536–630, `@example.com`, todos `alumno`/tenant 1) · 141 suscripciones (95 `activo` + 46 `vencido`) · **UPDATE 1 = 95**, **UPDATE 2 = 95** — idéntico a A.1 |
| Backup | `~/Desktop/Proyectos/_fix4_k6_backup_20261028_063424.json` — 95 filas de `usuarios` (id, correo, estado, activo, tenant_id, rol, created_at) + **141** filas de `suscripciones` (id, usuario_id, estado, plan_id, fechas) + los ids aplicados (95/95) |
| `UPDATE 1` (suscripciones) | **95** filas → `estado='vencido'`, `updated_at=now()` |
| `UPDATE 2` (usuarios) | **95** filas → `estado='rechazado'`, `activo=false` |
| Guardas dentro de la transacción | `suscripciones vigentes = 0`, `usuarios sin rechazar/activos = 0` ⇒ `COMMIT` (si el rowcount no hubiera sido 95/95 ⇒ `ROLLBACK`) |
| Post-fix (conexión nueva) | usuarios k6: `rechazado/false` ×95 · suscripciones k6: `vencido` ×141 · **0** vigentes · suscripciones vigentes de usuarios reales: **260**, igual que antes del fix |
| Dry-run de `mantenimiento_cloud.py` (`DRY_RUN=1`, `ENVIRONMENT=production`) | `cambios_a_realizar=0` · `detecciones_hallazgos=0` (**A.3 sin hallazgos**) · `integridad_hallazgos=0` · `vencidos: 0 fila(s)` · `suscripciones_activas: 260` · `MAIL: no se envía (todo OK)` · `duracion_s=85` |

Efecto lateral conocido y aceptado: el `updated_at` de las **95** suscripciones que el `UPDATE 1`
tocó quedó en el momento del fix (las 46 que ya estaban `vencido` no entraron en el `WHERE` y
conservan su fecha). A.3 sólo mira suscripciones **vigentes** y estos usuarios ya no tienen
ninguna, así que no puede aparecer un descuadre falso por eso.

Artefactos (fuera del repo, no se commitean): `_fix4_k6.py` (dry-run / apply / **revert** desde el
backup), `_fix4_k6_backup_20261028_063424.json` y `_fix4_k6_mantenimiento_dryrun.log`, los tres en
`~/Desktop/Proyectos/`. Revertir: `python _fix4_k6.py --revert --backup _fix4_k6_backup_…json`.
El script aborta solo si el dry-run no da 95/95, así que una segunda corrida no puede tocar nada
(hoy da 0/0 por idempotencia).

---

## Anexo B — Metodología y límites de las mediciones

**Entorno:** PROD (Neon), conexión de **solo lectura** (`SELECT`) vía `DIRECT_URL` con
`sslmode=require` (`backend/.env.prod`). **Cero escrituras**: no se ejecutó ningún `INSERT`,
`UPDATE`, `DELETE` ni DDL. `MAINT_DB_URL` nunca estuvo disponible durante la medición (Anexo A.2);
se usó el 2026-10-28 ya con la credencial provista, sólo para el FIX 4 (A.4).

**Población de referencia:** `usuarios` con `tenant_id = 1`, `rol = 'alumno'` y
`correo NOT LIKE 'carga_k6_%'` → **410 alumnos**. Los 95 usuarios de carga k6 (ids 536–630)
se excluyen de todas las estadísticas de nivel y de perfil, porque son datos sintéticos; se
analizan por separado en el Anexo A.

**Estado del repo al medir:** `git HEAD = a246538` (2026-10-27); Alembic con **un solo head**,
`059_reserva_suscripcion_id`, sobre 59 revisiones (verificado con el `down_revision` de todas
las migraciones, no por `alembic heads`, para no depender de la DB).

**Cómo se obtuvieron los números:**

| Medición | Consulta |
|---|---|
| RMs por movimiento y dueño | `historial_rm` agrupado por `movimiento_id`, con `count(*)`, `count(distinct alumno_id)`, `min/max(peso_kg)` |
| Completitud de perfil | una sola pasada con `count(*) filter (where ...)` para las 4 combinaciones peso/género |
| Nivel actual | se replicó la lógica de `nivel_service` en Python (importando el módulo, no una copia de las tablas) sobre los 6 alumnos completos |
| Coincidencia catálogo ↔ estándares | comparación de strings exactos entre `movimientos.nombre` (103 filas) y las claves de `CROSSFIT_RATIOS`/`CROSSFIT_HABILIDADES` |
| `student_segments` | `count(*)`, huérfanos por `LEFT JOIN`, `pg_views`, `pg_proc`, `pg_trigger`, `pg_constraint`, `pg_depend` |
| k6 (Anexo A) | conteos por `estado`/`plan` de `suscripciones` y por tabla dependiente |

Los scripts usados son desechables y **no** forman parte del repo (vivieron en un directorio
temporal fuera del proyecto); para reproducir cualquier número alcanza con las consultas
descritas arriba. Codificación de consola resuelta con `PYTHONUTF8=1` +
`Out-File -Encoding utf8` (Windows/PowerShell).

**Límites que hay que tener en cuenta al leer el documento:**

1. **n=2 dueños de RM.** Todas las conclusiones sobre “qué nivel publica hoy” se apoyan en dos
   alumnos. Sirven para demostrar el defecto de la regla (§1), no para estimar adopción.
2. **Sin serie temporal.** Se midió un snapshot. No se puede decir si la adopción de RM crece
   o no: `historial_rm` tiene 19 filas y una sola fecha de carga masiva.
3. **Los ratios propuestos en §5.2–5.3 no son percentiles medidos**: son derivaciones de las
   tablas existentes usando las reglas que el propio archivo declara y el criterio de coach.
   Marcados como “a calibrar” a propósito (D9).
4. **Duplicados de catálogo** (2869/2870, 2874/2875) se reportan por id, pero no se verificó si
   algún día se usaron con otro nombre: no hay `auditoria` de `movimientos` que lo permita.
5. **`ENVIRONMENT`/`DRY_RUN`** del mantenimiento no se ejecutaron contra PROD en esta sesión
   (§Anexo A), así que los hallazgos A.3 son los del reporte previo, no una corrida nueva.

