# DISEÑO — FIDELIZACIÓN (F1–F4)

Creado: 2026-09-29 · Estado: **F1 implementada** (catálogo completo por situación) · Autor: sesión
de trabajo
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
antes de mandar (F1), beneficios por correo con su estado (F2), el seguimiento de la gestión —el
correo guardado y legible desde Notificaciones (F3)— y las métricas de efectividad de esa gestión
(F4).

**La automatización por reglas NO es una fase de este diseño.** Se evaluó y quedó **fuera de
alcance**: un job que manda correos solo necesita reglas de negocio (cuándo, a quién, con qué
frecuencia) y un panel para apagarlo, y nada de eso está aprobado. Si algún día se hace, tiene que
reusar **estas mismas plantillas** (una campaña = plantilla + filtro) para no abrir un segundo
lugar donde se escriban los textos; pero no se diseña ni se implementa acá.

---

## 1. Punto de partida (lo que YA existe, para no duplicarlo)

| Pieza | Dónde | Qué aporta |
|---|---|---|
| Pantalla del box | `frontend/src/pages/admin/Fidelizacion.jsx` | Tabla de churn + filtros + "⚡ Acción Rápida" |
| Panel del coach | `frontend/src/pages/coach/DashboardCoach.jsx` + `components/PreviewEmailModal.jsx` | Ya tiene preview (el correo lo renderiza el backend) |
| API | `app/api/v1/fidelizacion.py` | `analizar`, `campana-email`, `coach/*`, `tenant/*` |
| Puerta única de salida | `app/services/email_service.py` | `_template()` (layout de marca) + `_enviar()` (Gmail SMTP + fila en `notificaciones_enviadas`) |
| Renders reutilizables | `email_service.render_email_fidelizacion*()` | Fuente única del copy de cada situación (envío real, preview del coach y catálogo) |
| Envío manual actual | `POST /notificaciones-enviadas/enviar-manual` | Manda `inactividad`/`vencimiento` **sin preview** |
| 6ª sección del Historial | `historial_alumno_service` | `beneficios` declarada y **no anunciada** (llega con F2) |

Cuando se diseñó la F1 **no existía** nada de esto (y por eso la F1 no lo inventó): tabla de
beneficios, "Pase de regreso" ni ningún tipo de campaña. La F2 los agrega; la F1 sólo dejó el
catálogo, el preview, el envío y el modo prueba.

---

## 2. Las 4 fases

### F1 — Plantillas con preview (ESTA FASE)
- `app/services/fidelizacion_plantillas.py`: **única definición** del catálogo (qué se puede
  mandar, con qué datos REALES de la BD, cómo se renderiza y cómo se envía).
- `GET /api/v1/fidelizacion/plantillas` · `POST /api/v1/fidelizacion/preview` ·
  `POST /api/v1/fidelizacion/enviar` · `POST /api/v1/fidelizacion/sugerir`.
- `frontend/src/components/ModalEnviarCorreo.jsx` + conexión en la Acción Rápida de
  Fidelización: el envío pasa a ser **elegir plantilla → ver el correo exacto → enviar**.
- `EMAIL_MODO=real|noop` (modo prueba) para poder probar sin mandar correo real.
- **Sin** beneficios, **sin** tablas nuevas, **sin** migraciones.

#### El catálogo es por situación (no una plantilla "de inactividad" genérica)
Un alumno inactivo de 8 días no necesita el mismo mensaje que uno que ya lleva 3 meses y dejó de
pagar. El catálogo cubre **las situaciones reales** y cada plantilla usa los datos reales de esa
situación:

| Plantilla (`id`) | Situación | Datos reales que usa |
|---|---|---|
| `inactividad_7_14` | 7 a 14 días sin entrenar | días sin entrenar |
| `inactividad_15_30` | 15 a 30 días sin entrenar | días sin entrenar |
| `inactividad_mas_30` | más de 30 días sin entrenar **o** plan vencido | días sin entrenar + si la membresía venció |
| `riesgo_alto` | el modelo (ML) lo marca ALTO/CRÍTICO | probabilidad de churn, motivo y recomendación de `predictions_churn` |
| `vencimiento` | plan por vencer (≤ 5 días) | plan y fecha reales de vencimiento |

Cada una tiene su propio copy en `email_service` (un asunto y un texto distintos): tres plantillas
que rinden el MISMO correo son una lista que le miente al admin.

