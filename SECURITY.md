# SECURITY.md — Checklist de hardening de seguridad

- **Fecha:** 18/08/2026
- **Base:** `AUDIT.md` (misma sesión). El repo ya traía 2 commits de seguridad (`6b99e4a`, `f8d30a1`) con rate limiting, CORS, headers, IDOR parciales, sanitización PII y Sentry.
- **Criterio de este documento:** ✅ implementado · ⚠️ parcial · ❌ no implementado. Para lo pendiente se da **commit/PR concreto**. Los fixes que implican **cambio de esquema de BD o breaking change de API** están marcados como **⛔ REQUIERE CONFIRMACIÓN** (no ejecutados).

---

## 1. Resumen ejecutivo

| Área | Estado general |
|---|---|
| Autenticación y sesión | ⚠️ bcrypt + JWT OK; falta refresh token, cookie httpOnly, invalidación de sesión |
| Autorización multi-tenant | ❌ Enforcement inconsistente (~90 endpoints toman `tenant_id` del cliente; varios sin auth) |
| Validación de entrada | ⚠️ Schemas Pydantic mayormente OK; `body: dict` en `/wods/batch`; uploads sin MIME real |
| API y transporte | ✅ CORS restringido + security headers + rate limiting global; CSP con `unsafe-inline` |
| Datos sensibles | ✅ `.env` gitignored + logs con PII sanitizada; ❌ sin encriptación en reposo de pagos |
| Frontend | ❌ JWT en `localStorage`; tenant hardcodeado; sin `dangerouslySetInnerHTML` (bien) |
| Infraestructura | ⚠️ Backups + rotación de credenciales existen; sin `npm audit`/`pip-audit` ejecutados (sin red en esta sesión); sin CI |

**Vulnerabilidades críticas encontradas (P0, priorizar):**
1. **PRs (historial-rm) sin autenticación**: `POST/PUT/DELETE` permiten crear/editar/borrar récords de cualquier alumno y tenant.
2. **IDOR en membresías y notificaciones**: `GET /membresias/mi-membresia`, `GET /planes/membresia-activa`, `GET /notificaciones*` exponen datos de cualquier `alumno_id`.
3. **`POST /auditoria` abierto**: cualquiera inyecta logs de auditoría falsos.
4. **`POST /solicitudes/solicitar` sin auth**: cualquiera crea solicitudes de plan (y sin aviso al admin).
5. **`tenant_id` desde el cliente con default `=1`**: permite leer/escribir datos de otro box cambiando el query param.
6. **JWT en `localStorage`** → exfiltrable por XSS.

---

## 2. Checklist por categoría

### 2.1 Autenticación y sesión

| Ítem | Estado | Evidencia / plan |
|---|---|---|
| Hash de passwords bcrypt/argon2 (nunca SHA) | ✅ | `core/security.py` (`CryptContext(schemes=["bcrypt"])`) + `usuarios.py` (bcrypt). Verificar que `bcrypt` esté declarado en requirements (hoy solo transitivo). |
| JWT con expiración corta | ⚠️ | `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60` por defecto, pero `.env.example` documenta `1440` (24h). **Plan:** bajar a 30–60 min en prod. |
| Refresh token rotativo | ❌ | No existe. ⛔ **REQUIERE CONFIRMACIÓN** (nuevo endpoint + tabla/columna para sesiones). |
| Token en cookie httpOnly/secure (no localStorage) | ❌ | `AuthContext.jsx` + `services/api.js` usan `localStorage`. ⛔ **REQUIERE CONFIRMACIÓN** (cambio en frontend + backend, y definición CSRF). |
| Rate limiting en login | ✅ | `auth.py`: `@limiter.limit(LIMIT_LOGIN)` (5/min por IP). |
| Invalidación de sesión al cambiar password | ❌ | `usuarios.py/cambiar-password` solo re-hashea. ⛔ **REQUIERE CONFIRMACIÓN** (token_version por usuario o denylist). |

### 2.2 Autorización multi-tenant

| Ítem | Estado | Evidencia / plan |
|---|---|---|
| Middleware/dependency que derive `tenant_id` del token | ❌ | `get_current_user` expone `tenant_id` del token, pero la mayoría de endpoints lo toman del query/path/body (`grep tenant_id` → ~90 ocurrencias; ~15 con default `=1`). |
| Ningún query cruza `box_id` por error | ❌ | `planes PUT/DELETE`, `solicitudes aprobar`, `notificaciones`, `auditoria`, `wods`, `clases`, `historial-rm` filtran por id sin `tenant_id` del token. |
| Enforcement de rol por endpoint | ⚠️ | Mutaciones admin/coach OK en la mayoría; **lecturas sensibles abiertas** (ver AUDIT.md §4.3). |
| RLS en PostgreSQL | ❌ | No hay policies RLS. ⛔ **REQUIERE CONFIRMACIÓN** (requiere rol de BD + SET app.tenant_id por conexión). |

