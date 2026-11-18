# E2E (Playwright)

Arnés de tests end-to-end del frontend. Corre contra el **stack completo de TEST**.

## 1. Levantar el entorno completo

La BD es la rama TEST de Neon (externa), así que el stack completo se levanta con
Docker Compose:

```powershell
cd C:\Users\Asus\Desktop\Proyectos\proyecto-crossfit
docker compose up -d
```

Esto deja:

| Pieza   | URL                         |
|---------|-----------------------------|
| Frontend (build Vite + nginx) | http://localhost        |
| Backend (FastAPI)          | http://localhost:8001 (`/docs` = Swagger) |
| DB                        | rama TEST de Neon (`backend/.env.test`) |

> El `docker-compose.yml` base usa `backend/.env.test` (TEST) a propósito:
> `docker compose up -d` NUNCA toca producción por accidente. PROD requiere el
> override explícito `-f docker-compose.prod.yml`.

## 2. Instalar Playwright

```powershell
cd frontend
npm install -D @playwright/test
npx playwright install chromium   # opcional: navegador bundled
```

Los tests usan por defecto **Chrome del sistema** (`channel: 'chrome'`) para no
depender de la descarga del chromium bundled (que en esta red suele cortarse por
timeout). Si prefieres el bundled, corre `npx playwright install chromium` y deja
`E2E_BROWSER_CHANNEL` vacío.

## 3. Usuarios y contraseña

Los tests usan usuarios de carga ya sembrados en la rama TEST (los crea
`k6-tests/_seed_load_test.py` con la clave `TEST_SEED_PASSWORD`):

| Rol    | Correo                        |
|--------|-------------------------------|
| alumno | `carga_k6_alumno0001@load.test` |
| coach  | `carga_k6_coach@load.test`      |
| admin  | `carga_k6_admin@load.test`      |

La contraseña **no se versiona** (misma política de la Auditoría 4.1 del backend).
Setéala con `E2E_PASSWORD` tomándola de `backend/.env.test`:

```powershell
$env:E2E_PASSWORD = (Select-String -Path ..\backend\.env.test -Pattern '^TEST_SEED_PASSWORD=').Line.Split('=',2)[1]
```

> Si esos usuarios no existen (p. ej. tras un re-sync de TEST desde PROD),
> regeneralos con `python k6-tests/_seed_load_test.py` o con el seed canónico de
> prueba (`backend/scripts/seed_usuarios_prueba.py` +
> `backend/scripts/seed_apoyo_usuarios_prueba.py`).

## 4. Correr los tests

```powershell
cd frontend
$env:E2E_PASSWORD = '...'   # o exportarla desde backend/.env.test como arriba
npx playwright test
```

Sobrescribir base URL / navegador / correos si hace falta:

```powershell
$env:E2E_BASE_URL        = 'http://localhost'
$env:E2E_BROWSER_CHANNEL = 'chrome'   # o 'msedge'
$env:E2E_ALUMNO_EMAIL    = '...'
$env:E2E_COACH_EMAIL     = '...'
$env:E2E_ADMIN_EMAIL     = '...'
```

Reporte HTML: `npx playwright show-report`. Artefactos en `test-results/` y
`playwright-report/` (gitignored).

## 5. Qué cubre

- `tests/login-navegacion.spec.js`: login de alumno/coach/admin y que cada uno
  aterriza en su dashboard según rol, más navegación básica de cada panel.
- `tests/reservar-asistir.spec.js`: el alumno reserva una clase disponible por la
  UI, confirma que aparece en "Mis reservas" y se le marca la asistencia.
- `tests/planes-ui.spec.js`: regresiones de la UI de planes:
  - el admin puede **tipear** el monto de la matrícula y el input lo refleja
    (monta la pantalla real; un test de texto fuente no detectaba el onChange
    roto);
  - el filtro "Todos" del alumno muestra planes de ambos géneros.
- `tests/pago-membresia.spec.js`: flujo de pago de membresía con Mercado Pago
  **sandbox real** (Checkout Pro), sin mockear MP:
  - **a)** abandona antes de llegar a MP: el intento queda `iniciado`, no
    aparece en la cola del admin y el alumno puede cancelarlo.
  - **d)** segundo intento inmediato: el guard de 5 min lo bloquea con el
    mensaje esperado; a los 5 min reales se libera solo y el intento viejo queda
    `expirado` (se puede saltear la espera con `E2E_ESPERAR_GUARD_5MIN=0`, pero
    entonces sólo se verifica la liberación por Cancelar).
  - **b)** pago APROBADO con la tarjeta de prueba de MP (titular `APRO`):
    activación + transacción visible para el admin.
  - **c)** pago RECHAZADO (titular `OTHE`): solicitud `rejected` y reintento
    inmediato sin chocar con el guard.

### Pago de membresía: entorno y limitaciones

