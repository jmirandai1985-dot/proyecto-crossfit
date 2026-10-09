"""Plantillas de correo de Fidelización — el catálogo completo en UNA definición.

Qué es
------
El panel de Fidelización detecta a quién hay que ir a buscar (churn del ML, planes por
vencer) y "Acción Rápida" mandaba un correo **a ciegas**: el admin elegía un texto genérico y
no veía nunca el mensaje. Ahora el envío es: **elegir plantilla → ver el correo EXACTO →
enviar**. Este módulo es la definición única de:

  * qué se puede mandar (catálogo **por situación**, con su grupo y su `tipo_envio`);
  * con qué datos REALES se arma (días sin entrenar, membresía vigente y su vencimiento, y el
    riesgo del modelo cuando la situación es esa);
  * **qué plantilla le corresponde a cada alumno** (`sugerir()`): la pantalla no adivina;
  * cómo se renderiza (reusando los renders de `email_service`: el copy vive en UN lugar);
  * cómo se envía (la puerta única de `email_service`, que registra el envío en
    `notificaciones_enviadas`).

El router (`app/api/v1/fidelizacion_plantillas.py`) NO arma textos ni consulta datos: elige,
valida el ACL/tenant y devuelve el dict.

Reglas (una definición por criterio)
------------------------------------
 1. `preview` y `enviar` renderizan con LA MISMA función: lo que el admin ve es lo que se
    manda. Si divergieran, el preview sería una mentira.
 2. Los datos del correo salen de la BD, nunca del frontend.
 3. `tipo_envio` es el tipo que se registra en `notificaciones_enviadas` (`inactividad`,
    `vencimiento`, …): los mismos valores que ya usa el resto del sistema.
 4. "Días sin entrenar" = días desde la última asistencia y, si nunca asistió, desde su alta,
    con piso en 1 (`DIAS_MINIMOS`): un correo de recuperación que diga "0 días" es absurdo.
    Se cuentan en fecha de CHILE (`hoy_santiago()`).
 5. "Membresía vigente" = `estado = 'activo'` y `fecha_expiracion >= hoy` — el MISMO criterio
    que `GET /fidelizacion/tenant/{id}/vencimientos`, que es la lista desde la que se manda
    este correo. NO se usa `sql_suscripcion_vigente()` porque esa definición también acepta
    `vencido` (sirve para mirar el pasado): para ofrecer una renovación hace falta un plan
    usable HOY.
 6. El grupo `beneficios` existe como RESERVADO y NO se anuncia (Fase 2 de Fidelización,
    mismo criterio que las pestañas del Historial del alumno: lo que no está listo no se
    muestra). El catálogo público se filtra por `GRUPOS_RESERVADOS`.
 7. Un envío NUNCA es automático acá: lo dispara una persona. La automatización no es parte
    de este diseño (ver `docs/DISENO_FIDELIZACION.md`).
 8. **El catálogo es por SITUACIÓN, con rangos declarados.** Cada tramo de inactividad dice a
    qué días corresponde y RECHAZA lo que no le toca (`PlantillaSinDatos`, con el id de la
    que sí corresponde en el mensaje): tres plantillas que rinden el mismo correo con distinta
    etiqueta son una lista que le miente al admin, y mandar el mensaje de "7 a 14 días" a
    alguien que lleva 90 días es peor que no mandar nada.
 9. **Los números del modelo son del ADMIN.** La plantilla `riesgo_alto` usa la predicción
    para elegir el mensaje y la devuelve en el `contexto` (la ve el admin en el preview), pero
    el correo del alumno NO menciona probabilidades ni el motivo técnico: al alumno se le
    escribe como una persona del box que se preocupa.
10. `sugerir()` es la ÚNICA definición de "qué correo le corresponde a este alumno", y dice
    cuál regla ganó (`regla` + `motivo`). Si no corresponde ninguno, devuelve vacío: no se
    inventa un correo para el alumno que entrenó ayer.
"""
from datetime import date
from typing import Final

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.estados import vigente_hoy   # "el plan da acceso HOY" (día chileno, inclusivo)
from app.models.asistencia import Asistencia
from app.models.plan import Plan
from app.models.predictions_churn import PredictionsChurn
from app.models.suscripcion import Suscripcion
from app.services import beneficios_service
# "Plan sin usar" (plan vigente y sin estrenar): la MISMA definición que la recomendación del
# churn (`churn_service.es_plan_sin_usar`), para que la sugerencia y el panel no diverjan.
from app.services import churn_service
from app.services import email_service
# ÚNICA definición de "días para vencer el plan vigente": la comparte con la situación del BI
# (kpis_populate) para que la columna "Recomendación" y el "Motivo" nunca digan nº distintos.
from app.services.plan_vencimiento import dias_hasta, suscripcion_vigente
from app.utils.santiago import fecha_chile, hoy_santiago

# ── Grupos del catálogo ───────────────────────────────────────────────────────
GRUPO_GESTION: Final[str] = "gestion"
GRUPO_BENEFICIOS: Final[str] = "beneficios"
GRUPOS: Final[tuple] = (
    (GRUPO_GESTION, "Correos de gestión"),
    (GRUPO_BENEFICIOS, "Beneficios"),
)
# Grupos que aún NO se ofrecen en el modal (llegan con la Fase 2).
GRUPOS_RESERVADOS: Final[tuple] = (GRUPO_BENEFICIOS,)

