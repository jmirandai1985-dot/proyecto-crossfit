"""
Router de endpoints para gestión de Historial RM
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from app.db.database import get_db
from app.core.dependencies import get_current_user, require_full_access
from app.services.auditoria_service import registrar_auditoria
from app.models.historial_rm import HistorialRM
from app.models.movimiento import Movimiento
from app.models.usuario import Usuario
from app.schemas.historial_rm import (
    HistorialRMCreate, HistorialRMUpdate, HistorialRMResponse, HistorialRMListItem, RMPorMovimiento
)
from app.services.nivel_service import (
    obtener_nivel_fuerza, obtener_nivel_gimnastico, calcular_nivel_general
)
from app.db.crossfit_ratios import CROSSFIT_RATIOS
from app.db.crossfit_habilidades import CROSSFIT_HABILIDADES
from app.services.nivel_service import NIVELES

# FIX 1: alumnos con plan de prueba NO pueden usar RM/Performance Hub/Evolución
router = APIRouter(dependencies=[Depends(require_full_access)])

# Roles con acceso de staff (pueden operar sobre datos de cualquier alumno del box)
ROLES_STAFF = ("coach", "admin", "administrador")

# Ventana de edición de PRs (regla de negocio): 24 horas desde su creación.
VENTANA_EDICION_PR_HORAS = 24


def _verificar_acceso_alumno(current_user: dict, alumno_id: int) -> None:
    """
    Solo el propio alumno (mismo tenant por token) o staff del box puede
    acceder a los datos de un alumno_id que no sea el suyo.
    """
    rol = current_user.get("rol", "")
    if rol in ROLES_STAFF:
        return
    if current_user.get("usuario_id") != alumno_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para acceder a los datos de otro alumno",
        )


def _verificar_ventana_edicion(created_at) -> None:
    """
    Regla de negocio: un PR solo puede editarse dentro de las 24 horas
    posteriores a su registro.
    """
    if created_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El registro no tiene fecha de creación; no se permite editarlo",
        )
    creado = created_at
    if creado.tzinfo is None:
        creado = creado.replace(tzinfo=timezone.utc)
    antiguedad = datetime.now(timezone.utc) - creado
    if antiguedad > timedelta(hours=VENTANA_EDICION_PR_HORAS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Edición no permitida: el PR se registró hace más de "
                f"{VENTANA_EDICION_PR_HORAS} horas. "
                "La edición solo está habilitada dentro de las 24h posteriores al registro."
            ),
        )


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_historial_rm(
    historial_data: HistorialRMCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Crea un nuevo registro de RM y calcula nivel automáticamente"""
    from app.models.movimiento import Movimiento

    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (nunca del body).
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    # 🔒 IDOR: un alumno solo puede registrar PRs para sí mismo.
    #        coach/admin pueden registrar en nombre de un alumno del mismo box.
    if rol not in ROLES_STAFF and historial_data.alumno_id != current_user["usuario_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes registrar un PR para otro alumno",
        )

    historial_data.tenant_id = tenant_id  # sobreescribe lo que venga del body

    # Verify movimiento existe
    movimiento = db.query(Movimiento).filter(
        Movimiento.id == historial_data.movimiento_id,
        Movimiento.tenant_id == historial_data.tenant_id
    ).first()
    if not movimiento:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")

    db_historial = HistorialRM(
        tenant_id=historial_data.tenant_id,
        alumno_id=historial_data.alumno_id,
        movimiento_id=historial_data.movimiento_id,
        peso_kg=historial_data.peso_kg,
        tipo_rm=historial_data.tipo_rm or "peso",
        valor_extra=historial_data.valor_extra,
        repeticiones=historial_data.repeticiones,
        series=historial_data.series,
        minutos=historial_data.minutos,
        vueltas=historial_data.vueltas,
        km=historial_data.km,
        calorias=historial_data.calorias,
        fecha=historial_data.fecha,
        notas=historial_data.notas
    )

    db.add(db_historial)
    db.commit()
    db.refresh(db_historial)

    # --- CALCULO AUTOMATICO DE NIVEL ---
    movimiento_nombre = movimiento.nombre
    nivel_resultado = None

    if movimiento_nombre in CROSSFIT_RATIOS:
        # Grupo A - Fuerza: necesita peso corporal y género
        alumno = db.query(Usuario).filter(
            Usuario.id == historial_data.alumno_id,
            Usuario.tenant_id == historial_data.tenant_id
        ).first()
        if alumno:
            result = obtener_nivel_fuerza(
                movimiento_nombre=movimiento_nombre,
                peso_rm=historial_data.peso_kg,
                peso_corporal=getattr(alumno, "peso_kg", None),
                genero=getattr(alumno, "genero", None)
            )
            if result.get("clasificable"):
                nivel_resultado = result["nivel"]
    elif movimiento_nombre in CROSSFIT_HABILIDADES:
        # Grupo B - Gimnástico
        alumno = db.query(Usuario).filter(
            Usuario.id == historial_data.alumno_id,
            Usuario.tenant_id == historial_data.tenant_id
        ).first()
        genero = getattr(alumno, "genero", None) if alumno else None
        valor_para_nivel = historial_data.peso_kg
        # Para ciertos movimientos gimnásticos, el valor se pasa directo
        result = obtener_nivel_gimnastico(
            movimiento_nombre=movimiento_nombre,
            valor=valor_para_nivel,
            genero=genero
        )
        if result.get("clasificable"):
            nivel_resultado = result["nivel"]

    if nivel_resultado:
        db_historial.nivel_calculado = nivel_resultado
        db.commit()
        db.refresh(db_historial)
    # --- FIN CALCULO AUTOMATICO ---

    return {
        "id": db_historial.id,
        "tenant_id": db_historial.tenant_id,
        "alumno_id": db_historial.alumno_id,
        "movimiento_id": db_historial.movimiento_id,
        "movimiento_nombre": movimiento.nombre,
        "peso_kg": db_historial.peso_kg,
        "tipo_rm": db_historial.tipo_rm,
        "valor_extra": db_historial.valor_extra,
        "repeticiones": db_historial.repeticiones,
        "series": db_historial.series,
        "minutos": db_historial.minutos,
        "vueltas": db_historial.vueltas,
        "km": db_historial.km,
        "calorias": db_historial.calorias,
        "fecha": str(db_historial.fecha),
        "notas": db_historial.notas,
        "nivel_calculado": db_historial.nivel_calculado,
        "created_at": str(db_historial.created_at),
        "updated_at": str(db_historial.updated_at),
    }


