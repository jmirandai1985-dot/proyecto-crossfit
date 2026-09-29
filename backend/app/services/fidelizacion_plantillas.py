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

from app.models.asistencia import Asistencia
from app.models.plan import Plan
from app.models.predictions_churn import PredictionsChurn
from app.models.suscripcion import Suscripcion
from app.services import email_service
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

# ── Umbrales de cada situación (cada número vive en UN lugar) ─────────────────
# Piso de "días sin entrenar": un correo de recuperación no puede decir "0 días".
DIAS_MINIMOS: Final[int] = 1
# Tramos de inactividad del catálogo.
DIAS_TEMPRANA_MIN: Final[int] = 7        # desde acá ya es "hace unos días que no venís"
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
    """Desde cuándo se cuentan los días sin entrenar.

    Última asistencia y, si nunca asistió, la fecha de alta: mismo criterio que la
    Acción Rápida del panel (decir "7 días" fijo era un número inventado).
    """
    ultima = db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == alumno.tenant_id,
        Asistencia.usuario_id == alumno.id,
    ).scalar()
    return ultima or fecha_chile(getattr(alumno, "created_at", None))


def _contexto_inactividad(db: Session, alumno) -> dict:
    """Días sin entrenar (mínimo 1) y la fecha desde la que se cuentan."""
    referencia = _referencia_actividad(db, alumno)
    dias = (DIAS_MINIMOS if referencia is None
            else max(DIAS_MINIMOS, (hoy_santiago() - referencia).days))
    return {"dias_inactividad": dias, "ultima_asistencia": referencia}


def dias_inactividad(db: Session, alumno) -> int:
    """Días sin entrenar (UNA definición: sale del contexto de la plantilla)."""
    return _contexto_inactividad(db, alumno)["dias_inactividad"]


def suscripcion_vigente(db: Session, alumno, hoy: date = None):
    """`(Suscripcion, Plan)` de la membresía que HOY da acceso, o `None` (criterio 5).

    Si hay más de una, gana la que vence MÁS TARDE: es la que el alumno va a renovar.
    """
    hoy = hoy or hoy_santiago()
    return (
        db.query(Suscripcion, Plan)
        .join(Plan, Suscripcion.plan_id == Plan.id)
        .filter(Suscripcion.tenant_id == alumno.tenant_id,
                Suscripcion.usuario_id == alumno.id,
                Suscripcion.estado == ESTADO_SUSCRIPCION_ACTIVO,
                Suscripcion.fecha_expiracion >= hoy)
        .order_by(Suscripcion.fecha_expiracion.desc(), Suscripcion.id.desc())
        .first()
    )


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
        "dias_restantes": max(0, (vence - hoy_santiago()).days),
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
    """El mensaje de fondo: más de un mes sin entrenar **o** sin plan vigente.

    Acá SÍ se admite una de las dos situaciones (no hay rango de días que rechazar): el texto
    del correo cambia la frase del plan según `plan_vencido`.
    """
    datos = _contexto_inactividad(db, alumno)
    datos["plan_vencido"] = not tiene_membresia_vigente(db, alumno)
    if datos["dias_inactividad"] <= DIAS_INACTIVIDAD_LARGA and not datos["plan_vencido"]:
        otra = _tramo_que_corresponde(db, alumno)
        raise PlantillaSinDatos(
            f"Esta plantilla es para más de {DIAS_INACTIVIDAD_LARGA} días sin entrenar o una "
            f"membresía vencida, y este alumno lleva {datos['dias_inactividad']} días con plan "
            f"vigente." + (f" Le corresponde `{otra}`." if otra else ""))
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
        "label": "Recuperación (más de 30 días o plan vencido)",
        "descripcion": "El mensaje de fondo: propone coordinar la vuelta con el coach y, si dejó "
                       "de pagar, lo dice sin mezclar las dos cosas.",
        "grupo": GRUPO_GESTION,
        "tipo_envio": TIPO_INACTIVIDAD,
        "requiere": "Más de 30 días sin entrenar o una membresía vencida.",
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


