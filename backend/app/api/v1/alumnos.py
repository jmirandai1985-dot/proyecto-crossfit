"""Router de endpoints para el flujo de registro/activación de alumnos."""
from app.core.urls import url_frontend  # B.2
import string
import secrets
import logging
import sentry_sdk
from datetime import datetime, timedelta, date

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr, Field, AliasChoices, ConfigDict, model_validator
from sqlalchemy.orm import Session
from typing import ClassVar, Optional

from app.db.database import get_db
from app.core.config import settings
from app.core.rate_limit import limiter, LIMIT_REGISTRO
from app.models.usuario import Usuario, RolUsuario
from app.models.plan import Plan
from app.models.suscripcion import Suscripcion
from app.api.v1.usuarios import hash_password
from app.core.dependencies import get_current_user, get_current_admin, es_usuario_prueba
# El RUT chileno vive en `app/utils/rut.py` (módulo 11): lo comparten esta ruta y la
# configuración bancaria del box (`api/v1/configuracion.py`, donde el RUT es del titular
# de la cuenta). Se importa acá y se sigue exponiendo como `alumnos.validar_rut` porque
# hay consumidores que lo importan desde este módulo (`scripts/seed_ml_data*.py`).
from app.utils.rut import validar_rut
from app.services.auditoria_service import registrar_auditoria
# Avisos del PANEL (la campana): el alta avisa al admin del box también in-app.
# Ver docs/NOTIFICACIONES_PANEL.md.
from app.services.notificaciones_panel import notificar_admins_del_tenant
from app.services.email_service import (
    enviar_email_solicitud_admin,
    send_solicitud_prueba_clase, send_bienvenida_activacion,
    send_confirmacion_renovacion_plan, formatear_fecha_es
)

router = APIRouter()

logger = logging.getLogger(__name__)


class ActualizarMiPerfil(BaseModel):
    """Campos editables por el usuario sobre su PROPIO perfil (Ajustes).

    SOLO se aplican los campos AUTOEDITABLES:

        telefono · peso_kg · estatura_cm

    El resto de la ficha (`nombre`, `correo`, `genero`, `fecha_nacimiento`) es
    dato de identidad/administración del box y se edita por
    `PUT /usuarios/{id}` (admin-only). Esos 4 campos siguen declarados en el
    schema por compatibilidad con clientes viejos, pero se DESCARTAN antes de
    validar: el PUT responde 200, no cambia nada y el intento queda en el log
    (antes el alumno podía reescribir su propio correo/género/fecha de
    nacimiento desde Ajustes, con la UI ya bloqueada: backend ≠ UI).

    NO permite cambiar rol/activo/estado/password (eso es admin o un flujo
    dedicado).
    `extra='forbid'`: una clave desconocida falla con 422 en vez de ignorarse.
    """
    correo: Optional[EmailStr] = None
    telefono: Optional[str] = Field(None, max_length=20)
    peso_kg: Optional[float] = Field(None, gt=0, le=400)
    estatura_cm: Optional[int] = Field(None, ge=50, le=250)
    genero: Optional[str] = Field(None, max_length=10)
    fecha_nacimiento: Optional[date] = None

    model_config = ConfigDict(extra='forbid')

    # Campos que el alumno SÍ autogestiona (contrato con Ajustes.jsx).
    CAMPOS_AUTOEDITABLES: ClassVar[tuple] = ("telefono", "peso_kg", "estatura_cm")
    # Campos que sólo modifica el box (`PUT /usuarios/{id}`): si llegan por acá
    # se descartan (200 + log) en vez de aplicarse o dar 422.
    CAMPOS_SOLO_BOX: ClassVar[tuple] = (
        "nombre", "correo", "genero", "fecha_nacimiento")

    @model_validator(mode='before')
    @classmethod
    def _descartar_campos_solo_box(cls, data):
        """N-1 (extendido): ningún campo de `CAMPOS_SOLO_BOX` se edita por acá.

        Se descartan ANTES de validar, así que un cliente viejo que los mande
        (incluso con un `correo` malformado) recibe 200 + los valores viejos en
        la respuesta, y el intento queda registrado en el log.
        """
        if isinstance(data, dict):
            presentes = [c for c in cls.CAMPOS_SOLO_BOX if c in data]
            if presentes:
                logger.info(
                    "PUT /alumnos/me: descartados %s (solo los modifica el box "
                    "vía PUT /usuarios/{id})", ", ".join(sorted(presentes)))
                return {k: v for k, v in data.items()
                        if k not in cls.CAMPOS_SOLO_BOX}
        return data


