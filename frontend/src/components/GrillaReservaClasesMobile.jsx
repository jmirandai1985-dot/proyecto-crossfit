import React, { useEffect, useState } from 'react';
// Paleta, tarjetas y chips del Inicio móvil: todas las reglas están acotadas a
// `.ub-inicio` (ver inicioMobile.css). El CSS se importa acá para que el bloque
// se vea igual cuando se monta fuera del Inicio (pestaña "Agendar Reserva").
import '../pages/alumno/inicioMobile.css';
// Chips de disciplina: el MISMO componente, hook y criterio que "Mis Reservas"
// y el Inicio móvil (no se duplica ni el control ni su memoria de sesión).
import FiltroDisciplina from './FiltroDisciplina';
import { useFiltroDisciplina } from '../hooks/useFiltroDisciplina';
import { CLAVE_FILTRO_INICIO, filtrarPorDisciplina } from '../utils/filtroDisciplina';
// Filtro por franja horaria (debajo del de disciplina). La franja se
// preselecciona con la hora de Chile (misma fuente que el resto de la app).
import { franjaActual, filtrarPorFranja, rangoFranja, TODO_EL_DIA, FRANJAS } from '../utils/franjaHoraria';
import { agruparClasesRepetidas, horaCorta } from '../utils/grillaReserva';

// Título con el que la sección se ve en el Inicio del alumno.
const TITULO_POR_DEFECTO = 'Clases disponibles';

// "Pocos cupos": por debajo de este umbral la tarjeta muestra un badge rojo
// (advertencia de que la clase está por llenarse). No hay otro umbral definido
// en el resto de la app, así que este es el único.
const UMBRAL_POCOS_CUPOS = 3;

/**
 * Grilla de reserva para TOMAR una clase en móvil (<768px): selector de día,
 * chips de disciplina/franja y las clases del día en TARJETAS, con su botón
 * Reservar. Es el bloque que vivía inline en `pages/alumno/InicioMobile.jsx`
 * y ahora comparten el Inicio móvil y la pestaña "Agendar Reserva".
 *
 * Genérica: no consulta la API ni conoce el rol ni la membresía. Recibe los
 * días, las clases ya agrupadas por día y `onReservar(clase)`. La confirmación
 * vive en `ModalConfirmarReserva` (`GrillaReservaClases`), igual para las dos
 * vistas.
 *
 * Props:
 *   proximosDias  — [{ fecha, nombreDia, diaNum }] (utils/grillaReserva)
 *   clasesPorDia  — { [fecha]: clase[] } (utils/grillaReserva)
 *   onReservar    — (clase) => void; abre el modal compartido
 *   titulo        — encabezado de la tarjeta
 *   id            — ancla del bloque (el Inicio móvil la usa en "Reservar otra clase")
 *   suelto        — true cuando se monta fuera del Inicio (hereda la paleta, sin
 *                   el marco de pantalla completa del Inicio)
 *   testid        — data-testid de la tarjeta (tests E2E)
 */
