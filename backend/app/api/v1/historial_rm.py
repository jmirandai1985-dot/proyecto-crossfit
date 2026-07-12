"""
Router de endpoints para gestión de Historial RM
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.db.database import get_db
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

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_historial_rm(
    historial_data: HistorialRMCreate,
    db: Session = Depends(get_db)
):
    """Crea un nuevo registro de RM y calcula nivel automáticamente"""
    from app.models.movimiento import Movimiento

    # Verify movimiento exists
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
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un registro de RM por su ID"""
    historial = db.query(HistorialRM).filter(
        HistorialRM.id == historial_id,
        HistorialRM.tenant_id == tenant_id
    ).first()

    if not historial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Historial RM con ID {historial_id} no encontrado"
        )

    return historial


@router.get("", response_model=List[HistorialRMListItem])
def listar_historial_rm(
    tenant_id: int,
    alumno_id: int = None,
    movimiento_id: int = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Lista registros de RM con filtros opcionales"""
    query = db.query(HistorialRM).filter(HistorialRM.tenant_id == tenant_id)

    if alumno_id is not None:
        query = query.filter(HistorialRM.alumno_id == alumno_id)

    if movimiento_id is not None:
        query = query.filter(HistorialRM.movimiento_id == movimiento_id)

    # Join with Movimiento to include movimiento_nombre
    from app.models.movimiento import Movimiento
    historial = query.add_columns(
        Movimiento.nombre.label('movimiento_nombre')
    ).join(
        Movimiento, HistorialRM.movimiento_id == Movimiento.id, isouter=True
    ).order_by(HistorialRM.fecha.desc()).offset(
        skip).limit(limit).all()

    # Manually build response with movimiento_nombre
    result = []
    for row in historial:
        rm, mov_nombre = row
        result.append({
            "id": rm.id,
            "alumno_id": rm.alumno_id,
            "movimiento_id": rm.movimiento_id,
            "peso_kg": rm.peso_kg,
            "tipo_rm": rm.tipo_rm,
            "valor_extra": rm.valor_extra,
            "repeticiones": rm.repeticiones,
            "series": rm.series,
            "minutos": rm.minutos,
            "vueltas": rm.vueltas,
            "km": rm.km,
            "calorias": rm.calorias,
            "fecha": rm.fecha,
            "notas": rm.notas,
            "movimiento_nombre": mov_nombre
        })
    return result


@router.get("/alumnos/{alumno_id}/rms", response_model=List[RMPorMovimiento])
def obtener_rms_alumno(
    alumno_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene el mejor RM por movimiento para un alumno.

    Para movimientos de FUERZA y GIMNASTICO se usa el criterio actual:
    mayor peso_kg (o mayor reps para gimnástico).

    Para movimientos de CARDIO y MAQUINAS (metabolico) no tiene sentido
    comparar por peso_kg (es un dummy), así que se usa el registro MÁS RECIENTE.
    """
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
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Actualiza un registro de RM existente"""
    historial = db.query(HistorialRM).filter(
        HistorialRM.id == historial_id,
        HistorialRM.tenant_id == tenant_id
    ).first()

    if not historial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Historial RM con ID {historial_id} no encontrado"
        )

    update_data = historial_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(historial, field, value)

    db.commit()
    db.refresh(historial)

    return historial


@router.delete("/{historial_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_historial_rm(
    historial_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Elimina un registro de RM"""
    historial = db.query(HistorialRM).filter(
        HistorialRM.id == historial_id,
        HistorialRM.tenant_id == tenant_id
    ).first()

    if not historial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Historial RM con ID {historial_id} no encontrado"
        )

    db.delete(historial)
    db.commit()

    return None


@router.post("/nivel-fuerza")
def calcular_nivel_fuerza_endpoint(
    alumno_id: int,
    movimiento_id: int,
    peso_rm: float,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Calcula el nivel de fuerza para un movimiento específico"""
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
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Calcula el nivel gimnástico para un movimiento específico"""
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


@router.get("/alumnos/{alumno_id}/nivel-general")
def obtener_nivel_general_endpoint(
    alumno_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """Calcula el nivel general del alumno (fuerza y gimnástico)"""
    return calcular_nivel_general(alumno_id, db, tenant_id)


@router.get("/alumnos/{alumno_id}/nivel-fuerza")
def obtener_nivel_fuerza_alumno(
    alumno_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Calcula el nivel de fuerza del alumno basado en sus RMs.
    Retorna el nivel general y los top RMs de movimientos de fuerza.
    """
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


@router.get("/alumnos/{alumno_id}/nivel-gimnastico")
def obtener_nivel_gimnastico_alumno(
    alumno_id: int,
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Calcula el nivel gimnástico del alumno basado en sus RMs.
    Retorna el nivel general y los top RMs de movimientos gimnásticos.
    """
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
