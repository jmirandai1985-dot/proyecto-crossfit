"""
Invitaciones ALUMNO → ALUMNO (migración 054) — tests SIN base de datos.

Qué cubre, sin levantar Postgres ni el servidor:
  * el link rastreable es único, no adivinable y apunta a `/landing?inv=`;
  * las reglas anti-abuso puras (`motivo_invitacion_rechazada`) y el
    normalizado del correo;
  * `marcar_invitacion_registrada` deja la fila `registrado` + usuario (y un
    token inválido no rompe nada);
  * los serializadores de los dos endpoints, incluido `{codigo: null}`;
  * el schema del body prohíbe campos extra y valida el correo;
  * el alta acepta `token_invitacion` opcional;
  * el correo de invitación no intenta enviar sin destinatario;
  * el router expone `GET /mi-invitacion` y `POST /invitaciones`;
  * la 054 agrega el valor de enum y las columnas sin recrear el tipo.

    cd backend && py -3.12 -m pytest tests/test_invitaciones_alumno.py -q --noconftest
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.referidos import EstadoInvitacion, Invitacion, OrigenInvitacion
from app.services import referidos_service as svc

RAIZ = Path(__file__).resolve().parents[1]          # .../backend


# ── Link rastreable ──────────────────────────────────────────────────────────

def test_el_token_es_unico_largo_y_url_safe():
    tokens = {svc.generar_token_invitacion() for _ in range(200)}
    assert len(tokens) == 200, "dos tokens iguales: colisión inaceptable"
    for token in tokens:
        assert 20 <= len(token) <= 64, token
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token), token


def test_el_enlace_apunta_al_formulario_de_clase_de_prueba():
    assert svc.enlace_invitacion("abc123").endswith("/landing?inv=abc123")


def test_el_correo_se_normaliza_como_en_el_alta():
    assert svc.normalizar_correo_invitacion("  Amigo@Box.CL ") == "amigo@box.cl"
    assert svc.normalizar_correo_invitacion(None) == ""


# ── Anti-abuso (función pura) ────────────────────────────────────────────────

def test_las_reglas_anti_abuso_tienen_prioridad_fija():
    assert svc.motivo_invitacion_rechazada(
        es_propio=True, ya_usuario=True, enviada_reciente=True
    ) == svc.MOTIVO_INVITACION_PROPIA
    assert svc.motivo_invitacion_rechazada(
        es_propio=False, ya_usuario=True, enviada_reciente=True
    ) == svc.MOTIVO_INVITACION_YA_USUARIO
    assert svc.motivo_invitacion_rechazada(
        es_propio=False, ya_usuario=False, enviada_reciente=True
    ) == svc.MOTIVO_INVITACION_DUPLICADA
    assert svc.motivo_invitacion_rechazada(
        es_propio=False, ya_usuario=False, enviada_reciente=False) is None


def test_los_limites_declarados_son_los_acordados():
    assert svc.LIMITE_INVITACIONES_DIA == 5
    assert svc.DIAS_BLOQUEO_REENVIO == 7


# ── La fila y sus serializadores ─────────────────────────────────────────────

def test_la_invitacion_queda_registrada_con_su_usuario():
    ahora = datetime.now(timezone.utc)
    invitacion = Invitacion(
        tenant_id=1, origen=OrigenInvitacion.alumno,
        correo_prospecto="amigo@box.cl", token_rastreo="tok",
        estado=EstadoInvitacion.enviada)

    svc.marcar_invitacion_registrada(invitacion, 42, momento=ahora)

    assert invitacion.estado == EstadoInvitacion.registrado
    assert invitacion.usuario_registrado_id == 42
    assert invitacion.fecha_registro == ahora

    # Un token inválido (None) se ignora: el alta no puede fallar por eso.
    svc.marcar_invitacion_registrada(None, 42)


def test_mi_invitacion_sin_invitacion_devuelve_codigo_nulo():
    assert svc.datos_mi_invitacion(None, None, None) == {
        "codigo": None,
        "nombre_invitador": None,
        "estado": None,
        "fecha_registro": None,
    }


def test_mi_invitacion_devuelve_el_codigo_del_invitador():
    ahora = datetime.now(timezone.utc)
    invitacion = Invitacion(
        tenant_id=1, origen=OrigenInvitacion.alumno,
        correo_prospecto="amigo@box.cl", estado=EstadoInvitacion.registrado,
        fecha_registro=ahora)

    datos = svc.datos_mi_invitacion(invitacion, "JPERE234", "Juan Pérez")

    assert datos["codigo"] == "JPERE234"
    assert datos["nombre_invitador"] == "Juan Pérez"
    assert datos["estado"] == "registrado"
    assert datos["fecha_registro"] == ahora


def test_la_respuesta_del_envio_trae_el_enlace_reenviable():
    ahora = datetime.now(timezone.utc)
    invitacion = Invitacion(
        tenant_id=1, origen=OrigenInvitacion.alumno,
        correo_prospecto="amigo@box.cl", token_rastreo="tok-123",
        estado=EstadoInvitacion.enviada, fecha_envio=ahora)

    datos = svc.datos_invitacion_enviada(invitacion, "JPERE234")

    assert datos["codigo"] == "JPERE234"
    assert datos["token_rastreo"] == "tok-123"
    assert datos["enlace"].endswith("/landing?inv=tok-123")
    assert datos["estado"] == "enviada"
    assert datos["fecha_envio"] == ahora


# ── Contrato HTTP y alta ─────────────────────────────────────────────────────

def test_el_body_de_invitar_prohibe_campos_extra_y_valida_correo():
    from app.schemas.referidos import InvitarAlumnoRequest

    # `EmailStr` normaliza el DOMINIO a minúsculas (el local part lo respeta).
    assert str(InvitarAlumnoRequest(correo="Amigo@Box.cl").correo) == \
        "Amigo@box.cl"

    with pytest.raises(ValidationError):
        InvitarAlumnoRequest(correo="no-es-un-correo")

    # El usuario y el código salen del TOKEN: mandarlos es un 422, no un campo
    # ignorado en silencio.
    with pytest.raises(ValidationError):
        InvitarAlumnoRequest(correo="amigo@box.cl", usuario_id=1)


def test_el_alta_acepta_el_token_de_invitacion_opcional():
    from app.api.v1.alumnos import RegistroAlumnoNuevo

    base = {"nombre": "Ana María", "correo": "ana@box.cl",
            "rut": "12.345.678-5"}

    assert RegistroAlumnoNuevo(**base).token_invitacion is None
    assert RegistroAlumnoNuevo(
        **base, token_invitacion="tok-123").token_invitacion == "tok-123"


def test_el_correo_de_invitacion_no_envia_sin_destinatario():
    from app.services.email_service import send_invitacion_alumno

    assert send_invitacion_alumno(
        "Juan Pérez", "", "JPERE234", "https://box.cl/landing?inv=x") is False


def test_el_router_expone_los_dos_endpoints_de_invitacion():
    from app.api.v1 import referidos as router_referidos

    por_ruta = {ruta.path: set(getattr(ruta, "methods", ()) or ())
                for ruta in router_referidos.router.routes}
    assert "GET" in por_ruta["/mi-invitacion"]
    assert "POST" in por_ruta["/invitaciones"]


# ── Migración 054 ────────────────────────────────────────────────────────────

def _fuente_migracion() -> str:
    return (RAIZ / "alembic" / "versions" /
            "054_invitaciones_alumno.py").read_text(encoding="utf-8-sig")


def test_la_054_agrega_el_valor_sin_recrear_el_tipo():
    fuente = _fuente_migracion()

    assert 'VALORES_NUEVOS_ORIGEN = ("alumno",)' in fuente
    # El ALTER TYPE se arma con placeholders: el valor vive en la constante.
    assert "ALTER TYPE {TIPO_ORIGEN} ADD VALUE IF NOT EXISTS '{valor}'" \
        in fuente
    assert "create_type" not in fuente, \
        "la 054 no crea el tipo: sólo le agrega el valor"
    assert "uq_invitaciones_token_rastreo" in fuente
    assert "ix_invitaciones_usuario_registrado_id" in fuente
    assert 'ondelete="SET NULL"' in fuente


def test_la_054_no_toca_el_dinero_ni_la_configuracion():
    """La migración es aditiva: ningún DROP/ALTER de tablas de negocio."""
    fuente = _fuente_migracion()

    assert "referidos_aplicados" not in fuente
    assert "creditos_referido" not in fuente
    assert "configuracion_referidos" not in fuente

