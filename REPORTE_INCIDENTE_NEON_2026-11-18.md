# Incidente Neon 2026-11-18 — restauración y separación TEST/PROD

Sesión autónoma. Registro de **qué se corrió, qué devolvió y qué quedó pendiente**.
Nada se pusheó ni se commiteó: los comandos quedan al final para revisión manual.

## Resumen

| Ítem | Estado | Verificación |
|---|---|---|
| **1** Restaurar backup de R2 en la base nueva | **HECHO** | 60 tablas · 517 usuarios · 19 planes · 7.747 clases · 24.752 asistencias · stderr vacío |
| **1** `alembic stamp head` | **CAMBIADO** (ver §1.3) | dump en 086, head 088 → se corrió `alembic upgrade head`; `current` = `088_matricula_configurable (head)` |
| **1** `SELECT count(*) FROM usuarios` | **HECHO** | 517 (no 0) |
| **1B** Plan B (`create_all` + cuentas a mano) | **NO USADO** | no hizo falta: el restore fue limpio |
| **2** Deploy en Render | **PENDIENTE (usuario)** | no tengo acceso al dashboard ni API token de Render |
| **3** Rama TEST en Neon | **HECHO** | rama `test` = `br-silent-pine-aram54y2`, endpoint `ep-spring-thunder-argjp1mm`, 60 tablas / 517 usuarios / 088 |
| **3** `.env.test` apuntando a TEST | **HECHO** | `DATABASE_URL`→`ep-spring-thunder-argjp1mm-pooler…`, `DIRECT_URL`→`ep-spring-thunder-argjp1mm…` |
| **3** Guard de arranque en `config.py` | **HECHO** | 10 tests nuevos + 40 existentes ⇒ **50 passed**; aborto real verificado al importar |
| **4** Renombrar `N8N_API_KEY` | **CÓDIGO HECHO / RENDER PENDIENTE** | canónico `CRON_API_KEY`, `N8N_API_KEY` legacy; el header `X-N8N-API-Key` NO cambia |
| **5** (detectado, fuera del pedido) Cron Jobs de backup/roles | **PENDIENTE** | `PROD_DB_DIRECT_URL` sigue apuntando a la base vieja — ver §5 |

## Bloqueo de seguridad respetado

- Repo: `C:\Users\Asus\Desktop\Proyectos\proyecto-crossfit`, rama `main`
  (HEAD `c580684`), working tree limpio al empezar.
- No se tocó `carpeta_respaldo_box` ni nada fuera del repo.
- **No se hizo `git push` ni `git commit`.**
- Contra Neon **sólo** se corrió: restore en la base nueva, 2 migraciones aditivas
  (087/088) y una base descartable de ensayo (ya eliminada). Nada contra la base
  vieja ni contra TEST para escrituras.
- Las credenciales que pasaste por chat no se escribieron en el repo (sólo en los
  `.env*`, que están gitignored) ni se imprimieron en logs.

## Paso 1 — Restore desde R2 (hecho)

### 1.1 Listado de `daily/`

Con las credenciales de `backups-prod` (`R2_*`): **65 objetos**, del 26/09 al 17/11.

```
últimos:
  daily/2026-11-15_0301_neon_backup.sql.gz   809.9 KB   2026-11-15T06:01:39Z
  daily/2026-11-16_0302_neon_backup.sql.gz   795.9 KB   2026-11-16T06:02:05Z
  daily/2026-11-17_0301_neon_backup.sql.gz   801.4 KB   2026-11-17T06:02:00Z   <= elegido
```

**No existe `2026-11-18`**: el backup de las 03:00 CLT de hoy falló por la cuota,
tal como se sospechaba. Se usó el **17/11 03:01**.

> Nota: las credenciales `STORAGE_R2_*` (buckets de uploads/public) dan
> **AccessDenied** sobre `box-crossfit-backups`. Son tokens distintos a propósito.

### 1.2 Descarga y validación del dump

```
archivo : backend/backups/r2_daily_2026-11-17_0301.sql.gz   (gitignored)
bytes   : 820.629   (coincide con el Size de R2)
sha256  : b45db1b0a6de53b53b5f0dabac746089e6c2a9cf52b799349249cb354832e253
```

Contenido (`pg_dump --no-owner --no-privileges --format=plain`, comprimido con gzip):

