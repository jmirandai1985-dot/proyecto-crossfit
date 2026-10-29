"""
Router del Sistema de Referidos — Fase 3a.

QUÉ RESUELVE
-----------
  * `GET  /api/v1/referidos/mi-codigo`       → el alumno ve SU código (y sólo el suyo).
  * `POST /api/v1/referidos/validar-codigo`  → el invitado aplica el código de otro alumno.
  * `GET  /api/v1/referidos/configuracion`   → el admin lee los porcentajes de su box.
  * `PUT  /api/v1/referidos/configuracion`   → el admin crea/actualiza esos porcentajes.
  * `GET  /api/v1/referidos/mi-invitacion`   → la invitación que trajo al alumno (prellenado).
  * `POST /api/v1/referidos/invitaciones`    → el alumno invita a un amigo por correo.

Fase 5 agrega las PROMOCIONES POR VOLUMEN (sólo admin):
  * `GET/POST /promociones` y `PUT/DELETE /promociones/{id}` → CRUD del premio.
  * `GET /promociones-detectadas` → umbrales alcanzados, con el premio congelado.
  * `POST /promociones-detectadas/{id}/confirmar` → APLICA el premio.
  * `POST /promociones-detectadas/{id}/rechazar` → no aplica nada.

El `tenant_id` sale SIEMPRE del token y una promoción/detección de otro box se
comporta como inexistente (404), igual que el resto de los recursos del panel.

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
7. **Invitaciones alumno → alumno (054):** el link `/landing?inv=<token>` sólo
   IDENTIFICA la invitación: no autentica, no aplica el código y no crea el
   referido. El invitado se registra normal, la invitación queda ligada a su
   cuenta y `mi-invitacion` devuelve el código para PRELLENAR el campo; aplicar
   sigue siendo un acto explícito (`validar-codigo`).
8. **El correo no deja filas fantasma:** si el envío falla se borra la
   invitación y se responde 502. Si quedara, el anti-abuso de 7 días impediría
   reenviar un correo que el amigo nunca recibió.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin, get_current_user
from app.db.database import get_db
from app.models.aviso_marketing import TIPO_PROMOCION, AvisoMarketing
from app.models.referidos import (CodigoReferido, ConfiguracionReferidos,
                                  EstadoInvitacion, EstadoPromocionDetectada,
                                  EstadoReferido, Invitacion, MotorPremios,
                                  OrigenInvitacion, PremioTramoCiclo,
                                  PromocionReferidos,
                                  PromocionReferidosDetectada,
                                  ReferidoAplicado, TarjetaReferidos,
                                  TramoReferido)
from app.models.usuario import Usuario
from app.schemas.aviso_marketing import AvisoMarketingOut
from app.schemas.referidos import (ConfiguracionReferidosOut,
                                   ConfiguracionReferidosUpdate,
                                   ConfirmarPremioTramoOut,
                                   ConfirmarPromocionOut, EscaleraTramosOut,
                                   InvitarAlumnoRequest,
                                   InvitacionEnviadaOut, MiCodigoOut,
                                   MiInvitacionOut, MiProgresoOut,
                                   MotorPremiosUpdate, PremioTramoOut,
                                   PromocionDetectadaOut,
                                   PromocionReferidosCreate,
                                   PromocionReferidosOut,
                                   PromocionReferidosUpdate,
                                   PublicarPromocionRequest,
                                   RechazarPremioTramoOut,
                                   RechazarPromocionOut, TramoReferidoCreate,
                                   TramoReferidoOut, TramoReferidoUpdate,
                                   ValidarCodigoOut, ValidarCodigoRequest,
                                   TarjetaReferidosOut,
                                   TarjetaReferidosUpdate)
from app.services import avisos_marketing as avisos_svc
from app.services import promociones_referidos_service as promos_svc
from app.services import referidos_service as svc
from app.services import storage
from app.services import tramos_referidos_service as tramos_svc
from app.services.email_service import send_invitacion_alumno

router = APIRouter()

logger = logging.getLogger(__name__)


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


@router.get("/mi-invitacion", response_model=MiInvitacionOut)
def mi_invitacion(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """La invitación de OTRO alumno que trajo a este usuario, o `codigo=None`.

    Es la fuente del prellenado en la compra: el alumno ve el código de quien lo
    invitó y decide si lo aplica. NO se aplica solo; el alta de
    `referidos_aplicados` sigue siendo explícita (`POST /validar-codigo`).

    Sin invitación se responde 200 con `codigo=None` (no 404): "no me invitó
    nadie" es un estado normal y el front simplemente no prellena el campo.
    """
    _exigir_alumno(current_user)

    fila = (
        db.query(Invitacion, CodigoReferido, Usuario)
        .join(CodigoReferido,
              CodigoReferido.id == Invitacion.codigo_referido_id)
        .join(Usuario, Usuario.id == Invitacion.enviado_por_usuario_id)
        .filter(
            Invitacion.usuario_registrado_id == current_user["usuario_id"],
            Invitacion.tenant_id == current_user["tenant_id"],
            Invitacion.origen == OrigenInvitacion.alumno,
        )
        .order_by(Invitacion.id.desc())
        .first()
    )
    if fila is None:
        return svc.datos_mi_invitacion(None, None, None)

    invitacion, codigo, invitador = fila
    return svc.datos_mi_invitacion(invitacion, codigo.codigo, invitador.nombre)


@router.post("/invitaciones", response_model=InvitacionEnviadaOut,
             status_code=status.HTTP_201_CREATED)
def invitar_alumno(
    datos: InvitarAlumnoRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Envía una invitación por correo a un amigo con el código del alumno.

    El código y el remitente salen del TOKEN (nunca del body). El link lleva un
    token opaco que no autoriza nada: sólo identifica la invitación para saber
    quién se registró desde ella.

    Anti-abuso, todo por ALUMNO (no por IP, que es compartida en el box):
      * 5 envíos por día → 429;
      * sin reenvío al mismo correo dentro de 7 días → 400 (el enlace viejo
        sigue sirviendo, así que no se pierde nada);
      * se rechaza el correo propio y el de alguien que ya es usuario del box.

    Si el correo NO sale, la invitación se BORRA y se responde 502: no se deja
    una fila fantasma que después bloquee el reenvío durante 7 días.
    """
    _exigir_alumno(current_user)

    usuario_id = current_user["usuario_id"]
    tenant_id = current_user["tenant_id"]

    codigo = _codigo_propio(db, usuario_id)
    if not bool(codigo.activo):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=svc.MOTIVO_CODIGO_INACTIVO)

    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id,
        Usuario.tenant_id == tenant_id,
    ).first()
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Usuario no encontrado en este box")

    correo = svc.normalizar_correo_invitacion(str(datos.correo))

    ahora = datetime.now(timezone.utc)
    enviadas_ultimo_dia = db.query(func.count(Invitacion.id)).filter(
        Invitacion.enviado_por_usuario_id == usuario_id,
        Invitacion.tenant_id == tenant_id,
        Invitacion.fecha_envio >= ahora - timedelta(days=1),
    ).scalar() or 0
    if enviadas_ultimo_dia >= svc.LIMITE_INVITACIONES_DIA:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=svc.MOTIVO_INVITACION_LIMITE)

    ya_usuario = db.query(Usuario.id).filter(
        Usuario.correo == correo,
        Usuario.tenant_id == tenant_id,
    ).first() is not None
    enviada_reciente = db.query(Invitacion.id).filter(
        Invitacion.tenant_id == tenant_id,
        Invitacion.correo_prospecto == correo,
        Invitacion.fecha_envio >= ahora - timedelta(
            days=svc.DIAS_BLOQUEO_REENVIO),
    ).first() is not None

    motivo = svc.motivo_invitacion_rechazada(
        es_propio=(correo == (usuario.correo or "").strip().lower()),
        ya_usuario=ya_usuario,
        enviada_reciente=enviada_reciente,
    )
    if motivo is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=motivo)

    invitacion = Invitacion(
        tenant_id=tenant_id,
        origen=OrigenInvitacion.alumno,
        enviado_por_usuario_id=usuario_id,
        correo_prospecto=correo,
        codigo_referido_id=codigo.id,
        token_rastreo=svc.generar_token_invitacion(),
        estado=EstadoInvitacion.enviada,
        fecha_envio=ahora,
    )
    db.add(invitacion)
    db.flush()

    enlace = svc.enlace_invitacion(invitacion.token_rastreo)
    try:
        enviado = bool(send_invitacion_alumno(
            usuario.nombre, correo, codigo.codigo, enlace,
            tenant_id=tenant_id))
    except Exception:
        logger.exception("Fallo inesperado enviando la invitación de referido")
        enviado = False

    if not enviado:
        db.delete(invitacion)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=("No pudimos enviar la invitación por correo. "
                    "Inténtalo de nuevo en unos minutos."))

    db.commit()
    db.refresh(invitacion)
    return svc.datos_invitacion_enviada(invitacion, codigo.codigo)


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


