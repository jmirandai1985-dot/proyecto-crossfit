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

Los cuatro consumidores (pantalla Marketing del admin, el aviso rápido del coach en
la Gestión de Clases, el Bazar al publicar un producto y el carrusel del alumno)
pasan por acá: si cada uno armara su propia ventana, un aviso se vería en una
pantalla y no en la otra.

Las funciones puras (`rango_vigencia`, `esta_vigente`, `normalizar`, `validar`) no
tocan la BD y se prueban aisladas.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import or_

from app.models.aviso_marketing import (
    TIPOS_EDITABLES, TIPO_AVISO, TIPO_COLABORACION, TIPO_EVENTO,
    TIPO_PRODUCTO_BAZAR, TIPO_PROMOCION, AvisoMarketing,
)
from app.models.producto import Producto
from app.utils.santiago import (
    ahora_santiago, fecha_chile, fin_del_dia_chile, hoy_santiago,
    inicio_del_dia_chile,
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
        # Vínculo con una promoción de Referidos publicada (migración 056).
        "promocion_id": aviso.promocion_id,
        # Tarjeta de la ESCALERA de tramos (migración 064): se publica una sola
        # por box y no cuelga de `promociones_referidos`.
        "escalera_tramos": bool(aviso.escalera_tramos),
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
        # Sólo lo manda el flujo de publicación de Referidos (056); el
        # formulario "Nuevo aviso" nunca lo incluye y queda en None.
        promocion_id=limpio.get("promocion_id"),
        # Sólo lo manda `POST /referidos/tramos/publicar` (064).
        escalera_tramos=bool(limpio.get("escalera_tramos", False)),
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
    if aviso.promocion_id is not None and limpio["tipo"] != TIPO_PROMOCION:
        # Un aviso VINCULADO (056) es la tarjeta de una promoción de Referidos:
        # convertirlo en Evento dejaría el vínculo apuntando a otra cosa y la
        # pantalla de referidos seguiría diciendo "publicada".
        raise ValueError([
            "Este aviso anuncia una promoción de Referidos: despublica la "
            "promoción antes de cambiarlo a otro tipo."])
    desde, hasta = rango_vigencia(limpio["vigente_desde"], limpio["vigente_hasta"])
    aviso.tipo = limpio["tipo"]
    aviso.titulo = limpio["titulo"]
    aviso.texto = limpio.get("texto")
    aviso.nombre_aliado = limpio.get("nombre_aliado")
    aviso.fecha_evento = limpio.get("fecha_evento")
    aviso.vigente_desde = desde
    aviso.vigente_hasta = hasta
    aviso.fijado_arriba = bool(limpio.get("fijado_arriba", False))
    # La tarjeta de la escalera (064) republica sobre su MISMA fila: el marcador
    # no puede apagarse por un PUT que no lo mande.
    aviso.escalera_tramos = bool(limpio.get("escalera_tramos",
                                            aviso.escalera_tramos))
    db.commit()
    db.refresh(aviso)
    return serializar(aviso)


def eliminar(db, aviso: AvisoMarketing) -> str | None:
    """Borra el aviso y devuelve la URL de su flyer (para borrar el archivo).

    El archivo se borra DESPUÉS del commit y best-effort: si el almacenamiento
    falla, el aviso ya no está (que es lo que pidió el admin) y lo único que queda
    es un archivo huérfano, no un aviso visible. Para un aviso `producto_bazar`
    devuelve None: su "flyer" es la foto del producto (ver `url_a_borrar`).
    """
    flyer = url_a_borrar(aviso)
    db.delete(aviso)
    db.commit()
    return flyer


def url_a_borrar(aviso: AvisoMarketing) -> str | None:
    """La URL del flyer a borrar del almacenamiento, o None si NO hay que borrarla.

    Un aviso `producto_bazar` NO tiene flyer propio: su `imagen_url` ES la foto del
    producto (la tarjeta del alumno la muestra). Borrarla dejaría al producto SIN
    imagen en el Bazar, así que para ese tipo siempre devuelve None.
    """
    if aviso.tipo == TIPO_PRODUCTO_BAZAR:
        return None
    return aviso.imagen_url


# ── El aviso automático del Bazar (Bloque 3) ────────────────────────────────
# El párrafo de la tarjeta es FIJO: la tarjeta ya muestra el nombre y el precio
# reales del producto, así que el texto sólo dice dónde comprarlo (el mockup
# escribe exactamente eso).
TEXTO_PRODUCTO = "Disponible en el Bazar"


def _fin_de_ventana(desde: date, dias: int) -> datetime:
    """Último instante de la ventana de `dias` días CONTANDO hoy como el primero.

    1 día = sólo hoy (hasta las 23:59:59 de Chile); 7 días = hoy y los 6 que
    siguen. Nunca menos de un día (`dias` <= 0 no llega acá).
    """
    return fin_del_dia_chile(desde + timedelta(days=max(int(dias), 1) - 1))


def sincronizar_producto(db, producto: Producto, creado_por: int | None = None,
                         ahora: datetime | None = None) -> dict | None:
    """Crea, actualiza o quita el aviso `producto_bazar` de un producto del Bazar.

    Toda la perilla del admin es `productos.dias_anuncio`:
      * 0 → se QUITA el aviso (no se anuncia) y se devuelve None;
      * >0 y no hay aviso → se crea, con la ventana que empieza HOY (día de Chile);
      * >0 y el aviso ya existe → se RELANZA: la ventana se vuelve a contar desde hoy
        con los días que el admin acaba de guardar (más días = anuncio más largo,
        menos días = más corto) y el contenido se refresca, porque título, texto y
        foto son del producto y pudieron cambiar.

    El relanzado es una DECISIÓN del admin, no un efecto de guardar el producto: la
    ruta sólo llama al sync cuando `dias_anuncio` viene en el payload, así que editar
    el stock, el precio o el nombre sin tocar los días deja la ventana como estaba
    (si no, cada edición relanzaría el anuncio desde hoy).

    Lo llaman POST /productos y PUT /productos/{id}: el aviso es DERIVADO del
    producto y no se toca a mano (la API del admin rechaza ese tipo).
    """
    ahora = ahora or ahora_santiago()
    dias = int(producto.dias_anuncio or 0)
    aviso = db.query(AvisoMarketing).filter(
        AvisoMarketing.tenant_id == producto.tenant_id,
        AvisoMarketing.producto_id == producto.id,
    ).first()

    if dias <= 0:
        if aviso is None:
            return None
        db.delete(aviso)
        db.commit()
        return None

    hoy = fecha_chile(ahora)
    # La ventana se recalcula SIEMPRE desde hoy (darle 7 días a un aviso que estaba
    # por vencer lo deja con 7 días completos por delante). Lo que evita que el
    # anuncio se estire solo es la PUERTA de la ruta: sin `dias_anuncio` en el
    # payload, el sync ni siquiera se llama.
    desde = inicio_del_dia_chile(hoy)
    hasta = _fin_de_ventana(hoy, dias)

    if aviso is None:
        aviso = AvisoMarketing(
            tenant_id=producto.tenant_id,
            tipo=TIPO_PRODUCTO_BAZAR,
            # El vínculo con el producto: es lo que hace que la tarjeta muestre su
            # foto, su nombre y su precio REALES (y lo que respeta el único
            # `uq_avisos_marketing_producto`). Sin esto el aviso quedaría suelto.
            producto_id=producto.id,
            titulo=producto.nombre,
            texto=TEXTO_PRODUCTO,
            imagen_url=producto.imagen_url,
            vigente_desde=desde,
            vigente_hasta=hasta,
            # Un aviso automático nunca va fijado arriba: el carrusel lo ordena por
            # fecha y lo que el admin fija a mano sigue mandando.
            fijado_arriba=False,
            creado_por=creado_por,
        )
        db.add(aviso)
    else:
        # El contenido se refresca SIEMPRE (nombre, foto y texto son del producto) y
        # la ventana se relanza con los días recién guardados.
        aviso.tipo = TIPO_PRODUCTO_BAZAR
        aviso.titulo = producto.nombre
        aviso.texto = TEXTO_PRODUCTO
        aviso.imagen_url = producto.imagen_url
        aviso.vigente_desde = desde
        aviso.vigente_hasta = hasta

    db.commit()
    db.refresh(aviso)
    return serializar(aviso, producto, ahora)


# ── El aviso rápido del coach (Bloque 3 — Gestión de Clases) ────────────────
# El coach publica desde su panel de clases un aviso que el alumnado ve HOY en su
# Inicio del alumno. Escribe UNA caja de texto (mockup "Aviso rápido") y el resto lo
# fija el backend —no la pantalla—: así un coach no puede publicar de paso una
# Promoción de un mes, una Colaboración con aliado ni un Evento con fecha.

TITULO_RAPIDO_MAX = 60


def ventana_de_hoy(ahora: datetime | None = None) -> tuple[date, date]:
    """Los dos días del aviso rápido: HOY en Chile, dos veces (el día que se publica).

    Se devuelve como par `(desde, hasta)` porque es lo que come `rango_vigencia`:
    la ventana arranca a las 00:00 y cierra a las 23:59:59, así que el aviso dura el
    día COMPLETO y desaparece solo a medianoche (sin que nadie lo despublica).
    """
    hoy = fecha_chile(ahora) if ahora is not None else hoy_santiago()
    return hoy, hoy


def titulo_desde_texto(texto: str | None, tope: int = TITULO_RAPIDO_MAX) -> str:
    """El título del aviso rápido SALE del mensaje (el coach escribe una sola caja).

    La tarjeta del carrusel dibuja título y texto por separado, así que un aviso
    rápido necesita un título: se usa la PRIMERA FRASE ("Trae calcetas. Hay cuerda"
    -> "Trae calcetas") y, si no entra en `tope`, se recorta en la palabra anterior
    (nunca al medio de una palabra) y se marca con "…".
    """
    # Los saltos de línea y los espacios de más no llegan a la tarjeta: se aplanan.
    plano = " ".join((texto or "").split())
    if not plano:
        return ""
    cortes = [posicion for posicion in (plano.find(c) for c in ".!?;")
              if posicion != -1]
    if cortes:
        plano = plano[:min(cortes)].strip()
    if len(plano) <= tope:
        return plano
    recorte = plano[:tope].rstrip()
    ultimo_espacio = recorte.rfind(" ")
    if ultimo_espacio > 0:
        recorte = recorte[:ultimo_espacio]
    return f"{recorte}…"


def payload_aviso_de_fecha(texto: str, fecha: date) -> dict:
    """El payload de un aviso para UN día concreto (el archivo semanal del coach).

    Es el MISMO aviso del box (tipo `aviso`, sin flyer, sin fijar arriba) que el aviso
    rápido, pero con la ventana de ESE día en lugar de HOY: el aviso del miércoles se ve el
    miércoles y desaparece solo a medianoche, sin que nadie lo despublica. La ventana la
    arma `rango_vigencia` (00:00 → 23:59:59 del día, hora de Chile) — la única definición
    de ventana del proyecto, no una nueva — y el título sale del mensaje con la misma regla
    (`titulo_desde_texto`).
    """
    desde, hasta = rango_vigencia(fecha, fecha)
    mensaje = (texto or "").strip()
    return {
        "tipo": TIPO_AVISO,
        "titulo": titulo_desde_texto(mensaje),
        "texto": mensaje,
        "nombre_aliado": None,
        "fecha_evento": None,
        "vigente_desde": desde,
        "vigente_hasta": hasta,
        "fijado_arriba": False,
        "imagen_url": None,
    }


def payload_aviso_rapido(texto: str, ahora: datetime | None = None) -> dict:
    """El payload de `crear()` del aviso rápido: tipo `aviso`, HOY y nada más.

    Todo lo que el coach NO elige se fija ACÁ: el tipo (`aviso`), la ventana (HOY,
    día de Chile), `fijado_arriba=False` y sin flyer (`imagen_url`). El título se
    DERIVA del mensaje. Una Promoción, una Colaboración o un Evento llevan
    fechas/aliado y siguen siendo del admin.
    """
    desde, hasta = ventana_de_hoy(ahora)
    mensaje = (texto or "").strip()
    return {
        "tipo": TIPO_AVISO,
        "titulo": titulo_desde_texto(mensaje),
        "texto": mensaje,
        "nombre_aliado": None,
        "fecha_evento": None,
        "vigente_desde": desde,
        "vigente_hasta": hasta,
        "fijado_arriba": False,
        "imagen_url": None,
    }
