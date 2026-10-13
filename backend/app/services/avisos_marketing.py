"""
Avisos de marketing: la vigencia, la validación y el CRUD del carrusel.

QUÉ ES
------
`avisos_marketing` es la fuente de las tarjetas de "Novedades del box" del Inicio
del alumno. Este módulo es el ÚNICO lugar donde vive:

  * la VENTANA de vigencia (`vigente_desde` / `vigente_hasta`): el admin elige dos
    DÍAS de calendario y acá se convierten en INSTANTES de Chile (00:00:00 del
    primero, 23:59:59 del último) — el último día vale completo, la misma regla
    que `suscripciones.fecha_expiracion` (`app/utils/santiago.py`);
  * el ORDEN del carrusel: `fijado_arriba` primero y, a igualdad, el más reciente
    (`creado_en DESC`). Un aviso fijado tiene que ganarle a uno nuevo; si no,
    "fijar" no serviría para nada;
  * la VALIDACIÓN por tipo (Colaboración exige el nombre del aliado, Evento exige
    la fecha) y la normalización que APAGA los campos que no aplican al tipo.

Los tres consumidores (pantalla Marketing del admin, el Bazar al publicar un
producto y el carrusel del alumno) pasan por acá: si cada uno armara su propia
ventana, un aviso se vería en una pantalla y no en la otra.

Las funciones puras (`rango_vigencia`, `esta_vigente`, `normalizar`, `validar`) no
tocan la BD y se prueban aisladas.
"""
from datetime import date, datetime

from sqlalchemy import or_

from app.models.aviso_marketing import (
    TIPOS_EDITABLES, TIPO_COLABORACION, TIPO_EVENTO, AvisoMarketing,
)
from app.models.producto import Producto
from app.utils.santiago import (
    ahora_santiago, fin_del_dia_chile, inicio_del_dia_chile,
)

# ── Filtros de la lista del admin ───────────────────────────────────────────
# Cada uno es un predicado SQL distinto sobre la MISMA ventana: "programado" (no
# empezó) es tan importante como "vencido" para el admin, que necesita ver los dos.
FILTRO_TODOS = "todos"
FILTRO_VIGENTES = "vigentes"
FILTRO_PROGRAMADOS = "programados"
FILTRO_VENCIDOS = "vencidos"
FILTROS = (FILTRO_TODOS, FILTRO_VIGENTES, FILTRO_PROGRAMADOS, FILTRO_VENCIDOS)

# Topes de largo: espejo de las columnas del modelo (String(150) / String(1000)).
TITULO_MAX = 150
TEXTO_MAX = 1000
ALIADO_MAX = 150


# ── Puras: ventana, orden y datos ───────────────────────────────────────────

def orden_carrusel() -> tuple:
    """`fijado_arriba DESC, creado_en DESC` (el orden del carrusel y de la lista).

    Es una tupla de expresiones SQLAlchemy: la comparten `listar()` y `vigentes()`
    para que la pantalla del admin y el Inicio del alumno muestren el MISMO orden.
    """
    return (AvisoMarketing.fijado_arriba.desc(),
            AvisoMarketing.creado_en.desc())


def rango_vigencia(desde: date, hasta: date) -> tuple[datetime, datetime]:
    """Los dos DÍAS que elige el admin → los dos INSTANTES que se guardan.

    Día de Chile: el aviso arranca a las 00:00 del primer día (si no, un aviso que
    empieza "hoy" aparecería recién a las 03:00 de la madrugada) y termina a las
    23:59:59 del último (el día de cierre vale COMPLETO).
    """
    return inicio_del_dia_chile(desde), fin_del_dia_chile(hasta)


def esta_vigente(vigente_desde, vigente_hasta, ahora: datetime | None = None) -> bool:
    """¿La ventana contiene `ahora` (default: ahora en Chile)? Bordes INCLUSIVOS."""
    if vigente_desde is None or vigente_hasta is None:
        return False
    ahora = ahora or ahora_santiago()
    return vigente_desde <= ahora <= vigente_hasta