# ── La tarjeta FIJA del carrusel ("Invita y Gana") ──────────────────────────
# El copy de la última tarjeta de "Novedades del box". Se guarda aparte de
# `configuracion` porque lo LEE el alumno y porque crear una fila de copy no
# debe tocar `configurada` ni `activo` (ver el docstring del modelo).

@router.get("/tarjeta", response_model=TarjetaReferidosOut)
def obtener_tarjeta(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Copy EFECTIVO de la tarjeta fija del carrusel. Cualquier autenticado.

    La lee el Inicio del alumno, por eso NO lleva `require_full_access` (un
    alumno en plan de prueba también ve su Inicio, igual que
    `GET /marketing/vigentes`) y NO devuelve los porcentajes del box. Sin fila
    se responden los textos por defecto SIN crear nada: leer no escribe.
    """
    tarjeta = db.query(TarjetaReferidos).filter(
        TarjetaReferidos.tenant_id == current_user["tenant_id"]
    ).first()
    return svc.datos_tarjeta(tarjeta)


@router.put("/tarjeta", response_model=TarjetaReferidosOut)
def actualizar_tarjeta(
    datos: TarjetaReferidosUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea o actualiza (upsert) el copy de la tarjeta fija. Sólo admin.

    Un texto `null` o en blanco vuelve al default de ESE campo: el botón
    "Restablecer" del panel manda los tres en `null`. El `tenant_id` sale
    siempre del token, nunca del cuerpo (el schema lo prohíbe con
    `extra="forbid"`).
    """
    tenant_id = current_user["tenant_id"]
    tarjeta = db.query(TarjetaReferidos).filter(
        TarjetaReferidos.tenant_id == tenant_id
    ).first()

    if tarjeta is None:
        tarjeta = TarjetaReferidos(tenant_id=tenant_id)
        db.add(tarjeta)

    tarjeta.titulo = datos.titulo
    tarjeta.texto = datos.texto
    tarjeta.cta = datos.cta
    tarjeta.visible = bool(datos.visible)

    db.commit()
    db.refresh(tarjeta)

    return svc.datos_tarjeta(tarjeta)


# ── Fase 5: promociones por volumen (sólo admin) ─────────────────────────────

def _promocion_del_tenant(db: Session, tenant_id: int,
                          promocion_id: int) -> PromocionReferidos:
    """La promoción del box del token; la de otro box se comporta como 404."""
    promocion = db.query(PromocionReferidos).filter(
        PromocionReferidos.id == promocion_id,
        PromocionReferidos.tenant_id == tenant_id,
    ).first()
    if promocion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Promoción no encontrada.")
    return promocion


def _aplicar_datos_promocion(promocion: PromocionReferidos,
                             datos: PromocionReferidosCreate) -> None:
    """Copia el cuerpo validado al ORM (crear y editar comparten las reglas)."""
    promocion.nombre = datos.nombre.strip()
    promocion.umbral_referidos_convertidos = datos.umbral_referidos_convertidos
    promocion.periodo = datos.periodo
    promocion.tipo_premio = datos.tipo_premio
    promocion.valor_premio = datos.valor_premio
    promocion.activo = bool(datos.activo)


def _pendientes_por_promocion(db: Session, tenant_id: int) -> dict:
    """`{promocion_id: pendientes}` en UNA query (sin N+1 en la lista)."""
    filas = (
        db.query(PromocionReferidosDetectada.promocion_id,
                 func.count(PromocionReferidosDetectada.id))
        .join(PromocionReferidos,
              PromocionReferidos.id == PromocionReferidosDetectada.promocion_id)
        .filter(
            PromocionReferidos.tenant_id == tenant_id,
            PromocionReferidosDetectada.estado
            == EstadoPromocionDetectada.pendiente_confirmacion,
        )
        .group_by(PromocionReferidosDetectada.promocion_id)
        .all()
    )
    return {int(promocion_id): int(total) for promocion_id, total in filas}


def _avisos_por_promocion(db: Session, tenant_id: int) -> dict:
    """`{promocion_id: aviso}` de las tarjetas publicadas, en UNA query (sin N+1)."""
    filas = db.query(AvisoMarketing).filter(
        AvisoMarketing.tenant_id == tenant_id,
        AvisoMarketing.promocion_id.isnot(None),
    ).all()
    return {int(aviso.promocion_id): aviso for aviso in filas}


def _aviso_de_promocion(db: Session, tenant_id: int,
                        promocion_id: int) -> AvisoMarketing | None:
    """La tarjeta del carrusel VINCULADA a la promoción (o None si no se publicó)."""
    return db.query(AvisoMarketing).filter(
        AvisoMarketing.tenant_id == tenant_id,
        AvisoMarketing.promocion_id == promocion_id,
    ).first()


@router.get("/promociones", response_model=list[PromocionReferidosOut])
def listar_promociones(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Todas las promociones del box, con cuántos umbrales esperan confirmación.

    Incluye si cada una está PUBLICADA en el carrusel (migración 056): la pantalla
    muestra el chip y el botón correcto sin pedir los avisos por separado.
    """
    tenant_id = current_user["tenant_id"]
    promociones = db.query(PromocionReferidos).filter(
        PromocionReferidos.tenant_id == tenant_id
    ).order_by(
        PromocionReferidos.activo.desc(),
        PromocionReferidos.umbral_referidos_convertidos,
        PromocionReferidos.id,
    ).all()
    pendientes = _pendientes_por_promocion(db, tenant_id)
    avisos = _avisos_por_promocion(db, tenant_id)
    return [promos_svc.serializar_promocion(
        promocion, pendientes.get(promocion.id, 0),
        avisos.get(promocion.id)) for promocion in promociones]


@router.post("/promociones", response_model=PromocionReferidosOut,
             status_code=status.HTTP_201_CREATED)
def crear_promocion(
    datos: PromocionReferidosCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea una promoción por volumen en el box del token.

    El valor del premio ya viene validado por Pydantic según el tipo
    (`mes_gratis` sin valor, `dias_gratis` entero, `descuento_extra` 0-100 %).
    """
    promocion = PromocionReferidos(tenant_id=current_user["tenant_id"])
    _aplicar_datos_promocion(promocion, datos)
    db.add(promocion)
    db.commit()
    db.refresh(promocion)
    return promos_svc.serializar_promocion(promocion)


@router.put("/promociones/{promocion_id}",
            response_model=PromocionReferidosOut)
def actualizar_promocion(
    promocion_id: int,
    datos: PromocionReferidosUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Actualiza una promoción. Los premios YA detectados conservan su snapshot."""
    tenant_id = current_user["tenant_id"]
    promocion = _promocion_del_tenant(db, tenant_id, promocion_id)
    _aplicar_datos_promocion(promocion, datos)
    db.commit()
    db.refresh(promocion)
    pendientes = _pendientes_por_promocion(db, tenant_id)
    return promos_svc.serializar_promocion(
        promocion, pendientes.get(promocion.id, 0),
        _aviso_de_promocion(db, tenant_id, promocion.id))


@router.delete("/promociones/{promocion_id}")
def eliminar_promocion(
    promocion_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Borra una promoción SIN historial. Si ya detectó umbrales, se desactiva.

    Borrarla con detecciones se llevaría por CASCADE la traza de premios ya
    ganados; el panel ofrece apagarla (`activo=false`) en ese caso.
    """
    tenant_id = current_user["tenant_id"]
    promocion = _promocion_del_tenant(db, tenant_id, promocion_id)
    detectadas = db.query(PromocionReferidosDetectada.id).filter(
        PromocionReferidosDetectada.promocion_id == promocion.id
    ).first()
    if detectadas is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Esta promoción ya detectó umbrales y no se puede borrar: "
                    "apágala para conservar el historial de premios."))
    # La tarjeta publicada se va con ella (ON DELETE CASCADE, 056). Se borra por
    # el servicio para recuperar el flyer y no dejar el archivo huérfano.
    aviso = _aviso_de_promocion(db, tenant_id, promocion.id)
    flyer = avisos_svc.eliminar(db, aviso) if aviso is not None else None
    db.delete(promocion)
    db.commit()
    if flyer:
        storage.borrar_publico(flyer)
    return {"status": "ok", "id": promocion_id}


# ── Publicación de una promoción en el carrusel del alumno (migración 056) ────
# La tarjeta NO repite la configuración del premio: sólo lo anuncia y el alumno
# la abre en `/alumno/invita-y-gana`. Por eso `tipo` y `promocion_id` los fija el
# backend y el cuerpo lleva lo mismo que un aviso manual (título, texto y ventana).

def _payload_aviso_promocion(datos: PublicarPromocionRequest,
                             promocion: PromocionReferidos,
                             imagen_url: str | None = None) -> dict:
    """Payload de `avisos_marketing` armado desde el cuerpo de publicación."""
    return {
        "tipo": TIPO_PROMOCION,
        "titulo": datos.titulo,
        "texto": datos.texto,
        "nombre_aliado": None,
        "fecha_evento": None,
        "vigente_desde": datos.vigente_desde,
        "vigente_hasta": datos.vigente_hasta,
        "fijado_arriba": datos.fijado_arriba,
        # El flyer se sube desde Marketing (`POST /marketing/{id}/imagen`); si la
        # tarjeta ya tenía uno, republicar NO lo pierde.
        "imagen_url": imagen_url,
        "promocion_id": promocion.id,
    }


@router.post("/promociones/{promocion_id}/publicar",
             response_model=AvisoMarketingOut,
             status_code=status.HTTP_200_OK)
def publicar_promocion(
    promocion_id: int,
    datos: PublicarPromocionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Publica la promoción en "Novedades del box" del Inicio del alumno.

    Responde 200 (no 201) a propósito: el MISMO botón sirve para publicar y para
    corregir la tarjeta ya publicada. Si existe, se EDITA ese aviso —no se crea
    otro— porque el índice único `(tenant_id, promocion_id)` admite una sola
    tarjeta por promoción y así se conserva su flyer y su `creado_en`.
    """
    tenant_id = current_user["tenant_id"]
    promocion = _promocion_del_tenant(db, tenant_id, promocion_id)
    if not promocion.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("La promoción está apagada: actívala antes de publicarla "
                    "para que el alumno no llegue a una promoción sin premio."))
    aviso = _aviso_de_promocion(db, tenant_id, promocion.id)
    try:
        if aviso is not None:
            return avisos_svc.actualizar(
                db, aviso, _payload_aviso_promocion(datos, promocion,
                                                    aviso.imagen_url))
        return avisos_svc.crear(
            db, tenant_id, _payload_aviso_promocion(datos, promocion),
            creado_por=current_user["usuario_id"])
    except ValueError as error:
        # `avisos_marketing.validar` devuelve la lista de errores: se responde 400
        # con todos juntos, igual que `POST /marketing`.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=" ".join(error.args[0]))


@router.delete("/promociones/{promocion_id}/publicar")
def despublicar_promocion(
    promocion_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Quita la tarjeta del carrusel. La promoción sigue existiendo y activa.

    El aviso se BORRA (no se vence): si el admin la vuelve a publicar, arranca
    una tarjeta nueva con la ventana que elija. El flyer se borra después del
    commit y best-effort, igual que `DELETE /marketing/{id}`.
    """
    tenant_id = current_user["tenant_id"]
    promocion = _promocion_del_tenant(db, tenant_id, promocion_id)
    aviso = _aviso_de_promocion(db, tenant_id, promocion.id)
    if aviso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Esta promoción no está publicada.")
    flyer = avisos_svc.eliminar(db, aviso)
    if flyer:
        storage.borrar_publico(flyer)
    return {"status": "ok", "id": promocion_id}


@router.get("/promociones-detectadas",
            response_model=list[PromocionDetectadaOut])
def listar_promociones_detectadas(
    estado: str = "pendiente_confirmacion",
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Umbrales detectados del box. `estado=todas` incluye el historial."""
    tenant_id = current_user["tenant_id"]
    consulta = (
        db.query(PromocionReferidosDetectada, Usuario)
        .join(PromocionReferidos,
              PromocionReferidos.id == PromocionReferidosDetectada.promocion_id)
        .join(Usuario, Usuario.id == PromocionReferidosDetectada.usuario_id)
        .filter(PromocionReferidos.tenant_id == tenant_id)
    )
    if estado != "todas":
        valores = {opcion.value
                   for opcion in EstadoPromocionDetectada}
        if estado not in valores:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=("Estado inválido. Usa 'pendiente_confirmacion', "
                        "'confirmado', 'rechazado' o 'todas'."))
        consulta = consulta.filter(
            PromocionReferidosDetectada.estado == estado)
    filas = consulta.order_by(
        PromocionReferidosDetectada.fecha_deteccion.desc(),
        PromocionReferidosDetectada.id.desc(),
    ).all()
    return [promos_svc.serializar_deteccion(deteccion, alumno)
            for deteccion, alumno in filas]


@router.post("/promociones-detectadas/{deteccion_id}/confirmar",
             response_model=ConfirmarPromocionOut)
def confirmar_promocion_detectada(
    deteccion_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Confirma el umbral y APLICA el premio congelado (extensión o crédito)."""
    try:
        resultado = promos_svc.confirmar_deteccion(
            db,
            tenant_id=current_user["tenant_id"],
            deteccion_id=deteccion_id,
            admin_id=current_user["usuario_id"],
        )
        db.commit()
        return resultado
    except promos_svc.ErrorPromocion as error:
        db.rollback()
        raise HTTPException(status_code=error.status_code,
                            detail=error.mensaje)


@router.post("/promociones-detectadas/{deteccion_id}/rechazar",
             response_model=RechazarPromocionOut)
def rechazar_promocion_detectada(
    deteccion_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Rechaza el umbral sin aplicar ningún premio."""
    try:
        resultado = promos_svc.rechazar_deteccion(
            db,
            tenant_id=current_user["tenant_id"],
            deteccion_id=deteccion_id,
            admin_id=current_user["usuario_id"],
        )
        db.commit()
        return resultado
    except promos_svc.ErrorPromocion as error:
        db.rollback()
        raise HTTPException(status_code=error.status_code,
                            detail=error.mensaje)


# ── Parte C: tramos del invitador (escalera por ciclo) ──────────────────────
# El motor paga al cierre del CICLO de facturación del alumno y UN solo premio
# (el tramo más alto). El flag `configuracion_referidos.motor_premios` decide
# cuál de los dos motores evalúa: `tramos` apaga la detección por mes calendario.

def _tramo_del_tenant(db: Session, tenant_id: int,
                      tramo_id: int) -> TramoReferido:
    """El escalón del box del token; el de otro box se comporta como 404."""
    tramo = db.query(TramoReferido).filter(
        TramoReferido.id == tramo_id,
        TramoReferido.tenant_id == tenant_id,
    ).first()
    if tramo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Tramo no encontrado.")
    return tramo


def _escalera_completa(db: Session, tenant_id: int) -> list[TramoReferido]:
    """TODOS los escalones del box (también los apagados): es la pantalla admin."""
    return (db.query(TramoReferido)
            .filter(TramoReferido.tenant_id == tenant_id)
            .order_by(TramoReferido.umbral_referidos, TramoReferido.id)
            .all())


def _premios_pendientes_por_tramo(db: Session, tenant_id: int) -> dict:
    """`{tramo_id: pendientes}` en UNA query (sin N+1 en la lista)."""
    filas = (
        db.query(PremioTramoCiclo.tramo_id,
                 func.count(PremioTramoCiclo.id))
        .filter(
            PremioTramoCiclo.tenant_id == tenant_id,
            PremioTramoCiclo.estado
            == EstadoPromocionDetectada.pendiente_confirmacion,
        )
        .group_by(PremioTramoCiclo.tramo_id)
        .all()
    )
    return {int(tramo_id): int(total) for tramo_id, total in filas
            if tramo_id is not None}


def _serializar_tramo_admin(tramo: TramoReferido,
                            pendientes: dict) -> dict:
    datos = tramos_svc.serializar_tramo(tramo)
    datos["premios_pendientes"] = pendientes.get(int(tramo.id), 0)
    return datos


def _aplicar_datos_tramo(tramo: TramoReferido,
                         datos: TramoReferidoCreate) -> None:
    """Copia el cuerpo validado al ORM (crear y editar comparten las reglas)."""
    tramo.umbral_referidos = datos.umbral_referidos
    tramo.tipo_premio = datos.tipo_premio
    tramo.valor_premio = datos.valor_premio
    tramo.activo = bool(datos.activo)


def _texto_con_escalera(texto: str, escalera: list[str]) -> str:
    """Texto de la tarjeta + la escalera completa, dentro del tope de 1000.

    El pie se genera SIEMPRE desde los tramos activos (decisión 4): la tarjeta
    no puede quedar anunciando una escalera vieja porque el admin editó el texto
    a mano.
    """
    limpio = (texto or "").strip()
    if not escalera:
        return limpio[:1000]
    pie = "Escalera: " + " · ".join(escalera)
    combinado = f"{limpio}\n\n{pie}" if limpio else pie
    return combinado[:1000]


@router.get("/tramos", response_model=EscaleraTramosOut)
def listar_tramos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """La escalera completa del box + qué motor está activo.

    Incluye los escalones APAGADOS (la pantalla los muestra como historial) y
    dos ayudas: `escalera` (la frase que lee el alumno) y `advertencias` (saltos
    raros: un tramo que premia menos que el anterior).
    """
    tenant_id = current_user["tenant_id"]
    tramos = _escalera_completa(db, tenant_id)
    pendientes = _premios_pendientes_por_tramo(db, tenant_id)
    aviso = (db.query(AvisoMarketing)
             .filter(AvisoMarketing.tenant_id == tenant_id,
                     AvisoMarketing.escalera_tramos.is_(True))
             .first())
    return {
        "motor": tramos_svc.motor_del_tenant(db, tenant_id),
        "tramos": [_serializar_tramo_admin(tramo, pendientes)
                   for tramo in tramos],
        "escalera": tramos_svc.texto_escalera(tramos),
        "advertencias": tramos_svc.advertencias_escalera(tramos),
        # La tarjeta del carrusel (064): el chip "Publicada" y el botón
        # Publicar/Despublicar salen de acá, sin pedir los avisos por separado.
        "publicada": aviso is not None,
        "publicada_desde": aviso.vigente_desde if aviso is not None else None,
        "publicada_hasta": aviso.vigente_hasta if aviso is not None else None,
        "publicada_titulo": aviso.titulo if aviso is not None else None,
        "publicada_texto": aviso.texto if aviso is not None else None,
        "publicada_fijado_arriba": (bool(aviso.fijado_arriba)
                                    if aviso is not None else False),
    }


@router.post("/tramos", response_model=TramoReferidoOut,
             status_code=status.HTTP_201_CREATED)
def crear_tramo(
    datos: TramoReferidoCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea un escalón. 409 si el umbral ya existe en el box.

    El valor del premio ya viene validado por Pydantic según el tipo
    (`mes_gratis` sin valor, `dias_gratis` entero, `descuento_extra` 0-100 %).
    """
    tenant_id = current_user["tenant_id"]
    repetido = db.query(TramoReferido.id).filter(
        TramoReferido.tenant_id == tenant_id,
        TramoReferido.umbral_referidos == datos.umbral_referidos,
    ).first()
    if repetido is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Ya existe un tramo de {datos.umbral_referidos} "
                    "referidos: edita ese escalón en vez de crear otro."))

    tramo = TramoReferido(tenant_id=tenant_id)
    _aplicar_datos_tramo(tramo, datos)
    db.add(tramo)
    try:
        db.commit()
    except IntegrityError:
        # Carrera entre dos admins: la UNIQUE (tenant_id, umbral) gana.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un tramo con ese umbral.")
    db.refresh(tramo)
    return _serializar_tramo_admin(tramo, {})


@router.put("/tramos/motor", response_model=dict)
def actualizar_motor_premios(
    datos: MotorPremiosUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Cambia el motor de premios del box (`promociones` ↔ `tramos`).

    Es el interruptor de la decisión de negocio: con `'tramos'` la detección por
    mes calendario deja de correr (su job se salta el box) y evalúa la escalera.
    Los premios YA detectados conservan su snapshot; nada se reescribe.

    Guarda de seguridad: no se puede encender `'tramos'` sin al menos un escalón
    activo (el box se quedaría sin pagar ningún premio).
    """
    tenant_id = current_user["tenant_id"]
    if datos.motor_premios == MotorPremios.tramos.value:
        activos = db.query(func.count(TramoReferido.id)).filter(
            TramoReferido.tenant_id == tenant_id,
            TramoReferido.activo.is_(True),
        ).scalar() or 0
        if int(activos) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Carga al menos un tramo ACTIVO antes de encender el "
                        "motor de tramos: si no, el box dejaría de pagar "
                        "cualquier premio."))

    config = (db.query(ConfiguracionReferidos)
              .filter(ConfiguracionReferidos.tenant_id == tenant_id)
              .first())
    if config is None:
        config = ConfiguracionReferidos(
            tenant_id=tenant_id, motor_premios=datos.motor_premios)
        db.add(config)
    else:
        config.motor_premios = datos.motor_premios
    db.commit()
    return {
        "motor_premios": datos.motor_premios,
        "mensaje": ("Motor actualizado. Los premios ya detectados conservan "
                    "su snapshot."),
    }


@router.post("/tramos/publicar", response_model=AvisoMarketingOut,
             status_code=status.HTTP_200_OK)
def publicar_escalera(
    datos: PublicarPromocionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Publica la ESCALERA completa en "Novedades del box" del Inicio del alumno.

    Decisión de negocio: la tarjeta muestra la escalera entera ("1 = 15 %,
    2 = 30 %, 3 = mes gratis"), no un mensaje genérico. El texto que escribe el
    admin se conserva y la escalera se agrega SIEMPRE al final, generada desde
    los tramos activos: si después cambia un escalón y republica, la tarjeta se
    actualiza sola.

    Responde 200 (no 201) y EDITA la tarjeta existente: una sola tarjeta de
    escalera por box (`uq_avisos_marketing_escalera`), así republicar no duplica
    ni pierde el flyer.
    """
    tenant_id = current_user["tenant_id"]
    activos = [tramo for tramo in _escalera_completa(db, tenant_id)
               if tramo.activo]
    if not activos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Carga al menos un tramo activo antes de publicar: la "
                    "tarjeta anuncia la escalera y hoy está vacía."))
    escalera = tramos_svc.texto_escalera(activos)

    aviso = (db.query(AvisoMarketing)
             .filter(AvisoMarketing.tenant_id == tenant_id,
                     AvisoMarketing.escalera_tramos.is_(True))
             .first())
    payload = {
        "tipo": TIPO_PROMOCION,
        "titulo": datos.titulo,
        "texto": _texto_con_escalera(datos.texto, escalera),
        "nombre_aliado": None,
        "fecha_evento": None,
        "vigente_desde": datos.vigente_desde,
        "vigente_hasta": datos.vigente_hasta,
        "fijado_arriba": datos.fijado_arriba,
        # El flyer se sube desde Marketing; republicar NO lo pierde.
        "imagen_url": aviso.imagen_url if aviso is not None else None,
        "promocion_id": None,
        "escalera_tramos": True,
    }
    try:
        if aviso is not None:
            return avisos_svc.actualizar(db, aviso, payload)
        return avisos_svc.crear(db, tenant_id, payload,
                                creado_por=current_user["usuario_id"])
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=" ".join(error.args[0]))