| Control | Valor |
|---|---|
| `CREATE TABLE` | 60 |
| `COPY` | 60 |
| footer `PostgreSQL database dump complete` | sí |
| sentencias `OWNER TO` / `GRANT` | **0** (no hace falta sanitizar) |
| `alembic_version` en el dump | **`086_pago_iniciado`** |
| `Dumped from` / `Dumped by` | server 18.7 / pg_dump 18.6 |

### 1.3 Restore y decisión sobre Alembic

Restore con el cliente local 18.0.4 contra `DIRECT_URL` (sin pooler), en
background (`Start-Process`, tarda ~3 min por la latencia de Neon):

```
psql -h ep-bitter-field-armkhpzr.c-4.us-west-2.aws.neon.tech -U neondb_owner -d neondb \
     -v ON_ERROR_STOP=1 -q -f backend/backups/r2_daily_2026-11-17_0301.sql
```

Resultado: **stderr = 0 bytes** (sin errores ni warnings). Verificación:

| Tabla | Filas |
|---|---|
| tablas en `public` | 60 |
| `usuarios` | **517** |
| `planes` | 19 |
| `clases` | 7.747 |
| `asistencias` | 24.752 |
| `transacciones_financieras` | 2.572 |
| `suscripciones` | 2.304 |
| `tenants` | 2 |
| `alembic_version` | `086_pago_iniciado` |

**DESVÍO CONSCIENTE respecto del prompt:** el prompt pedía `alembic stamp head`,
pero el dump quedó en **086** y el head del repo es **088**. `stamp head` habría
marcado 087/088 como aplicadas **sin crear sus columnas** (`planes.plan_referencia_id`,
`tenants.matricula_*`, `solicitudes_planes.matricula_clp_snapshot`) y la app
desplegada rompería al consultarlas. Se corrió el **mismo comando que ejecuta el
preDeploy de Render**:

```
ENVIRONMENT=production python -m alembic upgrade head    # aplica 087 y 088
```

Las dos migraciones son **DDL aditivo e idempotente** (`ADD COLUMN IF NOT EXISTS`,
sin tocar datos), por lo que el riesgo es mínimo. Resultado:

```
$ python -m alembic current
088_matricula_configurable (head)
```

y las 3 columnas nuevas existen (`information_schema.columns` = 1 cada una).

> Transparencia: el primer `upgrade head` se lanzó desde PowerShell y el wrapper
> levantó un `NativeCommandError` por el log INFO en stderr **después** de aplicar
> las migraciones. Se repitió con `Start-Process` → `rc=0` y la base ya estaba en 088.

### 1.4 Cuentas demo

Las 3 cuentas permanentes existen y están activas en la base restaurada:

```
demo.admin@urbanbox.cl  | administrador | activo
demo.coach@urbanbox.cl  | coach         | activo
demo.alumno@urbanbox.cl | alumno        | activo
```

Reparto general: 507 alumnos, 6 coaches, 4 administradores.

## Paso 2 — Deploy en Render (pendiente: lo tiene que disparar el usuario)

No tengo dashboard ni API token de Render, así que no puedo iniciar el deploy.

Estado esperado cuando lo dispares:

- `preDeployCommand: alembic upgrade head` → **no-op** (la base ya está en 088).
  El bug de orden de las 88 migraciones **no aplica** porque no se corre desde cero.
- La app debe quedar **Live** y el login con `demo.admin@urbanbox.cl` debe funcionar
  (la cuenta y su hash están en el dump).

Checklist después del deploy:

1. `GET https://box-crossfit.onrender.com/health/db` → OK.
2. Login `demo.admin@urbanbox.cl` desde el frontend.
3. Revisar en el log del deploy que no haya `RuntimeError: [config] ... apunta a la base ...`.

Verificación local previa (hecha): con `ENVIRONMENT=production`, `SCHEDULER_ENABLED=false`,
`CORS_ORIGINS`/`FRONTEND_URL` https válidos y la base restaurada,
`import app.main` devuelve **OK** (no se corrieron los startup events, así que no se
escribió nada). Con `backend/.env` tal cual el import falla por `CORS_ORIGINS` en
localhost + `ENVIRONMENT=production`: es preexistente y **no** afecta a Render, que
inyecta sus propias variables.

## Paso 3 — TEST separado de PROD (hecho)

### 3.1 Rama TEST

