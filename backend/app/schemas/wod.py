"""
Schemas Pydantic para WOD
"""
from pydantic import BaseModel
from datetime import date, datetime, time
from typing import Optional, List


class WodMovimientoCreate(BaseModel):
    movimiento_id: int
    orden: int = 1
    series: Optional[int] = None
    repeticiones: Optional[str] = None
    peso: Optional[float] = None
    tiempo: Optional[str] = None
    notas: Optional[str] = None
    # Fase del WOD: CALENTAMIENTO, FUERZA, WOD, o NULL
    fase: Optional[str] = None


class WodMovimientoResponse(BaseModel):
    id: int
    wod_id: int
    movimiento_id: int
    orden: int
    series: Optional[int]
    repeticiones: Optional[str]
    peso: Optional[float]
    tiempo: Optional[str]
    notas: Optional[str]
    fase: Optional[str] = None
    # Nombre del movimiento (resuelto desde la relación con Movimiento)
    nombre: Optional[str] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_movimiento(cls, wod_mov):
        """Crea una instancia desde un WodMovimiento, extrayendo el nombre
        de la relación con Movimiento (wod_mov.movimiento.nombre)"""
        data = {
            "id": wod_mov.id,
            "wod_id": wod_mov.wod_id,
            "movimiento_id": wod_mov.movimiento_id,
            "orden": wod_mov.orden,
            "series": wod_mov.series,
            "repeticiones": wod_mov.repeticiones,
            "peso": wod_mov.peso,
            "tiempo": wod_mov.tiempo,
            "notas": wod_mov.notas,
            "fase": wod_mov.fase,
            "nombre": wod_mov.movimiento.nombre if wod_mov.movimiento else None
        }
        return cls(**data)


class MovimientoEnFase(BaseModel):
    """Movimiento dentro de una fase (sin fase propia, hereda la de la fase)"""
    movimiento_id: int
    orden: int = 1
    series: Optional[int] = None
    repeticiones: Optional[str] = None
    peso: Optional[float] = None
    tiempo: Optional[str] = None
    notas: Optional[str] = None


class FaseWodCreate(BaseModel):
    """Una fase del WOD con sus movimientos"""
    nombre: str  # CALENTAMIENTO, FUERZA, WOD
    descripcion: Optional[str] = None
    movimientos: List[MovimientoEnFase] = []


class WodCreate(BaseModel):
    fecha: date
    hora_inicio: Optional[time] = None
    hora_fin: Optional[time] = None
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    # Nuevos campos de texto libre
    calentamiento: Optional[str] = None
    fuerza_habilidad: Optional[str] = None
    wod_principal: Optional[str] = None
    tipo_metcon: Optional[str] = None  # AMRAP, EMOM, RFT, FOR TIME
    coach_id: Optional[int] = None
    estado: Optional[str] = "draft"
    # Mantenemos compatibilidad con formato viejo por ahora
    movimientos: List[WodMovimientoCreate] = []
    fases: List[FaseWodCreate] = []


class WodUpdate(BaseModel):
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    estado: Optional[str] = None
    hora_inicio: Optional[time] = None
    hora_fin: Optional[time] = None
    # Nuevos campos de texto libre
    calentamiento: Optional[str] = None
    fuerza_habilidad: Optional[str] = None
    wod_principal: Optional[str] = None
    tipo_metcon: Optional[str] = None
    movimientos: Optional[List[WodMovimientoCreate]] = None
    fases: Optional[List[FaseWodCreate]] = None


class FaseWodResponse(BaseModel):
    """Fase en la respuesta del WOD"""
    nombre: str
    descripcion: Optional[str] = None
    movimientos: List[WodMovimientoResponse] = []


class WodResponse(BaseModel):
    id: int
    tenant_id: int
    fecha: date
    hora_inicio: Optional[time] = None
    hora_fin: Optional[time] = None
    titulo: Optional[str]
    descripcion: Optional[str]
    # Nuevos campos de texto libre
    calentamiento: Optional[str] = None
    fuerza_habilidad: Optional[str] = None
    wod_principal: Optional[str] = None
    tipo_metcon: Optional[str] = None
    coach_id: Optional[int]
    estado: str
    activo: bool
    created_at: datetime
    movimientos: List[WodMovimientoResponse] = []
    # Movimientos agrupados por fase (calculado del campo fase)
    fases: List[FaseWodResponse] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_names(cls, wod):
        """Crea WodResponse poblado con nombres de movimientos.
        Procesa cada WodMovimiento para extraer el nombre desde la relación."""
        movs = []
        for m in wod.movimientos or []:
            movs.append(WodMovimientoResponse.from_orm_with_movimiento(m))
        # Agrupar por fase (NULL → "OTROS")
        fases_map = {}
        for m in movs:
            fase_nombre = m.fase or "OTROS"
            if fase_nombre not in fases_map:
                fases_map[fase_nombre] = FaseWodResponse(
                    nombre=fase_nombre, descripcion=None)
            fases_map[fase_nombre].movimientos.append(m)
        wod_response = cls(
            id=wod.id,
            tenant_id=wod.tenant_id,
            fecha=wod.fecha,
            hora_inicio=wod.hora_inicio,
            hora_fin=wod.hora_fin,
            titulo=wod.titulo,
            descripcion=wod.descripcion,
            calentamiento=wod.calentamiento,
            fuerza_habilidad=wod.fuerza_habilidad,
            wod_principal=wod.wod_principal,
            tipo_metcon=wod.tipo_metcon,
            coach_id=wod.coach_id,
            estado=wod.estado.value if hasattr(
                wod.estado, 'value') else wod.estado,
            activo=wod.activo,
            created_at=wod.created_at,
            movimientos=movs,
            fases=list(fases_map.values())
        )
        return wod_response
