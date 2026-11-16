import React from 'react';
import { filaIntervalosVacia } from '../../utils/formulariosWod';
import {
    AYUDA, BOTON_AGREGAR, BOTON_QUITAR, CAMPO, ETIQUETA, TARJETA,
    TITULO_SECCION,
} from './camposWod';

/**
 * Familia `intervalos`: Running, Ciclismo, Natación.
 * Series con distancia, tiempo y ritmo en texto libre (sin validación estricta).
 */
const FormularioIntervalos = ({ valor, onChange }) => {
    const series = valor?.series || [];

    const actualizar = (indice, campo, nuevoValor) => onChange({
        ...valor,
        series: series.map((serie, i) => (
            i === indice ? { ...serie, [campo]: nuevoValor } : serie
        )),
    });

    const agregar = () => onChange({
        ...valor,
        series: [...series, filaIntervalosVacia()],
    });

    const quitar = (indice) => onChange({
        ...valor,
        series: series.filter((_, i) => i !== indice),
    });

    return (
        <div className={TARJETA} data-testid="form-intervalos">
            <div className="flex items-start justify-between gap-2">
                <div>
                    <p className={TITULO_SECCION}>Series de intervalos</p>
                    <p className={AYUDA}>Distancia, tiempo y ritmo por serie. Texto libre.</p>
                </div>
                <button type="button" onClick={agregar} className={BOTON_AGREGAR}
                    data-testid="intervalos-agregar">
                    + Agregar serie
                </button>
            </div>

            {series.length === 0 ? (
                <p className="mt-2 text-[11px] italic text-zinc-600">
                    Todavía no hay series.
                </p>
            ) : (
                <div className="mt-2 space-y-2">
                    {series.map((serie, indice) => (
                        <div key={indice} className="rounded-lg border border-zinc-800 bg-zinc-900 p-2.5"
                            data-testid={`intervalos-serie-${indice}`}>
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-[10.5px] font-black uppercase tracking-wide text-zinc-400">
                                    Serie {indice + 1}
                                </span>
                                <button type="button" onClick={() => quitar(indice)}
                                    className={BOTON_QUITAR}
                                    data-testid={`intervalos-quitar-${indice}`}>
                                    Quitar
                                </button>
                            </div>
                            <div className="mt-1.5 grid grid-cols-3 gap-2">
                                <label className={ETIQUETA}>
                                    Distancia
                                    <input type="text" value={serie.distancia}
                                        onChange={(e) => actualizar(indice, 'distancia', e.target.value)}
                                        maxLength={40} placeholder="400 m"
                                        data-testid={`intervalos-distancia-${indice}`}
                                        className={CAMPO} />
                                </label>
                                <label className={ETIQUETA}>
                                    Tiempo
                                    <input type="text" value={serie.tiempo}
                                        onChange={(e) => actualizar(indice, 'tiempo', e.target.value)}
                                        maxLength={40} placeholder="1:30"
                                        data-testid={`intervalos-tiempo-${indice}`}
                                        className={CAMPO} />
                                </label>
                                <label className={ETIQUETA}>
                                    Ritmo
                                    <input type="text" value={serie.ritmo}
                                        onChange={(e) => actualizar(indice, 'ritmo', e.target.value)}
                                        maxLength={40} placeholder="5:30/km"
                                        data-testid={`intervalos-ritmo-${indice}`}
                                        className={CAMPO} />
                                </label>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default FormularioIntervalos;
