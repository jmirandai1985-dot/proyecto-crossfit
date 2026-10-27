# REPORTE DE SESIÓN — SMTP, mantenimiento/crons, referidos/tramos y 5 flujos k6

**Fecha:** 2026-10-26
**Rama:** `main` (working tree limpio al inicio: `git status --porcelain` sin salida)
**Alcance de la sesión:** investigación **sólo lectura** del backend, los scripts de
mantenimiento y el arnés de carga. **No se modificó código de producción, no se
ejecutaron tests (`run_tests.bat` no se corrió), no se tocó PROD ni
`carpeta_respaldo_box`, y no hay commits ni push.**
**Archivos nuevos de esta sesión:** este reporte, 5 escenarios k6 en `k6-tests/` y
`k6-tests/FLUJOS_NUEVOS.md` (todos *untracked*, ninguno commiteado).

---

## RESUMEN EJECUTIVO

| # | Tema | Estado verificado | Hallazgo principal | Acción propuesta |
|---|------|-------------------|--------------------|------------------|
| 1 | SMTP (`email_service.py`) | Funciona, pero frágil | 1 conexión + 1 login por correo, sin `timeout` y sin reintento; 2 correos síncronos dentro del request de registro | 4 fixes candidatos (sección 1) |
| 2 | Deuda técnica | 2 ítems concretos | `pendiente_activacion` ya no se escribe pero sigue ramificando el panel; arnés k6 no reproducible (falta el generador y los verificadores) | Sección 2 |
| 3 | Mantenimiento / crons | Diseño sano, **estado no verificable desde el repo** | `render.yaml` deja los Cron Jobs **fuera** del blueprint: se crean a mano en el dashboard; el `crontab` del repo es del contenedor **local** y sólo respalda TEST | Checklist de verificación en Render (sección 3) |
| 4 | Referidos: activación en PROD | Cadena completa (Fases 1-5) **ya implementada** | Sin fila en `configuracion_referidos` no se aplica **ningún** descuento; el registro con `token_invitacion` **no** crea el referido `pendiente` | Backfill + hook de registro (sección 4) |
| 5 | Referidos: "tramos" | **Ya existen** como `promociones_referidos` (Fase 5) | Crear una tabla `tramos_referido` **duplicaría el motor de premios**; lo único que falta es el tramo *vitalicio* (hoy `periodo` sólo admite `mensual`) | Diseño de migración `060` sin tabla nueva (sección 5) |
| 6 | k6: 5 flujos nuevos | Endpoints identificados y verificados | Faltan flujos de check-in QR, WOD masivo, entrega de Bazar por código, embudo de referidos y lecturas de panel admin | 5 escenarios redactados (sección 6) |

**Correcciones a supuestos previos de la sesión** (quedan registradas porque cambian
conclusiones):

1. **`scheduler.py` SÍ usa `CronTrigger`** (import en `app/services/scheduler.py:13`,
   triggers en `:160-200`). No es un scheduler "sin cron": son 10 jobs con
   `CronTrigger` + heartbeat por `interval`, con `SCHEDULER_ENABLED` como interruptor
   y lock de líder.
2. **`configuracion_referidos` SÍ existe** (modelo `app/models/referidos.py:259`,
   tabla creada en `alembic/versions/051_referidos_invitaciones.py`), igual que el
   motor de descuentos (`referidos_service.confirmar_compra`) y su enganche real en
   los dos puntos de cobro. Lo que falta **no es código**: es **dato/configuración**
   en PROD y un hueco de embudo en el registro.
3. **Los tramos por volumen ya están implementados completos** (tablas `053`,
   servicio `promociones_referidos_service`, 8 endpoints, detección diaria 23:55 y
   confirmación manual del admin). Por eso la sección 5 **no** propone un modelo
   nuevo paralelo.
4. **El mantenimiento NO corre dentro de la app**: se eliminó de `scheduler.py` el
   21/08/2026 (`backend/maintenance/README.md:5-8`) y vive en Cron Jobs de Render
   con una imagen aparte (`backend/Dockerfile.cron`).
5. **El ingreso financiero sí usa el precio FINAL con descuento** en los dos caminos
   (`suscripciones.py:190-205` y `solicitudes_planes.py:461-470`). No es un bug: se
   verificó explícitamente para no reportar un falso positivo.

---

## 1. SMTP — diagnóstico y 4 fixes candidatos

### 1.1 Cómo funciona hoy (evidencia)

- **Un único embudo:** `_enviar()` en `backend/app/services/email_service.py:341`
  concentra los 21 envíos del sistema; `enviar_renderizado()` (`:435`) y
  `enviar_renderizado_con_id()` (`:447`) son envoltorios del mismo camino.
- **Una conexión + un login por correo, sin `timeout` ni reintento:**

  ```python
  # email_service.py:407-409
  with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
      server.login(usuario_smtp, clave_smtp)
      server.send_message(msg)
  ```

  No se pasa `timeout=`, así que `smtplib` usa el default global de socket
  (**bloqueante, sin límite**). Un `connect`/`login` colgado deja el hilo tomado.
