# 🔧 Mantenimiento Urban Training Box

**Carpeta de scripts automáticos de mantenimiento.**

> **A partir de Fase 1.4 se ejecutan en el contenedor de mantenimiento**
> (`docker-compose.yml` → servicio `maintenance`, target `maintenance` del
> Dockerfile), vía `cron`, y **ya NO los ejecuta APScheduler** en el backend
> (los jobs de mantenimiento se eliminaron de `scheduler.py` el 21/08/2026).

## Ejecución automática

- **Diario 02:30 CLT** → `run_daily.py` (backup, planes vencidos, huérfanas, health, neon usage)
- **Mensual (1º día 03:00 CLT)** → `run_monthly.py` (todo + integridad + estadísticas + rotación)

Los horarios se definen en `maintenance/crontab` (copiado a
`/etc/cron.d/box-maintenance` en la imagen). El contenedor usa
`TZ=America/Santiago`, así que las horas son CLT.

### En Docker (Fase 1.4)

```bash
cd <raíz del proyecto>
docker compose up -d                     # levanta backend + maintenance + frontend
docker compose build maintenance          # rebuild solo del contenedor de mantenimiento
docker logs box-crossfit-maintenance-1    # logs del cron (jobs salen a /app/logs/cron.log)
```

- **Volumen `logs`** (compartido con el backend): `/app/logs` — `app.log` del
  backend y `maintenance_*.log` de los jobs viven juntos; `cleanup_logs.py`
  (mensual) limpia ambos.
- **Volumen `backups`**: `/app/backups` — dumps `pg_dump` (retención 30 días).
  El backend lo monta read-only.
- **`BACKEND_URL=http://backend:8000`** se inyecta en el contenedor porque
  `health_check.py` hace ping al API; en Docker el backend no es `localhost`.

## Scripts

### CRÍTICOS
- `backup_neon.py` — Backup diario de BD (retención 30 días)
- `marcar_plan_vencido.py` — Marcar suscripciones vencidas, alumnos inactivos
- `transacciones_huerfanas.py` — Limpiar suscripciones/solicitudes pendientes > 7 días
- `health_check.py` — Verificar salud del backend + BD, enviar aviso si falla

### IMPORTANTES
- `neon_usage_alerts.py` — Alertar si uso > 90% free tier
- `cleanup_logs.py` — Eliminar logs > 30 días
- `verificar_integridad.py` — Checks: RUT únicos, correos únicos, FKs, fechas válidas

### OPCIONALES
- `reporte_estadisticas.py` — Reporte mensual: alumnos, planes, ingresos
- `rotar_credenciales.py` — Recordatorio rotación credenciales (ACCIÓN MANUAL)

## Ejecución manual

```bash
cd backend
python -m maintenance.run_daily      # Ejecuta diario
python -m maintenance.run_monthly    # Ejecuta mensual
python -m maintenance.backup_neon    # Backup solo
```

## Logs

Todos los jobs generan logs en `backend/logs/maintenance_*.log`

## Requisito `backup_neon.py` — pg_dump de la MISMA major que el servidor

`pg_dump` **aborta si el cliente es de una major menor que el servidor** (Neon corre PostgreSQL
18.x):

```
pg_dump: error: aborting because of server version mismatch
pg_dump: detail: server version: 18.6 (6569466); pg_dump version: 17.11 (Debian 17.11-0+deb13u1)
```

Eso dejó el volumen `backups` **vacío durante días** (ver historial en la sección de estado).
Por eso:

- **En Docker (lo normal)**: el target `maintenance` del `Dockerfile` instala
  `postgresql-client-18` desde el repo oficial de PGDG (`trixie-pgdg`) y **verifica la versión en
  el build** (`pg_dump --version | grep -q " 18\."`). Si PGDG o la base cambian de major, el
  build falla en vez de fallar en silencio a las 02:30. No hay nada que configurar a mano.
- **En el host (ejecución manual desde Windows)**: instalar el cliente de la misma major que Neon
  (p. ej. `C:\Program Files\PostgreSQL\18\bin`) y agregarlo al PATH del usuario:

```powershell
$bin = 'C:\Program Files\PostgreSQL\18\bin'
$cur = [Environment]::GetEnvironmentVariable('Path', 'User')
[Environment]::SetEnvironmentVariable('Path', "$cur;$bin", 'User')   # reabrir la terminal
```

- El dump usa la **conexión directa** (`DIRECT_URL`), no la del pooler: Neon desaconseja `pg_dump`
  contra `-pooler` (PgBouncer mantiene estado de sesión que rompe dumps largos).

## Conexión a base de datos

Los scripts usan **`settings.DATABASE_URL`** (singleton de `app/core/config.py`), es decir
la del `.env` **activo** del proceso. No definen `ENVIRONMENT=test` por defecto
(verificado 19/08/2026): si el proceso arranca con `ENVIRONMENT=test` carga `.env.test`
(BD de TEST), si no, carga `.env` (BD activa).

## Estado y verificación del contenedor (2026-09-26)

### ¿Estaba desactualizada la imagen?
Se comparó el código de dentro del contenedor con el repo (`md5sum`): `maintenance/*.py`,
`app/core/config.py` y `app/services/email_service.py` **coincidían** con el repo. Lo único
desactualizado era el **cliente `pg_dump` (17.11) frente al servidor de Neon (18.6)**, que es
justamente lo que rompía los backups. Con el fix del `Dockerfile` se reconstruyó la imagen:

```powershell
docker compose -p box-crossfit build maintenance
docker compose -p box-crossfit up -d --force-recreate --no-deps maintenance
```

### Cómo verificar el contenedor (todos los comandos son read-only)
| Chequeo | Comando | Esperado |
|---|---|---|
| Versión del cliente | `docker exec box-crossfit-maintenance-1 pg_dump --version` | `... 18.6` |
| Entorno | `docker exec box-crossfit-maintenance-1 printenv ENVIRONMENT` | `test` |
| Guard anti-PROD | `docker exec ... python -c "from app.core.config import settings,is_test_db_url; print(is_test_db_url(settings.DATABASE_URL))"` | `True` |
| Sin URL de PROD | `docker exec box-crossfit-maintenance-1 printenv DATABASE_URL_PROD` | vacío |
| cron vivo | `docker top box-crossfit-maintenance-1` | `cron -f -l 2` |
| Job real | `docker exec -u boxapp box-crossfit-maintenance-1 sh -c "cd /app && python -m maintenance.run_daily"` | `✅ Backup creado: ...` |
| Backups | `docker exec box-crossfit-maintenance-1 ls -la /app/backups` | `neon_backup_*.sql` |

### Corrida real registrada (2026-09-26 15:44 CLT)
- `pg_dump (PostgreSQL) 18.6 (Debian 18.6-1.pgdg13+2) | origen: ep-jolly-butterfly-b6ty2z89...neon.tech/neondb` (conexión **directa**).
- `✅ Backup creado: /app/backups/neon_backup_20260926_154426.sql (1439.1 KB)`.
- Integridad verificada: **36 `CREATE TABLE`** (== 36 tablas de `public` en TEST), **36 bloques `COPY`**,
  footer `PostgreSQL database dump complete`, y `alembic_version = 035_precio_snapshot_solicitudes`
  idéntico al de la BD viva.
