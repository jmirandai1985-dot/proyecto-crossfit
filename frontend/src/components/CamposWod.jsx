import {
    TIPOS_BLOQUE, TIPOS_WOD, bloqueVacio,
} from '../utils/formulariosWod';

const CAMPO = 'mt-1.5 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none';
const ETIQUETA = 'block text-[12px] text-zinc-400';
const tagBtn = (activo) => `rounded-lg border px-3 py-1.5 text-[12px] font-semibold transition-colors ${activo ? 'border-orange-500 bg-orange-500/15 text-orange-200' : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'}`;

/**
 * Los campos del WOD de tipo metcon (el formulario histórico), COMPARTIDOS.
 *
 * POR QUÉ EXISTE: el `ModalPublicarWod` y la tarjeta "Publicar WOD" de la pestaña Clases del
 * coach publican con el mismo endpoint, así que tienen que ofrecer —y mandar— los MISMOS
 * campos: Calentamiento, Musculación, WOD · Nombre, Tipo, Descripción y los Bloques del WOD.
 * Este componente es la ÚNICA copia de esa UI; el payload se arma con
 * `contenidoMetconDesdeFormulario` (`utils/formulariosWod`), también único, para que los dos
 * formularios no puedan desincronizarse.
 *
 * Es controlado: no guarda estado. Props:
 *   · `form` / `setForm`       — { calentamiento, musculacion, wod_nombre, wod_tipo, wod_descripcion }
 *   · `bloques` / `setBloques` — [{ titulo, tipo_metcon, descripcion }]
 *   · `testidPrefijo`          — '' en el modal (testids de siempre) · 'inline-' en la
 *                                tarjeta del día, para que los dos puedan coexistir en la
 *                                página sin testids repetidos.
 */
