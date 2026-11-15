import React, { useState, useEffect } from 'react';
import { useGuardarProducto } from '../hooks/queries';
import ImagenProducto from './ImagenProducto';

const MAX_FOTOS = 5;

// Lee el archivo como data URL para la vista previa local. La subida real la hace
// el hook al guardar; acá sólo se muestra lo que el admin eligió.
const leerFoto = (archivo) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve({
        key: `nueva-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        id: null,
        archivo,
        preview: typeof reader.result === 'string' ? reader.result : '',
    });
    reader.onerror = () => reject(new Error(`No se pudo leer ${archivo.name}`));
    reader.readAsDataURL(archivo);
});

const ModalProducto = ({ isOpen, onClose, onSuccess, productoEditar }) => {
    const [loading, setLoading] = useState(false);
    const [formData, setFormData] = useState({
        nombre: '',
        descripcion: '',
        precio: '',
        stock: '',
        stock_minimo: '',
        dias_anuncio: '0',
        descuento_pct: '',
        activo: true,
    });
    // Galería en edición: fotos guardadas ({ id, preview }) + fotos nuevas
    // ({ archivo, preview }). El orden del arreglo ES el orden de la galería y la
    // posición 0 es la portada (`imagen_url`).
    const [fotos, setFotos] = useState([]);
    const [errors, setErrors] = useState({});
    // ── Tallas/variantes (migración 083) ──────────────────────────────────
    // El switch nace APAGADO: los productos existentes siguen usando el stock
    // plano. Encendido, el stock se maneja por talla (lista compacta de filas
    // talla + stock) y viaja como `variantes_json` en el POST multipart o como
    // `variantes` en el PUT JSON. Se valida acá para dar feedback inmediato;
    // el backend lo vuelve a validar (índice único case-insensitive).
    const [tieneVariantes, setTieneVariantes] = useState(false);
    const [variantes, setVariantes] = useState([]);   // [{ talla, stock }]

    const esEdicion = !!productoEditar;
    // Bloque 3 (parte A): guardar invalida `['productos']`, el prefijo que comparten el
    // inventario del admin y el Bazar del alumno.
    const guardarProducto = useGuardarProducto();

    useEffect(() => {
        if (isOpen) {
            if (productoEditar) {
                // Pre-cargar datos del producto a editar
                setFormData({
                    nombre: productoEditar.nombre || '',
                    descripcion: productoEditar.descripcion || '',
                    precio: productoEditar.precio ? String(productoEditar.precio) : '',
                    stock: productoEditar.stock !== undefined ? String(productoEditar.stock) : '',
                    stock_minimo: (productoEditar.stock_minimo !== undefined && productoEditar.stock_minimo !== null)
                        ? String(productoEditar.stock_minimo) : '',
                    // Días de anuncio: se precargan para que el admin vea si el
                    // producto está anunciado (y por cuánto) al abrirlo.
                    dias_anuncio: String(productoEditar.dias_anuncio ?? 0),
                    // Descuento manual (migración 072). NULL = sin descuento.
                    descuento_pct: (productoEditar.descuento_pct !== undefined && productoEditar.descuento_pct !== null)
                        ? String(productoEditar.descuento_pct) : '',
                    activo: productoEditar.activo !== undefined ? productoEditar.activo : true,
                });
                // Tallas del producto (083). `productoEditar.stock` ya viene como
                // la SUMA de las tallas activas, así que sirve de arranque si el
                // admin apaga el switch y vuelve al stock plano.
                setTieneVariantes(Boolean(productoEditar.tiene_variantes));
                setVariantes((productoEditar.variantes || []).map((variante) => ({
                    talla: variante.talla || '',
                    stock: String(variante.stock ?? 0),
                })));
            } else {
                // Limpiar formulario para nuevo producto
                setFormData({
                    nombre: '',
                    descripcion: '',
                    precio: '',
                    stock: '',
                    stock_minimo: '',
                    dias_anuncio: '0',
                    descuento_pct: '',
                    activo: true,
                });
                setTieneVariantes(false);
                setVariantes([]);
            }
            setErrors({});

            // Galería inicial: primero `imagenes` (migración 055); si el producto
            // es viejo y sólo tiene `imagen_url`, esa URL funciona como única foto.
            const guardadas = productoEditar
                ? [...(productoEditar.imagenes || [])]
                    .filter((foto) => foto && foto.url)
                    .sort((a, b) => ((a.orden ?? 0) - (b.orden ?? 0))
                        || ((a.id ?? 0) - (b.id ?? 0)))
                : [];
            if (productoEditar && !guardadas.length && productoEditar.imagen_url) {
                guardadas.push({ id: null, url: productoEditar.imagen_url });
            }
            setFotos(guardadas.map((foto, indice) => ({
                key: `guardada-${foto.id ?? `url-${indice}`}`,
                id: foto.id ?? null,
                url: foto.url,
                preview: foto.url,
                archivo: null,
            })));
        }
    }, [isOpen, productoEditar]);

    const handleImagenChange = async (e) => {
        const seleccionados = Array.from(e.target.files || []);
        e.target.value = ''; // permite volver a elegir el mismo archivo
        if (!seleccionados.length) return;

        const espacio = MAX_FOTOS - fotos.length;
        if (espacio <= 0) {
            setErrors((prev) => ({
                ...prev,
                imagenes: `Máximo ${MAX_FOTOS} fotos por producto. Elimina una para agregar otra.`,
            }));
            return;
        }

        const aAgregar = seleccionados.slice(0, espacio);
        try {
            const nuevas = await Promise.all(aAgregar.map(leerFoto));
            setFotos((prev) => [...prev, ...nuevas].slice(0, MAX_FOTOS));
            setErrors((prev) => {
                const copia = { ...prev };
                delete copia.imagenes;
                if (seleccionados.length > espacio) {
                    copia.imagenes = `Sólo se agregaron ${espacio} foto(s): el máximo es ${MAX_FOTOS}.`;
                }
                return copia;
            });
        } catch (error) {
            setErrors((prev) => ({ ...prev, imagenes: error.message }));
        }
    };

    const moverFoto = (indice, delta) => {
        const destino = indice + delta;
        if (destino < 0 || destino >= fotos.length) return;
        setFotos((prev) => {
            const copia = [...prev];
            [copia[indice], copia[destino]] = [copia[destino], copia[indice]];
            return copia;
        });
    };

    const eliminarFoto = (indice) => {
        // La última foto no se borra: el backend también la protege. Para
        // reemplazarla, primero se agrega la nueva y después se quita la vieja.
        if (fotos.length <= 1) {
            setErrors((prev) => ({
                ...prev,
                imagenes: 'El producto debe conservar al menos una foto.',
            }));
            return;
        }
        setFotos((prev) => prev.filter((_, posicion) => posicion !== indice));
        setErrors((prev) => {
            const copia = { ...prev };
            delete copia.imagenes;
            return copia;
        });
    };

    // ── Tallas: filas editables del modal (083) ──────────────────────────────
    const agregarVariante = () => setVariantes((prev) => [...prev, { talla: '', stock: '0' }]);

    const actualizarVariante = (indice, campo, valor) => setVariantes((prev) => prev.map(
        (variante, posicion) => (posicion === indice ? { ...variante, [campo]: valor } : variante),
    ));

    const quitarVariante = (indice) => setVariantes(
        (prev) => prev.filter((_, posicion) => posicion !== indice));

    /** Tallas listas para el backend: texto recortado y stock numérico. */
    const variantesParaEnviar = () => variantes.map((variante) => ({
        talla: (variante.talla || '').trim(),
        stock: parseInt(variante.stock, 10) || 0,
    }));

    const validateForm = () => {
        const newErrors = {};

        if (!formData.nombre.trim()) newErrors.nombre = 'Nombre requerido';
        if (formData.nombre.length > 150) newErrors.nombre = 'Máximo 150 caracteres';
        if (!formData.precio) newErrors.precio = 'Precio requerido';
        if (formData.precio && parseFloat(formData.precio) <= 0) newErrors.precio = 'Precio debe ser mayor a 0';
        // Con tallas el stock del producto NO se pide: se carga por fila.
        if (!tieneVariantes) {
            if (formData.stock === '' || formData.stock === undefined) newErrors.stock = 'Stock requerido';
            if (formData.stock !== '' && parseInt(formData.stock) < 0) newErrors.stock = 'Stock no puede ser negativo';
        } else {
            // Validación de tallas ANTES de enviar (el backend igual la repite):
            // al menos una, sin vacías, máximo 30 caracteres y sin duplicados
            // CASE-INSENSITIVE ('S' y 's' son la misma talla).
            const tallas = variantes.map((variante) => (variante.talla || '').trim());
            const vistas = new Set();
            let repetida = null;
            for (const talla of tallas) {
                const clave = talla.toLowerCase();
                if (vistas.has(clave)) { repetida = talla; break; }
                vistas.add(clave);
            }
            if (!tallas.length) {
                newErrors.variantes = 'Agrega al menos una talla.';
            } else if (tallas.some((talla) => !talla)) {
                newErrors.variantes = 'Completa el nombre de cada talla.';
            } else if (tallas.some((talla) => talla.length > 30)) {
                newErrors.variantes = 'Máximo 30 caracteres por talla.';
            } else if (repetida) {
                newErrors.variantes = `Ya existe la talla '${repetida}' para este producto.`;
            } else if (variantes.some((variante) => variante.stock === ''
                || parseInt(variante.stock) < 0)) {
                newErrors.variantes = 'El stock de cada talla debe ser 0 o más.';
            }
        }
        if (formData.stock_minimo !== '' && formData.stock_minimo !== undefined
            && parseInt(formData.stock_minimo) < 0) newErrors.stock_minimo = 'El stock mínimo no puede ser negativo';
        // Días de anuncio en el Inicio del alumno (0 = no anunciar).
        if (formData.dias_anuncio !== '' && formData.dias_anuncio !== undefined
            && parseInt(formData.dias_anuncio) < 0) newErrors.dias_anuncio = 'Los días no pueden ser negativos';
        if (formData.dias_anuncio !== '' && formData.dias_anuncio !== undefined
            && parseInt(formData.dias_anuncio) > 365) newErrors.dias_anuncio = 'Máximo 365 días';
        // Descuento manual (migración 072): opcional, entre 1 y 90%.
        if (formData.descuento_pct !== '' && formData.descuento_pct !== undefined) {
            const desc = parseInt(formData.descuento_pct);
            if (desc < 1 || desc > 90) newErrors.descuento_pct = 'El descuento debe estar entre 1 y 90%';
        }

        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!validateForm()) return;

        setLoading(true);
        try {
            if (esEdicion) {
                // PUT para editar (JSON normal, sin imagen)
                const payload = {
                    nombre: formData.nombre,
                    descripcion: formData.descripcion || null,
                    precio: parseFloat(formData.precio),
                    // Con tallas el stock plano queda en 0 (el real es la suma de
                    // las tallas, calculada por el backend en la respuesta).
                    stock: tieneVariantes ? 0 : parseInt(formData.stock),
                    stock_minimo: (formData.stock_minimo === '' || formData.stock_minimo === undefined)
                        ? null : parseInt(formData.stock_minimo),
                    // Días de anuncio en el carrusel del Inicio: el backend crea,
                    // actualiza o quita el aviso del producto con este número.
                    dias_anuncio: parseInt(formData.dias_anuncio || 0),
                    // Descuento manual (migración 072). Vacío = null (sin descuento).
                    descuento_pct: (formData.descuento_pct === '' || formData.descuento_pct === undefined)
                        ? null : parseInt(formData.descuento_pct),
                    activo: formData.activo,
                    // Tallas (083): con el switch encendido se manda la lista
                    // COMPLETA (reemplaza el set). Apagado se omite a propósito:
                    // las tallas quedan guardadas (dormidas) por si se reactiva.
                    tiene_variantes: tieneVariantes,
                    ...(tieneVariantes ? { variantes: variantesParaEnviar() } : {}),
                };
                // El PUT es JSON y no puede llevar archivos: la galería se manda
                // aparte. `eliminar` son las fotos guardadas que ya no están en la
                // lista; `orden` mezcla ids existentes con posiciones nuevas.
                const idsOriginales = [...(productoEditar.imagenes || [])]
                    .map((foto) => foto.id)
                    .filter(Boolean);
                const idsConservados = new Set(fotos.filter((foto) => foto.id).map((foto) => foto.id));
                await guardarProducto.mutateAsync({
                    id: productoEditar.id,
                    payload,
                    galeria: {
                        eliminar: idsOriginales.filter((id) => !idsConservados.has(id)),
                        archivos: fotos.filter((foto) => foto.archivo).map((foto) => foto.archivo),
                        orden: fotos.map((foto, indice) => (
                            foto.id ? { id: foto.id } : { nueva: indice }
                        )),
                        totalExistentes: idsOriginales.length,
                    },
                });
            } else {
                // POST para crear con FormData (multipart/form-data para soportar imagen)
                const data = new FormData();
                data.append('nombre', formData.nombre);
                data.append('descripcion', formData.descripcion || '');
                data.append('precio', parseFloat(formData.precio));
                // Con tallas el stock plano va en 0: el stock real son las filas
                // de `variantes_json` (el POST es multipart y no acepta un Form
                // anidado, así que la lista viaja serializada).
                data.append('stock', tieneVariantes ? 0 : parseInt(formData.stock));
                data.append('tiene_variantes', tieneVariantes);
                if (tieneVariantes) {
                    data.append('variantes_json', JSON.stringify(variantesParaEnviar()));
                }
                if (formData.stock_minimo !== '' && formData.stock_minimo !== undefined) {
                    data.append('stock_minimo', parseInt(formData.stock_minimo));
                }
                // Días de anuncio en el carrusel "Novedades del box" del Inicio.
                data.append('dias_anuncio', parseInt(formData.dias_anuncio || 0));
                // Descuento manual (migración 072). Vacío = sin descuento.
                if (formData.descuento_pct !== '' && formData.descuento_pct !== undefined) {
                    data.append('descuento_pct', parseInt(formData.descuento_pct));
                }
                data.append('activo', formData.activo);
                // La galería completa viaja en la MISMA petición (`files`, en orden:
                // la primera es la portada). Si una foto falla, el backend no crea
                // el producto: el admin puede corregir y reintentar sin duplicarlo.
                const archivosNuevos = fotos.filter((foto) => foto.archivo).map((foto) => foto.archivo);
                archivosNuevos.forEach((archivo) => data.append('files', archivo));
                await guardarProducto.mutateAsync({ payload: data });
            }

            setFormData({
                nombre: '',
                descripcion: '',
                precio: '',
                stock: '',
                stock_minimo: '',
                dias_anuncio: '0',
                descuento_pct: '',
                activo: true,
            });
            setFotos([]);
            setTieneVariantes(false);
            setVariantes([]);
            setErrors({});

            if (onSuccess) onSuccess();
            onClose();
        } catch (error) {
            console.error('Error guardando producto:', error);
            setErrors({ submit: error.response?.data?.detail || 'Error al guardar producto' });
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-[90dvh] md:max-h-screen overflow-y-auto">
                <div className="bg-blue-900 text-white px-6 py-4 rounded-t-lg">
                    <h2 className="text-xl font-bold">{esEdicion ? 'Editar Producto' : 'Nuevo Producto'}</h2>
                </div>

                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    {errors.submit && (
                        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                            {errors.submit}
                        </div>
                    )}

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Nombre del Producto *
                        </label>
                        <input
                            type="text"
                            value={formData.nombre}
                            onChange={(e) => setFormData({ ...formData, nombre: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.nombre ? 'border-red-500' : 'border-gray-300'}`}
                            maxLength="150"
                            placeholder="Ej: Protein Powder Whey"
                        />
                        {errors.nombre && <p className="text-xs text-red-600 mt-1">{errors.nombre}</p>}
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                Precio (CLP) *
                            </label>
                            <input
                                type="number"
                                value={formData.precio}
                                onChange={(e) => setFormData({ ...formData, precio: e.target.value })}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.precio ? 'border-red-500' : 'border-gray-300'}`}
                                step="1"
                                min="1"
                                placeholder="0"
                            />
                            {errors.precio && <p className="text-xs text-red-600 mt-1">{errors.precio}</p>}
                        </div>

                        {/* Con tallas el stock NO es un número plano: se carga por
                            fila en el bloque de abajo (083). */}
                        {tieneVariantes ? (
                            <div className="flex items-end">
                                <p className="pb-2 text-xs text-gray-500">
                                    El stock se carga por talla, más abajo.
                                </p>
                            </div>
                        ) : (
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Stock *
                                </label>
                                <input
                                    type="number"
                                    value={formData.stock}
                                    onChange={(e) => setFormData({ ...formData, stock: e.target.value })}
                                    className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.stock ? 'border-red-500' : 'border-gray-300'}`}
                                    min="0"
                                    placeholder="0"
                                />
                                {errors.stock && <p className="text-xs text-red-600 mt-1">{errors.stock}</p>}
                            </div>
                        )}
                    </div>

                    {/* ── Tallas/variantes (migración 083) ──
                        Switch APAGADO por defecto: el producto nace con el stock
                        plano y el admin agrega tallas cuando las necesita. */}
                    <div className="rounded-lg border border-gray-200 p-3">
                        <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                                <label htmlFor="tiene_variantes" className="block text-sm font-medium text-gray-700">
                                    Este producto tiene tallas
                                </label>
                                <p className="mt-0.5 text-xs text-gray-500">
                                    Maneja el stock por talla (S, M, L, sabores, números…).
                                </p>
                            </div>
                            <button
                                type="button"
                                id="tiene_variantes"
                                role="switch"
                                aria-checked={tieneVariantes}
                                onClick={() => setTieneVariantes((prev) => !prev)}
                                className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors ${tieneVariantes ? 'border-orange-500 bg-orange-500' : 'border-gray-300 bg-gray-200'}`}
                            >
                                <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${tieneVariantes ? 'translate-x-6' : 'translate-x-1'}`} />
                            </button>
                        </div>

                        {tieneVariantes && (
                            <div className="mt-3 space-y-2">
                                {variantes.length === 0 && (
                                    <p className="text-xs text-gray-500">Sin tallas todavía. Agrega la primera.</p>
                                )}
                                {variantes.map((variante, indice) => (
                                    <div key={indice} className="flex items-center gap-2">
                                        <input
                                            type="text"
                                            value={variante.talla}
                                            onChange={(e) => actualizarVariante(indice, 'talla', e.target.value)}
                                            maxLength="30"
                                            placeholder="Talla"
                                            aria-label={`Nombre de la talla ${indice + 1}`}
                                            className="min-w-0 flex-1 rounded-lg border border-gray-300 px-2.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                                        />
                                        <input
                                            type="number"
                                            value={variante.stock}
                                            onChange={(e) => actualizarVariante(indice, 'stock', e.target.value)}
                                            min="0"
                                            placeholder="0"
                                            aria-label={`Stock de la talla ${indice + 1}`}
                                            className="w-24 shrink-0 rounded-lg border border-gray-300 px-2.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => quitarVariante(indice)}
                                            aria-label={`Quitar la talla ${indice + 1}`}
                                            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-red-200 text-red-600 transition-colors hover:bg-red-50"
                                        >
                                            ×
                                        </button>
                                    </div>
                                ))}
                                <button
                                    type="button"
                                    onClick={agregarVariante}
                                    className="w-full rounded-lg border border-dashed border-gray-300 px-3 py-2 text-sm font-medium text-gray-600 transition-colors hover:border-orange-400 hover:text-orange-600"
                                >
                                    + Agregar talla
                                </button>
                                {errors.variantes && <p className="text-xs text-red-600">{errors.variantes}</p>}
                                <p className="text-xs text-gray-500">
                                    El stock del producto será la suma de sus tallas.
                                </p>
                            </div>
                        )}
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Stock mínimo para alerta
                        </label>
                        <input
                            type="number"
                            value={formData.stock_minimo}
                            onChange={(e) => setFormData({ ...formData, stock_minimo: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.stock_minimo ? 'border-red-500' : 'border-gray-300'}`}
                            min="0"
                            placeholder="Opcional"
                        />
                        {errors.stock_minimo && <p className="text-xs text-red-600 mt-1">{errors.stock_minimo}</p>}
                        <p className="text-xs text-gray-500 mt-1">
                            Recibirás un correo automático cuando el stock baje a este valor. Vacío = alerta desactivada.
                        </p>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Días de anuncio en el Inicio
                        </label>
                        <input
                            type="number"
                            value={formData.dias_anuncio}
                            onChange={(e) => setFormData({ ...formData, dias_anuncio: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.dias_anuncio ? 'border-red-500' : 'border-gray-300'}`}
                            min="0"
                            max="365"
                            placeholder="0"
                        />
                        {errors.dias_anuncio && <p className="text-xs text-red-600 mt-1">{errors.dias_anuncio}</p>}
                        <p className="text-xs text-gray-500 mt-1">
                            Con días &gt; 0 el producto se anuncia en el carrusel "Novedades del box" del
                            Inicio del alumno (con su foto y su precio). 0 = no se anuncia.
                            Al guardar, el anuncio se relanza desde hoy con estos días.
                        </p>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Descuento (%)
                        </label>
                        <input
                            type="number"
                            value={formData.descuento_pct}
                            onChange={(e) => setFormData({ ...formData, descuento_pct: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.descuento_pct ? 'border-red-500' : 'border-gray-300'}`}
                            min="1"
                            max="90"
                            placeholder="Opcional"
                        />
                        {errors.descuento_pct && <p className="text-xs text-red-600 mt-1">{errors.descuento_pct}</p>}
                        <p className="text-xs text-gray-500 mt-1">
                            Descuento manual que el alumno verá como badge "-N%" en el Bazar.
                            Vacío = sin descuento.
                        </p>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Descripción
                        </label>
                        <textarea
                            value={formData.descripcion}
                            onChange={(e) => setFormData({ ...formData, descripcion: e.target.value })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                            rows="3"
                            maxLength="500"
                            placeholder="Descripción opcional del producto..."
                        />
                    </div>

                    <div>
                        <div className="flex items-baseline justify-between gap-2 mb-1">
                            <label className="block text-sm font-medium text-gray-700">
                                📷 Fotos del Producto
                            </label>
                            <span className="text-xs text-gray-500">{fotos.length} / {MAX_FOTOS}</span>
                        </div>
                        <input
                            type="file"
                            accept="image/*"
                            multiple
                            onChange={handleImagenChange}
                            disabled={fotos.length >= MAX_FOTOS}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 text-sm text-gray-600 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-sm file:font-medium file:bg-orange-50 file:text-orange-700 hover:file:bg-orange-100 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                        />

                        {fotos.length > 0 ? (
                            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                                {fotos.map((foto, indice) => (
                                    <div
                                        key={foto.key}
                                        className="relative overflow-hidden rounded-lg border border-gray-200 bg-gray-50"
                                    >
                                        <ImagenProducto
                                            url={foto.preview || foto.url}
                                            alt={`Foto ${indice + 1}`}
                                            className="h-24 w-full object-cover"
                                            respaldo={<span className="flex h-24 items-center justify-center text-3xl">🛍️</span>}
                                        />
                                        {indice === 0 && (
                                            <span className="absolute left-1 top-1 rounded bg-orange-500 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
                                                Portada
                                            </span>
                                        )}
                                        <div className="flex items-center justify-between gap-1 border-t border-gray-200 bg-white px-1 py-1">
                                            <div className="flex gap-1">
                                                <button
                                                    type="button"
                                                    onClick={() => moverFoto(indice, -1)}
                                                    disabled={indice === 0}
                                                    aria-label={`Mover foto ${indice + 1} hacia arriba`}
                                                    className="flex h-6 w-6 items-center justify-center rounded border border-gray-200 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-30"
                                                >
                                                    ↑
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => moverFoto(indice, 1)}
                                                    disabled={indice === fotos.length - 1}
                                                    aria-label={`Mover foto ${indice + 1} hacia abajo`}
                                                    className="flex h-6 w-6 items-center justify-center rounded border border-gray-200 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-30"
                                                >
                                                    ↓
                                                </button>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => eliminarFoto(indice)}
                                                disabled={fotos.length <= 1}
                                                aria-label={`Eliminar foto ${indice + 1}`}
                                                className="flex h-6 w-6 items-center justify-center rounded border border-red-200 text-xs text-red-600 hover:bg-red-50 disabled:opacity-30"
                                            >
                                                ✕
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="mt-2 text-xs text-gray-400">Sin fotos. La primera que agregues será la portada.</p>
                        )}

                        {errors.imagenes && (
                            <p className="text-xs text-red-600 mt-1">{errors.imagenes}</p>
                        )}
                        <p className="text-xs text-gray-500 mt-1">
                            Hasta {MAX_FOTOS} fotos (JPG, PNG, WEBP, máx. 5 MB cada una). La primera es
                            la portada; usa ↑/↓ para cambiar el orden.
                        </p>
                    </div>

                    {esEdicion && (
                        <div className="flex items-center gap-3">
                            <input
                                type="checkbox"
                                id="activo"
                                checked={formData.activo}
                                onChange={(e) => setFormData({ ...formData, activo: e.target.checked })}
                                className="w-4 h-4 text-orange-500 rounded"
                            />
                            <label htmlFor="activo" className="text-sm font-medium text-gray-700">
                                Producto activo (visible en el bazar)
                            </label>
                        </div>
                    )}

                    <div className="flex gap-3 pt-4">
                        <button
                            type="button"
                            onClick={onClose}
                            className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-medium"
                            disabled={loading}
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium disabled:opacity-50"
                            disabled={loading}
                        >
                            {loading ? (esEdicion ? 'Guardando...' : 'Creando...') : (esEdicion ? 'Guardar Cambios' : 'Crear Producto')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ModalProducto;