- Env del contenedor: `ENVIRONMENT=test`, `is_test_db_url()=True`, `DATABASE_URL_PROD` vacía,
  `BACKEND_URL=http://backend:8000`. Los dos jobs del crontab están instalados
  (diario 02:30 y mensual día 1 03:00, ambos como `boxapp`).

### ⚠️ Limitación operativa (importante)
Este contenedor corre **en la máquina de desarrollo**. Los logs diarios que existen son del
22/08, 11/09, 24/09 y 25/09: **sólo de los días en que la máquina estuvo encendida a las 02:30 CLT**
(el 26/09 no corrió por eso mismo). O sea: mientras los backups dependan de este contenedor,
**los días que la PC está apagada no hay backup de PROD**. Opciones (a decidir con Jebbus):
1. Un **Cron Job de Render** (siempre encendido) que ejecute el dump con `pg_dump` 18 contra
   `DIRECT_URL` y suba el archivo a almacenamiento externo (S3/R2/Backblaze).
2. Usar el **backup/PITR propio de Neon** como respaldo principal y dejar este contenedor como
   copia secundaria.
3. Un **runner siempre encendido** (VPS) corriendo esta misma imagen.

Los backups que sí se generan son válidos (se verificó la integridad del de hoy).


## Backup de PROD en la nube — Cron Job de Render + Cloudflare R2 (Fase 2, 2026-09-26)

Motivo: el backup vivía en **este** contenedor, así que solo corría los días que la PC estaba
encendida a las 02:30 (logs del 22/08, 11/09, 24/09 y 25/09) y, por default, contra la rama de
**TEST**. Ahora el backup de PROD corre en la nube, todos los días, sin depender de la PC.

| Pieza | Qué es |
|---|---|
| Runner | **Cron Job** de Render (`Dockerfile.cron`: imagen mínima con `pg_dump` 18 + `boto3`) |
| Origen | `PROD_DB_DIRECT_URL` → rol **`backup_ro`** de Neon (solo lectura, `GRANT pg_read_all_data`), conexión **directa** (sin `-pooler`) |
| Destino | **Cloudflare R2**, bucket privado `box-crossfit-backups`, prefijo `daily/`, retención **90 días** |
| Secretos | Environment Group de Render **`backups-prod`** (cero credenciales en el repo) |
| Script | `maintenance/backup_cloud.py` (dump + asserts + subida verificada) |

### Comportamiento
- `DRY_RUN=1` (default de la imagen): dump + asserts + **lista** el bucket y termina **sin subir
  nada**.
- `DRY_RUN=0`: sube, **verifica con `head_object`** que el objeto pesa igual que el archivo
  local, purga lo que tenga más de `RETENTION_DAYS` y **re-lista** para confirmar la subida.
- **Falla de verdad**: exit `2` config (falta variable / `-pooler` / major distinta), `3` dump,
  `4` asserts de contenido, `5` R2 ⇒ Render marca el run como fallido. Nunca dice "OK" en falso
  (el bug del 26/09 fue un "✅ Backup completado" con el dump fallando).
- Asserts de contenido: tamaño ≥ 200 KB, `CREATE TABLE` ≥ 30, footer
  `PostgreSQL database dump complete`, `COPY public.alembic_version` presente.

### Verificación local (sin R2; usa TEST y es solo lectura)
```bash
# construir la imagen (el contexto es backend/)
docker build -f backend/Dockerfile.cron backend -t box-crossfit-backup-cron:local

# guardas: versión del cliente, sin variables y con URL del pooler (estas últimas: exit 2)
docker run --rm --entrypoint pg_dump box-crossfit-backup-cron:local --version
docker run --rm box-crossfit-backup-cron:local
docker run --rm -e PROD_DB_DIRECT_URL='postgresql://u:p@ep-fake-pooler.c-2...neon.tech/neondb' \
  -e R2_ENDPOINT=x -e R2_BUCKET=x -e R2_ACCESS_KEY_ID=x -e R2_SECRET_ACCESS_KEY=x \
  box-crossfit-backup-cron:local
```
Registrado el 2026-09-26: `pg_dump 18.6` · sin variables ⇒ lista las 5 que faltan (exit 2) ·
URL `-pooler` ⇒ rechazada (exit 2) · dump+asserts contra TEST ⇒
`dump 1429.8 KB → gz 144.5 KB | 36 CREATE TABLE | 36 COPY | footer OK |
alembic=035_precio_snapshot_solicitudes | VEREDICTO: OK`.

### El Cron Job de backup en Render (ya existe: se llama `proyecto-crossfit`)
1. Dashboard → **New → Cron Job** → **nombre `proyecto-crossfit`** (así se llama el job que ya
   corre el backup) + repo + rama (`main`).
2. Runtime **Docker**: *Dockerfile Path* = `backend/Dockerfile.cron`;
   *Docker Build Context Directory* = `backend`.
3. **Environment**: *Link Environment Group* → **`backups-prod`** (entran las 10 variables).
   Confirmá `DRY_RUN=1` para el primer disparo.
4. Schedule (UTC): `0 6 * * *` = **03:00 CLT** diario.
5. Región: **Oregon (us-west-2)**, la misma del Web Service `box-crossfit` (ya probada).
6. Crear → **Runs → Trigger Run** (no hace falta esperar a las 03:00) y revisar el log.
7. Con el log en verde: `DRY_RUN=0`, disparar de nuevo a mano y verificar que el objeto aparece
   en R2 (`daily/AAAA-MM-DD_HHMM_neon_backup.sql.gz`).

> Costo: los Cron Jobs no existen en el plan free; el mínimo es **US$1/mes** por servicio.
> Para versionarlo se puede declarar en `render.yaml` (`type: cron`), pero recién después de
> validarlo a mano, así un sync del blueprint no crea algo a medio probar.

## Watchdog de frescura del backup — Fase 3 (2026-09-27)

Motivo: el 26/09 el backup de la nube estuvo días sin correr y **nadie se enteró** (el job
local logueaba "✅ Backup completado" con el dump fallando). El watchdog es un Cron Job
**independiente** del de backup: si el backup no corre, el watchdog avisa igual.

| Pieza | Qué es |
|---|---|
| Script | `maintenance/watchdog_backups.py` |
| Alcance | **sólo lee R2** (token de solo lectura, env group `r2-lectura`). No necesita `PROD_DB_DIRECT_URL` |
| Alertas | `maintenance/alertas.py` → **Gmail SMTP** (`smtp.gmail.com:465` + `SMTP_SSL` con App Password): el mismo camino de correo que ya usa la app |
| Reglas | sin objetos en `daily/` ⇒ alerta · el más nuevo con más de `MAX_EDAD_HORAS` (36 h) ⇒ alerta · el más nuevo con menos de `MIN_BYTES` (50 KB) ⇒ alerta |
| Sin alerta | una línea de log y exit 0, **sin email** (no se spamea) |

### Los Cron Jobs: 1 ya existe y quedan **2 por crear** (Render va en UTC; CLT = UTC-3)

