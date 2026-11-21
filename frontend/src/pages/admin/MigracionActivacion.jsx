import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Mail, Pencil, Send } from 'lucide-react';
import Layout from '../../components/Layout';
import { KpiCard } from '../../components/kpis/KpiCard';
import EditarCandidatoBoxmagic from '../../components/EditarCandidatoBoxmagic';
import {
    useEnviarActivacionMasiva, useGuardarCorreoCandidato, useMigracionActivacion,
} from '../../hooks/queries';
import {
    BLOQUE_ALUMNOS, ETAPAS_ACTIVACION, activadosHoy, badgeEtapa,
    candidatosParaMigrar, candidatosSinCorreo, conteoPorEtapa, filtrarAlumnos,
    hayFiltro, paginaAlumnos, pendientesPorActivar, porcentajeComprado, totalAlumnos,
} from '../../utils/migracionActivacion';

/**
 * Panel de ACTIVACIÓN de la migración BoxMagic (Fase 4).
 *
 * TEMPORAL: es el panel de control de la carga de los ~712 alumnos reales desde
 * BoxMagic. Cuando la migración termine se borran, de una sola vez, la sección del menú
 * (`config/menu.js`), las rutas de `App.jsx` y este archivo.
 *
 * LEE el embudo (en qué etapa está cada alumno y el resumen con los activados de las
 * últimas 24 h) del backend en `GET /api/v1/migracion-boxmagic/activacion`. La ÚNICA
 * escritura es la corrección del padrón (nombre/correo con el lápiz "Editar"), porque
 * el Excel real puede traer correos truncados; nada toca la cuenta del alumno.
 *
 * Interacción (mismo patrón que Fidelización): las tarjetas son botones que filtran la
 * tabla de abajo, se prenden y se apagan con el mismo clic, y el filtro activo queda a
 * la vista en los chips. Los conteos y las reglas del filtro viven en
 * `utils/migracionActivacion.js` (probado sin navegador).
 *
 * En el TELÉFONO (<768px) las tarjetas de etapa van en una fila con scroll horizontal
 * propio y la tabla se reemplaza por una tarjeta por alumno (Nombre/Correo/Etapa/Plan
 * apilados). En >=768px se mantiene la tabla de siempre.
 */