- **Sin reintento:** cualquier excepción cae en `except Exception` (`:418`), se
  registra `fallido` en `notificaciones_enviadas` (`:425`) y devuelve `False`
  (`:432`). No hay backoff ni distinción entre error transitorio
  (`SMTPServerDisconnected`, `SMTPConnectError`, `socket.timeout`) y permanente
  (credenciales, `From` inválido).
- **Modo simulado:** `EMAIL_MODO=noop` (`:381-390`) no abre SMTP y registra
  `simulado`. En TEST no sale correo real: cualquier prueba de SMTP tiene que ser
  dirigida o con una casilla real.
- **Saneamiento de headers (precedente):** el `From` se sanea desde el fix del
  2026-09-26 (`:354-360`) porque un salto de línea pegado en la env var de Render
  hacía fallar el **100%** de los correos (107 filas `fallido` en PROD el 26/09).
- **Correos dentro del request:** `alumnos.py:291` manda el aviso al admin y, unas
  líneas más abajo, el correo con la contraseña temporal al lead — **2 conexiones
  SMTP síncronas por registro**, en el hilo del request (sin `BackgroundTasks`).
  `scheduler.py` sí lo hace fuera del event loop (`anyio.to_thread`, `:14`), pero
  sigue siendo 1 conexión por correo, en serie.
- **Estado global compartido:** `ULTIMO_ERROR_SMTP` (`:32`, escrito en `:420`) y
  `ULTIMO_ENVIO_ID` (`:362`, leído en `:459`) son **globales de módulo**. Con dos
  envíos concurrentes, `enviar_renderizado_con_id()` puede devolver el id de la
  fila de **otro** correo, y el panel admin muestra el error de **otro** envío.

### 1.2 Los 4 fixes candidatos (no aplicados)

| # | Fix | Dónde | Por qué | Cómo se valida |
|---|-----|-------|---------|----------------|
| **F1** | `timeout` explícito en la conexión (`SMTP_SSL(..., timeout=10)`) y tratar `socket.timeout` como error transitorio | `email_service.py:407` | Hoy un Gmail lento/bloqueado agota el threadpool de Starlette (40 hilos): 40 registros colgados = API sin atender | Test con `SMTP_SSL` monkeypatcheado que duerme > timeout: `_enviar` devuelve `False` en ≤ ~10 s y registra `fallido` |
| **F2** | Reutilizar **una** conexión para un lote (`_enviar_lote(destinatarios)`) + reintento con backoff (2 intentos sólo para errores transitorios) | nuevo helper en `email_service.py`, usado por `scheduler.py` (alertas) y `notificaciones_enviadas.py` | Los jobs de alertas mandan N correos seguidos: N logins son N oportunidades de fallar y el doble de latencia | Test con 3 destinatarios y un fake de `SMTP_SSL` que cuenta `login()`: 1 conexión, 1 login, 3 `send_message` |
| **F3** | Sacar el envío del path de request: `BackgroundTasks` en `registro_alumno_nuevo` y en los endpoints admin que mandan correo | `alumnos.py:291` y el bloque de credenciales; `fidelizacion.py:252`, `notificaciones_enviadas.py:178/187/335-387` | El registro ya está limitado a `5/hour/IP`: no hay razón para que la latencia del alta dependa de Gmail | Test de endpoint: el registro responde 201 con el servicio de correo parcheado para dormir 5 s (la respuesta no espera) |
| **F4** | Sanitizar PII en **todos** los handlers + eliminar los globales de estado | `app/core/logging.py:53-56`, `:73`, `:84-90`; `email_service.py:32/362` | `PIISanitizer` está en el *logger* raíz y en el handler de archivo. Los **filtros de un logger no se aplican a los records que suben por propagación** desde hijos (`uvicorn.email`, `uvicorn.alumnos`): sanitiza sólo el handler que tiene el filtro. El handler de Sentry (LoggingIntegration) **no lo tiene** ⇒ emails, RUT y teléfonos viajan a Sentry. Además los globales devuelven el error/id de otro envío bajo concurrencia | Test: loggear `"fallo a juan@x.cl"` con `logging.getLogger("uvicorn.email")` y verificar que llega `[EMAIL]` a un handler nuevo sin filtro propio; test de concurrencia para `enviar_renderizado_con_id` |

> **Prioridad sugerida:** F1 (disponibilidad) y F4 (Ley de datos que el propio
> módulo declara en su docstring) primero; F2 y F3 después. F3 es el que más
> simplifica: convierte el registro en lo que ya es — un alta con avisos
> best-effort.

---

## 2. Deuda técnica — 2 ítems

### TD-1 · `pendiente_activacion`: un estado que ya no se escribe pero sigue vivo

