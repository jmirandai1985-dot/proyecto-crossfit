# AUDIT.md — Auditoría de avance y estado — Plataforma de gestión para boxes de CrossFit

- **Fecha:** 18/08/2026
- **Repo:** `c:\Users\Asus\Desktop\Proyectos\proyecto-crossfit` (git, rama `main`)
- **Alcance:** Tarea 1 del prompt de auditoría (solo lectura; no se modificó código en esta tarea).
- **Método:** recorrido de todo el repo, lectura de models/routers/schemas/services/frontend, revisión de migraciones, esquema SQL, tests, commits y reportes previos.

> Convención del proyecto: el concepto **`box_id`** de la arquitectura objetivo se implementa como **`tenant_id`** en todo el código (columna en las tablas + claim `tenant_id` en el JWT). **No existe** una tabla `BoxMembership` ni el rol por-box: un usuario tiene **un único `rol`** y **un único `tenant_id`** en la tabla `usuarios`.

---

## 1. Inventario de estructura

### 1.1 Árbol de carpetas (nivel principal)

```
proyecto-crossfit/
├── .gitignore
├── alembic.ini
├── sql/schema_clean.sql              # esquema de referencia (DESACTUALIZADO: 8 tablas)
├── backend/
│   ├── alembic/versions/             # 7 migraciones (001→007)
│   ├── app/
│   │   ├── api/v1/                   # 29 routers (≈120 endpoints)
│   │   ├── core/                     # config, security, dependencies, rate_limit, logging
│   │   ├── db/                       # database.py + tablas estáticas de ratios (crossfit_ratios, crossfit_habilidades)
│   │   ├── middleware/security_headers.py
│   │   ├── models/                   # 24 modelos SQLAlchemy
│   │   ├── schemas/                  # schemas Pydantic
│   │   └── services/                 # email, scheduler, nivel, reportes, auditoria, alertas, generar_clases
│   ├── maintenance/                  # 11 scripts operativos (backup, health, rotar credenciales…)
│   ├── scripts/                      # 9 scripts de test/envíos
│   ├── tests/                        # 6 archivos pytest (integración contra API real en branch TEST)
│   ├── requirements.txt              # deps con versiones fijadas (sin lockfile completo)
│   └── + ≈80 scripts one-off sueltos en la raíz (diagnóstico/migraciones ad-hoc)
├── frontend/
│   ├── src/
│   │   ├── components/               # Layout, ProtectedRoute, modales, etc.
│   │   ├── context/AuthContext.jsx
│   │   ├── pages/{admin,coach,alumno}/  # 3 paneles separados
│   │   ├── services/api.js           # cliente axios con token
│   │   └── config/roles.js
│   ├── package.json / package-lock.json
│   └── vite.config.js / tailwind.config.js
├── k6-tests/                         # 3 tests de carga (500 logins, concurrencia de reservas)
├── backups/                          # vacío (dumps se generan vía maintenance/backup_neon.py)
├── logo/                             # assets de emails
└── _notas-desarrollo/                # notas de sesiones anteriores
```

### 1.2 Stack detectado

| Capa | Tecnología | Versión detectada | Evidencia |
|---|---|---|---|
| Backend | Python | 3.13 (local) | `backend/` env |
| Backend | FastAPI | 0.109.0 | `requirements.txt` |
| Backend | Uvicorn | 0.27.0 | `requirements.txt` |
| ORM | SQLAlchemy | 2.0.25 | `requirements.txt` |
| Migraciones | Alembic | 1.13.1 | `requirements.txt`, `alembic/versions/` |
| BD | PostgreSQL (Neon cloud) | — (PostgreSQL 15+ según `sql/schema_clean.sql`) | `DATABASE_URL`, `psycopg2-binary` |
| BD (artefacto) | SQLite | — | `backend/app/box_crossfit.db` (gitignored, residuo de desarrollo) |
| Auth | python-jose (JWT HS256) + passlib (bcrypt) | 3.3.0 / 1.7.4 | `core/security.py` |
| Rate limiting | slowapi | 0.1.10 | `core/rate_limit.py` |
| Scheduler | APScheduler | 3.11.3 | `services/scheduler.py` |
| Frontend | React | 19.2.7 | `frontend/package.json` |
| Frontend | Vite | 8.1.0 | `package.json` |
| Frontend | React Router | 7.18.0 | `package.json` |
| Frontend | Tailwind CSS | 4.3.1 | `package.json` |
| Tests backend | pytest | 7.4.4 | `requirements.txt`, `tests/` |
| Tests carga | k6 | — | `k6-tests/` |
| Monitoreo | Sentry SDK | 2.68.0 | `requirements.txt`, `main.py` |

