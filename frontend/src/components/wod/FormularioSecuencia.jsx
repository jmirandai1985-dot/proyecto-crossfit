import React from 'react';
import { filaSecuenciaVacia } from '../../utils/formulariosWod';
import {
    AYUDA, BOTON_AGREGAR, BOTON_MOVER, BOTON_QUITAR, CAMPO, ETIQUETA,
    TARJETA, TITULO_SECCION,
} from './camposWod';

/**
 * Familia `secuencia`: Yoga, Pilates, Movilidad.
 * Lista ordenada de bloques/posturas (nombre + descripción o duración opcional).
 * Se puede agregar, quitar y mover arriba/abajo: el orden es parte del contenido.
 */
const FormularioSecuencia = ({ valor, onChange }) => {
    const bloques = valor?.bloques || [];

    const actualizar = (indice, campo, nuevoValor) => onChange({
        ...valor,
        bloques: bloques.map((bloque, i) => (
            i === indice ? { ...bloque, [campo]: nuevoValor } : bloque
        )),
    });

    const agregar = () => onChange({
        ...valor,
        bloques: [...bloques, filaSecuenciaVacia()],
    });

    const quitar = (indice) => onChange({
        ...valor,
        bloques: bloques.filter((_, i) => i !== indice),
    });

    const mover = (indice, destino) => {
        if (destino < 0 || destino >= bloques.length) return;
        const copia = [...bloques];
        const [fila] = copia.splice(indice, 1);
        copia.splice(destino, 0, fila);
        onChange({ ...valor, bloques: copia });
    };

    return (
        <div className={TARJETA} data-testid="form-secuencia">
            <div className="flex items-start justify-between gap-2">
                <div>
                    <p className={TITULO_SECCION}>Secuencia de bloques</p>
                    <p className={AYUDA}>Posturas o bloques en orden. La duración va en la descripción.</p>
                </div>
                <button type="button" onClick={agregar} className={BOTON_AGREGAR}
                    data-testid="secuencia-agregar">
                    + Agregar bloque
                </button>
            </div>

            {bloques.length === 0 ? (
                <p className="mt-2 text-[11px] italic text-zinc-600">
                    Todavía no hay bloques.
                </p>
            ) : (
                <div className="mt-2 space-y-2">
                    {bloques.map((bloque, indice) => (
                        <div key={indice} className="rounded-lg border border-zinc-800 bg-zinc-900 p-2.5"
                            data-testid={`secuencia-bloque-${indice}`}>
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-[10.5px] font-black uppercase tracking-wide text-zinc-400">
                                    Bloque {indice + 1}
                                </span>
                                <div className="flex items-center gap-1">
                                    <button type="button" onClick={() => mover(indice, indice - 1)}
                                        disabled={indice === 0} className={BOTON_MOVER}
                                        data-testid={`secuencia-subir-${indice}`}>
                                        Subir
                                    </button>
                                    <button type="button" onClick={() => mover(indice, indice + 1)}
                                        disabled={indice === bloques.length - 1} className={BOTON_MOVER}
                                        data-testid={`secuencia-bajar-${indice}`}>
                                        Bajar
                                    </button>
                                    <button type="button" onClick={() => quitar(indice)}
                                        className={BOTON_QUITAR}
                                        data-testid={`secuencia-quitar-${indice}`}>
                                        Quitar
                                    </button>
                                </div>
                            </div>
                            <label className={ETIQUETA}>
                                Nombre
                                <input type="text" value={bloque.nombre}
                                    onChange={(e) => actualizar(indice, 'nombre', e.target.value)}
                                    maxLength={120} placeholder="Ej. Postura del niño"
                                    data-testid={`secuencia-nombre-${indice}`}
                                    className={CAMPO} />
                            </label>
                            <label className={ETIQUETA}>
                                Descripción o duración
                                <textarea rows={2} value={bloque.descripcion}
                                    onChange={(e) => actualizar(indice, 'descripcion', e.target.value)}
                                    maxLength={500} placeholder="Ej. 5 minutos, respiración lenta"
                                    data-testid={`secuencia-descripcion-${indice}`}
                                    className={CAMPO} />
                            </label>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default FormularioSecuencia;
