# 🔧 Mantenimiento Urban Training Box

**Carpeta de scripts automáticos ejecutados por APScheduler.**

## Ejecución automática

- **Diario 02:30 AM** → `run_daily.py` (backup, planes vencidos, huérfanas, health, neon usage)
- **Mensual (1º día 03:00 AM)** → `run_monthly.py` (todo + integridad + estadísticas + rotación)

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
