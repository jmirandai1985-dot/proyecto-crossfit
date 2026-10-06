/**
 * Detalle de CADA tarjeta de KPIs, en UN solo lugar.
 *
 * Por qué existe: las tarjetas de las tres pestañas (Diario, Mensual e Inteligencia de Negocio)
 * mostraban un número con un rótulo y nada más. Para decidir con el dato hay que poder responder
 * cuatro preguntas, y son las cuatro claves de cada entrada de este catálogo:
 *
 *   - `que`     : qué mide, en una frase, sin siglas.
 *   - `calculo` : cómo sale el número (de qué se toma y qué queda afuera).
 *   - `lectura` : qué valor es bueno y qué valor es malo.
 *   - `accion`  : qué hacer con el dato.
 *
 * Las abre `KpiDetalleModal` desde el clic (o Enter/Espacio) en cualquier `KpiCard`. Las
 * definiciones están escritas para el DUEÑO DEL BOX: nada de nombres de tablas, endpoints ni
 * columnas — eso vive en el código del backend, no en la pantalla.
 *
 * Las claves son `<pestaña>:<dato>` para que el mismo dato de dos pestañas (el MRR del mes y el
 * MRR de hoy, por ejemplo) pueda explicarse distinto: son números parecidos pero NO el mismo
 * período, y confundirlos es el error que este detalle tiene que evitar.
 */

/** Fábrica de una entrada: obliga a completar las cuatro preguntas (y el rótulo del valor). */
const kpi = (label, valorTitulo, que, calculo, lectura, accion) => ({
    label, valorTitulo, que, calculo, lectura, accion,
});

