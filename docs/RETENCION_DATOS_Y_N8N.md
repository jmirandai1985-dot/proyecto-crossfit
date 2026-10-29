# Retención de datos (B8) y baja de n8n (B9) — diagnóstico y plan aprobable

> Estado: **B8 implementado el 2026-10-29, sin tocar PROD**; B9 **NO implementado a propósito**
> (2026-10-28). B8 ya tiene código, migración y tests (**59 unitarios + 9 de integración en TEST,
> todos en verde**), y se corre **sólo contra TEST y en `DRY_RUN`**: el Cron Job en Render está
> comentado a propósito (`render.yaml`, bloque *# 6-8)*)
> y el primer disparo real en PROD necesita autorización explícita. Lo que sigue del documento
> es el diagnóstico original, tal como se escribió; el mapa código↔plan está en
> `backend/maintenance/README.md` ("Fase 12") y `docs/CRON_JOBS_RENDER.md` §8.

## 1. B8 — Retención de datos

### 1.1 Lo que existe hoy (leído del código)

| Tabla | Fecha para cortar | Notas |
| --- | --- | --- |
| `asistencias` | `fecha` (`DATE`) | FK `usuario_id` CASCADE, FK `clase_id` sin acción |
| `reservas` | `fecha_reserva` (`timestamptz`) | la fecha de la CLASE vive en `clases.fecha`; `fecha_reserva` es la creación (criterio conservador) |
| `auditoria` | `fecha` (`timestamptz`) | `entidad`/`accion`/`detalle` JSON; índice por `fecha` ya existe |
| `usuarios.fecha_baja` | — | 46 bajas hoy; la columna ya existe y la usa el churn |

Jobs de mantenimiento existentes: `backend/maintenance/*.py` (Cron Jobs de Render,
`render.yaml`), APScheduler interno (`app/services/scheduler.py`, 10 jobs) y el patrón
`lock_de_job(...)` + correo de resumen. **Todos los jobs nuevos deben seguir ese
patrón** (`docs/CRON_JOBS_RENDER.md`).

### 1.2 Enfoque propuesto (recomendado)

**Archivar, no borrar** (tu propia preferencia, y es la correcta para BI/Data Science):

1. Migración `065_retencion_datos`:
   * `asistencias_archivo` / `reservas_archivo`: mismas columnas que el origen +
     `archivado_en timestamptz` + PK propia; **sin FKs** (un archivo histórico no
     debe impedir borrar un alumno ni una clase).
   * `usuarios.anonimizado_en timestamptz NULL` (marca para no re-anonimizar).
2. Job `retencion_archivar` (mensual, día 1, 03:30 CLT):
   * `WITH movidas AS (DELETE FROM asistencias WHERE fecha < :corte RETURNING ...)
     INSERT INTO asistencias_archivo SELECT ...` en LOTES (5.000 filas) para no
     bloquear la tabla; idem `reservas`.
   * Antes de mover, `pg_dump` **solo de esas filas** a R2 (`backups-prod`), con el
     mismo manifiesto/size-check que usa `maintenance/backup_cloud.py`.
   * `DRY_RUN=1` por defecto: sin la variable explícita en `0` sólo informa cuántas
     filas movería (mismo criterio que B4).
3. Job `retencion_auditoria` (mensual): `DELETE FROM auditoria WHERE fecha < now() -
   interval '2 years'` en lotes, con el conteo en el correo de resumen.
4. Job `retencion_anonimizar` (mensual, después de los anteriores):
   * Candidatos: `usuarios` con `fecha_baja <= now() - interval '12 months'` y
     `anonimizado_en IS NULL` (incluye las ~46 bajas actuales en la primera corrida).
   * Reemplazo: `nombre = 'Alumno anonimizado <id>'`, `correo =
     'anonimo+<id>@anonimizado.invalid'`, `telefono = NULL`. El `rut` **se conserva**
     (no identifica sin los otros tres y es único; cambiarlo rompe la unicidad del
     negocio) salvo que prefieras `ANON-<id>`.
   * Se conservan fechas, montos, asistencias y conteos: las estadísticas no cambian.
   * **Nunca** toca usuarios con `fecha_baja IS NULL` ni staff.

### 1.3 Por qué no lo implementé en esta sesión

* El punto 2 (archivo/borrado) y el 4 (anonimización) son **irreversibles**. Tu
  instrucción fue proponer el enfoque antes de implementar y no asumir borrado.
* Hay dos decisiones que cambian el resultado y no puedo tomar por vos:
  1. ¿`asistencias`/`reservas` se **mueven** (quedan fuera de la tabla operativa) o
     se **copian** y se dejan (doble almacenamiento, consultas históricas sin tocar
     código)? Mover es lo que pediste ("archivar/eliminar de la tabla operativa"),
     pero rompe cualquier consulta que hoy lea más de 5 años.
  2. ¿El `rut` anonimizado se conserva o se reemplaza?
* El primer disparo en PROD necesita tu autorización explícita (igual que B3).

## 2. B9 — n8n fuera de producción

### 2.1 Lo que hay (verificado)

* `n8n/workflows/` está **VACÍO**: los 9 JSON que había se borraron en `017bd65`
  (2026-10-02) y nunca se versionaron los 18 de la instancia.
* El contenedor local `box-crossfit-n8n-1` está `Exited` hace semanas y la instancia
  de PROD es externa: **no hay forma de exportar los 18 workflows desde este equipo**
  (ni el JSON ni el panel).
* Todo lo que la instancia hacía tiene hoy un reemplazo en el repo (tabla 2.2).

### 2.2 Tabla de equivalencia

| Workflow (instancia) | Qué hacía | Qué lo reemplaza hoy | Estado |
| --- | --- | --- | --- |
| `fidelizacion y retencion` | cierre mensual: cumplimiento, acompañamiento, hitos, reactivación | `job_cierre_mes` (APScheduler, día 1 00:05 CLT) → `asistencia_service.evaluar_mes` | **Migrado** (el endpoint n8n se borró en `017bd65`) |
| `1. RENOVACIÓN` | correo de renovación (3 días) | `job_alerta_renovacion` (08:00 CLT) → `alertas_email_service` | **Migrado** |
| `Urgencia` | correo de vencimiento HOY | `job_alerta_urgencia_renovacion` (06:00 CLT) | **Migrado** |
| `INACTIVIDAD` | 7+ días sin asistencia | `job_alerta_inactividad` (09:00 CLT) | **Migrado** |
| `ÚLTIMO CRÉDITO` | 1 crédito restante | `job_alerta_ultimo_credito` (07:00 CLT) | **Migrado** |
| `SIN CRÉDITOS` | 0 créditos | `job_alerta_sin_creditos` (10:00 CLT) | **Migrado** |
| `Populate Daily KPIs` / `[PROD]` | KPIs diarios | `maintenance/kpis_cloud.py` (Render `box-crossfit-kpis-ml`, 10:00 UTC) | **Migrado** |
| `Populate Monthly KPIs` / `[PROD]` | KPIs mensuales (día 1) | idem (decide por fecha de Chile) | **Migrado** |
| `Populate Predictions` / `[PROD]` | forecast/churn | idem + `job_reentrenar_churn` (lunes 04:30 CLT) | **Migrado** |
| `Reentrenar Modelo ML` | churn + forecast | idem (la **segmentación K-Means sigue manual**: `POST /segmentacion/reentrenar`) | **Parcial** |
| `Mantenimiento Diario` / `Mensual` | limpieza/consistencia de datos | `maintenance/mantenimiento_cloud.py` (Render, días 1 y 15) | **Migrado** |
| `My workflow` (puerto 8000) | prueba obsoleta | — | **Descartado** |
| `Fidelización y Retención Mensual` | vacío, sin nodos | — | **Descartado** |
| `Renovación` | duplicado de `1. RENOVACIÓN` | `job_alerta_renovacion` | **Descartado (duplicado)** |

**Conclusión:** no hace falta crear ningún Cron Job nuevo de Render para B9. Lo que
falta es (a) archivar los JSON como respaldo histórico y (b) apagar la instancia.

### 2.3 Bloqueo concreto y qué necesito

Para cumplir el punto 4 del encargo (exportar los 18 JSON a `n8n/workflows/`) hace
falta **una de estas dos cosas**:

1. Levantar la instancia de n8n unas horas y correr
   `n8n export:workflow --all --output=...`, sanear `X-N8N-API-Key`
   (`REPLACE_WITH_YOUR_KEY`) y versionarlos; o
2. Un backup/export de la instancia (volumen `n8n_data` o el JSON ya exportado).

Sin eso, cualquier archivo que ponga en `n8n/workflows/` sería inventado. Mientras
tanto queda constancia en `n8n/README.md` de que n8n está dado de baja y la tabla de
equivalencia está en 2.2.

### 2.4 Qué falta para cerrar B9

- [ ] Export real de los 18 workflows (bloqueado por 2.3).
- [ ] Apagar/eliminar la instancia de PROD (acción del usuario en su hosting).
- [ ] Confirmar que `N8N_API_KEY` ya no hace falta en Render (el backend acepta
      `CRON_API_KEY` para los endpoints de cron).
- [ ] (Opcional) Cron Job para reentrenar la segmentación K-Means, hoy manual.

