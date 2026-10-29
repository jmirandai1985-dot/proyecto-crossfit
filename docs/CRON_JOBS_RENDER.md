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

## 1. Los 5 jobs de PROD (+ 3 de retención en TEST y 3 en PROD, todos en modo ensayo)

> **+ 3 jobs de retención (B8) de TEST** y **+ 3 de PROD**, todos declarados en `render.yaml` con
> `DRY_RUN="1"` por default (cuentan filas y no borran nada): ver **§8** (TEST) y **§9** (PROD).
> Son **11 `type: cron`** en total (+ el web service).

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
| `retencion-test` | `RETENCION_DB_URL` (rol `retencion_rw` de TEST), `ENVIRONMENT=test`, `ANONIMIZACION_PEPPER` | jobs 6-8 (§8) |
| `retencion-prod` | `RETENCION_DB_URL` (rol `retencion_rw` de PROD), `ENVIRONMENT=production`, `ANONIMIZACION_PEPPER` | jobs 9-11 (§9) |

El inventario completo de variables, con los valores recomendados y qué pasa si falta cada una,
está en `backend/maintenance/README.md` (una sección por job).

## 3. Cómo se aplica (y el orden que importa)

Los 5 jobs de PROD **ya existen** en el dashboard, con esos mismos nombres. El sync de un
Blueprint empareja por nombre, así que para ellos este bloque no crea nada nuevo: sólo deja de
haber configuración invisible. Los 3 de **retención de TEST** (§8) y los 3 de **retención de
PROD** (§9) sí se **crean** en el primer sync.

1. Antes de sincronizar, crear los env groups `retencion-test` (§8.1) y `retencion-prod` (§9.2),
   y aplicar la migración 065 en las dos bases: si un `fromGroup` no existe, el sync **falla
   entero** y el web service se queda con la versión anterior.
2. Dashboard → **Blueprints** → el blueprint del repo → **Sync** (o *Manual sync*).
3. Leer el plan del sync **antes** de aplicar: los 5 Cron Jobs de PROD tienen que aparecer como
   *actualización* de un servicio existente. Si Render propone **crear** un servicio con un
   nombre que ya existe, el sync falla: significa que el job del dashboard no está asociado a
   este blueprint. Salida: copiar su log de los últimos runs (para tener historia), borrarlo del
   dashboard —su configuración completa ya está en `render.yaml`— y volver a sincronizar.
4. Verificar uno por uno que el job quedó con el `dockerCommand` de la tabla de §1 / §8 / §9
   (un job con el `CMD` de la imagen hace un **backup** en vez de lo suyo).
