"""
Router de endpoints para gestión de Planes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from typing import Literal, Optional

from app.db.database import get_db
from app.models.plan import Plan
from app.core.dependencies import get_current_admin, get_current_user
from app.core.estados import vigente_hoy   # vigencia por DÍA CHILENO (no por instante)
from app.utils.santiago import dias_para_vencer
# Auditoría 1.1: un choque de UNIQUE/FK/CHECK es un 400/409 del cliente, no un 500.
from app.utils.db_commit import commit_o_4xx

router = APIRouter()


# ── Los campos del plan viajan en el BODY (JSON), no en query params ──────────
# El panel manda `api.post('/planes', payload)` / `api.put('/planes/{id}', payload)`
# (body JSON de axios). Con los campos declarados SUELTOS, FastAPI los lee como
# QUERY PARAMS: el POST moría con 400 ("revisa el nombre...") y el PUT devolvía 200
# sin aplicar NADA (edición silenciosa). Es el mismo bug que se corrigió en
# `horarios` (tests/test_horarios_body_json.py). Estos modelos lo cierran.
#
# `extra="forbid"`: una clave desconocida falla con 422 en vez de ignorarse.
# En el PUT, `model_fields_set` distingue "no lo mandó" (no cambiar) de
# "lo mandó en null" (limpiar): `genero: null` = plan UNISEX y
# `plan_referencia_id: null` = sin comparación de ahorro.
class PlanCreate(BaseModel):
    """Cuerpo del POST /planes."""

    nombre: str = Field(min_length=1, max_length=100)
    precio_clp: int = Field(ge=0)
    duracion_dias: int = Field(30, ge=1, le=3650)
    creditos: Optional[int] = Field(None, ge=0)
    es_ilimitado: bool = False
    # `null` = plan UNISEX (sin género): es la categoría "Larga duración" del panel
    # y lo que ve el alumno en "Planes extendidos".
    genero: Optional[Literal["masculino", "femenino"]] = None
    es_estudiante: bool = False
    requiere_certificado_estudiante: bool = False
    # Comparación de ahorro contra un mensual del mismo box (null = sin comparación).
    plan_referencia_id: Optional[int] = None
    activo: Optional[bool] = None
    # El tenant SIEMPRE sale del token. Se acepta e ignora por compatibilidad con
    # el panel anterior (mandaba `tenant_id` al crear).
    tenant_id: Optional[int] = None

    model_config = ConfigDict(extra="forbid")


class PlanUpdate(BaseModel):
    """Cuerpo del PUT /planes/{id}: todo opcional (lo que no viene no se toca)."""

    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    precio_clp: Optional[int] = Field(None, ge=0)
    duracion_dias: Optional[int] = Field(None, ge=1, le=3650)
    creditos: Optional[int] = Field(None, ge=0)
    es_ilimitado: Optional[bool] = None
    genero: Optional[Literal["masculino", "femenino"]] = None
    es_estudiante: Optional[bool] = None
    requiere_certificado_estudiante: Optional[bool] = None
    plan_referencia_id: Optional[int] = None
    activo: Optional[bool] = None
    tenant_id: Optional[int] = None

    model_config = ConfigDict(extra="forbid")


def _referencia_valida(db: Session, tenant_id: int, plan_id: Optional[int],
                       referencia_id: Optional[int]) -> Optional[int]:
    """Valida el plan de comparación: del MISMO box y distinto de sí mismo.

    `None` (o 0) = sin comparación. Un id de otro box se responde 400 (no 404):
    el admin no tiene que distinguir "no existe" de "es de otro box".
    """
    if not referencia_id:
        return None
    if plan_id is not None and int(referencia_id) == int(plan_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un plan no puede compararse consigo mismo.",
        )
    referencia = db.query(Plan).filter(
        Plan.id == referencia_id, Plan.tenant_id == tenant_id).first()
    if referencia is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El plan de referencia no existe en este box.",
        )
    return referencia.id



@router.post("", status_code=status.HTTP_201_CREATED)
def crear_plan(
    data: PlanCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea un nuevo plan. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (el del body se ignora).
    tenant_id = current_user["tenant_id"]
    nombre = (data.nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="El nombre del plan no puede quedar vacío.")
    existing = db.query(Plan).filter(
        Plan.tenant_id == tenant_id,
        Plan.nombre == nombre
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe el plan '{nombre}' en este box"
        )

    db_plan = Plan(
        tenant_id=tenant_id,
        nombre=nombre,
        precio_clp=data.precio_clp,
        creditos=data.creditos,
        es_ilimitado=data.es_ilimitado,
        genero=data.genero,
        es_estudiante=data.es_estudiante,
        # `requiere_certificado_estudiante` y `es_estudiante` llegan derivados del
        # panel (fuente única: "es plan de estudiante"); se acepta cualquiera de
        # los dos para que un cliente viejo no deje el plan a medias.
        requiere_certificado_estudiante=bool(
            data.requiere_certificado_estudiante or data.es_estudiante),
        duracion_dias=data.duracion_dias,
        activo=True if data.activo is None else bool(data.activo),
        plan_referencia_id=_referencia_valida(
            db, tenant_id, None, data.plan_referencia_id),
    )
    db.add(db_plan)
    commit_o_4xx(
        db,
        "No se pudo crear el plan: revisa el nombre, el precio y la duración.",
        unico=f"Ya existe el plan '{nombre}' en este box.",
        contexto="crear_plan",
    )
    db.refresh(db_plan)
    return db_plan


@router.get("")
def listar_planes(
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    activo: Optional[bool] = None,
    genero: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lista planes del tenant (el tenant se deriva del JWT, no del query)"""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    query = db.query(Plan).filter(Plan.tenant_id == tenant_id)
    if activo is not None:
        query = query.filter(Plan.activo == activo)
    if genero is not None:
        query = query.filter(Plan.genero == genero)
    return query.offset(skip).limit(limit).all()


