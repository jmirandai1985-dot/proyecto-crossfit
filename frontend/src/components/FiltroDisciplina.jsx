/**
 * FiltroDisciplina — chips "Todas" + cada disciplina.
 *
 * POR QUÉ EXISTE: el mismo control lo usan "Mis Reservas" (variante `claro`,
 * Tailwind) y las dos pantallas móviles que pintan clases: "Clases disponibles"
 * del Inicio del alumno y la "Asistencia" del panel del admin (variante `ub`,
 * estilos de `inicioMobile.css` / `inicioMobileAdmin.css`, según el ancestro).
 *
 * Reglas del mockup que respeta:
 *   · objetivos táctiles ≥44px de alto (`min-h-11` / `min-height: 44px`);
 *   · la fila scrollea en horizontal si hay muchas disciplinas;
 *   · con UNA sola disciplina no se pinta nada (`hayQueFiltrar`): no hay nada
 *     que filtrar y "Todas" sería un chip inútil.
 *
 * Regla de oro ≥768px: en Mis Reservas el contenedor lleva `md:hidden`, así que
 * el filtro sigue siendo SÓLO móvil, igual que hoy; el Inicio móvil entero se
 * pinta bajo <768px.
 */
import { DISCIPLINA_INSIGNIA, TODAS, hayQueFiltrar, ordenarChips } from '../utils/filtroDisciplina';

// Las dos pieles del mismo control. `claro` = panel del alumno (Tailwind);
// `ub` = Inicio móvil (clases `ub-*` definidas en pages/alumno/inicioMobile.css).
// `insignia` = la disciplina insignia (CrossFit): siempre relleno naranja sólido.
const VARIANTES = {
    claro: {
        contenedor: 'md:hidden flex gap-2 overflow-x-auto pb-1',
        boton: 'shrink-0 inline-flex items-center justify-center min-h-11 px-4 rounded-full border text-sm font-semibold transition-colors',
        activo: 'bg-emerald-500 text-white border-emerald-500',
        inactivo: 'bg-white text-gray-700 border-gray-300 hover:border-emerald-400',
        insignia: 'bg-orange-500 text-white border-orange-500',
    },
    ub: {
        contenedor: 'filtro',
        boton: '',
        activo: 'on',
        inactivo: '',
        insignia: 'insignia',
    },
};

const FiltroDisciplina = ({
    disciplinas = [],
    valor = TODAS,
    onCambiar,
    variante = 'claro',
    testid,
}) => {
    const piel = VARIANTES[variante] || VARIANTES.claro;
    if (!hayQueFiltrar(disciplinas)) return null;

    return (
        <div className={piel.contenedor} data-testid={testid}>
            {ordenarChips(disciplinas).map((disciplina) => {
                const activo = valor === disciplina;
                const insignia = disciplina === DISCIPLINA_INSIGNIA;
                const clases = insignia
                    ? [piel.boton, piel.insignia]
                    : [piel.boton, activo ? piel.activo : piel.inactivo];
                return (
                    <button
                        key={disciplina}
                        type="button"
                        onClick={() => onCambiar && onCambiar(disciplina)}
                        aria-pressed={activo}
                        className={clases.filter(Boolean).join(' ')}
                    >
                        {disciplina}
                    </button>
                );
            })}
        </div>
    );
};

export default FiltroDisciplina;
