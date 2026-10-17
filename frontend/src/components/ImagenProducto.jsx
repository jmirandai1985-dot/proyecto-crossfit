import React, { useEffect, useState } from 'react';
import { urlArchivo } from '../utils/imagen';

/**
 * Imagen de un producto del Bazar con RESPALDO.
 *
 * POR QUÉ EXISTE: un producto puede tener una `imagen_url` que el navegador no logre
 * cargar (URL mal formada —pasó en PROD— o archivo que ya no está). Sin respaldo se ve
 * el ícono de imagen rota. Este componente esconde el <img> y muestra `respaldo` (el
 * emoji/ícono que la pantalla ya usaba cuando el producto no tenía foto).
 *
 * Se usa en el inventario del admin, el catálogo del alumno y el Inicio móvil: las tres
 * pantallas tienen que reaccionar igual. La URL se sigue normalizando en `urlArchivo`.
 */
const ImagenProducto = ({ url, alt, className, respaldo = null }) => {
    const [fallo, setFallo] = useState(false);
    const src = urlArchivo(url);

    // Si el producto cambia de foto (edición), se vuelve a intentar.
    useEffect(() => {
        setFallo(false);
    }, [url]);

    if (!src || fallo) return respaldo;

    return (
        <img
            src={src}
            alt={alt}
            className={className}
            loading="lazy"
            onError={() => setFallo(true)}
        />
    );
};

export default ImagenProducto;
