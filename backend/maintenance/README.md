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

## Alertas por correo: la regla es "correo = algo que revisar" (2026-09-27)

Los 4 Cron Jobs comparten **un solo camino de correo** (`maintenance/alertas.py` → Gmail SMTP) y
**una sola regla**: el mail sale **sólo si hay algo que revisar**. Un run normal (verde) deja
**únicamente el log** en Render. El correo es una **alerta, no un informe**: un buzón que recibe
"todo OK" todos los días termina ignorándose, y entonces la alerta de verdad tampoco se lee.

| Job | ¿Cuándo manda correo? | Exit |
|---|---|---|
| `backup_cloud` (job `proyecto-crossfit`) | **nunca**: no manda correo. Si el dump falla, el run queda rojo en Render y el que avisa es el watchdog | 2/3/4/5 |
| `watchdog_backups` | sólo si hay alerta de frescura/tamaño (asunto `[ALERTA] Watchdog backups PROD: …`) | 6 |
| `restore_drill` | sólo si el run falla (exit ≠ 0) o si la rama temporal quedó viva | 13 |
| `mantenimiento_cloud` | sólo si el run falla (exit ≠ 0: config, lectura, escritura, verificación, guarda de volumen, integridad) o si Neon pasó `NEON_UMBRAL_PCT` | ≠ 0 |

Todos los asuntos empiezan con **`[ALERTA]`** + el job + **qué pasó**, así la notificación del
teléfono ya dice de qué se trata sin abrir el correo (el motivo detallado va en el cuerpo, junto
con las listas completas):

```
[ALERTA] Mantenimiento PROD: excede MAX_VENCIDOS_PCT (130 > 120) — la guarda de volumen no aborta en DRY-RUN: …
[ALERTA] Mantenimiento PROD: excede MAX_HUERFANAS (13 > 10) — la guarda de volumen no aborta en DRY-RUN: …
[ALERTA] Mantenimiento PROD: excede MAX_CAMBIOS (512 > 500) — la guarda de volumen no aborta en DRY-RUN: …
[ALERTA] Mantenimiento PROD: Neon al 83.98% del free tier (430.0 MB de 512 MB)
[ALERTA] Mantenimiento PROD: integridad con 2 problema(s) — los datos se actualizaron igual: …
[ALERTA] Drill de restore PROD: CRÍTICO: EL ROL DE BACKUP PUDO CREAR UNA TABLA EN PROD …
[ALERTA] Drill de restore PROD: la rama temporal br-drill-20261001-1000 quedó viva …
```

> El **watchdog** (Fase 3, ya en producción) usa el asunto `[ALERTA] Watchdog backups PROD: …`
> y el job de **backup no manda correo** (sus fallas se ven como run rojo en Render; el watchdog es
> el que avisa). Ninguno de los dos archivos se tocó en este cambio: su comportamiento "sólo si hay
> problema" ya era el correcto. Si se quiere el mismo prefijo `[ALERTA]` también ahí, es un cambio
> aparte.

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
| `box-crossfit-restore-drill` | **hay que crearlo** | `0 13 1 * *` | 10:00 el día 1 | `backend/Dockerfile.cron` · `python -m maintenance.restore_drill` | `backups-prod` + `neon-api` + `alertas` | 2/8/9/10/11/12/13 |

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
| drill | 0 / 2 / 8 / 9 / 10 / 11 / 12 / 13 | OK (sin email) / config (falta variable o cupo de ramas lleno) / descarga-dump ilegible / API Neon / restore o verificación / **la prueba negativa no falló (crítico)** / inesperado / **la rama temporal quedó viva** (con el resto del drill OK) |
| mantenimiento | 0 / 2 / 3 / 4 / 6 / 7 / 8 / **9** | OK (sin email, salvo que Neon pase el umbral de espacio o haya un aviso de CU-horas/ramas) / config / lectura / integridad / guarda de volumen (`MAX_VENCIDOS_PCT`, `MAX_HUERFANAS`, `MAX_CAMBIOS`, `MAX_CIERRE`, `MAX_PURGA`) / escritura / verificación / **detecciones A.1–A.6 o un chequeo de Neon que no pudo correr** |

### Env groups (cero credenciales en el repo)

| Env group | Variables | Lo usan |
|---|---|---|
| `backups-prod` | `PROD_DB_DIRECT_URL`, `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `DRY_RUN`, `RETENTION_DAYS`, `MIN_BYTES`, `MIN_TABLAS`, `BACKUP_PREFIX` | backup, drill |
| `alertas` | `GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`, `ALERT_EMAIL` | watchdog, drill, mantenimiento |
| `neon-api` | `NEON_API_KEY`, `NEON_PROJECT_ID` | drill, mantenimiento (sólo lectura) |
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
1. **Email** por Gmail SMTP, con la regla "correo = algo que revisar": el drill avisa **sólo si
   falla** (o si la rama quedó viva) y el watchdog **sólo cuando hay alerta**. Si todo sale bien no
   hay correo (ni tampoco en el día 1 del drill, que es lo normal).
2. **Run rojo** en Render → *Cron Job → Runs* (exit ≠ 0).
3. **Log del run**: todo lo impreso pasa por `log()`, que sanea (`://***@`) cualquier
   credencial (por eso ni el email ni el log pueden filtrar la password del rol).

### Tests (sin R2, sin Neon, sin red y sin credenciales)
```bash
cd backend
py -3.12 -m pytest tests/test_watchdog_backups.py tests/test_restore_drill.py tests/test_email_config_prod.py -q --noconftest
```
Registrado el 2026-09-27: **28 passed** (8 del watchdog + 12 del drill + 8 de la config de email).
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
| Reporte | email por Gmail SMTP **sólo si hay algo que revisar** (exit ≠ 0 o rama viva; asunto `[ALERTA] Drill de restore PROD: <motivo>`). Un drill verde deja **sólo log** |
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
  que pase. Si el `DELETE` de la rama falla, **el run no puede quedar verde**: sale exit **13** y
  se manda la alerta `[ALERTA] Drill de restore PROD: la rama temporal … quedó viva` (si el drill
  ya venía rojo conserva su exit code y el log lo dice). Igual hay que borrarla a mano.

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
8. Guardar y usar **Trigger Run** una vez. ⚠️ Con la regla "correo = algo que revisar", un drill
   **verde NO manda correo**: hay que mirar el log del run (`Restored OK…`) y que el run quede
   verde. Si algo falla, ahí sí llega el `[ALERTA] Drill de restore PROD: …`.

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
| Rol de la base | `maint_rw`: `SELECT` en 12 tablas + `UPDATE` **a nivel de columna** en 5 + `DELETE` en 2 (sólo la purga: ver Fase 7) |
| Reporte | email por Gmail SMTP **sólo si hay algo que revisar**: exit ≠ 0 (config, lectura, escritura, verificación, guarda de volumen, integridad) o Neon pasado del umbral de espacio. Asunto `[ALERTA] Mantenimiento PROD: <qué pasó> — <motivo>`. Un día normal (aplicar y verificar) deja **sólo log** |
| Escritura | los 4 `UPDATE` de los scripts locales, en **UNA sola transacción** |
| Env grupos | `mantenimiento-prod` + `alertas` (ni R2; la API de Neon se usa SÓLO para leer CU-horas y ramas desde la Fase 7, con el env group `neon-api`) |
| Exit codes | 0 OK · 2 config · 3 lectura · 4 integridad · 6 guarda de volumen (por regla) · 7 escritura · 8 verificación · **9** (detecciones y chequeos de Neon: Fase 7) |

### Qué aplica (4 pasos, una transacción)

| # | `UPDATE` | Antes en |
|---|---|---|
| 1 | `suscripciones.estado` → `vencido` (+`updated_at`) si `estado='activo'` y `fecha_expiracion < current_date` | `marcar_plan_vencido.py` |
| 2 | `suscripciones.estado` → `rechazado` (+`updated_at`) si `estado='pendiente'` y `created_at < now() - 7 días` | `transacciones_huerfanas.py` |
| 3 | `solicitudes_planes.estado` → `rejected` (+`comentario_admin`, `updated_at`) si `estado='pending'` y `created_at < now() - 7 días` | `transacciones_huerfanas.py` |
| 4 | `usuarios.estado` → `rechazado` **y** `activo=false` si `estado='pendiente_activacion'` y `created_at < now() - 7 días` | `transacciones_huerfanas.py` |

> Desde la Fase 7 estos 4 pasos son la **transacción 1 de 3** (después van la consistencia y
> la purga): ver "Mantenimiento de PROD 2× al mes — Fase 7" más abajo.
>
El paso 4 setea **los dos campos juntos** a propósito: el CHECK `ck_usuarios_activo_estado` de
la migración 034 (`activo = (estado = 'activo')`) rechaza cualquier otro par (es el bug P0-1 que
dejó `marcar_plan_vencido` sin funcionar en TEST).

Y lo que **sólo informa** (no escribe nada): los 5 chequeos de `verificar_integridad.py`
(RUT/correos duplicados, FKs rotas, fechas inválidas), el tamaño de la base contra el free tier
de Neon y el reporte del mes (`reporte_estadisticas.py`). El reporte ya no escribe el JSON local
de antes: en un Cron Job el filesystem es efímero, y desde la regla "correo = algo que revisar" el
reporte viaja **dentro de la alerta** (o queda sólo en el log si el run está verde).

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
| Config numérica | `MAX_CAMBIOS`/`MAX_VENCIDOS_PCT`/`MAX_HUERFANAS`/`DIAS_PENDIENTE`/`NEON_*` se validan como enteros en rango **antes** de armar el SQL (nunca se pega texto de una variable de entorno) | 2 |
| Variable faltante | falta cualquier variable obligatoria (incluidas las 3 de `alertas`) | 2 |
| Una transacción | los 4 `UPDATE` van juntos: si cualquiera falla, `ON_ERROR_STOP` + la transacción abierta ⇒ **no se aplica nada** | 7 |
| Guarda de volumen | `DO $$ … RAISE EXCEPTION 'GUARDA DE VOLUMEN: …' … $$` **dentro** de la transacción (en REAL aborta): % de vencidos, `MAX_HUERFANAS` por lista y `MAX_CAMBIOS` global | 6 |
| Verificación posterior | se vuelven a correr las MISMAS 4 consultas: en REAL tienen que dar 0 | 8 |
| Integridad | los hallazgos ponen el run en **rojo** pero **no** abortan el mantenimiento (decisión del 2026-09-27) | 4 |