**Qué pasó:** el alta pública nace activa desde el Bloque 1 — `alumnos.py:208-222`
lo dice explícitamente (`estado="activo"`, `activo=True`,
`cambiar_password_al_login=True`). Pero medio sistema sigue ramificando por el
estado viejo:

| Consumidor | Línea | Efecto real |
|---|---|---|
| `GET /admin/pendientes/resumen` (campo `registros`) | `admin.py:56` (ruta), `:85` (cuenta), `:68` (doc) | Panel "Registros pendientes" **siempre vacío** en altas nuevas. Ojo: la ruta `GET /admin/registros` **no existe** — `registros` es un campo del resumen de pendientes |
| Listado/activación | `alumnos.py:353`, `:379`, `:409` | El endpoint de activación responde **409** si el usuario no está en `pendiente_activacion` (rama inalcanzable por el alta nueva) |
| `auth.py:100` | mensaje "Tu cuenta está pendiente de activación" | Texto muerto para altas nuevas |
| Esquemas y filtros | `schemas/usuario.py:34-35/51-52/74`, `usuarios.py:373` | El valor se acepta y se filtra, sugiriendo que existe |
| Frontend | `PanelRegistros.jsx:10`, `AlumnoFichaModal.jsx:80-84`, `Alumnos.jsx:26`, `Coaches.jsx:276-277`, `utils/alumnos.js:70-72` | Badge ámbar "Pendiente" y panel de aprobación que casi nunca aplican |

**Riesgo:** no es un bug funcional, es **ambigüedad operativa**: el admin ve una
pantalla de aprobación que ya no gobierna nada y un badge que puede aparecer en
datos históricos. Además, el guard 409 de activación es una trampa para un futuro
flujo de aprobación manual.
**Propuesta (no aplicada):** decidir el contrato — (a) si la aprobación manual
vuelve, que el alta escriba `pendiente_activacion`; (b) si no vuelve, dejar el
estado como **sólo lectura histórica**: no ofrecerlo en filtros de alta, mantener
el `GET` de registros pero con un texto "sólo altas anteriores a
`<fecha>`", y unificar el badge. Requiere tests de `test_*` de altas + panel.

### TD-2 · El arnés k6 no es reproducible desde el repo

Los escenarios **referencian** archivos que no están versionados:

| Referencia | Dónde | Estado real |
|---|---|---|
| `_seed_load_test.py` ("generado por…") | `k6-tests/lib/config.js:1`, `lib/tokens.js:1` | **No existe** en `k6-tests/` (ni en el repo) |
| `tokens.json` | `lib/tokens.js:3` (`open('../tokens.json')`) | **No existe**: cualquier escenario que importe `lib/tokens.js` falla al iniciar k6 |
| `_verificar_escenario_a/b/c/d.py` | comentarios de `scenario_a_registro.js:3`, `b_reservas.js:5`, `c_compra_plan.js:7`, `d_bazar.js:5` | **No existen** |
| `_verificar_escenario_f*.py`, `_verificar_escenario_e.py` | comentarios de `scenario_e_mix.js` / `f1` / `f2` | **No existen** |

Consecuencia: los invariantes que los escenarios declaran ("stock final == 0",
"pedidos == 30", "1 suscripción paga por solicitud") **no se pueden comprobar**
con lo que hay en git. Además `load_config.json` **sí** está versionado con un
`admin_token` JWT de TEST y `base_url: http://localhost:8000` — token caducado y
entorno local: sirve como plantilla, no como configuración ejecutable.
**Propuesta (no aplicada):** versionar `_seed_load_test.py` y los verificadores
(idempotentes, contra `DATABASE_URL` de TEST con guard `is_test_db_url`), y
`gitignore`ear `tokens.json` + `load_config.json` reales, dejando
`load_config.example.json` sin token.

---

## 3. Auditoría de mantenimiento y cron jobs

### 3.1 Los dos mecanismos, separados a propósito

| Mecanismo | Qué corre | Dónde se define | Estado |
|---|---|---|---|
| **APScheduler in-app** (`app/services/scheduler.py`) | Negocio: generación de clases (00:05), 5 alertas de email (06:00-10:00), cierre de mes (día 1 00:05), reentrenamiento de churn (lunes 04:30), detección de promociones de referidos (23:55) | Código: `CronTrigger` en `:160-200` + heartbeat `interval` en `:289`; arranca en `main.py:385-424` bajo `SCHEDULER_ENABLED` | Activo en el web service; **coordinado por lock de líder** (evita doble ejecución en deploy solapado) |
| **Cron Jobs de Render** (`backend/Dockerfile.cron`) | Infra: backup de PROD a R2, watchdog de frescura, drill de restore, mantenimiento de datos de PROD, KPIs/ML | **Fuera del blueprint** (`render.yaml:5`: "n8n y el cron de mantenimiento quedan FUERA de este blueprint"); se crean a mano | **No verificable desde el repo** |

