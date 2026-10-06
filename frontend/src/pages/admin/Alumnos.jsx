import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { useNavigate, useSearchParams } from 'react-router-dom';
import AlumnoFichaModal from '../../components/AlumnoFichaModal';
import { fmtFechaChile, sumarDiasInstante } from '../../utils/fecha';

const Alumnos = () => {
    const { tenant_id } = useAuth();
    const [alumnos, setAlumnos] = useState([]);
    const [searchTerm, setSearchTerm] = useState('');
    // PAGINACION REAL: el endpoint acepta limit/skip y devuelve el total (sin paginar)
    // en el header X-Total-Count. La busqueda tambien es server-side (`buscar`) porque
    // con paginacion, filtrar en el cliente solo alcanzaria la pagina actual.
    const [porPagina, setPorPagina] = useState(25);
    const [pagina, setPagina] = useState(1);
    const [totalAlumnos, setTotalAlumnos] = useState(0);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [showVoucherModal, setShowVoucherModal] = useState(false);
    const [selectedAlumnoVoucher, setSelectedAlumnoVoucher] = useState(null);
    const [planes, setPlanes] = useState([]);
    const [planSeleccionado, setPlanSeleccionado] = useState('');
    const [aprobandoPago, setAprobandoPago] = useState(false);
    const [mensajeAprobacion, setMensajeAprobacion] = useState('');
    const [suscripciones, setSuscripciones] = useState([]);
    // ─── F2: el estado de beneficios del alumno que se está aprobando ──
    // Trae el descuento vigente y el precio final de cada plan (lo calcula el backend): el panel
    // avisa ANTES de asignar y precarga lo que hay que cobrar.
    const [beneficioAlumno, setBeneficioAlumno] = useState(null);
    const [editingAlumno, setEditingAlumno] = useState(null);
    const [fichaAlumnoId, setFichaAlumnoId] = useState(null);
    const [searchParams, setSearchParams] = useSearchParams();
    // Navegación al Historial del alumno (`/admin/alumnos/:id/historial`).
    const navigate = useNavigate();

    // ?alumno_id=<id>: deep-link desde Notificaciones -> abre la ficha de ESE
    // alumno. AlumnoFichaModal se auto-carga por API, asi que no depende de que
    // el alumno este en la lista. Al cerrar se limpia el param (si no, un cambio
    // de filtro lo volveria a abrir).
    useEffect(() => {
        const id = Number(searchParams.get('alumno_id'));
        if (Number.isFinite(id) && id > 0) setFichaAlumnoId(id);
    }, [searchParams]);

    const [formData, setFormData] = useState({
        nombre: '',
        correo: '',
        telefono: '',
        password: '',
        rol: 'alumno',
        rut: '',
        estado: 'activo',
    });

    const fetchAlumnos = async () => {
        try {
            const response = await api.get('/api/v1/usuarios/', {
                params: {
                    rol: 'alumno',
                    limit: porPagina,
                    skip: (pagina - 1) * porPagina,
                    buscar: searchTerm.trim() || undefined,
                },
            });
            const lista = response.data || [];
            const total = Number(response.headers?.['x-total-count'] ?? 0);
            // Si la pagina pedida quedo FUERA DE RANGO (p. ej. borraste el ultimo de
            // la ultima pagina, o el patron de busqueda encogio el total) se
            // retrocede al ultimo tramo valido en vez de mostrar una tabla vacia.
            const paginasServidor = Math.max(1, Math.ceil(total / porPagina));
            if (pagina > paginasServidor) {
                setPagina(paginasServidor);
                return;
            }
            setAlumnos(lista);
            setTotalAlumnos(total);
        } catch (error) {
            console.error('Error fetching alumnos:', error);
            setAlumnos([]);
            setTotalAlumnos(0);
        } finally {
            setLoading(false);
        }
    };

    // Refetch al cambiar de pagina o al buscar (debounce de 350ms en la busqueda
    // para no disparar una request por tecla).
    useEffect(() => {
        const timer = setTimeout(fetchAlumnos, searchTerm ? 350 : 0);
        return () => clearTimeout(timer);
    }, [tenant_id, pagina, searchTerm, porPagina]);

    useEffect(() => {
        const fetchSuscripciones = async () => {
            try {
                const response = await api.get(`/api/v1/suscripciones?estado=activo`);
                setSuscripciones(response.data || []);
            } catch (error) {
                console.error('Error fetching suscripciones:', error);
            }
        };
        fetchSuscripciones();
    }, [tenant_id]);

    useEffect(() => {
        const fetchPlanes = async () => {
            try {
                const response = await api.get(`/api/v1/planes?activo=true`);
                setPlanes(response.data || []);
            } catch (error) {
                console.error('Error fetching planes:', error);
            }
        };
        fetchPlanes();
    }, [tenant_id]);

    // ─── F2: beneficios del alumno cuando se abre la aprobación del pago ───────────────
    // Se piden los precios de TODOS los planes de una vez (con el descuento del alumno puesto):
    // el aviso y el precio precargado salen del backend, no de una cuenta del navegador.
    useEffect(() => {
        const traerBeneficios = async () => {
            if (!selectedAlumnoVoucher?.id || planes.length === 0) {
                setBeneficioAlumno(null);
                return;
            }
            try {
                const { data } = await api.get(
                    `/api/v1/beneficios/alumno/${selectedAlumnoVoucher.id}`,
                    { params: { plan_ids: planes.map((p) => p.id).join(',') } },
                );
                setBeneficioAlumno(data);
            } catch {
                // Sin esta info el panel sigue igual (sin aviso): no se cae la aprobación.
                setBeneficioAlumno(null);
            }
        };
        traerBeneficios();
    }, [selectedAlumnoVoucher, planes]);

    /** Plan elegido en la aprobación del pago (o `undefined`). */
    const planElegido = planes.find((p) => p.id === parseInt(planSeleccionado));

    /** Desglose del descuento para un plan (o `null`): lo calcula el backend. */
    const precioConBeneficio = (plan) =>
        beneficioAlumno?.precios?.[String(plan?.id)] || null;

    // La busqueda y el total los resuelve el backend (server-side).
    const totalPaginas = Math.max(1, Math.ceil(totalAlumnos / porPagina));
    const desde = totalAlumnos === 0 ? 0 : (pagina - 1) * porPagina + 1;
    const hasta = (pagina - 1) * porPagina + alumnos.length;

    // Badge del estado REAL del registro. `estado` es la fuente de verdad (el flag
    // `activo` es derivado y el backend garantiza que no se desincronicen).
    const badgeEstado = (u) => {
        const est = u.estado || (u.activo ? 'activo' : 'baja');
        return {
            texto: est === 'pendiente_activacion' ? 'pendiente' : est,
            clase: est === 'activo' ? 'bg-green-100 text-green-800'
                : est === 'pendiente_activacion' ? 'bg-amber-100 text-amber-800'
                    : est === 'rechazado' ? 'bg-red-100 text-red-800'
                        : 'bg-zinc-700 text-zinc-300',
        };
    };

    const getSuscripcionAlumno = (alumnoId) => {
        return suscripciones.find(s => s.usuario_id === alumnoId) || null;
    };

    // Formato de fecha es-CL usado en toda la tabla (created_at viene del API).
    const fmtFecha = (v) => {
        if (!v) return '—';
        // Fecha del calendario CHILENO (no la del navegador).
        return fmtFechaChile(v) || v;
    };

    const openModal = (alumno = null, rolFijo = 'alumno') => {
        if (alumno) {
            setEditingAlumno(alumno);
            setFormData({
                nombre: alumno.nombre,
                correo: alumno.correo,
                telefono: alumno.telefono,
                estado: (alumno.estado === 'activo' || (!alumno.estado && alumno.activo)) ? 'activo' : 'inactivo',
            });
        } else {
            setEditingAlumno(null);
            setFormData({ nombre: '', correo: '', telefono: '', password: '', rol: rolFijo, rut: '', estado: 'activo' });
        }
        setShowModal(true);
    };

    const closeModal = () => {
        setShowModal(false);
        setEditingAlumno(null);
        setFormData({ nombre: '', correo: '', telefono: '', password: '', rol: 'alumno', rut: '', estado: 'activo' });
    };

    const openVoucherModal = (alumno) => {
        setSelectedAlumnoVoucher(alumno);
        setPlanSeleccionado('');
        setMensajeAprobacion('');
        setShowVoucherModal(true);
    };

    const closeVoucherModal = () => {
        setShowVoucherModal(false);
        setSelectedAlumnoVoucher(null);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (editingAlumno) {
            try {
                await api.put(`/api/v1/usuarios/${editingAlumno.id}`, {
                    nombre: formData.nombre,
                    correo: formData.correo,
                    telefono: formData.telefono,
                    // `estado` es la fuente de verdad: se manda él y el backend deriva `activo`.
                    estado: formData.estado === 'activo' ? 'activo' : 'baja',
                });
                await fetchAlumnos();
                closeModal();
            } catch (error) {
                console.error('Error al actualizar usuario:', error);
                alert('Error al actualizar: ' + (error.response?.data?.detail || 'Intenta nuevamente'));
            }
            return;
        }
        try {
            await api.post('/api/v1/usuarios/', {
                nombre: formData.nombre,
                correo: formData.correo,
                telefono: formData.telefono,
                password: formData.password,
                rol: formData.rol,
                rut: formData.rut,
                tenant_id: tenant_id,
            });
            await fetchAlumnos();
            closeModal();
        } catch (error) {
            console.error('Error al crear usuario:', error);
            alert('Error al crear usuario: ' + (error.response?.data?.detail || 'Intenta nuevamente'));
        }
    };

    const handleDelete = async (alumno) => {
        if (!window.confirm(`¿Estás seguro de eliminar a ${alumno.nombre}?`)) return;
        try {
            await api.delete(`/api/v1/usuarios/${alumno.id}`);
            // Refetch (no un filtro local): el total del padron y el tramo
            // "Mostrando A-B de N" los manda el servidor; filtrar en el cliente
            // dejaria el pie mintiendo y la pagina con una fila de menos.
            await fetchAlumnos();
        } catch (error) {
            console.error('Error al eliminar alumno:', error);
            alert('Error al eliminar: ' + (error.response?.data?.detail || 'Intenta nuevamente'));
        }
    };

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4"></div>
                        <p className="text-zinc-400">Cargando alumnos...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div>
                    <h1 className="text-3xl font-bold text-zinc-100">Gestión de Alumnos</h1>
                    <p className="text-zinc-400 mt-1">Administra los miembros de tu box</p>
                </div>

                <div className="bg-zinc-900 rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-zinc-800">
                        <div className="flex items-center justify-between">
                            <h2 className="text-lg font-bold text-zinc-100">Lista de Alumnos</h2>
                            <div className="flex gap-2">
                                <button
                                    onClick={() => openModal()}
                                    className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium text-sm"
                                >
                                    + Nuevo Alumno
                                </button>
                                <button
                                    onClick={() => openModal(null, 'coach')}
                                    className="px-4 py-2 bg-blue-900 text-white rounded-lg hover:bg-blue-800 transition-colors font-medium text-sm"
                                >
                                    + Nuevo Coach
                                </button>
                            </div>
                        </div>
                    </div>

                    <div className="px-6 py-4 bg-zinc-800/50 border-b border-zinc-800">
                        <input
                            type="text"
                            placeholder="Buscar por nombre o correo..."
                            value={searchTerm}
                            onChange={(e) => { setSearchTerm(e.target.value); setPagina(1); }}
                            className="w-full px-4 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                        />
                    </div>

                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-blue-900 text-white">
                                <tr>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Nombre</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Correo</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Teléfono</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Estado</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Fecha Registro</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Plan Activo</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Créditos</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-800">
                                {alumnos.length > 0 ? (
                                    alumnos.map((alumno, index) => (
                                        <tr key={alumno.id} className={index % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                            <td className="px-6 py-4 text-sm font-medium text-zinc-100">{alumno.nombre}</td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">{alumno.correo}</td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">{alumno.telefono}</td>
                                            <td className="px-6 py-4 text-sm">
                                                <span className={`px-3 py-1 rounded-full text-xs font-medium ${badgeEstado(alumno).clase}`}>
                                                    {badgeEstado(alumno).texto}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">{fmtFecha(alumno.created_at)}</td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">
                                                {(() => {
                                                    const sus = getSuscripcionAlumno(alumno.id);
                                                    if (!sus) return <span className="text-zinc-500">Sin plan</span>;
                                                    const plan = planes.find(p => p.id === sus.plan_id);
                                                    return <span className="px-2 py-1 bg-blue-500/20 text-blue-300 rounded-full text-xs font-medium">{plan ? plan.nombre : `Plan ID ${sus.plan_id}`}</span>;
                                                })()}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">
                                                {(() => {
                                                    const sus = getSuscripcionAlumno(alumno.id);
                                                    if (!sus) return <span className="text-zinc-500">—</span>;
                                                    if (sus.creditos_disponibles === null) return <span className="font-bold text-orange-500">∞</span>;
                                                    return <span className="font-bold text-zinc-100">{sus.creditos_disponibles}</span>;
                                                })()}
                                            </td>
                                            <td className="px-6 py-4 text-sm space-x-2">
                                                <button
                                                    onClick={() => openVoucherModal(alumno)}
                                                    className="px-3 py-1 text-purple-600 hover:bg-purple-50 rounded transition-colors text-xs font-medium"
                                                >
                                                    📄 Voucher
                                                </button>
                                                <button
                                                    onClick={() => setFichaAlumnoId(alumno.id)}
                                                    className="px-3 py-1 text-emerald-400 hover:bg-zinc-800 rounded transition-colors text-xs font-medium"
                                                >
                                                    👤 Ficha
                                                </button>
                                                <button
                                                    onClick={() => navigate(`/admin/alumnos/${alumno.id}/historial`)}
                                                    data-testid={`btn-historial-${alumno.id}`}
                                                    className="px-3 py-1 text-indigo-400 hover:bg-zinc-800 rounded transition-colors text-xs font-medium"
                                                >
                                                    📜 Historial
                                                </button>
                                                <button
                                                    onClick={() => openModal(alumno)}
                                                    className="px-3 py-1 text-blue-400 hover:bg-zinc-800 rounded transition-colors text-xs font-medium"
                                                >
                                                    Editar
                                                </button>
                                                <button
                                                    onClick={() => handleDelete(alumno)}
                                                    className="px-3 py-1 text-red-600 hover:bg-red-50 rounded transition-colors text-xs font-medium"
                                                >
                                                    Eliminar
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                ) : (
                                    <tr>
                                        <td colSpan="8" className="px-6 py-8 text-center text-zinc-400">
                                            No se encontraron alumnos
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>

                    <div className="px-6 py-4 bg-zinc-800/50 border-t border-zinc-800 flex items-center justify-between gap-4 flex-wrap">
                        <p className="text-sm text-zinc-400" data-testid="rango-alumnos">
                            {totalAlumnos === 0
                                ? 'Sin resultados'
                                : <>Mostrando <span className="font-bold text-zinc-100">{desde}-{hasta}</span> de <span className="font-bold text-zinc-100">{totalAlumnos}</span>{searchTerm ? ' (búsqueda)' : ' alumnos'}</>}
                        </p>
                        <div className="flex items-center gap-2">
                            <label className="flex items-center gap-1 text-sm text-zinc-400">
                                Por página
                                <select
                                    data-testid="por-pagina"
                                    value={porPagina}
                                    onChange={(e) => { setPorPagina(Number(e.target.value)); setPagina(1); }}
                                    className="px-2 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-200 text-sm"
                                >
                                    <option value={25}>25</option>
                                    <option value={50}>50</option>
                                    <option value={100}>100</option>
                                </select>
                            </label>
                            <button
                                data-testid="pagina-anterior"
                                onClick={() => setPagina(p => Math.max(1, p - 1))}
                                disabled={pagina <= 1}
                                className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
                            >◀ Anterior</button>
                            <span className="text-sm text-zinc-400">Página <span className="font-bold text-zinc-100">{pagina}</span> de {totalPaginas}</span>
                            <button
                                data-testid="pagina-siguiente"
                                onClick={() => setPagina(p => Math.min(totalPaginas, p + 1))}
                                disabled={pagina >= totalPaginas}
                                className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
                            >Siguiente ▶</button>
                        </div>
                    </div>
                </div>

                {showModal && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full">
                            <div className="bg-blue-900 text-white px-6 py-4 rounded-t-lg">
                                <h2 className="text-xl font-bold">{editingAlumno ? 'Editar Alumno' : (formData.rol === 'coach' ? 'Nuevo Coach' : 'Nuevo Alumno')}</h2>
                            </div>
                            <form onSubmit={handleSubmit} className="p-6 space-y-4">
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Nombre Completo</label>
                                    <input type="text" value={formData.nombre} onChange={(e) => setFormData({ ...formData, nombre: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">RUT</label>
                                    <input type="text" value={formData.rut} onChange={(e) => setFormData({ ...formData, rut: e.target.value })} placeholder="12345678-9" className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Correo Electrónico</label>
                                    <input type="email" value={formData.correo} onChange={(e) => setFormData({ ...formData, correo: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Teléfono</label>
                                    <input type="tel" value={formData.telefono} onChange={(e) => setFormData({ ...formData, telefono: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                {!editingAlumno && (
                                    <div>
                                        <label className="block text-sm font-medium text-zinc-300 mb-1">Contraseña</label>
                                        <input type="password" value={formData.password} onChange={(e) => setFormData({ ...formData, password: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                    </div>
                                )}
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Estado</label>
                                    <select value={formData.estado} onChange={(e) => setFormData({ ...formData, estado: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500">
                                        <option value="activo">Activo</option>
                                        <option value="inactivo">Inactivo</option>
                                    </select>
                                </div>
                                <div className="flex gap-3 pt-4">
                                    <button type="button" onClick={closeModal} className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 transition-colors font-medium">Cancelar</button>
                                    <button type="submit" className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium">{editingAlumno ? 'Actualizar' : 'Crear'}</button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}

                {showVoucherModal && selectedAlumnoVoucher && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-2xl w-full">
                            <div className="bg-purple-600 text-white px-6 py-4 rounded-t-lg flex items-center justify-between">
                                <h2 className="text-xl font-bold">Comprobante de Pago</h2>
                                <button onClick={closeVoucherModal} className="text-white hover:text-gray-200 text-2xl">×</button>
                            </div>
                            <div className="p-6 space-y-6">
                                <div className="bg-zinc-800/50 p-4 rounded-lg">
                                    <h3 className="text-sm font-semibold text-zinc-300 mb-3">Información del Alumno</h3>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div><p className="text-xs text-zinc-400">Nombre</p><p className="text-sm font-medium text-zinc-100">{selectedAlumnoVoucher.nombre}</p></div>
                                        <div><p className="text-xs text-zinc-400">Correo</p><p className="text-sm font-medium text-zinc-100">{selectedAlumnoVoucher.correo}</p></div>
                                        <div><p className="text-xs text-zinc-400">Teléfono</p><p className="text-sm font-medium text-zinc-100">{selectedAlumnoVoucher.telefono}</p></div>
                                        <div><p className="text-xs text-zinc-400">Fecha Registro</p><p className="text-sm font-medium text-zinc-100">{fmtFecha(selectedAlumnoVoucher.created_at)}</p></div>
                                    </div>
                                </div>
                                <div className="border-2 border-dashed border-zinc-700 rounded-lg p-8 text-center bg-zinc-800/50">
                                    <div className="text-6xl mb-4">📋</div>
                                    <h4 className="text-lg font-semibold text-zinc-100 mb-2">Comprobante de Pago</h4>
                                    <p className="text-sm text-zinc-400 mb-4">Transacción ID: <span className="font-mono font-bold">TXN-{selectedAlumnoVoucher.id}-2026</span></p>
                                    <div className="bg-zinc-900 p-4 rounded border border-zinc-800 mb-4">
                                        <p className="text-xs text-zinc-400 mb-2">Monto Pagado</p>
                                        <p className="text-2xl font-bold text-green-600">$49.990</p>
                                        <p className="text-xs text-zinc-400 mt-2">Membresía Mensual</p>
                                    </div>
                                    <p className="text-xs text-zinc-400">Fecha de Pago: {fmtFechaChile(new Date())}</p>
                                </div>
                                <div className="flex items-center gap-3 p-4 bg-green-50 border border-green-200 rounded-lg">
                                    <span className="text-2xl">✓</span>
                                    <div>
                                        <p className="text-sm font-semibold text-green-800">Pago Verificado</p>
                                        <p className="text-xs text-green-700">El comprobante ha sido validado correctamente</p>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Seleccionar Plan</label>
                                    <select value={planSeleccionado} onChange={(e) => setPlanSeleccionado(e.target.value)} className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500">
                                        <option value="">-- Elige un plan --</option>
                                        {planes.map((p) => (
                                            <option key={p.id} value={p.id}>{p.nombre} — ${p.precio_clp?.toLocaleString('es-CL')} / {p.duracion_dias} días</option>
                                        ))}
                                    </select>
                                </div>
                                {planElegido && (
                                    <p className="text-sm text-zinc-300" data-testid="precio-precargado">
                                        Precio a cobrar:{' '}
                                        <span className="font-bold text-white">
                                            ${(precioConBeneficio(planElegido)?.precio_final_clp
                                                ?? planElegido.precio_clp ?? 0).toLocaleString('es-CL')}
                                        </span>
                                        {precioConBeneficio(planElegido) && (
                                            <span className="ml-2 text-xs text-zinc-500 line-through">
                                                ${(planElegido.precio_clp || 0).toLocaleString('es-CL')}
                                            </span>
                                        )}
                                    </p>
                                )}
                                {beneficioAlumno?.descuento_pct && (
                                    <div className="bg-amber-500/10 border-l-4 border-amber-500 rounded p-3 text-sm text-amber-200"
                                        data-testid="aviso-beneficio-alumno">
                                        🎁 Este alumno tiene un −{beneficioAlumno.descuento_pct} % de
                                        descuento vigente hasta el {fmtFechaChile(beneficioAlumno.descuento_hasta)}.
                                        <span className="block text-xs mt-1 text-amber-300/80">
                                            El descuento lo aplica el sistema cuando él solicita su plan
                                            desde la app: acá se muestra para cobrar el precio correcto.
                                        </span>
                                    </div>
                                )}
                                {mensajeAprobacion && (
                                    <p className={`text-sm font-medium ${mensajeAprobacion.startsWith('✅') ? 'text-green-700' : 'text-red-600'}`}>
                                        {mensajeAprobacion}
                                    </p>
                                )}
                                <div className="flex gap-3 pt-4">
                                    <button onClick={closeVoucherModal} className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 transition-colors font-medium">Cerrar</button>
                                    <button
                                        disabled={aprobandoPago}
                                        onClick={async () => {
                                            if (!planSeleccionado) { setMensajeAprobacion('Debes seleccionar un plan antes de aprobar.'); return; }
                                            setAprobandoPago(true);
                                            setMensajeAprobacion('');
                                            try {
                                                const plan = planes.find((p) => p.id === parseInt(planSeleccionado));
                                                // Duracion exacta desde el instante del alta: el vencimiento cae el mismo
                                                // dia chileno N dias despues (sin aritmetica de calendario del navegador).
                                                const fechaInicio = new Date();
                                                const fechaExpiracion = sumarDiasInstante(fechaInicio, plan?.duracion_dias || 30);
                                                await api.post('/api/v1/suscripciones', {
                                                    tenant_id: tenant_id,
                                                    usuario_id: selectedAlumnoVoucher.id,
                                                    plan_id: parseInt(planSeleccionado),
                                                    fecha_inicio: fechaInicio.toISOString(),
                                                    fecha_expiracion: fechaExpiracion.toISOString(),
                                                    estado: 'activo',
                                                    creditos_totales: plan?.es_ilimitado ? null : (plan?.creditos || null),
                                                    creditos_disponibles: plan?.es_ilimitado ? null : (plan?.creditos || null),
                                                });
                                                setMensajeAprobacion('✅ Suscripción creada correctamente.');
                                                setTimeout(() => closeVoucherModal(), 1500);
                                            } catch (error) {
                                                console.error('Error al crear suscripción:', error);
                                                setMensajeAprobacion('Error al crear la suscripción. Intenta nuevamente.');
                                            } finally {
                                                setAprobandoPago(false);
                                            }
                                        }}
                                        className="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        {aprobandoPago ? 'Aprobando...' : 'Aprobar Pago'}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* MODAL FICHA ALUMNO */}
            {fichaAlumnoId && (
                <AlumnoFichaModal
                    alumnoId={fichaAlumnoId}
                    tenantId={tenant_id}
                    onVerHistorial={() => navigate(`/admin/alumnos/${fichaAlumnoId}/historial`)}
                    onClose={() => {
                        setFichaAlumnoId(null);
                        // Limpia el deep-link para no re-abrir la ficha.
                        const next = new URLSearchParams(searchParams);
                        next.delete('alumno_id');
                        setSearchParams(next);
                    }}
                />
            )}
        </Layout>
    );
};

export default Alumnos;