### 1.3 Gestores de dependencias

- **Backend:** `requirements.txt` con versiones pinneadas **pero sin lockfile** (`pip freeze` no versionado). Riesgo: no hay `pip-compile`/`poetry`/`uv`; versiones transitivas no garantizadas (ej: `bcrypt` no está declarado explícitamente pero es requerido por `passlib` y se usa en `usuarios.py`).
- **Frontend:** `npm` con `package.json` + `package-lock.json` (sí hay lockfile). Scripts: `dev`, `build`, `lint` (oxlint), `preview`.

## 2. Mapeo contra la arquitectura objetivo

### 2.1 Módulos

| Módulo | Estado | Evidencia |
|---|---|---|
| **Admin** — gestión de coaches/estudiantes | ✅ Implementado | `usuarios.py` (CRUD), `alumnos.py` (registro/activación), `coach_disciplinas.py`, frontend `pages/admin/{Alumnos,Coaches}.jsx` |
| **Admin** — planes con tokens | ✅ Implementado | `planes.py`, `suscripciones.py`, `solicitudes_planes.py`, `membresias.py`; frontend `admin/Planes.jsx` |
| **Admin** — pagos multi-método | ⚠️ Parcial | Solo **transferencia con comprobante** (`upload/voucher`, `solicitudes`) + "compra de emergencia" (`comprar_emergencia.py`). No hay pasarela (Webpay/PayPal/MercadoPago), no hay referencia de pago encriptada. |
| **Admin** — validación de comprobantes | ⚠️ Parcial | Flujo `pending→approved/rejected` funciona (con notificación al alumno), **pero** `POST /solicitudes/solicitar` no tiene auth ni notificación al admin. |
| **Admin** — espacios/equipo | ❌ No iniciado | No hay modelo de espacios/equipos ni UI; solo `cupo_maximo` por clase/horario. |
| **Admin** — reglas de negocio | ⚠️ Parcial | `configuracion.py` (datos bancarios por tenant); no hay engine de reglas genérico. |
| **Admin** — tienda con inventario | ✅ Implementado | `productos.py`, `pedidos.py` (con transiciones de estado y descuento de stock); frontend `admin/Bazar.jsx` |
| **Admin** — retención automática | ✅ Implementado | `retencion.py` + `fidelizacion.py` + jobs de email en `scheduler.py` |
| **Admin** — dashboard de asistencia | ✅ Implementado | `dashboard.py`, `reservas.py` (asistencia semanal/mes), `reportes.py` KPIs |
| **Admin** — reportes PDF | ⚠️ Parcial (desvío) | **Excel** (`reportes_service.py`, openpyxl), no PDF. Tags en main.py: `Reportes Excel`. |
| **Coach** — creación de clases | ✅ Implementado | `clases.py`, `horarios.py`, `supervision.py`, `services/generar_clases.py` + scheduler |
| **Coach** — WODs con librería de ejercicios | ✅ Implementado | `wods.py` (parser de texto), `movimientos.py`, `wod_movimiento.py`; frontend `coach/Pizarra.jsx` |
| **Coach** — registro de asistencia/resultados | ✅ Implementado | `reservas.py` (`PUT /{id}/asistencia`), `historial_rm.py` |
| **Coach** — tracking individual | ✅ Implementado | `historial_rm.py` (RMs por alumno), `reportes.py`, frontend `coach/DashboardCoach.jsx` |
| **Coach** — vista grupal por nivel (RX/scaled) | ⚠️ Parcial | `nivel_service.py` calcula niveles; no se detectó una vista grupal explícita por bandas RX/scaled por clase. |
| **Coach** — PRs read-only | ⚠️ Parcial/Con bugs | Los PRs son de solo lectura en la UI, pero los **endpoints de edición/borrado están abiertos sin auth** (ver §6). |
| **Coach** — historial de compras | ✅ Implementado | `pedidos.py` GET por alumno (sin auth — riesgo §4.3); frontend `alumno/MisPedidos.jsx` |
| **Student** — reserva con consumo de tokens | ✅ Implementado con bugs | `reservas.py` POST valida cupo, membresía y descuenta 1 token (§6). Race condition parcial en el descuento. |
| **Student** — tab de planes + upload comprobante | ✅ Implementado | `solicitudes_planes.py`, `upload.py`; frontend `alumno/SolicitarPlan.jsx` |
| **Student** — módulo PR/clasificación (fuerza, gimnasia, metabólico: bici/remo) | ✅ Implementado | `historial_rm.py`, `movimientos.py` (categorías), `db/crossfit_ratios.py` |
| **Student** — cálculo de nivel relativo al peso (Epley/Brzycki) | ❌ No implementado | `nivel_service.py` usa **tablas estáticas de ratios**; no hay Epley/Brzycki en todo el repo (búsqueda sin resultados). |
| **Student** — gráfico de evolución mensual | ✅ Implementado | frontend `alumno/Evolucion.jsx`, endpoint mejoras en `historial_rm.py` |
| **Student** — compras | ✅ Implementado | `pedidos.py` + frontend `alumno/Bazar.jsx`, `MisPedidos.jsx` |
| **Student** — notificaciones | ⚠️ Parcial/Con bugs | Tabla `notificaciones` + UI; **sin `tenant_id`**, endpoints sin auth e IDOR (§4.3); hardcode `tenant_id=1` en `admin/Notificaciones.jsx`. |

