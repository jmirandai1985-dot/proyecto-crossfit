"""
Capa ÚNICA de almacenamiento (app/services/storage.py): backend LOCAL y R2 FAKE.

Qué se prueba, SIN red, SIN boto3 y SIN base de datos:
  * local: guardar/leer un archivo privado y uno público (las URLs de siempre);
  * r2 (cliente FALSO en memoria): subir+leer el privado, la URL pública absoluta
    de la imagen de un producto y el error CLARO si el objeto no está;
  * 400 origen desconocido / 403 path traversal en los dos backends;
  * STORAGE_BACKEND desconocido -> error explícito (no cae a "local" en silencio);
  * el mapeo a códigos HTTP del guard (documentos_privados.respuesta_documento):
    400 / 403 / 404 y las respuestas 200 (FileResponse local, streaming en R2).

El 401 y el 403 cross-tenant (dueño/box) los cubre la prueba de integración
test_documentos_solicitud_privados.py, que sí pega contra la API.
"""
import io
import os

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.core import documentos_privados
from app.core.config import settings
from app.services import storage

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63f8cff00000050101ff9c9c4f9c")


class SinObjeto(Exception):
    """Equivalente al NoSuchKey del cliente real (mismo `response` que botocore)."""

    def __init__(self):
        super().__init__("NoSuchKey")
        self.response = {"Error": {"Code": "NoSuchKey"}}


class ClienteR2Fake:
    """Cliente S3 EN MEMORIA con lo único que usa la capa: put/get_object."""

    def __init__(self):
        self.objetos = {}
        self.subidas = []          # (bucket, clave, content_type)

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objetos[(Bucket, Key)] = Body
        self.subidas.append((Bucket, Key, ContentType))
        return {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objetos:
            raise SinObjeto()
        return {"Body": io.BytesIO(self.objetos[(Bucket, Key)])}


@pytest.fixture
def local(tmp_path, monkeypatch):
    """Backend local en carpetas TEMPORALES (no ensucia el repo)."""
    static = tmp_path / "static"
    priv = tmp_path / "private_uploads"
    pub = static / "uploads"
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(storage, "PRIVATE_DIR", str(priv))
    monkeypatch.setattr(storage, "STATIC_DIR", str(static))
    monkeypatch.setattr(storage, "UPLOAD_DIR", str(pub))
    return priv, pub


@pytest.fixture
def r2(monkeypatch):
    """Backend r2 con cliente FALSO (no se importa boto3 ni se toca la red).

    Dos buckets, como en PROD: el privado SIN acceso público y el público aparte
    (Cloudflare expone el bucket completo, no un prefijo).
    """
    cliente = ClienteR2Fake()
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "r2")
    monkeypatch.setattr(settings, "STORAGE_R2_ENDPOINT",
                        "https://fake.r2.cloudflarestorage.com")
    monkeypatch.setattr(settings, "STORAGE_R2_BUCKET", "box-crossfit-uploads-test")
    monkeypatch.setattr(settings, "STORAGE_R2_PUBLIC_BUCKET", "box-crossfit-public-test")
    monkeypatch.setattr(settings, "STORAGE_R2_ACCESS_KEY_ID", "AKIAFAKE")
    monkeypatch.setattr(settings, "STORAGE_R2_SECRET_ACCESS_KEY", "secreto-falso")
    monkeypatch.setattr(settings, "STORAGE_R2_PUBLIC_BASE_URL", "https://pub-fake.r2.dev")
    monkeypatch.setattr(storage, "_cliente_r2", lambda: cliente)
    return cliente


# ═══════════════════════════════════════════════════════════════════
# Backend local (dev/TEST): igual que antes de la capa
# ═══════════════════════════════════════════════════════════════════

def test_local_privado_ida_y_vuelta(local):
    url = storage.guardar_privado(b"contenido-voucher", "voucher_a.pdf")

    assert url == "/privado/vouchers/voucher_a.pdf"      # misma URL que se guarda en BD
    doc = storage.abrir_privado(url, "voucher")
    assert doc.nombre == "voucher_a.pdf"
    assert doc.flujo is None
    with open(doc.ruta, "rb") as f:
        assert f.read() == b"contenido-voucher"


