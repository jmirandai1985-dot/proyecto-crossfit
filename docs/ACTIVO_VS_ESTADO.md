# `usuarios.activo` vs `usuarios.estado` — diagnóstico y propuesta de unificación

> Documento de **SOLO DIAGNÓSTICO** (T11): NO se cambió ninguna línea de código para escribirlo.
> Mide el estado real en la rama **TEST** y propone un camino, con riesgos.
>
> **T12 (2026-04-10): Fase 2 IMPLEMENTADA.** Todas las LECTURAS de `usuarios.activo` pasaron a
> `usuarios.estado` (ORM y SQL crudo). Lo fija el guard de fuente
> `backend/tests/test_activo_estado_unificacion.py`. El resto del documento se conserva como
> diagnóstico; donde la realidad cambió, el texto lo dice. **La Fase 3 sigue BLOQUEADA** (ver
> 2.4: el front sí consume `activo`).

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

### 2.3 Lecturas por `activo` — **MIGRADAS a `estado` en T12**

Como el CHECK garantiza que `activo == (estado == 'activo')`, estas lecturas daban **lo
mismo** que leer `estado`: eran una segunda forma de decir lo mismo. T12 las migró todas.

| Archivo (antes) | Uso |
|---|---|
| `app/api/v1/dashboard.py:78` | `Usuario.activo == True` (alumnos del box) |
| `app/services/asistencia_service.py:281,305,405` | coach del box y alumnos a evaluar |
| `app/services/email_service.py:681,1079` | destinatario admin de los avisos |
| `app/services/metricas_service.py:52` | **SQL crudo** `_vigente_sql()` (cohorte/MRR del BI) |
| `app/services/reportes_service.py:267,486` | **SQL crudo** (histórico mensual y KPI vivo) |
| `app/services/alertas_email_service.py:86,117,160,211,248` | **SQL crudo** (5 alertas por correo) |
| `app/api/v1/clases.py:205`, `app/api/v1/reportes.py:124` | **SQL crudo** (fallback de coaches / KPI) |
| `app/api/v1/supervision.py:542` | **SQL crudo** (coaches de la disciplina) |
| `scripts/seed_anual_prod.py:1469` | `Usuario.activo == True` (coaches del plan) |
| `scripts/sync_test_from_prod.py:306`, `maintenance/mantenimiento_cloud.py:856-876,1046,1097,1110,1118`, `maintenance/reporte_estadisticas.py:25` | **SQL crudo** `u.activo = true` |
| `scripts/aplicar_overrides_test.py:27` | **escritor**: `UPDATE usuarios SET activo=true` → ahora `estado='activo', activo=true` |

> Los tests que fijaban el SQL textual se ajustaron donde la prohibición era sobre el estado de
> la **suscripción** (`s.estado = 'activo'`) y no sobre el del alumno:
> `test_mantenimiento_cloud.py`, `test_reporte_historico_mensual.py`, `test_mrr_historico.py`.

### 2.4 Frontend — usa `activo` (por eso la Fase 3 no está lista)

El diagnóstico original decía que el front no lo usaba. **Era falso**:

| Archivo | Uso |
|---|---|
| `frontend/src/components/AlumnoFichaModal.jsx:38` | pide `/planes?activo: true` (planes, no usuarios) |
| `frontend/src/components/AlumnoFichaModal.jsx:90-96` | **lee `d.activo`** de `GET /usuarios/{id}`: marca el conflicto «Inactivo (estado: activo)» y el badge verde |
| `frontend/src/pages/admin/Alumnos.jsx:157,185` | respaldo `u.estado \|\| (u.activo ? 'activo' : 'baja')` |
| `frontend/src/pages/admin/Alumnos.jsx:221` | al guardar manda **solo** `estado` (el backend deriva `activo`) |

⇒ Antes de la Fase 3 hay que cambiar el front (el test `test_activo_estado_unificacion.py::test_c`
falla ese contrato a propósito, para que nadie saque la clave por error).

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

### Fase 2 — Migrar las LECTURAS de `Usuario.activo` a `Usuario.estado` — **HECHA (T12)**

La lista REAL de sitios fue más larga que la del diagnóstico: además del ORM
(`dashboard.py:78`, `asistencia_service.py:281/305/405`, `email_service.py:681/1079`,
`seed_anual_prod.py:1469`) había **11 SQL crudo** que el inventario inicial no tenía
(`metricas_service.py:52`, `reportes_service.py:267/486`, `alertas_email_service.py` ×5,
`clases.py:205`, `reportes.py:124`, `supervision.py:542`, más los de
`maintenance/mantenimiento_cloud.py` y `maintenance/reporte_estadisticas.py:25`) — ver 2.3.
- **Riesgo (realizado):** bajo. El riesgo que se materializó fue el previsto: **olvidar** los SQL
  crudos. Se encontraron con un `grep` de `u\.activo` sobre `backend/app`, `backend/maintenance`
  y `backend/scripts`, no con los tests (varios de esos caminos sólo corren con base).
- **Cómo se probó:** `test_activo_estado_unificacion.py` (guard de fuente, aislado) + los tests
  que fijaban el SQL textual (`test_mantenimiento_cloud.py`, `test_reporte_historico_mensual.py`,
  `test_mrr_historico.py`, ajustados donde prohibían `estado = 'activo'` de la **suscripción**).

### Fase 2b — Los ESCRITORES siguen escribiendo los dos campos (a propósito)

`alumnos.py` (aprobar/rechazar), `usuarios.py` (baja), `mantenimiento_cloud.py:1757` y
`aplicar_overrides_test.py` escriben `estado` **y** `activo`. Es obligatorio mientras el CHECK
exista: escribir sólo uno lo viola. El caso de `aplicar_overrides_test.py` se corrigió en T12
(antes hacía `SET activo=true` a secas y dependía de que el usuario ya estuviera activo).

### Fase 3 — Dejar de ESCRIBIR/exponer `activo` (mediano)
1. Que las APIs dejen de devolver `"activo"` (`alumnos.py:110`, `dependencies.py:100`,
   `historial_alumno_service.py:1054`) — **solo** después de migrar el **frontend**, que hoy SÍ
   lo consume (ver 2.4: `AlumnoFichaModal.jsx` lo usa para pintar el badge y detectar el
   conflicto). Antes de esto, `test_activo_estado_unificacion.py::test_c` lo impide a propósito.
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
| Estado del código | lo **leen** todas las consultas (Fase 2, T12) | sólo se **escribe** (junto a `estado`) y se **expone** en la API |
| Quién lo sigue leyendo | — | el detector A.1(a) y el **front** (⇒ Fase 3 bloqueada) |
| Acción sugerida | conservar y usar siempre | migrar el front → dejar de exponerlo → quitarlo (Fases 3-4) |

