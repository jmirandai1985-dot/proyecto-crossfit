"""Configuración del negocio (datos bancarios por tenant): R1 y validaciones, SIN BD.

Qué cubre (nada de esto toca la base ni la API real: se arma una app mínima con el router
REAL y se reemplaza `get_db` por una sesión falsa en memoria —mismo patrón que
`test_notificaciones_panel.py` y el cliente falso de `test_storage_r2.py`):

  A. R1 — `GET /configuracion` exige token y el box sale del JWT: sin token -> 401, token
     inválido -> 401 y un token del box 1 pidiendo `?tenant_id=2` responde con el box 1
     (el query param se ignora: el filtro SQL usa el del token).
  B. PUT — sin body -> 422 (antes, sin body, era un 500 por `AttributeError`); se aplican
     SÓLO los campos enviados; un campo vacío BORRA el dato; con dos admins se escribe UNA
     fila de auditoría con `antes`/`despues` y un aviso `config_bancaria` por admin; y si
     el request no cambia nada, se audita pero NO se avisa.
  C. Validaciones de `ConfiguracionUpdate` (I2/M2/M3): cuenta sólo dígitos, RUT con dígito
     verificador real (módulo 11), email, `tipo_cuenta` en lista cerrada, largos y claves
     desconocidas.
  D. Guardas de FUENTE: el GET depende de `get_current_user` y el PUT de
     `get_current_admin`, los dos tienen rate limit, el `tenant_id` del query no puede
     volver a leerse, y el WhatsApp del pie de los correos sale escapado.

Los PERMISOS contra la API de verdad (401/403 con tokens reales y la fila en `auditoria`
leída de la BD) viven en `tests/test_configuracion_permisos.py` (integración: pide la API
de TEST levantada y ESCRIBE en la rama TEST).

Correr (sin API ni BD; `--noconftest` porque no usa el servidor):
    cd backend && py -3.12 -m pytest tests/test_configuracion_validacion.py -q --noconftest
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1.configuracion import (CAMPOS_EDITABLES, ConfiguracionUpdate,  # noqa: E402
                                      router)
from app.core.rate_limit import LIMIT_CONFIG_LECTURA, LIMIT_CRITICO, limiter   # noqa: E402
from app.core.security import create_access_token                              # noqa: E402
from app.db.database import get_db                                             # noqa: E402
from app.models.auditoria import Auditoria                                     # noqa: E402
from app.models.configuracion import ConfiguracionNegocio                      # noqa: E402
from app.models.notificacion import Notificacion                               # noqa: E402
from app.models.usuario import Usuario                                         # noqa: E402

TENANT = 1
OTRO_TENANT = 2
ADMIN_ID = 7
# Los DOS admins activos del box: el que guarda y el otro (el aviso va a los dos).
ADMINS_DEL_BOX = (7, 9)

# RUT reales del verificador: `12345678-5` es válido; `12.345.678-9` (el placeholder viejo
# de la pantalla) tiene el DV cambiado, así que sirve de contra-ejemplo.
RUT_OK = "12345678-5"
RUT_DV_MALO = "12.345.678-9"

FUENTE = (BACKEND / "app" / "api" / "v1" / "configuracion.py").read_text(encoding="utf-8")


class _Usuario:
    """Fila de `usuarios` que devuelve la sesión falsa (activa, con rol y tenant).

    `rol` va como STRING: es lo que devuelve `get_current_user` cuando lo lee de la BD
    (la columna es un enum de Postgres y el driver entrega el texto).
    """

    def __init__(self, usuario_id, tenant_id, rol="administrador", nombre="Admin"):
        self.id = usuario_id
        self.tenant_id = tenant_id
        self.rol = rol
        self.nombre = nombre
        self.correo = f"admin{usuario_id}@test.com"
        self.activo = True
        self.estado = "activo"


class _Res:
    def __init__(self, fila):
        self._fila = fila

    def first(self):
        return self._fila


class _Consulta:
    def __init__(self, filas):
        self.filas = list(filas)
        self.criterios = []

    def filter(self, *criterios):
        self.criterios.extend(criterios)
        return self

    def first(self):
        return self.filas[0] if self.filas else None

    def all(self):
        return list(self.filas)


class _SesionFalsa:
    """Session mínima: filtra por modelo, guarda lo que se agrega y no abre ninguna BD.

    `execute` devuelve el usuario que pide el token (así `get_current_user` respeta el
    `tenant_id` del JWT) y `query(ConfiguracionNegocio)` devuelve la fila que ya se guardó
    en este test (o ninguna), que es lo que la BD hace entre un request y el siguiente.
    """

    def __init__(self, admins=ADMINS_DEL_BOX):
        self.admins = list(admins)
        self.agregadas = []
        self.commits = 0
        self.flushes = 0
        self.consultas = []
        self.config = None

    def execute(self, _query, params=None):
        params = params or {}
        return _Res(_Usuario(params.get("usuario_id", ADMIN_ID),
                             params.get("tenant_id", TENANT)))

    def query(self, modelo):
        if modelo is Usuario:
            consulta = _Consulta(_Usuario(i, TENANT) for i in self.admins)
        elif modelo is ConfiguracionNegocio:
            consulta = _Consulta([self.config] if self.config else [])
        else:
            consulta = _Consulta([])
        self.consultas.append((modelo, consulta))
        return consulta

    def add(self, obj):
        self.agregadas.append(obj)
        if isinstance(obj, ConfiguracionNegocio):
            self.config = obj

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        # `updated_at` lo pone la BD (server_default + onupdate): acá se simula.
        obj.updated_at = datetime.now(timezone.utc)
        return obj

    def rollback(self):
        pass

    def close(self):
        pass

    def agregadas_de(self, modelo):
        return [o for o in self.agregadas if isinstance(o, modelo)]

    def consultas_de(self, modelo):
        return [c for m, c in self.consultas if m is modelo]


def _valores(consulta):
    """Los valores comparados en el `.filter(...)` (la frontera de tenant, en SQL)."""
    return [getattr(getattr(c, "right", None), "value", None) for c in consulta.criterios]


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures: app mínima con el router REAL + sesión falsa (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def sesion():
    return _SesionFalsa()


@pytest.fixture
def cliente(sesion):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router, prefix="/api/v1/configuracion")
    app.dependency_overrides[get_db] = lambda: sesion
    return TestClient(app)


def _auth(usuario_id=ADMIN_ID, tenant_id=TENANT, rol="administrador"):
    token = create_access_token({
        "usuario_id": usuario_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"admin{usuario_id}@test.com"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth():
    return _auth()


# ══════════════════════════════════════════════════════════════════════════════
# A. R1: el GET exige token y el box sale del TOKEN (el query param se ignora)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_sin_token_el_get_responde_401(cliente):
    """El bug (R1): `GET /configuracion?tenant_id=1..N` respondía 200 a cualquiera."""
    r = cliente.get(f"/api/v1/configuracion?tenant_id={OTRO_TENANT}")

    assert r.status_code == 401
    assert "Bearer" in r.headers.get("www-authenticate", "")
    assert "banco" not in r.text


def test_a2_un_token_invalido_tampoco_alcanza(cliente):
    r = cliente.get("/api/v1/configuracion?tenant_id=1",
                    headers={"Authorization": "Bearer basura"})

    assert r.status_code == 401


def test_a3_el_box_sale_del_token_y_no_del_query(cliente, sesion, auth):
    """Pidiendo el box 2 con un token del box 1, la respuesta es la del box 1."""
    r = cliente.get(f"/api/v1/configuracion?tenant_id={OTRO_TENANT}", headers=auth)

    assert r.status_code == 200
    assert r.json()["tenant_id"] == TENANT
    filtros = sesion.consultas_de(ConfiguracionNegocio)
    assert _valores(filtros[-1]) == [TENANT], "el filtro SQL no puede salir del query"


def test_a4_un_admin_de_otro_box_lee_su_propio_box(cliente, sesion):
    r = cliente.get("/api/v1/configuracion", headers=_auth(usuario_id=55,
                                                           tenant_id=OTRO_TENANT))

    assert r.status_code == 200
    assert r.json()["tenant_id"] == OTRO_TENANT
    assert _valores(sesion.consultas_de(ConfiguracionNegocio)[-1]) == [OTRO_TENANT]


def test_a5_un_alumno_del_box_puede_leer_los_datos_de_su_box(cliente):
    """Bazar y Solicitar plan los lee el ALUMNO (con su token): el GET no es admin-only."""
    r = cliente.get("/api/v1/configuracion", headers=_auth(usuario_id=99, rol="alumno"))

    assert r.status_code == 200
    assert r.json()["tenant_id"] == TENANT


# ══════════════════════════════════════════════════════════════════════════════
# B. El PUT: body requerido, cambio parcial, borrado, auditoría y aviso (I1/I2/M6)
# ══════════════════════════════════════════════════════════════════════════════
def test_b1_sin_body_responde_422_y_no_un_500(cliente, auth):
    """`data: ConfiguracionUpdate = None` hacía `data.banco` sobre None -> 500."""
    r = cliente.put("/api/v1/configuracion", headers=auth)

    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body"]


def test_b2_el_cambio_queda_en_auditoria_y_avisa_a_los_dos_admins(cliente, sesion, auth):
    r = cliente.put("/api/v1/configuracion", headers=auth,
                    json={"banco": "Banco de Chile", "numero_cuenta": RUT_DV_MALO,
                          "rut": RUT_OK})

    assert r.status_code == 200, r.text

    auditorias = sesion.agregadas_de(Auditoria)
    assert len(auditorias) == 1
    auditoria = auditorias[0]
    assert (auditoria.accion, auditoria.entidad, auditoria.usuario_id) == (
        "UPDATE", "configuracion_negocio", ADMIN_ID)
    assert auditoria.detalle["antes"] == {c: None for c in CAMPOS_EDITABLES}
    # El "después" es lo que QUEDÓ guardado (cuenta normalizada a dígitos).
    assert auditoria.detalle["despues"]["banco"] == "Banco de Chile"
    assert auditoria.detalle["despues"]["numero_cuenta"] == "123456789"

    avisos = sesion.agregadas_de(Notificacion)
    assert sorted(a.alumno_id for a in avisos) == sorted(ADMINS_DEL_BOX)
    assert {a.tipo for a in avisos} == {"config_bancaria"}
    assert all(a.leida is False for a in avisos)

    assert sesion.config.updated_by == ADMIN_ID
    assert r.json()["updated_by"] == ADMIN_ID
    assert r.json()["updated_at"] is not None


def test_b3_sin_cambios_se_audita_pero_no_se_avisa(cliente, sesion, auth):
    """Re-guardar el mismo formulario no puede llenar la campana de los admins."""
    cuerpo = {"banco": "Banco de Chile", "rut": RUT_OK}
    cliente.put("/api/v1/configuracion", headers=auth, json=cuerpo)
    sesion.agregadas.clear()

    r = cliente.put("/api/v1/configuracion", headers=auth, json=cuerpo)

    assert r.status_code == 200
    assert len(sesion.agregadas_de(Auditoria)) == 1
    assert sesion.agregadas_de(Notificacion) == []


def test_b4_un_request_parcial_no_pisa_el_resto(cliente, auth):
    cliente.put("/api/v1/configuracion", headers=auth,
                json={"banco": "Banco de Chile", "rut": RUT_OK})

    r = cliente.put("/api/v1/configuracion", headers=auth,
                    json={"whatsapp": "9 1234 5678"})

    assert r.status_code == 200
    assert r.json()["banco"] == "Banco de Chile"
    assert r.json()["rut"] == RUT_OK
    assert r.json()["whatsapp"] == "9 1234 5678"


def test_b5_un_campo_vacio_borra_el_dato(cliente, auth):
    """Antes `if data.banco is not None` hacía IMPOSIBLE vaciar un campo del formulario."""
    cliente.put("/api/v1/configuracion", headers=auth, json={"banco": "Banco de Chile"})

    r = cliente.put("/api/v1/configuracion", headers=auth, json={"banco": ""})

    assert r.status_code == 200
    assert r.json()["banco"] is None


def test_b6_el_put_tambien_valida(cliente, auth):
    r = cliente.put("/api/v1/configuracion", headers=auth,
                    json={"numero_cuenta": "12a456", "otra_clave": 1})

    assert r.status_code == 422
    campos = {e["loc"][-1] for e in r.json()["detail"]}
    assert {"numero_cuenta", "otra_clave"} <= campos


# ══════════════════════════════════════════════════════════════════════════════
# C. Validaciones de ConfiguracionUpdate (I2/M2/M3)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("caso,datos", [
    ("cuenta con letras", {"numero_cuenta": "12a456"}),
    ("cuenta muy corta", {"numero_cuenta": "123"}),
    ("cuenta de 21 dígitos", {"numero_cuenta": "1" * 21}),
    ("tipo de cuenta inventado", {"tipo_cuenta": "Corriente GOLD"}),
    ("tipo de cuenta en minúscula", {"tipo_cuenta": "corriente"}),
    ("RUT con el DV cambiado", {"rut": RUT_DV_MALO}),
    ("RUT que no es un RUT", {"rut": "abc"}),
    ("RUT sin guion", {"rut": "123456785"}),
    ("email que no es email", {"email_comprobantes": "pagos arroba box.cl"}),
    ("clave desconocida", {"beneficio_descuento_max_pct": 99}),
    ("banco de 201 caracteres", {"banco": "x" * 201}),
    ("cuenta de 51 caracteres", {"numero_cuenta": "1" * 51}),
    ("whatsapp de 31 caracteres", {"whatsapp": "9" * 31}),
])
def test_c1_lo_que_no_es_un_dato_bancario_valido_no_pasa(caso, datos):
    """Todo esto se guardaba tal cual y lo leía el alumno en la pantalla de transferencia."""
    with pytest.raises(ValidationError):
        ConfiguracionUpdate(**datos)


@pytest.mark.parametrize("crudo,esperado", [
    (RUT_DV_MALO, "123456789"),          # el guion del DV no es un separador de miles
    ("0012 3456 7890", "001234567890"),
    (" 12345678 ", "12345678"),
    ("12.345.678", "12345678"),
])
def test_c2_la_cuenta_se_guarda_solo_con_digitos(crudo, esperado):
    assert ConfiguracionUpdate(numero_cuenta=crudo).numero_cuenta == esperado


def test_c3_el_rut_se_guarda_normalizado():
    assert ConfiguracionUpdate(rut=RUT_OK).rut == RUT_OK
    # Mismo RUT con puntos y el DV en minúscula: se guarda en la forma canónica.
    assert ConfiguracionUpdate(rut="12.345.678-5").rut == RUT_OK


@pytest.mark.parametrize("tipo", ["Corriente", "Vista", "Rut", "Ahorro"])
def test_c4_los_tipos_de_cuenta_del_formulario_son_los_que_acepta_el_backend(tipo):
    """La lista cerrada del backend tiene que cubrir las opciones del <select>."""
    assert ConfiguracionUpdate(tipo_cuenta=tipo).tipo_cuenta == tipo
    fuente_jsx = (BACKEND.parent / "frontend" / "src" / "pages" / "admin"
                  / "Configuracion.jsx").read_text(encoding="utf-8")
    assert f'<option value="{tipo}">' in fuente_jsx


def test_c5_un_campo_vacio_es_none_pero_queda_marcado_como_enviado():
    """`""` significa "sin dato" (NULL), y `model_fields_set` distingue eso de "no lo mandó"."""
    modelo = ConfiguracionUpdate(banco="", whatsapp="   ", rut="")

    assert modelo.banco is None and modelo.whatsapp is None and modelo.rut is None
    assert {"banco", "whatsapp", "rut"} <= modelo.model_fields_set


def test_c6_un_body_parcial_marca_solo_lo_que_vino():
    assert ConfiguracionUpdate(whatsapp="9 1234 5678").model_fields_set == {"whatsapp"}


# ══════════════════════════════════════════════════════════════════════════════
# D. Guardas de FUENTE y del texto del correo
# ══════════════════════════════════════════════════════════════════════════════
def test_d1_el_get_exige_token_y_el_put_admin():
    """Guardas de fuente: el día que alguien quite una dependencia, esto se pone rojo."""
    assert "current_user: dict = Depends(get_current_user)" in FUENTE
    assert 'tenant_id = current_user["tenant_id"]' in FUENTE
    assert "current_user: dict = Depends(get_current_admin)" in FUENTE
    # El query param sigue declarado (clientes viejos lo mandan) pero NO se puede leer.
    assert "tenant_id: Optional[int] = None" in FUENTE


def test_d2_los_dos_endpoints_tienen_rate_limit():
    assert "@limiter.limit(LIMIT_CONFIG_LECTURA)" in FUENTE
    assert "@limiter.limit(LIMIT_CRITICO)" in FUENTE
    assert LIMIT_CONFIG_LECTURA != LIMIT_CRITICO


def test_d3_el_whatsapp_del_pie_del_correo_sale_escapado(monkeypatch):
    """El número lo escribe el admin a mano y termina en el HTML del correo (M3)."""
    from app.services import email_service

    monkeypatch.setattr(email_service, "contacto_del_box",
                        lambda tenant_id=None: '+56 9 1111 2222<b>"x"')

    bloque = email_service.bloque_contacto(TENANT)

    assert "<b>" not in bloque
    assert "&lt;b&gt;" in bloque
    assert "https://wa.me/56911112222" in bloque, "el link se arma con los dígitos"


def test_d4_sin_datos_bancarios_las_pantallas_de_alumno_avisan():
    """Bazar (I3) y Solicitar plan: el pie bloqueante no puede quedar sólo en uno."""
    raiz = BACKEND.parent / "frontend" / "src"
    bazar = (raiz / "pages" / "alumno" / "Bazar.jsx").read_text(encoding="utf-8")
    solicitar = (raiz / "pages" / "alumno" / "SolicitarPlan.jsx").read_text(encoding="utf-8")

    for fuente, nombre in ((bazar, "Bazar.jsx"), (solicitar, "SolicitarPlan.jsx")):
        assert "aún no ha configurado sus datos de pago" in fuente, nombre
    # En el Bazar, sin datos bancarios no se puede comprar ni enviar el pedido.
    assert "disabled={!configBancaria}" in bazar
    assert "disabled={subiendo || !archivoVoucher || !configBancaria}" in bazar

