import React, { useState } from 'react';
import Layout from '../../components/Layout';
import { KpiCard } from '../../components/kpis/KpiCard';
import {
    useConfigurarPromocion, useMarcarRecuperado, useMigracionRecuperacion,
    usePreviewPromocionRecuperacion,
} from '../../hooks/queries';
import {
    BLOQUE_ALUMNOS, ESTADOS_RECUPERACION, TIPOS_BENEFICIO, badgeEstado, conteoPorEstado,
    esVencimientoValido, fechaEnDias, fechaParaInput, fechaTexto, filtrarAlumnos, hayFiltro,
    paginaAlumnos, pendientesPorRecuperar, porcentajeRecuperado, promocionCompleta,
    puedeConfigurarPromocion, puedeMarcarRecuperado, textoBeneficio, tieneCuenta,
    tipoBeneficioDe, totalAlumnos,
} from '../../utils/migracionRecuperacion';

/**
 * Formulario "Configurar promoción" de una fila del panel de recuperación.
 *
 * El admin elige TRES cosas y nada más (`PromocionRecuperacionIn` del backend):
 * tipo de beneficio, cantidad y fecha de vencimiento. La oferta se guarda y, en la misma
 * llamada, el backend manda el correo dedicado.
 *
 * `correo_enviado: false` NO es un fallo de la operación: la promoción quedó guardada y
 * el alumno NO se enteró. Ese caso se avisa con un mensaje propio (ámbar) en vez de
 * mostrarse como éxito (verde) o tragárselo: el admin tiene que contactarlo a mano.
 */