| Job | ¿Existe? | Schedule (UTC) | Hora CLT | Dockerfile / comando | Env group | Exit ≠ 0 |
|---|---|---|---|---|---|---|
| **`proyecto-crossfit`** (backup) | **sí, ya corriendo** | `0 6 * * *` | 03:00 diario | `backend/Dockerfile.cron` · `python -m maintenance.backup_cloud` | `backups-prod` | 2/3/4/5 |
| `box-crossfit-watchdog` | **hay que crearlo** | `0 12 * * *` | 09:00 diario | `backend/Dockerfile.cron` · `python -m maintenance.watchdog_backups` | `r2-lectura` + `alertas` | 2/6/7 |
| `box-crossfit-restore-drill` | **hay que crearlo** | `0 13 1 * *` | 10:00 el día 1 | `backend/Dockerfile.cron` · `python -m maintenance.restore_drill` | `backups-prod` + `neon-api` + `alertas` | 2/8/9/10/11/12 |

> Resumen de lo que falta hacer a mano: **3 env groups nuevos** (`alertas`, `neon-api`,
> `r2-lectura`; el job de backup ya tiene los suyos) y **2 Cron Jobs nuevos** (watchdog + drill).
> El de backup ya existe con el nombre `proyecto-crossfit` y **no hay que tocarlo**.
>
> El watchdog corre **6 h después** del backup para dar margen a un reintento manual antes
> de que el email de alerta salga.

### Exit codes (todos los jobs: exit ≠ 0 ⇒ run **rojo** en Render)

| Job | Código | Significado |
|---|---|---|
| backup | 0 / 2 / 3 / 4 / 5 | OK / config / pg_dump / asserts de contenido / R2 |
| watchdog | 0 / 2 / 6 / 7 | OK (sin email) / config (falta variable o R2 inaccesible) / **hay algo que avisar** / inesperado |
| drill | 0 / 2 / 8 / 9 / 10 / 11 / 12 | OK / config (falta variable o cupo de ramas lleno) / descarga-dump ilegible / API Neon / restore o verificación / **la prueba negativa no falló (crítico)** / inesperado |

### Env groups (cero credenciales en el repo)

| Env group | Variables | Lo usan |
|---|---|---|
| `backups-prod` | `PROD_DB_DIRECT_URL`, `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `DRY_RUN`, `RETENTION_DAYS`, `MIN_BYTES`, `MIN_TABLAS`, `BACKUP_PREFIX` | backup, drill |
| `alertas` | `GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`, `ALERT_EMAIL` | watchdog, drill |
| `neon-api` | `NEON_API_KEY`, `NEON_PROJECT_ID` | drill |
| `r2-lectura` | `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (token **solo lectura**) | watchdog |

### Las credenciales: cómo se crean (una sola vez) y a qué grupo van

Se generan en cada proveedor y se pegan **sólo** en Render (*Env Groups*). Ninguna entra al repo
ni a los `.env` locales.

1. **Cloudflare R2 → `backups-prod` (lectura y escritura)**: R2 → *Manage R2 API Tokens* → token
   con *Object Read & Write* limitado al bucket de respaldos. Van al grupo `R2_ENDPOINT`
   (`https://<account-id>.r2.cloudflarestorage.com`), `R2_BUCKET`, `R2_ACCESS_KEY_ID` y
   `R2_SECRET_ACCESS_KEY`. En el mismo grupo, `PROD_DB_DIRECT_URL` = cadena **directa** (host sin
   `-pooler`) del rol de backup `backup_ro` de Neon: el runner rechaza el pooler con exit 2 porque
   `pg_dump` contra PgBouncer se corta.
2. **Cloudflare R2 → `r2-lectura` (sólo lectura)**: **otro** token, mismo bucket, permiso *Object
   Read only*. Es el que usa el watchdog: aunque se filtre, no puede subir ni borrar nada.
3. **Neon → `neon-api`**: Console de Neon → *Account settings → API keys* → crear la key
   (`NEON_API_KEY`) y copiar el `NEON_PROJECT_ID` (*Project → Settings*). Es lo único que permite
   que el drill cree y borre la rama temporal; sin esas 2 variables sale exit 2 **sin tocar nada**.
4. **Gmail → `alertas`**: en la casilla del box (Gmail) → *Seguridad → Verificación en 2 pasos →
   Contraseñas de aplicaciones* → generar una **App Password de 16 caracteres**. Al grupo `alertas`
   van `GMAIL_SMTP_USER` (la casilla, ej. `urban.training.box.2026@gmail.com`),
   `GMAIL_SMTP_APP_PASSWORD` (esa App Password — **no** la password de la cuenta) y `ALERT_EMAIL`
   (la casilla que uno lee). Es el **mismo Gmail que ya usa la app**, así que si el Web Service ya
   tiene esas 2 variables se copian los mismos valores: no hay nada nuevo que crear ni dominio que
   verificar.

En Render: *Env Groups → New Environment Group* con el **nombre exacto** de la tabla de arriba
(`backups-prod`, `alertas`, `neon-api`, `r2-lectura`) y después, en cada Cron Job,
*Environment → Link Environment Group*. Verificación rápida: los valores se ven como `•••` en
el dashboard, y en el log/email de un run sólo pueden aparecer saneados (`://***@`) — nunca la
password del rol ni la key.


### Cómo se entera uno de un problema (3 vías, ninguna depende del log local)
1. **Email** por Gmail SMTP: el drill lo manda **siempre** (OK o FALLA + motivo); el watchdog
   sólo cuando hay alerta.
2. **Run rojo** en Render → *Cron Job → Runs* (exit ≠ 0).
3. **Log del run**: todo lo impreso pasa por `log()`, que sanea (`://***@`) cualquier
   credencial (por eso ni el email ni el log pueden filtrar la password del rol).

### Tests (sin R2, sin Neon, sin red y sin credenciales)
```bash
cd backend
py -3.12 -m pytest tests/test_watchdog_backups.py tests/test_restore_drill.py tests/test_email_config_prod.py -q --noconftest
```
Registrado el 2026-09-27: **26 passed** (8 del watchdog + 10 del drill + 8 de la config de email).
Neon, R2, `psql` y `smtplib` están mockeados: no se usa red ni credenciales y **no se manda ningún
correo real**. Ojo con el intérprete: usar `py -3.12` — el `python` del PATH (3.13) no tiene
`pytest` instalado.

## Drill de restore automático — Fase 4 (2026-09-27)

Un backup que nunca se restauró **no es un backup**. Este Cron Job mensual baja el último
dump de R2, lo restaura en una rama temporal de Neon, verifica que lo restaurado coincida
con lo que el dump dice y comprueba que el rol de backup siga siendo de solo lectura.

| Pieza | Qué es |
|---|---|
| Script | `maintenance/restore_drill.py` |
| Cuándo | día 1 de cada mes, 10:00 CLT (`0 13 1 * *` UTC) |
| Reporte | email por Gmail SMTP **siempre** (OK con números o FALLA con el motivo) |
| Rama temporal | `drill-YYYYMMDD-HHMM`, creada con `init_source="parent-schema"` y borrada en el `finally` |

### Los 8 pasos y sus guardas

