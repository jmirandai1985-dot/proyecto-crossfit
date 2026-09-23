# MIGRACIÓN DE PROD A UN PROYECTO NEON NUEVO

**Estado:** ✅ **PROD migrado al proyecto nuevo "produccion2.0"** (2026-09-23). Falta solo el PASO 3 de Render (lo hace Jebbus).
Última actualización: 2026-09-23.

## Contexto

- PROD vive hoy en el proyecto **viejo** (`ep-withered-silence-acly7gq5`, cuenta Neon vieja): ese proyecto **agotó la cuota** y la base está inaccesible.
- TEST ya está migrado a la cuenta nueva y **sano** (verificado 2026-09-23): `ep-odd-smoke-b6f31576`, 36 tablas, `alembic 033_trim_tenants`, clases 1480 / asistencias 4101 / transacciones 478 / usuarios 115.
- El backup de PROD más reciente disponible es **`backend/backups/neon_backup_prod_20260917_060659.sql`** (17/09/2026 06:07, 1.42 MB, 36 tablas con datos, dump completo).
  ⚠️ **Se pierde la actividad de PROD entre el 17/09 y la caída** (la base no responde, no se puede hacer un `pg_dump` fresco). No hay otra copia más nueva.
- Ese dump está en la migración **031_trim_disciplinas** → después del restore hay que correr `alembic upgrade head` (aplica **032_cupo_original_clases** y **033_trim_tenants**).

---

## PASO 1 — ⏸ LO HACE JEBBUS (dashboard de Neon)

1. Entrar a la **cuenta Neon NUEVA** (la misma del proyecto de TEST) → **New Project**.
2. Nombre sugerido: `proyecto-crossfit-prod`. Región: **AWS · São Paulo (sa-east-1)**. Postgres: **18**.
   ⚠️ **NO** reusar el proyecto de TEST ni crear una *branch* dentro de él: PROD tiene que quedar aislado.
3. Copiar la connection string **con pooler** (botón *Connect* → *Connection string*):
   `postgresql://neondb_owner:<PASSWORD>@ep-<id>-pooler.c-2.sa-east-1.aws.neon.tech/neondb?sslmode=require`
4. Pasársela a Cline (con la contraseña) y avisar.

## PASO 2 — CLINE (con la URL en mano)

1. Actualizar **`backend/.env`** (PROD — nunca `.env.test`): `DATABASE_URL` = pooler, `DIRECT_URL` = el mismo host **sin** `-pooler`.
2. Restaurar el dump con `scripts/restaurar_backup.py` en **modo PROD explícito** (requiere confirmar el host a mano; el guard automático sólo autoriza endpoints TEST).
3. `ENVIRONMENT=production python -m alembic upgrade head` → 032 + 033.
4. Verificar los conteos contra la tabla de abajo y `GET /health` local contra esa base.

## PASO 3 — ⏸ LO HACE JEBBUS (dashboard de Render)

Servicio **`box-crossfit`** → *Environment* → editar y guardar:

| Variable | Valor nuevo |
|---|---|
| `DATABASE_URL` | connection string del **proyecto nuevo CON `-pooler`** |
| `DIRECT_URL` | la misma **SIN `-pooler`** |

Luego: **Manual Deploy → Deploy latest commit**. El `preDeployCommand` (`alembic upgrade head`) corre solo; si falla, Render aborta y deja la versión anterior (sin outage).

Verificar: `GET https://<servicio>.onrender.com/health` → `{"status":"healthy","database":"connected"}`.

---

## Conteos esperados después del restore (extraídos del dump 20260917)

| tabla | filas | | tabla | filas |
|---|---|---|---|---|
| asistencias | 4101 | | movimientos | 103 |
| clases | **1377** | | notificaciones | 3 |
| transacciones_financieras | 476 | | notificaciones_enviadas | 2 |
| usuarios | 110 | | password_reset_tokens | 2 |
| predictions_churn | 106 | | pedidos | 0 |
| segmentacion_alumnos | 106 | | planes | 16 |
| suscripciones | 105 | | predictions_forecast | 3 |
| horarios | 127 | | productos | 1 |
| auditoria | 2 | | reservas | 2 |
| churn_gestion | 1 | | retencion_alumnos | 0 |
| coach_disciplinas | 2 | | solicitudes_planes | 4 |
| cobertura_emergencia | 0 | | student_segments | 6 |
| configuracion_negocio | 0 | | tenants | 2 |
| daily_kpis | 13 | | wod_movimientos | 0 |
| disciplinas | 6 | | wods | 0 |
| historial_rm | 16 | | horarios_base | 0 |
| hitos_alumno | 0 | | ml_modelos | 3 |
| monthly_kpis | 1 | | alembic_version | 1 (031 → luego 033) |

