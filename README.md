# Urban Training Box

SaaS de gestión para gimnasios y boxes de CrossFit: alumnos, planes, reservas, asistencia, bazar, reportes, fidelización, referidos y automatizaciones.

> **Estado:** proyecto en desarrollo activo. Hay una base **PROD** y una rama **TEST** en Neon (espejo de PROD con datos reales). Los scripts de test que hacen `TRUNCATE`/re-seed sólo deben apuntar a TEST.

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12, FastAPI 0.109, Uvicorn 0.27, SQLAlchemy 2.0, Alembic 1.13, Pydantic 2.5 (+ pydantic-settings) |
| Auth / seguridad | JWT (python-jose), passlib[argon2] + bcrypt, slowapi (rate limiting) |
| Pagos | Mercado Pago Checkout Pro (`mercadopago` 3.6) |
| Reportes / ML | pandas + openpyxl (export Excel), scikit-learn + numpy (churn y forecast de ingresos) |
| Frontend | React 19, Vite 8, Tailwind CSS 4, React Router 7, TanStack Query 5, Recharts 3 |
| Base de datos | PostgreSQL en Neon (ramas TEST y PROD separadas) |
| Storage | Cloudflare R2 en producción; disco local en desarrollo/TEST |
| Automatizaciones | APScheduler (interno) + Cron Jobs de Render; n8n opcional vía Docker Compose |
| Monitoreo | Sentry (opcional, `SENTRY_DSN`) |
| Tests | pytest + httpx (backend); scripts `.mjs` con Node (smoke/click del frontend) |

## Estructura del proyecto

```text
proyecto-crossfit/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # Endpoints REST por recurso
│   │   ├── core/            # Configuración, seguridad, tenant, logging, estados
│   │   ├── db/              # Sesión y base SQLAlchemy
│   │   ├── middleware/      # Middleware (seguridad, tenant, auditoría)
│   │   ├── models/          # Modelos SQLAlchemy
│   │   ├── private_uploads/ # Archivos privados (vouchers) en storage local
│   │   ├── schemas/         # Schemas Pydantic
│   │   ├── services/        # Reglas de negocio y servicios
│   │   ├── static/uploads/  # Archivos públicos (imágenes del Bazar) en storage local
│   │   └── utils/           # Utilidades (fechas de Chile, reglas de planes)
│   ├── alembic/             # Migraciones versionadas (alembic/versions/)
│   ├── maintenance/         # Scripts de jobs/cron: backups, KPIs, retención, planes en cola
│   ├── ml/                  # Modelos y entrenamiento (churn, forecast)
│   ├── scripts/             # Seeds, sincronización TEST/PROD, utilidades
│   ├── shared/              # Constantes compartidas (estados)
│   ├── tests/               # Tests (aislados, integración, guards de fuente)
│   ├── requirements.txt
│   ├── .env.example         # Plantilla (sin credenciales reales)
│   ├── .env                 # PROD local (gitignored)
│   ├── .env.test            # Rama TEST de Neon (gitignored)
│   ├── run_tests.bat        # Suite completa (destructiva sobre TEST)
│   └── start_server.py      # Arranque de uvicorn
├── frontend/
│   ├── src/
│   │   ├── components/      # Componentes compartidos (kpis, pendientes, historial)
│   │   ├── pages/
│   │   │   ├── admin/       # Panel de administración
│   │   │   ├── alumno/      # Panel del alumno
│   │   │   ├── coach/       # Panel del coach
│   │   │   └── tv/          # Vista para pantallas del box
│   │   ├── context/         # Contextos de React
│   │   ├── hooks/           # Hooks (queries, mutations)
│   │   ├── services/        # Cliente API (axios)
│   │   ├── config/          # Configuración del frontend
│   │   └── utils/           # Utilidades del frontend
│   ├── public/
│   ├── scripts/             # Scripts de capturas y smoke tests (.mjs)
│   ├── package.json
│   ├── vite.config.js       # Proxy /api y /static hacia :8000
│   ├── tailwind.config.js
│   └── .env.example
├── docs/                    # Documentación funcional, diseños y auditorías
├── k6-tests/                # Tests de carga (k6)
├── n8n/                     # Workflows de automatización (opcional)
├── sql/                     # Scripts SQL / esquemas
├── mockup/                  # Mockups de UI
├── logo/                    # Assets de marca
├── docker-compose.yml       # Stack local (TEST por defecto)
├── docker-compose.prod.yml  # Override de PRODUCCIÓN
├── Dockerfile.render        # Imagen combinada nginx + uvicorn (Render)
├── nginx.render.conf        # Proxy /api, /static, /health y /health/db
├── render.yaml              # Blueprint de Render (web service + cron jobs)
└── README.md
```

## Entorno local

### Requisitos

- Python 3.12
- Node.js 20+ y npm
- Git
- Acceso a una base PostgreSQL en Neon (o una instancia local compatible)

### Backend

```powershell
cd backend
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Crea tu archivo de entorno a partir de la plantilla (`backend/.env.example`, sin credenciales reales):

```powershell
# Desarrollo contra la rama TEST (recomendado):
copy .env.example .env.test

# O, para operar contra PROD local:
copy .env.example .env
```

Arranque:

```powershell
# TEST: sin ENVIRONMENT definida (o ENVIRONMENT=test) se carga .env.test
python start_server.py

# PROD local: definí ENVIRONMENT=production explícitamente
$env:ENVIRONMENT='production'; python start_server.py

# Alternativa equivalente (uvicorn directo):
py -3.12 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Liveness: `GET /health`
- Readiness (incluye `SELECT 1`): `GET /health/db`

