"""
Servicio central del sistema de Asistencia + Hitos.

Reglas de negocio confirmadas (diseño Fase 1 y 2):
- "Clase contratada" = reserva con estado IN ('confirmada','completada').
- % de asistencia del mes M = asistidas / reservadas (sobre lo RESERVADO).
- Mes sin reservas → la racha se CONGELA (no suma ni corta).
- Mes con <100% → la racha se CORTA (vuelve a 0).
- Hitos: una sola vez por nivel (1/3/6/12), garantizado por UNIQUE(alumno_id, nivel).
- Evaluación mensual idempotente: dedupe con notificaciones_enviadas.mes_referencia.
- Fechas "hoy"/"mes" SIEMPRE en America/Santiago (app.utils.santiago).
"""
import calendar
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.utils.santiago import ahora_santiago, hoy_santiago
from app.models.reserva import Reserva
from app.models.clase import Clase
from app.models.usuario import Usuario, RolUsuario
from app.models.hito_alumno import HitoAlumno
from app.models.notificacion_enviada import NotificacionEnviada

NIVELES_HITO = (1, 3, 6, 12)
ESTADOS_VALIDOS = ("confirmada", "completada")

# Tipos de correo registrados en notificaciones_enviadas
TIPO_CUMPLIMIENTO = "cumplimiento"
TIPO_ACOMPANAMIENTO = "acompanamiento"


def _mes_anterior(anio: int, mes: int):
    if mes == 1:
        return anio - 1, 12
    return anio, mes - 1


def _mes_siguiente(anio: int, mes: int):
    if mes == 12:
        return anio + 1, 1
    return anio, mes + 1


def _rango_mes(anio: int, mes: int):
    ultimo = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, 1), date(anio, mes, ultimo)


def _reservas_mes(db: Session, alumno_id: int, tenant_id: int,
                  anio: int, mes: int, hasta_hoy: bool = False):
    """Reservas válidas del alumno cuyas CLASES caen en el mes indicado."""
    desde, hasta = _rango_mes(anio, mes)
    if hasta_hoy:
        hasta = hoy_santiago()
    return db.query(Reserva).join(Clase, Reserva.clase_id == Clase.id).filter(
        Reserva.tenant_id == tenant_id,
        Reserva.alumno_id == alumno_id,
        Reserva.estado.in_(ESTADOS_VALIDOS),
        Clase.fecha >= desde,
        Clase.fecha <= hasta,
    ).all()


def calcular_asistencia_mes(db: Session, alumno_id: int, tenant_id: int,
                            anio: int, mes: int, hasta_hoy: bool = False) -> dict:
    """% de asistencia del mes (sobre lo reservado).

    `hasta_hoy=True` se usa para el mes EN CURSO (solo clases ya pasadas,
    para no inflar el total con reservas futuras del mes).
    """
    reservas = _reservas_mes(db, alumno_id, tenant_id, anio, mes,
                             hasta_hoy=hasta_hoy)
    total = len(reservas)
    asistidas = sum(1 for r in reservas if r.asistio)
    if total == 0:
        estado = "sin_actividad"
    elif asistidas == total:
        estado = "completo"
    else:
        estado = "parcial"
    return {
        "anio": anio,
        "mes": mes,
        "total_reservadas": total,
        "asistidas": asistidas,
        "pct": round(asistidas / total * 100) if total else 0,
        "estado": estado,
    }


def calcular_racha(db: Session, alumno_id: int, tenant_id: int,
                   anio: int, mes: int) -> int:
    """Meses consecutivos cerrados con 100% desde (anio, mes) hacia atrás.

    - Mes con <100% de asistencia → corte (racha a 0).
    - Mes sin reservas → se congela (no suma, no corta).

    La caminata se acota al mes más antiguo con reservas del alumno (evita
    consultas inútiles; crítico con la latencia de Neon).
    """
    min_fecha = db.query(func.min(Clase.fecha)).join(
        Reserva, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.alumno_id == alumno_id,
        Reserva.tenant_id == tenant_id,
        Reserva.estado.in_(ESTADOS_VALIDOS),
    ).scalar()
    if min_fecha is None:
        return 0
    min_ym = (min_fecha.year, min_fecha.month)

    racha = 0
    a, m = anio, mes
    while (a, m) >= min_ym:
        reservas = _reservas_mes(db, alumno_id, tenant_id, a, m)
        if not reservas:
            a, m = _mes_anterior(a, m)
            continue
        asistidas = sum(1 for r in reservas if r.asistio)
        if asistidas != len(reservas):
            break
        racha += 1
        a, m = _mes_anterior(a, m)
    return racha


def _nivel_para_racha(racha: int) -> int:
    """Máximo nivel de hito alcanzado con la racha actual (0 si ninguno)."""
    nivel = 0
    for n in NIVELES_HITO:
        if racha >= n:
            nivel = n
    return nivel

