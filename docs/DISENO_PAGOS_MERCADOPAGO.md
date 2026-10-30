# Diseño: pago online con Mercado Pago (Checkout Pro)

**Estado:** IMPLEMENTADO en `feature/pagos-mercadopago` (2026-10-29). Este documento
sigue siendo el diseño de referencia; lo construido y las decisiones menores que se
tomaron sobre la marcha están en el §14.
**Fecha:** 2026-10-29
**Rama:** `feature/pagos-mercadopago` (creada desde `main`; **no** mergeada, nada
desplegado a PROD).
**Alcance:** cobrar por pasarela las dos cosas que hoy se cobran a mano (membresías y
Bazar), sin romper el flujo manual ni el modelo contable.

---

## 1. Qué se quiere y qué NO

**Sí:**
- Que el alumno pueda pagar su plan y sus compras del Bazar con tarjeta/efectivo
  desde la app, sin subir un comprobante y sin esperar a que un admin lo apruebe.
- Que el dinero se acredite en la cuenta de Mercado Pago del box.
- Que el estado del pago lo diga **Mercado Pago**, no el navegador.
- Que todo lo que hoy funciona (transferencia + voucher + aprobación manual) siga
  funcionando igual. Convivencia, no reemplazo.

**No (en esta fase):**
- Suscripciones recurrentes / cobro automático mensual (MP tiene *preapproval*;
  es otro diseño).
- Guardar tarjetas, hacer *payouts*, split de pagos entre boxes.
- Reemplazar `transacciones_financieras` por un log de la pasarela.

---

## 2. Lo que hay hoy (verificado en el código)

No hay ninguna pasarela: cero referencias a `mercadopago` en backend, frontend,
`requirements.txt` o `render.yaml`. Cobrar es un proceso **manual con comprobante**.

### 2.1 Membresías

| Paso | Dónde | Qué hace |
|---|---|---|
| Alumno sube comprobante | `POST /api/v1/upload/voucher?privado=1` | Guarda en `app/private_uploads` (dev) o R2 privado. Devuelve `/privado/vouchers/<archivo>` |
| Alumno crea la solicitud | `POST /api/v1/solicitudes/solicitar` (`solicitud.py`: `tenant_id, alumno_id, plan_id, voucher_url, certificado_estudiante_url`) | `solicitudes_planes` en estado `pending`, con **snapshot** de precio: `precio_clp_snapshot`, `descuento_pct`, `precio_final_clp`, `beneficio_id` |
| Admin aprueba | `PUT /api/v1/solicitudes/{id}/aprobar` | Crea `Suscripcion` (`activo`) + `TransaccionFinanciera` (ingreso, categoría membresía) + auditoría + correo |
| Admin rechaza | `PUT /api/v1/solicitudes/{id}/rechazar` | `rejected`, sin efecto económico |
| Alta en el mesón | `POST /api/v1/suscripciones` | Sin solicitud: crea suscripción + transacción. Idempotencia de 10 min + `FOR UPDATE` del alumno |
| Compra de emergencia | `POST /api/v1/planes/comprar-emergencia` | Activa el plan **directo** (sin solicitud ni aprobación) y **no** registra `TransaccionFinanciera` |

Los datos bancarios que se muestran al alumno salen de `configuracion_negocio`
(`banco`, `numero_cuenta`, `tipo_cuenta`, `rut`, `email_comprobantes`) vía
`GET /api/v1/configuracion` (`LIMIT_CONFIG_LECTURA`).

### 2.2 Bazar

| Paso | Dónde | Qué hace |
|---|---|---|
| Alumno compra | `POST /api/v1/pedidos` (requiere `require_full_access`) | `estado` forzado a `pendiente`, valida `producto.activo` y stock, **descuenta stock atómicamente** (`UPDATE ... WHERE stock >= cantidad`) y guarda `voucher_url` |
| Admin valida | `PUT /api/v1/pedidos/{id}/estado` (`pendiente` → `validado`) | Genera `codigo_retiro`, notifica |
| Admin entrega | `POST /api/v1/pedidos/entregar` (código de 4 símbolos, `LIMIT_CODIGO_RETIRO`) | `entregado` |
| Admin rechaza | `POST /api/v1/pedidos/{id}/rechazar` | Devuelve stock |

**Detalle contable que condiciona todo el diseño:** el Bazar **no** inserta en
`transacciones_financieras`. El BI, Reportes y el historial de pagos del alumno leen
`pedidos` filtrando por `ESTADOS_PAGO_BAZAR` (`shared/estados.py`: un pedido sólo es
plata si está `validado`/`entregado`). Si la pasarela insertara una transacción por
cada pedido, **el ingreso del Bazar se contaría dos veces**.

### 2.3 Restricciones del proyecto que la integración debe respetar

- **Multi-tenant estricto:** `tenant_id` siempre sale del JWT, nunca del body. Toda
  tabla nueva lleva `tenant_id` + índice.
- **Dinero:** `planes.precio_clp` es `Integer` (CLP sin decimales) pero
  `productos.precio` y `pedidos.total` son `Float`. CLP no tiene decimales: el pago
  del Bazar hay que redondearlo a entero antes de mandarlo a MP.
