import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import AsistenciaClases from '../../components/coach/AsistenciaClases';

const DashboardCoach = () => {
    const navigate = useNavigate();
    const location = useLocation();
    const searchParams = new URLSearchParams(location.search);
    const activeTab = searchParams.get('tab') || 'resumen';

    const { usuario_id, tenant_id, usuario } = useAuth();

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
    const [coachDisciplinas, setCoachDisciplinas] = useState([]);
    // Toggle Fase 2: "Ver todas" vs "Ver solo con WOD publicado"
    const [verSoloConWod, setVerSoloConWod] = useState(false);
    // ── Asistencia inline en tarjetas de "Mis Clases de Hoy" ──
    const [claseAsistenciaExpandida, setClaseAsistenciaExpandida] = useState(null);
    const [asistenciaPorClase, setAsistenciaPorClase] = useState({});
    const [cargandoAsistencia, setCargandoAsistencia] = useState(false);
    const [msgAsistencia, setMsgAsistencia] = useState(null); // { claseId, texto, tipo }

    // ---- Terminología dinámica por disciplina ----
    const TERMINO_POR_DISCIPLINA = {
        'CrossFit': 'WOD',
        'Gap': 'WOD',
        'Levantamiento Olímpico': 'WOD',
        'Musculación': 'Entrenamiento',
        'Musculacion': 'Entrenamiento',
        'Open Box': 'Entrenamiento',
    };
    const getTerminoDisciplina = (nombre) => {
        if (!nombre) return 'WOD';
        const nombreLower = nombre.trim();
        return TERMINO_POR_DISCIPLINA[nombreLower] || 'WOD';
    };

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

    const [weekRange, setWeekRange] = useState(getWeekRange);
    const irSemanaAnterior = () => {
        const start = new Date(weekRange.start + 'T12:00:00');
        start.setDate(start.getDate() - 7);
        setWeekRange({
            start: toLocalDateStr(start),
            end: toLocalDateStr(new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6))
        });
    };
    const irSemanaSiguiente = () => {
        const start = new Date(weekRange.start + 'T12:00:00');
        start.setDate(start.getDate() + 7);
        setWeekRange({
            start: toLocalDateStr(start),
            end: toLocalDateStr(new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6))
        });
    };

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
            const [clasesRes, alumnosRes, wodsRes, riesgoRes, movRes, coachDiscRes] = await Promise.all([
                api.get(`/api/v1/clases?coach_id=${usuario_id}`),
                api.get(`/api/v1/usuarios?rol=alumno&activo=true`),
                api.get(`/api/v1/wods`),
                api.get(`/api/v1/fidelizacion/coach/${usuario_id}/en-riesgo`),
                api.get(`/api/v1/movimientos`),
                api.get(`/api/v1/coach-disciplinas`)
            ]);

            // Disciplinas asignadas al coach (activo=True)
            const coachDiscData = coachDiscRes.data || [];
            const discIds = coachDiscData
                .filter(cd => cd.activo && cd.coach_id === usuario_id)
                .map(cd => cd.disciplina_id);
            setCoachDisciplinas(discIds);

            const clasesData = clasesRes.data || [];
            const alumnosData = alumnosRes.data || [];
            const wodsData = wodsRes.data || [];
            const riesgoData = riesgoRes.data?.alumnos_alerta || [];
            const movimientosData = movRes.data || [];

            setAlumnos(alumnosData);
            setAlumnosEnRiesgo(riesgoData);
            setWods(wodsData);
            setMovimientos(movimientosData);

            // Filtrar SOLO las disciplinas asignadas al coach (tabla coach_disciplinas activo=True)
            const clasesFiltradas = coachDisciplinas.length > 0
                ? clasesData.filter(c => coachDisciplinas.includes(c.disciplina_id))
                : clasesData;

            // Filter today's classes
            const hoyClases = clasesFiltradas.filter(c => {
                const fechaStr = c.fecha ? (typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha) : '';
                return fechaStr === today;
            });
            setClasesHoy(hoyClases);

            // Filter week classes
            const semanaClases = clasesFiltradas.filter(c => {
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
        // Fix rendimiento N+1: lanzar TODAS las consultas de RM en paralelo
        // (Promise.all) en vez de un for con await secuencial que bloqueaba
        // la carga del dashboard (hasta 50 llamadas HTTP en fila).
        const alumnos = alumnosData.slice(0, 50);
        const resultados = await Promise.all(alumnos.map(async (alumno) => {
            try {
                const rmsRes = await api.get(`/api/v1/historial-rm/alumnos/${alumno.id}/rms`);
                const rms = rmsRes.data || [];
                return {
                    id: alumno.id,
                    nombre: alumno.nombre,
                    correo: alumno.correo,
                    telefono: alumno.telefono,
                    total_rms: rms.length,
                    rms: rms,
                    estado: rms.length >= 5 ? 'activo' : rms.length > 0 ? 'iniciando' : 'sin_datos'
                };
            } catch {
                return {
                    id: alumno.id,
                    nombre: alumno.nombre,
                    correo: alumno.correo,
                    telefono: alumno.telefono,
                    total_rms: 0,
                    rms: [],
                    estado: 'sin_datos'
                };
            }
        }));
        setProgresoAlumnos(resultados);
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
                const rmsRes = await api.get(`/api/v1/historial-rm?limit=5`);
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
                    const response = await api.get(`/api/v1/historial-rm/alumnos/${selectedAlumno.id}/rms`);
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
    const cargarAsistenciaClase = async (claseId) => {
        // Toggle: si ya está expandida, colapsar
        if (claseAsistenciaExpandida === claseId) {
            setClaseAsistenciaExpandida(null);
            return;
        }
        setCargandoAsistencia(true);
        setMsgAsistencia(null);
        try {
            const r = await api.get(`/api/v1/reservas/por-clase/${claseId}`);
            const reservas = r.data || [];
            setAsistenciaPorClase(prev => ({
                ...prev,
                [claseId]: reservas.map(r => ({
                    reserva_id: r.id,
                    alumno_id: r.alumno_id,
                    nombre: r.alumno_nombre || `#${r.alumno_id}`,
                    asistio: r.asistio || false
                }))
            }));
            setClaseAsistenciaExpandida(claseId);
        } catch (e) {
            console.error('Error cargando asistencia:', e);
            setMsgAsistencia({ claseId, texto: 'Error al cargar la asistencia', tipo: 'error' });
        }
        setCargandoAsistencia(false);
    };

    const toggleAsistenciaAlumno = async (claseId, reservaId, valor) => {
        try {
            await api.put(`/api/v1/reservas/${reservaId}/asistencia`, { asistio: valor });
            setAsistenciaPorClase(prev => ({
                ...prev,
                [claseId]: (prev[claseId] || []).map(a => a.reserva_id === reservaId ? { ...a, asistio: valor } : a)
            }));
            setMsgAsistencia({ claseId, texto: valor ? '✅ Asistencia guardada (asistió)' : '❌ Asistencia guardada (no asistió)', tipo: 'exito' });
        } catch (e) {
            console.error('Error marcando asistencia:', e);
            setMsgAsistencia({ claseId, texto: 'Error al guardar la asistencia', tipo: 'error' });
        }
    };

    const marcarTodosAsistencia = async (claseId, valor) => {
        const reservas = asistenciaPorClase[claseId] || [];
        if (reservas.length === 0) return;
        let errores = 0;
        for (const a of reservas) {
            try {
                await api.put(`/api/v1/reservas/${a.reserva_id}/asistencia`, { asistio: valor });
                setAsistenciaPorClase(prev => ({
                    ...prev,
                    [claseId]: (prev[claseId] || []).map(r => r.reserva_id === a.reserva_id ? { ...r, asistio: valor } : r)
                }));
            } catch (e) {
                console.error(`Error marcando reserva ${a.reserva_id}:`, e);
                errores++;
            }
        }
        setMsgAsistencia({
            claseId,
            texto: errores === 0
                ? (valor ? '✅ Todos marcados como ASISTIERON' : '❌ Todos marcados como NO ASISTIERON')
                : `⚠️ ${errores} error(es) al marcar`,
            tipo: errores === 0 ? 'exito' : 'error'
        });
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

    const handlePublicarWOD = async () => {
        if (!wodHoy) return;
        try {
            await api.put(`/api/v1/wods/${wodHoy.id}`, {
                estado: 'publicado',
                titulo: wodHoy.titulo,
                descripcion: wodHoy.descripcion,
                calentamiento: wodHoy.calentamiento,
                fuerza_habilidad: wodHoy.fuerza_habilidad,
                wod_principal: wodHoy.wod_principal,
                tipo_metcon: wodHoy.tipo_metcon
            });
            setWodHoy({ ...wodHoy, estado: 'publicado' });
            fetchAllData();
        } catch (error) {
            console.error('Error publishing WOD:', error);
            alert('Error al publicar el WOD');
        }
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
                {/* Header — sin botón de crear WOD, solo informativo */}
                <div className="flex flex-col md:flex-row md:items-center md:justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Dashboard Coach</h1>
                        <p className="text-gray-600 mt-1">Bienvenido, {usuario || 'Coach'} — {today}</p>
                    </div>
                    <div className="mt-4 md:mt-0 flex gap-2">
                        {/* PUNTO DE ENTRADA ÚNICO (TAREA 6): publicar WOD de la clase de hoy */}
                        {clasesHoy.length > 0 && (
                            <button
                                onClick={() => navigate(`/coach/gestion-clases?clase=${clasesHoy[0].id}`)}
                                className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors text-sm font-bold flex items-center gap-2 animate-pulse"
                            >
                                <span>📝</span> Publicar WOD de Hoy
                            </button>
                        )}
                        <button
                            onClick={() => navigate('/coach/gestion-clases')}
                            className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors text-sm font-medium flex items-center gap-2"
                        >
                            <span>📋</span> Ir a Gestión de Clases
                        </button>
                    </div>
                </div>

                {/* Stats Cards — ahora clickeables, cada una navega a su pantalla */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    <button onClick={() => navigate('/coach/dashboard?tab=clases')} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-all cursor-pointer text-left">
                        <div className="flex items-start justify-between">
                            <div>
                                <p className="text-sm font-medium text-gray-500">Clases Hoy</p>
                                <p className="text-2xl font-bold text-gray-900 mt-1">{clasesHoy.length}</p>
                                <p className="text-xs text-gray-500 mt-1">{clasesHoy.reduce((sum, c) => sum + (c.asistentes_confirmados || 0), 0)} asistentes — Clic para ver</p>
                            </div>
                            <div className="bg-blue-500 w-12 h-12 rounded-lg flex items-center justify-center text-xl">📅</div>
                        </div>
                    </button>
                    <button onClick={() => navigate('/coach/dashboard?tab=alumnos')} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-all cursor-pointer text-left">
                        <div className="flex items-start justify-between">
                            <div>
                                <p className="text-sm font-medium text-gray-500">Alumnos Activos</p>
                                <p className="text-2xl font-bold text-gray-900 mt-1">{alumnos.length}</p>
                                <p className="text-xs text-gray-500 mt-1">{progresoAlumnos.filter(a => a.total_rms > 0).length} con RMs — Clic para ver</p>
                            </div>
                            <div className="bg-green-500 w-12 h-12 rounded-lg flex items-center justify-center text-xl">👥</div>
                        </div>
                    </button>
                    <button onClick={() => navigate('/coach/dashboard?tab=clases')} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-all cursor-pointer text-left">
                        <div className="flex items-start justify-between">
                            <div>
                                <p className="text-sm font-medium text-gray-500">WOD del Día</p>
                                <p className="text-2xl font-bold text-gray-900 mt-1">{wodHoy ? (wodHoy.estado === 'publicado' ? 'Publicado' : 'Borrador') : 'Sin WOD'}</p>
                                <p className="text-xs text-gray-500 mt-1">{wodHoy?.titulo || 'Crea el WOD — Clic para ver'}</p>
                            </div>
                            <div className={`${wodHoy?.estado === 'publicado' ? 'bg-orange-500' : 'bg-gray-500'} w-12 h-12 rounded-lg flex items-center justify-center text-xl`}>💪</div>
                        </div>
                    </button>
                    <button onClick={() => navigate('/coach/dashboard?tab=riesgo')} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-all cursor-pointer text-left">
                        <div className="flex items-start justify-between">
                            <div>
                                <p className="text-sm font-medium text-gray-500">Alumnos en Riesgo</p>
                                <p className="text-2xl font-bold text-gray-900 mt-1">{alumnosEnRiesgo.length}</p>
                                <p className="text-xs text-gray-500 mt-1">{alumnosEnRiesgo.length > 0 ? 'Requieren atención — Clic para ver' : 'Todos activos'}</p>
                            </div>
                            <div className={`${alumnosEnRiesgo.length > 0 ? 'bg-red-500' : 'bg-emerald-500'} w-12 h-12 rounded-lg flex items-center justify-center text-xl`}>⚠️</div>
                        </div>
                    </button>
                    <button onClick={() => navigate('/coach/dashboard?tab=clases')} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-all cursor-pointer text-left col-span-1">
                        <div className="flex items-start justify-between">
                            <div>
                                <p className="text-sm font-medium text-gray-500">WODs esta semana</p>
                                <p className="text-2xl font-bold text-gray-900 mt-1">{clasesSemana.filter(c => c.wod_id != null).length}/{clasesSemana.length} publicados</p>
                                <p className="text-xs text-gray-500 mt-1">Clic para ver Clases y WODs</p>
                            </div>
                            <div className="bg-orange-500 w-12 h-12 rounded-lg flex items-center justify-center text-xl">💪</div>
                        </div>
                    </button>
                </div>

                {/* ─── CONTENIDO BASADO EN URL (sin pestañas internas duplicadas) ─── */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
                    <div className="p-6">
                        {/* ─── TAB: RESUMEN ─── */}
                        {activeTab === 'resumen' && (
                            <div className="space-y-6">
                                {/* (Fase 1) Bloque "WOD del Día" duplicado eliminado — la tarjeta superior
                                    ya muestra el estado e invita a ver Mis WODs (abre ?tab=wods). */}

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
                                                        <div className="flex flex-col sm:flex-row gap-2">
                                                            <button
                                                                onClick={() => navigate(`/coach/gestion-clases?clase=${clase.id}`)}
                                                                className="px-3 py-1 bg-emerald-600 text-white rounded text-xs font-medium hover:bg-emerald-700 transition-colors"
                                                            >
                                                                📝 Publicar {getTerminoDisciplina(clase.disciplina_nombre)}
                                                            </button>
                                                            <button
                                                                onClick={() => cargarAsistenciaClase(clase.id)}
                                                                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${claseAsistenciaExpandida === clase.id
                                                                    ? 'bg-orange-600 text-white'
                                                                    : 'bg-orange-500 text-white hover:bg-orange-600'
                                                                    }`}
                                                            >
                                                                {claseAsistenciaExpandida === clase.id ? '▼ Cerrar Asistencia' : '📋 Asistencia'}
                                                            </button>
                                                        </div>
                                                    </div>

                                                    {/* Panel de asistencia expandible inline */}
                                                    {claseAsistenciaExpandida === clase.id && (
                                                        <div className="mt-4 p-3 bg-orange-50 rounded-lg border border-orange-200">
                                                            {/* Feedback visual de guardado */}
                                                            {msgAsistencia?.claseId === clase.id && (
                                                                <div className={`mb-3 px-3 py-2 rounded-md text-sm font-medium ${msgAsistencia.tipo === 'exito'
                                                                    ? 'bg-green-100 text-green-800 border border-green-300'
                                                                    : 'bg-red-100 text-red-800 border border-red-300'
                                                                    }`}>
                                                                    {msgAsistencia.texto}
                                                                </div>
                                                            )}

                                                            {cargandoAsistencia ? (
                                                                <div className="flex items-center justify-center py-6">
                                                                    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-orange-500"></div>
                                                                </div>
                                                            ) : (asistenciaPorClase[clase.id] || []).length === 0 ? (
                                                                <p className="text-sm text-gray-500 text-center py-4">
                                                                    Sin alumnos reservados en esta clase
                                                                </p>
                                                            ) : (
                                                                <>
                                                                    {/* Botones "marcar todos" */}
                                                                    <div className="flex gap-2 mb-3">
                                                                        <button
                                                                            onClick={() => marcarTodosAsistencia(clase.id, true)}
                                                                            className="px-3 py-1.5 bg-emerald-500 text-white rounded text-xs font-bold hover:bg-emerald-600 transition-colors"
                                                                        >
                                                                            ✅ Todos ASISTIERON
                                                                        </button>
                                                                        <button
                                                                            onClick={() => marcarTodosAsistencia(clase.id, false)}
                                                                            className="px-3 py-1.5 bg-red-500 text-white rounded text-xs font-bold hover:bg-red-600 transition-colors"
                                                                        >
                                                                            ❌ Todos FALTA
                                                                        </button>
                                                                    </div>
                                                                    {/* Lista de alumnos con toggle individual */}
                                                                    <div className="space-y-2 max-h-64 overflow-y-auto">
                                                                        {(asistenciaPorClase[clase.id] || []).map(a => (
                                                                            <button
                                                                                key={a.reserva_id}
                                                                                onClick={() => toggleAsistenciaAlumno(clase.id, a.reserva_id, !a.asistio)}
                                                                                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${a.asistio
                                                                                    ? 'bg-emerald-100 text-emerald-800 border-emerald-400 hover:bg-emerald-200'
                                                                                    : 'bg-red-100 text-red-800 border-red-400 hover:bg-red-200'
                                                                                    }`}
                                                                            >
                                                                                <span>{a.nombre}</span>
                                                                                <span>{a.asistio ? '✅ ASISTIÓ' : '❌ FALTA'}</span>
                                                                            </button>
                                                                        ))}
                                                                    </div>
                                                                </>
                                                            )}
                                                        </div>
                                                    )}
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
                                                                onClick={() => { setSelectedAlumno(alumno); navigate('/coach/dashboard?tab=alumnos'); }}
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

                        {/* ─── TAB: CLASES (Fusión Fase 2: Clases + Mis WODs con toggle) ───
                            NOTA: activeTab === 'wods' se conserva como alias de compatibilidad
                            (URLs viejas ?tab=wods ahora muestran la vista fusionada). */}
                        {(activeTab === 'clases' || activeTab === 'wods') && (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between flex-wrap gap-3">
                                    <div>
                                        <h2 className="text-xl font-bold text-gray-900">📅 Clases y {getTerminoDisciplina('CrossFit')}s de la Semana</h2>
                                        <p className="text-sm text-gray-600 mt-1">
                                            Semana: {weekRange.start} → {weekRange.end}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <button
                                            onClick={irSemanaAnterior}
                                            className="px-3 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-300 transition-colors"
                                        >
                                            ◀ Semana anterior
                                        </button>
                                        <button
                                            onClick={irSemanaSiguiente}
                                            className="px-3 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-300 transition-colors"
                                        >
                                            Semana siguiente ▶
                                        </button>
                                        <button
                                            onClick={() => navigate('/coach/gestion-clases')}
                                            className="px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 transition-colors"
                                        >
                                            📋 Gestionar Clases
                                        </button>
                                    </div>
                                </div>

                                {/* Toggle Fase 2: "Ver todas" / "Ver solo con WOD publicado" */}
                                <div className="inline-flex items-center gap-3 p-2 bg-gray-100 rounded-xl">
                                    <button
                                        onClick={() => setVerSoloConWod(false)}
                                        className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${!verSoloConWod
                                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200'
                                            : 'text-gray-500 hover:text-gray-700'
                                            }`}
                                    >
                                        👁️ Ver todas
                                    </button>
                                    <button
                                        onClick={() => setVerSoloConWod(true)}
                                        className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${verSoloConWod
                                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200'
                                            : 'text-gray-500 hover:text-gray-700'
                                            }`}
                                    >
                                        ✅ Ver solo con {getTerminoDisciplina('CrossFit')} publicado
                                    </button>
                                </div>

                                {/* Vista MOBILE (Fase 3): lista vertical de clases — visible solo en < md */}
                                <div className="block md:hidden space-y-3">
                                    {dayDates.map((date, dayIdx) => {
                                        // Clases de este día, ordenadas por hora
                                        const clasesDelDia = (clasesSemana || [])
                                            .filter(c => {
                                                const fechaStr = c.fecha ? (typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha) : '';
                                                return fechaStr === date;
                                            })
                                            .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));

                                        // WODs de este día
                                        const wodDeClase = (clase) => clase ? wods.find(w => {
                                            const fechaW = w.fecha ? (typeof w.fecha === 'string' ? w.fecha.split('T')[0] : w.fecha) : '';
                                            return fechaW === date && w.id === clase.wod_id;
                                        }) : null;

                                        // Fase 2/3: si el toggle está en "solo con WOD publicado", filtrar
                                        const clasesVisibles = verSoloConWod
                                            ? clasesDelDia.filter(c => wodDeClase(c))
                                            : clasesDelDia;

                                        return (
                                            <div key={date} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                                                {/* Encabezado del día */}
                                                <div className={`px-4 py-2.5 flex items-center justify-between ${date === today ? 'bg-orange-50 border-b border-orange-200' : 'bg-gray-50 border-b border-gray-200'}`}>
                                                    <div className="flex items-center gap-2">
                                                        <span className={`text-sm font-bold ${date === today ? 'text-orange-600' : 'text-gray-700'}`}>
                                                            {DAYS[dayIdx]} {date.split('-')[2]}
                                                        </span>
                                                        {date === today && (
                                                            <span className="text-[10px] font-bold bg-orange-500 text-white px-2 py-0.5 rounded-full uppercase">Hoy</span>
                                                        )}
                                                    </div>
                                                    <span className="text-xs text-gray-500">{clasesVisibles.length} clase(s)</span>
                                                </div>

                                                {/* Clases del día (vertical) */}
                                                <div className="divide-y divide-gray-100">
                                                    {clasesVisibles.length > 0 ? (
                                                        clasesVisibles.map((clase) => {
                                                            const wod = wodDeClase(clase);
                                                            return (
                                                                <button
                                                                    key={clase.id}
                                                                    onClick={() => {
                                                                        const fechaISO = clase.fecha ? (typeof clase.fecha === 'string' ? clase.fecha.split('T')[0] : clase.fecha) : date;
                                                                        navigate(`/coach/gestion-clases?fecha=${fechaISO}&clase=${clase.id}`);
                                                                    }}
                                                                    className={`w-full px-4 py-3 flex items-center gap-3 text-left transition-colors ${wod
                                                                        ? 'bg-green-50/50 hover:bg-green-100'
                                                                        : 'bg-yellow-50/50 hover:bg-yellow-100'
                                                                        }`}
                                                                >
                                                                    <span className="text-lg font-bold text-gray-800 w-14 shrink-0">
                                                                        {clase.hora_inicio ? clase.hora_inicio.substring(0, 5) : '--:--'}
                                                                    </span>
                                                                    <div className="flex-1 min-w-0">
                                                                        <p className="text-sm font-semibold text-gray-900 truncate">
                                                                            {clase.disciplina_nombre || 'Clase'}
                                                                        </p>
                                                                        <p className={`text-xs truncate ${wod ? 'text-green-700 font-medium' : 'text-gray-600'}`}>
                                                                            {wod ? (
                                                                                <span className="whitespace-pre-line">
                                                                                    <span className="font-bold text-green-700">💪 {wod.titulo || 'WOD publicado'}</span>
                                                                                    {wod.calentamiento && <span className="block text-[10px] text-gray-600 mt-0.5">🔥 {wod.calentamiento}</span>}
                                                                                    {wod.fuerza_habilidad && <span className="block text-[10px] text-gray-600">🏋️ {wod.fuerza_habilidad}</span>}
                                                                                    {wod.wod_principal && <span className="block text-[10px] text-gray-700">💥 {wod.wod_principal}</span>}
                                                                                </span>
                                                                            ) : (
                                                                                `⬜ Sin ${getTerminoDisciplina(clase.disciplina_nombre)}`
                                                                            )}
                                                                        </p>
                                                                        <p className="text-xs text-gray-500">
                                                                            👥 {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || 0}
                                                                        </p>
                                                                    </div>
                                                                    <div className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-lg ${wod ? 'bg-green-100' : 'bg-yellow-100'}`}>
                                                                        {wod ? '✅' : '📝'}
                                                                    </div>
                                                                </button>
                                                            );
                                                        })
                                                    ) : (
                                                        <p className="px-4 py-4 text-sm text-gray-400 text-center italic">
                                                            {verSoloConWod ? 'Sin WODs publicados este día' : 'Sin clases este día'}
                                                        </p>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>

                                {/* Week Grid (DESKTOP) — celda clickeable: crear WOD si no existe, editar si ya existe */}
                                <div className="hidden md:block overflow-x-auto">
                                    <table className="w-full border-collapse min-w-[900px]">
                                        <thead>
                                            <tr>
                                                <th className="bg-gray-800 text-white px-3 py-3 text-sm font-bold uppercase sticky left-0 z-10 min-w-[90px]">
                                                    Horario
                                                </th>
                                                {DAYS.map((day, i) => {
                                                    const isToday = dayDates[i] === today;
                                                    return (
                                                        <th
                                                            key={day}
                                                            className={`px-3 py-3 text-sm font-bold uppercase text-center min-w-[130px] ${isToday ? 'bg-orange-600 text-white ring-2 ring-orange-300 shadow-inner' : 'bg-gray-800 text-white'
                                                                }`}
                                                        >
                                                            <div className="text-base">{day}</div>
                                                            <div className="text-xl font-bold">{dayDates[i].split('-')[2]}</div>
                                                            {isToday && <div className="text-[10px] font-black bg-white text-orange-600 rounded-full mt-1 px-2 py-0.5">HOY</div>}
                                                        </th>
                                                    );
                                                })}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {SCHEDULE_HOURS.map(hour => (
                                                <tr key={hour} className="border-b border-gray-200 hover:bg-gray-50/50">
                                                    <td className="sticky left-0 bg-white border-r border-gray-200 px-3 py-3 text-base font-bold text-gray-700 whitespace-nowrap z-10">
                                                        {hour}
                                                    </td>
                                                    {dayDates.map((date, dayIdx) => {
                                                        const clase = weekGrid[date]?.[hour];
                                                        const isToday = date === today;
                                                        // WOD asociado a esta clase (directamente desde el objeto clase que ahora trae wod_id)
                                                        const wodDeClase = clase ? wods.find(w => {
                                                            const fechaW = w.fecha ? (typeof w.fecha === 'string' ? w.fecha.split('T')[0] : w.fecha) : '';
                                                            return fechaW === date && w.id === clase.wod_id;
                                                        }) : null;

                                                        // Fase 2: si el toggle está en "solo con WOD publicado" y la celda no tiene WOD, ocultarla
                                                        if (verSoloConWod && (!clase || !wodDeClase)) {
                                                            return null;
                                                        }

                                                        return (
                                                            <td
                                                                key={`${date}-${hour}`}
                                                                className={`p-2 text-center transition-all border-r border-zinc-700 ${dayIdx === 6 ? 'border-r-0' : ''
                                                                    }`}
                                                            >
                                                                {clase ? (
                                                                    wodDeClase ? (
                                                                        // Celda con WOD publicado — fondo naranja translúcido sobre dark + ícono ✅
                                                                        <button
                                                                            onClick={() => {
                                                                                const fechaISO = clase.fecha ? (typeof clase.fecha === 'string' ? clase.fecha.split('T')[0] : clase.fecha) : date;
                                                                                navigate(`/coach/gestion-clases?fecha=${fechaISO}&clase=${clase.id}`);
                                                                            }}
                                                                            className="w-full h-full min-h-[64px] flex flex-col items-center justify-center gap-1 rounded-lg transition-all cursor-pointer bg-orange-500/20 border-2 border-orange-500 hover:bg-orange-500/30"
                                                                        >
                                                                            <div className="text-base font-bold text-orange-200 leading-tight capitalize">
                                                                                {clase.disciplina_nombre || 'Clase'}
                                                                            </div>
                                                                            <div className="text-sm text-orange-300 font-bold leading-tight max-w-[110px] text-center">
                                                                                ✅ {wodDeClase.titulo || 'WOD publicado'}
                                                                            </div>
                                                                            <div className="text-[9px] text-orange-400 leading-tight max-w-[110px] text-center whitespace-pre-line overflow-hidden">
                                                                                {wodDeClase.calentamiento && `🔥 ${wodDeClase.calentamiento.split('\n').slice(0, 2).join('\n')}`}
                                                                                {wodDeClase.fuerza_habilidad && `\n🏋️ ${wodDeClase.fuerza_habilidad.split('\n').slice(0, 2).join('\n')}`}
                                                                                {wodDeClase.wod_principal && `\n💥 ${wodDeClase.wod_principal.split('\n').slice(0, 2).join('\n')}`}
                                                                            </div>
                                                                            <div className="text-sm text-orange-400">
                                                                                ✔ Publicado
                                                                            </div>
                                                                        </button>
                                                                    ) : (
                                                                        // Celda con clase sin WOD — fondo zinc-800 oscuro + texto claro legible
                                                                        <button
                                                                            onClick={() => {
                                                                                const fechaISO = clase.fecha ? (typeof clase.fecha === 'string' ? clase.fecha.split('T')[0] : clase.fecha) : date;
                                                                                navigate(`/coach/gestion-clases?fecha=${fechaISO}&clase=${clase.id}`);
                                                                            }}
                                                                            className="w-full h-full min-h-[64px] flex flex-col items-center justify-center gap-1 rounded-lg transition-all cursor-pointer bg-zinc-800 border border-zinc-600 hover:bg-zinc-700"
                                                                        >
                                                                            <div className="text-base font-semibold text-zinc-200 leading-tight capitalize">
                                                                                {clase.disciplina_nombre || 'Clase'}
                                                                            </div>
                                                                            <div className="text-sm text-zinc-300">
                                                                                ⬜ Sin {getTerminoDisciplina(clase.disciplina_nombre)}
                                                                            </div>
                                                                            <div className="text-sm text-zinc-400">
                                                                                👥 {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || 0}
                                                                            </div>
                                                                        </button>
                                                                    )
                                                                ) : (
                                                                    <div className="flex items-center justify-center h-full py-3 bg-zinc-900/60 rounded-lg">
                                                                        <span className="text-zinc-500 text-base italic">—</span>
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
                                <div className="flex flex-wrap gap-4 text-xs text-zinc-400 mt-2 p-3 bg-zinc-900 rounded-lg border border-zinc-800">
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-3 rounded-sm bg-orange-500/30 border-2 border-orange-500"></span> Con {getTerminoDisciplina('CrossFit')} publicado (naranja)
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-3 rounded-sm bg-zinc-800 border border-zinc-600"></span> Sin {getTerminoDisciplina('CrossFit')} (gris oscuro)
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-3 rounded-sm bg-zinc-900/60 border border-zinc-700"></span> Celda vacía
                                    </span>
                                    {!verSoloConWod && (
                                        <span className="text-zinc-500 italic">📌 Clic en una celda gris oscura para crear el {getTerminoDisciplina('CrossFit')} de esa clase</span>
                                    )}
                                </div>
                                <p className="text-xs text-gray-400 text-center">
                                    ℹ️ Clic en una celda para publicar/editar el {getTerminoDisciplina('CrossFit')} de esa clase. Para crear o editar, usa "Gestión de Clases".
                                </p>
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
                                                                onClick={() => { setSelectedAlumno(alumno); navigate('/coach/dashboard?tab=alumnos'); }}
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
                                                            🕐 {alumno.tiene_historial === false
                                                                ? <span className="font-semibold text-red-600">Sin actividad registrada</span>
                                                                : <>Sin entrenar: <span className="font-semibold text-red-600">{alumno.dias_ausente} días</span></>}
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
                                                        onClick={() => setSelectedAlumno(alumno)}
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

                        {/* ── TAB: ASISTENCIA ── */}
                        {activeTab === 'asistencia' && (
                            <AsistenciaClases />
                        )}
                    </div>
                </div>
            </div>
        </Layout>
    );
};

export default DashboardCoach;