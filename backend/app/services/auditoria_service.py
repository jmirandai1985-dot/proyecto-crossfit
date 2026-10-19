"""
Servicio de Auditoría
Proporciona funciones para registrar acciones en el sistema
"""
from sqlalchemy.orm import Session
from typing import Optional, Any

from app.models.auditoria import Auditoria


def registrar_auditoria(
    db: Session,
    tenant_id: int,
    usuario_id: Optional[int],
    accion: str,
    entidad: str,
    entidad_id: Optional[int] = None,
    detalle: Optional[dict] = None
) -> Auditoria:
    """
    Registra una acción en la auditoría.

    Args:
        db: Sesión de base de datos
        tenant_id: ID del tenant
        usuario_id: ID del usuario que realizó la acción
        accion: Tipo de acción (CREATE, UPDATE, DELETE, LOGIN)
        entidad: Nombre de la entidad afectada (ej: reserva, clase, pedido)
        entidad_id: ID de la entidad afectada (opcional)
        detalle: Detalles adicionales en formato dict (opcional)

    Returns:
        Registro de auditoría creado
    """
    registro = Auditoria(
        tenant_id=tenant_id,
        usuario_id=usuario_id,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        detalle=detalle
    )

    db.add(registro)
    db.commit()
    db.refresh(registro)

    return registro