const GrillaReservaClasesMobile = ({
    proximosDias = [],
    clasesPorDia = {},
    onReservar,
    titulo = TITULO_POR_DEFECTO,
    id = 'ub-clases',
    suelto = false,
    testid = 'ub-clases-mobile',
}) => {
    // Día elegido. Arranca en el primer día con clases (igual que el acordeón
    // del Inicio de escritorio); se fija cuando llegan los datos.
    const [diaSeleccionado, setDiaSeleccionado] = useState(null);
    useEffect(() => {
        if (diaSeleccionado) return;
        const primero = proximosDias.find((d) => (clasesPorDia[d.fecha] || []).length > 0);
        if (primero) setDiaSeleccionado(primero.fecha);
    }, [proximosDias, clasesPorDia, diaSeleccionado]);

    // Clases del día elegido: deduplicadas (varias sedes comparten disciplina y
    // hora) y ordenadas por horario.
    const clasesDelDia = agruparClasesRepetidas(clasesPorDia[diaSeleccionado] || [])
        .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));

    // ── Filtro por disciplina ──
    // Filtra la LISTA del día elegido (con varias disciplinas la lista se hace
    // larguísima). El selector de 7 días NO se filtra: cada día sigue mostrando
    // el TOTAL de clases que trae `clasesPorDia` (por eso se filtra una copia).
    // La última disciplina elegida se recuerda mientras dure la sesión.
    const {
        disponibles: disciplinasClases,
        filtro: filtroClases,
        cambiar: cambiarFiltroClases,
        mostrar: mostrarFiltroClases,
    } = useFiltroDisciplina(clasesDelDia, CLAVE_FILTRO_INICIO);
    const clasesFiltradas = filtrarPorDisciplina(clasesDelDia, filtroClases);

    // ── Filtro por franja horaria (se combina con el de disciplina) ──
    // Arranca preseleccionado en la franja del momento (hora de Chile); el alumno
    // puede cambiarlo libremente. "Todo el día" no filtra por franja.
    const [franjaFiltro, setFranjaFiltro] = useState(franjaActual);
    const clasesFiltradasPorFranja = filtrarPorFranja(clasesFiltradas, franjaFiltro);

    return (
        // `.ub-inicio` aporta las variables de color y el reset de botones del
        // Inicio móvil; `.ub-inicio-suelto` anula sólo el marco de pantalla
        // completa cuando la grilla se monta en otra pantalla.
        <div className={suelto ? 'ub-inicio ub-inicio-suelto' : undefined}>
            <section className="card sec" id={id} aria-label={titulo} data-testid={testid}>
                <div className="head">
                    <h2>{titulo}</h2>
                </div>

                {proximosDias.length > 0 && (
                    <div className="days" role="tablist" aria-label="Elige el día">
                        {proximosDias.map((d) => {
                            const n = (clasesPorDia[d.fecha] || []).length;
                            const activo = d.fecha === diaSeleccionado;
                            return (
                                <button
                                    key={d.fecha}
                                    type="button"
                                    role="tab"
                                    aria-selected={activo}
                                    className={`day${activo ? ' on' : ''}`}
                                    onClick={() => setDiaSeleccionado(d.fecha)}
                                >
                                    <span className="dn">{d.nombreDia.substring(0, 3)}</span>
                                    <span className="dd">{d.diaNum}</span>
                                    <span className={`dc${n ? ' has' : ''}`}>{n || '–'}</span>
                                </button>
                            );
                        })}
                    </div>
                )}

                {/* Filtro por disciplina del día elegido, sobre la MISMA lista
                    filtrada de abajo. Si hay una sola disciplina no se pinta:
                    "Todas" y esa disciplina darían la misma lista. */}
                {mostrarFiltroClases && (
                    <FiltroDisciplina
                        variante="ub"
                        disciplinas={disciplinasClases}
                        valor={filtroClases}
                        onCambiar={cambiarFiltroClases}
                        testid="ub-filtro-disciplina"
                    />
                )}

                {/* Filtro por franja horaria (debajo del de disciplina): fila de 4
                    chips fijos con el MISMO estilo `.filtro`/`.on`. No reusa el
                    componente de disciplinas (esas son dinámicas). */}
                <div className="filtro" data-testid="ub-filtro-franja" aria-label="Filtrar por franja horaria">
                    {FRANJAS.map((f) => (
                        <button
                            key={f.id}
                            type="button"
                            onClick={() => setFranjaFiltro(f.id)}
                            aria-pressed={franjaFiltro === f.id}
                            className={franjaFiltro === f.id ? 'on' : ''}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
                {franjaFiltro !== TODO_EL_DIA && (
                    <p className="franja-info">
                        Mostrando {rangoFranja(franjaFiltro)} · {clasesFiltradasPorFranja.length} de {clasesFiltradas.length} horarios
                    </p>
                )}

                <div className="clases">
                    {clasesDelDia.length === 0 ? (
                        <p className="vacio">Sin clases programadas este día.</p>
                    ) : clasesFiltradas.length === 0 ? (
                        <p className="vacio">No hay clases de {filtroClases} este día.</p>
                    ) : clasesFiltradasPorFranja.length === 0 ? (
                        <p className="vacio">No hay clases en esta franja horaria.</p>
                    ) : (
                        clasesFiltradasPorFranja.map((clase) => {
                            // Migración 066: cupo NULL = sin tope (Musculación / Open Box).
                            const sinTope = clase.cupo_maximo === null || clase.cupo_maximo === undefined;
                            const cupos = sinTope
                                ? Infinity
                                : (clase.cupo_maximo || 0) - (clase.asistentes_confirmados || 0);
                            const libre = cupos > 0;
                            // Pocos cupos = advertencia roja (sin tope no cuenta).
                            const pocosCupos = !sinTope && libre && cupos <= UMBRAL_POCOS_CUPOS;
                            return (
                                <div className="clase" key={clase.id} data-testid="ub-clase">
                                    <div className="ci">
                                        <span className="ch">{horaCorta(clase.hora_inicio)}</span>
                                        <span className="cd">{clase.disciplina_nombre || 'Clase'}</span>
                                        <span className="cc">{clase.coach_nombre ? `Con ${clase.coach_nombre}` : 'Coach por confirmar'}</span>
                                    </div>
                                    <div className="cq">
                                        <span className={`cupos${!libre ? ' no' : pocosCupos ? ' pocos' : ' ok'}`}>
                                            {sinTope
                                                ? 'Acceso libre'
                                                : (!libre ? 'Lleno' : pocosCupos ? `¡Quedan ${cupos}!` : `${cupos} cupos`)}
                                        </span>
                                        <button
                                            type="button"
                                            className="res"
                                            disabled={!libre}
                                            onClick={() => onReservar && onReservar(clase)}
                                        >
                                            {libre ? 'Reservar' : 'Lleno'}
                                        </button>
                                    </div>
                                </div>
                            );
                        })
                    )}
                </div>
            </section>
        </div>
    );
};

export default GrillaReservaClasesMobile;
