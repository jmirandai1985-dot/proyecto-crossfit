import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAvisosMarketingVigentes, useTarjetaReferidos } from '../hooks/queries';
import IconoTipoAviso from './IconoTipoAviso';
import { urlArchivo } from '../utils/imagen';
// Productos del carrusel: la foto también cae al ícono si la URL no carga.
import ImagenProducto from './ImagenProducto';
import {
    agruparParaCarrusel, esPromocionVinculada, etiquetaTipo,
    formatearFechaEvento, fotoDeTarjeta, MAX_MINIATURAS, PIE_PRODUCTO, precioDeTarjeta,
    resumenVigencia, tarjetaReferidosDe, textoDeTarjeta, TIPO_REFERIDOS, tieneFlyer,
    tipoDe, tituloDeGrupo, tituloDeTarjeta,
} from '../utils/avisosMarketing';
import './carruselMarketing.css';

// Los 4 remaches de las esquinas de la placa (el mockup los dibuja con dos
// pseudo-elementos y dos <i>).
const Remaches = () => (
    <>
        <i className="cm-remache r3" />
        <i className="cm-remache r4" />
    </>
);

// Íconos del propio carrusel (los del mockup): la foto y la flecha de "Ver todo".
const IconoFoto = () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <path d="m21 15-5-5L5 21" />
    </svg>
);

const IconoFlecha = () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
        <path d="M9 18l6-6-6-6" />
    </svg>
);

// El regalo de la tarjeta "Invita y Gana" (decorativa: el texto ya lo dice).
const IconoRegalo = () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <path d="M20 12v9H4v-9" />
        <rect x="2" y="7" width="20" height="5" rx="1" />
        <path d="M12 21V7" />
        <path d="M12 7H7.5a2.5 2.5 0 1 1 0-5C11 2 12 7 12 7Z" />
        <path d="M12 7h4.5a2.5 2.5 0 1 0 0-5C13 2 12 7 12 7Z" />
    </svg>
);

// La etiqueta del tipo, con el color del mockup (el de "Aviso del box" es ámbar
// con texto oscuro, por ejemplo).
const Etiqueta = ({ tipo }) => (
    <span className="cm-tag" style={{ background: tipo.tagFondo, color: tipo.tagTexto }}>
        <IconoTipoAviso tipo={tipo.id} />
        {etiquetaTipo(tipo.id)}
    </span>
);

// Tarjeta de uno de los CUATRO avisos que escribe el admin. La de una promoción
// publicada desde Referidos (`promocion_id`) suma un CTA a `/alumno/invita-y-gana`:
// es la tarjeta que ANUNCIA el premio, y el alumno necesita su código para ganarlo.
const TarjetaAviso = ({ aviso, onVerFlyer, onVerReferidos }) => {
    const tipo = tipoDe(aviso.tipo);
    const evento = aviso.tipo === 'evento' ? formatearFechaEvento(aviso.fecha_evento) : null;
    const pie = resumenVigencia(aviso);
    const texto = textoDeTarjeta(aviso);

    return (
        <article
            className="cm-tarjeta"
            style={{ background: tipo.fondo }}
            data-tipo={aviso.tipo}
        >
            {/* La foto del flyer, de fondo y apagada: da contexto sin tapar el
                texto (el velo de `.cm-fondo::after` garantiza el contraste). */}
            {aviso.imagen_url && (
                <span className="cm-fondo" aria-hidden="true">
                    <img src={urlArchivo(aviso.imagen_url)} alt="" loading="lazy" />
                </span>
            )}
            <Remaches />
            <Etiqueta tipo={tipo} />
            {evento && (
                <div className="cm-fecha-grande" style={{ color: tipo.detalle }}>
                    <b>{evento.dia}</b>
                    <span>{evento.mes}</span>
                </div>
            )}
            <div className="cm-cuerpo">
                {aviso.nombre_aliado && (
                    <span className="cm-marca" style={{ color: tipo.detalle }}>
                        {aviso.nombre_aliado}
                    </span>
                )}
                <h3 className="cm-titulo" style={{ color: tipo.titulo }}>
                    {tituloDeTarjeta(aviso)}
                </h3>
                {texto && <p className="cm-texto">{texto}</p>}
                {esPromocionVinculada(aviso) && onVerReferidos && (
                    <button
                        type="button"
                        className="cm-ver"
                        onClick={onVerReferidos}
                        data-testid="carrusel-promo-cta"
                    >
                        <IconoRegalo />
                        Participar con mi código
                    </button>
                )}
                {tieneFlyer(aviso) && (
                    <button type="button" className="cm-ver" onClick={() => onVerFlyer(aviso)}>
                        <IconoFoto />
                        Toca para ver el flyer
                    </button>
                )}
            </div>
            {pie && <span className="cm-fecha">{pie}</span>}
        </article>
    );
};