> Nota: `clases` es 1377 en PROD y 1480 en TEST: son líneas temporales distintas (TEST tenía clases generadas de más).

---

## Comandos exactos del PASO 2 (ya probados en seco)

```powershell
cd backend
# 1) .env (PROD) con la URL nueva: DATABASE_URL=pooler  ·  DIRECT_URL=sin "-pooler"
# 2) restore (los 3 candados ya validados sin tocar ninguna base):
set ENVIRONMENT=production
python scripts\restaurar_backup.py backups\neon_backup_prod_20260917_060659.sql --prod --confirmo-host=<host-nuevo-sin-pooler>
# 3) migraciones que faltan (el dump está en 031):
python -m alembic upgrade head          # aplica 032_cupo_original_clases y 033_trim_tenants
# 4) verificación: los conteos de la tabla de arriba + GET http://localhost:8001/health
```

Candados del modo PROD (probados):

| Prueba | Resultado |
|---|---|
| `ENVIRONMENT=production` sin `--prod` | FATAL: "no es un endpoint TEST conocido → usá `--prod --confirmo-host=<host>`" |
| `--prod` sin `--confirmo-host` | FATAL: "agregá `--confirmo-host=<host>`" (imprime el host detectado) |
| `ENVIRONMENT=test` con `--prod` | FATAL: "definí `ENVIRONMENT=production`" |

## Archivos que mencionan el host VIEJO de PROD (actualizar en la migración)

- `backend/.env` → `DATABASE_URL` + `DIRECT_URL` *(crítico)*
- `docker-compose.prod.yml` → 2 comentarios (`# PRODUCCIÓN (ep-withered-silence)`)
- `backend/scripts/seed_ml_data_prod.py` (6 refs), `_diag_planes_prod.py`, `_aplicar_env_test_cierre.py`,
  `_validar_segmentacion.py`, `_kmeans_*.py` (scripts one-off con guard) → quedan en la lista de
  pendientes de "actualizar guards", no bloquean la migración.
- Docs: `DIAGNOSTICO_URGENTE_PROD_TEST.md`, `SECURITY.md`, `REPORTE_FINAL_SESION_AUTONOMA.md`.

## Pendiente menor detectado

- El servicio **`maintenance`** tiene su propia imagen (target `maintenance`) y **no** se reconstruyó
  en el rebuild de hoy (sólo `backend` y `frontend`): su código es de hace 4 semanas. No afecta a
  esta migración (sus cron usan `settings.DATABASE_URL` del `.env.test` y no se tocó su código), pero
  conviene un `docker compose build` completo algún día.

---

## HECHO (2026-09-23) - resultado de la migracion

| Paso | Resultado |
|---|---|
| 1. Proyecto Neon nuevo | OK: `produccion2.0` - project_id `lively-breeze-53844834` - branch `br-late-scene-b6muci2n` - endpoint `ep-nameless-sound-b6km6wyi` (PostgreSQL 18.6) |
| 2. `backend/.env` (PROD) | OK: `DATABASE_URL` (pooler) + `DIRECT_URL` (directa). Las credenciales viejas quedaron como comentario historico. |
| 3. Restore | OK: 36 tablas. El dump traia ACL de roles internos de Neon (`ALTER DEFAULT PRIVILEGES` x2 + `ALTER ... OWNER TO` x75) que `neondb_owner` no puede ejecutar: se agrego **sanitizacion automatica** al script (77 sentencias omitidas) y el restore entro limpio. |
| 4. `alembic upgrade head` | OK: `031_trim_disciplinas` -> **033_trim_tenants (head)** |
| 5. Conteos | OK: **36/36** contra el baseline del dump (clases 1377, asistencias 4101, transacciones 476, usuarios 110, suscripciones 105, planes 16, ...) |
| 6. `/health` local | OK: `200 {"status":"healthy","database":"connected"}` contra la base nueva (uvicorn en :8002 con `--lifespan off`, para no disparar las escrituras del startup). Los conteos quedaron identicos tras el chequeo: cero escrituras. |