@router.get("/membresia-activa")
def obtener_membresia_activa(
    tenant_id: Optional[int] = None,
    alumno_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna la membresía activa del alumno autenticado (suscripción vigente).

    🔒 SEGURIDAD: tenant_id y alumno_id se derivan del JWT; los parámetros
    de query se ignoran (cerraba IDOR que exponía el saldo de tokens de
    cualquier alumno).
    """
    from app.models.suscripcion import Suscripcion
    from app.models.solicitud_plan import SolicitudPlan

    tenant_id = current_user["tenant_id"]
    alumno_id = current_user["usuario_id"]

    # ── "Plan en cola": pagado y aprobado, esperando a que termine el actual ──
    # El Dashboard lo usa para NO mostrar el banner de renovación (el próximo
    # plan ya está pago). Se consulta aparte porque NO es una suscripción activa.
    plan_en_cola = (db.query(SolicitudPlan)
                    .filter(SolicitudPlan.tenant_id == tenant_id,
                            SolicitudPlan.alumno_id == alumno_id,
                            SolicitudPlan.estado == "en_cola")
                    .first() is not None)

    # Vigencia por DÍA CHILENO: el plan vale hasta las 23:59:59 de su último día (el 30/09 un
    # plan de septiembre sigue vigente). El `> datetime.now(timezone.utc)` de antes lo cortaba
    # a las 20:59 CLT del último día y dependía de la TZ del proceso.
    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id == alumno_id,
        Suscripcion.estado == 'activo',
        vigente_hoy(Suscripcion.fecha_expiracion)
    ).order_by(Suscripcion.creditos_disponibles.desc().nulls_last(), Suscripcion.fecha_expiracion.desc()).first()

    if not suscripcion:
        return {"activa": False, "plan_nombre": None, "dias_restantes": 0, "clases_disponibles": 0, "clases_totales": None, "es_ilimitado": False, "fecha_vencimiento": None, "plan_en_cola": plan_en_cola}

    plan = db.query(Plan).filter(Plan.id == suscripcion.plan_id).first()
    # 0 = vence HOY (día de vencimiento inclusive) y sin fecha = 0: nunca negativo.
    dias_restantes = dias_para_vencer(suscripcion.fecha_expiracion) or 0

    return {
        "activa": True,
        "plan_nombre": plan.nombre if plan else None,
        "dias_restantes": dias_restantes,
        "clases_disponibles": suscripcion.creditos_disponibles if hasattr(suscripcion, 'creditos_disponibles') else 0,
        "clases_totales": suscripcion.creditos_totales if hasattr(suscripcion, 'creditos_totales') else None,
        "es_ilimitado": plan.es_ilimitado if plan else False,
        "fecha_vencimiento": suscripcion.fecha_expiracion,
        "plan_en_cola": plan_en_cola,
    }


@router.get("/{plan_id}")
def obtener_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Obtiene un plan por su ID (scoped al tenant del token)"""
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    plan = db.query(Plan).filter(
        Plan.id == plan_id,
        Plan.tenant_id == tenant_id,
    ).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {plan_id} no encontrado"
        )
    return plan


@router.put("/{plan_id}")
def actualizar_plan(
    plan_id: int,
    data: PlanUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Actualiza un plan existente. Solo admin (tenant del token).

    Sólo se tocan los campos que VIENEN en el body (`model_fields_set`), así un
    `null` explícito limpia (`genero`, `plan_referencia_id`) y un campo ausente no
    cambia nada.
    """
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    plan = db.query(Plan).filter(
        Plan.id == plan_id,
        Plan.tenant_id == tenant_id,
    ).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {plan_id} no encontrado"
        )

    campos = data.model_fields_set

    if "nombre" in campos:
        nombre = (data.nombre or "").strip()
        if not nombre:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El nombre del plan no puede quedar vacío.",
            )
        plan.nombre = nombre
    if "precio_clp" in campos:
        plan.precio_clp = data.precio_clp
    if "creditos" in campos:
        # `null` se guarda como NULL (mismo contrato que la columna); el panel
        # manda siempre un número, salvo el caso "ilimitado".
        plan.creditos = data.creditos
    if "es_ilimitado" in campos:
        plan.es_ilimitado = data.es_ilimitado
    if "duracion_dias" in campos:
        plan.duracion_dias = data.duracion_dias
    if "activo" in campos:
        plan.activo = data.activo
    if "genero" in campos:
        # `null` = plan UNISEX (categoría "Larga duración").
        plan.genero = data.genero
    if "es_estudiante" in campos:
        plan.es_estudiante = data.es_estudiante
    if "requiere_certificado_estudiante" in campos:
        plan.requiere_certificado_estudiante = data.requiere_certificado_estudiante
    if "plan_referencia_id" in campos:
        plan.plan_referencia_id = _referencia_valida(
            db, tenant_id, plan.id, data.plan_referencia_id)

    commit_o_4xx(
        db,
        "No se pudo actualizar el plan: revisa los datos enviados.",
        unico="Ya existe otro plan con ese nombre en este box.",
        contexto="actualizar_plan",
    )
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Desactiva un plan (soft delete). Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    plan = db.query(Plan).filter(
        Plan.id == plan_id,
        Plan.tenant_id == tenant_id,
    ).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {plan_id} no encontrado"
        )
    plan.activo = False
    commit_o_4xx(
        db,
        "No se pudo desactivar el plan. Intenta de nuevo.",
        contexto="eliminar_plan",
    )
    return None