| # | Paso | Guarda que aborta antes de tocar nada |
|---|---|---|
| 0 | `contar_ramas()` contra la API | el plan Free permite **10 ramas/proyecto** (`MAX_RAMAS`): si está lleno ⇒ exit 2, **no se crea nada** |
| 1 | Bajar el objeto más nuevo de `daily/` en R2 | sin objetos ⇒ exit 8 · error de red/permiso ⇒ exit 8 |
| 2 | `descomprimir()` + `verificar_dump()` + `esperar_del_dump()` | dump truncado o sin footer `-- PostgreSQL database dump complete` ⇒ exit 8 |
| 3 | Crear la rama temporal (hija del branch por defecto) | error de API ⇒ exit 9 · **si algo falla después, la rama se borra igual** |
| 4 | Crear la base `drill_restore` (`DRILL_DB_NAME`) **nueva y vacía** en esa rama | `contar_tablas() != 0` ⇒ exit 10 **sin restaurar** |
| 5 | `psql_restore()` del dump (una sola transacción) | `returncode != 0` ⇒ exit 10 (con `psql_error` saneado en el email) |
| 6 | `verificar_restore()`: nº de tablas, usuarios y `alembic_version` **contra lo que dice el dump** | lo restaurado no coincide ⇒ exit 10 |
| 7 | `probar_solo_lectura_prod()`: `CREATE TABLE` en PROD **debe** fallar | si **no** falla ⇒ exit 11 + email marcado **CRÍTICO** |

### Decisiones que importan (y por qué)

- **Base nueva y vacía, nunca `neondb`:** una rama de Neon trae el schema del padre copiado,
  así que restaurar sobre `neondb` daría `already exists` en cada `CREATE TABLE` de un dump
  que no usa `--clean`. Por eso el drill crea `drill_restore` y verifica que esté en 0 tablas.
- **`init_source="parent-schema"`:** copia el *schema* del padre (no los datos) y **no cuenta**
  contra el límite de 3 raíces del plan Free (`schema-only` sí crearía una raíz) — y así la
  rama se puede borrar sin arrastrar nada. Textual de la API: `parent-schema` *"copies schema
  only from the parent branch"* y `schema-only` *"creates a new root branch containing schema
  only"* (`BranchCreateRequest.init_source`, verificado en el OpenAPI
  <https://neon.com/api_spec/release/v2.json> y en
  <https://neon.com/docs/reference/api/branches/create-project-branch.md>). Ojo: `parent-data`
  es el **default**, así que el campo se manda explícito; `init_source` no está detrás de
  Early Access (eso es sólo `expires_at`).
- **Nada de umbrales hardcodeados:** en vez de "deberían haber ~35 tablas", se leen el nº de
  `CREATE TABLE` y el `alembic_version` **del propio dump** (`esperar_del_dump`). El drill no
  se rompe cuando se agrega una migración.
- **Prueba negativa obligatoria:** el drill vale por lo que verifica *además* del restore: que
  la credencial de backup no pueda escribir en la base de producción.
- **Neon es asíncrono (fix del 423, run real del 2026-09-27):** crear la rama y crear la base
  devuelven `operations` que siguen corriendo; la llamada siguiente contestaba `HTTP 423 "project
  already has running conflicting operations, scheduling of new ones is prohibited"` (la rama se
  creaba OK y el drill moría con exit 9 enseguida). Ahora, tras cada `POST`, se hace polling de
  `GET /projects/{id}/operations/{op_id}` (cada `DRILL_POLL_S`, timeout `DRILL_OPS_TIMEOUT_S`)
  hasta que TODAS queden en `finished`; `failed`/`error`/`cancelled` ⇒ exit 9 con el motivo. Y
  **toda** llamada a la API reintenta el 423 con backoff 2/4/8 s (hasta `DRILL_INTENTOS_423`):
  el 423 no ejecuta nada, así que reintentar no duplica ramas ni bases. El `DELETE` del `finally`
  espera lo que quedó pendiente (`DRILL_BORRADO_TIMEOUT_S`) para no dejar la rama viva (consume
  cupo del plan Free). Estos 4 `DRILL_*` son opcionales: tienen default.

- **Limpieza garantizada:** la rama y el directorio temporal se borran en el `finally`, pase lo
  que pase. Si el `DELETE` de la rama falla, el email lo dice y hay que borrarla a mano.

### Restauración manual de emergencia (runbook)

Neon guarda historial propio (PITR), pero un dump en R2 es el último recurso si se pierde el
proyecto. Con las variables de `backups-prod` exportadas (o desde el shell del Cron Job):

```bash
# 0. NUNCA pisar PROD: restaurar en una rama temporal y recién ahí decidir.
neonctl branches create --project-id "$NEON_PROJECT_ID" --name rescate \
  --parent "$(neonctl branches list --project-id "$NEON_PROJECT_ID" -o json | jq -r '.[]|select(.default)|.id')"
neonctl databases create --project-id "$NEON_PROJECT_ID" --branch rescate --name rescate_db
```

```bash
# 1. Bajar y descomprimir el último dump (aws cli s3api con las credenciales de R2).
aws s3api list-objects-v2 --endpoint-url "$R2_ENDPOINT" --bucket "$R2_BUCKET" \
  --prefix daily/ --query 'Contents[?ends_with(Key,`sql.gz`)]|sort_by(@,&LastModified)[-1].Key'
aws s3 cp "s3://$R2_BUCKET/daily/<objeto>.sql.gz" . --endpoint-url "$R2_ENDPOINT"
gzip -dk <objeto>.sql.gz
```

```bash
# 2. Restaurar en UNA transacción (atómico: o entra todo o no entra nada).
psql "<uri de la rama rescate>/rescate_db?sslmode=require" \
  -v ON_ERROR_STOP=1 --single-transaction -f <objeto>.sql
```

```bash
# 3. Verificar ANTES de apuntar la app: el dump ya dice cuántas tablas y qué alembic trae.
grep -c '^CREATE TABLE' <objeto>.sql          # esperado del propio dump
psql "<uri>" -tAc 'SELECT count(*) FROM information_schema.tables WHERE table_schema='"'"'public'"'"';'
psql "<uri>" -tAc 'SELECT version_num FROM alembic_version;'
psql "<uri>" -tAc 'SELECT count(*) FROM usuarios;'   # sanity de datos reales
```

```bash
# 4. Recién si los 4 números cuadran: apuntar la app y borrar la rama temporal.
neonctl branches delete rescate --project-id "$NEON_PROJECT_ID"
```

> Todo lo de arriba sale **saneado** en logs y emails: `log()` y `sanear()` reemplazan
> `usuario:password@` por `***`, así que pegar la salida del run en un issue es seguro.

## Cómo dejar los Cron Jobs nuevos corriendo en Render

Mismo patrón que el job de backup que **ya existe** (`proyecto-crossfit`): el Dockerfile ya está
en el repo, no hay que construir nada.

1. Render → **New → Cron Job** → repo `proyecto-crossfit`, branch `main`.
2. **Nombre**: `box-crossfit-watchdog`, `box-crossfit-restore-drill` y
   `box-crossfit-mantenimiento-prod` (los 3 que faltan; el de mantenimiento tiene su propia tabla
   en la sección de la Fase 6).
