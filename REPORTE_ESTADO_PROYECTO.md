# REPORTE DE ESTADO DEL PROYECTO — proyecto-crossfit

> Generado el: 10/07/2026
> Repositorio: https://github.com/jmirandai1985-dot/proyecto-crossfit.git

---

## 1. ÁRBOL COMPLETO DEL PROYECTO

```
proyecto-crossfit/
│
├── .gitignore
├── alembic.ini
│
├── _notas-desarrollo/
│   ├── ANALISIS_ERROR_PASSWORD.md
│   ├── INSTRUCCIONES_DEBUG.md
│   ├── INSTRUCCIONES_INSTALACION_NODEJS.md
│   └── SOLUCION_PATH_NODEJS.md
│
├── backend/
│   ├── .env.example
│   ├── .gitignore
│   ├── GUIA_PRUEBAS_API.md
│   ├── INSTRUCCIONES_INSTALACION.md
│   ├── README.md
│   ├── RESUMEN_CONFIGURACION.md
│   ├── RESUMEN_IMPLEMENTACION_API.md
│   ├── requirements.txt
│   ├── start_server.py
│   ├── iniciar_servidor.bat
│   │
│   ├── alembic/
│   │   ├── README
│   │   ├── env.py
│   │   └── script.py.mako
│   │
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── main_backup.py
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── auditoria.py
│   │   │       ├── auth.py
│   │   │       ├── clases.py
│   │   │       ├── coach_disciplinas.py
│   │   │       ├── comprar_emergencia.py
│   │   │       ├── dashboard.py
│   │   │       ├── disciplinas.py
│   │   │       ├── fidelizacion.py
│   │   │       ├── fix_fechas.py
│   │   │       ├── historial_rm.py
│   │   │       ├── horarios.py
│   │   │       ├── membresias.py
│   │   │       ├── migracion.py
│   │   │       ├── movimientos.py
│   │   │       ├── notificaciones.py
│   │   │       ├── pedidos.py
│   │   │       ├── planes.py
│   │   │       ├── productos.py
│   │   │       ├── reportes.py
│   │   │       ├── reservas.py
│   │   │       ├── retencion.py
│   │   │       ├── solicitudes_planes.py
│   │   │       ├── suscripciones.py
│   │   │       ├── tenants.py
│   │   │       ├── upload.py
│   │   │       ├── usuarios.py
│   │   │       └── wods.py
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── dependencies.py
│   │   │   └── security.py
│   │   │
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── crossfit_habilidades.py
│   │   │   ├── crossfit_ratios.py
│   │   │   └── database.py
│   │   │
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── asistencia.py
│   │   │   ├── auditoria.py
│   │   │   ├── clase.py
│   │   │   ├── coach_disciplina.py
│   │   │   ├── disciplina.py
│   │   │   ├── historial_rm.py
│   │   │   ├── horario_base.py
│   │   │   ├── movimiento.py
│   │   │   ├── notificacion.py
│   │   │   ├── pedido.py
│   │   │   ├── plan.py
│   │   │   ├── producto.py
│   │   │   ├── reserva.py
│   │   │   ├── retencion.py
│   │   │   ├── solicitud_plan.py
│   │   │   ├── suscripcion.py
│   │   │   ├── tenant.py
│   │   │   ├── usuario.py
│   │   │   ├── wod.py
│   │   │   └── wod_movimiento.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── auditoria.py
│   │   │   ├── auth.py
│   │   │   ├── clase.py
│   │   │   ├── coach_disciplina.py
│   │   │   ├── dashboard.py
│   │   │   ├── disciplina.py
│   │   │   ├── historial_rm.py
│   │   │   ├── horario_base.py
│   │   │   ├── movimiento.py
│   │   │   ├── pedido.py
│   │   │   ├── plan.py
│   │   │   ├── plan_schema.py
│   │   │   ├── producto.py
│   │   │   ├── reserva.py
│   │   │   ├── retencion.py
│   │   │   ├── solicitud.py
│   │   │   ├── tenant.py
│   │   │   ├── usuario.py
│   │   │   ├── wod.py
│   │   │   └── wod_parse.py
│   │   │
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── auditoria_service.py
│   │       ├── nivel_service.py
│   │       └── reportes_service.py
│   │
│   ├── migrations/
│   │   ├── README
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 001_fix_reservas_clases_seguridad.py
│   │
│   └── tests/
│       └── __init__.py
│
├── frontend/
│   ├── .gitignore
│   ├── .oxlintrc.json
│   ├── GUIA_INTEGRACION_API.md
│   ├── README.md
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── postcss.config.js
│   ├── tailwind.config.js
│   ├── vite.config.js
│   │
│   ├── public/
│   │   ├── favicon.svg
│   │   └── icons.svg
│   │
│   └── src/
│       ├── App.css
│       ├── App.jsx
│       ├── index.css
│       ├── main.jsx
│       │
│       ├── assets/
│       │   ├── hero.png
│       │   ├── react.svg
│       │   └── vite.svg
│       │
│       ├── components/
│       │   ├── Layout.jsx
│       │   ├── ModalClase.jsx
│       │   ├── ModalProducto.jsx
│       │   └── ProtectedRoute.jsx
│       │
│       ├── config/
│       │   └── roles.js
│       │
│       ├── context/
│       │   └── AuthContext.jsx
│       │
│       ├── pages/
│       │   ├── Login.jsx
│       │   ├── Setup.jsx
│       │   ├── admin/
│       │   │   ├── Alumnos.jsx
│       │   │   ├── Bazar.jsx
│       │   │   ├── Clases.jsx
│       │   │   ├── Coaches.jsx
│       │   │   ├── Dashboard.jsx
│       │   │   └── Reportes.jsx
│       │   ├── alumno/
│       │   │   ├── Dashboard.jsx
│       │   │   └── PizarraRMs.jsx
│       │   └── coach/
│       │       ├── Dashboard.jsx
│       │       ├── DashboardCoach.jsx
│       │       └── Pizarra.jsx
│       │
│       └── services/
│           └── api.js
│
└── sql/
    ├── schema.sql
    └── schema_clean.sql
```