def obtener_hito_pendiente(db: Session, alumno_id: int, tenant_id: int,
                           anio: int, mes: int):
    """Hito a notificar por cierre del mes (nuevo o pendiente de correo).

    Devuelve (hito, racha). Si no corresponde ningún hito → (None, racha).
    Un hito con notificado=False (p.ej. el correo anterior falló) se devuelve
    para reintentar el envío SIN duplicar la fila (UNIQUE ya la protege).
    """
    racha = calcular_racha(db, alumno_id, tenant_id, anio, mes)
    nivel = _nivel_para_racha(racha)
    if not nivel:
        return None, racha
    hito = db.query(HitoAlumno).filter(
        HitoAlumno.alumno_id == alumno_id,
        HitoAlumno.nivel == nivel,
    ).first()
    if hito:
        # Si ya está notificado, no hay nada nuevo; si no, es un reintento.
        return hito, racha
    hito = HitoAlumno(
        tenant_id=tenant_id,
        alumno_id=alumno_id,
        nivel=nivel,
        meses_consecutivos=racha,
        mes_alcanzado=date(anio, mes, 1),
        notificado=False,
    )
    db.add(hito)
    db.flush()
    return hito, racha


# ── Dedupe de correos mensuales ──────────────────────────────────────────────
def ya_notificado(db: Session, alumno_id: int, tipo: str,
                  mes_referencia: date) -> bool:
    """True si ya se registró un envío del tipo para ese mes (idempotencia)."""
    return db.query(NotificacionEnviada).filter(
        NotificacionEnviada.alumno_id == alumno_id,
        NotificacionEnviada.tipo == tipo,
        NotificacionEnviada.mes_referencia == mes_referencia,
    ).first() is not None


# ── Evaluación mensual (n8n) ─────────────────────────────────────────────────
def _coach_del_box(db: Session, tenant_id: int):
    """Primer coach activo del box (para el correo de acompañamiento)."""
    coach = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.coach,
        Usuario.activo == True,
    ).order_by(Usuario.id).first()
    return coach.nombre if coach else "Tu coach"


def evaluar_mes(db: Session, tenant_id: int, anio: int, mes: int,
                enviar_correos: bool = True) -> dict:
    """Cierra el mes (anio, mes) para todos los alumnos activos del tenant.

    - 100% → correo de cumplimiento (dedupe por mes_referencia) + evalúa hito.
    - <100% → correo de acompañamiento (dedupe por mes_referencia).
    - Sin reservas → no aplica (ni cumple ni incumple; la racha se congela).

    Idempotente: si n8n llama 2 veces el mismo mes, los dedupes no re-envían
    y los hitos no se duplican (UNIQUE(alumno_id, nivel)).
    """
    from app.services.asistencia_email_service import (
        enviar_email_cumplimiento, enviar_email_acompanamiento, _enviar_racha,
        _nombre_mes,
    )

    alumnos = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.activo == True,
        Usuario.estado == "activo",
    ).all()

    mes_referencia = date(anio, mes, 1)
    mes_nombre = _nombre_mes(mes)

    resumen = {
        "tenant_id": tenant_id,
        "anio": anio,
        "mes": mes,
        "alumnos_evaluados": 0,
        "cumplimiento": 0,
        "acompanamiento": 0,
        "hitos_generados": 0,
        "detalle_hitos": [],
    }

    for alumno in alumnos:
        calculo = calcular_asistencia_mes(db, alumno.id, tenant_id, anio, mes)
        if calculo["estado"] == "sin_actividad":
            continue
        resumen["alumnos_evaluados"] += 1

        if calculo["estado"] == "completo":
            # Correo 1: cumplimiento mensual (una sola vez por mes).
            if not ya_notificado(db, alumno.id, TIPO_CUMPLIMIENTO, mes_referencia):
                racha_actual = calcular_racha(db, alumno.id, tenant_id, anio, mes)
                if enviar_correos:
                    enviar_email_cumplimiento(
                        alumno.nombre, alumno.correo, alumno.id,
                        mes_nombre, calculo["total_reservadas"],
                        racha_actual, mes_referencia)
                resumen["cumplimiento"] += 1

            # Hito de racha (dedupe por hitos_alumno.notificado).
            hito, _ = obtener_hito_pendiente(db, alumno.id, tenant_id, anio, mes)
            if hito and not hito.notificado:
                if enviar_correos:
                    _enviar_racha(alumno.nombre, alumno.correo, alumno.id,
                                  hito.nivel, mes_nombre, mes_referencia)
                hito.notificado = True
                hito.fecha_notificacion = ahora_santiago()
                db.flush()
                resumen["hitos_generados"] += 1
                resumen["detalle_hitos"].append({
                    "alumno_id": alumno.id,
                    "nombre": alumno.nombre,
                    "nivel": hito.nivel,
                    "meses_consecutivos": hito.meses_consecutivos,
                    "mes_alcanzado": str(hito.mes_alcanzado),
                })
        else:  # parcial
            # Correo 2: acompañamiento (una sola vez por mes).
            if not ya_notificado(db, alumno.id, TIPO_ACOMPANAMIENTO, mes_referencia):
                coach_nombre = _coach_del_box(db, tenant_id)
                if enviar_correos:
                    enviar_email_acompanamiento(
                        alumno.nombre, alumno.correo, alumno.id,
                        mes_nombre, calculo["asistidas"],
                        calculo["total_reservadas"], coach_nombre,
                        mes_referencia)
                resumen["acompanamiento"] += 1

    db.commit()
    return resumen


