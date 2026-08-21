import axios from 'axios';

// Cliente axios estándar (autenticado).
//
// API_URL = VITE_API_URL o '' (mismo origen).
// En Docker/producción se usa el path relativo: el navegador llama a
// /api/v1/... en el MISMO origen y nginx proxea /api/ → backend:8000.
// NUNCA se usa localhost por defecto (rompía dentro de contenedores).
const API_URL = import.meta.env.VITE_API_URL || '';

const api = axios.create({
    baseURL: API_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Interceptor de request: agregar token JWT
api.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('access_token');
        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// Interceptor de response: manejar errores 401
api.interceptors.response.use(
    (response) => {
        return response;
    },
    (error) => {
        const isLoginEndpoint = error.config?.url?.includes('/auth/login');
        if (error.response && error.response.status === 401 && !isLoginEndpoint) {
            // Token inválido o expirado (solo fuera del endpoint de login)
            localStorage.removeItem('access_token');
            localStorage.removeItem('usuario');
            localStorage.removeItem('tenant_id');
            localStorage.removeItem('rol');
            localStorage.removeItem('usuario_id');
            window.location.href = '/login';
        }
        return Promise.reject(error);
    }
);

export default api;
