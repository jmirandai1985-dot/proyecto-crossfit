import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import api from '../../services/api';
import { fmtFechaChile, fmtFechaCortaChile } from '../../utils/fecha';

/**
 * Panel del Historial del alumno: la MISMA pantalla para el box y para el alumno.
 *
 * El backend devuelve SIEMPRE la misma envoltura para las 7 secciones
 * (`{alumno, seccion, secciones, incluye_privado, datos}`), así que acá hay un solo
 * cliente: se pide una sección por vez (`?seccion=...`) y se dibuja lo que traiga
 * `datos`. Nada de números calculados en el front (el backend es la única
 * definición de cada métrica).
 *
 * Props:
 *   - alumnoId: id del alumno (vista del box). Sin `alumnoId` se usa la puerta del
 *     propio alumno (`/alumnos/me/historial`), que NUNCA trae la gestión del box.
 */

const POR_PAGINA = 25;

// Los 5 estados de una reserva (mismos valores que el servicio del backend).
const ESTADOS_ASISTENCIA = {
    asistio: { label: 'Asistió', clase: 'bg-emerald-500/20 text-emerald-300' },
    falto: { label: 'Faltó', clase: 'bg-red-500/20 text-red-300' },
    cancelada: { label: 'Cancelada', clase: 'bg-zinc-600/40 text-zinc-300' },
    cancelada_tarde: { label: 'Cancelada tarde', clase: 'bg-amber-500/20 text-amber-200' },
    reservada: { label: 'Reservada', clase: 'bg-sky-500/20 text-sky-300' },
};

const TIPOS_PAGO = {
    membresia: { label: 'Membresía', clase: 'bg-violet-500/20 text-violet-300' },
    bazar: { label: 'Bazar', clase: 'bg-orange-500/20 text-orange-300' },
};

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
    'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

// ── Formato (solo presentación: los números vienen calculados del backend) ──
const clp = (v) => (v === null || v === undefined ? '—' : `$${Number(v).toLocaleString('es-CL')}`);
const num = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('es-CL'));
const fecha = (v) => (v ? fmtFechaChile(String(v)) : '—');
const fechaCorta = (v) => (v ? fmtFechaCortaChile(String(v)) : '—');
const etiquetaMes = (anio, mes) => `${MESES[mes - 1] || mes} ${String(anio).slice(2)}`;

const Card = ({ titulo, children, testid }) => (
    <div className="bg-zinc-900 rounded-lg shadow p-5" data-testid={testid}>
        {titulo && (
            <h3 className="text-sm font-bold uppercase tracking-wide text-zinc-400 mb-3">
                {titulo}
            </h3>
        )}
        {children}
    </div>
);

const Dato = ({ label, valor, testid, destacado = false }) => (
    <div className="bg-zinc-800/50 rounded-lg p-3">
        <p className="text-xs text-zinc-500">{label}</p>
        <p className={`font-bold ${destacado ? 'text-2xl text-white' : 'text-lg text-zinc-100'}`}
            data-testid={testid}>
            {valor}
        </p>
    </div>
);