Creada con la API de Neon (`NEON_API_KEY` que pasaste) en el proyecto nuevo
`still-dust-51155335` ("urban-training-box", us-west-2):

| Dato | Valor |
|---|---|
| rama | `test` → `br-silent-pine-aram54y2` |
| endpoint | `ep-spring-thunder-argjp1mm` (c-4, read_write) |
| origen | copia de `production` **después** del restore |
| contenido verificado | 60 tablas · 517 usuarios · `alembic_version` 088 |

> La primera rama que creé (`br-summer-waterfall-arzotzfk` / `ep-small-scene-ar03iey4`)
> salió vacía porque production todavía no tenía datos. Se borró (estaba en 0 tablas)
> y se recreó después del restore. Ese endpoint ya no existe.

### 3.2 `.env.test`

```ini
DATABASE_URL=…@ep-spring-thunder-argjp1mm-pooler.c-4.us-west-2.aws.neon.tech/neondb?channel_binding=require&sslmode=require
DIRECT_URL=…@ep-spring-thunder-argjp1mm.c-4.us-west-2.aws.neon.tech/neondb?channel_binding=require&sslmode=require
CRON_API_KEY=<mismo valor que N8N_API_KEY de TEST>
```

Verificado: `ENVIRONMENT=test` ⇒ `is_test_db_url(settings.DATABASE_URL) = True`.

### 3.3 Guard de arranque (`backend/app/core/config.py`)

`_verificar_entorno_db()` corre **al importar el módulo** (final del archivo, porque
necesita las tuplas de endpoints). Evalúa `DATABASE_URL` **y** `DIRECT_URL`:

| Entorno | Host cargado | Resultado |
|---|---|---|
| `test` / sin definir | PROD (`ep-bitter-field-armkhpzr…`) | **aborta** con `RuntimeError` |
| `production` | TEST (`ep-spring-thunder-argjp1mm…`) | **aborta** con `RuntimeError` |
| `production` | PROD | arranca |
| `test` | desconocido (localhost, docker, rama nueva) | arranca |

Evidencia real (no sólo tests):

```
ENVIRONMENT=test DATABASE_URL=…ep-bitter-field-armkhpzr-pooler…
  -> RuntimeError: [config] DATABASE_URL apunta a la base de PRODUCCION (...) con
     ENVIRONMENT=test (se esperaba TEST). Abortando para no escribir ni consumir
     cuota de la base real...

ENVIRONMENT=production DATABASE_URL=…ep-spring-thunder-argjp1mm-pooler…
  -> RuntimeError: [config] DATABASE_URL apunta a la base de TEST (...) con
     ENVIRONMENT=production. Abortando: un proceso de PRODUCCION no puede escribir en TEST.
```

Topología actualizada en el mismo archivo: `PROD_BRANCH_ID` = el nuevo,
`ep-crimson-tooth-akhx7q2s` movido a `ENDPOINTS_RETIRADOS` (tenía datos reales y su
cuenta está bloqueada) y `TEST_BRANCH_IDS` = sólo la rama nueva.

### 3.4 Tests

`backend/tests/test_config_db_guard.py` (nuevo, 10 casos, sin red ni BD):
guard en ambos sentidos, `DIRECT_URL`, hosts desconocidos, `is_test_db_url`
fail-closed y aborto real al importar en un subproceso.

```
py -3.12 -m pytest tests/test_config_db_guard.py tests/test_cron_api_key.py tests/test_kpis_cloud.py -q --noconftest
50 passed, 1 warning
```


## Paso 4 — Renombrar `N8N_API_KEY` (código hecho; Render pendiente)

**Nombre propuesto: `CRON_API_KEY`.** No inventé `CRON_JOBS_API_KEY` porque
`CRON_API_KEY` ya existía en el código (propiedad `settings.automation_api_key`,
`kpis_cloud.VARS_API_KEY`) y ya estaba documentada: agregar un tercer nombre
sumaba superficie de error sin beneficio. Si preferís `CRON_JOBS_API_KEY`, se
agrega como alias en 3 líneas.

Cambios:

- `config.py`: `CRON_API_KEY` es el campo canónico; `N8N_API_KEY` queda documentado
  como legacy. `automation_api_key = CRON_API_KEY or N8N_API_KEY`.
  WARNING al arrancar si sólo está el nombre viejo.