@router.delete("/tramos/publicar")
def despublicar_escalera(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Quita la tarjeta de la escalera del carrusel (los tramos siguen igual)."""
    tenant_id = current_user["tenant_id"]
    aviso = (db.query(AvisoMarketing)
             .filter(AvisoMarketing.tenant_id == tenant_id,
                     AvisoMarketing.escalera_tramos.is_(True))
             .first())
    if aviso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="La escalera no está publicada.")
    flyer = avisos_svc.eliminar(db, aviso)
    if flyer:
        storage.borrar_publico(flyer)
    return {"status": "ok"}


@router.put("/tramos/{tramo_id}", response_model=TramoReferidoOut)
def actualizar_tramo(
    tramo_id: int,
    datos: TramoReferidoUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Edita un escalón. Los premios YA detectados conservan su snapshot.

    Cambiar el umbral puede chocar con otro escalón del box: se responde 409 en
    vez de dejar que reviente la UNIQUE.
    """
    tenant_id = current_user["tenant_id"]
    tramo = _tramo_del_tenant(db, tenant_id, tramo_id)
    if datos.umbral_referidos != tramo.umbral_referidos:
        repetido = db.query(TramoReferido.id).filter(
            TramoReferido.tenant_id == tenant_id,
            TramoReferido.umbral_referidos == datos.umbral_referidos,
            TramoReferido.id != tramo.id,
        ).first()
        if repetido is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Ya existe un tramo de {datos.umbral_referidos} "
                        "referidos en este box."))
    _aplicar_datos_tramo(tramo, datos)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un tramo con ese umbral.")
    db.refresh(tramo)
    pendientes = _premios_pendientes_por_tramo(db, tenant_id)
    return _serializar_tramo_admin(tramo, pendientes)