El `scheduler.py` **ya no** ejecuta mantenimiento: se eliminó el 21/08/2026
(`maintenance/README.md:5-8`). Esa separación es correcta (infra aislada, sin
secretos de la app).

### 3.2 Inventario de jobs de infraestructura (según `Dockerfile.cron` + README)

| Job | Comando | Schedule (UTC) | Hora CLT | Env groups | Existe |
|---|---|---|---|---|---|
| Backup PROD → R2 | `python -m maintenance.backup_cloud` | `0 6 * * *` | 03:00 diario | `backups-prod` | **sí** (se llama `proyecto-crossfit`) |
| Watchdog de backups | `python -m maintenance.watchdog_backups` | `0 12 * * *` | 09:00 diario | `r2-lectura` + `alertas` | **por crear** |
| Restore drill | `python -m maintenance.restore_drill` | `0 13 1 * *` | 10:00 día 1 | `backups-prod` + `neon-api` + `alertas` | **por crear** |
| Mantenimiento de datos PROD | `python -m maintenance.mantenimiento_cloud` | (tabla propia, Fase 6) | días 1 y 15 | `mantenimiento-prod` + `alertas` | **por crear** |
| KPIs / ML | `python -m maintenance.kpis_cloud` | (Fase 8) | — | — | **por crear** |

**Nota de coherencia documental:** `maintenance/README.md:298` dice "quedan **2** por
crear", pero `:489-491` lista **3** y `Dockerfile.cron` documenta **5** comandos.
El README está desactualizado en ese punto (no en el procedimiento, que sí es
correcto).

### 3.3 Señales de robustez que sí están (no hay que rehacerlas)

- `Dockerfile.cron` **verifica en el build** que `pg_dump` sea 18.x
  (`pg_dump --version | grep -q " 18\."`): si PGDG cambia de major, **falla el
  build** en vez de fallar de noche contra el servidor 18 de Neon.
- `DRY_RUN=1` por defecto en la imagen: si alguien olvida la variable, el
  contenedor **no sube nada**.
- Exit codes diferenciados por job (backup 2/3/4/5 — watchdog 2/6/7 — drill
  2/8..13) y "correo = algo que revisar": un run verde **no** manda mail
  (`README.md:313-320`).
- `mantenimiento_cloud` tiene guardas de volumen (`MAX_VENCIDOS_PCT`,
  `MAX_HUERFANAS`, `MAX_CAMBIOS`, `MAX_CIERRE`, `MAX_PURGA`) antes de escribir.

### 3.4 Qué **no** se pudo verificar (y cómo cerrarlo)

`render.yaml` no declara los Cron Jobs, así que **su existencia, su schedule y su
última corrida viven sólo en el dashboard de Render**. Checklist read-only:

1. Render → **Cron Jobs**: ¿existen `proyecto-crossfit`, `box-crossfit-watchdog`,
   `box-crossfit-restore-drill`, `box-crossfit-mantenimiento-prod` (y el de KPIs)?
2. En cada uno: **Runs** de los últimos 7 días → verde/rojo, y comparar con el
   schedule esperado (03:00 / 09:00 CLT / día 1).
3. **Environment Groups**: `backups-prod`, `alertas`, `neon-api`, `r2-lectura`
   completos (una variable faltante = exit 2, run rojo).
4. Último objeto en R2 `daily/` con fecha < 36 h (si no, el watchdog debería haber
   alertado: si no alertó, el watchdog tampoco corre).
5. **Contenedor local** (`docker compose ps`): el `crontab` del repo
   (`maintenance/crontab`: diario 02:30, mensual día 1 03:00 CLT) respalda **TEST**
   en la laptop; `README.md:136-145` documenta la limitación — los días que la PC
   está apagada no hay backup de TEST, y ese contenedor **no** toca PROD.

> **Riesgo vivo:** si los Cron Jobs nuevos nunca se crearon, PROD tiene backup
> diario (el job viejo sí existe) pero **sin watchdog ni drill**: nadie se enteraría
> de un backup que dejó de subirse, ni se habría probado nunca una restauración.

---

## 4. Referidos — qué falta para que los descuentos se apliquen en PROD

### 4.1 La cadena ya está completa (Fases 1-5, código verificado)

```
código del alumno  →  invitación (link con token)  →  invitado se registra
   →  referido `pendiente`  →  primera compra PAGA del invitado
   →  confirmar_compra()  →  crédito del invitador + descuento del invitado
   →  se cobra el precio FINAL  →  ingreso financiero por el precio FINAL
```

