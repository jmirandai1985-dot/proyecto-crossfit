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
        const storedUsuario = localStorage.getItem('usuario');
        const storedRol = localStorage.getItem('rol');
        const storedTenant = localStorage.getItem('tenant_id');
        const storedUsuarioId = localStorage.getItem('usuario_id');

        if (storedToken && storedUsuario) {
            setToken(storedToken);
            setUsuario(storedUsuario);
            setRol(storedRol);
            setTenant_id(parseInt(storedTenant));
            setUsuario_id(parseInt(storedUsuarioId));
            setIsAuthenticated(true);
        }

        setLoading(false);
    }, []);

    const login = async (correo, password) => {
        try {
            const response = await api.post('/api/v1/auth/login', {
                correo,
                password,
            });

            const { access_token, usuario_id, rol: userRol, tenant_id: userTenant, nombre } = response.data;

            // Guardar en localStorage
            localStorage.setItem('access_token', access_token);
            localStorage.setItem('usuario', nombre);
            localStorage.setItem('usuario_id', usuario_id);
            localStorage.setItem('rol', userRol);
            localStorage.setItem('tenant_id', userTenant);

            // Actualizar state
            setToken(access_token);
            setUsuario(nombre);
            setRol(userRol);
            setTenant_id(userTenant);
            setUsuario_id(usuario_id);
            setIsAuthenticated(true);

            return { success: true, rol: userRol };
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
