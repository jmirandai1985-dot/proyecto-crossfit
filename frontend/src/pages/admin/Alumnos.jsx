import React, { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import { useNavigate, useSearchParams } from 'react-router-dom';
import AlumnoFichaModal from '../../components/AlumnoFichaModal';
import { fmtFechaChile, sumarDiasInstante } from '../../utils/fecha';
import {
    SIN_DATOS, useAlumnosPaginados, useBeneficiosAlumno, useCrearSuscripcion,
    useDesactivarUsuario, useGuardarUsuario, usePlanesActivos,
    useSuscripcionesActivas, useSuscripcionesAlumno,
} from '../../hooks/queries';
// Las reglas del padrón (¿la suscripción está vigente HOY?, badge del estado, params del
// listado paginado, tramos de la paginación) viven en `utils/alumnos`: las comparte la
// tabla de escritorio con la vista móvil del padrón (A5) y no pueden divergir.
import {
    badgeEstado, nombrePlan, paginaFueraDeRango, paginaValida, rangoMostrado,
    suscripcionDeAlumno, suscripcionVigente,
} from '../../utils/alumnos';

const Alumnos = () => {
    const { tenant_id } = useAuth();
    const [searchTerm, setSearchTerm] = useState('');
    // Lo que viaja al backend es ESTE término (debounce de 350 ms): una request por
    // tecla haría parpadear la tabla y contaría de más al servidor.
    const [busqueda, setBusqueda] = useState('');
    // PAGINACION REAL: el endpoint acepta limit/skip y devuelve el total (sin paginar)
    // en el header X-Total-Count. La busqueda tambien es server-side (`buscar`) porque
    // con paginacion, filtrar en el cliente solo alcanzaria la pagina actual.
    const [porPagina, setPorPagina] = useState(25);
    const [pagina, setPagina] = useState(1);
    const [showModal, setShowModal] = useState(false);
    const [showVoucherModal, setShowVoucherModal] = useState(false);
    const [selectedAlumnoVoucher, setSelectedAlumnoVoucher] = useState(null);
    // Plan VIGENTE del alumno (si lo tiene) cuando se abre el comprobante: el
    // modal lo muestra y exige confirmación antes de crear una SEGUNDA
    // suscripción activa sobre la que ya tiene.
    const [planVigenteAlumno, setPlanVigenteAlumno] = useState(null);
    const [confirmarDuplicado, setConfirmarDuplicado] = useState(false);
    const [planSeleccionado, setPlanSeleccionado] = useState('');
    const [mensajeAprobacion, setMensajeAprobacion] = useState('');
    const [editingAlumno, setEditingAlumno] = useState(null);
    const [fichaAlumnoId, setFichaAlumnoId] = useState(null);
    const [searchParams, setSearchParams] = useSearchParams();
    // Navegación al Historial del alumno (`/admin/alumnos/:id/historial`).
    const navigate = useNavigate();

    // ── Datos (React Query) ─────────────────────────────────────────────────────
    // El padrón paginado: la página, el tamaño y el término de búsqueda van en la CLAVE
    // de la consulta, así que cambiar de página o buscar es un DATO más, no un efecto
    // que vuelva a pedir a mano. `placeholderData` deja la tabla anterior en pantalla
    // mientras llega la nueva (sin parpadeo).
    const { data: datos, isPending: cargandoAlumnos } = useAlumnosPaginados({
        porPagina, pagina, buscar: busqueda,
    });
    const alumnos = datos?.lista ?? SIN_DATOS;
    const totalAlumnos = datos?.total ?? 0;

    // Planes ACTIVOS del box: los comparten la tabla (columna Plan Activo), el
    // comprobante (select + precio) y el resto del panel (`usePlanesActivos`).
    const { data: planesData } = usePlanesActivos();
    const planes = planesData ?? SIN_DATOS;

    // Suscripciones ACTIVAS del box: de acá salen "Plan Activo" y los créditos de la fila.
    const { data: suscripcionesData } = useSuscripcionesActivas();
    const suscripciones = suscripcionesData ?? SIN_DATOS;

    // ─── F2: el estado de beneficios del alumno que se está aprobando ──
    // Trae el descuento vigente y el precio final de cada plan (lo calcula el backend): el panel
    // avisa ANTES de asignar y precarga lo que hay que cobrar.
    const planIds = planes.map((p) => p.id).join(',');
    const { data: beneficioData } = useBeneficiosAlumno(selectedAlumnoVoucher?.id, planIds);
    const beneficioAlumno = beneficioData ?? null;

    // Suscripciones del alumno del comprobante: alimenta el aviso de plan ya vigente.
    const { data: suscripcionesAlumnoData } = useSuscripcionesAlumno(selectedAlumnoVoucher?.id);

    // ── Mutaciones ──────────────────────────────────────────────────────────────
    // Crear/editar y dar de baja invalidan `['usuarios']`, así que la tabla se refresca
    // sola: ya no hace falta el `await fetchAlumnos()` que remataba cada acción.
    const guardarUsuario = useGuardarUsuario();
    const desactivarUsuario = useDesactivarUsuario();
    const crearSuscripcion = useCrearSuscripcion();

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

    // El término de búsqueda viaja al backend con un retardo de 350 ms (y sin retardo al
    // vaciar la caja): la misma espera de antes, ahora sin volver a pedir la tabla a mano.
    useEffect(() => {
        const timer = setTimeout(() => setBusqueda(searchTerm.trim()), searchTerm ? 350 : 0);
        return () => clearTimeout(timer);
    }, [searchTerm]);

    // Si la página pedida quedó FUERA DE RANGO (se borró el último de la última, o la
    // búsqueda encogió el total) se retrocede al último tramo válido en vez de mostrar una
    // tabla vacía: la misma regla que tenía el fetch manual, disparada cuando llega el total
    // del servidor. Sin datos (cargando o error) no se toca la página que eligió el admin.
    useEffect(() => {
        if (!datos || !paginaFueraDeRango(pagina, datos.total, porPagina)) return;
        setPagina(paginaValida(pagina, datos.total, porPagina));
    }, [datos, pagina, porPagina]);

    // ¿El alumno del comprobante ya tiene un plan ACTIVO? Se consulta al ABRIR el modal (no
    // al aprobar) para avisar y pedir confirmación antes de crear una SEGUNDA suscripción
    // activa sobre una vigente (doble cobro / doble plan). Best-effort: si la consulta falla
    // no se setea nada y el modal sigue igual (no se bloquea la aprobación).
    useEffect(() => {
        if (!selectedAlumnoVoucher) return;
        const vigente = suscripcionVigente(suscripcionesAlumnoData);
        if (!vigente) return;
        setPlanVigenteAlumno({
            plan_nombre: nombrePlan(planes, vigente.plan_id),
            fecha_expiracion: vigente.fecha_expiracion,
        });
    }, [suscripcionesAlumnoData, selectedAlumnoVoucher, planes]);

    /** Plan elegido en la aprobación del pago (o `undefined`). */
    const planElegido = planes.find((p) => p.id === parseInt(planSeleccionado));

    /** Desglose del descuento para un plan (o `null`): lo calcula el backend. */
    const precioConBeneficio = (plan) =>
        beneficioAlumno?.precios?.[String(plan?.id)] || null;

    // La busqueda y el total los resuelve el backend (server-side): el tramo que muestra el
    // pie lo calcula `rangoMostrado` (misma fórmula de siempre, cubierta por `test:alumnos`).
    const { totalPaginas, desde, hasta } = rangoMostrado({
        total: totalAlumnos, porPagina, pagina, enPagina: alumnos.length,
    });

    // La suscripción de una fila: mismo criterio (y mismo badge) que la vista móvil.
    const getSuscripcionAlumno = (alumnoId) => suscripcionDeAlumno(suscripciones, alumnoId);

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
        setPlanVigenteAlumno(null);
        setConfirmarDuplicado(false);
        setShowVoucherModal(true);
        // El "¿ya tiene un plan ACTIVO?" lo resuelve la consulta `useSuscripcionesAlumno`
        // (arranca al quedar puesto `selectedAlumnoVoucher`) y lo aplica el efecto de
        // arriba, que además deja el aviso listo antes de que el admin pueda aprobar.
    };

    const closeVoucherModal = () => {
        setShowVoucherModal(false);
        setSelectedAlumnoVoucher(null);
        setPlanVigenteAlumno(null);
        setConfirmarDuplicado(false);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        // Un solo hook para las dos caras del formulario: con `id` es PUT (editar) y sin
        // `id` es el alta. La mutación invalida `['usuarios']`, así que el padrón se
        // refresca solo (antes cada rama terminaba con un `await fetchAlumnos()`).
        const payload = editingAlumno
            ? {
                nombre: formData.nombre,
                correo: formData.correo,
                telefono: formData.telefono,
                // `estado` es la fuente de verdad: se manda él y el backend deriva `activo`.
                estado: formData.estado === 'activo' ? 'activo' : 'baja',
            }
            : {
                nombre: formData.nombre,
                correo: formData.correo,
                telefono: formData.telefono,
                password: formData.password,
                rol: formData.rol,
                rut: formData.rut,
                tenant_id: tenant_id,
            };
        try {
            await guardarUsuario.mutateAsync({ id: editingAlumno?.id, payload });
            closeModal();
        } catch (error) {
            console.error('Error al guardar usuario:', error);
            alert((editingAlumno ? 'Error al actualizar: ' : 'Error al crear usuario: ')
                + (error.response?.data?.detail || 'Intenta nuevamente'));
        }
    };

    const handleDelete = async (alumno) => {
        if (!window.confirm(`¿Estás seguro de eliminar a ${alumno.nombre}?`)) return;
        try {
            // La baja invalida `['usuarios']`: el servidor vuelve a mandar el padrón y con
            // el total recalculado (filtrar en el cliente dejaría el pie "Mostrando A-B de
            // N" mintiendo y la página con una fila de menos).
            await desactivarUsuario.mutateAsync(alumno.id);
        } catch (error) {
            console.error('Error al eliminar alumno:', error);
            alert('Error al eliminar: ' + (error.response?.data?.detail || 'Intenta nuevamente'));
        }
    };

    // La primera carga del padrón: mismo spinner que antes, pero sólo mientras no haya
    // NINGUNA página en caché (al cambiar de página se sigue viendo la tabla anterior).
    if (cargandoAlumnos) {
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
                                                    // El nombre del plan lo resuelve `nombrePlan` (utils/alumnos), igual que la vista móvil.
                                                    return <span className="px-2 py-1 bg-blue-500/20 text-blue-300 rounded-full text-xs font-medium">{nombrePlan(planes, sus.plan_id)}</span>;
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
                                {planVigenteAlumno && (
                                    <div className="bg-amber-500/10 border-l-4 border-amber-500 rounded p-4 text-sm text-amber-200"
                                        data-testid="aviso-plan-vigente">
                                        ⚠️ Este alumno ya tiene el plan{' '}
                                        <span className="font-bold">{planVigenteAlumno.plan_nombre}</span>{' '}
                                        vigente hasta el {fmtFechaChile(planVigenteAlumno.fecha_expiracion)}.
                                        <p className="text-xs mt-1 text-amber-300/80">
                                            ¿Crear otro de todas formas? Se creará una SEGUNDA suscripción
                                            activa sobre la que ya tiene.
                                        </p>
                                        <label className="mt-3 flex items-center gap-2 cursor-pointer text-amber-100">
                                            <input
                                                type="checkbox"
                                                checked={confirmarDuplicado}
                                                onChange={(e) => setConfirmarDuplicado(e.target.checked)}
                                                data-testid="confirmar-plan-duplicado"
                                            />
                                            Sí, crear una nueva suscripción de todas formas
                                        </label>
                                    </div>
                                )}
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
                                        disabled={crearSuscripcion.isPending || (planVigenteAlumno && !confirmarDuplicado)}
                                        onClick={async () => {
                                            if (!planSeleccionado) { setMensajeAprobacion('Debes seleccionar un plan antes de aprobar.'); return; }
                                            if (planVigenteAlumno && !confirmarDuplicado) { setMensajeAprobacion('El alumno ya tiene un plan vigente: marca la confirmación para crear otra suscripción.'); return; }
                                            setMensajeAprobacion('');
                                            try {
                                                const plan = planes.find((p) => p.id === parseInt(planSeleccionado));
                                                // Duracion exacta desde el instante del alta: el vencimiento cae el mismo
                                                // dia chileno N dias despues (sin aritmetica de calendario del navegador).
                                                const fechaInicio = new Date();
                                                const fechaExpiracion = sumarDiasInstante(fechaInicio, plan?.duracion_dias || 30);
                                                await crearSuscripcion.mutateAsync({
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
                                            }
                                        }}
                                        className="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        {crearSuscripcion.isPending ? 'Aprobando...' : 'Aprobar Pago'}
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