| Pieza | Dónde | Estado |
|---|---|---|
| Código por alumno (`codigos_referido`, 8 chars sin ambigüedad) | `models/referidos.py:150-200`; `GET /referidos/mi-codigo` | OK |
| Invitación con token + envío por email | `POST /referidos/invitar`, `referidos.py:300-341` | OK |
| Registro con `token_invitacion` | `alumnos.py:192-234` | **parcial** (ver gap B) |
| Validación de código del invitado | `POST /referidos/validar-codigo` | OK |
| Premio al confirmar compra | `services/referidos_service.py:543+`; `confirmar_compra()` | OK, **pero** requiere config (gap A) |
| Enganche en los **dos** cobros | `suscripciones.py:160-205` y `solicitudes_planes.py:434-470` | OK |
| Ledger con precio final | `suscripciones.py:190-205`; `solicitudes_planes.py:461-470` | **verificado: correcto** (no es bug) |
| Trinquete anti-abuso | `es_primera_compra_pagada` (`referidos_service.py:451-473`) ignora planes de precio 0 | OK |
| Panel admin (config, listado, marcar pagado) | `referidos.py:344-385` + `PUT /configuracion` | OK |

### 4.2 Los 4 huecos reales (en orden de impacto)

**A · Sin fila en `configuracion_referidos` no hay descuentos (bloqueante).**
`referidos_service._configuracion_activa()` (`:476`) devuelve `None` y
`confirmar_compra()` sale sin hacer nada (`:543-545`). La migración
`051_referidos_invitaciones.py` **crea la tabla y nada más**: no siembra fila.
`GET /referidos/configuracion` es honesto (`configurada: false`, defaults sin crear
la fila, `referidos.py:344-353`), pero nada obliga a crear la fila.
*Fix (dato, no código):* `PUT /api/v1/referidos/configuracion` con el admin del
tenant (upsert idempotente, `:356-385`), o backfill SQL idempotente:

```sql
INSERT INTO configuracion_referidos
    (tenant_id, porcentaje_descuento_invitado, porcentaje_descuento_invitador, activo)
SELECT t.id, 10, 10, TRUE          -- valores a decidir por el box
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM configuracion_referidos c WHERE c.tenant_id = t.id);
```

**B · El registro con `token_invitacion` no crea el referido `pendiente` (fuga de
embudo).** El alta **sí** liga la invitación a la cuenta nueva
(`marcar_invitacion_registrada`, `alumnos.py:230-234`), y por eso
`GET /referidos/mi-invitacion` devuelve el código del invitador para **prellenar**
la compra. Pero el `ReferidoAplicado` en estado `pendiente` sólo nace con
`POST /referidos/validar-codigo` **estando logueado** (`referidos.py:185-193`).
No aplicar el descuento en silencio es una decisión **deliberada y correcta**
(docstring de `mi-invitacion`, `:204-211`); lo que se pierde es la **intención**:
si el invitado compra sin pasar por la pantalla que llama a `validar-codigo`,
quien lo invitó **nunca** gana crédito.
*Fix (código):* al registrar con token válido, crear el `pendiente` en la misma
transacción (reutilizando el helper de `validar-codigo`), **sin tocar precios** —
el descuento sigue materializándose sólo en `confirmar_compra()`, así que la
garantía de "no se aplica solo" se conserva. Test: alta con token → 1 fila
`pendiente` y 0 cambios de precio.

**C · Alumnos históricos sin código.** `models/referidos.py:180-182` documenta que
**no** se hizo backfill: `GET /mi-codigo` responde **404** para todo alumno
anterior a la Fase 2, así que no pueden invitar. *Fix:* job de backfill idempotente
(`INSERT ... SELECT` con `ON CONFLICT DO NOTHING` sobre el generador de código) o
generación perezosa en `GET /mi-codigo`.

**D · Riesgo silencioso en `es_primera_compra_pagada`.** El trinquete
(`referidos_service.py:540-542`) descarta precios no positivos para que el plan
Prueba y el Pase de regreso no cuenten como "primera compra pagada". El riesgo es
simétrico: si en algún tenant el plan de prueba se cargó con precio mayor que 0,
**nadie** tendría "primera compra pagada" y los descuentos no se aplicarían nunca,
sin ningún error visible. *Verificación:* consultar precios de los planes de prueba
por tenant antes de activar.

---

## 5. "Tramos" de referidos — qué existe, qué falta y cómo modelarlo

### 5.1 Lo que ya existe (y por qué **no** hay que crear `tramos_referido`)

`promociones_referidos` (migración `053`, modelo `models/referidos.py:337-370`)
**ya es** un motor de tramos por volumen:

| Campo | Semántica |
|---|---|
| `umbral_referidos_convertidos` | N referidos convertidos (CHECK `> 0`) |
| `periodo` | `SQLEnum(PeriodoPromocion)` — hoy **sólo** `mensual` (`:75-78`) |
| `tipo_premio` | `mes_gratis` \| `descuento_extra` \| `dias_gratis` (`:81-89`) |
| `valor_premio` | días o % según el tipo (NULL para `mes_gratis`) |
| `activo` | permite apagar un tramo sin borrar historial |