const EstadoAsistencia = ({ estado }) => {
    const conf = ESTADOS_ASISTENCIA[estado] || { label: estado, clase: 'bg-zinc-700 text-zinc-200' };
    return (
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${conf.clase}`}>
            {conf.label}
        </span>
    );
};

const Paginado = ({ paginado, onPagina, testid = 'historial-paginado' }) => {
    if (!paginado || paginado.paginas <= 1) return null;
    return (
        <div className="flex items-center justify-between gap-3 pt-3 text-sm text-zinc-400"
            data-testid={testid}>
            <span>
                Página {paginado.pagina} de {paginado.paginas} · {num(paginado.total)} en total
            </span>
            <div className="flex gap-2">
                <button type="button" disabled={paginado.pagina <= 1}
                    onClick={() => onPagina(paginado.pagina - 1)}
                    className="px-3 py-1 rounded-lg bg-zinc-800 font-bold text-zinc-200 hover:bg-zinc-700 disabled:opacity-40">
                    Anterior
                </button>
                <button type="button" disabled={paginado.pagina >= paginado.paginas}
                    onClick={() => onPagina(paginado.pagina + 1)}
                    className="px-3 py-1 rounded-lg bg-zinc-800 font-bold text-zinc-200 hover:bg-zinc-700 disabled:opacity-40">
                    Siguiente
                </button>
            </div>
        </div>
    );
};

const Tabla = ({ columnas, children }) => (
    <div className="overflow-x-auto">
        <table className="w-full text-sm">
            <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-zinc-500">
                    {columnas.map((c) => <th key={c} className="py-2 pr-4">{c}</th>)}
                </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">{children}</tbody>
        </table>
    </div>
);


// ══════════════════════════════════════════════════════════════════════════════
// Secciones
// ══════════════════════════════════════════════════════════════════════════════
const SeccionResumen = ({ datos }) => {
    const a = datos.asistencia || {};
    const m = datos.membresia || {};
    const p = datos.pagos || {};
    const r = datos.rms || {};
    const g = datos.gestion;
    const actual = m.actual;

    return (
        <div className="space-y-5">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="historial-resumen">
                <Dato label="Clases asistidas" valor={num(a.asistidas)} destacado
                    testid="historial-asistidas" />
                <Dato label="% de asistencia" valor={`${num(a.pct_asistencia)}%`}
                    testid="historial-pct" />
                <Dato label="Promedio por semana" valor={num(a.promedio_semanal)}
                    testid="historial-promedio" />
                <Dato label="Racha (meses al 100%)" valor={num(a.racha_meses_100)} />
                <Dato label="Total pagado" valor={clp(p.total_clp)} destacado
                    testid="historial-total-pagado" />
                <Dato label="Meses con plan"
                    valor={`${num(m.meses_con_plan)} de ${num(m.meses_como_alumno)}`} />
                <Dato label="Días sin asistir" valor={num(a.dias_sin_asistir)}
                    testid="historial-dias-sin-asistir" />
                <Dato label="PRs registrados" valor={num(r.movimientos)} />
            </div>

            <Card titulo="Membresía actual">
                {!actual ? (
                    <p className="text-sm text-zinc-500">Sin plan vigente hoy</p>
                ) : (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                        <div>
                            <p className="text-xs text-zinc-500">Plan</p>
                            <p className="text-zinc-100 font-semibold">{actual.plan}</p>
                        </div>
                        <div>
                            <p className="text-xs text-zinc-500">Créditos disponibles</p>
                            <p className="text-zinc-100 font-semibold">
                                {actual.es_ilimitado ? '∞'
                                    : (actual.creditos_disponibles ?? '—')}
                            </p>
                        </div>
                        <div>
                            <p className="text-xs text-zinc-500">Vence el</p>
                            <p className="text-zinc-100 font-semibold">
                                {fechaCorta(actual.fecha_expiracion)}
                            </p>
                        </div>
                        <div>
                            <p className="text-xs text-zinc-500">Días restantes</p>
                            <p className="text-zinc-100 font-semibold">{num(actual.dias_restantes)}</p>
                        </div>
                    </div>
                )}
            </Card>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <Card titulo="Hitos de constancia">
                    {datos.hitos?.alcanzados ? (
                        <p className="text-sm text-zinc-300">
                            {num(datos.hitos.alcanzados)} hito(s) acumulado(s) · racha máxima{' '}
                            <strong className="text-white">{num(datos.hitos.nivel_maximo)}</strong>{' '}
                            mes(es) al 100%
                        </p>
                    ) : (
                        <p className="text-sm text-zinc-500">Todavía sin hitos</p>
                    )}
                </Card>

                {g && (
                    <Card titulo="Gestión del box" testid="historial-gestion">
                        <div className="grid grid-cols-2 gap-3 text-sm">
                            <div>
                                <p className="text-xs text-zinc-500">Arquetipo</p>
                                <p className="text-zinc-100 font-semibold">{g.arquetipo || '—'}</p>
                                {g.arquetipo_calculado_en && (
                                    <p className="text-[10px] text-zinc-500 mt-0.5"
                                        title="Cuándo se entrenó el modelo de segmentación">
                                        calculado el {fechaCorta(g.arquetipo_calculado_en)}
                                    </p>
                                )}
                            </div>
                            <div>
                                <p className="text-xs text-zinc-500">Riesgo de baja</p>
                                <p className="text-zinc-100 font-semibold">
                                    {g.riesgo_nivel || '—'}
                                    {g.riesgo_probabilidad !== null && g.riesgo_probabilidad !== undefined
                                        && <span className="text-zinc-400"> · {g.riesgo_probabilidad}%</span>}
                                </p>
                                {g.riesgo_calculado_en && (
                                    <p className="text-[10px] text-zinc-500 mt-0.5"
                                        title="Cuándo se calculó el modelo (no es la situación de hoy, que es en vivo)">
                                        calculado el {fechaCorta(g.riesgo_calculado_en)}
                                    </p>
                                )}
                            </div>
                            <div>
                                <p className="text-xs text-zinc-500">Gestión</p>
                                <p className="text-zinc-100 font-semibold">{g.estado_gestion || 'PENDIENTE'}</p>
                            </div>
                            <div>
                                <p className="text-xs text-zinc-500">Días sin asistir</p>
                                <p className="text-zinc-100 font-semibold">{num(g.dias_sin_asistir)}</p>
                            </div>
                        </div>
                    </Card>
                )}
            </div>
        </div>
    );
};


const SeccionAsistencia = ({ datos, onPagina }) => {
    const t = datos.totales || {};
    const suspendidas = t.clases_suspendidas || 0;
    const items = datos.items || [];
    const porMes = datos.por_mes || [];

    return (
        <div className="space-y-5" data-testid="historial-asistencia">
            <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                <Dato label="Asistió" valor={num(t.asistio)} />
                <Dato label="Faltó" valor={num(t.falto)} />
                <Dato label="Cancelada" valor={num(t.cancelada)} />
                <Dato label="Cancelada tarde" valor={num(t.cancelada_tarde)} />
                <Dato label="Reservada" valor={num(t.reservada)} />
                <Dato label="% de asistencia" valor={`${num(t.pct_asistencia)}%`} destacado
                    testid="historial-asistencia-pct" />
            </div>

            <p className="text-xs text-zinc-500">
                El % se calcula sobre las {num(t.cuentan)} clases que cuentan (asistidas + faltadas
                + canceladas con menos de 6 h de margen). Cancelar a tiempo y las reservas futuras
                no lo mueven.
            </p>
            {suspendidas > 0 && (
                <p className="text-xs text-amber-300" data-testid="historial-suspendidas">
                    {num(suspendidas)} clase(s) suspendida(s) por el box: no se cuentan como falta.
                </p>
            )}

            <Card titulo="Todas las clases">
                <Tabla columnas={['Fecha', 'Hora', 'Disciplina', 'Coach', 'Estado', 'Créditos']}>
                    {items.map((i) => (
                        <tr key={i.reserva_id} data-testid="historial-clase">
                            <td className="py-2 pr-4 text-zinc-200">{fechaCorta(i.fecha)}</td>
                            <td className="py-2 pr-4 text-zinc-400">{i.hora_inicio}</td>
                            <td className="py-2 pr-4 text-zinc-300">{i.disciplina || '—'}</td>
                            <td className="py-2 pr-4 text-zinc-400">{i.coach || '—'}</td>
                            <td className="py-2 pr-4">
                                <EstadoAsistencia estado={i.estado_asistencia} />
                            </td>
                            <td className="py-2 pr-4 text-zinc-400">{i.creditos_gastados}</td>
                        </tr>
                    ))}
                    {items.length === 0 && (
                        <tr>
                            <td colSpan="6" className="py-6 text-center text-zinc-500">
                                Sin clases registradas
                            </td>
                        </tr>
                    )}
                </Tabla>
                <Paginado paginado={datos.paginado} onPagina={onPagina} />
            </Card>

            <Card titulo="Mes a mes">
                <Tabla columnas={['Mes', 'Asistió', 'Faltó', 'C. tarde', 'Cancelada',
                    'Reservada', '%']}>
                    {porMes.map((m) => (
                        <tr key={`${m.anio}-${m.mes}`}>
                            <td className="py-2 pr-4 text-zinc-200">{etiquetaMes(m.anio, m.mes)}</td>
                            <td className="py-2 pr-4 text-emerald-300">{m.asistio}</td>
                            <td className="py-2 pr-4 text-red-300">{m.falto}</td>
                            <td className="py-2 pr-4 text-amber-200">{m.cancelada_tarde}</td>
                            <td className="py-2 pr-4 text-zinc-400">{m.cancelada}</td>
                            <td className="py-2 pr-4 text-sky-300">{m.reservada}</td>
                            <td className="py-2 pr-4 font-semibold text-zinc-100">{m.pct}%</td>
                        </tr>
                    ))}
                    {porMes.length === 0 && (
                        <tr>
                            <td colSpan="7" className="py-6 text-center text-zinc-500">
                                Sin meses con actividad
                            </td>
                        </tr>
                    )}
                </Tabla>
            </Card>
        </div>
    );
};


const SeccionPagos = ({ datos, onPagina }) => {
    const t = datos.totales || {};
    const items = datos.items || [];
    const porAnio = datos.por_anio || [];

    return (
        <div className="space-y-5" data-testid="historial-pagos">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Dato label="Total pagado" valor={clp(t.total_clp)} destacado
                    testid="historial-total-pagado" />
                <Dato label="Membresías" valor={clp(t.membresias_clp)} />
                <Dato label="Bazar" valor={clp(t.bazar_clp)} />
                <Dato label="Último pago" valor={fechaCorta(t.ultimo_pago)} />
            </div>

            <p className="text-xs text-zinc-500">
                Las membresías muestran lo que se cobró DE VERDAD (las transacciones del box: el
                descuento a la vista y las devoluciones ya restadas), no el precio de lista del
                plan; del Bazar solo cuentan los pedidos validados o entregados.
            </p>
            {t.descuentos_clp > 0 && (
                <p className="text-xs text-emerald-400" data-testid="historial-descuentos">
                    Pagó {clp(t.descuentos_clp)} menos que el precio de lista.
                </p>
            )}

            <Card titulo="Por año">
                <Tabla columnas={['Año', 'Membresías', 'Bazar', 'Total']}>
                    {porAnio.map((a) => (
                        <tr key={a.anio}>
                            <td className="py-2 pr-4 text-zinc-200">{a.anio}</td>
                            <td className="py-2 pr-4 text-zinc-300">{clp(a.membresias)}</td>
                            <td className="py-2 pr-4 text-zinc-300">{clp(a.bazar)}</td>
                            <td className="py-2 pr-4 font-semibold text-white">{clp(a.total)}</td>
                        </tr>
                    ))}
                    {porAnio.length === 0 && (
                        <tr>
                            <td colSpan="4" className="py-6 text-center text-zinc-500">Sin pagos</td>
                        </tr>
                    )}
                </Tabla>
            </Card>

            <Card titulo="Detalle de pagos">
                <Tabla columnas={['Fecha', 'Tipo', 'Detalle', 'Monto']}>
                    {items.map((i) => {
                        const tipo = TIPOS_PAGO[i.tipo]
                            || { label: i.tipo, clase: 'bg-zinc-700 text-zinc-200' };
                        return (
                            <tr key={`${i.tipo}-${i.referencia_id}`} data-testid="historial-pago">
                                <td className="py-2 pr-4 text-zinc-200">{fechaCorta(i.fecha)}</td>
                                <td className="py-2 pr-4">
                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${tipo.clase}`}>
                                        {tipo.label}
                                    </span>
                                </td>
                                <td className="py-2 pr-4 text-zinc-300">{i.detalle}</td>
                                <td className="py-2 pr-4 font-semibold text-zinc-100">
                                    {clp(i.monto_clp)}
                                    {i.descuento_clp > 0 && (
                                        <span className="block text-xs font-normal text-emerald-400"
                                            data-testid="historial-pago-descuento">
                                            lista {clp(i.precio_lista_clp)} · −{clp(i.descuento_clp)}
                                        </span>
                                    )}
                                    {i.transacciones === 0 && (
                                        <span className="block text-xs font-normal text-zinc-500">
                                            sin pago registrado
                                        </span>
                                    )}
                                </td>
                            </tr>
                        );
                    })}
                    {items.length === 0 && (
                        <tr>
                            <td colSpan="4" className="py-6 text-center text-zinc-500">
                                Todavía no hay pagos registrados
                            </td>
                        </tr>
                    )}
                </Tabla>
                <Paginado paginado={datos.paginado} onPagina={onPagina} />
            </Card>
        </div>
    );
};


