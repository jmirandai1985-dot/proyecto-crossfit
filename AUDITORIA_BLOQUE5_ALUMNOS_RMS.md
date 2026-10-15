# Auditoría Bloque 5 — "Alumnos & RMs" + RMs en la ficha del coach

Fecha: 2026-10-15 · Autor: sesión de auditoría
**Decisión aprobada por Jebbus (15-oct): agregar "Ver Perfil" al tab Alumnos y los RMs a
`AlumnoFichaCoach`.** Implementado y verificado. El 403 del admin
(`historial_alumno.py`) queda como está: es intencional.

## 1. Evidencia de datos (SQL solo lectura contra PRODUCCIÓN)

Script: `%TEMP%\bloque5\rm_detalle.py` (y `rms_counts.py`), engine del backend, sólo `SELECT`:

```
cd backend
$env:ENVIRONMENT='production'; $env:PYTHONPATH=(Get-Location).Path
python "$env:TEMP\bloque5\rm_detalle.py"
```

Host: `ep-nameless-sound-b6km6wyi-pooler.c-2.sa-east-1.aws.neon.tech` (base de producción).

**Estado del dato en el box (esto es el fondo del bloque):**

| movimiento | categoría (BD) | filas | alumnos | `peso_kg` min-max |
|---|---|---|---|---|
| Air Runner | `metabolico` | 6 | 1 | **1,0 – 530,0** |
| Clean (Cargada) | `fuerza` | 4 | 2 | 100 – 160 |
| Sled Push | `cardio` | 3 | 1 | 1,0 – 1,0 |
| Chest to Bar (C2B) | `gimnastico` | 1 | 1 | 10 |
| Kipping Pull-up | `gimnastico` | 1 | 1 | 1,0 |
| Strict Pull-up | `gimnastico` | 1 | 1 | 15 |
| Snatch (Arrancada) | `fuerza` | 1 | 1 | 100 |

- **17 filas de RM en total, de sólo 2 alumnos** (`Alumno Demo` id 5 con 16, `fanny carrasco`
  id 9 con 1) **sobre 364 alumnos activos → 0,5%**.
- El `peso_kg` de cardio/máquinas es un **dummy** (Air Runner tiene 1,0 y 530,0; Sled Push 1,0).
  Ese número no significa nada: la medida real está en `km`/`minutos`/`vueltas`/`calorias`
  (`rms_service.py:63-87` `_unidad_y_valor`).

## 2. Qué se implementó

| archivo:línea | cambio |
|---|---|
| `frontend/src/pages/coach/DashboardCoach.jsx:801-835` | la fila del tab Alumnos deja de ser UN `<button>` (botón dentro de botón = HTML inválido) y pasa a `<div>` con la tarjeta clickeable + **"Ver Perfil"** (`data-testid="btn-ver-perfil"`, el MISMO que ya usa el tab Riesgo en `:1036`) → `setFichaAlumnoId(alumno.id)` |
| `frontend/src/pages/coach/DashboardCoach.jsx:24-27, 861, 864` | el valor del RM del panel usa **`formatResultadoRM()`** (antes `{rm.peso_kg} kg` → mostraba "530 kg" en un Air Runner) y la fecha `fmtFechaCortaChile` |
| `frontend/src/components/AlumnoFichaCoach.jsx:15-21, 44-49` | la ficha pide `useRmsAlumno(alumnoId)` → `GET /historial-rm/alumnos/{id}/rms` (el MISMO endpoint coach-scoped del panel: sin permisos nuevos) |
| `frontend/src/components/AlumnoFichaCoach.jsx:137-196` | sección **"RMs · mejor marca por movimiento"** con 4 estados: cargando / error + "Reintentar" / lista / **"Sin RMs registrados"** |
| `frontend/src/components/AlumnoFichaCoach.jsx:57-60, 71` | `max-h-[90vh]` + cuerpo `overflow-y-auto min-h-0`: la ficha entra en 375×568 y "Cerrar" queda siempre visible |
| `frontend/src/components/AsistenciaClases.jsx:339` | `data-testid="aviso-asistencia"` en el banner (para el cierre del punto 1) |

**No se inventó ningún modal nuevo**: la ficha es la misma que abre el tab Riesgo
(`fichaAlumnoId` → `<AlumnoFichaCoach>`, `DashboardCoach.jsx:1052-1059`).
**No se tocó** `historial_alumno.py` (el 403 del admin sigue igual).

### Por qué `formatResultadoRM` y no `peso_kg`

`RMPorMovimiento` (`backend/app/schemas/historial_rm.py:86-107`) no manda `categoria`, así que el
front usa la fuente única `frontend/src/utils/rm.js` (H-03): gimnasia → reps x series, cardio →
km/min/vueltas, máquinas → cal/km/vueltas, fuerza → kg. Con `peso_kg` a mano, un Air Runner
mostraba "530 kg" y un Kipping Pull-up "1 kg" (en vez de "10 reps x 3 series").

## 3. Verificación con capturas y mediciones

