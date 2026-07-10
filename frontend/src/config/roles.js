// ─── Fuente única de verdad: rutas por rol ────────────────────────────────
// Soporta 'administrador' (ENUM real en BD PostgreSQL)
// y 'admin' (alias usado en algunos contextos del sistema).
export const DASHBOARD_MAP = {
    administrador: '/admin/dashboard',
    admin: '/admin/dashboard', // alias defensivo
    coach: '/coach/dashboard',
    alumno: '/alumno/dashboard',
};

// Roles agrupados por sección
export const ROLES_ADMIN = ['administrador', 'admin'];
export const ROLES_COACH = ['coach'];
export const ROLES_ALUMNO = ['alumno'];