---

## 2. SCHEMA DE BASE DE DATOS (PostgreSQL)

### Tabla: `tenants`
| Columna | Tipo | Restricciones |
|---------|------|---------------|
| id | SERIAL | PRIMARY KEY |
| nombre | VARCHAR(150) | NOT NULL |
| subdomain | VARCHAR(63) | NOT NULL, UNIQUE |
| activo | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

### Tabla: `usuarios`
| Columna | Tipo | Restricciones |
|---------|------|---------------|
| id | SERIAL | PRIMARY KEY |
| tenant_id | INTEGER | NOT NULL, FK → tenants(id) ON DELETE CASCADE |
| rut | VARCHAR(12) | NOT NULL |
| nombre | VARCHAR(150) | NOT NULL |
| telefono | VARCHAR(20) | |
| correo | VARCHAR(150) | NOT NULL |
| password_hash | VARCHAR(255) | NOT NULL |
| rol | rol_usuario (ENUM) | NOT NULL, DEFAULT 'alumno' |
| activo | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |
| **UNIQUE** | | (tenant_id, rut) |
| **UNIQUE** | | (tenant_id, correo) |

**Enum `rol_usuario`**: `'alumno'`, `'coach'`, `'administrador'`

### Tabla: `planes`
| Columna | Tipo | Restricciones |
|---------|------|---------------|
| id | SERIAL | PRIMARY KEY |
| tenant_id | INTEGER | NOT NULL, FK → tenants(id) ON DELETE CASCADE |
| nombre | VARCHAR(100) | NOT NULL |
| creditos | INTEGER | NULL = ilimitado |
| es_ilimitado | BOOLEAN | NOT NULL, DEFAULT FALSE |
| precio_clp | INTEGER | NOT NULL |
| duracion_dias | INTEGER | NOT NULL, DEFAULT 30 |
| activo | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

### Tabla: `suscripciones`
| Columna | Tipo | Restricciones |
|---------|------|---------------|
| id | SERIAL | PRIMARY KEY |
| tenant_id | INTEGER | NOT NULL, FK → tenants(id) ON DELETE CASCADE |
| usuario_id | INTEGER | NOT NULL, FK → usuarios(id) ON DELETE CASCADE |
| plan_id | INTEGER | NOT NULL, FK → planes(id) |
| estado | estado_suscripcion (ENUM) | NOT NULL, DEFAULT 'pendiente' |
| creditos_totales | INTEGER | |
| creditos_disponibles | INTEGER | |
| fecha_inicio | TIMESTAMPTZ | |
| fecha_expiracion | TIMESTAMPTZ | |
| voucher_url | VARCHAR(500) | NOT NULL |
| aprobado_por | INTEGER | FK → usuarios(id) |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