@router.delete("/tramos/{tramo_id}")
def eliminar_tramo(
    tramo_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Borra un escalón SIN historial. Si ya generó premios, se apaga.

    Borrarlo con premios dejaría las filas del alumno sin su escalón (el
    snapshot del premio sobrevive, pero se pierde la traza): el panel ofrece
    apagarlo (`activo=false`) en ese caso, igual que las promociones de la Fase 5.
    """
    tenant_id = current_user["tenant_id"]
    tramo = _tramo_del_tenant(db, tenant_id, tramo_id)
    usado = db.query(PremioTramoCiclo.id).filter(
        PremioTramoCiclo.tramo_id == tramo.id).first()
    if usado is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Este tramo ya generó premios y no se puede borrar: "
                    "apágalo para conservar el historial."))
    db.delete(tramo)
    db.commit()
    return {"status": "ok", "id": tramo_id}


@router.get("/tramos/premios", response_model=list[PremioTramoOut])
def listar_premios_tramo(
    estado: str = "pendiente_confirmacion",
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Premios de tramo del box. `estado=todas` incluye el historial."""
    tenant_id = current_user["tenant_id"]
    consulta = (
        db.query(PremioTramoCiclo, Usuario)
        .join(Usuario, Usuario.id == PremioTramoCiclo.usuario_id)
        .filter(PremioTramoCiclo.tenant_id == tenant_id)
    )
    if estado != "todas":
        valores = {opcion.value for opcion in EstadoPromocionDetectada}
        if estado not in valores:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=("Estado inválido. Usa 'pendiente_confirmacion', "
                        "'confirmado', 'rechazado' o 'todas'."))
        consulta = consulta.filter(PremioTramoCiclo.estado == estado)
    filas = consulta.order_by(
        PremioTramoCiclo.fecha_deteccion.desc(),
        PremioTramoCiclo.id.desc(),
    ).all()
    return [tramos_svc.serializar_premio(premio, alumno)
            for premio, alumno in filas]