# ── Ids de plantilla (uno por SITUACIÓN, no uno genérico) ─────────────────────
P_INACTIVIDAD_7_14: Final[str] = "inactividad_7_14"
P_INACTIVIDAD_15_30: Final[str] = "inactividad_15_30"
P_INACTIVIDAD_MAS_30: Final[str] = "inactividad_mas_30"
P_RIESGO_ALTO: Final[str] = "riesgo_alto"
P_VENCIMIENTO: Final[str] = "vencimiento"
# Plan vigente COMPRADO y todavía sin estrenar (el alumno activó el plan y no vino nunca).
P_PLAN_SIN_USAR: Final[str] = "plan_sin_usar"
# Los dos correos de la Fase 2 (grupo `beneficios`): no nacen de una situación del alumno
# sino de un REGALO concreto, así que su id ES el tipo del beneficio que anuncian
# (`beneficios_service.TIPOS`): el log de correos queda agrupado por tipo de regalo, que es
# justo lo que mide la F4 (tasa de uso por beneficio).
P_BENEFICIO_DESCUENTO: Final[str] = "beneficio_descuento"
P_BENEFICIO_CLASES_GRATIS: Final[str] = "beneficio_clases_gratis"
# Plantillas cuyo contexto NO alcanza con el alumno: necesitan los datos del regalo, que
# viajan en el pedido (`datos`). Es una lista DECLARADA (y no un `if` escondido en el
# render) para que se vea de un vistazo qué plantillas no se pueden renderizar sin datos.
PLANTILLAS_CON_DATOS: Final[tuple] = (P_BENEFICIO_DESCUENTO, P_BENEFICIO_CLASES_GRATIS)

# ── Umbrales de cada situación (cada número vive en UN lugar) ─────────────────
# Piso de "días sin entrenar": un correo de recuperación no puede decir "0 días".
DIAS_MINIMOS: Final[int] = 1
# Tramos de inactividad del catálogo.
DIAS_TEMPRANA_MIN: Final[int] = 7        # desde acá ya es "hace unos días que no vienes"
DIAS_TEMPRANA_MAX: Final[int] = 14       # hasta acá todavía se recupera el hábito solo
DIAS_INACTIVIDAD_LARGA: Final[int] = 30  # más de un mes: se ofrece coordinar la vuelta
# "Plan por vencer": el MISMO corte que usa el panel para la tarjeta de próximos a vencer.
DIAS_RENOVACION_SUGERIDA: Final[int] = 5

# Riesgo del modelo que justifica el mensaje de acompañamiento (mismos niveles que el filtro
# "En riesgo" del panel de Fidelización: ALTO + CRITICO).
NIVELES_RIESGO_ALTO: Final[tuple] = ("ALTO", "CRITICO")

# Tipos que se registran en `notificaciones_enviadas` (la columna es texto libre, VARCHAR(50)).
TIPO_INACTIVIDAD: Final[str] = "inactividad"
TIPO_RIESGO_ALTO: Final[str] = "riesgo_alto"
TIPO_VENCIMIENTO: Final[str] = "vencimiento"
TIPO_PLAN_SIN_USAR: Final[str] = "plan_sin_usar"

# Regla que devuelve `sugerir()` cuando HOY no hay nada que reclamarle al alumno.
REGLA_SIN_SITUACION: Final[str] = "sin_situacion"

# Criterio 5: el estado de una membresía que HOY da acceso.
ESTADO_SUSCRIPCION_ACTIVO: Final[str] = "activo"


class PlantillaDesconocida(ValueError):
    """El id no está en el catálogo (el router lo traduce a 422)."""


class PlantillaSinDatos(ValueError):
    """La plantilla existe, pero a ESTE alumno no se le puede mandar (el router: 400)."""



# ── Datos reales que alimentan cada plantilla ─────────────────────────────────
def _referencia_actividad(db: Session, alumno) -> date | None:
    """Desde cuándo se cuentan los días sin entrenar (ÚNICA definición).

    La última asistencia; si el alumno NUNCA asistió, el INICIO de su plan vigente (compró un plan
    y todavía no lo estrenó); y sin plan vigente, su alta. Es la MISMA referencia que usa
    `_sugerir_con`: la sugerencia y los tramos no pueden contar días distintos.
    """
    ultima = db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == alumno.tenant_id,
        Asistencia.usuario_id == alumno.id,
    ).scalar()
    if ultima is not None:
        return ultima
    fila = suscripcion_vigente(db, alumno)
    if fila is not None:
        return fecha_chile(fila[0].fecha_inicio)
    return fecha_chile(getattr(alumno, "created_at", None))


def _contexto_inactividad(db: Session, alumno) -> dict:
    """Días sin entrenar (mínimo 1) y la fecha desde la que se cuentan."""
    referencia = _referencia_actividad(db, alumno)
    dias = (DIAS_MINIMOS if referencia is None
            else max(DIAS_MINIMOS, (hoy_santiago() - referencia).days))
    return {"dias_inactividad": dias, "ultima_asistencia": referencia}


def dias_inactividad(db: Session, alumno) -> int:
    """Días sin entrenar (UNA definición: sale del contexto de la plantilla)."""
    return _contexto_inactividad(db, alumno)["dias_inactividad"]


# `suscripcion_vigente` se importa de `app.services.plan_vencimiento` (arriba) y NO se
# redefine acá: la membresía "vigente" es UNA sola definición (criterio 5 del módulo).


