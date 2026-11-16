import React from 'react';
import {
    AYUDA, CAMPO, ETIQUETA, TARJETA, TITULO_SECCION,
} from './camposWod';

/**
 * Familia `rounds_tecnica`: Boxeo, Kickboxing, Artes marciales.
 * Número de rounds + duración por round + un foco técnico general (campo único
 * simplificado: el coach puede listar combinaciones separadas por línea).
 */
const FormularioRoundsTecnica = ({ valor, onChange }) => {
    const datos = valor || { rounds: '', duracion: '', foco: '' };
    const actualizar = (campo, nuevoValor) => onChange({ ...datos, [campo]: nuevoValor });

    return (
        <div className={TARJETA} data-testid="form-rounds-tecnica">
            <p className={TITULO_SECCION}>Rounds y técnica</p>
            <p className={AYUDA}>Duración por round y el foco técnico o las combinaciones del día.</p>

            <div className="mt-2 grid grid-cols-2 gap-2">
                <label className={ETIQUETA}>
                    Número de rounds
                    <input type="text" inputMode="numeric" value={datos.rounds}
                        onChange={(e) => actualizar('rounds', e.target.value)}
                        maxLength={10} placeholder="Ej. 6"
                        data-testid="rounds-cantidad" className={CAMPO} />
                </label>
                <label className={ETIQUETA}>
                    Duración por round
                    <input type="text" value={datos.duracion}
                        onChange={(e) => actualizar('duracion', e.target.value)}
                        maxLength={40} placeholder="Ej. 3 minutos"
                        data-testid="rounds-duracion" className={CAMPO} />
                </label>
            </div>

            <label className={ETIQUETA}>
                Foco técnico / combinaciones
                <textarea rows={4} value={datos.foco}
                    onChange={(e) => actualizar('foco', e.target.value)}
                    maxLength={1000}
                    placeholder={'Ej. Round 1-3: jab, cross, hook\nRound 4-6: defensa y contragolpe'}
                    data-testid="rounds-foco" className={CAMPO} />
            </label>
        </div>
    );
};

export default FormularioRoundsTecnica;