def test_local_publico_url_de_static(local):
    priv, pub = local
    assert storage.guardar_publico(PNG_1X1, "producto_1.png") == \
        "/static/uploads/producto_1.png"
    assert (pub / "producto_1.png").read_bytes() == PNG_1X1


def test_local_legacy_vive_en_static_y_avisa_si_no_esta(local):
    """El comprobante HISTÓRICO (/static/...) se sirve si está; si no, mensaje claro."""
    _priv, _pub = local
    legacy = "/static/uploads/voucher_viejo.png"

    with pytest.raises(storage.ArchivoNoDisponible) as e:
        storage.abrir_privado(legacy, "voucher")
    assert "lo vuelva a subir" in str(e.value)

    ruta = os.path.join(storage.STATIC_DIR, "uploads", "voucher_viejo.png")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "wb") as f:
        f.write(PNG_1X1)
    assert storage.abrir_privado(legacy, "voucher").ruta == ruta


def test_local_rechaza_traversal_y_origen_desconocido(local):
    with pytest.raises(storage.RutaNoPermitida):
        storage.abrir_privado("/static/../../../etc/passwd", "voucher")
    with pytest.raises(storage.OrigenNoSoportado):
        storage.abrir_privado("https://otro-sitio.example/voucher.png", "voucher")


# ═══════════════════════════════════════════════════════════════════
# Backend r2 (cliente falso, sin red)
# ═══════════════════════════════════════════════════════════════════

def test_r2_privado_ida_y_vuelta(r2):
    """Sube al prefijo privado y lo vuelve a leer por streaming."""
    url = storage.guardar_privado(b"contenido-voucher", "voucher_b.pdf")

    assert url == "/privado/vouchers/voucher_b.pdf"       # MISMA URL en la BD que en local
    assert ("box-crossfit-uploads-test", "privado/vouchers/voucher_b.pdf",
            "application/pdf") in r2.subidas           # con su Content-Type

    doc = storage.abrir_privado(url, "voucher")
    assert doc.ruta is None                                # en R2 NO hay path local
    assert doc.nombre == "voucher_b.pdf"
    assert doc.flujo.read() == b"contenido-voucher"


def test_r2_imagen_de_producto_va_al_bucket_publico(r2):
    """La foto del producto NO se guarda con los comprobantes: bucket público aparte."""
    url = storage.guardar_publico(PNG_1X1, "producto_9.png")

    assert url == "https://pub-fake.r2.dev/publico/producto_9.png"
    assert ("box-crossfit-public-test", "publico/producto_9.png",
            "image/png") in r2.subidas
    # Y NADA quedó en el bucket privado (el que no tiene acceso público).
    assert not [s for s in r2.subidas if s[0] == "box-crossfit-uploads-test"]


def test_r2_sin_bucket_publico_usa_el_privado(r2, monkeypatch):
    """Sin STORAGE_R2_PUBLIC_BUCKET (dev/TEST) se usa el mismo bucket."""
    monkeypatch.setattr(settings, "STORAGE_R2_PUBLIC_BUCKET", "")
    storage.guardar_publico(PNG_1X1, "producto_11.png")
    assert ("box-crossfit-uploads-test", "publico/producto_11.png",
            "image/png") in r2.subidas


def test_r2_imagen_sin_url_publica_falla_claro(r2, monkeypatch):
    """Sin STORAGE_R2_PUBLIC_BASE_URL no se puede guardar: se avisa, no se rompe."""
    monkeypatch.setattr(settings, "STORAGE_R2_PUBLIC_BASE_URL", "")
    with pytest.raises(storage.ErrorAlmacenamiento) as e:
        storage.guardar_publico(PNG_1X1, "producto_10.png")
    assert "STORAGE_R2_PUBLIC_BASE_URL" in str(e.value)


