import axios from 'axios';

// Cliente axios para ENDPOINTS PÚBLICOS (pantalla TV del ranking, sin login).
//
// A diferencia de `services/api.js`, esta instancia NO tiene el interceptor
// que inyecta el JWT ni el que redirige a /login en un 401. El endpoint público
// de ranking nunca debería devolver 401, pero si por cualquier motivo ocurre,
// esta pantalla NO debe gatillar una redirección al login.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const apiPublica = axios.create({
    baseURL: API_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

export default apiPublica;