@router.get("/{historial_id}", response_model=HistorialRMResponse)
def obtener_historial_rm(
    historial_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Obtiene un registro de RM por su ID (solo el propio alumno o staff del box)"""
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    historial = db.query(HistorialRM).filter(
        HistorialRM.id == historial_id,
        HistorialRM.tenant_id == tenant_id
    ).first()

    if not historial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Historial RM con ID {historial_id} no encontrado"
        )

    _verificar_acceso_alumno(current_user, historial.alumno_id)

    return historial


@router.get("", response_model=List[HistorialRMListItem])
def listar_historial_rm(
    tenant_id: Optional[int] = None,
    alumno_id: Optional[int] = None,
    movimiento_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lista registros de RM con filtros opcionales (solo propios o staff)"""
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    # 🔒 IDOR: si se filtra por alumno, validar acceso.
    # Si no se filtra y el usuario es alumno, listar solo los propios.
    if alumno_id is not None:
        _verificar_acceso_alumno(current_user, alumno_id)
    elif rol not in ROLES_STAFF:
        alumno_id = current_user["usuario_id"]

    query = db.query(HistorialRM).filter(HistorialRM.tenant_id == tenant_id)

    if alumno_id is not None:
        query = query.filter(HistorialRM.alumno_id == alumno_id)

    if movimiento_id is not None:
        query = query.filter(HistorialRM.movimiento_id == movimiento_id)

    # ── Construir query con columnas explícitas ──
    # NOTA: Usamos with_entities() en vez de .add_columns() para evitar
    # el patrón frágil de desempaquetado de tupla (rm, mov_nombre = row)
    # que causó bugs previos en otros endpoints.
    from app.models.movimiento import Movimiento
    rows = query.with_entities(
        HistorialRM.id,
        HistorialRM.alumno_id,
        HistorialRM.movimiento_id,
        HistorialRM.peso_kg,
        HistorialRM.tipo_rm,
        HistorialRM.valor_extra,
        HistorialRM.repeticiones,
        HistorialRM.series,
        HistorialRM.minutos,
        HistorialRM.vueltas,
        HistorialRM.km,
        HistorialRM.calorias,
        HistorialRM.fecha,
        HistorialRM.notas,
        Movimiento.nombre.label('movimiento_nombre'),
    ).join(
        Movimiento, HistorialRM.movimiento_id == Movimiento.id, isouter=True
    ).order_by(HistorialRM.fecha.desc()).offset(
        skip).limit(limit).all()

    # ── Construir respuesta con acceso directo a columnas ──
    # Resultado son named tuples, cada columna es un atributo directo (row.columna)
    # NO hay anidamiento ni desempaquetado de tupla
    result = []
    for row in rows:
        result.append({
            "id": row.id,
            "alumno_id": row.alumno_id,
            "movimiento_id": row.movimiento_id,
            "peso_kg": row.peso_kg,
            "tipo_rm": row.tipo_rm,
            "valor_extra": row.valor_extra,
            "repeticiones": row.repeticiones,
            "series": row.series,
            "minutos": row.minutos,
            "vueltas": row.vueltas,
            "km": row.km,
            "calorias": row.calorias,
            "fecha": row.fecha,
            "notas": row.notas,
            "movimiento_nombre": row.movimiento_nombre,
        })
    return result


@router.get("/alumnos/{alumno_id}/rms", response_model=List[RMPorMovimiento])
def obtener_rms_alumno(
    alumno_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Obtiene el mejor RM por movimiento para un alumno (propio o staff del box).

    Para movimientos de FUERZA y GIMNASTICO se usa el criterio actual:
    mayor peso_kg (o mayor reps para gimnástico).

    Para movimientos de CARDIO y MAQUINAS (metabolico) no tiene sentido
    comparar por peso_kg (es un dummy), así que se usa el registro MÁS RECIENTE.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    _verificar_acceso_alumno(current_user, alumno_id)

    cols = [
        HistorialRM.movimiento_id,
        Movimiento.nombre.label('movimiento_nombre'),
        HistorialRM.peso_kg,
        HistorialRM.tipo_rm,
        HistorialRM.valor_extra,
        HistorialRM.repeticiones,
        HistorialRM.series,
        HistorialRM.minutos,
        HistorialRM.vueltas,
        HistorialRM.km,
        HistorialRM.calorias,
        HistorialRM.fecha,
        HistorialRM.notas,
    ]

    base_filter = [
        HistorialRM.alumno_id == alumno_id,
        HistorialRM.tenant_id == tenant_id,
    ]

    # --- Fuerza y Gimnástico: se elige por mayor peso_kg ---
    rms_fuerza = db.query(*cols).join(
        Movimiento, HistorialRM.movimiento_id == Movimiento.id
    ).filter(
        *base_filter,
        Movimiento.categoria.in_(['fuerza', 'gimnastico'])
    ).order_by(
        HistorialRM.movimiento_id,
        HistorialRM.peso_kg.desc()
    ).distinct(HistorialRM.movimiento_id).all()

    # --- Cardio y Máquinas (metabolico): se elige el REGISTRO MÁS RECIENTE ---
    # Usamos id.desc() como desempate para garantizar que sea el último creado
    rms_cardio = db.query(*cols).join(
        Movimiento, HistorialRM.movimiento_id == Movimiento.id
    ).filter(
        *base_filter,
        Movimiento.categoria.in_(['cardio', 'metabolico'])
    ).order_by(
        HistorialRM.movimiento_id,
        HistorialRM.fecha.desc(),
        HistorialRM.id.desc()
    ).distinct(HistorialRM.movimiento_id).all()

    rms = rms_fuerza + rms_cardio

    return [
        RMPorMovimiento(
            movimiento_id=rm[0],
            movimiento_nombre=rm[1],
            peso_kg=rm[2],
            tipo_rm=rm[3] or 'peso',
            valor_extra=rm[4],
            repeticiones=rm[5],
            series=rm[6],
            minutos=rm[7],
            vueltas=rm[8],
            km=rm[9],
            calorias=rm[10],
            fecha=rm[11],
            notas=rm[12]
        )
        for rm in rms
    ]


@router.put("/{historial_id}", response_model=HistorialRMResponse)
def actualizar_historial_rm(
    historial_id: int,
    historial_data: HistorialRMUpdate,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Actualiza un registro de RM existente.

    🔒 Seguridad:
    - tenant_id siempre del token JWT.
    - Solo el propio alumno o staff del mismo box puede editar.
    - Regla de negocio: la edición solo está permitida dentro de las 24h
      posteriores al registro (created_at).
    """
    # 🔒 SEGURIDAD: tenant_id del token.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    historial = db.query(HistorialRM).filter(
        HistorialRM.id == historial_id,
        HistorialRM.tenant_id == tenant_id
    ).first()

    if not historial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Historial RM con ID {historial_id} no encontrado"
        )

    # 🔒 IDOR: ownership (propio alumno o staff del mismo box)
    if rol not in ROLES_STAFF and historial.alumno_id != current_user["usuario_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes editar los PRs de otro alumno",
        )

    # ⏱ Regla de negocio: ventana de edición de 24 horas.
    _verificar_ventana_edicion(historial.created_at)

    update_data = historial_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(historial, field, value)

    db.commit()
    db.refresh(historial)

    # ── Auditoría interna: edición de PR ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="historial_rm",
        entidad_id=historial.id,
        detalle={
            "alumno_id": historial.alumno_id,
            "movimiento_id": historial.movimiento_id,
            "campos": sorted(update_data.keys()),
        },
    )

    return historial


@router.delete("/{historial_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_historial_rm(
    historial_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Elimina un registro de RM.

    🔒 Seguridad: solo el propio alumno o admin del mismo tenant.
    """
    # 🔒 SEGURIDAD: tenant_id del token.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    historial = db.query(HistorialRM).filter(
        HistorialRM.id == historial_id,
        HistorialRM.tenant_id == tenant_id
    ).first()

    if not historial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Historial RM con ID {historial_id} no encontrado"
        )

    # 🔒 IDOR: solo el propio alumno o admin del mismo box.
    if rol not in ("admin", "administrador") and historial.alumno_id != current_user["usuario_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes eliminar tus propios PRs (o ser administrador del box)",
        )

    db.delete(historial)
    db.commit()

    # ── Auditoría interna: borrado de PR ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="DELETE",
        entidad="historial_rm",
        entidad_id=historial_id,
        detalle={"alumno_id": historial.alumno_id, "movimiento_id": historial.movimiento_id},
    )

    return None