### 2.2 Entidades de negocio

| Entidad | Estado | Evidencia |
|---|---|---|
| **Tenant** (`box`) | ✅ Implementado | `models/tenant.py`, `tenants.py`, `schema_clean.sql` (subdomain único) |
| **BoxMembership** | ❌ **No existe** | No hay modelo/tabla. El rol vive en `usuarios.rol` (enum `alumno/coach/administrador`). Un usuario no puede tener roles distintos por box. **Desvío arquitectónico mayor.** |
| **Plan** | ✅ Implementado | `models/plan.py` (créditos, ilimitado, género, estudiante), `planes.py` |
| **Token** (crédito de clase) | ✅ Implementado | `suscripciones.creditos_disponibles`, consumo en `reservas.py`, devolución por cancelación ≥6h |
| **Reservation** | ✅ Implementado | `models/reserva.py` + `reservas.py` (con control atómico de aforo, política de cancelación) |
| **WOD** | ✅ Implementado | `models/wod.py`, `wod_movimiento.py`, `wods.py` (+ parser) |
| **PR** (historial_rm) | ⚠️ Implementado con bugs | CRUD completo pero **sin auth**, sin ventana de 24h, sin notificación a coach |
| **Voucher** (comprobante) | ⚠️ Parcial | Upload valida solo extensión; flujo de aprobación existe; sin notificación inmediata al admin |
| **Product / Store** | ✅ Implementado | `models/producto.py`, `pedido.py`, `productos.py`, `pedidos.py` |
| **Pagos multi-método** | ❌ No iniciado | Solo transferencia + emergencia; sin encriptación en reposo de referencias de pago |

## 3. Estado de la capa de datos

### 3.1 Migraciones

- **Existen** migraciones Alembic: `backend/alembic/versions/001…007` (`001` género planes → `007` notificaciones_enviadas). Están versionadas en git.
- **Problema:** la mayoría de los cambios de esquema recientes se aplicaron con **scripts one-off** en la raíz de `backend/` (~30 scripts con `ALTER TABLE ... ADD COLUMN`) y con un **endpoint HTTP** `POST /api/v1/migracion/run` que ejecuta DDL dinámico en producción (solo admin). El estado real de la BD está **divergido** del historial de Alembic.
- `sql/schema_clean.sql` está **desactualizado**: define solo 8 tablas (tenants, usuarios, planes, suscripciones, disciplinas, horarios_base, clases, reservas) mientras el código tiene **24 modelos** (wods, movimientos, historial_rm, notificaciones, solicitudes_planes, productos, pedidos, retención, cobertura_emergencia, coach_disciplinas, transacciones_financieras, configuracion_negocio, auditoria, etc.).

### 3.2 Modelos ORM y esquema multi-tenant