**Enum `estado_suscripcion`**: `'pendiente'`, `'activo'`, `'vencido'`, `'rechazado'`

### Tabla: `disciplinas`
| Columna | Tipo | Restricciones |
|---------|------|---------------|
| id | SERIAL | PRIMARY KEY |
| tenant_id | INTEGER | NOT NULL, FK → tenants(id) ON DELETE CASCADE |
| nombre | VARCHAR(100) | NOT NULL |
| es_open_box | BOOLEAN | NOT NULL, DEFAULT FALSE |
| activo | BOOLEAN | NOT NULL, DEFAULT TRUE |

### Tabla: `horarios_base`
| Columna | Tipo | Restricciones |
|---------|------|---------------|
| id | SERIAL | PRIMARY KEY |
| tenant_id | INTEGER | NOT NULL, FK → tenants(id) ON DELETE CASCADE |
| disciplina_id | INTEGER | NOT NULL, FK → disciplinas(id) |
| coach_id | INTEGER | FK → usuarios(id) |
| dia_semana | SMALLINT | NOT NULL, CHECK (0-6) |
| hora | TIME | NOT NULL |
| cupo_maximo | INTEGER | NOT NULL, DEFAULT 16 |
| activo | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

### Tabla: `clases`
| Columna | Tipo | Restricciones |
|---------|------|---------------|
| id | SERIAL | PRIMARY KEY |
| tenant_id | INTEGER | NOT NULL, FK → tenants(id) ON DELETE CASCADE |
| disciplina_id | INTEGER | NOT NULL, FK → disciplinas(id) |
| coach_id | INTEGER | FK → usuarios(id) |
| horario_base_id | INTEGER | FK → horarios_base(id) |
| fecha_hora | TIMESTAMPTZ | NOT NULL |
| cupo_maximo | INTEGER | NOT NULL, DEFAULT 16 |
| estado | VARCHAR(20) | NOT NULL, DEFAULT 'programada' |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |
| **UNIQUE** | | (tenant_id, disciplina_id, fecha_hora) |

### Tabla: `reservas`
| Columna | Tipo | Restricciones |
|---------|------|---------------|
| id | SERIAL | PRIMARY KEY |
| tenant_id | INTEGER | NOT NULL, FK → tenants(id) ON DELETE CASCADE |
| clase_id | INTEGER | NOT NULL, FK → clases(id) ON DELETE CASCADE |
| usuario_id | INTEGER | NOT NULL, FK → usuarios(id) ON DELETE CASCADE |
| suscripcion_id | INTEGER | NOT NULL, FK → suscripciones(id) |
| estado | estado_reserva (ENUM) | NOT NULL, DEFAULT 'confirmada' |
| token_devuelto | BOOLEAN | NOT NULL, DEFAULT FALSE |
| asistio | BOOLEAN | NULL |
| creado_en | TIMESTAMPTZ | NOT NULL, DEFAULT now() |
| cancelado_en | TIMESTAMPTZ | |
| **UNIQUE** | | (clase_id, usuario_id) |

**Enum `estado_reserva`**: `'confirmada'`, `'cancelada'`

---

## 3. ENDPOINTS DE LA API (FastAPI)

### Autenticación (`/auth`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/login` | Login con email+password, retorna JWT |

### Tenants (`/tenants`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/tenants/` | Crear nuevo tenant (box) |
| GET | `/tenants/` | Listar tenants con paginación |
| GET | `/tenants/{tenant_id}` | Obtener tenant por ID |
| GET | `/tenants/subdomain/{subdomain}` | Obtener tenant por subdominio |

