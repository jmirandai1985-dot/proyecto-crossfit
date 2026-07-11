import React, { useState, useEffect, useMemo } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

// ─── Utilidades de fechas ─────────────────────────────────────────
const DIAS_NOMBRES = ['domingo', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado'];
const DIAS_NOMBRES_CAPTION = { lunes: 'Lunes', martes: 'Martes', miercoles: 'Miércoles', jueves: 'Jueves', viernes: 'Viernes', sabado: 'Sábado' };
const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

const DIAS_LABELS = [
    { key: 'lunes', label: 'Lunes' },
    { key: 'martes', label: 'Martes' },
    { key: 'miercoles', label: 'Miércoles' },
    { key: 'jueves', label: 'Jueves' },
    { key: 'viernes', label: 'Viernes' },
    { key: 'sabado', label: 'Sábado' },
];

/** Obtiene el lunes de la semana a la que pertenece una fecha */
const getLunesSemana = (fecha) => {
    const d = new Date(fecha);
    const dia = d.getDay(); // 0=Dom
    const diff = dia === 0 ? -6 : 1 - dia; // Si domingo, retrocede 6; si no, va al lunes
    d.setDate(d.getDate() + diff);
    d.setHours(0, 0, 0, 0);
    return d;
};

/** Genera los 7 días de la semana (lunes a domingo) para una fecha dada */
const generarSemana = (fechaRef) => {
    const lunes = getLunesSemana(fechaRef);
    const dias = [];
    for (let i = 0; i < 7; i++) {
        const d = new Date(lunes);
        d.setDate(lunes.getDate() + i);
        dias.push(d);
    }
    return dias; // [lunes, martes, ..., domingo]
};

/** Formatea una fecha como "Viernes 10 Jul" */
const formatFecha = (date) => {
    const diaSemana = DIAS_NOMBRES[date.getDay()];
    const nombre = DIAS_NOMBRES_CAPTION[diaSemana] || diaSemana;
    const dia = date.getDate();
    const mes = MESES[date.getMonth()];
    return { nombre, dia, mes, full: `${nombre} ${dia} ${mes}` };
};

/** Formatea rango de semana: "6 - 12 Jul 2026" */
const formatRangoSemana = (dias) => {
    if (!dias || dias.length === 0) return '';
    const primero = dias[0];
    const ultimo = dias[6];
    const dia1 = primero.getDate();
    const dia2 = ultimo.getDate();
    const mes = MESES[primero.getMonth()];
    const año = primero.getFullYear();
    return `${dia1} - ${dia2} ${mes} ${año}`;
};

/** Compara si dos fechas son el mismo día */
const esMismoDia = (d1, d2) => {
    return d1.getFullYear() === d2.getFullYear() &&
        d1.getMonth() === d2.getMonth() &&
        d1.getDate() === d2.getDate();
};

/** Obtiene el key del día de la semana para una fecha (lunes=0, martes=1...) */
const getDiaKey = (date) => {
    const diaSemana = DIAS_NOMBRES[date.getDay()];
    const idx = DIAS_LABELS.findIndex(d => d.key === diaSemana);
    return idx >= 0 ? DIAS_LABELS[idx].key : null;
};

// ─── Horarios por día ──────────────────────────────────────────────
const HORARIOS_SEMANA = {
    lunes: ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
    martes: ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
    miercoles: ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
    jueves: ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
    viernes: ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
    sabado: ['10:00-12:00']
};

const Pizarra = () => {
    const { tenant_id, usuario_id } = useAuth();

    // ─── Estado del selector de semana ───
    const hoy = useMemo(() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }, []);
    const [semanaOffset, setSemanaOffset] = useState(0);
    const diasSemana = useMemo(() => {
        const ref = new Date(hoy);
        ref.setDate(ref.getDate() + semanaOffset * 7);
        return generarSemana(ref);
    }, [hoy, semanaOffset]);

    // ─── Estado del día/hora ───
    const [diaSeleccionado, setDiaSeleccionado] = useState(null);  // objeto Date
    const [horaSeleccionada, setHoraSeleccionada] = useState(null);
    const [fechaCalculada, setFechaCalculada] = useState(null);

    // ─── Estado del formulario ───
    const [formData, setFormData] = useState({
        titulo: '',
        descripcion: '',
    });

    const [movimientosDisponibles, setMovimientosDisponibles] = useState([]);
    const [movimientoSeleccionado, setMovimientoSeleccionado] = useState('');
    const [movimientoPersonalizado, setMovimientoPersonalizado] = useState('');
    const [nuevoMovimiento, setNuevoMovimiento] = useState({
        series: '',
        repeticiones: '',
        peso: '',
        tiempo: '',
        notas: '',
    });
    const [movimientosAgregados, setMovimientosAgregados] = useState([]);
    const [mensaje, setMensaje] = useState(null);
    const [guardando, setGuardando] = useState(false);

    // ─── Estado del parser (lado derecho) ───
    const [textoLibre, setTextoLibre] = useState('');
    const [erroresParser, setErroresParser] = useState([]);
    const [procesando, setProcesando] = useState(false);

    // ─── Seleccionar día y hora ───
    const handleSeleccionarDiaHora = (fechaDate, horaStr) => {
        setDiaSeleccionado(fechaDate);
        setHoraSeleccionada(horaStr);

        // Extraer hora_inicio y hora_fin del string "7:00-8:00"
        let horaInicio = null;
        let horaFin = null;
        if (horaStr) {
            const partes = horaStr.split('-');
            if (partes.length === 2) {
                horaInicio = partes[0].trim();
                horaFin = partes[1].trim();
                const formatHora = (h) => {
                    const nums = h.split(':');
                    return `${String(parseInt(nums[0])).padStart(2, '0')}:${nums[1] ? String(parseInt(nums[1])).padStart(2, '0') : '00'}`;
                };
                horaInicio = formatHora(horaInicio);
                horaFin = formatHora(horaFin);
            }
        }

        const fechaStr = `${fechaDate.getFullYear()}-${String(fechaDate.getMonth() + 1).padStart(2, '0')}-${String(fechaDate.getDate()).padStart(2, '0')}`;
        setFechaCalculada({ fecha: fechaStr, hora_inicio: horaInicio, hora_fin: horaFin });
    };

    useEffect(() => {
        const cargarMovimientos = async () => {
            try {
                const response = await api.get(`/api/v1/movimientos?tenant_id=${tenant_id}`);
                setMovimientosDisponibles(response.data);
            } catch (error) {
                console.error('Error cargando movimientos:', error);
            }
        };
        cargarMovimientos();
    }, [tenant_id]);

    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value });
    };

    const handleNuevoMovimientoChange = (e) => {
        setNuevoMovimiento({ ...nuevoMovimiento, [e.target.name]: e.target.value });
    };

    // ─── Procesar texto libre con el parser ──────────────────────────────
    const handleProcesarTexto = async () => {
        if (!textoLibre.trim()) {
            setErroresParser(['El texto está vacío. Escribe al menos un movimiento.']);
            return;
        }

        setProcesando(true);
        setErroresParser([]);
        setMensaje(null);

        try {
            const response = await api.post(`/api/v1/wods/parse`, {
                texto: textoLibre,
                tenant_id: parseInt(tenant_id)
            });

            const data = response.data;
            const fases = data.fases || [];
            const errs = data.errores || [];

            setErroresParser(errs);

            if (fases.length > 0) {
                const nuevos = [];
                for (const fase of fases) {
                    for (const m of fase.movimientos) {
                        nuevos.push({
                            key: Date.now() + Math.random(),
                            movimiento_id: m.movimiento_id,
                            nombre: m.nombre,
                            orden: nuevos.length + 1,
                            series: m.series,
                            repeticiones: m.repeticiones || '',
                            peso: m.peso,
                            tiempo: '',
                            notas: '',
                            fase: fase.nombre,
                        });
                    }
                }

                if (nuevos.length > 0) {
                    setMovimientosAgregados(prev => [...prev, ...nuevos]);

                    if (errs.length === 0) {
                        setMensaje({ tipo: 'exito', texto: `${nuevos.length} movimiento(s) en ${fases.length} fase(s) procesado(s) correctamente` });
                    } else {
                        setMensaje({ tipo: 'warning', texto: `${nuevos.length} movimiento(s) procesado(s), ${errs.length} error(es)` });
                    }

                    if (errs.length === 0) {
                        setTextoLibre('');
                    }
                } else {
                    setErroresParser(['No se encontraron movimientos válidos en las fases detectadas']);
                    setMensaje({ tipo: 'error', texto: 'No se pudo procesar ningún movimiento' });
                }
            } else {
                if (errs.length === 0) {
                    setErroresParser(['No se encontraron movimientos válidos en el texto. Usa el formato: "NombreMovimiento 3x10" o separa por fases (CALENTAMIENTO, FUERZA, WOD)']);
                }
                setMensaje({ tipo: 'error', texto: 'No se pudo procesar ningún movimiento' });
            }
        } catch (error) {
            const detalle = error.response?.data?.detail || 'Error al conectar con el parser';
            setErroresParser([detalle]);
            setMensaje({ tipo: 'error', texto: detalle });
        } finally {
            setProcesando(false);
        }
    };

    // ─── Agregar movimiento manual ────────────────────────────────
    const agregarMovimiento = async () => {
        if (!movimientoSeleccionado) {
            setMensaje({ tipo: 'error', texto: 'Debes seleccionar un movimiento' });
            return;
        }

        if (movimientoSeleccionado === 'otro') {
            if (!movimientoPersonalizado.trim()) {
                setMensaje({ tipo: 'error', texto: 'Debes escribir el nombre del movimiento' });
                return;
            }
            try {
                const response = await api.post('/api/v1/movimientos', {
                    tenant_id: parseInt(tenant_id),
                    nombre: movimientoPersonalizado.trim(),
                    descripcion: `Movimiento libre: ${movimientoPersonalizado.trim()}`,
                    activo: true
                });
                const nuevoMov = response.data;

                const movs = await api.get(`/api/v1/movimientos?tenant_id=${tenant_id}`);
                setMovimientosDisponibles(movs.data);

                setMovimientosAgregados([
                    ...movimientosAgregados,
                    {
                        key: Date.now(),
                        movimiento_id: nuevoMov.id,
                        nombre: nuevoMov.nombre,
                        orden: movimientosAgregados.length + 1,
                        series: nuevoMovimiento.series ? parseInt(nuevoMovimiento.series) : null,
                        repeticiones: nuevoMovimiento.repeticiones || null,
                        peso: nuevoMovimiento.peso ? parseFloat(nuevoMovimiento.peso) : null,
                        tiempo: nuevoMovimiento.tiempo || null,
                        notas: nuevoMovimiento.notas || null,
                    }
                ]);

                setMovimientoSeleccionado('');
                setMovimientoPersonalizado('');
                setNuevoMovimiento({ series: '', repeticiones: '', peso: '', tiempo: '', notas: '' });
                return;
            } catch (error) {
                const detalle = error.response?.data?.detail || 'Error al crear movimiento';
                setMensaje({ tipo: 'error', texto: detalle });
                return;
            }
        }

        const movimiento = movimientosDisponibles.find(m => m.id === parseInt(movimientoSeleccionado));
        if (!movimiento) return;

        setMovimientosAgregados([
            ...movimientosAgregados,
            {
                key: Date.now(),
                movimiento_id: movimiento.id,
                nombre: movimiento.nombre,
                orden: movimientosAgregados.length + 1,
                series: nuevoMovimiento.series ? parseInt(nuevoMovimiento.series) : null,
                repeticiones: nuevoMovimiento.repeticiones || null,
                peso: nuevoMovimiento.peso ? parseFloat(nuevoMovimiento.peso) : null,
                tiempo: nuevoMovimiento.tiempo || null,
                notas: nuevoMovimiento.notas || null,
            }
        ]);

        setMovimientoSeleccionado('');
        setNuevoMovimiento({ series: '', repeticiones: '', peso: '', tiempo: '', notas: '' });
    };

    const eliminarMovimiento = (key) => {
        const actualizados = movimientosAgregados
            .filter(m => m.key !== key)
            .map((m, i) => ({ ...m, orden: i + 1 }));
        setMovimientosAgregados(actualizados);
    };

    // ─── Agrupar movimientos por fase ───
    const agruparMovimientosPorFase = () => {
        const tieneFases = movimientosAgregados.some(m => m.fase);
        if (!tieneFases) return null;

        const fasesMap = {};
        for (const m of movimientosAgregados) {
            const nombreFase = m.fase || 'SIN_CLASIFICAR';
            if (!fasesMap[nombreFase]) {
                fasesMap[nombreFase] = { nombre: nombreFase, descripcion: null, movimientos: [] };
            }
            fasesMap[nombreFase].movimientos.push({
                movimiento_id: m.movimiento_id,
                orden: m.orden,
                series: m.series,
                repeticiones: m.repeticiones,
                peso: m.peso,
                tiempo: m.tiempo,
                notas: m.notas,
            });
        }
        return Object.values(fasesMap);
    };

    const crearWod = async (estado) => {
        if (!fechaCalculada) {
            setMensaje({ tipo: 'error', texto: 'Debes seleccionar un día y horario de la grilla' });
            return;
        }
        if (movimientosAgregados.length === 0) {
            setMensaje({ tipo: 'error', texto: 'Debes agregar al menos un movimiento' });
            return;
        }

        setGuardando(true);
        setMensaje(null);

        try {
            const fasesAgrupadas = agruparMovimientosPorFase();

            let payload;
            const basePayload = {
                tenant_id: parseInt(tenant_id),
                fecha: fechaCalculada.fecha,
                hora_inicio: fechaCalculada.hora_inicio,
                hora_fin: fechaCalculada.hora_fin,
                titulo: formData.titulo || null,
                descripcion: formData.descripcion || null,
                estado: estado,
                coach_id: parseInt(usuario_id) || null,
            };

            if (fasesAgrupadas) {
                payload = { ...basePayload, fases: fasesAgrupadas };
            } else {
                payload = {
                    ...basePayload,
                    movimientos: movimientosAgregados.map(m => ({
                        movimiento_id: m.movimiento_id,
                        orden: m.orden,
                        series: m.series,
                        repeticiones: m.repeticiones,
                        peso: m.peso,
                        tiempo: m.tiempo,
                        notas: m.notas,
                        fase: m.fase || null,
                    })),
                };
            }

            await api.post(`/api/v1/wods?tenant_id=${tenant_id}`, payload);

            const textoEstado = estado === 'publicado' ? 'publicado' : 'guardado como borrador';
            setMensaje({ tipo: 'exito', texto: `WOD ${textoEstado} exitosamente` });

            // Limpiar formulario
            setFormData({ titulo: '', descripcion: '' });
            setDiaSeleccionado(null);
            setHoraSeleccionada(null);
            setFechaCalculada(null);
            setMovimientosAgregados([]);
            setTextoLibre('');
            setErroresParser([]);
        } catch (error) {
            const detalle = error.response?.data?.detail || 'Error al crear el WOD';
            setMensaje({ tipo: 'error', texto: detalle });
        } finally {
            setGuardando(false);
        }
    };

    const diaSeleccionadoKey = diaSeleccionado ? getDiaKey(diaSeleccionado) : null;

    return (
        <Layout>
            <div className="max-w-6xl mx-auto space-y-6">
                {/* Título */}
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">Pizarra de WOD</h1>
                    <p className="text-gray-600 mt-1">Selecciona día y horario para crear el entrenamiento</p>
                </div>

                {/* Mensaje */}
                {mensaje && (
                    <div className={`p-4 rounded-lg ${mensaje.tipo === 'exito'
                        ? 'bg-green-100 text-green-800 border border-green-300'
                        : mensaje.tipo === 'warning'
                            ? 'bg-yellow-100 text-yellow-800 border border-yellow-300'
                            : 'bg-red-100 text-red-800 border border-red-300'
                        }`}>
                        {mensaje.texto}
                    </div>
                )}

                {/* ─── SELECTOR DE SEMANA ─── */}
                <div className="bg-white rounded-lg shadow p-6">
                    <div className="flex items-center justify-between mb-6">
                        <button
                            onClick={() => setSemanaOffset(prev => prev - 1)}
                            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-bold text-lg"
                            title="Semana anterior"
                        >
                            ← Anterior
                        </button>
                        <div className="text-center">
                            <h2 className="text-lg font-bold text-gray-900">📅 {formatRangoSemana(diasSemana)}</h2>
                            <p className="text-sm text-gray-500">
                                {semanaOffset === 0 ? 'Semana actual' : semanaOffset < 0 ? `${Math.abs(semanaOffset)} semana(s) atrás` : `${semanaOffset} semana(s) adelante`}
                            </p>
                        </div>
                        <button
                            onClick={() => setSemanaOffset(prev => prev + 1)}
                            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-bold text-lg"
                            title="Semana siguiente"
                        >
                            Siguiente →
                        </button>
                    </div>

                    {/* ─── GRILLA VERTICAL POR DÍA ─── */}
                    <div className="space-y-4">
                        {diasSemana.map((fechaDate, idx) => {
                            const diaKey = getDiaKey(fechaDate);
                            if (!diaKey) return null; // domingo no mostramos
                            const horarios = HORARIOS_SEMANA[diaKey];
                            if (!horarios || horarios.length === 0) return null;
                            const esHoy = esMismoDia(fechaDate, hoy);
                            const fmt = formatFecha(fechaDate);

                            return (
                                <div
                                    key={idx}
                                    className={`rounded-xl border-2 p-4 transition-all ${esHoy
                                        ? 'border-orange-400 bg-orange-50/40 shadow-sm'
                                        : 'border-gray-200 hover:border-gray-300'
                                        } ${diaSeleccionado && esMismoDia(fechaDate, diaSeleccionado) ? 'ring-2 ring-orange-500' : ''}`}
                                >
                                    {/* Encabezado del día */}
                                    <div className="flex items-center justify-between mb-3">
                                        <div className="flex items-center gap-2">
                                            <span className="text-lg font-bold text-gray-800">{fmt.full}</span>
                                            {esHoy && (
                                                <span className="px-2 py-0.5 bg-orange-500 text-white text-xs font-bold rounded-full">
                                                    HOY
                                                </span>
                                            )}
                                        </div>
                                        {diaSeleccionado && esMismoDia(fechaDate, diaSeleccionado) && (
                                            <span className="text-sm font-medium text-orange-600">✓ Seleccionado</span>
                                        )}
                                    </div>

                                    {/* Horarios del día */}
                                    <div className="flex flex-wrap gap-2">
                                        {horarios.map((hora) => {
                                            const seleccionado = diaSeleccionado && esMismoDia(fechaDate, diaSeleccionado) && horaSeleccionada === hora;
                                            return (
                                                <button
                                                    key={hora}
                                                    onClick={() => handleSeleccionarDiaHora(fechaDate, hora)}
                                                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${seleccionado
                                                        ? 'bg-orange-500 text-white shadow-md ring-2 ring-orange-300'
                                                        : 'bg-gray-100 text-gray-600 border border-gray-200 hover:bg-orange-100 hover:text-orange-700 hover:border-orange-200'
                                                        }`}
                                                >
                                                    {hora}
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    {/* Día y hora seleccionados */}
                    {fechaCalculada && (
                        <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2">
                            <span className="text-lg">📅</span>
                            <span className="text-sm font-medium text-green-800">
                                Día y hora seleccionado: <strong>{diaSeleccionado ? formatFecha(diaSeleccionado).full : ''} — {horaSeleccionada}</strong>
                                {' | '}Fecha real: <strong>{fechaCalculada.fecha}</strong>
                            </span>
                            <span className="ml-auto text-green-600 text-lg">✅</span>
                        </div>
                    )}
                </div>

                {/* Información del WOD (título, descripción) */}
                <div className="bg-white rounded-lg shadow p-6 space-y-4">
                    <h2 className="text-lg font-bold text-gray-900">📝 Información del WOD</h2>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Título</label>
                            <input
                                type="text"
                                name="titulo"
                                value={formData.titulo}
                                onChange={handleChange}
                                placeholder="Ej: Upper Body Day"
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                            />
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Descripción</label>
                        <textarea
                            name="descripcion"
                            value={formData.descripcion}
                            onChange={handleChange}
                            placeholder="Notas generales del WOD..."
                            rows={3}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                        />
                    </div>
                </div>

                {/* ─── COLUMNAS DUALES: FORMULARIO + PARSER ──────────────── */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* ── COLUMNA IZQUIERDA: Formulario tradicional ── */}
                    <div className="bg-white rounded-lg shadow p-6 space-y-4">
                        <h2 className="text-lg font-bold text-gray-900">Movimientos (Manual)</h2>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Movimiento</label>
                                <select
                                    value={movimientoSeleccionado}
                                    onChange={(e) => setMovimientoSeleccionado(e.target.value)}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                                >
                                    <option value="">Seleccionar...</option>
                                    <option value="otro">✏️ Otro (movimiento libre)...</option>
                                    {movimientosDisponibles.map((m) => (
                                        <option key={m.id} value={m.id}>{m.nombre}</option>
                                    ))}
                                </select>
                                {movimientoSeleccionado === 'otro' && (
                                    <input
                                        type="text"
                                        value={movimientoPersonalizado}
                                        onChange={(e) => setMovimientoPersonalizado(e.target.value)}
                                        placeholder="Escribe el nombre del movimiento..."
                                        className="w-full px-3 py-2 mt-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                                    />
                                )}
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Series</label>
                                <input
                                    type="number"
                                    name="series"
                                    value={nuevoMovimiento.series}
                                    onChange={handleNuevoMovimientoChange}
                                    placeholder="Ej: 3"
                                    min="1"
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Repeticiones</label>
                                <input
                                    type="text"
                                    name="repeticiones"
                                    value={nuevoMovimiento.repeticiones}
                                    onChange={handleNuevoMovimientoChange}
                                    placeholder="Ej: 10-12"
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Peso (kg)</label>
                                <input
                                    type="number"
                                    name="peso"
                                    value={nuevoMovimiento.peso}
                                    onChange={handleNuevoMovimientoChange}
                                    placeholder="Ej: 50"
                                    min="0"
                                    step="0.5"
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Tiempo</label>
                                <select
                                    name="tiempo"
                                    value={nuevoMovimiento.tiempo}
                                    onChange={handleNuevoMovimientoChange}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                                >
                                    <option value="">Seleccionar tiempo...</option>
                                    <option value="1 min">1 min</option>
                                    <option value="2 min">2 min</option>
                                    <option value="3 min">3 min</option>
                                    <option value="4 min">4 min</option>
                                    <option value="5 min">5 min</option>
                                    <option value="6 min">6 min</option>
                                    <option value="7 min">7 min</option>
                                    <option value="8 min">8 min</option>
                                    <option value="9 min">9 min</option>
                                    <option value="10 min">10 min</option>
                                    <option value="15 min">15 min</option>
                                    <option value="20 min">20 min</option>
                                    <option value="25 min">25 min</option>
                                    <option value="30 min">30 min</option>
                                    <option value="35 min">35 min</option>
                                    <option value="40 min">40 min</option>
                                    <option value="45 min">45 min</option>
                                    <option value="50 min">50 min</option>
                                    <option value="55 min">55 min</option>
                                    <option value="60 min">60 min</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Notas</label>
                                <input
                                    type="text"
                                    name="notas"
                                    value={nuevoMovimiento.notas}
                                    onChange={handleNuevoMovimientoChange}
                                    placeholder="Ej: RX, Scaled..."
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                                />
                            </div>
                        </div>

                        <button
                            onClick={agregarMovimiento}
                            className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium w-full"
                        >
                            + Agregar Movimiento
                        </button>
                    </div>

                    {/* ── COLUMNA DERECHA: Parser de texto libre ── */}
                    <div className="bg-white rounded-lg shadow p-6 space-y-4">
                        <h2 className="text-lg font-bold text-gray-900">Pizarra (Texto Libre)</h2>
                        <p className="text-sm text-gray-500">
                            Escribe el WOD con el formato: <code className="bg-gray-100 px-1 rounded">Nombre 3x10</code> o <code className="bg-gray-100 px-1 rounded">Nombre 5x5 @ 80%</code>
                        </p>
                        <textarea
                            value={textoLibre}
                            onChange={(e) => {
                                setTextoLibre(e.target.value);
                                setErroresParser([]);
                            }}
                            placeholder={`Ejemplo:\nClean 5x3\nPush Press 3x5 @ 80%\nDeadlift 5x5\nBurpees 3x10\n\nNota: Describe el formato de rondas/AMRAP en la descripción del WOD, no aquí.`}
                            rows={10}
                            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent font-mono text-sm resize-y"
                        />

                        <button
                            onClick={handleProcesarTexto}
                            disabled={procesando || !textoLibre.trim()}
                            className="px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium disabled:opacity-50 w-full flex items-center justify-center gap-2"
                        >
                            {procesando ? (
                                <>
                                    <span className="animate-spin">⏳</span> Procesando...
                                </>
                            ) : (
                                <>⚡ Procesar Texto</>
                            )}
                        </button>

                        {erroresParser.length > 0 && (
                            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                                <p className="text-sm font-semibold text-red-800 mb-2">
                                    ⚠️ {erroresParser.length} error(es):
                                </p>
                                <ul className="list-disc list-inside space-y-1">
                                    {erroresParser.map((err, idx) => (
                                        <li key={idx} className="text-sm text-red-700">{err}</li>
                                    ))}
                                </ul>
                                <p className="text-xs text-red-600 mt-2">
                                    Corrige el texto y vuelve a presionar "Procesar Texto"
                                </p>
                            </div>
                        )}

                        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                            <p className="text-xs font-semibold text-gray-700 mb-2">📖 Formato aceptado:</p>
                            <div className="space-y-1 text-xs text-gray-600 font-mono">
                                <p><span className="text-green-600">✓</span> Clean <b>5x3</b></p>
                                <p><span className="text-green-600">✓</span> Push Press <b>3x5 @ 80%</b></p>
                                <p><span className="text-green-600">✓</span> Deadlift <b>5x5 @ 85%</b></p>
                                <p><span className="text-gray-400">—</span> AMRAP 10 min (saltado automáticamente)</p>
                                <p><span className="text-gray-400">—</span> 3 rounds of: (saltado automáticamente)</p>
                            </div>
                        </div>
                    </div>
                </div>

                {/* ─── LISTA DE MOVIMIENTOS AGREGADOS ─── */}
                {movimientosAgregados.length > 0 && (
                    <div className="bg-white rounded-lg shadow p-6">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-lg font-bold text-gray-900">
                                Movimientos del WOD ({movimientosAgregados.length})
                            </h3>
                            <span className="text-xs text-gray-500">
                                Puedes editar o eliminar movimientos antes de guardar
                            </span>
                        </div>
                        <div className="space-y-2">
                            {movimientosAgregados.map((m, idx) => (
                                <div
                                    key={m.key}
                                    className="flex items-center justify-between bg-gray-50 p-3 rounded-lg border border-gray-200 hover:border-orange-200 transition-colors"
                                >
                                    <div className="flex-1">
                                        <span className="font-medium text-gray-900">{idx + 1}. {m.nombre}</span>
                                        <div className="text-sm text-gray-600 mt-1 space-x-3">
                                            {m.series && <span>🔢 {m.series} series</span>}
                                            {m.repeticiones && <span>🔁 {m.repeticiones} reps</span>}
                                            {m.peso && <span>🏋️ {m.peso} kg</span>}
                                            {m.tiempo && <span>⏱️ {m.tiempo}</span>}
                                            {m.notas && <span className="italic">({m.notas})</span>}
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => eliminarMovimiento(m.key)}
                                        className="ml-3 p-2 text-red-600 hover:bg-red-100 rounded-lg transition-colors"
                                        title="Eliminar movimiento"
                                    >
                                        ✕
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* ─── BOTONES DE ACCIÓN ─── */}
                <div className="flex space-x-4">
                    <button
                        onClick={() => crearWod('draft')}
                        disabled={guardando || !fechaCalculada}
                        className="px-6 py-3 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition-colors font-medium disabled:opacity-50"
                    >
                        {guardando ? 'Guardando...' : 'Guardar como Borrador'}
                    </button>
                    <button
                        onClick={() => crearWod('publicado')}
                        disabled={guardando || !fechaCalculada}
                        className="px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium disabled:opacity-50"
                    >
                        {guardando ? 'Publicando...' : 'Publicar WOD'}
                    </button>
                </div>
            </div>
        </Layout>
    );
};

export default Pizarra;