#### Quién sugiere la plantilla: el backend, con los datos del alumno
`sugerir(db, alumno)` es **la única definición** de "qué correo le corresponde a este alumno". La
pantalla ya no adivina: antes elegía con su propia heurística ("si vence en ≤ 5 días →
vencimiento, si no → inactividad"), que con 5 plantillas nunca podría sugerir las otras 3. Gana la
**primera regla que aplica**, y la respuesta dice **cuál** regla ganó y por qué (`regla` + `motivo`)
para poder mostrárselo al admin:

1. **`vencimiento`** — membresía vigente que vence en ≤ `DIAS_RENOVACION_SUGERIDA` (5) días: es el
   único caso con fecha límite y el alumno todavía está pagando.
2. **`inactividad_mas_30`** — no tiene membresía vigente (su plan ya venció) o lleva más de
   `DIAS_INACTIVIDAD_LARGA` (30) días sin entrenar.
3. **`riesgo_alto`** — el ML lo marca ALTO/CRÍTICO (paga hoy, pero el modelo dice que se va).
4. **`inactividad_15_30`** — entre 15 y 30 días sin entrenar.
5. **`inactividad_7_14`** — el resto de los inactivos.
6. Si **ninguna** aplica (ej. entrenó hace 2 días), la sugerencia es **vacía** con el motivo: no
   hay nada que reclamarle y el sistema no inventa un correo.

### F2 — Beneficios y el "Pase de regreso"
Tabla de beneficios del alumno (con migración), el grupo `beneficios` del modal deja de estar
oculto, la sección `beneficios` del Historial se llena, y el pase se materializa como una
suscripción gratuita. **Antes de escribir la F2 hay que aplicar las correcciones A/B/C (§5).**

### F3 — Seguimiento: "Ver correo" en Notificaciones
El envío deja la gestión del alumno en `CONTACTADO` de forma consistente y **el correo que se mandó
queda legible después**, desde el panel de Notificaciones:

- **asunto y resumen guardados al enviar** (migración): hoy el log (`notificaciones_enviadas`) sólo
  guarda tipo, estado y destinatario, así que el mensaje que recibió el alumno es irrecuperable;
- **botón "Ver correo" por fila** con modal (asunto + resumen): sin esto, "se mandó un correo" no se
  puede auditar ni explicar cuando el alumno llama;
- **etiqueta "Plan por vencer"** para el tipo `vencimiento` en la lista de Notificaciones (hoy el
  panel muestra el id crudo).

### F4 — Métricas de efectividad (¿sirvió la gestión?)
Todo lo que se mandó se puede medir, con los datos que ya existen (log de correos + asistencias +
beneficios): **contactados**, **recuperados en 30 días** (volvieron a entrenar), **tasa por
beneficio**, **conversión del pase** (aceptado → usado), **ingreso recuperado vs descuento
otorgado** y **días hasta volver**. La tasa se rotula **"tasa observada"**: es una observación
sobre la gestión que se hizo, no un experimento controlado (no hay grupo de control, así que no se
promete causalidad).

### Lo que NO es una fase
- **Automatización por reglas** (jobs que mandan solos): fuera de alcance, ver §0.
- **Un segundo lugar donde se escriban los textos**: cualquier envío futuro reusa las plantillas de
  F1 (preview y envío renderizan con la MISMA función).
- **Opciones a medio terminar en la UI**: los grupos del catálogo y las pestañas del Historial que
  no están listos no se anuncian; una opción deshabilitada es ruido.


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
8. **Ningún envío es automático.** Cada correo lo dispara una persona: no hay jobs que manden solos
   (la automatización no es una fase de este diseño, ver §2).
9. **La sugerencia también vive en el servicio.** `sugerir()` es la única definición de qué
   plantilla le corresponde al alumno, y devuelve la regla que ganó: la pantalla ya no tiene su
   propia heurística (dos definiciones de "corresponde renovación" se desincronizan siempre).

---

## 4. Contrato de F1 (lo que el frontend puede esperar)

```
GET  /api/v1/fidelizacion/plantillas            (admin)
  -> {"modo_envio": "real"|"noop",
      "grupos":     [{"id","label","plantillas":[P]}],     # sólo grupos listos
      "plantillas": [P]}                                   # lista plana, sin beneficios

POST /api/v1/fidelizacion/preview               (admin)
  {"plantilla": "inactividad_15_30", "alumno_id": 999}
  -> {"plantilla","label","tipo_envio","destinatario","asunto","html","contexto":{...}}

POST /api/v1/fidelizacion/enviar                (admin)
  {"plantilla": "inactividad_15_30", "alumno_id": 999}
  -> {"ok": true, "estado": "enviado"|"simulado"|"fallido", "modo_envio": "...",
      "detalle_error": null, ...}

POST /api/v1/fidelizacion/sugerir               (admin)
  {"alumno_id": 999}
  -> {"plantilla": "inactividad_15_30"|null, "label": "..."|null,
      "regla": "inactividad_15_30"|"riesgo_alto"|... |"sin_situacion",
      "motivo": "Lleva 18 días sin entrenar", "contexto": {...}}
```

Plantillas del catálogo (ids válidos, en orden): `inactividad_7_14`, `inactividad_15_30`,
`inactividad_mas_30`, `riesgo_alto`, `vencimiento` (más el grupo `beneficios`, que llega con la F2).

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
$env:TEST_URL='/admin/fidelizacion'; $env:CLICK_SELECTOR='[data-testid="plantilla-inactividad_15_30"]'
$env:ASSERT_JS='document.querySelector("[data-testid=preview-asunto]").innerText.length > 0'
npm run test:click
```

Reglas de test (heredadas del proyecto): nada de correo real, no se toca PROD ni `.env`, y las
migraciones se prueban sólo en TEST y en dry-run.