def _serializar_mi_perfil(usuario):
    return {
        "id": usuario.id,
        # N-7: el `tenant_id` del token también se expone acá para que el front
        # pueda HIDRATAR su identidad desde el servidor (y no desde localStorage)
        # en el bootstrap de la sesión.
        "tenant_id": usuario.tenant_id,
        "nombre": usuario.nombre,
        "correo": usuario.correo,
        "telefono": usuario.telefono,
        "rut": usuario.rut,
        "rol": usuario.rol,
        "estado": usuario.estado,
        "activo": usuario.activo,
        "cambiar_password_al_login": usuario.cambiar_password_al_login,
        "peso_kg": usuario.peso_kg,
        "estatura_cm": usuario.estatura_cm,
        "genero": usuario.genero,
        "fecha_nacimiento": usuario.fecha_nacimiento,
    }



def generar_password_provisional(longitud=8) -> str:
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(longitud))


class RegistroAlumnoNuevo(BaseModel):
    nombre: str
    correo: EmailStr
    sexo: Optional[str] = None
    peso: Optional[float] = Field(
        None, validation_alias=AliasChoices("peso", "peso_kg"),
        description="Peso en kg (acepta campo 'peso' o 'peso_kg')")
    estatura: Optional[float] = Field(
        None, validation_alias=AliasChoices("estatura", "estatura_cm"),
        description="Estatura en cm (acepta campo 'estatura' o 'estatura_cm')")
    rut: str
    tenant_id: int = 1

    model_config = {"populate_by_name": True}