- `kpis_cloud.py`, `.env.example`, `README.md`, `maintenance/README.md`,
  `docs/CRON_JOBS_RENDER.md`, `docs/RETENCION_DATOS_Y_N8N.md`, `render.yaml` y
  docstrings de `kpis_populate.py` / `ml.py` / `ranking.py`: nombre canónico nuevo.
- **El header HTTP sigue siendo `X-N8N-API-Key`**: cambiarlo rompería los Cron Jobs
  desplegados. Es sólo el nombre de la variable de entorno.

En Render (cuando puedas):

1. Web Service `box-crossfit`: agregar `CRON_API_KEY` con **el mismo valor** que
   `N8N_API_KEY`; guardar (redeploy).
2. Env group `kpis-prod`: idem.
3. Verificar un run del Cron Job `box-crossfit-kpis-ml` (debe dar verde).
4. Recién entonces borrar `N8N_API_KEY` de ambos lados.

## Paso 5 — Cron Jobs y roles (actualizado 2026-11-18, pedido urgente)

### 5.1 `backup_ro` — CREADO Y VERIFICADO

Creado **por SQL** con `neondb_owner` (no por el botón del panel de Neon):

```sql
CREATE ROLE backup_ro WITH LOGIN;
ALTER ROLE backup_ro WITH LOGIN INHERIT PASSWORD '<password-generada>';
GRANT pg_read_all_data TO backup_ro;
GRANT CONNECT ON DATABASE neondb TO backup_ro;
```

> `ALTER ROLE ... NOSUPERUSER/NOBYPASSRLS` **falla** con `neondb_owner`
> (`permission denied to alter role`): esos atributos sólo los cambia un superusuario
> y no hacen falta (un rol creado por un no-superusuario ya nace `NOSUPERUSER` y
> `NOBYPASSRLS`). `INHERIT` sí importa: con `NOINHERIT`, `pg_read_all_data` no se
> aplica al conectar y `pg_dump` fallaría.

Verificación (todas pasaron):

| Chequeo | Resultado |
|---|---|
| `rolsuper` | `false` |
| miembro de `neon_superuser` | `false` |
| miembro de `pg_read_all_data` | `true` |
| `has_table_privilege('backup_ro','public.usuarios','SELECT')` | `true` |
| `has_table_privilege('backup_ro','public.usuarios','INSERT')` | `false` |
| `has_schema_privilege('backup_ro','public','CREATE')` | `false` |
| conexión real: `SELECT count(*) FROM usuarios` | **517** |
| conexión real: `CREATE TABLE public._perm_test(x int)` | **permission denied for schema public** |
| `pg_dump --no-owner --no-privileges --format=plain` como `backup_ro` | 8.517.038 bytes · 60 tablas · 60 COPY · footer OK · alembic 088 · stderr vacío |

La connection string directa se entregó **sólo por chat** (este archivo se versiona,
así que no lleva el password). Forma:

```
postgresql://backup_ro:<password>@ep-bitter-field-armkhpzr.c-4.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require
```

### 5.2 Qué cambia en cada Environment Group (Render)

| Group | Variable | Valor nuevo | Estado |
|---|---|---|---|
| `backups-prod` | `PROD_DB_DIRECT_URL` | connection string de `backup_ro` (host directo) | listo para pegar |
| `neon-api` | `NEON_PROJECT_ID` | `still-dust-51155335` | listo para pegar |
| `neon-api` | `NEON_API_KEY` | API key de la cuenta nueva | listo para pegar |
| `mantenimiento-prod` | `MAINT_DB_URL` | `postgresql://maint_rw:<password>@ep-bitter-field-armkhpzr…/neondb?...` | **BLOQUEADO: `maint_rw` no existe** |
| `retencion-prod` | `RETENCION_DB_URL` | `postgresql://retencion_rw:<password>@ep-bitter-field-armkhpzr…/neondb?...` | **BLOQUEADO: `retencion_rw` no existe** |

Roles presentes en el proyecto nuevo: `backup_ro`, `cloud_admin`, `neon_service`,
`neon_superuser`, `neondb_owner`, `token_roles`. **No hay `maint_rw` ni `retencion_rw`.**
El SQL completo de `maint_rw` (grants por columna) está en
`backend/maintenance/README.md` §"El rol `maint_rw`" (línea ~704); `retencion_rw` en
la sección de retención. **No se crearon**: son roles con escritura, fuera de la
aprobación del rol de sólo lectura; sus jobs corren los días 1-3 de cada mes.

