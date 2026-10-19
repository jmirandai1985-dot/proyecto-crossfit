"""
Router del Sistema de Referidos — Fase 3a.

QUÉ RESUELVE
-----------
  * `GET  /api/v1/referidos/mi-codigo`       → el alumno ve SU código (y sólo el suyo).
  * `POST /api/v1/referidos/validar-codigo`  → el invitado aplica el código de otro alumno.
  * `GET  /api/v1/referidos/configuracion`   → el admin lee los porcentajes de su box.
  * `PUT  /api/v1/referidos/configuracion`   → el admin crea/actualiza esos porcentajes.

DECISIONES DE DISEÑO
--------------------
1. **El invitado ya está registrado.** `validar-codigo` exige token y usa
   SIEMPRE el `usuario_id` del JWT: no hay `usuario_id` en el body (el esquema
   lo prohíbe con `extra="forbid"`). Aceptar un id ajeno permitiría aplicar el
   código a otra persona y consumirle su única oportunidad de referido. El
   formulario de auto-registro puede llamar a este endpoint después de crear la
   cuenta; para "validar antes de crear la cuenta" no se expone nada en esta
   fase (sería un endpoint público y enumerable).
2. **Sólo alumnos participan.** `mi-codigo` y `validar-codigo` responden 403 a
   admin/coach: el programa es alumno → alumno y sólo los alumnos reciben
   código (`asignar_codigo_referido` ni siquiera crea filas para staff).
3. **La configuración es del ADMIN.** Leerla también: son porcentajes de
   negocio del box, no un dato del alumno. El `tenant_id` sale del token.
4. **Aplicar un código NO cobra ni descuenta nada.** Sólo crea la fila
   `referidos_aplicados` en estado `pendiente` con `fecha_ingreso_codigo`. El
   cálculo y la aplicación de descuentos son la Fase 3b.
5. **Doble referencia:** un alumno puede ser invitado UNA sola vez. Se mira
   cualquier fila previa (aunque siga `pendiente`). Además, la fila del usuario
   se bloquea con `FOR UPDATE` durante la validación para que dos requests
   simultáneos del mismo invitado no creen dos filas.
6. **Tenant:** el código se busca unido al dueño y filtrando por el box del
   token. El código de otro box se comporta como inexistente (no se filtra su
   existencia entre boxes).
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin, get_current_user
from app.db.database import get_db
from app.models.referidos import (CodigoReferido, ConfiguracionReferidos,
                                  EstadoReferido, ReferidoAplicado)
from app.models.usuario import Usuario
from app.schemas.referidos import (ConfiguracionReferidosOut,
                                   ConfiguracionReferidosUpdate, MiCodigoOut,
                                   ValidarCodigoOut, ValidarCodigoRequest)
from app.services import referidos_service as svc

router = APIRouter()


def _exigir_alumno(current_user: dict) -> None:
    """403 si el token no es de un alumno (admin/coach no participan)."""
    if current_user.get("rol") != "alumno":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sólo los alumnos tienen código de referido")


def _codigo_propio(db: Session, usuario_id: int) -> CodigoReferido:
    """El código del usuario del token, o 404 con el mensaje para el alumno."""
    codigo = db.query(CodigoReferido).filter(
        CodigoReferido.usuario_id == usuario_id
    ).first()
    if codigo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=("No tienes un código de referido asignado. "
                    "Contacta al administrador de tu box."))
    return codigo


@router.get("/mi-codigo", response_model=MiCodigoOut)
def mi_codigo(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """El código propio del alumno autenticado (sale del token, no de un id).

    Un alumno histórico sin backfill no tiene fila: 404 con un mensaje claro en
    vez de un 500 o de un código inventado.
    """
    _exigir_alumno(current_user)
    return svc.datos_mi_codigo(
        _codigo_propio(db, current_user["usuario_id"]))


@router.post("/validar-codigo", response_model=ValidarCodigoOut)
def validar_codigo(
    datos: ValidarCodigoRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Valida el código de otro alumno y registra la intención (`pendiente`).

    No aplica descuentos ni modifica montos: sólo inserta en
    `referidos_aplicados`. Un código inválido responde 400 con el motivo exacto
    (inexistente / inactivo / propio / ya referido).
    """
    _exigir_alumno(current_user)

    usuario_id = current_user["usuario_id"]
    tenant_id = current_user["tenant_id"]

    # Bloquea la fila del invitado hasta el commit: dos validaciones simultáneas
    # del MISMO alumno se serializan y la segunda ve la fila de la primera.
    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id,
        Usuario.tenant_id == tenant_id,
    ).with_for_update().first()
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en este box")

    codigo = svc.normalizar_codigo_ingresado(datos.codigo)
    codigo_referido = db.query(CodigoReferido).join(
        Usuario, Usuario.id == CodigoReferido.usuario_id
    ).filter(
        CodigoReferido.codigo == codigo,
        Usuario.tenant_id == tenant_id,
    ).first()

    ya_referido = db.query(ReferidoAplicado.id).filter(
        ReferidoAplicado.usuario_invitado_id == usuario_id
    ).first() is not None

    motivo = svc.motivo_codigo_invalido(
        existe=codigo_referido is not None,
        activo=bool(codigo_referido.activo) if codigo_referido else False,
        es_propio=(codigo_referido is not None
                   and codigo_referido.usuario_id == usuario_id),
        ya_referido=ya_referido,
    )
    if motivo is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=motivo)

    referido = ReferidoAplicado(
        codigo_referido_id=codigo_referido.id,
        usuario_invitador_id=codigo_referido.usuario_id,
        usuario_invitado_id=usuario_id,
        fecha_ingreso_codigo=datetime.now(timezone.utc),
        estado=EstadoReferido.pendiente,
    )
    db.add(referido)
    db.commit()
    db.refresh(referido)

    return svc.datos_referido_aplicado(referido, codigo)


@router.get("/configuracion", response_model=ConfiguracionReferidosOut)
def obtener_configuracion(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """La configuración del box del token, o los defaults sin crear la fila."""
    config = db.query(ConfiguracionReferidos).filter(
        ConfiguracionReferidos.tenant_id == current_user["tenant_id"]
    ).first()
    return svc.datos_configuracion(config)


@router.put("/configuracion", response_model=ConfiguracionReferidosOut)
def actualizar_configuracion(
    datos: ConfiguracionReferidosUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea o actualiza (upsert) la fila de configuración del box. Sólo admin.

    El rango 0-100 lo valida Pydantic (`422` antes de la BD) y el CHECK de la
    tabla queda como última defensa.
    """
    tenant_id = current_user["tenant_id"]
    config = db.query(ConfiguracionReferidos).filter(
        ConfiguracionReferidos.tenant_id == tenant_id
    ).first()

    if config is None:
        config = ConfiguracionReferidos(tenant_id=tenant_id)
        db.add(config)

    config.porcentaje_descuento_invitado = Decimal(
        datos.porcentaje_descuento_invitado)
    config.porcentaje_descuento_invitador = Decimal(
        datos.porcentaje_descuento_invitador)
    config.activo = bool(datos.activo)

    db.commit()
    db.refresh(config)

    return svc.datos_configuracion(config)
