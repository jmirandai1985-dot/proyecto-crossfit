import axios from 'axios';

// Crear instancia de axios con baseURL
const api = axios.create({
    baseURL: 'http://localhost:8000',
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