- **Rate limit:** slowapi por IP; `LIMIT_CRITICO = "30/minute"` para acciones de pago.
- **Auditoría:** `registrar_auditoria(db, tenant_id, usuario_id, accion, entidad, entidad_id, detalle)`
  acepta `usuario_id=None` (FK `SET NULL`) → sirve para acciones automáticas.
- **Migraciones:** última es `066_cupos_sin_tope_open_box.py` → la nueva sería
  `067_pagos_mercadopago.py`, con docstring explicando el *por qué* (estilo del repo).
- **Entornos:** `ENVIRONMENT=production` usa `.env`; si no, `.env.test` (gitignored).
  Los secretos van en Render Environment Groups con `sync: false`.
- **Pruebas:** integración contra `localhost:8000` (el `conftest` aborta si el server
  no es TEST) + tests "front" que leen el fuente sin red ni BD.

---

## 3. Enfoque técnico: Checkout Pro vs Checkout Bricks vs Checkout API

| | **Checkout Pro** (Preferences API) | **Checkout Bricks** | **Checkout API** (transparente) |
|---|---|---|---|
| Frontend | sólo redirige a `init_point` | componente React `@mercadopago/sdk-react`, `public_key` | formulario propio + SDK JS, tokeniza tarjeta |
| Backend | crea preferencia, lee webhook | crea pago con `card_token` que manda el front | crea pago con `card_token`, 3DS, idempotencia explícita |
| PCI / seguridad | la tarjeta nunca pasa por el box | el box hospeda el iframe | el box maneja más flujo sensible |
| UX | el alumno sale a la pasarela y vuelve | todo dentro de la app | todo dentro de la app |
| Dependencias nuevas | **ninguna** en el front; `mercadopago` (Python) en el back | SDK JS + backend | SDK JS + backend |
| Esfuerzo / riesgo | bajo | medio | alto (3DS, reintentos, idempotencia fina) |
| Mejor para | membresías (monto alto, pocas veces) | Bazar (muchas compras, monto chico) | checkout propio muy cuidado |

**Recomendación: Checkout Pro para la fase 1, en los dos flujos.**

Por qué, en este proyecto concreto:
1. El modelo actual ya es "documento de pago + confirmación". Checkout Pro cambia
   **sólo el medio de pago**: el webhook aprobado dispara *la misma* activación que
   hoy ejecuta el admin (ver §7). No hay que diseñar un checkout nuevo.
2. Menos superficie: no hay token de tarjeta ni 3DS en nuestro código, no hay
   `@mercadopago/sdk-react` que versionar en el front, y el front sólo hace
   `window.location.href = init_point`.
3. El `back_urls` no se usa para decidir nada (§6.7), así que la fricción de "salir
   de la app" no agrega riesgo, sólo un paso visual.

**Contras asumidos:** el alumno ve la marca de Mercado Pago y el retorno a la app es
una pantalla de "estamos confirmando"; la confirmación real llega por webhook (1-30 s).

**Evolución (no ahora):** si el Bazar crece, migrar **sólo el Bazar** a Bricks, que
reutiliza el mismo backend de `pagos` (la tabla y el webhook no cambian: cambia cómo
se crea el pago). Eso deja el cambio acotado a un endpoint y una pantalla.

---

## 4. Modelo de datos

### 4.1 Decisión central

- Tabla nueva **`pagos`** = fuente de verdad de la pasarela (estado del cobro).
- Tabla nueva **`pagos_eventos`** = bitácora de webhooks (idempotencia + trazabilidad).
- `transacciones_financieras` **no** cambia de estructura: se sigue escribiendo en la
  **misma** función que hoy, una sola vez, cuando el pago queda aprobado. La pasarela
  no escribe plata: dispara el mismo camino que el admin.
- `pedidos.total` (Bazar) sigue siendo la fuente del ingreso del Bazar: el pago
  aprobado mueve el pedido a `validado`, que es lo que el BI ya cuenta.

### 4.2 `pagos` (nueva)

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `Integer` PK | |
| `tenant_id` | FK `tenants` `ON DELETE CASCADE`, NOT NULL | índice `(tenant_id, created_at)` |
| `usuario_id` | FK `usuarios` `ON DELETE CASCADE`, NOT NULL | quién paga |
| `concepto` | `String(20)` NOT NULL + CHECK | `membresia` \| `bazar` \| `emergencia` |
| `referencia_tipo` | `String(30)` NULL | `solicitud_plan` \| `pedido` \| `suscripcion` |
| `referencia_id` | `Integer` NULL | sin FK (referencia polimórfica, igual que en `transacciones_financieras`) |
| `monto_clp` | `Integer` NOT NULL + CHECK `> 0` | **entero**, calculado en el backend |
| `moneda` | `String(3)` NOT NULL default `CLP` | |
| `estado` | `String(20)` NOT NULL + CHECK | ver §4.5 |
| `proveedor` | `String(20)` NOT NULL default `mercadopago` | deja la puerta abierta a otra pasarela |
| `preference_id` | `String(64)` NULL, UNIQUE | id de la preferencia de Checkout Pro |
| `payment_id` | `String(64)` NULL, UNIQUE | id del pago en MP (llega por webhook) |
| `external_reference` | `String(64)` NOT NULL, UNIQUE | UUID que mandamos a MP; **no** es el `id` de la fila (no se filtra un id secuencial a un tercero) |
| `metodo_pago` | `String(50)` NULL | `payment_method_id` (visa, master, …) |
| `tipo_pago` | `String(30)` NULL | `payment_type_id` (credit_card, debit_card, account_money, ticket) |
| `estado_detalle` | `String(60)` NULL | `status_detail` de MP (`cc_rejected_insufficient_amount`, …) |
| `pagado_en` | `TIMESTAMP(tz)` NULL | `date_approved` de MP |
| `detalle_json` | `JSONB` NULL | último snapshot del pago leído a MP (auditoría/depuración) |
| `created_at` / `updated_at` | `TIMESTAMP(tz)` NOT NULL | `server_default=now()` |

