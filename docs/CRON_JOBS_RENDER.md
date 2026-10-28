# Cron Jobs de Render — qué corre, con qué entorno y cómo verificarlo

> Documento operativo del hallazgo **B4** de la auditoría (2026-10-28). Hasta esa fecha los
> 5 Cron Jobs de PROD existían **sólo en el dashboard de Render**: no había forma de auditarlos
> ni de recrearlos, y `mantenimiento_cloud.py` traía `DRY_RUN=1` **por defecto** (el job hacía
> todo el trabajo y terminaba en `ROLLBACK`, con el run en verde). Ahora están versionados en
> `render.yaml` (`type: cron`) y el modo de ejecución es explícito.
>
> Fuentes: `render.yaml` (bloque *CRON JOBS*), `backend/Dockerfile.cron`,
> `backend/maintenance/README.md` (detalle de cada script y de cada variable) y
> `backend/maintenance/{backup_cloud,watchdog_backups,restore_drill,mantenimiento_cloud,kpis_cloud}.py`.

## 1. Los 5 jobs

`schedule` en Render **siempre es UTC**. Chile es UTC-3 de septiembre a abril y UTC-4 el resto
del año, así que la hora CLT de abajo se corre 1 h en invierno.

| # | Job (`name` en `render.yaml`) | Schedule (UTC) | Hora CLT | `dockerCommand` | Env groups | Exit ≠ 0 |
|---|---|---|---|---|---|---|
| 1 | `proyecto-crossfit` | `0 6 * * *` | 03:00 diario | `python -m maintenance.backup_cloud` | `backups-prod` | 2/3/4/5 |
| 2 | `box-crossfit-mantenimiento-prod` | `0 8 1,15 * *` | 05:00 días 1 y 15 | `python -m maintenance.mantenimiento_cloud` | `mantenimiento-prod` + `alertas` + `neon-api` | 2/3/4/6/9 |
| 3 | `box-crossfit-watchdog` | `0 12 * * *` | 09:00 diario | `python -m maintenance.watchdog_backups` | `r2-lectura` + `alertas` | 2/6/7 |
| 4 | `box-crossfit-restore-drill` | `0 13 1 * *` | 10:00 el día 1 | `python -m maintenance.restore_drill` | `backups-prod` + `neon-api` + `alertas` | 2/8/9/10/11/12/13 |
| 5 | `box-crossfit-kpis-ml` | `0 10 * * *` | 06:00 (07:00 en verano) | `python -m maintenance.kpis_cloud` | `kpis-prod` + `alertas` | 2/6 |

Común a los 5:

| Campo | Valor | Por qué |
|---|---|---|
| `runtime` | `docker` | La imagen la construye `backend/Dockerfile.cron` (no `Dockerfile.render`): copia **sólo** los módulos de `maintenance/` + `shared/`, sin FastAPI ni SQLAlchemy |
| `dockerfilePath` / `dockerContext` | `backend/Dockerfile.cron` / `backend` | Si se apunta al Dockerfile del web service, el job arranca uvicorn y el run queda vivo hasta el corte de 12 h |
| `plan` | `starter` | Los Cron Jobs **no existen** en el free tier; el mínimo facturado es **US$1/mes** por job (se cobra por segundo de ejecución, con ese piso) |
| `region` | `oregon` | La misma del Web Service `box-crossfit` (us-west-2, ya probada contra Neon) |
| `autoDeploy` | (default) | El job se reconstruye cuando cambia `backend/`: un arreglo en `maintenance/` llega sin tocar el dashboard |

`dockerCommand` es **obligatorio** en los 5: si se omite, Render usa el `CMD` de la imagen
(`python -m maintenance.backup_cloud`) y el job de mantenimiento terminaría haciendo un backup.

## 2. Env groups: tienen que existir ANTES de sincronizar

`render.yaml` **no** declara los env groups: los referencia con `fromGroup` porque ya existen en
el dashboard con sus secretos (el repo no lleva valores). Si un nombre no existe, el sync falla.

