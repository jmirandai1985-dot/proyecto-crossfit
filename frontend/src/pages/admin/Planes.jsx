import React, { useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import { fmtFechaChile } from '../../utils/fecha';
// Reglas puras del ahorro de los planes largos (probadas sin navegador en
// `scripts/test-planes-larga-duracion.mjs`). El ahorro NO se guarda: se recalcula.
import {
    ahorroDelPlan, creditosDesdeClasesPorMes, esPlanLargo, mesesDelPlan,
    planesComparables,
} from '../../utils/planes';
import {
    usePlanes, useGuardarPlan, useEliminarPlan, useMatriculaConfig,
    useGuardarMatriculaConfig, SIN_DATOS,
} from '../../hooks/queries';

const TARJETAS = [
    { key: 'masculino', label: 'Masculino', barColor: 'border-l-blue-500', textColor: 'text-blue-400', genero: 'masculino', soloEstudiante: false },
    { key: 'femenino', label: 'Femenino', barColor: 'border-l-pink-500', textColor: 'text-pink-400', genero: 'femenino', soloEstudiante: false },
    { key: 'estudiante_m', label: 'Estudiante Masculino', barColor: 'border-l-blue-500', textColor: 'text-blue-400', genero: 'masculino', soloEstudiante: true },
    { key: 'estudiante_f', label: 'Estudiante Femenino', barColor: 'border-l-pink-500', textColor: 'text-pink-400', genero: 'femenino', soloEstudiante: true },
];

// Tarjeta PROPIA (misma jerarquía visual, al mismo nivel) de los planes UNISEX
// (`genero = NULL`): trimestral / semestral / anual. Los cuatro bloques de arriba
// NO se tocan. El criterio completo vive en `esPlanLargo` (utils/planes): exige
// comercial y con precio, así que el plan "Prueba" del alta y el "Pase de regreso"
// (los dos gratis) no aparecen acá.
const TARJETA_LARGA = {
    key: 'larga',
    label: 'Larga duración (unisex)',
    barColor: 'border-l-orange-500',
    textColor: 'text-orange-400',
    genero: null,
    soloEstudiante: false,
};

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

/** `$60.000` — mismo formato que las otras pantallas del panel. */
const fmtCLP = (monto) => `$${(Number(monto) || 0).toLocaleString('es-CL')}`;


const Planes = () => {
    const { tenant_id } = useAuth();
    // Bloque 3 (parte A): la lista sale de la caché compartida y las mutaciones invalidan
    // `['planes']`, el prefijo que también cubre `planesActivos` (lo que ve el alumno al
    // solicitar plan): guardar acá deja al día las dos pantallas.
    const { data, isPending } = usePlanes();
    const planes = data || SIN_DATOS;
    const guardar = useGuardarPlan();
    const eliminar = useEliminarPlan();
    const [formData, setFormData] = useState({
        nombre: '', precio_clp: 0, creditos: 0, duracion_dias: 30,
        genero: 'masculino', activo: true, es_estudiante: false,
        requiere_certificado_estudiante: false, es_ilimitado: false,
    });
    // "Clases por mes" es una CALCULADORA del formulario: no es una columna. Mientras
    // el admin no la toque (`clasesPorMesTocado` false) se respeta `creditos` tal cual
    // (un plan viejo de 100 créditos en 3 meses no se reescribe a 99 sin querer).
    const [clasesPorMes, setClasesPorMes] = useState('');
    const [clasesPorMesTocado, setClasesPorMesTocado] = useState(false);
    const [planReferenciaId, setPlanReferenciaId] = useState('');
    const [editingId, setEditingId] = useState(null);
    const [showForm, setShowForm] = useState(false);
    // Acordeón de categorías: arranca solo la primera abierta; se pueden abrir varias a la vez.
    const [openCategories, setOpenCategories] = useState({ masculino: true });
    const toggleCategory = (key) => setOpenCategories(prev => ({ ...prev, [key]: !prev[key] }));

    // ── Matrícula del box (panel superior) ──────────────────────────────────
    const { data: configMatricula } = useMatriculaConfig();
    const guardarMatricula = useGuardarMatriculaConfig();
    // `null` = "todavía no lo tocó": manda el valor del servidor. Se DERIVA en el
    // render (sin un efecto que copie estado) y, al guardar, se fija con la
    // respuesta del PUT (que ya trae la config nueva).
    const [matriculaActivaEdit, setMatriculaActivaEdit] = useState(null);
    const [matriculaMontoEdit, setMatriculaMontoEdit] = useState(null);
    // ── Feedback del guardado (3 piezas, cada una con su reloj) ─────────────
    //   · `toastMatricula`  → aviso flotante de éxito, se va solo a los 3 s.
    //   · `errorMatricula`  → error inline (rojo). NO se auto-oculta: si falló,
    //     el admin tiene que poder leer el motivo.
    //   · `guardadoMonto`   → pill "Guardado" DENTRO del input + pulso verde en
    //     el borde, 1,8 s. `guardadoSeq` re-monta el bloque en cada guardado para
    //     que la animación se reinicie si el admin guarda dos veces seguidas (si
    //     sólo se togglea la clase, React la deja puesta y el pulso no vuelve).
    const [toastMatricula, setToastMatricula] = useState(false);
    const [errorMatricula, setErrorMatricula] = useState('');
    const [guardadoMonto, setGuardadoMonto] = useState(false);
    const [guardadoSeq, setGuardadoSeq] = useState(0);
    const toastTimerRef = useRef(null);
    const guardadoTimerRef = useRef(null);
    useEffect(() => () => {
        clearTimeout(toastTimerRef.current);
        clearTimeout(guardadoTimerRef.current);
    }, []);
    const matriculaActiva = matriculaActivaEdit === null
        ? Boolean(configMatricula?.activa) : matriculaActivaEdit;
    const matriculaMonto = matriculaMontoEdit === null
        ? (configMatricula?.monto_clp ?? '') : matriculaMontoEdit;

    const guardarConfigMatricula = async () => {
        // Cada guardado arranca limpio: sin error viejo, sin toast viejo y sin el
        // pulso anterior (los timers se cancelan para no pisar el nuevo estado).
        setErrorMatricula('');
        setToastMatricula(false);
        setGuardadoMonto(false);
        clearTimeout(toastTimerRef.current);
        clearTimeout(guardadoTimerRef.current);
        try {
            const guardada = await guardarMatricula.mutateAsync({
                activa: Boolean(matriculaActiva),
                monto_clp: aEntero(matriculaMonto, 0),
            });
            setMatriculaActivaEdit(Boolean(guardada?.activa));
            setMatriculaMontoEdit(guardada?.monto_clp ?? '');
            // Éxito: toast 3 s + "Guardado" con pulso 1,8 s (el pulso son 2
            // repeticiones de 900 ms; el timer apaga la pill cuando termina).
            setToastMatricula(true);
            setGuardadoSeq((n) => n + 1);
            setGuardadoMonto(true);
            toastTimerRef.current = setTimeout(() => setToastMatricula(false), 3000);
            guardadoTimerRef.current = setTimeout(() => setGuardadoMonto(false), 1800);
        } catch (error) {
            setErrorMatricula(
                error.response?.data?.detail || 'No se pudo guardar la matrícula.');
        }
    };

    const openNew = (tarjeta) => {
        setEditingId(null);
        setFormData({
            nombre: '', precio_clp: 0, creditos: 0, duracion_dias: 30,
            // La tarjeta unisex crea el plan con `genero = null` (lo que la hace
            // aparecer en "Larga duración (unisex)" y en "Planes extendidos").
            genero: tarjeta.key === 'larga' ? '' : tarjeta.genero,
            activo: true,
            es_estudiante: tarjeta.soloEstudiante,
            // Al dar "Añadir" en una tarjeta de estudiante, el plan nuevo se crea
            // como estudiantil (requiere certificado) de una — consistente con el
            // criterio real de filtrado.
            requiere_certificado_estudiante: tarjeta.soloEstudiante,
            es_ilimitado: false,
        });
        setClasesPorMes('');
        setClasesPorMesTocado(false);
        setPlanReferenciaId('');
        setShowForm(true);
    };

    const openEdit = (p) => {
        // `requiere_certificado_estudiante` es la fuente REAL de "plan de
        // estudiante" (los 6 planes viejos tienen `es_estudiante = False` con el
        // certificado en True). Derivarlo al revés los degradaba al guardar.
        const esEstudiante = p.requiere_certificado_estudiante === true;
        const meses = mesesDelPlan(p.duracion_dias);
        setEditingId(p.id);
        setFormData({
            // `creditos` es la única columna nullable de las tres (NULL = plan sin cupo;
            // la marca de "ilimitado" vive aparte, en `es_ilimitado`).
            nombre: p.nombre, precio_clp: p.precio_clp, creditos: p.creditos ?? '',
            duracion_dias: p.duracion_dias,
            // `|| 'masculino'` convertía un plan UNISEX en masculino al guardar.
            genero: p.genero ?? '',
            activo: p.activo ?? true,
            es_estudiante: esEstudiante,
            requiere_certificado_estudiante: esEstudiante,
            es_ilimitado: p.es_ilimitado === true,
        });
        setClasesPorMes(
            p.es_ilimitado || p.creditos == null ? '' : String(Math.round(p.creditos / meses)));
        setClasesPorMesTocado(false);
        setPlanReferenciaId(p.plan_referencia_id ? String(p.plan_referencia_id) : '');
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
        const esEstudiante = Boolean(formNormalizado.es_estudiante);
        // Total de créditos: si el admin usó la calculadora, manda el producto
        // (clases por mes × meses); si no, el valor tal cual estaba.
        const totalCalculado = creditosDesdeClasesPorMes(
            clasesPorMes, formNormalizado.duracion_dias);
        const creditosFinal = clasesPorMesTocado && totalCalculado !== null
            ? totalCalculado
            : aEntero(formNormalizado.creditos, 0);
        try {
            // Payload EXPLÍCITO (el endpoint valida con `extra="forbid"`): lo que no
            // está en la lista no viaja, y lo que se quiere LIMPIAR viaja en `null`.
            const payload = {
                nombre: formNormalizado.nombre,
                precio_clp: formNormalizado.precio_clp,
                duracion_dias: formNormalizado.duracion_dias,
                creditos: formNormalizado.es_ilimitado ? 0 : creditosFinal,
                es_ilimitado: Boolean(formNormalizado.es_ilimitado),
                // `null` = plan UNISEX (categoría "Larga duración").
                genero: formNormalizado.genero || null,
                es_estudiante: esEstudiante,
                requiere_certificado_estudiante: esEstudiante,
                // La comparación de ahorro sólo tiene sentido en los planes unisex.
                plan_referencia_id: !formNormalizado.genero && planReferenciaId
                    ? Number(planReferenciaId) : null,
                activo: Boolean(formNormalizado.activo),
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
    const planesPorTarjeta = (tarjeta) => planes.filter(p => (tarjeta.key === 'larga'
        ? esPlanLargo(p)
        : p.genero === tarjeta.genero
            && esPlanEstudiante(p) === tarjeta.soloEstudiante
            && p.activo !== false));

    // Mensuales activos de las 4 categorías: candidatos a "comparar ahorro contra".
    const comparables = planesComparables(planes).filter((p) => p.id !== editingId);

    // Vista previa del formulario (misma aritmética que se guarda).
    const duracionFormulario = aEntero(formData.duracion_dias, 30);
    const mesesFormulario = mesesDelPlan(duracionFormulario);
    const totalDesdeClases = creditosDesdeClasesPorMes(clasesPorMes, duracionFormulario);
    const totalCreditosMostrado = clasesPorMesTocado && totalDesdeClases !== null
        ? totalDesdeClases
        : aEntero(formData.creditos, 0);

    // Ahorro de una fila de la tarjeta larga (recalculado con los precios de HOY).
    const ahorroDeFila = (p) => (p.plan_referencia_id
        ? ahorroDelPlan(p, planes.find((r) => r.id === p.plan_referencia_id) || null)
        : null);


    if (isPending) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div></div></Layout>);
    }

    return (
        <Layout>
            {/* Animaciones del feedback de matrícula. Van locales (no hay keyframes
                globales en el proyecto) y respetan `prefers-reduced-motion`. */}
            <style>{`
                @keyframes matricula-toast-in {
                    from { opacity: 0; transform: translateY(-16px); }
                    to   { opacity: 1; transform: translateY(0); }
                }
                .matricula-toast { animation: matricula-toast-in 350ms cubic-bezier(.16, 1, .3, 1) both; }

                @keyframes matricula-guardado-pulso {
                    0%   { box-shadow: 0 0 0 0 rgba(16, 185, 129, .55); }
                    60%  { box-shadow: 0 0 0 5px rgba(16, 185, 129, .16); }
                    100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
                }
                /* 2 repeticiones × 900 ms = 1,8 s */
                .matricula-guardado-pulso { animation: matricula-guardado-pulso 900ms ease-out 2; }

                @keyframes matricula-guardado-fade {
                    0%   { opacity: 0; transform: translateY(2px); }
                    12%  { opacity: 1; transform: translateY(0); }
                    75%  { opacity: 1; }
                    100% { opacity: 0; }
                }
                .matricula-guardado-fade { animation: matricula-guardado-fade 1800ms ease-out both; }

                @media (prefers-reduced-motion: reduce) {
                    .matricula-toast,
                    .matricula-guardado-pulso,
                    .matricula-guardado-fade { animation: none !important; }
                }
            `}</style>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-zinc-100">Planes</h1><p className="text-zinc-400 mt-1">Administra los planes de suscripción</p></div>
                    <button onClick={() => openNew(TARJETAS[0])} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Nuevo Plan</button>
                </div>

                {/* ── PARTE SUPERIOR: matrícula configurable (un valor por box) ── */}
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-5"
                    data-testid="panel-matricula">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                        <div>
                            <h2 className="text-base font-bold text-zinc-100">Matrícula</h2>
                            <p className="text-sm text-zinc-400 mt-1">
                                Cobro único para el <strong className="text-zinc-300">alumno nuevo</strong>
                                {' '}(sin membresía pagada previa). Se suma al plan al momento de pagar.
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={() => setMatriculaActivaEdit(!matriculaActiva)}
                            data-testid="toggle-matricula"
                            className={`px-4 py-2 rounded-lg text-sm font-bold transition-colors ${matriculaActiva
                                ? 'bg-emerald-600 text-white hover:bg-emerald-500'
                                : 'border border-zinc-700 text-zinc-300 hover:bg-zinc-800'}`}>
                            {matriculaActiva ? 'Activa' : 'Inactiva'}
                        </button>
                    </div>
                    <div className="mt-4 flex flex-wrap items-end gap-4">
                        <div>
                            <label htmlFor="matricula-monto"
                                className="block text-xs text-zinc-500 mb-1">Monto ($)</label>
                            {/* `key={guardadoSeq}` re-monta en cada guardado para que el pulso
                                verde vuelva a correr aunque se guarde dos veces seguidas. */}
                            <div key={guardadoSeq} className="relative w-44">
                                <input id="matricula-monto" type="number" min="0"
                                    value={matriculaMonto}
                                    onChange={(e) => setMatriculaMontoEdit(e.target.value)}
                                    data-testid="monto-matricula"
                                    className={`w-44 rounded-lg border border-zinc-700 bg-zinc-950 py-2 pl-3 text-sm text-zinc-100 ${guardadoMonto
                                        ? 'pr-[5.75rem] matricula-guardado-pulso'
                                        : 'pr-3'}`} />
                                {guardadoMonto && (
                                    <span
                                        data-testid="guardado-matricula"
                                        aria-live="polite"
                                        className="matricula-guardado-fade pointer-events-none absolute inset-y-0 right-2.5 flex items-center gap-1 text-[11px] font-semibold text-emerald-400">
                                        <Check size={14} strokeWidth={3} aria-hidden="true" />
                                        Guardado
                                    </span>
                                )}
                            </div>
                        </div>
                        {configMatricula?.activada_en && (
                            matriculaActiva ? (
                                <span
                                    data-testid="badge-matricula"
                                    className="inline-flex items-center gap-2 rounded-full border border-[#A7F3D0] bg-[#ECFDF5] px-3 py-1 text-xs font-semibold text-[#047857]">
                                    <span aria-hidden="true"
                                        className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                                    Activa desde el {fmtFechaChile(configMatricula.activada_en)}
                                </span>
                            ) : (
                                <span
                                    data-testid="badge-matricula"
                                    className="inline-flex items-center rounded-full border border-zinc-700 bg-zinc-800/60 px-3 py-1 text-xs font-semibold text-zinc-300">
                                    Última activación: {fmtFechaChile(configMatricula.activada_en)}
                                </span>
                            )
                        )}
                        <p className="text-sm text-zinc-400" data-testid="contador-matricula">
                            <strong className="text-zinc-200">
                                {configMatricula?.alumnos_cobrados ?? 0}
                            </strong>
                            {' '}alumnos nuevos cobrados hasta hoy
                        </p>
                        <button type="button" onClick={guardarConfigMatricula}
                            disabled={guardarMatricula.isPending}
                            data-testid="guardar-matricula"
                            className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm disabled:opacity-50">
                            {guardarMatricula.isPending ? 'Guardando...' : 'Guardar matrícula'}
                        </button>
                    </div>
                    {errorMatricula && (
                        <p role="alert" data-testid="mensaje-matricula"
                            className="mt-3 text-sm font-medium text-red-400">
                            {errorMatricula}
                        </p>
                    )}
                    {/* Toast flotante de éxito: fixed arriba a la derecha, entra con
                        slide-down + fade (350 ms) y se va solo a los 3 s. Es el
                        reemplazo del texto plano "Matrícula guardada.": el error
                        sigue siendo inline (arriba), para que se pueda leer. */}
                    {toastMatricula && (
                        <div role="status" aria-live="polite" data-testid="toast-matricula"
                            className="matricula-toast fixed right-4 top-4 z-[80] flex w-[min(92vw,22rem)] items-start gap-3 rounded-xl border border-emerald-500/25 bg-[#0F172A] p-4 shadow-2xl sm:right-6 sm:top-6">
                            <span aria-hidden="true"
                                className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white">
                                <Check size={20} strokeWidth={3} />
                            </span>
                            <div className="min-w-0">
                                <p className="text-sm font-bold text-white">Matrícula guardada</p>
                                <p className="mt-0.5 text-xs text-zinc-300">
                                    Los cambios se aplicaron correctamente
                                </p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="space-y-3">
                    {[...TARJETAS, TARJETA_LARGA].map(tarjeta => {
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
                                                {planesTarjeta.map(p => {
                                                    // Ahorro de los planes largos: se recalcula
                                                    // con los precios vigentes (no se guarda).
                                                    const ahorro = ahorroDeFila(p);
                                                    return (
                                                    <div key={p.id} className="flex items-center justify-between px-4 py-3 hover:bg-zinc-800/30 transition-colors">
                                                        <div className="flex items-center gap-3 min-w-0">
                                                            <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${p.activo !== false ? 'bg-green-500' : 'bg-zinc-500'}`} title={p.activo !== false ? 'Activo' : 'Inactivo'} />
                                                            <div className="min-w-0">
                                                                <div className="flex items-center gap-2 flex-wrap">
                                                                    <span className="font-semibold text-zinc-100">{p.nombre}</span>
                                                                    {esPlanEstudiante(p) && (
                                                                        <span className="bg-amber-500 text-white uppercase text-[10px] font-semibold tracking-wide px-1.5 py-0.5 rounded">Estudiante</span>
                                                                    )}
                                                                    {ahorro && (
                                                                        <span
                                                                            data-testid={`badge-ahorro-${p.id}`}
                                                                            className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase text-[10px] font-bold tracking-wide px-2 py-0.5 rounded-full">
                                                                            Ahorra {fmtCLP(ahorro.ahorro)} ({ahorro.pct}%)
                                                                        </span>
                                                                    )}
                                                                </div>
                                                                <div className="text-sm text-zinc-400">
                                                                    {fmtCLP(p.precio_clp)} · {p.es_ilimitado ? 'ilimitado' : `${p.creditos || 0} créditos`} · {p.duracion_dias || 0} días
                                                                </div>
                                                                {ahorro && (
                                                                    <div
                                                                        className="text-xs text-emerald-400/80"
                                                                        data-testid={`ahorro-detalle-${p.id}`}>
                                                                        vs. {ahorro.meses} {ahorro.meses === 1 ? 'mes' : 'meses'} de
                                                                        {' '}'{planes.find((r) => r.id === p.plan_referencia_id)?.nombre}'
                                                                        {' '}({fmtCLP(ahorro.contra)})
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-3 shrink-0 ml-4">
                                                            <button onClick={() => openEdit(p)} className="text-blue-400 hover:text-blue-300 hover:underline text-sm">Editar</button>
                                                            <button onClick={() => handleDelete(p.id)} className="text-red-500 hover:text-red-400 hover:underline text-sm">Eliminar</button>
                                                        </div>
                                                    </div>
                                                    );
                                                })}
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
                                {/* Ilimitado / Limitado: antes `es_ilimitado` NO se podía
                                    editar desde este modal (el PUT ya lo aceptaba). */}
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Clases</label>
                                    <div className="flex gap-2">
                                        <button type="button"
                                            data-testid="plan-limitado"
                                            onClick={() => setFormData({ ...formData, es_ilimitado: false })}
                                            className={`flex-1 px-3 py-2 rounded text-sm font-medium border transition-colors ${formData.es_ilimitado
                                                ? 'border-zinc-700 text-zinc-300 hover:bg-zinc-800'
                                                : 'border-orange-500 bg-orange-500/15 text-orange-300'}`}>
                                            Limitado
                                        </button>
                                        <button type="button"
                                            data-testid="plan-ilimitado"
                                            onClick={() => setFormData({ ...formData, es_ilimitado: true })}
                                            className={`flex-1 px-3 py-2 rounded text-sm font-medium border transition-colors ${formData.es_ilimitado
                                                ? 'border-orange-500 bg-orange-500/15 text-orange-300'
                                                : 'border-zinc-700 text-zinc-300 hover:bg-zinc-800'}`}>
                                            Ilimitado
                                        </button>
                                    </div>
                                </div>
                                {!formData.es_ilimitado && (
                                    <div>
                                        <label className="block text-sm font-medium text-zinc-300 mb-1">
                                            Clases por mes
                                        </label>
                                        <input type="number" min="0" value={clasesPorMes}
                                            data-testid="plan-clases-por-mes"
                                            onChange={(e) => {
                                                setClasesPorMes(e.target.value);
                                                setClasesPorMesTocado(true);
                                            }}
                                            className="w-full border rounded px-3 py-2" />
                                        <p className="text-xs text-zinc-500 mt-1"
                                            data-testid="plan-total-creditos">
                                            = {totalCreditosMostrado} créditos totales para los
                                            {' '}{duracionFormulario} días del plan
                                            {' '}({mesesFormulario} {mesesFormulario === 1 ? 'mes' : 'meses'})
                                        </p>
                                    </div>
                                )}
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Duración (días)</label>
                                    <input type="number" value={formData.duracion_dias} onChange={e => setFormData({ ...formData, duracion_dias: e.target.value })} onBlur={() => normalizarCampo('duracion_dias')} className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Género</label>
                                    <select value={formData.genero} onChange={e => setFormData({ ...formData, genero: e.target.value })} className="w-full border rounded px-3 py-2">
                                        <option value="masculino">Masculino</option><option value="femenino">Femenino</option>
                                        <option value="">Unisex (sin género)</option>
                                    </select></div>
                                {/* Comparar el ahorro contra un mensual: sólo tiene sentido
                                    en los planes UNISEX (los largos). */}
                                {!formData.genero && (
                                    <div>
                                        <label className="block text-sm font-medium text-zinc-300 mb-1">
                                            Comparar ahorro contra
                                        </label>
                                        <select value={planReferenciaId}
                                            onChange={e => setPlanReferenciaId(e.target.value)}
                                            data-testid="plan-referencia"
                                            className="w-full border rounded px-3 py-2">
                                            <option value="">Sin comparación (no mostrar ahorro)</option>
                                            {comparables.map((c) => (
                                                <option key={c.id} value={c.id}>
                                                    {c.nombre} — {fmtCLP(c.precio_clp)}
                                                </option>
                                            ))}
                                        </select>
                                        <p className="text-xs text-zinc-500 mt-1">
                                            Mensuales activos del box. El ahorro se recalcula con
                                            los precios vigentes de los dos planes.
                                        </p>
                                    </div>
                                )}
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