3. **Dockerfile Path**: `backend/Dockerfile.cron` · **Docker Context**: `backend`.
4. **Command**: el de la tabla de arriba (`python -m maintenance.<script>`).
5. **Schedule**: el de la tabla (`0 12 * * *`, `0 13 1 * *` — en UTC).
6. **Environment Group(s)**: los de la tabla (`r2-lectura` + `alertas`; `backups-prod` +
   `neon-api` + `alertas`; y `mantenimiento-prod` + `alertas` para el de la Fase 6).
7. **Region**: **Oregon (us-west-2)**, la misma del Web Service `box-crossfit`.
8. Guardar y usar **Trigger Run** una vez; el mail del drill tiene que llegar en < 1 min.

> Los horarios se cargan a mano en el dashboard a propósito: así un sync del blueprint no
> crea un job a medio configurar con credenciales incompletas.

## Fase 5 — propuesta: red de seguridad de TEST (SÓLO texto: sin código y sin aplicar)

> **Decisión del 2026-09-27:** el diseño anterior (script `copia_test.py` + un 4º Cron Job en
> Render con bucket y credenciales propias) queda **descartado**, y **no se implementa**. No hay
> ningún archivo creado para eso (verificado con `git status`: no existe `copia_test.py` en el
> repo). Lo de abajo es una propuesta a decidir más adelante: **hoy no se toca nada**.

### Qué hay hoy (y no se cambia)
El contenedor **local** de mantenimiento es el que respalda **TEST** en la laptop:
`docker-compose.yml` → servicio `maintenance` (target `maintenance` del Dockerfile, cron
`/etc/cron.d/box-maintenance`, `TZ=America/Santiago`, `env_file=backend/.env.test`), que corre
`run_daily.py` y adentro `backup_neon.py` (`pg_dump` de la branch TEST de Neon → `.sql` al volumen
`backups`). **Sigue como está.**

Y sigue sin credenciales propias en local: en `.env.test` **no** hay ninguna `R2_*` ni
`ALERT_EMAIL`; lo único de correo que aparece ahí es la configuración de la **app**, que es otra
cosa y queda fuera de esta propuesta. R2 y alertas viven **sólo** en Render
(`backups-prod`, `alertas`, `neon-api`, `r2-lectura`).

### Los 2 cambios propuestos (en texto, sin aplicar)
| # | Qué | Hoy | Propuesta | Dónde se aplicaría |
|---|---|---|---|---|
| 1 | Horario del job diario local | 02:30 CLT (`30 2 * * *`) | **04:30 CLT** (`30 4 * * *`) | `backend/maintenance/crontab` (la línea del `run_daily.py`) |
| 2 | Retención de los dumps locales | 30 días fijos (`timedelta(days=30)` dentro de `backup_neon.py`) | **7 días** | `backup_neon.py`: leer `RETENTION_DAYS` con default `7`, igual que `backup_cloud.py` |

Detalles que importan **si algún día** se aplica:
- El cron del contenedor corre con `TZ=America/Santiago`, así que el horario se escribe **en CLT**
  (`30 4 * * *`) y **no** se convierte a UTC como en los Cron Jobs de Render. Después hay que
  reconstruir el contenedor (`docker compose build maintenance` +
  `docker compose up -d --force-recreate --no-deps maintenance`), porque el `crontab` va copiado
  dentro de la imagen.
- Bajar la retención no borra nada de golpe: `backup_neon.py` purga por `mtime` durante el propio
  dump, así que los `.sql` viejos se van yendo en las corridas siguientes (quedan ≤ ~8 archivos).
  No toca ningún respaldo de PROD: ésos viven en R2 y la retención la aplica el lifecycle del bucket.
- Lo que esta propuesta **no** hace: no agrega scripts, no agrega jobs ni env groups en Render, no
  crea bucket ni prefijo nuevos, no le da credenciales de R2 a la laptop y no automatiza ninguna
  restauración. El drill de Fase 4 sigue siendo la única prueba de restore, y corre en Render.

## Mantenimiento de PROD 2× al mes — Fase 6 (2026-09-27)

Los 5 scripts de mantenimiento de datos sólo corrían en el contenedor **local** (contra TEST,
cuando la laptop está encendida). En PROD no había nada programado: ni vencidos, ni huérfanas,
ni reporte, ni alerta de uso de Neon. Este 4º Cron Job de Render es eso, sin tocar los scripts
locales y sin darle a PROD un usuario con más permisos de los necesarios.

| Pieza | Qué es |
|---|---|
| Script | `maintenance/mantenimiento_cloud.py` |
| Cuándo | días **1 y 15**, `0 8 1,15 * *` **UTC** = 05:00 CLT (04:00 en invierno: el schedule es UTC fijo) |
| Rol de la base | `maint_rw`: `SELECT` en 6 tablas (`alembic_version` incluida) + `UPDATE` **a nivel de columna** en 3 |
| Reporte | email por Gmail SMTP **siempre** (OK / EXCEDE MAX_CAMBIOS / FALLA + motivo) |
| Escritura | los 4 `UPDATE` de los scripts locales, en **UNA sola transacción** |
| Env grupos | `mantenimiento-prod` + `alertas` (no usa R2 ni la API de Neon) |
| Exit codes | 0 OK · 2 config · 3 lectura · 4 integridad · 6 guarda de volumen · 7 escritura · 8 verificación |

### Qué aplica (4 pasos, una transacción)

| # | `UPDATE` | Antes en |
|---|---|---|
| 1 | `suscripciones.estado` → `vencido` (+`updated_at`) si `estado='activo'` y `fecha_expiracion < current_date` | `marcar_plan_vencido.py` |
| 2 | `suscripciones.estado` → `rechazado` (+`updated_at`) si `estado='pendiente'` y `created_at < now() - 7 días` | `transacciones_huerfanas.py` |
| 3 | `solicitudes_planes.estado` → `rejected` (+`comentario_admin`, `updated_at`) si `estado='pending'` y `created_at < now() - 7 días` | `transacciones_huerfanas.py` |
| 4 | `usuarios.estado` → `rechazado` **y** `activo=false` si `estado='pendiente_activacion'` y `created_at < now() - 7 días` | `transacciones_huerfanas.py` |

El paso 4 setea **los dos campos juntos** a propósito: el CHECK `ck_usuarios_activo_estado` de
la migración 034 (`activo = (estado = 'activo')`) rechaza cualquier otro par (es el bug P0-1 que
dejó `marcar_plan_vencido` sin funcionar en TEST).

Y lo que **sólo informa** (no escribe nada): los 5 chequeos de `verificar_integridad.py`
(RUT/correos duplicados, FKs rotas, fechas inválidas), el tamaño de la base contra el free tier
de Neon y el reporte del mes (`reporte_estadisticas.py`). El reporte ya no escribe el JSON local
de antes: en un Cron Job el filesystem es efímero, así que el "reporte" es el mail.

### Por qué `psql` directo y no importar la app (decisión D1)

- **`Dockerfile.cron` no copia `app/`** y la imagen no tiene SQLAlchemy: el job habla con la
  base por `psql`. Cero dependencias nuevas, cero `pip install` nuevo, cero pool de conexiones.
- **`ROLLBACK`/`COMMIT` es nativo**: los 4 pasos van en una sola transacción y la guarda de
  volumen se evalúa *dentro* del SQL (`DO $$ … RAISE EXCEPTION … $$`), no depende del código.
