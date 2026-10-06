# `usuarios.activo` vs `usuarios.estado` — diagnóstico y propuesta de unificación

> Documento de **SOLO DIAGNÓSTICO**: NO se cambió ninguna línea de código para escribirlo.
> Mide el estado real en la rama **TEST** y propone un camino, con riesgos.

## 1. Resumen

La tabla `usuarios` tiene **dos campos para decir casi lo mismo**:

- **`estado`** (texto): `pendiente_activacion` | `activo` | `rechazado` | `baja`.
  **Es la fuente de verdad** (lo dice el propio código: `auth.py:81-82`,
  `usuarios.py:431-432`).
- **`activo`** (booleano): bandera **heredada** de cuando "estar activo" era un sí/no. Hoy
  es **derivado**: tiene que valer exactamente `estado = 'activo'`.

Un **CHECK de la migración 034** mantiene los dos sincronizados a nivel base de datos:
`ck_usuarios_activo_estado`: `CHECK (activo = (estado::text = 'activo'))`. Es decir, la
propia base **impide** que se contradigan.

## 2. Dónde se usa cada uno (en el código)

### 2.1 Escrituras que sincronizan AMBOS (correcto)

| Archivo | Qué hace |
|---|---|
| `app/api/v1/alumnos.py:351-352` | aprobar alumno: `activo = True` **y** `estado = "activo"` |
| `app/api/v1/alumnos.py:457-458` | rechazar alumno: `estado = "rechazado"` **y** `activo = False` |
| `app/api/v1/usuarios.py:434-435` | soft delete: `estado = "baja"` **y** `activo = False` |
| `scripts/crear_usuarios_demo.py:555` | alta/upsert: `activo = true, estado = 'activo'` juntos |
| `scripts/crear_usuarios_test.py:106`, `seed_usuarios_prueba.py:96`, `seed_ml_data*.py` | inserts con los dos campos juntos |

### 2.2 Lecturas por `estado` (la fuente de verdad)

| Archivo | Uso |
|---|---|
| `app/api/v1/auth.py:84` | **login**: bloquea si `estado != "activo"` (mensaje por caso) |
| `app/api/v1/auth.py:144` | login alterno / selección: filtra `estado == "activo"` |
| `app/api/v1/fidelizacion.py:73,162,310,429,713` | listados de alumnos a contactar: `estado == "activo"` |
| `app/api/v1/kpis_populate.py:670` | `estado == "activo"` en el cálculo de KPIs |
| `app/core/dependencies.py:100` / `app/api/v1/alumnos.py:109-110` | la API DEVUELVE las dos: `estado` **y** `activo` |

### 2.3 Lecturas por `activo` (heredadas, redundantes pero correctas)

Como el CHECK garantiza que `activo == (estado == 'activo')`, estas lecturas dan **lo
mismo** que leer `estado`; son una segunda forma de decir lo mismo:

| Archivo | Uso |
|---|---|
| `app/api/v1/dashboard.py:78` | `Usuario.activo == True` |
| `app/services/asistencia_service.py:281,305,405` | `Usuario.activo == True` |
| `app/services/email_service.py:681,1079` | destinatarios de correo: `Usuario.activo == True` |
| `scripts/seed_anual_prod.py:1469` | `Usuario.activo == True` |
| `scripts/sync_test_from_prod.py:306`, `maintenance/mantenimiento_cloud.py:856-876` | **SQL crudo** `u.activo = true` |
| `scripts/aplicar_overrides_test.py:27` | **SQL crudo** `UPDATE usuarios SET activo=true WHERE id=7` |

> ⚠️ `app/services/scheduler.py:196-199` deja una pista HISTÓRICA: "en PROD hay alumnos con
> `estado='activo'` y `activo=false`". Eso describe el estado **antes** de la migración 034
> (por eso el scheduler NO deriva los tenants de `Usuario.activo`, sino de `tenants.activo`).
> Con el CHECK vigente esa combinación **ya no puede existir**.

### 2.4 Frontend

## 3. Conteo en TEST (medido el 2026-04-10)

Consulta de **solo lectura** contra la rama TEST
(`ep-summer-river-b6c8fj2f...sa-east-1...neon.tech`, la misma del `.env.test`):

```
SELECT
  count(*)                                                        AS total,
  count(*) FILTER (WHERE activo AND estado <> 'activo')           AS activo_no_activo,
  count(*) FILTER (WHERE NOT activo AND estado = 'activo')        AS inactivo_activo
FROM usuarios;
```

| Métrica | Valor |
|---|---|
| usuarios totales | **416** |
| `activo = true` pero `estado <> 'activo'` (contradicción A) | **0** |
| `activo = false` y `estado = 'activo'` (contradicción B) | **0** |
| `activo = true` | 370 |
| `estado = 'activo'` | 370 |
| CHECK `ck_usuarios_activo_estado` presente en TEST | **sí** (`CHECK ((activo = ((estado)::text = 'activo'::text)))`) |

