# 🚀 Guía de Integración con la API de FastAPI

## ✅ Estado Actual del Proyecto

Tu aplicación frontend de React + Vite está **funcionando correctamente** y se puede acceder en:

**URL:** http://localhost:5173/

## 📁 Archivos Clave para Editar

### 1. **`src/App.jsx`** - Componente Principal
Este es el archivo que debes editar para integrar tu API de FastAPI. Actualmente contiene:
- Dashboard con KPIs simulados
- Sistema de validación de pagos
- Portal de autoservicio para alumnos

### 2. **Estructura de Carpetas Recomendada**

Para una mejor organización, te recomiendo crear la siguiente estructura:

```
frontend/src/
├── App.jsx                 # Componente principal (ya existe)
├── index.css              # Estilos Tailwind (ya configurado)
├── main.jsx               # Punto de entrada (ya existe)
├── services/              # 📌 CREAR ESTA CARPETA
│   └── api.js            # Configuración de llamadas a la API
├── components/            # 📌 CREAR ESTA CARPETA
│   ├── Dashboard.jsx     # Componente del dashboard
│   ├── PagosValidacion.jsx  # Componente de validación de pagos
│   └── PortalAlumno.jsx  # Componente del portal de alumnos
└── hooks/                 # 📌 CREAR ESTA CARPETA (opcional)
    └── useUsuarios.js    # Hook personalizado para usuarios
```

## 🔧 Pasos para Integrar la API

### Paso 1: Instalar Axios (Cliente HTTP)

Abre una nueva terminal y ejecuta:

```bash
cd C:\Users\Asus\Desktop\proyecto_box_crossfit\frontend
npm install axios
```

### Paso 2: Crear el Servicio de API

Crea el archivo `src/services/api.js`:

```javascript
import axios from 'axios';

// Configuración base de la API
const API_BASE_URL = 'http://localhost:8000/api/v1';

// Crear instancia de axios con configuración base
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor para agregar el tenant_id a todas las peticiones
api.interceptors.request.use((config) => {
  // Por ahora usamos el tenant demo
  config.headers['X-Tenant-ID'] = 'demo_box_2024';
  return config;
});

// Servicios de Usuarios
export const usuariosAPI = {
  // Obtener todos los usuarios
  getAll: () => api.get('/usuarios/'),
  
  // Obtener un usuario por ID
  getById: (id) => api.get(`/usuarios/${id}`),
  
  // Crear un nuevo usuario
  create: (data) => api.post('/usuarios/', data),
  
  // Actualizar un usuario
  update: (id, data) => api.put(`/usuarios/${id}`, data),
  
  // Eliminar un usuario
  delete: (id) => api.delete(`/usuarios/${id}`),
};

export default api;
```

### Paso 3: Ejemplo de Uso en App.jsx

Modifica `src/App.jsx` para consumir la API:

```javascript
import React, { useState, useEffect } from 'react';
import { usuariosAPI } from './services/api';
// ... resto de imports

export default function App() {
  const [currentTab, setCurrentTab] = useState('dashboard');
  const [usuarios, setUsuarios] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Cargar usuarios desde la API
  useEffect(() => {
    const fetchUsuarios = async () => {
      setLoading(true);
      try {
        const response = await usuariosAPI.getAll();
        setUsuarios(response.data);
        setError(null);
      } catch (err) {
        setError('Error al cargar usuarios: ' + err.message);
        console.error('Error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchUsuarios();
  }, []);

  // ... resto del código
}
```

### Paso 4: Ejemplo de Crear Usuario

```javascript
const handleCrearUsuario = async (datosUsuario) => {
  try {
    const nuevoUsuario = {
      nombre: datosUsuario.nombre,
      apellido: datosUsuario.apellido,
      email: datosUsuario.email,
      telefono: datosUsuario.telefono,
      rut: datosUsuario.rut,
      tipo_usuario: "alumno", // o "entrenador", "administrador"
      estado: "activo"
    };

    const response = await usuariosAPI.create(nuevoUsuario);
    console.log('Usuario creado:', response.data);
    
    // Actualizar la lista de usuarios
    setUsuarios([...usuarios, response.data]);
    
    alert('Usuario creado exitosamente');
  } catch (error) {
    console.error('Error al crear usuario:', error);
    alert('Error al crear usuario: ' + error.message);
  }
};
```

## 🌐 URLs Importantes

### Frontend (React + Vite)
- **Desarrollo:** http://localhost:5173/
- **Archivos a editar:** `src/App.jsx`, `src/services/api.js`

### Backend (FastAPI)
- **API Base:** http://localhost:8000
- **Documentación Swagger:** http://localhost:8000/docs
- **Endpoint Usuarios:** http://localhost:8000/api/v1/usuarios/

## 📝 Próximos Pasos Recomendados

1. **Instalar Axios:** `npm install axios`
2. **Crear carpeta services:** `mkdir src/services`
3. **Crear archivo api.js** con la configuración de arriba
4. **Modificar App.jsx** para consumir datos reales de la API
5. **Probar la integración** con el endpoint de usuarios

## 🔍 Verificar que el Backend esté Corriendo

Antes de integrar, asegúrate de que tu API de FastAPI esté corriendo:

```bash
cd C:\Users\Asus\Desktop\proyecto_box_crossfit\backend
python start_server.py
```

La API debería estar disponible en: http://localhost:8000

## 💡 Consejos

- **CORS:** Si tienes problemas de CORS, verifica que tu backend de FastAPI tenga configurado CORS para permitir peticiones desde `http://localhost:5173`
- **Tenant ID:** Todas las peticiones requieren el header `X-Tenant-ID`. El servicio de API ya lo incluye automáticamente.
- **Manejo de Errores:** Siempre usa try/catch para manejar errores de la API
- **Loading States:** Muestra indicadores de carga mientras se obtienen datos

## 🎨 Hot Module Replacement (HMR)

Tu aplicación ya tiene HMR activado. Cualquier cambio que hagas en `src/App.jsx` se reflejará automáticamente en el navegador sin necesidad de recargar la página.

---

**¡Tu entorno de desarrollo está listo! 🎉**

Abre http://localhost:5173/ en tu navegador para ver la aplicación funcionando.
