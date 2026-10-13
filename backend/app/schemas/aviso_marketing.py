"""
Esquemas Pydantic para los avisos de marketing (el carrusel "Novedades del box").

Un aviso tiene DOS caras:
  * la VENTANA (`vigente_desde` / `vigente_hasta`) llega como FECHA de calendario
    (lo que el admin elige en el formulario) y se guarda como INSTANTE de Chile
    (00:00 del primer día / 23:59:59 del último): la conversión la hace el servicio
    (`app/services/avisos_marketing.py`), no el esquema;
  * los datos del PRODUCTO vinculado (`producto_bazar`) viajan RESUELTOS en la
    respuesta porque la tarjeta del alumno muestra su foto, su nombre y su precio
    reales, sin que la pantalla tenga que cruzarlos.
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AvisoMarketingCrear(BaseModel):
    """Lo que manda el formulario "Nuevo aviso" del admin (multipart/form-data).

    El flyer NO va acá: viaja como `file` en el mismo POST multipart, igual que la
    foto de un producto del Bazar.
    """
    tipo: str = Field(..., description="promocion | colaboracion | aviso | evento")
    titulo: str = Field(..., min_length=1, max_length=150)
    texto: str = Field(..., min_length=1, max_length=1000)
    # Sólo Colaboración (el servicio lo apaga en el resto de los tipos).
    nombre_aliado: Optional[str] = Field(None, max_length=150)
    # Sólo Evento: es la fecha que la tarjeta dibuja grande ("25 / OCT").
    fecha_evento: Optional[date] = None
    vigente_desde: date
    vigente_hasta: date
    fijado_arriba: bool = False


class AvisoMarketingActualizar(AvisoMarketingCrear):
    """PUT /marketing/{id}: REEMPLAZA los campos editables (el form manda todo).

    No es un PATCH a propósito: los campos del aviso están acoplados al tipo
    (cambiar Promoción → Evento tiene que pedir la fecha del evento en la misma
    vuelta), así que un update parcial podría dejar un Evento sin fecha. El flyer
    no viene acá: se cambia por POST/DELETE /marketing/{id}/imagen.
    """


class AvisoRapidoCrear(BaseModel):
    """Lo que manda el modal "Aviso rápido" del coach (POST /marketing/aviso-rapido).

    Sólo el MENSAJE. El tipo (`aviso`), la ventana (HOY, día de Chile) y el título
    (derivado del propio mensaje) los fija el backend —`app/services/avisos_marketing.py:
    payload_aviso_rapido`—: sin tipo ni fechas en el payload, desde el panel del coach
    NO se puede publicar una Promoción de un mes, una Colaboración ni un Evento, que
    son contenido del admin. Tampoco lleva flyer.
    """
    texto: str = Field(..., min_length=1, max_length=1000)


class AvisoMarketingOut(BaseModel):
    """La fila como la consumen la pantalla del admin y el carrusel del alumno."""
    id: int
    tipo: str
    titulo: str
    texto: Optional[str] = None
    # Flyer opcional: NULL = la tarjeta se pinta con el color de su tipo.
    imagen_url: Optional[str] = None
    nombre_aliado: Optional[str] = None
    fecha_evento: Optional[date] = None
    vigente_desde: datetime
    vigente_hasta: datetime
    fijado_arriba: bool = False
    # Sólo `producto_bazar`: el vínculo con el producto real del Bazar.
    producto_id: Optional[int] = None
    creado_en: datetime
    # Derivado (no es columna): ¿la ventana contiene AHORA, hora de Chile? Lo usa el
    # chip "Vigente/Vencido" del admin; el carrusel del alumno sólo recibe vigentes.
    vigente: bool = False
    # Datos RESUELTOS del producto vinculado (NULL en los 4 tipos manuales).
    producto_nombre: Optional[str] = None
    producto_precio: Optional[float] = None
    producto_imagen_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