const MigracionActivacion = () => {
    const { data, isPending, isFetching, isError, error, refetch } = useMigracionActivacion();
    // Envío masivo del correo de activación (sólo Activos) y correo puntual de una
    // fila que llegó sin email.
    const enviarActivacion = useEnviarActivacionMasiva();
    const guardarCorreo = useGuardarCorreoCandidato();
    // Filtros de la tabla. Se COMBINAN entre sí (etapa + "se activaron hoy") y, encima de
    // los dos, el buscador de texto.
    const [etapaFiltro, setEtapaFiltro] = useState(null);
    const [soloHoy, setSoloHoy] = useState(false);
    // Buscador por nombre o correo: filtra la tabla EN VIVO en el cliente (el backend ya
    // mandó el padrón completo en esta misma respuesta), así que escribir no dispara
    // ninguna request.
    const [busqueda, setBusqueda] = useState('');
    // Candidato abierto en el modal de corrección del padrón (nombre/correo).
    const [alumnoEditar, setAlumnoEditar] = useState(null);
    // ── Envío masivo del correo de activación ──
    // "Faltan correos" arranca ABIERTO: es lo primero que el admin tiene que ver
    // antes de apretar el botón. El borrador del input se guarda por `candidato_id`
    // y no se pierde si la consulta se refresca mientras escribe.
    const [faltanAbiertas, setFaltanAbiertas] = useState(true);
    const [correosBorrador, setCorreosBorrador] = useState({});
    const [erroresCorreo, setErroresCorreo] = useState({});
    const [guardandoCorreoId, setGuardandoCorreoId] = useState(null);
    const [resultadoEnvio, setResultadoEnvio] = useState(null);
    const [errorEnvio, setErrorEnvio] = useState('');
    // Toggle de seguridad: el botón "Comenzar migración" queda bloqueado hasta que
    // el admin lo arme explícitamente. Se resetea al recargar la página (intencional).
    const [armado, setArmado] = useState(false);
    // Cuántos resultados se pintan. Arranca en el primer bloque y "Cargar 25 más" lo
    // agranda (AGREGA filas, no reemplaza las que ya se están mirando). El reset a 25 NO
    // va en un efecto (dispararía un render de más): el estado guarda, junto al límite, la
    // "clave" de los filtros con la que se cargó, y si esa clave ya no coincide (cambió
    // una tarjeta, un chip o el texto buscado) se vuelve al primer bloque en el mismo
    // render.
    const claveFiltros = `${etapaFiltro ?? ''}|${soloHoy}|${busqueda}`;
    const [paginacion, setPaginacion] = useState({ clave: claveFiltros, limite: BLOQUE_ALUMNOS });
    const limite = paginacion.clave === claveFiltros ? paginacion.limite : BLOQUE_ALUMNOS;

    const alumnos = data?.alumnos || [];
    const resumen = data?.resumen || {};
    // Envío masivo: el backend sólo manda a los 'Activo'. El panel cuenta con las
    // MISMAS reglas (`utils/migracionActivacion.js`) para que el número del botón y
    // la advertencia de "faltan correos" no mientan.
    const activosConCorreo = candidatosParaMigrar(alumnos);
    const activosSinCorreo = candidatosSinCorreo(alumnos);
    // El botón cuenta a TODOS los Activos (con y sin correo): el backend omite a los
    // que no tienen email y lo informa en `omitidos`. Los dos números cuadran con
    // `total` de la respuesta.
    const activosTotales = activosConCorreo.length + activosSinCorreo.length;
    // Derivaciones baratas (el backend ya mandó el resumen hecho y son cientos de filas):
    // se calculan en el render, sin `useMemo` — memoizar objetos que se arman con `||`
    // sólo agrega una dependencia que cambia en cada render.
    const conteo = conteoPorEtapa(resumen);
    const total = totalAlumnos(resumen);
    const pendientes = pendientesPorActivar(resumen);
    const comprados = conteo.plan_comprado;
    const avance = porcentajeComprado(resumen);
    const hoy = activadosHoy(resumen);

    const visibles = filtrarAlumnos(alumnos, {
        etapa: etapaFiltro, soloActivadosHoy: soloHoy, busqueda,
    });
    const conFiltro = hayFiltro({
        etapa: etapaFiltro, soloActivadosHoy: soloHoy, busqueda,
    });
    // El bloque que se pinta (25) + los números del footer ("faltan Z"). Sólo se calcula
    // en memoria: el backend ya mandó el padrón completo.
    const bloque = paginaAlumnos(visibles, limite);

    const alternarEtapa = (clave) => setEtapaFiltro((previa) => (previa === clave ? null : clave));
    const quitarFiltros = () => { setEtapaFiltro(null); setSoloHoy(false); setBusqueda(''); };
    const cargarMas = () => setPaginacion({ clave: claveFiltros, limite: limite + BLOQUE_ALUMNOS });

    // ── "Faltan correos": guardar el email de UNA fila ──
    // Misma validación liviana que el modal de edición del padrón (el backend
    // revalida con EmailStr y responde 422/409 si hace falta).
    const correoValido = (valor) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(valor);

    const guardarCorreoFila = async (candidatoId) => {
        const valor = String(correosBorrador[candidatoId] ?? '').trim();
        if (!correoValido(valor)) {
            setErroresCorreo((previo) => ({
                ...previo,
                [candidatoId]: 'Ingresa un correo válido (ej: nombre@dominio.cl).',
            }));
            return;
        }
        setGuardandoCorreoId(candidatoId);
        setErroresCorreo((previo) => {
            const copia = { ...previo };
            delete copia[candidatoId];
            return copia;
        });
        try {
            await guardarCorreo.mutateAsync({ candidatoId, correo: valor });
            // Al guardar OK la fila deja de estar "sin correo": se limpia el borrador
            // y la caché de la consulta ya trae el email nuevo.
            setCorreosBorrador((previo) => {
                const copia = { ...previo };
                delete copia[candidatoId];
                return copia;
            });
        } catch (err) {
            const detalle = err?.response?.data?.detail;
            const texto = Array.isArray(detalle) ? detalle[0]?.msg : detalle;
            setErroresCorreo((previo) => ({
                ...previo,
                [candidatoId]: texto || 'No se pudo guardar el correo.',
            }));
        } finally {
            setGuardandoCorreoId(null);
        }
    };

    // ── "Comenzar migración": dispara el envío masivo ──
    const comenzarMigracion = async () => {
        setErrorEnvio('');
        setResultadoEnvio(null);
        try {
            const dataEnvio = await enviarActivacion.mutateAsync();
            setResultadoEnvio(dataEnvio);
        } catch (err) {
            const detalle = err?.response?.data?.detail;
            const texto = Array.isArray(detalle) ? detalle[0]?.msg : detalle;
            setErrorEnvio(texto || 'No se pudo comenzar la migración.');
        }
    };

    const mensajeError = error?.response?.data?.detail || 'No se pudo cargar el panel de activación.';

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
                            Panel de Activación — Migración BoxMagic
                        </h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            En qué etapa del alta quedó cada alumno del padrón de BoxMagic.
                            Desde acá se envía el correo de activación a los Activos.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => refetch()}
                        disabled={isFetching}
                        aria-busy={isFetching}
                        title="Volver a pedir el padrón al servidor"
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

                {/* ── Envío masivo del correo de activación (sólo Activos) ──
                    El backend filtra grupo='activacion' + estado 'Activo' y omite a
                    los que ya tienen un token vigente. Los otros estados del padrón
                    (Nuevo/Prueba/Congelado) no tienen botón: son otra sesión. */}
                <section
                    data-testid="envio-migracion-activos"
                    className="mb-4 rounded-2xl border border-zinc-800 bg-zinc-900 p-4 sm:p-5"
                >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div className="flex items-start gap-3">
                            <Mail className="mt-0.5 h-5 w-5 shrink-0 text-orange-400" aria-hidden="true" />
                            <div>
                                <h2 className="text-base font-bold text-zinc-100">
                                    Correo de activación — Activos
                                </h2>
                                <p className="text-[13px] text-zinc-400">
                                    Invita a los candidatos Activos que ya tienen correo en el padrón.
                                    Los que tengan un link vigente no reciben otro.
                                </p>
                            </div>
                        </div>
                        <span className="shrink-0 self-start rounded-full border border-orange-500/40 bg-orange-500/10 px-3 py-1 text-xs font-semibold text-orange-300">
                            {activosConCorreo.length} con correo
                        </span>
                    </div>

                    {/* ── Faltan correos: filas del padrón Activo sin email ──
                        Sin correo el envío no puede invitarlos. Se completan acá, una
                        por una, con el mismo PATCH que valida formato + UNIQUE. */}
                    {activosSinCorreo.length > 0 && (
                        <div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/5">
                            <button
                                type="button"
                                onClick={() => setFaltanAbiertas((previo) => !previo)}
                                aria-expanded={faltanAbiertas}
                                data-testid="toggle-faltan-correos"
                                className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-[13px] font-semibold text-amber-200 transition hover:text-amber-100"
                            >
                                <span className="inline-flex items-center gap-2">
                                    <Mail className="h-4 w-4" aria-hidden="true" />
                                    Faltan correos ({activosSinCorreo.length})
                                </span>
                                {faltanAbiertas
                                    ? <ChevronUp className="h-4 w-4" aria-hidden="true" />
                                    : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
                            </button>
                            {faltanAbiertas && (
                                <ul
                                    className="max-h-72 space-y-2 overflow-y-auto px-3 pb-3"
                                    data-testid="faltan-correos-lista"
                                >
                                    {activosSinCorreo.map((alumno) => {
                                        const candidatoId = alumno.candidato_id ?? alumno.id;
                                        const guardando = guardandoCorreoId === candidatoId;
                                        const errorFila = erroresCorreo[candidatoId];
                                        return (
                                            <li
                                                key={candidatoId}
                                                className="rounded-lg border border-zinc-800 bg-zinc-900/80 p-2.5"
                                            >
                                                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                                                    <p className="min-w-0 flex-1 break-words text-[13px] font-semibold text-zinc-200">
                                                        {alumno.nombre}
                                                    </p>
                                                    <input
                                                        type="email"
                                                        value={correosBorrador[candidatoId] ?? ''}
                                                        onChange={(e) => setCorreosBorrador((previo) => ({
                                                            ...previo,
                                                            [candidatoId]: e.target.value,
                                                        }))}
                                                        placeholder="correo@dominio.cl"
                                                        aria-label={`Correo de ${alumno.nombre}`}
                                                        data-testid={`correo-candidato-${candidatoId}`}
                                                        disabled={guardando}
                                                        className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-orange-500 disabled:opacity-60 sm:w-64"
                                                    />
                                                    <button
                                                        type="button"
                                                        onClick={() => guardarCorreoFila(candidatoId)}
                                                        disabled={guardando}
                                                        data-testid={`guardar-correo-${candidatoId}`}
                                                        className="shrink-0 rounded-lg bg-orange-600 px-3 py-1.5 text-xs font-bold text-white transition hover:bg-orange-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
                                                    >
                                                        {guardando ? 'Guardando...' : 'Guardar'}
                                                    </button>
                                                </div>
                                                {errorFila && (
                                                    <p
                                                        className="mt-1.5 text-[11.5px] text-red-300"
                                                        data-testid={`error-correo-${candidatoId}`}
                                                    >
                                                        {errorFila}
                                                    </p>
                                                )}
                                            </li>
                                        );
                                    })}
                                </ul>
                            )}
                        </div>
                    )}

                    {activosSinCorreo.length > 0 && (
                        <p className="mt-3 text-[12px] text-amber-300" data-testid="aviso-faltan-correos">
                            Aún hay {activosSinCorreo.length} candidatos sin correo — igual puedes
                            comenzar, se omitirán.
                        </p>
                    )}

                    {/* Toggle de seguridad: debe armarse antes de enviar */}
                    <div className="mt-4 flex items-center gap-3">
                        <button
                            type="button"
                            role="switch"
                            aria-checked={armado}
                            onClick={() => setArmado((prev) => !prev)}
                            data-testid="toggle-armado"
                            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 transition-colors focus:outline-none focus:ring-2 focus:ring-orange-500 focus:ring-offset-2 focus:ring-offset-zinc-900 ${armado ? 'border-orange-500 bg-orange-500' : 'border-zinc-600 bg-zinc-700'}`}
                        >
                            <span
                                aria-hidden="true"
                                className={`pointer-events-none inline-block h-4 w-4 translate-y-[1px] rounded-full bg-white shadow transition-transform ${armado ? 'translate-x-5' : 'translate-x-0.5'}`}
                            />
                        </button>
                        <span className={`text-[13px] font-semibold ${armado ? 'text-orange-400' : 'text-zinc-500'}`}>
                            {armado ? 'Listo para enviar' : 'Desarmado — activa para habilitar el envío'}
                        </span>
                    </div>

                    <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center">
                        <button
                            type="button"
                            onClick={comenzarMigracion}
                            disabled={enviarActivacion.isPending || activosTotales === 0 || !armado}
                            aria-busy={enviarActivacion.isPending}
                            data-testid="comenzar-migracion"
                            className="inline-flex items-center justify-center gap-2 rounded-xl bg-orange-600 px-5 py-2.5 text-sm font-bold text-white transition hover:bg-orange-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            <Send className="h-4 w-4" aria-hidden="true" />
                            {enviarActivacion.isPending ? 'Enviando...' : `Comenzar migración (${activosTotales})`}
                        </button>
                        {activosTotales === 0 && (
                            <p className="text-[12px] text-zinc-500">No hay candidatos Activos para invitar.</p>
                        )}
                    </div>

                    {errorEnvio && (
                        <p
                            className="mt-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-[12.5px] text-red-200"
                            data-testid="error-envio-migracion"
                        >
                            {errorEnvio}
                        </p>
                    )}

                    {resultadoEnvio && (
                        <div
                            className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[12.5px] text-emerald-200"
                            data-testid="resultado-envio-migracion"
                        >
                            Migración ejecutada: <b>{resultadoEnvio.enviados}</b> enviados,{' '}
                            <b>{resultadoEnvio.fallidos}</b> fallidos,{' '}
                            <b>{resultadoEnvio.omitidos}</b> omitidos de{' '}
                            {resultadoEnvio.total}.
                        </div>
                    )}
                </section>

                {/* ── Pendientes por activar: el número que importa + avance del embudo ── */}
                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 mb-4">
                    <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
                        <div>
                            <p className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">
                                Pendientes por activar
                            </p>
                            <p className="text-3xl font-extrabold text-zinc-100 mt-1" data-testid="pendientes-por-activar">
                                {pendientes}
                            </p>
                            <p className="text-[12px] text-zinc-500 mt-1">
                                de {total} alumnos migrados
                            </p>
                        </div>
                        <p className="text-sm text-zinc-400">
                            <span className="font-extrabold text-emerald-400">{comprados}</span>
                            {' '}ya compraron plan ({avance}%)
                        </p>
                    </div>
                    <div
                        className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-800"
                        role="progressbar"
                        aria-valuenow={avance}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label="Porcentaje de alumnos migrados que ya compraron plan"
                        data-testid="barra-avance-activacion"
                    >
                        <div
                            className="h-full rounded-full bg-emerald-500 transition-all"
                            style={{ width: `${avance}%` }}
                        />
                    </div>
                </div>

                {/* ── Hoy se activaron: CLICKEABLE, filtra la tabla por `activado_hoy` ── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-6">
                    <button
                        type="button"
                        onClick={() => setSoloHoy((previo) => !previo)}
                        aria-pressed={soloHoy}
                        aria-label="Filtrar la tabla por los alumnos que se activaron hoy"
                        title={soloHoy ? 'Quitar este filtro' : 'Filtrar la tabla por los que se activaron hoy'}
                        data-testid="tarjeta-activados-hoy"
                        className={`w-full text-left rounded-2xl transition ${soloHoy
                            ? 'ring-2 ring-orange-500'
                            : 'hover:ring-1 hover:ring-zinc-600 active:ring-2 active:ring-orange-500'}`}
                    >
                        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                            <span className="absolute left-0 top-0 bottom-0 w-1 bg-emerald-500" />
                            <p className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">
                                Hoy se activaron
                            </p>
                            <p className="text-2xl font-extrabold text-zinc-100 mt-1.5">{hoy}</p>
                            <p className="text-[11px] text-zinc-500 mt-1">
                                alumnos en las últimas 24 h
                            </p>
                        </div>
                    </button>
                </div>

                {/* ── Las 5 etapas: tarjetas que filtran la tabla (patrón de Fidelización) ──
                    En el TELÉFONO van en UNA fila con scroll horizontal propio: el scroll
                    queda contenido acá (no arrastra la página) y las 5 caben a un dedazo.
                    Desde 768px vuelve a ser la grilla de siempre. */}
                <div className="mb-4 flex snap-x gap-3.5 overflow-x-auto p-1 md:grid md:grid-cols-2 md:overflow-visible md:p-0 lg:grid-cols-5">
                    {ETAPAS_ACTIVACION.map((etapa) => {
                        const activa = etapaFiltro === etapa.key;
                        return (
                            <button
                                key={etapa.key}
                                type="button"
                                onClick={() => alternarEtapa(etapa.key)}
                                aria-pressed={activa}
                                aria-label={`Filtrar la tabla por la etapa: ${etapa.label}`}
                                title={activa ? 'Quitar este filtro' : `Filtrar la tabla por ${etapa.label}`}
                                data-testid={`tarjeta-etapa-${etapa.key}`}
                                className={`w-40 shrink-0 snap-start text-left rounded-lg transition active:scale-[0.97] md:w-auto ${activa
                                    ? 'ring-2 ring-orange-500'
                                    : 'hover:ring-1 hover:ring-zinc-600 active:ring-2 active:ring-orange-500'}`}
                            >
                                <KpiCard
                                    label={etapa.label}
                                    value={conteo[etapa.key]}
                                    color={etapa.color}
                                />
                            </button>
                        );
                    })}
                </div>

                {/* ── Filtros activos (se pueden quitar uno por uno) ── */}
                {conFiltro && (
                    <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="filtros-activos">
                        <span className="text-xs text-zinc-500">Filtrando:</span>
                        {etapaFiltro && (
                            <button
                                type="button"
                                onClick={() => setEtapaFiltro(null)}
                                className="px-3 py-1 rounded-full text-xs font-semibold border border-orange-500/40 bg-orange-500/10 text-orange-400 hover:bg-orange-500/20 transition-colors"
                            >
                                Etapa: {badgeEtapa(etapaFiltro).texto} <span aria-hidden="true">×</span>
                            </button>
                        )}
                        {soloHoy && (
                            <button
                                type="button"
                                onClick={() => setSoloHoy(false)}
                                className="px-3 py-1 rounded-full text-xs font-semibold border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-colors"
                            >
                                Activados hoy <span aria-hidden="true">×</span>
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
                    Sin request: el padrón ya está en memoria. Se combina con las tarjetas
                    de etapa y con "Hoy". */}
                <input
                    type="text"
                    value={busqueda}
                    onChange={(e) => setBusqueda(e.target.value)}
                    placeholder="Buscar por nombre o correo..."
                    aria-label="Buscar alumno por nombre o correo"
                    data-testid="buscar-activacion"
                    className="mb-3 w-full px-4 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 bg-zinc-800 text-zinc-100 placeholder:text-zinc-500"
                />

                {/* ── Vista MÓVIL (<768px): una tarjeta por alumno con los datos apilados
                    (Nombre / Correo / Etapa / Plan). Reemplaza a la tabla en el teléfono;
                    en >=768px no se muestra (regla de oro: el escritorio no cambia). */}
                <ul data-testid="padron-activacion-movil" className="md:hidden space-y-2">
                    {bloque.mostrados.length > 0 ? bloque.mostrados.map((alumno) => {
                        const badge = badgeEtapa(alumno.etapa);
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
                                <div className="flex items-start justify-between gap-2">
                                    <p className="text-sm font-bold text-zinc-100 break-words">{alumno.nombre}</p>
                                    <button
                                        type="button"
                                        onClick={() => setAlumnoEditar(alumno)}
                                        aria-label={`Editar el padrón de ${alumno.nombre}`}
                                        data-testid={`editar-candidato-movil-${clave}`}
                                        className="shrink-0 inline-flex items-center gap-1 rounded-lg border border-zinc-700 px-2 py-1 text-[11px] font-semibold text-zinc-300 transition hover:border-orange-500 hover:text-orange-400 active:bg-zinc-800 active:scale-[0.98]"
                                    >
                                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                                        Editar
                                    </button>
                                </div>
                                {/* El correo se ve COMPLETO (break-all): en mobile no se
                                    recorta ni se trunca, para detectar errores del padrón. */}
                                <p className="mt-0.5 whitespace-normal break-all text-[12.5px] text-zinc-400">{alumno.correo}</p>
                                <dl className="mt-3 space-y-1.5">
                                    <div className="flex items-center justify-between gap-2">
                                        <dt className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Etapa</dt>
                                        <dd className="flex items-center gap-2">
                                            <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${badge.clase}`}>
                                                {badge.texto}
                                            </span>
                                            {alumno.activado_hoy && (
                                                <span className="text-[11px] font-bold uppercase tracking-wide text-emerald-400">
                                                    Hoy
                                                </span>
                                            )}
                                        </dd>
                                    </div>
                                    <div className="flex items-center justify-between gap-2">
                                        <dt className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Plan</dt>
                                        <dd>
                                            {alumno.plan_comprado
                                                ? <span className="px-2 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-300">{alumno.plan_comprado}</span>
                                                : <span className="text-xs text-zinc-500">Sin plan</span>}
                                        </dd>
                                    </div>
                                </dl>
                            </li>
                        );
                    }) : (
                        <li className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-8 text-center text-sm text-zinc-400">
                            {alumnos.length === 0
                                ? 'El padrón de BoxMagic no tiene alumnos de activación cargados todavía.'
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
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Etapa</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Plan</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Acción</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800">
                            {bloque.mostrados.length > 0 ? bloque.mostrados.map((alumno) => {
                                const badge = badgeEtapa(alumno.etapa);
                                // Clave de la fila = `candidato_id` (el padrón). `id` es la
                                // cuenta REAL y viene en null mientras no exista: usarlo de
                                // clave repetiría la misma key en casi todas las filas.
                                const clave = alumno.candidato_id ?? alumno.id;
                                return (
                                    <tr key={clave} data-alumno-id={clave} className="hover:bg-zinc-800/40">
                                        <td className="px-6 py-3 text-sm font-medium text-zinc-100">{alumno.nombre}</td>
                                        <td className="px-6 py-3 text-sm text-zinc-400">{alumno.correo}</td>
                                        <td className="px-6 py-3 text-sm">
                                            <span className={`px-3 py-1 rounded-full text-xs font-medium border ${badge.clase}`}>
                                                {badge.texto}
                                            </span>
                                            {/* El hito de las últimas 24 h, al lado de la etapa: así el número
                                                de la tarjeta "Hoy se activaron" se puede verificar fila por
                                                fila, sin una columna propia. */}
                                            {alumno.activado_hoy && (
                                                <span className="ml-2 text-[11px] font-bold uppercase tracking-wide text-emerald-400">
                                                    Hoy
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-6 py-3 text-sm">
                                            {alumno.plan_comprado
                                                ? <span className="px-2 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-300">{alumno.plan_comprado}</span>
                                                : <span className="text-zinc-500">—</span>}
                                        </td>
                                        <td className="px-6 py-3 text-sm">
                                            <button
                                                type="button"
                                                onClick={() => setAlumnoEditar(alumno)}
                                                aria-label={`Editar el padrón de ${alumno.nombre}`}
                                                data-testid={`editar-candidato-${clave}`}
                                                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-2.5 py-1.5 text-xs font-semibold text-zinc-300 transition hover:border-orange-500 hover:text-orange-400 active:bg-zinc-800 active:scale-[0.98]"
                                            >
                                                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                                                Editar
                                            </button>
                                        </td>
                                    </tr>
                                );
                            }) : (
                                <tr>
                                    <td colSpan={5} className="px-6 py-8 text-center text-sm text-zinc-400">
                                        {alumnos.length === 0
                                            ? 'El padrón de BoxMagic no tiene alumnos de activación cargados todavía.'
                                            : 'Ningún alumno coincide con el filtro.'}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>

                <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <p className="text-[12px] text-zinc-500" data-testid="footer-listado-activacion">
                        Mostrando <span className="font-bold text-zinc-300">{bloque.mostrados.length}</span> de{' '}
                        <span className="font-bold text-zinc-300">{bloque.total}</span>
                        {bloque.faltan > 0 && (
                            <> — faltan <span className="font-bold text-zinc-300">{bloque.faltan}</span></>
                        )}.
                        <span className="mt-1 block">
                            &quot;Pendientes por activar&quot; son los que todavía no compraron plan.
                        </span>
                    </p>
                    {bloque.hayMas && (
                        <button
                            type="button"
                            onClick={cargarMas}
                            data-testid="cargar-mas-activacion"
                            className="shrink-0 rounded-xl border border-zinc-700 bg-zinc-800 px-4 py-2 text-sm font-bold text-zinc-200 transition hover:border-orange-500 hover:text-orange-400 active:border-orange-500 active:bg-zinc-700 active:text-orange-400 active:scale-[0.98]"
                        >
                            Cargar {BLOQUE_ALUMNOS} más
                        </button>
                    )}
                </div>

                {/* Corrección del padrón: el modal sólo escribe nombre/correo del
                    candidato (nunca su cuenta real). */}
                {alumnoEditar && (
                    <EditarCandidatoBoxmagic
                        alumno={alumnoEditar}
                        onClose={() => setAlumnoEditar(null)}
                    />
                )}
            </div>
        </Layout>
    );
};

export default MigracionActivacion;