def normalizar(datos: dict) -> dict:
    """Limpia el payload y APAGA los campos que no aplican al tipo elegido.

    El nombre del aliado existe sólo en Colaboración y la fecha del evento sólo en
    Evento: guardar un aliado dentro de una Promoción dejaría un dato invisible que
    reaparecería si alguien cambia el tipo después. Acá se apaga (NULL) en vez de
    confiar en que la pantalla no lo mande.
    """
    limpio = dict(datos)
    for campo in ("titulo", "texto", "nombre_aliado"):
        valor = limpio.get(campo)
        if isinstance(valor, str):
            limpio[campo] = valor.strip() or None
    if limpio.get("tipo") != TIPO_COLABORACION:
        limpio["nombre_aliado"] = None
    if limpio.get("tipo") != TIPO_EVENTO:
        limpio["fecha_evento"] = None
    return limpio


def validar(datos: dict) -> list[str]:
    """Los errores del aviso, en castellano y listos para mostrar. [] = válido.

    Espejo de lo que valida el formulario del admin: el backend NO confía en el
    front, así que las reglas viven acá y la pantalla las repite sólo para dar
    feedback inmediato.
    """
    errores = []
    if datos.get("tipo") not in TIPOS_EDITABLES:
        # `producto_bazar` NO se crea a mano: lo mantiene el Bazar (Bloque 3).
        errores.append("El tipo de aviso no es válido.")

    titulo = (datos.get("titulo") or "").strip()
    if not titulo:
        errores.append("El título es obligatorio.")
    elif len(titulo) > TITULO_MAX:
        errores.append(f"El título no puede superar los {TITULO_MAX} caracteres.")

    texto = (datos.get("texto") or "").strip()
    if not texto:
        errores.append("El texto es obligatorio.")
    elif len(texto) > TEXTO_MAX:
        errores.append(f"El texto no puede superar los {TEXTO_MAX} caracteres.")

    desde, hasta = datos.get("vigente_desde"), datos.get("vigente_hasta")
    if not desde or not hasta:
        errores.append("La vigencia (desde y hasta) es obligatoria.")
    elif hasta < desde:
        errores.append("La vigencia no puede terminar antes de empezar.")

    if datos.get("tipo") == TIPO_COLABORACION:
        aliado = (datos.get("nombre_aliado") or "").strip()
        if not aliado:
            errores.append("Una colaboración necesita el nombre del aliado.")
        elif len(aliado) > ALIADO_MAX:
            errores.append("El nombre del aliado no puede superar los "
                           f"{ALIADO_MAX} caracteres.")

    if datos.get("tipo") == TIPO_EVENTO and not datos.get("fecha_evento"):
        errores.append("Un evento necesita su fecha.")

    return errores


def serializar(aviso: AvisoMarketing, producto: Producto | None = None,
               ahora: datetime | None = None) -> dict:
    """La fila tal como la consumen el panel del admin y el carrusel del alumno.

    `producto` es el producto vinculado (sólo `producto_bazar`) y viene de la
    consulta: la tarjeta muestra su foto, su nombre y su precio REALES, así que si
    el admin cambia el precio en el Bazar, el aviso lo refleja sin tocarlo.
    """
    return {
        "id": aviso.id,
        "tipo": aviso.tipo,
        "titulo": aviso.titulo,
        "texto": aviso.texto,
        "imagen_url": aviso.imagen_url,
        "nombre_aliado": aviso.nombre_aliado,
        "fecha_evento": aviso.fecha_evento,
        "vigente_desde": aviso.vigente_desde,
        "vigente_hasta": aviso.vigente_hasta,
        "fijado_arriba": bool(aviso.fijado_arriba),
        "producto_id": aviso.producto_id,
        "creado_en": aviso.creado_en,
        # Derivado, para que el admin vea de un vistazo si está al aire hoy.
        "vigente": esta_vigente(aviso.vigente_desde, aviso.vigente_hasta, ahora),
        "producto_nombre": producto.nombre if producto else None,
        "producto_precio": producto.precio if producto else None,
        "producto_imagen_url": producto.imagen_url if producto else None,
    }


# ── Con la sesión del llamador ──────────────────────────────────────────────

def _consulta(db, tenant_id: int, filtro: str, ahora: datetime | None = None):
    """Los avisos del box con su producto vinculado (UN JOIN, sin N+1)."""
    ahora = ahora or ahora_santiago()
    consulta = db.query(AvisoMarketing, Producto).outerjoin(
        Producto, AvisoMarketing.producto_id == Producto.id
    ).filter(AvisoMarketing.tenant_id == tenant_id)
    if filtro == FILTRO_VIGENTES:
        consulta = consulta.filter(AvisoMarketing.vigente_desde <= ahora,
                                   AvisoMarketing.vigente_hasta >= ahora)
    elif filtro == FILTRO_PROGRAMADOS:
        consulta = consulta.filter(AvisoMarketing.vigente_desde > ahora)
    elif filtro == FILTRO_VENCIDOS:
        consulta = consulta.filter(AvisoMarketing.vigente_hasta < ahora)
    return consulta.order_by(*orden_carrusel())


