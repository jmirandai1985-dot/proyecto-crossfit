import React, { createContext, useState, useEffect } from 'react';
import api from '../services/api';

export const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
    const [usuario, setUsuario] = useState(null);
    const [token, setToken] = useState(null);
    const [rol, setRol] = useState(null);
    const [tenant_id, setTenant_id] = useState(null);
    const [usuario_id, setUsuario_id] = useState(null);
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [loading, setLoading] = useState(true);

    // Recuperar sesión desde localStorage al cargar
    useEffect(() => {
        const storedToken = localStorage.getItem('access_token');

        // ── N-7: la IDENTIDAD sale del SERVIDOR, no de localStorage ──
        // `usuario_id`, `rol` y `tenant_id` son datos de AUTORIZACIÓN: si se
        // toman de localStorage, cualquiera los edita desde la consola y el
        // front decide el menú/rutas con un valor manipulado. Ahora se hidratan
        // con `GET /alumnos/me` (misma fila que usa el backend para autorizar).
        // localStorage queda solo como caché visual del nombre.
        // Si la consulta falla, la sesión NO se restaura (fail-closed): sin
        // identidad verificada no se muestra ningún panel.
        const hidratar = async () => {
            if (!storedToken) {
                setLoading(false);
                return;
            }
            try {
                const { data } = await api.get('/api/v1/alumnos/me');
                setToken(storedToken);
                setUsuario_id(data.id);
                setRol(data.rol);
                setTenant_id(data.tenant_id);
                setUsuario(data.nombre || localStorage.getItem('usuario'));
                setIsAuthenticated(true);

                // Caché visual (nunca fuente de decisión).
                if (data.nombre) localStorage.setItem('usuario', data.nombre);
                if (data.rol) localStorage.setItem('rol', data.rol);
            } catch (e) {
                // El interceptor de `api.js` ya limpia y manda a /login en 401.
                console.error('No se pudo verificar la sesión contra el servidor:', e);
                setIsAuthenticated(false);
            } finally {
                setLoading(false);
            }
        };

        hidratar();
    }, []);

    // Persiste la sesión (localStorage + state) tras un login válido.
    const persistirSesion = ({ access_token, usuario_id, rol: userRol, tenant_id: userTenant, nombre }) => {
        localStorage.setItem('access_token', access_token);
        localStorage.setItem('usuario', nombre);
        localStorage.setItem('usuario_id', usuario_id);
        localStorage.setItem('rol', userRol);
        localStorage.setItem('tenant_id', userTenant);

        setToken(access_token);
        setUsuario(nombre);
        setRol(userRol);
        setTenant_id(userTenant);
        setUsuario_id(usuario_id);
        setIsAuthenticated(true);
    };

    const login = async (correo, password) => {
        try {
            const response = await api.post('/api/v1/auth/login', {
                correo,
                password,
            });

            const data = response.data;
            const userRol = data.rol;

            // Alumno nuevo con contraseña temporal: NO iniciamos sesión todavía.
            // El Login mostrará el modal de cambio forzado y, al terminar, repetirá
            // el login con la contraseña nueva (ya sin el flag).
            if (data.cambiar_password_al_login) {
                return {
                    success: true,
                    requiereCambioPassword: true,
                    accessToken: data.access_token,
                    rol: userRol,
                };
            }

            persistirSesion(data);

            return { success: true, rol: userRol, requiereCambioPassword: false };
        } catch (error) {
            const detail = error.response?.data?.detail;
            let errorMessage = 'Correo o contraseña incorrectos';

            if (typeof detail === 'string') {
                // Error simple de FastAPI (401, 403, etc.)
                errorMessage = detail;
            } else if (Array.isArray(detail) && detail.length > 0) {
                // Error de validación Pydantic 422: array de objetos {type, loc, msg, ...}
                errorMessage = detail[0]?.msg || 'Error de validación en los datos enviados';
            }

            return { success: false, error: errorMessage };
        }
    };

    const logout = () => {
        // Limpiar localStorage
        localStorage.removeItem('access_token');
        localStorage.removeItem('usuario');
        localStorage.removeItem('usuario_id');
        localStorage.removeItem('rol');
        localStorage.removeItem('tenant_id');

        // Limpiar state
        setToken(null);
        setUsuario(null);
        setRol(null);
        setTenant_id(null);
        setUsuario_id(null);
        setIsAuthenticated(false);

        // Redirigir a login
        window.location.href = '/login';
    };

    const value = {
        usuario,
        token,
        rol,
        tenant_id,
        usuario_id,
        isAuthenticated,
        loading,
        login,
        logout,
    };

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
    const context = React.useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth debe ser usado dentro de AuthProvider');
    }
    return context;
};
