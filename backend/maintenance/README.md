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

### Crear el Cron Job en Render
1. Dashboard → **New → Cron Job** → repo + rama (`main`).
2. Runtime **Docker**: *Dockerfile Path* = `backend/Dockerfile.cron`;
   *Docker Build Context Directory* = `backend`.
3. **Environment**: *Link Environment Group* → **`backups-prod`** (entran las 10 variables).
   Confirmá `DRY_RUN=1` para el primer disparo.
4. Schedule (UTC): `0 6 * * *` = **03:00 CLT** diario.
5. Región: la misma que el resto de los servicios (us-east-2) si el plan lo permite.
6. Crear → **Runs → Trigger Run** (no hace falta esperar a las 03:00) y revisar el log.
7. Con el log en verde: `DRY_RUN=0`, disparar de nuevo a mano y verificar que el objeto aparece
   en R2 (`daily/AAAA-MM-DD_HHMM_neon_backup.sql.gz`).

> Costo: los Cron Jobs no existen en el plan free; el mínimo es **US$1/mes** por servicio.
> Para versionarlo se puede declarar en `render.yaml` (`type: cron`), pero recién después de
> validarlo a mano, así un sync del blueprint no crea algo a medio probar.

