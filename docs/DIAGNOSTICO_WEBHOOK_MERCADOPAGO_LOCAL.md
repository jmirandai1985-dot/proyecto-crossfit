# Diagnóstico: webhook de Mercado Pago no llega en local

**Fecha:** 2026-10-31
**Rama:** `feature/pagos-mercadopago`
**Entorno:** stack Docker local (`box-crossfit`: frontend/nginx `:80`, backend `:8001->8000`, maintenance), `backend/.env.test` → branch TEST de Neon (`ep-crimson-tooth-akhx7q2s`).
**Estado:** diagnóstico cerrado. **La prueba e2e NO se ejecutó** (decisión del usuario).

---

## 1. Objetivo

Validar el ciclo completo de pago con Checkout Pro en local: MP confirma el pago → webhook → el plan se activa solo (sin aprobación manual del admin).

Ya estaban resueltos y cubiertos por tests: el bug de `auto_return` (MP exige `https` en `back_urls.success`) y el cálculo del descuento de referido antes de generar el monto a cobrar.

---

## 2. Resultado

**Causa raíz: la preferencia que se crea en Mercado Pago lleva `notification_url` apuntando a `http://localhost:8001/...`.** MP llama al webhook desde sus servidores, donde `localhost` es MP mismo: la notificación nunca sale del lado de MP. No es un problema de firma, ni de puerto, ni del path de nginx.

Evidencia de que **nunca llegó ninguna notificación** (ni siquiera una rechazada):

- `pagos_eventos` tiene **0 filas** (la tabla registra también los intentos con `firma_valida=false`).
- `pagos` id 4 y 5 siguen en `pendiente`, con `payment_id = NULL`.

| Dato | Valor |
|---|---|
| Pago 5 | `pendiente`, 44.000 CLP, `usuario_id=9`, tenant 1 |
| Preferencia del pago 5 | `3796774888-e03b14c2-9246-476a-902e-cf7a25ba1419` |
| `notification_url` leída de MP (`GET /checkout/preferences/{id}`) | `http://localhost:8001/api/v1/pagos/webhook/mercadopago` |
| `back_urls` leídas de MP | `{"success":"","pending":"","failure":""}` |
| `auto_return` | vacío |

Las dos preferencias verificadas (pagos 4 y 5) tienen exactamente esa misma `notification_url`.

---

## 3. Qué se verificó que SÍ funciona

| Verificación | Comando | Resultado |
|---|---|---|
| Config en el contenedor | `docker exec box-crossfit-backend-1 printenv MERCADOPAGO_*` | `MERCADOPAGO_NOTIFICATION_URL=http://localhost:8001/api/v1/pagos/webhook/mercadopago`; `MERCADOPAGO_BACK_URL_BASE` y `MERCADOPAGO_MODO` **no definidas** (defaults) |
| Ruta nginx → backend | `curl.exe http://localhost/api/v1/pagos/webhook/mercadopago` | **405** (llega a FastAPI; el fallback SPA de nginx habría dado 200 con `index.html`) |
| Ruta directa al backend | `curl.exe http://localhost:8001/api/v1/pagos/webhook/mercadopago` | **405** |
| Pasarela habilitada | `curl.exe http://localhost/api/v1/pagos/disponibilidad` | `{"habilitado":true}` |
| Credencial de MP | `GET https://api.mercadopago.com/users/me` | cuenta **de prueba** (`nickname` `TESTUSER7982…`, `site_id` MLC): los cobros ahí son de sandbox, no mueven plata real |
| `backend/.env.test` versionado | `git check-ignore -v backend/.env.test` | ignorado por `backend/.gitignore:9` → no se puede commitear por accidente |

Conclusión parcial: **el camino `URL pública → nginx (:80) → backend:8000 → /api/v1/pagos/webhook/mercadopago` está OK**. Lo único que falta es que la URL sea alcanzable desde internet.
