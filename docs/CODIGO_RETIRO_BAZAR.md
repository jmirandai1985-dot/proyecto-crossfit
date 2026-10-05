# Código de retiro del Bazar

Retiro de un pedido del Bazar **con prueba**: el alumno muestra un código corto
(`UB-4827`) — y su QR — y quien atiende el mesón lo ingresa o lo escanea para cerrar
la entrega. Antes el retiro se hacía "de palabra" con el botón *Marcar entregado*: no
había forma de saber si quien retiraba era el dueño ni quedaba registro de quién y
cuándo entregó.

## Flujo

```
1. El admin VALIDA el pedido (comprobante revisado)
        └─► se genera el código UNA vez: UB-4827   (services/codigos_retiro.py)
        └─► campana del alumno: "Tu pedido fue validado. Código de retiro: UB-4827"

2. El alumno lo muestra: código destacado + QR en "Mis Pedidos"

3. El mesón lo ingresa o lo escanea (admin en /admin/pedidos, coach en
   /coach/entregar-pedido → mismo modal)
        └─► el pedido pasa a "entregado" con entregado_por + entregado_en
        └─► campana del alumno: "Tu pedido de X xN fue entregado"

4. Un código usado no se reutiliza: 409 "Este pedido ya fue entregado el … por …"
```

## Backend

| Pieza | Dónde |
|---|---|
| Formato, unicidad, normalización y textos | `app/services/codigos_retiro.py` (puro, sin HTTP) |
| Migración 044 (`codigo_retiro`, `entregado_por`, `entregado_en`) | `alembic/versions/044_pedidos_codigo_retiro.py` |
| Endpoints | `app/api/v1/pedidos.py` |
| Rate limit | `app/core/rate_limit.py` (`LIMIT_CODIGO_RETIRO = "10/minute"`) |

### Formato `UB-XXXX`

* alfabeto **sin caracteres ambiguos**: `23456789ABCDEFGHJKMNPQRSTUVWXYZ` (nada de
  `0/O`, `1/I/L`: se confunden leídos, dictados o en pantalla). `PATRON` se deriva del
  alfabeto, así que el formato y el alfabeto no pueden divergir;
* **único por box**, no global: índice único `uq_pedidos_codigo_retiro`
  (`tenant_id`, `codigo_retiro`). En Postgres varios `NULL` conviven: los pedidos sin
  validar no chocan;
* el CHECK `ck_pedidos_codigo_retiro_formato` garantiza el formato en la BD y es espejo
  del `PATRON` de Python;
* se normaliza lo que entra (`normalizar`): `"ub-4827"`, `" UB 4827 "`, `"4827"`,
  `"UB–4827"` (guion largo) → `UB-4827`. Basura o largo equivocado → 404.

### Endpoints

| Método y ruta | Quién | Qué hace |
|---|---|---|
| `PUT /pedidos/{id}/estado` (`validado`) | admin | genera el código (una sola vez) y avisa al alumno con el código |
| `POST /pedidos/entregar` `{codigo}` | admin **y coach del mismo box** | valida y cierra la entrega |
| `GET /pedidos/{id}/qr.svg` | dueño o staff del box | SVG del QR con **sólo el código** (lo lee cualquier lector) |
| `PUT /pedidos/{id}/estado` (`entregado`) | admin | **respaldo** sin código (también sella `entregado_por`/`entregado_en`) |

Respuestas de `POST /entregar`, en este orden:

* **404 genérico** — el código no existe *en este box*: uno de otro box es
  indistinguible de uno inexistente (no se filtra que exista en el vecino);
* **409** — el pedido sigue `pendiente` ("todavía no fue validado") o **ya se entregó**
  ("Este pedido ya fue entregado el 10/04/2026 19:30 por Ana Admin": fecha en hora de
  Chile + nombre de quien entregó);
* **200** — entregado. Devuelve **alumno, producto y cantidad, sin montos**: el coach
  entrega pedidos pero no administra el Bazar (no ve la lista ni los totales).

### Concurrencia

La entrega es un `UPDATE … WHERE estado = 'validado' … RETURNING rowcount`: si dos
mesones escanean el mismo código a la vez, **uno** entrega y el otro recibe el 409 de
"ya fue entregado" (mismo patrón que el descuento atómico de stock del Bazar).

## Quién ve qué

| Pantalla | Código | Lista de pedidos | Montos |
|---|---|---|---|
| `/admin/pedidos` (admin) | ✅ por fila + en el modal | ✅ con comprobante | ✅ |
| `/coach/entregar-pedido` (coach) | sólo lo ingresa/escanea | ❌ | ❌ |
| `/alumno/mis-pedidos` (dueño) | ✅ destacado + QR | sus pedidos | ✅ |

`GET /pedidos` sigue siendo el endpoint de **staff** (coach incluido) y no se tocó: la
restricción del coach es de pantalla (su panel no pide la lista ni pinta montos), como
el resto de sus vistas. El endpoint de entrega sí está cerrado con
`get_current_coach` (coach/admin del box) + rate limit.

## La decisión del botón "Marcar entregado" (respaldo)

**Propuesta aplicada: se conserva, sólo para el admin, como RESPALDO explícito.**

* el camino normal es el código (`📷 Entregar` por fila, o `Entregar con código` en el
  encabezado) y el panel del coach sólo entrega así;
* el botón viejo se renombró a **"Marcar entregado (respaldo)"** y su confirmación dice
  explícitamente que es un respaldo sin código y que queda registrado quién entregó;
* **por qué se deja**: casos reales — el alumno perdió el código, retira un tercero con
  autorización en el mesón, o el celular se quedó sin batería. Sin respaldo el box
  tendría que pedirle a soporte editar la BD;
* no se abre el respaldo al coach (nunca ve listados ni montos) y **sella igual**
  `entregado_por` / `entregado_en`, así que la traza no se rompe.

## Operación

* **TEST**: `cd backend && py -3.12 -m alembic upgrade head` (el `.env.test` se carga
  solo; la conexión de migraciones es la DIRECTA, sin pooler).
* **PROD**: el `preDeployCommand: alembic upgrade head` de Render la aplica en el
  deploy del commit que la incluye; si falla, Render aborta y deja la versión anterior.
* **Backfill**: los pedidos que ya estaban `validado` sin código reciben uno en la
  misma migración (idempotente: sólo toca `codigo_retiro IS NULL`). Los `pendiente`
  recibirán el suyo al validarse.

## Tests

```bash
cd backend
# Aislados (sin red ni BD): formato, unicidad, validaciones, normalización y wiring
py -3.12 -m pytest tests/test_codigos_retiro.py tests/test_codigo_retiro_front.py -q --noconftest
# Integración (requiere la API contra el branch TEST; NO se corre en la validación local)
py -3.12 -m pytest tests/test_pedido_entrega_codigo.py -q
```

Cobertura de la integración: código generado al validar + aviso con el código, 404 de
código inexistente, 200 del admin, 409 del reuso con fecha y nombre, 403 de un alumno,
200 del coach del box, **404 del coach de otro box**, QR por dueño (200) y por otro
alumno del box (403), y el respaldo sellando la traza.