const CamposWod = ({
    form, setForm, bloques, setBloques, testidPrefijo = '',
}) => {
    // Los testids del modal se mantienen tal cual (`wod-calentamiento`, `wod-bloques`, …):
    // la tarjeta inline los pide con prefijo. Un solo lugar que los define.
    const tid = (base) => `${testidPrefijo}${base}`;
    const setCampo = (campo) => (e) => setForm((prev) => ({ ...prev, [campo]: e.target.value }));
    const agregarBloque = () => setBloques((prev) => [...prev, bloqueVacio()]);
    const editarBloque = (indice, campo, valor) => setBloques(
        (prev) => prev.map((b, i) => (i === indice ? { ...b, [campo]: valor } : b)),
    );
    const quitarBloque = (indice) => setBloques(
        (prev) => prev.filter((_, i) => i !== indice));

    return (
        <>
            {/* Sección "contenido": los campos del WOD en sí, agrupados para que la
                jerarquía sea clara (arriba el contenido, abajo el alcance). */}
            <p className="pt-1 text-[11px] font-bold uppercase tracking-wider text-zinc-500">
                Contenido del WOD
            </p>

            <label className={ETIQUETA}>
                1 · Calentamiento
                <textarea rows={2} value={form.calentamiento}
                    onChange={setCampo('calentamiento')} maxLength={500}
                    placeholder="Ej. 400m trote + movilidad de cadera y hombro"
                    data-testid={tid('wod-calentamiento')} className={CAMPO} />
            </label>

            <label className={ETIQUETA}>
                2 · Musculación
                <textarea rows={2} value={form.musculacion}
                    onChange={setCampo('musculacion')} maxLength={500}
                    placeholder="Ej. 5x5 Back Squat 70%"
                    data-testid={tid('wod-musculacion')} className={CAMPO} />
            </label>

            <label className={ETIQUETA}>
                3 · WOD · Nombre
                <input type="text" value={form.wod_nombre} onChange={setCampo('wod_nombre')}
                    maxLength={200} placeholder="Ej. Fran, Cindy…"
                    data-testid={tid('wod-nombre')} className={CAMPO} />
            </label>

            <div>
                <span className={ETIQUETA}>Tipo</span>
                <div className="mt-1.5 flex flex-wrap gap-2" data-testid={tid('wod-tipos')}>
                    {TIPOS_WOD.map((tipo) => (
                        <button key={tipo} type="button"
                            onClick={() => setForm((prev) => ({ ...prev, wod_tipo: tipo }))}
                            data-testid={tid(`wod-tipo-${tipo}`)}
                            className={tagBtn(form.wod_tipo === tipo)}>{tipo}</button>
                    ))}
                </div>
            </div>


            <label className={ETIQUETA}>
                Descripción
                <textarea rows={3} value={form.wod_descripcion}
                    onChange={setCampo('wod_descripcion')} maxLength={500}
                    placeholder="Ej. 21-15-9 Thrusters / Pull-ups"
                    data-testid={tid('wod-descripcion')} className={CAMPO} />
            </label>

            {/* ── Bloques del WOD (opcional) ──
                Un WOD real puede tener 2 metcons + un RM final. Sin bloques se comporta
                EXACTAMENTE como antes (WOD simple). */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-3" data-testid={tid('wod-bloques')}>
                <div className="flex items-start justify-between gap-2">
                    <div>
                        <p className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Bloques del WOD</p>
                        <p className="mt-0.5 text-[10.5px] text-zinc-500">
                            Opcional: metcons encadenados y/o un RM final. Sin bloques = un único resultado.
                        </p>
                    </div>
                    <button type="button" onClick={agregarBloque}
                        data-testid={tid('agregar-bloque')}
                        className="shrink-0 rounded-lg border border-emerald-600/60 bg-emerald-600/15 px-2.5 py-1.5 text-[11px] font-bold text-emerald-200 hover:bg-emerald-600/25">
                        + Agregar bloque
                    </button>
                </div>
                {bloques.length === 0 ? (
                    <p className="mt-2 text-[11px] italic text-zinc-600">
                        Este WOD no tiene bloques.
                    </p>
                ) : (
                    <div className="mt-2 space-y-2">
                        {bloques.map((bloque, indice) => (
                            <div key={indice} className="rounded-lg border border-zinc-800 bg-zinc-900 p-2.5"
                                data-testid={tid(`bloque-${indice}`)}>
                                <div className="flex items-center justify-between gap-2">
                                    <span className="text-[10.5px] font-black uppercase tracking-wide text-zinc-400">
                                        Bloque {indice + 1}
                                    </span>
                                    <button type="button" onClick={() => quitarBloque(indice)}
                                        data-testid={tid(`quitar-bloque-${indice}`)}
                                        className="rounded px-2 py-0.5 text-[11px] font-semibold text-red-300 hover:bg-red-500/10">
                                        Quitar
                                    </button>
                                </div>
                                <input type="text" value={bloque.titulo}
                                    onChange={(e) => editarBloque(indice, 'titulo', e.target.value)}
                                    maxLength={200} placeholder="Título (ej. Metcon 1, RM Final)"
                                    data-testid={tid(`bloque-titulo-${indice}`)}
                                    className={`${CAMPO} mt-1.5`} />
                                <div className="mt-1.5 flex flex-wrap gap-1.5">
                                    {TIPOS_BLOQUE.map((tipo) => (
                                        <button key={tipo} type="button"
                                            onClick={() => editarBloque(indice, 'tipo_metcon', tipo)}
                                            data-testid={tid(`bloque-tipo-${indice}-${tipo}`)}
                                            className={tagBtn(bloque.tipo_metcon === tipo)}>
                                            {tipo}
                                        </button>
                                    ))}
                                </div>
                                <textarea rows={2} value={bloque.descripcion}
                                    onChange={(e) => editarBloque(indice, 'descripcion', e.target.value)}
                                    maxLength={2000}
                                    placeholder="Detalle del bloque (ej. 21-15-9 Thrusters / Pull-ups)"
                                    data-testid={tid(`bloque-descripcion-${indice}`)}
                                    className={`${CAMPO} mt-1.5`} />
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </>
    );
};

export default CamposWod;