- ✅ La gran mayoría de modelos tienen `tenant_id` NOT NULL + FK → `tenants.id` (usuarios, planes, suscripciones, reservas, clases, horarios, wods, movimientos, historial_rm, productos, pedidos, retención, transacciones, auditoria, configuracion, cobertura_emergencia).
- ❌ **Sin aislamiento en dos tablas:** `notificaciones` y `notificaciones_enviadas` **no tienen `tenant_id`** → un alumno de otro tenant puede consultar/alterar notificaciones por `alumno_id` sin frontera de tenant.
- ❌ **No existe `BoxMembership`**: el modelo de autorización es rol único por usuario (`usuarios.rol`). No soporta "un usuario con roles distintos por box".
- ⚠️ `tenant_id` de algunos bodies/forms no se valida contra el token (ver §4.2).

### 3.3 Foreign keys e índices

- ✅ FKs correctas en la mayoría de modelos (`clase_id`, `alumno_id`, `plan_id`, `movimiento_id`, etc.) con `ON DELETE CASCADE`/`SET NULL` adecuados.
- ✅ Índices definidos en `__table_args__` para consultas frecuentes (tenant, alumno, clase, fecha, estado).
- ⚠️ `solicitudes_planes`, `notificaciones`, `notificaciones_enviadas`, `configuracion_negocio` **no declaran índices** sobre `tenant_id`.
- ⚠️ `schema_clean.sql` documenta `UNIQUE(tenant_id, rut)` y `UNIQUE(tenant_id, correo)`; los modelos no los reflejan explícitamente (se depende del DDL real en Neon).
- ⚠️ Queries con JOIN a `Movimiento`/`Usuario` desde `historial_rm` a veces no incluyen el `tenant_id` del lado unido (solo del lado principal).
- **No hay Row-Level Security (RLS)** en PostgreSQL: el aislamiento es 100% por lógica de aplicación.

## 4. Estado de la API

### 4.1 Convenciones

- Prefijo global: `/api/v1`. Docs en `/docs` (Swagger) y `/redoc`.
- Auth: `HTTPBearer` + JWT HS256 (60 min) en `Authorization: Bearer`. Dependencies: `get_current_user`, `get_current_coach`, `get_current_admin`.
- **Inconsistencia crítica de multi-tenancy:** en muchos endpoints el `tenant_id` se toma del **query/path/body del cliente** (a veces con **default hardcodeado `=1`**) en lugar de derivarse del token. Solo `dashboard/{tenant_id}`, `reportes/*`, `reservas POST/PUT/DELETE`, `comprar_emergencia` validan contra el token.

### 4.2 Matriz de endpoints (1/2)

Leyenda: 🅰️ = `get_current_admin` · 🛡️ = `get_current_coach` · 👤 = `get_current_user` · 🔓 = sin auth (o auth insuficiente). La columna *tenant* indica si el `tenant_id` sale del token (T), del cliente (C), o no aplica/global (G).