El spec usa `carga_k6_alumno0020@load.test` por defecto
(`E2E_PAGO_ALUMNO_EMAIL` lo cambia). Antes de cada test corre
`backend/scripts/limpiar_e2e_pago.py`, que en la rama TEST:

* cierra pagos `iniciado`/`pendiente` del alumno,
* saca de la cola sus solicitudes `iniciado`/`pending`,
* marca `vencido` su plan pago vigente (si no, la compra quedaría `en_cola`).

No es un mock: es limpieza de datos de TEST, con el mismo guard
(`ENVIRONMENT=test` + `is_test_db_url`) que los scripts de test.

Tarjetas de prueba MLC (documentación de Mercado Pago): Mastercard
`5416 7526 0258 2580`, CVV `123`, vencimiento `11/30`; el **nombre del titular**
elige el resultado (`APRO`, `OTHE`, `CONT`, ...). RUT de prueba: `11111111-1`.

Limitaciones verificadas en este entorno (se declaran como `skip` con motivo,
no se simulan):

1. **Credenciales MP de TEST (resueltas)**: `.env.test` usa el
   `test_access_token` (`TEST-…`) y la public key `TEST-…` de la MISMA app
   (`GET /applications/8755987062124145` con el token de la app devuelve
   `test_access_token`; el checkout usa su public key de prueba). Además,
   `MERCADOPAGO_TEST_BUYER_EMAIL` apunta al correo del test user collector:
   con el correo de otro test buyer el checkout devuelve 500. Verificación
   directa contra MP: card_token `live_mode=false`; pago APRO
   `approved/accredited` y OTHE `rejected/cc_rejected_other_reason` por
   `POST /v1/payments`.
   **Limitación restante**: en este entorno el checkout sandbox real llega a
   “Revisa tu pago” pero el botón **Pagar queda deshabilitado** (también en
   navegador headed) y no crea el pago; b/c se saltean con ese motivo. No se
   mockea el cobro. Es la misma limitación de
   `AUDITORIA_ABANDONO_PAGO_MERCADOPAGO.md`.
2. **Webhook inalcanzable**: `MERCADOPAGO_NOTIFICATION_URL` apunta a
   `http://localhost:8001/...`, que Mercado Pago no puede alcanzar desde
   Internet. Aun con un cobro aprobado/rechazado en el sandbox, la app no
   recibiría el aviso y el estado local no cambiaría. Se necesita un túnel
   público o el deploy de TEST para verificar la activación end-to-end.
3. **Botón físico de atrás**: no se puede simular en escritorio; el escenario
   **a)** aborta la navegación a MP y vuelve a la app, que es el efecto
   equivalente del lado de la aplicación (sin webhook ni pago).
4. **Reloj del guard**: no hay forma de inyectar el reloj del backend de TEST,
   así que **d)** espera los 5 minutos reales (timeout del test: 660 s). Con
   `E2E_ESPERAR_GUARD_5MIN=0` se saltea la espera y se verifica la liberación
   por Cancelar.

### Corrida de referencia (2026-11-17)

| Test | Resultado | Tiempo |
|---|---|---|
| a) abandona antes de MP | **passed** | 2.0 min |
| d) guard de 5 min (espera real) | **passed** | 9.1 min |
| b) pago APROBADO | **skipped** (checkout sandbox: “Pagar” deshabilitado) | 7.4 min ambos |
| c) pago RECHAZADO | **skipped** (checkout sandbox: “Pagar” deshabilitado) | 7.4 min ambos |

El skip de b/c **no es de credenciales**: el par de TEST quedó alineado
(`test_access_token` + public key `TEST-…`, card_token `live_mode=false`) y por
REST el mismo tipo de pago devuelve APRO `approved` y OTHE `rejected`. Lo que
no se puede completar en este entorno es el submit del checkout sandbox (el
botón “Pagar” queda deshabilitado en “Revisa tu pago”). No se simula el pago.




### Nota sobre "marcar asistencia"

El check-in por QR del alumno (`POST /api/v1/asistencia/qr/{publicId}/check-in`)
sólo marca cuando la clase está **en curso** (ventana de -60 min hasta el fin), por
lo que no es determinístico para un test automatizado. Por eso el E2E marca la
asistencia con el endpoint que ya usa el panel de Asistencia
(`PUT /api/v1/reservas/{id}/asistencia` con el admin), que es el mismo flujo de
check-in del staff sin depender de la hora de ejecución.

### Datos que escribe (TEST)

El flujo de reserva **escribe datos reales** en la rama TEST: crea una reserva y
luego le marca la asistencia. Para no acumular datos en corridas repetidas, el test
**cancela su propia reserva al final** (limpieza best-effort con `DELETE
/api/v1/reservas/{id}`). Si la limpieza no llegara a correr (p. ej. por un fallo
intermedio), la corrida siguiente puede chocar con "ya reservada" en esa misma
clase; en ese caso cancela la reserva colgada del alumno o re-siembra los usuarios de
carga (`python k6-tests/_seed_load_test.py`).

