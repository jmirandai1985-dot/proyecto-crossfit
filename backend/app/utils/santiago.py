"""
Zona horaria de Chile (America/Santiago) — ÚNICO punto de verdad para fechas
"hoy"/"mes" de todo el módulo de Asistencia/Hitos y para la VIGENCIA DE LOS PLANES.

No usar date.today() ni datetime.now() sin zona horaria en los endpoints de
asistencia: en servidores con TZ=UTC (producción) darían el día equivocado.

── REGLA DE UN PLAN (2026-09-29) ──────────────────────────────────────────────
Un plan vale hasta las **23:59:59 del último día del mes, hora de Chile**: el
día de `fecha_expiracion` está vigente COMPLETO (el 30/09 un plan de septiembre
sigue vigente; recién desde las 00:00 del 01/10 está vencido).

Por eso acá viven las dos únicas formas de decidir/crear ese vencimiento:

  * `vigente_el_dia()` / `dias_para_vencer()` — la decisión, en Python, con el
    día de Chile (espejo de `shared.estados.sql_suscripcion_vigente()` y de
    `app.core.estados.vigente_hoy()`).
  * `fin_del_dia_chile()` / `fin_de_mes_chile()` — lo que se ESCRIBE en
    `suscripciones.fecha_expiracion` (antes se guardaba `23:59:59+00`, que en
    Chile es 20:59 y le robaba las últimas 3 horas al último día).

Un comparación por INSTANTE (`fecha_expiracion > now()`) no sirve para esto:
corta el día al mediodía de la tarde y depende de la TZ del proceso.
"""
import calendar
from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo

SANTIAGO = ZoneInfo("America/Santiago")


def ahora_santiago() -> datetime:
    """Fecha/hora actual en Chile (tz-aware)."""
    return datetime.now(SANTIAGO)


def hoy_santiago() -> date:
    """Fecha calendario actual en Chile."""
    return ahora_santiago().date()


def fecha_chile(valor: datetime) -> date | None:
    """Fecha CHILENA de un instante de la BD (las columnas son `timestamptz`).

    Única definición: la usan el panel del Historial del alumno y las plantillas de
    Fidelización (un mes o un día de vencimiento leídos con la TZ del servidor —UTC—
    caen en la fecha equivocada de noche).

    `None` entra, `None` sale: el llamador decide qué hacer con "sin dato" en vez de
    recibir una fecha inventada. Un instante sin zona se asume UTC (es lo que devuelve
    Postgres para una columna tz-aware).
    """
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(SANTIAGO).date()


# ── Vigencia de un plan: el día de vencimiento vale COMPLETO (hora de Chile) ───
def vigente_el_dia(fecha_expiracion, ahora: datetime | None = None) -> bool:
    """¿El plan sigue vigente en `ahora` (default: ahora en Chile)?

    Espejo en Python de los dos predicados SQL (`shared.estados.sql_suscripcion_vigente()`
    y `app.core.estados.vigente_hoy()`): se compara el DÍA chileno de `fecha_expiracion`
    contra el día chileno de `ahora`, así que un plan que vence el 30/09 está vigente a las
    08:00, a las 21:00 (cuando en UTC ya es el 01/10) y a las 23:30 de ese día, y recién
    está vencido desde las 00:00 (Chile) del 01/10.

    `None` entra, `False` sale: sin fecha de vencimiento NO está vigente (en SQL un NULL
    tampoco pasa el `>=`). `ahora` se puede inyectar para probar la hora exacta.
    """
    if fecha_expiracion is None:
        return False
    hoy = (ahora or ahora_santiago()).astimezone(SANTIAGO).date()
    return fecha_chile(fecha_expiracion) >= hoy


def dias_para_vencer(fecha_expiracion, ahora: datetime | None = None) -> int | None:
    """Días (de Chile) que le quedan al plan: 0 = vence HOY, `None` = sin fecha.

    Nunca negativo: el día de vencimiento cuenta como 0 (todavía sirve), y el día
    siguiente el plan ya no está vigente (`vigente_el_dia()` es False).
    """
    if fecha_expiracion is None:
        return None
    hoy = (ahora or ahora_santiago()).astimezone(SANTIAGO).date()
    return max(0, (fecha_chile(fecha_expiracion) - hoy).days)


def fin_del_dia_chile(dia: date) -> datetime:
    """El último instante de ese día en Chile: 23:59:59 tz-aware.

    Es lo que se guarda en `suscripciones.fecha_expiracion` (la regla del negocio): el
    plan vale hasta las 23:59:59 del último día, hora de Chile.
    """
    return datetime.combine(dia, time(23, 59, 59), tzinfo=SANTIAGO)


def fin_de_mes_chile(desde: date | None = None) -> datetime:
    """23:59:59 hora de Chile del ÚLTIMO día del mes de `desde` (default: hoy en Chile).

    Única definición del "fin de mes" que se escribe al activar/renovar un plan
    (solicitudes_planes, compra de emergencia, fix_fechas). Antes cada endpoint lo armaba
    con `datetime.now(timezone.utc).replace(hour=23)`: eso es 20:59 hora de Chile, así que
    el último día del plan terminaba tres horas antes de lo que dice la regla.
    """
    desde = desde or hoy_santiago()
    ultimo = calendar.monthrange(desde.year, desde.month)[1]
    return fin_del_dia_chile(date(desde.year, desde.month, ultimo))
