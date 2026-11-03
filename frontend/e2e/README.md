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
timeout). Si preferís el bundled, corré `npx playwright install chromium` y dejá
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
clase; en ese caso cancelá la reserva colgada del alumno o re-sembrá los usuarios de
carga (`python k6-tests/_seed_load_test.py`).

