"""
Dependencias de FastAPI para autenticación y autorización
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db
from app.core.security import verify_token
from app.models.coach_disciplina import CoachDisciplina
from app.models.disciplina import Disciplina
from app.models.cobertura_emergencia import CoberturaEmergencia
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan

# Esquema de seguridad HTTP Bearer
# auto_error=False: no lanza 403 automáticamente si falta el header;
# get_current_user emite 401 con WWW-Authenticate (semántica HTTP correcta).
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials=Depends(security),
    db: Session = Depends(get_db)
):
    """
    Obtiene el usuario actual desde el JWT token.

    Args:
        credentials: Credenciales HTTP Bearer (token JWT)
        db: Sesión de base de datos

    Returns:
        Diccionario con datos del usuario

    Raises:
        HTTPException 401: Si el token es inválido, expirado o no se envió
        HTTPException 404: Si el usuario no existe en BD
    """
    token = credentials.credentials if credentials else None

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado: se requiere token Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verificar token
    payload = verify_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    usuario_id = payload.get("usuario_id")
    tenant_id = payload.get("tenant_id")

    if not usuario_id or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token incompleto",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Obtener usuario de BD
    query = text("""
        SELECT id, tenant_id, nombre, correo, rol, activo
        FROM usuarios
        WHERE id = :usuario_id AND tenant_id = :tenant_id AND activo = true
    """)

    usuario = db.execute(
        query,
        {"usuario_id": usuario_id, "tenant_id": tenant_id}
    ).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado o inactivo"
        )

    return {
        "usuario_id": usuario.id,
        "tenant_id": usuario.tenant_id,
        "nombre": usuario.nombre,
        "correo": usuario.correo,
        "rol": usuario.rol,
        "activo": usuario.activo
    }


async def get_current_admin(
    current_user: dict = Depends(get_current_user)
):
    """
    Verifica que el usuario actual sea administrador.

    Args:
        current_user: Usuario actual obtenido de get_current_user

    Returns:
        Diccionario con datos del usuario si es admin

    Raises:
        HTTPException 403: Si el usuario no es administrador
    """
    if current_user.get("rol") not in ("admin", "administrador"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador"
        )

    return current_user


def verificar_coach_disciplina(
    coach_id: int,
    disciplina_id: int,
    db: Session,
    modo_emergencia: bool = False,
    clase_id: int = None,
    accion: str = "operacion",
    tenant_id: int = None
):
    """
    Verifica que un coach pertenezca a la disciplina especificada.
    Los admins tienen acceso a cualquier disciplina.

    Si modo_emergencia=True y el coach NO pertenece a la disciplina:
    - Registra auditoria en CoberturaEmergencia
    - PERMITE la operacion (no lanza 403)
    - Esto es para cobertura de emergencia: un coach cubriendo una clase de otra disciplina

    Args:
        coach_id: ID del coach/usuario
        disciplina_id: ID de la disciplina
        db: Sesion de base de datos
        modo_emergencia: Si es True, permite operar en disciplinas no asignadas (con auditoria)
        clase_id: ID de la clase (para el registro de auditoria)
        accion: Tipo de accion (asignar_wod, marcar_asistencia, crear_wod, editar_wod)
        tenant_id: ID del tenant (para el registro de auditoria)

    Raises:
        HTTPException 403: Si el usuario no pertenece a la disciplina Y no esta en modo emergencia
    """
    # Verificar si es admin - los admins pueden operar en cualquier disciplina
    from sqlalchemy import text
    user = db.execute(
        text("SELECT rol FROM usuarios WHERE id = :uid"),
        {"uid": coach_id}
    ).first()

    if user and user.rol in ('admin', 'administrador'):
        return  # Admin tiene acceso total

    # Verificar relacion coach-disciplina
    relacion = db.query(CoachDisciplina).filter(
        CoachDisciplina.coach_id == coach_id,
        CoachDisciplina.disciplina_id == disciplina_id,
        CoachDisciplina.activo == True
    ).first()

    if not relacion:
        if modo_emergencia and clase_id and tenant_id:
            # Cobertura de emergencia: registrar auditoria y permitir
            from sqlalchemy import text as sa_text
            db.execute(
                sa_text("""
                    INSERT INTO cobertura_emergencia 
                    (tenant_id, usuario_id, coach_id, clase_id, disciplina_id, accion)
                    VALUES (:tid, :uid, :cid, :clid, :did, :acc)
                """),
                {"tid": tenant_id, "uid": coach_id, "cid": coach_id,
                 "clid": clase_id, "did": disciplina_id, "acc": accion}
            )
            db.flush()
            return  # Permitir la operacion bajo cobertura de emergencia
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"El coach (id={coach_id}) no esta asignado a la disciplina (id={disciplina_id}). No puede operar sobre clases de otra disciplina."
            )


async def get_current_coach(
    current_user: dict = Depends(get_current_user)
):
    """
    Verifica que el usuario actual sea coach o administrador.

    Args:
        current_user: Usuario actual obtenido de get_current_user

    Returns:
        Diccionario con datos del usuario si es coach o admin

    Raises:
        HTTPException 403: Si el usuario no es coach ni admin
    """
    if current_user.get("rol") not in ["coach", "admin", "administrador"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de coach o administrador"
        )

    return current_user


# ── Acceso limitado: alumnos con plan de prueba (FIX 1, Fase alumno nuevo) ──
def es_usuario_prueba(db: Session, usuario_id: int) -> bool:
    """True si el usuario tiene una suscripción ACTIVA del plan 'Prueba'.

    Es el mismo criterio que usa el frontend (GET /alumnos/me/es-prueba) para
    poder mantener la consistencia UI/backend.
    """
    sus = db.query(Suscripcion).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.usuario_id == usuario_id,
        Suscripcion.estado == "activo",
        Plan.nombre == "Prueba",
    ).first()
    return sus is not None


async def require_full_access(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bloquea a alumnos en modo 'plan de prueba' (acceso limitado).

    El alumno de prueba solo puede usar Clases, Planes y Reservas. Cualquier
    sección de pago (Performance Hub/RMs, Bazar, Evolución, catálogo de
    movimientos) devuelve 403 hasta que el admin apruebe su plan pago.
    Staff (coach/admin) siempre pasa. Se aplica a nivel de router.
    """
    rol = current_user.get("rol")
    if rol in ("coach", "admin", "administrador"):
        return current_user
    if es_usuario_prueba(db, current_user.get("usuario_id")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Acceso limitado: tu plan de prueba solo incluye Clases, "
                "Planes y Reservas. Elige un plan y espera la aprobación "
                "para desbloquear esta sección."
            ),
        )
    return current_user