### 2.3 Validación de entrada

| Ítem | Estado | Evidencia / plan |
|---|---|---|
| Schemas Pydantic estrictos | ⚠️ | `app/schemas/` existe; **excepciones:** `wods.py` POST `/batch` usa `body: dict`; varios schemas inline en routers (finanzas, configuracion, suscripciones, comprar_emergencia). |
| Uploads: MIME real (no solo extensión) | ❌ | `upload.py` valida **extensión**; `productos.py` valida `content_type` (spoofeable). ⚠️ **Fix seguro aplicado en esta sesión** (magic bytes) — ver §3. |
| Uploads: tamaño máximo | ✅ | 5 MB en `upload.py` y `productos.py`. |
| Uploads: escaneo / almacenamiento fuera de webroot | ❌ | Archivos en `app/static/uploads` (webroot). ⛔ **REQUIERE CONFIRMACIÓN** (mover a bucket con URLs firmadas = breaking). Mitigación intermedia: servir con `Content-Disposition` y deshabilitar ejecución. |
| SQL injection | ✅ | Sin f-strings en SQL dentro de `app/`; todo `text()` parametrizado. (Los scripts one-off de `backend/` raíz sí tienen f-strings, pero no corren en la API.) |

### 2.4 API y transporte

| Ítem | Estado | Evidencia / plan |
|---|---|---|
| CORS restringido | ✅ | `main.py` usa `settings.cors_origins_list` + `FRONTEND_URL` (nunca `*`). |
| HTTPS forzado (HSTS) | ✅ | `SecurityHeadersMiddleware`: `Strict-Transport-Security max-age=31536000`. |
| Headers de seguridad | ✅ | CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`. ⚠️ CSP usa `script-src 'unsafe-inline'` (Vite dev); en prod conviene hashes/nonce. |
| Rate limiting global y en endpoints sensibles | ⚠️ | Global vía slowapi + login/registro/críticos. **Faltan:** `upload/voucher`, `solicitudes/solicitar`, `reservas` POST. ⚠️ **Fix seguro aplicado en esta sesión** (rate limits en upload + solicitar) — ver §3. |

### 2.5 Datos sensibles

| Ítem | Estado | Evidencia / plan |
|---|---|---|
| Secrets en env, `.env` gitignored | ✅ | `.gitignore` raíz + `backend/.gitignore` + `frontend/.gitignore` cubren `.env`, `.env.test`, `.env.prod`; solo se trackea `.env.example` (verificado con `git ls-files`). |
| Sin secretos hardcodeados | ✅ | `security.py` bloquea placeholders conocidos y lanza si falta `JWT_SECRET_KEY`. |
| Encriptación en tránsito | ✅ | `DATABASE_URL` documenta `sslmode=require` (Neon); SMTP usa `starttls`. |
| Encriptación en reposo de datos de pago | ❌ | `transacciones_financieras` guarda montos/descripciones en claro; vouchers son imágenes en disco. ⛔ **REQUIERE CONFIRMACIÓN** (cifrado de columnas / bucket privado). |
| Logs de auditoría de acciones críticas | ⚠️ | Existe tabla `auditoria` + `auditoria_service.py`, pero **no se usa** en aprobación de vouchers, cambios de rol, edición de PRs ni ajustes de tokens; y el endpoint `POST /auditoria` está abierto (P0). |
| PII en logs | ✅ | `core/logging.py` sanitiza emails/RUT/teléfonos + rotación 5MB×5. |

### 2.6 Frontend

| Ítem | Estado | Evidencia / plan |
|---|---|---|
| Sanitización de contenido user-generated | ✅ | No se encontró `dangerouslySetInnerHTML`/`innerHTML` en `src/`. React escapa por defecto. |
| CSRF (si cookies para auth) | — | Hoy auth es Bearer en header → no aplica; **sí aplicará** si se migra a cookies (ver §2.1). |
| No exponer IDs/lógica sensible en bundle | ⚠️ | `services/api.js` expone `VITE_API_URL` fallback; `admin/Notificaciones.jsx` hardcodea `tenant_id=1`. ⚠️ **Fix seguro aplicado en esta sesión** (Notificaciones lee de AuthContext) — ver §3. |

### 2.7 Infraestructura

| Ítem | Estado | Evidencia / plan |
|---|---|---|
| `pip-audit` / `npm audit` | ❌ No ejecutado | `pip-audit` no está instalado; `npm audit` no completó (sin red/registry timeout en esta sesión). Comandos en §5. |
| Backups automáticos con retención | ⚠️ | `maintenance/backup_neon.py` + `run_daily.py`/`run_monthly.py`; `backups/` está vacío (no se han generado en el entorno local). Definir retención (ej. 14 daily / 6 monthly). |
| Separación de entornos | ⚠️ | `ENVIRONMENT` + `.env`/`.env.test` + guard de `conftest.py` (`/debug/db-url`). Falta config de staging explícita. |

## 3. Cambios aplicados en esta sesión (seguros, sin breaking changes)

| # | Archivo | Cambio | Por qué es seguro |
|---|---|---|---|
| 1 | `backend/app/api/v1/upload.py` | Validación de **magic bytes** (firma real del archivo) además de la extensión; rechazo 400 si no coincide. Solo stdlib. | Rechaza archivos con extensión falsa; no altera respuestas de archivos válidos. |
| 2 | `backend/app/api/v1/productos.py` | Ídem para imágenes de productos. | Rechaza imágenes cuyo `content_type` declarado no coincide con la firma real. |
| 3 | `backend/app/api/v1/upload.py` | Rate limit `LIMIT_CRITICO` en `POST /voucher`. | Añade `429` tras umbral; no cambia el contrato feliz. |
| 4 | `backend/app/api/v1/solicitudes_planes.py` | Rate limit `LIMIT_CRITICO` en `POST /solicitar`. | Ídem. |
| 5 | `frontend/src/pages/admin/Notificaciones.jsx` | Reemplaza `{ tenant_id: 1 }` hardcodeado por `useAuth()`. | Corrige el tenant real del box; si no hay session, usa `1` como fallback conservador. |

> Los hallazgos restantes (cookies, RLS, cifrado, refresh token) **no se implementaron** porque implican breaking changes de API o cambios de esquema → ver plan en §4. La Fase 1 (fix IDOR + tenant-hijacking) quedó implementada: ver §3.1.

---

## 3.1 FASE 1 — Fix de seguridad crítica (IDOR + tenant-hijacking) — 18/08/2026

### Resumen

Se aplicó la regla general en **13 routers**: `get_current_user` / `get_current_coach` / `get_current_admin` + `tenant_id` derivado del JWT. Los parámetros de query/body del cliente se **mantienen en la firma** (no se rompe el frontend) pero **se ignoran** y se sobreescriben internamente. Sin cambios de esquema de BD. Los `tenant_id: int = Query(1)` pasaron a `Query(None)` (si falta el token → 401, nunca se asume el tenant 1).

### Endpoints migrados en esta fase: 54 endpoint-funciones

| Router | Endpoints | Cambio |
|---|---|---|
| `historial-rm` | POST, GET `/{id}`, GET `""`, GET `/alumnos/{id}/rms`, PUT, DELETE, POST `/nivel-fuerza`, POST `/nivel-gimnastico`, GET `/alumnos/{id}/movimiento/{mid}`, GET `/nivel-general`, `/nivel-fuerza`, `/progreso-destacado`, `/nivel-gimnastico` **(13)** | Auth `get_current_user`; tenant del token; ownership (propio alumno o staff); **PUT con ventana de 24h** (`_verificar_ventana_edicion`); DELETE solo propio alumno o admin |
| `membresias` | GET `/mi-membresia` (1) | Auth; tenant y alumno del token (cierra IDOR del saldo de tokens) |
| `planes` | GET `""` (listar), GET `/membresia-activa` (2) | Auth; tenant/alumno del token |
| `notificaciones` | GET `""`, PUT `/{id}/leer`, PUT `/leer-todas` (3) | Auth; alumno del token; ownership al marcar leída |
| `auditoria` | POST `""` (1) | Rol **admin/coach**; tenant/usuario del token (cierra inyección de logs falsos) |
| `solicitudes` | POST `/solicitar` (1) | Auth; tenant del token; `alumno_id` = propio salvo staff (que además valida que el alumno destino sea del box) |
| `wods` | GET `/`, GET `/hoy`, GET `/{id}`, POST `/`, PUT `/{id}`, DELETE `/{id}`, POST `/clases/{c}/asignar-wod/{w}`, POST `/batch` (8) | Auth en GETs; tenant del token en todos (quitados `Query(1)`) |
| `movimientos` | GET `""`, GET `/{id}`, POST `""`, PUT `/{id}`, DELETE `/{id}` (5) | GETs auth; writes `get_current_coach`; tenant del token |
| `reservas` | POST `""`, PUT `/{id}/asistencia`, GET `/por-clase/{id}`, GET `/asistencia-semanal`, GET `/asistencia-mes`, GET `""`, GET `/{id}`, PUT `/{id}`, DELETE `/{id}` (9) | Auth; tenant del token; ownership en filtros `usuario_id`; `/por-clase` solo coach/admin |
| `clases` | GET `/`, GET `/{id}`, POST `/`, PUT `/{id}`, DELETE `/{id}` (5) | Auth en GETs; tenant del token en writes |
| `horarios` | GET `""`, GET `/grid-semanal` (2) | Auth; tenant del token |
| `disciplinas` | GET `/`, GET `/{id}` (2) | Auth; tenant del token (`obtener_disciplina` ahora filtra por tenant) |
| `productos` | GET `""`, GET `/{id}` (2) | Auth; tenant del token |

**Infraestructura nueva:** `app/middleware/tenant_audit.py` (registrado en `main.py`) — loguea en **warning** (path, método, IP) cada request donde `tenant_id` llegue como `None` o `1` desde query o body. Sin bloqueo; sirve para medir tráfico del patrón inseguro y priorizar la Fase 2.

### Pendientes documentados (Fase 2 / PROMPT 2)

- **≈36 endpoint-funciones** aún reciben `tenant_id` del cliente o siguen sin auth. Principales: `auditoria` GETs (4), `tenants` GETs (3), `fidelizacion` GETs (4), `retencion` GETs (4), `supervision` GETs (5), `planes` GET `/{plan_id}` (sin filtro tenant), `horarios` GET `/generar-clases-dia` y `/{id}`, `wods` POST `/parse`, `pedidos` GETs, `finanzas` (2), `suscripciones` (2), `configuracion` PUT, `usuarios`/`alumnos` (admin), `dashboard` GET `/{tenant_id}/ocupacion-hoy`.
- ⏳ **Notificación al coach por nuevo PR / cambio de nivel: PENDIENTE.** El mecanismo actual (`notificaciones`) está orientado a alumnos (destinatario = `alumno_id`, sin `tenant_id`, sin UI de coach). Requiere decisión (extender la tabla `notificaciones` = schema, o usar el email service existente). No se implementó por la restricción "no inventar un sistema nuevo / no cambiar schema".
- ⏳ **`POST /auditoria` como endpoint interno:** se protegió con rol admin/coach, pero se recomienda evaluar quitarlo de la API pública (el servicio `auditoria_service.py` ya registra internamente). Requiere confirmación.

### Validación tras los cambios

- `python -m compileall app` → **OK** · `import app.main` → **OK**.
- Verificación por inspección de dependencias de cada ruta: **todos los endpoints de Fase 1 quedan `SECURED`** (exigen token); los abiertos restantes son los listados en pendientes.
- Middleware probado en aislamiento: loguea `TENANT_AUDIT query|body tenant_id=None|1 METHOD path ip=...` y deja pasar el body aguas abajo.
- **Suite pytest NO ejecutable en este entorno:** `pytest` y `httpx` no están instalados en el Python 3.13 local y no hay servidor+branch TEST levantado. Comandos para validar en el entorno del proyecto: `backend\run_tests.bat` (Python 3.12 + `ENVIRONMENT=test`).
- **Frontend:** sin cambios necesarios (los endpoints conservan su firma y axios ya envía el JWT). `oxlint` sin errores en el único archivo tocado (`Notificaciones.jsx`).

---

## 3.2 FASE 1 — ✅ CERRADA (validación runtime + migración completa + schema alineado + 20/20 en Postgres real) — 18/08/2026

### Tarea A — Validación en runtime (17/17 PASS)

Se construyó `backend/_fase1_validation.py` (harness con SQLite local + `httpx` ASGITransport sobre la app real). La BD de test (`ep-lingering-shape…neon.tech`) **rechaza autenticación** (credenciales rotadas), por lo que la validación se hizo contra un SQLite con schema mínimo, sin depender del entorno.

| # | Caso (Tarea A) | Esperado | Real |
|---|---|---|---|
| 1 | `DELETE /historial-rm/{id}` de otro alumno | 403 | ✅ 403 |
| 2 | `PUT /historial-rm/{id}` de otro alumno | 403 | ✅ 403 |
| 3 | `PUT /historial-rm/{id}` propio con `created_at` > 24h | 403 + msj ventana | ✅ 403 "…hace más de 24 horas…" |
| 4 | `GET /membresias/mi-membresia?tenant_id=2&alumno_id=<otro>` | 200, datos propios | ✅ 200 activa=True |
| 5 | `GET /planes/membresia-activa?tenant_id=2&alumno_id=<otro>` | 200, datos propios | ✅ 200 activa=True |
| 6 | `GET /notificaciones?alumno_id=<otro>` (sin staff) | 403 | ✅ 403 |
| 7 | `POST /solicitudes/solicitar` `alumno_id` ajeno (no staff) | 403 | ✅ 403 |
| 8 | `POST /auditoria` sin token | 401 | ✅ 401 |
| 9 | `POST /auditoria` token rol alumno | 403 | ✅ 403 |

Positivos (8/8): notificaciones propias (200, solo las propias) · coach lee notif. de otro (200) · alumno solicita para sí (201) · coach por alumno del box (201) · coach con alumno de otro box (403) · auditoria rol coach (201 con actor del token) · `GET /historial-rm` sin filtro → solo propios · `GET /historial-rm?alumno_id=ajeno` → 403.

**Ajuste derivado de la Tarea A (aplicado antes de la Tarea B):** `POST /solicitudes/solicitar` y `GET /notificaciones` ahora devuelven **403 explícito** ante un ID ajeno sin rol staff (antes lo silenciaban/ignoraban). No rompe el frontend (envía siempre el ID propio).

### Tarea B — Migración completa de endpoints pendientes

- Migradas **69 endpoint-funciones adicionales** en 19 routers (`tenants`, `fidelizacion`, `retencion`, `supervision`, `auditoria` GETs, `planes`, `horarios`, `coach_disciplinas`, `pedidos`, `wods/parse`, `alumnos`, `usuarios`, `disciplinas`, `productos`, `finanzas`, `suscripciones`, `configuracion` PUT, `dashboard/ocupacion-hoy`, `solicitudes/pendientes`).
- **Estado final de la API:** 150 rutas bajo `/api/*` → **147 exigen autenticación** · 3 públicas por diseño (`POST /auth/login`, `POST /alumnos/registro/alumno-nuevo`, `GET /configuracion`) · **0 abiertas restantes** (verificado por inspección de dependencias de cada ruta).
- **Middleware `tenant_audit` tras la migración:** los warnings que genere provendrán de que el **frontend todavía envía** `tenant_id` en query/body (ahora ignorado). Ya no es un patrón estructural de riesgo; su utilidad pasa a ser (a) detectar **regresiones** (un endpoint que vuelva a leer el param) y (b) priorizar la **limpieza del frontend** (dejar de enviar `tenant_id`) en una fase posterior.
- **Único `tenant_id` con default restante:** `alumnos.py` `RegistroAlumnoNuevo.tenant_id = 1` (registro público). La landing no envía tenant; hoy hay un único box. Cumplir la regla #3 sin romper la landing exige resolver el box por subdominio en el frontend → **⛔ REQUIERE CONFIRMACIÓN** (cambio de frontend).

### Tarea C — Propuesta de esquema para `Notificacion` (sin ejecutar)

La tabla `notificaciones` está orientada a alumnos: destinatario = `alumno_id`, **sin `tenant_id`**, sin UI para coach. Dos alternativas:

1. **Extender la tabla existente** (⛔ REQUIERE CONFIRMACIÓN — migración Alembic `008`): agregar `tenant_id` + `destinatario_tipo` (alumno/coach) + `destinatario_id` nullable. Reutiliza el router existente y habilita la notificación al coach por nuevo PR/cambio de nivel.
2. **Tabla separada `notificaciones_staff`** (⛔ REQUIERE CONFIRMACIÓN): si el modelo alumno-notificación no es compatible (destinatario = `alumno_id` NOT NULL). Aislada, con `tenant_id`, destinatario usuario_id + rol, y endpoints propios.

**Ambas se agrupan con la decisión pendiente de `BoxMembership`** (AUDIT.md §2.2): el modelo de roles actual (rol único en `usuarios`) condiciona quién es "el coach del box" receptor. Resolver en conjunto, no aisladas.

### Tarea D — `POST /auditoria` como endpoint interno — ✅ EJECUTADO (cierre 2, 18/08/2026)

Se retiró la ruta pública `POST /auditoria` de la API (ahora responde **405**; verificado en el harness). La escritura de auditoría se realiza únicamente vía `auditoria_service.registrar_*`, cableado en las acciones sensibles:

| Acción sensible | Archivo | Entrada de auditoría |
|---|---|---|
| Aprobación de comprobante | `solicitudes_planes.py` (`aprobar`) | `UPDATE solicitud_plan` + detalle (estado, alumno, plan, voucher) |
| Rechazo de comprobante | `solicitudes_planes.py` (`rechazar`) | `UPDATE solicitud_plan` + motivo |
| Alta de usuario | `usuarios.py` (`crear_usuario`) | `CREATE usuario` + rol/correo |
| Cambio de datos/rol | `usuarios.py` (`actualizar_usuario`) | `UPDATE usuario` + rol_anterior/nuevo |
| Baja de usuario | `usuarios.py` (`eliminar_usuario`) | `DELETE usuario` |
| Activación/rechazo de alumno | `alumnos.py` (`activar`, `rechazar`) | `UPDATE usuario` + estado |
| Edición de PR | `historial_rm.py` (`actualizar_historial_rm`) | `UPDATE historial_rm` + campos |
| Borrado de PR | `historial_rm.py` (`eliminar_historial_rm`) | `DELETE historial_rm` |
| Alta de suscripción | `suscripciones.py` (`crear_suscripcion`) | `CREATE suscripcion` + tokens |
| Compra de emergencia | `comprar_emergencia.py` | `UPDATE suscripcion` + tokens |

**Verificado en runtime (harness, 2 casos):** aprobar comprobante → aparece fila `solicitud_plan/UPDATE`; editar rol → aparece fila `usuario/UPDATE`. El actor (usuario_id/tenant_id) siempre sale del token.

### Validación final — ✅ FASE 1 CERRADA (Postgres real, 20/20 PASS)

- `python -m compileall -q app` → **OK** · `import app.main` → **OK**.
- **Harness `_fase1_validation_pg.py` → 20/20 PASS contra Postgres real** (`ep-withered-silence…neon.tech`): IDOR de PRs/membresías/notificaciones/solicitudes, ventana 24h, auditoría interna (aprobar comprobante + editar rol), `POST /auditoria` retirado (405), regresiones de coach (`fidelizacion/coach/{id}/en-riesgo`, `generar-clases-dia`). **Cleanup doble pasada OK — 0 filas TEST_VALIDACION remanentes** (verificado post-corrida).
- **Schema alineado (24/24 modelos → 26 tablas, 0 faltantes, 0 columnas faltantes):** migraciones Alembic aplicadas y en `head` (`2b922f9cd037`):
  - `007_add_notificaciones_enviadas` → tabla `notificaciones_enviadas`
  - `2ad8b8e1dfc7` → columnas `planes.es_estudiante`, `planes.primera_clase_tomada`, `disciplinas.requiere_coach` (default `true`, igual que el modelo), `pedidos.voucher_url`
  - `2b922f9cd037` → tablas `coach_disciplinas`, `cobertura_emergencia`, `transacciones_financieras`
  - Backup previo confirmado: `backend/backups/neon_backup_full_20260818_191406.sql` (21 tablas + 4 enums + datos, verificado).
- **Bug real detectado y corregido por el harness:** `horarios.py` tenía `GET /generar-clases-dia` (flip de `POST`→`GET` en commit `92d9565`), lo que rompía el panel coach (`GenerarClases.jsx` usa POST) → 405. **Corregido a `POST`** (alineado con frontend, doc y scheduler). Sin esta corrección el harness no cerraba 20/20.
- **Ajustes del harness PG** (no de la app): seed con roles reales (`coach`/`administrador`; antes creaba a todos como `alumno`, lo que producía 403 porque `get_current_user` lee el rol de la BD) y emails `@test.com` (el validador `EmailStr` rechaza `.invalid`).
- Harness SQLite `_fase1_validation.py` (regresión histórica) → **17/17 PASS**.
- `oxlint` frontend → **0 errores** (67 warnings pre-existentes en otros archivos).
- **Suite pytest oficial NO ejecutable en este entorno:** `pytest` no está instalado y la branch TEST de Neon rechaza las credenciales. Para el entorno del proyecto: `backend\run_tests.bat`.

---

## 3.3 CIERRE 2 — Auditoría interna, limpieza de frontend y propuestas de esquema — 18/08/2026

### Tarea 1 — `POST /auditoria` como función interna — ✅ EJECUTADO
Ver §3.2 Tarea D (actualizado a "ejecutado"). Confirmado por grep que ningún módulo del frontend llamaba a `/auditoria`.

### Tarea 2 — Frontend: dejar de enviar `tenant_id`/`alumno_id`/`usuario_id` — ✅ EJECUTADO

Se recorrieron los ~25 archivos del frontend y se removió el envío manual de `tenant_id` (query params), y de `alumno_id`/`usuario_id` (query params) en los endpoints ya migrados. **Se mantienen intactos:**
- Params de **path** (`/historial-rm/alumnos/{id}/...`, `/dashboard/{tenant_id}/ocupacion-hoy`, `/fidelizacion/tenant/{tenant_id}/...`, `/usuarios/{id}`).
- **Body** de schemas que los requieren (`POST /reservas`, `/historial-rm`, `/solicitudes/solicitar`, `/pedidos`, `/movimientos`, `/planes`, `/disciplinas`, `/horarios`, `/suscripciones`, `/finanzas`, `/coach-disciplinas`, `/productos`, `/usuarios`) — el backend los **sobreescribe/valida** contra el token.
- `GET /configuracion?tenant_id=` (público, el backend lo requiere) y `GET /reportes?tenant_id=` (el backend lo requiere y lo valida contra el token).
- Filtros de staff legítimos: `AlumnoFichaModal` (`usuario_id`), `Fidelizacion` (`alumno_id` para enviar email).

**Verificación:**
- `oxlint` frontend → **0 errores** (70 warnings, +3 sobre el baseline de 67, todos de `exhaustive-deps` por `tenant_id` en arrays de dependencias que quedaron definidas pero sin uso en requests; cosméticos).
- Harness `_fase1_validation.py` re-ejecutado → **17/17 PASS** (los 9 casos de Tarea A + positivos + 2 casos de auditoría interna + ruta `POST /auditoria` retirada = 405).
- **Middleware `tenant_audit`:** el frontend ya no envía `tenant_id` en query para los endpoints migrados. **Warnings esperados que permanecerán (no explotables):** `GET /configuracion` y `GET /reportes` (los requieren) y los **body** de schemas obligatorios (el backend los sobreescribe). Eliminar estos últimos por completo exigiría hacer `tenant_id` opcional en esos schemas Pydantic + quitarlo de los bodies del frontend → candidato a Fase 3 (no es una vulnerabilidad: el valor se ignora/valida).

**Corrección de regresiones detectadas al revisar el frontend (parte de esta tarea):** `GET /fidelizacion/coach/{id}/en-riesgo` y `POST /horarios/generar-clases-dia` habían quedado admin-only en la Tarea B, pero los **paneles de coach** los usan → se reabrieron a `get_current_coach` (con validación de que un coach solo consulta su propio `coach_id`). Sin esta corrección el dashboard del coach habría roto.

### Tarea 3 — Propuesta de esquema para notificaciones a coach/staff (NO ejecutada, ⛔ REQUIERE CONFIRMACIÓN)

La tabla `notificaciones` actual está orientada a alumnos: destinatario = `alumno_id`, **sin `tenant_id`**, sin UI para coach. Dos alternativas:

1. **Extender `notificaciones`** (migración Alembic `008`): `tenant_id` + `destinatario_tipo` (alumno/coach) + `destinatario_id` nullable. Reutiliza el router existente y habilita la notificación al coach por nuevo PR/cambio de nivel.
2. **Tabla separada `notificaciones_staff`**: aislada, con `tenant_id`, destinatario usuario_id + rol, y endpoints propios — si el modelo alumno-notificación no es compatible.

> ⚠️ **Decisión acoplada a `BoxMembership`:** ambas tablas modelan la relación **persona-box-rol** (quién es "el coach receptor" depende del rol por box). `BoxMembership` (AUDIT.md §2.2) modela lo mismo desde el lado del usuario. Resolverlas por separado arriesga diseñar la misma relación dos veces de forma distinta → **resolver en conjunto, no aisladas**. No se crean migraciones todavía.

### Tarea 4 — Propuesta de resolución de tenant en registro público (NO ejecutada, ⛔ REQUIERE CONFIRMACIÓN)

**Problema:** `RegistroAlumnoNuevo.tenant_id = 1` asigna siempre al box 1 porque un registro público no tiene sesión ni forma de identificar el box. La landing no envía `tenant_id`.

Dos vías posibles (decisión de **producto** — afecta cómo cada box comparte su link de registro):

1. **Subdominio por box** (`boxequis.tuapp.com/registro`): el backend resuelve `tenant` desde el subdominio del host (encaja con `tenants.subdomain` ya existente).
2. **Slug/parámetro en la ruta** (`tuapp.com/registro/box-equis`): el frontend resuelve el box vía `GET /tenants/subdomain/{slug}` (hoy admin-only) y lo envía explícitamente.

**Condición:** esta decisión debe resolverse **antes** de tocar el default hardcodeado; mientras tanto el registro sigue funcionando para el box único actual. No se implementa nada en esta ronda.

---

## 4. Plan concreto de PRs/commits (priorizado)

Convención: **P0** = corregir de inmediato · **P1** = antes del próximo deploy · **P2** = backlog. ⛔ = requiere confirmación tuya antes de ejecutar (breaking/schema).

### PR-01 · P0 · Auth en CRUD de PRs y movimientos — ✅ IMPLEMENTADO (Fase 1, 18/08/2026)
- **Commits:** `historial_rm.py` (POST/PUT/DELETE + 10 GETs: `get_current_user`, tenant del token, ownership, ventana de 24h en PUT). `movimientos.py` (GETs auth; POST/PUT/DELETE `get_current_coach`).
- **Pendiente asociado:** notificación al coach por nuevo PR/cambio de nivel (ver §3.1 pendientes) y edición de PR con ventana de 24h ya aplicada (PUT).

### PR-02 · P0 · Cerrar IDOR de membresías y notificaciones — ✅ IMPLEMENTADO (Fase 1)
- `membresias.py` GET `/mi-membresia`, `planes/membresia-activa`, `notificaciones.py` (GET/listar, `/{id}/leer`, `/leer-todas`): auth + IDs del token + ownership.

### PR-03 · P0 · `POST /auditoria` y `POST /solicitudes/solicitar` — ✅ IMPLEMENTADO (Fase 1) + ⏳ pendiente funcional
- `auditoria.py` POST → rol admin/coach + actor del token. `solicitudes_planes.py` POST `/solicitar` → auth + `alumno_id`/`tenant_id` del token (staff validado por rol y tenant).
- **Pendiente funcional:** notificación/email al admin al recibir una solicitud (requisito de negocio del AUDIT.md §6, gap #6). Y evaluar quitar `POST /auditoria` de la API pública (ver §3.1).

### PR-04 · P0 · Dependency `get_current_tenant` para derivar tenant del token — ✅ IMPLEMENTADO (Fase 1 + cierre 18/08/2026)
- Migradas **123 endpoint-funciones** en total (54 en Fase 1 + 69 en el cierre). Estado final: **147/150 rutas `/api/*` con auth obligatoria** (3 públicas por diseño) y **0 abiertas**. Todos los endpoints tenant-scoped derivan `tenant_id` del JWT; los parámetros del cliente se mantienen en la firma pero se ignoran.
- El middleware `TenantAuditMiddleware` queda activo para detectar regresiones y priorizar la limpieza del frontend (dejar de enviar `tenant_id`).

### PR-05 · P1 · Auditoría de acciones críticas (sin breaking)
- **Commits:** cablear `auditoria_service.registrar_*` en: aprobación/rechazo de solicitudes (`solicitudes_planes.py`), cambios de rol/estado (`usuarios.py` PUT/DELETE, `alumnos.py` activar), edición de PRs (`historial_rm.py`), ajustes de tokens (`suscripciones.py`, `comprar_emergencia.py`). Datos: quién (usuario_id), cuándo (created_at), qué (entidad/entidad_id/detalle). **Seguro** (solo inserts).

### PR-06 · P1 · CSRF + migración de token a cookie httpOnly — ⛔ REQUIERE CONFIRMACIÓN (breaking frontend+backend)
- Backend: `POST /auth/refresh` con rotación, cookie `httpOnly; Secure; SameSite=Strict`, y `X-CSRF-Token` (doble submit) para mutaciones. Frontend: quitar `localStorage`, axios `withCredentials`, interceptor de refresh. Incluir `Cache-Control: no-store` en respuestas autenticadas.

### PR-07 · P1 · Invalidación de sesión por cambio de password — ⛔ REQUIERE CONFIRMACIÓN (schema: columna `token_version` en `usuarios`)
- Alembic `008_add_token_version`. `create_access_token` incluye `ver`; `get_current_user` compara con BD; `cambiar-password` incrementa `ver`.

### PR-08 · P1 · Hardening de uploads — ✅ SEGURO (ya aplicado el punto 1)
- Aplicado: magic bytes. Pendiente (no aplicado por impacto): mover de `static/uploads` a carpeta fuera del webroot con `FileResponse` y `Content-Disposition: attachment` (breaking de URLs). Opción corta: agregar a `SecurityHeadersMiddleware` `X-Content-Type-Options: nosniff` (ya presente).

### PR-09 · P2 · RLS en PostgreSQL — ⛔ REQUIERE CONFIRMACIÓN (schema/operación)
- `CREATE POLICY` por tabla con `USING (tenant_id = current_setting('app.tenant_id')::int)`, `SET app.tenant_id` en cada conexión (evento de sesión SQLAlchemy). Capa adicional a la lógica de aplicación.

### PR-10 · P2 · Dependencias y CI
- **Commits:** añadir `bcrypt==4.x` a `requirements.txt`; generar `requirements.lock` (o migrar a `uv`). CI (GitHub Actions): `pytest` contra branch TEST, `pip-audit`, `npm audit`, `npm run build`. Definir retención de backups (ej. 14 daily / 6 monthly) en `maintenance/run_daily.py`.

### PR-11 · P2 · Endpoints internos peligrosos
- Desactivar/limitar `POST /api/v1/migracion/run` y `POST /api/v1/fix/corregir-fechas` a `ENVIRONMENT=test` (guard en el endpoint). ⛔ breaking mínimo, requiere confirmación de que ya no se usan en prod.

---

## 5. Auditoría de dependencias (pendiente de red)

- **Backend:** `pip install pip-audit && pip-audit -r requirements.txt`
- **Frontend:** `cd frontend && npm audit --omit=dev`
- En esta sesión no pudieron completarse (`pip-audit` no instalado; `npm audit` time-out de red/registry). Ejecutarlos antes del próximo deploy y adjuntar el resultado a este documento.

---

## 6. ⚠️ ACCIÓN MANUAL PENDIENTE — Rotación de credenciales de BD (18/08/2026)

- Las contraseñas de **`DATABASE_URL`** y **`DATABASE_URL_PROD`** quedaron expuestas en texto plano durante una **sesión de soporte externa a este entorno** (chat de soporte).
- **Ambas deben rotarse nuevamente en el panel de Neon** (usuarios/roles del endpoint `ep-withered-silence…neon.tech`) **antes de continuar a producción**.
- ⛔ **Cline no puede ejecutar esta acción:** requiere acceso al panel web de Neon. Es una **acción manual pendiente del usuario**.
- Después de rotar, el usuario debe:
  1. Actualizar las dos contraseñas en `backend/.env` (gitignored, no va a git).
  2. Verificar conexión: `python test_connection.py`.
  3. Re-ejecutar el harness: `python _fase1_validation_pg.py` (debe dar 20/20 PASS).
  4. Regenerar el backup con `python _backup_full.py` (el dump actual quedó con la password vieja).
- Hasta rotar, la BD activa debe considerarse potencialmente comprometida.

*Fin de SECURITY.md.*


