# Auditoría real: abandono del checkout de Mercado Pago

**Fecha:** 2026-11-16
**Rama de prueba:** `ep-crimson-tooth-akhx7q2s` (Neon TEST, `ENVIRONMENT=test`)
**Credencial de MP:** cuenta de prueba `TESTUSER7982365823223167243` (id 3796774888,
`site_id=MLC`, tag `test_user`), `MERCADOPAGO_MODO=test`
**Cómo se reprodujo:** llamadas reales a la API del proyecto (TestClient en proceso
y servidor `localhost:8000`) contra la rama TEST, y llamadas REALES a la API de
Mercado Pago sandbox (creación/lectura de preferencias y búsqueda de pagos).

> **Actualización posterior (mismo día):** el guard de membresía se acortó a
> **5 min** (`MINUTOS_GUARD_MEMBRESIA`, también para limpiar la intención
> `iniciado`). Los pagos REALES `pendiente`/`en_proceso` conservan **30 min**
> (`MINUTOS_MEMBRESIA`) y el Bazar sigue en **30 min** (`MINUTOS_BAZAR`). El
> resto de este informe describe la auditoría y la implementación originales con
> un único umbral de 30 min.

> Workaround de transporte: el SDK `mercadopago==3.6.0` se quedaba colgado en
> `preference().create()` (timeout de 60 s × 3 reintentos), mientras que el MISMO
> payload por REST directo respondía `201` en ~2,5 s. Para la auditoría se
> reemplazó SÓLO el transporte del SDK por REST; `crear_preferencia` siguió
> armando el payload y procesando la respuesta reales. No es un cambio de código.

---

## Escenario 1 — Clic y salida ANTES de ver Mercado Pago · CONFIRMADO

Hecho real: `POST /api/v1/pagos/membresia` respondió `200` y, en la MISMA
transacción, la base ya tenía:

| Objeto | Estado inmediato |
|---|---|
| `solicitudes_planes` #890 | `pending`, `origen_pago=mercadopago`, `precio_final_clp=44000` |
| `pagos` #32 | `pendiente`, `preference_id=3796774888-71373380-698d-4d73-b182-6d9bd29751e9` |
| preferencia real en MP | creada (`201`) con `external_reference=04fe889f-…` |
| cola del admin (`GET /solicitudes/pendientes`) | **la trae**, badge **"Esperando pago"**, `pago_estado=pendiente` |
| `GET /pagos/32` (lo que vería PagoResultado) | `estado=pendiente`, `aplicado=false` |
| pagos REALES en MP con ese `external_reference` | **0** |
| `pagos_eventos` del pago | **0** |

Nunca se abrió el checkout. El admin ya veía la solicitud, y seguía viéndola: sin
acción en MP no hay webhook que la cierre.

**Conclusión:** el problema existe y es exactamente el descrito. El backend crea
la fila visible en el clic, antes de que el alumno haga nada en la pasarela.

---

## Escenario 2 — Llegar a MP, no pagar, salir con el botón FÍSICO de atrás · PARCIAL (limitación explícita)

Lo que sí se pudo verificar:

* `GET sandbox_init_point` desde este entorno respondió **HTTP 403** en
  `sandbox.mercadopago.cl`. No hay credenciales del comprador de prueba en el
  repo, así que **no se pudo cargar el formulario de tarjeta** ni pulsar el botón
  físico de atrás. No se simula al 100 % en escritorio.
* La preferencia REAL leída de MP devolvió:
  `back_urls = {"success":"","pending":"","failure":""}` y
  `notification_url = "http://localhost:8001/api/v1/pagos/webhook/mercadopago"`.
  Es decir: en este sandbox MP **vació las back_urls** (aunque la app las envió
  con `http://192.168.100.241:5173/alumno/pago/resultado/32`) y la URL de webhook
  es inalcanzable desde internet.
* Aun si la `back_urls.failure` existiera, visitarla sólo provoca
  `GET /pagos/32`: se llamó dos veces y la respuesta siguió en `pendiente`,
  `aplicado=false`, sin ningún cambio en la base.
