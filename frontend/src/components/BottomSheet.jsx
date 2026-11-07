import React, { useCallback, useEffect, useRef } from 'react';
import { X } from 'lucide-react';

/**
 * Bottom sheet reutilizable: un panel que sube desde abajo sobre un overlay
 * oscuro. Se usa para la vista expandida del gráfico "Progreso de RM".
 *
 * Cierra de cuatro formas (igual que un sheet nativo):
 *   1. tocando la X del encabezado;
 *   2. tocando el fondo oscuro;
 *   3. presionando Escape;
 *   4. con el botón atrás del navegador (apila una entrada de historial al
 *      abrir y la quita al cerrar, para no ensuciar el historial).
 *
 * El manejo del historial está pensado para convivir con el doble montaje de
 * StrictMode en desarrollo: la entrada se apila UNA sola vez y el listener de
 * `popstate` se vuelve a registrar en cada ciclo sin desapilar nada.
 *
 * Props:
 *   - isOpen:   si el sheet está visible.
 *   - onClose:  callback de cierre (el padre dueño del estado).
 *   - title:    título del encabezado (obligatorio).
 *   - subtitle: aclaración corta bajo el título (opcional).
 *   - children: contenido (el ancho/alto del gráfico lo define quien lo usa).
 */
const BottomSheet = ({ isOpen, onClose, title, subtitle, children }) => {
    const onCloseRef = useRef(onClose);
    useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

    // true mientras haya una entrada de historial apilada por ESTE sheet.
    const pushedRef = useRef(false);

    // Cierre programático (X, fondo, Escape): quita la entrada de historial
    // apilada y cierra. Si la entrada ya la consumió el botón atrás, sólo cierra.
    const cerrar = useCallback(() => {
        if (pushedRef.current) {
            pushedRef.current = false;
            // Dispara `popstate` → el listener de abajo llama a onClose().
            window.history.back();
        } else {
            onCloseRef.current();
        }
    }, []);

    // Cierre con Escape.
    useEffect(() => {
        if (!isOpen) return undefined;
        const onKey = (e) => { if (e.key === 'Escape') cerrar(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [isOpen, cerrar]);

    // Botón atrás del navegador: apila una entrada UNA vez y escucha `popstate`.
    useEffect(() => {
        if (!isOpen) {
            pushedRef.current = false;
            return undefined;
        }
        if (!pushedRef.current) {
            window.history.pushState({ bottomSheet: true }, '');
            pushedRef.current = true;
        }
        const onPop = () => {
            pushedRef.current = false;
            onCloseRef.current();
        };
        window.addEventListener('popstate', onPop);
        return () => {
            window.removeEventListener('popstate', onPop);
        };
    }, [isOpen]);

    if (!isOpen) return null;

    return (
        <div
            className="fixed inset-0 z-50 flex items-end justify-center bg-black/60"
            onClick={cerrar}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label={title}
                className="w-full max-w-3xl max-h-[90dvh] overflow-y-auto rounded-t-2xl border border-zinc-700 bg-[#12161f] shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Encabezado */}
                <div className="sticky top-0 flex items-start justify-between gap-4 border-b border-zinc-700 bg-[#12161f] px-5 py-4">
                    <div className="min-w-0">
                        <h2 className="text-lg font-bold text-zinc-100">{title}</h2>
                        {subtitle && <p className="mt-0.5 text-xs text-zinc-400 capitalize">{subtitle}</p>}
                    </div>
                    <button
                        type="button"
                        onClick={cerrar}
                        aria-label="Cerrar"
                        className="shrink-0 rounded-lg p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Contenido */}
                <div className="p-5">{children}</div>
            </div>
        </div>
    );
};

export default BottomSheet;
