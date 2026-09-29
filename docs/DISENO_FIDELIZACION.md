# DISEÑO — FIDELIZACIÓN (F1–F4)

Creado: 2026-09-29 · Estado: **F1 implementada** · Autor: sesión de trabajo
Este documento existe para que el diseño **no se pierda entre sesiones**: nació de una
conversación y no estaba escrito en ninguna parte del repo (a diferencia de otros bloques, que
tienen su `LOG_*.md` / `AUDITORIA_*.md`).

---

## 0. Para qué existe la feature

La pantalla de Fidelización ya muestra quién está en riesgo de irse (`GET /kpis/churn`, ML) y
ofrece una "Acción Rápida" que **manda un correo a ciegas**: el admin elige `inactividad` o
`vencimiento`, aprieta y no ve nunca lo que va a recibir el alumno. Además no hay beneficios
(regalar un pase, un mes con descuento) ni seguimiento de si la gestión funcionó.

Fidelización es la capa que convierte ese diagnóstico en **acciones**: correos que el admin ve
antes de mandar (F1), beneficios por correo con su estado (F2), seguimiento de la gestión (F3) y
automatización por reglas (F4).

---

## 1. Punto de partida (lo que YA existe, para no duplicarlo)

| Pieza | Dónde | Qué aporta |
|---|---|---|
| Pantalla del box | `frontend/src/pages/admin/Fidelizacion.jsx` | Tabla de churn + filtros + "⚡ Acción Rápida" |
| Panel del coach | `frontend/src/pages/coach/DashboardCoach.jsx` + `components/PreviewEmailModal.jsx` | Ya tiene preview (el correo lo renderiza el backend) |
| API | `app/api/v1/fidelizacion.py` | `analizar`, `campana-email`, `coach/*`, `tenant/*` |
| Puerta única de salida | `app/services/email_service.py` | `_template()` (layout de marca) + `_enviar()` (Gmail SMTP + fila en `notificaciones_enviadas`) |
| Renders reutilizables | `email_service.render_email_fidelizacion()` | Fuente única del copy de inactividad (envío real y preview) |
| Envío manual actual | `POST /notificaciones-enviadas/enviar-manual` | Manda `inactividad`/`vencimiento` **sin preview** |
| 6ª sección del Historial | `historial_alumno_service` | `beneficios` declarada y **no anunciada** (llega con F2) |

**No existe** (y por eso F1 no lo inventa): tabla de beneficios, "Pase de regreso", catálogo de
plantillas, ni ningún tipo de campaña.

---

## 2. Las 4 fases

### F1 — Plantillas con preview (ESTA FASE)
- `app/services/fidelizacion_plantillas.py`: **única definición** del catálogo (qué se puede
  mandar, con qué datos REALES de la BD, cómo se renderiza y cómo se envía).
- `GET /api/v1/fidelizacion/plantillas` · `POST /api/v1/fidelizacion/preview` ·
  `POST /api/v1/fidelizacion/enviar`.
- `frontend/src/components/ModalEnviarCorreo.jsx` + conexión en la Acción Rápida de
  Fidelización: el envío pasa a ser **elegir plantilla → ver el correo exacto → enviar**.
- `EMAIL_MODO=real|noop` (modo prueba) para poder probar sin mandar correo real.
- **Sin** beneficios, **sin** tablas nuevas, **sin** migraciones.

### F2 — Beneficios y el "Pase de regreso"
Tabla de beneficios del alumno (con migración), el grupo `beneficios` del modal deja de estar
oculto, la sección `beneficios` del Historial se llena, y el pase se materializa como una
suscripción gratuita. **Antes de escribir la F2 hay que aplicar las correcciones A/B/C (§5).**

### F3 — Seguimiento de la gestión
El envío deja la gestión del alumno en `CONTACTADO` de forma consistente y se puede medir qué
plantilla trajo de vuelta al alumno (efectividad por plantilla, no sólo "se mandó").

### F4 — Automatización
Los jobs (`scheduler.py`) usan **las mismas plantillas**: una campaña = plantilla + filtro, sin
copy nuevo ni un segundo lugar donde se escriban los textos.


---

## 3. Decisiones de F1 (y por qué)

1. **Servicio = reglas, router = elegir y devolver.** Mismo patrón que el Historial del alumno:
   el router no arma textos ni consulta la BD por su cuenta.
2. **Preview y envío renderizan con LA MISMA función.** Lo que el admin ve es exactamente lo que
   se manda (el preview no puede "derivar" del envío).
3. **Los datos del correo salen de la BD**, nunca del frontend: días reales de inactividad y
   vencimiento real de la suscripción vigente.
4. **ACL: sólo admin del box** (`get_current_admin`) y siempre con el `tenant_id` del token; un
   alumno de otro box es **404**, no 403 (no se confirma que exista).
