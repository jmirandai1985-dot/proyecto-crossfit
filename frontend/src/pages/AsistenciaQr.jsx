import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

/**
 * Página pública que se abre al escanear el QR del box.
 *
 * Flujo:
 *  - Sin sesión → redirige a /login guardando `state.from` para volver acá
 *    tras loguear (Login.jsx ya respeta ese state).
 *  - Sesión con rol alumno → llama a POST /api/v1/asistencia/qr/{publicId}/check-in
 *    y muestra el resultado (marcado OK / ya estaba / sin reserva / ambiguo).
 *  - Sesión con rol coach/admin → mensaje informativo (el check-in por QR es
 *    de alumnos; ellos marcan desde su panel).
 */
const AsistenciaQr = () => {
    const { publicId } = useParams();
    const navigate = useNavigate();
    const { isAuthenticated, rol, loading } = useAuth();
    const [vista, setVista] = useState({ tipo: 'cargando', titulo: '', mensaje: '' });

    useEffect(() => {
        if (loading) return;

        if (!isAuthenticated) {
            navigate('/login', {
                state: { from: `/asistencia/qr/${publicId || ''}` },
                replace: true,
            });
            return;
        }

        if (rol !== 'alumno') {
            setVista({
                tipo: 'info',
                titulo: 'Este QR es para alumnos',
                mensaje: 'Si sos coach o administrador, marcá la asistencia de tus clases desde tu panel. Para autoescanearte necesitás una cuenta de alumno.',
            });
            return;
        }

        const hacerCheckin = async () => {
            try {
                const r = await api.post(`/api/v1/asistencia/qr/${publicId || ''}/check-in`);
                const d = r.data || {};
                if (d.estado === 'ok') {
                    setVista({ tipo: 'ok', titulo: '✅ ¡Asistencia registrada!', mensaje: d.mensaje || 'Buen entrenamiento.' });
                } else if (d.estado === 'ya_marcado') {
                    setVista({ tipo: 'ok', titulo: '🔄 Ya estabas registrado', mensaje: d.mensaje || 'Tu asistencia a esta clase ya estaba marcada.' });
                } else if (d.estado === 'ambiguo') {
                    setVista({ tipo: 'amb', titulo: '⚠️ Más de una clase en curso', mensaje: d.mensaje || 'Hablá con tu coach para registrar la clase correcta.' });
                } else {
                    setVista({ tipo: 'sin', titulo: '😕 No tenés reserva en este horario', mensaje: d.mensaje || 'Hablá con tu coach.' });
                }
            } catch (e) {
                const det = e.response?.data?.detail
                    || (e.response?.status === 403 ? 'Este QR no corresponde a tu box.' : 'No pudimos registrar tu asistencia. Intentalo de nuevo.');
                setVista({ tipo: 'error', titulo: '❌ Error', mensaje: det });
            }
        };

        hacerCheckin();
    }, [loading, isAuthenticated, rol, publicId, navigate]);

    const estilos = {
        cargando: 'border-orange-500',
        ok: 'bg-green-500/15 border-green-500/40',
        ya: 'bg-green-500/15 border-green-500/40',
        amb: 'bg-yellow-500/15 border-yellow-500/40',
        sin: 'bg-blue-500/15 border-blue-500/40',
        info: 'bg-blue-500/15 border-blue-500/40',
        error: 'bg-red-500/15 border-red-500/40',
    };

    return (
        <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
            <div className={`w-full max-w-md rounded-xl border p-8 text-center shadow-2xl ${estilos[vista.tipo] || 'border-zinc-800'}`}>
                <img src="/imgs/logo.png" alt="Urban Box" className="h-14 w-auto object-contain mx-auto mb-4" />
                {vista.tipo === 'cargando' ? (
                    <>
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto" />
                        <p className="mt-4 text-zinc-300">Registrando tu asistencia…</p>
                    </>
                ) : (
                    <>
                        <h1 className="text-2xl font-bold text-white mb-2">{vista.titulo}</h1>
                        <p className="text-zinc-300 mb-6">{vista.mensaje}</p>
                        <button
                            onClick={() => navigate('/alumno/dashboard')}
                            className="px-6 py-2 bg-orange-500 text-white rounded-lg text-sm font-bold hover:bg-orange-600 transition-colors"
                        >
                            Ir a mi panel
                        </button>
                    </>
                )}
            </div>
        </div>
    );
};

export default AsistenciaQr;
