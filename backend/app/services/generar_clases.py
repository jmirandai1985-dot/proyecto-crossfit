"""
Servicio compartido para generación de clases desde horarios_base
Usado por: endpoint HTTP, scheduler diario, y respaldo automático
"""
import logging
from datetime import date, timedelta
from sqlalchemy.orm import Session

logger = logging.getLogger("uvicorn.generar_clases")


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
    """
    from app.models.horario_base import HorarioBase
    from app.models.clase import Clase

    dia_semana = fecha.weekday()  # 0=Lun ... 6=Dom
    if dia_semana == 6:
        return {"message": "Domingo: no hay horarios base programados", "creadas": 0, "omitidas": 0, "total_horarios": 0}

    horarios = db.query(HorarioBase).filter(
        HorarioBase.tenant_id == tenant_id,
        HorarioBase.dia_semana == dia_semana,
        HorarioBase.activo == True
    ).all()

    if not horarios:
        return {"message": f"No hay horarios base activos para el día {dia_semana}", "creadas": 0, "omitidas": 0, "total_horarios": 0}

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

        clase = Clase(
            tenant_id=tenant_id,
            horario_base_id=h.id,
            disciplina_id=h.disciplina_id,
            fecha=fecha,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            cupo_maximo=h.cupo_maximo,
            asistentes_confirmados=0,
            cancelada=False,
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
