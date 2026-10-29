# Cupos del Historial de Asistencia — de dónde sale "113 / 4.640"

Investigación del reporte **B.4.2** ("cifras de cupos anómalas en los círculos
semanales"). Conclusión corta: **no hay un error de cálculo**. El denominador es
la suma de los cupos de **todas las clases ya ocurridas de ese día de la semana
en el mes** —no los de una clase ni los de una semana— y el 84 % de esos cupos
salen de las disciplinas *open box* (Musculación y Open Box), que se generan con
cupo 50 por bloque y no tienen reservas.

Fecha del diagnóstico: 2026-10-28. Datos leídos de la rama **TEST**
(`ep-crimson-tooth-akhx7q2s`, `backend/.env.test`) con sesión `readonly=True`.
Ver el aviso de entorno al final del documento.

---

## 1. Cómo se calcula hoy

| Paso | Dónde |
| --- | --- |
| `GET /api/v1/asistencia/historial?anio=&mes=` devuelve el mes del box (admin) | `backend/app/api/v1/asistencia.py:217` |
| El front agrupa por día de la semana y suma | `frontend/src/utils/historialAsistencia.js` (`totalesDe`) |
| Un anillo por día: `presentes / cupos` | `frontend/src/components/HistorialAsistencia.jsx:331` |

`totalesDe(clases)` hace literalmente:

```js
const cupos = lista.reduce((a, c) => a + cuposDe(c), 0);   // cupo_maximo de CADA clase
```

y `semana[dow]` contiene **todas** las clases de ese día de la semana en el mes
(4 o 5 jueves), filtradas por `clasesOcurridas` (fecha ≤ hoy). No hay `JOIN` con
reservas en el backend que duplique filas: las reservas se cuentan con un
`GROUP BY` aparte (`_contadores_de_clases`), así que la duplicación no existe.

## 2. Reproducción del número exacto

Mes en curso en TEST (octubre 2026), clases no canceladas:

| día de semana | clases | cupos (suma de `cupo_maximo`) | min | max |
| --- | --- | --- | --- | --- |
| lunes | 106 | 3.888 | 12 | 50 |
| martes | 96 | 3.712 | 16 | 50 |
| miércoles | 104 | 3.808 | 12 | 50 |
| **jueves** | **120** | **4.640** | 16 | 50 |
| viernes | 130 | 4.760 | 12 | 50 |
| sábado | 11 | 180 | 16 | 20 |

→ El **4.640 es el jueves**: 120 clases (5 jueves × ~24 bloques) sumando cupos de
16 a 50. El total del mes es 20.988 cupos en 567 clases.

`113` es la cantidad de presentes de esas 120 clases (el mes entero tiene 258
presentes sobre 510 reservas vigentes). O sea: **113 / 4.640 = 2,4 %** es la
ocupación real de los jueves del mes con ese denominador.

## 3. Por qué el denominador se siente absurdo

Reparto de los 20.988 cupos del mes por disciplina:

| disciplina | clases | cupos | cupo por bloque |
| --- | --- | --- | --- |
| Musculación (`es_open_box = true`) | 220 | 11.000 | 50 |
| Open Box (`es_open_box = true`) | 132 | 6.600 | 50 |
| crossfit | 189 | 3.076 | 16–40 |
| Levantamiento Olímpico | 26 | 312 | 12 |

- **17.600 de 20.988 cupos (84 %) son de las dos disciplinas open box**, que el
  generador crea con cupo 50 por bloque (`es_open_box` en `disciplinas`, sin
  `requiere_coach`). Son salas de acceso libre: el cupo no representa una
  butaca reservable y casi nunca tienen reservas.
- El box genera ~21 clases/día (24–26 de lunes a viernes), así que un solo día
  de la semana en el mes ya suma ~900 cupos.
- Encima hay 5 clases de madrugada (03:00) y 3 con minutos no redondos
  (`14:26`), residuos de datos de prueba que suman cupos sin aportar asistencia.

## 4. Qué se cambió

Sólo el **rótulo**, no la matemática (cambiar un KPI sin decisión de negocio no
corresponde):

- Anillo: `113/4.640 cupos` → **`113 de 4.640 cupos (mes)`**.
- `title` del anillo: ahora dice presentes, cupos ofrecidos y cantidad de clases
  ya ocurridas del mes (`HistorialAsistencia.jsx:339`).
- Totales: `X cupos en clases ya ocurridas` → **`X cupos ofrecidos en N clases ya
  ocurridas`**.

## 5. Decisión tomada (2026-10-29): implementada la opción 2 + 3

La decisión de negocio fue: **Musculación y Open Box no tienen tope de cupos**.
Se implementó en `docs/CUPOS_SIN_TOPE_OPEN_BOX.md` (migración
`066_cupos_sin_tope_open_box`):

- `clases.cupo_maximo` y `horarios.cupo_maximo` aceptan `NULL` = **sin tope**, y
  las disciplinas con `es_open_box = true` quedaron con `NULL` (backfill).
- El KPI de ocupación suma al denominador **sólo las clases con tope**; las
  salas libres informan su **conteo de reservas** aparte (nunca un %).
- Se borraron las 5 clases de las 03:00 (sin reservas ni asistencias) después de
  confirmarlo con SQL.

Lo que sigue es el análisis original, que explica por qué el número estaba
inflado; se conserva como contexto histórico.

### 5.1 Opciones que se evaluaron (histórico)

1. **Dejarlo así** (sólo con el rótulo nuevo). Es la lectura "butacas ofrecidas
   vs. gente que vino", honesta pero poco accionable.
2. **Excluir `es_open_box` del denominador** de ocupación (mostrarlos aparte:
   "Musculación / Open Box: acceso libre, sin cupo"). Cambia el KPI de
   `/admin/historial` y el de Reportes/BI: hay que decidirlo una vez y aplicarlo
   en `utils/historialAsistencia.js` (`cuposDe`) o en el backend.
3. **Normalizar los datos**: bajar el cupo de las disciplinas open box a un
   valor realista (o 0 = sin cupo), y limpiar las 5 clases de madrugada.
   Es limpieza de datos, no código.

## 6. SQL usado (read-only)

```sql
-- cupos por día de la semana del mes en curso
select to_char(fecha, 'ID') dow, count(*) clases, sum(cupo_maximo) cupos,
       min(cupo_maximo), max(cupo_maximo)
from clases
where cancelada = false
  and fecha >= date_trunc('month', current_date)
  and fecha <  date_trunc('month', current_date) + interval '1 month'
group by 1 order by 1;

-- cupos por disciplina (mes en curso)
select d.nombre, count(*), sum(c.cupo_maximo), min(c.cupo_maximo), max(c.cupo_maximo)
from clases c left join disciplinas d on d.id = c.disciplina_id
where c.cancelada = false
  and c.fecha >= date_trunc('month', current_date)
  and c.fecha <  date_trunc('month', current_date) + interval '1 month'
group by 1 order by 3 desc;
```

## ⚠️ Entorno

`backend/.env` (el que usa el uvicorn de `:8000`) apunta a
**`ep-winter-star-akwis51j` = PROD**. `backend/.env.test` apunta a
`ep-crimson-tooth-akhx7q2s` (TEST oficial). Este diagnóstico se hizo **sólo con
SELECTs** sobre TEST; no se ejecutó ninguna escritura ni se corrió la suite de
integración, porque `tests/conftest.py` habla con el servidor de `:8000` y ese
servidor está apuntando a PROD.