def test_r2_objeto_inexistente_avisa_que_se_vuelva_a_subir(r2):
    """El objeto que ya no está en R2 responde con el mensaje claro (no un 404 mudo)."""
    with pytest.raises(storage.ArchivoNoDisponible) as e:
        storage.abrir_privado("/privado/vouchers/voucher_perdido.pdf", "voucher")
    assert "lo vuelva a subir" in str(e.value)


def test_r2_legacy_static_no_se_busca_en_el_bucket(r2):
    """Los comprobantes HISTÓRICOS (/static/...) NO viven en R2: archivo perdido."""
    with pytest.raises(storage.ArchivoNoDisponible):
        storage.abrir_privado("/static/uploads/voucher_viejo.png", "voucher")
    assert r2.subidas == [] and r2.objetos == {}


def test_r2_rechaza_traversal_y_origen_desconocido(r2):
    with pytest.raises(storage.RutaNoPermitida):
        storage.abrir_privado("/privado/vouchers/../../etc/passwd", "voucher")
    with pytest.raises(storage.RutaNoPermitida):
        storage.abrir_privado("/privado/vouchers/sub/carpeta.pdf", "voucher")
    with pytest.raises(storage.OrigenNoSoportado):
        storage.abrir_privado("r2://privado/vouchers/x.pdf", "voucher")


def test_backend_desconocido_no_cae_a_local(r2, monkeypatch):
    """Un STORAGE_BACKEND con typo es ERROR: no se escribe en el disco efímero."""
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
    with pytest.raises(storage.ErrorAlmacenamiento) as e:
        storage.guardar_privado(b"x", "voucher_c.pdf")
    assert "STORAGE_BACKEND" in str(e.value)


# ═══════════════════════════════════════════════════════════════════
# El guard: mapeo a códigos HTTP (una sola implementación, dos backends)
# ═══════════════════════════════════════════════════════════════════

def test_guard_400_origen_desconocido(r2):
    with pytest.raises(HTTPException) as e:
        documentos_privados.respuesta_documento(
            "https://otro-sitio.example/certificado.png", "certificado", False)
    assert e.value.status_code == 400


def test_guard_403_path_traversal(r2):
    with pytest.raises(HTTPException) as e:
        documentos_privados.respuesta_documento(
            "/privado/vouchers/../../../etc/passwd", "voucher", False)
    assert e.value.status_code == 403


def test_guard_404_archivo_perdido_con_mensaje(r2):
    with pytest.raises(HTTPException) as e:
        documentos_privados.respuesta_documento(
            "/privado/vouchers/voucher_perdido.pdf", "voucher", False)
    assert e.value.status_code == 404
    assert "lo vuelva a subir" in str(e.value.detail)


def test_guard_200_r2_transmite_por_streaming(r2):
    """En R2 el documento sale por STREAMING (sin prefirmar y sin bucket público)."""
    storage.guardar_privado(b"pdf-bytes", "voucher_d.pdf")

    respuesta = documentos_privados.respuesta_documento(
        "/privado/vouchers/voucher_d.pdf", "voucher", False)

    assert isinstance(respuesta, StreamingResponse)
    assert respuesta.media_type == "application/pdf"
    assert respuesta.headers["content-disposition"] == \
        "attachment; filename=voucher_d.pdf"


def test_guard_200_local_usa_file_response(local):
    """En local sigue saliendo igual que siempre: FileResponse con su tipo real."""
    ruta = os.path.join(storage.PRIVATE_DIR, "certificado_1.png")
    os.makedirs(storage.PRIVATE_DIR, exist_ok=True)
    with open(ruta, "wb") as f:
        f.write(PNG_1X1)

    respuesta = documentos_privados.respuesta_documento(
        "/privado/vouchers/certificado_1.png", "certificado", True)

    assert isinstance(respuesta, FileResponse)
    assert respuesta.media_type == "image/png"
    assert respuesta.headers["content-disposition"] == \
        "inline; filename=certificado_1.png"

