/**
 * useFiltroDisciplina — estado del filtro por disciplina (los chips).
 *
 * POR QUÉ EXISTE: "Mis Reservas" y "Clases disponibles" del Inicio móvil usan el
 * MISMO filtro (elegir una disciplina y recordarla mientras dure la sesión). La
 * lógica vive acá una sola vez; el pintado, en `components/FiltroDisciplina`.
 *
 * Nada de acá toca el backend: las disciplinas se derivan de las filas que la
 * pantalla ya recibió (`disciplina_nombre`) y el filtro sobre esas mismas filas.
 *
 * Uso:
 *   const { disponibles, filtro, cambiar, mostrar } =
 *       useFiltroDisciplina(clasesDelDia, CLAVE_FILTRO_INICIO);
 *   const visibles = filtrarPorDisciplina(clasesDelDia, filtro);
 */
import { useState } from 'react';
import {
    disciplinasDe, filtroEfectivo, hayQueFiltrar, leerRecordado, recordar,
} from '../utils/filtroDisciplina';

export function useFiltroDisciplina(filas, claveSesion) {
    // Arranca con lo ÚLTIMO elegido en esta sesión (sessionStorage). La clave es
    // una constante por pantalla, así que no cambia entre renders.
    const [recordado, setRecordado] = useState(() => leerRecordado(claveSesion));

    const disponibles = disciplinasDe(filas);
    // Si lo recordado ya no está en los datos, cae a "Todas".
    const filtro = filtroEfectivo(recordado, disponibles);

    const cambiar = (disciplina) => {
        setRecordado(disciplina);
        recordar(claveSesion, disciplina);
    };

    return { disponibles, filtro, cambiar, mostrar: hayQueFiltrar(disponibles) };
}

export default useFiltroDisciplina;
