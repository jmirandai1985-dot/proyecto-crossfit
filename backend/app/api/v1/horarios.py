"""
Router de endpoints para gestión de Horarios
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.db.database import get_db
from app.models.horario_base import HorarioBase
from app.models.disciplina import Disciplina
from sqlalchemy import text
from app.core.dependencies import get_current_admin, get_current_user, get_current_coach
from app.services import asignaciones_clases as asignaciones
from app.services.auditoria_service import registrar_auditoria
from app.utils.santiago import hoy_santiago   # HOY en Chile (la TZ del proceso es UTC)

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_horario(
    tenant_id: Optional[int] = None,
    disciplina_id: int = None,
    dia_semana: int = None,
    hora_inicio: str = None,
    hora_fin: str = None,
    cupo_maximo: int = 16,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    db_horario = HorarioBase(
        tenant_id=tenant_id,
        disciplina_id=disciplina_id,
        dia_semana=dia_semana,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        cupo_maximo=cupo_maximo,
        activo=True
    )
    db.add(db_horario)
    db.commit()
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
    dia_semana: Optional[int] = None,
    hora_inicio: Optional[str] = None,
    hora_fin: Optional[str] = None,
    cupo_maximo: Optional[int] = None,
    activo: Optional[bool] = None,
    disciplina_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Actualiza una plantilla de horario (admin).

    B6 · `disciplina_id`: si se CAMBIA la disciplina de la plantilla, se suelta al
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
    if dia_semana is not None:
        horario.dia_semana = dia_semana
    if hora_inicio is not None:
        horario.hora_inicio = hora_inicio
    if hora_fin is not None:
        horario.hora_fin = hora_fin
    if cupo_maximo is not None:
        horario.cupo_maximo = cupo_maximo
    if activo is not None:
        horario.activo = activo

    # ── B6: cambio de disciplina de la plantilla ──
    cambio_disciplina = (
        disciplina_id is not None and disciplina_id != horario.disciplina_id)
    vigencia_cerrada = False
    clases_liberadas = 0
    if disciplina_id is not None:
        nueva = db.query(Disciplina).filter(
            Disciplina.id == disciplina_id,
            Disciplina.tenant_id == tenant_id,
        ).first()
        if not nueva:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La disciplina no existe o no pertenece a este box",
            )
        horario.disciplina_id = disciplina_id

    if cambio_disciplina:
        hoy = hoy_santiago()
        vigencia = asignaciones.coach_vigente(db, tenant_id, horario.id)
        if vigencia:
            asignaciones.cerrar_vigencia(vigencia, hoy)
            vigencia_cerrada = True
        clases_liberadas = asignaciones.liberar_clases_futuras_de_horario(
            db, tenant_id, horario.id, hoy)

    db.commit()
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
    db.commit()
    return None