### `DRY_RUN` (default `1`, también en la imagen)

Con `DRY_RUN=1` la transacción se ejecuta **completa** y termina en `ROLLBACK`. No es una
estimación: el log (y la alerta, cuando la hay) trae exactamente las filas que el `UPDATE` tocó
(la tabla temporal `_maint_cambios` cuenta lo real, no lo que se leyó antes). Además:

- En DRY-RUN las guardas **no abortan**: informan. Si se pasa **cualquier** tope, el asunto nombra
  la regla que cortó (`… excede MAX_VENCIDOS_PCT (n > N)`, `… excede MAX_HUERFANAS (n > N)` o
  `… excede MAX_CAMBIOS (n > N)`) y el cuerpo dice "no se aplicaría
  nada" + lleva la **lista completa** de esas filas y **cada regla con su conteo y su tope**
  (bloque `Límites de volumen`). El run queda rojo (exit 6) a propósito,
  para que no se pierda de vista entre los verdes.
- En REAL las guardas **abortan**, dentro del propio SQL: no se aplica nada y el asunto es el mismo
  `[ALERTA] Mantenimiento PROD: excede MAX_VENCIDOS_PCT (n > N)` con el motivo "la transacción
  abortó por la guarda de volumen y NO se aplicó nada" (más el `GUARDA DE VOLUMEN` de psql
  saneado en el cuerpo).

### Guardas de volumen POR REGLA (2026-09-27)

Un único tope global bloqueaba justo el día en que el volumen es **esperable**: los planes vencen
el ÚLTIMO día del mes, así que el run del día 1 marca vencidos a todos los que no renovaron (con
`MAX_CAMBIOS=40` el job abortaba ese día). Las huérfanas, en cambio, son pocas por definición.
Ahora hay 3 reglas, evaluadas todas por la MISMA función pura (`evaluar_limites()`: conteos +
config → reglas, sin base, sin reloj y sin entorno):

| Regla | Qué cuenta | Cuándo corta | Default |
|---|---|---|---|
| `MAX_VENCIDOS_PCT` | suscripciones que pasan a `vencido` vs. el universo previo | `vencidos * 100 > activas * pct` (enteros: sin floats) | `80` % |
| `MAX_HUERFANAS` | **cada** una de las 3 listas de huérfanas (`_maint_cambios` por paso) | `n > MAX_HUERFANAS` | `10` |
| `MAX_CAMBIOS` | total de filas del run | `n > MAX_CAMBIOS` | `500` |

El denominador del % es el **mismo universo del que salen los vencidos** (`suscripciones` en el
estado que ese paso evalúa, antes de aplicar), con **una sola constante SQL** compartida por la
lectura previa, el reporte del mes y la guarda: así el numerador es subconjunto del denominador y
el % nunca pasa de 100 (`MAX_VENCIDOS_PCT=100` no puede cortar nunca).

Dónde se evalúa cada una:

- **DRY-RUN:** Python (`evaluar_limites()`) con lo que la transacción midió más el universo leído
  antes. Informa con la lista completa y **no** aborta.
- **REAL:** adentro de la transacción, en el SQL: el % **antes del paso 1** (único momento en el que
  `estado = 'activo'` sigue siendo el universo previo) y `MAX_HUERFANAS`/`MAX_CAMBIOS` al final,
  sobre `_maint_cambios` (lo que la transacción REALMENTE tocó). Las transacciones 2 y 3 siguen con
  su único tope (`MAX_CIERRE`, `MAX_PURGA`).

El log del run trae una línea con todas las reglas (`Límites: …=conteo/tope · …`, con `EXCEDE` en
la que cortó) y el correo un bloque `Límites de volumen` con cada regla, su conteo, su tope y 🚨 en
la que se pasó. La configuración se lee **sólo** en `leer_config()` (los `os.getenv` del módulo
viven ahí, y hay un test que lo verifica con el AST del archivo).

### La primera aplicación real (procedimiento, en orden)

1. **`DRY_RUN=1`** (como queda al crear el env group, con los defaults `MAX_VENCIDOS_PCT=80`,
   `MAX_HUERFANAS=10` y `MAX_CAMBIOS=500`) → *Trigger Run*. Si el run queda **verde, no llega
   ningún correo**: eso es lo normal (mirar el log del run). El correo sale sólo si alguna regla se
   pasó, y el asunto dice **cuál**.
2. Si llegó esa alerta: leer la lista completa (`Alumno`, plan, fecha) y el bloque `Límites de
   volumen` (el número exacto de cada regla). El día 1 el volumen de vencimientos es el esperado: si
   corta por `MAX_VENCIDOS_PCT`, la decisión es **subir el porcentaje** con ese número a la vista
   (no sacar la regla). Si corta por `MAX_HUERFANAS` (pocas filas: anomalía) o por `MAX_CAMBIOS`,
   primero mirar por qué.
3. **`DRY_RUN=0`** → *Trigger Run* **a mano** (no esperar al día 1). Ahí se aplican los cambios:
   si todo cuadra, el log dice `Transacción aplicada y verificada: n cambio(s)` y **no hay correo**
   (la verificación debe dar `n → 0 (esperado 0)`).
4. Dejar `DRY_RUN=0` con los topes decididos (`MAX_VENCIDOS_PCT=80`, `MAX_HUERFANAS=10`,
   `MAX_CAMBIOS=500`). Desde ahí corre solo los días 1 y 15.
5. Comparar `planes_vencidos_mes` del log con la cantidad de filas que el job marcó como vencidas
   ese día: tienen que ser coherentes (si no, algo del criterio cambió).

> Si en una corrida normal aparecen de golpe más huérfanas de las esperadas, o el % de vencidos se
> dispara muy por encima de lo normal, la guarda aborta y la alerta lo dice: eso es una señal para
> mirar (¿un bug? ¿una importación?), no para subir el tope.

### Enterarse de un problema (3 vías, ninguna depende de la laptop)

1. **Email**: sólo cuando hay algo que revisar (exit ≠ 0 o Neon pasado del umbral). Asunto
   `[ALERTA] Mantenimiento PROD: <qué pasó> — <motivo>`; el cuerpo trae el motivo, las listas
   completas, la integridad, Neon y el reporte del mes. **Un run verde no manda correo.**
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

-- 2) Lectura: las 12 tablas que el job consulta = las 6 de la Fase 6 + las 6 que
--    agregó la Fase 7 (`reservas`, `clases`, `disciplinas`, `coach_disciplinas`,
--    `password_reset_tokens`, `notificaciones_enviadas`).
--    OJO: `solicitudes_planes` necesita SELECT para el UPDATE ... WHERE estado/created_at y
--    para el RETURNING (sin eso falla con "permission denied for table solicitudes_planes").
GRANT SELECT ON public.usuarios, public.planes, public.suscripciones,
                public.solicitudes_planes, public.transacciones_financieras,
                public.alembic_version,
                -- Fase 7: reservas/clases/disciplinas para A.2/A.4/A.5 y para el paso 8-9,
                -- y las 2 tablas de la purga (necesitan SELECT para la lista del mail y para
                -- la verificación: `DELETE ... RETURNING` también exige SELECT).
                public.reservas, public.clases, public.disciplinas, public.coach_disciplinas,
                public.password_reset_tokens, public.notificaciones_enviadas TO maint_rw;

-- 3) Escritura: UPDATE a NIVEL DE COLUMNA (el resto del registro queda intacto).
--    Las 3 primeras son de la Fase 6; las 2 últimas, de la consistencia (paso 8-9).
GRANT UPDATE (estado, updated_at)                   ON public.suscripciones      TO maint_rw;
GRANT UPDATE (estado, comentario_admin, updated_at) ON public.solicitudes_planes TO maint_rw;
GRANT UPDATE (estado, activo)                       ON public.usuarios           TO maint_rw;
--    Paso 8: SOLO la auditoría del cierre. `estado` no se toca (D-6: conserva los KPIs de
--    asistencia ya publicados).
GRANT UPDATE (asistencia_marcada_at, asistencia_via, updated_at) ON public.reservas TO maint_rw;
--    Paso 9: el aforo publicado vuelve a ser el conteo real de reservas vivas.
GRANT UPDATE (asistentes_confirmados, updated_at)                ON public.clases   TO maint_rw;

-- 3b) DELETE: SÓLO en las 2 tablas de la purga (Fase 7, decisión D-7). No existe DELETE "por
--     columna": cuando hace falta borrar filas, el GRANT es de tabla y no hay otra forma.
--     Se eligieron esas dos porque son datos operativos (un token de reset vencido no le sirve
--     a nadie y ya no lo puede usar nadie) y porque NO tienen FKs de entrada: borrarlas no
--     arrastra nada. En el resto de las tablas el rol sigue sin poder borrar.
GRANT DELETE ON public.password_reset_tokens, public.notificaciones_enviadas TO maint_rw;

-- 4) Nada de INSERT / TRUNCATE / DDL en ninguna tabla (y NO hay memberships).
```

> Si la base no se llamara `neondb`, cambiá el nombre en el `GRANT CONNECT` (o usá
> `current_database()`) — el resto del SQL es igual.

#### Verificación (todo tiene que dar `t` / `f` como dice el comentario)

```sql
-- Entrar (3 × t): conexión, esquema y TEMP (la tabla temporal del script)
SELECT has_database_privilege('maint_rw',current_database(),'CONNECT')              AS db_connect,
       has_schema_privilege('maint_rw','public','USAGE')                            AS schema_usage,
       has_database_privilege('maint_rw',current_database(),'TEMP')                 AS db_temp;