Índices: `(tenant_id, created_at)`, `(usuario_id, created_at)`, UNIQUE
`external_reference`, UNIQUE `payment_id`, UNIQUE `preference_id`,
`(referencia_tipo, referencia_id)`.

### 4.3 `pagos_eventos` (nueva)

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `Integer` PK | |
| `tenant_id` | FK `tenants` NULL | puede no saberse si el evento llega antes de crear el pago |
| `pago_id` | FK `pagos` `ON DELETE SET NULL`, NULL | |
| `proveedor` | `String(20)` NOT NULL | `mercadopago` |
| `notificacion_id` | `String(64)` NOT NULL, **UNIQUE** | el `id` (UUID) del body → dedupe exacto de reintentos |
| `tipo` | `String(30)` NULL | `payment`, `chargebacks`, … |
| `recurso_id` | `String(64)` NULL | el `data.id` (id del pago en MP) |
| `firma_valida` | `Boolean` NOT NULL | |
| `request_id` | `String(64)` NULL | header `x-request-id` |
| `ts_header` | `String(20)` NULL | `ts` del header `x-signature` |
| `resultado` | `String(40)` NULL | `aplicado` \| `duplicado` \| `monto_no_coincide` \| `desconocido` \| `error` |
| `recibido_en` | `TIMESTAMP(tz)` NOT NULL | |
| `procesado_en` | `TIMESTAMP(tz)` NULL | NULL = quedó pendiente de reintento/reconciliación |

Índices: UNIQUE `notificacion_id`, `(pago_id)`, `(recibido_en)`.
Retención: esta tabla se puede archivar/borrar a los 90 días (política B8 de
`docs/RETENCION_DATOS_Y_N8N.md`); `pagos.detalle_json` es lo que se conserva.

### 4.4 Cambios en tablas existentes (mínimos, aditivos)

| Tabla | Columna nueva | Para qué |
|---|---|---|
| `solicitudes_planes` | `pago_id` FK `pagos` `ON DELETE SET NULL`, NULL | trazar que esta solicitud se cobró online |
| `solicitudes_planes` | `origen_pago` `String(12)` default `manual` | `manual` \| `mercadopago` (el admin lo ve) |
| `pedidos` | `pago_id` FK `pagos` `ON DELETE SET NULL`, NULL | idem |
| `pedidos` | `origen_pago` `String(12)` default `manual` | idem |
| `suscripciones` | `pago_id` FK `pagos` `ON DELETE SET NULL`, NULL | trazabilidad del alta automática |

Nada de esto es `NOT NULL` ni rompe filas viejas: los registros históricos quedan
`manual` / `NULL`, que es exactamente lo que son.

### 4.5 Mapa de estados (MP → interno)

| `status` de MP | `pagos.estado` | ¿Activa el beneficio? |
|---|---|---|
| `approved` | `aprobado` | **Sí** |
| `pending` | `pendiente` | No |
| `in_process` / `authorized` | `en_proceso` | No |
| `rejected` | `rechazado` | No (se puede reintentar con otro medio) |
| `cancelled` | `cancelado` | No |
| `refunded` / `charged_back` | `reembolsado` | No (si ya estaba aplicado → **alerta al admin**, no se revierte solo) |
| (preferencia creada, sin pago) | `pendiente` | No (expira por job) |

`pagos.estado` **no** replica los strings de MP: se traducen en un mapa único, en un
solo módulo, testeable sin red (`tests/test_pagos_mercadopago_estados.py`).

---

## 5. Endpoints propuestos

Router `app/api/v1/pagos.py`, incluido en `main.py` con `prefix="/api/v1/pagos"`.

| Método | Ruta | Quién | Qué hace |
|---|---|---|---|
| `POST` | `/pagos/membresia` | alumno (`get_current_user` + `require_full_access`) | Recibe `{plan_id, certificado_estudiante_url?}`. Recalcula precio en el backend (snapshot de beneficios/referidos, la misma aritmética que hoy), crea `SolicitudPlan` (`pending`, `origen_pago='mercadopago'`) + fila `pagos` (`pendiente`) + preferencia en MP. Devuelve `{pago_id, init_point}` |
| `POST` | `/pagos/bazar` | alumno (`require_full_access`) | Recibe `{producto_id, cantidad}`. Valida y **crea el pedido en `pendiente`** (mantiene el descuento atómico de stock de hoy) + `pagos` (`pendiente`) + preferencia MP. Devuelve `{pago_id, init_point}` |
| `GET` | `/pagos/{id}` | dueño del pago o staff del tenant | Estado del pago + si ya se aplicó. Lo usa la pantalla de retorno (polling corto) |
| `POST` | `/pagos/webhook/mercadopago` | **nadie** (público, firmado) | Ver §6 |
| `POST` | `/pagos/{id}/reintentar` (fase 2) | alumno | Nueva preferencia sobre el mismo concepto, reusando la fila `pagos` si sigue `rechazado`/`cancelado` |
| `GET` | `/pagos` (fase 2) | admin | Listado con filtros por estado/fecha para conciliar contra el panel de MP |

