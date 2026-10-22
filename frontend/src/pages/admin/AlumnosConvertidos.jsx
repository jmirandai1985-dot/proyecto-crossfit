import React from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAlumnosConvertidos } from '../../hooks/queries';
import { mensajeError } from '../../services/queryClient';
import { hoyChileStr } from '../../utils/fecha';

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

const formatCLP = (valor) => `$${Number(valor || 0).toLocaleString('es-CL')}`;

/**
 * Mes CERRADO por defecto: el anterior al actual. Es el mismo período que publica
 * el BI para la tarjeta "Convertidos" cuando nadie pasó `anio`/`mes`.
 */
const periodoPorDefecto = () => {
    const hoy = new Date(`${hoyChileStr()}T12:00:00Z`);
    let anio = hoy.getUTCFullYear();
    // getUTCMonth() es 0-based: en octubre vale 9, que ES el número de septiembre.
    let mes = hoy.getUTCMonth();
    if (mes === 0) {
        mes = 12;
        anio -= 1;
    }
    return { anio, mes };
};

const periodoDeParams = (searchParams) => {
    const defecto = periodoPorDefecto();
    const anio = Number(searchParams.get('anio'));
    const mes = Number(searchParams.get('mes'));
    const valido = Number.isInteger(anio) && anio >= 2000
        && Number.isInteger(mes) && mes >= 1 && mes <= 12;
    return valido ? { anio, mes } : defecto;
};

/**
 * Detalle de la tarjeta "Convertidos": las altas de plan COMERCIAL del mes que
 * respaldan el número del BI (`GET /admin/alumnos-convertidos`).
 *
 * La tarjeta manda `?anio=&mes=` con el período EXACTO que publicó el BI, así el
 * total de esta pantalla y el de la tarjeta son el mismo dato. Sin params se abre
 * el último mes cerrado.
 */