Desglose por rol/estado:

| rol | estado | activos | total |
|---|---|---|---|
| administrador | activo | 3 | 3 |
| alumno | activo | 364 | 364 |
| alumno | baja | 0 | 45 |
| coach | activo | 3 | 3 |
| coach | baja | 0 | 1 |

**Conclusión:** en TEST hay **0 registros contradictorios** (y no pueden aparecer mientras
el CHECK esté). Los 370 con `activo = true` coinciden 1:1 con los 370 con
`estado = 'activo'`.

## 4. Propuesta de unificación (con riesgos)

**Objetivo:** que quede UNA sola palabra para "habilitado", `estado`. No hay que hacer nada
urgente: hoy los dos coinciden por construcción. La deuda es de **claridad**, no de datos.

### Fase 1 — `estado` es la fuente de verdad (YA HECHO)
- Migración 034 + CHECK `ck_usuarios_activo_estado`; login por `estado`; escrituras que
  sincronizan ambos. **No tocar.**

### Fase 2 — Migrar las LECTURAS de `Usuario.activo` a `Usuario.estado` (barato)
Cambiar en el ORM (`dashboard.py:78`, `asistencia_service.py:281/305/405`,
`email_service.py:681/1079`, `seed_anual_prod.py:1469`) y en el **SQL crudo**
(`sync_test_from_prod.py:306`, `mantenimiento_cloud.py:856-876`) `Usuario.activo == True`
por `Usuario.estado == "activo"`. Mismo resultado (el CHECK lo garantiza), pero una sola
definición.
- **Riesgo:** bajo. Cada cambio es mecánico y verificable. Riesgo real: **olvidar** uno de
  los SQL crudos de mantenimiento/sync (no los cubre el ORM ni los tests de la app).
- **Cómo se prueba:** tests existentes + un `grep` de `\.activo` sobre `usuarios`.

### Fase 3 — Dejar de ESCRIBIR/exponer `activo` (mediano)
1. Que las APIs dejen de devolver `"activo"` (`alumnos.py:110`, `dependencies.py:100`) —
   **solo** después de confirmar que el front no lo usa (hoy no lo usa).
2. Escribir únicamente `estado` (el CHECK se cae si `activo` no se actualiza) → hay que
   **aflojar el CHECK** creando un `DEFAULT`/trigger que derive `activo` de `estado`, o
   directamente dejar `activo` como columna generada.
- **Riesgo:** MEDIO. Tocar el CHECK o los writers afecta a TODOS los scripts (seed, demo,
  overrides) y al mantenimiento. Un writer que quede escribiendo solo `activo` falla el
  CHECK → INSERT/UPDATE roto en PROD.

### Fase 4 — Eliminar la columna (largo plazo, opcional)
`ALTER TABLE usuarios DROP COLUMN activo` + borrar el CHECK.
- **Riesgo:** ALTO hasta que la Fase 2/3 estén 100% cerradas. La columna la usa SQL crudo
  fuera del ORM (`maintenance/`, `scripts/`), backups y posiblemente consultas a mano en
  Neon. Un `DROP COLUMN` con un lector vivo rompe ese job en silencio.
- **Precondición:** `grep` sin resultados de `usuarios.activo`/`u.activo` en TODO el repo
  (incluidos `maintenance/`, `scripts/`, `sql/`, `n8n/`) y una corrida verde de los jobs.

## 5. Qué NO hacer

- **No** copiar el patrón "escribir solo `activo`" en código nuevo: `aplicar_overrides_test.py:27`
  hace `UPDATE usuarios SET activo=true` **sin** `estado`. Funciona solo si ese usuario ya
  tiene `estado='activo'`; si no, el CHECK lo **rechaza**. Es un script de overrides de TEST,
  no un ejemplo a seguir.
- **No** derivar la lista de boxes/tenants de `Usuario.activo` (ya lo aprendió el scheduler:
  usa `tenants.activo`).
- **No** aflojar el CHECK sin migrar antes TODOS los writers (Fase 3), o vuelven las
  contradicciones que la 034 vino a matar.

## 6. Resumen para decidir

| | `estado` | `activo` |
|---|---|---|
| Rol | **fuente de verdad** | derivado (`estado == 'activo'`) |
| Valores | 4 (incluye `pendiente_activacion`, `rechazado`, `baja`) | 2 |
| Contradicciones en TEST | — | **0** (el CHECK lo impide) |
| Acción sugerida | conservar y usar siempre | migrar lecturas → `estado`; quitar al final |