Reglas de estos endpoints:
- `monto_clp` **siempre** se calcula server-side; el front nunca manda plata.
- `tenant_id` y `usuario_id` salen del JWT.
- Rate limit `LIMIT_CRITICO` (`30/minute`) en los `POST` de creación.
- Si `MERCADOPAGO_HABILITADO` es `false` o faltan credenciales → **503** con mensaje
  claro ("El pago online no está disponible; usa transferencia"), nunca 500 ni un
  `init_point` vacío.
- El JSON de error nunca incluye el access token ni el cuerpo crudo de MP.

---

## 6. Webhook: el punto crítico de seguridad

Ruta pública `POST /api/v1/pagos/webhook/mercadopago` (sin `Depends(get_current_user)`).

### 6.1 Verificación de firma

MP manda dos headers: `x-signature` (`ts=1704908010,v1=<hmac>`) y `x-request-id`, y el
`data.id` viene en la query (`?data.id=123456&type=payment`). El manifest que se firma
es `id:<data.id>;request-id:<x-request-id>;ts:<ts>;` con HMAC-SHA256 y el **secreto del
webhook** (distinto del access token).

Se usa el validador del SDK oficial (`WebhookSignatureValidator.validate(...)`, tolerancia
de 300 s) en vez de reimplementar el HMAC: menos chance de equivocarse en el formato y
en el *lowercase* del `data.id` alfanumérico. Firma inválida o ausente → **401**, se
registra el intento (IP + `request_id`, sin loguear la firma completa ni el secreto) y
no se toca la base de negocio.

**Fail-closed:** si `MERCADOPAGO_WEBHOOK_SECRET` está vacío, el endpoint responde 503 y
no procesa nada. Nunca "aceptar porque no hay secreto configurado".

### 6.2 No se confía en el body

El body sólo aporta **ids** (`type`, `data.id`, `id` de la notificación). El estado,
monto y referencia reales se leen con
`sdk.payment().get(payment_id)` usando el access token del servidor. Un body
manipulado no puede declarar "aprobado".

### 6.3 Idempotencia (doble candado)

1. `INSERT` del evento en `pagos_eventos` con UNIQUE en `notificacion_id`
   (`ON CONFLICT DO NOTHING`). Si ya existía y `procesado_en IS NOT NULL` → **200** sin
   reprocesar.
2. El efecto de negocio está guardado por estado: sólo se aplica si
   `pagos.estado IN ('pendiente','en_proceso')` y el `UPDATE` es condicional
   (`UPDATE ... WHERE id=:id AND estado='pendiente'`), el mismo patrón que ya usa el
   proyecto para aprobar solicitudes y descontar stock. Si `rowcount=0` → ya estaba
   aplicado → `duplicado`.

### 6.4 Validaciones antes de aplicar

- `external_reference` debe existir en `pagos` (si no → `desconocido`, 200 y alerta).
- `transaction_amount` debe coincidir con `pagos.monto_clp` **y** `currency_id` con
  `moneda`. Si no coincide → **no se aplica nada**, `resultado='monto_no_coincide'` y
  notificación a los admins del box.
- El pago debe pertenecer a una preferencia nuestra (`preference_id` guardado).

### 6.5 Respuesta rápida

MP espera 200/201 en pocos segundos y reintenta si no. Se responde **200
`{"ok": true}`** apenas se valida la firma y se encola el procesamiento
(`BackgroundTasks`, ya usado en el proyecto); el trabajo pesado (llamar a MP, activar el
plan) corre después. Si algo falla en el proceso, el evento queda
`procesado_en=NULL` y la reconciliación (§6.6) lo levanta — **no** se devuelve 5xx por
un pago ya aplicado, porque eso genera reintentos inútiles.

### 6.6 Reconciliación (los webhooks se pierden)

- Job/script `backend/maintenance/reconciliar_pagos.py`: busca `pagos` en
  `pendiente`/`en_proceso` con más de 15 minutos y consulta MP por
  `external_reference`; aplica el resultado con la misma función del webhook.
- `GET /pagos/{id}` también puede "auto-sanar" al leer (patrón que ya existe en el
  proyecto para niveles), pero sólo para el dueño del pago.
- Los `pagos` `pendiente` con más de 24 h sin pago pasan a `expirado` (liberando lo que
  corresponda, ver §7.3).

### 6.7 Lo que NO se hace

- No se usa `back_urls` ni el `status` de la URL de retorno para activar nada: el alumno
  puede cerrar el navegador, y cualquiera puede visitar la URL a mano.
- No se acepta `topic=merchant_order` como confirmación de pago (no dice si se cobró).
- No se confía en `live_mode` para lógica (sólo se registra): con credenciales de
  prueba MP puede devolver `live_mode=false` y eso no debe cambiar el flujo.