### Usuarios (`/usuarios`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/usuarios/` | Crear nuevo usuario |
| GET | `/usuarios/` | Listar usuarios de un tenant |
| GET | `/usuarios/{usuario_id}` | Obtener usuario por ID |
| PUT | `/usuarios/{usuario_id}` | Actualizar usuario |
| DELETE | `/usuarios/{usuario_id}` | Desactivar usuario (soft delete) |
| PUT | `/usuarios/cambiar-password` | Cambiar contraseña del usuario autenticado |

### Clases (`/clases`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/clases/` | Listar clases con filtros |
| GET | `/clases/{clase_id}` | Obtener una clase por ID |
| POST | `/clases/` | Crear nueva clase |
| PUT | `/clases/{clase_id}` | Actualizar una clase |
| DELETE | `/clases/{clase_id}` | Eliminar una clase |

### Reservas (`/reservas`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/reservas` | Listar reservas de un tenant |
| GET | `/reservas/{reserva_id}` | Obtener reserva por ID |
| POST | `/reservas` | Crear reserva (valida aforo y descuenta token) |
| PUT | `/reservas/{reserva_id}` | Actualizar reserva |
| DELETE | `/reservas/{reserva_id}` | Cancelar reserva (decrementa asistentes) |

### Planes (`/planes`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/planes` | Listar planes de un tenant |
| GET | `/planes/membresia-activa` | Obtener membresía activa del alumno |
| GET | `/planes/{plan_id}` | Obtener plan por ID |
| POST | `/planes` | Crear nuevo plan |
| PUT | `/planes/{plan_id}` | Actualizar un plan |
| DELETE | `/planes/{plan_id}` | Desactivar plan (soft delete) |

### Suscripciones (`/suscripciones`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/suscripciones/suscripciones` | Listar suscripciones |
| POST | `/suscripciones/suscripciones` | Crear suscripción |

### Membresías (`/membresias`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/membresias/mi-membresia` | Obtener membresía activa con tokens del alumno |

### Disciplinas (`/disciplinas`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/disciplinas/` | Crear nueva disciplina |
| GET | `/disciplinas/` | Listar disciplinas |
| GET | `/disciplinas/{disciplina_id}` | Obtener disciplina por ID |
| PUT | `/disciplinas/{disciplina_id}` | Actualizar disciplina |
| DELETE | `/disciplinas/{disciplina_id}` | Desactivar disciplina (soft delete) |

### Horarios (`/horarios`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/horarios` | Crear horario base |
| GET | `/horarios` | Listar horarios base |
| GET | `/horarios/{horario_id}` | Obtener horario por ID |
| PUT | `/horarios/{horario_id}` | Actualizar horario |
| DELETE | `/horarios/{horario_id}` | Desactivar horario (soft delete) |

### Movimientos (Catálogo) (`/movimientos`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/movimientos` | Crear nuevo movimiento |
| GET | `/movimientos` | Listar movimientos |
| GET | `/movimientos/{movimiento_id}` | Obtener movimiento por ID |
| PUT | `/movimientos/{movimiento_id}` | Actualizar movimiento |
| DELETE | `/movimientos/{movimiento_id}` | Desactivar movimiento (soft delete) |

### WODs (`/api/v1/wods`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/v1/wods/parse` | Parsear texto de WOD y extraer movimientos |
| POST | `/api/v1/wods/` | Crear WOD con movimientos |
| GET | `/api/v1/wods/` | Listar WODs con filtros |
| GET | `/api/v1/wods/{wod_id}` | Obtener WOD por ID |
| PUT | `/api/v1/wods/{wod_id}` | Actualizar WOD (reemplaza movimientos) |
| DELETE | `/api/v1/wods/{wod_id}` | Eliminar WOD |
| POST | `/api/v1/wods/clases/{clase_id}/asignar-wod/{wod_id}` | Asignar WOD a una clase |

### Productos (`/productos`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/productos` | Crear producto con imagen opcional |
| GET | `/productos` | Listar productos |
| GET | `/productos/{producto_id}` | Obtener producto por ID |
| PUT | `/productos/{producto_id}` | Actualizar producto |
| DELETE | `/productos/{producto_id}` | Desactivar producto (soft delete) |