@router.post("/nivel-fuerza")
def calcular_nivel_fuerza_endpoint(
    alumno_id: int,
    movimiento_id: int,
    peso_rm: float,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Calcula el nivel de fuerza para un movimiento específico (propio o staff)"""
    # 🔒 SEGURIDAD: tenant_id del token + acceso al alumno.
    tenant_id = current_user["tenant_id"]
    _verificar_acceso_alumno(current_user, alumno_id)

    movimiento = db.query(Movimiento).filter(
        Movimiento.id == movimiento_id,
        Movimiento.tenant_id == tenant_id
    ).first()
    if not movimiento:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")

    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == tenant_id
    ).first()
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    return obtener_nivel_fuerza(
        movimiento_nombre=movimiento.nombre,
        peso_rm=peso_rm,
        peso_corporal=getattr(alumno, "peso_kg", None),
        genero=getattr(alumno, "genero", None)
    )


@router.post("/nivel-gimnastico")
def calcular_nivel_gimnastico_endpoint(
    alumno_id: int,
    movimiento_id: int,
    valor: float,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Calcula el nivel gimnástico para un movimiento específico (propio o staff)"""
    # 🔒 SEGURIDAD: tenant_id del token + acceso al alumno.
    tenant_id = current_user["tenant_id"]
    _verificar_acceso_alumno(current_user, alumno_id)

    movimiento = db.query(Movimiento).filter(
        Movimiento.id == movimiento_id,
        Movimiento.tenant_id == tenant_id
    ).first()
    if not movimiento:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")

    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == tenant_id
    ).first()

    genero = getattr(alumno, "genero", None) if alumno else None
    return obtener_nivel_gimnastico(movimiento.nombre, valor, genero)


