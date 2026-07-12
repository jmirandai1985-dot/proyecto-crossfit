import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const SolicitarPlan = () => {
    const { usuario_id, tenant_id } = useAuth();

    // ─── Estados ───────────────────────────────────────────────────────
    const [planes, setPlanes] = useState([]);
    const [planesFiltrados, setPlanesFiltrados] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [sexoAlumno, setSexoAlumno] = useState(null);
    const [sinSexo, setSinSexo] = useState(false);
    const [categoriaSeleccionada, setCategoriaSeleccionada] = useState(null);

    // Flujo: paso 1 = elegir plan, paso 2 = datos pago, paso 3 = confirmación
    const [paso, setPaso] = useState(1);
    const [planSeleccionado, setPlanSeleccionado] = useState(null);
    const [archivoVoucher, setArchivoVoucher] = useState(null);
    const [archivoCertificado, setArchivoCertificado] = useState(null);
    const [subiendo, setSubiendo] = useState(false);
    const [mensajeExito, setMensajeExito] = useState('');
    const [mensajeError, setMensajeError] = useState('');

    // ─── Cargar perfil del alumno y planes ─────────────────────────────
    useEffect(() => {
        const fetchData = async () => {
            setLoading(true);
            setError('');
            try {
                const perfilRes = await api.get(`/api/v1/usuarios/${usuario_id}`);
                const perfil = perfilRes.data;
                const sexo = perfil?.genero || null;
                setSexoAlumno(sexo);
                setSinSexo(!sexo);

                const res = await api.get(`/api/v1/planes?tenant_id=${tenant_id}&activo=true`);
                const data = res.data?.planes || res.data || [];
                const todosLosPlanes = Array.isArray(data) ? data : [];
                setPlanes(todosLosPlanes);

                const categoriaInicial = sexo === 'M' ? 'masculino' : sexo === 'F' ? 'femenino' : null;
                setCategoriaSeleccionada(categoriaInicial);
            } catch (err) {
                console.error('Error cargando datos:', err);
                setError('No se pudieron cargar los planes disponibles.');
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [usuario_id, tenant_id]);

    // ─── Filtrar planes cuando cambia la categoría ──────────────────
    useEffect(() => {
        if (categoriaSeleccionada) {
            setPlanesFiltrados(planes.filter(p => !p.genero || p.genero === categoriaSeleccionada));
        } else {
            setPlanesFiltrados(planes);
        }
    }, [categoriaSeleccionada, planes]);

    // Separar planes regulares y de estudiante
    const planesRegulares = planesFiltrados.filter(p => !p.requiere_certificado_estudiante);
    const planesEstudiante = planesFiltrados.filter(p => p.requiere_certificado_estudiante);

    const handleSeleccionarPlan = (plan) => {
        setPlanSeleccionado(plan);
        setPaso(2);
        setMensajeError('');
    };

    const handleEnviarSolicitud = async () => {
        if (!archivoVoucher) {
            setMensajeError('Debes seleccionar un comprobante de pago.');
            return;
        }
        if (planSeleccionado?.requiere_certificado_estudiante && !archivoCertificado) {
            setMensajeError('Este plan requiere un certificado de estudiante. Debes subirlo.');
            return;
        }
        if (!planSeleccionado) return;

        setSubiendo(true);
        setMensajeError('');
        try {
            // 1. Subir voucher
            const formDataVoucher = new FormData();
            formDataVoucher.append('file', archivoVoucher);
            const uploadVoucherRes = await api.post('/api/v1/upload/voucher', formDataVoucher, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            const voucherUrl = uploadVoucherRes.data?.url || uploadVoucherRes.data?.voucher_url || '';

            // 2. Subir certificado (si es necesario)
            let certificadoUrl = '';
            if (planSeleccionado?.requiere_certificado_estudiante && archivoCertificado) {
                const formDataCert = new FormData();
                formDataCert.append('file', archivoCertificado);
                const uploadCertRes = await api.post('/api/v1/upload/voucher', formDataCert, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                });
                certificadoUrl = uploadCertRes.data?.url || uploadCertRes.data?.voucher_url || '';
            }

            // 3. Enviar solicitud
            await api.post('/api/v1/solicitudes/solicitar', {
                tenant_id,
                alumno_id: usuario_id,
                plan_id: planSeleccionado.id,
                voucher_url: voucherUrl,
                certificado_estudiante_url: certificadoUrl || null,
            });

            setPaso(3);
            setMensajeExito('✅ Tu solicitud fue enviada, espera la aprobación del administrador.');
        } catch (err) {
            console.error('Error al enviar solicitud:', err);
            const detalle = err.response?.data?.detail || 'Error al procesar la solicitud. Intenta nuevamente.';
            setMensajeError(detalle);
        } finally {
            setSubiendo(false);
        }
    };

    const formatearPrecio = (precio) => {
        if (!precio) return '—';
        return '$' + precio.toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    };

    const renderPlanCard = (plan) => (
        <button
            key={plan.id}
            onClick={() => handleSeleccionarPlan(plan)}
            className="bg-white rounded-xl border-2 border-gray-200 p-6 shadow-sm hover:border-emerald-400 hover:shadow-md transition-all text-left group"
        >
            <div className="flex items-center gap-2 mb-3">
                <span className="text-2xl">🏅</span>
                <h3 className="text-lg font-bold text-gray-800 group-hover:text-emerald-600 transition-colors">
                    {plan.nombre}
                </h3>
            </div>
            <p className="text-3xl font-bold text-emerald-600 mb-4">
                {formatearPrecio(plan.precio_clp)}
            </p>
            <div className="space-y-2 text-sm text-gray-600">
                <div className="flex items-center gap-2">
                    <span className="text-emerald-500">✅</span>
                    <span>
                        {plan.es_ilimitado
                            ? '♾️ Clases ilimitadas'
                            : `📊 ${plan.creditos || plan.clases_por_mes || '—'} créditos`}
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-emerald-500">✅</span>
                    <span>📆 Duración: {plan.duracion_dias || 30} días</span>
                </div>
                {plan.requiere_certificado_estudiante && (
                    <div className="flex items-center gap-2 mt-2">
                        <span className="text-amber-500">🎓</span>
                        <span className="text-amber-700 font-semibold">Plan Estudiante</span>
                    </div>
                )}
                {plan.descripcion && (
                    <p className="text-gray-400 italic mt-2 text-xs">{plan.descripcion}</p>
                )}
            </div>
            <div className="mt-5 text-center">
                <span className="inline-block px-6 py-2 bg-emerald-500 text-white rounded-lg text-sm font-bold group-hover:bg-emerald-600 transition-colors">
                    Seleccionar
                </span>
            </div>
        </button>
    );

    // ─── Loading ───────────────────────────────────────────────────────
    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500 mx-auto mb-4"></div>
                        <p className="text-gray-500">Cargando planes disponibles...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">

                {/* ─── TÍTULO ─────────────────────────────────────── */}
                <div className="flex items-center gap-3">
                    <span className="text-3xl">💳</span>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Solicitar Plan</h1>
                        <p className="text-sm text-gray-500">Elige el plan que mejor se adapte a ti</p>
                    </div>
                </div>

                {/* ─── ERROR GENERAL ───────────────────────────────── */}
                {error && (
                    <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 font-medium text-sm">
                        ❌ {error}
                    </div>
                )}

                {/* ─── AVISO: SIN SEXO CARGADO ────────────────────── */}
                {paso === 1 && sinSexo && (
                    <div className="p-5 rounded-xl bg-amber-50 border border-amber-200 text-amber-800">
                        <div className="flex items-center gap-3">
                            <span className="text-2xl">⚠️</span>
                            <div>
                                <p className="font-bold text-sm">Completa tu sexo en Ajustes</p>
                                <p className="text-xs text-amber-600 mt-1">
                                    Para sugerirte planes según tu perfil, indica tu sexo en Ajustes.
                                    Mientras tanto, puedes explorar todas las categorías.
                                </p>
                                <a href="/alumno/ajustes" className="inline-block mt-2 text-xs font-bold text-amber-700 underline hover:text-amber-800">
                                    Ir a Ajustes →
                                </a>
                            </div>
                        </div>
                    </div>
                )}

                {/* ══════════════════════════════════════════════════════
                    PASO 1: ELEGIR PLAN
                    ══════════════════════════════════════════════════════ */}
                {paso === 1 && (
                    <>
                        {/* ─── TOGGLE: FEMENINO / MASCULINO / TODOS ── */}
                        <div className="flex gap-2 p-1 bg-gray-100 rounded-xl w-fit mx-auto">
                            <button onClick={() => setCategoriaSeleccionada('femenino')}
                                className={`px-6 py-2.5 rounded-lg text-sm font-bold transition-all ${categoriaSeleccionada === 'femenino'
                                    ? 'bg-pink-500 text-white shadow-md'
                                    : 'text-gray-600 hover:bg-pink-50 hover:text-pink-600'}`}>
                                ♀️ Femeninos
                            </button>
                            <button onClick={() => setCategoriaSeleccionada('masculino')}
                                className={`px-6 py-2.5 rounded-lg text-sm font-bold transition-all ${categoriaSeleccionada === 'masculino'
                                    ? 'bg-blue-500 text-white shadow-md'
                                    : 'text-gray-600 hover:bg-blue-50 hover:text-blue-600'}`}>
                                ♂️ Masculinos
                            </button>
                            <button onClick={() => setCategoriaSeleccionada(null)}
                                className={`px-6 py-2.5 rounded-lg text-sm font-bold transition-all ${categoriaSeleccionada === null
                                    ? 'bg-gray-500 text-white shadow-md'
                                    : 'text-gray-600 hover:bg-gray-200'}`}>
                                Todos
                            </button>
                        </div>

                        {planesRegulares.length === 0 && planesEstudiante.length === 0 && (
                            <div className="col-span-full text-center py-12">
                                <p className="text-gray-400 text-lg mb-2">📋 No hay planes disponibles</p>
                                <p className="text-gray-400 text-sm">Prueba seleccionando otra categoría arriba</p>
                            </div>
                        )}

                        {/* ─── PLANES REGULARES ───────────────────── */}
                        {planesRegulares.length > 0 && (
                            <div>
                                <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-2">
                                    <span>⭐</span> PLANES REGULARES
                                </h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                                    {planesRegulares.map(renderPlanCard)}
                                </div>
                            </div>
                        )}

                        {/* ─── PLANES PARA ESTUDIANTES ────────────── */}
                        {planesEstudiante.length > 0 && (
                            <div className="mt-6">
                                <h3 className="text-sm font-bold text-amber-600 uppercase tracking-wider mb-3 flex items-center gap-2">
                                    <span>🎓</span> PLANES PARA ESTUDIANTES
                                </h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                                    {planesEstudiante.map(renderPlanCard)}
                                </div>
                            </div>
                        )}
                    </>
                )}

                {/* ══════════════════════════════════════════════════════
                    PASO 2: DATOS DE PAGO Y VOUCHER
                    ══════════════════════════════════════════════════════ */}
                {paso === 2 && planSeleccionado && (
                    <div className="space-y-6">
                        {/* Resumen del plan seleccionado */}
                        <div className="bg-emerald-50 rounded-xl border border-emerald-200 p-5">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs text-emerald-600 uppercase tracking-wider font-semibold">Plan seleccionado</p>
                                    <h3 className="text-xl font-bold text-gray-800">{planSeleccionado.nombre}</h3>
                                </div>
                                <span className="text-2xl font-bold text-emerald-600">
                                    {formatearPrecio(planSeleccionado.precio_clp)}
                                </span>
                            </div>
                        </div>

                        {/* ─── SUBIR VOUCHER DE PAGO ──────────────── */}
                        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                            <h4 className="font-bold text-gray-800 mb-3 flex items-center gap-2">
                                <span>📎</span> Subir Comprobante de Pago
                            </h4>
                            <p className="text-xs text-gray-500 mb-4">
                                Formatos aceptados: imagen (JPG, PNG) o PDF. Máximo 5 MB.
                            </p>
                            <div className="border-2 border-dashed border-gray-300 rounded-xl p-6 text-center hover:border-emerald-400 transition-colors">
                                <input type="file" id="voucher-upload" accept="image/*,application/pdf"
                                    onChange={(e) => setArchivoVoucher(e.target.files[0] || null)} className="hidden" />
                                <label htmlFor="voucher-upload" className="cursor-pointer">
                                    <span className="text-4xl block mb-2">{archivoVoucher ? '📄' : '📤'}</span>
                                    {archivoVoucher ? (
                                        <div>
                                            <p className="text-sm font-medium text-emerald-600">{archivoVoucher.name}</p>
                                            <p className="text-xs text-gray-400 mt-1">{(archivoVoucher.size / 1024 / 1024).toFixed(2)} MB</p>
                                            <p className="text-xs text-emerald-500 mt-2">Haz clic para cambiar archivo</p>
                                        </div>
                                    ) : (
                                        <div>
                                            <p className="text-sm font-medium text-gray-600">Haz clic para seleccionar el comprobante</p>
                                            <p className="text-xs text-gray-400 mt-1">o arrastra el archivo aquí</p>
                                        </div>
                                    )}
                                </label>
                            </div>
                        </div>

                        {/* ─── SUBIR CERTIFICADO ESTUDIANTE (solo si aplica) ── */}
                        {planSeleccionado.requiere_certificado_estudiante && (
                            <div className="bg-amber-50 rounded-xl border border-amber-200 p-5 shadow-sm">
                                <h4 className="font-bold text-amber-800 mb-3 flex items-center gap-2">
                                    <span>🎓</span> Certificado de Estudiante
                                </h4>
                                <p className="text-xs text-amber-600 mb-4">
                                    Este plan requiere que acredites tu condición de estudiante.
                                    Sube tu carnet de alumno, certificado de matrícula o cualquier documento que lo acredite.
                                    Formatos: imagen (JPG, PNG) o PDF. Máximo 5 MB.
                                </p>
                                <div className="border-2 border-dashed border-amber-300 rounded-xl p-6 text-center hover:border-amber-500 transition-colors bg-white">
                                    <input type="file" id="certificado-upload" accept="image/*,application/pdf"
                                        onChange={(e) => setArchivoCertificado(e.target.files[0] || null)} className="hidden" />
                                    <label htmlFor="certificado-upload" className="cursor-pointer">
                                        <span className="text-4xl block mb-2">{archivoCertificado ? '📄' : '🎓'}</span>
                                        {archivoCertificado ? (
                                            <div>
                                                <p className="text-sm font-medium text-amber-700">{archivoCertificado.name}</p>
                                                <p className="text-xs text-amber-500 mt-1">{(archivoCertificado.size / 1024 / 1024).toFixed(2)} MB</p>
                                                <p className="text-xs text-amber-600 mt-2">Haz clic para cambiar archivo</p>
                                            </div>
                                        ) : (
                                            <div>
                                                <p className="text-sm font-medium text-amber-700">Haz clic para subir tu certificado</p>
                                                <p className="text-xs text-amber-500 mt-1">Carnet, matrícula o documento similar</p>
                                            </div>
                                        )}
                                    </label>
                                </div>
                            </div>
                        )}

                        {mensajeError && (
                            <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 font-medium text-sm">
                                ❌ {mensajeError}
                            </div>
                        )}

                        <div className="flex gap-4 pt-2">
                            <button type="button"
                                onClick={() => { setPaso(1); setPlanSeleccionado(null); setMensajeError(''); }}
                                className="px-6 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm transition-colors"
                                disabled={subiendo}>
                                ← Volver
                            </button>
                            <button type="button"
                                onClick={handleEnviarSolicitud}
                                disabled={subiendo || !archivoVoucher || (planSeleccionado.requiere_certificado_estudiante && !archivoCertificado)}
                                className="flex-1 px-6 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                {subiendo ? 'Enviando solicitud...' : '✅ Enviar Solicitud'}
                            </button>
                        </div>
                    </div>
                )}

                {/* ══════════════════════════════════════════════════════
                    PASO 3: CONFIRMACIÓN
                    ══════════════════════════════════════════════════════ */}
                {paso === 3 && (
                    <div className="text-center py-12">
                        <div className="text-6xl mb-6">✅</div>
                        <h2 className="text-2xl font-bold text-gray-800 mb-3">¡Solicitud Enviada!</h2>
                        <p className="text-gray-600 mb-8 max-w-md mx-auto">{mensajeExito}</p>
                        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 max-w-md mx-auto text-left text-sm text-gray-700 space-y-2">
                            <p className="font-semibold text-emerald-800">📋 ¿Qué sigue?</p>
                            <p>1. El administrador revisará tu solicitud y comprobante.</p>
                            <p>2. Una vez aprobado, tu plan se activará automáticamente.</p>
                            <p>3. Recibirás una notificación cuando esté listo.</p>
                            <p className="text-xs text-gray-400 italic mt-2">Este proceso puede tomar hasta 24 horas hábiles.</p>
                        </div>
                        <a href="/alumno/dashboard"
                            className="inline-block mt-8 px-8 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors">
                            Volver al Inicio
                        </a>
                    </div>
                )}

            </div>
        </Layout>
    );
};

export default SolicitarPlan;