def _contexto_vencimiento(db: Session, alumno) -> dict:
    """Plan y vencimiento REALES de la membresía vigente (o error claro si no hay)."""
    fila = suscripcion_vigente(db, alumno)
    if fila is None:
        raise PlantillaSinDatos(
            "Este alumno no tiene una membresía vigente: el aviso de renovación es para un "
            "plan que sigue activo.")
    suscripcion, plan = fila
    vence = fecha_chile(suscripcion.fecha_expiracion)
    return {
        "plan": plan.nombre,
        "fecha_expiracion": vence,
        "dias_restantes": dias_hasta(suscripcion.fecha_expiracion),
        "suscripcion_id": suscripcion.id,
    }


def _contexto_plan_sin_usar(db: Session, alumno) -> dict:
    """Plan vigente que el alumno COMPRÓ y todavía no estrenó (o error claro si no).

    Criterio 5 (sin filtrar por comercial) + ninguna asistencia DESDE que arrancó el plan + el
    margen mínimo ya cumplido: la MISMA definición que la categoría `plan_sin_usar` de la
    recomendación del churn (`churn_service.es_plan_sin_usar`). Si el alumno ya estrenó el plan
    (o lo activó hace muy poco), el envío se rechaza y el error dice por qué.
    """
    fila = churn_service.plan_sin_usar(db, alumno, solo_comercial=False)
    if fila is None:
        if not tiene_membresia_vigente(db, alumno):
            raise PlantillaSinDatos(
                "Este alumno no tiene una membresía vigente: el aviso de \"plan sin usar\" es "
                "para un plan que sigue activo y todavía no se estrenó.")
        raise PlantillaSinDatos(
            "Este alumno ya estrenó su plan (o lo activó hace muy poco): el aviso de \"plan "
            "sin usar\" es para un plan vigente que nunca se usó.")
    suscripcion, plan = fila
    inicio = fecha_chile(suscripcion.fecha_inicio)
    return {
        "plan": plan.nombre,
        "fecha_inicio": inicio,
        "dias_desde_inicio": (hoy_santiago() - inicio).days if inicio else 0,
        "dias_restantes": dias_hasta(suscripcion.fecha_expiracion),
        "suscripcion_id": suscripcion.id,
    }


def tiene_membresia_vigente(db: Session, alumno) -> bool:
    """¿Hoy tiene un plan que le da acceso? (misma definición que el criterio 5)."""
    return suscripcion_vigente(db, alumno) is not None


def prediccion_riesgo(db: Session, alumno):
    """La fila del ML que lo marca con riesgo ALTO/CRÍTICO, o `None`.

    Los niveles son los mismos que el filtro "En riesgo" del panel: pedir el correo de
    acompañamiento para un riesgo BAJO sería mandar un mensaje que los datos no respaldan.
    Si el data mart tiene más de una fila, gana la más reciente.
    """
    return (
        db.query(PredictionsChurn)
        .filter(PredictionsChurn.tenant_id == alumno.tenant_id,
                PredictionsChurn.usuario_id == alumno.id,
                PredictionsChurn.riesgo_nivel.in_(NIVELES_RIESGO_ALTO))
        .order_by(PredictionsChurn.created_at.desc(), PredictionsChurn.id.desc())
        .first()
    )


def _tramo_que_corresponde(db: Session, alumno) -> str | None:
    """El id de la plantilla de inactividad que le toca a sus días reales (o `None`).

    Es la sugerencia aplicada a los tramos de inactividad: sirve para que el error de un tramo
    mal elegido diga cuál SÍ corresponde, en vez de dejar al admin adivinando.
    """
    dias = dias_inactividad(db, alumno)
    if dias > DIAS_INACTIVIDAD_LARGA:
        return P_INACTIVIDAD_MAS_30
    if dias > DIAS_TEMPRANA_MAX:
        return P_INACTIVIDAD_15_30
    if dias >= DIAS_TEMPRANA_MIN:
        return P_INACTIVIDAD_7_14
    return None


def _contexto_tramo(db: Session, alumno, minimo: int, maximo: int) -> dict:
    """Contexto del tramo de inactividad que SÍ le corresponde a este alumno (regla 8).

    Rechaza el tramo cuando los días reales no caen en su rango: mandar el mensaje de "hace unos
    días" a alguien que no viene desde hace tres meses no es un mensaje, es un error del admin.
    El error dice qué plantilla SÍ corresponde.
    """
    datos = _contexto_inactividad(db, alumno)
    dias = datos["dias_inactividad"]
    if not minimo <= dias <= maximo:
        otra = _tramo_que_corresponde(db, alumno)
        raise PlantillaSinDatos(
            f"Esta plantilla es para {minimo} a {maximo} días sin entrenar y este alumno lleva "
            f"{dias}." + (f" Le corresponde `{otra}`." if otra else " Hoy no le corresponde "
                          "ninguna: entrenó hace muy pocos días."))
    return datos


def _contexto_inactividad_7_14(db: Session, alumno) -> dict:
    """Alumno que recién se está desenganchando (7 a 14 días)."""
    return _contexto_tramo(db, alumno, DIAS_TEMPRANA_MIN, DIAS_TEMPRANA_MAX)


def _contexto_inactividad_15_30(db: Session, alumno) -> dict:
    """Alumno que ya lleva la mitad de un mes sin venir (15 a 30 días)."""
    return _contexto_tramo(db, alumno, DIAS_TEMPRANA_MAX + 1, DIAS_INACTIVIDAD_LARGA)


