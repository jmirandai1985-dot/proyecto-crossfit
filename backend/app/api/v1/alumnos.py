"""Router de endpoints para el flujo de registro/activación de alumnos."""
import re
import string
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.plan import Plan
from app.models.suscripcion import Suscripcion
from app.api.v1.usuarios import hash_password
from app.core.dependencies import get_current_user, get_current_admin
from app.services.email_service import (
    enviar_email_solicitud_admin, enviar_email_activacion_alumno
)

router = APIRouter()


def validar_rut(rut: str) -> bool:
    """Valida RUT chileno con dígito verificador (módulo 11)."""
    rut = (rut or "").strip().upper().replace(".", "")
    if not re.match(r"^\d{1,8}-[0-9K]$", rut):
        return False
    cuerpo, dv = rut.split("-")
    suma = 0
    multiplo = 2
    for d in reversed(cuerpo):
        suma += int(d) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1
    resto = suma % 11
    dv_calc = 11 - resto
    if dv_calc == 11:
        dv_calc = 0
    elif dv_calc == 10:
        dv_calc = "K"
    return str(dv_calc) == dv


def generar_password_provisional(longitud=8) -> str:
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(longitud))


class RegistroAlumnoNuevo(BaseModel):
    nombre: str
    correo: EmailStr
    sexo: Optional[str] = None
    peso: Optional[float] = None
    estatura: Optional[float] = None
    rut: str
    tenant_id: int = 1


# ─── POST /registro/alumno-nuevo (público) ───
@router.post("/registro/alumno-nuevo", status_code=status.HTTP_201_CREATED)
def registrar_alumno_nuevo(
    datos: RegistroAlumnoNuevo,
    db: Session = Depends(get_db)
):
    """Registro público: valida correo/RUT únicos, crea el usuario en estado
    pendiente_activacion y una suscripción de prueba."""
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

    password_tmp = generar_password_provisional(10)
    usuario = Usuario(
        tenant_id=datos.tenant_id,
        rut=datos.rut.strip().upper(),
        nombre=datos.nombre.strip(),
        telefono=None,
        correo=datos.correo.lower(),
        password_hash=hash_password(password_tmp),
        rol=RolUsuario.alumno,
        activo=False,
        estado="pendiente_activacion",
        cambiar_password_al_login=True,
        peso_kg=datos.peso,
        estatura_cm=int(datos.estatura) if datos.estatura else None,
        genero=datos.sexo,
    )
    db.add(usuario)
    db.flush()

    suscripcion = Suscripcion(
        tenant_id=datos.tenant_id,
        usuario_id=usuario.id,
        plan_id=plan_prueba.id,
        estado="pendiente",
        creditos_totales=1,
        creditos_disponibles=1,
        fecha_expiracion=datetime.utcnow() + timedelta(days=7),
    )
    db.add(suscripcion)
    db.commit()

    try:
        enviar_email_solicitud_admin({
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "id": usuario.id,
        })
    except Exception:
        pass

    return {"mensaje": "Registro exitoso, admin revisará"}


# ─── GET /pendientes-activacion (admin only) ───
@router.get("/pendientes-activacion")
def alumnos_pendientes(
    tenant_id: int = 1,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
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
    tenant_id: int = 1,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
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

    sus = db.query(Suscripcion).filter(
        Suscripcion.usuario_id == alumno_id,
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "pendiente"
    ).first()
    if sus:
        sus.estado = "activo"
    db.commit()

    try:
        enviar_email_activacion_alumno({
            "id": usuario.id,
            "nombre": usuario.nombre,
            "correo": usuario.correo,
        }, password_provisional)
    except Exception:
        pass

    return {"ok": True, "mensaje": "Alumno activado y credenciales enviadas"}


# ─── PUT /{alumno_id}/rechazar (admin only) ───
@router.put("/{alumno_id}/rechazar")
def rechazar_alumno(
    alumno_id: int,
    tenant_id: int = 1,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    usuario = db.query(Usuario).filter(
        Usuario.id == alumno_id, Usuario.tenant_id == tenant_id
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    usuario.estado = "rechazado"
    usuario.activo = False
    db.commit()
    return {"ok": True, "mensaje": "Solicitud rechazada"}


# ─── GET /me/es-prueba (alumno autenticado) ───
@router.get("/me/es-prueba")
def es_prueba(
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
    return {"es_prueba": sus is not None}


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
        raise HTTPException(status_code=404, detail="No tenés plan de prueba activo")
    sus[1].primera_clase_tomada = True
    db.commit()
    return {"ok": True, "mensaje": "Primera clase marcada"}