-- Lectura (12 × t)
SELECT has_table_privilege('maint_rw','public.usuarios','SELECT')                  AS usuarios_select,
       has_table_privilege('maint_rw','public.planes','SELECT')                    AS planes_select,
       has_table_privilege('maint_rw','public.suscripciones','SELECT')             AS suscripciones_select,
       has_table_privilege('maint_rw','public.solicitudes_planes','SELECT')        AS solicitudes_select,
       has_table_privilege('maint_rw','public.transacciones_financieras','SELECT') AS transacciones_select,
       has_table_privilege('maint_rw','public.alembic_version','SELECT')           AS alembic_select,
       -- Fase 7
       has_table_privilege('maint_rw','public.reservas','SELECT')                  AS reservas_select,
       has_table_privilege('maint_rw','public.clases','SELECT')                    AS clases_select,
       has_table_privilege('maint_rw','public.disciplinas','SELECT')               AS disciplinas_select,
       has_table_privilege('maint_rw','public.coach_disciplinas','SELECT')         AS coach_disciplinas_select,
       has_table_privilege('maint_rw','public.password_reset_tokens','SELECT')     AS tokens_select,
       has_table_privilege('maint_rw','public.notificaciones_enviadas','SELECT')   AS notificaciones_select;

-- Escritura exacta (12 × t y nada más: UPDATE por columna)
SELECT has_column_privilege('maint_rw','public.suscripciones','estado','UPDATE')                AS s_estado,
       has_column_privilege('maint_rw','public.suscripciones','updated_at','UPDATE')            AS s_updated_at,
       has_column_privilege('maint_rw','public.solicitudes_planes','estado','UPDATE')           AS p_estado,
       has_column_privilege('maint_rw','public.solicitudes_planes','comentario_admin','UPDATE') AS p_comentario,
       has_column_privilege('maint_rw','public.solicitudes_planes','updated_at','UPDATE')       AS p_updated_at,
       has_column_privilege('maint_rw','public.usuarios','estado','UPDATE')                     AS u_estado,
       has_column_privilege('maint_rw','public.usuarios','activo','UPDATE')                     AS u_activo,
       -- Fase 7: paso 8 (cierre de asistencia) y paso 9 (aforo)
       has_column_privilege('maint_rw','public.reservas','asistencia_marcada_at','UPDATE')      AS r_marcada_at,
       has_column_privilege('maint_rw','public.reservas','asistencia_via','UPDATE')             AS r_via,
       has_column_privilege('maint_rw','public.reservas','updated_at','UPDATE')                 AS r_updated_at,
       has_column_privilege('maint_rw','public.clases','asistentes_confirmados','UPDATE')       AS c_asistentes,
       has_column_privilege('maint_rw','public.clases','updated_at','UPDATE')                   AS c_updated_at;

-- DELETE: sólo las 2 tablas de la purga (2 × t)
SELECT has_table_privilege('maint_rw','public.password_reset_tokens','DELETE')     AS tokens_delete,
       has_table_privilege('maint_rw','public.notificaciones_enviadas','DELETE')   AS notificaciones_delete;

-- Lo que NO puede hacer (21 × f): columnas prohibidas, INSERT/DELETE/TRUNCATE y DDL
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
       has_function_privilege('maint_rw','version()','EXECUTE')                        AS fn_execute,
       -- Fase 7: lo que sigue PROHIBIDO (t × 9, todas tienen que dar f)
       has_table_privilege('maint_rw','public.reservas','DELETE')                      AS r_delete,
       has_table_privilege('maint_rw','public.clases','DELETE')                        AS c_delete,
       has_table_privilege('maint_rw','public.reservas','INSERT')                      AS r_insert,
       has_column_privilege('maint_rw','public.reservas','estado','UPDATE')            AS r_estado,
       has_column_privilege('maint_rw','public.clases','cupo_maximo','UPDATE')         AS c_cupo,
       has_column_privilege('maint_rw','public.clases','coach_id','UPDATE')            AS c_coach,
       has_column_privilege('maint_rw','public.password_reset_tokens','expires_at','UPDATE') AS t_expira,
       has_table_privilege('maint_rw','public.notificaciones_enviadas','UPDATE')       AS n_update,
       has_table_privilege('maint_rw','public.notificaciones_enviadas','INSERT')       AS n_insert;

-- Y que NO sea miembro de neon_superuser (es el chequeo que atrapa el rol creado por consola)
SELECT pg_has_role('maint_rw','neon_superuser','member')                               AS es_superuser;   -- f

-- Ver EXACTAMENTE lo que tiene: 12 columnas con UPDATE == 12 filas
SELECT table_name, column_name, privilege_type
FROM information_schema.role_column_grants WHERE grantee = 'maint_rw'
ORDER BY table_name, column_name;

-- A nivel TABLA (lo único que NO se puede otorgar por columna: el DELETE de la purga)
SELECT table_name, privilege_type FROM information_schema.role_table_grants
WHERE grantee = 'maint_rw' AND privilege_type = 'DELETE'
ORDER BY table_name;   -- 2 filas: password_reset_tokens y notificaciones_enviadas
```

#### Prueba negativa (con la URL de `maint_rw`, antes de encender el job)

```bash
# Las NUEVE DEBEN fallar con "permission denied"; el ROLLBACK no deja nada.
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c 'BEGIN; CREATE TABLE _maint_no_debe_poder (i int); ROLLBACK;'
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c 'BEGIN; DELETE FROM usuarios WHERE false; ROLLBACK;'
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c "UPDATE usuarios SET nombre = nombre WHERE false;"
# Fase 7: el DELETE está SOLO en las 2 tablas de la purga y el UPDATE, sólo en sus columnas.
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c 'BEGIN; DELETE FROM reservas WHERE false; ROLLBACK;'
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c 'BEGIN; DELETE FROM clases WHERE false; ROLLBACK;'
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c 'BEGIN; DELETE FROM suscripciones WHERE false; ROLLBACK;'
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c "UPDATE reservas SET estado = estado WHERE false;"
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c "UPDATE clases SET cupo_maximo = cupo_maximo WHERE false;"
psql "$MAINT_DB_URL" -v ON_ERROR_STOP=1 -c "UPDATE usuarios SET correo = correo WHERE false;"
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
| `MAX_CAMBIOS` | `500` (tope **global** de respaldo: si el run toca más filas que esto, se aborta; el detalle fino lo dan las 2 reglas de abajo) |
| `MAX_VENCIDOS_PCT` | `80` (máximo **%** de las suscripciones activas que pueden pasar a vencido en un run: el día 1 vencen los planes de todos los que no renovaron y ese volumen es **esperable**) |
| `MAX_HUERFANAS` | `10` (**por cada** lista de huérfanas: suscripciones, solicitudes y usuarios; acá muchas filas sí son una **anomalía**; `0` = ninguna) |
| `DIAS_PENDIENTE` | `7` |
| `NEON_LIMITE_MB` | `512` (free tier de Neon: **0,5 GB por proyecto**; la alerta se calcula contra esto, no contra los 3 GB que decía `neon_usage_alerts.py`) |
| `NEON_UMBRAL_PCT` | `80` |
| `DRY_RUN` | `1` (arranca así; se apaga en el paso 3 de la puesta en marcha) |

Más el env group `alertas` (`GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`, `ALERT_EMAIL`, los
mismos valores del Web Service). **No** se enlaza `backups-prod` (este job no toca R2).
Desde la Fase 7 SÍ se enlaza `neon-api` (sólo para leer CU-horas y ramas: el job no crea ni
borra nada en Neon). `TZ=America/Santiago` ya viene en la imagen.

### El Cron Job en Render

| Campo | Valor |
|---|---|
| Name | `box-crossfit-mantenimiento-prod` |
| Repo / Branch | `proyecto-crossfit` / `main` |
| Dockerfile Path | `backend/Dockerfile.cron` |
| Docker Context | `backend` |
| Command | `python -m maintenance.mantenimiento_cloud` |
| Schedule | `0 8 1,15 * *` (UTC) = 05:00 CLT (04:00 con horario de invierno: es UTC fijo) |
| Environment Groups | `mantenimiento-prod` + `alertas` + `neon-api` (Fase 7) |
| Region | **Oregon (us-west-2)** (la misma del Web Service) |
| Plan | Starter (el mismo de los otros 3 Cron Jobs) |