def _contexto_inactividad_mas_30(db: Session, alumno) -> dict:
    """El mensaje de fondo: el alumno YA NO tiene un plan vigente (su membresía venció).

    Con un plan vigente este correo NUNCA aplica: su copy habla de "no tienes un plan vigente" y de
    coordinar la vuelta con el coach. Los días sin entrenar los cubren los tramos 7-14/15-30 y, por
    encima de 30, el modelo de riesgo; acá sólo se admite "sin plan". El correo cambia la frase del
    plan según `plan_vencido` (que ahora es siempre verdadero).
    """
    datos = _contexto_inactividad(db, alumno)
    datos["plan_vencido"] = not tiene_membresia_vigente(db, alumno)
    if not datos["plan_vencido"]:
        otra = _tramo_que_corresponde(db, alumno)
        raise PlantillaSinDatos(
            "Esta plantilla es para un alumno SIN plan vigente (su membresía ya venció), y este "
            f"alumno todavía tiene un plan activo y lleva {datos['dias_inactividad']} días sin "
            "entrenar." + (f" Le corresponde `{otra}`." if otra else ""))
    return datos


def _contexto_riesgo_alto(db: Session, alumno) -> dict:
    """Datos del alumno + la predicción REAL que justifica el mensaje (regla 9).

    El `contexto` lo ve el ADMIN en el preview: el correo que recibe el alumno no menciona ni la
    probabilidad ni el motivo del modelo.
    """
    prediccion = prediccion_riesgo(db, alumno)
    if prediccion is None:
        raise PlantillaSinDatos(
            "El modelo no marca a este alumno con riesgo alto (o todavía no tiene predicción): "
            "el mensaje de acompañamiento necesita un riesgo alto real.")
    datos = dict(_contexto_inactividad(db, alumno))
    datos.update({
        "riesgo_nivel": prediccion.riesgo_nivel,
        "probabilidad_churn": float(prediccion.probabilidad_churn),
        "motivo_ml": prediccion.motivo,
        "recomendacion_ml": prediccion.recomendacion,
        # Cuándo se calculó el MODELO: el admin ve el riesgo CON su fecha (no se confunde con
        # la situación, que es de hoy).
        "riesgo_calculado_en": (prediccion.created_at.isoformat()
                                if prediccion.created_at else None),
    })
    return datos


# ── Renders (reusan el copy de `email_service`: no hay una segunda versión) ────
def _render_inactividad_temprana(alumno, contexto) -> tuple:
    return email_service.render_email_fidelizacion_temprana(
        alumno.nombre, contexto["dias_inactividad"])


def _render_inactividad(alumno, contexto) -> tuple:
    return email_service.render_email_fidelizacion(alumno.nombre, contexto["dias_inactividad"])


def _render_inactividad_mas_30(alumno, contexto) -> tuple:
    return email_service.render_email_fidelizacion_larga(
        alumno.nombre, contexto["dias_inactividad"], contexto["plan_vencido"])


def _render_riesgo_alto(alumno, contexto) -> tuple:
    return email_service.render_email_riesgo_alto(alumno.nombre, contexto["dias_inactividad"])


def _render_vencimiento(alumno, contexto) -> tuple:
    return email_service.render_email_vencimiento_plan(
        alumno.nombre, contexto["plan"], contexto["fecha_expiracion"])


def _render_plan_sin_usar(alumno, contexto) -> tuple:
    return email_service.render_email_plan_sin_usar(
        alumno.nombre, contexto["plan"], contexto["dias_desde_inicio"])


# ── Los correos del grupo `beneficios` (Fase 2) ───────────────────────────────
def _contexto_beneficio(db: Session, alumno, datos) -> dict:
    """Datos del REGALO que anuncia el correo (no del alumno): tipo, valor y vigencia.

    El beneficio se crea ANTES de mandar el correo (es el alta la que materializa el acceso
    y fija la ventana), así que lo que viaja acá son los números de la fila recién creada y
    no una promesa del frontend. `plan` es el plan al que se sumaron las clases (`None` si
    se le abrió un pase).
    """
    if not datos:
        raise PlantillaSinDatos(
            "El correo de un beneficio necesita el beneficio: sin tipo, valor y vigencia "
            "no hay nada que anunciar.")
    tipo = datos.get("tipo")
    if not beneficios_service.tipo_valido(tipo):
        raise PlantillaSinDatos(f"Tipo de beneficio desconocido: `{tipo}`.")
    valor = datos.get("valor")
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise PlantillaSinDatos(
            "El valor del beneficio no sirve para armar el correo: un regalo dice un número.")
    return {"tipo": str(tipo), "valor": valor,
            "vigente_hasta": datos.get("vigente_hasta"), "plan": datos.get("plan")}


def _render_beneficio(alumno, contexto, tipo_esperado: str) -> tuple:
    """El correo del regalo, sólo si el tipo del catálogo es el del beneficio de verdad.

    Los dos ids existen para que el LOG (y la F4) distingan un descuento de unas clases: si
    el tipo del pedido no es el de la plantilla, el correo anunciaría un regalo que no es, y
    eso el alumno lo nota.
    """
    if contexto["tipo"] != tipo_esperado:
        raise PlantillaSinDatos(
            f"Esta plantilla es para un beneficio `{tipo_esperado}` y este es "
            f"`{contexto['tipo']}`: cada regalo tiene su correo.")
    return email_service.render_email_beneficio(
        alumno.nombre, contexto["tipo"], contexto["valor"], contexto["vigente_hasta"],
        contexto["plan"])


def _render_beneficio_descuento(alumno, contexto) -> tuple:
    return _render_beneficio(alumno, contexto, beneficios_service.TIPO_DESCUENTO)


def _render_beneficio_clases(alumno, contexto) -> tuple:
    return _render_beneficio(alumno, contexto, beneficios_service.TIPO_CLASES_GRATIS)


