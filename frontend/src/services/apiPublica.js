import axios from 'axios';

// Cliente axios para ENDPOINTS PÚBLICOS (pantalla TV del ranking, sin login).
//
// API_URL = VITE_API_URL o '' (mismo origen) — ver services/api.js.
// El navegador llama a /api/v1/ranking/... en el MISMO origen y nginx
// proxea /api/ → backend:8000. Nunca localhost por defecto.
//
// A diferencia de `services/api.js`, esta instancia NO tiene el interceptor
// que inyecta el JWT ni el que redirige a /login en un 401. El endpoint público
// de ranking nunca debería devolver 401, pero si por cualquier motivo ocurre,
// esta pantalla NO debe gatillar una redirección al login.
const API_URL = import.meta.env.VITE_API_URL || '';

const apiPublica = axios.create({
    baseURL: API_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

export default apiPublica;