Pasos: **New → Cron Job** → completar la tabla → **Guardar** → **Trigger Run** una vez y mirar el
log (con `DRY_RUN=1` no aplica nada y, si el run queda verde, **no llega ningún correo**: la
alerta sólo sale si hay algo que revisar). El Dockerfile ya está en el repo: la única línea nueva
es `COPY maintenance/mantenimiento_cloud.py`, y no hace falta ningún `pip install` nuevo porque el
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
py -3.12 -m pytest tests/test_mantenimiento_cloud.py tests/test_mantenimiento_pasos.py tests/test_mantenimiento_vencidos.py tests/test_email_config_prod.py tests/test_watchdog_backups.py tests/test_restore_drill.py tests/test_email_header_saneo.py tests/test_estados_compartido.py tests/test_mrr_historico.py tests/test_reporte_historico_mensual.py -q
```
Registrado el 2026-09-27, con la Fase 7, las **guardas por regla**, los ajustes de A.5, el **conteo
real** de las listas (integridad, A.3 y paso 9), la **lista compartida de "cancelada"** y el **MRR y
churn por fecha** (en el correo y en el Excel) ya adentro: **231 passed, 1 skipped** — 127 de
`mantenimiento_cloud` (los 33 de la Fase 6 + 47 de la Fase 7 + **22 de los límites por regla**:
evaluación pura, borde del %, huérfanas por lista, tope global, config inválida, las guardas en el
SQL y el prefijo `[maint]` del correo, + **17 de A.5** (`requiere_coach`, complementariedad de
(a)/(b), conteo real vs tope, `A5_NOTA_HASTA` y el log/motivo según el modo) + **6 del
tope-conteo y A.6** (integridad con `LIMITE_DUP`, A.3 con `LIMITE_A3`, el paso 9 con
`LIMITE_LISTA` y una variante de cancelación desconocida) + **2 del bloque E por fecha**
(`test_cr` y `test_cs`: el SQL del mes anterior y de la cohorte)),
12 de `estados_compartido` (la constante se define en un solo lugar, `shared/` no importa nada, los
helpers son exactos, la app no compara contra el literal, el predicado ORM == el del job, las TRES
imágenes copian `shared/` y el predicado de vigencia por fecha parte el enum en dos), **4 de
`mrr_historico`** (vencer hoy no cambia el MRR del pasado, una rechazada no suma nunca, el churn de
la cohorte es histórico y el MRR del pasado y el de hoy son la MISMA consulta), **8 de
`reporte_historico_mensual`** (el .xlsx se genera y se LEE: la celda de MRR del mes pasado de la hoja
"Historico Mensual" es la de `metricas_service.mrr` para esa fecha —la misma del dashboard y del BI—,
vencer una suscripción hoy no la cambia, la columna de alumnos va con el predicado de fecha, la
tarjeta KPI de MRR es el corte del MES ELEGIDO —el mismo número que la celda de "Historico Mensual" de
ese mes, y HOY si el mes elegido es el en curso—, su etiqueta dice la fecha del corte y el export no
vuelve a tener su propia copia del SQL del MRR ni su propia fecha),
4 de
`mantenimiento_pasos`,
1 de `mantenimiento_vencidos` y 76 de los tests de correo/drill/watchdog (el skip es el drill
cuando falta una variable del env group). `psql`, `smtplib` y la API de Neon (`urllib`) están
mockeados: no se usa red ni credenciales, **no se manda ningún correo real ni se llama a
Neon**. ⚠️ Usar `py -3.12`: el `python` del PATH (3.13) no tiene
`pytest`.

## Mantenimiento de PROD 2× al mes — Fase 7: detecciones, límites, consistencia y reporte (2026-09-27)

La Fase 6 dejó el job corriendo (4 `UPDATE` en una transacción). La Fase 7 lo amplía **sin
agregar scripts ni jobs**: tres bloques de trabajo nuevos y el reporte de gestión, en el mismo
Cron Job, los mismos días (1 y 15) y con la misma regla de correo (**sólo si hay algo que
revisar**).

| Pieza | Qué agrega la Fase 7 |
|---|---|
| Detecciones (A) | 6 familias de chequeos de **sólo lectura** (A.1–A.6). No escriben nada: lo que encuentran viaja en el mail y pone el run rojo con **exit 9** |
| Límites de Neon (B) | `B.6` CU-horas del mes y `B.7` cupo de ramas, leídos de la **API v2** (env group `neon-api`, opcional). Son avisos: mandan correo pero **no** cambian el exit code |
| Consistencia (C) | `C.8–C.10` con **escritura controlada**: cierre de asistencia de las clases pasadas, resincronización del aforo y purga de tokens/notificaciones viejas |
| Reporte (E) | MRR, variación de MRR, retención/churn de la cohorte de 30 días y bajas del mes (mismas fórmulas que el BI) |
| Watchdog (F) | el asunto del correo del watchdog de backups pasa a `[ALERTA] Watchdog backups PROD: …` (mismo prefijo que este job) |

### Las 3 transacciones (antes era 1)

| # | Transacción | Qué hace | Tope | Exit si se pasa |
|---|---|---|---|---|
| 1 | `cambios` | los 4 `UPDATE` de la Fase 6 | `MAX_VENCIDOS_PCT` (80 %), `MAX_HUERFANAS` (10) y `MAX_CAMBIOS` (500) | 6 |
| 2 | `consistencia` | paso 8 (asistencia) + paso 9 (aforo) | `MAX_CIERRE` (500) | 6 |
| 3 | `purga` | paso 10 (tokens + notificaciones) | `MAX_PURGA` (5000) | 6 |

Cada una es **una transacción propia** (`BEGIN … COMMIT|ROLLBACK`) con su `CREATE TEMP TABLE` y su
propia guarda de volumen *dentro* del SQL. Si la guarda de la 2 aborta, la 1 ya quedó aplicada y
verificada, la 3 **no se intenta** y el correo dice exactamente dónde se cortó. Las tres se
verifican igual: en REAL la lista tiene que quedar en 0 y en DRY-RUN en el mismo número de antes.

| # | Escritura | Detalle | Antes en |
|---|---|---|---|
| 8 | `UPDATE reservas SET asistencia_marcada_at = now(), asistencia_via = 'cierre', updated_at = now()` | sólo las reservas **vivas** de clases terminadas hace más de `DIAS_CIERRE_RESERVAS` días sin `asistencia_marcada_at`. **No toca `estado`** (D-6): pasar la reserva a `no_asistio` reescribiría los KPIs de asistencia ya publicados | (nuevo) |
| 9 | `UPDATE clases SET asistentes_confirmados = <reservas vivas>, updated_at = now()` | deja el aforo publicado igual al conteo real, que es lo que la app mantiene con +1/−1 al reservar y cancelar | (nuevo) |
| 10 | `DELETE FROM password_reset_tokens` · `DELETE FROM notificaciones_enviadas` | tokens vencidos o usados hace más de `DIAS_PURGA_TOKENS` días y notificaciones de más de `DIAS_PURGA_NOTIF` días | (nuevo) |

> **Única excepción de `DELETE` (D-7)**: ésas son las dos únicas tablas donde `maint_rw` puede
> borrar. Son datos operativos (no historial del box) y no tienen FKs de entrada. En el resto de
> las tablas el rol sigue **sin** `DELETE`, `INSERT`, `TRUNCATE` ni DDL, y la prueba negativa lo
> verifica con cuatro sentencias que tienen que fallar.

#### Qué significa "reserva viva" (una sola lista, compartida con la app)

`reservas.estado` es un `character varying(20)` con default `'reserved'` y en los datos hay **dos
formas de "cancelada"**: la que escribe la app (`'cancelled'`, en el `DELETE /reservas/{id}`) y la
del enum viejo `estado_reserva` (`'cancelada'`). Esa lista vive **una sola vez** en
`backend/shared/estados.py` (`ESTADO_CANCELADO = 'cancelled'` —lo que se ESCRIBE—,
`ESTADOS_CANCELADA = ('cancelled', 'cancelada')` —lo que se LEE—, más `lista_sql()` y
`es_cancelada()`) y la importan las dos partes: la app por `app/core/estados.py` (que agrega
`no_cancelada()`, el predicado de SQLAlchemy) y este job por `sql_viva()` (`NOT IN (...)`) y
`sql_cancelada()` (`IN (...)`).

Antes el job comparaba con `ILIKE '%cancel%'` y la app contra el literal, así que una variante nueva
se comportaba distinto en cada lado: contra el literal, una reserva `'cancelada'` pasaba por viva y
el **paso 8 le escribía `updated_at`** —el dato con el que A.3 reconstruye la tardanza— y el paso 9
la contaba en el aforo. La lista es **exacta a propósito** (nada de `LIKE` "por parecido") y lo que
el `ILIKE` cubría de más ahora lo delata la detección **A.6** (rojo) contra esa misma lista.

`shared/` es un paquete **neutral** (sólo importa `typing`), porque lo copian las **TRES** imágenes
de Docker: `Dockerfile.cron` copia `maintenance/` **+ `shared/`** y deliberadamente **no** lleva la
app; `Dockerfile` (web, contexto `backend/`) usa `COPY shared/ shared/`; y `Dockerfile.render` (la
combinada nginx+uvicorn del Web Service de Render, contexto **la raíz del repo**) usa
`COPY backend/shared/ shared/`. Si una de las tres se olvida de `shared/`, el proceso muere **al
arrancar** con *No module named 'shared'* —no en un endpoint cualquiera: `app/main.py` importa todos
los routers en su primera línea y varios de ellos (`wods.py`, `reservas.py`, …) pasan por
`app.core.estados` → `shared.estados`—. Pasó de verdad el 27/09/2026: a `Dockerfile.render` le
faltaba la línea, o sea que el Web Service de PROD no habría arrancado. Por eso
`tests/test_estados_compartido.py` verifica **las tres** (y que `render.yaml` siga apuntando a
`Dockerfile.render` con contexto la raíz). En el dump de
PROD del 24/09/2026 sólo hay `'cancelled'` y `'confirmada'`, así que el cambio es equivalente: es la
red para la otra variante.

#### Guarda, verificación e idempotencia de los pasos 8-9

- Los **dos** pasos comparten la guarda `MAX_CIERRE`: cuenta `_maint_cierre`, o sea la suma de
  asistencias cerradas **+** clases resincronizadas, y va después de los dos, dentro de la
  transacción. Si el total se pasa del tope, aborta y **no se aplica nada** de esa transacción.
- Los dos se **verifican** después con las mismas dos listas (`cierre_asistencia` y `aforo_resync`):
  en REAL tienen que quedar en 0 y en DRY-RUN en el mismo número de antes.
- El log del run imprime el resumen **paso por paso** (`consistencia: aforo_resync=3,
  cierre_asistencia=2`), así que se ve cuántas **clases** cambió el resync y no sólo el total.
- Las 3 transacciones son **idempotentes** y escriben tablas **disjuntas** (1: `suscripciones`,
  `solicitudes_planes`, `usuarios` · 2: `reservas`, `clases` · 3: `password_reset_tokens`,
  `notificaciones_enviadas`): la segunda corrida no encuentra nada que volver a tocar (los filtros
  son por estado / `asistencia_marcada_at IS NULL` / antigüedad), no hay `INSERT` en tablas reales
  (nada se puede duplicar) y un fallo en la 2 o la 3 no puede deshacer ni reescribir lo que la 1 ya
  confirmó con su `COMMIT`.

### Detecciones A.1–A.6 (sólo leen)

| # | Chequeo | Rojo o informativo |
|---|---|---|
| A.1(a) | usuarios con `activo <> (estado = 'activo')` | **rojo** — el CHECK `ck_usuarios_activo_estado` de la 034 lo hace imposible: si sale ≠ 0, esa base no tiene el CHECK |
| A.1(b) | `estado` fuera de la lista conocida (`activo`, `pendiente_activacion`, `rechazado`, `baja`) | **rojo** — la columna es un `String(20)`: la base no lo impide |
| A.1(c) | usuarios que matchean `PROD_PERMITIDOS` | informativo — son los datos de demo de `seed_ml_data_prod.py` |
| A.2(a) | `clases.asistentes_confirmados` ≠ reservas vivas | **rojo** — lo resincroniza el paso 9 en la misma corrida |
| A.2(b) | reservas vivas duplicadas (mismo alumno y clase) | **rojo** — aforo inflado |
| A.2(c) | `asistentes_confirmados > cupo_maximo` | **rojo** |
| A.3 | descuadre de créditos por suscripción vigente | **rojo** si `\|descuadre\| > CREDITOS_DESCUADRE_TOLERANCIA` (usa `reservas.updated_at` como momento de la cancelación: ver la limitación conocida más abajo) |
| A.4(a) | reservas de clases terminadas sin `asistencia_marcada_at` | informativo — es el insumo del paso 8 y el propio run lo cierra |
| A.4(b) | `asistio = true` sin `asistencia_marcada_at` | **rojo** — falta la auditoría de quién marcó |
| A.5(a) | clase futura sin `coach_id` de una disciplina que **exige** coach (`COALESCE(d.requiere_coach, true)`: las self-service quedan fuera) **y** sin ningún coach activo en `coach_disciplinas` para su disciplina | **rojo** (D-2) — no hay a quién asignársela. Con `A5_NOTA_HASTA` vigente se le agrega una nota de contexto (el run sigue rojo) |
| A.5(b) | igual que A.5(a) pero **con** coach activo en su disciplina (`EXISTS` en vez de `NOT EXISTS`) | informativo — falta asignarla |
| A.5(c) | clase futura asignada a alguien que no es `coach` activo | **rojo** |
| A.6 | `reservas.estado` que contiene "cancel" pero **no** está en la lista compartida (`shared/estados.ESTADOS_CANCELADA`) | **rojo** — el predicado lo ve como vivo (el paso 8 le escribiría `updated_at`, el dato de A.3) y el paso 9 lo contaría en el aforo: es la red que reemplaza al `ILIKE '%cancel%'` (la lista es exacta, así que una variante nueva tiene que verse) |

Un hallazgo **no aborta** el mantenimiento (igual que la integridad): se aplica todo y el run queda
rojo con **exit 9** (si además hay integridad, gana el 4). Las listas viajan completas en el correo;
las de detecciones no llevan columna "→ nuevo" porque no cambian nada.

> **Datos de demo y `A.1(c)`.** El único chequeo que **sube** cuando se siembra datos
> sintéticos es A.1(c) (usuarios que matchean `PROD_PERMITIDOS`): es informativo justamente
> por eso. El seed anual (`scripts/seed_anual_prod.py`) agrega **300** usuarios
> `demo.prod.anual.N@example.com` (+ `DEMOPRODANUAL…` en `transacciones_financieras`), así que
> el conteo de A.1(c) pasa de *n* a *n + 300* y **ningún otro número del run cambia**: el
> seed está construido para que los pasos 1-9 y A.1-A.6 queden en **0 cambios / 0
> detecciones**, incluido el descuadre de créditos de A.3. El plan, los invariantes y la
> reversión (`scripts/borrar_seed_anual.py`) están en
> **[`scripts/README_seed_anual.md`](../scripts/README_seed_anual.md)**.


#### Por qué A.5(a) y A.5(b) daban "25 y 25" (y qué se corrigió)

No eran dos conjuntos solapados: los dos `WHERE` son **el mismo** y sólo cambian `NOT EXISTS` ⇄
`EXISTS` sobre el mismo subquery (`coach_disciplinas` + `usuarios.rol = 'coach' AND activo`), así
que ninguna clase puede salir en los dos. Lo que se veía igual era el **tope de la lista**: cada
detección de tipo lista termina en `LIMIT 25` (`LIMITE_LISTA`) y el conteo reportado era
`len(filas)`, o sea el tope. Ahora `detecciones()` pide el total real con `count(*) OVER ()`
(`sql_con_total()`: la ventana se calcula **antes** del `LIMIT`) ⇒ el log y el correo dicen el
tamaño del hallazgo (`63 fila(s)`) y, cuando la lista trae menos filas, lo aclaran:
`63 fila(s) (mostrando 25 de 63)`. El test `test_cb_…` fija que los dos predicados siguen siendo
complementarios y `test_cc_…` que el conteo no es el tope.

`disciplinas.requiere_coach` existe desde la migración **018** (`ADD COLUMN IF NOT EXISTS … DEFAULT
true`) y se administra en la pantalla **Disciplinas** del admin (`PUT /api/v1/disciplinas/{id}`,
`requiere_coach` en el body): "Musculación" y "Open Box" se destildan ahí. **El mantenimiento nunca
compara por nombre** —el nombre sólo aparece en ese destildado manual— y si en PROD la bandera
quedó en `true`, A.5(a) sigue contando esas clases (fue exactamente el caso del run en rojo).

#### El tope de una lista NO es su conteo: `sql_con_total()` (integridad, A.3 y paso 9)

El defecto del punto anterior no era exclusivo de A.5: **toda** lista que termina en un `LIMIT` y
reporta `len(filas)` está diciendo el tope como si fuera el tamaño del conjunto. Desde el
2026-09-27 las tres listas que cortan se leen con `sql_con_total(sql)`, que prefija
`count(*) OVER ()::text` (la ventana se calcula **después del `WHERE` y antes del `LIMIT`), y el
`n` que va al log y al correo es ese total:

| Lista | Tope | Qué se informa ahora |
|---|---|---|
| `SQL_DUP_RUT` / `SQL_DUP_CORREO` (integridad) | `LIMITE_DUP` = 10 | `RUT duplicados (37) (mostrando 10 de 37): …` — sin recorte el texto es el de antes |
| A.3 (`descuadre_creditos()`) | `LIMITE_A3` = 200 | `revisadas` = total real y `escaneadas` = las que entraron por el tope; si difieren, el informe dice `(se evaluaron 200: el tope de A.3 (200) deja el resto para la próxima corrida)`. El subconjunto evaluado es determinista (la consulta ordena por `s.id`) |
| Paso 9 (`aforo_resync`) | `LIMITE_LISTA` = 25 (antes un `25` **hardcodeado**) | el bloque del correo dice `30 fila(s) (mostrando 25 de 30)` |

Las listas de la fase 8-10 (huérfanas) no tienen `LIMIT` y la de la purga corta en 5000: su
verificación va por tabla temporal, así que ahí el conteo siempre fue exacto. En `verificar()` **no**
se cambió nada a propósito: relee `consulta["sql"]` (sin la ventana, mismo tope), así que la
comparación de después —0 en REAL, el mismo número en DRY-RUN— sigue siendo consistente.

#### A5_NOTA_HASTA: la nota de contexto de A.5(a) (opcional)

Mientras `hoy <= A5_NOTA_HASTA` (fecha ISO, el mismo día incluido), el log y el correo agregan
**junto a A.5(a)** —en el `<li>` del hallazgo y en su bloque de lista— la nota:

> Esperado en esta etapa: aún no hay coaches asignados a estas clases (desarrollo). Asígnalos en la
> pantalla Coaches. Esta nota se quita sola el AAAA-MM-DD.

La detección **no se silencia**: A.5(a) sigue roja, el correo sigue saliendo y el exit sigue siendo
9. Sin la variable (o vacía) no hay nota; pasada la fecha, la nota desaparece sola y la detección
queda exactamente como estaba. Una fecha inválida (o con otro formato) ⇒ `ConfigError` ⇒ **exit 2**
sin tocar la base: `_fecha_iso()` exige el patrón `AAAA-MM-DD` antes de parsear.

#### A.3: cómo se mide el consumo de créditos (y por qué NO se usa `tokens_gastados`)

`reservas.tokens_gastados` no sirve para esto: el `DELETE /reservas/{id}` de
`app/api/v1/reservas.py` sólo escribe `estado='cancelled'` y `updated_at=now()`, así que la columna
queda siempre en 1 (el dump de PROD tiene la reserva 1 cancelada con `tokens_gastados=1`). Lo que sí
refleja el consumo es `suscripciones.creditos_totales - creditos_disponibles`, y la devolución se
puede reconstruir porque `updated_at` **es** el momento de la cancelación:

```
consumo_esperado = reservas vivas de la ventana + cancelaciones TARDÍAS (< 6 h antes de la clase)
descuadre        = (creditos_totales - creditos_disponibles) - consumo_esperado
```

Las cancelaciones con ≥ 6 h (la MISMA regla de `reservas.py`) devolvieron el crédito y no consumen:
sin restarlas, cada cancelación legítima aparecería como descuadre. Se exige **una sola** suscripción
vigente por alumno (con dos, el crédito pudo salir de la otra) y la tolerancia es **simétrica**,
porque los dos sentidos pueden ser legítimos: hacia arriba, una cancelación en plazo que la app no
pudo acreditar (plan ya vencido al cancelar); hacia abajo, una reserva cancelada que el staff editó
y que ahora parece tardía. Con `DRY_RUN=1` se ve el número real y se decide la tolerancia.

**Limitación conocida**: `updated_at` es a la vez el momento de la cancelación y el de cualquier otra
edición de esa fila. El mantenimiento **no** puede corromperlo —el paso 8 excluye cualquier forma de
cancelación, ver más abajo—, pero **una edición manual de una reserva ya cancelada** (por ejemplo,
corregir el `alumno_id` desde el panel de supervisión) mueve esa marca: si la deja a menos de 6 h del
inicio de la clase, A.3 la cuenta como tardía y el descuadre sale negativo. Por eso la tolerancia es
simétrica y el correo muestra los dos lados con el número esperado: con el caso a la vista se decide
si es un dato a corregir o un umbral a ajustar.

> **Tope y orden**: A.3 evalúa hasta `LIMITE_A3` (200) vigentes con `ORDER BY s.id` (determinista) y
> el informe del correo dice el total real y cuántas se evaluaron — ver *El tope de una lista NO es
> su conteo*, más arriba.

> **Propuesta (NO implementada): `reservas.cancelada_at`.** Lo de fondo es dejar de usar `updated_at`
> como proxy. Una columna `cancelada_at timestamptz` que la app escriba en el MISMO `UPDATE` que pone
> `estado='cancelled'` —y que el mantenimiento nunca toque— hace que A.3 deje de depender de cuándo se
> editó la fila por última vez, y de paso permite distinguir "cancelada" de "editada" en cualquier
> auditoría futura. Requiere migración + el cambio en `app/api/v1/reservas.py` y el backfill de las
> cancelaciones existentes (con su `updated_at` actual, que es el mejor dato disponible hoy): queda
> fuera de esta fase a propósito, es un cambio de modelo y merece su propia revisión.

### Límites del plan Free en la API de Neon (B.6 y B.7)

| # | Chequeo | Cómo se lee | Aviso cuando |
|---|---|---|---|
| B.6 | CU-horas del mes | `GET /projects/{id}` → `compute_time_seconds` ÷ 3600 | `NEON_CU_UMBRAL_PCT` (80 %) de `NEON_CU_HORAS_LIMITE` (100 CU-horas) |
| B.7 | ramas del proyecto | `GET /projects/{id}/branches`, contadas | llega a `NEON_RAMAS_LIMITE` (10): el drill mensual ya no puede crear la suya |

- Son **opcionales**: sin `NEON_API_KEY`/`NEON_PROJECT_ID` (env group `neon-api`) el job corre
  igual, sale con **exit 0** y deja **una sola** nota —`no configurado (faltan …)`— en el log del run
  y en el correo, **no una por chequeo**: el mail muestra esa nota y omite el detalle de B.6/B.7. La
  falta del env group no es un hallazgo (es una decisión de dónde corre el job); lo que sí es rojo es
  un chequeo **configurado** que no puede correr.
- Son **avisos**: mandan correo aunque el run quede verde y **no** cambian el exit code, igual que
  la alerta de almacenamiento de la Fase 6.
- Con las variables puestas y la API caída el run queda **rojo (exit 9)**: un chequeo configurado
  que no corre tiene que verse, no callarse. El `NEON_PROJECT_ID` se valida antes de armar la URL.
- La API de **consumo histórico** (`/consumption_history/...`) sólo existe en planes pagos (en Free
  contesta 403): no se usa. Si la API no trae `compute_time_seconds` (campo renombrado), el módulo
  cae a `cpu_used_sec` y lo dice en el mail en vez de informar 0.
- `NEON_CU_HORAS_LIMITE=100` es el valor del plan Free y se confirma en **Neon → Projects → Usage**
  (decisión D-5): si el proyecto tuviera otro autoscaling, se ajusta la variable.

### Reporte del mes (E)

Además de lo que ya traía la Fase 6, el correo agrega `mrr`, `mrr_mes_anterior`,
`variacion_mrr_pct`, `retencion_30d_pct`, `churn_30d_pct`, `alumnos_vigentes` y `bajas_mes`. Las
fórmulas son las MISMAS de `app/services/metricas_service.py` (una sola definición por métrica en el
proyecto), copiadas a SQL porque el job no importa `app.*`:

- **MRR**: `SUM(planes.precio_clp)` de las suscripciones VIGENTES EN LA FECHA (precio de lista, no
  caja cobrada). El de referencia es el del **último día del mes anterior**. "Vigente en la fecha" =
  `fecha_inicio <= fecha <= fecha_expiracion` y estado ≠ `pendiente`/`rechazado`
  (`shared.estados.sql_suscripcion_vigente()`, el MISMO predicado que `metricas_service.mrr`): una
  suscripción VENCIDA sigue contando para los meses en los que estuvo vigente y una rechazada no
  suma nunca. **No** se filtra por `estado = 'activo'`: ese es el estado de hoy y reescribía el
  pasado (fix del 2026-09-27).
- **Retención 30 días**: de los alumnos vigentes hace 30 días, cuántos siguen vigentes hoy;
  **churn** = 100 − retención. Misma definición de vigencia por fecha (la base de hace 30 días no se
  encoge porque hoy venció una suscripción). Con base < `MIN_BASE_RETENCION` (5, el mismo umbral del
  BI) se publica "sin dato" en vez de un porcentaje que no representa al box (el bug del 7600 %).

### Exit codes con la Fase 7

| Exit | Cuándo |
|---|---|
| 0 | todo aplicado y verificado (o simulado en DRY-RUN). Con avisos de Neon igual: el correo sale con exit 0 |
| 2 | configuración inválida: variable faltante, URL con `-pooler`, rol ≠ `maint_rw`, `ENVIRONMENT` ≠ `production`, número fuera de rango, allowlist con caracteres raros o `A5_NOTA_HASTA` con formato inválido |
| 3 | falló una lectura |
| 4 | la integridad encontró problemas (no aborta la escritura) |
| 6 | se pasó un tope de volumen (`MAX_VENCIDOS_PCT`, `MAX_HUERFANAS`, `MAX_CAMBIOS`, `MAX_CIERRE` o `MAX_PURGA`) |
| 7 | falló una transacción de escritura |
| 8 | la verificación posterior no cuadró |
| **9** | **nuevo**: las detecciones A.1–A.6, o un chequeo de Neon configurado que no pudo correr |

### Variables de entorno nuevas (todas con default)

| Variable | Default | Para qué |
|---|---|---|
| `MAX_CIERRE` | `500` | tope de la transacción 2 (consistencia) |
| `MAX_VENCIDOS_PCT` | `80` | % máximo de suscripciones activas que pueden vencer en un run (regla del día 1) |
| `MAX_HUERFANAS` | `10` | máximo **por cada** lista de huérfanas (`0` = ninguna) |
| `MAX_PURGA` | `5000` | tope de la transacción 3 (purga) |
| `DIAS_CIERRE_RESERVAS` | `7` | antigüedad mínima de la clase para cerrar su asistencia |
| `DIAS_PURGA_TOKENS` | `30` | retención de `password_reset_tokens` |
| `DIAS_PURGA_NOTIF` | `180` | retención de `notificaciones_enviadas` |
| `CREDITOS_DESCUADRE_TOLERANCIA` | `0` | descuadre por alumno tolerado en A.3 |
| `A5_NOTA_HASTA` | *(sin setear)* | fecha ISO hasta la que se muestra la nota de contexto de A.5(a) (el mismo día incluido). Sin la variable no hay nota y **la alerta no se silencia**; una fecha inválida ⇒ exit 2 |
| `PROD_PERMITIDOS` | `demo.prod.%@example.com` | allowlist de correos de demo (A.1c). **Tras la defensa del 6/10/2026 se limpian esos datos y esta variable queda vacía** |
| `TENANT_ID` | `1` | filtro de las consultas de MRR/churn (el box es uno) |
| `MIN_BASE_RETENCION` | `5` | mismo umbral que el BI para publicar churn |
| `NEON_CU_HORAS_LIMITE` | `100` | CU-horas del mes del plan Free (confirmar en Neon → Usage) |
| `NEON_CU_UMBRAL_PCT` | `80` | umbral de aviso de B.6 |
| `NEON_RAMAS_LIMITE` | `10` | ramas por proyecto del plan Free (B.7) |
| `NEON_API_BASE` | `https://console.neon.tech/api/v2` | base de la API v2 (la misma variable que usa `restore_drill`) |