### Pedidos (`/pedidos`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/pedidos` | Crear pedido (valida stock y descuenta) |
| GET | `/pedidos` | Listar pedidos con filtros |
| GET | `/pedidos/{pedido_id}` | Obtener pedido por ID |
| PUT | `/pedidos/{pedido_id}/estado` | Avanzar estado del pedido (pendiente→validado→entregado) |
| PUT | `/pedidos/{pedido_id}` | Actualizar pedido |
| DELETE | `/pedidos/{pedido_id}` | Eliminar pedido (solo pendiente, restaura stock) |

### Dashboard (`/dashboard`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/dashboard/{tenant_id}` | Estadísticas del dashboard |

### Historial RM (`/historial_rm`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/historial_rm` | Crear RM con cálculo automático de nivel |
| GET | `/historial_rm` | Listar RMs con filtros |
| GET | `/historial_rm/{historial_id}` | Obtener RM por ID |
| PUT | `/historial_rm/{historial_id}` | Actualizar RM |
| DELETE | `/historial_rm/{historial_id}` | Eliminar RM |
| GET | `/historial_rm/alumnos/{alumno_id}/rms` | Mejor RM por movimiento para un alumno |
| GET | `/historial_rm/alumnos/{alumno_id}/nivel-general` | Nivel general del alumno |
| POST | `/historial_rm/nivel-fuerza` | Calcular nivel de fuerza |
| POST | `/historial_rm/nivel-gimnastico` | Calcular nivel gimnástico |

### Coach-Disciplinas (`/coach_disciplinas`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/coach_disciplinas` | Asignar coach a disciplina |
| GET | `/coach_disciplinas` | Listar relaciones coach-disciplina |
| GET | `/coach_disciplinas/{id}` | Obtener relación por ID |
| PUT | `/coach_disciplinas/{id}` | Actualizar relación |
| DELETE | `/coach_disciplinas/{id}` | Desactivar relación (soft delete) |

### Auditoría (`/auditoria`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/auditoria` | Crear registro de auditoría |
| GET | `/auditoria` | Listar registros con filtros |
| GET | `/auditoria/{auditoria_id}` | Obtener registro por ID |
| GET | `/auditoria/usuario/{usuario_id}` | Historial de auditoría por usuario |
| GET | `/auditoria/entidad/{entidad}/{entidad_id}` | Historial de auditoría por entidad |

### Retención (`/retencion`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/retencion` | Crear registro de retención |
| GET | `/retencion` | Listar registros de retención |
| GET | `/retencion/{retencion_id}` | Obtener registro por ID |
| GET | `/retencion/en-riesgo` | Alumnos en riesgo de abandono |
| GET | `/retencion/kpi-coach` | KPIs de retención por coach |
| PUT | `/retencion/{retencion_id}` | Actualizar retención |
| DELETE | `/retencion/{retencion_id}` | Eliminar retención |

### Fidelización (`/fidelizacion`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/fidelizacion/analizar/{tenant_id}` | Analizar asistencias y detectar alumnos en riesgo |
| POST | `/fidelizacion/registrar` | Registrar asistencia de un alumno |
| POST | `/fidelizacion/campana-email/{tenant_id}` | Enviar campaña de emails a ausentes |
| GET | `/fidelizacion/coach/{coach_id}/en-riesgo` | Alumnos en riesgo de un coach |

### Notificaciones (`/notificaciones`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/notificaciones` | Listar notificaciones de un alumno |
| PUT | `/notificaciones/{id}/leer` | Marcar notificación como leída |
| PUT | `/notificaciones/leer-todas` | Marcar todas como leídas |

### Solicitudes de Planes (`/solicitudes_planes`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/solicitudes_planes/solicitar` | Crear solicitud de plan (pendiente admin) |
| GET | `/solicitudes_planes/pendientes` | Listar solicitudes pendientes |
| GET | `/solicitudes_planes/{id}/voucher` | Descargar voucher de pago |
| PUT | `/solicitudes_planes/{id}/aprobar` | Aprobar solicitud y activar plan |
| PUT | `/solicitudes_planes/{id}/rechazar` | Rechazar solicitud |

### Upload (`/upload`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/upload/voucher` | Subir archivo de voucher |

### Reportes (`/reportes`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/reportes/monthly-sales` | Descargar reporte Excel de ventas mensuales |
| GET | `/reportes/dashboard` | Descargar dashboard en Excel |
| GET | `/reportes/` | Obtener analytics del dashboard |

