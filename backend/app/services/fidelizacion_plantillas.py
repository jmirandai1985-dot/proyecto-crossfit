"""Plantillas de correo de Fidelización — el catálogo completo en UNA definición.

Qué es
------
El panel de Fidelización detecta a quién hay que ir a buscar (churn del ML, planes por
vencer) y "Acción Rápida" mandaba un correo **a ciegas**: el admin elegía `inactividad` o
`vencimiento` y no veía nunca el mensaje. Ahora el envío es: **elegir plantilla → ver el
correo EXACTO → enviar**. Este módulo es la definición única de:

  * qué se puede mandar (catálogo, con su grupo y su `tipo_envio` para el log de correos);
  * con qué datos REALES se arma (días sin entrenar, membresía vigente y su vencimiento);
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
 7. Un envío NUNCA es automático acá: lo dispara una persona (la automatización es otra fase).
"""
from datetime import date
from typing import Final

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.asistencia import Asistencia
from app.models.plan import Plan
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

# ── Ids de plantilla ─────────────────────────────────────────────────────────
P_INACTIVIDAD: Final[str] = "inactividad"
P_VENCIMIENTO: Final[str] = "vencimiento"

# Piso de "días sin entrenar": un correo de recuperación no puede decir "0 días".
DIAS_MINIMOS: Final[int] = 1

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


# ── Renders (reusan el copy de `email_service`: no hay una segunda versión) ────
def _render_inactividad(alumno, contexto) -> tuple:
    return email_service.render_email_fidelizacion(alumno.nombre, contexto["dias_inactividad"])


def _render_vencimiento(alumno, contexto) -> tuple:
    return email_service.render_email_vencimiento_plan(
        alumno.nombre, contexto["plan"], contexto["fecha_expiracion"])


# ── El catálogo ──────────────────────────────────────────────────────────────
# Cada entrada es autosuficiente: sus datos (`_contexto`) y su render (`_render`) viven en
# la MISMA fila, así que agregar una plantilla no puede desincronizar un segundo diccionario.
# Las claves que empiezan con `_` son internas: `plantillas_disponibles()` no las publica.
PLANTILLAS: Final[tuple] = (
    {
        "id": P_INACTIVIDAD,
        "label": "Recuperación (alumno inactivo)",
        "descripcion": "Sus días reales sin entrenar y una invitación a volver al box.",
        "grupo": GRUPO_GESTION,
        "tipo_envio": "inactividad",
        "requiere": "Nada más que su historial: los días salen de sus asistencias.",
        "_contexto": _contexto_inactividad,
        "_render": _render_inactividad,
    },
    {
        "id": P_VENCIMIENTO,
        "label": "Renovación (plan por vencer)",
        "descripcion": "El aviso de vencimiento con el plan y la fecha reales.",
        "grupo": GRUPO_GESTION,
        "tipo_envio": "vencimiento",
        "requiere": "Una membresía vigente (si no tiene, el envío se rechaza).",
        "_contexto": _contexto_vencimiento,
        "_render": _render_vencimiento,
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