# ── El catálogo ──────────────────────────────────────────────────────────────
# Cada entrada es autosuficiente: sus datos (`_contexto`) y su render (`_render`) viven en
# la MISMA fila, así que agregar una plantilla no puede desincronizar un segundo diccionario.
# Las claves que empiezan con `_` son internas: `plantillas_disponibles()` no las publica.
# El orden es el de la SITUACIÓN (del aviso más cercano al más lejano): es el orden en el que el
# modal las muestra y el que usa `sugerir()` para desempatar.
PLANTILLAS: Final[tuple] = (
    {
        "id": P_VENCIMIENTO,
        "label": "Renovación (plan por vencer)",
        "descripcion": "El aviso de vencimiento con el plan y la fecha reales.",
        "grupo": GRUPO_GESTION,
        "tipo_envio": TIPO_VENCIMIENTO,
        "requiere": "Una membresía vigente (si no tiene, el envío se rechaza).",
        "_contexto": _contexto_vencimiento,
        "_render": _render_vencimiento,
    },
    {
        "id": P_PLAN_SIN_USAR,
        "label": "Plan sin usar (activó el plan y no vino)",
        "descripcion": "El empujón para el que compró un plan y todavía no estrenó ninguna "
                       "clase: lo ayuda a agendar su primera sesión.",
        "grupo": GRUPO_GESTION,
        "tipo_envio": TIPO_PLAN_SIN_USAR,
        "requiere": "Un plan vigente sin ninguna asistencia desde que arrancó (y ya pasó el "
                    "margen mínimo).",
        "_contexto": _contexto_plan_sin_usar,
        "_render": _render_plan_sin_usar,
    },
    {
        "id": P_INACTIVIDAD_7_14,
        "label": "Recuperación temprana (7 a 14 días sin entrenar)",
        "descripcion": "El recordatorio del que se está desenganchando: sus días reales y volver "
                       "a su horario de siempre.",
        "grupo": GRUPO_GESTION,
        "tipo_envio": TIPO_INACTIVIDAD,
        "requiere": "Llevar de 7 a 14 días sin entrenar.",
        "_contexto": _contexto_inactividad_7_14,
        "_render": _render_inactividad_temprana,
    },
    {
        "id": P_INACTIVIDAD_15_30,
        "label": "Recuperación (15 a 30 días sin entrenar)",
        "descripcion": "El mensaje del que ya lleva medio mes afuera: el impulso se entrena y su "
                       "lugar sigue en el box.",
        "grupo": GRUPO_GESTION,
        "tipo_envio": TIPO_INACTIVIDAD,
        "requiere": "Llevar de 15 a 30 días sin entrenar.",
        "_contexto": _contexto_inactividad_15_30,
        "_render": _render_inactividad,
    },
    {
        "id": P_INACTIVIDAD_MAS_30,
        "label": "Recuperación (sin plan vigente)",
        "descripcion": "El mensaje de fondo para quien dejó de pagar: propone coordinar la vuelta "
                       "con el coach y lo dice sin mezclarlo con la inactividad.",
        "grupo": GRUPO_GESTION,
        "tipo_envio": TIPO_INACTIVIDAD,
        "requiere": "No tener un plan vigente (su membresía ya venció).",
        "_contexto": _contexto_inactividad_mas_30,
        "_render": _render_inactividad_mas_30,
    },
    {
        "id": P_RIESGO_ALTO,
        "label": "Acompañamiento (riesgo alto · ML)",
        "descripcion": "El check-in del coach con el alumno que el modelo marca en riesgo: el "
                       "correo NO menciona probabilidades (son datos del admin).",
        "grupo": GRUPO_GESTION,
        "tipo_envio": TIPO_RIESGO_ALTO,
        "requiere": "Que el modelo lo marque con riesgo ALTO o CRÍTICO.",
        "_contexto": _contexto_riesgo_alto,
        "_render": _render_riesgo_alto,
    },
    {
        "id": P_BENEFICIO_DESCUENTO,
        "label": "Beneficio: descuento en el próximo plan",
        "descripcion": "El correo que anuncia el % de descuento que el box acaba de regalarle.",
        "grupo": GRUPO_BENEFICIOS,
        "tipo_envio": P_BENEFICIO_DESCUENTO,
        "requiere": "Un beneficio de descuento (lo crea el panel al darlo).",
        "_contexto": _contexto_beneficio,
        "_render": _render_beneficio_descuento,
    },
    {
        "id": P_BENEFICIO_CLASES_GRATIS,
        "label": "Beneficio: clases de regalo",
        "descripcion": "El correo que anuncia las clases gratis y hasta cuándo usarlas.",
        "grupo": GRUPO_BENEFICIOS,
        "tipo_envio": P_BENEFICIO_CLASES_GRATIS,
        "requiere": "Un beneficio de clases gratis (lo crea el panel al darlo).",
        "_contexto": _contexto_beneficio,
        "_render": _render_beneficio_clases,
    },
)

# Campos del catálogo que viajan al frontend (los `_...` son internos).
CAMPOS_PUBLICOS: Final[tuple] = ("id", "label", "descripcion", "grupo", "tipo_envio", "requiere")

# Patrón de ids válidos para el `pattern` de FastAPI (una plantilla desconocida es un 422
# del cliente, no un fallback silencioso al catálogo).
PATRON_IDS: Final[str] = "^(" + "|".join(p["id"] for p in PLANTILLAS) + ")$"


def plantilla(plantilla_id) -> dict | None:
    """La entrada del catálogo con ese id, o `None`."""
    for p in PLANTILLAS:
        if p["id"] == plantilla_id:
            return p
    return None