5. Disparar **Trigger Run** en los jobs 1 y 5 (son baratos y sus logs dicen en una línea si
   actuaron: `DRY_RUN=0 (subida REAL)` / `fin: N/N llamada(s) ok`). Los jobs 2, 3, 4 y los 3 de
   retención se verifican en su próxima corrida programada: un run verde **no** manda correo
   (regla "correo = algo que revisar"), así que hay que mirar el log. En retención, la línea que
   importa es `DRY_RUN=1 (ensayo: no escribe)` + `habría movido N`.

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
#    ('cron', 'box-crossfit-restore-drill'), ('cron', 'box-crossfit-kpis-ml'),
#    ('cron', 'box-crossfit-retencion-archivar'), ('cron', 'box-crossfit-retencion-auditoria'),
#    ('cron', 'box-crossfit-retencion-anonimizar'),
#    ('cron', 'box-crossfit-retencion-archivar-prod'),
#    ('cron', 'box-crossfit-retencion-auditoria-prod'),
#    ('cron', 'box-crossfit-retencion-anonimizar-prod')]
```

Con el Render CLI instalado, `render blueprints validate` valida contra el esquema oficial
(incluye `fromGroup` y `dockerCommand`).

## 8. Retención de datos (B8): 3 jobs dados de alta en modo ENSAYO

`backend/maintenance/retencion_cloud.py` implementa los 3 trabajos de retención pedidos en
`docs/RETENCION_DATOS_Y_N8N.md` §1. Están **probados y corribles** y desde 2026-10-29 están
**declarados en `render.yaml`** con `DRY_RUN="1"` por default: la primera corrida cuenta filas,
manda el correo de "habría movido N" y **no escribe nada**. Pasar a `"0"` es una decisión
explícita (y en TEST exige además `RETENCION_TEST_OK=1`).

| # | Job (`name`) | Schedule (UTC) | Hora CLT | `dockerCommand` | Exit ≠ 0 |
|---|---|---|---|---|---|
| 6 | `box-crossfit-retencion-archivar` | `0 15 1 * *` | 12:00 el día 1 | `python -m maintenance.retencion_cloud archivar` | 2/3/4/5/6/7 |
| 7 | `box-crossfit-retencion-auditoria` | `0 15 2 * *` | 12:00 el día 2 | `python -m maintenance.retencion_cloud auditoria` | 2/3/5/6/7 |
| 8 | `box-crossfit-retencion-anonimizar` | `0 15 3 * *` | 12:00 el día 3 | `python -m maintenance.retencion_cloud anonimizar` | 2/3/5/6/7 |

Por qué `15:00 UTC` y días 1/2/3 (la grilla completa, en UTC):

| Hora UTC | Job | Frecuencia |
|---|---|---|
| 06:00 | backup (`proyecto-crossfit`) | diario |
| 08:00 | mantenimiento | días 1 y 15 |
| 10:00 | KPIs/ML | diario |
| 12:00 | watchdog | diario |
| 13:00 | restore drill | día 1 |
| **15:00** | **retención (§8)** | **días 1, 2 y 3** |

15:00 UTC queda 9 h después del backup y 2 h después del restore drill del día 1 (el job más
caro de la grilla): ningún cron pisa a otro y ninguno compite por la base con el archivado.
Los 3 trabajos caen en **días distintos a propósito**: `anonimizar` es irreversible y nunca
corre el mismo día que `archivar`.

Qué hace cada uno (y por qué en ese orden del mes):

| Trabajo | Regla | Qué mueve | Reversible |
|---|---|---|---|
| `archivar` | > **5 años** (`ANIOS_RETENCION_ARCHIVO`) | `asistencias` y `reservas` → `asistencias_archivo` / `reservas_archivo` + CSV.gz en R2 | Sí (las filas quedan en `*_archivo`) |
| `auditoria` | > **2 años** (`ANIOS_RETENCION_AUDITORIA`) | `DELETE` de `auditoria` (no se archiva) | **No** |
| `anonimizar` | **12 meses** desde `fecha_baja` (`MESES_RETENCION_ANONIMIZAR`) | nombre/correo/teléfono/RUT → valores anónimos + `anonimizado_en` | **No**; el día 2, nunca el mismo día que el archivo |

`dockerCommand` **siempre con el argumento**: el script exige exactamente un trabajo
(`archivar | auditoria | anonimizar`) y sale con exit 2 si falta o es otro. Sin argumento
**no hace nada** — no hay default, a propósito.

### 8.1 Variables (env group `retencion-test`, que hay que crear antes de sincronizar)

| Variable | Obligatoria | Default | Nota |
|---|---|---|---|
| `RETENCION_DB_URL` | sí | — | Conexión **directa** (nunca `-pooler`). En PROD: usuario `retencion_rw` |
| `ENVIRONMENT` | sí | — | `test` (hoy) o `production`. El script **rechaza** la URL si no calza con el entorno |
| `DRY_RUN` | no | `1` | Con `1` cuenta filas, manda correo con "habría movido N" y **no escribe** |
| `RETENCION_TEST_OK` | sólo para escribir en TEST | — | `1` habilita `DRY_RUN=0` contra TEST; sin ella ⇒ exit 2 (guarda anti-PROD) |
| `ANONIMIZACION_PEPPER` | `anonimizar` | — | ≥ 16 caracteres; sal del `sha256` del RUT anónimo. **Perderla cambia todos los `rut_anonimo` futuros** |
| `RETENCION_RESPALDO_LOCAL` | alternativa a R2 | — | Directorio local para el CSV.gz cuando no hay R2 (sólo TEST) |
| `R2_ENDPOINT` / `R2_BUCKET` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | `archivar` (si no hay respaldo local) | — | Se reusan los del grupo `backups-prod` |
| `ANIOS_RETENCION_ARCHIVO` / `ANIOS_RETENCION_AUDITORIA` / `MESES_RETENCION_ANONIMIZAR` | no | `5` / `2` / `12` | Rangos validados (1..50 / 1..50 / 1..120) |
| `TAM_LOTE` | no | `5000` | Filas por lote de copia/borrado |
| `MAX_ARCHIVAR` / `MAX_BORRAR_AUDITORIA` / `MAX_ANONIMIZAR` | no | `20000` / `100000` / `1000` | Tope **por corrida**: si se supera ⇒ exit 5 y **no se escribe nada** |
| `RETENCION_LOCK_HORAS` | no | `12` | Vencimiento del bloqueo en `retencion_bloqueos` |
| `RETENCION_PREFIJO` | no | `retencion/` | Prefijo de los objetos en R2 |
| `GMAIL_SMTP_USER` / `GMAIL_SMTP_APP_PASSWORD` / `ALERT_EMAIL` | no | — | Sin las 3 no hay correo, pero el exit code no cambia |

### 8.2 Correrlo a mano contra TEST (lo que se hace hoy)

```bash
# Desde backend/, con el entorno de TEST cargado (.env.test: DATABASE_URL de la rama TEST).
$env:ENVIRONMENT="test"; $env:RETENCION_DB_URL=$env:DATABASE_URL
$env:DRY_RUN="1"                 # default, pero explícito: no escribe
$env:RETENCION_RESPALDO_LOCAL="$env:TEMP\retencion"   # sin R2: el CSV queda en disco
py -3.12 -m maintenance.retencion_cloud archivar      # exit 0 = sólo contó
py -3.12 -m maintenance.retencion_cloud auditoria
py -3.12 -m maintenance.retencion_cloud anonimizar    # + ANONIMIZACION_PEPPER (≥16)
```

Para que **escriba** en TEST hacen falta las dos: `DRY_RUN=0` **y** `RETENCION_TEST_OK=1`.
Con una sola, exit 2 y correo. Antes de la primera corrida real hay que aplicar
`alembic upgrade head` (migración `065_retencion_datos`): si faltan las tablas, el script sale
con exit 3 y dice exactamente qué falta.

### 8.3 Cómo se activan en Render (orden que importa)

1. `alembic upgrade head` en la base destino (TEST primero).
2. Crear el rol `retencion_rw` por SQL (mismo procedimiento que `maint_rw`, README Fase 12) con
   `GRANT` sólo sobre `asistencias`, `reservas`, `auditoria`, `usuarios`,
   `asistencias_archivo`, `reservas_archivo`, `retencion_bloqueos`.
3. Crear el env group `retencion-test` con las variables de §8.1 (`DRY_RUN=1`).
4. Sincronizar el Blueprint: el bloque *# 6-8)* del final de `render.yaml` ya está descomentado,
   así que el sync **crea** los 3 jobs.
5. Correr una vez con `DRY_RUN=1`, leer el correo/el log, y recién entonces pasar a `0` +
   `RETENCION_TEST_OK=1` para la corrida real en TEST.
6. PROD: mismo orden, con el grupo `retencion-prod` (§9), `ENVIRONMENT=production` y **sin**
   `RETENCION_TEST_OK` (esa guarda es sólo de TEST).

Estado: los 3 de **TEST** quedaron dados de alta el 2026-10-29 y corrieron en ensayo (§8.4);
los 3 de **PROD**, el mismo día, en modo ensayo también (§9).

### 8.4 Pruebas hechas en TEST (2026-10-29)

| Suite | Comando | Resultado |
|---|---|---|
| Unitaria (sin red/psql/R2) | `py -3.12 -m pytest tests/test_retencion_unit.py -q --noconftest` | **59 passed** |
| Integración con `psql` real contra TEST (opt-in) | `$env:ENVIRONMENT='test'; $env:RETENCION_INTEGRACION='1'; py -3.12 -m pytest tests/test_retencion_integracion.py -q --noconftest` | **9 passed** (~3 min) |

La integración siembra filas propias (`asistencias`/`reservas` de hace 7 años, `auditoria` de
hace 3, un alumno con baja de 18 meses) y las borra en el `finally`; el esquema verificado en TEST
es `alembic_version = 065_retencion_datos`, con `asistencias_archivo`, `reservas_archivo`,
`retencion_bloqueos` y `usuarios.anonimizado_en` + índice parcial
`ix_usuarios_bajas_por_anonimizar`.

## 9. Retención de datos en PROD (B8): los mismos 3 jobs, también en ENSAYO

Los 3 trabajos de §8 están declarados **dos veces** en `render.yaml`: una contra TEST (grupo
`retencion-test`) y otra contra **PROD** (grupo `retencion-prod`). Mismo binario, mismo
`Dockerfile.cron`, mismo contexto `backend` y mismo `dockerCommand`; lo único que cambia es el
env group y el `schedule`. Los de PROD también arrancan con **`DRY_RUN="1"`**: la primera corrida
cuenta filas y **no escribe**.

| # | Job (`name`) | Schedule (UTC) | Hora CLT | `dockerCommand` | Env groups | Exit ≠ 0 |
|---|---|---|---|---|---|---|
| 9 | `box-crossfit-retencion-archivar-prod` | `0 17 4 * *` | 14:00 el día 4 | `python -m maintenance.retencion_cloud archivar` | `retencion-prod` + `backups-prod` + `alertas` | 2/3/4/5/6/7 |
| 10 | `box-crossfit-retencion-auditoria-prod` | `0 17 5 * *` | 14:00 el día 5 | `python -m maintenance.retencion_cloud auditoria` | `retencion-prod` + `alertas` | 2/3/5/6/7 |
| 11 | `box-crossfit-retencion-anonimizar-prod` | `0 17 6 * *` | 14:00 el día 6 | `python -m maintenance.retencion_cloud anonimizar` | `retencion-prod` + `alertas` | 2/3/5/6/7 |

`runtime`, `plan`, `region`, `dockerfilePath`/`dockerContext` y `autoDeploy` son los de la tabla
"Común a los 5" (§1): `docker`, `starter`, `oregon`, `backend/Dockerfile.cron` + `backend`.

Dos detalles que no son obvios:

* `archivar` toma **sólo** `R2_*` de `backups-prod` (es donde sube el CSV.gz, prefijo
  `retencion/`). Ese grupo trae `DRY_RUN=0`, pero **no gana**: la variable declarada en el
  servicio tiene precedencia (ver §4), así que el job sigue en ensayo hasta que se cambie el
  `value` de `render.yaml`.
* `anonimizar` **no** declara `ANONIMIZACION_PEPPER` con `sync: false` (como sí hace el de TEST):
  el pepper vive en el grupo `retencion-prod`. Si se declarara en el servicio con `sync: false`,
  la variable del servicio ganaría sobre la del grupo y llegaría **vacía** ⇒ exit 2.

### 9.1 Por qué 17:00 UTC en los días 4/5/6

Grilla completa en UTC (los 11 `type: cron` del blueprint):

| Hora UTC | Job | Frecuencia |
|---|---|---|
| 06:00 | backup (`proyecto-crossfit`) | diario |
| 08:00 | mantenimiento | días 1 y 15 |
| 10:00 | KPIs/ML | diario |
| 12:00 | watchdog | diario |
| 13:00 | restore drill | día 1 |
| 15:00 | retención **TEST** (§8) | días 1, 2 y 3 |
| **17:00** | **retención PROD (§9)** | **días 4, 5 y 6** |

* **17:00 UTC** es la primera franja libre después de las 15:00 de TEST: ningún job de PROD ni de
  TEST la usa, y queda 2 h después del último de retención de TEST (margen para que un run largo
  de TEST no se solape con el arranque del de PROD).
* **Días 4/5/6** dejan libre el día 1 (el más cargado: mantenimiento 08:00 + restore drill 13:00,
  los dos jobs más caros, + `archivar` de TEST 15:00) y los días 2/3 para la retención de TEST.
  Todos los meses tienen día 4, 5 y 6, así que la corrida nunca se saltea un mes.
* Se conserva el orden del mes: `archivar` (día 4) **antes** de `anonimizar` (día 6), que es el
  irreversible, y nunca el mismo día.
* 14:00 CLT con horario de verano; **13:00 CLT** en invierno (UTC-4).

### 9.2 Env group `retencion-prod` (crear ANTES de sincronizar)

Render → *Env Groups* → **New Environment Group**, nombre exacto `retencion-prod`:

| Variable | Valor | Nota |
|---|---|---|
| `RETENCION_DB_URL` | `postgresql://retencion_rw:<password-generada>@ep-winter-star-akwis51j.c-3.us-west-2.aws.neon.tech/neondb?sslmode=require` | Conexión **DIRECTA** a la rama PROD (sin `-pooler`: el script la rechaza con exit 2). En `ENVIRONMENT=production` el usuario **tiene que ser** `retencion_rw` (cualquier otro ⇒ exit 2 sin abrir conexión) |
| `ENVIRONMENT` | `production` | **Exacto**: el script sólo acepta `test` o `production` (`prod` ⇒ exit 2) |
| `ANONIMIZACION_PEPPER` | el mismo valor de `retencion-test` | ≥ 16 caracteres; ver §9.3 |

