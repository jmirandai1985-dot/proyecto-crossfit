"""La asistencia REAL del panel: `reservas.asistio` sobre la fecha de la CLASE.

POR QUÉ EXISTE (auditoría 2026-10-15 — el bug "En riesgo = 251")
----------------------------------------------------------------
`asistencias` es una tabla histórica que el sistema actual NO puebla: el único `INSERT` de la
app es `POST /fidelizacion/asistencia`, y NINGUNA pantalla lo llama (el coach y el alumno marcan
por `POST /asistencia/clases/{id}/confirmar`, que escribe `reservas.asistio`); los seeds/demo son
lo único que la llena. Leerla para responder "¿hace cuánto no entrena este alumno?" devuelve
SIEMPRE "Nunca asistió", así que la alerta de riesgo marcaba a TODO el padrón: el coach veía
"251 En riesgo" sobre 251 alumnos.

La fuente real —la que usa el resto del panel— es `reservas.asistio = true` sobre `clases.fecha`:
el MISMO patrón de `api/v1/admin._alumnos_con_asistencia_de_prueba`,
`services/historial_alumno_service._inicio_actividad` y los contadores "ya marcaron" de
`api/v1/asistencia`. Este módulo es el ÚNICO lugar donde se lee "asistió" para el cálculo de
riesgo/inactividad, para que no vuelvan a existir dos definiciones.

QUÉ VIVE ACÁ (una sola definición de "asistió", y nada más)
----------------------------------------------------------
  * `condicion_asistio()` — el predicado ORM (`asistio = true` + la reserva no cancelada). Es lo
    que comparten TODOS los lectores de abajo.
  * `ultima_asistencia_por_alumno()` — "¿cuándo entrenó por última vez?" (`hasta=` acota la
    ventana: lo necesitan los features as-of del ML, que no pueden ver el futuro).
  * `asistencias_entre_por_alumno()` — "¿cuántas clases hizo en la ventana?" (churn 30/90 y ML).
  * `sql_cte_asistencias()` — el espejo en SQL CRUDO de la misma definición, para los endpoints
    de BI que no pasan por el ORM (`kpis.py`: bloques horarios y cohortes).

MIGRADOS (2ª tanda, decisión del usuario 2026-10-15: "la base actual es de prueba y el envío de
correos no tiene alumnos reales; es el mejor momento para corregirlo")
---------------------------------------------------------------------------------------------
`churn_service` (churn del data mart + "plan sin usar"), `fidelizacion_plantillas`,
`alertas_email_service` (el correo de inactividad), `kpis_populate`, `kpis` (incluidos
`/bloques-horarios` y `/cohortes`, que daban 0 para SIEMPRE porque el join salía de la tabla
vacía), `usuarios` (la última asistencia del buscador del Admin) y `ml/features` + `ml/entrenar`
(los features y el label del churn: sin esto el modelo se entrenaría y puntuaría contra una tabla
vacía, y el data mart volvería a decir "todos sin historial"). Los números de BI, del churn y de
las campañas de correo CAMBIAN: es el objetivo del cambio, no un efecto colateral.

⚠️ Escritores que quedan de la tabla histórica: `POST /fidelizacion/registrar` (ninguna pantalla
lo llama; no se toca el flujo de guardado) y el seed de la demo de alertas. Ninguno de los dos
alimenta ya ningún cálculo.
"""
from datetime import date
from typing import Iterable

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.estados import no_cancelada
from app.models.clase import Clase
from app.models.reserva import Reserva
from shared.estados import lista_sql


def condicion_asistio(reserva):
    """El predicado ORM de "asistió": `reservas.asistio = true` + la reserva NO cancelada.

    Es la ÚNICA definición en el ORM y la usan todos los lectores de este módulo (última
    asistencia, conteo por ventana) más el BI que pregunta "¿vinieron a esta clase?". Una clase
    que no ocurrió no puede contar como asistencia: mismo criterio que los contadores "ya
    marcaron" de `api/v1/asistencia`.
    """
    return and_(reserva.asistio.is_(True), no_cancelada(reserva.estado))