Y el flujo completo está implementado:
`generar_detecciones()` (`promociones_referidos_service.py:170-211`) evalúa
**todas** las promociones activas en **una** consulta agrupada por
(promoción, alumno) con `HAVING count >= umbral`; inserta
`promociones_referidos_detectadas` con **snapshot** del premio y
`UNIQUE (promocion_id, usuario_id, periodo_cumplido)` (`:416-417`) hace la
detección idempotente. El admin confirma o rechaza, y la confirmación crea el
`CreditoReferido` (`UNIQUE promocion_detectada_id`, `:484`) o extiende la
suscripción. Corre a las 23:55 por `CronTrigger` del scheduler.

**Consecuencia:** una escalera mensual (3 → 6 → 10 referidos) se configura **hoy**
creando 3 filas con umbrales crecientes. Si un alumno salta de 2 a 7 en un mes, se
detectan **dos** tramos (6 y 10 no; 3 y 6 sí) en la misma corrida: el panel debe
mostrar **varias** pendientes, no una.

**Por qué descartar una tabla nueva `tramos_referido`:**

1. Duplicaría el motor de premios: habría dos caminos para crear
   `creditos_referido` y para extender suscripciones.
2. Rompería el invariante documentado en `053` (un único punto de otorgamiento,
   con `UNIQUE promocion_detectada_id` como candado anti-doble-premio).
3. Obligaría a duplicar la UI de confirmación, las notificaciones y la idempotencia
   ya probadas.

### 5.2 Lo único que **no** se puede hacer hoy: tramos vitalicios o mixtos

Tres límites concretos en el esquema, no en la lógica:

1. `PeriodoPromocion` sólo tiene `mensual` (el docstring `:76-77` lo declara como
   punto de extensión previsto).
2. La detección **filtra** `periodo == mensual` (`promociones_referidos_service.py:204`)
   y siempre acota por `rango_periodo(periodo)` (`:190`).
3. `promociones_referidos_detectadas.periodo_cumplido` es `String(7)` con
   `CHECK ~ '^\d{4}-(0[1-9]|1[0-2])$'` (`:395-420`): no cabe un marcador de
   "histórico".

### 5.3 Diseño recomendado — migración `060` (Opción A, sin tabla nueva)