`DRY_RUN` **no** va en el grupo: va en cada servicio (`"1"`) para que cambiarlo sea un cambio
versionado en `render.yaml` y no un click invisible en el dashboard (mismo criterio que los jobs
2 y 5 de §4). Las variables `R2_*` y las de SMTP no se declaran acá: vienen de `backups-prod`
y `alertas` con `fromGroup`.

### 9.3 ¿Mismo pepper que TEST o uno nuevo?

**El mismo valor de TEST**, por ahora:

* PROD todavía no tiene alumnos reales, así que **no hay ningún `rut_anonimo` emitido** cuyo hash
  dependa de un pepper anterior: cambiarlo más adelante no reescribe nada.
* Un solo secreto que custodiar y una sola variable que copiar; además una corrida en TEST
  produce exactamente el mismo `rut_anonimo` que produciría en PROD, que es lo que comparan los
  tests de integración.
* Rotarlo después **no** invalida lo ya anonimizado: el `rut_anonimo` guardado se conserva y el
  pepper nuevo sólo afecta a los futuros. Por eso la decisión se puede tomar **antes de cargar
  alumnos reales**, sin migración ni backfill.

### 9.4 Rol `retencion_rw` en la rama PROD — se crea SÓLO por SQL

> ⚠️ **No usar el botón *Connect* ni *Roles* de la consola de Neon.** Los roles que crea la
> consola quedan como miembros de `neon_superuser` (heredan todo y anulan cualquier contención).
> Se crea por SQL en el **SQL Editor** de la rama PROD, conectado como `neondb_owner`, igual que
> `maint_rw` y `backup_ro` (README `backend/maintenance/README.md`, Fase 6/12).

