import axios from 'axios';

// Cliente axios estándar (autenticado).
//
// API_URL = VITE_API_URL o '' (mismo origen).
// En Docker/producción se usa el path relativo: el navegador llama a
// /api/v1/... en el MISMO origen y nginx proxea /api/ → backend:8000.
// NUNCA se usa localhost por defecto (rompía dentro de contenedores).
const API_URL = import.meta.env.VITE_API_URL || '';

// Lee el token CSRF de la cookie `csrf_token` (NO httpOnly) sin dependencias
// nuevas: una sola línea de `document.cookie`.
const leerCsrfToken = () => {
    if (typeof document === 'undefined') return '';
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
};

const api = axios.create({
    baseURL: API_URL,
    // Hallazgo #15: el navegador manda la cookie httpOnly `access_token`
    // automáticamente (y el CSRF se inyecta abajo en cada mutación).
    withCredentials: true,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Interceptor de request: header CSRF en las mutaciones.
// El JWT ya NO se inyecta acá: viaja en la cookie httpOnly. Se respeta un
// `X-CSRF-Token` provisto explícitamente (p. ej. flujos custom).
api.interceptors.request.use(
    (config) => {
        const metodo = (config.method || '').toLowerCase();
        const headers = config.headers;
        if (['post', 'put', 'patch', 'delete'].includes(metodo) && headers && !headers.has('X-CSRF-Token')) {
            const csrf = leerCsrfToken();
            if (csrf) headers.set('X-CSRF-Token', csrf);
        }
        return config;
    },
    (error) => Promise.reject(error)
);

// Interceptor de response: manejar errores 401.
// El JWT ya no vive en localStorage, así que acá sólo se redirige a /login.
// Se saltan /auth/login (el propio login) y /alumnos/me (rehidratación de
// sesión): ese 401 lo maneja AuthContext sin redirigir en duro, para no entrar
// en bucle al recargar la página sin sesión.
api.interceptors.response.use(
    (response) => response,
    (error) => {
        const url = error.config?.url || '';
        const esLogin = url.includes('/auth/login');
        const esMe = url.includes('/alumnos/me');
        if (error.response && error.response.status === 401 && !esLogin && !esMe) {
            window.location.href = '/login';
        }
        return Promise.reject(error);
    }
);

export default api;
