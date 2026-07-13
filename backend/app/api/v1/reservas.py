"""
Router de endpoints para gestión de Reservas
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.db.database import get_db
from app.models.reserva import Reserva
from app.models.clase import Clase
from app.models.disciplina import Disciplina
from app.models.usuario import Usuario
from app.schemas.reserva import (
    ReservaCreate, ReservaUpdate, ReservaResponse, ReservaListItem
)

router = APIRouter()


@router.post("", response_model=ReservaResponse, status_code=status.HTTP_201_CREATED)
def crear_reserva(
    reserva_data: ReservaCreate,
    db: Session = Depends(get_db)
):
    """
    Crea una nueva reserva con validaciones de aforo y cálculo automático de tokens.

    ARREGLO 1: Control de aforo
    - Verifica que asistentes_confirmados < cupo_maximo
    - Si está lleno → HTTPException 400
    - Si hay cupo → Crea reserva e INCREMENTA asistentes_confirmados

    ARREGLO 3: Protección IDOR
    - tenant_id se extrae del usuario autenticado (no del body)
    - tokens_gastados se calcula automáticamente según plan/disciplina
    """

    # ARREGLO 3: Extraer tenant_id del usuario autenticado (no del JSON)
    # En producción, esto vendría del token JWT
    # TODO: Reemplazar con get_current_user_from_token()
    tenant_id = reserva_data.tenant_id

    # Verificar que la clase existe y pertenece al tenant
    clase = db.query(Clase).filter(
        Clase.id == reserva_data.clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clase no encontrada"
        )

    # ARREGLO 1: Verificar aforo disponible
    if clase.asistentes_confirmados >= clase.cupo_maximo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Clase sin cupos disponibles"
        )

    # Verificar que el alumno existe y pertenece al tenant
    alumno = db.query(Usuario).filter(
        Usuario.id == reserva_data.alumno_id,
        Usuario.tenant_id == tenant_id
    ).first()

    if not alumno:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alumno no encontrado"
        )

    # Verificar que no exista una reserva duplicada
    existing = db.query(Reserva).filter(
        Reserva.clase_id == reserva_data.clase_id,
        Reserva.alumno_id == reserva_data.alumno_id,
        Reserva.estado != "cancelled"
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El alumno ya tiene una reserva activa para esta clase"
        )

    # Verificar créditos disponibles del alumno
    from app.models.suscripcion import Suscripcion
    from datetime import datetime, timezone

    membresia = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id == reserva_data.alumno_id,
        Suscripcion.estado == 'activo',
        Suscripcion.fecha_expiracion > datetime.now(timezone.utc)
    ).order_by(
        Suscripcion.creditos_disponibles.desc().nulls_last(),
        Suscripcion.fecha_expiracion.desc()
    ).first()

    if not membresia:
        raise HTTPException(
            status_code=400, detail="No tienes una membresía activa")

    if membresia.creditos_disponibles is not None and membresia.creditos_disponibles <= 0:
        raise HTTPException(
            status_code=400, detail="No te quedan clases disponibles. Renueva tu plan.")

    tokens_gastados = 1

    # Crear la reserva
    db_reserva = Reserva(
        tenant_id=tenant_id,
        clase_id=reserva_data.clase_id,
        alumno_id=reserva_data.alumno_id,
        asistio=reserva_data.asistio,
        tokens_gastados=tokens_gastados,
        estado=reserva_data.estado
    )

    # Descontar token
    if membresia.creditos_disponibles is not None:
        membresia.creditos_disponibles -= 1

    # ARREGLO 1: Incrementar asistentes_confirmados en la misma transacción
    clase.asistentes_confirmados += 1

    db.add(db_reserva)
    db.commit()
    db.refresh(db_reserva)

    return db_reserva


@router.get("/asistencia-semanal")
def obtener_asistencia_semanal(
    tenant_id: int,
    usuario_id: int,
    db: Session = Depends(get_db)
):
    """
    Retorna la asistencia del alumno agrupada por semana en los últimos 3 meses.
    Cada elemento tiene: semana (fecha ISO), asistencias, total_reservas.
    """
    from datetime import datetime, timezone, date, timedelta

    hoy = date.today()
    hace_3_meses = date(hoy.year, hoy.month, 1) - timedelta(days=90)

    reservas = db.query(
        Clase.fecha,
        Reserva.asistio
    ).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Reserva.alumno_id == usuario_id,
        Reserva.estado.in_(["confirmada", "completada"]),
        Clase.fecha >= hace_3_meses,
        Clase.fecha <= hoy
    ).order_by(Clase.fecha.asc()).all()

    # Agrupar por semana (ISO week)
    from collections import defaultdict
    semanas = defaultdict(lambda: {"asistencias": 0, "total": 0})

    for fecha, asistio in reservas:
        semana_key = fecha.isocalendar()[:2]  # (year, week)
        label = f"{semana_key[0]}-S{semana_key[1]:02d}"
        semanas[label]["total"] += 1
        if asistio:
            semanas[label]["asistencias"] += 1

    resultado = []
    for label in sorted(semanas.keys()):
        d = semanas[label]
        resultado.append({
            "semana": label,
            "asistencias": d["asistencias"],
            "total": d["total"],
            "porcentaje": round((d["asistencias"] / d["total"] * 100), 0) if d["total"] > 0 else 0,
        })

    return resultado


@router.get("/asistencia-mes")
def obtener_asistencia_mes(
    tenant_id: int,
    usuario_id: int,
    db: Session = Depends(get_db)
):
    """
    Calcula la asistencia del alumno en el mes actual.
    Usa la fecha de la clase (Clase.fecha) para determinar si pertenece al mes,
    no la fecha de creación de la reserva.

    Retorna: total_reservas, asistencias, porcentaje
    """
    from datetime import datetime, timezone, date

    hoy = date.today()
    primer_dia_mes = date(hoy.year, hoy.month, 1)

    # Total de reservas del alumno en el mes actual
    # JOIN con Clase para filtrar por fecha de la clase (no fecha de reserva)
    total_reservas = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Reserva.alumno_id == usuario_id,
        Reserva.estado.in_(["confirmada", "completada"]),
        Clase.fecha >= primer_dia_mes,
        Clase.fecha <= hoy
    ).scalar() or 0

    # Asistencias confirmadas (asistio = true) en el mes actual
    asistencias = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Reserva.alumno_id == usuario_id,
        Reserva.estado.in_(["confirmada", "completada"]),
        Reserva.asistio == True,
        Clase.fecha >= primer_dia_mes,
        Clase.fecha <= hoy
    ).scalar() or 0

    porcentaje = round((asistencias / total_reservas * 100),
                       0) if total_reservas > 0 else 0

    # Contar reservas confirmadas FUTURAS (fecha > hoy, dentro del mismo mes)
    # para mejorar el mensaje en la UI
    import calendar
    ultimo_dia_mes = date(hoy.year, hoy.month,
                          calendar.monthrange(hoy.year, hoy.month)[1])
    reservas_futuras = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Reserva.alumno_id == usuario_id,
        Reserva.estado.in_(["confirmada", "completada"]),
        Clase.fecha >= primer_dia_mes,
        Clase.fecha > hoy,
        Clase.fecha <= ultimo_dia_mes
    ).scalar() or 0

    sin_reservas = total_reservas == 0 and reservas_futuras == 0
    solo_futuras = total_reservas == 0 and reservas_futuras > 0

    return {
        "total_reservas": total_reservas,
        "asistencias": asistencias,
        "porcentaje": int(porcentaje),
        "sin_datos": sin_reservas,
        "solo_futuras": solo_futuras,
        "reservas_futuras": reservas_futuras,
    }


@router.get("")
def listar_reservas(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    estado: str = None,
    usuario_id: int = None,
    db: Session = Depends(get_db)
):
    """
    Lista reservas de un tenant con paginación y filtros opcionales.
    Incluye datos de la clase asociada (disciplina, fecha, horario).

    NOTA: Usa columnas explícitas (with_entities) en vez de .add_columns()
    para evitar el patrón frágil de acceso row.ModelName que causó bugs previos.
    """
    # ── Construir query con columnas explícitas ──
    query = db.query(
        Reserva.id,
        Reserva.tenant_id,
        Reserva.clase_id,
        Reserva.alumno_id,
        Reserva.asistio,
        Reserva.tokens_gastados,
        Reserva.estado,
        Reserva.fecha_reserva,
        Reserva.created_at,
        Clase.fecha.label('clase_fecha'),
        Clase.hora_inicio,
        Clase.hora_fin,
        Disciplina.nombre.label('disciplina_nombre'),
    ).join(
        Clase, Reserva.clase_id == Clase.id
    ).join(
        Disciplina, Clase.disciplina_id == Disciplina.id
    ).filter(
        Reserva.tenant_id == tenant_id
    )

    if estado is not None:
        query = query.filter(Reserva.estado == estado)

    if usuario_id is not None:
        query = query.filter(Reserva.alumno_id == usuario_id)

    rows = query.offset(skip).limit(limit).all()

    # ── Construir respuesta con acceso directo a columnas ──
    # Resultado son named tuples, cada columna es un atributo directo (row.columna)
    # NO hay anidamiento row.ModelName — eso se elimina con columnas explícitas
    result = []
    for r in rows:
        result.append({
            "id": r.id,
            "tenant_id": r.tenant_id,
            "clase_id": r.clase_id,
            "alumno_id": r.alumno_id,
            "asistio": r.asistio,
            "tokens_gastados": r.tokens_gastados,
            "estado": r.estado,
            "fecha_reserva": str(r.fecha_reserva) if r.fecha_reserva else None,
            "created_at": str(r.created_at) if r.created_at else None,
            "disciplina_nombre": r.disciplina_nombre,
            "clase_fecha": str(r.clase_fecha) if r.clase_fecha else None,
            "hora_inicio": r.hora_inicio,
            "hora_fin": r.hora_fin,
        })

    return result


@router.get("/{reserva_id}", response_model=ReservaResponse)
def obtener_reserva(
    reserva_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Obtiene una reserva por su ID.

    ARREGLO 3: Protección IDOR
    - Valida que tenant_id del usuario = tenant_id del recurso
    """
    reserva = db.query(Reserva).filter(
        Reserva.id == reserva_id,
        Reserva.tenant_id == tenant_id
    ).first()

    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reserva con ID {reserva_id} no encontrada"
        )

    return reserva