La password se genera **antes**, sólo alfanumérica (32 caracteres), y se pega **sólo** en el env
group de Render: no va al repo.

```powershell
# PowerShell: 32 caracteres alfanuméricos (sin + / = , que rompen la URI)
-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 32 | % {[char]$_})
```

```sql
-- 0) Como neondb_owner, en el SQL Editor de la rama PROD (la de ep-winter-star-akwis51j).
CREATE ROLE retencion_rw WITH LOGIN NOINHERIT PASSWORD '<password-generada>';

-- 1) Entrar: CONNECT a la base + USAGE del esquema (explícitos, aunque PUBLIC ya los otorgue).
GRANT CONNECT ON DATABASE neondb TO retencion_rw;
GRANT USAGE   ON SCHEMA   public TO retencion_rw;

-- 2) Datos: GRANT AMPLIO sobre el esquema public (decisión 2026-10-29: hoy PROD tiene datos
--    ficticios, así que no se acota al mínimo como en TEST). Lo que el job usa de verdad es:
--    SELECT/INSERT/DELETE en asistencias y reservas, lo mismo en asistencias_archivo y
--    reservas_archivo, SELECT/DELETE en auditoria, SELECT/UPDATE en usuarios (nombre, correo,
--    telefono, rut, anonimizado_en, updated_at) y SELECT/INSERT/UPDATE/DELETE en
--    retencion_bloqueos.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO retencion_rw;
GRANT USAGE,  SELECT                ON ALL SEQUENCES IN SCHEMA public TO retencion_rw;

-- 3) Que las tablas que creen las próximas migraciones también queden cubiertas: sin esto, el
--    primer job que toque una tabla nueva sale con exit 3 "permission denied". Se corre como
--    neondb_owner, que es el rol que ejecuta `alembic upgrade head`.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO retencion_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO retencion_rw;

-- 4) Nada de DDL ni de memberships: el rol NO es miembro de ningún otro (ni de neon_superuser).
```

