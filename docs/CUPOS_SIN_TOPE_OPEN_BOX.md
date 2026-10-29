# Cupos sin tope: Musculación y Open Box

Decisión de negocio del **2026-10-29** (reemplaza la "decisión pendiente" de
`docs/CUPOS_ASISTENCIA.md` §5, opciones 2-3): **Musculación y Open Box no tienen
tope de cupos**. Son salas de acceso libre dentro del horario: el alumno entra y
entrena, no reserva una butaca. El `cupo_maximo = 50` con el que se generaban
sus bloques era un placeholder sin sentido de negocio, y era el **84 % del
denominador** del KPI de ocupación (de ahí el "113 / 4.640 cupos" = 2,4 %).

Regla nueva, en una línea: **`cupo_maximo IS NULL` = sin tope.** No es 0 (un 0
rechazaría todas las reservas) ni 50 (un número es un techo).

Todo lo de este documento se hizo y verificó **en TEST**
(`ep-crimson-tooth-akhx7q2s`). Nada se aplicó en PROD.

---

## 1. Qué se cambió

### 1.1 Base de datos — migración `066_cupos_sin_tope_open_box`

`backend/alembic/versions/066_cupos_sin_tope_open_box.py`

1. `clases.cupo_maximo` y `horarios.cupo_maximo` pasan a **NULLABLE** (sin eso,
   `generar_clases.py` no podría dejar un bloque sin tope: copia el cupo del
   horario tal cual).
2. **Backfill**: `UPDATE ... FROM disciplinas d WHERE d.id = c.disciplina_id AND
   d.es_open_box = true` → `cupo_maximo = NULL` y `cupo_original = NULL` (el
   snapshot del techo de "ampliar cupo"; una clase sin tope no tiene techo que
   ampliar). El criterio es `es_open_box`, no una lista de nombres: si mañana se
   suma otra sala libre, alcanza con marcarla así.
3. Dos CHECK que fijan el contrato: `cupo_maximo IS NULL OR cupo_maximo > 0`
   (`ck_clases_cupo_maximo_positivo`, `ck_horarios_cupo_maximo_positivo`).

Aplicada en TEST: `alembic upgrade head` → `alembic_version =
066_cupos_sin_tope_open_box`.

### 1.2 Modelos y esquemas

| Archivo | Cambio |
| --- | --- |
| `app/models/clase.py` | `cupo_maximo` y `cupo_original` `nullable=True` |
| `app/models/horario_base.py` | `cupo_maximo` `nullable=True` |
| `app/schemas/clase.py` | `ClaseBase.cupo_maximo: Optional[int] = Field(20, gt=0)` y `ClaseListItem.cupo_maximo: Optional[int] = None` |

### 1.3 Reservas: NULL nunca rechaza

| Archivo:línea | Antes | Ahora |
| --- | --- | --- |
| `api/v1/reservas.py:155-166` | `.where(Clase.asistentes_confirmados < Clase.cupo_maximo)` | `.where(or_(Clase.cupo_maximo.is_(None), ... < Clase.cupo_maximo))` |
| `api/v1/asistencia.py:683-692` (presencia sin cargo) | idem | idem |
| `api/v1/clases.py:177-183` (`solo_con_cupo`) | `c.asistentes_confirmados < c.cupo_maximo` | `(c.cupo_maximo IS NULL OR ... < c.cupo_maximo)` |

Sin el `OR`, comparar contra NULL da NULL → `rowcount = 0` → "Clase sin cupos"
en una sala de acceso libre. El contador `asistentes_confirmados` se sigue
incrementando: es el dato que muestran los KPIs y el panel del coach.

### 1.4 Panel: no se puede inventar un cupo

* `POST /clases/{id}/ampliar-cupo` (`clases.py:490-499`): con `cupo_maximo IS
  NULL` responde **400** ("no hay cupo que ampliar"). Antes, `original + 10` con
  `original = None` era un **500** (TypeError).
* `POST /horarios` (`horarios.py:33-51`): si la disciplina tiene
  `es_open_box = true`, la plantilla se crea con `cupo_maximo = NULL` aunque el
  cliente mande un número.
