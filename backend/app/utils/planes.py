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

Y para la compra de emergencia, que además arrastra lo que le quedaba al alumno:

    from app.utils.planes import creditos_de_emergencia

    creditos = creditos_de_emergencia(plan, tokens_sobrantes)

Ver `backend/tests/test_creditos_de_plan.py` y `backend/tests/test_comprar_emergencia.py`.
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


def creditos_de_emergencia(plan, tokens_sobrantes=0) -> Optional[int]:
    """Créditos que quedan después de una compra de emergencia: `plan + sobrantes`.

    Es la otra mitad de la misma regla (`creditos_de_plan` + lo que el alumno NO alcanzó a usar):

      * plan **ilimitado** → `None`: no hay un número que sumar (`NULL` = "∞" en el front);
      * plan **con cupo** → sus clases **más** `tokens_sobrantes`;
      * `tokens_sobrantes` `None` o negativo → cuenta como 0. Un saldo negativo no es
        "sobrante" y no se arrastra como deuda al plan nuevo.

    Por qué existe
    --------------
    `POST /comprar-emergencia` dice "1ra vez al año: acumula tokens sobrantes al mes
    siguiente" y calculaba `tokens_sobrantes`… para después guardar
    `creditos_de_plan(plan)` a secas: lo que le quedaba al alumno se **pisaba** (se
    devolvía en la respuesta y se perdía en la base). Hoy el guard del endpoint exige
    `creditos_disponibles == 0` (con clases disponibles no hace falta la emergencia), así
    que el caso es defensivo; pero la cuenta tiene que ser la correcta si ese guard se
    relaja, si el plan tiene un cupo mayor que 0 y, sobre todo, porque es la regla
    escrita en el endpoint: no puede depender de una precondición para no destruir datos.

    Ver `backend/tests/test_comprar_emergencia.py`.
    """
    del_plan = creditos_de_plan(plan)
    if del_plan is None:
        return None
    return del_plan + max(0, tokens_sobrantes or 0)
