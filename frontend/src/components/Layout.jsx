import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

// ─── Iconos SVG inline ───────────────────────────────────────────────────
const icons = {
    home: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
        </svg>
    ),
    calendar: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
    ),
    dumbbell: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
    ),
    settings: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
    ),
    logout: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
        </svg>
    ),
};

const Layout = ({ children }) => {
    const { usuario, rol, logout } = useAuth();
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const location = useLocation();

    const getMenuItems = () => {
        if (rol === 'alumno') {
            return [
                { label: 'Inicio', path: '/alumno/dashboard', icon: icons.home },
                { label: 'Mis Reservas', path: '/alumno/mis-reservas', icon: icons.calendar },
                { label: 'Pizarra de RMs', path: '/alumno/rms', icon: icons.dumbbell },
                { label: 'Ajustes', path: '/alumno/ajustes', icon: icons.settings },
            ];
        } else if (rol === 'coach') {
            return [
                { label: 'Dashboard', path: '/coach/dashboard', icon: icons.home },
                { label: 'Pizarra', path: '/coach/pizarra', icon: icons.dumbbell },
            ];
        } else if (rol === 'administrador' || rol === 'admin') {
            return [
                { label: 'Dashboard', path: '/admin/dashboard', icon: icons.home },
                { label: 'Alumnos', path: '/admin/alumnos', icon: icons.calendar },
                { label: 'Coaches', path: '/admin/coaches', icon: icons.settings },
                { label: 'Clases', path: '/admin/clases', icon: icons.calendar },
                { label: 'Bazar', path: '/admin/bazar', icon: icons.settings },
                { label: 'Reportes', path: '/admin/reportes', icon: icons.dumbbell },
            ];
        }
        return [];
    };

    const menuItems = getMenuItems();
    const isActive = (path) => location.pathname === path;

    return (
        <div className="flex h-screen bg-gray-50">
            {/* Sidebar */}
            <div
                className={`${sidebarOpen ? 'w-64' : 'w-20'
                    } bg-white border-r border-gray-200 transition-all duration-300 flex flex-col shadow-sm`}
            >
                {/* Logo */}
                <div className="p-5 border-b border-gray-100">
                    <div className="flex items-center gap-3">
                        <span className="text-2xl">🏋️</span>
                        {sidebarOpen && (
                            <div>
                                <h2 className="font-bold text-gray-800 text-sm leading-tight">URBAN BOX</h2>
                                <p className="text-[10px] text-gray-400">CrossFit Maipú</p>
                            </div>
                        )}
                    </div>
                </div>

                {/* Menu Items */}
                <nav className="flex-1 p-3 space-y-1">
                    {menuItems.map((item) => (
                        <Link
                            key={item.label}
                            to={item.path}
                            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all text-sm ${isActive(item.path)
                                    ? 'bg-emerald-50 text-emerald-700 font-semibold'
                                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-800'
                                }`}
                        >
                            <span className={`${isActive(item.path) ? 'text-emerald-600' : 'text-gray-400'}`}>
                                {item.icon}
                            </span>
                            {sidebarOpen && <span>{item.label}</span>}
                        </Link>
                    ))}
                </nav>

                {/* User & Logout */}
                <div className="p-4 border-t border-gray-100 space-y-3">
                    {sidebarOpen && (
                        <div className="px-2">
                            <p className="text-sm font-medium text-gray-800 truncate">{usuario || 'Usuario'}</p>
                            <p className="text-xs text-gray-400 capitalize">{rol}</p>
                        </div>
                    )}
                    <button
                        onClick={logout}
                        className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                    >
                        <span className="text-red-400">{icons.logout}</span>
                        {sidebarOpen && <span>Cerrar Sesión</span>}
                    </button>
                    <button
                        onClick={() => setSidebarOpen(!sidebarOpen)}
                        className="w-full flex items-center justify-center py-2 text-gray-400 hover:bg-gray-100 rounded-lg transition-colors text-xs"
                    >
                        {sidebarOpen ? '◀ Colapsar' : '▶'}
                    </button>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 flex flex-col overflow-hidden">
                {/* Header */}
                <header className="bg-white border-b border-gray-200">
                    <div className="flex items-center justify-between px-6 py-3">
                        <div className="flex items-center gap-2">
                            <span className="text-lg">🏋️</span>
                            <h1 className="text-lg font-bold text-gray-800">URBAN BOX</h1>
                        </div>
                        <div className="flex items-center gap-4">
                            <span className="text-sm text-gray-500">
                                {new Date().toLocaleDateString('es-CL', {
                                    weekday: 'long',
                                    year: 'numeric',
                                    month: 'long',
                                    day: 'numeric',
                                })}
                            </span>
                            {sidebarOpen && (
                                <div className="text-right hidden md:block">
                                    <p className="text-sm font-medium text-gray-800">👋 ¡Hola, {usuario || 'Atleta'}!</p>
                                </div>
                            )}
                        </div>
                    </div>
                </header>

                {/* Page Content */}
                <main className="flex-1 overflow-auto p-6 bg-gray-50">{children}</main>
            </div>
        </div>
    );
};

export default Layout;