* Abrir y abandonar el checkout no generó pagos en MP (`payment search` = 0) ni
  eventos (`pagos_eventos` = 0). El admin siguió viendo **"Esperando pago"**.

**Sobre el botón físico de atrás:** es una acción del historial del navegador o
del webview (Android/iOS); no dispara un webhook ni abre `back_urls`. Vuelve a la
entrada anterior del historial (nuestra app), no a `/alumno/pago/resultado/:id`.
Por lo tanto, si el alumno entra a MP desde `SolicitarPlan`, al volver con el
gesto físico **no pasa por PagoResultado.jsx**. Esto no se pudo reproducir en un
webview real desde este entorno; queda declarado como limitación.

**Conclusión:** el efecto en el admin queda confirmado (solicitud visible sin
acción real). El comportamiento exacto del gesto físico depende del webview y no
se pudo simular al 100 %.


---

## Escenario 3 — El banco RECHAZA el pago · CONFIRMADO (y NO era como se creía)

La API de MP con estas credenciales no permite crear el pago de prueba: el token
de acceso es de un **test user** y la `MERCADOPAGO_PUBLIC_KEY` del `.env` es
**live**, así que `POST /v1/payments` responde
`401 Unauthorized use of live credentials`. No hay tarjetas reales ni usuario
comprador de prueba disponible. **Limitación explícita.**

Para auditar el lado que importa (qué hace la app con un rechazo real) se usó el
MISMO camino del webhook: `registrar_evento` + `procesar_notificacion` con un
detalle de pago con el shape real de MP (`status=rejected`,
`status_detail=cc_rejected_other_reason`, `transaction_amount` y
`external_reference` del pago real), contra la base TEST real.

Resultado con el código anterior al fix:

| Dato | Valor |
|---|---|
| `pagos` #34 | `rechazado`, `payment_id=9876543210123` |
| `solicitudes_planes` #892 | **`pending`**, `comentario_admin=NULL` |
| cola del admin | **sigue apareciendo**, badge "Pago no completado" |
| `pagos_eventos` | 1 (procesado) |
| guard "ya tienes una solicitud pendiente" | **1** → el alumno NO puede reintentar |

**Conclusión:** el supuesto "el webhook marca la SolicitudPlan como rejected" era
FALSO. El webhook sólo cambia `pagos.estado`; la solicitud queda `pending` para
siempre (el cron sólo expira `pendiente`/`en_proceso`, no `rechazado`) y bloquea el
reintento. Este caso también necesitaba corrección.

---

## Escenario 4 — Volver por la app y usar "Cancelar pago" · CONFIRMADO

`POST /api/v1/pagos/32/cancelar` (dueño del pago):

* `200 {"estado":"cancelado"}`
* `pagos` #32 → `cancelado`
* `solicitudes_planes` #890 → `rejected`, comentario
  `"Cancelado por el alumno antes de completar el pago"`
* `GET /solicitudes/pendientes` → la solicitud #890 **ya no aparece**
* `GET /pagos/32` → `cancelado`

Nota de entorno: el proceso de auditoría se colgó al cerrar la conexión de Neon
DESPUÉS del commit; el estado se verificó por el servidor `localhost:8000` y la
base. No es un fallo de la lógica de cancelación.

**Conclusión:** el botón existente funciona. El problema es el alumno que NUNCA
llega a PagoResultado.

---

## Cambio aplicado

1. **Nuevo estado `iniciado`** en `pagos` (migración `086_pago_iniciado`) y en
   `solicitudes_planes` (sin CHECK en la tabla).
2. `POST /pagos/membresia` crea la solicitud y el pago en `iniciado`:
   la fila existe para que el backend pueda pedir el `init_point` y para que el
   webhook tenga `referencia_id`, pero **no la ve el admin** (todas las consultas
   de pendientes filtran `estado='pending'`) y **no manda campana**.
