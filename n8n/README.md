# `n8n/workflows/` — Workflows exportados (⚠️ leer antes de importar)

Estos JSON son **copias de referencia** de workflows que viven en la **instancia de n8n**.
El repo **no** es la fuente de verdad de la automatización: la instancia lo es.

## ⚠️ Autenticación: `X-N8N-API-Key`

Los nodos HTTP Request mandan el header `X-N8N-API-Key` (**no** usan credencial de n8n).
En este repo el valor está **sanitizado** como placeholder:

```json
{ "name": "X-N8N-API-Key", "value": "REPLACE_WITH_YOUR_KEY" }
```

> **Historia:** hasta el 14/09/2026 estos 6 archivos estaban versionados con la clave real
> en texto plano (y el repo de GitHub es público). Se rotaron las claves y se reemplazó el
> valor por el placeholder. La clave vieja queda visible en commits anteriores: la
> mitigación real fue **rotarla**, no borrarla del historial.

### Qué clave corresponde a cada workflow

| Workflow (instancia) | URL destino | Variable que valida |
|---|---|---|
| `Populate Daily/Monthly KPIs`, `Populate Predictions`, `Mantenimiento Diario/Mensual`, `Urgencia`, `1. RENOVACIÓN`, `INACTIVIDAD`, `ÚLTIMO CRÉDITO`, `SIN CRÉDITOS` | `http://host.docker.internal:8001` (**TEST**) | `N8N_API_KEY` de `backend/.env.test` |
| `Populate Daily/Monthly KPIs [PROD]`, `Populate Predictions [PROD]`, `Reentrenar Modelo ML`, **`fidelizacion y retencion`** | `https://box-crossfit.onrender.com` (**PROD**) | `N8N_API_KEY` de `backend/.env` **y** de la env var del servicio backend en Render |

> **Cambio 2026-09-26 — `fidelizacion y retencion` pasó de TEST a PROD.**
> Es el cierre MENSUAL (cron `0 5 0 1 * *` → día 1, 00:05 CLT) que llama a
> `POST /api/v1/asistencia/n8n/evaluar-mes` y dispara los correos de
> **cumplimiento, acompañamiento, hito_racha_1/3/6/12 y reactivación**.
> Antes apuntaba a `host.docker.internal:8001` (TEST) con la key de TEST, así que
> esos correos **nunca llegaban a alumnos reales**. Ahora apunta a PROD con la key
> de PROD (misma key que usan los workflows `[PROD]`).
> Copia saneada versionada en `n8n/workflows/fidelizacion_y_retencion_prod.json`.
> Verificado con una corrida real del trigger (sonda `?anio=2026&mes=13`): n8n
> ejecutó el workflow (`mode=trigger`) y PROD respondió su propia validación
> `400 "mes fuera de rango (1-12)"`, lo que prueba URL + key válidas sin enviar
> un solo correo.
> Para revivir el flujo contra TEST (por ejemplo para pruebas) hay que crear un
> workflow aparte apuntando a `host.docker.internal:8001` con la key de `.env.test`.

### ⚠️ Si editás workflows por SQLite (sin la UI)

n8n v2 versiona por `versionId`/`activeVersionId` y el motor NO relee
`workflow_entity.nodes` si hay una **WAL** pendiente. Procedimiento probado:

1. `docker stop box-crossfit-n8n-1`
2. editar `database.sqlite`: los `nodes` + nueva versión en `workflow_history` +
   `workflow_entity.versionId`/`activeVersionId`
3. borrar `database.sqlite-wal` y `database.sqlite-shm` del volumen
   (`docker run --rm --user root --entrypoint sh -v box-crossfit_n8n_data:/data n8nio/n8n:2.36.4 -c "rm -f /data/database.sqlite-wal /data/database.sqlite-shm; chown 1000:1000 /data/database.sqlite"`)
4. `docker start box-crossfit-n8n-1`
5. `docker exec box-crossfit-n8n-1 n8n publish:workflow --id=<id>` (**obligatorio**:
   sin publicar, el trigger programado NO se registra) y reiniciar n8n
6. verificar con `n8n export:workflow --id=<id> --output=/tmp/wf.json`

(La UI hace los pasos 2–5 sola; esto es sólo para automatizar sin credenciales.)


El backend valida con `secrets.compare_digest` contra `settings.N8N_API_KEY` y rechaza
claves vacías (`app/api/v1/kpis_populate.py`, `app/api/v1/mantenimiento.py`).

## Cómo rotar la clave (procedimiento probado)

1. Generar una clave nueva por entorno: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   (TEST y PROD **distintas**).
2. Actualizar `backend/.env.test` (TEST) y `backend/.env` (PROD) → `N8N_API_KEY=...`
   (gitignored; nunca versionar).
3. **PROD:** actualizar la env var `N8N_API_KEY` del **servicio backend en Render** y guardar
   (Render redeploya). El backend de PROD no la lee del repo.
4. Recrear el backend local para que tome la clave nueva:
   `docker compose up -d --force-recreate backend`.
5. En la instancia n8n, actualizar el valor del header en cada nodo (ver tabla) y **publicar**
   cada workflow:
   ```
   docker exec box-crossfit-n8n-1 n8n publish:workflow --id=<workflow-id>
   docker restart box-crossfit-n8n-1     # los cambios de publish requieren reinicio
   ```
   (alternativa manual: UI de n8n → abrir cada workflow → nodo HTTP Request → editar el valor
   del header `X-N8N-API-Key` → Save).
6. Verificar: `POST http://localhost:8001/api/v1/kpis/populate/daily` con `X-N8N-API-Key` nueva
   → **200**; con la vieja → **401**.
7. Revisar que las claves viejas ya no estén en el working tree:
   `git grep -n "<clave-vieja>"` (debe devolver solo commits históricos, no archivos).

## Recomendado (pendiente)

- Migrar de header hardcodeado a **credencial HTTP Header Auth** en n8n (así el valor no viaja
  en los exports) y referenciarla con `{{ $credentials.n8nApiKey.value }}` o, con variables de
  entorno de n8n, `={{ $env.N8N_API_KEY }}`.
- El repo tiene sólo **7 de los 18** workflows de la instancia: además de los 6 de KPIs/ML
  se agregó `fidelizacion_y_retencion_prod.json` (cierre mensual de Asistencia + Hitos).
  Faltan `Mantenimiento Diario/Mensual` y los de alertas (`Urgencia`, `1. RENOVACIÓN`,
  `INACTIVIDAD`, `ÚLTIMO CRÉDITO`, `SIN CRÉDITOS`). Exportarlos y sanitizarlos igual.
- Revisar workflows inactivos/duplicados de la instancia: `My workflow` (apunta al puerto 8000,
  obsoleto), `"Fidelización y Retención Mensual"` (vacío, sin nodos) y `"Renovación"`
  (duplicado del activo `1. RENOVACIÓN`).
- `Reentrenar Modelo ML` reentrena sólo `churn` + `forecast`; **la segmentación K-Means
  (arquetipos) no la reentrena ningún workflow** → hoy es manual
  (`POST /api/v1/segmentacion/reentrenar`).