# ─── POST /registro/alumno-nuevo (público con rate limit) ───
@router.post("/registro/alumno-nuevo", status_code=status.HTTP_201_CREATED)
@limiter.limit(LIMIT_REGISTRO)
def registrar_alumno_nuevo(
    request: Request,
    datos: RegistroAlumnoNuevo,
    db: Session = Depends(get_db)
):
    """Registro público (autoservicio): valida correo/RUT únicos, crea el
    usuario ACTIVO con contraseña temporal (cambio forzado en el 1er login) y
    una suscripción de prueba activa (plan "Prueba", 1 crédito, 7 días)."""
    if db.query(Usuario).filter(
        Usuario.correo == datos.correo.lower(),
        Usuario.tenant_id == datos.tenant_id
    ).first():
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese correo")

    # Endurecimiento: rechaza el registro si el correo pertenece a un admin
    # (independiente del tenant), para evitar suplantación de cuentas admin.
    # NOTA: el valor del enum rol_usuario es 'administrador'.
    admin_con_correo = db.query(Usuario).filter(
        Usuario.correo == datos.correo.lower(),
        Usuario.rol == RolUsuario.administrador
    ).first()
    if admin_con_correo:
        raise HTTPException(status_code=400, detail="Correo pertenece a administrador")

    if db.query(Usuario).filter(
        Usuario.rut == datos.rut.strip().upper(),
        Usuario.tenant_id == datos.tenant_id
    ).first():
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese RUT")

    if not validar_rut(datos.rut):
        raise HTTPException(status_code=400, detail="RUT inválido (formato chileno requerido)")

    plan_prueba = db.query(Plan).filter(
        Plan.tenant_id == datos.tenant_id,
        Plan.nombre == "Prueba"
    ).first()
    if not plan_prueba:
        plan_prueba = Plan(
            tenant_id=datos.tenant_id, nombre="Prueba", creditos=1,
            es_ilimitado=False, precio_clp=0, duracion_dias=7, activo=True,
        )
        db.add(plan_prueba)
        db.flush()

    # ── AUTOSERVICIO (Bloque 1) ──────────────────────────────────────────
    # El alumno nuevo nace ACTIVO de inmediato (ya no queda "pendiente_activacion")
    # para que pueda ingresar con la contraseña temporal recibida por correo.
    # cambiar_password_al_login=True lo fuerza a cambiar la temporal en el 1er login.
    password_tmp = generar_password_provisional(10)
    usuario = Usuario(
        tenant_id=datos.tenant_id,
        rut=datos.rut.strip().upper(),
        nombre=datos.nombre.strip(),
        telefono=None,
        correo=datos.correo.lower(),
        password_hash=hash_password(password_tmp),
        rol=RolUsuario.alumno,
        activo=True,
        estado="activo",
        cambiar_password_al_login=True,
        peso_kg=datos.peso,
        estatura_cm=int(datos.estatura) if datos.estatura else None,
        genero=datos.sexo,
    )
    db.add(usuario)
    db.flush()

    # La suscripción "Prueba" nace ACTIVA (no "pendiente"): el crédito de prueba
    # queda usable de inmediato y el gate de acceso limitado (require_full_access)
    # empieza a aplicar sin intervención del admin.
    suscripcion = Suscripcion(
        tenant_id=datos.tenant_id,
        usuario_id=usuario.id,
        plan_id=plan_prueba.id,
        estado="activo",
        creditos_totales=1,
        creditos_disponibles=1,
        fecha_expiracion=datetime.utcnow() + timedelta(days=7),
    )
    db.add(suscripcion)
    db.commit()

    # ── Campana del ADMIN: el alta también avisa in-app ──
    # El registro avisa por EMAIL más abajo (enviar_email_solicitud_admin), pero el
    # correo no siempre es un canal disponible (con EMAIL_MODO=noop —TEST— no llega
    # nada, y en prod puede fallar el SMTP). El aviso del panel deja el alta visible
    # en la campana del box apenas el alumno se registra. Best-effort: si el aviso
    # falla, el registro NO se cae (el alumno ya está creado).
    notificar_admins_del_tenant(
        db, datos.tenant_id, "alumno_nuevo",
        f"🆕 Nuevo alumno de prueba: {usuario.nombre} ({usuario.correo})")

    try:
        # Notifica al admin que ingresó un alumno de prueba hoy (tarjeta informativa)
        enviar_email_solicitud_admin({
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "id": usuario.id,
        }, tenant_id=datos.tenant_id)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logging.getLogger("uvicorn.alumnos").warning(
            "Fallo al notificar al admin (email solicitud)")

    # RG-04: ⚠️ el servicio de correo NO levanta excepción cuando falla: devuelve False
    # (y guarda el detalle en ULTIMO_ERROR_SMTP). Antes el endpoint ignoraba el valor y
    # respondía siempre "revisa tu correo", incluso si el alumno nunca iba a recibir la
    # contraseña temporal. Ahora se usa el valor devuelto (y también se cubre una
    # eventual excepción) y, si falló, se devuelve la contraseña provisional + aviso.
    email_enviado = False
    try:
        # Confirma al LEAD con sus credenciales temporales para agendar la clase de prueba
        email_enviado = bool(send_solicitud_prueba_clase(
            usuario.nombre,
            usuario.correo,
            password_tmp,
            url_frontend("/login"),
            tenant_id=datos.tenant_id,
        ))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logging.getLogger("uvicorn.alumnos").warning(
            "Excepcion al enviar email de clase de prueba: %s", e)

    if not email_enviado:
        logging.getLogger("uvicorn.alumnos").warning(
            "Email de clase de prueba NO enviado a %s: se devuelve la contrasena provisional",
            usuario.correo)
        return {
            "mensaje": ("Tu registro quedó creado, pero NO pudimos enviarte el correo con "
                        "la contraseña temporal. Usa la contraseña de abajo para ingresar "
                        "y cambiala desde Ajustes."),
            "email_enviado": False,
            "password_provisional": password_tmp,
            "aviso": ("El envío del correo falló; si no puedes ingresar, contacta al box "
                      "para que te ayuden a restablecerla."),
        }

    return {
        "mensaje": "Registro exitoso. Revisa tu correo para obtener tu contraseña temporal.",
        "email_enviado": True,
    }


# ─── GET /pendientes-activacion (admin only) ───
@router.get("/pendientes-activacion")
def alumnos_pendientes(
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    lista = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.estado == "pendiente_activacion"
    ).order_by(Usuario.created_at.desc()).all()

    return [
        {
            "id": u.id,
            "nombre": u.nombre,
            "correo": u.correo,
            "rut": u.rut,
            "genero": u.genero,
            "peso_kg": u.peso_kg,
            "estatura_cm": u.estatura_cm,
            "fecha_registro": u.created_at.isoformat() if u.created_at else None,
        }
        for u in lista
    ]


