# ANÁLISIS DEL ERROR DE CONTRASEÑA EN BCRYPT

## Problema Identificado

El error `ValueError: password cannot be longer than 72 bytes, truncate manually if necessary` ocurre cuando bcrypt intenta hashear una contraseña que excede 72 bytes.

## Investigación Realizada

### 1. Frontend (Setup.jsx - líneas 44-66)
```javascript
const handleAdminSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
        await usuariosAPI.create({
            tenant_id: createdTenantId,
            ...adminData,  // Expande: rut, nombre, telefono, correo, password
            rol: 'administrador'
        });
        // ...
    }
};
```

**Hallazgo**: El objeto enviado es correcto. El campo `password` se envía tal como está en `adminData.password` sin concatenación.

### 2. API (frontend/src/services/api.js - líneas 76-85)
```javascript
create: async (data) => {
    const response = await fetch(`${API_BASE_URL}/usuarios/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    });
    return handleResponse(response);
},
```

**Hallazgo**: El JSON se serializa correctamente sin manipulación de la contraseña.

### 3. Backend (backend/app/api/v1/usuarios.py - línea 75)
```python
password_hash=hash_password(usuario_data.password),
```

**Hallazgo**: La contraseña se pasa directamente a `hash_password()` sin concatenación.

### 4. Función hash_password (backend/app/api/v1/usuarios.py - líneas 19-21)
```python
def hash_password(password: str) -> str:
    """Hashea una contraseña usando bcrypt"""
    return pwd_context.hash(password)
```

**Hallazgo**: Aquí es donde ocurre el error. La contraseña se pasa directamente a bcrypt.

## Causa Raíz

El error ocurre en la función `hash_password()` cuando bcrypt intenta hashear la contraseña. Esto significa que:

1. **La contraseña que llega al backend es más larga de lo esperado** (>72 bytes)
2. **NO hay concatenación en el frontend** - el campo password se envía limpio
3. **El problema está en el backend** - bcrypt rechaza contraseñas > 72 bytes

## Solución

Hay dos opciones:

### Opción 1: Truncar la contraseña en el backend (RECOMENDADO)
Modificar la función `hash_password()` para truncar a 72 bytes antes de hashear:

```python
def hash_password(password: str) -> str:
    """Hashea una contraseña usando bcrypt (máximo 72 bytes)"""
    # Bcrypt tiene un límite de 72 bytes, truncar si es necesario
    password_truncated = password[:72]
    return pwd_context.hash(password_truncated)
```

### Opción 2: Validar en el frontend
Agregar validación en el formulario para limitar a 72 caracteres (menos seguro).

## Recomendación

Implementar la **Opción 1** en el backend porque:
- Es más seguro (no expone el límite al usuario)
- Bcrypt ya tiene este límite por diseño
- Es una práctica común en aplicaciones profesionales