def backfill_hitos(db: Session, meses: int = 12,
                   tenant_id: int = None) -> dict:
    """Backfill retroactivo de hitos sobre los últimos `meses` meses cerrados.

    Se ejecuta UNA vez al desplegar la funcionalidad. Genera los hitos que
    correspondan con notificado=True (NO envía correos retroactivos, para no
    disparar una avalancha de emails). Idempotente: re-ejecutarlo no duplica
    nada (UNIQUE(alumno_id, nivel)).
    """
    hoy = hoy_santiago()
    anio_fin, mes_fin = _mes_anterior(hoy.year, hoy.month)

    query_alumnos = db.query(Usuario).filter(
        Usuario.rol == RolUsuario.alumno,
        Usuario.activo == True,
        Usuario.estado == "activo",
    )
    if tenant_id is not None:
        query_alumnos = query_alumnos.filter(Usuario.tenant_id == tenant_id)
    alumnos = query_alumnos.all()

    creados_total = 0
    detalle = []
    ahora = ahora_santiago()

    for alumno in alumnos:
        # Ventana de meses oldest → newest (para racha corrida).
        ventana = []
        a, m = anio_fin, mes_fin
        for _ in range(meses):
            ventana.append((a, m))
            a, m = _mes_anterior(a, m)
        ventana.reverse()

        racha = 0
        for a, m in ventana:
            reservas = _reservas_mes(db, alumno.id, alumno.tenant_id, a, m)
            if not reservas:
                continue  # mes sin actividad → se congela
            asistidas = sum(1 for r in reservas if r.asistio)
            if asistidas != len(reservas):
                racha = 0  # corte
                continue
            racha += 1
            nivel = _nivel_para_racha(racha)
            if not nivel:
                continue
            existente = db.query(HitoAlumno).filter(
                HitoAlumno.alumno_id == alumno.id,
                HitoAlumno.nivel == nivel,
            ).first()
            if existente:
                continue
            db.add(HitoAlumno(
                tenant_id=alumno.tenant_id,
                alumno_id=alumno.id,
                nivel=nivel,
                meses_consecutivos=racha,
                mes_alcanzado=date(a, m, 1),
                notificado=True,
                fecha_notificacion=ahora,
            ))
            # flush para que las consultas siguientes vean el hito recién
            # agregado (autoflush=False en la sesión) y no se duplique.
            db.flush()
            creados_total += 1
            detalle.append({
                "alumno_id": alumno.id,
                "nombre": alumno.nombre,
                "nivel": nivel,
                "meses_consecutivos": racha,
                "mes_alcanzado": f"{a}-{m:02d}-01",
            })

    db.commit()
    return {
        "hitos_creados": creados_total,
        "alumnos_procesados": len(alumnos),
        "ventana_meses": meses,
        "detalle": detalle,
    }


# ── Vistas para el alumno ────────────────────────────────────────────────────
def resumen_alumno(db: Session, alumno_id: int, tenant_id: int) -> dict:
    """Racha actual, % del mes en curso y próximo hito (GET /mi-resumen)."""
    hoy = hoy_santiago()

    # Mes en curso: solo clases ya pasadas (no inflar con reservas futuras).
    mes_curso = calcular_asistencia_mes(db, alumno_id, tenant_id,
                                        hoy.year, hoy.month, hasta_hoy=True)

    anio_prev, mes_prev = _mes_anterior(hoy.year, hoy.month)
    racha = calcular_racha(db, alumno_id, tenant_id, anio_prev, mes_prev)

    hitos = db.query(HitoAlumno).filter(
        HitoAlumno.alumno_id == alumno_id,
        HitoAlumno.tenant_id == tenant_id,
    ).order_by(HitoAlumno.nivel.asc()).all()

    proximo_hito = next((n for n in NIVELES_HITO if n > racha), None)

    return {
        "mes_en_curso": mes_curso,
        "racha_actual": racha,
        "proximo_hito": proximo_hito,
        "nivel_maximo": 12,
        "hitos_alcanzados": [
            {
                "nivel": h.nivel,
                "meses_consecutivos": h.meses_consecutivos,
                "mes_alcanzado": str(h.mes_alcanzado),
                "notificado": h.notificado,
            }
            for h in hitos
        ],
    }


def hitos_alumno_list(db: Session, alumno_id: int, tenant_id: int) -> list:
    """Lista de hitos alcanzados por el alumno (GET /mis-hitos)."""
    hitos = db.query(HitoAlumno).filter(
        HitoAlumno.alumno_id == alumno_id,
        HitoAlumno.tenant_id == tenant_id,
    ).order_by(HitoAlumno.nivel.asc()).all()
    return [
        {
            "id": h.id,
            "nivel": h.nivel,
            "meses_consecutivos": h.meses_consecutivos,
            "mes_alcanzado": str(h.mes_alcanzado),
            "fecha_logro": str(h.fecha_logro) if h.fecha_logro else None,
            "notificado": h.notificado,
        }
        for h in hitos
    ]

