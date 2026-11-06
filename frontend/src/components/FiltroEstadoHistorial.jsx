/**
 * FiltroEstadoHistorial — chips fijos "Todas / Asistió / No asistió / Cancelada".
 *
 * POR QUÉ EXISTE: el Historial de "Mis Reservas" hoy pinta TODO desplegado sin
 * filtro y, con muchos meses, la lista se hace larga. Se agrega un filtro por
 * estado SOLO para el historial (las activas son pocas y no lo necesitan).
 *
 * Mismo patrón VISUAL que `FiltroDisciplina` en su variante `claro` (Tailwind):
 * chips con min-height 44px, scroll horizontal si no entran y `md:hidden` para
 * que siga siendo SÓLO móvil (en desktop el historial no tiene ese scroll largo).
 *
 * Las opciones y la agrupación de `cancelada` + `cancelada_tarde` viven en
 * `utils/estadoReserva.js` (ESTADOS_HISTORIAL), la misma fuente que los rótulos.
 */
import { ESTADOS_HISTORIAL } from '../utils/estadoReserva';

// La MISMA piel "claro" de FiltroDisciplina (clases Tailwind copiadas a propósito,
// para no acoplar este control a la lógica de disciplinas dinámicas).
const PIEL = {
    contenedor: 'md:hidden flex gap-2 overflow-x-auto pb-1',
    boton: 'shrink-0 inline-flex items-center justify-center min-h-11 px-4 rounded-full border text-sm font-semibold transition-colors',
    activo: 'bg-emerald-500 text-white border-emerald-500',
    inactivo: 'bg-white text-gray-700 border-gray-300 hover:border-emerald-400',
};

const FiltroEstadoHistorial = ({ valor = 'Todas', onCambiar, testid }) => (
    <div className={PIEL.contenedor} data-testid={testid}>
        {ESTADOS_HISTORIAL.map((op) => {
            const activo = valor === op.id;
            return (
                <button
                    key={op.id}
                    type="button"
                    onClick={() => onCambiar && onCambiar(op.id)}
                    aria-pressed={activo}
                    className={[PIEL.boton, activo ? PIEL.activo : PIEL.inactivo].join(' ')}
                >
                    {op.label}
                </button>
            );
        })}
    </div>
);

export default FiltroEstadoHistorial;