// Tarjeta de UN producto nuevo: foto, nombre y precio REALES (salen del producto
// en el Bazar, así que si el admin le cambia el precio, acá se ve al instante).
const TarjetaProducto = ({ aviso, onAbrir }) => {
    const tipo = tipoDe('producto_bazar');
    const foto = fotoDeTarjeta(aviso);
    const precio = precioDeTarjeta(aviso);

    return (
        <article
            className="cm-tarjeta cm-producto"
            style={{ background: tipo.fondo }}
            data-tipo={aviso.tipo}
        >
            <Remaches />
            <Etiqueta tipo={tipo} />
            <button
                type="button"
                className="cm-abrir"
                onClick={() => onAbrir(aviso.producto_id)}
                aria-label={`Ver ${tituloDeTarjeta(aviso)} en el Bazar`}
            >
                <div className="cm-foto">
                    <ImagenProducto url={foto} alt={tituloDeTarjeta(aviso)}
                        respaldo={<IconoFoto />} />
                </div>
                <div className="cm-info">
                    <h3 className="cm-titulo" style={{ color: tipo.titulo }}>
                        {tituloDeTarjeta(aviso)}
                    </h3>
                    {precio && (
                        <div className="cm-precio" style={{ color: tipo.detalle }}>{precio}</div>
                    )}
                    <p className="cm-texto">{PIE_PRODUCTO}</p>
                </div>
            </button>
        </article>
    );
};

// Tarjeta de VARIOS productos nuevos: la que el mockup rotula "Llegaron poleras
// y polerones" — miniaturas y un "+N" cuando no caben todas.
const TarjetaProductos = ({ tarjeta, onVerBazar, onVerProducto }) => {
    const tipo = tipoDe('producto_bazar');
    const visibles = tarjeta.avisos.slice(0, MAX_MINIATURAS);

    return (
        <article
            className="cm-tarjeta"
            style={{ background: tipo.fondo }}
            data-tipo="producto_bazar"
        >
            <Remaches />
            <Etiqueta tipo={tipo} />
            <h3 className="cm-titulo" style={{ color: tipo.titulo }}>
                {tituloDeGrupo(tarjeta.avisos.length)}
            </h3>
            <div className="cm-minis">
                {visibles.map((aviso) => (
                    <button
                        type="button"
                        className="cm-mini"
                        key={aviso.id}
                        onClick={() => onVerProducto(aviso.producto_id)}
                        aria-label={`Ver ${tituloDeTarjeta(aviso)} en el Bazar`}
                    >
                        <ImagenProducto url={fotoDeTarjeta(aviso)}
                            alt={tituloDeTarjeta(aviso)} respaldo={<IconoFoto />} />
                    </button>
                ))}
                {tarjeta.extra > 0 && (
                    <div className="cm-mini cm-mas" style={{ color: tipo.detalle }}>
                        +{tarjeta.extra}
                    </div>
                )}
            </div>
            <button type="button" className="cm-vertodo" style={{ color: tipo.detalle }} onClick={onVerBazar}>
                Ver todo en el Bazar
                <IconoFlecha />
            </button>
        </article>
    );
};

// La tarjeta FIJA de "Invita y Gana": siempre la ÚLTIMA del carrusel y la única
// cuyo copy NO viene de la BD de avisos: lo edita el admin desde Marketing →
// Referidos (`GET/PUT /referidos/tarjeta`, migración 058) y llega acá como
// `copy` ya resuelto. Es un <button> de verdad —teclado incluido— que abre
// `/alumno/invita-y-gana`, donde está el código del alumno y el botón para
// compartir la invitación. La etiqueta ("Trae a un amigo"), el dorado y el
// destino son fijos: son el lenguaje visual del carrusel, no copy.
const TarjetaReferidos = ({ copy, onAbrir }) => {
    const tipo = TIPO_REFERIDOS;

    return (
        <button
            type="button"
            className="cm-tarjeta cm-referidos"
            style={{ background: tipo.fondo }}
            onClick={onAbrir}
            data-testid="carrusel-referidos"
        >
            <Remaches />
            <span className="cm-tag" style={{ background: tipo.tagFondo, color: tipo.tagTexto }}>
                <IconoRegalo />
                {tipo.tag}
            </span>
            <span className="cm-regalo" aria-hidden="true"><IconoRegalo /></span>
            <span className="cm-cuerpo">
                <span className="cm-titulo" style={{ color: tipo.titulo }}>
                    {copy.titulo}
                </span>
                <span className="cm-texto">{copy.texto}</span>
            </span>
            <span className="cm-chip" style={{ color: tipo.detalle }}>
                {copy.cta}
                <IconoFlecha />
            </span>
        </button>
    );
};

