"""
Router de endpoints para gestión de Horarios
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.db.database import get_db
from app.models.horario_base import HorarioBase
from app.models.disciplina import Disciplina
from app.core.dependencies import get_current_admin, get_current_user
from app.services import asignaciones_clases as asignaciones
from app.services.auditoria_service import registrar_auditoria
from app.utils.santiago import hoy_santiago   # HOY en Chile (la TZ del proceso es UTC)
# Auditoría 1.1: un choque de UNIQUE/FK/CHECK es un 400/409 del cliente, no un 500.
from app.utils.db_commit import commit_o_4xx

router = APIRouter()


# ── Body JSON de crear/editar horario ───────────────────────────────────────
# POR QUÉ EXISTEN: los campos estaban declarados como parámetros SUELTOS de la
# función. En FastAPI un `int`/`str`/`bool` suelto (sin `Body()` ni un modelo
# Pydantic) se lee como QUERY PARAM, no del body. El panel manda
# `api.post('/api/v1/horarios', payload)` (body JSON de axios), así que el
# backend recibía `disciplina_id = None`, el `if not disc` daba 404 "La
# disciplina no existe o no pertenece a este box" SIEMPRE, y el PUT (todo
# Optional) se quedaba con todos los `None` = "no cambiar nada" y no aplicaba
# ningún cambio, en silencio. Con un modelo de body el campo viaja donde el
# navegador lo manda.
class HorarioCreate(BaseModel):
    """Body de POST /horarios (crear plantilla de horario)."""
    disciplina_id: int = Field(..., description="ID de la disciplina del box")
    dia_semana: int = Field(..., description="0=Lunes … 6=Domingo")
    hora_inicio: str = Field(..., description="Hora de inicio HH:MM")
    hora_fin: str = Field(..., description="Hora de fin HH:MM")
    # Musculación / Open Box lo ignoran (migración 066: cupo NULL = sin tope).
    cupo_maximo: int = Field(16, description="Cupo máximo (se ignora si es acceso libre)")


class HorarioUpdate(BaseModel):
    """Body de PUT /horarios/{id}. `None` = ese campo no se toca."""
    dia_semana: Optional[int] = None
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    cupo_maximo: Optional[int] = None
    activo: Optional[bool] = None
    disciplina_id: Optional[int] = None


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_horario(
    body: HorarioCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    # ── Migración 066: una disciplina de acceso libre no tiene cupo ──────────
    # `es_open_box` (Musculación / Open Box) = sala libre: la plantilla se crea
    # con `cupo_maximo = NULL` (sin tope), aunque el cliente mande un número.
    disc = db.query(Disciplina).filter(
        Disciplina.id == body.disciplina_id,
        Disciplina.tenant_id == tenant_id,
    ).first()
    if not disc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La disciplina no existe o no pertenece a este box",
        )
    db_horario = HorarioBase(
        tenant_id=tenant_id,
        disciplina_id=body.disciplina_id,
        dia_semana=body.dia_semana,
        hora_inicio=body.hora_inicio,
        hora_fin=body.hora_fin,
        cupo_maximo=None if disc.es_open_box else body.cupo_maximo,
        activo=True
    )
    db.add(db_horario)
    commit_o_4xx(
        db,
        "No se pudo crear el horario: revisa la disciplina, el día y las horas.",
        unico="Ya existe un horario igual para esa disciplina, día y hora.",
        contexto="crear_horario",
    )
    db.refresh(db_horario)
    return db_horario


@router.get("")
def listar_horarios(
    tenant_id: Optional[int] = None,
    dia_semana: Optional[int] = None,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    query = db.query(HorarioBase).filter(HorarioBase.tenant_id == tenant_id)
    if dia_semana is not None:
        query = query.filter(HorarioBase.dia_semana == dia_semana)
    if activo is not None:
        query = query.filter(HorarioBase.activo == activo)
    return query.order_by(HorarioBase.dia_semana, HorarioBase.hora_inicio).all()


# ── MUST be before /{horario_id} to avoid route collision ──
@router.get("/grid-semanal")
def grid_semanal(
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Devuelve horarios agrupados por (dia_semana, hora_inicio, hora_fin)
    con lista de disciplinas en cada celda. Para alimentar el grid Lun-Dom."""
    from sqlalchemy import text as sql_text
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    rows = db.execute(sql_text("""
        SELECT h.dia_semana, h.hora_inicio::text, h.hora_fin::text,
               MAX(h.cupo_maximo) as cupo_maximo,
               json_agg(json_build_object(
                   'id', h.id, 'disciplina_id', h.disciplina_id,
                   'disciplina_nombre', d.nombre,
                   'cupo_maximo', h.cupo_maximo,
                   'activo', h.activo
               ) ORDER BY d.nombre) as disciplinas
        FROM horarios h
        JOIN disciplinas d ON h.disciplina_id = d.id
        WHERE h.tenant_id = :tid AND h.activo = true
        GROUP BY h.dia_semana, h.hora_inicio, h.hora_fin
        ORDER BY h.dia_semana, h.hora_inicio
    """), {"tid": tenant_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/generar-clases-dia")
def generar_clases_dia_route(
    tenant_id: Optional[int] = None,
    fecha: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Genera clases desde horarios_base para una fecha. SOLO admin (tenant del token).

    H-15: antes lo podia llamar cualquier coach para cualquier fecha del box (escritura
    global, y `fecha` llegaba como string sin validar). La generacion normal ya corre
    por el startup y el scheduler diario; esta ruta queda como el boton explicito de Admin.
    """
    from app.services.generar_clases import generar_clases_para_fecha
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    # `fecha` llega ya validada como date (FastAPI responde 422 si el formato es invalido);
    # sin fecha se usa HOY en Chile (antes `date.today()`: el reloj del proceso, UTC en el
    # contenedor, adelantaba el dia entre las 21:00 y las 23:59 CLT).
    fecha_date = fecha or hoy_santiago()
    resultado = generar_clases_para_fecha(db, tenant_id, fecha_date)
    return resultado


@router.get("/{horario_id}")
def obtener_horario(
    horario_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    horario = db.query(HorarioBase).filter(
        HorarioBase.id == horario_id,
        HorarioBase.tenant_id == tenant_id,
    ).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado"
        )
    return horario


@router.put("/{horario_id}")
def actualizar_horario(
    horario_id: int,
    body: HorarioUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Actualiza una plantilla de horario (admin).

    B6 · `body.disciplina_id`: si se CAMBIA la disciplina de la plantilla, se suelta al
    coach que la tenía (se cierra la vigencia de `horarios_coach`) y se liberan las
    clases FUTURAS de ese horario: nadie queda a cargo de una disciplina que no
    dicta. Las clases YA generadas conservan su disciplina (no se reescriben: puede
    haber alumnos reservados); la disciplina nueva aplica a lo que se genere después.
    """
    horario = db.query(HorarioBase).filter(
        HorarioBase.id == horario_id).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado"
        )
    # 🔒 Verificar que el horario pertenezca al tenant del admin
    tenant_id = current_user["tenant_id"]
    if horario.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este horario",
        )
    if body.dia_semana is not None:
        horario.dia_semana = body.dia_semana
    if body.hora_inicio is not None:
        horario.hora_inicio = body.hora_inicio
    if body.hora_fin is not None:
        horario.hora_fin = body.hora_fin
    if body.cupo_maximo is not None:
        # Migración 066: las disciplinas de acceso libre (Musculación / Open Box)
        # NO tienen cupo. Fijarles un número volvería a inventar el placeholder
        # que esta migración sacó, así que es un 400 de negocio.
        efectiva = (body.disciplina_id if body.disciplina_id is not None
                    else horario.disciplina_id)
        disc_efectiva = db.query(Disciplina).filter(
            Disciplina.id == efectiva,
            Disciplina.tenant_id == tenant_id,
        ).first()
        if disc_efectiva is not None and disc_efectiva.es_open_box:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Musculación y Open Box son de acceso libre: no tienen "
                        "cupo máximo que configurar."),
            )
        horario.cupo_maximo = body.cupo_maximo
    if body.activo is not None:
        horario.activo = body.activo

    # ── B6: cambio de disciplina de la plantilla ──
    cambio_disciplina = (
        body.disciplina_id is not None
        and body.disciplina_id != horario.disciplina_id)
    vigencia_cerrada = False
    clases_liberadas = 0
    if body.disciplina_id is not None:
        nueva = db.query(Disciplina).filter(
            Disciplina.id == body.disciplina_id,
            Disciplina.tenant_id == tenant_id,
        ).first()
        if not nueva:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La disciplina no existe o no pertenece a este box",
            )
        horario.disciplina_id = body.disciplina_id
        # Si la plantilla pasa a una disciplina de acceso libre, el cupo que
        # tuviera deja de tener sentido: se limpia (migración 066).
        if nueva.es_open_box:
            horario.cupo_maximo = None

    if cambio_disciplina:
        hoy = hoy_santiago()
        vigencia = asignaciones.coach_vigente(db, tenant_id, horario.id)
        if vigencia:
            asignaciones.cerrar_vigencia(vigencia, hoy)
            vigencia_cerrada = True
        clases_liberadas = asignaciones.liberar_clases_futuras_de_horario(
            db, tenant_id, horario.id, hoy)

    commit_o_4xx(
        db,
        "No se pudo actualizar el horario: revisa los datos enviados.",
        unico="Ya existe otro horario igual para esa disciplina, día y hora.",
        contexto="actualizar_horario",
    )
    db.refresh(horario)

    if cambio_disciplina:
        registrar_auditoria(
            db,
            tenant_id=tenant_id,
            usuario_id=current_user["usuario_id"],
            accion="cambiar_disciplina_horario",
            entidad="horario",
            entidad_id=horario.id,
            detalle={
                "disciplina_id": horario.disciplina_id,
                "vigencia_cerrada": vigencia_cerrada,
                "clases_liberadas": clases_liberadas,
            },
        )
        # `registrar_auditoria` commitea y EXPIRA `horario`: sin este refresh la
        # respuesta salía `{}` (FastAPI serializa con los atributos ya cargados
        # del objeto) aunque el cambio SÍ había quedado guardado.
        db.refresh(horario)
    return horario


@router.delete("/{horario_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_horario(
    horario_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant del token (antes no filtraba por tenant).
    tenant_id = current_user["tenant_id"]
    horario = db.query(HorarioBase).filter(
        HorarioBase.id == horario_id,
        HorarioBase.tenant_id == tenant_id,
    ).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado"
        )
    horario.activo = False
    commit_o_4xx(
        db,
        "No se pudo desactivar el horario. Intenta de nuevo.",
        contexto="eliminar_horario",
    )
    return None