def ultima_asistencia_por_alumno(db: Session, tenant_id: int,
                                 alumno_ids: Iterable[int],
                                 hasta: date | None = None) -> dict[int, date]:
    """Última fecha de clase a la que asistió cada alumno (`reservas.asistio = true`).

    UNA sola consulta agregada para todo el lote (sin N+1) y sólo de los ids pedidos. La usan las
    alertas de riesgo (coach y admin), el análisis de fidelización, los "días sin entrenar" del
    correo de contacto, el churn y "plan sin usar", las plantillas de Fidelización, el buscador
    del Admin y los features del ML.

    - Un id que NO aparece en el resultado nunca asistió: el que llama lo lee como
      `.get(id) -> None`, que es el "sin historial" del panel — y NO es lo mismo que "ausente"
      (el alumno que nunca empezó no entra a la campaña de inactividad).
    - `hasta` acota la ventana (`clases.fecha <= hasta`): lo pide el ML, que calcula features
      "as-of" sobre una fecha de corte y no puede ver asistencias POSTERIORES (fuga del futuro).
    - Las condiciones de "asistió" salen de `condicion_asistio()`, que se define UNA sola vez.
    """
    ids = [int(i) for i in (alumno_ids or []) if i is not None]
    if not ids:
        return {}

    consulta = (
        db.query(Reserva.alumno_id,
                 func.max(Clase.fecha).label("ultima_fecha"))
        # La fecha es la de la CLASE, no la de la reserva: el alumno reserva días antes.
        .join(Clase, Reserva.clase_id == Clase.id)
        .filter(
            Reserva.tenant_id == tenant_id,
            Reserva.alumno_id.in_(ids),
            condicion_asistio(Reserva),
        )
    )
    if hasta is not None:
        consulta = consulta.filter(Clase.fecha <= hasta)
    filas = consulta.group_by(Reserva.alumno_id).all()
    return {alumno_id: fecha for alumno_id, fecha in filas if fecha is not None}


def asistencias_entre_por_alumno(db: Session, tenant_id: int, alumno_ids: Iterable[int],
                                 desde: date, hasta: date) -> dict[int, int]:
    """{alumno_id: nº de clases a las que asistió} en `[desde, hasta]` (fechas de la CLASE).

    UNA sola consulta agregada para todo el lote (sin N+1) y sólo de los ids pedidos. Es el mismo
    conteo que la tabla histórica hacía con `count(asistencias.id)`, pero sobre la asistencia
    REAL: lo usan las ventanas del churn ("asistencias últimos 30/90 días"), el embudo de la
    clase de prueba, los "días sin asistir" del insight del BI y los features del ML.

    - `desde`/`hasta` son días INCLUSIVOS, en fechas de Chile (las mismas de `clases.fecha`).
    - Un alumno sin asistencias en la ventana NO aparece en el resultado: el que llama lo lee como
      0 (`.get(id, 0)`), igual que hacía el `count` de la tabla histórica.
    """
    ids = [int(i) for i in (alumno_ids or []) if i is not None]
    if not ids or desde is None or hasta is None:
        return {}

    filas = (
        db.query(Reserva.alumno_id, func.count(Reserva.id))
        .join(Clase, Reserva.clase_id == Clase.id)
        .filter(
            Reserva.tenant_id == tenant_id,
            Reserva.alumno_id.in_(ids),
            condicion_asistio(Reserva),
            Clase.fecha >= desde,
            Clase.fecha <= hasta,
        )
        .group_by(Reserva.alumno_id)
        .all()
    )
    return {alumno_id: int(n or 0) for alumno_id, n in filas}


def sql_cte_asistencias() -> str:
    """La MISMA definición de "asistió", en SQL crudo, para el BI que no pasa por el ORM.

    Se pega como CTE al principio de la consulta y el resto queda igual:

        sql_text(f"WITH {sql_cte_asistencias()} SELECT ... FROM asistencias a ...")

    Expone las columnas que esas consultas ya usaban (`id`, `usuario_id`, `clase_id`, `tenant_id`,
    `fecha`), así que lo único que cambia es de dónde salen las filas: de la tabla histórica que
    nadie puebla pasan a `reservas.asistio` sobre la fecha de la clase. `lista_sql()` se lee en
    CADA llamada (no se captura al importar), así que un estado de cancelación nuevo llega acá sin
    tocar nada.
    """
    return (
        "asistencias AS ("
        "SELECT r.id AS id, r.alumno_id AS usuario_id, r.clase_id AS clase_id,"
        " r.tenant_id AS tenant_id, c.fecha AS fecha"
        " FROM reservas r JOIN clases c ON c.id = r.clase_id"
        f" WHERE r.asistio = true AND r.estado NOT IN ({lista_sql()}))"
    )