> **Fail-safe de entorno:** sin `ENVIRONMENT` definida, el backend carga `backend/.env.test` (rama TEST) y **nunca** PROD. Para correr contra PROD hay que definir `ENVIRONMENT=production` de forma explícita.

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

- Frontend: `http://localhost:5173`
- `VITE_API_URL` puede quedar vacío en desarrollo: Vite proxea `/api` y `/static` hacia `http://localhost:8000`.
- Lint: `npm run lint` (oxlint). Build de producción: `npm run build` (vite build).

### Ambientes (TEST vs PROD)

- `backend/.env.test` → rama **TEST** de Neon (espejo de PROD con datos reales). Es el **SAFE DEFAULT**: lo carga cualquier proceso sin `ENVIRONMENT` o con `ENVIRONMENT=test`.
- `backend/.env` → **PROD** local (se carga sólo con `ENVIRONMENT=production`).
- `docker-compose.yml` usa `.env.test` (TEST). Para PROD: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
- `run_setup_test_db.py` reconstruye schema + seed de TEST (destructivo).
- No subas `.env`, `.env.test`, `.env.prod`, dumps ni backups al repositorio.

## Tests

Suite completa (destructiva sobre TEST):

```powershell
cd backend
run_tests.bat
# no interactivo:
run_tests.bat /y
```

> **Importante:** `run_tests.bat` hace `DROP SCHEMA public CASCADE` + re-seed sobre la branch TEST y mata cualquier uvicorn que escuche en el puerto 8000. Está protegido para no tocar PROD, pero verifica siempre el ambiente antes de correrlo.

Test aislado (integración contra TEST; escribe y restaura sus propios datos):

```powershell
cd backend
$env:ENVIRONMENT='test'
py -3.12 -m pytest tests/test_plan_en_cola.py -q --noconftest
```

Tests de fuente aislados (sin red ni base de datos):

```powershell
cd backend
py -3.12 -m pytest tests/test_salud_liveness_readiness.py --noconftest -q
py -3.12 -m pytest tests/test_codigo_retiro_front.py --noconftest -q
```

Los tests de integración que usan la API levantada en `localhost:8000` se ejecutan normalmente a través de `run_tests.bat` (orquestador `_run_tests_orchestrator.py`).

## Variables de entorno

Nombres solamente; los valores reales se configuran localmente o en el dashboard de Render y **nunca** se versionan.

### Backend (`backend/.env` / `.env.test`)

| Grupo | Variables |
|---|---|
| Entorno | `ENVIRONMENT` (`production` o `test`; controla qué `.env` se carga) |
| Base de datos | `DATABASE_URL`, `DIRECT_URL`, `DATABASE_URL_PROD` (sólo scripts de sincronización/auditoría) |
| Seguridad/JWT | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `SECRET_KEY` (legacy) |
| Aplicación | `APP_NAME`, `APP_VERSION`, `DEBUG` |
| URLs/CORS | `CORS_ORIGINS`, `FRONTEND_URL`, `BACKEND_PUBLIC_URL` |
| Correo | `EMAIL_MODO` (`real`/`noop`), `GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD` |
| Storage | `STORAGE_BACKEND`, `STORAGE_R2_ENDPOINT`, `STORAGE_R2_BUCKET`, `STORAGE_R2_PUBLIC_BUCKET`, `STORAGE_R2_ACCESS_KEY_ID`, `STORAGE_R2_SECRET_ACCESS_KEY`, `STORAGE_R2_PUBLIC_BASE_URL`, `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB` |
| Automatizaciones | `N8N_API_KEY`, `CRON_API_KEY`, `REACTIVACION_OPT_OUT_SECRET`, `SCHEDULER_ENABLED` |
| Pagos (Mercado Pago) | `MERCADOPAGO_HABILITADO`, `MERCADOPAGO_MODO`, `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_PUBLIC_KEY`, `MERCADOPAGO_WEBHOOK_SECRET`, `MERCADOPAGO_BACK_URL_BASE`, `MERCADOPAGO_NOTIFICATION_URL`, `MERCADOPAGO_TEST_BUYER_EMAIL` |
| Tests | `TEST_SEED_PASSWORD` |
| Monitoreo | `SENTRY_DSN` |

### Frontend (`frontend/.env.local`)

| Variable | Uso |
|---|---|
| `VITE_API_URL` | URL absoluta del backend sólo si frontend y API viven en hosts distintos; vacía en desarrollo/Docker |

## Deploy

- **Render:** `render.yaml` define el Web Service Docker (imagen `Dockerfile.render`) y los Cron Jobs de automatización; el `preDeployCommand` ejecuta `alembic upgrade head` antes de activar la versión nueva.
- **Neon:** PostgreSQL externo; no se declara una base dentro de `render.yaml`.
- **Cloudflare R2:** almacenamiento de comprobantes, certificados e imágenes del Bazar en producción.
- **n8n (opcional):** el contenedor no se levanta por defecto. Para habilitarlo:

```powershell
docker compose --profile n8n up -d n8n
```

## Seguridad

- No incluir credenciales, API keys, tokens ni connection strings reales en el repositorio.
- `.env`, `.env.test`, `.env.prod`, `*.dump`, `backups/` y logs están fuera de git.
- `backend/.env.example` y `frontend/.env.example` contienen únicamente marcadores de posición.
- El dump local `prod_backup.dump` no se versiona; trátalo como información sensible.

## Repositorio

[https://github.com/jmirandai1985-dot/proyecto-crossfit](https://github.com/jmirandai1985-dot/proyecto-crossfit)
