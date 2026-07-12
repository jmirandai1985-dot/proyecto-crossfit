import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import { DASHBOARD_MAP, ROLES_ADMIN, ROLES_COACH, ROLES_ALUMNO } from './config/roles';

// ─── Pages ──────────────────────────────────────────────────────────────
import Login from './pages/Login';
import AdminDashboard from './pages/admin/Dashboard';
import AdminAlumnos from './pages/admin/Alumnos';
import AdminCoaches from './pages/admin/Coaches';
import AdminClases from './pages/admin/Clases';
import AdminBazar from './pages/admin/Bazar';
import AdminReportes from './pages/admin/Reportes';
import CoachDashboard from './pages/coach/DashboardCoach';
import CoachPizarra from './pages/coach/Pizarra';
import CoachGenerarClases from './pages/coach/GenerarClases';
import AlumnoDashboard from './pages/alumno/Dashboard';
import AlumnoMisReservas from './pages/alumno/MisReservas';
import AlumnoPizarraRMs from './pages/alumno/PizarraRMs';
import AlumnoAjustes from './pages/alumno/Ajustes';
import AlumnoSolicitarPlan from './pages/alumno/SolicitarPlan';

// ─── Spinner compartido ────────────────────────────────────────────────
const LoadingScreen = () => (
  <div className="min-h-screen flex items-center justify-center bg-gray-50">
    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" />
  </div>
);

// ─── Redirección inteligente según rol ─────────────────────────────────
const RootRedirect = () => {
  const { isAuthenticated, rol, loading } = useAuth();
  if (loading) return <LoadingScreen />;
  if (isAuthenticated && rol) {
    return <Navigate to={DASHBOARD_MAP[rol] || '/login'} replace />;
  }
  return <Navigate to="/login" replace />;
};

// ─── Ruta pública (solo para no autenticados) ─────────────────────────
const PublicRoute = ({ children }) => {
  const { isAuthenticated, rol, loading } = useAuth();
  if (loading) return <LoadingScreen />;
  if (isAuthenticated && rol) {
    return <Navigate to={DASHBOARD_MAP[rol] || '/login'} replace />;
  }
  return children;
};

// ═══════════════════════════════════════════════════════════════════════
// APP — árbol de rutas
// ═══════════════════════════════════════════════════════════════════════
function App() {
  return (
    <Router>
      <AuthProvider>
        <Routes>

          {/* ── "/" → redirige según rol o a /login ── */}
          <Route path="/" element={<RootRedirect />} />

          {/* ── /login → si ya autenticado, redirige a su dashboard ── */}
          <Route
            path="/login"
            element={
              <PublicRoute>
                <Login />
              </PublicRoute>
            }
          />

          {/* ── Rutas de Administrador ──────────────────────────── */}
          <Route path="/admin/*" element={<ProtectedRoute roles={ROLES_ADMIN} />}>
            <Route path="dashboard" element={<AdminDashboard />} />
            <Route path="alumnos" element={<AdminAlumnos />} />
            <Route path="coaches" element={<AdminCoaches />} />
            <Route path="clases" element={<AdminClases />} />
            <Route path="bazar" element={<AdminBazar />} />
            <Route path="reportes" element={<AdminReportes />} />
            <Route path="*" element={<Navigate to="/admin/dashboard" replace />} />
          </Route>

          {/* ── Rutas de Coach ──────────────────────────────────── */}
          <Route path="/coach/*" element={<ProtectedRoute roles={ROLES_COACH} />}>
            <Route path="dashboard" element={<CoachDashboard />} />
            <Route path="pizarra" element={<CoachPizarra />} />
            <Route path="generar-clases" element={<CoachGenerarClases />} />
            <Route path="*" element={<Navigate to="/coach/dashboard" />} />
          </Route>

          {/* ── Rutas de Alumno ─────────────────────────────────── */}
          <Route path="/alumno/*" element={<ProtectedRoute roles={ROLES_ALUMNO} />}>
            <Route path="dashboard" element={<AlumnoDashboard />} />
            <Route path="mis-reservas" element={<AlumnoMisReservas />} />
            <Route path="rms" element={<AlumnoPizarraRMs />} />
            <Route path="ajustes" element={<AlumnoAjustes />} />
            <Route path="solicitar-plan" element={<AlumnoSolicitarPlan />} />
            <Route path="*" element={<Navigate to="/alumno/dashboard" />} />
          </Route>

          {/* ── 404 → redirige según rol o a /login ── */}
          <Route path="*" element={<RootRedirect />} />

        </Routes>
      </AuthProvider>
    </Router>
  );
}

export default App;