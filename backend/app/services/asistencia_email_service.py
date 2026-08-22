"""
Correos del sistema de Asistencia + Hitos (Fase 2).

Usa el template visual existente de `email_service` (marca, CTA) y el envío
SMTP centralizado. Cada envío se registra en `notificaciones_enviadas` con
`mes_referencia` para que el flujo mensual (n8n) sea idempotente.

Tipos de correo:
  1. cumplimiento     — mes con 100% de asistencia sobre lo reservado
  2. acompanamiento   — mes con asistencia parcial (<100%)
  3. hito_racha_1     — primer mes de racha (🔥)
  4. hito_racha_3     — 3 meses de racha (🔥🔥)
  5. hito_racha_6     — 6 meses de racha (🔥🔥🔥)
  6. hito_racha_12    — 12 meses de racha (🏆, nivel máximo)
"""
import logging

from app.core.config import settings
from app.services.email_service import _template, _enviar

logger = logging.getLogger("uvicorn.email")

# NOTA: la URL base del frontend sale de settings.FRONTEND_URL (.env/.env.test).
# En dev apunta a http://localhost:5173; el dominio real de producción se
# definirá en el despliegue a VPS (ver comentario en backend/.env.example).

NOMBRES_MES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _nombre_mes(mes: int) -> str:
    return NOMBRES_MES[mes] if 1 <= mes <= 12 else ""

# ── Correos de racha (asunto + título + copy motivador) ──────────────────────
RACHA_COPY = {
    1: {
        "asunto": "🔥 ¡{nombre}, encendiste la racha!",
        "titulo": "Primer mes completo 🔥",
        "cuerpo": (
            "<p><strong>{nombre}, primer mes completo.</strong> Asististe al "
            "100% de las clases que reservaste en {mes} — eso no es suerte, es "
            "decisión. La racha empieza hoy: 1 mes 🔥.</p>"
            "<p>La próxima parada son 3 meses. Nos vemos en el box.</p>"
        ),
    },
    3: {
        "asunto": "🔥🔥 {nombre}, 3 meses a todo fuego",
        "titulo": "Tres meses de fuego 🔥🔥",
        "cuerpo": (
            "<p><strong>{nombre}, tres meses seguidos con asistencia perfecta.</strong> "
            "Mientras otros buscan excusas, vos construís hábito 🔥🔥. La constancia "
            "ya es tu marca personal.</p>"
            "<p>Seguí así: la meta de los 6 meses está más cerca de lo que creés.</p>"
        ),
    },
    6: {
        "asunto": "🔥🔥🔥 {nombre}, medio año imparable",
        "titulo": "Medio año imparable 🔥🔥🔥",
        "cuerpo": (
            "<p><strong>{nombre}, medio año sin faltarle a tu entrenamiento.</strong> "
            "Seis meses de compromiso ininterrumpido 🔥🔥🔥. Ya sos referente del box.</p>"
            "<p>Falta la mitad para el año de leyenda: nosotros ponemos los WODs, "
            "vos el resto.</p>"
        ),
    },
    12: {
        "asunto": "🏆 {nombre}, ¡un año de leyenda!",
        "titulo": "Un año de leyenda 🏆",
        "cuerpo": (
            "<p><strong>{nombre}, un año entero con asistencia perfecta.</strong> "
            "Doce meses de constancia, disciplina y carácter 🏆. Esto no se logra "
            "con motivación: se logra con identidad.</p>"
            "<p>Tenés un lugar entre la élite del box. Nivel máximo alcanzado.</p>"
        ),
    },
}