Notas operativas:

- `uvicorn` **con** lifespan (el arranque normal, tambien en Render) genera las clases faltantes del rango `HOY + DIAS_ANTICIPACION` (en el dump faltan las posteriores al 15/10) y arranca el scheduler. Es el comportamiento normal de PROD: al primer arranque en Render se completaran esas clases.
- El `preDeployCommand: alembic upgrade head` de Render sera **no-op** (ya estamos en head).

## PASO 3 - VALORES EXACTOS PARA RENDER (los pega Jebbus)

> El repo es publico: las URLs con credenciales NO se escriben en este archivo. Los valores completos
> son los de `backend/.env` (PROD): `DATABASE_URL` y `DIRECT_URL`.

Servicio **`box-crossfit`** -> *Environment* -> editar **solo estas dos**:

| Variable | Que valor poner |
|---|---|
| `DATABASE_URL` | el de `backend/.env`: **pooler** del proyecto nuevo (`...@ep-nameless-sound-b6km6wyi-pooler.c-2.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`) |
| `DIRECT_URL` | el de `backend/.env`: el mismo host **sin** `-pooler` (`...@ep-nameless-sound-b6km6wyi.c-2.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`) |

Despues: **Manual Deploy -> Deploy latest commit**. Render corre `alembic upgrade head` (no-op) y levanta la
app; verificar con `GET https://<servicio>.onrender.com/health` -> `{"status":"healthy","database":"connected"}`.
Las demas variables (`ENVIRONMENT=production`, `DEBUG=false`, JWT, CORS, SMTP, etc.) NO cambian.

## PASO 4 - Migracion 034 (`activo` vs `estado`) en PROD

**Estado: NO aplicada a PROD todavia** (probada y verificada en TEST el 2026-09-23).

Que hace la migracion `034_activo_estado_check`:

1. **Backfill**: `UPDATE usuarios SET activo = (estado = 'activo') WHERE activo IS DISTINCT FROM (estado = 'activo')`.
   `estado` es la fuente de verdad del ciclo de vida (`pendiente_activacion | activo | rechazado | baja`);
   `activo` queda como flag derivado/legacy. Es idempotente: si no hay filas desincronizadas, no hace nada.
2. **Invariante en la BD**: `CHECK (activo = (estado = 'activo'))` (constraint `ck_usuarios_activo_estado`),
   para que no puedan volver a desincronizarse.

Como se aplica (automatico, sin paso manual extra):

- El `preDeployCommand: alembic upgrade head` de Render la ejecuta al hacer el deploy del commit que la incluye.
- No requiere ventana de mantenimiento: el backfill es instantaneo y el `ADD CONSTRAINT` valida la tabla
  (~110 filas en PROD).

> **Impacto real en PROD (verificado 2026-09-23, solo lectura):** la base nueva tiene **los mismos 7 conflictos**
> que TEST (`id` 2, 3, 4, 5, 6, 8 y 9: `activo=false` con `estado='activo'`). Como `get_current_user` filtraba
> `activo = true`, **esos 7 usuarios reales no pueden usar la app hoy** (el login funciona pero todos los
> endpoints devuelven 404 `Usuario no encontrado o inactivo`). El backfill de la 034 les devuelve el acceso sin
> tocar `estado`, que es lo que el admin ve en la UI (`Activo`).

Verificacion posterior (SQL de solo lectura):

```sql
-- 1) la constraint existe
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid = 'usuarios'::regclass AND conname = 'ck_usuarios_activo_estado';
-- esperado: CHECK ((activo = ((estado)::text = 'activo'::text)))

-- 2) cero conflictos
SELECT count(*) FROM usuarios WHERE activo IS DISTINCT FROM (estado = 'activo');
-- esperado: 0
```

Cambios de codigo que la acompañan (mismo commit):

- `get_current_user`: filtra por `estado = 'activo'` (antes `activo = true`) y devuelve `estado` en el dict.
- `auth.py` (login): 403 con mensaje especifico segun el estado (`Tu cuenta esta pendiente de activacion...`,
  `Tu solicitud fue rechazada...`, `Tu cuenta esta dada de baja...`) en vez del generico `Usuario inactivo`.
- `PUT /usuarios/{id}`: acepta `estado` y deriva `activo` (o al reves si llega `activo`), asi la API no puede
  romper el CHECK. Soft delete (`DELETE /usuarios/{id}`) setea **ambos**: `estado='baja'` + `activo=false`.