- **Los 5 scripts locales no se refactorizan**: siguen igual, sirviendo a TEST (y al contenedor
  local con `app.db` + `settings.DATABASE_URL`). Este módulo es la versión "de nube".
- La zona horaria se fija en la MISMA sesión que las consultas (`SET TIME ZONE
  'America/Santiago'`), así `current_date` y `now() - interval '7 days'` se calculan en hora de
  Chile igual que lo hacía el ORM del contenedor: el servidor de Neon corre en UTC.

### Guardas (todas antes de tocar nada)

| Guarda | Qué hace | Exit |
|---|---|---|
| Rol dedicado | `MAINT_DB_URL` tiene que ser de `maint_rw` (no `backup_ro`, no `neondb_owner`) y con host **sin** `-pooler` | 2 |
| Entorno | `ENVIRONMENT` tiene que ser exactamente `production` (si no, el job no corre: escribe en PROD) | 2 |
| Config numérica | `MAX_CAMBIOS`/`DIAS_PENDIENTE`/`NEON_*` se validan como enteros en rango **antes** de armar el SQL (nunca se pega texto de una variable de entorno) | 2 |
| Variable faltante | falta cualquier variable obligatoria (incluidas las 3 de `alertas`) | 2 |
| Una transacción | los 4 `UPDATE` van juntos: si cualquiera falla, `ON_ERROR_STOP` + la transacción abierta ⇒ **no se aplica nada** | 7 |
| Guarda de volumen | `DO $$ … RAISE EXCEPTION 'GUARDA DE VOLUMEN: n > MAX_CAMBIOS' … $$` **dentro** de la transacción (en REAL aborta) | 6 |
| Verificación posterior | se vuelven a correr las MISMAS 4 consultas: en REAL tienen que dar 0 | 8 |
| Integridad | los hallazgos ponen el run en **rojo** pero **no** abortan el mantenimiento (decisión del 2026-09-27) | 4 |

### `DRY_RUN` (default `1`, también en la imagen)

Con `DRY_RUN=1` la transacción se ejecuta **completa** y termina en `ROLLBACK`. No es una
estimación: el mail trae exactamente las filas que el `UPDATE` tocó (la tabla temporal
`_maint_cambios` cuenta lo real, no lo que se leyó antes). Además:

- En DRY-RUN la guarda de volumen **no aborta**: informa. Si se pasa del tope, el asunto y el
  cuerpo dicen `EXCEDE MAX_CAMBIOS (n > N): no se aplicaría` y el mail lleva la **lista
  completa** de esas filas. El run queda rojo (exit 6) a propósito, para que no se pierda de
  vista entre los verdes.
- En REAL la guarda **aborta**: no se aplica nada y el mail dice `guarda de volumen: n > N ⇒ la
  transacción abortó y NO se aplicó nada`.

### La primera aplicación real (procedimiento, en orden)

1. **`DRY_RUN=1` + `MAX_CAMBIOS=20`** (como queda al crear el env group) → *Trigger Run*.
2. Leer el mail: la lista completa de lo que se aplicaría. Si el run salió rojo por
   `EXCEDE MAX_CAMBIOS (25 > 20)`, revisar la lista: si esas 25 filas son correctas, se sube
   `MAX_CAMBIOS` al número revisado (**25**), no más.
3. **`DRY_RUN=0` + `MAX_CAMBIOS=25`** → *Trigger Run* **a mano** (no esperar al día 1). El mail
   tiene que decir `APLICADO (25 cambio(s))` y la verificación `n → 0 (esperado 0)`.
4. Bajar `MAX_CAMBIOS` a **20** y dejar `DRY_RUN=0`. Desde ahí corre solo los días 1 y 15.
5. Comparar `planes_vencidos_mes` del reporte del mail con la cantidad de filas que el job
   marcó como vencidas ese día: tienen que ser coherentes (si no, algo del criterio cambió).

> Si en una corrida normal aparecen de golpe más de `MAX_CAMBIOS` cambios, la guarda aborta y el
> mail lo dice: eso es una señal para mirar (¿un bug? ¿una importación?), no para subir el tope.

### Enterarse de un problema (3 vías, ninguna depende de la laptop)

1. **Email** (siempre, verde o rojo): asunto `[Mantenimiento PROD] <estado> — <motivo>`.
2. **Run rojo** en Render → *Cron Job `box-crossfit-mantenimiento-prod` → Runs* (exit ≠ 0).
3. **Log del run**: todo pasa por `log()` → `sanear()`, así que pegar el log en un issue es
   seguro (la URL sale como `://***@`). El JSON del reporte mensual ya no se escribe a disco.

### El rol `maint_rw`: se crea SÓLO por SQL (nunca desde la consola de Neon)

> ⚠️ **No crear el rol desde la consola de Neon.** Los roles que crea la consola quedan como
> miembros de `neon_superuser` (heredan todo) y anulan cualquier contención. Se crea por SQL y se
> verifica con `pg_has_role(...)` + `has_*_privilege(...)`.

```sql
-- 0) Con la conexión del owner del proyecto (neondb_owner). La password se genera antes,
--    SÓLO alfanumérica (32 caracteres) y se pega SÓLO en el env group de Render: no va al repo.
--    ⚠️ NO usar `openssl rand -base64`: trae `+` `/` `=` y rompen la URL (hay que escaparlos en
--    la URI y `psql`/`urlsplit` no lo leen igual), así que se evita el problema de raíz.
--    PowerShell:
--      -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 32 | % {[char]$_})
CREATE ROLE maint_rw WITH LOGIN NOINHERIT PASSWORD '<password-generada>';

-- 1) Entrar: CONNECT a la base + USAGE del esquema. Por defecto los da PUBLIC, pero se
--    otorgan explícito para que el permiso quede escrito (y sobreviva a un REVOKE de PUBLIC).
--    `TEMP` NO se otorga acá: también es un default de PUBLIC y es lo que habilita la
--    `CREATE TEMP TABLE _maint_cambios` del script.
GRANT CONNECT ON DATABASE neondb TO maint_rw;
GRANT USAGE   ON SCHEMA   public TO maint_rw;

-- 2) Lectura: sólo las 6 tablas que el job consulta = las 5 del mantenimiento +
--    `alembic_version` (se lee para el encabezado del mail).
--    OJO: `solicitudes_planes` necesita SELECT para el UPDATE … WHERE estado/created_at y
--    para el RETURNING (sin eso falla con "permission denied for table solicitudes_planes").
GRANT SELECT ON public.usuarios, public.planes, public.suscripciones,
                public.solicitudes_planes, public.transacciones_financieras,
                public.alembic_version TO maint_rw;

-- 3) Escritura: UPDATE a NIVEL DE COLUMNA (el resto del registro queda intacto).
GRANT UPDATE (estado, updated_at)                   ON public.suscripciones      TO maint_rw;
GRANT UPDATE (estado, comentario_admin, updated_at) ON public.solicitudes_planes TO maint_rw;
GRANT UPDATE (estado, activo)                       ON public.usuarios           TO maint_rw;

-- 4) Nada de INSERT / DELETE / TRUNCATE / DDL: no se otorga nada más (y NO hay memberships).
```

