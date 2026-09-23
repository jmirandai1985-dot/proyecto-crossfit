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
