"""Acciones del coach que no pertenecen a Fidelización (Parte H).

`POST /invitaciones-externas` reemplaza la navegación vieja del botón "✉️ Invitar" (que iba
a `/coach/alumnos-prueba`, el panel del ADMIN para reenviar correo a alumnos YA registrados):
acá el coach invita a una persona NUEVA con un formulario libre (nombre + correo) y se manda
un correo genérico con el link a la landing de registro.

NO crea usuario ni valida que el correo no exista: es sólo una invitación por correo. Sí avisa
`ya_es_alumno` si el correo ya coincide con un usuario del box, sin bloquear el envío.
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_coach
from app.core.rate_limit import limiter, LIMIT_REGISTRO
from app.db.database import get_db
from app.models.usuario import Usuario
from app.services import email_service

router = APIRouter()


class InvitacionExterna(BaseModel):
    """Nombre y correo libre de la persona a invitar (no es un usuario todavía)."""

    nombre: str = Field(..., min_length=1, max_length=200, description="Nombre de la persona")
    correo: EmailStr = Field(..., max_length=255, description="Correo al que mandar la invitación")

    model_config = ConfigDict(extra="forbid")


@router.post("/invitaciones-externas")
@limiter.limit(LIMIT_REGISTRO)
def invitar_externo(
    request: Request,
    datos: InvitacionExterna,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Manda la invitación genérica a una persona nueva (coach_id sale del token).

    Rate limit = `LIMIT_REGISTRO` (el mismo anti-spam que el registro público): un coach con el
    token filtrado no puede barrer el formulario. Un fallo de Gmail no es un 4xx: se informa
    `exito:false` con el detalle, igual que el resto de los envíos manuales.
    """
    tenant_id = current_user["tenant_id"]
    # El nombre del coach ya viene en el dict de `get_current_user` (una sola consulta por
    # request); no hace falta una segunda búsqueda.
    nombre_coach = current_user.get("nombre") or "Tu coach"

    correo = str(datos.correo).strip().lower()
    ya_es_alumno = db.query(Usuario).filter(
        Usuario.correo == correo,
        Usuario.tenant_id == tenant_id,
    ).first() is not None

    ok = email_service.send_invitacion_externa(
        datos.nombre.strip(), correo, nombre_coach, tenant_id=tenant_id)

    modo = email_service.modo_envio()
    estado = ("fallido" if not ok else
              (email_service.ESTADO_SIMULADO
               if modo == email_service.MODO_NOOP else "enviado"))
    return {
        "exito": ok,
        "estado": estado,
        "ya_es_alumno": ya_es_alumno,
        "detalle_error": None if ok else (email_service.ULTIMO_ERROR_SMTP
                                          or "No se pudo enviar el correo via Gmail SMTP."),
    }