> Si la base no se llamara `neondb`, cambiá el nombre en el `GRANT CONNECT` (o usá
> `current_database()`) — el resto del SQL es igual.

#### Verificación (todo tiene que dar `t` / `f` como dice el comentario)

```sql
-- Entrar (3 × t): conexión, esquema y TEMP (la tabla temporal del script)
SELECT has_database_privilege('maint_rw',current_database(),'CONNECT')              AS db_connect,
       has_schema_privilege('maint_rw','public','USAGE')                            AS schema_usage,
       has_database_privilege('maint_rw',current_database(),'TEMP')                 AS db_temp;

-- Lectura (6 × t)
SELECT has_table_privilege('maint_rw','public.usuarios','SELECT')                  AS usuarios_select,
       has_table_privilege('maint_rw','public.planes','SELECT')                    AS planes_select,
       has_table_privilege('maint_rw','public.suscripciones','SELECT')             AS suscripciones_select,
       has_table_privilege('maint_rw','public.solicitudes_planes','SELECT')        AS solicitudes_select,
       has_table_privilege('maint_rw','public.transacciones_financieras','SELECT') AS transacciones_select,
       has_table_privilege('maint_rw','public.alembic_version','SELECT')           AS alembic_select;

-- Escritura exacta (7 × t y nada más)
SELECT has_column_privilege('maint_rw','public.suscripciones','estado','UPDATE')                AS s_estado,
       has_column_privilege('maint_rw','public.suscripciones','updated_at','UPDATE')            AS s_updated_at,
       has_column_privilege('maint_rw','public.solicitudes_planes','estado','UPDATE')           AS p_estado,
       has_column_privilege('maint_rw','public.solicitudes_planes','comentario_admin','UPDATE') AS p_comentario,
       has_column_privilege('maint_rw','public.solicitudes_planes','updated_at','UPDATE')       AS p_updated_at,
       has_column_privilege('maint_rw','public.usuarios','estado','UPDATE')                     AS u_estado,
       has_column_privilege('maint_rw','public.usuarios','activo','UPDATE')                     AS u_activo;

-- Lo que NO puede hacer (12 × f): columnas prohibidas, INSERT/DELETE/TRUNCATE y DDL
SELECT has_column_privilege('maint_rw','public.usuarios','nombre','UPDATE')            AS u_nombre_update,
       has_column_privilege('maint_rw','public.suscripciones','plan_id','UPDATE')      AS s_plan_update,
       has_column_privilege('maint_rw','public.suscripciones','usuario_id','UPDATE')   AS s_usuario_update,
       has_table_privilege('maint_rw','public.usuarios','INSERT')                      AS u_insert,
       has_table_privilege('maint_rw','public.usuarios','DELETE')                      AS u_delete,
       has_table_privilege('maint_rw','public.usuarios','TRUNCATE')                    AS u_truncate,
       has_table_privilege('maint_rw','public.usuarios','REFERENCES')                  AS u_references,
       has_table_privilege('maint_rw','public.suscripciones','INSERT')                 AS s_insert,
       has_table_privilege('maint_rw','public.solicitudes_planes','DELETE')            AS p_delete,
       has_schema_privilege('maint_rw','public','CREATE')                              AS schema_create,
       has_database_privilege('maint_rw',current_database(),'CREATE')                  AS db_create,
       has_function_privilege('maint_rw','version()','EXECUTE')                        AS fn_execute;

-- Y que NO sea miembro de neon_superuser (es el chequeo que atrapa el rol creado por consola)
SELECT pg_has_role('maint_rw','neon_superuser','member')                               AS es_superuser;   -- f

-- Ver EXACTAMENTE lo que tiene (tienen que ser 7 filas, todas de UPDATE)
SELECT table_name, column_name, privilege_type
FROM information_schema.role_column_grants WHERE grantee = 'maint_rw'
ORDER BY table_name, column_name;
```

#### Prueba negativa (con la URL de `maint_rw`, antes de encender el job)

```bash
# Las dos DEBEN fallar con "permission denied"; el ROLLBACK no deja nada.
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c 'BEGIN; CREATE TABLE _maint_no_debe_poder (i int); ROLLBACK;'
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c 'BEGIN; DELETE FROM usuarios WHERE false; ROLLBACK;'
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c "UPDATE usuarios SET nombre = nombre WHERE false;"
```

#### Reversión (deshacer todo sin dejar rastro)

```sql
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM maint_rw;
REVOKE USAGE   ON SCHEMA   public FROM maint_rw;
REVOKE CONNECT ON DATABASE neondb FROM maint_rw;
DROP ROLE maint_rw;                            -- falla si le quedó algún privilegio: es a propósito
```
(El default de PUBLIC sigue dando CONNECT/USAGE/TEMP al resto de los roles: revocárselos a
`maint_rw` sólo le quita lo que se le otorgó a él.)
Y en Render: borrar el Cron Job y el env group `mantenimiento-prod` (la password muere con el
rol). El chequeo final es `SELECT rolname FROM pg_roles WHERE rolname = 'maint_rw';` ⇒ 0 filas.

### Env group `mantenimiento-prod` (Render → *Env Groups → New*)

| Variable | Valor |
|---|---|
| `MAINT_DB_URL` | `postgresql://maint_rw:<password>@ep-<endpoint>.us-west-2.aws.neon.tech/neondb?sslmode=require` (**directa**, sin `-pooler`) |
| `ENVIRONMENT` | `production` |
| `MAX_CAMBIOS` | `20` (ver el procedimiento de la primera aplicación real) |
| `DIAS_PENDIENTE` | `7` |
| `NEON_LIMITE_MB` | `512` (free tier de Neon: **0,5 GB por proyecto**; la alerta se calcula contra esto, no contra los 3 GB que decía `neon_usage_alerts.py`) |
| `NEON_UMBRAL_PCT` | `80` |
| `DRY_RUN` | `1` (arranca así; se apaga en el paso 3 de la puesta en marcha) |

Más el env group `alertas` (`GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`, `ALERT_EMAIL`, los
mismos valores del Web Service). **No** se enlaza `backups-prod` (este job no toca R2) ni
`neon-api` (no crea ni borra ramas). `TZ=America/Santiago` ya viene en la imagen.

### El Cron Job en Render

| Campo | Valor |
|---|---|
| Name | `box-crossfit-mantenimiento-prod` |
| Repo / Branch | `proyecto-crossfit` / `main` |
| Dockerfile Path | `backend/Dockerfile.cron` |
| Docker Context | `backend` |
| Command | `python -m maintenance.mantenimiento_cloud` |
| Schedule | `0 8 1,15 * *` (UTC) = 05:00 CLT (04:00 con horario de invierno: es UTC fijo) |
| Environment Groups | `mantenimiento-prod` + `alertas` |
| Region | **Oregon (us-west-2)** (la misma del Web Service) |
| Plan | Starter (el mismo de los otros 3 Cron Jobs) |

Pasos: **New → Cron Job** → completar la tabla → **Guardar** → **Trigger Run** una vez y mirar el
mail (con `DRY_RUN=1` no aplica nada). El Dockerfile ya está en el repo: la única línea nueva es
`COPY maintenance/mantenimiento_cloud.py`, y no hace falta ningún `pip install` nuevo porque el
job no importa la app ni boto3.