* `PUT /horarios/{id}` (`horarios.py:195-209`): fijar un cupo en una disciplina
  libre es **400**; si la plantilla **pasa a** una disciplina libre, el cupo se
  limpia (`horarios.py:230-233`).
* `PATCH /supervision/cupo-disciplina` (`supervision.py:589-606`): **400** para
  disciplinas libres. `GET /supervision/cupos-disciplinas` devuelve
  `cupo_actual: null` y `sin_tope: true` (`supervision.py:645-666`).
* Front: los controles de subir/bajar cupo se reemplazan por "Acceso libre ·
  sin cupo" (`SupervisionClases.jsx`), y "Ampliar cupo" no se ofrece
  (`SupervisionClaseRow.jsx`, `AsistenciaFranja.jsx`, `cuposClase.js`).

### 1.5 KPIs: dos universos, un denominador honesto

| Pantalla / archivo | Antes | Ahora |
| --- | --- | --- |
| Historial de Asistencia (`utils/historialAsistencia.js`) | `cupos = Σ cupo_maximo` de TODAS las clases | `cupos` y `pct` sólo de las clases CON tope; `reservasSinTope` y `clasesSinTope` como conteo; `pct = null` si ninguna tiene tope |
| Anillo semanal / calendario / detalle (`HistorialAsistencia.jsx`) | `113/4.640` · `2%` | `158 de 640 cupos (mes) + 98 sin cupo` · `25%`; en una sala libre el centro del anillo muestra las **reservas** (`87`), no un `%` |
| Franjas del admin móvil (`utils/franjasAsistencia.js`) | `ocupacion = reservas/cupos` con `cupos` inflado | `cupos` y `ocupacion` sólo de las clases con tope; `reservasSinTope` aparte; `ocupacion = null` si la franja no tiene ninguna con tope |
| Reportes / BI (`api/v1/reportes.py`) | `SUM(COALESCE(cupo_maximo, 1))` (un 1 inventado por clase sin cupo) | `SUM(cupo_maximo) FILTER (WHERE cupo_maximo IS NOT NULL)`; `ocupacion_pct = null` + `sin_tope: true` + `reservas: N` por disciplina; el endpoint suma `reservasSinCupo` |
| Ocupación promedio (`services/metricas_service.py`) | numerador y denominador sobre TODAS las clases | `FILTER (WHERE cupo_maximo IS NOT NULL)` en las dos partes + `reservas_sin_tope()` como función aparte |
| Excel de Reportes (`services/reportes_service.py`) | `SUM(COALESCE(cupo_maximo, 1))` y `%` | `FILTER` para el cupo; en una disciplina libre la celda dice `87 reservas (sin cupo)` |
| Tarjetas del alumno / coach | `0/0 libres`, `Completo`, `x/0` | `Acceso libre`, botón siempre habilitado, `x (acceso libre)` |

Regla del agregado (punto 4 del pedido): **el denominador suma sólo las
disciplinas con tope real** y las reservas de las salas libres se muestran
**aparte, como conteo** — nunca como ratio.

### 1.6 Seed de TEST

`run_setup_test_db.py` creaba Open Box y Musculación con `es_open_box = false` y
cupo 10/15. Ahora las siembra con `es_open_box=True` y sus horarios con
`cupo_maximo=None` (líneas 421-460), así un `run_tests.bat` no vuelve a inventar
el placeholder.


---

## 2. Datos de TEST (antes → después)

Octubre 2026, `cancelada = false`:

| | Antes | Después |
| --- | --- | --- |
| Clases del mes | 567 | **562** (se borraron las 5 de las 03:00) |
| Cupos del mes | 20.988 | **3.308** (sólo clases con tope) |
| De esos cupos, open box | 17.600 (84 %) | **0** |
| Clases sin tope | 0 | **352** |

Jueves del mes (el "113 / 4.640"):

| | Antes | Después |
| --- | --- | --- |
| Clases | 120 | 120 (80 sin tope) |
| Cupos (denominador) | 4.640 | **640** |
| Reservas confirmadas en clases con tope | 113 | **158** |
| % de ocupación | 2,4 % | **24,7 %** |
| Reservas en salas libres | dentro del denominador | **98, como conteo aparte** |

Verificación (SQL read-only, con la migración ya aplicada):

