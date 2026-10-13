"""
Router de los avisos de marketing (el carrusel "Novedades del box" del Inicio).

QUIÉN PUEDE QUÉ
---------------
  * `GET /marketing` (lista con filtro) y TODAS las mutaciones: sólo el ADMIN del
    box (`get_current_admin`, tenant del token). Publicar contenido que ve todo el
    alumnado no puede quedar al alcance de un alumno.
  * `GET /marketing/vigentes`: cualquier usuario autenticado. Es lo que pinta el
    carrusel del Inicio del alumno <768px, así que NO lleva el candado de
    `require_full_access` (un alumno en plan de prueba también entra a su Inicio;
    las tarjetas de producto lo llevan al Bazar, que sí le responde 403).

El tenant SIEMPRE sale del token: el query param no existe (mismo criterio que
`productos.py`). Los avisos de un box no se ven ni se tocan desde otro.
"""
from datetime import date
from typing import List, Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     UploadFile, status)
from sqlalchemy.orm import Session

from app.core.dependencies import (get_current_admin, get_current_user,
                                   require_full_access)
from app.core.imagenes_publicas import guardar_imagen_publica
from app.db.database import get_db
from app.models.aviso_marketing import TIPO_PRODUCTO_BAZAR, AvisoMarketing
from app.schemas.aviso_marketing import (AvisoMarketingActualizar,
                                         AvisoMarketingOut)
from app.services import avisos_marketing as servicio
from app.services import storage

router = APIRouter()


def _aviso_del_box(db: Session, aviso_id: int, tenant_id: int) -> AvisoMarketing:
    """El aviso de ESE box o 404 (nunca se opera sobre el aviso de otro box)."""
    aviso = db.query(AvisoMarketing).filter(
        AvisoMarketing.id == aviso_id,
        AvisoMarketing.tenant_id == tenant_id,
    ).first()
    if not aviso:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aviso con ID {aviso_id} no encontrado",
        )
    return aviso


def _sin_errores(datos: dict) -> None:
    """400 con los errores juntos si el payload no es válido (mismo `validar`)."""
    errores = servicio.validar(datos)
    if errores:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=" ".join(errores))


def _solo_manuales(aviso: AvisoMarketing) -> None:
    """400 si el aviso es de un producto del Bazar: ese lo mantiene el Bazar.

    Su título, su precio y su foto salen del PRODUCTO, así que editarlo a mano
    dejaría el carrusel mostrando algo distinto de lo que hay en la tienda. Sus
    días de anuncio se cambian desde el Bazar (PUT /productos/{id}).
    """
    if aviso.tipo == TIPO_PRODUCTO_BAZAR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("El aviso de un producto del Bazar se administra desde el Bazar: "
                    "edita el producto y sus días de anuncio."))