export const DETALLES_KPI = {
    // ── Pestaña DIARIO: el día del dato (el job puebla AYER) ─────────────────────
    'diario:alumnos_activos': kpi(
        'Alumnos activos',
        'Membresías vigentes ese día',
        'Cuántas membresías seguían vigentes el día del dato: es la foto del tamaño del box ese día.',
        'Se cuentan las membresías de alumno vigentes al cerrar ese día y de un plan que se vende. '
        + 'Los planes internos de regalo dan acceso pero NO cuentan como cliente, y un alumno con dos '
        + 'membresías activas cuenta dos veces.',
        'Más alto es mejor, pero lo que importa es la tendencia: si baja varios días seguidos, se están '
        + 'yendo más alumnos de los que entran.',
        'Si viene bajando, abrir Fidelización y revisar el riesgo de abandono de esos alumnos: ahí están '
        + 'los botones para contactarlos o darles un beneficio.',
    ),
    'diario:alumnos_nuevos': kpi(
        'Alumnos nuevos',
        'Fichas de alumno creadas ese día',
        'Cuántos alumnos se dieron de alta ese día, tengan o no plan pagado (incluye a quien recién '
        + 'empieza con la clase de prueba).',
        'Se cuenta cada ficha de alumno creada ese día.',
        'No hay un número bueno: un día en 0 es normal, una semana entera en 0 no. Es el motor del box '
        + 'y por eso se mira junto con la conversión del mes.',
        'Si entran muchos alumnos y compran pocos, el problema no es captar: es el cierre. Mirar la '
        + 'conversión prueba→plan de la pestaña Mensual y el seguimiento después de la clase de prueba.',
    ),
    'diario:asistentes_totales': kpi(
        'Asistentes del día',
        'Personas que entrenaron ese día',
        'Cuántas personas entrenaron ese día, contando sólo las asistencias que quedaron marcadas.',
        'Se cuentan las reservas de ese día que terminaron marcadas como asistidas.',
        'Es el pulso del box. Conviene leerlo junto con la ocupación: mucha gente con poca ocupación '
        + 'significa que la gente está repartida en horarios donde casi no hay clases.',
        'Si un día cae mucho respecto del mismo día de semanas anteriores, revisar primero feriados, '
        + 'clima y clases canceladas antes de dar por hecho que se está perdiendo gente.',
    ),
    'diario:ingresos_total': kpi(
        'Ingresos del día',
        'Dinero cargado ese día',
        'Cuánto dinero entró ese día, sumando membresías y bazar.',
        'Suma de las transacciones cargadas como ingreso en la fecha del dato. Es lo registrado en el '
        + 'sistema, no lo que muestra el banco ni la pasarela de pago.',
        'Los ingresos se concentran al principio del mes (cuando se cobran las membresías): un día en 0 '
        + 'no dice nada, el acumulado del mes sí.',
        'Si el día quedó en 0 y debería haber cobros, revisar que esos cobros se hayan cargado en '
        + 'Ingresos: el dato sale de ahí y no del banco.',
    ),
    'diario:clases_ejecutadas': kpi(
        'Clases ejecutadas',
        'Clases dictadas ese día',
        'Cuántas clases se dictaron ese día.',
        'Se cuentan las clases programadas para ese día que no quedaron canceladas.',
        'Comparado con los asistentes dice si la oferta está bien puesta: muchas clases con poca gente '
        + 'es coach y sala pagados para pocos.',
        'Con el detalle de bloques horarios (Inteligencia de Negocio) se ve en qué franja sobra oferta, '
        + 'y ahí es donde se ajustan horarios.',
    ),
    'diario:ocupacion_promedio': kpi(
        'Ocupación promedio',
        'Lugares usados sobre los ofrecidos',
        'Qué porcentaje de los lugares que se ofrecieron ese día se usó.',
        'Asistentes del día dividido por el cupo total de las clases dictadas ese día, en porcentaje.',
        'Arriba de 80 % el box está lleno (y conviene abrir cupos u horarios). Abajo de 40 % hay lugares '
        + 'ofrecidos que nadie usa (se pueden juntar clases). En el medio, sano.',
        'Si un horario está alto de forma sostenida, es la señal para sumar una clase en ese bloque; si '
        + 'está bajo, para juntar dos clases o mover el horario.',
    ),
    'diario:reservas_confirmadas': kpi(
        'Reservas confirmadas',
        'Reservas hechas ese día',
        'Cuántas reservas se hicieron ese día, sin importar para qué día de clase son.',
        'Se cuentan las reservas creadas ese día que quedaron en estado confirmada.',
        'Mide el uso de la app: una caída fuerte de reservas suele avisar ANTES que la caída de '
        + 'asistentes.',
        'Leerlo junto con las cancelaciones: si las dos suben, hay clases que se llenan y se vacían el '
        + 'mismo día (revisar horarios y recordatorios).',
    ),
    'diario:cancellaciones': kpi(
        'Cancelaciones',
        'Reservas canceladas ese día',
        'Cuántas reservas se cancelaron ese día.',
        'Se cuentan las reservas que quedaron canceladas en esa fecha. El crédito vuelve al alumno sólo '
        + 'si avisó con la anticipación mínima (6 horas antes de la clase).',
        'Pocas cancelaciones con aviso son sanas: el alumno libera el lugar y lo puede usar otro. Muchas, '
        + 'o casi todas a último minuto, rompen la ocupación.',
        'Si se concentran en un horario puntual, revisar si la clase es la que los alumnos esperan '
        + '(nivel, coach) y usar las notificaciones para recordar la reserva.',
    ),
    'diario:ingresos_membresia': kpi(
        'Ingresos por membresía',
        'Dinero de planes ese día',
        'La parte de los ingresos del día que viene de planes y membresías.',
        'Igual que Ingresos del día, mirando sólo las transacciones de membresías.',
        'Es el ingreso recurrente del box: la columna que sostiene el negocio. Un mes con bazar fuerte y '
        + 'membresía floja no es un mes sano.',
        'Si cae respecto de los meses anteriores, mirar el MRR y los alumnos activos de la pestaña '
        + 'Mensual, y la lista de planes por vencer de Fidelización.',
    ),
    'diario:ingresos_bazar': kpi(
        'Ingresos por bazar',
        'Dinero de bazar ese día',
        'La parte de los ingresos del día que viene del bazar (suplementos, ropa, accesorios).',
        'Suma de los pedidos del bazar COBRADOS ese día: los que el box ya validó (o entregó). '
        + 'Un pedido con el comprobante sin revisar todavía no es plata y no suma; un pedido '
        + 'cancelado tampoco. Es la misma cuenta que ven el historial del alumno y el reporte '
        + 'descargable.',
        'Es ingreso variable, no recurrente: suma, pero no se puede planificar como la membresía. '
        + 'Un día en 0 es normal si nadie pidió nada.',
        'Si el bazar aporta mucho, dejar el stock y los precios al día: los avisos de stock bajo '
        + 'llegan por correo.',
    ),

    // ── Pestaña MENSUAL: el mes elegido (cerrado, o el mes en curso parcial) ─────
    'mensual:conversion_rate': kpi(
        'Conversión prueba→plan',
        'Conversión del mes',
        'De cada 100 alumnos que arrancan con la clase de prueba en el mes, cuántos terminan comprando '
        + 'un plan.',
        'Alumnos que compraron en el mes dividido por los alumnos que empezaron su prueba ese mismo mes, '
        + 'en porcentaje. El bloque "Proceso de Conversión de Nuevos Clientes" de esta pantalla muestra '
        + 'los dos números y el escalón del medio (los que efectivamente ejecutaron la prueba).',
        'Es el termómetro comercial: abajo de 30 % hay margen claro para mejorar, arriba de 50 % el '
        + 'cierre está afinado. Comparar el mismo mes de meses anteriores dice más que el número solo.',
        'Si está baja, revisar el proceso completo: cuántos de los que empezaron la prueba alcanzaron a '
        + 'venir a una clase y qué seguimiento reciben después.',
    ),
    'mensual:churn_rate': kpi(
        'Riesgo de abandono',
        'Alumnos con plan que se pierden',
        'De los alumnos que tenían plan vigente, qué porcentaje dejó de tenerlo en el mes.',
        'Se toma el grupo de alumnos vigentes y se mira cuántos siguen vigentes al cierre; el resto es lo '
        + 'que se perdió. Si el grupo es muy chico (menos de 5 alumnos) el porcentaje no se publica y se '
        + 'muestra "—": un porcentaje calculado sobre dos personas no representa al box.',
        'Más bajo es mejor: hasta 5 % el box retiene bien, arriba de 10 % está perdiendo gente más rápido '
        + 'de lo que la repone. Un "—" no es bueno ni malo: es "todavía no hay con qué calcularlo".',
        'Si sube, abrir Fidelización y mirar primero a los alumnos inactivos: son los que están por irse.',
    ),
    'mensual:mrr': kpi(
        'Ingresos Recurrentes Mensuales (MRR)',
        'Plan al mes a precio de lista, al cierre',
        'Cuánto factura el box al mes por los planes vigentes, a precio de lista.',
        'Suma del precio de lista de los planes vigentes al cierre del mes. NO descuenta descuentos '
        + 'puntuales ni egresos (es ingreso recurrente, no caja) y no cuenta los planes internos de '
        + 'regalo.',
        'Es la medida estable del tamaño del negocio: sube cuando entran alumnos o cuando sube el '
        + 'precio, baja cuando se van. Comparado con el mes anterior dice si el box crece.',
        'Si baja dos meses seguidos, cruzarlo con el riesgo de abandono y con la conversión de pruebas: '
        + 'el problema está en uno de los dos lados.',
    ),
    'mensual:ingresos_total': kpi(
        'Ingresos del mes',
        'Caja neta del mes',
        'La plata que efectivamente entró en el mes.',
        'Ingresos del mes menos los egresos cargados en ese mes. Es el mismo número que Reportes muestra '
        + 'como ingreso neto del mes.',
        'Es la foto de la caja y se mueve distinto que el MRR: un mes puede tener MRR parejo y un ingreso '
        + 'flojo por menos bazar o menos altas nuevas. En el mes EN CURSO los números van a medias.',
        'Comparar con los meses anteriores en el selector de arriba y bajar al detalle de ingresos de '
        + 'Reportes para revisar los meses flojos.',
    ),
    // Separada a propósito de MRR e Ingresos del mes: es BRUTA (sin egresos), no recurrente y no
    // está incluida en las otras dos.
    'mensual:ingresos_bazar': kpi(
        'Ventas Bazar',
        'Plata del bazar en el mes',
        'Cuánto vendió el bazar del box en el mes (suplementos, ropa, accesorios).',
        'Suma de los pedidos COBRADOS del mes (validados o entregados), por la fecha del pedido. '
        + 'Un pedido con el comprobante sin revisar todavía no es plata y no suma. No está incluida '
        + 'en el MRR (que sólo cuenta planes, a precio de lista) ni en el ingreso del mes (que es '
        + 'caja neta de las transacciones).',
        'Es ingreso variable: un mes fuerte de bazar mejora la caja, pero no dice nada del tamaño '
        + 'del negocio (para eso está el MRR). Conviene compararlo con el mismo mes de años anteriores.',
        'Si el bazar crece, revisar stock, precios y la entrega de los pedidos: un pedido pagado que '
        + 'nadie retira es una mala experiencia para el alumno.',
    ),
    'mensual:asistencia_promedio': kpi(
        'Asistencia promedio',
        'Reservas que terminan en clase',
        'De las reservas que se hicieron en el mes, qué porcentaje terminó entrenando.',
        'Asistentes del mes dividido por las reservas confirmadas del mes, en porcentaje.',
        'Es el "no-show" del box: 90 % o más es excelente; abajo de 70 % hay muchas reservas que no se '
        + 'usan, y son lugares que quedaron tomados sin que nadie los aprovechara.',
        'Si está baja, recordar la reserva (notificaciones) y revisar la política de cancelación: liberar '
        + 'el lugar a tiempo lo puede ocupar otro alumno.',
    ),
    'mensual:frecuencia_semanal': kpi(
        'Frecuencia semanal',
        'Clases por semana de cada alumno',
        'Cuántas clases por semana entrena, en promedio, cada alumno con plan vigente.',
        'Asistentes del mes dividido por los alumnos con plan vigente al inicio del mes y por las semanas '
        + 'que tuvo el mes.',
        'Quien entrena 3 veces por semana se queda; quien viene una vez, se va. En un box de CrossFit 2,5 '
        + 'o más es un box sano; menos de 1,5 avisa que los alumnos están pagando y no viniendo.',
        'Si está baja, mirar la asistencia de cada alumno en su historial y usar los avisos: el que dejó '
        + 'de venir suele ser el que se va a dar de baja.',
    ),
    'mensual:ocupacion_promedio': kpi(
        'Ocupación promedio',
        'Lugares usados sobre los ofrecidos',
        'Qué porcentaje de los lugares ofrecidos en el mes se usó.',
        'Asistentes confirmados del mes dividido por el cupo total de las clases del mes, en porcentaje.',
        'Alta = clases llenas (se puede abrir cupo o ajustar el precio). Baja = mucha oferta para la '
        + 'gente que hay. Es el número que se mira antes de tocar horarios.',
        'Si está baja, o se sube la gente o se baja la oferta: el detalle de concurrencia por bloque '
        + 'horario de Inteligencia de Negocio dice en qué franja está el problema.',
    ),
    'mensual:alumnos_activos_inicio': kpi(
        'Alumnos activos (inicio)',
        'Alumnos con plan vigente al abrir el mes',
        'Cuántos alumnos tenían un plan vigente el primer día del mes: el punto de partida del mes.',
        'Se cuentan los alumnos con plan vigente al abrir el mes (los planes valen hasta el último día, '
        + 'hora de Chile). Los planes internos de regalo no cuentan y el número es HISTÓRICO: no cambia '
        + 'con el tiempo, dice lo que había ese día.',
        'Muestra si el box crece mes a mes. Como el riesgo de abandono se calcula sobre esta base, un mes '
        + 'con pocos alumnos al inicio puede quedar sin porcentaje publicado.',
        'Si cae respecto del mes anterior, fue un mes de más bajas que altas: revisar el riesgo de '
        + 'abandono de ese mes y la conversión de las pruebas nuevas.',
    ),

    // ── Pestaña INTELIGENCIA DE NEGOCIO (BI): números en vivo ────────────────────
    'bi:mrr': kpi(
        'Ingresos Recurrentes Mensuales',
        'Plan al mes a precio de lista, HOY',
        'Cuánto factura el box al mes por los planes vigentes hoy, a precio de lista.',
        'Suma del precio de lista de los planes vigentes a HOY. No espera al cierre del mes ni depende '
        + 'del dato mensual (por eso puede diferir del MRR de la pestaña Mensual) y no cuenta los planes '
        + 'internos de regalo.',
        'Es el tamaño del negocio medido en ingreso recurrente. Conviene leerlo junto con la vida '
        + 'promedio: crecer sin retener sólo infla el número de un mes.',
        'Si baja, mirar el riesgo de abandono; si sube, revisar que la vida promedio no esté cayendo '
        + '(entra gente nueva y se va la de siempre).',
    ),
    'bi:forecast_mes1': kpi(
        'Proyección mes 1',
        'Ingreso estimado del mes que viene',
        'Cuánto se espera facturar el mes próximo, según el modelo de pronóstico.',
        'El modelo aprende de los ingresos netos (ingresos menos egresos) de los últimos meses y del '
        + 'patrón de cada mes del año, y proyecta hacia adelante. La tabla de abajo muestra los meses '
        + 'siguientes con su variación estimada.',
        'Es una estimación, no un dato: mide la tendencia. Cuanto más parejo es el box, más confiable. '
        + 'Si dos meses seguidos van para abajo, el modelo espera un mes flojo.',
        'Si la proyección baja, adelantar las acciones comerciales (campañas y beneficios) en los meses '
        + 'flojos que marca la Estacionalidad.',
    ),
    'bi:ticket_promedio': kpi(
        'Ticket promedio',
        'Gasto promedio por compra de plan',
        'Cuánto gasta, en promedio, un alumno cada vez que compra una membresía.',
        'Ingreso total de membresías dividido por la cantidad de compras registradas. Incluye sólo '
        + 'membresías: el bazar no entra en este promedio.',
        'Mide si el box vende planes completos o los más baratos. Un ticket que baja con ventas que '
        + 'suben puede ser un plan nuevo más económico: no es malo si se compensa con cantidad.',
        'Si baja, revisar las promociones y descuentos vigentes en Fidelización y si el plan que más se '
        + 'vende es el que conviene.',
    ),
    'bi:ltv_estimado': kpi(
        'LTV estimado',
        'Lo que deja un alumno en toda su vida',
        'Cuánto dinero deja, en total, un alumno promedio durante toda su vida en el box.',
        'Ingreso promedio por alumno al mes (ARPU) multiplicado por los meses que en promedio se queda '
        + 'cada alumno.',
        'Es el techo de lo que tiene sentido gastar para conseguir un alumno. Si la vida promedio está '
        + 'cayendo, el LTV baja aunque el ingreso mensual suba.',
        'Usarlo como referencia al promocionar: un descuento que cuesta menos que la vida promedio que '
        + 'ayuda a ganar se paga solo; uno que cuesta más, no.',
    ),
    'bi:vida_promedio': kpi(
        'Vida promedio del alumno',
        'Meses que se queda un alumno',
        'Cuántos meses, en promedio, se queda un alumno antes de darse de baja.',
        'Se promedian los meses que estuvieron los alumnos que YA se dieron de baja: los que siguen '
        + 'activos no entran en el promedio porque su historia sigue abierta.',
        'Retener rinde más que captar: subir esta cifra mejora el LTV sin vender un peso más. Una vida '
        + 'corta (menos de 6 meses) avisa de un problema de experiencia, precio u horarios.',
        'Si baja, mirar el historial de los alumnos que se fueron y los avisos de riesgo: la baja suele '
        + 'venir anunciada por semanas de inactividad.',
    ),
};

/** Detalle de una tarjeta: `null` si el id no está en el catálogo (no se abre nada). */
export const detalleKpi = (id) => DETALLES_KPI[id] || null;
