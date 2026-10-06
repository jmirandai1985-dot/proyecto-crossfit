"""ÚNICA definición de "días para vencer el plan vigente de un alumno" (días de Chile).

POR QUÉ EXISTE
--------------
Antes había DOS caminos que calculaban lo mismo y podían NO coincidir en la misma
pantalla de Fidelización:

  * la **situación** (columna "Motivo"): un TEXTO congelado que escribía
    `kpis_populate` al poblar `predictions_churn` (query propia: `func.max`
    por alumno, comercial);
  * la **recomendación** (columna "Recomendación"): se calculaba EN VIVO en
    `fidelizacion_plantillas` (otra query + otra resta de fechas).

El alumno #165 (Josefa) mostraba "plan vence en 7 días" arriba y "Su plan vence en
3 día(s)" abajo: la situación venía de un snapshot viejo (poblado 4 días antes) y la
recomendación era de hoy. Con UNA sola función y el nº refrescado en vivo al servir
el panel, las dos columnas dicen siempre el mismo número.

REGLAS
------
* Días CALENDARIO de Chile: `fecha_chile(fecha_expiracion) - hoy_santiago()` — el día
  de vencimiento cuenta 0 (todavía sirve) y nunca es negativo (una suscripción ya
  vencida no dice "-2 días").
* Suscripción VIGENTE = `estado = 'activo'` y `vigente_hoy(fecha_expiracion)` (el día
  de vencimiento COMPLETO, en hora de Chile); si hay varias, gana la que vence MÁS
  TARDE (la que el alumno va a renovar).
* `solo_comercial=True` excluye el "Pase de regreso" (un plan NO comercial da acceso
  sin ser un cliente): lo usa el churn/BI para no contar un pase gratis como plan
  vigente. La Fidelización (criterio 5 de sus plantillas) NO filtra por comercial.
"""
import re
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.estados import plan_comercial, vigente_hoy
from app.models.plan import Plan
from app.models.suscripcion import Suscripcion
from app.utils.santiago import fecha_chile, hoy_santiago

# Estado comercial de una membresía que HOY da acceso (el único que se considera vigente).
ESTADO_SUSCRIPCION_ACTIVO = "activo"

# El corte de "plan por vencer" que la SITUACIÓN nombra en el texto (<= N días). Es el mismo
# valor que usa la recomendación del churn; acá vive UNA vez.
DIAS_PLAN_POR_VENCER = 7

# "plan vence en 7 días" / "plan vence en 1 día": el fragmento del `motivo` (situación)
# que se refresca EN VIVO al servir el panel de Fidelización.
_RE_PLAN_EN_MOTIVO = re.compile(r"plan vence en \d+ días?")


def plural_dias(n: int) -> str:
    """`1 -> 'día'`, cualquier otro -> `'días'` (misma regla que el resto del módulo)."""
    return "día" if n == 1 else "días"


def motivo_situacion(dias_sin_asistir, dias_para_vencer) -> str:
    """El `motivo` (columna "Motivo" del panel de Fidelización) armado 100% EN VIVO.

    Texto ÚNICO para las dos ramas del BI (heurística y ML) y para el refresco al servir el
    panel: `dias_sin_asistir` (días desde la última asistencia, o desde el alta) + qué pasa con
    el plan vigente (`dias_para_vencer = None` si HOY no tiene uno usable). Es la SITUACIÓN
    actual del alumno: del snapshot del modelo sólo quedan el riesgo, la probabilidad y el
    arquetipo (números del modelo), nunca esta frase.

    Antes el `motivo` era un TEXTO congelado al poblar `predictions_churn` y sólo se refrescaba
    su fragmento "plan vence en N días": un alumno que recuperaba el plan (o dejaba de tenerlo)
    seguía mostrando la situación vieja ("sin plan vigente" con plan vigente).
    """
    dias_sin_asistir = int(dias_sin_asistir or 0)
    base = f"{dias_sin_asistir} {plural_dias(dias_sin_asistir)} sin asistir"
    if dias_para_vencer is None:
        return f"{base} · sin plan vigente"
    if dias_para_vencer <= DIAS_PLAN_POR_VENCER:
        return (f"{base} · plan vence en {dias_para_vencer} "
                f"{plural_dias(dias_para_vencer)}")
    return base


