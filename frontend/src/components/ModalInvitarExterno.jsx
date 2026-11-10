import React, { useState } from 'react';
import { useInvitarExterno } from '../hooks/queries';

/**
 * Modal "✉️ Invitar" del Dashboard Coach (Parte H).
 *
 * Reemplaza la navegación vieja a `/coach/alumnos-prueba` (el panel del ADMIN para reenviar
 * correo a alumnos YA registrados): acá el coach invita a una persona NUEVA con un formulario
 * libre de 2 campos. El correo sale de `POST /api/v1/coach/invitaciones-externas` con el link
 * a `/landing`; el `coach_id` lo deriva el backend del token.
 */
const ModalInvitarExterno = ({ onClose }) => {
    const invitar = useInvitarExterno();
    const [nombre, setNombre] = useState('');
    const [correo, setCorreo] = useState('');
    const [error, setError] = useState('');
    const [msg, setMsg] = useState(null);

    const enviar = async (e) => {
        e.preventDefault();
        setError('');
        setMsg(null);
        const nom = nombre.trim();
        const cor = correo.trim();
        if (!nom || !cor) {
            setError('Completá nombre y correo.');
            return;
        }
        try {
            const d = await invitar.mutateAsync({ nombre: nom, correo: cor });
            if (d.exito) {
                setMsg(d.ya_es_alumno
                    ? `✉️ Invitación enviada a ${nom}. Ojo: ese correo ya es alumno del box.`
                    : `✉️ Invitación enviada a ${nom}.`);
                setNombre('');
                setCorreo('');
            } else {
                setError(d.detalle_error || 'No se pudo enviar la invitación.');
            }
        } catch (err) {
            setError(err.response?.data?.detail || 'No se pudo enviar la invitación.');
        }
    };

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-md">
                <div className="flex items-start justify-between p-5 border-b border-zinc-800">
                    <div>
                        <h3 className="text-lg font-bold text-zinc-100">✉️ Invitar a una clase de prueba</h3>
                        <p className="text-sm text-zinc-400">Mandá la invitación a alguien que todavía no es alumno.</p>
                    </div>
                    <button type="button" onClick={onClose} aria-label="Cerrar"
                        className="text-xl font-bold leading-none text-zinc-400 hover:text-zinc-200">✕</button>
                </div>
                <form onSubmit={enviar} className="p-5 space-y-4">
                    <label className="block">
                        <span className="text-sm font-medium text-zinc-300">Nombre</span>
                        <input type="text" value={nombre} maxLength={200}
                            onChange={(e) => setNombre(e.target.value)}
                            placeholder="Nombre de la persona"
                            data-testid="invitar-nombre"
                            className="mt-1.5 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none" />
                    </label>
                    <label className="block">
                        <span className="text-sm font-medium text-zinc-300">Correo</span>
                        <input type="email" value={correo} maxLength={255}
                            onChange={(e) => setCorreo(e.target.value)}
                            placeholder="correo@ejemplo.com"
                            data-testid="invitar-correo"
                            className="mt-1.5 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none" />
                    </label>
                    {error && (
                        <div className="rounded-lg border border-red-700 bg-red-900/30 px-3 py-2 text-sm text-red-200" data-testid="invitar-error">
                            {error}
                        </div>
                    )}
                    {msg && (
                        <div className="rounded-lg border border-green-700 bg-green-900/30 px-3 py-2 text-sm text-green-200" data-testid="invitar-exito">
                            {msg}
                        </div>
                    )}
                    <div className="flex justify-end gap-2 pt-1">
                        <button type="button" onClick={onClose}
                            className="px-4 py-2 rounded-lg text-sm font-medium text-zinc-300 hover:text-zinc-100">
                            Cancelar
                        </button>
                        <button type="submit" disabled={invitar.isPending}
                            data-testid="invitar-enviar"
                            className="px-4 py-2 rounded-lg bg-orange-500 text-white text-sm font-bold hover:bg-orange-600 disabled:opacity-50">
                            {invitar.isPending ? 'Enviando…' : 'Enviar invitación'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ModalInvitarExterno;
