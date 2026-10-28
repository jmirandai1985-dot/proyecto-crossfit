/**
 * Banner "Completá tu perfil" (D2) del panel del ALUMNO.
 *
 * Peso y género son obligatorios para clasificar el nivel: sin ellos el motor no puede
 * calcular fuerza (ratio peso_rm/peso_corporal) ni elegir la tabla M/F de gimnasia. Los
 * alumnos que ya existían no los tienen porque el alta no los pedía (en PROD: 300 con peso y
 * sin género, 104 sin ninguno), así que este banner los manda a Ajustes, donde el género se
 * puede COMPLETAR una vez (y el peso editar siempre).
 *
 * Se monta desde `Layout` solo para `rol === 'alumno'` y desaparece solo cuando el perfil está
 * completo: la fuente es `GET /alumnos/me` (la misma caché que Ajustes comparte, así que al
 * guardar se refresca sin recargar).
 */
import React from 'react';
import { Link } from 'react-router-dom';
import { useMiPerfil } from '../hooks/queries';

const BannerPerfilIncompleto = () => {
    const { data: perfil } = useMiPerfil();

    // Sin dato (cargando o error): no se muestra nada. Un banner de "falta tu perfil" cuando
    // todavía no sabemos si falta sería una acusación falsa.
    if (!perfil) return null;

    const faltaPeso = !perfil.peso_kg;
    const faltaGenero = !perfil.genero;
    if (!faltaPeso && !faltaGenero) return null;

    const faltantes = [faltaPeso ? 'peso' : null, faltaGenero ? 'género' : null]
        .filter(Boolean).join(' y ');

    return (
        <div
            data-testid="banner-perfil-incompleto"
            className="mb-4 flex flex-col gap-2 rounded-lg border border-orange-500/40 bg-orange-500/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
        >
            <p className="text-sm text-orange-200">
                <span className="font-semibold">Completá tu perfil:</span> falta tu {faltantes}.
                Sin esos datos no podemos calcular tu nivel (fuerza y gimnasia).
            </p>
            <Link
                to="/alumno/ajustes"
                className="shrink-0 rounded-md bg-orange-500 px-3 py-1.5 text-center text-xs font-bold text-zinc-950 hover:bg-orange-400"
            >
                Completar ahora
            </Link>
        </div>
    );
};

export default BannerPerfilIncompleto;
