import React from 'react';
import { esFalloDeChunk, recargarPorChunk } from '../utils/recargaAutomatica.js';

/**
 * Último paracaídas de la app: si CUALQUIER render revienta, el usuario ve un aviso
 * con botón "Recargar" en lugar de una pantalla en blanco.
 *
 * POR QUÉ EXISTE: un deploy cualquiera deja a los celulares con la SPA vieja en
 * memoria; al tocar el menú piden un chunk con el nombre anterior, nginx responde 404
 * (`try_files $uri =404`) y el import() dinámico de la ruta `lazy` rechaza. Sin
 * boundary que lo atrape, React desmonta el árbol y el usuario no ve NADA: ni spinner
 * ni error, sólo pantalla blanca. Con esto ve qué pasó y puede recargar.
 *
 * Es una CLASE porque React sólo entrega el paracaídas por `getDerivedStateFromError` /
 * `componentDidCatch` (no hay equivalente con hooks).
 *
 * Si el error es de chunk, además se dispara UNA recarga automática (ver
 * utils/recargaAutomatica.js): el `index.html` va con `no-cache`, así que la recarga
 * trae los nombres nuevos y el usuario no tiene que hacer nada.
 */
class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { error: null };
    }

    static getDerivedStateFromError(error) {
        return { error };
    }

    componentDidCatch(error, info) {
        // Queda en la consola del celular: es el dato que se pide para diagnosticar.
        console.error('ErrorBoundary: la app falló al renderizar', error, info && info.componentStack);
        if (esFalloDeChunk(error)) recargarPorChunk();
    }

    render() {
        const { error } = this.state;
        if (!error) return this.props.children;

        const deChunk = esFalloDeChunk(error);
        const detalle = String((error && error.message) || error);

        return (
            <div
                data-testid="error-boundary"
                role="alert"
                className="min-h-screen flex items-center justify-center bg-gray-50 p-6"
            >
                <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-6 text-center shadow-sm">
                    <div className="text-4xl">{deChunk ? '🔄' : '⚠️'}</div>
                    <h1 className="mt-3 text-lg font-bold text-gray-800">
                        {deChunk ? 'Hay una versión nueva de la app' : 'La app no pudo abrir esta pantalla'}
                    </h1>
                    <p className="mt-2 text-sm text-gray-600">
                        {deChunk
                            ? 'Tu sesión quedó con archivos de la versión anterior. Recarga y sigues donde estabas.'
                            : 'Algo salió mal al dibujar la pantalla. Recarga para volver a intentarlo.'}
                    </p>
                    <button
                        type="button"
                        data-testid="error-boundary-recargar"
                        onClick={() => window.location.reload()}
                        className="mt-4 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-emerald-700"
                    >
                        Recargar
                    </button>
                    <details className="mt-4 text-left">
                        <summary className="cursor-pointer text-xs text-gray-400">Detalle técnico</summary>
                        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-2 text-[11px] text-gray-500">
                            {detalle}
                        </pre>
                    </details>
                </div>
            </div>
        );
    }
}

export default ErrorBoundary;
