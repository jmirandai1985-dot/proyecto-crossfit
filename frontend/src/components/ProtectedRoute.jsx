import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { DASHBOARD_MAP } from '../config/roles';

// ─── Spinner ──────────────────────────────────────────────────────────────
const LoadingScreen = () => (
    <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: '#0f0f0f' }}
    >
        <div
            className="animate-spin rounded-full h-12 w-12 border-b-2"
            style={{ borderColor: '#f97316' }}
        />
    </div>
);

// ══════════════════════════════════════════════════════════════════════════
//  ProtectedRoute
//
//  Props:
//    children  — (opcional) componente a renderizar si el acceso es válido
//    roles     — array de roles permitidos (ej. ['administrador', 'admin'])
//
//  Uso:
//    - Como wrapper envolvente (con children):
//        <ProtectedRoute roles={ROLES_COACH}><MiComponente /></ProtectedRoute>
//    - Con rutas anidadas y <Outlet> (sin children):
//        <Route element={<ProtectedRoute roles={ROLES_COACH} />}>
//          <Route path="dashboard" ... />
//        </Route>
//
//  Lógica:
//    1. Mientras carga la sesión → spinner
//    2. No autenticado           → /login
//    3. Rol no permitido         → dashboard propio del usuario (DASHBOARD_MAP)
//    4. Todo OK                  → renderiza children o <Outlet />
// ══════════════════════════════════════════════════════════════════════════
const ProtectedRoute = ({ children, roles = [] }) => {
    const { isAuthenticated, rol, loading } = useAuth();

    // 1. Esperando que AuthContext cargue la sesión desde localStorage
    if (loading) return <LoadingScreen />;

    // 2. No autenticado → login
    if (!isAuthenticated) {
        return <Navigate to="/login" replace />;
    }

    // 3. Rol no permitido → redirigir al dashboard correcto del usuario
    //    Usa DASHBOARD_MAP de config/roles.js (fuente única de verdad).
    if (roles.length > 0 && !roles.includes(rol)) {
        const destino = DASHBOARD_MAP[rol] || '/login';
        return <Navigate to={destino} replace />;
    }

    // 4. Acceso válido → renderiza children si existe, sino <Outlet />
    return children || <Outlet />;
};

export default ProtectedRoute;