def listar(db, tenant_id: int, filtro: str = FILTRO_TODOS,
           ahora: datetime | None = None) -> list[dict]:
    """Los avisos del box para el panel del admin (`filtro` = uno de FILTROS).

    Un filtro desconocido no rompe: cae en "todos" (la pantalla puede mandar
    cualquier basura en el query string).
    """
    if filtro not in FILTROS:
        filtro = FILTRO_TODOS
    ahora = ahora or ahora_santiago()
    return [serializar(aviso, producto, ahora)
            for aviso, producto in _consulta(db, tenant_id, filtro, ahora).all()]


def vigentes(db, tenant_id: int, ahora: datetime | None = None) -> list[dict]:
    """Los avisos que el carrusel del alumno dibuja HOY, ya ordenados.

    Un aviso `producto_bazar` cuyo producto fue RETIRADO (activo=false) no sale:
    anunciar algo que ya no se vende es peor que no anunciar nada.
    """
    ahora = ahora or ahora_santiago()
    filas = _consulta(db, tenant_id, FILTRO_VIGENTES, ahora).filter(
        or_(AvisoMarketing.producto_id.is_(None), Producto.activo.is_(True))
    ).all()
    return [serializar(aviso, producto, ahora) for aviso, producto in filas]


def crear(db, tenant_id: int, datos: dict,
          creado_por: int | None = None) -> dict:
    """Crea el aviso del box. `ValueError(errores)` si el payload no es válido."""
    errores = validar(datos)
    if errores:
        raise ValueError(errores)
    limpio = normalizar(datos)
    desde, hasta = rango_vigencia(limpio["vigente_desde"], limpio["vigente_hasta"])
    aviso = AvisoMarketing(
        tenant_id=tenant_id,
        tipo=limpio["tipo"],
        titulo=limpio["titulo"],
        texto=limpio.get("texto"),
        nombre_aliado=limpio.get("nombre_aliado"),
        fecha_evento=limpio.get("fecha_evento"),
        # El flyer lo sube la ruta ANTES de llamar acá (POST /marketing): el
        # servicio sólo lo persiste. Los otros tipos quedan con None.
        imagen_url=limpio.get("imagen_url"),
        vigente_desde=desde,
        vigente_hasta=hasta,
        fijado_arriba=bool(limpio.get("fijado_arriba", False)),
        creado_por=creado_por,
    )
    db.add(aviso)
    db.commit()
    db.refresh(aviso)
    return serializar(aviso)


def actualizar(db, aviso: AvisoMarketing, datos: dict) -> dict:
    """REEMPLAZA los campos editables (el formulario del admin manda todo).

    No toca `producto_id` (el vínculo con el Bazar), ni el flyer (se cambia por
    POST/DELETE /marketing/{id}/imagen), ni `creado_por`/`creado_en`. Un aviso
    `producto_bazar` NO se edita a mano: `validar()` rechaza ese tipo y la pantalla
    no ofrece el botón (su contenido lo mantiene el Bazar).
    """
    errores = validar(datos)
    if errores:
        raise ValueError(errores)
    limpio = normalizar(datos)
    desde, hasta = rango_vigencia(limpio["vigente_desde"], limpio["vigente_hasta"])
    aviso.tipo = limpio["tipo"]
    aviso.titulo = limpio["titulo"]
    aviso.texto = limpio.get("texto")
    aviso.nombre_aliado = limpio.get("nombre_aliado")
    aviso.fecha_evento = limpio.get("fecha_evento")
    aviso.vigente_desde = desde
    aviso.vigente_hasta = hasta
    aviso.fijado_arriba = bool(limpio.get("fijado_arriba", False))
    db.commit()
    db.refresh(aviso)
    return serializar(aviso)


def eliminar(db, aviso: AvisoMarketing) -> str | None:
    """Borra el aviso y devuelve la URL de su flyer (para borrar el archivo).

    El archivo se borra DESPUÉS del commit y best-effort: si el almacenamiento
    falla, el aviso ya no está (que es lo que pidió el admin) y lo único que queda
    es un archivo huérfano, no un aviso visible.
    """
    flyer = aviso.imagen_url
    db.delete(aviso)
    db.commit()
    return flyer
