# Urban Training Box

SaaS de gestión para gimnasios y boxes de CrossFit: alumnos, planes, reservas, asistencia, bazar, reportes, fidelización y automatizaciones.

> **Estado:** proyecto en desarrollo activo. Todavía no hay alumnos reales en producción; los datos de prueba viven en una branch TEST separada de Neon.

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic 2, APScheduler |
| Frontend | React 19, Vite 8, Tailwind CSS 4, React Router 7, TanStack Query 5, Recharts |
| Base de datos | PostgreSQL en Neon (branch TEST separada para pruebas) |
| Deploy | Render (Docker, `Dockerfile.render`, nginx) |
| Storage | Cloudflare R2 en producción; disco local en desarrollo/TEST |
| Automatizaciones | APScheduler, Cron Job de Render y n8n opcional vía Docker Compose |
| Tests | pytest + httpx |

## Estructura del proyecto

```text
proyecto-crossfit/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # Endpoints REST por recurso
│   │   ├── core/            # Configuración, seguridad, tenant, logging
│   │   ├── db/              # Sesión y base SQLAlchemy
│   │   ├── middleware/      # Seguridad, auditoría de tenant, etc.
│   │   ├── models/          # Modelos SQLAlchemy
│   │   ├── schemas/         # Schemas Pydantic
│   │   ├── services/        # Reglas de negocio y servicios
│   │   └── utils/           # Utilidades (fechas de Chile, helpers)
│   ├── alembic/versions/    # Migraciones versionadas
│   ├── maintenance/         # Scripts de cron: backups, KPIs, limpieza
│   ├── ml/                  # Modelos y entrenamiento (churn, forecast)
│   ├── scripts/             # Seeds, sincronización TEST/PROD, utilidades
│   └── tests/               # Tests de API, integración y guards de fuente
├── frontend/
│   ├── src/components/      # Componentes compartidos
│   ├── src/pages/
│   │   ├── admin/           # Panel administración
│   │   ├── alumno/          # Panel alumno
│   │   ├── coach/           # Panel coach
│   │   └── tv/              # Vista para pantallas del box
│   ├── src/context/         # Contextos de React
│   ├── src/hooks/           # Hooks (queries, mutations)
│   ├── src/services/        # Cliente API
│   └── src/utils/           # Utilidades del frontend
├── docs/                    # Documentación funcional y auditorías
├── n8n/                     # Workflows/automatizaciones (opcional)
├── docker-compose.yml       # Stack local (TEST por defecto)
├── Dockerfile.render        # Imagen combinada nginx + uvicorn para Render
├── nginx.render.conf        # Proxy /api, /static, /health y /health/db
├── render.yaml              # Blueprint de Render
└── README.md
```

## Entorno local

### Requisitos

- Python 3.12
- Node.js 20+ y npm
- Git
- Acceso a una base PostgreSQL (Neon o una instancia local compatible)

### Backend

```powershell
cd backend
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edita `backend/.env` con tus valores locales. Las variables principales están documentadas en `backend/.env.example` (sin credenciales reales). Luego inicia la API:

```powershell
python start_server.py
```

Alternativa equivalente:

```powershell
py -3.12 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Liveness: `GET /health`
- Readiness (incluye `SELECT 1`): `GET /health/db`

`iniciar_servidor.py` es solo para testing local: fuerza `ENVIRONMENT=test` y usa `backend/.env.test`. No lo uses para operar datos reales.

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

- Frontend: `http://localhost:5173`
- `VITE_API_URL` puede quedar vacío en desarrollo: Vite proxea `/api` y `/static` hacia `http://localhost:8000`.

### Base de datos y ambientes

- `backend/.env` se usa para desarrollo/operación.
- `backend/.env.test` apunta a la branch **TEST** de Neon: es una copia aislada para pruebas destructivas. **Nunca la apuntes a producción.**
- `run_setup_test_db.py` reconstruye el schema y el seed de TEST.
- No subas `.env`, `.env.test`, dumps ni backups al repositorio.

## Tests

La suite completa se ejecuta con:

```powershell
cd backend
run_tests.bat
```

o de forma no interactiva:

```powershell
run_tests.bat /y
```

> **Importante:** `run_tests.bat` es destructivo sobre la branch TEST: hace `DROP SCHEMA public CASCADE`, vuelve a sembrar la base y mata cualquier uvicorn que escuche en el puerto 8000. Está protegido para no tocar producción, pero verifica siempre el ambiente antes de correrlo.

Tests de fuente aislados (sin red ni base de datos):

```powershell
cd backend
py -3.12 -m pytest tests/test_salud_liveness_readiness.py --noconftest -q
py -3.12 -m pytest tests/test_codigo_retiro_front.py --noconftest -q
```

Los tests de integración requieren la API levantada en `localhost:8000` y la branch TEST; por eso se ejecutan normalmente a través de `run_tests.bat`.

## Variables de entorno principales

Nombres solamente; los valores reales se configuran localmente o en el dashboard de Render y **nunca** se versionan.

### Backend

| Grupo | Variables |
|---|---|
| Base de datos | `DATABASE_URL`, `DATABASE_URL_PROD`, `DIRECT_URL` |
| Seguridad/JWT | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `SECRET_KEY` |
| Aplicación | `APP_NAME`, `APP_VERSION`, `DEBUG`, `ENVIRONMENT` |
| URLs/CORS | `CORS_ORIGINS`, `FRONTEND_URL`, `BACKEND_PUBLIC_URL` |
| Correo | `EMAIL_MODO`, `GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD` |
| Storage | `STORAGE_BACKEND`, `STORAGE_R2_ENDPOINT`, `STORAGE_R2_BUCKET`, `STORAGE_R2_PUBLIC_BUCKET`, `STORAGE_R2_ACCESS_KEY_ID`, `STORAGE_R2_SECRET_ACCESS_KEY`, `STORAGE_R2_PUBLIC_BASE_URL`, `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB` |
| Automatizaciones | `N8N_API_KEY`, `CRON_API_KEY`, `REACTIVACION_OPT_OUT_SECRET` |
| Monitoreo | `SENTRY_DSN` |

### Frontend

| Variable | Uso |
|---|---|
| `VITE_API_URL` | URL absoluta del backend solo si frontend y API viven en hosts distintos; vacía en desarrollo/Docker |

## Deploy

- **Render:** `render.yaml` define el Web Service Docker que usa `Dockerfile.render`; el `preDeployCommand` ejecuta `alembic upgrade head` antes de activar la versión nueva.
- **Neon:** PostgreSQL externo; no se declara una base dentro de `render.yaml`.
- **Cloudflare R2:** almacenamiento de comprobantes, certificados e imágenes del Bazar en producción.
- **n8n (opcional):** el contenedor no se levanta por defecto. Para habilitarlo:

```powershell
docker compose --profile n8n up -d n8n
```

## Seguridad

- No incluir credenciales, API keys, tokens ni connection strings reales en el repositorio.
- `.env`, `.env.test`, `*.dump`, `backups/` y logs están fuera de git.
- `backend/.env.example` contiene únicamente marcadores de posición.
- El dump local `prod_backup.dump` no se versiona; trátalo como información sensible.

## Repositorio

[https://github.com/jmirandai1985-dot/proyecto-crossfit](https://github.com/jmirandai1985-dot/proyecto-crossfit)