- No hay allow-list de IP (MP no publica rangos estables para webhooks): el control es
  la firma.

---

## 7. Cómo se enchufa con los flujos actuales

Esta es la parte que decide si la integración sale bien o termina con dos verdades
(el admin aprueba por un lado y la pasarela activa por otro, con planes duplicados).

### 7.1 Refactor previo obligatorio: una sola función de "aprobar"

Antes de escribir una línea de Mercado Pago hay que **sacar la lógica de aprobación de
los endpoints**:

| Hoy (dentro del endpoint) | Mañana (servicio) |
|---|---|
| `PUT /solicitudes/{id}/aprobar` → `UPDATE ... WHERE estado='pending'` + `Suscripcion` + `TransaccionFinanciera` + expirar suscripciones viejas + auditoría + correo (`solicitudes_planes.py:412-646`) | `app/services/aprobacion_planes.py::activar_plan(db, solicitud, actor_id=None, origen='manual')` |
| `PUT /pedidos/{id}/estado` (`pendiente`→`validado`: `codigo_retiro` + aviso) | `app/services/pedidos_estado.py::marcar_validado(db, pedido, actor_id=None, origen='manual')` |
| `POST /pedidos/{id}/rechazar` (motivo + devolver stock + aviso con `texto_rechazo`) | `...::rechazar_pedido(db, pedido, motivo, actor_id=None)` |

Los endpoints quedan como *wrappers* delgados (mismas validaciones, mismos códigos y
mensajes, mismo `LIMIT_CRITICO`). Criterio de aceptación del refactor: **los tests de
integración de aprobar/rechazar/entregar pasan sin tocarlos**. `actor_id=None` es
válido: `solicitudes_planes.aprobado_por` y `auditoria.usuario_id` son `nullable`, así
que una aprobación automática se distingue de una humana sin inventar un "usuario
sistema".

Así, el webhook **no reimplementa** la activación: llama a la misma función que el
admin. Un bug de negocio se arregla una vez y vale para los dos caminos.

### 7.2 Membresía — secuencia

1. `POST /pagos/membresia` valida lo mismo que hoy (plan del tenant, `require_full_access`,
   que no tenga suscripción vigente) y calcula el precio **con la aritmética existente**
   (ficha del plan + descuentos F2/F3b). Ese número se congela en `pagos.monto_clp`
   y en el snapshot de la solicitud.
2. Crea `SolicitudPlan` (`pending`, `voucher_url=NULL`, `origen_pago='mercadopago'`) +
   `Pago` (`pendiente`, `external_reference=<uuid4>`) y recién entonces pide la
   preferencia a MP (si MP falla, la fila queda `pendiente` y expira sola). Guarda
   `preference_id` y devuelve `init_point`.
3. Alumno paga → webhook `approved` → `pagos.estado='aprobado'` (UPDATE condicional) →
   `activar_plan(solicitud, actor_id=None, origen='mercadopago')` → suscripción activa,
   `TransaccionFinanciera`, auditoría (`accion='PAGO_APROBADO'`, `detalle` con
   `payment_id`, `metodo_pago`, `monto`) y los correos/avisos de siempre.
4. Rechazado/cancelado → `pagos` queda así y la solicitud **sigue `pending`** para que
   el alumno reintente desde la app (no se crea basura en la cola del admin).
5. Sin pago en 24 h → job: `pagos.estado='expirado'` y solicitud a `rejected` con
   `comentario_admin='Pago online no completado'` (así sale de la cola de pendientes).

**Efecto colateral a resolver en el front:** el admin ve solicitudes **sin voucher**.
`GET /solicitudes/{id}/voucher` daría 404 y la UI mostraría un error. Hay que mostrar
un badge "Pagado online (MP)" con `payment_id` en lugar del enlace al comprobante, tanto
en la lista de pendientes como en el historial del alumno.

### 7.3 Bazar — secuencia y la trampa del stock

Hoy el pedido nace `pendiente` y **descuenta stock al crearse** (UPDATE atómico). Se
mantiene igual, porque reservar stock al pagar sería peor: dos alumnos podrían pagar la
última polera y habría que devolver uno.

1. `POST /pagos/bazar` reusa la creación de pedido (misma validación de `activo`, stock y
   `require_full_access`), le pone `origen_pago='mercadopago'` y `pago_id`, y devuelve
   `init_point`.
2. Pago `approved` → `marcar_validado(...)` (genera `codigo_retiro`, avisa). El BI sigue
   contando el ingreso por `pedidos.estado`, sin transacción nueva → **no se duplica**.
3. Pago rechazado/cancelado o 30 min sin pagar → `rechazar_pedido(..., motivo='Pago
   online no completado')`, que **devuelve el stock** con el mismo camino ya probado.
4. Si un pago se aprueba DESPUÉS de ese vencimiento (pasa con medios "en efectivo", que
   se acreditan días después): el pedido ya está rechazado → **no se revive**; se avisa a
   los admins para devolver el dinero o reponer stock a mano. Mitigación: en el Bazar
   limitar la preferencia a medios inmediatos (tarjeta y dinero en cuenta, sin
   `ticket`), o estirar el vencimiento si se aceptan.

### 7.4 Reglas transversales

- El webhook **nunca crea** solicitudes ni pedidos: sólo cambia el estado de algo que ya
  existe con `pago_id` vinculado. Por eso un evento repetido o fuera de orden es inocuo.