const SeccionMembresias = ({ datos, onPagina }) => {
    const r = datos.resumen || {};
    const actual = datos.membresia_actual;
    const items = datos.items || [];
    const suscripciones = datos.suscripciones || [];

    return (
        <div className="space-y-5" data-testid="historial-membresias">
            <div className="grid grid-cols-3 gap-3">
                <Dato label="Meses como alumno" valor={num(r.meses_como_alumno)} />
                <Dato label="Meses con plan" valor={num(r.meses_con_plan)} destacado
                    testid="historial-meses-con-plan" />
                <Dato label="Meses sin plan" valor={num(r.meses_sin_plan)} />
            </div>

            <Card titulo="Plan vigente hoy">
                {!actual ? (
                    <p className="text-sm text-zinc-500">Sin plan vigente hoy</p>
                ) : (
                    <p className="text-sm text-zinc-300">
                        <strong className="text-white">{actual.plan}</strong> · {clp(actual.precio_clp)}
                        {' · '}créditos {actual.es_ilimitado ? '∞' : (actual.creditos_disponibles ?? '—')}
                        {' · '}vence el {fechaCorta(actual.fecha_expiracion)}
                        {' '}({num(actual.dias_restantes)} días)
                    </p>
                )}
            </Card>

            <Card titulo="Mes a mes">
                <Tabla columnas={['Mes', 'Plan', 'Estado', 'Precio']}>
                    {items.map((i) => (
                        <tr key={`${i.anio}-${i.mes}`} data-testid="historial-mes">
                            <td className="py-2 pr-4 text-zinc-200">{etiquetaMes(i.anio, i.mes)}</td>
                            <td className="py-2 pr-4 text-zinc-300">
                                {i.plan || <span className="text-zinc-500">Sin plan</span>}
                            </td>
                            <td className="py-2 pr-4 capitalize text-zinc-400">{i.estado || '—'}</td>
                            <td className="py-2 pr-4 text-zinc-300">
                                {i.con_plan ? clp(i.precio_clp) : '—'}
                            </td>
                        </tr>
                    ))}
                    {items.length === 0 && (
                        <tr>
                            <td colSpan="4" className="py-6 text-center text-zinc-500">
                                Todavía no hay meses registrados
                            </td>
                        </tr>
                    )}
                </Tabla>
                <Paginado paginado={datos.paginado} onPagina={onPagina}
                    testid="historial-paginado-meses" />
            </Card>

            <Card titulo="Suscripciones registradas">
                <Tabla columnas={['Desde', 'Hasta', 'Plan', 'Estado', 'Cuenta como vigente']}>
                    {suscripciones.map((s) => (
                        <tr key={s.id}>
                            <td className="py-2 pr-4 text-zinc-300">{fechaCorta(s.fecha_inicio)}</td>
                            <td className="py-2 pr-4 text-zinc-300">
                                {fechaCorta(s.fecha_expiracion)}
                            </td>
                            <td className="py-2 pr-4 text-zinc-200">
                                {s.plan || `Plan ${s.plan_id}`}
                            </td>
                            <td className="py-2 pr-4 capitalize text-zinc-400">{s.estado}</td>
                            <td className="py-2 pr-4 text-zinc-300">
                                {s.cuenta_como_vigente ? 'Sí' : 'No (nunca estuvo vigente)'}
                            </td>
                        </tr>
                    ))}
                    {suscripciones.length === 0 && (
                        <tr>
                            <td colSpan="5" className="py-6 text-center text-zinc-500">
                                Sin suscripciones
                            </td>
                        </tr>
                    )}
                </Tabla>
            </Card>
        </div>
    );
};


