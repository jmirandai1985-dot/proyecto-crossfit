# 🧪 Guía de Pruebas - API de Usuarios

Esta guía te ayudará a probar los endpoints de usuarios que acabamos de implementar.

## 📋 Requisitos Previos

1. **Backend corriendo**: El servidor FastAPI debe estar ejecutándose
2. **Base de datos**: Las tablas deben estar creadas en Neon
3. **Tenant demo**: Debe existir al menos un tenant en la base de datos

## 🚀 Paso 1: Iniciar el Servidor

Abre una terminal en la carpeta `backend` y ejecuta:

```bash
cd proyecto_box_crossfit/backend
uvicorn app.main:app --reload
```

Deberías ver algo como:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
🚀 Iniciando Box CrossFit Platform API...
📚 Documentación disponible en: http://localhost:8000/docs
```

## 🏢 Paso 2: Crear Tenant de Demostración

En otra terminal, ejecuta:

```bash
cd proyecto_box_crossfit/backend
python crear_tenant_demo.py
```

Este script creará un tenant con ID 1 que usaremos para las pruebas.

## 🧪 Paso 3: Ejecutar Pruebas Automáticas

Ejecuta el script de pruebas:

```bash
python test_usuarios_api.py
```

Este script probará automáticamente:
- ✅ Health check de la API
- ✅ Crear un usuario (alumno)
- ✅ Obtener usuario por ID
- ✅ Listar usuarios
- ✅ Actualizar usuario
- ✅ Crear un coach

## 📚 Paso 4: Probar con Swagger UI (Recomendado)

FastAPI genera documentación interactiva automáticamente. Abre tu navegador en:

**http://localhost:8000/docs**

### Probar Crear Usuario

1. Busca el endpoint `POST /api/v1/usuarios/`
2. Haz clic en "Try it out"
3. Modifica el JSON de ejemplo:

```json
{
  "tenant_id": 1,
  "rut": "11111111-1",
  "nombre": "Pedro Sánchez",
  "telefono": "+56912345678",
  "correo": "pedro.sanchez@example.com",
  "password": "mipassword123",
  "rol": "alumno"
}
```

4. Haz clic en "Execute"
5. Deberías ver una respuesta 201 con los datos del usuario creado

### Probar Obtener Usuario

1. Busca el endpoint `GET /api/v1/usuarios/{usuario_id}`
2. Haz clic en "Try it out"
3. Ingresa el ID del usuario que creaste (ejemplo: 1)
4. Haz clic en "Execute"
5. Deberías ver los datos del usuario

### Probar Listar Usuarios

1. Busca el endpoint `GET /api/v1/usuarios/`
2. Haz clic en "Try it out"
3. Ingresa:
   - `tenant_id`: 1
   - `skip`: 0
   - `limit`: 10
4. Haz clic en "Execute"
5. Deberías ver una lista de usuarios

### Probar Actualizar Usuario

1. Busca el endpoint `PUT /api/v1/usuarios/{usuario_id}`
2. Haz clic en "Try it out"
3. Ingresa el ID del usuario
4. Modifica los campos que quieras actualizar:

```json
{
  "nombre": "Pedro Sánchez Actualizado",
  "telefono": "+56987654321"
}
```

5. Haz clic en "Execute"
6. Deberías ver los datos actualizados

## 🔍 Verificar en la Base de Datos

Puedes verificar que los datos se guardaron correctamente conectándote a Neon:

```sql
-- Ver todos los usuarios
SELECT id, nombre, correo, rol, activo FROM usuarios;

-- Ver usuarios de un tenant específico
SELECT id, nombre, correo, rol FROM usuarios WHERE tenant_id = 1;

-- Contar usuarios por rol
SELECT rol, COUNT(*) FROM usuarios GROUP BY rol;
```

## 📝 Endpoints Disponibles

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/api/v1/usuarios/` | Crear nuevo usuario |
| GET | `/api/v1/usuarios/{id}` | Obtener usuario por ID |
| GET | `/api/v1/usuarios/` | Listar usuarios (con filtros) |
| PUT | `/api/v1/usuarios/{id}` | Actualizar usuario |
| DELETE | `/api/v1/usuarios/{id}` | Desactivar usuario (soft delete) |

## 🎯 Casos de Prueba Importantes

### ✅ Validaciones que Funcionan

1. **RUT único por tenant**: Intenta crear dos usuarios con el mismo RUT en el mismo tenant
2. **Email único por tenant**: Intenta crear dos usuarios con el mismo email
3. **Roles válidos**: Solo acepta 'alumno', 'coach', 'administrador'
4. **Contraseña hasheada**: La contraseña se guarda encriptada (bcrypt)

### 🧪 Pruebas Sugeridas

```bash
# 1. Crear usuario alumno
POST /api/v1/usuarios/
{
  "tenant_id": 1,
  "rut": "22222222-2",
  "nombre": "Ana López",
  "correo": "ana.lopez@example.com",
  "password": "password123",
  "rol": "alumno"
}

# 2. Crear usuario coach
POST /api/v1/usuarios/
{
  "tenant_id": 1,
  "rut": "33333333-3",
  "nombre": "Carlos Díaz",
  "correo": "carlos.diaz@example.com",
  "password": "coach123",
  "rol": "coach"
}

# 3. Crear usuario administrador
POST /api/v1/usuarios/
{
  "tenant_id": 1,
  "rut": "44444444-4",
  "nombre": "Laura Martínez",
  "correo": "laura.martinez@example.com",
  "password": "admin123",
  "rol": "administrador"
}

# 4. Intentar crear usuario con RUT duplicado (debe fallar)
POST /api/v1/usuarios/
{
  "tenant_id": 1,
  "rut": "22222222-2",  # RUT ya existe
  "nombre": "Otro Usuario",
  "correo": "otro@example.com",
  "password": "password123",
  "rol": "alumno"
}
```

## 🐛 Solución de Problemas

### Error: "No se pudo conectar a la API"
- Verifica que el servidor esté corriendo: `uvicorn app.main:app --reload`
- Verifica que esté en el puerto 8000: http://localhost:8000

### Error: "Ya existe un usuario con el RUT..."
- Esto es correcto, la validación está funcionando
- Usa un RUT diferente para cada usuario

### Error: "Usuario con ID X no encontrado"
- Verifica que el ID exista en la base de datos
- Usa el endpoint de listar para ver los IDs disponibles

### Error de conexión a la base de datos
- Verifica que el archivo `.env` tenga la URL correcta
- Verifica que Neon esté accesible

## 🎉 ¡Listo!

Si todas las pruebas pasan, tienes una API REST funcional con:
- ✅ Modelos SQLAlchemy
- ✅ Schemas Pydantic
- ✅ Endpoints CRUD completos
- ✅ Validaciones de negocio
- ✅ Documentación automática
- ✅ Conexión a base de datos Neon

## 📚 Próximos Pasos

1. Implementar autenticación JWT
2. Agregar middleware de tenant
3. Crear endpoints para Planes
4. Crear endpoints para Suscripciones
5. Crear endpoints para Clases y Reservas
