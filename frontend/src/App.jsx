import React, { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import { DASHBOARD_MAP, ROLES_ADMIN, ROLES_COACH, ROLES_ALUMNO } from './config/roles';

// ─── Pages públicas (EAGER) ───────────────────────────────────────────────
// Se quedan en el bundle inicial: son la primera pantalla para quien aún no
// inició sesión (landing con clase de prueba, login, reset de contraseña).
// Mantenerlas eager evita un spinner extra justo en la entrada.
import LandingPage from './pages/LandingPage';
import Login from './pages/Login';
import ResetPassword from './pages/ResetPassword';

// ─── Pages por rol (LAZY) ─────────────────────────────────────────────────
// Cada pantalla se importa dinámicamente => chunk propio, cargado SOLO al
// entrar a esa ruta. Así el alumno no descarga el código de admin/coach (ni
// al revés). El <Suspense> de más abajo muestra un spinner mientras llega el
// chunk de la ruta pedida y, ya cargado, se comporta igual que antes.
//
// · Familia ADMIN
const AdminDashboard = lazy(() => import('./pages/admin/Dashboard'));
const AdminAlumnos = lazy(() => import('./pages/admin/Alumnos'));
const AdminHistorialAlumno = lazy(() => import('./pages/admin/HistorialAlumno'));
const AdminCoaches = lazy(() => import('./pages/admin/Coaches'));
const AdminClases = lazy(() => import('./pages/admin/Clases'));
const AdminBazar = lazy(() => import('./pages/admin/Bazar'));
// Pedidos del Bazar: revisar comprobantes y avanzar el estado (pendiente → validado → entregado).
const AdminPedidos = lazy(() => import('./pages/admin/Pedidos'));
const AdminReportes = lazy(() => import('./pages/admin/Reportes'));
const AdminSupervisionClases = lazy(() => import('./pages/admin/SupervisionClases'));
const AdminConfiguracion = lazy(() => import('./pages/admin/Configuracion'));
const AdminNotificaciones = lazy(() => import('./pages/admin/Notificaciones'));
const AdminFidelizacion = lazy(() => import('./pages/admin/Fidelizacion'));
const AdminKpis = lazy(() => import('./pages/admin/Kpis'));
const AdminPlanes = lazy(() => import('./pages/admin/Planes'));
const AdminAlumnosPendientes = lazy(() => import('./pages/admin/AdminAlumnosPendientes'));
const AdminDisciplinas = lazy(() => import('./pages/admin/Disciplinas'));
const AdminAsistencia = lazy(() => import('./pages/admin/Asistencia'));
const AdminMiQr = lazy(() => import('./pages/admin/MiQr'));
// · Familia COACH
const CoachDashboard = lazy(() => import('./pages/coach/DashboardCoach'));
const CoachPizarra = lazy(() => import('./pages/coach/Pizarra'));
const CoachGenerarClases = lazy(() => import('./pages/coach/GenerarClases'));
const CoachGestionClases = lazy(() => import('./pages/coach/GestionClases'));
// Código de retiro del Bazar: el coach entrega pedidos con el código del alumno
// (misma pantalla/modal que usa el admin), sin ver listados ni montos.
const CoachEntregarPedido = lazy(() => import('./pages/coach/EntregarPedido'));
// · Familia ALUMNO
const AlumnoDashboard = lazy(() => import('./pages/alumno/Dashboard'));
const AlumnoMisReservas = lazy(() => import('./pages/alumno/MisReservas'));
const AlumnoPizarraRMs = lazy(() => import('./pages/alumno/PizarraRMs'));
const AlumnoAjustes = lazy(() => import('./pages/alumno/Ajustes'));
const AlumnoSolicitarPlan = lazy(() => import('./pages/alumno/SolicitarPlan'));
const AlumnoEvolucion = lazy(() => import('./pages/alumno/Evolucion'));
const AlumnoBazar = lazy(() => import('./pages/alumno/Bazar'));
const AlumnoMisPedidos = lazy(() => import('./pages/alumno/MisPedidos'));
const AlumnoPerformanceHub = lazy(() => import('./pages/alumno/PerformanceHub'));
const AlumnoMiProgreso = lazy(() => import('./pages/alumno/MiProgreso'));
const AlumnoMiHistorial = lazy(() => import('./pages/alumno/MiHistorial'));
// · Páginas públicas de acceso directo (TV y check-in por QR): fuera del
//   primer render, así que también van perezosas.
const RankingAsistencia = lazy(() => import('./pages/tv/RankingAsistencia'));
const AsistenciaQr = lazy(() => import('./pages/AsistenciaQr'));

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
        {/* Suspense: hace de fallback mientras se descarga el chunk de la ruta lazy. */}
        <Suspense fallback={<LoadingScreen />}>
        <Routes>

          {/* ── /landing → Landing pública de registro (clase de prueba) ── */}
          <Route path="/landing" element={<LandingPage />} />
          {/* ── /tv/ranking/:boxPublicId → Pantalla TV pública (sin login, sin sidebar) ── */}
          <Route path="/tv/ranking/:boxPublicId" element={<RankingAsistencia />} />
          {/* ── /asistencia/qr/:publicId → check-in del alumno escaneando el QR del box ── */}
          <Route path="/asistencia/qr/:publicId" element={<AsistenciaQr />} />
          {/* ── "/" → redirige según rol o a /login (RootRedirect) ── */}
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

          {/* ── /reset-password → nueva contraseña con token de un solo uso ── */}
          <Route path="/reset-password" element={<ResetPassword />} />

          {/* ── Rutas de Administrador ──────────────────────────── */}
          <Route path="/admin/*" element={<ProtectedRoute roles={ROLES_ADMIN} />}>
            <Route path="dashboard" element={<AdminDashboard />} />
            <Route path="alumnos" element={<AdminAlumnos />} />
            {/* Historial de UN alumno (se entra desde la tabla de Alumnos o desde la ficha). */}
            <Route path="alumnos/:alumnoId/historial" element={<AdminHistorialAlumno />} />
            <Route path="alumnos-pendientes" element={<AdminAlumnosPendientes />} />
            <Route path="coaches" element={<AdminCoaches />} />
            <Route path="clases" element={<AdminClases />} />
            <Route path="supervision-clases" element={<AdminSupervisionClases />} />
            <Route path="asistencia" element={<AdminAsistencia />} />
            <Route path="mi-qr" element={<AdminMiQr />} />
            <Route path="planes" element={<AdminPlanes />} />
            <Route path="disciplinas" element={<AdminDisciplinas />} />
            <Route path="bazar" element={<AdminBazar />} />
            <Route path="pedidos" element={<AdminPedidos />} />
            <Route path="reportes" element={<AdminReportes />} />
            <Route path="configuracion" element={<AdminConfiguracion />} />
            <Route path="notificaciones" element={<AdminNotificaciones />} />
            <Route path="fidelizacion" element={<AdminFidelizacion />} />
            <Route path="kpis" element={<AdminKpis />} />
            <Route path="*" element={<Navigate to="/admin/dashboard" replace />} />
          </Route>

          {/* ── Rutas de Coach ──────────────────────────────────── */}
          <Route path="/coach/*" element={<ProtectedRoute roles={ROLES_COACH} />}>
            <Route path="dashboard" element={<CoachDashboard />} />
            <Route path="pizarra" element={<CoachPizarra />} />
            <Route path="generar-clases" element={<CoachGenerarClases />} />
            <Route path="gestion-clases" element={<CoachGestionClases />} />
            {/* Mesón del Bazar: entrega con el código de retiro del alumno. */}
            <Route path="entregar-pedido" element={<CoachEntregarPedido />} />
            <Route path="*" element={<Navigate to="/coach/dashboard" />} />
          </Route>

          {/* ── Rutas de Alumno ─────────────────────────────────── */}
          <Route path="/alumno/*" element={<ProtectedRoute roles={ROLES_ALUMNO} />}>
            <Route path="dashboard" element={<AlumnoDashboard />} />
            <Route path="mis-reservas" element={<AlumnoMisReservas />} />
            <Route path="rms" element={<AlumnoPizarraRMs />} />
            <Route path="ajustes" element={<AlumnoAjustes />} />
            <Route path="solicitar-plan" element={<AlumnoSolicitarPlan />} />
            <Route path="evolucion" element={<AlumnoEvolucion />} />
            <Route path="bazar" element={<AlumnoBazar />} />
            <Route path="mis-pedidos" element={<AlumnoMisPedidos />} />
            <Route path="performance-hub" element={<AlumnoPerformanceHub />} />
            <Route path="mi-progreso" element={<AlumnoMiProgreso />} />
            <Route path="mi-historial" element={<AlumnoMiHistorial />} />
            <Route path="*" element={<Navigate to="/alumno/dashboard" />} />
          </Route>

          {/* ── 404 → redirige según rol o a /login ── */}
          <Route path="*" element={<RootRedirect />} />

        </Routes>
        </Suspense>
      </AuthProvider>
    </Router>
  );
}

export default App;