import React from 'react';
import { AYUDA, CAMPO, ETIQUETA, TARJETA, TITULO_SECCION } from './camposWod';

/**
 * Familia `libre`: Zumba, Baile, otros.
 * Título + descripción en texto, sin estructura de series/rounds.
 */
const FormularioLibre = ({ valor, onChange }) => {
    const datos = valor || { titulo: '', descripcion: '' };
    const actualizar = (campo, nuevoValor) => onChange({ ...datos, [campo]: nuevoValor });

    return (
        <div className={TARJETA} data-testid="form-libre">
            <p className={TITULO_SECCION}>Entrenamiento libre</p>
            <p className={AYUDA}>Un título y la descripción completa. Sin bloques ni series.</p>

            <label className={ETIQUETA}>
                Título
                <input type="text" value={datos.titulo}
                    onChange={(e) => actualizar('titulo', e.target.value)}
                    maxLength={200} placeholder="Ej. Coreografía de la semana"
                    data-testid="libre-titulo" className={CAMPO} />
            </label>

            <label className={ETIQUETA}>
                Descripción
                <textarea rows={6} value={datos.descripcion}
                    onChange={(e) => actualizar('descripcion', e.target.value)}
                    maxLength={2000}
                    placeholder="Describe el entrenamiento, la música o las indicaciones del día."
                    data-testid="libre-descripcion" className={CAMPO} />
            </label>
        </div>
    );
};

export default FormularioLibre;