| Env group | Variables | Lo usan |
|---|---|---|
| `backups-prod` | `PROD_DB_DIRECT_URL`, `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, **`DRY_RUN=0`**, `RETENTION_DAYS`, `MIN_BYTES`, `MIN_TABLAS`, `BACKUP_PREFIX` | jobs 1 y 4 |
| `r2-lectura` | `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` — **otro** token, permiso *Object Read only* | job 3 |
| `alertas` | `GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`, `ALERT_EMAIL` | jobs 2, 3, 4 y 5 |
| `neon-api` | `NEON_API_KEY`, `NEON_PROJECT_ID` | jobs 2 (lectura de CU-horas) y 4 (crear/borrar la rama del drill) |
| `mantenimiento-prod` | `MAINT_DB_URL` (rol `maint_rw`), `ENVIRONMENT=production`, límites (`MAX_*`, `DIAS_*`, `NEON_*`), `DRY_RUN` | job 2 |
| `kpis-prod` | `KPIS_API_URL`, `N8N_API_KEY` / `CRON_API_KEY` | job 5 |

El inventario completo de variables, con los valores recomendados y qué pasa si falta cada una,
está en `backend/maintenance/README.md` (una sección por job).

## 3. Cómo se aplica (y el orden que importa)

Los 5 jobs **ya existen** en el dashboard, con esos mismos nombres. El sync de un Blueprint
empareja por nombre, así que este bloque no crea nada nuevo: sólo deja de haber configuración
invisible.

1. Dashboard → **Blueprints** → el blueprint del repo → **Sync** (o *Manual sync*).
2. Leer el plan del sync **antes** de aplicar: los 5 Cron Jobs tienen que aparecer como
   *actualización* de un servicio existente. Si Render propone **crear** un servicio con un
   nombre que ya existe, el sync falla: significa que el job del dashboard no está asociado a
   este blueprint. Salida: copiar su log de los últimos runs (para tener historia), borrarlo del
   dashboard —su configuración completa ya está en `render.yaml`— y volver a sincronizar.
3. Verificar uno por uno que el job quedó con el `dockerCommand` de la tabla del §1 (un job con
   el `CMD` de la imagen hace un **backup** en vez de lo suyo).
4. Disparar **Trigger Run** en los jobs 1 y 5 (son baratos y sus logs dicen en una línea si
   actuaron: `DRY_RUN=0 (subida REAL)` / `fin: N/N llamada(s) ok`). Los jobs 2, 3 y 4 se
   verifican en su próxima corrida programada: un run verde **no** manda correo (regla "correo =
   algo que revisar"), así que hay que mirar el log.

> **Regla:** un Cron Job se cambia en `render.yaml` y se sincroniza; **nunca** sólo en el
> dashboard. Si se toca en el dashboard, el próximo sync lo revierte (o marca el blueprint como
> *out of sync*) y volvemos al punto de partida de B4.

## 4. `DRY_RUN`: fail-closed, y la precedencia que hay que conocer

`backend/Dockerfile.cron` **ya no define `DRY_RUN`** (antes traía `DRY_RUN=1`, y por eso un env
group incompleto producía runs verdes que no aplicaban nada). Qué hace hoy cada script:

| Script | Sin `DRY_RUN` | Qué se hizo |
|---|---|---|
| `mantenimiento_cloud` | **exit 2** + correo `[ALERTA] … configuración inválida` | Lista cerrada de valores (`DRY_RUN_VALORES`); la ausencia es error de configuración, no un modo de ejecución |
| `kpis_cloud` | cae a `1`: imprime el plan, no llama a nada, run **verde** | Se fija `DRY_RUN: "0"` **en el servicio** (`render.yaml`) para que no dependa del grupo |
| `backup_cloud` | cae a `1`: hace el dump y **no lo sube** | Queda en el env group `backups-prod`; si se pierde, el watchdog (job 3) avisa a las 6 h |
| `watchdog_backups`, `restore_drill` | no lo usan | No escriben en PROD: el watchdog sólo lee R2 y el drill restaura en una rama desechable |

**Precedencia (garantizada por Render):** una variable definida **en el servicio** gana sobre la
del env group. Por eso `DRY_RUN: "0"` está en los jobs 2 y 5: si mañana alguien deja el grupo sin
la variable, el job sigue actuando en vez de fingir.

⚠️ Consecuencia práctica: para un **ensayo** del job 2 no alcanza con cambiar el valor en el env
group `mantenimiento-prod` — hay que editar `render.yaml` (`value: "1"`), sincronizar, disparar el
run, leer el log/el correo (dice exactamente qué filas habrían cambiado) y volver a `"0"`.
No borrar la clave: sin ella el job sale con exit 2 a propósito.

## 5. Verificación (B1: el entorno del cron)

Esto es para el contenedor **local** `maintenance` (el que corre `docker compose --profile
mantenimiento up -d maintenance`). Los Cron Jobs de Render **no** pasan por acá: Render les
inyecta el entorno del env group directamente y `Dockerfile.cron` no tiene daemon de cron.

```bash
# 1. El entrypoint dice cuántas variables volcó y qué falta (nunca imprime valores)
docker logs --tail 20 box-crossfit-maintenance-1
#    [entrypoint] 47 variable(s) exportadas a /etc/box-maintenance.env
#    [entrypoint] ENVIRONMENT=test
#    [entrypoint] DATABASE_URL: definida
#    [entrypoint] DRY_RUN: FALTA      <- esperado: el crontab local no corre mantenimiento_cloud

