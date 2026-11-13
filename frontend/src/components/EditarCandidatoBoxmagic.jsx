import React, { useState } from 'react';
import { Pencil } from 'lucide-react';
import { useEditarCandidatoBoxmagic } from '../hooks/queries';

/**
 * Modal para corregir el NOMBRE/CORREO de un candidato del padrón de BoxMagic.
 *
 * El Excel real trae correos truncados o mal escritos; el admin los corrige acá sin
 * tocar la base a mano. Si el candidato ya tiene una cuenta real, el backend BLOQUEA
 * el cambio de correo (rompería el LEFT JOIN por correo): el campo queda deshabilitado
 * y sólo se puede corregir el nombre.
 *
 * Lo usan los DOS paneles (Activación y Recuperación). Al guardar, el hook parchea la
 * fila en la caché de ambos y reconcilia en segundo plano (sin recargar la página).
 */
const EditarCandidatoBoxmagic = ({ alumno, onClose }) => {
    const editar = useEditarCandidatoBoxmagic();
    const [nombre, setNombre] = useState(alumno.nombre || '');
    const [correo, setCorreo] = useState(alumno.correo || '');
    const [error, setError] = useState('');

    // `id` es la cuenta REAL: si no es null, el candidato ya está vinculado por correo.
    const tieneCuenta = alumno.id !== null && alumno.id !== undefined;
    const candidatoId = alumno.candidato_id ?? alumno.id;
    const guardando = editar.isPending;

    const guardar = async (e) => {
        e.preventDefault();
        setError('');
        const nombreLimpio = nombre.trim();
        const correoLimpio = correo.trim();
        if (!nombreLimpio) {
            setError('El nombre no puede estar vacío.');
            return;
        }
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(correoLimpio)) {
            setError('Ingresa un correo válido (ej: nombre@dominio.cl).');
            return;
        }
        try {
            await editar.mutateAsync({
                candidatoId,
                nombre: nombreLimpio,
                correo: correoLimpio,
            });
            onClose();
        } catch (err) {
            const detalle = err?.response?.data?.detail;
            const texto = Array.isArray(detalle) ? detalle[0]?.msg : detalle;
            setError(texto || 'No se pudo guardar la corrección.');
        }
    };

    return (
        <div
            className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
            role="dialog"
            aria-modal="true"
            data-testid="modal-editar-candidato"
        >
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-md">
                <div className="flex items-start justify-between p-5 border-b border-zinc-800">
                    <div className="flex items-start gap-3">
                        <Pencil className="mt-1 h-5 w-5 shrink-0 text-orange-400" aria-hidden="true" />
                        <div>
                            <h3 className="text-lg font-bold text-zinc-100">Editar candidato</h3>
                            <p className="text-sm text-zinc-400">
                                Corrige el nombre o el correo del padrón de BoxMagic.
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Cerrar"
                        data-testid="modal-editar-candidato-cerrar"
                        className="text-zinc-400 hover:text-zinc-100 text-xl leading-none"
                    >
                        ×
                    </button>
                </div>

                <form onSubmit={guardar} className="p-5 space-y-4">
                    {tieneCuenta && (
                        <div className="bg-amber-500/10 border-l-4 border-amber-500 rounded p-3 text-sm text-amber-200">
                            Este candidato ya tiene una cuenta real: el correo no se puede
                            cambiar porque es el vínculo con su cuenta. Puedes corregir el
                            nombre.
                        </div>
                    )}

                    {error && (
                        <div
                            className="bg-red-500/10 border-l-4 border-red-500 rounded p-3 text-sm text-red-300"
                            data-testid="modal-editar-candidato-error"
                        >
                            {error}
                        </div>
                    )}

                    <div>
                        <label htmlFor="candidato-nombre"
                            className="block text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                            Nombre
                        </label>
                        <input
                            id="candidato-nombre"
                            data-testid="modal-editar-candidato-nombre"
                            type="text"
                            value={nombre}
                            onChange={(e) => setNombre(e.target.value)}
                            maxLength={150}
                            disabled={guardando}
                            className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500 disabled:opacity-60"
                            required
                        />
                    </div>

                    <div>
                        <label htmlFor="candidato-correo"
                            className="block text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                            Correo
                        </label>
                        <input
                            id="candidato-correo"
                            data-testid="modal-editar-candidato-correo"
                            type="email"
                            value={correo}
                            onChange={(e) => setCorreo(e.target.value)}
                            maxLength={150}
                            disabled={guardando || tieneCuenta}
                            className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500 disabled:opacity-60 disabled:cursor-not-allowed"
                            required
                        />
                        {tieneCuenta && (
                            <p className="mt-1 text-[11px] text-zinc-500">
                                Correo bloqueado: la cuenta real lo usa para entrar.
                            </p>
                        )}
                    </div>

                    <div className="flex justify-end gap-2 pt-1">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={guardando}
                            className="px-4 py-2 rounded-lg text-sm font-semibold text-zinc-300 hover:bg-zinc-800 disabled:opacity-60"
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            disabled={guardando}
                            data-testid="modal-editar-candidato-guardar"
                            className="px-4 py-2 rounded-lg text-sm font-bold bg-orange-600 text-white transition hover:bg-orange-700 active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
                        >
                            {guardando ? 'Guardando...' : 'Guardar'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default EditarCandidatoBoxmagic;