// Estados de un pedido del Bazar (mismos valores que el backend) para la etiqueta de color.
const ESTADOS_BAZAR = {
    pendiente: { label: 'Pendiente', clase: 'bg-amber-500/20 text-amber-200' },
    validado: { label: 'Validado', clase: 'bg-sky-500/20 text-sky-300' },
    entregado: { label: 'Entregado', clase: 'bg-emerald-500/20 text-emerald-300' },
    cancelado: { label: 'Cancelado', clase: 'bg-red-500/20 text-red-300' },
};

const SeccionBazar = ({ datos, onPagina }) => {
    const t = datos.totales || {};
    const items = datos.items || [];

    return (
        <div className="space-y-5" data-testid="historial-bazar">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Dato label="Pedidos" valor={num(t.pedidos)} destacado
                    testid="historial-bazar-pedidos" />
                <Dato label="Cobrados" valor={num(t.cobrados)} />
                <Dato label="Pendientes" valor={num(t.pendientes)} />
                <Dato label="Total cobrado" valor={clp(t.cobrado_clp)}
                    testid="historial-bazar-cobrado" />
            </div>

            <p className="text-xs text-zinc-500">
                Aparecen TODOS los pedidos, incluidos los que todavía no se validaron. El “Total
                cobrado” suma solo los validados y entregados: es el mismo Bazar que muestra la
                pestaña Pagos. El código de retiro se genera cuando el box valida el pedido.
            </p>

            <Card titulo="Pedidos del bazar">
                <Tabla columnas={['Fecha', 'Producto', 'Cant.', 'Total', 'Estado', 'Código',
                    'Entregado por', 'Entregado el']}>
                    {items.map((p) => {
                        const estado = ESTADOS_BAZAR[p.estado]
                            || { label: p.estado, clase: 'bg-zinc-700 text-zinc-200' };
                        return (
                            <tr key={p.id} data-testid="historial-pedido">
                                <td className="py-2 pr-4 text-zinc-200">{fechaCorta(p.fecha)}</td>
                                <td className="py-2 pr-4 text-zinc-300">{p.producto}</td>
                                <td className="py-2 pr-4 text-zinc-400">{num(p.cantidad)}</td>
                                <td className="py-2 pr-4 font-semibold text-zinc-100">{clp(p.total_clp)}</td>
                                <td className="py-2 pr-4">
                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${estado.clase}`}>
                                        {estado.label}
                                    </span>
                                </td>
                                <td className="py-2 pr-4 font-mono text-zinc-300">
                                    {p.codigo_retiro
                                        || <span className="font-sans text-zinc-600">—</span>}
                                </td>
                                <td className="py-2 pr-4 text-zinc-400">{p.entregado_por || '—'}</td>
                                <td className="py-2 pr-4 text-zinc-400">
                                    {p.entregado_en ? fechaCorta(p.entregado_en) : '—'}
                                </td>
                            </tr>
                        );
                    })}
                    {items.length === 0 && (
                        <tr>
                            <td colSpan="8" className="py-6 text-center text-zinc-500">
                                Todavía no hay pedidos del bazar
                            </td>
                        </tr>
                    )}
                </Tabla>
                <Paginado paginado={datos.paginado} onPagina={onPagina}
                    testid="historial-paginado-bazar" />
            </Card>
        </div>
    );
};


const SeccionRms = ({ datos, onPagina }) => {
    const t = datos.totales || {};
    const items = datos.items || [];
    const porCategoria = t.por_categoria || {};

    return (
        <div className="space-y-5" data-testid="historial-rms">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Dato label="Movimientos con marca" valor={num(t.movimientos)} destacado />
                <Dato label="Registros" valor={num(t.registros)} />
                <Dato label="Fuerza" valor={num(porCategoria.fuerza || 0)} />
                <Dato label="Gimnasia" valor={num(porCategoria.gimnastico || 0)} />
            </div>

            <Card titulo="Mejor marca por movimiento">
                <Tabla columnas={['Movimiento', 'Categoría', 'Mejor marca', 'Registros', 'Última']}>
                    {items.map((i) => (
                        <tr key={i.id} data-testid="historial-rm">
                            <td className="py-2 pr-4 text-zinc-200">{i.movimiento_nombre}</td>
                            <td className="py-2 pr-4 capitalize text-zinc-400">{i.categoria}</td>
                            <td className="py-2 pr-4 font-semibold text-white">
                                {i.valor_mostrado}
                            </td>
                            <td className="py-2 pr-4 text-zinc-400">{num(i.registros)}</td>
                            <td className="py-2 pr-4 text-zinc-400">{fechaCorta(i.ultima_fecha)}</td>
                        </tr>
                    ))}
                    {items.length === 0 && (
                        <tr>
                            <td colSpan="5" className="py-6 text-center text-zinc-500">
                                Sin marcas registradas
                            </td>
                        </tr>
                    )}
                </Tabla>
                <Paginado paginado={datos.paginado} onPagina={onPagina}
                    testid="historial-paginado-rms" />
            </Card>
        </div>
    );
};


const ESTADO_BENEFICIO = {
    vigente: 'bg-emerald-500/15 text-emerald-300',
    usado: 'bg-sky-500/15 text-sky-300',
    vencido: 'bg-zinc-700/40 text-zinc-300',
    anulado: 'bg-red-500/10 text-red-300',
};

const SeccionBeneficios = ({ datos, onPagina }) => {
    const t = datos.totales || {};
    const items = datos.items || [];

    return (
        <div className="space-y-5" data-testid="historial-beneficios">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Dato label="Vigentes" valor={num(t.vigentes)} destacado />
                <Dato label="Usados" valor={num(t.usados)} />
                <Dato label="Vencidos" valor={num(t.vencidos)} />
                <Dato label="Anulados" valor={num(t.anulados)} />
            </div>

            <Card titulo="Regalos del box">
                <Tabla columnas={['Beneficio', 'Estado', 'Dado', 'Vale hasta', 'Uso', 'Nota']}>
                    {items.map((b) => (
                        <tr key={b.id} data-testid="historial-beneficio">
                            <td className="py-2 pr-4 text-zinc-200">
                                {b.tipo_label}
                                <span className="ml-1 font-semibold text-white">
                                    {b.unidad === 'pct' ? `−${b.valor} %` : `${b.valor} clase${b.valor === 1 ? '' : 's'}`}
                                </span>
                            </td>
                            <td className="py-2 pr-4">
                                <span className={`inline-block rounded-full px-2 py-0.5 text-xs ${ESTADO_BENEFICIO[b.estado] || ''}`}>
                                    {b.estado}
                                </span>
                            </td>
                            <td className="py-2 pr-4 text-zinc-400">{fechaCorta(b.created_at)}</td>
                            <td className="py-2 pr-4 text-zinc-400">{fechaCorta(b.vigente_hasta)}</td>
                            <td className="py-2 pr-4 text-zinc-400">
                                {b.estado === 'usado'
                                    ? `${fechaCorta(b.usado_en)}${b.descuento_clp != null ? ` · $${b.descuento_clp.toLocaleString('es-CL')}` : ''}`
                                    : '—'}
                            </td>
                            <td className="py-2 pr-4 text-zinc-500">
                                {b.anulado_motivo
                                    || (b.avisado_por_correo ? 'avisado por correo' : 'sin correo')}
                            </td>
                        </tr>
                    ))}
                    {items.length === 0 && (
                        <tr>
                            <td colSpan="6" className="py-6 text-center text-zinc-500">
                                Todavía no tiene beneficios
                            </td>
                        </tr>
                    )}
                </Tabla>
                <Paginado paginado={datos.paginado} onPagina={onPagina}
                    testid="historial-paginado-beneficios" />
            </Card>
        </div>
    );
};

// Sección → componente. La clave es el `id` que devuelve el backend.
const SECCIONES_RENDER = {
    resumen: SeccionResumen,
    asistencia: SeccionAsistencia,
    pagos: SeccionPagos,
    membresias: SeccionMembresias,
    bazar: SeccionBazar,
    rms: SeccionRms,
    beneficios: SeccionBeneficios,
};

// Pestañas del primer render (mientras llega la primera respuesta), con los mismos
// ids/labels que el servicio para no inventar un menú distinto al del backend.
const SECCIONES_UI = [
    { id: 'resumen', label: 'Resumen', disponible: true },
    { id: 'asistencia', label: 'Asistencia', disponible: true },
    { id: 'pagos', label: 'Pagos', disponible: true },
    { id: 'membresias', label: 'Membresías', disponible: true },
    { id: 'bazar', label: 'Bazar', disponible: true },
    { id: 'rms', label: 'RMs', disponible: true },
    { id: 'beneficios', label: 'Beneficios', disponible: true },
];


const PanelHistorial = ({ alumnoId = null }) => {
    const [searchParams, setSearchParams] = useSearchParams();
    const seccion = searchParams.get('seccion') || 'resumen';
    const [pagina, setPagina] = useState(1);
    const [panel, setPanel] = useState(null);
    const [cargando, setCargando] = useState(true);
    const [error, setError] = useState('');

    // Sin `alumnoId` se usa la puerta del propio alumno (nunca trae la gestión del box).
    const url = alumnoId
        ? `/api/v1/alumnos/${alumnoId}/historial`
        : '/api/v1/alumnos/me/historial';

    const cargar = useCallback(async () => {
        setCargando(true);
        setError('');
        try {
            const respuesta = await api.get(url, {
                params: { seccion, pagina, por_pagina: POR_PAGINA },
            });
            setPanel(respuesta.data);
        } catch (e) {
            console.error('Historial: no se pudo cargar', e);
            setPanel(null);
            setError(e.response?.data?.detail || 'No se pudo cargar el historial.');
        } finally {
            setCargando(false);
        }
    }, [url, seccion, pagina]);

    useEffect(() => { cargar(); }, [cargar]);

    // Cambiar de sección vuelve a la página 1 (una sección más corta daría vacío).
    const irASeccion = (id) => {
        setPagina(1);
        setSearchParams({ seccion: id });
    };

    const secciones = panel?.secciones?.length ? panel.secciones : SECCIONES_UI;
    const Render = SECCIONES_RENDER[seccion] || SeccionResumen;
    const alumno = panel?.alumno;

    return (
        <div className="space-y-5" data-testid="historial-panel">
            {alumno && (
                <div className="bg-zinc-900 rounded-lg shadow p-5 flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h2 className="text-xl font-bold text-white">{alumno.nombre}</h2>
                        <p className="text-sm text-zinc-400">
                            {alumno.correo} · alumno desde {fecha(alumno.alumno_desde || alumno.created_at)}
                            {alumno.antiguedad_dias !== null
                                && ` (${num(alumno.antiguedad_dias)} días)`}
                        </p>
                    </div>
                    <span className="px-3 py-1 rounded-full text-xs font-medium bg-zinc-800 text-zinc-300 capitalize">
                        {alumno.estado || '—'}
                    </span>
                </div>
            )}

            {/* Tabs del historial. En móvil (<768px): scroll horizontal (swipe),
                cada pestaña con alto táctil ≥44px y sin encogerse (shrink-0) para
                que el texto no se corte ni se monten unas con otras. En ≥768px
                se ve EXACTAMENTE igual que hoy (variantes `max-md:`). */}
            <div className="flex gap-2 overflow-x-auto pb-1 max-md:snap-x" data-testid="historial-tabs">
                {secciones.map((s) => (
                    <button
                        key={s.id}
                        type="button"
                        data-testid={`historial-tab-${s.id}`}
                        disabled={!s.disponible}
                        title={s.disponible ? undefined : (s.motivo || 'No disponible')}
                        onClick={() => irASeccion(s.id)}
                        className={`max-md:shrink-0 max-md:inline-flex max-md:items-center max-md:justify-center max-md:min-h-11 max-md:snap-start px-4 py-2 rounded-lg text-sm font-semibold whitespace-nowrap transition ${
                            seccion === s.id
                                ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/40'
                                : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'
                        } ${!s.disponible ? 'opacity-40 cursor-not-allowed' : ''}`}
                    >
                        {s.label}
                    </button>
                ))}
            </div>

            {cargando && (
                <div className="flex justify-center py-16">
                    <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
                </div>
            )}

            {!cargando && error && (
                <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-4 text-sm text-red-300"
                    data-testid="historial-error">
                    <p className="font-medium">⚠️ {error}</p>
                    <button type="button" onClick={cargar}
                        className="mt-2 px-3 py-1 bg-red-600 text-white rounded text-xs font-bold hover:bg-red-700">
                        Reintentar
                    </button>
                </div>
            )}

            {!cargando && !error && panel && (
                <Render datos={panel.datos || {}} onPagina={setPagina} />
            )}
        </div>
    );
};

export default PanelHistorial;
