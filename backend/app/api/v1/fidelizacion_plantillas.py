"""Router de las plantillas de Fidelización: catálogo, sugerencia, preview y envío.

Cuatro endpoints y UN servicio (`fidelizacion_plantillas`), que es donde viven el copy, los
datos reales del alumno, la sugerencia y el envío. Acá sólo se elige, se valida el ACL/tenant y se
devuelve.

  * `GET  /fidelizacion/plantillas` → lo que el modal puede mostrar (grupos reservados NO viajan).
  * `POST /fidelizacion/sugerir`    → qué plantilla le corresponde al alumno y por qué regla.
  * `POST /fidelizacion/preview`    → el correo EXACTO que se va a mandar, sin mandarlo.
  * `POST /fidelizacion/enviar`     → lo manda y reporta `enviado` / `simulado` / `fallido`.

🔒 ACL: sólo admin del box (`get_current_admin`), igual que el resto de la pantalla de
Fidelización (trae la lista de alumnos en riesgo y sus correos). El `tenant_id` sale SIEMPRE del
token: un alumno de otro box es 404, no 403.

Errores: 422 si el id de plantilla no está en el catálogo (patrón del propio catálogo), 400 si la
plantilla existe pero a ESE alumno no se le puede mandar (ej. renovación sin membresía vigente) y
404 si el alumno no es del box. Un fallo de Gmail NO es un error de la petición: devuelve 200 con
`ok:false` y el detalle (mismo criterio que `notificaciones-enviadas/enviar-manual`).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin
from app.db.database import get_db
from app.models.usuario import Usuario
from app.services import fidelizacion_plantillas as svc

router = APIRouter()


class EnvioPlantilla(BaseModel):
    """Qué plantilla y a qué alumno (el mismo cuerpo para preview y envío)."""

    plantilla: str = Field(
        ..., pattern=svc.PATRON_IDS,
        description="Id de la plantilla del catálogo (ej. 'inactividad_15_30').")
    alumno_id: int = Field(..., gt=0, description="Alumno del box del token.")


class ConsultaAlumno(BaseModel):
    """Sólo el alumno: es lo único que necesita la sugerencia (todavía no hay plantilla elegida)."""

    alumno_id: int = Field(..., gt=0, description="Alumno del box del token.")


def _alumno_del_box(db: Session, current_user: dict, alumno_id: int) -> Usuario:
    """El alumno, siempre DENTRO del tenant del token (otro box es 404, no 403)."""
    alumno = (
        db.query(Usuario)
        .filter(Usuario.id == alumno_id,
                Usuario.tenant_id == current_user["tenant_id"])
        .first()
    )
    if alumno is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {alumno_id} no encontrado en este box",
        )
    return alumno


@router.get("/plantillas")
def listar_plantillas(
    current_user: dict = Depends(get_current_admin),
):
    """Catálogo para el modal: modo de envío vigente + grupos + lista plana.

    Los grupos RESERVADOS (hoy `beneficios`, Fase 2) no se devuelven: el frontend dibuja lo
    que recibe, así que ocultar la opción es una decisión de una sola parte.
    """
    return svc.catalogo()


@router.post("/sugerir")
def sugerir_plantilla(
    datos: ConsultaAlumno,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Qué plantilla le corresponde al alumno según SUS datos reales (no manda ni renderiza nada).

    La sugerencia la define el servicio (`sugerir`): la pantalla no adivina. Devuelve la plantilla,
    la regla que ganó y el motivo; `plantilla:null` cuando hoy no hay una situación que la
    justifique (el alumno que entrenó ayer no necesita que nadie lo vaya a buscar).
    """
    alumno = _alumno_del_box(db, current_user, datos.alumno_id)
    return svc.sugerir(db, alumno)


@router.post("/preview")
def preview_plantilla(
    datos: EnvioPlantilla,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Renderiza el correo con los datos REALES del alumno (no manda nada).

    Misma función que usa el envío: lo que el admin aprueba es lo que sale.
    """
    alumno = _alumno_del_box(db, current_user, datos.alumno_id)
    try:
        return svc.render(db, alumno, datos.plantilla)
    except svc.PlantillaSinDatos as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except svc.PlantillaDesconocida as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.post("/enviar")
def enviar_plantilla(
    datos: EnvioPlantilla,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Envía la plantilla elegida y deja el registro en `notificaciones_enviadas`.

    `ok:false` = Gmail falló (o el modo prueba no mandó): el detalle viene en
    `detalle_error` y el estado NUNCA se infla (`enviado` sólo si salió de verdad).
    """
    alumno = _alumno_del_box(db, current_user, datos.alumno_id)
    try:
        return svc.enviar(db, alumno, datos.plantilla)
    except svc.PlantillaSinDatos as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except svc.PlantillaDesconocida as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