- Un pago sólo puede aplicar a **un** concepto, y un concepto a **un** pago aprobado
  (UNIQUE parcial en `pagos(payment_id)` + chequeo de estado).
- La comisión de MP **no** se resta del monto del negocio: el ingreso se registra bruto
  (lo que paga el alumno) y la comisión, si se quiere contabilizar, es un egreso aparte
  con su categoría. Si se neteara, el MRR y los reportes dejarían de cuadrar con los
  precios de lista.

---

## 8. Dependencias nuevas

### Backend

```
mercadopago==3.6.0      # SDK oficial (Python >= 3.9; el proyecto corre 3.12)
```

- Pin exacto, como el resto de `requirements.txt`.
- **Verificar antes de mergear** (`pip index versions mercadopago` y un `pip install`
  en un venv limpio): que la versión fijada exista, qué transitivas arrastra y que el
  build del contenedor/`render.yaml` siga completo. Es el único punto donde una
  dependencia nueva puede romper el deploy.
- El SDK se usa **sólo** en el backend; el access token nunca sale de ahí.

### Frontend

- **Ninguna** dependencia nueva si se usa Checkout Pro con redirect (`init_point`).
- Sólo si más adelante se pasa a Bricks: `@mercadopago/sdk-react` + `VITE_MERCADOPAGO_PUBLIC_KEY`.

### Desarrollo local (no va al repo)

- Un túnel (`cloudflared` o `ngrok`) para que MP alcance el webhook en `localhost`.
  En Render TEST ya hay URL pública y no hace falta.

---

## 9. Variables de entorno

| Variable | Dónde | Default | Notas |
|---|---|---|---|
| `MERCADOPAGO_HABILITADO` | backend | `false` | Interruptor maestro. En `false` no se muestra el botón ni se crean preferencias (503). Permite mergear sin encender nada |
| `MERCADOPAGO_MODO` | backend | `test` | `test` \| `production`. Decide si se usa `sandbox_init_point` y qué credenciales deberían estar cargadas |
| `MERCADOPAGO_ACCESS_TOKEN` | backend (secreto) | `""` | `APP_USR-…` / `TEST-…`. El de test y el de producción son distintos |
| `MERCADOPAGO_PUBLIC_KEY` | backend (secreto no crítico) | `""` | Sólo hace falta con Bricks. En Checkout Pro puro no se usa |
| `MERCADOPAGO_WEBHOOK_SECRET` | backend (secreto) | `""` | Firma del webhook. **Distinto** del access token. Vacío = webhook 503 (fail-closed) |
| `MERCADOPAGO_BACK_URL_BASE` | backend | `""` | Opcional; si está vacío se deriva de `FRONTEND_URL` |
| `MERCADOPAGO_NOTIFICATION_URL` | backend | `""` | Opcional; si está vacío se deriva de `BACKEND_PUBLIC_URL` + `/api/v1/pagos/webhook/mercadopago` |
| `VITE_MERCADOPAGO_PUBLIC_KEY` | frontend | — | Sólo Bricks. Nunca el access token |

Cómo se declaran (patrón vigente del repo):
- `app/core/config.py`: campos con default `""` / `False`, para que la app arranque sin
  credenciales y el fallo sea un 503 explícito, no un `ImportError` ni un 500.
- `.env.example`: **sólo los nombres**, con valor vacío y un comentario.
- `render.yaml`: `sync: false` (el valor se carga a mano en el Environment Group); nunca
  un valor en el YAML.
- `.env.test` / `.env` locales: gitignored (verificado). El token real de test va ahí,
  jamás en un test, doc o commit.
- Prohibido: pegar el token en un test, en este doc, en un log o en el frontend.

---

## 10. Estructura de archivos propuesta

### Backend (nuevo)

```
backend/app/models/pago.py                  # Pago + PagoEvento
backend/app/schemas/pago.py                 # PagoCreateMembresia, PagoCreateBazar, PagoResponse
backend/app/services/mercadopago_cliente.py # SDK: crear preferencia, leer pago, mapa de estados
backend/app/services/pagos.py               # orquestación: crear, aplicar resultado, idempotencia
backend/app/services/aprobacion_planes.py   # activar_plan()  ← refactor de solicitudes_planes
backend/app/services/pedidos_estado.py      # marcar_validado() / rechazar_pedido() ← refactor de pedidos
backend/app/api/v1/pagos.py                 # endpoints (§5)
backend/alembic/versions/067_pagos_mercadopago.py
backend/maintenance/reconciliar_pagos.py    # job de reconciliación / expiración
```

### Backend (editado, cambios chicos)

```
backend/requirements.txt        # + mercadopago==3.6.0
backend/app/core/config.py      # + 7 campos MERCADOPAGO_*
backend/app/main.py             # + include_router(pagos.router, prefix="/api/v1/pagos")
backend/app/models/solicitud_plan.py / pedido.py / suscripcion.py   # + pago_id, origen_pago
backend/app/api/v1/solicitudes_planes.py / pedidos.py               # wrappers del servicio
backend/.env.example · render.yaml                                   # nombres de variables
```

### Frontend (editado / nuevo)

