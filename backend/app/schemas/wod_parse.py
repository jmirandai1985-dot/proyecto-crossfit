"""
Schemas Pydantic para el parser de texto de WOD
"""
from pydantic import BaseModel
from typing import Optional, List


class WodParseRequest(BaseModel):
    texto: str
    tenant_id: int = 1


class MovimientoParseado(BaseModel):
    movimiento_id: int
    nombre: str
    orden: int
    series: Optional[int] = None
    repeticiones: Optional[str] = None
    peso: Optional[float] = None


class DebugInfo(BaseModel):
    linea_original: str
    movimiento_buscado: str = ""
    resultado_bd: str = ""
    tipo: str = "ok"  # "ok", "no_match", "descripcion", "error", "encabezado", "fase"


class FaseMovimiento(BaseModel):
    movimiento_id: int
    nombre: str
    series: Optional[int] = None
    repeticiones: Optional[str] = None
    peso: Optional[float] = None


class FaseInfo(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    movimientos: List[FaseMovimiento] = []


class WodParseResponse(BaseModel):
    fases: List[FaseInfo] = []
    movimientos: List[MovimientoParseado] = []  # legacy, plano
    errores: List[str] = []
    debug_info: List[DebugInfo] = []