@router.get("/vigentes", response_model=List[AvisoMarketingOut])
def avisos_vigentes(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Los avisos que el carrusel del Inicio del alumno dibuja HOY, ya ordenados.

    Sin avisos vigentes devuelve `[]` y la sección completa desaparece del Inicio
    (nunca se muestra un carrusel vacío).
    """
    return servicio.vigentes(db, current_user["tenant_id"])


@router.get("", response_model=List[AvisoMarketingOut],
            dependencies=[Depends(require_full_access)])
def listar_avisos(
    filtro: str = Query(servicio.FILTRO_TODOS,
                        description="todos | vigentes | programados | vencidos"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Lista los avisos del box para el panel Marketing. Sólo admin."""
    return servicio.listar(db, current_user["tenant_id"], filtro)


@router.post("", response_model=AvisoMarketingOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_full_access)])
async def crear_aviso(
    tipo: str = Form(..., description="promocion | colaboracion | aviso | evento"),
    titulo: str = Form(...),
    texto: str = Form(...),
    vigente_desde: date = Form(..., description="Primer día de la ventana (Chile)"),
    vigente_hasta: date = Form(..., description="Último día de la ventana (Chile)"),
    nombre_aliado: Optional[str] = Form(None, description="Sólo Colaboración"),
    fecha_evento: Optional[date] = Form(None, description="Sólo Evento"),
    fijado_arriba: bool = Form(False),
    file: Optional[UploadFile] = File(None, description="Flyer opcional"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea un aviso del carrusel (multipart: el flyer viaja en `file`). Sólo admin."""
    # 🔒 SEGURIDAD: tenant_id del token JWT (no hay Form/query que lo pise).
    tenant_id = current_user["tenant_id"]

    datos = {
        "tipo": tipo,
        "titulo": titulo,
        "texto": texto,
        "nombre_aliado": nombre_aliado,
        "fecha_evento": fecha_evento,
        "vigente_desde": vigente_desde,
        "vigente_hasta": vigente_hasta,
        "fijado_arriba": fijado_arriba,
    }
    # Se valida ANTES de subir el archivo: si el aviso no se va a crear, no queda
    # un flyer huérfano en el almacenamiento.
    _sin_errores(datos)

    # Flyer opcional: mismo camino que la foto de un producto del Bazar (valida
    # tipo/tamaño/contenido real y guarda en disco o en R2).
    datos["imagen_url"] = (await guardar_imagen_publica(file)
                           if file and file.filename else None)

    return servicio.crear(db, tenant_id, datos,
                          creado_por=current_user["usuario_id"])


@router.put("/{aviso_id}", response_model=AvisoMarketingOut,
            dependencies=[Depends(require_full_access)])
def actualizar_aviso(
    aviso_id: int,
    aviso_data: AvisoMarketingActualizar,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Edita un aviso del box (reemplaza los campos editables). Sólo admin."""
    # 🔒 SEGURIDAD: tenant_id del token; el aviso tiene que ser del mismo box.
    aviso = _aviso_del_box(db, aviso_id, current_user["tenant_id"])
    _solo_manuales(aviso)
    try:
        return servicio.actualizar(db, aviso, aviso_data.model_dump())
    except ValueError as error:
        # `servicio.validar` devuelve la lista de errores: se responde 400 con
        # ellos juntos (el admin ya los vio en el formulario).
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=" ".join(error.args[0]))


@router.post("/{aviso_id}/imagen", response_model=AvisoMarketingOut,
             dependencies=[Depends(require_full_access)])
async def subir_flyer(
    aviso_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Agrega o REEMPLAZA el flyer de un aviso (multipart). Sólo admin.

    El PUT es JSON (no puede llevar archivo), así que el flyer se sube por acá. El
    archivo VIEJO se borra del almacenamiento (no queda huérfano).
    """
    aviso = _aviso_del_box(db, aviso_id, current_user["tenant_id"])
    _solo_manuales(aviso)

    # Primero se guarda el NUEVO: si el guardado falla (503) el flyer viejo sigue
    # intacto y el aviso no queda sin imagen.
    url_nueva = await guardar_imagen_publica(file)
    url_previa = servicio.url_a_borrar(aviso)

    aviso.imagen_url = url_nueva
    db.commit()
    db.refresh(aviso)

    # Recién ahora se borra el viejo, y es best-effort: nunca rompe la respuesta.
    if url_previa and url_previa != url_nueva:
        storage.borrar_publico(url_previa)

    return servicio.serializar(aviso)


@router.delete("/{aviso_id}/imagen", response_model=AvisoMarketingOut,
               dependencies=[Depends(require_full_access)])
def quitar_flyer(
    aviso_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Quita el flyer de un aviso: la tarjeta vuelve a pintarse con su color. Sólo admin."""
    aviso = _aviso_del_box(db, aviso_id, current_user["tenant_id"])
    _solo_manuales(aviso)
    url_previa = servicio.url_a_borrar(aviso)

    aviso.imagen_url = None
    db.commit()
    db.refresh(aviso)

    if url_previa:
        storage.borrar_publico(url_previa)

    return servicio.serializar(aviso)


@router.delete("/{aviso_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_full_access)])
def eliminar_aviso(
    aviso_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Elimina un aviso del carrusel (y su flyer). Sólo admin."""
    aviso = _aviso_del_box(db, aviso_id, current_user["tenant_id"])
    flyer = servicio.eliminar(db, aviso)

    # Después del commit y best-effort: el aviso ya no está (que es lo que pidió el
    # admin) y lo único que puede quedar es un archivo huérfano.
    if flyer:
        storage.borrar_publico(flyer)

    return None