def grupo_disponible(grupo) -> bool:
    """¿Este grupo ya se puede ofrecer? (los reservados no, criterio 6)."""
    return grupo not in GRUPOS_RESERVADOS


def _publica(p: dict) -> dict:
    """La plantilla sin sus claves internas (lo que puede viajar como JSON)."""
    return {k: p[k] for k in CAMPOS_PUBLICOS}


def plantillas_disponibles() -> list:
    """Catálogo plano y listo para el modal: sólo plantillas de grupos NO reservados."""
    return [_publica(p) for p in PLANTILLAS if grupo_disponible(p["grupo"])]


def grupos_disponibles() -> list:
    """Grupos con sus plantillas, en el orden de `GRUPOS` (los reservados no se anuncian)."""
    return [
        {"id": gid, "label": label,
         "plantillas": [_publica(p) for p in PLANTILLAS if p["grupo"] == gid]}
        for gid, label in GRUPOS
        if grupo_disponible(gid)
    ]


def normalizar_plantilla(plantilla_id) -> dict | None:
    """La plantilla del catálogo que corresponde al id, o `None` (sin inventar una default).

    A diferencia de las secciones del Historial, acá NO hay fallback: enviar "otro" correo
    porque el id venía mal es peor que rechazar la petición.
    """
    return plantilla(plantilla_id)


def catalogo() -> dict:
    """Lo que consume el modal: modo de envío + grupos + lista plana."""
    return {
        "modo_envio": email_service.modo_envio(),
        "grupos": grupos_disponibles(),
        "plantillas": plantillas_disponibles(),
    }


# ── Sugerencia: qué correo le corresponde a ESTE alumno ───────────────────────
def _sugerida(plantilla_id: str, motivo: str, contexto: dict) -> dict:
    """La sugerencia con la forma que consume el router: la plantilla, la regla y el porqué."""
    p = plantilla(plantilla_id)
    return {
        "plantilla": p["id"],
        "label": p["label"],
        "grupo": p["grupo"],
        "tipo_envio": p["tipo_envio"],
        "regla": p["id"],
        "motivo": motivo,
        "contexto": contexto,
    }


def _datos_sugerencia(db: Session, alumnos: list) -> dict:
    """Todo lo que decide la sugerencia, para TODA una lista, en 3 consultas.

    Devuelve `{alumno_id: {"alumno", "ultima_asistencia", "suscripcion", "prediccion"}}`.
    Existe porque el panel de Fidelización necesita la sugerencia de toda su tabla: resolverla
    alumno por alumno costaba 3 consultas POR FILA (y la tabla entera, cientos de consultas).
    """
    ids = [a.id for a in alumnos]
    if not ids:
        return {}
    tenant_id = alumnos[0].tenant_id

    asistencias = dict(db.query(Asistencia.usuario_id, func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id.in_(ids),
    ).group_by(Asistencia.usuario_id).all())

    # MISMO criterio que `suscripcion_vigente()`, en una consulta para todos: el orden por
    # `fecha_expiracion` desc hace que la PRIMERA fila de cada alumno sea la que se queda.
    vigentes: dict = {}
    for suscripcion, plan in db.query(Suscripcion, Plan).join(
            Plan, Suscripcion.plan_id == Plan.id).filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id.in_(ids),
            Suscripcion.estado == ESTADO_SUSCRIPCION_ACTIVO,
            vigente_hoy(Suscripcion.fecha_expiracion, hoy=hoy_santiago()),
    ).order_by(Suscripcion.fecha_expiracion.desc(), Suscripcion.id.desc()).all():
        vigentes.setdefault(suscripcion.usuario_id, (suscripcion, plan))

    predicciones: dict = {}
    for prediccion in db.query(PredictionsChurn).filter(
            PredictionsChurn.tenant_id == tenant_id,
            PredictionsChurn.usuario_id.in_(ids),
            PredictionsChurn.riesgo_nivel.in_(NIVELES_RIESGO_ALTO),
    ).order_by(PredictionsChurn.created_at.desc(),
               PredictionsChurn.id.desc()).all():
        predicciones.setdefault(prediccion.usuario_id, prediccion)

    return {a.id: {"alumno": a, "ultima_asistencia": asistencias.get(a.id),
                   "suscripcion": vigentes.get(a.id),
                   "prediccion": predicciones.get(a.id)} for a in alumnos}


