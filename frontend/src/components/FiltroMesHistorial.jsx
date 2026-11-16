/**
 * FiltroMesHistorial — chips "Todos" + un chip por mes del historial
 * ("Noviembre 2026", "Octubre 2026", …).
 *
 * POR QUÉ EXISTE: el Historial de "Mis Reservas" agrupa por mes
 * (`agruparReservasPorMes`) y con varios meses de historial el scroll se hace
 * larguísimo. Con estos chips el alumno salta directo al mes que busca, sin un
 * `<select>` nativo (en el teléfono los chips son más cómodos y siguen el mismo
 * patrón táctil del resto de la pantalla).
 *
 * Mismo patrón VISUAL que `FiltroEstadoHistorial` (misma piel de chips que
 * `FiltroDisciplina`): chips con min-height 44px y scroll horizontal en mobile. La
 * elección NO se persiste: la pantalla arranca siempre en "Todos" (igual que el
 * filtro de estado).
 *
 * Los meses llegan ya calculados por la pantalla a partir de `gruposHistorial`
 * ([{ clave: 'YYYY-MM', label: 'Noviembre 2026' }]): acá no se agrupa ni se
 * consulta nada.
 */
import { TODOS_LOS_MESES } from '../utils/reservasEstadisticas';

// La MISMA piel "claro" de FiltroEstadoHistorial (clases Tailwind copiadas a
// propósito, mismo criterio que ese componente con FiltroDisciplina).
const PIEL = {
    contenedor: 'flex gap-2 overflow-x-auto pb-1 md:flex-wrap md:overflow-x-visible',
    boton: 'shrink-0 inline-flex items-center justify-center min-h-11 px-4 rounded-full border text-sm font-semibold transition-colors',
    activo: 'bg-emerald-500 text-white border-emerald-500',
    inactivo: 'bg-white text-gray-700 border-gray-300 hover:border-emerald-400',
};

const FiltroMesHistorial = ({ valor = TODOS_LOS_MESES, meses = [], onCambiar, testid }) => {
    // "Todos" primero, luego los meses tal como vienen (más reciente primero).
    const opciones = [{ clave: TODOS_LOS_MESES, label: TODOS_LOS_MESES }, ...meses];

    return (
        <div
            className={PIEL.contenedor}
            data-testid={testid}
            aria-label="Filtrar el historial por mes"
        >
            {opciones.map((mes) => {
                const activo = valor === mes.clave;
                return (
                    <button
                        key={mes.clave}
                        type="button"
                        onClick={() => onCambiar && onCambiar(mes.clave)}
                        aria-pressed={activo}
                        className={[PIEL.boton, activo ? PIEL.activo : PIEL.inactivo].join(' ')}
                    >
                        {mes.label}
                    </button>
                );
            })}
        </div>
    );
};

export default FiltroMesHistorial;