```
frontend/src/hooks/queries.js                     # useCrearPagoMembresia, useCrearPagoBazar, usePago
frontend/src/pages/alumno/SolicitarPlan.jsx       # botón "Pagar online" junto a "Subir comprobante"
frontend/src/pages/alumno/Bazar.jsx               # ídem al confirmar la compra
frontend/src/pages/alumno/PagoResultado.jsx       # retorno de MP: "confirmando…" + polling a GET /pagos/{id}
frontend/src/App.jsx                              # ruta de retorno
frontend/src/pages/admin/Solicitudes.jsx          # badge "Pagado online" (sin enlace a voucher)
frontend/src/pages/admin/Pedidos.jsx              # ídem
```

### Docs / tests

```
docs/DISENO_PAGOS_MERCADOPAGO.md                  # este documento
backend/tests/test_pagos_mercadopago_estados.py   # unitario puro: mapa de estados + montos
backend/tests/test_pagos_webhook_firma.py         # firma inválida/válida/faltante, sin red
backend/tests/test_pagos_preferencia_failfast.py  # sin credenciales o deshabilitado → 503
backend/tests/test_pagos_boton_front.py           # patrón "front": el botón sólo aparece si está habilitado
```

---

## 11. Plan por fases (para mañana)

| Fase | Qué entra | Criterio de aceptación |
|---|---|---|
| **0. Diseño** | este documento | revisado y aprobado por el usuario |
| **1. Cimientos sin cobrar** | migración 067, modelos `pagos`/`pagos_eventos`, `MERCADOPAGO_*` en `config.py`, `requirements.txt`, módulo de estados, validador de firma | `/health` sigue verde; `pytest` de estados y firma en verde; nada de Mercado Pago visible en la app |
| **2. Refactor de aprobación** | `aprobacion_planes.py` + `pedidos_estado.py`, endpoints como wrappers | tests de integración actuales (aprobar, rechazar, entregar, stock) pasan **sin modificarlos** |
| **3. Membresía con Checkout Pro** | `POST /pagos/membresia`, preferencia, webhook, `GET /pagos/{id}`, botón en `SolicitarPlan.jsx`, pantalla de retorno, badge en admin | pago de prueba `approved` → plan activo + 1 sola `TransaccionFinanciera`; webhook repetido → no duplica; pago rechazado → nada se activa; firma inválida → 401 |
| **4. Bazar** | `POST /pagos/bazar`, validación de pedido, expiración a 30 min con devolución de stock | stock vuelve al expirar; aprobado → `validado` + `codigo_retiro`; el BI no duplica ingresos |
| **5. Operación** | reconciliación, listado admin de pagos, reembolsos/contracargos (`chargebacks`) | un pago con webhook perdido se recupera; un reembolso genera alerta |

Reglas de trabajo: una rama `feature/pagos-mercadopago` (hoy el repo está en `main`;
**no** implementar sobre `main`), commits chicos, `run_tests.bat` sólo cuando el usuario
lo pida, y `MERCADOPAGO_HABILITADO=false` por defecto en cada fase.

### Prueba manual imprescindible antes de decir "funciona"

1. En el panel de MP, cuenta de prueba + **usuarios de prueba** (comprador `TESTUSER…`).
2. Pagar con las tarjetas de prueba (aprobada / rechazada / pendiente).
3. Verificar en la base: `pagos.estado`, `pagos.payment_id`, `suscripciones`, **una**
   fila en `transacciones_financieras`, `auditoria` con `usuario_id NULL`.
4. Reenviar el webhook desde el panel de MP (o con `curl` firmado) y comprobar que no
   duplica.
5. Mirar el `live_mode` que devuelve MP: con credenciales de prueba puede venir en
   `false`; si el flujo depende de eso, hay un bug.

---

## 12. Decisiones abiertas (necesito tu respuesta)

**RESUELTAS por el dueño (2026-10-29):**

- **12.1 (¿el pago aprobado activa el plan?)** → **SÍ, automático.** El webhook llama
  a `activar_plan(..., origen='mercadopago')`; la transferencia sigue con aprobación
  manual.
- **12.2 (¿una cuenta de MP o una por box?)** → **UNA sola cuenta** para todo el
  sistema (hoy sólo Urban Box usa el servicio). No hay credenciales por tenant.
- **12.5 (convivencia)** → **CONVIVEN**: el botón "Pagar con Mercado Pago" se suma al
  flujo de transferencia en plan y Bazar, y el admin ve un badge "Pagado online ✓"
  cuando no hay voucher.

Siguen abiertas (no bloquean esta fase, se aplicaron los criterios recomendados):

1. **¿El pago aprobado activa el plan automáticamente?** (recomiendo sí: MP ya confirmó
   la plata; la revisión humana existe para validar un comprobante, no para desconfiar
   de la pasarela). Alternativa conservadora: deja la solicitud `pending` y el admin
   aprieta "Aprobar" igual que hoy.
2. **¿Una sola cuenta de Mercado Pago para todos los boxes, o una por box?** Con una
   sola cuenta, el dinero de todos los tenants cae junto: sirve para un box, **no** para
   un SaaS multi-box. Si hay más de un box en producción, esto es bloqueante y hay que
   decidir entre credenciales por tenant (cifradas en BD) o no habilitar MP por ahora.