| Router (prefijo) | Método + Ruta | Auth | tenant | Notas |
|---|---|---|---|---|
| `/api/v1/auth` | POST `/login` | 🔓 (rate 5/min) | G | bcrypt + JWT. **Sin refresh token.** |
| `/api/v1/alumnos` | POST `/registro/alumno-nuevo` | 🔓 (rate 5/h) | C | Público por diseño; crea `pendiente_activacion` |
| | GET `/pendientes-activacion`, `/count` | 🅰️ | C (`=1`) | |
| | PUT/DELETE `/{id}/activar`, `/{id}/rechazar` | 🅰️ | C (`=1`) | `activar` devuelve password provisional en la respuesta |
| | GET `/me`, `/me/es-prueba`, POST `/me/primera-clase` | 👤 | T | |
| `/api/v1/usuarios` | PUT `/cambiar-password` | 👤 | T | **No invalida sesiones existentes** |
| | POST `/`, GET `/`, GET `/{id}`, PUT `/{id}`, DELETE `/{id}` | 🅰️ | C | POST/GET `/` con rate limit |
| `/api/v1/tenants` | POST `/` | 🅰️ | G | Cualquier admin crea tenants |
| | GET `/`, GET `/{id}`, GET `/subdomain/{s}` | 🔓 | G | **Lista todos los tenants** públicamente |
| `/api/v1/dashboard` | GET `/{tenant_id}/ocupacion-hoy` | 👤 | C | tenant del path **no validado** vs token |
| | GET `/{tenant_id}` | 🅰️ | T | validado |
| `/api/v1/clases` | GET `/`, GET `/{id}` | 🔓 | C (`=1`) | Lectura pública; **genera clases al leer** (efecto colateral) |
| | POST `/`, PUT `/{id}`, DELETE `/{id}` | 🛡️ | C (`=1`) | no validan vs token |
| `/api/v1/horarios` | POST `/` | 🅰️ | C | |
| | GET `/`, GET `/grid-semanal` | 🔓 | C | |
| `/api/v1/disciplinas` | POST `/`, PUT `/{id}`, DELETE `/{id}` | 🅰️ | C | |
| | GET `/`, GET `/{id}` | 🔓 | C | |
| `/api/v1/movimientos` | POST `/` | 🔓 | C | **Cualquiera puede crear movimientos** |
| | GET `/`, GET `/{id}` | 🔓 | C | |
| | PUT `/{id}`, DELETE `/{id}` | 🔓 | C | **sin auth** |
| `/api/v1/historial-rm` | POST `/` | 🔓 | C | **CRUD de PRs sin auth (grave)** |
| | GET `*` (9 GETs) | 🔓 | C | lectura de PRs/niveles de cualquier alumno |
| | PUT `/{id}`, DELETE `/{id}` | 🔓 | C | **sin auth + sin ventana de 24h** |
| | POST `/nivel-fuerza`, `/nivel-gimnastico` | 🔓 | C | sin auth |
| `/api/v1/wods` | GET `/`, GET `/hoy`, GET `/{id}` | 🔓 | C (`=1`) | |
| | POST `/parse` | 🔓 | G | parser (sin efecto en BD) |
| | POST `/`, PUT `/{id}`, DELETE `/{id}`, POST `/clases/{c}/asignar-wod/{w}` | 🛡️ | C (`=1`) | |
| | POST `/batch` | 👤 | C (`=1`) | **usa `body: dict` genérico** (no schema) |
| `/api/v1/reservas` | POST `/` | 👤 | T | IDOR protegido; aforo atómico; descuenta token |
| | PUT `/{id}/asistencia` | 🛡️ | C | valida coach-disciplina |
| | GET `/por-clase/{id}`, GET ``, GET `/{id}` | 🔓 | C | **lectura de reservas de cualquier tenant** |
| | GET `/asistencia-semanal`, `/asistencia-mes` | 🔓 | C | **IDOR** (usuario_id del query) |
| | PUT `/{id}`, DELETE `/{id}` | 👤 | C | IDOR protegido; política de cancelación ≥6h |

### 4.2 Matriz de endpoints (2/2)