**Objetivo:** permitir tramos por volumen **vitalicio** ("10 referidos en total
→ mes gratis") conviviendo con los mensuales, sin tocar el camino de otorgamiento.

```python
# backend/alembic/versions/060_tramos_historicos_referidos.py
revision = "060_tramos_historicos_referidos"
down_revision = "059_..."   # ← el head real al momento de aplicarla


def upgrade() -> None:
    # 1) Nuevo valor del enum. ADD VALUE no puede usarse en la MISMA transacción
    #    que lo crea (PG < 12 ni siquiera lo permite): bloque autocommit aparte.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE periodo_promocion ADD VALUE IF NOT EXISTS 'historico'")

    # 2) periodo_cumplido: de YYYY-MM a algo que quepa 'historico' (9 chars).
    op.alter_column("promociones_referidos_detectadas", "periodo_cumplido",
                    type_=sa.String(16), existing_type=sa.String(7),
                    existing_nullable=False)
    op.drop_constraint("ck_promociones_referidos_detectadas_periodo_formato",
                       "promociones_referidos_detectadas", type_="check")
    op.create_check_constraint(
        "ck_promociones_referidos_detectadas_periodo_formato",
        "promociones_referidos_detectadas",
        r"periodo_cumplido ~ '^\d{4}-(0[1-9]|1[0-2])$' OR periodo_cumplido = 'historico'",
    )


def downgrade() -> None:
    # Sólo es reversible si no hay filas 'historico' (si las hay, falla a propósito).
    op.execute("DELETE FROM promociones_referidos_detectadas "
               "WHERE periodo_cumplido = 'historico'")
    op.drop_constraint("ck_promociones_referidos_detectadas_periodo_formato",
                       "promociones_referidos_detectadas", type_="check")
    op.create_check_constraint(
        "ck_promociones_referidos_detectadas_periodo_formato",
        "promociones_referidos_detectadas",
        r"periodo_cumplido ~ '^\d{4}-(0[1-9]|1[0-2])$'",
    )
    op.alter_column("promociones_referidos_detectadas", "periodo_cumplido",
                    type_=sa.String(7), existing_type=sa.String(16),
                    existing_nullable=False)
    # El valor del enum NO se elimina: PostgreSQL no soporta DROP VALUE.
```

**Cambios de código que acompañan a la migración (2 PRs, no uno):**

| PR | Contenido | Riesgo |
|---|---|---|
| **060-A (esquema, neutro)** | La migración de arriba + `historico = "historico"` en `PeriodoPromocion` (`models/referidos.py:75-78`). Sin cambios de comportamiento: nada crea filas `historico` todavía | Casi nulo; reversible salvo que ya existan filas `historico` |
| **060-B (servicio + API)** | (1) `_rango_para(periodo, momento)` en `promociones_referidos_service`: si es `historico` → `desde=None, hasta=momento`, y `periodo_cumplido="historico"`; (2) quitar el filtro `periodo == mensual` (`:204`) y agrupar por `(promocion, alumno)` usando el `periodo` de cada fila; (3) validar en `PromocionReferidosCreate` que `periodo='historico'` no lleve `tipo_premio='descuento_extra'` (un % vitalicio se acumularía sin techo) o limitarlo a `mes_gratis`/`dias_gratis`; (4) exponer `periodo` en el listado del panel | Medio: toca la consulta que otorga premios → tests de detección (idempotencia, salto de tramo, promo inactiva, tenant cruzado) antes de tocar PROD |

**Alternativas evaluadas y descartadas:**

- **B · Tabla `tramos_referido`** con su propio motor: descartada (5.1).
- **C · Guardar `periodo` como `VARCHAR + CHECK`** en lugar del enum nativo:
  más flexible a futuro, pero exigiría migrar un enum en uso con
  `USING periodo::text` y reescribir el modelo. Sólo vale la pena si se prevén
  muchos períodos nuevos (semanal, trimestral, anual); con `historico` basta.
- **D · Un `grupo_escalera` (int) en `promociones_referidos`** para agrupar los
  tramos en la UI: opcional, **no** cambia la lógica de premios. Si el panel va a
  mostrar "Escalera Bronce/Plata/Oro", es una `060-C` de una sola columna nullable.

**Invariante que hay que preservar sí o sí:** el premio se otorga **sólo** por
`promociones_referidos_detectadas` → `creditos_referido` / extensión de
suscripción. Cualquier tramo nuevo debe pasar por ese camino para que sigan
valiendo los candados `UNIQUE (promocion_id, usuario_id, periodo_cumplido)` y
`UNIQUE (promocion_detectada_id)`.

---

## 6. k6 — los 5 flujos nuevos: endpoints confirmados

Estado del arnés: ver TD-2 (falta `tokens.json`, `_seed_load_test.py` y los
verificadores). Los 5 escenarios quedaron redactados en `k6-tests/` (ver
`k6-tests/FLUJOS_NUEVOS.md` para prerrequisitos de seed); **no se ejecutaron**.

Todos usan los helpers existentes (`lib/config.js`: `BASE_URL`, `jsonHeaders`,
`thinkTime`; `lib/tokens.js`: `tokensAlumno`, `tokensAdmin`) y los mismos
`thresholds` que los escenarios actuales (`http_req_duration p95 < 800 ms`,
`http_req_failed rate < 0.01`).

| # | Flujo | Endpoints (verificados) | Auth | Notas de límite/estado |
|---|---|---|---|---|
| **G1 · Check-in QR** | `POST /api/v1/asistencia/qr/{public_id}/check-in` (`asistencia.py:787`) | `get_current_user` + rol `alumno` (403 si no) | 200 con `estado ∈ {marcado, ya_marcado, ambiguo, sin_reserva}` — **no** son códigos de error; 404 si `public_id` no existe, 403 si es de otro box; `@limiter.limit("30/minute")` por IP; exige reserva dentro de `[hora_inicio-60min, hora_fin)` |
| **G2 · WOD masivo** | `POST /api/v1/wods/` (`wods.py:718`) y `POST /api/v1/wods/batch-create` (`:1199`) | `get_current_coach` | El coach **debe** mandar `?disciplina_id=` (400 si falta) y tener la disciplina asignada; admin bypass. **No hay 409 por fecha duplicada**: el alta simple no valida duplicados; sólo `batch-create` rechaza fechas repetidas en el body (**400**) y es atómico. Prefijo propio `/api/v1/wods` |
| **G3 · Bazar: entrega por código** | `POST /api/v1/pedidos/entregar` (`:724`) y `POST /api/v1/pedidos/{pedido_id}/rechazar` (`:549`) | coach/admin (entregar) · admin (rechazar) | Entregar lleva body `{codigo}` de 4 símbolos (**no** id): 404 código inexistente, **409** si ya se entregó o no es entregable, `LIMIT_CODIGO_RETIRO` = 10/min. Rechazar: **400** si el pedido no está `pendiente` y devuelve stock con `with_for_update` (`:587-596`). El código nace en `PUT /{id}/estado` |
| **G4 · Embudo de referidos** | `GET /referidos/mi-codigo` → `POST /referidos/invitaciones` (201) → `GET /referidos/mi-invitacion` → `POST /referidos/validar-codigo` | alumno (`_exigir_alumno` → 403 si admin/coach) | **Sin** `@limiter` de slowapi, pero límites de negocio **por alumno**: 5 invitaciones/día → **429**; mismo correo en 7 días → 400; correo propio o ya usuario → 400; si SMTP falla se borra la invitación y responde **502**. `validar-codigo`: 400 con motivo exacto y serializa por `with_for_update` |
| **G5 · Lecturas de panel** | `GET /api/v1/kpis/{diario,mensual,cohortes,churn,financiero}` (`kpis.py:375/409/1116/679/919`), `GET /api/v1/admin/pendientes/resumen` (`admin.py:56`), `GET /api/v1/pedidos?estado=pendiente`, `GET /api/v1/historial-rm?alumno_id=` (`historial_rm.py:307`) | admin | **No existe** `/admin/registros` (es un campo del resumen de pendientes), ni `/kpis/dashboard` ni `/historial-rm/{alumno_id}`: el detalle por alumno es `/historial-rm/alumnos/{alumno_id}/rms` (`:396`). Sólo lectura, sin seed nuevo; es el flujo que detecta N+1 y consultas sin índice |

**Hallazgo relevante para G4:** `POST /referidos/invitaciones` manda correo
**sincrónico** (`referidos.py:235-341` → `email_service`) y **no** tiene rate limit
por IP: sólo el tope de negocio de 5/día **por alumno**. Un escenario con N alumnos
distintos abre N conexiones SMTP en paralelo — es la mejor prueba de estrés posible
para F1/F2 de la sección 1, y la razón para correrlo con `EMAIL_MODO=noop` hasta
que esos fixes estén aplicados.

**Hallazgo relevante para G3:** el invariante de stock (`stock_final == 0` en
`scenario_d_bazar.js`) sólo tiene sentido si el verificador existe: hoy no está
versionado (TD-2). Sin él, el escenario mide latencia, no corrección.

**Hallazgo relevante para G1:** como el check-in QR responde **200** con un
`estado` de negocio, un escenario mal escrito pasaría con `http_req_failed = 0`
aunque el 100% de los check-ins cayeran en `sin_reserva`. Hay que contar
`estado === 'marcado'` explícitamente en un `Counter` propio.

---

## 7. Próximos pasos priorizados (nada de esto se ejecutó)

| # | Acción | Tipo | Esfuerzo | Riesgo | Depende de |
|---|---|---|---|---|---|
| 1 | Verificar en el dashboard de Render los 5 Cron Jobs y sus últimas corridas (checklist 3.4) | Operación | 15 min | Ninguno | Acceso a Render |
| 2 | Activar referidos en PROD: `PUT /referidos/configuracion` por tenant (gap A) + revisar precios de planes de prueba (gap D) | Operación | 10 min | Bajo, reversible | Acceso admin |
| 3 | Fix F1 (`timeout=10`) + F4 (filtros en todos los handlers, `contextvars`) | Código | ½ día | Bajo | — |
| 4 | Hook de alta: crear referido `pendiente` con `token_invitacion` (gap B) | Código | ½ día | Bajo | 2 |
| 5 | Versionar `_seed_load_test.py`, verificadores y `load_config.example.json` (TD-2) | Código/infra | 1 día | Bajo | — |
| 6 | Migración `060-A` (enum `historico` + `periodo_cumplido` 16 chars) | Esquema | ½ día | Bajo (neutro) | Revisión de head real |
| 7 | `060-B` detección histórica + validaciones de promoción | Código | 1-2 días | Medio | 6 |
| 8 | Decidir contrato de `pendiente_activacion` (TD-1) | Producto + código | 1 día | Bajo | — |
| 9 | F2 (lote SMTP) + F3 (`BackgroundTasks`) | Código | 1 día | Medio | 3 |
| 10 | Backfill de `codigos_referido` para alumnos históricos (gap C) | Script | 2 h | Bajo (idempotente) | 2 |

**Criterio de éxito por tema:** SMTP → un pico de 50 correos ya no bloquea el
threadpool ni filtra PII; mantenimiento → 7 días de runs verdes en Render con
watchdog enviando correo de prueba; referidos → una compra de prueba en TEST (con
`EMAIL_MODO=noop`) descuenta el % y deja `referidos_aplicados.convertido` +
`creditos_referido.pendiente`; tramos → un alumno con 10 conversiones históricas
genera **una** detección `historico` confirmable por el admin.

---

## Anexo · Trazabilidad de esta auditoría

- **Método:** lectura de código y migraciones en `main`, sin ejecutar la app ni la
  base. Cada afirmación de este reporte está anclada a `archivo:línea`; donde no se
  pudo verificar (estado de los Cron Jobs en Render, datos de PROD) se dice
  explícitamente y se propone cómo verificarlo.
- **No se modificó** ningún archivo de `backend/`, `frontend/` ni `maintenance/`.
- **No se ejecutaron** tests, migraciones, scripts de mantenimiento ni escenarios
  k6; **no se hizo commit ni push**; **no se accedió a PROD ni a
  `carpeta_respaldo_box`**.
- **Artefactos nuevos (untracked):**
  `REPORTE_SESION_MANTENIMIENTO.md`, `k6-tests/scenario_g1_checkin_qr.js`,
  `k6-tests/scenario_g2_wods_masivo.js`, `k6-tests/scenario_g3_bazar_entrega.js`,
  `k6-tests/scenario_g4_referidos_embudo.js`, `k6-tests/scenario_g5_panel_admin.js`
  y `k6-tests/FLUJOS_NUEVOS.md`.