### Migración (`/migracion`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/migracion/run` | Ejecutar migraciones pendientes vía HTTP |

### Fix Fechas (`/fix_fechas`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/fix_fechas/corregir-fechas` | Corregir fecha_expiracion de suscripciones activas |

### Comprar Emergencia (`/comprar_emergencia`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| *(pendiente de revisar)* | | Endpoint para compra de emergencia |

---

## 4. CONFIGURACIÓN DE LA APP (`backend/app/core/config.py`)

```python
class Settings(BaseSettings):
    # Información de la aplicación
    APP_NAME: str = "Box CrossFit Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Base de datos PostgreSQL (Neon)
    DATABASE_URL: str = "postgresql://user:pass@localhost/dbname"

    # Seguridad JWT
    JWT_SECRET_KEY: str = "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 horas

    # CORS - Dominios permitidos
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Configuración de archivos (vouchers)
    UPLOAD_DIR: str = "./uploads/vouchers"
    MAX_UPLOAD_SIZE_MB: int = 5
```

**Propiedades derivadas:**
- `cors_origins_list` → Convierte `CORS_ORIGINS` string en `List[str]`

---

## 5. PÁGINAS Y PANTALLAS DEL FRONTEND

### Frontend: React + Vite + Tailwind CSS

| Archivo | Ruta/Página | Rol |
|---------|-------------|-----|
| `src/App.jsx` | Componente raíz (maneja rutas) | Todos |
| `src/main.jsx` | Entry point de la app | Todos |
| `src/components/Layout.jsx` | Layout principal con navbar y sidebar | Todos |
| `src/components/ProtectedRoute.jsx` | HOC de protección de rutas | Todos |
| `src/components/ModalClase.jsx` | Modal para crear/editar clases | Admin/Coach |
| `src/components/ModalProducto.jsx` | Modal para crear/editar productos | Admin |
| `src/context/AuthContext.jsx` | Contexto de autenticación (JWT) | Todos |
| `src/config/roles.js` | Configuración de roles y permisos | - |
| `src/services/api.js` | Cliente HTTP (axios/fetch) con JWT | Todos |

### Páginas por Rol:

**Públicas:**
| Archivo | Ruta | Descripción |
|---------|------|-------------|
| `src/pages/Login.jsx` | `/login` | Inicio de sesión |
| `src/pages/Setup.jsx` | `/setup` | Configuración inicial del sistema |

**Admin:**
| Archivo | Ruta | Descripción |
|---------|------|-------------|
| `src/pages/admin/Dashboard.jsx` | `/admin/dashboard` | KPIs y métricas del box |
| `src/pages/admin/Alumnos.jsx` | `/admin/alumnos` | CRUD de alumnos |
| `src/pages/admin/Clases.jsx` | `/admin/clases` | Gestión de horarios y clases |
| `src/pages/admin/Coaches.jsx` | `/admin/coaches` | Gestión de coaches |
| `src/pages/admin/Bazar.jsx` | `/admin/bazar` | Tienda / productos del box |
| `src/pages/admin/Reportes.jsx` | `/admin/reportes` | Reportes y analytics |

**Coach:**
| Archivo | Ruta | Descripción |
|---------|------|-------------|
| `src/pages/coach/Dashboard.jsx` | `/coach/dashboard` | Dashboard del coach |
| `src/pages/coach/DashboardCoach.jsx` | `/coach/dashboard-alternativo` | Vista alternativa del coach |
| `src/pages/coach/Pizarra.jsx` | `/coach/pizarra` | Pizarra de WODs y RMs |

**Alumno:**
| Archivo | Ruta | Descripción |
|---------|------|-------------|
| `src/pages/alumno/Dashboard.jsx` | `/alumno/dashboard` | Dashboard del alumno |
| `src/pages/alumno/PizarraRMs.jsx` | `/alumno/rms` | Pizarra de RMs personales |

---

## ESTADÍSTICAS DEL PROYECTO

| Métrica | Valor |
|---------|-------|
| Total archivos en repo | ~200 |
| Endpoints API | ~60+ |
| Modelos SQLAlchemy | 18 |
| Tablas BD | 8 |
| Páginas Frontend | 14 |
| Componentes reutilizables | 4 |
| Commits en Git | 2 |