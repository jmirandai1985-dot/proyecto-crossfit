"""
Router de endpoints para gestión de Disciplinas
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.models.disciplina import Disciplina
from app.schemas.disciplina import DisciplinaCreate, DisciplinaUpdate
from app.core.dependencies import get_current_admin, get_current_user
from app.services.auditoria_service import registrar_auditoria
# Auditoría 1.1: un choque de UNIQUE/FK/CHECK es un 400/409 del cliente, no un 500.
from app.utils.db_commit import commit_o_4xx

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
def crear_disciplina(
    datos: DisciplinaCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    nombre_limpio = datos.nombre.strip()
    if not nombre_limpio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre de la disciplina es obligatorio",
        )
    existing = db.query(Disciplina).filter(
        Disciplina.tenant_id == tenant_id,
        Disciplina.nombre == nombre_limpio
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe la disciplina '{nombre_limpio}' en este box"
        )

    db_disciplina = Disciplina(
        tenant_id=tenant_id,
        nombre=nombre_limpio,
        descripcion=(datos.descripcion or "").strip() or None,
        es_open_box=datos.es_open_box,
        requiere_coach=datos.requiere_coach,
        activo=datos.activo,
        tipo_formulario=datos.tipo_formulario,
    )
    db.add(db_disciplina)
    commit_o_4xx(
        db,
        "No se pudo crear la disciplina: revisa el nombre.",
        unico=f"Ya existe la disciplina '{nombre_limpio}' en este box.",
        contexto="crear_disciplina",
    )
    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="crear_disciplina",
        entidad="disciplina",
        entidad_id=db_disciplina.id,
        detalle={
            "nombre": db_disciplina.nombre,
            "descripcion": db_disciplina.descripcion,
            "es_open_box": db_disciplina.es_open_box,
            "requiere_coach": db_disciplina.requiere_coach,
            "activo": db_disciplina.activo,
            "tipo_formulario": db_disciplina.tipo_formulario,
        },
    )
    # `registrar_auditoria` commitea y expira el objeto: refresh para que la
    # respuesta no salga vacía (mismo detalle que documenta horarios.py).
    db.refresh(db_disciplina)
    return db_disciplina


@router.get("/")
def listar_disciplinas(
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    query = db.query(Disciplina).filter(Disciplina.tenant_id == tenant_id)
    if activo is not None:
        query = query.filter(Disciplina.activo == activo)
    return query.offset(skip).limit(limit).all()


@router.get("/{disciplina_id}")
def obtener_disciplina(
    disciplina_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 🔒 SEGURIDAD: scoping por tenant del token.
    tenant_id = current_user["tenant_id"]
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id,
        Disciplina.tenant_id == tenant_id,
    ).first()
    if not disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disciplina {disciplina_id} no encontrada"
        )
    return disciplina


@router.put("/{disciplina_id}")
def actualizar_disciplina(
    disciplina_id: int,
    datos: DisciplinaUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id,
        Disciplina.tenant_id == tenant_id,
    ).first()
    if not disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disciplina {disciplina_id} no encontrada"
        )
    antes = {
        "nombre": disciplina.nombre,
        "descripcion": disciplina.descripcion,
        "es_open_box": disciplina.es_open_box,
        "requiere_coach": disciplina.requiere_coach,
        "activo": disciplina.activo,
        "tipo_formulario": disciplina.tipo_formulario,
    }

    if datos.nombre is not None:
        nombre_limpio = datos.nombre.strip()
        if not nombre_limpio:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El nombre de la disciplina es obligatorio",
            )
        disciplina.nombre = nombre_limpio
    if datos.descripcion is not None:
        disciplina.descripcion = datos.descripcion.strip() or None
    if datos.es_open_box is not None:
        disciplina.es_open_box = datos.es_open_box
    if datos.requiere_coach is not None:
        disciplina.requiere_coach = datos.requiere_coach
    if datos.activo is not None:
        disciplina.activo = datos.activo
    if datos.tipo_formulario is not None:
        disciplina.tipo_formulario = datos.tipo_formulario

    despues = {
        "nombre": disciplina.nombre,
        "descripcion": disciplina.descripcion,
        "es_open_box": disciplina.es_open_box,
        "requiere_coach": disciplina.requiere_coach,
        "activo": disciplina.activo,
        "tipo_formulario": disciplina.tipo_formulario,
    }
    cambios = {
        campo: {"antes": antes[campo], "despues": despues[campo]}
        for campo in antes if antes[campo] != despues[campo]
    }

    commit_o_4xx(
        db,
        "No se pudo actualizar la disciplina: revisa los datos enviados.",
        unico=f"Ya existe otra disciplina llamada '{disciplina.nombre}' en este box.",
        contexto="actualizar_disciplina",
    )
    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="actualizar_disciplina",
        entidad="disciplina",
        entidad_id=disciplina.id,
        detalle={"campos": sorted(cambios), "cambios": cambios},
    )
    # `registrar_auditoria` commitea y expira el objeto: refresh antes de responder.
    db.refresh(disciplina)
    return disciplina


@router.delete("/{disciplina_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_disciplina(
    disciplina_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    disciplina = db.query(Disciplina).filter(
        Disciplina.id == disciplina_id,
        Disciplina.tenant_id == tenant_id,
    ).first()
    if not disciplina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disciplina {disciplina_id} no encontrada"
        )
    # 🔒 Verificar que la disciplina pertenezca al tenant del admin
    if disciplina.tenant_id != current_user.get("tenant_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esta disciplina",
        )
    activo_antes = disciplina.activo
    disciplina.activo = False
    commit_o_4xx(
        db,
        "No se pudo desactivar la disciplina. Intenta de nuevo.",
        contexto="eliminar_disciplina",
    )
    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="desactivar_disciplina",
        entidad="disciplina",
        entidad_id=disciplina.id,
        detalle={
            "nombre": disciplina.nombre,
            "activo": {"antes": activo_antes, "despues": False},
        },
    )
    return None