const FormularioPromocion = ({ alumno, onClose }) => {
    const configurar = useConfigurarPromocion();
    const [tipo, setTipo] = useState(TIPOS_BENEFICIO[0].key);
    const [cantidad, setCantidad] = useState(String(TIPOS_BENEFICIO[0].defecto));
    // Por defecto, dos semanas desde hoy: una oferta sin plazo no se puede canjear.
    const [vence, setVence] = useState(() => fechaEnDias(14));
    const [error, setError] = useState('');
    // Respuesta del backend (la oferta tal como quedó guardada).
    const [resultado, setResultado] = useState(null);

    const entrada = tipoBeneficioDe(tipo);
    const guardando = configurar.isPending;
    // Vista previa del correo: el hook la pide solo cuando están los TRES datos (con
    // debounce para no pegarle al backend en cada tecla) y el backend renderiza con la
    // MISMA función del envío real. El vencimiento viaja como en el POST: el día elegido
    // anclado al mediodía UTC (el backend lo lleva al fin del día chileno).
    const datosCompletos = promocionCompleta({ tipo, cantidad, vence });
    const preview = usePreviewPromocionRecuperacion({
        usuarioId: alumno.id,
        tipo,
        cantidad,
        venceEn: datosCompletos ? `${fechaParaInput(vence)}T12:00:00Z` : '',
    });

    const enviar = async (e) => {
        e.preventDefault();
        setError('');
        const n = Number(cantidad);
        if (!Number.isInteger(n) || n < 1) {
            setError('La cantidad tiene que ser un número entero de 1 o más.');
            return;
        }
        if (!esVencimientoValido(vence)) {
            setError('Elige una fecha de vencimiento de hoy en adelante.');
            return;
        }
        try {
            // El backend descarta la hora y guarda el FIN DE ESE DÍA en Chile, así que se
            // manda el día elegido anclado al mediodía UTC (nunca corre un día de fecha).
            const data = await configurar.mutateAsync({
                usuarioId: alumno.id,
                payload: {
                    tipo_beneficio: tipo,
                    cantidad: n,
                    vence_en: `${fechaParaInput(vence)}T12:00:00Z`,
                },
            });
            setResultado(data);
        } catch (err) {
            setError(err?.response?.data?.detail || 'No se pudo guardar la promoción.');
        }
    };

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
            role="dialog" aria-modal="true" data-testid="modal-promocion">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-xl max-h-[92vh] flex flex-col">
                <div className="flex items-start justify-between p-5 border-b border-zinc-800">
                    <div>
                        <h3 className="text-lg font-bold text-zinc-100">Configurar promoción</h3>
                        <p className="text-sm text-zinc-400">
                            Para <span className="text-zinc-100 font-medium">{alumno.nombre}</span>
                            {alumno.correo && ` · ${alumno.correo}`}
                        </p>
                    </div>
                    <button onClick={onClose} aria-label="Cerrar" data-testid="modal-promocion-cerrar"
                        className="text-zinc-400 hover:text-zinc-100 text-xl leading-none">×</button>
                </div>

                <form id="form-promocion" onSubmit={enviar} className="p-5 space-y-4 overflow-y-auto">
                    {error && (
                        <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-3 text-sm text-red-300"
                            data-testid="modal-promocion-error">
                            {error}
                        </div>
                    )}

                    {resultado ? (
                        // La oferta quedó guardada: lo que sigue es contarle al admin si el
                        // alumno se enteró o no (los dos casos se muestran, sin adornos).
                        <div
                            data-testid="modal-promocion-resultado"
                            className={`rounded p-3 text-sm border-l-4 ${resultado.correo_enviado
                                ? 'bg-emerald-500/10 border-emerald-500 text-emerald-200'
                                : 'bg-amber-500/10 border-amber-500 text-amber-200'}`}
                        >
                            {resultado.correo_enviado
                                ? 'La promoción quedó guardada y el correo salió al alumno.'
                                : 'La promoción quedó guardada, pero el correo NO se pudo enviar. '
                                  + 'El alumno todavía no sabe de la oferta: contáctalo a mano '
                                  + 'o vuelve a intentarlo más tarde.'}
                            <span className="block mt-1 text-[12.5px] text-zinc-300">
                                Ofrece {textoBeneficio(resultado.tipo_beneficio, resultado.cantidad)}{' '}
                                hasta el {fechaTexto(resultado.vence_en)}.
                            </span>
                        </div>
                    ) : (
                        <>
                            <div>
                                <label htmlFor="promocion-tipo"
                                    className="block text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                                    Tipo de beneficio
                                </label>
                                <select
                                    id="promocion-tipo"
                                    value={tipo}
                                    onChange={(e) => setTipo(e.target.value)}
                                    disabled={guardando}
                                    data-testid="modal-promocion-tipo"
                                    className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
                                >
                                    {TIPOS_BENEFICIO.map((t) => (
                                        <option key={t.key} value={t.key}>{t.label}</option>
                                    ))}
                                </select>
                            </div>

                            <div>
                                {/* El rótulo CAMBIA con el tipo: días, % o pesos. */}
                                <label htmlFor="promocion-cantidad"
                                    className="block text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                                    {entrada.etiquetaCantidad}
                                </label>
                                <input
                                    id="promocion-cantidad"
                                    type="number"
                                    min={1}
                                    step={1}
                                    value={cantidad}
                                    onChange={(e) => setCantidad(e.target.value)}
                                    disabled={guardando}
                                    data-testid="modal-promocion-cantidad"
                                    className="w-40 bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
                                />
                                {entrada.ayuda && (
                                    <span className="ml-3 text-xs text-zinc-500">{entrada.ayuda}</span>
                                )}
                            </div>

                            <div>
                                <label htmlFor="promocion-vence"
                                    className="block text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                                    Vence el
                                </label>
                                <input
                                    id="promocion-vence"
                                    type="date"
                                    value={vence}
                                    min={fechaEnDias(0)}
                                    onChange={(e) => setVence(e.target.value)}
                                    disabled={guardando}
                                    data-testid="modal-promocion-vence"
                                    className="bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
                                />
                                <span className="ml-3 text-xs text-zinc-500">
                                    Vale hasta el final de ese día (hora de Chile).
                                </span>
                            </div>

                            <p className="text-xs text-zinc-400" data-testid="modal-promocion-resumen">
                                Se le ofrece {textoBeneficio(tipo, Number(cantidad) || 0)}
                                {' '}y se le manda un correo con esa oferta.
                            </p>

                            {/* ── Vista previa del correo ANTES de confirmar ──
                                El asunto y el HTML los arma el BACKEND con la MISMA función
                                del envío real, así que esto es lo que recibe el alumno. Se
                                reusa el patrón de preview del BeneficioModal (iframe con
                                `srcDoc` + `sandbox`): el HTML es del propio proyecto y el
                                iframe lo aísla del CSS del panel. */}
                            <div className="rounded-lg border border-zinc-700 bg-zinc-800/40 p-3"
                                data-testid="modal-promocion-preview">
                                <p className="text-[11.5px] font-semibold uppercase tracking-wide text-zinc-400">
                                    Vista previa del correo
                                </p>
                                {!datosCompletos ? (
                                    <p className="text-xs text-zinc-500 mt-2"
                                        data-testid="modal-promocion-preview-placeholder">
                                        Completa los datos para ver la vista previa.
                                    </p>
                                ) : preview.isError ? (
                                    <p className="text-xs text-red-300 mt-2"
                                        data-testid="modal-promocion-preview-error">
                                        {preview.error?.response?.data?.detail
                                            || 'No se pudo generar la vista previa del correo.'}
                                    </p>
                                ) : !preview.data ? (
                                    <div className="flex justify-center py-6">
                                        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-orange-500" />
                                    </div>
                                ) : (
                                    <>
                                        <p className="text-sm mt-2 mb-2">
                                            <span className="text-zinc-500">Asunto:</span>{' '}
                                            <span className="text-zinc-100 font-medium"
                                                data-testid="modal-promocion-preview-asunto">
                                                {preview.data.asunto}
                                            </span>
                                        </p>
                                        <iframe
                                            title="Vista previa del correo de la promoción"
                                            srcDoc={preview.data.html}
                                            sandbox=""
                                            data-testid="modal-promocion-preview-html"
                                            className="w-full h-72 bg-white rounded-lg border border-zinc-700"
                                        />
                                    </>
                                )}
                            </div>
                        </>
                    )}
                </form>

                <div className="p-5 border-t border-zinc-800 flex justify-end gap-2">
                    <button type="button" onClick={onClose} data-testid="modal-promocion-cancelar"
                        className="px-4 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700">
                        {resultado ? 'Cerrar' : 'Cancelar'}
                    </button>
                    {!resultado && (
                        <button
                            type="submit"
                            form="form-promocion"
                            disabled={guardando}
                            data-testid="modal-promocion-enviar"
                            className="px-4 py-2 bg-orange-600 text-white rounded-lg text-sm font-bold hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {guardando ? 'Guardando...' : 'Guardar y enviar'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

/**
 * Panel de RECUPERACIÓN de la migración BoxMagic (Fase 5).
 *
 * TEMPORAL: es el panel con el que el box persigue a los ~712 alumnos que vienen de
 * BoxMagic y dejaron de venir. Cuando la migración termine se borran, de una sola vez, la
 * sección del menú (`config/menu.js`), las rutas de `App.jsx` y este archivo.
 *
 * LEE Y ESCRIBE (los dos endpoints ya existían desde la Fase 2):
 *   - `GET  /api/v1/migracion-boxmagic/recuperacion` lista a los CANDIDATOS del padrón
 *     de BoxMagic que están `Inactivo` (el padrón se carga con
 *     `scripts/importar_candidatos_boxmagic.py`; son los alumnos reales, SIN crearles
 *     cuenta todavía) y el estado de su última oferta. El criterio de quién está en la
 *     lista y el estado (`sin_contactar` / `promocion_enviada` / `vencida` /
 *     `recuperado`) los decide el backend: acá no se recalcula nada de eso.
 *   - `POST .../recuperacion/{usuario_id}/promocion` guarda la oferta y manda el correo
 *     dedicado. Necesita la CUENTA REAL del alumno: las filas del padrón que todavía no
 *     tienen cuenta no ofrecen la acción (se muestran igual, en `sin_contactar`).
 *   - `PUT  .../recuperacion/{usuario_id}/marcar-recuperado` marca que el alumno volvió.
 *
 * Interacción (mismo patrón que el panel de Activación): las 4 tarjetas son botones que
 * filtran la tabla, se prenden y se apagan con el mismo clic, y el filtro activo queda a
 * la vista en los chips. Los conteos, los badges, el texto de la oferta y el filtro viven
 * en `utils/migracionRecuperacion.js` (probado sin navegador).
 *
 * En el TELÉFONO (<768px) las tarjetas de estado van en una fila con scroll horizontal
 * propio y la tabla se reemplaza por una tarjeta por alumno, con los datos y las acciones
 * apilados. En >=768px se mantiene la tabla de siempre.
 */
const MigracionRecuperacion = () => {
    const { data, isPending, isFetching, isError, error, refetch } = useMigracionRecuperacion();
    const [estadoFiltro, setEstadoFiltro] = useState(null);
    // Buscador por nombre o correo: filtra la tabla EN VIVO en el cliente (la respuesta ya
    // trae la lista completa), así que escribir no dispara ninguna request.
    const [busqueda, setBusqueda] = useState('');
    // Cuántos resultados se pintan. Arranca en el primer bloque y "Cargar 25 más" lo
    // agranda (AGREGA filas, no reemplaza las que ya se están mirando). El reset a 25 NO
    // va en un efecto (dispararía un render de más): el estado guarda, junto al límite, la
    // "clave" de los filtros con la que se cargó, y si esa clave ya no coincide (cambió
    // una tarjeta, un chip o el texto buscado) se vuelve al primer bloque en el mismo
    // render.
    const claveFiltros = `${estadoFiltro ?? ''}|${busqueda}`;
    const [paginacion, setPaginacion] = useState({ clave: claveFiltros, limite: BLOQUE_ALUMNOS });
    const limite = paginacion.clave === claveFiltros ? paginacion.limite : BLOQUE_ALUMNOS;
    // Alumno cuya oferta se está configurando (null = formulario cerrado).
    const [alumnoFormulario, setAlumnoFormulario] = useState(null);
    // Fila con el "Marcar como recuperado" en vuelo (para deshabilitar ESE botón).
    const [marcandoId, setMarcandoId] = useState(null);
    // Aviso de la última acción (el marcado no cambia la fila de lugar: se confirma acá).
    const [aviso, setAviso] = useState(null);
    const marcarRecuperado = useMarcarRecuperado();

    const alumnos = data?.alumnos || [];
    const resumen = data?.resumen || {};
    // Derivaciones baratas: el backend ya mandó el resumen hecho y son cientos de filas.
    // Se calculan en el render, sin `useMemo` (mismo criterio que Activación).
    const conteo = conteoPorEstado(resumen);
    const total = totalAlumnos(resumen);
    const pendientes = pendientesPorRecuperar(resumen);
    const recuperados = conteo.recuperado;
    const avance = porcentajeRecuperado(resumen);

    const visibles = filtrarAlumnos(alumnos, { estado: estadoFiltro, busqueda });
    const conFiltro = hayFiltro({ estado: estadoFiltro, busqueda });
    // El bloque que se pinta (25) + los números del footer ("faltan Z"). Sólo en memoria.
    const bloque = paginaAlumnos(visibles, limite);

    const alternarEstado = (clave) => setEstadoFiltro((previa) => (previa === clave ? null : clave));
    const quitarFiltros = () => { setEstadoFiltro(null); setBusqueda(''); };
    const cargarMas = () => setPaginacion({ clave: claveFiltros, limite: limite + BLOQUE_ALUMNOS });

    const marcar = async (alumno) => {
        setMarcandoId(alumno.id);
        setAviso(null);
        try {
            await marcarRecuperado.mutateAsync(alumno.id);
            setAviso({ tipo: 'ok', texto: `${alumno.nombre} quedó marcado como recuperado.` });
        } catch (err) {
            // El 404 ("El alumno no tiene una promoción vigente") es un dato real: se
            // muestra tal cual en vez de un mensaje genérico.
            setAviso({
                tipo: 'error',
                texto: err?.response?.data?.detail || 'No se pudo marcar como recuperado.',
            });
        } finally {
            setMarcandoId(null);
        }
    };

    const mensajeError = error?.response?.data?.detail || 'No se pudo cargar el panel de recuperación.';

    if (isPending) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-64">
                    <div className="animate-spin rounded-full h-10 w-10 border-4 border-orange-500 border-t-transparent" />
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
                    <div>
                        <h1 className="text-2xl font-extrabold text-zinc-100">
                            Panel de Recuperación — Migración BoxMagic
                        </h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            Los alumnos que en BoxMagic figuran Inactivo, con la oferta que se les envió.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => refetch()}
                        disabled={isFetching}
                        aria-busy={isFetching}
                        title="Volver a pedir la lista al servidor"
                        className="inline-flex shrink-0 items-center justify-center gap-2 px-4 py-2 rounded-xl border border-zinc-700 bg-zinc-800 text-zinc-200 text-sm font-bold transition hover:border-orange-500 hover:text-orange-400 active:border-orange-500 active:bg-zinc-700 active:text-orange-400 active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                        {/* El spinner ocupa su lugar SIEMPRE (invisible cuando no carga): así el
                            botón no cambia de ancho al empezar/terminar la request. */}
                        <span
                            aria-hidden="true"
                            className={`h-3.5 w-3.5 rounded-full border-2 border-orange-500 border-t-transparent ${isFetching ? 'animate-spin' : 'invisible'}`}
                        />
                        Actualizar
                    </button>
                </div>

                {isError && (
                    <div className="mb-4 rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-[13px] text-red-200">
                        {mensajeError}
                        <button type="button" onClick={() => refetch()} className="ml-3 underline font-semibold">
                            Reintentar
                        </button>
                    </div>
                )}

                {/* Resultado de la última acción de la tabla (marcar recuperado). */}
                {aviso && (
                    <div
                        data-testid="aviso-recuperacion"
                        className={`mb-4 rounded-2xl border px-4 py-3 text-[13px] ${aviso.tipo === 'ok'
                            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                            : 'border-red-500/40 bg-red-500/10 text-red-200'}`}
                    >
                        {aviso.texto}
                    </div>
                )}

                {/* ── Pendientes por recuperar: el número que importa + avance ── */}
                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 mb-4">
                    <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
                        <div>
                            <p className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">
                                Pendientes por recuperar
                            </p>
                            <p className="text-3xl font-extrabold text-zinc-100 mt-1" data-testid="pendientes-por-recuperar">
                                {pendientes}
                            </p>
                            <p className="text-[12px] text-zinc-500 mt-1">
                                de {total} alumnos inactivos
                            </p>
                        </div>
                        <p className="text-sm text-zinc-400">
                            <span className="font-extrabold text-emerald-400">{recuperados}</span>
                            {' '}ya volvieron ({avance}%)
                        </p>
                    </div>
                    <div
                        className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-800"
                        role="progressbar"
                        aria-valuenow={avance}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label="Porcentaje de alumnos inactivos que ya volvieron"
                        data-testid="barra-avance-recuperacion"
                    >
                        <div
                            className="h-full rounded-full bg-emerald-500 transition-all"
                            style={{ width: `${avance}%` }}
                        />
                    </div>
                </div>

                {/* ── Las 4 tarjetas: CLICKEABLES, filtran la tabla por estado ──
                    En el TELÉFONO van en UNA fila con scroll horizontal propio (el scroll
                    no arrastra la página); desde 768px vuelve a la grilla de siempre. */}
                <div className="mb-4 flex snap-x gap-3 overflow-x-auto p-1 md:grid md:grid-cols-2 md:overflow-visible md:p-0 lg:grid-cols-4">
                    {ESTADOS_RECUPERACION.map((estado) => {
                        const activa = estadoFiltro === estado.key;
                        return (
                            <button
                                key={estado.key}
                                type="button"
                                onClick={() => alternarEstado(estado.key)}
                                aria-pressed={activa}
                                aria-label={`Filtrar la tabla por el estado: ${estado.label}`}
                                title={activa ? 'Quitar este filtro' : `Filtrar la tabla por ${estado.label}`}
                                data-testid={`tarjeta-estado-${estado.key}`}
                                className={`w-40 shrink-0 snap-start text-left rounded-lg transition active:scale-[0.97] md:w-auto ${activa
                                    ? 'ring-2 ring-orange-500'
                                    : 'hover:ring-1 hover:ring-zinc-600 active:ring-2 active:ring-orange-500'}`}
                            >
                                <KpiCard
                                    label={estado.label}
                                    value={conteo[estado.key]}
                                    color={estado.color}
                                />
                            </button>
                        );
                    })}
                </div>

                {/* ── Filtros activos (se quitan uno por uno o con "Ver todos") ── */}
                {conFiltro && (
                    <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="filtros-activos">
                        <span className="text-xs text-zinc-500">Filtrando:</span>
                        {estadoFiltro && (
                            <button
                                type="button"
                                onClick={() => setEstadoFiltro(null)}
                                className="px-3 py-1 rounded-full text-xs font-semibold border border-orange-500/40 bg-orange-500/10 text-orange-400 hover:bg-orange-500/20 transition-colors"
                            >
                                Estado: {badgeEstado(estadoFiltro).texto} <span aria-hidden="true">×</span>
                            </button>
                        )}
                        {busqueda.trim() && (
                            <button
                                type="button"
                                onClick={() => setBusqueda('')}
                                title="Limpiar la búsqueda"
                                className="px-3 py-1 rounded-full text-xs font-semibold border border-zinc-600 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
                            >
                                Buscar: {busqueda.trim()} <span aria-hidden="true">×</span>
                            </button>
                        )}
                        <button type="button" onClick={quitarFiltros} className="ml-1 text-xs font-semibold text-zinc-400 underline">
                            Ver todos
                        </button>
                    </div>
                )}

                {/* ── Buscador por nombre o correo: filtra la tabla EN VIVO ──
                    Sin request: la lista ya está en memoria. Se combina con las tarjetas
                    de estado. */}
                <input
                    type="text"
                    value={busqueda}
                    onChange={(e) => setBusqueda(e.target.value)}
                    placeholder="Buscar por nombre o correo..."
                    aria-label="Buscar alumno por nombre o correo"
                    data-testid="buscar-recuperacion"
                    className="mb-3 w-full px-4 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 bg-zinc-800 text-zinc-100 placeholder:text-zinc-500"
                />

                {/* ── Vista MÓVIL (<768px): una tarjeta por alumno con los datos y las
                    acciones apilados. La tabla de 6 columnas no entra en un teléfono; en
                    >=768px esta vista no se muestra (el escritorio sigue igual). */}
                <ul data-testid="padron-recuperacion-movil" className="md:hidden space-y-2">
                    {bloque.mostrados.length > 0 ? bloque.mostrados.map((alumno) => {
                        const badge = badgeEstado(alumno.estado);
                        const promo = alumno.promocion;
                        const configurable = puedeConfigurarPromocion(alumno);
                        const marcable = puedeMarcarRecuperado(alumno);
                        const enVuelo = marcandoId === alumno.id;
                        // Misma clave que la fila de escritorio: `candidato_id` es el padrón
                        // e `id` la cuenta REAL (null mientras no exista).
                        const clave = alumno.candidato_id ?? alumno.id;
                        return (
                            <li
                                key={clave}
                                data-alumno-id={clave}
                                data-testid={`alumno-movil-${clave}`}
                                className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-3"
                            >
                                <p className="text-sm font-bold text-zinc-100 break-words">{alumno.nombre}</p>
                                <p className="mt-0.5 text-[12.5px] text-zinc-400 break-all">{alumno.correo}</p>
                                <dl className="mt-3 space-y-2">
                                    <div>
                                        <dt className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                                            Última asistencia
                                        </dt>
                                        <dd className="text-sm text-zinc-300">
                                            {alumno.ultima_asistencia
                                                ? fechaTexto(alumno.ultima_asistencia)
                                                : '—'}
                                            <span className="block text-[11.5px] text-zinc-500">
                                                {alumno.dias_ausente === null || alumno.dias_ausente === undefined
                                                    ? 'Sin historial de asistencia'
                                                    : `${alumno.dias_ausente} día${alumno.dias_ausente === 1 ? '' : 's'} ausente`}
                                            </span>
                                        </dd>
                                    </div>
                                    <div className="flex items-center justify-between gap-2">
                                        <dt className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Estado</dt>
                                        <dd>
                                            <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${badge.clase}`}>
                                                {badge.texto}
                                            </span>
                                        </dd>
                                    </div>
                                    <div>
                                        <dt className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Promoción</dt>
                                        <dd>
                                            {promo ? (
                                                <>
                                                    <span className="text-sm text-zinc-100">
                                                        {textoBeneficio(promo.tipo_beneficio, promo.cantidad)}
                                                    </span>
                                                    <span className="block text-[11.5px] text-zinc-500">
                                                        {promo.vence_en ? `Vence el ${fechaTexto(promo.vence_en)}` : 'Sin fecha de vencimiento'}
                                                    </span>
                                                </>
                                            ) : (
                                                <span className="text-sm text-zinc-500">Sin oferta</span>
                                            )}
                                        </dd>
                                    </div>
                                </dl>
                                {(configurable || marcable) && (
                                    <div className="mt-3 flex flex-col gap-2">
                                        {configurable && (
                                            <button
                                                type="button"
                                                onClick={() => { setAviso(null); setAlumnoFormulario(alumno); }}
                                                data-testid={`configurar-promocion-movil-${alumno.id}`}
                                                className="w-full px-3 py-2 rounded-lg text-xs font-bold bg-orange-600 text-white transition hover:bg-orange-700 active:bg-orange-700 active:scale-[0.98]"
                                            >
                                                Configurar promoción
                                            </button>
                                        )}
                                        {marcable && (
                                            <button
                                                type="button"
                                                onClick={() => marcar(alumno)}
                                                disabled={enVuelo}
                                                data-testid={`marcar-recuperado-movil-${alumno.id}`}
                                                className="w-full px-3 py-2 rounded-lg text-xs font-bold bg-emerald-600 text-white transition hover:bg-emerald-700 active:bg-emerald-700 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
                                            >
                                                {enVuelo ? 'Marcando...' : 'Marcar como recuperado'}
                                            </button>
                                        )}
                                    </div>
                                )}
                                {!configurable && !marcable && (
                                    <p className="mt-2 text-[11.5px] text-zinc-500">
                                        {tieneCuenta(alumno)
                                            ? '—'
                                            : 'Sin cuenta todavía'}
                                    </p>
                                )}
                            </li>
                        );
                    }) : (
                        <li className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-8 text-center text-sm text-zinc-400">
                            {alumnos.length === 0
                                ? 'El padrón de BoxMagic no tiene alumnos inactivos cargados todavía.'
                                : 'Ningún alumno coincide con el filtro.'}
                        </li>
                    )}
                </ul>

                {/* ── Vista de ESCRITORIO (>=768px): la tabla de siempre ── */}
                <div className="hidden md:block overflow-x-auto rounded-2xl border border-zinc-800 bg-zinc-900">
                    <table className="w-full">
                        <thead className="bg-zinc-800/60">
                            <tr>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Nombre</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Correo</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Última asistencia</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Estado</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Promoción</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Acción</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800">
                            {bloque.mostrados.length > 0 ? bloque.mostrados.map((alumno) => {
                                const badge = badgeEstado(alumno.estado);
                                const promo = alumno.promocion;
                                const configurable = puedeConfigurarPromocion(alumno);
                                const marcable = puedeMarcarRecuperado(alumno);
                                const enVuelo = marcandoId === alumno.id;
                                // Clave de la fila = `candidato_id` (el padrón). `id` es la
                                // cuenta REAL y viene en null mientras no exista.
                                const clave = alumno.candidato_id ?? alumno.id;
                                return (
                                    <tr key={clave} data-alumno-id={clave} className="hover:bg-zinc-800/40">
                                        <td className="px-6 py-3 text-sm font-medium text-zinc-100">{alumno.nombre}</td>
                                        <td className="px-6 py-3 text-sm text-zinc-400">{alumno.correo}</td>
                                        <td className="px-6 py-3 text-sm text-zinc-300">
                                            {alumno.ultima_asistencia
                                                ? fechaTexto(alumno.ultima_asistencia)
                                                : '—'}
                                            <span className="block text-[11.5px] text-zinc-500">
                                                {alumno.dias_ausente === null || alumno.dias_ausente === undefined
                                                    ? 'Sin historial de asistencia'
                                                    : `${alumno.dias_ausente} día${alumno.dias_ausente === 1 ? '' : 's'} ausente`}
                                            </span>
                                        </td>
                                        <td className="px-6 py-3 text-sm">
                                            <span className={`px-3 py-1 rounded-full text-xs font-medium border ${badge.clase}`}>
                                                {badge.texto}
                                            </span>
                                        </td>
                                        <td className="px-6 py-3 text-sm">
                                            {promo ? (
                                                <>
                                                    <span className="text-zinc-100">
                                                        {textoBeneficio(promo.tipo_beneficio, promo.cantidad)}
                                                    </span>
                                                    <span className="block text-[11.5px] text-zinc-500">
                                                        {promo.vence_en ? `Vence el ${fechaTexto(promo.vence_en)}` : 'Sin fecha de vencimiento'}
                                                    </span>
                                                </>
                                            ) : (
                                                <span className="text-zinc-500">Sin oferta</span>
                                            )}
                                        </td>
                                        <td className="px-6 py-3 text-sm">
                                            {configurable && (
                                                <button
                                                    type="button"
                                                    onClick={() => { setAviso(null); setAlumnoFormulario(alumno); }}
                                                    data-testid={`configurar-promocion-${alumno.id}`}
                                                    className="px-3 py-1.5 rounded-lg text-xs font-bold bg-orange-600 text-white hover:bg-orange-700 transition-colors"
                                                >
                                                    Configurar promoción
                                                </button>
                                            )}
                                            {marcable && (
                                                <button
                                                    type="button"
                                                    onClick={() => marcar(alumno)}
                                                    disabled={enVuelo}
                                                    data-testid={`marcar-recuperado-${alumno.id}`}
                                                    className="px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-600 text-white hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                                >
                                                    {enVuelo ? 'Marcando...' : 'Marcar como recuperado'}
                                                </button>
                                            )}
                                            {!configurable && !marcable && (
                                                <span className="text-[11.5px] text-zinc-500">
                                                    {tieneCuenta(alumno)
                                                        ? '—'
                                                        : 'Sin cuenta todavía'}
                                                </span>
                                            )}
                                        </td>
                                    </tr>
                                );
                            }) : (
                                <tr>
                                    <td colSpan={6} className="px-6 py-8 text-center text-sm text-zinc-400">
                                        {alumnos.length === 0
                                            ? 'El padrón de BoxMagic no tiene alumnos inactivos cargados todavía.'
                                            : 'Ningún alumno coincide con el filtro.'}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>

                <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <p className="text-[12px] text-zinc-500" data-testid="footer-listado-recuperacion">
                        Mostrando <span className="font-bold text-zinc-300">{bloque.mostrados.length}</span> de{' '}
                        <span className="font-bold text-zinc-300">{bloque.total}</span>
                        {bloque.faltan > 0 && (
                            <> — faltan <span className="font-bold text-zinc-300">{bloque.faltan}</span></>
                        )}.
                        <span className="mt-1 block">
                            &quot;Pendientes por recuperar&quot; son los que todavía no volvieron.
                        </span>
                    </p>
                    {bloque.hayMas && (
                        <button
                            type="button"
                            onClick={cargarMas}
                            data-testid="cargar-mas-recuperacion"
                            className="shrink-0 rounded-xl border border-zinc-700 bg-zinc-800 px-4 py-2 text-sm font-bold text-zinc-200 transition hover:border-orange-500 hover:text-orange-400 active:border-orange-500 active:bg-zinc-700 active:text-orange-400 active:scale-[0.98]"
                        >
                            Cargar {BLOQUE_ALUMNOS} más
                        </button>
                    )}
                </div>
            </div>

            {/* La oferta se configura en un modal: la tabla queda detrás, a la vista. */}
            {alumnoFormulario && (
                <FormularioPromocion
                    alumno={alumnoFormulario}
                    onClose={() => setAlumnoFormulario(null)}
                />
            )}
        </Layout>
    );
};

export default MigracionRecuperacion;

