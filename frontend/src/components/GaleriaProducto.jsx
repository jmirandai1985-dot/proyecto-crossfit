import React, { useEffect, useMemo, useRef, useState } from 'react';
import ImagenProducto from './ImagenProducto';

/**
 * Galería de fotos de un producto del Bazar (3 a 5 fotos, migración 055).
 *
 * - Muestra la portada grande + miniaturas (una por foto).
 * - Al tocar una foto se abre un visor a pantalla completa.
 * - En el visor: flechas, teclado (← → Esc) y swipe en móvil.
 *
 * `imagenes` es la galería que devuelve el backend (`[{ url, orden }]`). Si el
 * producto es anterior a la migración y sólo tiene `imagen_url`, se usa esa como
 * única foto (`urlPrincipal`).
 */
const normalizarFotos = (imagenes, urlPrincipal) => {
    const lista = (Array.isArray(imagenes) ? imagenes : [])
        .map((foto) => (typeof foto === 'string' ? { url: foto } : foto))
        .filter((foto) => foto && foto.url)
        .slice()
        // El backend ya las manda ordenadas; se reordena por si llega un objeto
        // de caché viejo o una lista construida a mano.
        .sort((a, b) => ((a.orden ?? 0) - (b.orden ?? 0)) || ((a.id ?? 0) - (b.id ?? 0)));
    if (lista.length) return lista;
    return urlPrincipal ? [{ url: urlPrincipal }] : [];
};