def _sugerir_con(datos: dict) -> dict:
    """La REGLA de la sugerencia sobre datos YA resueltos (una sola definición).

    Es la ÚNICA definición de la sugerencia: la pantalla no adivina con su propia heurística
    (dos definiciones de "le corresponde renovación" se desincronizan siempre). Gana la PRIMERA
    regla que aplica, en este orden:

      1. `vencimiento`         plan vigente que vence en ≤ `DIAS_RENOVACION_SUGERIDA` días: es el
                               único caso con fecha límite y el alumno todavía está pagando.
      2. `plan_sin_usar`       plan vigente que todavía no estrenó ninguna clase: un plan pago
                               esperando (la MISMA definición que la recomendación del churn).
      3. `inactividad_mas_30`  SIN plan vigente (su plan ya venció): el mensaje de fondo. Con un
                               plan vigente NUNCA aplica (su copy habla de "no tienes un plan").
      4. `riesgo_alto`         el modelo lo marca ALTO/CRÍTICO y ya pasó `DIAS_TEMPRANA_MIN` días:
                               paga hoy, pero se va.
      5. `inactividad_15_30`   entre 15 y 30 días sin entrenar.
      6. `inactividad_7_14`    entre 7 y 14 días sin entrenar.
      7. (ninguna)             menos de `DIAS_TEMPRANA_MIN` días (o más de 30 con plan vigente):
                               no se inventa un correo.

    "Días sin entrenar" se cuentan desde la última asistencia; si el alumno NUNCA asistió, desde el
    INICIO de su plan vigente (compró un plan y todavía no lo estrenó); y sin plan vigente, desde su
    alta. Es la MISMA referencia que `_contexto_inactividad` (los tramos no pueden contar distinto).

    `plantilla: None` (con `regla="sin_situacion"`) es una respuesta legítima, no un error: el
    alumno que entrenó ayer no necesita que nadie lo vaya a buscar.
    """
    alumno = datos["alumno"]
    fila = datos["suscripcion"]              # (Suscripcion, Plan) vigente, o None
    ultima = datos["ultima_asistencia"]      # date de la última asistencia, o None
    inicio = fecha_chile(fila[0].fecha_inicio) if fila is not None else None

    # Desde cuándo se cuentan los días sin entrenar (ÚNICA definición): la última asistencia; si
    # NUNCA asistió, el INICIO del plan vigente (compró un plan y todavía no lo estrenó); y sin
    # plan vigente, el alta. Antes, "nunca asistió" contaba desde el alta: un alumno que compró un
    # plan hace 4 días salía con "79 días sin entrenar" y caía en el mensaje de fondo.
    if ultima is not None:
        referencia = ultima
    elif fila is not None:
        referencia = inicio
    else:
        referencia = fecha_chile(getattr(alumno, "created_at", None))
    dias = (DIAS_MINIMOS if referencia is None
            else max(DIAS_MINIMOS, (hoy_santiago() - referencia).days))
    contexto = {"dias_inactividad": dias, "ultima_asistencia": referencia}

    dias_para_vencer = dias_hasta(fila[0].fecha_expiracion) if fila is not None else None
    contexto["dias_para_vencer"] = dias_para_vencer

    # 1. `vencimiento`: plan vigente que vence en ≤ DIAS_RENOVACION_SUGERIDA días.
    if dias_para_vencer is not None and dias_para_vencer <= DIAS_RENOVACION_SUGERIDA:
        return _sugerida(P_VENCIMIENTO, f"Su plan vence en {dias_para_vencer} día(s).", contexto)
    # 2. `plan_sin_usar`: plan vigente comprado y todavía sin estrenar. Va DESPUÉS de vencimiento
    #    (si está por vencer, el aviso con fecha manda) y ANTES de inactividad: un plan pago
    #    esperando es lo más concreto que hay para ofrecer. Misma definición que el churn.
    if fila is not None and churn_service.es_plan_sin_usar(True, inicio, ultima):
        contexto["plan_sin_usar"] = True
        dias_plan = (hoy_santiago() - inicio).days if inicio else dias
        return _sugerida(
            P_PLAN_SIN_USAR,
            f"Activó el plan {fila[1].nombre} hace {dias_plan} día(s) y no registra asistencias.",
            contexto)
    # 3. `inactividad_mas_30` — el mensaje de fondo: SOLO para quien YA no tiene plan vigente. Su
    #    copy habla de "no tienes un plan vigente", así que con un plan activo nunca aplica.
    if fila is None:
        return _sugerida(P_INACTIVIDAD_MAS_30, "No tiene un plan vigente.", contexto)

    # 4. CON plan vigente: el modelo de riesgo sólo cuenta como situación cuando ya hay una señal
    #    de tiempo (≥ DIAS_TEMPRANA_MIN días). A quien compró el plan esta semana no se le manda un
    #    "estamos preocupados": todavía no hay nada que interpretar.
    if dias >= DIAS_TEMPRANA_MIN:
        prediccion = datos["prediccion"]
        if prediccion is not None:
            contexto["riesgo_nivel"] = prediccion.riesgo_nivel
            contexto["probabilidad_churn"] = float(prediccion.probabilidad_churn)
            # El riesgo del modelo se usa, pero con su FECHA visible (no es la situación de hoy).
            calculado = (prediccion.created_at.isoformat()
                         if prediccion.created_at else None)
            contexto["riesgo_calculado_en"] = calculado
            etiqueta = f"El modelo lo marca con riesgo {prediccion.riesgo_nivel}"
            if calculado:
                etiqueta += f" (calculado el {fecha_chile(prediccion.created_at)})"
            return _sugerida(P_RIESGO_ALTO, f"{etiqueta}.", contexto)
        if dias <= DIAS_TEMPRANA_MAX:
            return _sugerida(P_INACTIVIDAD_7_14, f"Lleva {dias} días sin entrenar.", contexto)
        if dias <= DIAS_INACTIVIDAD_LARGA:
            return _sugerida(P_INACTIVIDAD_15_30, f"Lleva {dias} días sin entrenar.", contexto)
        # Más de 30 días CON plan vigente: el mensaje de fondo es para quien YA no tiene plan, así
        # que acá no se inventa un correo (lo cubre el modelo si lo marca; si no, ninguno).

    if ultima is None:
        motivo = (f"Su plan arrancó hace {dias} día(s) y todavía no registra asistencias: hoy no "
                  "hay una situación que justifique un correo.")
    else:
        motivo = (f"Entrenó hace {dias} día(s): hoy no hay una situación que justifique un "
                  "correo.")
    return {
        "plantilla": None,
        "label": None,
        "grupo": None,
        "tipo_envio": None,
        "regla": REGLA_SIN_SITUACION,
        "motivo": motivo,
        "contexto": contexto,
    }