| Router (prefijo) | Método + Ruta | Auth | tenant | Notas |
|---|---|---|---|---|
| `/api/v1/planes` | POST `/` | 🅰️ | C | |
| | GET `/`, GET `/membresia-activa` | 🔓 | C | **IDOR** (alumno_id del query) |
| | GET `/{plan_id}` | 🔓 | G | **sin filtro tenant** |
| | PUT `/{plan_id}`, DELETE `/{plan_id}` | 🅰️ | G | **sin filtro tenant** → admin de tenant A edita plan de tenant B |
| `/api/v1/solicitudes` | POST `/solicitar` | 🔓 | C | **sin auth + IDOR**: cualquiera crea solicitudes y miente `alumno_id`/`tenant_id` |
| | GET `/pendientes` | 🅰️ | C | |
| | GET `/{id}/voucher` | 🅰️ | G | path-traversal protegido |
| | PUT `/{id}/aprobar` | 🅰️ | G | solicitud **no scoped por tenant** |
| | PUT `/{id}/rechazar` | 🅰️ (rate) | G | |
| `/api/v1/membresias` | GET `/mi-membresia` | 🔓 | C | **sin auth + IDOR** (saldos de tokens de cualquier alumno) |
| `/api/v1/suscripciones` | POST `/suscripciones` | 🅰️ (rate) | C | crea suscripción + transacción financiera |
| | GET `/suscripciones` | 🅰️ | C | |
| `/api/v1/planes` (comprar_emergencia) | POST `/comprar-emergencia` | 👤 (rate) | C | IDOR protegido; regla 1/año |
| `/api/v1/productos` | POST `/` | 🅰️ | C (form) | imagen: valida content-type (spoofeable) |
| | GET `/`, GET `/{id}` | 🔓 | C | |
| | PUT `/{id}`, DELETE `/{id}` | 🅰️ | C | |
| `/api/v1/pedidos` | POST `/` | 🅰️ | C | descuenta stock |
| | GET `/`, GET `/{id}` | 🔓 | C | **historial de compras de cualquier alumno** |
| | PUT `/{id}/estado` | 🅰️ | C | máquina de estados correcta |
| `/api/v1/retencion` | POST `/` | 🅰️ | C | |
| | GET `/`, GET `/{id}`, GET `/en-riesgo`, GET `/kpi-coach` | 🔓 | C | |
| | PUT `/{id}`, DELETE `/{id}` | 🅰️ | C | |
| `/api/v1/fidelizacion` | POST `/registrar`, POST `/campana-email/{t}` | 🅰️ | C/T | |
| | GET `/analizar/{t}`, GET `/coach/{id}/en-riesgo`, GET `/tenant/{t}/en-riesgo`, GET `/tenant/{t}/vencimientos` | 🔓 | C | |
| `/api/v1/reportes` | GET `/`, `/monthly-sales`, `/dashboard` | 🅰️ | T | tenant validado; **Excel**, no PDF |
| `/api/v1/finanzas` | POST `/transaccion`, GET `/transacciones` | 🅰️ | C | tenant **no validado** vs token |
| `/api/v1/auditoria` | POST `/` | 🔓 | C | **cualquiera escribe logs de auditoría** |
| | GET `/`, `/{id}`, `/usuario/{u}`, `/entidad/{e}/{id}` | 🔓 | C | **logs de auditoría públicos** |
| `/api/v1/notificaciones` | GET ``, PUT `/{id}/leer`, PUT `/leer-todas` | 🔓 | G | **IDOR** (alumno_id del query); sin tenant |
| | POST `/enviar-alertas-*` (3) | 🅰️ | G | disparo manual de emails |
| `/api/v1/notificaciones-enviadas` | GET ``, POST `/enviar-manual`, POST `/{id}/reenviar` | 🅰️ | G | sin tenant en tabla |
| | POST `/registrar` | 👤 | G | |
| `/api/v1/upload` | POST `/voucher` | 👤 | T | valida **solo extensión**, no MIME real (§6) |
| `/api/v1/configuracion` | GET `` | 🔓 | C | público por diseño (datos bancarios para el comprobante) |
| | PUT `` | 👤 (chequeo manual de rol) | C | **debería usar `get_current_admin`**; no valida tenant vs token |
| `/api/v1/supervision` | GET `/proxima-clase-reservas`, `/horarios-base`, `/grid-semanal`, `/coaches-todos`, `/cupos-disciplinas` | 🔓 | C (`=1`) | |
| | PATCH `/cupo-disciplina` | 🅰️ | C (`=1`) | |
| `/api/v1/coach-disciplinas` | POST/PUT/DELETE | 🅰️ | C | |
| `/api/v1/migracion` | POST `/run` | 🅰️ | G | **DDL dinámico vía HTTP** (riesgo en prod) |
| `/api/v1/fix` | POST `/corregir-fechas` | 🅰️ | G | **afecta TODOS los tenants** |

### 4.3 Endpoints sin autenticación (riesgo confirmado)

Los siguientes mutan/escriben datos **sin ningún `Depends(get_current_*)`**:

1. `POST /api/v1/historial-rm` — crear PR de cualquier alumno/tenant.
2. `PUT/DELETE /api/v1/historial-rm/{id}` — editar/borrar cualquier PR (además, **sin ventana de 24h**).
3. `POST /api/v1/movimientos` — crear movimientos de la librería.
4. `POST /api/v1/auditoria` — inyectar logs de auditoría falsos.
5. `POST /api/v1/solicitudes/solicitar` — crear solicitudes de plan a nombre de otro alumno.
6. Lecturas sensibles sin auth: `membresias/mi-membresia`, `planes/membresia-activa`, `notificaciones/*`, `historial-rm/*`, `reservas/*` (GET), `pedidos/*` (GET), `auditoria/*` (GET), `tenants/*` (GET), `fidelizacion/*` (GET), `retencion/*` (GET), `wods/*` (GET), `clases/*` (GET), `horarios/*` (GET), `movimientos/*` (GET), `productos/*` (GET), `supervision/*` (GET).

