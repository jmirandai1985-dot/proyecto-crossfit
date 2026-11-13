import React, { useEffect, useState } from 'react';
import { ArrowRight, Download, Share, SquarePlus, X } from 'lucide-react';
import {
    descartarInstalacionApp, estadoInstalacionApp, iniciarInstalacionApp,
    pedirInstalacionApp, suscribirInstalacionApp,
} from '../services/instalacionApp';
import { puedeMostrarBannerIos, puedeMostrarBoton } from '../utils/instalarApp';

/**
 * "Instalar app" en el panel del alumno.
 *
 * Android/Chrome: el navegador dispara `beforeinstallprompt` (lo captura el singleton
 * de `services/instalacionApp`) y acá se ofrece un botón que dispara ESE prompt guardado.
 * iOS/Safari: no existe el evento, así que se muestra un banner con el paso manual
 * "Compartir -> Agregar a pantalla de inicio".
 *
 * El componente se auto-oculta: si la app ya está instalada, si el navegador no ofrece
 * el prompt o si el alumno descartó el aviso. No bloquea ni cambia ninguna otra parte
 * del panel. Se monta SOLO para rol alumno (ver Layout).
 */
const InstalarApp = () => {
    const [estado, setEstado] = useState(estadoInstalacionApp());
    const [instalando, setInstalando] = useState(false);
    const [aviso, setAviso] = useState('');

    useEffect(() => {
        // Idempotente: main.jsx ya lo inició; acá se cubre el caso de un montaje
        // aislado (tests, hot reload) sin depender del orden de arranque.
        iniciarInstalacionApp();
        return suscribirInstalacionApp(setEstado);
    }, []);

    const mostrarBoton = puedeMostrarBoton({
        promptDisponible: Boolean(estado.prompt),
        instalada: estado.instalada,
        descartado: estado.descartado,
    });
    const mostrarBannerIos = puedeMostrarBannerIos({
        esIos: estado.esIos,
        instalada: estado.instalada,
        descartado: estado.descartado,
    });

    if (!mostrarBoton && !mostrarBannerIos) return null;

    const instalar = async () => {
        setAviso('');
        setInstalando(true);
        const resultado = await pedirInstalacionApp();
        setInstalando(false);
        if (resultado === 'accepted') {
            setAviso('¡Listo! Urban Training Box quedó instalada.');
        } else if (resultado === 'no-disponible') {
            setAviso('El navegador no tiene el instalador disponible todavía. Intenta desde el menú.');
        }
    };

    if (mostrarBoton) {
        return (
            <div
                data-testid="instalar-app"
                className="mb-4 flex flex-col gap-3 rounded-xl border border-sky-500/30 bg-sky-500/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
                <div className="flex items-start gap-3">
                    <Download className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" aria-hidden="true" />
                    <div>
                        <p className="text-sm font-bold text-sky-100">Instala Urban Training Box</p>
                        <p className="text-[12.5px] leading-snug text-sky-200/80">
                            Acceso directo desde tu pantalla de inicio, sin abrir el navegador.
                        </p>
                        {aviso && (
                            <p className="mt-1 text-[12px] font-semibold text-emerald-300">
                                {aviso}
                            </p>
                        )}
                    </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                    <button
                        type="button"
                        onClick={instalar}
                        disabled={instalando}
                        data-testid="btn-instalar-app"
                        className="rounded-lg bg-[#ff8c00] px-4 py-2 text-sm font-bold text-black transition hover:bg-[#ff9e2e] active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                        {instalando ? 'Abriendo...' : 'Instalar app'}
                    </button>
                    <button
                        type="button"
                        onClick={descartarInstalacionApp}
                        aria-label="Ahora no"
                        title="Ahora no"
                        className="rounded-lg p-2 text-sky-200/70 transition hover:bg-sky-500/10 hover:text-white"
                    >
                        <X className="h-4 w-4" aria-hidden="true" />
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div
            data-testid="banner-ios-instalar"
            className="mb-4 rounded-xl border border-sky-500/30 bg-sky-500/10 px-4 py-3"
        >
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                    <Share className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" aria-hidden="true" />
                    <div>
                        <p className="text-sm font-bold text-sky-100">Instala la app en tu iPhone o iPad</p>
                        <p className="mt-1 text-[12.5px] leading-relaxed text-sky-200/90">
                            Toca <strong>Compartir</strong> en Safari, elige{' '}
                            <strong>Agregar a pantalla de inicio</strong> y confirma. Queda como
                            una app, sin abrir el navegador.
                        </p>
                        <p className="mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11.5px] text-sky-200/70">
                            <span className="inline-flex items-center gap-1">
                                <Share className="h-3.5 w-3.5" aria-hidden="true" /> Compartir
                            </span>
                            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                            <span className="inline-flex items-center gap-1">
                                <SquarePlus className="h-3.5 w-3.5" aria-hidden="true" />
                                Agregar a pantalla de inicio
                            </span>
                        </p>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={descartarInstalacionApp}
                    aria-label="Cerrar"
                    title="Cerrar"
                    className="shrink-0 rounded-lg p-2 text-sky-200/70 transition hover:bg-sky-500/10 hover:text-white"
                >
                    <X className="h-4 w-4" aria-hidden="true" />
                </button>
            </div>
        </div>
    );
};

export default InstalarApp;