# 2. El snapshot es 0600 y de boxapp (lleva SECRETOS: SMTP, URL con password)
docker exec box-crossfit-maintenance-1 ls -l /etc/box-maintenance.env
#    -rw------- 1 boxapp boxapp ... /etc/box-maintenance.env

# 3. El crontab usa el wrapper y declara SHELL/PATH
docker exec box-crossfit-maintenance-1 head -n 25 /etc/cron.d/box-maintenance

# 4. Un job ve el entorno de verdad (mismo camino que cron_job.sh, como boxapp)
docker exec -u boxapp box-crossfit-maintenance-1 sh -c \
  'set -a; . /etc/box-maintenance.env; set +a; echo "ENVIRONMENT=$ENVIRONMENT"; python -c "import os; print(\"DATABASE_URL definida:\", bool(os.getenv(\"DATABASE_URL\")))"'

# 5. Resultado de los jobs (los logs viven en el volumen `logs`)
docker exec box-crossfit-maintenance-1 tail -n 30 /app/logs/cron.log
```

El síntoma que esto elimina (B1): los 5 pasos de `run_daily` fallaban con *Connection refused*
contra `localhost:5432` **todas las noches desde 2026-10-02**, con salida 0. Si el punto 1 dice
`ENVIRONMENT no está definida`, el contenedor se levantó sin `environment:`/`env_file:` en
`docker-compose.yml` y los jobs vuelven a escribir en la base equivocada.

## 6. Qué sigue sin estar versionado acá

| Pieza | Dónde vive | Nota |
|---|---|---|
| Secretos del Web Service | Dashboard (`sync: false` en `render.yaml`) | Sólo se declara la **clave**, nunca el valor |
| Valores de los env groups | Dashboard (*Env Groups*) | El repo lista qué variable necesita cada job, no sus valores |
| Workflows de n8n | Fuera de Render | Hallazgo **B9** de la auditoría (sin reemplazo versionado para `fidelizacion y retencion`) |
| Contenedor local `maintenance` | `docker-compose.yml` (perfil `mantenimiento`) | Su propio `crontab` + `cron_job.sh` + `docker-entrypoint.sh`, ver §5 |

## 7. Validación del archivo

```bash
# Sintaxis y forma del bloque (no requiere Render CLI ni credenciales)
python -c "import yaml; d=yaml.safe_load(open('render.yaml', encoding='utf-8')); print([(s['type'], s['name']) for s in d['services']])"
#   [('web', 'box-crossfit'), ('cron', 'proyecto-crossfit'),
#    ('cron', 'box-crossfit-mantenimiento-prod'), ('cron', 'box-crossfit-watchdog'),
#    ('cron', 'box-crossfit-restore-drill'), ('cron', 'box-crossfit-kpis-ml')]
```

Con el Render CLI instalado, `render blueprints validate` valida contra el esquema oficial
(incluye `fromGroup` y `dockerCommand`).