## 5. Estado del frontend

### 5.1 Rutas existentes (`App.jsx`)

- Públicas: `/`, `/landing` (LandingPage), `/login`.
- Admin (`/admin/*`, roles `administrador|admin`): `dashboard`, `alumnos`, `alumnos-pendientes`, `coaches`, `clases`, `supervision-clases`, `planes`, `disciplinas`, `bazar`, `reportes`, `configuracion`, `notificaciones`, `fidelizacion`.
- Coach (`/coach/*`): `dashboard`, `pizarra`, `generar-clases`, `gestion-clases`.
- Alumno (`/alumno/*`): `dashboard`, `mis-reservas`, `rms`, `ajustes`, `solicitar-plan`, `evolucion`, `bazar`, `mis-pedidos`, `performance-hub`.
- `ProtectedRoute.jsx` redirige según rol (`config/roles.js` → `DASHBOARD_MAP`).

### 5.2 Componentes por rol

- **Admin (14 páginas):** Dashboard, Alumnos, AlumnosPendientes, Coaches, Clases, SupervisionClases, Planes, Disciplinas, Bazar, Reportes, Configuracion, Notificaciones, Fidelizacion.
- **Coach (4 páginas):** DashboardCoach, Pizarra, GenerarClases, GestionClases. (existe `coach/Dashboard.jsx` huérfano, no referenciado en rutas).
- **Alumno (9 páginas):** Dashboard, MisReservas, PizarraRMs, Ajustes, SolicitarPlan, Evolucion, Bazar, MisPedidos, PerformanceHub.
- **Componentes compartidos:** `Layout.jsx`, `ModalClase.jsx`, `ModalProducto.jsx`, `AlumnoFichaModal.jsx`, `RegistroAlumnoNuevo.jsx`, `ResetContrasena.jsx`.

### 5.3 Manejo de estado

- `AuthContext.jsx` (context) guarda **token + rol + tenant_id + usuario_id en `localStorage`** (vulnerabilidad XSS → ver SECURITY.md).
- El resto del estado es local (`useState`) por página + `services/api.js` (axios con interceptor de token y manejo de 401).
- No se usa Redux/Zustand/React Query.

### 5.4 Separación de paneles

- ✅ Separación real de los 3 paneles por rutas/roles (nested routes + `ProtectedRoute`).
- ⚠️ Endurecimiento solo en frontend: el backend no refuerza rol por endpoint en varios GETs, por lo que un alumno con curl podría leer datos de admin (ej. `supervision/*`, `retencion/*`, `fidelizacion/*` GET no están protegidos).
- ⚠️ `Notificaciones.jsx` (admin) tiene hardcodeado `{ tenant_id: 1 }` en vez de leerlo de `AuthContext`.

---

## 6. Gaps críticos (lógica de negocio)

| # | Requisito | Estado real | Evidencia |
|---|---|---|---|
| 1 | Tokens: consumo por reserva | ✅ Implementado | `reservas.py` POST descuenta 1 crédito; bloquea en `<=0` |
| 2 | Tokens: bloqueo al agotarse | ✅ Implementado | `reservas.py:128` (400 "No te quedan clases…") |
| 3 | Tokens: alerta en el último token | ❌ No implementado | No existe aviso cuando `creditos_disponibles == 1` (ni en backend ni en frontend) |
| 4 | Tokens: descuento atómico | ⚠️ Bug | `membresia.creditos_disponibles -= 1` (leer-modificar-escribir) sin `UPDATE ... WHERE creditos > 0` ni `FOR UPDATE` → puede quedar negativo bajo concurrencia (el commit `7d8f384` mitigó overbooking de cupo, no de tokens) |
| 5 | Comprobante → plan `pending`, sin acceso hasta aprobación | ✅ Implementado | `solicitudes_planes.py` (solo crea `SolicitudPlan`; la suscripción se crea en `aprobar`) |
| 6 | Notificación inmediata al admin al subir comprobante | ❌ No implementado | `POST /solicitar` no crea notificación ni email al admin |
| 7 | Peso corporal: campo de perfil separado, actualización voluntaria | ✅ Implementado | `usuarios.peso_kg` + `Ajustes.jsx`; usado en `nivel_service` |
| 8 | Edición de PR solo dentro de 24h | ❌ No implementado | `PUT /historial-rm/{id}` no valida antigüedad (y ni siquiera exige auth) |
| 9 | Notificación al coach cuando un student logra nuevo PR o cambia de nivel | ❌ No implementado | No hay llamada a `Notificacion`/email en `historial_rm.py` (búsqueda "nuevo PR" sin resultados) |
| 10 | Cálculo de nivel relativo al peso (Epley/Brzycki) | ❌ No implementado | `nivel_service.py` usa tablas estáticas de ratios por movimiento; no existe Epley ni Brzycki en el repo |
| 11 | Pago multi-método | ❌ No iniciado | Solo transferencia + compra de emergencia |
| 12 | Reportes PDF | ⚠️ Desvío | Excel (openpyxl) en vez de PDF |

