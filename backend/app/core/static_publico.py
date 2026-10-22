"""
Estáticos PÚBLICOS sin comprobantes privados.

`/static/uploads/` existe para las imágenes que SÍ son públicas (fotos de
productos del Bazar y flyers de avisos de marketing). Los comprobantes de pago
no pueden vivir ahí: los sirve StaticFiles sin token y cualquiera con la URL los
ve.

Los comprobantes NUEVOS se guardan en `private_uploads/` (`?privado=1` ->
`/privado/vouchers/...`) y sólo se leen por el endpoint autenticado. Pero hay
comprobantes HISTÓRICOS cuya URL en la BD todavía es `/static/uploads/...`
(subidos antes de que existiera el camino privado): ese archivo se seguía
sirviendo por su URL pública sin autenticación.

Este `StaticFiles` consulta la BD —sólo para archivos de `uploads/`— y responde
404 cuando el nombre está referenciado como voucher, certificado o comprobante
de pedido. Además niega los `voucher_*` HUÉRFANOS (sin ninguna fila que los
respalde): al borrar la solicitud/pedido, el archivo quedaba público para
siempre. Las imágenes públicas (foto/galería de producto y flyers de marketing)
se permiten porque están referenciadas en sus columnas; los nombres nuevos de
esas imágenes no usan el prefijo `voucher_`.

El resultado se cachea por nombre (`lru_cache`): los nombres son UUID y un
archivo público nunca pasa a ser comprobante (los nuevos ya nacen privados), así
que no hace falta invalidar la caché.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from posixpath import normpath

from starlette.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse
from starlette.staticfiles import StaticFiles

log = logging.getLogger("app.core.static_publico")

# Columnas de la BD que guardan comprobantes PRIVADOS. Si aparece un documento
# nuevo, se agrega acá: es la ÚNICA lista que decide qué no se sirve público.
COLUMNAS_COMPROBANTE = (
    ("solicitudes_planes", "voucher_url"),
    ("solicitudes_planes", "certificado_estudiante_url"),
    ("pedidos", "voucher_url"),
)

# Columnas que SÍ son imágenes públicas (se sirven por /static/uploads). La
# galería del producto usa `producto_imagenes.url` (orden=0 es la portada).
COLUMNAS_PUBLICAS = (
    ("productos", "imagen_url"),
    ("producto_imagenes", "url"),
    ("avisos_marketing", "imagen_url"),
)

# `POST /upload/voucher` nombraba TODOS los archivos `voucher_<uuid>`, tanto los
# comprobantes viejos como las imágenes públicas de esa época. Ese prefijo ya no
# se usa para archivos públicos: las fotos nuevas son `<uuid>.<ext>`.
PREFIJO_LEGACY_COMPROBANTE = "voucher_"


def _referenciado(db, sufijo: str, columnas) -> bool:
    """True si alguna columna guarda una URL que TERMINA en `sufijo`."""
    from sqlalchemy import text

    for tabla, columna in columnas:
        fila = db.execute(
            text(f"SELECT 1 FROM {tabla} "
                 f"WHERE right({columna}, :largo) = :sufijo LIMIT 1"),
            {"largo": len(sufijo), "sufijo": sufijo},
        ).first()
        if fila:
            return True
    return False


@lru_cache(maxsize=4096)
def es_comprobante_privado(nombre: str) -> bool:
    """True si `nombre` (archivo de static/uploads) NO debe servirse público.

    - referenciado por una columna de comprobantes -> True;
    - `voucher_*` no referenciado como imagen pública (huérfano) -> True;
    - el resto (imagen de producto/galería/flyer) -> False.

    FAIL-CLOSED: si la consulta falla se responde True (no se sirve el archivo).
    Un fallo de BD no puede convertirse en una filtración de comprobantes.
    """
    from app.db.database import SessionLocal
    from app.services.storage import PUBLIC_PREFIX

    # Se compara el FINAL de la URL guardada: cubre la forma relativa
    # (`/static/uploads/x.png`) y una absoluta vieja
    # (`https://host/static/uploads/x.png`). `right()` evita comodines de LIKE
    # inyectados desde el nombre pedido.
    sufijo = f"{PUBLIC_PREFIX}{nombre}"
    db = SessionLocal()
    try:
        if _referenciado(db, sufijo, COLUMNAS_COMPROBANTE):
            return True
        if not nombre.startswith(PREFIJO_LEGACY_COMPROBANTE):
            return False
        return not _referenciado(db, sufijo, COLUMNAS_PUBLICAS)
    except Exception:
        # Cualquier fallo al verificar (BD caída, tabla ausente) NIEGA el archivo:
        # un error no puede convertirse en una filtración de comprobantes.
        log.exception(
            "No se pudo verificar si %s es un comprobante; se niega por seguridad",
            nombre)
        return True
    finally:
        db.close()


def _nombre_en_uploads(path: str) -> str:
    """Nombre plano dentro de `uploads/`, o '' si el path no es de esa carpeta.

    Sólo se protegen los archivos PLANOS de uploads: cualquier subruta o intento
    de traversal lo resuelve (y lo rechaza) StaticFiles como siempre.
    """
    limpio = normpath(str(path or "").replace("\\", "/"))
    partes = limpio.split("/")
    if len(partes) != 2 or partes[0] != "uploads":
        return ""
    return partes[1]


class StaticFilesSinComprobantes(StaticFiles):
    """StaticFiles que nunca expone un comprobante guardado en la BD."""

    async def get_response(self, path, scope):
        nombre = _nombre_en_uploads(path)
        if nombre and await run_in_threadpool(es_comprobante_privado, nombre):
            # 404 (no 403): no se confirma que el archivo exista. El documento
            # sigue disponible por GET /solicitudes/{id}/voucher (con token).
            return PlainTextResponse("Not Found", status_code=404)
        return await super().get_response(path, scope)