### Qué NO hace (a propósito)

- **No toca TEST**: ni el contenedor local, ni `backup_neon.py`, ni el `.env.test`. Los 5 scripts
  locales quedan igual y siguen sirviendo a TEST.
- **No reemplaza el backup ni el drill**: `backup_cloud`, `watchdog_backups` y `restore_drill`
  no se tocan.
- **No limpia logs ni rota credenciales ni pingea la API**: `cleanup_logs`, `rotar_credenciales`
  y `health_check` son del contenedor local (`health_check` apunta a `localhost:8000`, que en un
  Cron Job no existe).
- **No usa la app**: no importa `app.*`, no usa `email_service.py` ni SQLAlchemy. El correo sale
  por `maintenance/alertas.py` (Gmail SMTP), la única vía permitida.
- **No hay endpoint nuevo**: los endpoints n8n de `app/api/v1/mantenimiento.py` quedan fuera de
  PROD (guarda de entorno: 404 si `ENVIRONMENT != "test"`) y **no** fueron la vía elegida para
  este job (los workflows de n8n los desactiva Jebbus en la UI).

### Tests (sin Neon, sin psql, sin red y sin mandar correos)

```bash
cd backend
py -3.12 -m pytest tests/test_mantenimiento_cloud.py tests/test_mantenimiento_pasos.py -q --noconftest
```
Registrado el 2026-09-27: **26 passed** (22 de `mantenimiento_cloud` + 4 del fix H1 de
`run_daily`/`run_monthly`). `psql` y `smtplib` están mockeados: no se usa red ni credenciales y
**no se manda ningún correo real**. ⚠️ Usar `py -3.12`: el `python` del PATH (3.13) no tiene
`pytest`.

## Estado y limitaciones (2026-09-27, sin commit)




- **Verificado (cerrado el pendiente):** `init_source="parent-schema"` **existe** en la API; no
  es un valor inventado. Textual en el OpenAPI v2 (`BranchCreateRequest.init_source` y el propio
  objeto `Branch`) y en la doc
  <https://neon.com/docs/reference/api/branches/create-project-branch.md>: *"`parent-data` copies
  schema and data from the parent branch. `parent-schema` copies schema only from the parent
  branch. `schema-only` creates a new root branch containing schema only…"*. Como `parent-data`
  es el **default**, el campo se manda explícito; y `schema-only` es el que crearía raíz, así que
  la elección del drill queda confirmada.
- **Verificado:** `py -3.12 -m py_compile maintenance/restore_drill.py maintenance/watchdog_backups.py
  maintenance/alertas.py` ⇒ rc 0, y `py -3.12 -m pytest tests/test_watchdog_backups.py
  tests/test_restore_drill.py tests/test_email_config_prod.py -q --noconftest` ⇒ **26 passed**
  (8 + 10 + 8, con Neon/R2/psql/smtplib mockeados: no se usó red ni credenciales).
  ⚠️ Usar `py -3.12`: el `python` del PATH (3.13) **no** tiene pytest.
- **Verificado (smoke sin credenciales):** con el entorno vacío, `restore_drill` sale con
  exit 2 ("faltan variables") y el watchdog también — sin mandar ningún mail.
- **Verificado en Render (run real del 2026-09-27):** el drill corrió contra Neon real: la rama
  temporal se creó y se **borró** bien en el `finally`, pero murió con
  `HTTP 423 "project already has running conflicting operations..."` (exit 9) en la llamada
  siguiente ⇒ fix de arriba (esperar `operations` + reintentar 423), cubierto por los tests
  h/i/j (mocks, sin red). **Falta el `Trigger Run` verde de punta a punta** (restore real +
  prueba negativa contra PROD): mirar el email y la lista de ramas de Neon.
- **Fase 5:** queda **sólo como propuesta escrita** (sección "Fase 5" de arriba). No se escribió
  `copia_test.py` ni ningún script/job nuevo, y el contenedor local de mantenimiento quedó igual.
  Los 2 cambios propuestos (04:30 CLT y retención de 7 días) **no** se aplicaron.
- **Regla permanente (2026-09-27): todo envío de correo va exclusivamente por Gmail SMTP; está
  prohibido cualquier otro proveedor.** `maintenance/alertas.py` manda por `smtp.gmail.com:465` +
  `SMTP_SSL` con `GMAIL_SMTP_USER`/`GMAIL_SMTP_APP_PASSWORD` (env group `alertas`, los mismos
  valores que ya usa el Web Service) y **no importa ni toca** `app/services/email_service.py`, que
  usa el mismo host y puerto. No hay segundo proveedor, ni librería de terceros, ni API key
  externa, ni dominio que verificar.
- **Sin tocar:** nada de `carpeta_respaldo_box`, ni `.env`/`.env.test`, ni PROD (el único acceso
  a PROD es el `CREATE TABLE` que **debe** fallar), ni `git` (todo sigue sin commit/push).
- **Fase 6 (entrega 2, 2026-09-27):** se escribió `maintenance/mantenimiento_cloud.py`, se agregó
  su `COPY` en `Dockerfile.cron` (sin `pip install` nuevo), se aplicó el **fix H1** en
  `run_daily.py`/`run_monthly.py` (el `_paso()` nuevo mira el valor de retorno real: un `False` se
  loguea como ❌ y el resumen final dice cuántos pasos fallaron) y la **guarda de entorno (H4)** en
  `app/api/v1/mantenimiento.py` (**va en un commit separado**: fuera de TEST esos endpoints n8n
  responden 404).
- **Verificado (Fase 6):** `py -3.12 -m py_compile maintenance/mantenimiento_cloud.py
  maintenance/run_daily.py maintenance/run_monthly.py` ⇒ rc 0. Smoke sin variables:
  `py -3.12 -m maintenance.mantenimiento_cloud` ⇒ **exit 2** ("faltan variables de entorno:
  MAINT_DB_URL, ENVIRONMENT, GMAIL_SMTP_USER, GMAIL_SMTP_APP_PASSWORD, ALERT_EMAIL"), sin red y
  sin credenciales. Tests: `tests/test_mantenimiento_cloud.py` (22) +
  `tests/test_mantenimiento_pasos.py` (4) ⇒ **26 passed**, y los 4 archivos de tests que ya
  existían siguen verdes (26 passed, 1 skipped).
- **Verificado (H4, con `TestClient`):** con `ENVIRONMENT=production` los 2 endpoints n8n
  responden **404** (sin llegar a mirar la API key); con `ENVIRONMENT=test` y una key inválida
  responden **401** ⇒ la guarda no rompió el chequeo de la key ni el camino de TEST.
- **Pendiente (necesita OK del dueño, nada de esto se tocó):** crear el rol `maint_rw` en Neon
  (SQL del README + verificación + prueba negativa), crear el env group `mantenimiento-prod`,
  crear el 4º Cron Job en Render y hacer la puesta en marcha por fases (`DRY_RUN=1` → leer el mail
  → `DRY_RUN=0` con `MAX_CAMBIOS` revisado → bajarlo a 20).
- **Menor, sigue pendiente:** volcar/desactivar los workflows de n8n "Mantenimiento %" (H2/H5):
  los desactiva Jebbus en la UI de n8n (el job nuevo no depende de n8n).