def sugerir(db: Session, alumno) -> dict:
    """Qué plantilla le corresponde a este alumno, con la regla que ganó y su motivo.

    Es la ÚNICA definición de la sugerencia: la pantalla ya no adivina con su propia heurística
    (dos definiciones de "le corresponde renovación" se desincronizan siempre). Gana la PRIMERA
    regla que aplica, en este orden:

      1. `vencimiento`         plan vigente que vence en ≤ `DIAS_RENOVACION_SUGERIDA` días: es el
                               único caso con fecha límite y el alumno todavía está pagando.
      2. `inactividad_mas_30`  sin plan vigente (su plan ya venció) o más de
                               `DIAS_INACTIVIDAD_LARGA` días sin entrenar: el mensaje de fondo.
      3. `riesgo_alto`         el modelo lo marca ALTO/CRÍTICO: paga hoy, pero se va.
      4. `inactividad_15_30`   entre 15 y 30 días sin entrenar.
      5. `inactividad_7_14`    el resto de los inactivos.
      6. (ninguna)             menos de `DIAS_TEMPRANA_MIN` días: no se inventa un correo.

    `plantilla: None` (con `regla="sin_situacion"`) es una respuesta legítima, no un error: el
    alumno que entrenó ayer no necesita que nadie lo vaya a buscar.
    """
    contexto = dict(_contexto_inactividad(db, alumno))
    dias = contexto["dias_inactividad"]
    fila = suscripcion_vigente(db, alumno)
    dias_para_vencer = None
    if fila is not None:
        suscripcion, _plan = fila
        dias_para_vencer = max(0, (fecha_chile(suscripcion.fecha_expiracion)
                                  - hoy_santiago()).days)
    contexto["dias_para_vencer"] = dias_para_vencer

    if dias_para_vencer is not None and dias_para_vencer <= DIAS_RENOVACION_SUGERIDA:
        return _sugerida(P_VENCIMIENTO, f"Su plan vence en {dias_para_vencer} día(s).", contexto)
    if fila is None:
        return _sugerida(P_INACTIVIDAD_MAS_30, "No tiene un plan vigente.", contexto)
    if dias > DIAS_INACTIVIDAD_LARGA:
        return _sugerida(P_INACTIVIDAD_MAS_30, f"Lleva {dias} días sin entrenar.", contexto)

    prediccion = prediccion_riesgo(db, alumno)
    if prediccion is not None:
        contexto["riesgo_nivel"] = prediccion.riesgo_nivel
        contexto["probabilidad_churn"] = float(prediccion.probabilidad_churn)
        return _sugerida(P_RIESGO_ALTO,
                         f"El modelo lo marca con riesgo {prediccion.riesgo_nivel}.", contexto)
    if dias > DIAS_TEMPRANA_MAX:
        return _sugerida(P_INACTIVIDAD_15_30, f"Lleva {dias} días sin entrenar.", contexto)
    if dias >= DIAS_TEMPRANA_MIN:
        return _sugerida(P_INACTIVIDAD_7_14, f"Lleva {dias} días sin entrenar.", contexto)
    return {
        "plantilla": None,
        "label": None,
        "grupo": None,
        "tipo_envio": None,
        "regla": REGLA_SIN_SITUACION,
        "motivo": (f"Entrenó hace {dias} día(s): hoy no hay una situación que justifique un "
                   "correo."),
        "contexto": contexto,
    }


# ── Render y envío ───────────────────────────────────────────────────────────
def _entrada(plantilla_id) -> dict:
    """La entrada del catálogo o `PlantillaDesconocida` (una sola validación)."""
    p = plantilla(plantilla_id)
    if p is None:
        validas = ", ".join(q["id"] for q in plantillas_disponibles())
        raise PlantillaDesconocida(
            f"Plantilla desconocida: {plantilla_id} (válidas: {validas})")
    return p


def contexto(db: Session, alumno, plantilla_id) -> dict:
    """Los datos REALES que alimentan la plantilla (o error claro si no alcanzan)."""
    return _entrada(plantilla_id)["_contexto"](db, alumno)


def render(db: Session, alumno, plantilla_id) -> dict:
    """El correo tal como se va a mandar (regla 1). Lo usan el PREVIEW y el ENVÍO.

    Los dos caminos pasan por acá a propósito: si el preview y el envío tuvieran cada uno
    su render, el admin podría aprobar un mensaje y mandar otro.
    """
    p = _entrada(plantilla_id)
    correo = (getattr(alumno, "correo", None) or "").strip()
    if not correo:
        raise PlantillaSinDatos(
            "El alumno no tiene correo registrado: no hay a quién mandarle este mensaje.")
    datos = p["_contexto"](db, alumno)
    asunto, html = p["_render"](alumno, datos)
    return {
        "plantilla": p["id"],
        "label": p["label"],
        "grupo": p["grupo"],
        "tipo_envio": p["tipo_envio"],
        "destinatario": correo,
        "asunto": asunto,
        "html": html,
        "contexto": datos,
    }


def enviar(db: Session, alumno, plantilla_id) -> dict:
    """Manda el correo ya renderizado y devuelve qué pasó DE VERDAD.

    `estado` distingue los tres desenlaces, porque el log de correos no puede mentir:
    `enviado` (salió), `simulado` (modo prueba: NO salió) y `fallido` (Gmail falló, con el
    detalle del error). El fallo de un correo no es un error de la petición: se informa.
    """
    mensaje = render(db, alumno, plantilla_id)
    ok = email_service.enviar_renderizado(
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
        "plantilla": mensaje["plantilla"],
        "label": mensaje["label"],
        "tipo_envio": mensaje["tipo_envio"],
        "destinatario": mensaje["destinatario"],
        "asunto": mensaje["asunto"],
    }
