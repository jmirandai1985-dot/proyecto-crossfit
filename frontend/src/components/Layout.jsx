import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
// Fuente única de menús por rol + registro de íconos (los comparte la barra
// inferior del alumno que llega en un paso posterior). Ver config/menu.js.
import { getMenuItems, COACH_SUBTABS } from '../config/menu';
import { MENU_ICONS } from '../config/menuIcons';
// N-2: campana de notificaciones del alumno (contador de no leídas + panel).
import CampanaNotificaciones from './CampanaNotificaciones';

const Layout = ({ children }) => {
    const { usuario, rol, logout } = useAuth();
    const [sidebarOpen, setSidebarOpen] = useState(true);
    // Drawer off-canvas para <md (arranca CERRADO). En >=md la barra es estática
    // (igual que hoy) y `sidebarOpen` controla el COLAPSAR de escritorio.
    const [mobileOpen, setMobileOpen] = useState(false);
    // ── N-6: `esPrueba` arranca en null = "todavía no sé". ──
    // Mientras no haya dato (o si la consulta falla) el menú del alumno queda
    // RESTRINGIDO: un chequeo de permisos no puede ABRIR el acceso cuando falla.
    // Antes, un error dejaba `esPrueba = false` (menú completo) y cada pantalla
    // de pago respondía 403 sin explicación.
    const [esPrueba, setEsPrueba] = useState(null);
    const [esPruebaError, setEsPruebaError] = useState(false);
    const [reintentoEsPrueba, setReintentoEsPrueba] = useState(0);
    const location = useLocation();
    const searchParams = new URLSearchParams(location.search);
    const currentTab = searchParams.get('tab') || 'resumen';

    // Alumno nuevo con plan de prueba: menú restringido a Clases + Planes.
    // N-6: si la consulta falla, se asume RESTRINGIDO (fail-closed) y se ofrece
    // Reintentar; nunca se asume "no es de prueba".
    useEffect(() => {
        if (rol !== 'alumno') return;
        let cancelado = false;
        setEsPruebaError(false);
        api.get('/api/v1/alumnos/me/es-prueba')
            .then(({ data }) => {
                if (!cancelado) setEsPrueba(Boolean(data?.es_prueba));
            })
            .catch((e) => {
                console.error('No se pudo verificar el plan de prueba del alumno:', e);
                if (!cancelado) {
                    setEsPrueba(true);      // fail-closed: menú restringido
                    setEsPruebaError(true); // + aviso con Reintentar
                }
            });
        return () => { cancelado = true; };
    }, [rol, reintentoEsPrueba]);

    // El drawer debe cerrarse AL NAVEGAR (cambia la ruta).
    useEffect(() => {
        setMobileOpen(false);
    }, [location.pathname]);

    // ... y con la tecla Escape (accesibilidad).
    useEffect(() => {
        if (!mobileOpen) return;
        const onKey = (e) => { if (e.key === 'Escape') setMobileOpen(false); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [mobileOpen]);

    const isCoachDashboard = location.pathname === '/coach/dashboard';

    // Menú del rol desde la fuente única (config/menu.js). El alumno en plan de
    // prueba queda restringido (fail-closed) según `esPrueba`.
    const menuItems = getMenuItems(rol, { esPrueba });
    const isActive = (path) => location.pathname === path;

    return (
        <div className="flex h-[100dvh] bg-zinc-950">
            {/* Backdrop del drawer (solo <md; en escritorio no existe) */}
            {mobileOpen && (
                <div
                    className="fixed inset-0 z-40 bg-black/60 md:hidden"
                    onClick={() => setMobileOpen(false)}
                    aria-hidden="true"
                />
            )}

            {/* Sidebar: drawer off-canvas en <md (arranca cerrado); estática en >=md */}
            <div
                className={`fixed md:static inset-y-0 left-0 z-50 w-64 ${sidebarOpen ? 'md:w-64' : 'md:w-20'
                    } bg-zinc-900 border-r border-zinc-800 transition-transform md:transition-all duration-300 flex flex-col shadow-sm ${mobileOpen ? 'translate-x-0' : '-translate-x-full'
                    } md:translate-x-0`}
            >
                {/* Logo */}
                <div className="p-5 border-b border-zinc-800">
                    <div className="flex items-center gap-3">
                        <img src="/imgs/logo.png" alt="Urban Box" className="w-10 h-10 object-contain shrink-0" />
                        {sidebarOpen && (
                            <div>
                                <h2 className="font-bold text-white text-sm leading-tight">URBAN BOX</h2>
                                <p className="text-[10px] text-zinc-400">CrossFit Maipú</p>
                            </div>
                        )}
                        {/* Cerrar el drawer (solo <md) */}
                        <button
                            type="button"
                            onClick={() => setMobileOpen(false)}
                            aria-label="Cerrar menú"
                            className="md:hidden ml-auto p-2 rounded-lg text-zinc-400 hover:bg-zinc-800"
                        >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                </div>

                {/* ── N-6: si no pudimos verificar el plan, el menú queda restringido
                    y el alumno tiene una salida visible (Reintentar) en vez de un
                    menú completo que después responde 403. ── */}
                {rol === 'alumno' && esPruebaError && (
                    <div className="mx-3 mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
                        {sidebarOpen && (
                            <p className="mb-1.5">⚠️ No pudimos verificar tu plan: mostrando el menú restringido.</p>
                        )}
                        <button
                            type="button"
                            onClick={() => setReintentoEsPrueba((n) => n + 1)}
                            className="w-full rounded-md bg-amber-500/20 px-2 py-1 font-semibold text-amber-100 hover:bg-amber-500/30 transition-colors"
                        >
                            Reintentar
                        </button>
                    </div>
                )}

                {/* Menu Items */}
                <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
                    {menuItems.map((item) =>
                        item.type === 'section' ? (
                            /* ── Encabezado de sección (no clickeable) ── */
                            <div
                                key={`section-${item.label}`}
                                className={sidebarOpen ? 'pt-4 pb-1 px-3' : 'pt-5 pb-1 px-2'}
                            >
                                {sidebarOpen
                                    ? <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{item.label}</span>
                                    : <div className="border-t border-zinc-800" />}
                            </div>
                        ) : (
                        <div key={item.label}>
                            <Link
                                to={item.path}
                                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all text-base ${isActive(item.path) || (rol === 'coach' && item.label === 'Dashboard' && isCoachDashboard)
                                    ? 'bg-orange-500/20 text-orange-300 font-semibold ring-1 ring-orange-500/40'
                                    : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'
                                    }`}
                            >
                                <span className={`${isActive(item.path) ? 'text-orange-500' : 'text-zinc-500'}`}>
                                    {MENU_ICONS[item.icon]}
                                </span>
                                {sidebarOpen && <span>{item.label}</span>}
                            </Link>
                            {/* Coach sub-tabs under Dashboard */}
                            {rol === 'coach' && item.label === 'Dashboard' && sidebarOpen && isCoachDashboard && (
                                <div className="ml-6 mt-1 space-y-0.5 border-l-2 border-orange-500/40 pl-2">
                                    {COACH_SUBTABS.map((sub) => (
                                        <Link
                                            key={sub.key}
                                            to={sub.path}
                                            className={`block px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${currentTab === sub.key
                                                ? 'bg-orange-500/20 text-orange-400'
                                                : 'text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300'
                                                }`}
                                        >
                                            {sub.label}
                                        </Link>
                                    ))}
                                </div>
                            )}
                            {/* Always show sub-tabs when coach is on dashboard path */}
                            {rol === 'coach' && item.label === 'Dashboard' && sidebarOpen && !isCoachDashboard && (
                                <div className="ml-6 mt-1 space-y-0.5 border-l-2 border-zinc-700 pl-2">
                                    {COACH_SUBTABS.map((sub) => (
                                        <Link
                                            key={sub.key}
                                            to={sub.path}
                                            className={`block px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${false
                                                ? 'bg-orange-500/20 text-orange-400'
                                                : 'text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300'
                                                }`}
                                        >
                                            {sub.label}
                                        </Link>
                                    ))}
                                </div>
                            )}
                        </div>
                        )
                    )}
                </nav>

                {/* User & Logout */}
                <div className="p-4 border-t border-zinc-800 space-y-3"
                    style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}>
                    {sidebarOpen && (
                        <div className="px-2">
                            <p className="text-sm font-medium text-zinc-100 truncate">{usuario || 'Usuario'}</p>
                            <p className="text-xs text-zinc-500 capitalize">{rol}</p>
                        </div>
                    )}
                    <button
                        onClick={logout}
                        className="w-full flex items-center gap-3 px-3 py-2.5 text-base text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                    >
                        <span className="text-red-500">{MENU_ICONS.logout}</span>
                        {sidebarOpen && <span>Cerrar Sesión</span>}
                    </button>
                    <button
                        onClick={() => setSidebarOpen(!sidebarOpen)}
                        className="w-full hidden md:flex items-center justify-center py-2 text-zinc-500 hover:bg-zinc-800 rounded-lg transition-colors text-xs"
                    >
                        {sidebarOpen ? '◀ Colapsar' : '▶'}
                    </button>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 flex flex-col overflow-hidden">
                {/* Header */}
                <header className="relative z-30 bg-zinc-900 border-b border-zinc-800"
                    style={{ paddingTop: 'env(safe-area-inset-top)' }}>
                    <div className="flex items-center justify-between px-3 md:px-6 py-3">
                        <div className="flex items-center gap-2 min-w-0">
                            {/* Hamburguesa: abre el drawer en <md (en escritorio no existe) */}
                            <button
                                type="button"
                                onClick={() => { setSidebarOpen(true); setMobileOpen(true); }}
                                aria-label="Abrir menú"
                                className="md:hidden shrink-0 -ml-1 p-2 rounded-lg text-zinc-300 hover:bg-zinc-800"
                            >
                                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                                </svg>
                            </button>
                            <img src="/imgs/logo.png" alt="Urban Box" className="h-7 w-7 object-contain" />
                            <h1 className="text-lg font-bold text-white truncate">URBAN BOX</h1>
                        </div>
                        <div className="flex items-center gap-2 md:gap-4 shrink-0">
                            {/* N-2/B4: campana del alumno, del ADMIN y del COACH.
                                Al alumno le entran los avisos de sus planes/pedidos;
                                al admin, los del box (p. ej. pedidos nuevos del Bazar);
                                al coach, las clases que le asignan/reasignan/liberan
                                desde Supervisión (B3) y que lo llevan a su grilla. */}
                            {(rol === 'alumno' || rol === 'administrador' || rol === 'admin' || rol === 'coach')
                                && <CampanaNotificaciones />}
                            {/* Fecha: larga en >=md; corta en <md (no desborda). */}
                            <span className="hidden md:inline text-sm text-zinc-400">
                                {new Date().toLocaleDateString('es-CL', {
                                    weekday: 'long',
                                    year: 'numeric',
                                    month: 'long',
                                    day: 'numeric',
                                })}
                            </span>
                            <span className="md:hidden text-sm text-zinc-400">
                                {new Date().toLocaleDateString('es-CL', {
                                    weekday: 'short',
                                    day: 'numeric',
                                    month: 'short',
                                })}
                            </span>
                            {sidebarOpen && (
                                <div className="text-right hidden md:block">
                                    <p className="text-sm font-medium text-zinc-100">👋 ¡Hola, {usuario || 'Atleta'}!</p>
                                </div>
                            )}
                        </div>
                    </div>
                </header>

                {/* Page Content */}
                <main className="flex-1 overflow-auto p-4 md:p-6 bg-zinc-950">
                    {/* Fondo decorativo sutil — solo en dashboards (marca de agua) */}
                    {location.pathname.endsWith('/dashboard') && (
                        <>
                            {rol === 'administrador' && (
                                <img src="/imgs/silueta-gym-3.png" alt=""
                                    className="hidden md:block pointer-events-none fixed -right-12 top-24 w-80 opacity-10 invert z-0 select-none" />
                            )}
                            {rol === 'coach' && (
                                <img src="/imgs/silueta-gym-4.png" alt=""
                                    className="hidden md:block pointer-events-none fixed -left-10 bottom-8 w-80 opacity-10 invert z-0 select-none" />
                            )}
                            {rol === 'alumno' && (
                                <img src="/imgs/silueta-gym-5.png" alt=""
                                    className="hidden md:block pointer-events-none fixed -right-10 bottom-8 w-80 opacity-10 invert z-0 select-none" />
                            )}
                        </>
                    )}
                    <div className="relative z-10">{children}</div>
                </main>
            </div>
        </div>
    );
};

export default Layout;