Verificación (todo `t`, salvo `es_superuser` que tiene que dar `f`):

```sql
SELECT rolname, rolcanlogin, rolinherit FROM pg_roles WHERE rolname = 'retencion_rw';
SELECT pg_has_role('retencion_rw', 'neon_superuser', 'MEMBER') AS es_superuser;   -- f

SELECT has_database_privilege('retencion_rw', current_database(), 'CONNECT')       AS db_connect,
       has_schema_privilege('retencion_rw', 'public', 'USAGE')                     AS schema_usage,
       has_table_privilege('retencion_rw', 'public.asistencias', 'DELETE')         AS asistencias_delete,
       has_table_privilege('retencion_rw', 'public.asistencias_archivo', 'INSERT') AS archivo_insert,
       has_table_privilege('retencion_rw', 'public.reservas_archivo', 'INSERT')    AS reservas_archivo_insert,
       has_table_privilege('retencion_rw', 'public.auditoria', 'DELETE')           AS auditoria_delete,
       has_column_privilege('retencion_rw', 'public.usuarios', 'rut', 'UPDATE')    AS usuarios_rut_update,
       has_table_privilege('retencion_rw', 'public.retencion_bloqueos', 'INSERT')  AS bloqueos_insert;
```

Prueba de humo con la URL nueva (desde `backend/`, contra PROD, **sin escribir**): el script
valida TODO antes de abrir la conexión, así que un exit 2 acá es un problema de configuración y
no de permisos.