const AlumnosConvertidos = () => {
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const { anio, mes } = periodoDeParams(searchParams);
    const { data, isPending, isError, error, refetch } = useAlumnosConvertidos(anio, mes);

    const alumnos = data?.alumnos ?? [];
    const total = data?.total ?? alumnos.length;
    const recaudado = alumnos.reduce((suma, a) => suma + Number(a.precio_clp || 0), 0);
    const ticketPromedio = total > 0 ? Math.round(recaudado / total) : 0;

    const cambiarPeriodo = (delta) => {
        const totalMeses = anio * 12 + (mes - 1) + delta;
        setSearchParams({
            anio: String(Math.floor(totalMeses / 12)),
            mes: String((totalMeses % 12) + 1),
        });
    };
    const periodoLabel = `${MESES[mes - 1]} ${anio}`;

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <button
                            type="button"
                            onClick={() => navigate('/admin/dashboard')}
                            className="mb-2 text-sm text-zinc-400 hover:text-zinc-200"
                        >
                            ← Volver al dashboard
                        </button>
                        <h1 className="text-3xl font-bold text-zinc-100">Alumnos convertidos</h1>
                        <p className="mt-1 text-zinc-400">
                            Altas de plan pagado de {periodoLabel}: alumnos que pasaron de prueba a un
                            plan comercial. Mismo criterio que la tarjeta Convertidos: planes con
                            precio, sin pruebas ni regalos.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => cambiarPeriodo(-1)}
                            className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-700"
                            aria-label="Mes anterior"
                            title="Mes anterior"
                        >
                            ←
                        </button>
                        <span className="min-w-[9rem] text-center text-sm font-semibold text-zinc-100">
                            {periodoLabel}
                        </span>
                        <button
                            type="button"
                            onClick={() => cambiarPeriodo(1)}
                            className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-700"
                            aria-label="Mes siguiente"
                            title="Mes siguiente"
                        >
                            →
                        </button>
                    </div>
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    <div className="rounded-lg border-l-4 border-teal-500 bg-zinc-900 p-5 shadow">
                        <p className="text-xs font-bold uppercase tracking-wide text-zinc-400">Convertidos</p>
                        <p className="mt-1 text-3xl font-bold text-teal-400">{isPending ? '…' : total}</p>
                        <p className="mt-1 text-xs text-zinc-500">Altas de plan comercial del mes</p>
                    </div>
                    <div className="rounded-lg border-l-4 border-emerald-500 bg-zinc-900 p-5 shadow">
                        <p className="text-xs font-bold uppercase tracking-wide text-zinc-400">Valor de lista</p>
                        <p className="mt-1 text-3xl font-bold text-emerald-400">
                            {isPending ? '…' : formatCLP(recaudado)}
                        </p>
                        <p className="mt-1 text-xs text-zinc-500">Suma del precio de los planes comprados</p>
                    </div>
                    <div className="rounded-lg border-l-4 border-blue-500 bg-zinc-900 p-5 shadow">
                        <p className="text-xs font-bold uppercase tracking-wide text-zinc-400">Ticket promedio</p>
                        <p className="mt-1 text-3xl font-bold text-blue-400">
                            {isPending ? '…' : formatCLP(ticketPromedio)}
                        </p>
                        <p className="mt-1 text-xs text-zinc-500">Precio de lista promedio por alta</p>
                    </div>
                </div>

                <div className="overflow-hidden rounded-lg bg-zinc-900 shadow">
                    <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
                        <h2 className="text-lg font-bold text-zinc-100">Detalle de conversiones</h2>
                        <button
                            type="button"
                            onClick={() => refetch()}
                            className="rounded-lg bg-zinc-800 px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-700"
                        >
                            ⟳ Actualizar
                        </button>
                    </div>

                    {isError ? (
                        <div className="p-8 text-center">
                            <p className="text-sm text-red-300">
                                ⚠️ {mensajeError(error, 'No se pudieron cargar los alumnos convertidos')}
                            </p>
                            <button
                                type="button"
                                onClick={() => refetch()}
                                className="mt-3 rounded-lg bg-zinc-800 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-700"
                            >
                                Reintentar
                            </button>
                        </div>
                    ) : isPending ? (
                        <div className="p-10 text-center text-sm text-zinc-400">Cargando conversiones…</div>
                    ) : alumnos.length === 0 ? (
                        <div className="p-10 text-center">
                            <p className="text-sm text-zinc-300">No hubo altas de plan en {periodoLabel}.</p>
                            <p className="mt-1 text-xs text-zinc-500">
                                Los alumnos con prueba gratuita o planes de regalo no cuentan como conversión.
                            </p>
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-zinc-800">
                                    <tr>
                                        <th className="px-6 py-3 text-left text-xs font-medium uppercase text-zinc-400">Alumno</th>
                                        <th className="px-6 py-3 text-left text-xs font-medium uppercase text-zinc-400">Plan</th>
                                        <th className="px-6 py-3 text-left text-xs font-medium uppercase text-zinc-400">Precio</th>
                                        <th className="px-6 py-3 text-left text-xs font-medium uppercase text-zinc-400">Fecha de conversión</th>
                                        <th className="px-6 py-3 text-left text-xs font-medium uppercase text-zinc-400">Vence</th>
                                        <th className="px-6 py-3 text-left text-xs font-medium uppercase text-zinc-400">Estado</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">

                                    {alumnos.map((a, index) => (
                                        <tr
                                            key={`${a.suscripcion_id}-${a.id}`}
                                            className={`${index % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'} cursor-pointer hover:bg-zinc-800`}
                                            onClick={() => navigate(`/admin/alumnos/${a.id}/historial`)}
                                            title="Ver el historial del alumno"
                                        >
                                            <td className="px-6 py-4">
                                                <p className="text-sm font-semibold text-zinc-100">{a.nombre}</p>
                                                <p className="text-xs text-zinc-400">{a.correo}</p>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-200">{a.plan_nombre || '—'}</td>
                                            <td className="px-6 py-4 text-sm font-bold text-emerald-400">
                                                {formatCLP(a.precio_clp)}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-300">
                                                {a.fecha_inicio ? String(a.fecha_inicio).slice(0, 10) : '—'}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-300">
                                                {a.fecha_expiracion ? String(a.fecha_expiracion).slice(0, 10) : '—'}
                                            </td>
                                            <td className="px-6 py-4 text-sm">
                                                <span className="rounded-full bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-300">
                                                    {a.estado || '—'}
                                                </span>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </Layout>
    );
};

export default AlumnosConvertidos;

