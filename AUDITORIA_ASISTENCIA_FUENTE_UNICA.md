# La asistencia tiene UNA sola fuente: `reservas.asistio` sobre `clases.fecha`

**Fecha:** 2026-10-15 · **Alcance:** 2ª tanda de la auditoría del panel del coach (la 1ª fueron
los endpoints de "En riesgo"). **Estado:** los 5 lectores pedidos + 2 agregados quedaron migrados,
con guards en verde y seeds de test actualizados. **Sin push** (lo hace el usuario al revisar).

## 1. Por qué (en una línea)

`asistencias` es una tabla histórica que **nadie puebla**: el único `INSERT` de la app es
`POST /fidelizacion/registrar` y ninguna pantalla lo llama (el coach y el alumno marcan por
`POST /asistencia/clases/{id}/confirmar`, que escribe `reservas.asistio`); los seeds/demo son lo
único que la llena. Todo cálculo que la leía respondía "este alumno nunca entrenó", y de ahí
salían los "251 En riesgo" del panel, el churn medido desde el alta y la campaña de inactividad
que no podía alcanzar a nadie real.

## 2. Qué se migró (y qué no)

| # | Lector | Qué leía | Qué lee ahora | Efecto esperado en los números |
|---|--------|----------|---------------|-------------------------------|
| 1 | `services/churn_service` | `max/min` sobre `asistencias` (churn del data mart, ventanas 30/90, `es_plan_sin_usar` vía `_ultima_asistencia`) | `asistencia_real.ultima_asistencia_por_alumno` + `asistencias_entre_por_alumno` | `dias_inactivo` pasa de "días desde el alta/plan" al valor REAL; caen los falsos CRÍTICOS de alumnos nuevos y aparecen los ausentes de verdad. **"Plan sin usar" se desploma**: con la tabla vacía `ultima=None` → TODO alumno con plan de +5 días contaba como "plan sin usar" |
| 2 | `services/fidelizacion_plantillas` | ídem, por alumno (`_referencia_actividad`) y por lote (`_datos_sugerencia`) | el mismo helper | Los tramos de inactividad (7-14 / 15-30 / +30) dejan de contarse desde el plan o el alta: la plantilla sugerida cambia para quien sí entrenó |
| 3 | `services/alertas_email_service` | `SELECT MAX(a.fecha) FROM asistencias` en SQL crudo | el CTE `asistencia_real.sql_cte_asistencias()` | La campaña de inactividad **empieza a incluir ausentes reales** (antes sólo alcanzaba a quien tuviera fila de seed) y deja de incluir a quien sí entrenó |
| 4 | `api/v1/kpis_populate` | `_ultima_asistencia`, `_conteos_asistencias` y el embudo `alumnos_clase_prueba_ejecutada` | helper + `asistencias_entre_por_alumno` | El data mart `predictions_churn` y el embudo prueba→plan se recalculan con datos reales (el embudo estaba en 0) |
| 5 | `api/v1/kpis` | `_dias_inactividad_por_alumno`, `_asistencias_ventana_por_alumno` y 2 consultas crudas (`/bloques-horarios`, `/cohortes`) | helper + CTE | El insight servido en vivo coincide con el churn; `/bloques-horarios` deja de dar 0 asistencias en todos los bloques (la ocupación se activa) y `/cohortes` deja de dar 0% de retención en todas las cohortes |
| 6 | `api/v1/usuarios` | `max(asistencias.fecha)` por página | el mismo helper | El buscador del Admin muestra la última asistencia REAL (antes "nunca" para todos) y puede reordenar resultados |
| 7 | `ml/features` **(agregado)** | `_ultima_asistencia` / `_asistencias_en_ventana` / `build_features` | helper (con `hasta=` para el as-of) | Sin esto el modelo se entrenaría y puntuaría contra una tabla vacía: la rama ML del churn habría seguido diciendo "todos sin historial" con el resto ya corregido |
| 8 | `ml/entrenar` **(agregado)** | el LABEL "silencio total" (0 asistencias en la ventana futura) | `asistencias_entre_por_alumno` | Sin esto el label habría marcado a TODOS como abandonados (con la tabla vacía, 0 asistencias siempre) |

## 3. La definición única (todo sale de `services/asistencia_real.py`)