3. El **primer webhook real** de MP:
   * `approved`/`pending`/`in_process`/`authorized` → solicitud `pending`
     (visible) + campana al admin UNA vez;
   * `rejected`/`cancelled`/`refunded`/`charged_back` → solicitud `rejected`
     (sale de la cola, con comentario del motivo) y el alumno puede reintentar.
4. **Guard de 30 min**: bloquea otro checkout (tarjeta) o una transferencia
   mientras haya una solicitud `pending` o un pago `iniciado` fresco del mismo
   alumno, con el mensaje "Ya tienes un pago en curso…". A los 30 min se libera
   solo (sin cron) y el intento viejo se cierra como `expirado`/`expirada`.
   El cron horario también levanta los `iniciado` viejos (housekeeping).
5. `Cancelar pago` acepta `iniciado` además de `pendiente`/`en_proceso`.
6. El historial de solicitudes del alumno/admin oculta las `iniciado`.
7. La expiración automática (servicio y cron SQL) y la reconciliación de
   webhooks perdidos incluyen `iniciado`: el intento invisible se limpia a los
   30 min y, si MP tiene un cobro real con webhook perdido, se aplica igual.

---

## Archivos tocados

* `backend/app/models/pago.py` — estado `iniciado` + CHECK.
* `backend/app/models/solicitud_plan.py` — documentación del estado oculto.
* `backend/app/services/pagos.py` — guard, creación oculta, promoción por
  webhook, cierre por rechazo, cancelación y expiración.
* `backend/app/api/v1/solicitudes_planes.py` — guard compartido y filtro del
  historial.
* `backend/alembic/versions/086_pago_iniciado.py` — migración del CHECK.
* `backend/maintenance/expirar_pendientes.py` y
  `backend/maintenance/reconciliar_pagos.py` — réplica SQL/reconciliación con
  `iniciado`.
* `frontend/src/pages/alumno/PagoResultado.jsx` — mensaje `iniciado` y botón
  Cancelar.
* `frontend/src/hooks/queries.js` — comentario del flujo.
* Tests: `test_pago_iniciado_oculto.py` (nuevo), `test_cancelar_pago.py`,
  `test_pagos_boton_front.py`, `test_pago_mercadopago_descuento.py`,
  `test_expirar_pendientes.py`, `test_solicitudes_pendientes_voucher.py`.

---

## Tests

| Suite | Resultado |
|---|---|
| Aislados: `test_pago_iniciado_oculto` + `test_cancelar_pago` + `test_pagos_boton_front` + `test_expirar_pendientes` | **57 passed** |
| `tests/test_pagos_webhook_firma.py` (aislado) | **10 passed** |
| `tests/test_solicitudes_pendientes_voucher.py` (integración) | **2 passed** |
| `tests/test_pago_mercadopago_descuento.py` completo (integración, SDK falso) | **4 passed** |

Nota: el primer test de `test_pago_mercadopago_descuento.py` ya estaba roto en
`main` por el commit `5bd0764` (la descripción de la transacción pasó de
`usuario #id` al nombre, pero el helper `_ultima_tx` seguía buscando el id). Se
corrigió el helper para buscar por la referencia real del dinero (suscripción o
solicitud). `test_solicitudes_pendientes_voucher.py` también necesitaba importar
`Pago` para resolver la FK `solicitudes_planes.pago_id` cuando corre aislado.


---

## Limitaciones de la auditoría (explícitas)

* No se pudo simular el **botón físico de atrás** de Android/iOS ni cargar el
  formulario de tarjeta del sandbox (403; no hay comprador de prueba en el repo).
* No se pudo crear un pago RECHAZADO en MP con estas credenciales (401 por
  mezcla test-user/public-key live); el lado app del rechazo se verificó con el
  shape real de MP por el mismo servicio del webhook.
* El SDK 3.6.0 se colgaba en la creación de preferencias desde este entorno; se
  reemplazó SÓLO el transporte por REST para la auditoría.
