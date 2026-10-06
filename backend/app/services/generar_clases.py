"""
Servicio compartido para generación de clases desde horarios_base
Usado por: endpoint HTTP, scheduler diario, y respaldo automático
"""
import logging
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger("uvicorn.generar_clases")

# ── Ventana de generación automática de clases ──────────────────────────────
# Cuántos días hacia adelante se generan/garantizan clases.
# Antes: 6 (hoy+6 = 7 días). Ahora: 28 (4 semanas).
# Centralizado acá para que scheduler (00:05), startup de main.py, el fallback
# de GET /clases y los overrides TEST compartan SIEMPRE el mismo valor.
DIAS_ANTICIPACION = 28


def generar_clases_para_fecha(
    db: Session,
    tenant_id: int,
    fecha: date,
) -> dict:
    """
    Genera clases en la tabla 'clases' a partir de los horarios_base
    del día de semana correspondiente a la 'fecha' indicada.
    NO duplica si ya existen clases con el mismo (horario_base_id, fecha).

    Args:
        db: Sesión de base de datos
        tenant_id: ID del tenant (box)
        fecha: Objeto date para el cual generar clases

    Returns:
        dict con: creadas, omitidas, total_horarios, message

    B2: cada clase nueva hereda al coach VIGENTE de su horario (tabla
    `horarios_coach`): así, tomar un horario recurrente alcanza también a las
    clases que se generen después (ver services/asignaciones_clases.py).
    """
    from app.models.horario_base import HorarioBase
    from app.models.clase import Clase
    # B2 (migración 043): import local para no crear un ciclo de imports con el
    # servicio de asignaciones, que es quien lee `horarios_coach`.
    from app.services.asignaciones_clases import (
        ORIGEN_COACH,
        vigencias_por_horario,
    )

    dia_semana = fecha.weekday()  # 0=Lun ... 6=Dom  (B2: ver coach vigente más abajo)
    if dia_semana == 6:
        return {"message": "Domingo: no hay horarios base programados", "creadas": 0, "omitidas": 0, "total_horarios": 0}

    horarios = db.query(HorarioBase).filter(
        HorarioBase.tenant_id == tenant_id,
        HorarioBase.dia_semana == dia_semana,
        HorarioBase.activo == True
    ).all()

    if not horarios:
        return {"message": f"No hay horarios base activos para el día {dia_semana}", "creadas": 0, "omitidas": 0, "total_horarios": 0}

    # Coach VIGENTE por horario para esta fecha: 1 sola query para todo el día.
    vigencias = vigencias_por_horario(
        db, tenant_id, [h.id for h in horarios], fecha)

    creadas = 0
    omitidas = 0
    for h in horarios:
        existe = db.query(Clase).filter(
            Clase.tenant_id == tenant_id,
            Clase.horario_base_id == h.id,
            Clase.fecha == fecha
        ).first()
        if existe:
            omitidas += 1
            continue

        vigencia = vigencias.get(h.id)
        clase = Clase(
            tenant_id=tenant_id,
            horario_base_id=h.id,
            disciplina_id=h.disciplina_id,
            fecha=fecha,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            cupo_maximo=h.cupo_maximo,
            cupo_original=h.cupo_maximo,
            asistentes_confirmados=0,
            cancelada=False,
            # B2: hereda el coach del horario recurrente (marca ✅ 'coach').
            coach_id=vigencia.coach_id if vigencia else None,
            asignacion_origen=ORIGEN_COACH if vigencia else None,
            asignada_por=vigencia.coach_id if vigencia else None,
            asignada_en=datetime.now(timezone.utc) if vigencia else None,
        )
        db.add(clase)
        creadas += 1

    db.commit()

    resultado = {
        "message": f"{creadas} clases generadas para {fecha.isoformat()}",
        "creadas": creadas,
        "omitidas": omitidas,
        "total_horarios": len(horarios),
        "fecha": fecha.isoformat(),
        "dia_semana": dia_semana,
    }

    if creadas > 0:
        logger.info(
            f"✅ Generadas {creadas} clases para {fecha.isoformat()} (tenant={tenant_id})")

    return resultado


def generar_clases_para_rango(
    db: Session,
    tenant_id: int,
    fecha_desde: date,
    fecha_hasta: date,
) -> dict:
    """
    Genera clases para un rango de fechas [fecha_desde, fecha_hasta].
    NO duplica si ya existen clases con el mismo (horario_base_id, fecha).

    Args:
        db: Sesión de base de datos
        tenant_id: ID del tenant
        fecha_desde: Fecha inicial (incluida)
        fecha_hasta: Fecha final (incluida)

    Returns:
        dict con resultados agregados
    """
    total_creadas = 0
    total_omitidas = 0
    fechas_procesadas = []
    fecha_actual = fecha_desde

    while fecha_actual <= fecha_hasta:
        if fecha_actual.weekday() == 6:  # Domingo
            fecha_actual += timedelta(days=1)
            continue

        resultado = generar_clases_para_fecha(
            db, tenant_id=tenant_id, fecha=fecha_actual)
        total_creadas += resultado.get("creadas", 0)
        total_omitidas += resultado.get("omitidas", 0)
        fechas_procesadas.append(fecha_actual.isoformat())
        fecha_actual += timedelta(days=1)

    logger.info(
        f"✅ Rango [{fecha_desde.isoformat()} -> {fecha_hasta.isoformat()}]: "
        f"{total_creadas} creadas, {total_omitidas} omitidas en {len(fechas_procesadas)} día(s)"
    )

    return {
        "message": f"{total_creadas} clases generadas del {fecha_desde.isoformat()} al {fecha_hasta.isoformat()}",
        "creadas": total_creadas,
        "omitidas": total_omitidas,
        "fechas_procesadas": fechas_procesadas,
        "fecha_desde": fecha_desde.isoformat(),
        "fecha_hasta": fecha_hasta.isoformat(),
    }


