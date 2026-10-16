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

⚠️ Fuera de alcance (reportado, NO migrado a propósito): `churn_service` (data mart de churn y
"plan sin usar"), `fidelizacion_plantillas`, `alertas_email_service`, `kpis.py`/`kpis_populate` y
`usuarios.py` también leen `asistencias`. Cambiar esos mueve números de BI y de campañas: es una
decisión aparte, no un efecto colateral de este fix.
"""
from datetime import date
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.estados import no_cancelada
from app.models.clase import Clase
from app.models.reserva import Reserva


def ultima_asistencia_por_alumno(db: Session, tenant_id: int,
                                 alumno_ids: Iterable[int]) -> dict[int, date]:
    """Última fecha de clase a la que asistió cada alumno (`reservas.asistio = true`).

    UNA sola consulta agregada para todo el lote (sin N+1) y sólo de los ids pedidos. La usan
    las dos alertas de riesgo (coach y admin), el análisis de fidelización y los "días sin
    entrenar" del correo de contacto.

    - Un id que NO aparece en el resultado nunca asistió: el que llama lo lee como
      `.get(id) -> None`, que es el "sin historial" del panel — y NO es lo mismo que "ausente"
      (el alumno que nunca empezó no entra a la campaña de inactividad).
    - Se descarta la reserva de una clase cancelada (`no_cancelada`), por la misma razón por la
      que la filtran los contadores "ya marcaron" de `api/v1/asistencia`: una clase que no
      ocurrió no puede contarse como asistencia.
    """
    ids = [int(i) for i in (alumno_ids or []) if i is not None]
    if not ids:
        return {}

    filas = (
        db.query(Reserva.alumno_id,
                 func.max(Clase.fecha).label("ultima_fecha"))
        # La fecha es la de la CLASE, no la de la reserva: el alumno reserva días antes.
        .join(Clase, Reserva.clase_id == Clase.id)
        .filter(
            Reserva.tenant_id == tenant_id,
            Reserva.alumno_id.in_(ids),
            Reserva.asistio.is_(True),
            no_cancelada(Reserva.estado),
        )
        .group_by(Reserva.alumno_id)
        .all()
    )
    return {alumno_id: fecha for alumno_id, fecha in filas if fecha is not None}