@router.get("/alumnos/{alumno_id}/movimiento/{movimiento_id}")
def obtener_historial_movimiento(
    alumno_id: int,
    movimiento_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Obtiene el historial COMPLETO de un movimiento específico para un alumno,
    ordenado por fecha ascendente (para gráficos de evolución).
    Solo el propio alumno o staff del box.
    """
    from app.models.movimiento import Movimiento

    # 🔒 SEGURIDAD: tenant_id del token + acceso al alumno.
    tenant_id = current_user["tenant_id"]
    _verificar_acceso_alumno(current_user, alumno_id)

    movimiento = db.query(Movimiento).filter(
        Movimiento.id == movimiento_id,
        Movimiento.tenant_id == tenant_id
    ).first()
    if not movimiento:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")

    registros = db.query(HistorialRM).filter(
        HistorialRM.alumno_id == alumno_id,
        HistorialRM.tenant_id == tenant_id,
        HistorialRM.movimiento_id == movimiento_id
    ).order_by(HistorialRM.fecha.asc(), HistorialRM.id.asc()).all()

    return [
        {
            "id": r.id,
            "fecha": str(r.fecha),
            "peso_kg": r.peso_kg,
            "repeticiones": r.repeticiones,
            "series": r.series,
            "minutos": r.minutos,
            "vueltas": r.vueltas,
            "km": r.km,
            "calorias": r.calorias,
            "notas": r.notas,
            "movimiento_nombre": movimiento.nombre,
            "categoria": movimiento.categoria,
        }
        for r in registros
    ]


@router.get("/alumnos/{alumno_id}/nivel-general")
def obtener_nivel_general_endpoint(
    alumno_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Calcula el nivel general del alumno (fuerza y gimnástico). Propio o staff."""
    # 🔒 SEGURIDAD: tenant_id del token + acceso al alumno.
    tenant_id = current_user["tenant_id"]
    _verificar_acceso_alumno(current_user, alumno_id)
    return calcular_nivel_general(alumno_id, db, tenant_id)


@router.get("/alumnos/{alumno_id}/nivel-fuerza")
def obtener_nivel_fuerza_alumno(
    alumno_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Calcula el nivel de fuerza del alumno basado en sus RMs.
    Retorna el nivel general y los top RMs de movimientos de fuerza.
    Solo el propio alumno o staff del box.
    """
    # 🔒 SEGURIDAD: tenant_id del token + acceso al alumno.
    tenant_id = current_user["tenant_id"]
    _verificar_acceso_alumno(current_user, alumno_id)

    resultado = calcular_nivel_general(alumno_id, db, tenant_id)

    # Extraer top RMs de fuerza para mostrar en el dashboard
    top_rms = []
    for detalle in resultado.get("detalle_fuerza", []):
        if detalle.get("nivel") and detalle["nivel"] != "Sin datos":
            # Buscar el movimiento por nombre para obtener su ID
            movimiento = db.query(Movimiento).filter(
                Movimiento.nombre == detalle["movimiento"],
                Movimiento.tenant_id == tenant_id
            ).first()
            if movimiento:
                mejor = db.query(
                    func.max(HistorialRM.peso_kg)
                ).filter(
                    HistorialRM.alumno_id == alumno_id,
                    HistorialRM.tenant_id == tenant_id,
                    HistorialRM.movimiento_id == movimiento.id
                ).scalar()
                if mejor:
                    top_rms.append({
                        "movimiento": detalle["movimiento"],
                        "valor": f"{mejor:.0f} kg"
                    })

    return {
        "nivel": resultado.get("nivel_fuerza", "SIN DATOS"),
        "top_rms": top_rms[:3]  # Top 3
    }


@router.get("/alumnos/{alumno_id}/progreso-destacado")
def obtener_progreso_destacado(
    alumno_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna los movimientos con MEJOR progreso del alumno.
    Para cada movimiento con al menos 2 registros, calcula:
    - diferencia entre primer y último valor
    - periodo entre esos registros
    Retorna top 3 ordenados por mejora absoluta descendente.

    También retorna los movimiento_ids que tienen al menos 1 registro
    (para destacar en el dropdown del frontend).
    Solo el propio alumno o staff del box.
    """
    # 🔒 SEGURIDAD: tenant_id del token + acceso al alumno.
    tenant_id = current_user["tenant_id"]
    _verificar_acceso_alumno(current_user, alumno_id)

    from app.models.movimiento import Movimiento
    from datetime import date

    # Obtener todos los movimiento_ids con registros para este alumno
    movs_con_marcas = db.query(
        HistorialRM.movimiento_id,
        func.count(HistorialRM.id).label('total')
    ).filter(
        HistorialRM.alumno_id == alumno_id,
        HistorialRM.tenant_id == tenant_id
    ).group_by(HistorialRM.movimiento_id).having(
        func.count(HistorialRM.id) >= 1
    ).all()

    ids_con_marcas = [m.movimiento_id for m in movs_con_marcas]

    # Para cada movimiento con >= 2 registros, calcular mejora
    mejoras = []
    for m in movs_con_marcas:
        if m.total < 2:
            continue
        registros = db.query(
            HistorialRM.fecha,
            HistorialRM.peso_kg,
            HistorialRM.repeticiones,
            HistorialRM.minutos,
            HistorialRM.km,
            HistorialRM.vueltas,
            HistorialRM.calorias,
        ).filter(
            HistorialRM.alumno_id == alumno_id,
            HistorialRM.tenant_id == tenant_id,
            HistorialRM.movimiento_id == m.movimiento_id
        ).order_by(HistorialRM.fecha.asc(), HistorialRM.id.asc()).all()

        if len(registros) < 2:
            continue

        primero = registros[0]
        ultimo = registros[-1]

        # Obtener valor según categoría
        movimiento = db.query(Movimiento).filter(
            Movimiento.id == m.movimiento_id,
            Movimiento.tenant_id == tenant_id
        ).first()
        if not movimiento:
            continue

        cat = movimiento.categoria
        val_primero = primero.peso_kg or 0
        val_ultimo = ultimo.peso_kg or 0

        if cat == 'gimnastico':
            val_primero = primero.repeticiones or primero.peso_kg or 0
            val_ultimo = ultimo.repeticiones or ultimo.peso_kg or 0
        elif cat == 'cardio':
            val_primero = primero.minutos or primero.km or primero.vueltas or 0
            val_ultimo = ultimo.minutos or ultimo.km or ultimo.vueltas or 0
        elif cat == 'metabolico':
            val_primero = primero.calorias or primero.km or primero.vueltas or 0
            val_ultimo = ultimo.calorias or ultimo.km or ultimo.vueltas or 0

        diff = val_ultimo - val_primero
        if diff <= 0:
            continue  # Solo mejoras positivas

        # Periodo
        dias = (ultimo.fecha -
                primero.fecha).days if ultimo.fecha and primero.fecha else 0
        if dias == 0:
            periodo = "mismo día"
        elif dias == 1:
            periodo = "1 día"
        else:
            periodo = f"{dias} días"

        unidad = "kg"
        if cat == 'gimnastico':
            unidad = "reps"
        elif cat == 'cardio':
            unidad = "min" if primero.minutos else "km" if primero.km else "vueltas"
        elif cat == 'metabolico':
            unidad = "cal" if primero.calorias else "km" if primero.km else "vueltas"

        mejoras.append({
            "movimiento_id": m.movimiento_id,
            "movimiento_nombre": movimiento.nombre,
            "categoria": cat,
            "diferencia": round(diff, 1),
            "unidad": unidad,
            "periodo": periodo,
            "dias": dias,
        })

    # Ordenar por diferencia descendente, top 3
    mejoras.sort(key=lambda x: x["diferencia"], reverse=True)

    return {
        "ids_con_marcas": ids_con_marcas,
        "top_mejoras": mejoras[:3],
    }


@router.get("/alumnos/{alumno_id}/nivel-gimnastico")
def obtener_nivel_gimnastico_alumno(
    alumno_id: int,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Calcula el nivel gimnástico del alumno basado en sus RMs.
    Retorna el nivel general y los top RMs de movimientos gimnásticos.
    Solo el propio alumno o staff del box.
    """
    # 🔒 SEGURIDAD: tenant_id del token + acceso al alumno.
    tenant_id = current_user["tenant_id"]
    _verificar_acceso_alumno(current_user, alumno_id)

    resultado = calcular_nivel_general(alumno_id, db, tenant_id)

    # Extraer top RMs gimnásticos: consultar DIRECTAMENTE los RMs del alumno
    # para movimientos con categoria='gimnastico', en vez de filtrar solo
    # por los que estan en CROSSFIT_HABILIDADES (que excluye variantes
    # como Strict Pull-up, Kipping Pull-up).
    top_rms = []
    rms_gimnasticos = db.query(
        Movimiento.nombre,
        func.max(HistorialRM.peso_kg).label('max_valor')
    ).join(
        HistorialRM, Movimiento.id == HistorialRM.movimiento_id
    ).filter(
        HistorialRM.alumno_id == alumno_id,
        HistorialRM.tenant_id == tenant_id,
        Movimiento.categoria == 'gimnastico'
    ).group_by(Movimiento.id, Movimiento.nombre).all()

    for nombre, max_valor in rms_gimnasticos:
        top_rms.append({
            "movimiento": nombre,
            "valor": f"{max_valor:.0f} reps"
        })

    return {
        "nivel": resultado.get("nivel_gimnastico", "SIN DATOS"),
        "top_rms": top_rms[:5]  # Top 5
    }