```powershell
$env:ENVIRONMENT      = "production"
$env:RETENCION_DB_URL = "<la del env group retencion-prod>"
$env:DRY_RUN          = "1"
Remove-Item Env:RETENCION_RESPALDO_LOCAL -ErrorAction SilentlyContinue   # en PROD el respaldo va a R2
py -3.12 -m maintenance.retencion_cloud auditoria      # exit 0 = contó filas, no borró nada
# `archivar` sin R2_* sale con exit 2 a propósito (no hay dónde respaldar).
```

Reversión (si hay que deshacerlo):

```sql
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES    FROM retencion_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT                ON SEQUENCES FROM retencion_rw;
REVOKE ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public FROM retencion_rw;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM retencion_rw;
REVOKE USAGE   ON SCHEMA   public FROM retencion_rw;
REVOKE CONNECT ON DATABASE neondb FROM retencion_rw;
DROP ROLE retencion_rw;      -- falla si le quedó algún privilegio: es a propósito
```

### 9.5 Cómo se activan (orden que importa)

1. `alembic upgrade head` en PROD (tiene que quedar `alembic_version = 065_retencion_datos`).
2. Crear el rol `retencion_rw` por SQL (§9.4) y verificar los `has_*_privilege`.
3. Crear el env group `retencion-prod` (§9.2). Sin el grupo, el sync **falla entero**.
4. Sincronizar el Blueprint: es el primer sync en que los 3 jobs de PROD **se crean** (US$1/mes
   cada uno). Los 5 de §1 y los 3 de TEST sólo se actualizan.