> **Dato real de PROD (D-3)**: los ~104 usuarios `demo.prod.N@example.com` son **intencionales**
> (los genera `backend/scripts/seed_ml_data_prod.py` para el modelo de ML). Por eso A.1(c) cuenta y
> no alerta, y la allowlist los declara explícitamente en vez de silenciar el chequeo.






## Estado y limitaciones (2026-09-27, commit local sin push)




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
  tests/test_restore_drill.py tests/test_email_config_prod.py -q --noconftest` ⇒ **28 passed**
  (8 + 12 + 8, con Neon/R2/psql/smtplib mockeados: no se usó red ni credenciales). Y con la regla
  nueva "correo = algo que revisar": `tests/test_mantenimiento_cloud.py` +
  `tests/test_restore_drill.py` + `tests/test_watchdog_backups.py` +
  `tests/test_email_config_prod.py` ⇒ **61 passed** (33 + 12 + 8 + 8): los casos verdes comprueban
  que NO se llama a `enviar_email` y los rojos que el asunto empieza con `[ALERTA]`.
  ⚠️ Usar `py -3.12`: el `python` del PATH (3.13) **no** tiene pytest.
- **Verificado (smoke sin credenciales):** con el entorno vacío, `restore_drill` sale con
  exit 2 ("faltan variables") y el watchdog también. El correo no sale: sin
  `GMAIL_SMTP_USER`/`GMAIL_SMTP_APP_PASSWORD`/`ALERT_EMAIL`, `enviar_email()` sólo loguea
  `FATAL (config)` y devuelve `False` (el exit code no cambia).
- **Verificado en Render (run real del 2026-09-27):** el drill corrió contra Neon real: la rama
  temporal se creó y se **borró** bien en el `finally`, pero murió con
  `HTTP 423 "project already has running conflicting operations..."` (exit 9) en la llamada
  siguiente ⇒ fix de arriba (esperar `operations` + reintentar 423), cubierto por los tests
  h/i/j (mocks, sin red). **Falta el `Trigger Run` verde de punta a punta** (restore real +
  prueba negativa contra PROD): mirar el **log** del run (si sale verde **no** habrá correo: la
  alerta sólo llega cuando falla) y la lista de ramas de Neon.
- **Fase 5:** queda **sólo como propuesta escrita** (sección "Fase 5" de arriba). No se escribió
  `copia_test.py` ni ningún script/job nuevo, y el contenedor local de mantenimiento quedó igual.
  Los 2 cambios propuestos (04:30 CLT y retención de 7 días) **no** se aplicaron.
- **Regla permanente (2026-09-27): "correo = algo que revisar".** Ningún Cron Job manda correo
  informativo: si el run está verde (incluido "aplicado y verificado") sólo queda el **log** en
  Render. Se avisa cuando el run falla (exit ≠ 0), cuando la guarda de volumen se excede, cuando
  la integridad encuentra hallazgos, cuando Neon pasa `NEON_UMBRAL_PCT` o cuando el drill deja la
  rama temporal viva. Todos los asuntos arrancan con `[ALERTA]` + el job + qué pasó (el detalle va
  en el cuerpo). (El prefijo `[ALERTA]` del `watchdog_backups` —que hoy usa
  `[Box CrossFit] ALERTA …`— queda como cambio aparte: el watchdog y `backup_cloud` no se
  tocaron.)
- **Regla permanente (2026-09-27): todo envío de correo va exclusivamente por Gmail SMTP; está
  prohibido cualquier otro proveedor.** `maintenance/alertas.py` manda por `smtp.gmail.com:465` +
  `SMTP_SSL` con `GMAIL_SMTP_USER`/`GMAIL_SMTP_APP_PASSWORD` (env group `alertas`, los mismos
  valores que ya usa el Web Service) y **no importa ni toca** `app/services/email_service.py`, que
  usa el mismo host y puerto. No hay segundo proveedor, ni librería de terceros, ni API key
  externa, ni dominio que verificar.
- **Límites por regla y logger del correo (2026-09-27, cierre de la revisión de la Fase 7):** el
  freno único `MAX_CAMBIOS` (40) dejaba el job sin red justo el día 1, que es cuando el volumen de
  vencimientos es **esperable** (los planes vencen el último día del mes). Ahora:
  `MAX_VENCIDOS_PCT=80` (% de las suscripciones activas del propio universo del paso, medido con
  enteros), `MAX_HUERFANAS=10` **por cada** lista de huérfanas y `MAX_CAMBIOS=500` como tope global
  de respaldo; la evaluación es la función pura `evaluar_limites()` (conteos + config → reglas,
  testeable sin dobles), el asunto/log/correo dicen **cuál** regla cortó y el bloque `Límites de
  volumen` muestra cada una con su conteo y su tope. En REAL las 3 reglas viajan **dentro** de la
  transacción (`guarda_vencidos()` antes del paso 1, `guarda_huerfanas()` + `guarda_volumen()` al
  final), así que siguen abortando desde el SQL y el exit sigue siendo 6. Además, la config se lee
  **sólo** en `leer_config()` (entraron `NEON_API_KEY`/`NEON_PROJECT_ID`, que se leían sueltas en
  `neon_api_get`) y `alertas.enviar_email(asunto, html, logger=None)` usa el `log()` de quien llama:
  en mantenimiento los avisos del correo salen `[maint]` y el watchdog/drill siguen con `[backup]`.
  **Verificado:** `tests/test_mantenimiento_cloud.py` ⇒ **119 passed** (102 + 22 de las reglas; ver
  el detalle y los 17 nuevos más abajo) y
  `tests/test_watchdog_backups.py` ⇒ 8 passed; el comando completo del README ⇒ **199 passed,
  1 skipped** (usa `py -3.12`). Nada de PROD: todo con `psql`/`smtplib`/API de Neon mockeados.
- **A.5(a)/(b) por dato, conteo real y nota de contexto (2026-09-27, cierre del run rojo por
  A.5(a)):** el run marcó en rojo 25 clases futuras sin coach. Tres cambios: (1) A.5(a) y A.5(b)
  pasan a decidir por **`disciplinas.requiere_coach`** (`COALESCE(d.requiere_coach, true)`), así que
  las disciplinas self-service —"Musculación" y "Open Box"— dejan de ser un hallazgo **por dato** y
  no por nombre (el mantenimiento no compara nombres en ningún lado; la bandera se destilda en la
  pantalla **Disciplinas** del admin, que ya la expone desde la migración 018 ⇒ **no hizo falta
  migración nueva ni tocar el CRUD/schema/frontend**); (2) el "25 y 25" de A.5(a) vs A.5(b) **no**
  era un solapamiento de predicados —son `NOT EXISTS`/`EXISTS` sobre el mismo subquery— sino el
  `LIMIT 25` leído como conteo: `detecciones()` ahora lee el total real con `count(*) OVER ()`
  (`sql_con_total()`, la ventana se calcula antes del `LIMIT`) y el log/correo informan
  `63 fila(s)`, aclarando `(mostrando 25 de 63)` cuando el tope recorta la lista; (3)
  **`A5_NOTA_HASTA`** (fecha ISO, opcional) agrega la nota "esperado en esta etapa: aún no hay
  coaches asignados…" junto a A.5(a) en el log y en el correo mientras `hoy <= la fecha`, **sin
  silenciar** la alerta (A.5(a) sigue roja, el correo sale y el exit sigue siendo 9); sin la
  variable o con la fecha pasada no hay nota, y una fecha inválida ⇒ `ConfigError` ⇒ exit 2 sin
  tocar la base (`_fecha_iso()`). Además: el **log nombra la detección** que puso el run rojo
  (`detecciones=1 hallazgo(s) [A.5(a)]` + `ROJO (A.5(a)): <título>: 63 fila(s) — …`) y el **motivo
  del exit 4/9 cambia según el modo** (en DRY-RUN ya no dice "el mantenimiento se aplicó igual"
  porque no se aplicó nada). **Verificado:** `tests/test_mantenimiento_cloud.py` ⇒ **119 passed**
  (102 + **17 nuevos**, `test_ca`–`test_ck`) y el comando completo ⇒ **199 passed, 1 skipped**.
  Nada de PROD (los "25" salen del run real; el doble de `psql` simula 63 filas con 25 en el
  `LIMIT`). Pendiente del usuario: destildar "Requiere coach" en **Musculación** y **Open Box**
  (pantalla Disciplinas) y setear `A5_NOTA_HASTA` en Render si quiere la nota.
- **El tope no es el conteo (integridad, A.3 y paso 9) + lista compartida de "cancelada"
  (2026-09-27, dos tareas del backlog):**
  (1) **T2 — el mismo defecto de A.5, en tres lugares más:** `integridad()` reportaba `len(dup)` con
  `LIMIT 10`, A.3 reportaba el `LIMIT 200` como "revisadas" y el paso 9 tenía un `LIMIT 25`
  **hardcodeado** cuyo `len(filas)` viajaba como el tamaño del hallazgo. Los tres se leen ahora con
  `sql_con_total()` (`count(*) OVER ()`): el hallazgo dice `RUT duplicados (37) (mostrando 10 de
  37)`, en A.3 `revisadas` es el total real y `escaneadas` lo que entró por el tope (con el aviso de
  que el resto queda para la próxima corrida) y el bloque del paso 9 dice `30 fila(s) (mostrando 25
  de 30)`; `LIMITE_DUP` y `LIMITE_A3` pasan a constantes con nombre. `verificar()` **no** se toca
  (relee el mismo SQL con el mismo tope: la comparación de después sigue siendo consistente) y
  `_bloques_listas()` aprende a decir "(mostrando N de M)" como las detecciones. Sin recorte, los
  textos son exactamente los de antes (test `test_co`).
  (2) **T3 — el predicado de "cancelada" es uno solo:** `ESTADOS_CANCELADA` ya no se define en
  `kpis_populate.py` ni se adivina con `ILIKE '%cancel%'`. Se agregó el paquete **neutral**
  `backend/shared/` (`estados.py` con `ESTADO_CANCELADO`, `ESTADOS_CANCELADA`, `lista_sql()` y
  `es_cancelada()`; sólo importa `typing`), que copian **las tres** imágenes de Docker (`Dockerfile`
  —web—, `Dockerfile.cron` —que lo copia explícitamente y sigue **sin** llevar la app: por eso no
  puede importar nada— y `Dockerfile.render` —la combinada de Render—). El job arma
  `sql_viva()`/`sql_cancelada()` con `lista_sql()`; la app importa por
  `app/core/estados.py` (re-exporta la constante y agrega `no_cancelada()` para SQLAlchemy) en **6
  módulos** —`reservas.py` (incluido el `UPDATE` crudo del `DELETE /reservas/{id}`), `asistencia.py`,
  `supervision.py` (donde `'cancelada'` se mostraba como activa: era un bug latente),
  `kpis_populate.py`, `fidelizacion.py` y `wods.py`—. Como la lista es **exacta**, una variante nueva
  pasaría por viva: para eso está la detección **A.6** (roja) — el único `ILIKE '%cancel%'` que
  queda, y a propósito.
  **Verificado:** `tests/test_mantenimiento_cloud.py` ⇒ **125 passed** (102 + 17 de A.5 + **6
  nuevos**, `test_cl`–`test_cq`) y `tests/test_estados_compartido.py` (nuevo) ⇒ **11 passed**; el
  comando completo del README ⇒ **216 passed, 1 skipped**. Nada de PROD ni de Render (todo con
  `psql`/`smtplib`/API de Neon mockeados; el nuevo test ni siquiera sale a la red).
- **Fix P0 (2026-09-27, mismo día): el Web Service de Render no copiaba `shared/`.** `render.yaml`
  usa `Dockerfile.render` (`dockerfilePath: Dockerfile.render`, `dockerContext: .`) y ese archivo
  copiaba `backend/app/`, `backend/ml/`, `backend/alembic/`, `backend/alembic.ini` y
  `backend/requirements.txt`, pero **no** `backend/shared/` ⇒ `uvicorn app.main:app` moría al
  importar (`ModuleNotFoundError: No module named 'shared'` en `app/core/estados.py:7`, importado
  desde `app/api/v1/wods.py:11`) y el contenedor no arrancaba (Render aborta el deploy y deja la
  versión anterior). Se agregó `COPY backend/shared/ shared/` junto a `COPY backend/app/ app/` —con
  el prefijo `backend/` porque el contexto es la raíz— y `test_f` de
  `tests/test_estados_compartido.py` pasó a verificar **las tres** imágenes (web, job y render) más
  la coherencia con `render.yaml`. **Verificado** sin red: layout temporal con sólo lo que copia
  `Dockerfile.render` (`app/`, `shared/`, `ml/`, `alembic/`, `alembic.ini`, `requirements.txt`) ⇒
  `python -c "import app.main"` **exit 0** (`Box CrossFit Platform API`, 204 rutas; `shared`
  resuelto desde la raíz del layout) y, quitando `shared/` (el estado anterior) ⇒ **exit 1** con ese
  `ModuleNotFoundError` (control negativo).
- **Sin tocar:** nada de `carpeta_respaldo_box`, ni `.env`/`.env.test`, ni PROD (el único acceso
  a PROD es el `CREATE TABLE` que **debe** fallar).
- **MRR y churn HISTÓRICOS: la vigencia por FECHA, no por el estado de hoy (2026-09-27, mismo día).**
  Las 5 consultas del bloque E definían "vigente" con `s.estado = 'activo'`, que es el estado de
  **hoy**: vencida una suscripción hoy (el paso 1 la pasa a `vencido`), desaparecía también de las
  fechas PASADAS en las que sí estuvo vigente ⇒ el MRR de referencia (último día del mes anterior)
  bajaba y `variacion_mrr_pct` / `churn_30d_pct` cambiaban solos sin que hubiera pasado nada en el
  negocio. Ahora la definición es `shared.estados.sql_suscripcion_vigente()`, el MISMO texto de SQL
  en la app y en el job: `fecha_inicio::date <= fecha AND fecha_expiracion::date >= fecha` + estado
  ≠ `pendiente`/`rechazado`. Es el criterio que `ml/features.py` ya tenía documentado desde antes
  (el estado es un snapshot mutable, el pasado se reconstruye con las fechas); la app
  (`metricas_service.mrr`, `_vigente_sql`, `retencion_cohorte`) quedó igual que el job porque la
  definición es una sola.
  La exclusión de lo que NUNCA estuvo vigente es **explícita y no implícita**: al invertir el filtro,
  una `pendiente`/`rechazada` con fechas dentro de la ventana se colaría en el MRR, así que la lista
  es cerrada (`ESTADOS_SUSCRIPCION_NUNCA_VIGENTES` = `pendiente`, `rechazado`) y parte el enum nativo
  `estado_suscripcion` (migración 023) en dos sin huecos: `activo`/`vencido` son los que pueden haber
  estado vigentes (una `vencido` SÍ suma para los meses en que lo estuvo) y `test_g` verifica la
  partición contra el modelo, para que un estado nuevo no se clasifique en silencio.
  **Verificado:** `tests/test_mrr_historico.py` (nuevo) ⇒ **4 passed** con los dos casos del pedido
  (vencer una suscripción hoy no cambia el MRR de los meses pasados; una rechazada no suma nunca) y
  la **contraprueba** del control negativo: con el SQL viejo `test_b`/`test_d` (app) y `test_cr`
  (job) **fallan**. `tests/test_mantenimiento_cloud.py` ⇒ **127 passed**,
  `tests/test_estados_compartido.py` ⇒ **12 passed** y el comando completo del README ⇒ **223
  passed, 1 skipped** (los **7** del Excel entran con el commit aparte que sigue; con ese commit el
  mismo comando da 230, y 231 con el de la tarjeta de MRR de más abajo). Sin red, sin base y sin PROD
  (el SQL del lado app se captura con una sesión doble).
- **El Excel de `/reportes/export`: el MRR por mes, de la MISMA función que el dashboard y el BI
  (2026-09-27, mismo día, commit aparte).** `_build_historico_mensual` —la tabla "Historico Mensual"
  del .xlsx— tenía su propia copia del MRR (`s.estado = 'activo' AND s.fecha_expiracion >= :fin`, sin
  `fecha_inicio`) y la columna "Alumnos activos fin de mes" con el mismo filtro, así que los meses ya
  cerrados se recalculaban con el estado de HOY: el mes pasado cambiaba según el día en que se
  descargaba el archivo (una suscripción vencida hoy desaparecía de los meses en los que sí estuvo
  vigente y una que empieza el mes que viene sumaba al mes pasado). Las dos columnas usan ahora el
  corte del **último día de cada mes**: el MRR es `metricas_service.mrr(db, tenant_id, ultimo_dia)`
  (la MISMA función del dashboard —`reportes.py`, en vivo— y del BI —`kpis_populate.py`, que persiste
  el mes cerrado con el mismo `fin`—, así el número no tiene una tercera versión) y el conteo de
  alumnos va con `shared.estados.sql_suscripcion_vigente("s", ":fin")`. La tarjeta KPI "MRR" del
  Resumen Ejecutivo (que también tenía su copia, con la fecha del día) pasa a `metricas_service.mrr`
  con la fecha UTC: la misma definición Y la misma fecha que el dashboard, así el Excel y la pantalla
  no pueden mostrar números distintos (la FECHA de la tarjeta la cambia el commit de abajo: pasa al
  corte del mes elegido). El `alumnos_activos` de esa fila de tarjetas queda como estaba a propósito:
  es la foto de HOY y su consulta es idéntica a la del KPI del dashboard.
  **Verificado:** `tests/test_reporte_historico_mensual.py` (nuevo) ⇒ **7 passed** con los dos casos
  del pedido: el .xlsx se genera de verdad (sesión doble con filas de fixture que evalúa el SQL
  capturado) y se LEE la celda de MRR del mes pasado de "Historico Mensual" y la tarjeta del KPI.
  **Contraprueba (control negativo):** volviendo el SQL viejo fallan **los 7** —la celda del mes
  pasado queda en 0 en vez de 75.000, el predicado desaparece del conteo de alumnos, la tarjeta deja
  de llamar a `metricas.mrr` y el export vuelve a tener su copia del `SUM(p.precio_clp)`—. Comando
  completo del README ⇒ **230 passed, 1 skipped**. Sin red, sin base y sin PROD.
- **La tarjeta de MRR del Excel: el corte del MES ELEGIDO, no el de hoy (2026-09-27, mismo día, commit
  aparte).** La tarjeta KPI "MRR" del Resumen Ejecutivo mostraba el MRR de HOY aunque el reporte fuera
  de, por ejemplo, agosto: el número no coincidía con la celda de ese mes en "Historico Mensual" y
  cambiaba según el día en que se descargaba el archivo. La fecha de corte sale ahora de una sola
  función, `reportes_service._corte_suscripciones(ultimo_dia_del_mes)`: el **último día** del mes
  elegido y **HOY** si el mes elegido es el **en curso** (el mes no cerró; contar los días que faltan
  adelantaría suscripciones que empiezan más adelante). Es el mismo corte que la celda del mismo mes de
  la tabla —el MRR sigue siendo `metricas_service.mrr`, la función única del dashboard y del BI— y la
  **etiqueta de la tarjeta lo dice: "MRR al 31/08/2026"** (con el mes en curso, "MRR al 28/09/2026").
  La columna de alumnos del mes en curso usa el mismo corte (antes se cortaba al último día del mes),
  así que la fila del mes en curso de la tabla y la tarjeta dicen siempre lo mismo; el resto de esa
  fila (los otros KPI, ingresos/egresos/ventas/nuevos) sigue siendo lo que ya era.
  **Verificado:** `tests/test_reporte_historico_mensual.py` ⇒ **8 passed**: el `test_f` nuevo (mes en
  curso: la tarjeta, la celda del mes y `metricas_service.mrr(db, tenant_id, hoy)` son el mismo número,
  y la fila de fixture que empieza mañana NO cuenta) y el `test_g` nuevo (mes pasado elegido: la
  tarjeta es la celda de ESE mes y no la de hoy, y la etiqueta trae la fecha del corte). **Contraprueba
  (control negativo):** volviendo `corte_mrr = datetime.now(timezone.utc).date()` fallan `test_e` y
  `test_g`; volviendo `corte = fin` (mes en curso "al cierre") fallan `test_a`, `test_d`, `test_e`,
  `test_f` y `test_g` (la celda del mes en curso da 170.000 contra 90.000 de hoy). Comando completo del
  README ⇒ **231 passed, 1 skipped**. Sin red, sin base y sin PROD.
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
  sin credenciales. Tests: `tests/test_mantenimiento_cloud.py` (33) +
  `tests/test_mantenimiento_pasos.py` (4) ⇒ **37 passed**, y los otros archivos de tests de
  mantenimiento/correo siguen verdes: `test_watchdog_backups.py` + `test_restore_drill.py` +
  `test_email_config_prod.py` ⇒ 28 passed; `test_email_header_saneo.py` ⇒ 48 passed; y
  `test_mantenimiento_vencidos.py` ⇒ **1 skipped** (sólo corre con `ENVIRONMENT=test`: ejecuta el
  job, que escribe). (Con la regla nueva "correo = algo que revisar": los casos verdes comprueban
  que NO se llama a `enviar_email` y los rojos que el asunto empieza con `[ALERTA]`.)
- **Verificado (H4, con `TestClient`):** con `ENVIRONMENT=production` los 2 endpoints n8n
  responden **404** (sin llegar a mirar la API key); con `ENVIRONMENT=test` y una key inválida
  responden **401** ⇒ la guarda no rompió el chequeo de la key ni el camino de TEST.
- **Pendiente (necesita OK del dueño, nada de esto se tocó):** crear el rol `maint_rw` en Neon
  (SQL del README + verificación + prueba negativa), crear el env group `mantenimiento-prod`,
  crear el 4º Cron Job en Render y hacer la puesta en marcha por fases (`DRY_RUN=1` → leer el log o
  la alerta → `DRY_RUN=0` a mano → dejar `DRY_RUN=0` con `MAX_VENCIDOS_PCT=80`,
  `MAX_HUERFANAS=10` y `MAX_CAMBIOS=500`).
- **Menor, sigue pendiente:** volcar/desactivar los workflows de n8n "Mantenimiento %" (H2/H5):
  los desactiva Jebbus en la UI de n8n (el job nuevo no depende de n8n).
- **Nota cruzada (2026-09-28, sólo documentación + scripts locales, nada de PROD):** para la demo
  del 6/10 se escribió el **seed anual** (`scripts/seed_anual_prod.py` + `scripts/borrar_seed_anual.py`
  + `tests/test_seed_anual_prod.py` ⇒ **30 passed**). Está diseñado contra ESTAS detecciones y estos
  pasos: con el seed adentro, `mantenimiento_cloud.py` en `DRY_RUN=1` tiene que dar **0 cambios y 0
  detecciones nuevas** (el único número que sube es **A.1(c)**, informativo, +300 usuarios
  `demo.prod.anual.N@example.com`). El único cambio que este README registra por eso es esta nota:
  **no se tocó** ni un paso, ni una guarda, ni un umbral del mantenimiento. Detalle, plan de
  ejecución y reversión: `scripts/README_seed_anual.md`.

