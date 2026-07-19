import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const Alumnos = () => {
    const { tenant_id } = useAuth();
    const [alumnos, setAlumnos] = useState([]);
    const [searchTerm, setSearchTerm] = useState('');
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [showVoucherModal, setShowVoucherModal] = useState(false);
    const [selectedAlumnoVoucher, setSelectedAlumnoVoucher] = useState(null);
    const [planes, setPlanes] = useState([]);
    const [planSeleccionado, setPlanSeleccionado] = useState('');
    const [aprobandoPago, setAprobandoPago] = useState(false);
    const [mensajeAprobacion, setMensajeAprobacion] = useState('');
    const [suscripciones, setSuscripciones] = useState([]);
    const [editingAlumno, setEditingAlumno] = useState(null);
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
            const response = await api.get(`/api/v1/usuarios?rol=alumno&tenant_id=${tenant_id}&activo=true`);
            setAlumnos(response.data || []);
        } catch (error) {
            console.error('Error fetching alumnos:', error);
            setAlumnos([]);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAlumnos();
    }, [tenant_id]);

    useEffect(() => {
        const fetchSuscripciones = async () => {
            try {
                const response = await api.get(`/api/v1/suscripciones?tenant_id=${tenant_id}&estado=activo`);
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
                const response = await api.get(`/api/v1/planes?tenant_id=${tenant_id}&activo=true`);
                setPlanes(response.data || []);
            } catch (error) {
                console.error('Error fetching planes:', error);
            }
        };
        fetchPlanes();
    }, [tenant_id]);

    const filteredAlumnos = alumnos.filter((alumno) =>
        (alumno.nombre || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
        (alumno.correo || '').toLowerCase().includes(searchTerm.toLowerCase())
    );

    const getSuscripcionAlumno = (alumnoId) => {
        return suscripciones.find(s => s.usuario_id === alumnoId) || null;
    };

    const openModal = (alumno = null, rolFijo = 'alumno') => {
        if (alumno) {
            setEditingAlumno(alumno);
            setFormData({
                nombre: alumno.nombre,
                correo: alumno.correo,
                telefono: alumno.telefono,
                estado: alumno.activo ? 'activo' : 'inactivo',
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
                    estado: formData.estado,
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
            await api.post('/api/v1/usuarios', {
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
            setAlumnos(alumnos.filter((a) => a.id !== alumno.id));
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
                        <p className="text-gray-600">Cargando alumnos...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">Gestión de Alumnos</h1>
                    <p className="text-gray-600 mt-1">Administra los miembros de tu box</p>
                </div>

                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-gray-200">
                        <div className="flex items-center justify-between">
                            <h2 className="text-lg font-bold text-gray-900">Lista de Alumnos</h2>
                            <button
                                onClick={() => openModal(null, 'coach')}
                                className="px-4 py-2 bg-blue-900 text-white rounded-lg hover:bg-blue-800 transition-colors font-medium text-sm ml-2"
                            >
                                + Nuevo Coach
                            </button>
                        </div>
                    </div>

                    <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
                        <input
                            type="text"
                            placeholder="Buscar por nombre o correo..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
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
                            <tbody className="divide-y divide-gray-200">
                                {filteredAlumnos.length > 0 ? (
                                    filteredAlumnos.map((alumno, index) => (
                                        <tr key={alumno.id} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                            <td className="px-6 py-4 text-sm font-medium text-gray-900">{alumno.nombre}</td>
                                            <td className="px-6 py-4 text-sm text-gray-600">{alumno.correo}</td>
                                            <td className="px-6 py-4 text-sm text-gray-600">{alumno.telefono}</td>
                                            <td className="px-6 py-4 text-sm">
                                                <span className={`px-3 py-1 rounded-full text-xs font-medium ${alumno.activo ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                                    {alumno.activo ? 'activo' : 'inactivo'}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-600">{alumno.fechaRegistro}</td>
                                            <td className="px-6 py-4 text-sm text-gray-600">
                                                {(() => {
                                                    const sus = getSuscripcionAlumno(alumno.id);
                                                    if (!sus) return <span className="text-gray-400">Sin plan</span>;
                                                    const plan = planes.find(p => p.id === sus.plan_id);
                                                    return <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">{plan ? plan.nombre : `Plan ID ${sus.plan_id}`}</span>;
                                                })()}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-600">
                                                {(() => {
                                                    const sus = getSuscripcionAlumno(alumno.id);
                                                    if (!sus) return <span className="text-gray-400">—</span>;
                                                    if (sus.creditos_disponibles === null) return <span className="font-bold text-orange-500">∞</span>;
                                                    return <span className="font-bold text-gray-900">{sus.creditos_disponibles}</span>;
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
                                                    onClick={() => openModal(alumno)}
                                                    className="px-3 py-1 text-blue-600 hover:bg-blue-50 rounded transition-colors text-xs font-medium"
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
                                        <td colSpan="8" className="px-6 py-8 text-center text-gray-600">
                                            No se encontraron alumnos
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>

                    <div className="px-6 py-4 bg-gray-50 border-t border-gray-200">
                        <p className="text-sm text-gray-600">
                            Total de alumnos: <span className="font-bold text-gray-900">{filteredAlumnos.length}</span>
                        </p>
                    </div>
                </div>

                {showModal && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                        <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
                            <div className="bg-blue-900 text-white px-6 py-4 rounded-t-lg">
                                <h2 className="text-xl font-bold">{editingAlumno ? 'Editar Alumno' : (formData.rol === 'coach' ? 'Nuevo Coach' : 'Nuevo Alumno')}</h2>
                            </div>
                            <form onSubmit={handleSubmit} className="p-6 space-y-4">
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Nombre Completo</label>
                                    <input type="text" value={formData.nombre} onChange={(e) => setFormData({ ...formData, nombre: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">RUT</label>
                                    <input type="text" value={formData.rut} onChange={(e) => setFormData({ ...formData, rut: e.target.value })} placeholder="12345678-9" className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Correo Electrónico</label>
                                    <input type="email" value={formData.correo} onChange={(e) => setFormData({ ...formData, correo: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Teléfono</label>
                                    <input type="tel" value={formData.telefono} onChange={(e) => setFormData({ ...formData, telefono: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                {!editingAlumno && (
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Contraseña</label>
                                        <input type="password" value={formData.password} onChange={(e) => setFormData({ ...formData, password: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                    </div>
                                )}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Estado</label>
                                    <select value={formData.estado} onChange={(e) => setFormData({ ...formData, estado: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500">
                                        <option value="activo">Activo</option>
                                        <option value="inactivo">Inactivo</option>
                                    </select>
                                </div>
                                <div className="flex gap-3 pt-4">
                                    <button type="button" onClick={closeModal} className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-medium">Cancelar</button>
                                    <button type="submit" className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium">{editingAlumno ? 'Actualizar' : 'Crear'}</button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}

                {showVoucherModal && selectedAlumnoVoucher && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                        <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full">
                            <div className="bg-purple-600 text-white px-6 py-4 rounded-t-lg flex items-center justify-between">
                                <h2 className="text-xl font-bold">Comprobante de Pago</h2>
                                <button onClick={closeVoucherModal} className="text-white hover:text-gray-200 text-2xl">×</button>
                            </div>
                            <div className="p-6 space-y-6">
                                <div className="bg-gray-50 p-4 rounded-lg">
                                    <h3 className="text-sm font-semibold text-gray-700 mb-3">Información del Alumno</h3>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div><p className="text-xs text-gray-500">Nombre</p><p className="text-sm font-medium text-gray-900">{selectedAlumnoVoucher.nombre}</p></div>
                                        <div><p className="text-xs text-gray-500">Correo</p><p className="text-sm font-medium text-gray-900">{selectedAlumnoVoucher.correo}</p></div>
                                        <div><p className="text-xs text-gray-500">Teléfono</p><p className="text-sm font-medium text-gray-900">{selectedAlumnoVoucher.telefono}</p></div>
                                        <div><p className="text-xs text-gray-500">Fecha Registro</p><p className="text-sm font-medium text-gray-900">{selectedAlumnoVoucher.fechaRegistro}</p></div>
                                    </div>
                                </div>
                                <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center bg-gray-50">
                                    <div className="text-6xl mb-4">📋</div>
                                    <h4 className="text-lg font-semibold text-gray-900 mb-2">Comprobante de Pago</h4>
                                    <p className="text-sm text-gray-600 mb-4">Transacción ID: <span className="font-mono font-bold">TXN-{selectedAlumnoVoucher.id}-2026</span></p>
                                    <div className="bg-white p-4 rounded border border-gray-200 mb-4">
                                        <p className="text-xs text-gray-500 mb-2">Monto Pagado</p>
                                        <p className="text-2xl font-bold text-green-600">$49.990</p>
                                        <p className="text-xs text-gray-500 mt-2">Membresía Mensual</p>
                                    </div>
                                    <p className="text-xs text-gray-500">Fecha de Pago: {new Date().toLocaleDateString('es-CL')}</p>
                                </div>
                                <div className="flex items-center gap-3 p-4 bg-green-50 border border-green-200 rounded-lg">
                                    <span className="text-2xl">✓</span>
                                    <div>
                                        <p className="text-sm font-semibold text-green-800">Pago Verificado</p>
                                        <p className="text-xs text-green-700">El comprobante ha sido validado correctamente</p>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Seleccionar Plan</label>
                                    <select value={planSeleccionado} onChange={(e) => setPlanSeleccionado(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500">
                                        <option value="">-- Elige un plan --</option>
                                        {planes.map((p) => (
                                            <option key={p.id} value={p.id}>{p.nombre} — ${p.precio_clp?.toLocaleString('es-CL')} / {p.duracion_dias} días</option>
                                        ))}
                                    </select>
                                </div>
                                {mensajeAprobacion && (
                                    <p className={`text-sm font-medium ${mensajeAprobacion.startsWith('✅') ? 'text-green-700' : 'text-red-600'}`}>
                                        {mensajeAprobacion}
                                    </p>
                                )}
                                <div className="flex gap-3 pt-4">
                                    <button onClick={closeVoucherModal} className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-medium">Cerrar</button>
                                    <button
                                        disabled={aprobandoPago}
                                        onClick={async () => {
                                            if (!planSeleccionado) { setMensajeAprobacion('Debes seleccionar un plan antes de aprobar.'); return; }
                                            setAprobandoPago(true);
                                            setMensajeAprobacion('');
                                            try {
                                                const plan = planes.find((p) => p.id === parseInt(planSeleccionado));
                                                const fechaInicio = new Date();
                                                const fechaExpiracion = new Date();
                                                fechaExpiracion.setDate(fechaInicio.getDate() + (plan?.duracion_dias || 30));
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
        </Layout>
    );
};

export default Alumnos;