3. **Comisión de MP:** ¿la absorbe el box (recomiendo) o se le suma al alumno? Si se le
   suma, el precio que ve el alumno no coincide con el de lista y hay que mostrarlo
   desglosado.
4. **Bazar:** ¿se aceptan medios "en efectivo" (que se acreditan días después) o sólo
   tarjeta/dinero en cuenta? Afecta el vencimiento del pedido y la devolución de stock.
5. **Convivencia:** ¿sigue existiendo "transferencia + comprobante" con el pago online
   como opción (recomiendo), o el pago online lo reemplaza?
6. **`comprar-emergencia`:** hoy activa el plan sin registrar `TransaccionFinanciera`.
   ¿Se cobra online también? Si sí, hay que decidir si pasa a registrar ingreso (y
   entonces cambia el MRR histórico, no sólo el flujo nuevo).
7. **Retención de `pagos_eventos`:** ¿90 días y listo, alineado a B8?

---

## 13. Estado del repo al terminar la implementación

- Rama: `feature/pagos-mercadopago` (creada desde `main`). **Sin push.**
- `MERCADOPAGO_HABILITADO=false` por default: la rama se puede desplegar sin encender
  nada (el botón no aparece y los `POST` responden 503 con "usa transferencia").
- La migración **067 se aplicó sólo a la branch TEST** (para poder correr los tests de
  integración). PROD queda pendiente: la corre el `preDeployCommand` de `render.yaml`
  en el próximo deploy.
- Tests: **46 aislados** (estados, montos, firma, HTTP fail-closed, guard de fuente del
  front) + **6 de integración** contra TEST, en verde.

---

## 14. Implementación (2026-10-29)

### Archivos nuevos

| Archivo | Qué es |
|---|---|
| `backend/alembic/versions/067_pagos_mercadopago.py` | `pagos` + `pagos_eventos` + `pago_id`/`origen_pago` |
| `backend/app/models/pago.py` | `Pago`, `PagoEvento`, `ESTADOS_PAGO`, `ESTADOS_PAGO_ABIERTOS` |
| `backend/app/schemas/pago.py` | requests/responses del checkout (sin montos) |
| `backend/app/services/mercadopago_cliente.py` | config fail-fast, mapa de estados, preferencia, lectura del pago, firma |
| `backend/app/services/pagos.py` | orquestación: crear cobro, aplicar resultado, idempotencia, expiración |
| `backend/app/services/aprobacion_planes.py` | `activar_plan()` ← refactor de `solicitudes_planes` |
| `backend/app/services/pedidos_estado.py` | `marcar_validado()` / `marcar_entregado()` / `rechazar_pedido()` |
| `backend/app/api/v1/pagos.py` | endpoints + webhook |
| `backend/maintenance/reconciliar_pagos.py` | expiración + reconciliación (`--dry-run` por default) |
| `backend/tests/test_pagos_mercadopago_estados.py` | estados, montos, config, firma, preferencia (29) |
| `backend/tests/test_pagos_webhook_firma.py` | fail-closed HTTP + firma + duplicado (10) |
| `backend/tests/test_pagos_boton_front.py` | guard de fuente del front (7) |
| `backend/tests/test_pagos_mercadopago_integracion.py` | integración contra TEST (6) |
| `frontend/src/pages/alumno/PagoResultado.jsx` | retorno de Checkout Pro con polling |

### Archivos editados

`requirements.txt` (`mercadopago==3.6.0`), `app/core/config.py` (7 variables),
`app/main.py` (router), `models/{solicitud_plan,pedido,suscripcion}.py`,
`api/v1/{solicitudes_planes,pedidos}.py` (wrappers), `schemas/pedido.py`,
`hooks/queries.js`, `App.jsx`, `alumno/{SolicitarPlan,Bazar}.jsx`,
`components/pendientes/{PanelSolicitudes,PanelPedidos}.jsx`, `admin/Pedidos.jsx`,
`backend/.env.example`, `render.yaml`.

### Decisiones menores (no estaban en el diseño)

1. **`GET /pagos/disponibilidad`** (nuevo, público): el front necesita saber si mostrar
   el botón y no puede leer una env var del backend. Devuelve sólo un booleano.
2. **El precio final se congela al CREAR el pago online** (`precio_final_clp = monto`).
   Consecuencia: un descuento de **referido** no se aplica a una compra online (el
   referido se resuelve recién al aprobar y MP ya cobró el precio de lista). Es la
   única forma de que la `TransaccionFinanciera` coincida con el cobro real.
3. **`/pagos/bazar` crea el pedido con `total` entero en CLP** (`float(total)` para la
   columna): MP no acepta decimales con `currency_id=CLP`.
4. **La expiración del Bazar es de 30 min y la de membresía de 24 h**, y corre en el
   script de mantenimiento (no en el scheduler todavía): hay que agendarlo.
5. **`reconciliar_pagos.py` escribe sólo con `--aplicar`** (default dry-run).
6. **Concurrencia del `activar_plan`**: el webhook y un admin aprobando a la vez se
   serializan con el `UPDATE ... WHERE estado='pending'`; el segundo recibe
   `duplicado`/400 y no crea nada.
7. **`GET /pagos/{id}` no "auto-sana"**: sólo el webhook (o la reconciliación) escribe
   el estado. Un GET no puede mover dinero.






