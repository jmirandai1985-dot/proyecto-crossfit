# Backend - Plataforma de Gestión de Box CrossFit

Backend desarrollado con **FastAPI** para gestionar boxes de CrossFit en un modelo multi-tenant SaaS.

## 🏗️ Arquitectura

- **Framework**: FastAPI (Python 3.10+)
- **Base de datos**: PostgreSQL en Neon (conexión remota)
- **ORM**: SQLAlchemy 2.0 + Alembic (migraciones)
- **Autenticación**: JWT manual (python-jose + passlib/argon2)
- **Despliegue**: VPS o servidor dedicado (NO serverless)

## 📋 Requisitos Previos

1. **Python 3.10 o superior** instalado
2. **Cuenta en Neon** (neon.com) con una base de datos PostgreSQL creada
3. **Git** (opcional, para control de versiones)

## 🚀 Instalación y Configuración

### 1. Crear entorno virtual

```bash
# Navegar a la carpeta backend
cd C:\Users\Asus\Desktop\proyecto_box_crossfit\backend

# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# En Windows:
venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
# Copiar el archivo de ejemplo
copy .env.example .env

# Editar .env con tus credenciales reales:
# - DATABASE_URL: cadena de conexión de Neon
# - JWT_SECRET_KEY: generar con: openssl rand -hex 32
```

**Ejemplo de DATABASE_URL de Neon:**
```
postgresql://usuario:password@ep-xxxxx.region.aws.neon.tech/nombredb?sslmode=require
```

### 4. Inicializar Alembic (migraciones)

```bash
# Esto se hará después de crear los modelos SQLAlchemy
alembic init alembic
```

### 5. Ejecutar el servidor de desarrollo

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

El servidor estará disponible en: `http://localhost:8000`

Documentación interactiva (Swagger): `http://localhost:8000/docs`

## 📁 Estructura del Proyecto

```
backend/
├── app/
│   ├── main.py                    # Punto de entrada FastAPI
│   ├── core/                      # Configuración central
│   │   ├── config.py              # Variables de entorno
│   │   ├── security.py            # JWT y hashing
│   │   └── tenant.py              # Middleware multi-tenant
│   ├── db/                        # Base de datos
│   │   ├── session.py             # Conexión a Neon
│   │   └── base.py                # Base SQLAlchemy
│   ├── models/                    # Modelos SQLAlchemy (8 tablas)
│   │   ├── tenant.py
│   │   ├── usuario.py
│   │   ├── plan.py
│   │   ├── suscripcion.py
│   │   ├── disciplina.py
│   │   ├── horario_base.py
│   │   ├── clase.py
│   │   └── reserva.py
│   ├── schemas/                   # Pydantic (validación)
│   │   ├── auth.py
│   │   ├── usuario.py
│   │   ├── plan.py
│   │   ├── suscripcion.py
│   │   ├── clase.py
│   │   └── reserva.py
│   ├── api/v1/                    # Endpoints REST
│   │   ├── auth.py                # Login con RUT
│   │   ├── usuarios.py            # CRUD usuarios
│   │   ├── planes.py              # CRUD planes
│   │   ├── suscripciones.py       # Vouchers y aprobación
│   │   ├── clases.py              # Gestión de clases
│   │   ├── reservas.py            # Reservas y cancelaciones
│   │   └── dashboard.py           # Reportes (admin)
│   └── services/                  # Lógica de negocio
│       ├── token_service.py       # Descuento/devolución tokens
│       ├── aforo_service.py       # Validación de cupos
│       ├── suscripcion_service.py # Activación de planes
│       └── clase_generator.py     # Generación automática de clases
├── alembic/                       # Migraciones de BD
├── tests/                         # Tests unitarios
├── requirements.txt               # Dependencias Python
├── .env.example                   # Plantilla de configuración
├── .gitignore                     # Archivos ignorados por Git
└── README.md                      # Este archivo
```

## 🔑 Reglas de Negocio Críticas

### Multi-tenancy
- Cada box es un **tenant** identificado por subdominio
- Todas las queries filtran por `tenant_id` automáticamente
- Un mismo RUT puede existir en múltiples boxes como cuentas independientes

### Sistema de Tokens
- **Al reservar**: se descuenta 1 token inmediatamente
- **Cancelación con 2+ horas**: token devuelto
- **Cancelación tardía o no-show**: token perdido
- Los tokens duran **30 días desde la aprobación** del plan (no mes calendario)

### Aforo de Clases
- Máximo **16 personas** por clase
- Validación con `SELECT FOR UPDATE` para evitar overbooking

### Disciplinas
- Todas las disciplinas (CrossFit, GAP, Musculación, Open Box) descuentan **1 token del mismo pool**
- No hay créditos separados por tipo de clase

## 🧪 Testing

```bash
# Ejecutar tests
pytest

# Con cobertura
pytest --cov=app tests/
```

## 📝 Próximos Pasos

1. ✅ Configurar entorno local (este paso)
2. ⏳ Crear modelos SQLAlchemy basados en schema.sql
3. ⏳ Configurar Alembic y ejecutar primera migración
4. ⏳ Implementar autenticación JWT
5. ⏳ Desarrollar endpoints críticos (reservas, suscripciones)
6. ⏳ Testing de reglas de negocio
7. ⏳ Despliegue a VPS/servidor dedicado

## 🔒 Seguridad

- **NO** subir el archivo `.env` a GitHub (ya está en `.gitignore`)
- Usar contraseñas seguras para la base de datos
- Cambiar `JWT_SECRET_KEY` en producción
- Configurar CORS solo para dominios confiables

## 📞 Soporte

Para dudas o problemas, revisar la documentación de:
- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/)
- [Neon PostgreSQL](https://neon.tech/docs)