- `POST /usuarios` y los modales de Alumnos/Coaches: mandan `estado` y los badges de las listas usan `estado`.

## PASO 5 - Correccion de DATOS: los 6 planes de estudiante (2026-09-23)

**Estado: APLICADO a PROD** (solo datos; no hay cambio de codigo).

### Causa
El backup de PROD usado en el restore es `neon_backup_prod_20260917_060659.sql` (**17/09 06:07**) y el fix
`5915b94` ("es_estudiante como fuente unica de requiere_certificado_estudiante") es de las **06:37** del mismo
dia: el dump es 30 minutos ANTERIOR al fix, asi que el restore devolvio los valores viejos.

En la nueva PROD los 6 planes quedaron con **ambos flags en `false`** -> la pantalla `/admin/planes`
(tarjetas "Estudiante Masculino/Femenino" y badges "Certif. estudiante") los mostraba como planes normales.
Verificado tambien en el propio dump del 17/09: `es_estudiante=f, requiere_certificado_estudiante=f` para
`id` 5, 6, 7, 13, 14 y 15.

### Que se hizo
1. **Backup previo** de PROD: `backend/backups/neon_backup_full_20260923_195655.sql` (1.451.958 bytes).
2. **UPDATE dirigido** (aditivo, solo esas 6 filas por `id`, con guarda de host = `ep-nameless-sound-b6km6wyi`
   y de `rowcount == 6`):

```sql
UPDATE planes SET es_estudiante = true, requiere_certificado_estudiante = true
WHERE id = ANY(ARRAY[5, 6, 7, 13, 14, 15]);   -- Girly, Aesthetic, Influencer, Brocoli, Diddy Kong, Donkey Kong
```

3. Verificado despues: 6/16 planes con `es_estudiante = true`, 0 inconsistencias
   (`es_estudiante <> requiere_certificado_estudiante`).

### Verificacion contra TEST
La referencia de TEST es el backup `neon_backup_full_20260923_191921.sql` (19:19, **previo** al reset que hace
el seed de la suite con `DROP SCHEMA public CASCADE` + `create_all`, que dejo TEST con solo 2 planes).
Comparados los 17 planes de TEST contra los 16 de PROD: **los 6 planes de estudiante coinciden (`true/true`)**
y no hay ninguna otra diferencia de valores; el unico plan que existe solo en TEST se llama `prueba`.
Nota: la verificacion de la 034 tambien se hizo antes de ese reset; despues de correr la suite, TEST queda con
el esquema creado por los modelos (sin `alembic_version` y sin la constraint), que es su estado normal.

### Verificacion de la categorizacion (por API, con el mismo codigo de `Planes.jsx`)
`GET /api/v1/planes?activo=true` contra la base de PROD devuelve:

| Tarjeta | Planes |
|---|---|
| 💪 Masculino (5) | Baby Chimp, Simio, Gorila, Alpha, King Kong |
| 🌸 Femenino (5) | Princesa, Vikinga, Super Woman, Diosa Griega, Bichota |
| 🎓 Estudiante Masculino (3) | Brocoli, Diddy Kong, Donkey Kong |
| 🎓 Estudiante Femenino (3) | Girly, Aesthetic, Influencer |

Los 6 quedan con el badge "Certif. estudiante", no se duplican en las tarjetas normales y coinciden con TEST.

### Para confirmar en el navegador (30 segundos)
Entrar a `https://box-crossfit.onrender.com/admin/planes` con un admin del box y ver las 4 tarjetas:
"Estudiante Femenino" debe listar Girly / Aesthetic / Influencer y "Estudiante Masculino" a
Brocoli / Diddy Kong / Donkey Kong, con el badge azul "🎓 Estudiantil".

### Ojo para el futuro
- El fix es de **datos**: si algun dia se restaura OTRA VEZ un dump anterior al 17/09 06:37, hay que
  reaplicar el UPDATE (queda documentado aca).
- El formulario de Planes ya deriva `requiere_certificado_estudiante` de `es_estudiante` (commit `5915b94`),
  asi que la UI no puede volver a desincronizarlos.
- Los endpoints de planes requieren token, por eso la verificacion se hizo contra la BD de PROD + su API
  local; el `JWT_SECRET_KEY` de Render NO es el del `.env` local (por eso un token generado aca da 401 alla).
