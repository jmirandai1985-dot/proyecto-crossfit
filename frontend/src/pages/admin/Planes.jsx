import React, { useState } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import { usePlanes, useGuardarPlan, useEliminarPlan, SIN_DATOS } from '../../hooks/queries';

const TARJETAS = [
    { key: 'masculino', label: 'Masculino', barColor: 'border-l-blue-500', textColor: 'text-blue-400', genero: 'masculino', soloEstudiante: false },
    { key: 'femenino', label: 'Femenino', barColor: 'border-l-pink-500', textColor: 'text-pink-400', genero: 'femenino', soloEstudiante: false },
    { key: 'estudiante_m', label: 'Estudiante Masculino', barColor: 'border-l-blue-500', textColor: 'text-blue-400', genero: 'masculino', soloEstudiante: true },
    { key: 'estudiante_f', label: 'Estudiante Femenino', barColor: 'border-l-pink-500', textColor: 'text-pink-400', genero: 'femenino', soloEstudiante: true },
];

// Campos numéricos del modal y su default cuando el valor queda vacío o inválido.
// Mientras se edita se acepta el texto tal cual (incluido `''`): normalizar en el `onChange`
// con `parseInt(valor) || default` reponía el default en el acto y no dejaba escribir un
// número nuevo (en "Duración" saltaba a 30 apenas se borraba el campo).
const CAMPOS_NUMERICOS = { precio_clp: 0, creditos: 0, duracion_dias: 30 };

const aEntero = (valor, porDefecto) => {
    if (valor === '' || valor === null || valor === undefined) return porDefecto;
    const numero = parseInt(valor, 10);
    return Number.isNaN(numero) ? porDefecto : numero;
};

// Copia del formulario con los 3 numéricos ya convertidos a entero (se usa al guardar).
const normalizarNumericos = (datos) => {
    const normalizado = { ...datos };
    Object.keys(CAMPOS_NUMERICOS).forEach((campo) => {
        normalizado[campo] = aEntero(normalizado[campo], CAMPOS_NUMERICOS[campo]);
    });
    return normalizado;
};