/**
 * Carrusel "Novedades del box" del Inicio del alumno (<768px).
 *
 * Los avisos los entrega el backend YA vigentes y ordenados (fijados primero y
 * después el más nuevo): acá sólo se agrupan y se dibujan con las plantillas del
 * mockup. Al final va la tarjeta de "Invita y Gana" (salvo que el admin la haya
 * ocultado), así que la sección ya no depende de que el admin publique algo. La
 * guarda de "sin tarjetas" queda como defensa: nunca un carrusel vacío.
 */
const CarruselMarketing = () => {
    const navigate = useNavigate();
    // Abre el flujo de compra del producto TOCADO (mismo deep link que las
    // tarjetas de la Tienda). Sin id, cae al catálogo para no romper el enlace.
    const irAProducto = (productoId) => {
        if (productoId == null) {
            navigate('/alumno/bazar');
            return;
        }
        navigate(`/alumno/bazar?producto=${productoId}`);
    };
    const { data } = useAvisosMarketingVigentes();
    // Copy y visibilidad de la tarjeta fija: los edita el admin desde
    // Marketing → Referidos (`GET /referidos/tarjeta`). Mientras carga NO se
    // pinta (evita mostrar una tarjeta que el admin ocultó); si la consulta
    // FALLA sí se pinta con el copy por defecto, porque un problema de red no
    // puede dejar al alumno sin el acceso a su código.
    const { data: tarjetaReferidos, isPending: cargandoTarjeta, isError: errorTarjeta } =
        useTarjetaReferidos();
    const copiaReferidos = useMemo(
        () => tarjetaReferidosDe(tarjetaReferidos), [tarjetaReferidos]);
    const mostrarReferidos = errorTarjeta || (!cargandoTarjeta && copiaReferidos.visible);
    // Destino de la tarjeta de referidos y del CTA de una promoción publicada
    // desde Referidos: es donde el alumno ve su código (una sola ruta para las dos).
    const irAReferidos = () => navigate('/alumno/invita-y-gana');
    // Tarjeta de "Invita y Gana" al final: es del alumno, no de la BD de avisos,
    // así que el carrusel se ve aunque no haya avisos vigentes.
    const tarjetas = useMemo(() => {
        const base = agruparParaCarrusel(data);
        return mostrarReferidos ? [...base, { clase: 'referidos' }] : base;
    }, [data, mostrarReferidos]);
    const [flyer, setFlyer] = useState(null);
    const [activo, setActivo] = useState(0);
    const pistaRef = useRef(null);
    // Rotación automática: se PAUSA al tocar/deslizar (10 s), al pasar el mouse por encima
    // y mientras hay un flyer abierto. Así el avance solo no pelea con el dedo del alumno.
    const [pausado, setPausado] = useState(false);
    const [hover, setHover] = useState(false);
    const reanudarRef = useRef(null);

    // Escape cierra el flyer (el overlay del mockup se cierra tocando fuera).
    useEffect(() => {
        if (!flyer) return undefined;
        const alTeclear = (evento) => {
            if (evento.key === 'Escape') setFlyer(null);
        };
        window.addEventListener('keydown', alTeclear);
        return () => window.removeEventListener('keydown', alTeclear);
    }, [flyer]);

    const alDesplazar = () => {
        const pista = pistaRef.current;
        if (!pista) return;
        // Con el snap CENTRADO la tarjeta activa es la que tiene su centro más
        // cerca del centro de la pista (no la que empieza más cerca del borde):
        // así el punto no depende de un ancho escrito a mano. Las cajas se miden
        // con `getBoundingClientRect` para no depender de quién sea el
        // `offsetParent` de la pista.
        const caja = pista.getBoundingClientRect();
        const medio = caja.width / 2;
        let indice = 0;
        let distancia = Infinity;
        Array.from(pista.children).forEach((tarjeta, posicion) => {
            const suya = tarjeta.getBoundingClientRect();
            const delta = Math.abs((suya.left - caja.left + suya.width / 2) - medio);
            if (delta < distancia) {
                distancia = delta;
                indice = posicion;
            }
        });
        setActivo(Math.max(0, Math.min(indice, tarjetas.length - 1)));
    };

    const irA = (indice) => {
        const pista = pistaRef.current;
        const tarjeta = pista?.children?.[indice];
        // `scrollTo` sobre la PISTA (no `scrollIntoView`): el salto automático no puede
        // arrastrar el scroll vertical de la página, solo mueve el carrusel.
        if (pista && tarjeta) {
            // La tarjeta queda CENTRADA: se asoma un trozo de la anterior y de la
            // siguiente, que es la pista visual de que se puede deslizar.
            const caja = pista.getBoundingClientRect();
            const suya = tarjeta.getBoundingClientRect();
            const destino = pista.scrollLeft + (suya.left - caja.left)
                - (caja.width - suya.width) / 2;
            pista.scrollTo({ left: Math.max(0, destino), behavior: 'smooth' });
        }
        setActivo(indice);
    };

    const pausarPorInteraccion = () => {
        setPausado(true);
        clearTimeout(reanudarRef.current);
        reanudarRef.current = setTimeout(() => setPausado(false), 10000);
    };

    useEffect(() => () => clearTimeout(reanudarRef.current), []);

    useEffect(() => {
        // Con una sola tarjeta no hay a dónde rotar. Tampoco con el flyer abierto, el dedo
        // sobre la pista o `prefers-reduced-motion` (accesibilidad).
        if (tarjetas.length <= 1 || flyer || pausado || hover) return undefined;
        if (typeof window === 'undefined') return undefined;
        if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return undefined;
        const intervalo = setInterval(() => {
            if (document.hidden) return;   // pestaña en segundo plano: no gastar ciclos
            irA((activo + 1) % tarjetas.length);
        }, 5500);
        return () => clearInterval(intervalo);
    }, [activo, tarjetas.length, flyer, pausado, hover]);

    if (!tarjetas.length) return null;

    return (
        <section className="cm-carrusel" aria-label="Novedades del box">
            <div className="cm-rotulo">Novedades del box</div>

            <div className="cm-pista" ref={pistaRef} onScroll={alDesplazar}
                onPointerDown={pausarPorInteraccion}
                onTouchStart={pausarPorInteraccion}
                onMouseEnter={() => setHover(true)}
                onMouseLeave={() => setHover(false)}>
                {tarjetas.map((tarjeta) => {
                    if (tarjeta.clase === 'referidos') {
                        return <TarjetaReferidos key="referidos" copy={copiaReferidos}
                                                 onAbrir={irAReferidos} />;
                    }
                    if (tarjeta.clase === 'aviso') {
                        return <TarjetaAviso key={`aviso-${tarjeta.aviso.id}`}
                                             aviso={tarjeta.aviso} onVerFlyer={setFlyer}
                                             onVerReferidos={irAReferidos} />;
                    }
                    if (tarjeta.clase === 'producto') {
                        return <TarjetaProducto key={`producto-${tarjeta.aviso.id}`}
                                                 aviso={tarjeta.aviso}
                                                 onAbrir={irAProducto} />;
                    }
                    return <TarjetaProductos key="productos"
                                             tarjeta={tarjeta}
                                             onVerProducto={irAProducto}
                                             onVerBazar={() => navigate('/alumno/bazar')} />;
                })}
            </div>

            {tarjetas.length > 1 && (
                <div className="cm-puntos">
                    {tarjetas.map((tarjeta, indice) => (
                        <button
                            key={`punto-${indice}`}
                            type="button"
                            className={`cm-punto${indice === activo ? ' on' : ''}`}
                            onClick={() => irA(indice)}
                            aria-label={`Ir al aviso ${indice + 1} de ${tarjetas.length}`}
                            aria-current={indice === activo}
                        />
                    ))}
                </div>
            )}

            {/* Flyer a pantalla completa: mismo patrón del comprobante del Bazar. */}
            {flyer && (
                <div className="cm-flyer" role="dialog" aria-modal="true"
                     onClick={() => setFlyer(null)}>
                    <button type="button" className="cm-flyer-cerrar" aria-label="Cerrar"
                            onClick={() => setFlyer(null)}>
                        ✕
                    </button>
                    <img src={urlArchivo(flyer.imagen_url)}
                         alt={`Flyer de ${tituloDeTarjeta(flyer)}`} />
                    <div className="cm-flyer-nota">Toca fuera para cerrar</div>
                </div>
            )}
        </section>
    );
};

export default CarruselMarketing;