### 5.3 Nombre real del cron de backup

En `render.yaml` el job se llama **`proyecto-crossfit`** (no `backups-prod-cron`):
`dockerCommand: python -m maintenance.backup_cloud`, `schedule: "0 6 * * *"`.
Es el que hay que disparar a mano.

## Paso 6 — Roles `maint_rw` y `retencion_rw` (entrega 2026-11-18)

Generados y **probados en seco** dentro de `BEGIN … ROLLBACK` contra la base nueva
(no se creó nada: se verificó que `pg_roles` quedó igual). Las passwords (32
caracteres alfanuméricos, método documentado) se entregaron **sólo por chat**.

### 6.1 `maint_rw` — verificación del dry-run

| Chequeo | Resultado |
|---|---|
| `rolcanlogin` / `rolinherit` / `rolsuper` | `t` / **`f`** (NOINHERIT) / `f` |
| CONNECT + USAGE + TEMP | `t` / `t` / `t` |
| SELECT en las 12 tablas | `t` × 12 |
| UPDATE por columna (12 columnas) | `t` × 12 |
| DELETE en `password_reset_tokens` / `notificaciones_enviadas` | `t` / `t` |
| UPDATE en columnas prohibidas (`usuarios.nombre`, `suscripciones.plan_id/usuario_id`, `reservas.estado`, `clases.cupo_maximo/coach_id`, `password_reset_tokens.expires_at`) | `f` |
| INSERT / DELETE / TRUNCATE / REFERENCES en `usuarios` | `f` × 4 |
| `CREATE` en schema / base | `f` / `f` |
| miembro de `neon_superuser` | `f` |
| `has_function_privilege('version()','EXECUTE')` | **`t`** — es de PUBLIC, no un permiso del rol (el comentario "21 × f" del README es optimista en esa fila) |

### 6.2 `retencion_rw` — verificación del dry-run

| Chequeo | Resultado |
|---|---|
| `rolcanlogin` / `rolinherit` / `rolsuper` | `t` / **`f`** (NOINHERIT) / `f` |
| CONNECT / USAGE | `t` / `t` |
| `asistencias` DELETE · `asistencias_archivo` INSERT · `reservas_archivo` INSERT | `t` × 3 |
| `auditoria` DELETE · `usuarios.rut` UPDATE · `retencion_bloqueos` INSERT | `t` × 3 |
| `CREATE` en schema | `f` |
| miembro de `neon_superuser` | `f` |

### 6.3 BUG corregido: `retencion_cloud.py` tenía la topología vieja

`maintenance/retencion_cloud.py` duplica a propósito las tuplas de
`app/core/config.py` (el contenedor de cron no puede importar `app/`). Al cambiar
de cuenta Neon en el incidente, **esa copia quedó desactualizada**:

- `PROD_BRANCH_IDS` no incluía `ep-bitter-field-armkhpzr` ⇒ `validar_url()` rechazaba
  la URL nueva con **exit 2** ("no es el endpoint de PROD conocido").
- `TEST_BRANCH_IDS` seguía con `ep-crimson-tooth-akhx7q2s` (retirada).
- `tests/test_retencion_unit.py::test_tuplas_de_ramas_iguales_a_app_core_config`
  **fallaba** (1 failed, 58 passed).

Corregido (sólo las 3 tuplas, mismo orden que `config.py`): **59 passed** y ahora
`test_retencion_unit.py + test_config_db_guard.py + test_cron_api_key.py +
test_kpis_cloud.py + test_watchdog_backups.py` ⇒ **117 passed**.

> ⚠️ Esto tiene que **desplegarse** (commit + push + rebuild del Cron Job) antes de
> cargar `RETENCION_DB_URL`: la imagen del cron se construye desde `backend/`, así
> que con el código viejo el job seguiría rechazando el endpoint nuevo.

### 6.4 Pendiente detectado (fuera de alcance, fail-closed)

`scripts/crear_usuarios_demo.py:160` y `scripts/seed_anual_prod.py:157-158` tienen
`HOST_PROD = "winter-star"` / `HOST_TEST = "crimson-tooth"` y abortan si el id
configurado no coincide (líneas 313 y 1387). Son scripts manuales de seed: hoy
**abortan** (seguro, no escriben), pero quedan inservibles hasta actualizarlos a
`bitter-field` / `spring-thunder` y sumar `winter-star` a la denylist de PROD
anterior. No se tocaron en esta entrega.

