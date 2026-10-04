"""
Servido de documentos PRIVADOS (comprobantes de pago y certificados).

Los comprobantes tienen DOS orígenes históricos y ambos se resuelven en la capa
ÚNICA de almacenamiento (`app/services/storage.py`):
  - `/privado/vouchers/...` -> lo que se sube hoy (disco en dev/TEST, R2 en PROD)
  - `/static/uploads/...`   -> comprobantes VIEJOS del disco efímero (si el
                               archivo ya no está, se avisa con un mensaje claro)

En los dos casos se sirven SOLO por endpoints autenticados (con guard de
dueño/box) y con el chequeo anti path-traversal hecho en la capa de almacenamiento.

POR QUÉ EXISTE: el voucher de un plan, el comprobante de un pedido y el certificado
de estudiante se sirven igual. Con la resolución y la respuesta en un solo lugar,
un endpoint nuevo (p. ej. el certificado) no puede olvidarse del guard ni del
chequeo de traversal, y no hay dos copias que se desincronicen.
"""
import mimetypes

from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.services import storage

# Las URLs que se guardan en BD para los comprobantes PRIVADOS / PÚBLICOS.
PRIVATE_PREFIX = storage.PRIVATE_PREFIX
STATIC_PREFIX = storage.STATIC_PREFIX

# Roles del box que pueden ver los comprobantes de sus alumnos (staff).
ROLES_STAFF = ("coach", "admin", "administrador")


def respuesta_documento(url_documento: str, etiqueta: str, inline: bool):
    """Respuesta con el documento privado de la URL guardada en BD (un solo paso).

    El archivo lo abre la capa de almacenamiento:
      - backend local: FileResponse desde el disco;
      - backend R2: STREAMING del objeto (nunca una URL prefirmada ni el bucket
        público: el prefijo `privado/` no está expuesto).

    Códigos: 400 origen no soportado, 403 path traversal, 404 el archivo ya no está
    (disco efímero de un deploy anterior) — con el mensaje que pide volver a subirlo.
    """
    try:
        documento = storage.abrir_privado(url_documento, etiqueta)
    except storage.OrigenNoSoportado as e:
        raise HTTPException(
            status_code=400, detail=f"Origen de {etiqueta} no soportado") from e
    except storage.RutaNoPermitida as e:
        raise HTTPException(status_code=403, detail="Acceso denegado") from e
    except storage.ArchivoNoDisponible as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    nombre = documento.nombre
    media_type = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    # attachment = descarga forzada; inline = previsualización en el panel
    disposicion = "inline" if inline else "attachment"
    headers = {"Content-Disposition": f"{disposicion}; filename={nombre}"}

    if documento.ruta:
        return FileResponse(path=documento.ruta, media_type=media_type, headers=headers)
    return StreamingResponse(documento.flujo, media_type=media_type, headers=headers)


def puede_ver_documento(usuario_id: int, tenant_id: int, alumno_id: int,
                        tenant_documento: int, rol: str) -> bool:
    """True si quien pide puede ver el documento de ESE alumno/box.

    Solo (a) el alumno dueño del documento, o (b) staff del MISMO box. Sin esto,
    cualquier usuario autenticado podía leer comprobantes ajenos de cualquier
    tenant con solo cambiar el id (IDOR).
    """
    es_dueno = usuario_id == alumno_id
    es_staff_mismo_box = rol in ROLES_STAFF and tenant_id == tenant_documento
    return es_dueno or es_staff_mismo_box