def _enviar_racha(nombre: str, correo: str, alumno_id: int, nivel: int,
                  mes_nombre: str, mes_referencia) -> bool:
    """Correo de hito de racha (1/3/6/12 meses)."""
    if not correo or nivel not in RACHA_COPY:
        return False
    copy = RACHA_COPY[nivel]
    asunto = copy["asunto"].format(nombre=nombre.split()[0])
    saludo = f"Hola {nombre.split()[0]}, queremos celebrarte hoy."
    cuerpo = copy["cuerpo"].format(nombre=nombre.split()[0], mes=mes_nombre)
    html = _template(copy["titulo"], saludo, cuerpo,
                     "Ver mi progreso", f"{settings.FRONTEND_URL}/alumno/mi-progreso")
    ok = _enviar(correo, asunto, html, alumno_id,
                 tipo=f"hito_racha_{nivel}", mes_referencia=mes_referencia)
    logger.info(f"[hito_racha_{nivel}] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def enviar_email_cumplimiento(nombre: str, correo: str, alumno_id: int,
                              mes_nombre: str, total_clases: int, racha: int,
                              mes_referencia) -> bool:
    """Correo 1: cerró el mes con 100% de asistencia."""
    if not correo:
        return False
    asunto = f"🔥 ¡{nombre.split()[0]}, cerraste el mes como un campeón!"
    saludo = f"Hola {nombre.split()[0]}, cumpliste el 100% de asistencia durante {mes_nombre}."
    cuerpo = (
        f"<p>Asististe a las <strong>{total_clases} clases</strong> que reservaste "
        f"en {mes_nombre}. Eso no es suerte: es constancia.</p>"
        f"<p>Llevás una racha de <strong>{racha} mes(es)</strong> con asistencia "
        "perfecta. Seguí así: cada mes suma a tu racha.</p>"
        "<p>¡Nos vemos en el box!</p>"
    )
    html = _template("¡Mes perfecto! 🔥", saludo, cuerpo,
                     "Ver mi progreso", f"{settings.FRONTEND_URL}/alumno/mi-progreso")
    ok = _enviar(correo, asunto, html, alumno_id,
                 tipo="cumplimiento", mes_referencia=mes_referencia)
    logger.info(f"[cumplimiento] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def enviar_email_acompanamiento(nombre: str, correo: str, alumno_id: int,
                                mes_nombre: str, asistidas: int, total: int,
                                coach_nombre: str, mes_referencia) -> bool:
    """Correo 2: mes con asistencia parcial (<100%)."""
    if not correo:
        return False
    asunto = f"{nombre.split()[0]}, queremos ayudarte a retomar el ritmo"
    saludo = f"Hola {nombre.split()[0]}, vimos tu asistencia de {mes_nombre}."
    cuerpo = (
        f"<p>En {mes_nombre} asististe a <strong>{asistidas} de {total}</strong> "
        "clases que reservaste. Cualquier caída es parte del camino: lo que importa "
        "es volver.</p>"
        f"<p>{coach_nombre or 'Tu coach'} está listo para ayudarte a retomar el ritmo. "
        "Agendá tus próximas clases y volvé a sumar a tu racha.</p>"
        "<p>Te esperamos en el box 💪</p>"
    )
    html = _template("Te acompañamos", saludo, cuerpo,
                     "Ver mis clases", f"{settings.FRONTEND_URL}/alumno/mis-reservas")
    ok = _enviar(correo, asunto, html, alumno_id,
                 tipo="acompanamiento", mes_referencia=mes_referencia)
    logger.info(f"[acompanamiento] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


# ── Correo de reactivación (alumno sin plan) — Fase 2 ─────────────────────────
# Copy EXACTO aprobado por el usuario (no improvisado). Solo se interpola el
# primer nombre en "Hola [Nombre],". CTA → /alumno/solicitar-plan.
REACTIVACION_COPY = {
    "calido": {
        "asunto": "La manada te extraña 🦍",
        "titulo": "La manada te extraña 🦍",
        "parrafos": [
            "En Urban Training Box seguimos entrenando fuerte, pero notamos que "
            "hace un tiempo no te vemos por acá.",
            "La manada no es la misma sin vos. Sabemos que la vida a veces se "
            "complica y los planes cambian — no hay drama.",
            "Cuando quieras volver a sumarte, ahí vamos a estar. La puerta sigue abierta.",
        ],
        "cta": "Ver planes disponibles",
    },
    "motivacional": {
        "asunto": "El progreso que dejaste en pausa, sigue esperándote 💪",
        "titulo": "El progreso que dejaste en pausa, sigue esperándote 💪",
        "parrafos": [
            "Van ya varios meses desde tu última clase en Urban Training Box.",
            "La manada sigue subiendo de nivel — nuevos récords, nuevas rachas, "
            "gente llegando a su mejor versión. Y sabemos que vos también ibas "
            "por ese camino.",
            "Cada mes que pasa sin entrenar es progreso que cuesta más recuperar: "
            "la fuerza, el hábito, la energía que habías construido. Nada de esto "
            "se pierde para siempre, pero mientras más tiempo pase, más arranque "
            "necesita el regreso.",
            "Todavía estás a tiempo de retomarlo. La manada te espera con los "
            "brazos abiertos.",
        ],
        "cta": "Volver a entrenar",
    },
}


def enviar_email_reactivacion(nombre: str, correo: str, alumno_id: int,
                              meses_sin_plan: int, mes_nombre: str,
                              mes_referencia) -> bool:
    """Correo de reactivación: tuvo plan, hoy no tiene ninguno que cubra el mes.

    - Meses 1-3 sin plan → variante cálida ("La manada te extraña 🦍").
    - Mes 4+ → variante motivacional ("El progreso que dejaste en pausa 💪").
    CTA → /alumno/solicitar-plan. Incluye link de opt-out (token HMAC) al final.
    """
    if not correo:
        return False
    from app.services.asistencia_service import generar_token_optout

    variante = "motivacional" if meses_sin_plan >= 4 else "calido"
    copy = REACTIVACION_COPY[variante]
    primer = nombre.split()[0]
    asunto = copy["asunto"]
    saludo = f"Hola {primer},"
    cuerpo = "".join(f"<p>{p}</p>" for p in copy["parrafos"])
    cuerpo += "<p>— El equipo de Urban Training Box</p>"

    # Link de opt-out: endpoint público del backend (no requiere frontend ni login).
    token = generar_token_optout(alumno_id)
    optout_url = (f"{settings.BACKEND_PUBLIC_URL}"
                  f"/api/v1/notificaciones/reactivacion/optout?token={token}")
    cuerpo += (
        "<p style='text-align:center;font-size:12px;color:#71717a;margin-top:24px;'>"
        "¿No querés recibir más correos como este? "
        f"<a href='{optout_url}' style='color:#71717a;'>"
        "Click acá para darte de baja</a></p>"
    )

    html = _template(copy["titulo"], saludo, cuerpo, copy["cta"],
                     f"{settings.FRONTEND_URL}/alumno/solicitar-plan")
    ok = _enviar(correo, asunto, html, alumno_id,
                 tipo="reactivacion", mes_referencia=mes_referencia)
    logger.info(f"[reactivacion] {'EXITOSO' if ok else 'FALLIDO'} -> {correo} "
                f"(meses_sin_plan={meses_sin_plan}, variante={variante})")
    return ok
