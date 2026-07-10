import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const DashboardCoach = () => {
    const navigate = useNavigate();
    const { usuario_id, tenant_id, usuario } = useAuth();
    const [activeTab, setActiveTab] = useState('resumen');

    // Data states
    const [clasesHoy, setClasesHoy] = useState([]);
    const [clasesSemana, setClasesSemana] = useState([]);
    const [alumnos, setAlumnos] = useState([]);
    const [alumnosEnRiesgo, setAlumnosEnRiesgo] = useState([]);
    const [wods, setWods] = useState([]);
    const [wodHoy, setWodHoy] = useState(null);
    const [movimientos, setMovimientos] = useState([]);
    const [registrosRecientes, setRegistrosRecientes] = useState([]);
    const [progresoAlumnos, setProgresoAlumnos] = useState([]);

    // UI states
    const [loading, setLoading] = useState(true);
    const [selectedAlumno, setSelectedAlumno] = useState(null);
    const [alumnoRMs, setAlumnoRMs] = useState([]);
    const [searchTerm, setSearchTerm] = useState('');

    // WOD creation modal
    const [showWodModal, setShowWodModal] = useState(false);
    const [editingWodId, setEditingWodId] = useState(null);
    const [wodForm, setWodForm] = useState({
        titulo: '',
        descripcion: '',
        estado: 'draft',
        coach_id: usuario_id,
        movimientos: []
    });
    const [wodMovimientos, setWodMovimientos] = useState([]);
    const [saving, setSaving] = useState(false);
    const [deleteConfirmWodId, setDeleteConfirmWodId] = useState(null);

    // ---- Helper: Fechas ----
    const toLocalDateStr = (d) => {
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    const today = toLocalDateStr(new Date());

    const getWeekRange = () => {
        const now = new Date();
        const startOfWeek = new Date(now);
        const day = now.getDay();
        const diff = day === 0 ? 6 : day - 1;
        startOfWeek.setDate(now.getDate() - diff);
        const endOfWeek = new Date(startOfWeek);
        endOfWeek.setDate(startOfWeek.getDate() + 6);
        return {
            start: toLocalDateStr(startOfWeek),
            end: toLocalDateStr(endOfWeek)
        };
    };

    const weekRange = getWeekRange();

    // Days of week (Monday–Sunday)
    const DAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
    const getDayDates = () => {
        const start = new Date(weekRange.start + 'T12:00:00');
        return DAYS.map((_, i) => {
            const d = new Date(start);
            d.setDate(start.getDate() + i);
            return toLocalDateStr(d);
        });
    };
    const dayDates = getDayDates();

    // Fixed schedule times
    const SCHEDULE_HOURS = [
        '06:00', '07:00', '08:00', '09:00', '10:00', '11:00',
        '15:00', '16:00', '17:00', '18:00', '19:00', '20:00', '21:00'
    ];

    // -- Build week grid data --
    const buildWeekGrid = () => {
        const grid = {};
        // Initialize all cells
        dayDates.forEach(date => {
            grid[date] = {};
            SCHEDULE_HOURS.forEach(hour => {
                grid[date][hour] = null;
            });
        });
        // Fill with actual classes
        (clasesSemana || []).forEach(clase => {
            const fechaStr = clase.fecha ? (typeof clase.fecha === 'string' ? clase.fecha.split('T')[0] : clase.fecha) : '';
            const horaInicio = clase.hora_inicio ? clase.hora_inicio.substring(0, 5) : '';
            if (grid[fechaStr] && grid[fechaStr][horaInicio] !== undefined) {
                grid[fechaStr][horaInicio] = clase;
            }
        });
        return grid;
    };
    const weekGrid = buildWeekGrid();

    // ---- Cargar datos ----
    const fetchAllData = useCallback(async () => {
        setLoading(true);
        try {
            const [clasesRes, alumnosRes, wodsRes, riesgoRes, movRes] = await Promise.all([
                api.get(`/api/v1/clases?coach_id=${usuario_id}&tenant_id=${tenant_id}`),
                api.get(`/api/v1/usuarios?tenant_id=${tenant_id}&rol=alumno&activo=true`),
                api.get(`/api/v1/wods?tenant_id=${tenant_id}`),
                api.get(`/api/v1/fidelizacion/coach/${usuario_id}/en-riesgo?tenant_id=${tenant_id}`),
                api.get(`/api/v1/movimientos?tenant_id=${tenant_id}`)
            ]);

            const clasesData = clasesRes.data || [];
            const alumnosData = alumnosRes.data || [];
            const wodsData = wodsRes.data || [];
            const riesgoData = riesgoRes.data?.alumnos_alerta || [];
            const movimientosData = movRes.data || [];

            setAlumnos(alumnosData);
            setAlumnosEnRiesgo(riesgoData);
            setWods(wodsData);
            setMovimientos(movimientosData);

            // Filter today's classes
            const hoyClases = clasesData.filter(c => {
                const fechaStr = c.fecha ? (typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha) : '';
                return fechaStr === today;
            });
            setClasesHoy(hoyClases);

            // Filter week classes
            const semanaClases = clasesData.filter(c => {
                const fechaStr = c.fecha ? (typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha) : '';
                return fechaStr >= weekRange.start && fechaStr <= weekRange.end;
            });
            semanaClases.sort((a, b) => {
                if (a.fecha < b.fecha) return -1;
                if (a.fecha > b.fecha) return 1;
                return (a.hora_inicio || '').localeCompare(b.hora_inicio || '');
            });
            setClasesSemana(semanaClases);

            // WOD of today
            const wodActual = wodsData.find(w => {
                const fechaWod = w.fecha ? (typeof w.fecha === 'string' ? w.fecha.split('T')[0] : w.fecha) : '';
                return fechaWod === today && w.activo !== false;
            });
            setWodHoy(wodActual || null);

            await calcularProgresoAlumnos(alumnosData, wodsData);
            await fetchRegistrosRecientes(wodsData);
        } catch (error) {
            console.error('Error fetching dashboard data:', error);
        }
        setLoading(false);
    }, [usuario_id, tenant_id, today, weekRange.start, weekRange.end]);

    const calcularProgresoAlumnos = async (alumnosData, wodsData) => {
        const progreso = [];
        for (const alumno of alumnosData.slice(0, 50)) {
            try {
                const rmsRes = await api.get(`/api/v1/historial-rm/alumnos/${alumno.id}/rms?tenant_id=${tenant_id}`);
                const rms = rmsRes.data || [];
                const totalRMs = rms.length;
                progreso.push({
                    id: alumno.id,
                    nombre: alumno.nombre,
                    correo: alumno.correo,
                    telefono: alumno.telefono,
                    total_rms: totalRMs,
                    rms: rms,
                    estado: totalRMs >= 5 ? 'activo' : totalRMs > 0 ? 'iniciando' : 'sin_datos'
                });
            } catch {
                progreso.push({
                    id: alumno.id,
                    nombre: alumno.nombre,
                    correo: alumno.correo,
                    telefono: alumno.telefono,
                    total_rms: 0,
                    rms: [],
                    estado: 'sin_datos'
                });
            }
        }
        setProgresoAlumnos(progreso);
    };

    const fetchRegistrosRecientes = async (wodsData) => {
        const fuenteWods = wodsData || wods;
        try {
            const wodsRecientes = [...fuenteWods].sort((a, b) => {
                const dateA = new Date(a.fecha || 0);
                const dateB = new Date(b.fecha || 0);
                return dateB - dateA;
            }).slice(0, 5).map(w => ({
                tipo: 'wod',
                titulo: w.titulo || 'WOD',
                fecha: w.fecha,
                estado: w.estado,
                id: w.id
            }));

            try {
                const rmsRes = await api.get(`/api/v1/historial-rm?tenant_id=${tenant_id}&limit=5`);
                const rmsData = rmsRes.data || [];
                const rmsRecientes = rmsData.map(r => ({
                    tipo: 'rm',
                    peso: r.peso_kg,
                    fecha: r.fecha,
                    alumno_id: r.alumno_id,
                    id: r.id
                }));

                const combinados = [...wodsRecientes, ...rmsRecientes];
                combinados.sort((a, b) => {
                    const dateA = new Date(a.fecha || 0);
                    const dateB = new Date(b.fecha || 0);
                    return dateB - dateA;
                });
                setRegistrosRecientes(combinados.slice(0, 10));
            } catch {
                setRegistrosRecientes(wodsRecientes);
            }
        } catch (error) {
            console.error('Error fetching registros recientes:', error);
        }
    };

    useEffect(() => {
        fetchAllData();
    }, [fetchAllData]);

    // ---- Alumno RMs ----
    useEffect(() => {
        if (selectedAlumno) {
            const fetchAlumnoRMs = async () => {
                setLoading(true);
                try {
                    const response = await api.get(`/api/v1/historial-rm/alumnos/${selectedAlumno.id}/rms?tenant_id=${tenant_id}`);
                    setAlumnoRMs(response.data || []);
                } catch (error) {
                    console.error('Error fetching alumno RMs:', error);
                    setAlumnoRMs([]);
                }
                setLoading(false);
            };
            fetchAlumnoRMs();
        }
    }, [selectedAlumno, tenant_id]);

    // ---- Handlers ----
    const handleMarcarAsistencia = (claseId) => {
        alert(`Asistencia marcada para clase ${claseId}`);
    };

    const handleContactar = (alumno) => {
        if (alumno.telefono) {
            const telefonoLimpio = alumno.telefono.replace(/\D/g, '');
            const telefonoConCodigo = telefonoLimpio.startsWith('56') ? telefonoLimpio : `56${telefonoLimpio}`;
            window.open(`https://wa.me/${telefonoConCodigo}`, '_blank');
        } else if (alumno.correo) {
            window.location.href = `mailto:${alumno.correo}`;
        } else {
            alert('Este alumno no tiene teléfono ni correo registrado.');
        }
    };

    const handleCrearWOD = async () => {
        if (!wodForm.titulo) {
            alert('Debes ingresar un título para el WOD');
            return;
        }
        setSaving(true);
        try {
            const payload = {
                ...wodForm,
                fecha: today,
                tenant_id: tenant_id,
                movimientos: wodMovimientos.map(m => ({
                    movimiento_id: m.movimiento_id,
                    orden: m.orden || 1,
                    series: m.series || 0,
                    repeticiones: m.repeticiones ? String(m.repeticiones) : null,
                    peso: m.peso || 0,
                    tiempo: m.tiempo || '',
                    notas: m.notas || ''
                }))
            };
            const response = await api.post(`/api/v1/wods?tenant_id=${tenant_id}`, payload);
            setWodHoy(response.data);
            setShowWodModal(false);
            setEditingWodId(null);
            setWodForm({ titulo: '', descripcion: '', estado: 'draft', coach_id: usuario_id, movimientos: [] });
            setWodMovimientos([]);
            fetchAllData();
        } catch (error) {
            console.error('Error creating WOD:', error);
            alert('Error al crear el WOD: ' + (error.response?.data?.detail || error.message));
        }
        setSaving(false);
    };

    // ---- Editar WOD ----
    const handleEditWod = async (wod) => {
        try {
            const res = await api.get(`/api/v1/wods/${wod.id}?tenant_id=${tenant_id}`);
            const wodData = res.data;
            setEditingWodId(wod.id);
            setWodForm({
                titulo: wodData.titulo || '',
                descripcion: wodData.descripcion || '',
                estado: wodData.estado || 'draft',
                coach_id: wodData.coach_id || usuario_id,
                movimientos: []
            });
            const movs = [];
            if (wodData.fases && wodData.fases.length > 0) {
                wodData.fases.forEach(fase => {
                    fase.movimientos.forEach((mov) => {
                        movs.push({
                            movimiento_id: mov.movimiento_id,
                            orden: movs.length + 1,
                            series: mov.series || 0,
                            repeticiones: mov.repeticiones || '',
                            peso: mov.peso || 0,
                            tiempo: mov.tiempo || '',
                            notas: mov.notas || ''
                        });
                    });
                });
            } else if (wodData.movimientos && wodData.movimientos.length > 0) {
                wodData.movimientos.forEach(mov => {
                    movs.push({
                        movimiento_id: mov.movimiento_id || mov.id,
                        orden: mov.orden || movs.length + 1,
                        series: mov.series || 0,
                        repeticiones: mov.repeticiones || '',
                        peso: mov.peso || 0,
                        tiempo: mov.tiempo || '',
                        notas: mov.notas || ''
                    });
                });
            }
            setWodMovimientos(movs);
            setShowWodModal(true);
        } catch (error) {
            console.error('Error fetching WOD for edit:', error);
            alert('Error al cargar el WOD para editar');
        }
    };

    // ---- Guardar Edición de WOD (FIXED 422 error) ----
    const handleUpdateWOD = async () => {
        if (!wodForm.titulo || !editingWodId) {
            alert('Debes ingresar un título para el WOD');
            return;
        }
        setSaving(true);
        try {
            const payload = {
                titulo: wodForm.titulo,
                descripcion: wodForm.descripcion,
                estado: wodForm.estado,
                movimientos: wodMovimientos
                    .filter(m => m.movimiento_id && Number(m.movimiento_id) > 0)
                    .map(m => ({
                        movimiento_id: Number(m.movimiento_id),
                        orden: Number(m.orden) || 1,
                        series: m.series ? Number(m.series) : null,
                        repeticiones: m.repeticiones ? String(m.repeticiones) : null,
                        peso: m.peso ? Number(m.peso) : null,
                        tiempo: m.tiempo || null,
                        notas: m.notas || null
                    }))
            };
            await api.put(`/api/v1/wods/${editingWodId}?tenant_id=${tenant_id}`, payload);
            setShowWodModal(false);
            setEditingWodId(null);
            setWodForm({ titulo: '', descripcion: '', estado: 'draft', coach_id: usuario_id, movimientos: [] });
            setWodMovimientos([]);
            fetchAllData();
        } catch (error) {
            console.error('Error updating WOD:', error);
            alert('Error al actualizar el WOD: ' + (error.response?.data?.detail || error.message));
        }
        setSaving(false);
    };

    // ---- Eliminar WOD ----
    const handleDeleteWod = async (wodId) => {
        setDeleteConfirmWodId(wodId);
    };

    const confirmDeleteWod = async () => {
        if (!deleteConfirmWodId) return;
        setSaving(true);
        try {
            await api.delete(`/api/v1/wods/${deleteConfirmWodId}?tenant_id=${tenant_id}`);
            setDeleteConfirmWodId(null);
            fetchAllData();
        } catch (error) {
            console.error('Error deleting WOD:', error);
            alert('Error al eliminar el WOD');
        }
        setSaving(false);
    };

    const handlePublicarWOD = async () => {
        if (!wodHoy) return;
        setSaving(true);
        try {
            await api.put(`/api/v1/wods/${wodHoy.id}?tenant_id=${tenant_id}`, {
                estado: 'publicado',
                titulo: wodHoy.titulo,
                descripcion: wodHoy.descripcion
            });
            setWodHoy({ ...wodHoy, estado: 'publicado' });
            fetchAllData();
        } catch (error) {
            console.error('Error publishing WOD:', error);
            alert('Error al publicar el WOD');
        }
        setSaving(false);
    };

    const addMovimientoToWod = () => {
        setWodMovimientos([...wodMovimientos, {
            movimiento_id: movimientos[0]?.id || '',
            orden: wodMovimientos.length + 1,
            series: 0,
            repeticiones: '',
            peso: 0,
            tiempo: '',
            notas: ''
        }]);
    };

    const updateWodMovimiento = (index, field, value) => {
        const updated = [...wodMovimientos];
        updated[index][field] = value;
        setWodMovimientos(updated);
    };

    const removeWodMovimiento = (index) => {
        setWodMovimientos(wodMovimientos.filter((_, i) => i !== index));
    };

    const filteredAlumnos = alumnos.filter((alumno) =>
        alumno.nombre.toLowerCase().includes(searchTerm.toLowerCase())
    );

    // ---- Stats ----
    const statsCards = [
        {
            titulo: 'Clases Hoy',
            valor: clasesHoy.length,
            icono: '📅',
            color: 'bg-blue-500',
            descripcion: `${clasesHoy.reduce((sum, c) => sum + (c.asistentes_confirmados || 0), 0)} asistentes totales`
        },
        {
            titulo: 'Alumnos Activos',
            valor: alumnos.length,
            icono: '👥',
            color: 'bg-green-500',
            descripcion: `${progresoAlumnos.filter(a => a.total_rms > 0).length} con RMs registrados`
        },
        {
            titulo: 'WOD del Día',
            valor: wodHoy ? (wodHoy.estado === 'publicado' ? 'Publicado' : 'Borrador') : 'Sin WOD',
            icono: '💪',
            color: wodHoy?.estado === 'publicado' ? 'bg-orange-500' : 'bg-gray-500',
            descripcion: wodHoy?.titulo || 'Crea el WOD de hoy'
        },
        {
            titulo: 'Alumnos en Riesgo',
            valor: alumnosEnRiesgo.length,
            icono: '⚠️',
            color: alumnosEnRiesgo.length > 0 ? 'bg-red-500' : 'bg-emerald-500',
            descripcion: alumnosEnRiesgo.length > 0 ? 'Requieren atención' : 'Todos activos'
        }
    ];

    const formatFecha = (fechaStr) => {
        if (!fechaStr) return '';
        const d = new Date(fechaStr + 'T12:00:00');
        const dias = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
        const meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
        return `${dias[d.getDay()]} ${d.getDate()} ${meses[d.getMonth()]}`;
    };

    const getEstadoColor = (estado) => {
        if (estado === 'publicado') return 'bg-green-100 text-green-800';
        if (estado === 'draft') return 'bg-yellow-100 text-yellow-800';
        return 'bg-gray-100 text-gray-800';
    };

    const getProgresoColor = (estado) => {
        if (estado === 'activo') return 'text-green-600 bg-green-50 border-green-300';
        if (estado === 'iniciando') return 'text-orange-600 bg-orange-50 border-orange-300';
        return 'text-gray-500 bg-gray-50 border-gray-200';
    };

    const getProgresoIcon = (estado) => {
        if (estado === 'activo') return '📈';
        if (estado === 'iniciando') return '🌱';
        return '❓';
    };

    if (loading && !clasesHoy.length) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-64">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto"></div>
                        <p className="mt-4 text-gray-600">Cargando dashboard...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                {/* Header */}
                <div className="flex flex-col md:flex-row md:items-center md:justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Dashboard Coach</h1>
                        <p className="text-gray-600 mt-1">Bienvenido, {usuario || 'Coach'} — {today}</p>
                    </div>
                    <div className="mt-4 md:mt-0 flex gap-2">
                        <button
                            onClick={() => navigate('/coach/pizarra')}
                            className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors text-sm font-medium flex items-center gap-2"
                        >
                            <span>➕</span> Crear WOD
                        </button>
                    </div>
                </div>

                {/* Stats Cards */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    {statsCards.map((stat, idx) => (
                        <div key={idx} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-shadow">
                            <div className="flex items-start justify-between">
                                <div>
                                    <p className="text-sm font-medium text-gray-500">{stat.titulo}</p>
                                    <p className="text-2xl font-bold text-gray-900 mt-1">{stat.valor}</p>
                                    <p className="text-xs text-gray-500 mt-1">{stat.descripcion}</p>
                                </div>
                                <div className={`${stat.color} w-12 h-12 rounded-lg flex items-center justify-center text-xl`}>
                                    {stat.icono}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>

                {/* Tabs (WOD tab eliminated, only "📋 Mis WODs" remains) */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
                    <div className="flex border-b border-gray-200 overflow-x-auto">
                        {[
                            { key: 'resumen', label: '📊 Resumen', icon: '📊' },
                            { key: 'clases', label: '📅 Clases', icon: '📅' },
                            { key: 'alumnos', label: '👥 Alumnos & RMs', icon: '👥' },
                            { key: 'progreso', label: '📈 Progreso', icon: '📈' },
                            { key: 'wods', label: '📋 Mis WODs', icon: '📋' },
                            { key: 'riesgo', label: '⚠️ Riesgo', icon: '⚠️' }
                        ].map(tab => (
                            <button
                                key={tab.key}
                                onClick={() => setActiveTab(tab.key)}
                                className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors ${activeTab === tab.key
                                    ? 'text-orange-500 border-b-2 border-orange-500 bg-orange-50/50'
                                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                                    }`}
                            >
                                {tab.label}
                            </button>
                        ))}
                    </div>

                    <div className="p-6">
                        {/* ─── TAB: RESUMEN ─── */}
                        {activeTab === 'resumen' && (
                            <div className="space-y-6">
                                {/* WOD del Día */}
                                <div className="bg-gradient-to-r from-orange-50 to-amber-50 rounded-xl p-6 border border-orange-200">
                                    <div className="flex items-start justify-between">
                                        <div>
                                            <h3 className="text-lg font-bold text-gray-900">💪 WOD del Día</h3>
                                            {wodHoy ? (
                                                <div className="mt-3">
                                                    <p className="text-xl font-bold text-gray-900">{wodHoy.titulo}</p>
                                                    <p className="text-sm text-gray-600 mt-1">{wodHoy.descripcion || 'Sin descripción'}</p>
                                                    <span className={`inline-block mt-2 px-2 py-1 text-xs font-medium rounded-full ${getEstadoColor(wodHoy.estado)}`}>
                                                        {wodHoy.estado === 'publicado' ? 'Publicado' : 'Borrador'}
                                                    </span>
                                                    {(wodHoy.fases && wodHoy.fases.length > 0) ? (
                                                        <div className="mt-3 space-y-2">
                                                            {wodHoy.fases.map(fase => (
                                                                <div key={fase.nombre} className="text-sm">
                                                                    <p className="font-bold text-orange-600 text-xs uppercase">{fase.nombre}</p>
                                                                    <div className="ml-2">
                                                                        {fase.movimientos.map((mov, i) => (
                                                                            <span key={i} className="text-gray-600">
                                                                                {i > 0 && ', '}{mov.nombre}{mov.series && ` ${mov.series}x`}{mov.repeticiones && ` ${mov.repeticiones}`}{mov.peso && ` @${mov.peso}kg`}
                                                                            </span>
                                                                        ))}
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    ) : wodHoy.movimientos && wodHoy.movimientos.length > 0 ? (
                                                        <div className="mt-3 text-sm text-gray-600">
                                                            <p className="font-bold text-gray-700 text-xs uppercase mb-1">MOVIMIENTOS</p>
                                                            {wodHoy.movimientos.map((mov, i) => (
                                                                <span key={i}>
                                                                    {i > 0 && ', '}{mov.nombre}{mov.series && ` ${mov.series}x`}{mov.repeticiones && ` ${mov.repeticiones}`}{mov.peso && ` @${mov.peso}kg`}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    ) : null}
                                                </div>
                                            ) : (
                                                <div className="mt-3">
                                                    <p className="text-gray-600">No hay WOD para hoy</p>
                                                    <button
                                                        onClick={() => navigate('/coach/pizarra')}
                                                        className="mt-2 px-4 py-2 bg-orange-500 text-white rounded-lg text-sm font-medium hover:bg-orange-600 transition-colors"
                                                    >
                                                        Crear WOD
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                        {wodHoy && wodHoy.estado === 'draft' && (
                                            <button
                                                onClick={handlePublicarWOD}
                                                disabled={saving}
                                                className="px-4 py-2 bg-green-500 text-white rounded-lg text-sm font-medium hover:bg-green-600 transition-colors disabled:opacity-50"
                                            >
                                                {saving ? 'Publicando...' : 'Publicar'}
                                            </button>
                                        )}
                                    </div>
                                </div>

                                {/* Clases de Hoy */}
                                <div>
                                    <h3 className="text-lg font-bold text-gray-900 mb-3">📅 Mis Clases de Hoy</h3>
                                    {clasesHoy.length > 0 ? (
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                            {clasesHoy.map((clase) => (
                                                <div key={clase.id} className="p-4 bg-white rounded-lg border border-gray-200 hover:border-orange-300 transition-colors">
                                                    <div className="flex justify-between items-start">
                                                        <div>
                                                            <p className="font-semibold text-gray-900">{clase.disciplina_nombre || 'Clase'}</p>
                                                            <p className="text-sm text-gray-600">⏰ {clase.hora_inicio} - {clase.hora_fin}</p>
                                                            <p className="text-sm text-gray-600">👥 {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || 0} alumnos</p>
                                                        </div>
                                                        <button
                                                            onClick={() => handleMarcarAsistencia(clase.id)}
                                                            className="px-3 py-1 bg-orange-500 text-white rounded text-xs font-medium hover:bg-orange-600 transition-colors"
                                                        >
                                                            Asistencia
                                                        </button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <p className="text-gray-500 text-sm">No tienes clases programadas para hoy</p>
                                    )}
                                </div>

                                {/* Alumnos en Progreso */}
                                <div>
                                    <h3 className="text-lg font-bold text-gray-900 mb-3">📈 Alumnos con Más RMs</h3>
                                    <div className="overflow-x-auto">
                                        <table className="w-full">
                                            <thead className="bg-gray-50">
                                                <tr>
                                                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Alumno</th>
                                                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">RMs</th>
                                                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Estado</th>
                                                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Acción</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-gray-200">
                                                {progresoAlumnos.slice(0, 5).map((alumno) => (
                                                    <tr key={alumno.id} className="hover:bg-gray-50">
                                                        <td className="px-4 py-3 text-sm font-medium text-gray-900">{alumno.nombre}</td>
                                                        <td className="px-4 py-3 text-sm text-gray-600">{alumno.total_rms}</td>
                                                        <td className="px-4 py-3">
                                                            <span className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full border ${getProgresoColor(alumno.estado)}`}>
                                                                {getProgresoIcon(alumno.estado)}
                                                                {alumno.estado === 'activo' ? 'Progresando' : alumno.estado === 'iniciando' ? 'Iniciando' : 'Sin datos'}
                                                            </span>
                                                        </td>
                                                        <td className="px-4 py-3">
                                                            <button
                                                                onClick={() => { setSelectedAlumno(alumno); setActiveTab('alumnos'); }}
                                                                className="text-xs text-orange-500 hover:text-orange-700 font-medium"
                                                            >
                                                                Ver RMs
                                                            </button>
                                                        </td>
                                                    </tr>
                                                ))}
                                                {progresoAlumnos.length === 0 && (
                                                    <tr>
                                                        <td colSpan="4" className="px-4 py-6 text-center text-gray-500 text-sm">
                                                            No hay datos de alumnos disponibles
                                                        </td>
                                                    </tr>
                                                )}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>

                                {/* Registros Recientes */}
                                <div>
                                    <h3 className="text-lg font-bold text-gray-900 mb-3">🕐 Registros Recientes</h3>
                                    <div className="space-y-2">
                                        {registrosRecientes.slice(0, 5).map((reg, idx) => (
                                            <div key={idx} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                                                <span className="text-lg">{reg.tipo === 'wod' ? '💪' : '🏋️'}</span>
                                                <div className="flex-1">
                                                    {reg.tipo === 'wod' ? (
                                                        <p className="text-sm font-medium text-gray-900">WOD: {reg.titulo}</p>
                                                    ) : (
                                                        <p className="text-sm font-medium text-gray-900">RM: {reg.peso} kg</p>
                                                    )}
                                                    <p className="text-xs text-gray-500">{reg.fecha ? formatFecha(reg.fecha) : ''}</p>
                                                </div>
                                                <span className={`text-xs px-2 py-1 rounded-full ${reg.tipo === 'wod' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'}`}>
                                                    {reg.tipo === 'wod' ? 'WOD' : 'RM'}
                                                </span>
                                            </div>
                                        ))}
                                        {registrosRecientes.length === 0 && (
                                            <p className="text-gray-500 text-sm text-center py-4">No hay registros recientes</p>
                                        )}
                                    </div>
                                </div>

                                {alumnosEnRiesgo.length > 0 && (
                                    <div className="bg-red-50 border-l-4 border-red-500 rounded-lg p-4">
                                        <div className="flex items-start gap-3">
                                            <span className="text-2xl">⚠️</span>
                                            <div>
                                                <p className="font-bold text-gray-900">{alumnosEnRiesgo.length} alumno(s) en riesgo de abandono</p>
                                                <p className="text-sm text-gray-600 mt-1">Llevan más de 7 días sin entrenar. Revisa la pestaña de Riesgo para contactarlos.</p>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ─── TAB: CLASES (Weekly Schedule Grid) ─── */}
                        {activeTab === 'clases' && (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h2 className="text-xl font-bold text-gray-900">📅 Planificación Semanal</h2>
                                        <p className="text-sm text-gray-600 mt-1">
                                            Semana: {weekRange.start} → {weekRange.end}
                                        </p>
                                    </div>
                                </div>

                                {/* Week Grid */}
                                <div className="overflow-x-auto">
                                    <table className="w-full border-collapse min-w-[900px]">
                                        <thead>
                                            <tr>
                                                <th className="bg-gray-800 text-white px-3 py-3 text-xs font-medium uppercase sticky left-0 z-10 min-w-[80px]">
                                                    Horario
                                                </th>
                                                {DAYS.map((day, i) => {
                                                    const isToday = dayDates[i] === today;
                                                    return (
                                                        <th
                                                            key={day}
                                                            className={`px-3 py-3 text-xs font-medium uppercase text-center min-w-[120px] ${isToday ? 'bg-orange-500 text-white' : 'bg-gray-800 text-white'
                                                                }`}
                                                        >
                                                            <div className="text-sm">{day}</div>
                                                            <div className="text-lg font-bold">{dayDates[i].split('-')[2]}</div>
                                                        </th>
                                                    );
                                                })}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {SCHEDULE_HOURS.map(hour => (
                                                <tr key={hour} className="border-b border-gray-200 hover:bg-gray-50/50">
                                                    <td className="sticky left-0 bg-white border-r border-gray-200 px-3 py-3 text-sm font-bold text-gray-700 whitespace-nowrap z-10">
                                                        {hour}
                                                    </td>
                                                    {dayDates.map((date, dayIdx) => {
                                                        const clase = weekGrid[date]?.[hour];
                                                        const isToday = date === today;
                                                        const isEmpty = !clase;

                                                        // Find WOD for this day
                                                        const wodDelDia = wods.find(w => {
                                                            const fechaWod = w.fecha ? (typeof w.fecha === 'string' ? w.fecha.split('T')[0] : w.fecha) : '';
                                                            return fechaWod === date;
                                                        });

                                                        return (
                                                            <td
                                                                key={`${date}-${hour}`}
                                                                className={`p-2 text-center transition-all ${isToday ? 'bg-orange-50/50' : 'bg-white'
                                                                    } ${isEmpty ? 'hover:bg-gray-100 cursor-pointer' : 'hover:shadow-inner cursor-pointer'
                                                                    } border-r border-gray-100 ${dayIdx === 6 ? 'border-r-0' : ''
                                                                    }`}
                                                                onClick={() => {
                                                                    if (isEmpty) {
                                                                        navigate('/coach/pizarra');
                                                                    } else {
                                                                        // Click on class with WOD → show edit
                                                                        if (wodDelDia) {
                                                                            handleEditWod(wodDelDia);
                                                                        }
                                                                    }
                                                                }}
                                                            >
                                                                {clase ? (
                                                                    <div className="space-y-1">
                                                                        <div className="text-xs font-semibold text-gray-800 leading-tight">
                                                                            {clase.disciplina_nombre || 'CrossFit'}
                                                                        </div>
                                                                        {wodDelDia ? (
                                                                            <div className="text-[10px] leading-tight">
                                                                                <span className="font-medium text-orange-600">
                                                                                    {wodDelDia.titulo}
                                                                                </span>
                                                                                <span className={`ml-1 inline-block px-1 py-0.5 rounded text-[8px] font-bold ${wodDelDia.estado === 'publicado'
                                                                                    ? 'bg-green-100 text-green-700'
                                                                                    : 'bg-yellow-100 text-yellow-700'
                                                                                    }`}>
                                                                                    {wodDelDia.estado === 'publicado' ? '✅' : '📝'}
                                                                                </span>
                                                                            </div>
                                                                        ) : (
                                                                            <div className="text-[10px] text-gray-400 italic">⬜ Sin WOD</div>
                                                                        )}
                                                                        <div className="text-[9px] text-gray-500">
                                                                            👥 {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || 0}
                                                                        </div>
                                                                    </div>
                                                                ) : (
                                                                    <div className="flex items-center justify-center h-full py-3">
                                                                        <span className="text-gray-300 hover:text-orange-400 text-lg transition-colors">+</span>
                                                                    </div>
                                                                )}
                                                            </td>
                                                        );
                                                    })}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>

                                {/* Legend */}
                                <div className="flex flex-wrap gap-4 text-xs text-gray-600 mt-2 p-3 bg-gray-50 rounded-lg">
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-3 rounded-sm bg-orange-50 border border-orange-200"></span> Celda con clase
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-3 rounded-sm bg-white border border-gray-200"></span> Celda vacía
                                    </span>
                                    <span className="flex items-center gap-1">✅ WOD Publicado</span>
                                    <span className="flex items-center gap-1">📝 WOD Borrador</span>
                                    <span className="flex items-center gap-1">⬜ Sin WOD asignado</span>
                                    <span className="flex items-center gap-1">+ Crear nuevo WOD</span>
                                </div>
                            </div>
                        )}

                        {/* ─── TAB: ALUMNOS & RMs ─── */}
                        {activeTab === 'alumnos' && (
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                <div className="space-y-4">
                                    <h2 className="text-xl font-bold text-gray-900">Buscar Alumno</h2>
                                    <input
                                        type="text"
                                        placeholder="Buscar por nombre..."
                                        value={searchTerm}
                                        onChange={(e) => setSearchTerm(e.target.value)}
                                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                    />
                                    <div className="space-y-2 max-h-96 overflow-y-auto">
                                        {filteredAlumnos.length > 0 ? (
                                            filteredAlumnos.map((alumno) => (
                                                <button
                                                    key={alumno.id}
                                                    onClick={() => setSelectedAlumno(alumno)}
                                                    className={`w-full p-4 text-left rounded-lg border-2 transition-colors ${selectedAlumno?.id === alumno.id
                                                        ? 'border-orange-500 bg-orange-50'
                                                        : 'border-gray-200 hover:border-orange-300'
                                                        }`}
                                                >
                                                    <p className="font-medium text-gray-900">{alumno.nombre}</p>
                                                    <p className="text-sm text-gray-600">
                                                        {alumno.correo || 'Sin correo'}
                                                        {alumno.telefono ? ` · ${alumno.telefono}` : ''}
                                                    </p>
                                                </button>
                                            ))
                                        ) : (
                                            <p className="text-gray-600 text-center py-4">
                                                {searchTerm ? 'No se encontraron alumnos' : 'No hay alumnos disponibles'}
                                            </p>
                                        )}
                                    </div>
                                </div>

                                <div className="space-y-4">
                                    <h2 className="text-xl font-bold text-gray-900">
                                        {selectedAlumno ? `RMs de ${selectedAlumno.nombre}` : 'Selecciona un alumno'}
                                    </h2>
                                    {selectedAlumno && (
                                        <div className="space-y-3">
                                            {loading ? (
                                                <div className="flex justify-center py-8">
                                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                                                </div>
                                            ) : alumnoRMs.length > 0 ? (
                                                alumnoRMs.map((rm) => (
                                                    <div key={rm.movimiento_id} className="p-4 bg-gray-50 rounded-lg border border-gray-200 hover:border-orange-300 transition-colors">
                                                        <div className="flex justify-between items-center">
                                                            <div>
                                                                <p className="font-medium text-gray-900">{rm.movimiento_nombre}</p>
                                                                <p className="text-sm text-gray-500">{rm.fecha ? `Último: ${rm.fecha}` : ''}</p>
                                                                {rm.notas && <p className="text-xs text-gray-400 mt-1">{rm.notas}</p>}
                                                            </div>
                                                            <p className="text-2xl font-bold text-orange-500">{rm.peso_kg} kg</p>
                                                        </div>
                                                    </div>
                                                ))
                                            ) : (
                                                <div className="text-center py-8 bg-gray-50 rounded-lg">
                                                    <p className="text-3xl mb-2">🏋️</p>
                                                    <p className="text-gray-600">Sin RMs registrados</p>
                                                    <p className="text-sm text-gray-500 mt-1">Este alumno no ha registrado marcas personales</p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {!selectedAlumno && (
                                        <div className="text-center py-12 bg-gray-50 rounded-lg">
                                            <p className="text-4xl mb-3">👆</p>
                                            <p className="text-gray-600">Selecciona un alumno de la lista</p>
                                            <p className="text-sm text-gray-500 mt-1">para ver sus marcas personales (RMs)</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* ─── TAB: PROGRESO ─── */}
                        {activeTab === 'progreso' && (
                            <div className="space-y-6">
                                <div>
                                    <h2 className="text-xl font-bold text-gray-900">📈 Progreso de Alumnos</h2>
                                    <p className="text-sm text-gray-600 mt-1">Estado actual de RMs y actividad de cada alumno</p>
                                </div>
                                <div className="flex gap-4 text-sm">
                                    <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-green-500"></span> Progresando (5+ RMs)</span>
                                    <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-orange-500"></span> Iniciando (1-4 RMs)</span>
                                    <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-gray-400"></span> Sin datos</span>
                                </div>
                                <div className="overflow-x-auto">
                                    <table className="w-full">
                                        <thead className="bg-gray-800 text-white">
                                            <tr>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Alumno</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Total RMs</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Progreso</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Estado</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Top RM</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Acción</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-200">
                                            {progresoAlumnos.map((alumno, index) => {
                                                const topRM = alumno.rms?.reduce((max, r) => (r.peso_kg > (max?.peso_kg || 0) ? r : max), null);
                                                return (
                                                    <tr key={alumno.id} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                                        <td className="px-6 py-4 text-sm font-medium text-gray-900">{alumno.nombre}</td>
                                                        <td className="px-6 py-4 text-sm">
                                                            <span className="font-bold text-lg">{alumno.total_rms}</span>
                                                        </td>
                                                        <td className="px-6 py-4">
                                                            <div className="flex items-center gap-2">
                                                                <div className="w-24 bg-gray-200 rounded-full h-2">
                                                                    <div
                                                                        className={`h-2 rounded-full ${alumno.estado === 'activo' ? 'bg-green-500 w-full' :
                                                                            alumno.estado === 'iniciando' ? 'bg-orange-500 w-1/3' : 'bg-gray-300 w-1/6'
                                                                            }`}
                                                                    ></div>
                                                                </div>
                                                                <span className="text-xs text-gray-500">{alumno.total_rms}/10+</span>
                                                            </div>
                                                        </td>
                                                        <td className="px-6 py-4">
                                                            <span className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full border ${getProgresoColor(alumno.estado)}`}>
                                                                {getProgresoIcon(alumno.estado)}
                                                                {alumno.estado === 'activo' ? 'Progresando' : alumno.estado === 'iniciando' ? 'Iniciando' : 'Sin datos'}
                                                            </span>
                                                        </td>
                                                        <td className="px-6 py-4 text-sm text-gray-600">
                                                            {topRM ? `${topRM.peso_kg} kg (${topRM.movimiento_nombre || ''})` : '-'}
                                                        </td>
                                                        <td className="px-6 py-4 text-sm">
                                                            <button
                                                                onClick={() => { setSelectedAlumno(alumno); setActiveTab('alumnos'); }}
                                                                className="text-orange-500 hover:text-orange-700 font-medium text-xs"
                                                            >
                                                                Ver RMs
                                                            </button>
                                                        </td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                                {progresoAlumnos.length === 0 && (
                                    <p className="text-gray-500 text-center py-8">No hay datos de progreso disponibles</p>
                                )}
                            </div>
                        )}

                        {/* ─── TAB: MIS WODs ─── */}
                        {activeTab === 'wods' && (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h2 className="text-xl font-bold text-gray-900">📋 Mis WODs de la Semana</h2>
                                        <p className="text-sm text-gray-600 mt-1">
                                            Semana: {weekRange.start} → {weekRange.end} — Total: {wods.length} WODs
                                        </p>
                                    </div>
                                    <button
                                        onClick={() => navigate('/coach/pizarra')}
                                        className="px-4 py-2 bg-orange-500 text-white rounded-lg text-sm font-medium hover:bg-orange-600 transition-colors flex items-center gap-2"
                                    >
                                        <span>➕</span> Crear WOD
                                    </button>
                                </div>

                                {/* Tabla de WODs */}
                                <div className="overflow-x-auto">
                                    <table className="w-full">
                                        <thead className="bg-gray-800 text-white">
                                            <tr>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Día / Horario</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Título</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Movimientos</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Estado</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Acciones</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-200">
                                            {wods.length > 0 ? (
                                                [...wods]
                                                    .sort((a, b) => new Date(b.fecha || 0) - new Date(a.fecha || 0))
                                                    .map((wod, index) => {
                                                        const numMovs = (wod.fases ? wod.fases.reduce((sum, f) => sum + (f.movimientos?.length || 0), 0) : 0) ||
                                                            (wod.movimientos?.length || 0);
                                                        return (
                                                            <tr key={wod.id} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                                                <td className="px-6 py-4 text-sm whitespace-nowrap">
                                                                    <span className="font-medium text-gray-900">{formatFecha(wod.fecha)}</span>
                                                                </td>
                                                                <td className="px-6 py-4 text-sm font-medium text-gray-900">
                                                                    {wod.titulo || 'WOD sin título'}
                                                                </td>
                                                                <td className="px-6 py-4 text-sm text-gray-600">
                                                                    <span className="inline-flex items-center gap-1">
                                                                        <span>🏋️</span>
                                                                        <span>{numMovs} movimiento(s)</span>
                                                                    </span>
                                                                    {numMovs > 0 && wod.movimientos && (
                                                                        <div className="text-xs text-gray-400 mt-1">
                                                                            {wod.movimientos.slice(0, 3).map((m, i) => (
                                                                                <span key={i}>{i > 0 && ', '}{m.nombre}</span>
                                                                            ))}
                                                                            {wod.movimientos.length > 3 && '...'}
                                                                        </div>
                                                                    )}
                                                                    {numMovs > 0 && wod.fases && (
                                                                        <div className="text-xs text-gray-400 mt-1">
                                                                            {wod.fases.map(f => (
                                                                                <span key={f.nombre} className="mr-2">
                                                                                    <span className="font-medium text-orange-500">{f.nombre}:</span> {f.movimientos?.length || 0} movs
                                                                                </span>
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                </td>
                                                                <td className="px-6 py-4 whitespace-nowrap">
                                                                    <span className={`inline-flex items-center px-2.5 py-1 text-xs font-medium rounded-full ${wod.estado === 'publicado'
                                                                        ? 'bg-green-100 text-green-800 border border-green-300'
                                                                        : 'bg-gray-100 text-gray-600 border border-gray-200'
                                                                        }`}>
                                                                        <span className={`w-2 h-2 rounded-full mr-1.5 ${wod.estado === 'publicado' ? 'bg-green-500' : 'bg-gray-400'
                                                                            }`}></span>
                                                                        {wod.estado === 'publicado' ? 'Publicado' : 'Borrador'}
                                                                    </span>
                                                                </td>
                                                                <td className="px-6 py-4 whitespace-nowrap">
                                                                    <div className="flex gap-2">
                                                                        {(wod.estado === 'draft' || wod.estado === 'borrador') && (
                                                                            <button
                                                                                onClick={async () => {
                                                                                    try {
                                                                                        setSaving(true);
                                                                                        await api.put(`/api/v1/wods/${wod.id}?tenant_id=${tenant_id}`, {
                                                                                            estado: 'publicado',
                                                                                            titulo: wod.titulo,
                                                                                            descripcion: wod.descripcion
                                                                                        });
                                                                                        fetchAllData();
                                                                                    } catch (error) {
                                                                                        console.error('Error publishing WOD:', error);
                                                                                        alert('Error al publicar el WOD');
                                                                                    }
                                                                                    setSaving(false);
                                                                                }}
                                                                                className="px-3 py-1.5 bg-green-500 text-white rounded-lg text-xs font-medium hover:bg-green-600 transition-colors flex items-center gap-1"
                                                                            >
                                                                                <span>📢</span> Publicar
                                                                            </button>
                                                                        )}
                                                                        <button
                                                                            onClick={() => handleEditWod(wod)}
                                                                            className="px-3 py-1.5 bg-orange-500 text-white rounded-lg text-xs font-medium hover:bg-orange-600 transition-colors flex items-center gap-1"
                                                                        >
                                                                            <span>✏️</span> Editar
                                                                        </button>
                                                                        <button
                                                                            onClick={() => handleDeleteWod(wod.id)}
                                                                            className="px-3 py-1.5 bg-red-500 text-white rounded-lg text-xs font-medium hover:bg-red-600 transition-colors flex items-center gap-1"
                                                                        >
                                                                            <span>🗑️</span> Eliminar
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        );
                                                    })
                                            ) : (
                                                <tr>
                                                    <td colSpan="5" className="px-6 py-12 text-center text-gray-500">
                                                        <div className="text-4xl mb-3">💪</div>
                                                        <p className="text-lg font-medium text-gray-700">No hay WODs creados</p>
                                                        <p className="text-sm text-gray-500 mt-1">Crea tu primer WOD para que los alumnos puedan verlo</p>
                                                        <button
                                                            onClick={() => navigate('/coach/pizarra')}
                                                            className="mt-4 px-6 py-2 bg-orange-500 text-white rounded-lg text-sm font-medium hover:bg-orange-600 transition-colors"
                                                        >
                                                            Crear Primer WOD
                                                        </button>
                                                    </td>
                                                </tr>
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        )}

                        {/* ─── TAB: RIESGO ─── */}
                        {activeTab === 'riesgo' && (
                            <div className="space-y-4">
                                <div>
                                    <h2 className="text-xl font-bold text-gray-900">⚠️ Alumnos en Riesgo de Abandono</h2>
                                    <p className="text-gray-600 mt-1">Alumnos sin actividad en más de 7 días — requieren contacto</p>
                                </div>
                                {alumnosEnRiesgo.length > 0 ? (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        {alumnosEnRiesgo.map((alumno) => (
                                            <div key={alumno.id} className="p-4 bg-red-50 border-l-4 border-red-500 rounded-lg hover:shadow-md transition-shadow">
                                                <div className="flex items-start justify-between">
                                                    <div>
                                                        <p className="font-bold text-gray-900">{alumno.nombre}</p>
                                                        <p className="text-sm text-gray-600 mt-1">
                                                            🕐 Sin entrenar: <span className="font-semibold text-red-600">{alumno.dias_ausente} días</span>
                                                        </p>
                                                        <p className="text-xs text-gray-500 mt-1">Última asistencia: {alumno.ultima_asistencia || 'Nunca'}</p>
                                                        {alumno.correo && <p className="text-xs text-gray-500">📧 {alumno.correo}</p>}
                                                        {alumno.telefono && <p className="text-xs text-gray-500">📱 {alumno.telefono}</p>}
                                                    </div>
                                                    <span className="text-2xl">⚠️</span>
                                                </div>
                                                <div className="mt-3 flex gap-2">
                                                    <button
                                                        onClick={() => handleContactar(alumno)}
                                                        className="flex-1 px-3 py-2 bg-red-500 text-white rounded text-sm font-medium hover:bg-red-600 transition-colors"
                                                    >
                                                        📞 Contactar
                                                    </button>
                                                    <button
                                                        onClick={() => { setSelectedAlumno(alumno); setActiveTab('alumnos'); }}
                                                        className="px-3 py-2 bg-white border border-red-300 text-red-600 rounded text-sm font-medium hover:bg-red-50 transition-colors"
                                                    >
                                                        Ver Perfil
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="text-center py-12 bg-green-50 rounded-lg border border-green-200">
                                        <p className="text-5xl mb-4">🎉</p>
                                        <p className="text-xl font-bold text-green-700">¡Excelente! Todos tus alumnos están activos</p>
                                        <p className="text-sm text-green-600 mt-2">No hay alumnos en riesgo de abandono</p>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* ─── CONFIRMACIÓN ELIMINAR WOD ─── */}
            {deleteConfirmWodId && (
                <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
                    <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
                        <div className="text-center">
                            <div className="text-5xl mb-4">⚠️</div>
                            <h3 className="text-xl font-bold text-gray-900 mb-2">¿Eliminar WOD?</h3>
                            <p className="text-gray-600 mb-6">Esta acción no se puede deshacer. El WOD se eliminará permanentemente.</p>
                            <div className="flex gap-3 justify-center">
                                <button
                                    onClick={() => setDeleteConfirmWodId(null)}
                                    className="px-6 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
                                >
                                    Cancelar
                                </button>
                                <button
                                    onClick={confirmDeleteWod}
                                    disabled={saving}
                                    className="px-6 py-2 bg-red-500 text-white rounded-lg text-sm font-medium hover:bg-red-600 transition-colors disabled:opacity-50"
                                >
                                    {saving ? 'Eliminando...' : 'Sí, Eliminar'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* ─── MODAL CREAR/EDITAR WOD ─── */}
            {showWodModal && (
                <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
                    <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
                        <div className="p-6 border-b border-gray-200 flex justify-between items-center">
                            <h2 className="text-2xl font-bold text-gray-900">
                                {editingWodId ? 'Editar WOD' : 'Crear WOD del Día'}
                            </h2>
                            <button
                                onClick={() => {
                                    setShowWodModal(false);
                                    setEditingWodId(null);
                                    setWodForm({ titulo: '', descripcion: '', estado: 'draft', coach_id: usuario_id, movimientos: [] });
                                    setWodMovimientos([]);
                                }}
                                className="text-gray-400 hover:text-gray-600 text-2xl"
                            >
                                ✕
                            </button>
                        </div>

                        <div className="p-6 space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Título del WOD *</label>
                                <input
                                    type="text"
                                    placeholder="Ej: 'Fran', 'Cindy', 'Hero WOD'..."
                                    value={wodForm.titulo}
                                    onChange={(e) => setWodForm({ ...wodForm, titulo: e.target.value })}
                                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Descripción</label>
                                <textarea
                                    placeholder="Describe el WOD: rondas, ejercicios, tiempos..."
                                    value={wodForm.descripcion}
                                    onChange={(e) => setWodForm({ ...wodForm, descripcion: e.target.value })}
                                    rows={3}
                                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Estado</label>
                                <select
                                    value={wodForm.estado}
                                    onChange={(e) => setWodForm({ ...wodForm, estado: e.target.value })}
                                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                >
                                    <option value="draft">Borrador</option>
                                    <option value="publicado">Publicado</option>
                                </select>
                            </div>

                            {/* Movimientos */}
                            <div>
                                <div className="flex items-center justify-between mb-2">
                                    <label className="text-sm font-medium text-gray-700">Movimientos</label>
                                    <button
                                        onClick={addMovimientoToWod}
                                        className="text-sm text-orange-500 hover:text-orange-700 font-medium"
                                    >
                                        + Agregar movimiento
                                    </button>
                                </div>
                                {wodMovimientos.length === 0 && (
                                    <p className="text-sm text-gray-500 text-center py-4 border-2 border-dashed border-gray-200 rounded-lg">
                                        No has agregado movimientos. Haz clic en "Agregar movimiento"
                                    </p>
                                )}
                                <div className="space-y-3">
                                    {wodMovimientos.map((mov, idx) => (
                                        <div key={idx} className="p-3 bg-gray-50 rounded-lg border border-gray-200">
                                            <div className="flex justify-between items-start mb-2">
                                                <span className="text-xs font-medium text-gray-500">Movimiento #{idx + 1}</span>
                                                <button
                                                    onClick={() => removeWodMovimiento(idx)}
                                                    className="text-red-500 hover:text-red-700 text-xs"
                                                >
                                                    Eliminar
                                                </button>
                                            </div>
                                            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                                                <select
                                                    value={mov.movimiento_id}
                                                    onChange={(e) => updateWodMovimiento(idx, 'movimiento_id', e.target.value ? parseInt(e.target.value) : '')}
                                                    className="col-span-2 px-2 py-1 border border-gray-300 rounded text-sm"
                                                >
                                                    <option value="">Seleccionar...</option>
                                                    {movimientos.map((m) => (
                                                        <option key={m.id} value={m.id}>{m.nombre}</option>
                                                    ))}
                                                </select>
                                                <input
                                                    type="number"
                                                    placeholder="Series"
                                                    value={mov.series || ''}
                                                    onChange={(e) => updateWodMovimiento(idx, 'series', e.target.value ? parseInt(e.target.value) || 0 : 0)}
                                                    className="px-2 py-1 border border-gray-300 rounded text-sm"
                                                />
                                                <input
                                                    type="text"
                                                    placeholder="Reps"
                                                    value={mov.repeticiones || ''}
                                                    onChange={(e) => updateWodMovimiento(idx, 'repeticiones', e.target.value)}
                                                    className="px-2 py-1 border border-gray-300 rounded text-sm"
                                                />
                                                <input
                                                    type="number"
                                                    step="0.5"
                                                    placeholder="Peso (kg)"
                                                    value={mov.peso || ''}
                                                    onChange={(e) => updateWodMovimiento(idx, 'peso', e.target.value ? parseFloat(e.target.value) || 0 : 0)}
                                                    className="px-2 py-1 border border-gray-300 rounded text-sm"
                                                />
                                            </div>
                                            <input
                                                type="text"
                                                placeholder="Notas (opcional)"
                                                value={mov.notas || ''}
                                                onChange={(e) => updateWodMovimiento(idx, 'notas', e.target.value)}
                                                className="mt-2 w-full px-2 py-1 border border-gray-300 rounded text-sm"
                                            />
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>

                        <div className="p-6 border-t border-gray-200 flex justify-end gap-3">
                            <button
                                onClick={() => {
                                    setShowWodModal(false);
                                    setEditingWodId(null);
                                    setWodForm({ titulo: '', descripcion: '', estado: 'draft', coach_id: usuario_id, movimientos: [] });
                                    setWodMovimientos([]);
                                }}
                                className="px-6 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
                            >
                                Cancelar
                            </button>
                            <button
                                onClick={editingWodId ? handleUpdateWOD : handleCrearWOD}
                                disabled={saving || !wodForm.titulo}
                                className="px-6 py-2 bg-orange-500 text-white rounded-lg text-sm font-medium hover:bg-orange-600 transition-colors disabled:opacity-50"
                            >
                                {saving ? (editingWodId ? 'Actualizando...' : 'Creando...') : (editingWodId ? 'Actualizar WOD' : 'Crear WOD')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </Layout>
    );
};

export default DashboardCoach;