## Evidencia: comandos clave corridos

| Comando | Resultado |
|---|---|
| `psql <nueva PROD> -tAc "select version()"` | PostgreSQL 18.7, 0 tablas (antes del restore) |
| `psql … -f backup_local_28_10.sql` (rehearsal, base descartable) | 47 tablas, 511 usuarios, 0 errores (validó `\restrict` de psql 18) |
| `python -c "boto3 … list daily/"` | 65 objetos, último 2026-11-17_0301 |
| `download_file` + sha256 | 820.629 bytes · `b45db1b0…e253` |
| `psql -f r2_daily_2026-11-17_0301.sql` | stderr 0 bytes · 60 tablas · 517 usuarios |
| `alembic upgrade head` (087+088) | rc=0 |
| `alembic current` | `088_matricula_configurable (head)` |
| `pytest test_config_db_guard + test_cron_api_key + test_kpis_cloud` | 50 passed |
| Neon API `POST /branches` (test) | `br-silent-pine-aram54y2` / `ep-spring-thunder-argjp1mm` |

Temporales generados y **eliminados**: `_rehearsal*.log`, `_restore_prod.*.log`,
`_alembic*.log`, `_current*.log`, `_restore_rehearsal.err.log`.
Queda (gitignored, útil para auditoría): `backend/backups/r2_daily_2026-11-17_0301.sql.gz`
y su `.sql` descomprimido.

Cambio de entorno local: se instaló `boto3` 1.43.108 en el Python 3.12 del usuario
(`py -3.12 -m pip install --user boto3`) para poder listar/descargar de R2. No hay
`aws` CLI en la máquina.

## Comandos de commit (NO ejecutados, sin push)

```bash
cd C:/Users/Asus/Desktop/Proyectos/proyecto-crossfit
git add backend/app/core/config.py backend/tests/test_config_db_guard.py backend/.env.example
git commit -m "fix(config): guard de arranque TEST/PROD y CRON_API_KEY como nombre canonico"

git add README.md docs/CRON_JOBS_RENDER.md docs/RETENCION_DATOS_Y_N8N.md \
        backend/maintenance/README.md backend/maintenance/kpis_cloud.py \
        backend/app/api/v1/kpis_populate.py backend/app/api/v1/ml.py \
        backend/app/api/v1/ranking.py render.yaml
git commit -m "docs(cron): N8N_API_KEY pasa a CRON_API_KEY (alias legacy)"

# opcional: versionar este informe
git add REPORTE_INCIDENTE_NEON_2026-11-18.md
git commit -m "docs(incidente): reporte de la restauracion en la cuenta Neon nueva"
```

Mensajes sin líneas de atribución, como se pidió.

## Rollback

```bash
git checkout -- backend/app/core/config.py backend/.env.example README.md \
  docs/CRON_JOBS_RENDER.md docs/RETENCION_DATOS_Y_N8N.md \
  backend/maintenance/README.md backend/maintenance/kpis_cloud.py \
  backend/app/api/v1/kpis_populate.py backend/app/api/v1/ml.py \
  backend/app/api/v1/ranking.py render.yaml
rm backend/tests/test_config_db_guard.py REPORTE_INCIDENTE_NEON_2026-11-18.md
```

Los `.env*` no están versionados. Para volver la base al estado vacío:
`DROP SCHEMA public CASCADE; CREATE SCHEMA public;` (sólo en el proyecto nuevo).

## Pendiente inmediato (por orden de impacto)

1. **Pegar `PROD_DB_DIRECT_URL` en `backups-prod`** (el rol `backup_ro` ya está creado
   y verificado) y disparar el cron **`proyecto-crossfit`** a mano antes de las 03:00 CLT.
2. **Deploy en Render** (usuario) y probar login con `demo.admin@urbanbox.cl`.
3. `NEON_PROJECT_ID` / `NEON_API_KEY` del env group `neon-api`.
4. `CRON_API_KEY` en Render (y después borrar `N8N_API_KEY`).
5. Crear `maint_rw` / `retencion_rw` + `MAINT_DB_URL` / `RETENCION_DB_URL`
   (bloqueado: los roles no existen; jobs corren los días 1-3).
6. Rotar los secretos que se compartieron por chat (R2, Neon API key).