## 7. Deuda técnica visible

1. **≈80 scripts one-off en `backend/` raíz** (diagnósticos, migraciones ad-hoc, fixes) → la migración de esquema **no está centralizada** en Alembic.
2. **Endpoint de migración vía HTTP** (`/api/v1/migracion/run`) y **endpoint global de fix** (`/api/v1/fix/corregir-fechas`) expuestos en la API de producción.
3. **`schema_clean.sql` desactualizado** (8 de ~24 tablas) → documentación divergente de la realidad.
4. **SQL raw mezclado con ORM:** ~30+ consultas con `text()`/`sql_text` en `api/v1` (clases, reservas, supervision, reportes, finanzas, fidelizacion, auth, dashboard). Parametrizadas (sin inyección), pero rompen consistencia y reutilización.
5. **`tenant_id` default hardcodeado `=1`** en ~15 endpoints (Query o parámetro) → riesgo de escribir/leer el tenant 1 por omisión.
6. **Schemas Pydantic definidos inline en routers** (`finanzas.py`, `configuracion.py`, `suscripciones.py`, `comprar_emergencia.py`, `alumnos.py`, `wods.py` `/batch` con `body: dict`) en lugar de `app/schemas/`.
7. **Duplicación de lógica de password:** `core/security.py` (passlib `CryptContext`) vs helpers `hash_password`/`verify` propios en `usuarios.py`.
8. **Dependencia no declarada:** `bcrypt` se usa pero no está en `requirements.txt` (pasó a instalarse como transitiva; `passlib[argon2]` no incluye bcrypt) → builds reproducibles frágiles.
9. **Artefactos en el árbol de trabajo:** `backend/app/box_crossfit.db` (SQLite), `backend/app/static/uploads/*` con vouchers reales subidos, logs de servidor (`server_*.log`), `build_log*.txt`, `test_report.xlsx` (están gitignored pero ocupan espacio y algunos contienen datos reales).
10. **Testing:** 6 archivos pytest de integración que requieren servidor levantado contra branch TEST (`conftest.py` con guard de seguridad) + k6. **Sin tests unitarios** (calculadoras de nivel, parser de WOD, lógica de tokens), sin CI configurado.
11. **Hardcoded en frontend:** `tenant_id=1` en `admin/Notificaciones.jsx`; `VITE_API_URL` con fallback a localhost en `services/api.js`.
12. **Passwords en respuestas:** `PUT /alumnos/{id}/activar` devuelve la password provisional en el body (documentado como intencional, pero sensible en logs/proxies).
13. **Roles como strings sueltos** (`"admin"`, `"administrador"`, `"coach"`, `"alumno"`) en lugar de usar `RolUsuario` enum en la capa de permisos (varios `if rol not in (...)` literales).

---

### Anexo — Reportes previos relevantes en el repo

`REPORTE_BLOQUE_SEGURIDAD.md`, `AUDITORIA_PANEL_COACH.md`, `AUDITORIA_CATCHES_ADMIN.md`, `DIAGNOSTICO_URGENTE_PROD_TEST.md`, `REPORTE_ESTADO_PROYECTO.md`, `LOG_ADMIN_PENDIENTES.md`, `backend/LOG_AISLAMIENTO_TESTS.md`, `backend/GUIA_PRUEBAS_API.md`, `backend/RESUMEN_IMPLEMENTACION_API.md`.

*Fin de AUDIT.md.*