def dias_hasta(fecha_expiracion, hoy: date | None = None) -> int | None:
    """Días (de Chile) que le quedan a `fecha_expiracion` desde `hoy`. `None` entra/sale.

    Es la aritmética del módulo: la usan la situación del BI, la recomendación y el
    refresco en vivo. El día de vencimiento cuenta 0 y nunca hay negativos.
    """
    if fecha_expiracion is None:
        return None
    hoy = hoy or hoy_santiago()
    return max(0, (fecha_chile(fecha_expiracion) - hoy).days)


def suscripcion_vigente(db: Session, alumno, hoy: date | None = None,
                        solo_comercial: bool = False):
    """`(Suscripcion, Plan)` de la membresía que HOY da acceso, o `None`.

    Si hay más de una, gana la que vence MÁS TARDE. `solo_comercial=True` excluye el
    "Pase de regreso" (ver el docstring del módulo).
    """
    hoy = hoy or hoy_santiago()
    consulta = (
        db.query(Suscripcion, Plan)
        .join(Plan, Suscripcion.plan_id == Plan.id)
        .filter(
            Suscripcion.tenant_id == alumno.tenant_id,
            Suscripcion.usuario_id == alumno.id,
            Suscripcion.estado == ESTADO_SUSCRIPCION_ACTIVO,
            # El día de vencimiento cuenta COMPLETO y en hora de Chile.
            vigente_hoy(Suscripcion.fecha_expiracion, hoy=hoy),
        )
    )
    if solo_comercial:
        consulta = consulta.filter(plan_comercial(Plan.es_comercial))
    return consulta.order_by(
        Suscripcion.fecha_expiracion.desc(), Suscripcion.id.desc()).first()


def dias_para_vencer_plan(db: Session, alumno, hoy: date | None = None,
                          solo_comercial: bool = False) -> int | None:
    """Días para vencer el plan VIGENTE del alumno (o `None` si no tiene uno usable hoy).

    LA función: la llaman la situación (`kpis_populate`) y la recomendación
    (`fidelizacion_plantillas`). Una sola definición => un solo número.
    """
    fila = suscripcion_vigente(db, alumno, hoy, solo_comercial)
    if fila is None:
        return None
    suscripcion, _plan = fila
    return dias_hasta(suscripcion.fecha_expiracion, hoy)


def dias_para_vencer_lote(db: Session, tenant_id: int, ids: list,
                          hoy: date | None = None,
                          solo_comercial: bool = True) -> dict:
    """`{usuario_id: días_para_vencer}` para TODA una lista, en UNA query (sin N+1).

    Mismo criterio que `dias_para_vencer_plan` (vigente, vence más tarde, comercial
    opcional). Lo usa `GET /kpis/churn` para refrescar la situación en vivo.
    """
    if not ids:
        return {}
    hoy = hoy or hoy_santiago()
    consulta = (
        db.query(Suscripcion.usuario_id, func.max(Suscripcion.fecha_expiracion))
        .join(Plan, Suscripcion.plan_id == Plan.id)
        .filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id.in_(ids),
            Suscripcion.estado == ESTADO_SUSCRIPCION_ACTIVO,
            vigente_hoy(Suscripcion.fecha_expiracion, hoy=hoy),
        )
    )
    if solo_comercial:
        consulta = consulta.filter(plan_comercial(Plan.es_comercial))
    filas = consulta.group_by(Suscripcion.usuario_id).all()
    return {uid: dias_hasta(vence, hoy) for uid, vence in filas}


def refrescar_dias_plan(motivo: str | None, dias: int | None) -> str | None:
    """Reemplaza "plan vence en N {día|días}" del `motivo` por el nº VIGENTE (`dias`).

    El `motivo` (situación) es un TEXTO guardado al poblar el BI: su nº de días queda
    congelado y se desincroniza del que muestra la recomendación (en vivo). Al servir
    el panel se recalcula con `dias_para_vencer_lote` y se refresca ESTE fragmento, así
    la situación y la recomendación dicen siempre lo mismo. Sin fragmento (o sin plan
    vigente) el texto queda igual.
    """
    if not motivo or dias is None:
        return motivo
    return _RE_PLAN_EN_MOTIVO.sub(f"plan vence en {dias} {plural_dias(dias)}", motivo)
