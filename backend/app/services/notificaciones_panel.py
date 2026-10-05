"""
Notificaciones del PANEL: la tabla `notificaciones` (la que lee la campana).

Antes de este módulo, cada flujo que quería avisar en el panel insertaba su fila
a mano:

  * aprobación / rechazo de un plan -> api/v1/solicitudes_planes.py
    (tipo 'aprobado' / 'rechazado', destinatario = el alumno);
  * cobertura de emergencia -> core/dependencies.py
    (tipo 'emergencia', destinatarios = los administradores del box).

`notificaciones` NO tiene `tenant_id`: sigue al DESTINATARIO (`alumno_id` es el id de
usuario, sin importar su rol). El aislamiento entre boxes se logra eligiendo bien los
destinatarios — por eso `notificar_admins_del_tenant` filtra por `usuarios.tenant_id`,
igual que el resto del proyecto (ver tests/test_notificaciones_tenant.py).

Dos reglas de este módulo:

  1. BEST-EFFORT: un aviso del panel NUNCA puede tumbar el flujo que lo originó
     (una compra no puede fallar porque no se pudo escribir un aviso). Se captura
     la excepción, se loguea y se sigue — mismo patrón que core/dependencies.py.
  2. `commit=False` deja el aviso en la MISMA transacción que el cambio de
     negocio (patrón de solicitudes_planes.py); `commit=True` (por defecto)
     cierra la transacción del aviso cuando el flujo ya commiteó lo suyo.

Qué NO hace: no manda correos (eso vive en services/email_service.py) y no escribe
en `notificaciones_enviadas` (ese es el log de la pantalla /admin/notificaciones).
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.notificacion import Notificacion
from app.models.usuario import RolUsuario, Usuario

logger = logging.getLogger(__name__)

__all__ = ["notificar_alumno", "notificar_admins_del_tenant", "notificar_usuario"]


def _rollback_si_propio(db: Session, commit: bool) -> None:
    """Deshace sólo si la transacción la cerró este módulo (`commit=True`).

    Con `commit=False` la transacción es del llamador: un rollback acá le
    borraría cambios suyos que todavía no commiteó.
    """
    if not commit:
        return
    try:
        db.rollback()
    except Exception:
        pass


def notificar_usuario(
    db: Session, usuario_id: int, tipo: str, mensaje: str, *, commit: bool = True
) -> Optional[Notificacion]:
    """Crea el aviso de UN usuario cualquiera (alumno, coach o admin).

    Es la primitiva genérica: `alumno_id` en la tabla es "el destinatario".
    Devuelve la `Notificacion` creada, o `None` si no se pudo (best-effort).
    `usuario_id` vacío/None -> `None` sin tocar la BD.
    """
    if not usuario_id:
        return None
    try:
        notificacion = Notificacion(
            alumno_id=usuario_id, tipo=tipo, mensaje=mensaje, leida=False)
        db.add(notificacion)
        if commit:
            db.commit()
        else:
            db.flush()
        return notificacion
    except Exception as e:
        logger.warning(
            f"No se pudo crear la notificación '{tipo}' del usuario "
            f"{usuario_id}: {e}")
        _rollback_si_propio(db, commit)
        return None


def notificar_alumno(
    db: Session, alumno_id: int, tipo: str, mensaje: str, *, commit: bool = True
) -> Optional[Notificacion]:
    """Crea el aviso de UN alumno (`alumno_id` = destinatario). Alias de
    `notificar_usuario` con el nombre del caso más común (Bazar, planes)."""
    return notificar_usuario(db, alumno_id, tipo, mensaje, commit=commit)


def notificar_admins_del_tenant(
    db: Session, tenant_id: int, tipo: str, mensaje: str, *, commit: bool = True
) -> int:
    """Crea el aviso de CADA administrador ACTIVO del box `tenant_id`.

    Devuelve cuántos avisos se crearon (0 si el box no tiene admins activos o si
    algo falló). Un admin de OTRO box nunca recibe nada: el destinatario se elige
    por `usuarios.tenant_id` (la tabla `notificaciones` no tiene `tenant_id`
    propio, así que la frontera del box vive acá).
    """
    if not tenant_id:
        return 0
    try:
        admins = db.query(Usuario).filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.administrador,
            Usuario.estado == "activo",
        ).all()
        for admin in admins:
            db.add(Notificacion(
                alumno_id=admin.id, tipo=tipo, mensaje=mensaje, leida=False))
        if admins:
            if commit:
                db.commit()
            else:
                db.flush()
        return len(admins)
    except Exception as e:
        logger.warning(
            f"No se pudo notificar a los admins del box {tenant_id}: {e}")
        _rollback_si_propio(db, commit)
        return 0