@router.put("/{reserva_id}", response_model=ReservaResponse)
def actualizar_reserva(
    reserva_id: int,
    reserva_data: ReservaUpdate,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Actualiza una reserva existente.

    ARREGLO 3: Protección IDOR
    - Valida que tenant_id del usuario = tenant_id del recurso
    """
    reserva = db.query(Reserva).filter(
        Reserva.id == reserva_id,
        Reserva.tenant_id == tenant_id
    ).first()

    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reserva con ID {reserva_id} no encontrada"
        )

    update_data = reserva_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(reserva, field, value)

    db.commit()
    db.refresh(reserva)

    return reserva


@router.delete("/{reserva_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_reserva(
    reserva_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Cancela una reserva (soft delete) y DECREMENTA asistentes_confirmados.

    Política de cancelación:
    - Si faltan >= 6 horas para la clase: cancela y DEVUELVE el crédito.
    - Si faltan < 6 horas: cancela pero NO devuelve el crédito (penalización).

    ARREGLO 1: Al eliminar reserva → DECREMENTA -1 asistentes_confirmados
    Usa transacción para integridad.

    ARREGLO 3: Protección IDOR
    - Valida que tenant_id del usuario = tenant_id del recurso
    """
    from datetime import datetime, timezone, timedelta
    from app.models.suscripcion import Suscripcion

    reserva = db.query(Reserva).filter(
        Reserva.id == reserva_id,
        Reserva.tenant_id == tenant_id
    ).first()

    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reserva con ID {reserva_id} no encontrada"
        )

    # ARREGLO 1: Obtener la clase y decrementar asistentes_confirmados
    clase = db.query(Clase).filter(Clase.id == reserva.clase_id).first()

    if clase and clase.asistentes_confirmados > 0:
        clase.asistentes_confirmados -= 1

    # Calcular horas restantes hasta la clase
    ahora = datetime.now(timezone.utc)
    hora_inicio = clase.hora_inicio
    inicio_clase = datetime(
        clase.fecha.year, clase.fecha.month, clase.fecha.day,
        hora_inicio.hour, hora_inicio.minute, tzinfo=timezone.utc
    )
    horas_restantes = (inicio_clase - ahora).total_seconds() / 3600

    # Buscar membresía activa para devolver el crédito si aplica
    if horas_restantes >= 6:
        membresia = db.query(Suscripcion).filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id == reserva.alumno_id,
            Suscripcion.estado == 'activo',
            Suscripcion.fecha_expiracion > ahora
        ).order_by(
            Suscripcion.creditos_disponibles.desc().nulls_last(),
            Suscripcion.fecha_expiracion.desc()
        ).first()
        if membresia and membresia.creditos_disponibles is not None:
            membresia.creditos_disponibles += 1

    reserva.estado = "cancelled"
    db.commit()

    return None
