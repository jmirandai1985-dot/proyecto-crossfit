import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAvisosMarketingVigentes } from '../hooks/queries';
import IconoTipoAviso from './IconoTipoAviso';
import { urlArchivo } from '../utils/imagen';
// Productos del carrusel: la foto también cae al ícono si la URL no carga.
import ImagenProducto from './ImagenProducto';
import {
    agruparParaCarrusel, etiquetaTipo, formatearFechaEvento, fotoDeTarjeta,
    MAX_MINIATURAS, PIE_PRODUCTO, precioDeTarjeta, resumenVigencia,
    textoDeTarjeta, tieneFlyer, tipoDe, tituloDeGrupo, tituloDeTarjeta,
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

// La etiqueta del tipo, con el color del mockup (el de "Aviso del box" es ámbar
// con texto oscuro, por ejemplo).
const Etiqueta = ({ tipo }) => (
    <span className="cm-tag" style={{ background: tipo.tagFondo, color: tipo.tagTexto }}>
        <IconoTipoAviso tipo={tipo.id} />
        {etiquetaTipo(tipo.id)}
    </span>
);

// Tarjeta de uno de los CUATRO avisos que escribe el admin.
const TarjetaAviso = ({ aviso, onVerFlyer }) => {
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
const TarjetaProducto = ({ aviso }) => {
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
        </article>
    );
};

// Tarjeta de VARIOS productos nuevos: la que el mockup rotula "Llegaron poleras
// y polerones" — miniaturas y un "+N" cuando no caben todas.
const TarjetaProductos = ({ tarjeta, onVerBazar }) => {
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
                    <div className="cm-mini" key={aviso.id}>
                        <ImagenProducto url={fotoDeTarjeta(aviso)}
                            alt={tituloDeTarjeta(aviso)} respaldo={<IconoFoto />} />
                    </div>
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

/**
 * Carrusel "Novedades del box" del Inicio del alumno (<768px).
 *
 * Los avisos los entrega el backend YA vigentes y ordenados (fijados primero y
 * después el más nuevo): acá sólo se agrupan y se dibujan con las plantillas del
 * mockup. Sin avisos vigentes la sección completa NO se dibuja (nunca un carrusel
 * vacío), que es la regla que el mockup pide en su nota final.
 */
const CarruselMarketing = () => {
    const navigate = useNavigate();
    const { data } = useAvisosMarketingVigentes();
    const tarjetas = useMemo(() => agruparParaCarrusel(data), [data]);
    const [flyer, setFlyer] = useState(null);
    const [activo, setActivo] = useState(0);
    const pistaRef = useRef(null);

    // Escape cierra el flyer (el overlay del mockup se cierra tocando fuera).
    useEffect(() => {
        if (!flyer) return undefined;
        const alTeclear = (evento) => {
            if (evento.key === 'Escape') setFlyer(null);
        };
        window.addEventListener('keydown', alTeclear);
        return () => window.removeEventListener('keydown', alTeclear);
    }, [flyer]);

    if (!tarjetas.length) return null;

    const alDesplazar = () => {
        const pista = pistaRef.current;
        if (!pista) return;
        // El ancho REAL de una tarjeta (86% del contenedor) + el gap de 10px de la
        // pista: así el punto activo no depende de un porcentaje escrito a mano.
        const ancho = pista.children[0]?.offsetWidth || 1;
        const indice = Math.round(pista.scrollLeft / (ancho + 10));
        setActivo(Math.max(0, Math.min(indice, tarjetas.length - 1)));
    };

    const irA = (indice) => {
        const tarjeta = pistaRef.current?.children?.[indice];
        if (tarjeta?.scrollIntoView) {
            tarjeta.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' });
        }
        setActivo(indice);
    };

    return (
        <section className="cm-carrusel" aria-label="Novedades del box">
            <div className="cm-rotulo">Novedades del box</div>

            <div className="cm-pista" ref={pistaRef} onScroll={alDesplazar}>
                {tarjetas.map((tarjeta) => {
                    if (tarjeta.clase === 'aviso') {
                        return <TarjetaAviso key={`aviso-${tarjeta.aviso.id}`}
                                             aviso={tarjeta.aviso} onVerFlyer={setFlyer} />;
                    }
                    if (tarjeta.clase === 'producto') {
                        return <TarjetaProducto key={`producto-${tarjeta.aviso.id}`}
                                                aviso={tarjeta.aviso} />;
                    }
                    return <TarjetaProductos key="productos"
                                             tarjeta={tarjeta}
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