5. Disparar **Trigger Run** en cada uno (o esperar a su día 4/5/6) y leer el **log**: la línea que
   importa es `DRY_RUN=1 (ensayo: no escribe)` + `habría movido N`. Un run sin nada que hacer no
   manda correo; con `N > 0` sí llega el correo (regla "correo = algo que revisar").
6. Con los 3 verdes en ensayo y los números leídos, **recién ahí** pasar `DRY_RUN` a `"0"` en los
   3 servicios de `render.yaml` y sincronizar. En PROD **no** hace falta `RETENCION_TEST_OK`.

Dos guardas de volumen que conviene mirar **antes** de la primera corrida real (no cambian nada
mientras `DRY_RUN=1`, pero sí abortan la corrida real con exit 5 y sin escribir):

| Guarda | Default | Qué hacer si el ensayo dice N > default |
|---|---|---|
| `MAX_ANONIMIZAR` | `1 000` | Subirlo en `retencion-prod`, o dejar que se anonimicen 1 000 por mes (la regla es 12 meses desde la baja, no hace falta ponerse al día de golpe) |
| `MAX_ARCHIVAR` | `20 000` | Las filas de más de 5 años suelen ser pocas por mes; si el backlog es grande, subirlo |

### 9.6 Pruebas (2026-10-29)

| Suite | Comando | Resultado |
|---|---|---|
| Unitaria (sin red/psql/R2) | `py -3.12 -m pytest tests/test_retencion_unit.py -q --noconftest` | **59 passed** |
| Integración con `psql` real contra TEST (opt-in) | `$env:ENVIRONMENT='test'; $env:RETENCION_INTEGRACION='1'; py -3.12 -m pytest tests/test_retencion_integracion.py -q --noconftest` | **9 passed** (~3 min) |

La primera pasada de integración dio **8 passed / 1 failed** en
`test_anonimizar_baja_de_18_meses`, y **no** por el código: la última aserción exigía que
*ningún dígito del RUT original* apareciera en el RUT anónimo (`ANON` + 8 caracteres base36
sacados de un SHA-256). El RUT sembrado por el test es `99.999.99x-9`, así que esa condición era
"el hash no contiene ningún `9`": falla **~20 % de las corridas** ((35/36)^8 ≈ 0,80). Se cambió
por dos aserciones deterministas (`rut_nuevo != rut and rut not in rut_nuevo` y "el valor guardado
ya no tiene forma de RUT"), que prueban lo mismo (no queda el RUT en claro) sin depender del azar
del hash. Con eso la suite completa quedó en **9 passed**, y la corrida del test aislado pasa en
18 s.

No hay suite nueva para PROD: el código es el mismo y lo que cambia es **configuración**
(`RETENCION_DB_URL`, `ENVIRONMENT`, `DRY_RUN`). Lo que sí se prueba en PROD es el arranque real:
el ensayo del punto 5 de §9.5 valida en un solo run la URL directa, el rol `retencion_rw`, la
migración 065 y los permisos (`exit 0` = todo eso está bien).