# ─── GET /pendientes-activacion/count (admin only) ───
@router.get("/pendientes-activacion/count")
def contar_alumnos_pendientes(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    count = db.query(Usuario).filter(
        Usuario.rol == RolUsuario.alumno,
        Usuario.estado == "pendiente_activacion",
        Usuario.tenant_id == current_user["tenant_id"],
    ).count()
    return {"count": count}


# ─── PUT /{alumno_id}/activar (admin only) ───
@router.put("/{alumno_id}/activar")
def activar_alumno(
    alumno_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    usuario = db.query(Usuario).filter(
        Usuario.id == alumno_id, Usuario.tenant_id == tenant_id
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    password_provisional = generar_password_provisional(8)
    usuario.password_hash = hash_password(password_provisional)
    usuario.activo = True
    usuario.estado = "activo"
    usuario.cambiar_password_al_login = True
    db.flush()

    # Detectar si es RENOVACIÓN: el alumno ya tenía al menos 1 suscripción a un
    # plan PAGO. Se cuentan las ACTIVAS y también las VENCIDAS, porque el caso
    # normal de renovación es que el plan pago anterior ya haya expirado.
    # Se EXCLUYE el plan "Prueba" del conteo: con el flujo de autoservicio un
    # alumno recién registrado ya nace con una suscripción ACTIVA a ese plan
    # (ver registrar_alumno_nuevo), por lo que sin este filtro el conteo daba
    # >0 y su PRIMERA activación se trataba como renovación (email equivocado).
    es_renovacion = db.query(Suscripcion).join(Plan, Suscripcion.plan_id == Plan.id).filter(
        Suscripcion.usuario_id == alumno_id,
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado.in_(("activo", "vencido")),
        Plan.nombre != "Prueba",
    ).count() > 0

    sus = db.query(Suscripcion).filter(
        Suscripcion.usuario_id == alumno_id,
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "pendiente"
    ).first()
    plan_nombre, cantidad_clases, fecha_vigencia = "Plan", 0, ""
    if sus:
        sus.estado = "activo"
        plan = db.query(Plan).filter(Plan.id == sus.plan_id).first()
        if plan:
            plan_nombre = plan.nombre
            cantidad_clases = plan.creditos if plan.creditos else 0
        if sus.fecha_expiracion:
            fecha_vigencia = formatear_fecha_es(sus.fecha_expiracion)
    db.commit()

    # ── Auditoría interna: activación de alumno (alta/cambio de estado) ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="usuario",
        entidad_id=usuario.id,
        detalle={"alumno_id": usuario.id, "estado": "activo", "es_renovacion": es_renovacion},
    )

    email_enviado = False
    email_error = ""
    try:
        if es_renovacion:
            # RENOVACION -> Email 6: confirmacion de renovacion
            send_confirmacion_renovacion_plan(
                usuario.nombre,
                usuario.correo,
                plan_nombre,
                cantidad_clases,
                fecha_vigencia,
                url_frontend("/alumno/dashboard"),
            )
        else:
            # PRIMERA ACTIVACION -> Email 2: bienvenida con credenciales + resumen
            send_bienvenida_activacion(
                usuario.nombre,
                usuario.correo,
                password_provisional,
                plan_nombre,
                cantidad_clases,
                fecha_vigencia,
                url_frontend("/login"),
                tenant_id=usuario.tenant_id,
            )
        email_enviado = True
    except Exception as e:
        # No se silencia: la UI necesita el dato para mostrarle la contrasena
        # provisional al admin (si el correo no sale, el alumno queda activo sin
        # credenciales y nadie se enteraba).
        email_error = str(e)[:200]
        logging.getLogger("uvicorn.alumnos").warning(
            "Fallo al enviar email de activacion (alumno %s): %s", usuario.id, e)

    return {
        "ok": True,
        "mensaje": "Alumno activado",
        "password_provisional": password_provisional,
        "es_renovacion": es_renovacion,
        "plan_nombre": plan_nombre,
        "email_enviado": email_enviado,
        "email_error": email_error,
    }


# ─── PUT /{alumno_id}/rechazar (admin only) ───
@router.put("/{alumno_id}/rechazar")
def rechazar_alumno(
    alumno_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    usuario = db.query(Usuario).filter(
        Usuario.id == alumno_id, Usuario.tenant_id == tenant_id
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    usuario.estado = "rechazado"
    usuario.activo = False
    db.commit()

    # ── Auditoría interna: rechazo de registro de alumno ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="usuario",
        entidad_id=usuario.id,
        detalle={"alumno_id": usuario.id, "estado": "rechazado"},
    )
    return {"ok": True, "mensaje": "Solicitud rechazada"}


# ─── GET /me (alumno autenticado) ───
@router.get("/me")
def obtener_mi_perfil(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Perfil del usuario autenticado (requiere token JWT)."""
    uid = current_user.get("usuario_id")
    usuario = db.query(Usuario).filter(
        Usuario.id == uid,
        Usuario.tenant_id == current_user.get("tenant_id"),
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return _serializar_mi_perfil(usuario)


# ─── PUT /me (el usuario edita su PROPIO perfil) ───
# Endpoint correcto para Ajustes del alumno: el CRUD /usuarios/{id} es
# admin-only por diseño. Acá sólo se editan los campos de perfil que el alumno
# autogestiona (telefono/peso_kg/estatura_cm); `nombre`, `correo`, `genero` y
# `fecha_nacimiento` los gestiona el box vía `PUT /usuarios/{id}` (N-1: si
# llegan, se descartan — ver `ActualizarMiPerfil`). NO se puede tocar
# rol/activo/estado/password.
@router.put("/me")
def actualizar_mi_perfil(
    datos: ActualizarMiPerfil,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Actualiza el perfil del usuario autenticado (solo campos autogestionados)."""
    uid = current_user.get("usuario_id")
    tenant_id = current_user.get("tenant_id")
    usuario = db.query(Usuario).filter(
        Usuario.id == uid,
        Usuario.tenant_id == tenant_id,
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    update_data = datos.model_dump(exclude_unset=True)

    # 🔒 N-1 (defensa en profundidad): los campos de identidad/ficha nunca se
    # aplican desde este endpoint, aunque el schema los aceptara. El alumno no
    # cambia su propia identidad ni sus datos administrativos: eso es del box
    # (`PUT /usuarios/{id}`, admin-only). El valor de `rol` no interviene: el
    # único cliente de este endpoint es el Ajustes del alumno (y el descarte ya
    # ocurrió al validar, con log), así que la regla es la misma para todos.
    for campo_solo_box in ActualizarMiPerfil.CAMPOS_SOLO_BOX:
        update_data.pop(campo_solo_box, None)

    # Correo: único dentro del tenant (mismo criterio que el CRUD admin).
    # ⚠️ Hoy es código DEFENSIVO: `correo` viene en CAMPOS_SOLO_BOX, así que
    # `update_data` nunca lo trae. Se mantiene por si el campo se rehabilita.
    nuevo_correo = update_data.get("correo")
    if nuevo_correo is not None and nuevo_correo != usuario.correo:
        duplicado = db.query(Usuario).filter(
            Usuario.tenant_id == tenant_id,
            Usuario.correo == nuevo_correo,
            Usuario.id != uid,
        ).first()
        if duplicado:
            raise HTTPException(
                status_code=400,
                detail=f"Ya existe otro usuario con el correo {nuevo_correo} en este box",
            )

    for field, value in update_data.items():
        setattr(usuario, field, value)

    db.commit()
    db.refresh(usuario)
    return _serializar_mi_perfil(usuario)


# ─── GET /me/es-prueba (alumno autenticado) ───
@router.get("/me/es-prueba")
def es_prueba(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """True si el alumno tiene una suscripción ACTIVA del plan 'Prueba'.

    Comparte criterio con la dependency `require_full_access` (misma lógica).
    """
    uid = current_user.get("usuario_id")
    return {"es_prueba": es_usuario_prueba(db, uid)}


# ─── POST /me/primera-clase (alumno autenticado) ───
@router.post("/me/primera-clase")
def marcar_primera_clase(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    uid = current_user.get("usuario_id")
    sus = db.query(Suscripcion, Plan).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.usuario_id == uid,
        Suscripcion.estado == "activo",
        Plan.nombre == "Prueba"
    ).first()
    if not sus:
        raise HTTPException(status_code=404, detail="No tienes plan de prueba activo")
    sus[1].primera_clase_tomada = True
    db.commit()
    return {"ok": True, "mensaje": "Primera clase marcada"}