def sugerir(db: Session, alumno) -> dict:
    """Qué plantilla le corresponde a ESTE alumno, con la regla que ganó y su motivo."""
    return _sugerir_con(_datos_sugerencia(db, [alumno])[alumno.id])


def sugerir_lote(db: Session, alumnos) -> dict:
    """La MISMA sugerencia para varios alumnos: `{alumno_id: sugerencia}`.

    La usa el panel de Fidelización para la columna "Recomendación" y para el modal de detalle: con
    UNA sola regla (`_sugerir_con`), la columna de la tabla, el modal de detalle, el modal de envío
    y los correos no pueden decir cosas distintas del mismo alumno.
    """
    return {aid: _sugerir_con(uno)
            for aid, uno in _datos_sugerencia(db, list(alumnos)).items()}


# ── Render y envío ───────────────────────────────────────────────────────────
def _entrada(plantilla_id) -> dict:
    """La entrada del catálogo o `PlantillaDesconocida` (una sola validación)."""
    p = plantilla(plantilla_id)
    if p is None:
        validas = ", ".join(q["id"] for q in plantillas_disponibles())
        raise PlantillaDesconocida(
            f"Plantilla desconocida: {plantilla_id} (válidas: {validas})")
    return p


def _contexto_de(p: dict, db: Session, alumno, datos=None) -> dict:
    """Los datos de ESA plantilla: del alumno, o del regalo cuando la plantilla lo pide.

    `PLANTILLAS_CON_DATOS` son las que no se pueden armar sólo con el alumno (los correos de
    un beneficio anuncian un regalo concreto): a esas se les pasa el `datos` del pedido y
    ellas mismas rechazan lo que no alcance. Las demás no ven `datos` ni de casualidad.
    """
    if p["id"] in PLANTILLAS_CON_DATOS:
        return p["_contexto"](db, alumno, datos)
    return p["_contexto"](db, alumno)


def contexto(db: Session, alumno, plantilla_id, datos=None) -> dict:
    """Los datos REALES que alimentan la plantilla (o error claro si no alcanzan)."""
    return _contexto_de(_entrada(plantilla_id), db, alumno, datos)


def render(db: Session, alumno, plantilla_id, datos=None) -> dict:
    """El correo tal como se va a mandar (regla 1). Lo usan el PREVIEW y el ENVÍO.

    Los dos caminos pasan por acá a propósito: si el preview y el envío tuvieran cada uno
    su render, el admin podría aprobar un mensaje y mandar otro.

    `datos` viaja sólo a las plantillas que anuncian algo con números propios (un beneficio):
    son las de `PLANTILLAS_CON_DATOS`, y el correo sale con los números REALES de la fila.
    """
    p = _entrada(plantilla_id)
    correo = (getattr(alumno, "correo", None) or "").strip()
    if not correo:
        raise PlantillaSinDatos(
            "El alumno no tiene correo registrado: no hay a quién mandarle este mensaje.")
    armado = _contexto_de(p, db, alumno, datos)
    asunto, html = p["_render"](alumno, armado)
    # El pie con el contacto del box se resuelve ACÁ y no en el envío: el preview del modal
    # tiene que mostrar el mismo pie que va a recibir el alumno (si el box cargó su WhatsApp,
    # el admin lo ve antes de aprobar el envío). Se reutiliza la `db` del request: una segunda
    # conexión acá es lo que colgaba el preview (ver email_service.contacto_del_box).
    html = email_service.render_con_contacto(
        html, getattr(alumno, "tenant_id", None), db=db)
    return {
        "plantilla": p["id"],
        "label": p["label"],
        "grupo": p["grupo"],
        "tipo_envio": p["tipo_envio"],
        "destinatario": correo,
        "asunto": asunto,
        "html": html,
        "contexto": armado,
    }


def enviar(db: Session, alumno, plantilla_id, datos=None) -> dict:
    """Manda el correo ya renderizado y devuelve qué pasó DE VERDAD.

    `estado` distingue los tres desenlaces, porque el log de correos no puede mentir:
    `enviado` (salió), `simulado` (modo prueba: NO salió) y `fallido` (Gmail falló, con el
    detalle del error). El fallo de un correo no es un error de la petición: se informa.

    `notificacion_id` es la fila del log que dejó ESTE envío (o `None`): es lo que permite
    ligar el correo a lo que anunciaba (el beneficio, que la F4 mide por su correo).
    """
    mensaje = render(db, alumno, plantilla_id, datos)
    ok, notificacion_id = email_service.enviar_renderizado_con_id(
        mensaje["destinatario"], mensaje["asunto"], mensaje["html"],
        alumno_id=alumno.id, tipo=mensaje["tipo_envio"], tenant_id=alumno.tenant_id)
    modo = email_service.modo_envio()
    if ok:
        estado = (email_service.ESTADO_SIMULADO if modo == email_service.MODO_NOOP
                  else "enviado")
    else:
        estado = "fallido"
    return {
        "ok": bool(ok),
        "estado": estado,
        "modo_envio": modo,
        "detalle_error": None if ok else (email_service.ULTIMO_ERROR_SMTP
                                          or "No se pudo enviar el correo via Gmail SMTP."),
        "notificacion_id": notificacion_id,
        "plantilla": mensaje["plantilla"],
        "label": mensaje["label"],
        "tipo_envio": mensaje["tipo_envio"],
        "destinatario": mensaje["destinatario"],
        "asunto": mensaje["asunto"],
    }