const Planes = () => {
    const { tenant_id } = useAuth();
    // Bloque 3 (parte A): la lista sale de la caché compartida y las mutaciones invalidan
    // `['planes']`, el prefijo que también cubre `planesActivos` (lo que ve el alumno al
    // solicitar plan): guardar acá deja al día las dos pantallas.
    const { data, isPending } = usePlanes();
    const planes = data || SIN_DATOS;
    const guardar = useGuardarPlan();
    const eliminar = useEliminarPlan();
    const [formData, setFormData] = useState({ nombre: '', precio_clp: 0, creditos: 0, duracion_dias: 30, genero: 'masculino', activo: true, es_estudiante: false, requiere_certificado_estudiante: false });
    const [editingId, setEditingId] = useState(null);
    const [showForm, setShowForm] = useState(false);
    // Acordeón de categorías: arranca solo la primera abierta; se pueden abrir varias a la vez.
    const [openCategories, setOpenCategories] = useState({ masculino: true });
    const toggleCategory = (key) => setOpenCategories(prev => ({ ...prev, [key]: !prev[key] }));

    const openNew = (tarjeta) => {
        setEditingId(null);
        setFormData({
            nombre: '', precio_clp: 0, creditos: 0, duracion_dias: 30,
            genero: tarjeta.genero,
            activo: true,
            es_estudiante: tarjeta.soloEstudiante,
            // Al dar "Añadir" en una tarjeta de estudiante, el plan nuevo se crea
            // como estudiantil (requiere certificado) de una — consistente con el
            // criterio real de filtrado.
            requiere_certificado_estudiante: tarjeta.soloEstudiante,
        });
        setShowForm(true);
    };

    const openEdit = (p) => {
        setEditingId(p.id);
        setFormData({
            // `creditos` es la única columna nullable de las tres (NULL = plan sin cupo; la
            // marca de "ilimitado" vive aparte, en `es_ilimitado`, y no se edita en este modal).
            // El input muestra '' y, si no se toca, el submit lo normaliza al default (0).
            nombre: p.nombre, precio_clp: p.precio_clp, creditos: p.creditos ?? '',
            duracion_dias: p.duracion_dias,
            genero: p.genero || 'masculino',
            activo: p.activo ?? true,
            es_estudiante: p.es_estudiante ?? false,
            // Derivado: un plan de estudiante SIEMPRE pide certificado (fuente unica).
            requiere_certificado_estudiante: p.es_estudiante ?? false,
        });
        setShowForm(true);
    };

    // Al perder el foco, un campo vacío o inválido vuelve a su default (30 días / 0 / 0).
    // Mientras tanto el input muestra el texto que escribe el usuario, sin pisarlo.
    const normalizarCampo = (campo) => setFormData(prev => ({
        ...prev,
        [campo]: aEntero(prev[campo], CAMPOS_NUMERICOS[campo]),
    }));

    const handleSubmit = async (e) => {
        e.preventDefault();
        // Un submit con Enter puede llegar antes que el `onBlur` del input: se normalizan los
        // numéricos acá también (campo vacío o inválido -> default de cada uno).
        const formNormalizado = normalizarNumericos(formData);
        setFormData(formNormalizado);
        try {
            // `requiere_certificado_estudiante` se DERIVA de `es_estudiante` (fuente única
            // del filtrado de planes estudiantiles); el tenant sólo viaja al crear.
            const payload = {
                ...formNormalizado,
                requiere_certificado_estudiante: formData.es_estudiante,
                ...(editingId ? {} : { tenant_id }),
            };
            await guardar.mutateAsync({ id: editingId, payload });
            setShowForm(false);
        } catch (error) {
            alert('Error: ' + (error.response?.data?.detail || error.message));
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm('¿Eliminar este plan?')) return;
        try {
            await eliminar.mutateAsync(id);
        } catch (e) { alert('Error: ' + (e.response?.data?.detail || e.message)); }
    };

    const esPlanEstudiante = (p) => (p.requiere_certificado_estudiante || false) === true;

    // Regla de negocio (igual que la vista del alumno): un plan es
    // "estudiantil" si requiere_certificado_estudiante === true (NO
    // es_estudiante, que en los 6 planes con certificado quedó en False).
    const planesPorTarjeta = (tarjeta) => planes.filter(p =>
        p.genero === tarjeta.genero
        && esPlanEstudiante(p) === tarjeta.soloEstudiante
        && p.activo !== false
    );

    if (isPending) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div></div></Layout>);
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-zinc-100">Planes</h1><p className="text-zinc-400 mt-1">Administra los planes de suscripción</p></div>
                    <button onClick={() => openNew({ genero: 'masculino', soloEstudiante: false })} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Nuevo Plan</button>
                </div>

                <div className="space-y-3">
                    {TARJETAS.map(tarjeta => {
                        const planesTarjeta = planesPorTarjeta(tarjeta);
                        const abierta = !!openCategories[tarjeta.key];
                        return (
                            <div key={tarjeta.key} className="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-900/40">
                                <div className={`flex items-stretch border-l-4 ${tarjeta.barColor} bg-zinc-900/50`}>
                                    <button
                                        type="button"
                                        onClick={() => toggleCategory(tarjeta.key)}
                                        className="flex-1 flex items-center justify-between px-4 py-3 text-left hover:bg-zinc-800/40 transition-colors"
                                    >
                                        <span className={`text-base font-bold ${tarjeta.textColor}`}>
                                            {tarjeta.label}
                                            <span className="ml-2 text-zinc-500 font-normal text-sm">({planesTarjeta.length})</span>
                                        </span>
                                        <svg className={`w-4 h-4 shrink-0 text-zinc-500 transition-transform ${abierta ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                        </svg>
                                    </button>
                                    <button type="button" onClick={() => openNew(tarjeta)} className="m-2 px-3 py-1.5 bg-blue-900 text-white rounded hover:bg-blue-800 text-xs font-medium whitespace-nowrap">+ Añadir</button>
                                </div>
                                {abierta && (
                                    <div className="border-t border-zinc-800">
                                        {planesTarjeta.length === 0 ? (
                                            <div className="px-5 py-6 text-center text-zinc-500 text-sm">No hay planes en esta categoría</div>
                                        ) : (
                                            <div className="divide-y divide-zinc-800">
                                                {planesTarjeta.map(p => (
                                                    <div key={p.id} className="flex items-center justify-between px-4 py-3 hover:bg-zinc-800/30 transition-colors">
                                                        <div className="flex items-center gap-3 min-w-0">
                                                            <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${p.activo !== false ? 'bg-green-500' : 'bg-zinc-500'}`} title={p.activo !== false ? 'Activo' : 'Inactivo'} />
                                                            <div className="min-w-0">
                                                                <div className="flex items-center gap-2 flex-wrap">
                                                                    <span className="font-semibold text-zinc-100">{p.nombre}</span>
                                                                    {esPlanEstudiante(p) && (
                                                                        <span className="bg-amber-500 text-white uppercase text-[10px] font-semibold tracking-wide px-1.5 py-0.5 rounded">Estudiante</span>
                                                                    )}
                                                                </div>
                                                                <div className="text-sm text-zinc-400">
                                                                    ${(p.precio_clp || 0).toLocaleString()} · {p.creditos || 0} créditos · {p.duracion_dias || 0} días
                                                                </div>
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-3 shrink-0 ml-4">
                                                            <button onClick={() => openEdit(p)} className="text-blue-400 hover:text-blue-300 hover:underline text-sm">Editar</button>
                                                            <button onClick={() => handleDelete(p.id)} className="text-red-500 hover:text-red-400 hover:underline text-sm">Eliminar</button>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>

                {showForm && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                        <div className="bg-zinc-900 rounded-lg p-6 w-full max-w-md">
                            <h2 className="text-xl font-bold mb-4">{editingId ? 'Editar Plan' : 'Nuevo Plan'}</h2>
                            <form onSubmit={handleSubmit} className="space-y-4">
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Nombre</label>
                                    <input type="text" value={formData.nombre} onChange={e => setFormData({ ...formData, nombre: e.target.value })} required className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Precio ($)</label>
                                    <input type="number" value={formData.precio_clp} onChange={e => setFormData({ ...formData, precio_clp: e.target.value })} onBlur={() => normalizarCampo('precio_clp')} className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Créditos</label>
                                    <input type="number" value={formData.creditos} onChange={e => setFormData({ ...formData, creditos: e.target.value })} onBlur={() => normalizarCampo('creditos')} className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Duración (días)</label>
                                    <input type="number" value={formData.duracion_dias} onChange={e => setFormData({ ...formData, duracion_dias: e.target.value })} onBlur={() => normalizarCampo('duracion_dias')} className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Género</label>
                                    <select value={formData.genero} onChange={e => setFormData({ ...formData, genero: e.target.value })} className="w-full border rounded px-3 py-2">
                                        <option value="masculino">Masculino</option><option value="femenino">Femenino</option>
                                    </select></div>
                                {formData.es_estudiante && (
                                    <>
                                        <div className="flex items-center gap-2 mt-2">
                                            <span className="inline-block px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded text-xs font-medium">Creando/Editando plan estudiante</span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <input type="checkbox" checked={!!formData.es_estudiante} disabled readOnly
                                                className="w-4 h-4 text-orange-500 rounded opacity-70" id="req_cert" />
                                            <label htmlFor="req_cert" className="text-sm text-zinc-400">Requiere certificado de estudiante (automático: lo define "es plan de estudiante")</label>
                                        </div>
                                    </>
                                )}
                                <div className="flex items-center gap-2">
                                    <input type="checkbox" checked={formData.activo} onChange={e => setFormData({ ...formData, activo: e.target.checked })} id="activo" />
                                    <label htmlFor="activo" className="text-sm text-zinc-300">Activo</label>
                                </div>
                                <div className="flex gap-3 justify-end pt-2">
                                    <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 text-zinc-400 hover:bg-zinc-800 rounded">Cancelar</button>
                                    <button type="submit" className="px-4 py-2 bg-blue-900 text-white rounded hover:bg-blue-800">{editingId ? 'Guardar' : 'Crear'}</button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default Planes;