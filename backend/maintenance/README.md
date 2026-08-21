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

## Requisito `backup_neon.py` — pg_dump en PATH

`backup_neon.py` ejecuta `pg_dump` (cliente PostgreSQL). En Windows suele instalarse en
`C:\Program Files\PostgreSQL\<version>\bin` y **no está en el PATH por defecto**.

Para que el backup funcione, agregar esa carpeta al PATH **del usuario** (una vez):

```powershell
# PowerShell (los procesos ya abiertos deben reiniciarse para tomar el PATH nuevo)
$bin = 'C:\Program Files\PostgreSQL\18\bin'
$cur = [Environment]::GetEnvironmentVariable('Path', 'User')
[Environment]::SetEnvironmentVariable('Path', "$cur;$bin", 'User')
```

> Alternativa sin tocar PATH: invocar el backup con el path completo
> `& 'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe'` (ver `backend/_backup_full.py`,
> que ya usa el binario directo).

## Conexión a base de datos

Los scripts usan **`settings.DATABASE_URL`** (singleton de `app/core/config.py`), es decir
la del `.env` **activo** del proceso. No definen `ENVIRONMENT=test` por defecto
(verificado 19/08/2026): si el proceso arranca con `ENVIRONMENT=test` carga `.env.test`
(BD de TEST), si no, carga `.env` (BD activa).