const GaleriaProducto = ({ imagenes, urlPrincipal, nombre = 'Producto', className = '' }) => {
    const fotos = useMemo(
        () => normalizarFotos(imagenes, urlPrincipal),
        [imagenes, urlPrincipal],
    );
    const [indice, setIndice] = useState(null);
    const touchX = useRef(null);
    const abierta = indice !== null;

    // Si el producto cambia (o se recarga la galería), el visor se cierra.
    const claveFotos = fotos.map((foto) => foto.url).join('|');
    useEffect(() => {
        setIndice(null);
    }, [claveFotos]);

    // Teclado + bloqueo del scroll del fondo mientras el visor está abierto.
    useEffect(() => {
        if (!abierta) return undefined;
        const onKeyDown = (e) => {
            if (e.key === 'Escape') setIndice(null);
            if (e.key === 'ArrowLeft') {
                setIndice((actual) => (actual === null ? actual : Math.max(0, actual - 1)));
            }
            if (e.key === 'ArrowRight') {
                setIndice((actual) => (
                    actual === null ? actual : Math.min(fotos.length - 1, actual + 1)
                ));
            }
        };
        window.addEventListener('keydown', onKeyDown);
        const overflowPrevio = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            window.removeEventListener('keydown', onKeyDown);
            document.body.style.overflow = overflowPrevio;
        };
    }, [abierta, fotos.length]);

    if (!fotos.length) return null;

    // Índice seguro: si la lista cambió mientras el visor estaba abierto.
    const actual = indice === null ? 0 : Math.min(Math.max(indice, 0), fotos.length - 1);

    const manejarTouchStart = (e) => {
        touchX.current = e.touches[0]?.clientX ?? null;
    };

    const manejarTouchEnd = (e) => {
        if (touchX.current === null) return;
        const fin = e.changedTouches[0]?.clientX ?? touchX.current;
        const desplazamiento = fin - touchX.current;
        touchX.current = null;
        if (Math.abs(desplazamiento) < 50) return;
        setIndice((posicion) => {
            if (posicion === null) return posicion;
            return desplazamiento > 0
                ? Math.max(0, posicion - 1)
                : Math.min(fotos.length - 1, posicion + 1);
        });
    };

    return (
        <>
            <div className={`space-y-2.5 ${className}`}>
                <button
                    type="button"
                    onClick={() => setIndice(0)}
                    className="relative block w-full overflow-hidden rounded-xl bg-gray-100 group"
                    aria-label={`Ampliar foto de ${nombre}`}
                >
                    <ImagenProducto
                        url={fotos[0].url}
                        alt={nombre}
                        className="w-full h-64 object-cover transition-transform duration-300 group-hover:scale-[1.02]"
                        respaldo={<span className="flex h-64 items-center justify-center text-5xl">🛍️</span>}
                    />
                    <span className="absolute bottom-2 right-2 rounded-full bg-black/65 px-2.5 py-1 text-xs font-semibold text-white">
                        🔍 {fotos.length} {fotos.length === 1 ? 'foto' : 'fotos'}
                    </span>
                </button>

                {fotos.length > 1 && (
                    <div className="grid grid-cols-5 gap-2">
                        {fotos.map((foto, posicion) => (
                            <button
                                key={`${foto.url}-${posicion}`}
                                type="button"
                                onClick={() => setIndice(posicion)}
                                aria-label={`Ver foto ${posicion + 1} de ${nombre}`}
                                aria-current={posicion === 0 ? 'true' : undefined}
                                className={`relative overflow-hidden rounded-lg border-2 transition-colors ${
                                    posicion === 0
                                        ? 'border-emerald-500'
                                        : 'border-transparent hover:border-emerald-300'
                                }`}
                            >
                                <ImagenProducto
                                    url={foto.url}
                                    alt={`${nombre} — foto ${posicion + 1}`}
                                    className="h-16 w-full object-cover"
                                    respaldo={<span className="flex h-16 items-center justify-center text-xl">🛍️</span>}
                                />
                                {posicion === 0 && (
                                    <span className="absolute left-1 top-1 rounded bg-emerald-600 px-1 py-0.5 text-[9px] font-bold uppercase text-white">
                                        Portada
                                    </span>
                                )}
                            </button>
                        ))}
                    </div>
                )}
            </div>

            {abierta && (
                <div
                    className="fixed inset-0 z-[100] flex flex-col bg-black/95"
                    role="dialog"
                    aria-modal="true"
                    aria-label={`Fotos de ${nombre}`}
                    onClick={() => setIndice(null)}
                >
                    <div
                        className="flex items-center justify-between gap-3 px-4 py-3 text-white"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <p className="truncate text-sm font-semibold">{nombre}</p>
                        <div className="flex items-center gap-3">
                            <span className="text-xs text-zinc-300">
                                {actual + 1} / {fotos.length}
                            </span>
                            <button
                                type="button"
                                onClick={() => setIndice(null)}
                                className="flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-lg hover:bg-white/20"
                                aria-label="Cerrar galería"
                            >
                                ✕
                            </button>
                        </div>
                    </div>

                    <div
                        className="relative flex min-h-0 flex-1 items-center justify-center px-12 pb-3"
                        onClick={(e) => e.stopPropagation()}
                        onTouchStart={manejarTouchStart}
                        onTouchEnd={manejarTouchEnd}
                    >
                        {actual > 0 && (
                            <button
                                type="button"
                                onClick={() => setIndice(actual - 1)}
                                className="absolute left-2 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-3xl text-white hover:bg-white/20"
                                aria-label="Foto anterior"
                            >
                                ‹
                            </button>
                        )}

                        <ImagenProducto
                            url={fotos[actual].url}
                            alt={`${nombre} — foto ${actual + 1}`}
                            className="max-h-full max-w-full select-none rounded-lg object-contain"
                            respaldo={<span className="text-6xl">🛍️</span>}
                        />

                        {actual < fotos.length - 1 && (
                            <button
                                type="button"
                                onClick={() => setIndice(actual + 1)}
                                className="absolute right-2 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-3xl text-white hover:bg-white/20"
                                aria-label="Foto siguiente"
                            >
                                ›
                            </button>
                        )}
                    </div>

                    {fotos.length > 1 && (
                        <div
                            className="flex justify-center gap-2 overflow-x-auto px-4 pb-5"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {fotos.map((foto, posicion) => (
                                <button
                                    key={`visor-${foto.url}-${posicion}`}
                                    type="button"
                                    onClick={() => setIndice(posicion)}
                                    aria-label={`Ir a la foto ${posicion + 1}`}
                                    className={`relative h-14 w-14 shrink-0 overflow-hidden rounded-lg border-2 transition-all ${
                                        posicion === actual
                                            ? 'border-white'
                                            : 'border-transparent opacity-50 hover:opacity-90'
                                    }`}
                                >
                                    <ImagenProducto
                                        url={foto.url}
                                        alt=""
                                        className="h-full w-full object-cover"
                                        respaldo={<span className="flex h-full items-center justify-center text-lg">🛍️</span>}
                                    />
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </>
    );
};

export default GaleriaProducto;