5. **`tipo_envio` = el tipo que se registra en `notificaciones_enviadas`** (`inactividad`,
   `vencimiento`, …): los mismos valores que ya usa el resto del sistema, para que el log de
   correos siga siendo uno solo.
6. **Modo prueba `EMAIL_MODO=noop`:** no se conecta a SMTP y la fila queda **`simulado`**, nunca
   `enviado`. Es la diferencia entre "no se mandó" y "se mandó", y el panel de notificaciones no
   puede mentir.
7. **Lo que no está listo no se anuncia.** El grupo `beneficios` del catálogo existe como
   reservado pero **no se manda al front** hasta la F2 (mismo criterio que las pestañas del
   Historial: una opción deshabilitada es ruido).
8. **Ningún envío es automático en F1.** Cada correo lo dispara una persona; la automatización es
   F4.

---

## 4. Contrato de F1 (lo que el frontend puede esperar)

```
GET  /api/v1/fidelizacion/plantillas            (admin)
  -> {"modo_envio": "real"|"noop",
      "grupos":     [{"id","label","plantillas":[P]}],     # sólo grupos listos
      "plantillas": [P]}                                   # lista plana, sin beneficios

POST /api/v1/fidelizacion/preview               (admin)
  {"plantilla": "inactividad", "alumno_id": 999}
  -> {"plantilla","label","tipo_envio","destinatario","asunto","html","contexto":{...}}

POST /api/v1/fidelizacion/enviar                (admin)
  {"plantilla": "inactividad", "alumno_id": 999}
  -> {"ok": true, "estado": "enviado"|"simulado"|"fallido", "modo_envio": "...",
      "detalle_error": null, ...}
```

Errores: `404` alumno de otro box/inexistente · `400` plantilla sin datos para ese alumno
(ej. renovación de alguien sin plan vigente) · `422` plantilla desconocida (patrón de ids válido).
El envío devuelve **200 con `ok:false`** si Gmail falla (el detalle va en `detalle_error`), igual
que `enviar-manual`: el fallo de un correo no es un error de la petición.

---

## 5. Correcciones obligatorias ANTES de la F2 (beneficios / Pase de regreso)

Se detectaron al diseñar la F2 y quedan acá para no perderlas. **Las tres nacen del mismo error
conceptual: tratar un beneficio regalado como si fuera una membresía pagada.**

**A. El "Pase de regreso" NO es una membresía: excluirlo de retención, cohortes, "vigentes", churn
y ML — con UN helper compartido.**
El pase se materializa como una suscripción gratuita, así que si no se excluye explícitamente
infla la retención (un alumno "vuelve" gratis), los cohorts, la cuenta de vigentes, el churn y el
dataset del ML (un registro que el modelo nunca debería aprender como cliente real). La exclusión
tiene que ser **una sola definición** (helper en `shared/estados.py`, p. ej.
`PLANES_NO_COMERCIALES = ("Prueba", "Pase de regreso")` + predicado SQL) usada por los cinco
consumidores. **Test:** un alumno con pase vigente no aparece en ninguna de las cinco vistas.

**B. Al crear un beneficio, vencer antes los vencidos — en la MISMA transacción.**
Antes de insertar el nuevo beneficio hay que marcar como `vencido` todo `ofrecido` con
`vigente_hasta < now()` del mismo alumno/tipo. Si la expiración queda para un job aparte, entre
que vence y que corre el job el alumno tiene dos pases vivos y puede usarlos dos veces. **Test:**
un beneficio con ventana pasada se lee `vencido` inmediatamente después del alta del nuevo.

**C. `POST /reservas` tiene que dejar reservar con el pase aunque `activo=False`.**
El pase es gratis y sin pago, así que su suscripción puede no estar "activa" en el sentido
comercial; el criterio de reserva no puede ser `activo` sino la **vigencia/créditos**. Hay que
verificarlo con un test que reserve con el pase puesto (si falla, el beneficio es inusable).

---

## 6. Cómo se prueba

```powershell
# Servicio + API de F1 (la API se prueba con EMAIL_MODO=noop: nunca manda correo real)
cd backend; $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_fidelizacion_plantillas.py -q

# Frontend
cd frontend; npm run lint; npm run build

# 1 click real hasta la VISTA PREVIA (sin enviar): Acción Rápida -> Enviar correo -> plantilla
$env:TEST_URL='/admin/fidelizacion'; $env:CLICK_SELECTOR='[data-testid="plantilla-inactividad"]'
$env:ASSERT_JS='document.querySelector("[data-testid=preview-asunto]").innerText.length > 0'
npm run test:click
```

Reglas de test (heredadas del proyecto): nada de correo real, no se toca PROD ni `.env`, y las
migraciones se prueban sólo en TEST y en dry-run.
