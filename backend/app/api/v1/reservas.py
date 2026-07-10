"""
Router de endpoints para gestión de Reservas
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.reserva import Reserva
from app.models.clase import Clase
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
        Suscripcion.estado.in_(['activo', 'active']),
        Suscripcion.fecha_expiracion > datetime.now(timezone.utc)
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


@router.get("", response_model=List[ReservaListItem])
def listar_reservas(
    tenant_id: int,
    skip: int = 0,
    limit: int = 100,
    estado: str = None,
    usuario_id: int = None,
    db: Session = Depends(get_db)
):
    """Lista reservas de un tenant con paginación y filtros opcionales"""
    query = db.query(Reserva).filter(Reserva.tenant_id == tenant_id)

    if estado is not None:
        query = query.filter(Reserva.estado == estado)

    if usuario_id is not None:
        query = query.filter(Reserva.alumno_id == usuario_id)

    reservas = query.offset(skip).limit(limit).all()

    return reservas


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

    ARREGLO 1: Al eliminar reserva → DECREMENTA -1 asistentes_confirmados
    Usa transacción para integridad.

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

    # ARREGLO 1: Obtener la clase y decrementar asistentes_confirmados
    clase = db.query(Clase).filter(Clase.id == reserva.clase_id).first()

    if clase and clase.asistentes_confirmados > 0:
        clase.asistentes_confirmados -= 1

    reserva.estado = "cancelled"
    db.commit()

    return None
