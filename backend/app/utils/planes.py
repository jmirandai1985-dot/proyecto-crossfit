"""
Créditos de una suscripción a partir de su plan: **UNA sola regla** para todos los flujos.

La regla
--------
  * Plan **ilimitado** (`es_ilimitado = True`) → `None`. Un plan sin cupo no tiene un "número de
    clases" que guardar: `NULL` es lo que el front pinta como "∞" (`pages/admin/Alumnos.jsx`,
    `components/AlumnoFichaCoach.jsx`, `pages/alumno/Dashboard.jsx`) y lo que el resto del backend
    trata como "no descontar" (`api/v1/reservas.py`, `services/beneficios_service.py`).
  * Plan **con cupo** → sus clases TAL CUAL (`plan.creditos`), incluso 0.

En PROD los ilimitados (King Kong, Donkey Kong, Diosa Griega, Influencer) están cargados con
`creditos = 0`, así que un `or 999` —el centinela viejo que vivía copiado en la aprobación de
solicitudes y en la compra de emergencia— guardaba `999` y el panel del box mostraba "999 créditos"
en un plan ilimitado (bug de producción del 2026-10-08, alumno 533). El alta manual del admin
(`pages/admin/Alumnos.jsx` → `POST /suscripciones`) ya mandaba `null` para esos planes: acá queda
escrito una sola vez para que los tres caminos coincidan.

Uso:
    from app.utils.planes import creditos_de_plan

    Suscripcion(**..., creditos_totales=creditos_de_plan(plan),
                     creditos_disponibles=creditos_de_plan(plan))

Ver `backend/tests/test_creditos_de_plan.py`.
"""
from typing import Optional


def creditos_de_plan(plan) -> Optional[int]:
    """Clases que le corresponden a una suscripción de `plan` (`None` = ilimitado).

    Acepta cualquier objeto con `es_ilimitado`/`creditos` (o `None`, si el plan no existe): sin
    plan no hay cupo que prometer, así que devuelve `None` en vez de inventar un número. Si el
    objeto no trae la marca `es_ilimitado`, se respeta su `creditos` tal cual (ante la duda, el
    número del plan; nunca un centinela inventado).
    """
    if plan is None or getattr(plan, "es_ilimitado", False):
        return None
    return plan.creditos
