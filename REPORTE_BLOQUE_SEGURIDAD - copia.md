# REPORTE FINAL — BLOQUE SEGURIDAD (proyecto-crossfit)

Fecha: 11/08/2026 · Rama: main · Sin commits · Backend: http://localhost:8000 (modo TEST, BD lingering-shape)

---

## FASE 1 — PLANTILLAS DE CORREO INVESTIGADAS (`backend/app/services/email_service.py`)

**Existentes (5):** todas usan el helper `_template()` (header negro con logo `cid`, titulo, saludo, cuerpo, boton CTA naranja, footer).

| # | Funcion | Variables dinamicas | Tipo registrado |
|---|---------|--------------------|-----------------|
| 1 | `enviar_email_bienvenida(alumno, token_onboarding)` | nombre, token_onboarding (link onboarding) | `bienvenida` |
| 2 | `enviar_email_vencimiento_plan(alumno, fecha_vencimiento)` | nombre, correo, plan_nombre, fecha_vencimiento | `vencimiento` |
| 3 | `enviar_email_fidelizacion(nombre, correo, dias_ausente)` | nombre, correo, dias_ausente | `inactividad` |
| 4 | `enviar_email_solicitud_admin(alumno)` | nombre, correo_alumno (notifica al ADMIN, no al lead) | `solicitud_registro` |
| 5 | `enviar_email_activacion_alumno(alumno, password)` | nombre, correo, password | `activacion` |

**Faltantes (4):** `send_solicitud_prueba_clase`, `send_bienvenida_activacion`, `send_renovacion_plan`, `send_vencimiento_inminente` -> ninguna existia con esos nombres.

---

## FASE 2 — IMPLEMENTADAS (las 4 en `email_service.py`)

- Se implementaron con el helper `_template()` del propio archivo (convencion del codigo, conservando los textos/CTA pedidos).
- Log explicito `[nombre_plantilla] EXITOSO/FALLIDO` para trazabilidad.
- Envio via `_enviar()` (Gmail SMTP + registro en BD).
- Cableadas en el flujo:
  - `registrar_alumno_nuevo` -> envia `send_solicitud_prueba_clase` al lead.
  - `activar_alumno` -> envia `send_bienvenida_activacion` (con credenciales) y ahora devuelve `password_provisional` en la respuesta.
- Fix: `enviar_email_solicitud_admin` consultaba `rol IN ('admin','administrador')` -> rompia el enum de Postgres (`rol_usuario` solo acepta 'administrador') -> el correo al admin nunca se enviaba. Corregido a `RolUsuario.administrador` (verificado en logs).

**?Todas funcionan?** **SI** - verificado por E2E (emails reales `solicitud_prueba_clase` y `bienvenida_activacion` EXITOSOS) y test unitario de las 4 (HTML valido + interpolacion de variables).

---

## FASE 3 — LANDING PAGE

| Item | Estado |
|------|--------|
| ?Creada? (`frontend/src/pages/LandingPage.jsx`) | **SI** |
| ?Valida RUT? | **SI** (regex `\d{7,8}-[\dkK]` en front; modulo 11 en backend) |
| ?POST funciona? | **SI** - URL real corregida `/api/v1/alumnos/registro/alumno-nuevo` + aliases `peso_kg`/`estatura_cm` en el schema del backend. E2E confirmo `peso=75 estatura=180` guardados. |
| ?`/landing` cargada? | **SI** |
| ?`/` apunta a landing? | **SI** |

`npm run build` -> OK.

---

## FASE 4 — TEST E2E (14/14 PASS, BD TEST aislada)

| Paso | Verificacion | Resultado |
|------|--------------|-----------|
| 1 | `POST /api/v1/alumnos/registro/alumno-nuevo` -> 201 + `pendiente_activacion` | **SI** / Email **SI** (`[solicitud_prueba_clase] EXITOSO`) |
| 2 | `GET /alumnos/pendientes-activacion` (admin) -> Test Lead | **SI** / `count=1` exacto |
| 3 | `PUT /alumnos/951/activar` -> 200 + password | **SI** / Email **SI** (`[bienvenida_activacion] EXITOSO`) |
| 4 | `POST /auth/login` -> JWT; `GET /alumnos/me` -> `estado=activo`, `cambiar_password_al_login=true` | **SI** |
| 5 | `GET /clases` + `POST /reservas` -> 201 (reserva_id=65) | **SI** |
| 6 | Coach ve clase (vida `GET /reservas/por-clase/551`) -> Test Lead visible | **SI** |
| 7 | Asistencia (`PUT /reservas/65/asistencia` con token coach) -> `asistio=true` | **SI** |
| 8 | Dashboard (`GET /dashboard/1`) -> 200 | **SI** |

---

## CONCLUSION

- **?Sistema E2E funciona?** **SI** (14/14 checks: Lead -> activacion -> login -> reserva -> asistencia -> dashboard).
- **Bugs corregidos:** (1) enum `rol` en correo al admin; (2) ruta real del registro (`/alumnos/registro/...` vs `/registro/...`); (3) schema ignoraba `peso_kg`/`estatura_cm`; (4) `/alumnos/me` no existia -> implementado; (5) `/activar` no devolvia la password -> ahora la devuelve.
- **Preexistentes detectados (no tocados):** `.env` tiene `DATABASE_URL_PROD` que rompe `Settings` (el server solo levanta con `ENVIRONMENT=test`); ruta del logo `logo/images (17).jfif` no existe (hay `logo.png`); warning `bcrypt.__about__` en passlib; RUT de ejemplo `12345678-9` invalido por modulo 11 (DV correcto = 5, se uso `12345678-5`); `tests/conftest.py` genera JWTs para usuarios (1000/1001) que no existen en la BD test.
- **Endpoints de la spec que NO existen** (se testearon con su equivalente real): `GET /clases/hoy` (-> `/reservas/por-clase/{id}` + `/dashboard/{tid}/ocupacion-hoy`); `POST /asistencia/{clase_id}` (-> `PUT /reservas/{id}/asistencia`); `GET /admin/dashboard` (-> `/dashboard/{tid}`).

### Hallazgos de seguridad

1. `POST /api/v1/reservas` NO requiere autenticacion y acepta cualquier `alumno_id` (IDOR). Recomendado: `get_current_user` + validar `alumno_id == usuario_id`.
2. `PUT /alumnos/{id}/activar` devuelve la password provisional en la respuesta (solo admin; intencional). No loguearla.
3. Para el E2E se reseteo la password del admin (id=1) en la BD TEST a `AdminTest123!` y se creo un coach de prueba (id=5555) en esa BD aislada - no afecta produccion.

### Recomendaciones

- Quitar `DATABASE_URL_PROD` del `.env` o hacer `Settings` tolerante a extras.
- Apuntar `LOGO_PATH` a `logo/logo.png`.
- Implementar los endpoints faltantes (`clases/hoy`, `asistencia/{clase_id}`, `admin/dashboard`) si se quiere la spec literal.
- Proteger `POST /reservas` con auth.
- Corregir el placeholder de RUT en la Landing y su ejemplo (`12345678-5`).

**Nota:** el servidor quedo corriendo en `http://localhost:8000` en modo TEST. Sin commits y sin `run_tests.bat`.