Pantalla nueva del harness (`scripts/capturas-bloque2.mjs:519-550`) con fixtures que usan los
valores REALES de producción (incluido el Air Runner con `peso_kg` dummy):

```
cd frontend
$env:PANTALLA='perfil-alumnos'; node scripts/capturas-bloque2.mjs
```

Salida real (**5/5 capturas · 0 errores de consola · `RESULTADO: OK`**):

```
mockup/_audit/bloque5-perfil-alumnos/
  01-movil-fila-ver-perfil.png          390x844
  02-movil-ficha-con-rms.png            390x844
  03-movil-375x568-ficha-con-rms.png    375x568
  04-escritorio-ficha-con-rms.png       1280x900
  05-movil-ficha-sin-rms.png            390x844   (alumno sin marcas)
```

Mediciones duras de la ficha (`MEDIR_FICHA`, `capturas-bloque2.mjs:352-392`; ahora también mide
`capa_tapa_header`, ver hallazgo 5):

| caso | `card` | ¿dentro del viewport? | cuerpo scrollea | "Cerrar" clickeable | RMs en la lista |
|---|---|---|---|---|---|
| 390×844 (teléfono) | 52 → 793 | sí | no | sí | 4 |
| **375×568 (pantalla chica)** | 28 → 540 | **sí** | **sí** | **sí** | 4 |
| 1280×900 (escritorio) | 88 → 813 | sí | no | sí | 4 |
| 390×844 · alumno sin RMs | 112 → 732 | sí | no | sí | 0 (`sin_rms: true`) |

Valores renderizados (lo que prueba que el `peso_kg` dummy ya no se muestra):

```
["160 kg", "10 reps x 3 series", "300 cal, 3.5 km, 10 vueltas", "0.4 km, 1 vueltas"]
```

Tests de lógica re-corridos después del cambio (todos verdes): `test:coach-subtabs`,
`test:coach-resumen`, `test:walkin`, `test:fidelizacion`, `test:alumnos`, `test:menu`,
`test:franjas`. Lint (`oxlint`): **0 errores** (28 warnings preexistentes, ninguno de estos archivos).

## 4. Hallazgos nuevos (no bloquean; van a backlog)

1. ✅ **RESUELTO (15-oct, tras la aprobación del ítem 2 del reporte)**: `/alumnos/{id}/rms` no
   exponía `categoria`, así que el front caía en la heurística por nombre
   (`utils/rm.js:39-43`), que clasifica "Sled Push" como `metabolico` (la BD dice `cardio`) y por
   eso su valor salía **"0.4 km, 1 vueltas"** sin los minutos. Ahora `categoria` va en
   `CAMPOS_SCHEMA` + los dos schemas y **también** en la lista plana (`GET /historial-rm`).
   Detalle, evidencia contra PROD y tests: **`AUDITORIA_RM_CATEGORIA_CONTRATO.md`**. El valor del
   Sled Push en las 4 tomas pasó a **"0.4 km, 2 min, 1 vueltas"**.
2. **"1 vueltas" (plural con 1)** viene de la fuente única H-03 (`utils/rm.js:79-99`), así que
   también se ve en la Pizarra del alumno. **No se tocó**: cambiar el helper afecta 3 pantallas.
3. **El dummy `peso_kg` sigue vivo en el backend**: el schema lo declara obligatorio
   (`peso_kg: float`), así que nunca llega `null` y su valor no significa nada en
   cardio/máquinas. El front ya lo ignora (correcto) — sólo queda anotado.
4. **0,5% de alumnos con RMs**: es un problema de **datos + producto**, no de código. Mientras no
   se carguen marcas (importador o pantalla del coach), el tab y la ficha van a decir "Sin RMs
   registrados" para casi todo el padrón. Decisión pendiente del negocio.
5. ✅ **RESUELTO (15-oct, aprobado)**: `frontend/src/components/Layout.jsx` tenía el wrapper de
   `{children}` con `relative z-10`, y eso es un **contexto de apilamiento**: ningún overlay de
   ninguna pantalla podía pintar sobre el header (`relative z-30`). Se veía en estas mismas tomas
   (a 375×568 los primeros 37 px de la tarjeta quedaban detrás de la barra y el header no se
   atenuaba con el fondo del modal). El wrapper ahora es sólo `relative` y está medido:
   `capa_tapa_header` pasó de `false` a `true` en las 4 tomas de la ficha, con `card` / `cerrar`
   clavados iguales. Detalle y alcance app-wide (51 overlays):
   **`AUDITORIA_LAYOUT_ZINDEX_MODALES.md`**.

## 5. Cómo re-verificar

```
cd frontend
$env:PANTALLA='perfil-alumnos'; node scripts/capturas-bloque2.mjs          # 5 capturas + mediciones
$env:PANTALLA='perfil-alumnos'; $env:SOLO='02,05'; node scripts/capturas-bloque2.mjs   # sólo dos
```

La pantalla `menu` (Bloque 8) sigue corriendo igual: el tab Alumnos no cambió su lógica de datos
(sólo el markup de la fila), y las 7 capturas del menú se re-corrieron verdes.