| Pieza | Para qué |
|-------|----------|
| `condicion_asistio(reserva)` | El predicado ORM: `reservas.asistio = true` **+** la reserva no cancelada (`no_cancelada`, la lista compartida de `shared.estados`). Se define UNA vez |
| `ultima_asistencia_por_alumno(db, tenant, ids, hasta=None)` | "¿Cuándo entrenó por última vez?" (`MAX(clases.fecha)`). `hasta=` es el as-of del ML |
| `asistencias_entre_por_alumno(db, tenant, ids, desde, hasta)` | "¿Cuántas clases hizo en la ventana?" (días inclusivos, fecha de la CLASE). Es el reemplazo del `count(asistencias.id)` |
| `sql_cte_asistencias()` | El espejo **en SQL crudo** para las consultas de BI que no pasan por el ORM: se pega como CTE (`WITH {sql_cte_asistencias()} SELECT ...`) y expone las mismas columnas que la tabla histórica (`id`, `usuario_id`, `clase_id`, `tenant_id`, `fecha`), así que el resto de la consulta queda igual. La lista de cancelaciones sale de `shared.estados.lista_sql()` (nunca escrita a mano) |

Decisiones de criterio (para no cambiar la SEMÁNTICA al cambiar la fuente):
- **Conteo de reservas**, no de clases distintas: es el mismo criterio que el `asistentes` del BI
  (`func.count(Reserva.id)` con `asistio == True`).
- **Fecha de la CLASE**, nunca la de la reserva (el alumno reserva días antes).
- **Ventanas inclusivas** en las dos puntas (`desde <= fecha <= hasta`), como el `count` viejo.
- **"Sin historial" = `None`/0**: no se inventa una fecha; el correo de inactividad sigue salteando
  a quien nunca asistió y el churn sigue midiendo desde el alta (fix del 999 de `kpis_populate`).

## 4. Qué esperar en los números (estimación, no medida)

No pude medir contra la base: las credenciales de la rama TEST fallan en este entorno
(`password authentication failed for user 'neondb_owner'`). Lo que se puede afirmar por lectura del
código:

1. **"Plan sin usar" baja en picada.** Con `asistencias` vacía, `ultima = None` y
   `es_plan_sin_usar()` devuelve `True` para TODO alumno con plan vigente de más de 5 días: el
   panel de Fidelización y la recomendación del churn lo marcaban a casi todo el padrón. Ahora sólo
   queda quien realmente no estrenó el plan.
2. **Churn:** `dias_inactivo` deja de ser "días desde el alta" para todos y pasa a ser el real →
   bajan los CRÍTICOS "falsos" (alumnos nuevos) y suben los que abandonaron y volvieron a
   clasificarse desde su alta.
3. **Campaña de inactividad:** la audiencia pasa de "sólo quien tenga fila de seed" a los ausentes
   reales de 7+ días. En la base de prueba actual eso puede ser MUCHA gente: **probar antes de
   disparar** (ver §6).
4. **BI:** `/bloques-horarios` deja de dar 0 asistencias por bloque (la ocupación se activa) y
   `/cohortes` deja de dar 0% de retención; el embudo "clase de prueba ejecutada" de
   `populate` deja de estar en 0.
5. **Buscador del Admin:** aparece la última asistencia real (antes "nunca" para todos); si algo
   ordena por esa columna, el orden cambia.
## 5. Pruebas

**Guards nuevos (sin base, corren en 2 s):**

```
cd backend
py -3.12 -m pytest tests/test_asistencia_fuente_unica.py tests/test_riesgo_fuente_real.py -q --noconftest
# 13 passed + 1 skipped (el skip es la integración contra la base TEST)
```

`tests/test_asistencia_fuente_unica.py` (nuevo) fija, sin base:
- **A.** sólo el ESCRITOR (`fidelizacion.py`) y el registro de modelos importan `Asistencia`; el
  flujo de guardado no se tocó.
- **B.** los 8 lectores pasan por `asistencia_real`; el predicado vive UNA sola vez
  (`condicion_asistio`); cada envoltorio *delega* (no reimplementa); las 4 consultas crudas pegan el
  CTE y la lista de cancelaciones sale de `shared.estados`.
- **C.** la semántica no cambió: ventanas inclusivas, conteo de reservas, "sin historial" sigue
  salteando el correo de inactividad y el churn sigue cayendo al alta.

**Guards existentes actualizados** (fijaban la definición vieja):
- `test_riesgo_fuente_real.py::test_b1…` (el predicado se movió a `condicion_asistio`).
- `test_usuarios_buscador_membresia.py::test_c2…` (el buscador ya no puede leer `asistencias`).