```sql
-- cupos por día de la semana: sólo las clases CON tope entran al denominador
select to_char(fecha,'ID') dow, count(*) clases,
       count(*) filter (where cupo_maximo is null) sin_tope,
       sum(cupo_maximo) cupos_con_tope,
       sum(asistentes_confirmados) filter (where cupo_maximo is not null) asistentes_con_tope,
       sum(asistentes_confirmados) filter (where cupo_maximo is null) asistentes_sin_tope
from clases
where cancelada = false
  and fecha >= date_trunc('month', current_date)
  and fecha <  date_trunc('month', current_date) + interval '1 month'
group by 1 order by 1;
```

Resultado (2026-10, TEST):

```
1 106 64 688  62 26
2  96 64 512  42 30
3 104 64 608  36 24
4 120 80 640 158 98
5 130 80 760 163 99
6   6  0 100   5  -
```

Invariante que quedó como test
(`tests/test_cupos_sin_tope.py::test_en_test_ninguna_sala_libre_tiene_cupo_numerico`):

```sql
select d.nombre, count(*) from clases c
  join disciplinas d on d.id = c.disciplina_id
 where d.es_open_box and c.cupo_maximo is not null
 group by 1;                       -- 0 filas
```

---

## 3. Limpieza de las 5 clases de las 03:00

Las 5 clases "basura" del diagnóstico (`docs/CUPOS_ASISTENCIA.md` §3) estaban el
**2026-10-24 a las 03:00** con `horario_base_id = 1` (CrossFit, 10:00). Se
verificó que no tuvieran nada asociado **antes** de borrarlas:

```sql
select
  (select count(*) from reservas   where clase_id = any(:ids)) reservas,
  (select count(*) from asistencias where clase_id = any(:ids)) asistencias,
  (select count(*) from cobertura_emergencia where clase_id = any(:ids)) coberturas;
-- (0, 0, 0)
```

Borrado (sólo TEST, y sólo si siguen sin referencias):

```sql
delete from clases c
 where c.hora_inicio = time '03:00'
   and not exists (select 1 from reservas r where r.clase_id = c.id)
   and not exists (select 1 from asistencias a where a.clase_id = c.id);
-- 5 filas
```

No hay horarios a las 03:00 (`horarios` con `hora_inicio = time '03:00'` → 0
filas), así que no se regeneran.

---

## 4. Tests

| Archivo | Qué cubre | Resultado |
| --- | --- | --- |
| `backend/tests/test_cupos_sin_tope.py` | modelo/migración, reservas con NULL, panel, KPIs, front, seed e invariante de datos en TEST | **16 passed** |
| `backend/tests/test_concurrencia_integracion.py::test_ultimo_cupo_solo_entra_uno` | con `cupo=1`, dos alumnos simultáneos: 201 + 400 (con NULL la reserva nunca se rechaza) | **passed** |
| `backend/tests/test_reportes_sin_n1.py` | ocupación por disciplina = 1 consulta; sin tope → `ocupacion_pct=None` y `reservas` | **8 passed** |
| `frontend/scripts/test-historial-asistencia.mjs` | util del Historial (incluye "un mes sin clases no divide por cero") | **TODO OK** |
| `frontend/scripts/test-franjas-asistencia.mjs` | franjas (incluye "franja sin clases: 0, sin NaN") | **OK** |

---

## 5. Riesgos y límites conocidos

* **Histórico**: el backfill deja en NULL los cupos históricos de las salas
  libres. Los reportes de meses pasados cambian de denominador (es el objetivo:
  esos cupos nunca representaron una butaca), pero un PDF/Excel emitido antes se
  verá distinto si se vuelve a generar. Es esperado y queda documentado acá.
* **Clases mixtas**: si alguien creara a mano una clase con cupo dentro de una
  disciplina libre, el `%` de esa disciplina se calcula sólo con las clases con
  cupo (`asistentes_con_tope / cupo`), así que no puede pasar de 100 %.
* **`cupo_original`**: las clases históricas de salas libres quedaron con
  `cupo_original = NULL`. Si se quisiera volver atrás, el `downgrade` de la 066
  repone 50 (el placeholder), no el valor exacto previo.
