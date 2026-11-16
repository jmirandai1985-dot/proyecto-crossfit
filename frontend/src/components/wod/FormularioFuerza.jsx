import React from 'react';
import { filaFuerzaVacia } from '../../utils/formulariosWod';
import {
    AYUDA, BOTON_AGREGAR, BOTON_QUITAR, BOTON_TOGGLE, CAMPO, ETIQUETA,
    TARJETA, TITULO_SECCION,
} from './camposWod';

/**
 * Familia `fuerza`: GAP, Levantamiento Olímpico, Musculación, Calistenia.
 * Una fila por ejercicio con series, repeticiones y peso O %RM (toggle).
 * Sin estado propio: el modal es dueño del borrador (value/onChange).
 */
const FormularioFuerza = ({ valor, onChange }) => {
    const ejercicios = valor?.ejercicios || [];

    const actualizar = (indice, campo, nuevoValor) => {
        onChange({
            ...valor,
            ejercicios: ejercicios.map((ejercicio, i) => (
                i === indice ? { ...ejercicio, [campo]: nuevoValor } : ejercicio
            )),
        });
    };

    const agregar = () => onChange({
        ...valor,
        ejercicios: [...ejercicios, filaFuerzaVacia()],
    });

    const quitar = (indice) => onChange({
        ...valor,
        ejercicios: ejercicios.filter((_, i) => i !== indice),
    });

    return (
        <div className={TARJETA} data-testid="form-fuerza">
            <div className="flex items-start justify-between gap-2">
                <div>
                    <p className={TITULO_SECCION}>Ejercicios de fuerza</p>
                    <p className={AYUDA}>Series x repeticiones, con peso en kg o %RM.</p>
                </div>
                <button type="button" onClick={agregar} className={BOTON_AGREGAR}
                    data-testid="fuerza-agregar">
                    + Agregar ejercicio
                </button>
            </div>

            {ejercicios.length === 0 ? (
                <p className="mt-2 text-[11px] italic text-zinc-600">
                    Todavía no hay ejercicios.
                </p>
            ) : (
                <div className="mt-2 space-y-2">
                    {ejercicios.map((ejercicio, indice) => (
                        <div key={indice} className="rounded-lg border border-zinc-800 bg-zinc-900 p-2.5"
                            data-testid={`fuerza-ejercicio-${indice}`}>
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-[10.5px] font-black uppercase tracking-wide text-zinc-400">
                                    Ejercicio {indice + 1}
                                </span>
                                <button type="button" onClick={() => quitar(indice)}
                                    className={BOTON_QUITAR}
                                    data-testid={`fuerza-quitar-${indice}`}>
                                    Quitar
                                </button>
                            </div>
                            <label className={ETIQUETA}>
                                Nombre
                                <input type="text" value={ejercicio.nombre}
                                    onChange={(e) => actualizar(indice, 'nombre', e.target.value)}
                                    maxLength={120} placeholder="Ej. Back Squat"
                                    data-testid={`fuerza-nombre-${indice}`}
                                    className={CAMPO} />
                            </label>
                            <div className="mt-2 grid grid-cols-2 gap-2">
                                <label className={ETIQUETA}>
                                    Series
                                    <input type="text" inputMode="numeric" value={ejercicio.series}
                                        onChange={(e) => actualizar(indice, 'series', e.target.value)}
                                        maxLength={20} placeholder="5"
                                        data-testid={`fuerza-series-${indice}`}
                                        className={CAMPO} />
                                </label>
                                <label className={ETIQUETA}>
                                    Repeticiones
                                    <input type="text" value={ejercicio.repeticiones}
                                        onChange={(e) => actualizar(indice, 'repeticiones', e.target.value)}
                                        maxLength={40} placeholder="5"
                                        data-testid={`fuerza-reps-${indice}`}
                                        className={CAMPO} />
                                </label>
                            </div>
                            <div className="mt-2">
                                <span className={ETIQUETA}>Carga</span>
                                <div className="mt-1.5 flex flex-wrap gap-1.5">
                                    <button type="button"
                                        onClick={() => actualizar(indice, 'cargaTipo', 'peso')}
                                        className={BOTON_TOGGLE(ejercicio.cargaTipo !== 'porcentaje')}
                                        data-testid={`fuerza-carga-peso-${indice}`}>
                                        Peso (kg)
                                    </button>
                                    <button type="button"
                                        onClick={() => actualizar(indice, 'cargaTipo', 'porcentaje')}
                                        className={BOTON_TOGGLE(ejercicio.cargaTipo === 'porcentaje')}
                                        data-testid={`fuerza-carga-rm-${indice}`}>
                                        % RM
                                    </button>
                                </div>
                                <input type="text" inputMode="decimal" value={ejercicio.carga}
                                    onChange={(e) => actualizar(indice, 'carga', e.target.value)}
                                    maxLength={20}
                                    placeholder={ejercicio.cargaTipo === 'porcentaje' ? 'Ej. 75' : 'Ej. 80'}
                                    data-testid={`fuerza-carga-${indice}`}
                                    className={CAMPO} />
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default FormularioFuerza;

