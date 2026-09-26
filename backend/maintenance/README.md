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

