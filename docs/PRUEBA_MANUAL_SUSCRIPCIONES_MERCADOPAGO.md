# Prueba manual: suscripción recurrente creada desde el box

**Fecha:** 2026-10-31
**Rama:** `feature/pagos-mercadopago`
**Qué se prueba:** `POST /api/v1/pagos/suscripcion` crea el `preapproval` en MP
("Planes y suscripciones") y el webhook deja la fila `activo` y registra el cobro
recurrente en `pagos`. No hay UI todavía: se prueba con el panel de MP + `curl`.

**Requisitos previos**

- `MERCADOPAGO_HABILITADO=true` y credenciales **TEST** en el entorno.
- En el panel de MP (tema **Planes y suscripciones**) la URL de notificación
  apunta al backend público: `https://<dominio>/api/v1/mp/webhook`. El
  `preapproval` no lleva `notification_url`, así que sin esto no llega nada.
- `MERCADOPAGO_BACK_URL_BASE` (o `FRONTEND_URL`) en **https**: con `http` el
  `back_url` se omite y el alumno no vuelve a la app, aunque el cobro igual se
  registra.
- Un alumno de prueba con token JWT y sin plan vigente del mismo tipo.

---

## 1. Pedir el checkout recurrente

```bash
curl -sS -X POST https://<dominio>/api/v1/pagos/suscripcion \
  -H "Authorization: Bearer <TOKEN_ALUMNO>" -H 'Content-Type: application/json' \
  -d '{"plan_id": 3}'
```

Esperado: `200` con `{"suscripcion_id": N, "init_point": "https://...", "monto_clp": <precio de lista>, "estado": "pendiente"}`.
El monto tiene que ser el **precio de lista** del plan (sin descuento de referidos ni de compra).

## 2. Autorizar con el comprador de prueba

Abrir `init_point` en una ventana privada con el usuario **comprador de prueba**
(`TESTUSER...`, el mismo que se usa en Checkout Pro) y pagar con la tarjeta de
prueba `APRO`. MP devuelve a `/alumno/solicitar-plan?mp=suscripcion&suscripcion=N`
(la pantalla todavía no muestra nada especial: no hay UI de retorno para esto).

## 3. Verificar que el webhook hizo el trabajo

```sql
SELECT id, estado, mp_estado, mp_preapproval_id, fecha_inicio, fecha_expiracion,
       creditos_disponibles
  FROM suscripciones WHERE id = N;
SELECT id, tipo, recurso_id, firma_valida, resultado, recibido_en
  FROM pagos_eventos ORDER BY id DESC LIMIT 5;
```

Esperado: `estado='activo'`, `mp_estado='authorized'`, `mp_preapproval_id` con el
id de MP, `fecha_inicio` = ahora y `fecha_expiracion` = `fecha_inicio` +
`duracion_dias` del plan (el periodo se abre al autorizar, no al crear el
checkout). En `pagos_eventos` tiene que haber una fila con
`tipo='subscription_preapproval'`, `recurso_id` = el id del `preapproval` y
`firma_valida=true`. El alumno ya ve el plan activo.

## 4. Ver el cobro recurrente registrado

Cuando MP cobra el primer periodo llega un `authorized_payment`:

```sql
SELECT id, concepto, referencia_tipo, referencia_id, monto_clp, estado,
       external_reference, proveedor
  FROM pagos WHERE referencia_tipo = 'suscripcion' AND referencia_id = N;
```

Esperado: una fila `concepto='membresia'`, `proveedor='mercadopago'`,
`external_reference='ap:<id del cobro>'` (clave de idempotencia: el mismo aviso
repetido no duplica la fila) y `estado` `aprobado`/`pendiente` según lo que diga
MP. **No** crea `transacciones_financieras` (la caja sigue entrando por la
aprobación manual; está anotado como pendiente).

## 5. Reintentos (los tres casos que tienen que quedar claros)

1. **Doble clic antes de autorizar:** repetir el `curl` con la suscripción todavía
   `pending` devuelve `200` con el **mismo** `suscripcion_id` y el **mismo**
   `init_point` (no se emiten dos `preapproval`).
2. **Ya autorizada:** repetir el `curl` devuelve `409` —"Ya tienes este plan
   activo…"— y no crea nada.
3. **Cancelada/pausada:** cancelar la suscripción en el panel de MP y repetir el
   `curl` devuelve `200` con una fila **nueva** y un `init_point` nuevo (una
   cancelada no se reusa). Si MP no responde al releer el `preapproval` anterior,
   el endpoint responde `503` y **no** emite otra: fail-closed, para no terminar
   con dos cobros recurrentes del mismo plan.
