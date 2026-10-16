// ─── FUENTE ÚNICA de menús por rol ──────────────────────────────────────────
// Cada ítem: { label, path, icon } donde `icon` es una CLAVE del registro de
// íconos (`config/menuIcons.jsx`). Los encabezados de sección usan
// { type: 'section', label } (no clickeables, sin ruta).
//
// Lo consumen: Layout.jsx (sidebar de los 3 roles) y, más adelante, la barra
// inferior del alumno. NO se duplican listas en ningún componente.
//
// Este módulo es JS PURO (sin JSX) a propósito: así los tests de rutas/roles
// (`scripts/test-menu.mjs`) lo pueden importar directamente con Node.

// Sub-pestañas del Dashboard del coach (dentro de /coach/dashboard?tab=...).
export const COACH_SUBTABS = [
    { key: 'resumen', label: '📊 Resumen', path: '/coach/dashboard?tab=resumen' },
    { key: 'clases', label: '📅 Clases', path: '/coach/dashboard?tab=clases' },
    { key: 'alumnos', label: '👥 Alumnos & RMs', path: '/coach/dashboard?tab=alumnos' },
    { key: 'asistencia', label: '📋 Asistencia', path: '/coach/dashboard?tab=asistencia' },
    { key: 'progreso', label: '📈 Progreso', path: '/coach/dashboard?tab=progreso' },
    { key: 'riesgo', label: '⚠️ Riesgo', path: '/coach/dashboard?tab=riesgo' },
];

// Menú completo por rol.
export const MENU_BY_ROL = {
    alumno: [
        { label: 'Inicio', path: '/alumno/dashboard', icon: 'home' },
        { label: 'Planes', path: '/alumno/solicitar-plan', icon: 'settings' },
        { label: 'Mis Reservas', path: '/alumno/mis-reservas', icon: 'calendar' },
        { label: 'Pizarra de RMs', path: '/alumno/rms', icon: 'dumbbell' },
        { label: 'Evolución', path: '/alumno/evolucion', icon: 'home' },
        { label: 'Performance Hub', path: '/alumno/performance-hub', icon: 'dumbbell' },
        { label: 'Mi Progreso', path: '/alumno/mi-progreso', icon: 'chart' },
        { label: 'Bazar', path: '/alumno/bazar', icon: 'dumbbell' },
        { label: 'Mis Pedidos', path: '/alumno/mis-pedidos', icon: 'calendar' },
        { label: 'Mi Historial', path: '/alumno/mi-historial', icon: 'chart' },
        { label: 'Ajustes', path: '/alumno/ajustes', icon: 'settings' },
    ],
    coach: [
        { label: 'Dashboard', path: '/coach/dashboard', icon: 'home' },
        // NO hay ítem "Gestión de Clases": era la configuración antigua y, al tocar una clase
        // en "Mis clases de hoy", el coach caía ahí y tardaba en cargar. Su vista semanal
        // (grilla Lun→Dom + filtro "Ver todas / Ver solo con WOD publicado") vive DENTRO del
        // Dashboard, en la sub-pestaña `?tab=clases` (`COACH_SUBTABS`, más abajo), y publicar
        // o editar un WOD abre el modal unificado en la MISMA pantalla.
        // La pantalla se retiró POR COMPLETO (menú, ruta y archivo `GestionClases.jsx`):
        // editar un WOD publicado es un modo del mismo `ModalPublicarWod` (`PUT /wods/{id}`),
        // la carga masiva por Excel y el aviso rápido del día son botones de la pestaña
        // Clases, y tomar/soltar/cubrir suplencia vive en `AccionesClaseCoach`.
        // Mesón del Bazar: entregar un pedido con el código de retiro del alumno
        // (mismo modal que el admin; sin listados ni montos).
        { label: 'Entregar pedido', path: '/coach/entregar-pedido', icon: 'qr' },
    ],
    administrador: [
        { label: 'Dashboard', path: '/admin/dashboard', icon: 'adminDashboard' },
        { label: 'Alumnos', path: '/admin/alumnos', icon: 'users' },
        { label: 'Pendientes', path: '/admin/alumnos-pendientes', icon: 'clock' },
        { label: 'Coaches', path: '/admin/coaches', icon: 'users' },
        { label: 'Supervisión', path: '/admin/supervision-clases', icon: 'eye' },
        { label: 'Asistencia', path: '/admin/asistencia', icon: 'squareCheck' },
        { label: 'Mi QR', path: '/admin/mi-qr', icon: 'qrcode' },

        // ── CATÁLOGO ──
        { type: 'section', label: 'CATÁLOGO' },
        { label: 'Planes', path: '/admin/planes', icon: 'creditCard' },
        { label: 'Disciplinas', path: '/admin/disciplinas', icon: 'dumbbellLc' },
        { label: 'Bazar', path: '/admin/bazar', icon: 'shoppingCart' },
        { label: 'Pedidos', path: '/admin/pedidos', icon: 'shoppingBag' },
        // Marketing: los avisos del carrusel "Novedades del box" del Inicio del
        // alumno (promociones, colaboraciones, avisos del box y eventos). Las
        // tarjetas de producto nuevo las genera el Bazar solo (días de anuncio).
        { label: 'Marketing', path: '/admin/marketing', icon: 'megaphone' },

        // ── ANÁLISIS ──
        { type: 'section', label: 'ANÁLISIS' },
        { label: 'Fidelización', path: '/admin/fidelizacion', icon: 'heart' },
        // `tag` = marca para el menú MÓVIL (<768px): la pantalla se ve mejor en PC.
        // No bloquea el acceso, solo avisa (y en ≥768px la barra lateral queda igual).
        { label: 'KPIs', path: '/admin/kpis', icon: 'trendingUp', tag: 'mejor en PC' },
        { label: 'Reportes', path: '/admin/reportes', icon: 'fileText', tag: 'mejor en PC' },

        // ── SISTEMA ──
        { type: 'section', label: 'SISTEMA' },
        { label: 'Notificaciones', path: '/admin/notificaciones', icon: 'bell' },
        { label: 'Configuración', path: '/admin/configuracion', icon: 'gear' },
    ],
};

// Alias defensivo: 'admin' es la variante corta usada en algunos contextos.
MENU_BY_ROL.admin = MENU_BY_ROL.administrador;

// Devuelve el menú de un rol. Para el alumno en plan de prueba se restringe a
// Clases (Inicio) + Planes. N-6 (fail-closed): mientras no se confirme que NO
// es de prueba (`esPrueba === false`), el menú queda restringido.
export function getMenuItems(rol, { esPrueba } = {}) {
    if (rol === 'alumno') {
        const items = MENU_BY_ROL.alumno;
        if (esPrueba !== false) {
            return items.filter((i) => i.label === 'Inicio' || i.label === 'Planes');
        }
        return items;
    }
    return MENU_BY_ROL[rol] || [];
}