**Seeds de integración migrados a la fuente real** (sembraban `INSERT INTO asistencias`, que ya no
alimenta ningún cálculo; ahora crean una **clase + reserva** y limpian lo suyo):
- `test_fidelizacion_plantillas.py` (escenario + `_fijar_dias`, que ahora mueve la fecha de la CLASE).
- `test_pase_regreso_no_es_membresia.py` (el escenario "inactivo hace 45 días").
- `test_plan_sin_usar.py`: no siembra asistencia (es su caso "cero asistencias") — sólo se dejó su
  limpieza de la tabla histórica, que ya es un no-op.

**Verificado ahora (11 suites, 113 passed):** `test_asistencia_fuente_unica`,
`test_riesgo_fuente_real`, `test_alertas_envio_unico`, `test_alertas_log_conteos`,
`test_alertas_dedupe_alumno`, `test_scheduler_alertas_tenants`, `test_usuarios_buscador_membresia`,
`test_admin_prueba_nuevos`, `test_pedidos_aviso_retiro`, `test_vigencia_plan_chile`.

**Lo que NO se pudo correr acá** (y por qué):
- Los tests que **escriben/leen la base** (`test_plan_sin_usar`, `test_fidelizacion_plantillas`,
  `test_pase_regreso_no_es_membresia`, `test_notif_dia_chile::test_b*`,
  `test_vigencia_plan_chile::test_b*`): las credenciales de la rama TEST fallan en este entorno
  (`password authentication failed for user 'neondb_owner'`) → `OperationalError`.
- `test_admin_prueba_nuevos.py::test_g3…`: falla **antes** de esta tanda (espera
  `label="Alumnos activos"` en `InicioMobileAdmin.jsx`, donde ese texto ya es un subtítulo). No se
  tocó ningún archivo del frontend en esta tanda.

## 6. El envío de correos: cómo probarlo (y qué probé)

El cambio hace que la campaña de inactividad **empiece a incluir gente que antes excluía**, así que
no se dispara sin probar. Para eso queda un script nuevo:

```
cd backend
# 1) SIMULACRO (sin correo real): valida el armado y el camino completo hasta `_enviar`
py -3.12 scripts/alertas_inactividad_test.py --correo tu-correo@gmail.com

# 2) ENVÍO REAL a una dirección controlada (nunca a un alumno real)
$env:EMAIL_MODO='real'; py -3.12 scripts/alertas_inactividad_test.py --correo tu-correo@gmail.com
```

- `.env.test` trae `EMAIL_MODO=noop`: ese es el modo seguro por defecto, y el script lo dice en
  pantalla antes de mandar. El envío real hay que pedirlo EXPLÍCITAMENTE.
- El script manda **un** correo con `registrar=False` (no ensucia `notificaciones_enviadas`) y
  **no dispara la campaña**: `enviar_alertas_inactividad` es el que recorre el padrón, y para
  probarlo hace falta la base (ver el docstring del script).
- La dirección de prueba del repo (`scripts/enviar_emails_test.py`) es `jesusmiranda26@gmail.com`:
  es la que se usó para el simulacro.

**Resultado de esta tanda:**
- **Simulacro (`EMAIL_MODO=noop`): OK** → el armado del correo y el camino completo hasta `_enviar`
  funcionan; el correo **no** sale y el script lo avisa en pantalla.
- **Envío real (`$env:EMAIL_MODO='real'`): OK** → el correo de inactividad se entregó por Gmail a
  `jesusmiranda26@gmail.com` (la dirección de prueba que ya usaba `scripts/enviar_emails_test.py`),
  sin error SMTP (`ULTIMO_ERROR_SMTP` vacío). Fue **un** correo, a una dirección controlada y con
  `registrar=False`.
- **Lo que sigue pendiente:** la campaña completa (`enviar_alertas_inactividad`, la que recorre el
  padrón) contra la base: eso es lo único que valida "QUIÉN entra" con los datos reales.

## 7. Pendientes

1. **Credenciales de la rama TEST** para (a) correr los tests de integración con los seeds nuevos,
   (b) medir los números reales antes/después (`SELECT count(*) FROM asistencias` contra la
   asistencia real) y (c) disparar el correo de inactividad contra la base (la última prueba que
   falta de la campaña).
2. **Reentrenar el churn** (`ml/entrenar.py` / `POST /kpis/populate/predictions`): el modelo en uso
   se entrenó con la tabla vacía (features degenerados).
3. **`.env.test` en `EMAIL_MODO=noop`** es lo que evita mandar correos por accidente: si algún día
   se quiere una campaña real, es una decisión explícita.
4. La tabla `asistencias` sigue existiendo con su escritor (`POST /fidelizacion/registrar`). Si se
   quiere retirar del todo, es un paso aparte (migración + borrar el endpoint + el modelo).
