// Clases compartidas por los formularios de familia del modal "Publicar WOD".
// Mismo lenguaje visual que el formulario de metcon (dark: zinc + naranjo).
export const CAMPO = 'mt-1.5 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none';
export const ETIQUETA = 'block text-[12px] text-zinc-400';
export const TARJETA = 'rounded-xl border border-zinc-800 bg-zinc-950/40 p-3';
export const BOTON_AGREGAR = 'shrink-0 rounded-lg border border-emerald-600/60 bg-emerald-600/15 px-2.5 py-1.5 text-[11px] font-bold text-emerald-200 hover:bg-emerald-600/25';
export const BOTON_QUITAR = 'rounded px-2 py-0.5 text-[11px] font-semibold text-red-300 hover:bg-red-500/10';
export const BOTON_MOVER = 'rounded border border-zinc-700 px-2 py-0.5 text-[11px] font-semibold text-zinc-300 hover:border-zinc-500 disabled:opacity-40';
export const BOTON_TOGGLE = (activo) => `rounded-lg border px-3 py-1.5 text-[12px] font-semibold transition-colors ${activo ? 'border-orange-500 bg-orange-500/15 text-orange-200' : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'}`;
export const TITULO_SECCION = 'text-[11px] font-bold uppercase tracking-wider text-zinc-500';
export const AYUDA = 'mt-0.5 text-[10.5px] text-zinc-500';