# ── Revisión del rango en UNA pasada (arranque del backend más rápido) ──────────
# Antes, el arranque (`main.startup_event`) recorría el rango día por día y hacía un COUNT
# de clases Y otro de horarios por CADA fecha (hasta 28 x 2 consultas; con la latencia de
# Neon eso alargaba el arranque). Acá la revisión es UNA consulta agregada de conteo por
# fecha + UNA de horarios activos por día de semana, y la generación toca SÓLO los días
# incompletos. El resultado final es el MISMO que regenerar el rango entero: un día
# completo no crea nada (el generador ya omite las clases existentes).
def dias_incompletos(conteo_clases_por_fecha, conteo_horarios_por_dia,
                     fecha_desde: date, fecha_hasta: date) -> list:
    """Fechas del rango (sin domingos) que NO tienen todas sus clases.

    `conteo_clases_por_fecha` = `{fecha: n}` y `conteo_horarios_por_dia` = `{weekday: n}`.
    Una fecha está incompleta si tiene horarios activos y le faltan clases
    (`clases < horarios`). Un día sin horarios (0) nunca está incompleto.

    **Puro** (recibe los conteos ya resueltos): es el MISMO criterio que el bucle día a día
    que reemplaza, y por eso se puede comparar contra él en un test sin base de datos.
    """
    faltantes = []
    f = fecha_desde
    while f <= fecha_hasta:
        if f.weekday() == 6:                      # Domingo: no hay horarios base.
            f += timedelta(days=1)
            continue
        esperado = conteo_horarios_por_dia.get(f.weekday(), 0)
        if conteo_clases_por_fecha.get(f, 0) < esperado:
            faltantes.append(f)
        f += timedelta(days=1)
    return faltantes


def revisar_rango(db: Session, tenant_id: int, fecha_desde: date,
                  fecha_hasta: date) -> list:
    """Fechas incompletas del rango con DOS consultas agregadas (no 2 por día).

    Devuelve la lista de fechas que `dias_incompletos` marca. Es la lectura que usa el
    arranque para decidir qué generar.
    """
    from app.models.clase import Clase
    from app.models.horario_base import HorarioBase

    filas_clases = (
        db.query(Clase.fecha, func.count(Clase.id))
        .filter(Clase.tenant_id == tenant_id,
                Clase.fecha >= fecha_desde,
                Clase.fecha <= fecha_hasta)
        .group_by(Clase.fecha)
        .all()
    )
    conteo_clases = {fecha: n for fecha, n in filas_clases}

    filas_horarios = (
        db.query(HorarioBase.dia_semana, func.count(HorarioBase.id))
        .filter(HorarioBase.tenant_id == tenant_id,
                HorarioBase.activo == True)        # noqa: E712 (columna booleana)
        .group_by(HorarioBase.dia_semana)
        .all()
    )
    conteo_horarios = {dia: n for dia, n in filas_horarios}

    return dias_incompletos(conteo_clases, conteo_horarios, fecha_desde, fecha_hasta)


def generar_dias_incompletos(db: Session, tenant_id: int, fecha_desde: date,
                             fecha_hasta: date) -> dict:
    """Genera SÓLO los días incompletos del rango y los informa.

    Mismo resultado final que `generar_clases_para_rango` (los días completos no crearían
    nada), pero sin recorrer los días que ya están listos.
    """
    faltantes = revisar_rango(db, tenant_id, fecha_desde, fecha_hasta)
    total_creadas = 0
    total_omitidas = 0
    for f in faltantes:
        resultado = generar_clases_para_fecha(db, tenant_id=tenant_id, fecha=f)
        total_creadas += resultado.get("creadas", 0)
        total_omitidas += resultado.get("omitidas", 0)

    logger.info(
        f"🔄 Días incompletos [{fecha_desde.isoformat()} -> {fecha_hasta.isoformat()}]: "
        f"{len(faltantes)} día(s), {total_creadas} creadas, {total_omitidas} omitidas")

    return {
        "message": f"{total_creadas} clases generadas en {len(faltantes)} día(s) incompleto(s)",
        "creadas": total_creadas,
        "omitidas": total_omitidas,
        "dias_incompletos": [f.isoformat() for f in faltantes],
        "fecha_desde": fecha_desde.isoformat(),
        "fecha_hasta": fecha_hasta.isoformat(),
    }
