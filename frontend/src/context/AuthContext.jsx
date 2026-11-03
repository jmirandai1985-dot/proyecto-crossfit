import React, { createContext, useState, useEffect } from 'react';
import api from '../services/api';

export const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
    const [usuario, setUsuario] = useState(null);
    const [rol, setRol] = useState(null);
    const [tenant_id, setTenant_id] = useState(null);
    const [usuario_id, setUsuario_id] = useState(null);
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [loading, setLoading] = useState(true);

    // Rehidratar la sesión al cargar.
    // Hallazgo #15: ya NO hay JWT en localStorage; el token vive en la cookie
    // httpOnly y el navegador lo manda solo. La IDENTIDAD sale del SERVIDOR vía
    // `GET /alumnos/me` (misma fila que usa el backend para autorizar), nunca de
    // localStorage. Si la consulta falla (sin cookie válida), la sesión NO se
    // restaura (fail-closed). El interceptor de `api.js` NO redirige en duro acá
    // (salta /alumnos/me), así que este catch es el que decide el estado.
    useEffect(() => {
        const hidratar = async () => {
            try {
                const { data } = await api.get('/api/v1/alumnos/me');
                setUsuario_id(data.id);
                setRol(data.rol);
                setTenant_id(data.tenant_id);
                setUsuario(data.nombre || localStorage.getItem('usuario'));
                setIsAuthenticated(true);

                // Caché visual (nunca fuente de decisión).
                if (data.nombre) localStorage.setItem('usuario', data.nombre);
                if (data.rol) localStorage.setItem('rol', data.rol);
            } catch {
                setIsAuthenticated(false);
            } finally {
                setLoading(false);
            }
        };

        hidratar();
    }, []);

    // Persiste la sesión (estado de React + caché visual de localStorage) tras un
    // login válido. El JWT ya NO se persiste en localStorage: queda en la cookie
    // httpOnly que setea el backend en `POST /auth/login`.
    const persistirSesion = ({ usuario_id, rol: userRol, tenant_id: userTenant, nombre }) => {
        localStorage.setItem('usuario', nombre);
        localStorage.setItem('usuario_id', usuario_id);
        localStorage.setItem('rol', userRol);
        localStorage.setItem('tenant_id', userTenant);

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

    const logout = async () => {
        // Limpia las cookies httpOnly + CSRF en el backend (Max-Age=0).
        // Best-effort: si falla, se cierra igual en el cliente.
        try {
            await api.post('/api/v1/auth/logout');
        } catch {
            // La cookie puede estar expirada/ausente: se ignora.
        }

        // Limpiar caché visual de localStorage (el JWT ya no vive ahí).
        localStorage.removeItem('usuario');
        localStorage.removeItem('usuario_id');
        localStorage.removeItem('rol');
        localStorage.removeItem('tenant_id');

        // Limpiar state
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