@router.post("/tramos/premios/{premio_id}/confirmar",
             response_model=ConfirmarPremioTramoOut)
def confirmar_premio_tramo(
    premio_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Confirma el premio del ciclo y lo APLICA con el premio congelado.

    Si el alumno no tiene plan vigente NO es un error: el premio queda
    confirmado y pendiente de aplicar (ver `aplicado_en` / `pendiente_de_aplicar`).
    """
    try:
        resultado = tramos_svc.confirmar_premio(
            db,
            tenant_id=current_user["tenant_id"],
            premio_id=premio_id,
            admin_id=current_user["usuario_id"],
        )
        db.commit()
        return resultado
    except tramos_svc.ErrorPromocion as error:
        db.rollback()
        raise HTTPException(status_code=error.status_code,
                            detail=error.mensaje)


@router.post("/tramos/premios/{premio_id}/rechazar",
             response_model=RechazarPremioTramoOut)
def rechazar_premio_tramo(
    premio_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Rechaza el premio de tramo sin aplicar nada."""
    try:
        resultado = tramos_svc.rechazar_premio(
            db,
            tenant_id=current_user["tenant_id"],
            premio_id=premio_id,
            admin_id=current_user["usuario_id"],
        )
        db.commit()
        return resultado
    except tramos_svc.ErrorPromocion as error:
        db.rollback()
        raise HTTPException(status_code=error.status_code,
                            detail=error.mensaje)


# ── Progreso del alumno en su ciclo ("Tu ciclo" en Invita y Gana) ───────────

@router.get("/mi-progreso", response_model=MiProgresoOut)
def mi_progreso(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """El alumno ve SU ciclo: cuántos referidos lleva y cuánto le falta.

    No expone datos de otros alumnos: el `usuario_id` sale del token y la
    respuesta sólo trae la escalera del box (los premios, que son públicos en la
    pantalla) y sus propios conteos.
    """
    _exigir_alumno(current_user)
    return tramos_svc.progreso_actual(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
    )

