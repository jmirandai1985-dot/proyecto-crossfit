"""
Alta de la suscripción recurrente y el vínculo que deja para el webhook.

Qué se prueba (sin red y sin base: `_SesionFalsa` + doble del SDK en
`mp._SDK_CACHE`, que es el patrón de `test_pago_mercadopago_descuento.py`):

1. **El alta** (`services/suscripciones_mp.crear_suscripcion_mp` +
   `mp.crear_preapproval`) manda a MP lo que la referencia de Suscripciones pide
   —`reason`, `external_reference=sus:<id>`, `payer_email`, `status=pending`,
   `auto_recurring`— y guarda el `id` que devuelve MP en `mp_preapproval_id`.
   Es el dato que hace que el webhook ya no dependa del correo del comprador.
2. **Los atajos**: si el alumno ya tiene un `preapproval` pendiente se REUSA su
   checkout (dos clics no pueden terminar en dos cobros recurrentes); si ya está
   autorizado se responde 409; si MP falla, la fila `pendiente` se borra.
3. **El resolver** (`buscar_suscripcion`) mantiene el orden
   `mp_preapproval_id` -> `external_reference` -> `payer_email`, y
   `procesar_preapproval` vincula por referencia una fila que todavía no tenía id
   y le abre el periodo en el momento en que MP autoriza.
4. **El contrato del endpoint** `POST /pagos/suscripcion`: 200 con el
   `init_point`, 503 si MP no responde, 503 si la pasarela está apagada.
5. **La carrera del alta** (fix de la migración 082): dos altas simultáneas del
   MISMO alumno+plan producen UNA sola fila `pendiente` y UN solo
   `preapproval`; la que pierde el INSERT recibe 409 sin llegar a Mercado Pago.
   El índice único parcial está declarado igual en el modelo y en la 082.

El flujo completo contra la BD de TEST (filas reales) está en
`tests/test_mp_webhook_suscripciones_integracion.py`.

Correr (aislado, sin servidor ni suite completa):
    cd backend && py -3.12 -m pytest tests/test_suscripcion_mp_alta.py -q
"""
import importlib.util
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import pagos as api_pagos            # noqa: E402
from app.core.config import settings                 # noqa: E402
from app.core.dependencies import require_full_access  # noqa: E402
from app.core.rate_limit import limiter              # noqa: E402
from app.db.database import get_db                   # noqa: E402
from app.models.plan import Plan                     # noqa: E402
from app.models.suscripcion import (                 # noqa: E402
    EstadoSuscripcion, NOMBRE_INDICE_PENDIENTE_UNICA, PREDICADO_PENDIENTE,
    Suscripcion, es_suscripcion_pendiente_duplicada,
)
from app.models.usuario import Usuario                              # noqa: E402
from app.services import mercadopago_cliente as mp                   # noqa: E402
from app.services import suscripciones_mp                            # noqa: E402
from app.utils.santiago import fin_de_plan_chile                     # noqa: E402

# Token de mentira: el test verifica qué se le manda a MP, nunca un token real.
TOKEN_MP = "TEST-token-suscripcion"
ALUMNO = {"usuario_id": 55, "tenant_id": 1, "rol": "alumno",
          "correo": "alumno@test.com"}
PRECIO = 44990
ID_FILA = 4242


# ── Dobles ───────────────────────────────────────────────────────────────────

class _Consulta:
    """Cadena `query(...).filter(...).order_by(...).first()` de mentira."""

    def __init__(self, resultado, resultado_join=None):
        self._resultado = resultado
        self._resultado_join = resultado_join

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        # `plan_vigente_usable` (cola de planes) consulta con `.join(Plan...)`.
        # En estos tests no hay otro plan vigente, así que devuelve None.
        return _Consulta(self._resultado_join)

    def first(self):
        return self._resultado


class _SesionFalsa:
    """Sesión de mentira con una fila por tabla.

    `add()` le asigna el id a la fila nueva, como haría el `INSERT`: el servicio
    necesita ese id para armar `external_reference = sus:<id>`.
    """

    def __init__(self, *, plan=None, usuario=None, previa=None,
                 id_nuevo=ID_FILA, falla_commit=False):
        self.plan = plan
        self.usuario = usuario
        self.previa = previa
        self.id_nuevo = id_nuevo
        self.falla_commit = falla_commit
        self.agregados = []
        self.eliminados = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, modelo):
        if modelo is Plan:
            return _Consulta(self.plan)
        if modelo is Usuario:
            return _Consulta(self.usuario)
        if modelo is Suscripcion:
            return _Consulta(self.previa)
        return _Consulta(None)

    def add(self, objeto):
        self.agregados.append(objeto)
        if getattr(objeto, "id", None) is None:
            objeto.id = self.id_nuevo

    def delete(self, objeto):
        self.eliminados.append(objeto)

    def commit(self):
        self.commits += 1
        if self.falla_commit:
            raise RuntimeError("la base se cayó")

    def rollback(self):
        self.rollbacks += 1


class _SesionSecuencial:
    """Sesión cuyo `query()` devuelve el SIGUIENTE resultado de esa tabla.

    El resolver consulta la misma tabla varias veces con criterios distintos
    (id de MP, referencia, correo): una lista por tabla dice exactamente qué
    devuelve cada consulta, en orden.

    Las claves son las CLASES del modelo: no sirve `**kwargs`, porque ahí las
    claves son strings y `db.query(Suscripcion)` no encontraría la lista.
    """

    def __init__(self, *, suscripcion=(), usuario=(), plan=()):
        self.restantes = {Suscripcion: list(suscripcion),
                          Usuario: list(usuario),
                          Plan: list(plan)}
        self.commits = 0

    def query(self, modelo):
        cola = self.restantes.get(modelo) or []
        return _Consulta(cola.pop(0) if cola else None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class _SesionCarrera:
    """Sesión de mentira que IMPONE el índice único parcial de la migración 082.

    `commit()` se comporta como Postgres: si ya hay una fila `pendiente`
    confirmada del mismo (usuario_id, plan_id), el INSERT de la nueva choca
    contra `uq_suscripciones_pendiente_por_alumno_plan` y no se confirma nada.
    Así el test reproduce la carrera real —entre la fila `pendiente` y el
    `mp_preapproval_id` hay una llamada HTTP— sin threads.
    """

    def __init__(self, *, plan=None, usuario=None, pendientes=()):
        self.plan = plan
        self.usuario = usuario
        self.pendientes = list(pendientes)  # filas `pendiente` YA confirmadas
        self.sin_confirmar = []
        self.commits = 0
        self.rollbacks = 0
        self.duplicados = 0
        self._siguiente_id = 5000

    def query(self, modelo):
        if modelo is Plan:
            return _Consulta(self.plan)
        if modelo is Usuario:
            return _Consulta(self.usuario)
        if modelo is Suscripcion:
            # `_previa_reutilizable`: sólo las que YA tienen id de MP.
            con_id = [f for f in self.pendientes if f.mp_preapproval_id]
            return _Consulta(con_id[-1] if con_id else None)
        return _Consulta(None)

    def add(self, objeto):
        self.sin_confirmar.append(objeto)

    def _choca_con_el_indice(self, objeto) -> bool:
        if suscripciones_mp.valor_estado(objeto.estado) != "pendiente":
            return False
        return any(
            suscripciones_mp.valor_estado(otra.estado) == "pendiente"
            and otra.usuario_id == objeto.usuario_id
            and otra.plan_id == objeto.plan_id
            for otra in self.pendientes)

    def commit(self):
        self.commits += 1
        for objeto in self.sin_confirmar:
            if self._choca_con_el_indice(objeto):
                self.duplicados += 1
                raise IntegrityError(
                    "INSERT INTO suscripciones ...", {},
                    Exception("duplicate key value violates unique constraint "
                              f'"{NOMBRE_INDICE_PENDIENTE_UNICA}"'))
            self._siguiente_id += 1
            objeto.id = self._siguiente_id
        self.pendientes.extend(self.sin_confirmar)
        self.sin_confirmar.clear()

    def rollback(self):
        self.rollbacks += 1
        self.sin_confirmar.clear()


class _PreapprovalMP:
    """`sdk.preapproval()`: guarda lo que se le manda y devuelve lo que se le pide."""

    def __init__(self, *, creado=None, actual=None, error_create=None,
                 error_get=None):
        self.payloads = []
        self.leidos = []
        self.creado = creado if creado is not None else {
            "status": 201,
            "response": {"id": "pre-1", "status": "pending",
                         "init_point": "https://mp/checkout"},
        }
        self.actual = actual if actual is not None else {
            "status": 200,
            "response": {"id": "pre-viejo", "status": "pending",
                         "init_point": "https://mp/reuso"},
        }
        self.error_create = error_create
        self.error_get = error_get

    def create(self, datos):
        self.payloads.append(datos)
        if self.error_create is not None:
            raise self.error_create
        return self.creado

    def get(self, preapproval_id):
        self.leidos.append(preapproval_id)
        if self.error_get is not None:
            raise self.error_get
        return self.actual


class _SDKFalso:
    def __init__(self, preapproval):
        self._preapproval = preapproval

    def preapproval(self):
        return self._preapproval


@pytest.fixture(autouse=True)
def pasarela(monkeypatch):
    """Pasarela ENCENDIDA + SDK de mentira: nada sale a la red.

    `monkeypatch.setitem` borra la entrada de `_SDK_CACHE` al terminar, así el SDK
    real queda intacto (mismo patrón que `test_pago_mercadopago_descuento.py`).
    """
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", True, raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", TOKEN_MP,
                        raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_MODO", "test", raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_BACK_URL_BASE",
                        "https://app.test", raising=False)
    doble = _PreapprovalMP()
    monkeypatch.setitem(mp._SDK_CACHE, TOKEN_MP, _SDKFalso(doble))
    return doble


def _con_sdk(monkeypatch, doble):
    """Cambia el doble del SDK por uno con otra respuesta (misma caché)."""
    monkeypatch.setitem(mp._SDK_CACHE, TOKEN_MP, _SDKFalso(doble))
    return doble


def _plan(**extra):
    datos = {"id": 3, "tenant_id": 1, "nombre": "Plan Full", "creditos": 12,
             "es_ilimitado": False, "precio_clp": PRECIO, "duracion_dias": 30}
    datos.update(extra)
    return Plan(**datos)


def _alumno(correo="alumno@test.com"):
    return Usuario(id=ALUMNO["usuario_id"], tenant_id=1, correo=correo,
                   rol="alumno")


def _suscripcion(*, estado=EstadoSuscripcion.pendiente, preapproval_id=None,
                 plan_id=3, dias=10):
    """Fila de mentira: empieza `dias` atrás, para ver si el periodo se reabre."""
    inicio = datetime.now(timezone.utc) - timedelta(days=dias)
    return Suscripcion(
        id=77, tenant_id=1, usuario_id=ALUMNO["usuario_id"], plan_id=plan_id,
        estado=estado, mp_preapproval_id=preapproval_id, fecha_inicio=inicio,
        fecha_expiracion=inicio + timedelta(days=30))



# ── 1. El alta: qué se le manda a MP y qué queda guardado ───────────────────
def test_el_alta_manda_la_referencia_y_guarda_el_preapproval(pasarela):
    """`external_reference=sus:<id>` + `mp_preapproval_id` guardado: el vínculo."""
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno())

    resultado = suscripciones_mp.crear_suscripcion_mp(
        sesion, current_user=ALUMNO, plan_id=3)

    payload = pasarela.payloads[0]
    assert payload["external_reference"] == f"sus:{ID_FILA}"
    assert payload["payer_email"] == "alumno@test.com"
    assert payload["status"] == "pending"
    assert payload["auto_recurring"] == {
        "frequency": 1, "frequency_type": "months",
        "transaction_amount": PRECIO, "currency_id": "CLP"}
    assert payload["back_url"].startswith(
        "https://app.test/alumno/solicitar-plan")
    # `notification_url` NO es un campo de `POST /preapproval`: la URL del webhook
    # se configura en el panel de MP.
    assert "notification_url" not in payload

    fila = sesion.agregados[0]
    assert fila.mp_preapproval_id == "pre-1", \
        "el id de MP tiene que quedar guardado: es el vínculo que usa el webhook"
    assert fila.estado is EstadoSuscripcion.pendiente, \
        "una fila pendiente no puede dar acceso antes de que MP autorice"
    assert fila.creditos_totales == 12
    assert fila.creditos_disponibles == 12
    assert fila.fecha_expiracion > fila.fecha_inicio

    assert resultado == {"suscripcion_id": ID_FILA,
                         "init_point": "https://mp/checkout",
                         "monto_clp": PRECIO, "estado": "pendiente"}


@pytest.mark.parametrize("base", ["http://localhost:5173", ""])
def test_back_url_sin_https_se_omite(monkeypatch, pasarela, base):
    """MP exige https en `back_url`: con http se omite en vez de arriesgar un 400."""
    monkeypatch.setattr(settings, "MERCADOPAGO_BACK_URL_BASE", base, raising=False)
    monkeypatch.setattr(settings, "FRONTEND_URL", base, raising=False)
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno())

    suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO, plan_id=3)

    assert "back_url" not in pasarela.payloads[0]
    assert sesion.agregados, "el alta tiene que completarse igual"


def test_pasarela_apagada_no_escribe_nada(monkeypatch, pasarela):
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", False, raising=False)
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno())

    with pytest.raises(mp.PagoOnlineNoDisponible):
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert sesion.agregados == []
    assert pasarela.payloads == []


def test_plan_de_otro_box_es_404(pasarela):
    sesion = _SesionFalsa(plan=None, usuario=_alumno())

    with pytest.raises(suscripciones_mp.ErrorSuscripcion) as error:
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert error.value.status_code == 404
    assert sesion.agregados == [] and pasarela.payloads == []


def test_plan_sin_precio_es_400(pasarela):
    sesion = _SesionFalsa(plan=_plan(precio_clp=0), usuario=_alumno())

    with pytest.raises(suscripciones_mp.ErrorSuscripcion) as error:
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert error.value.status_code == 400
    assert sesion.agregados == []


def test_sin_correo_es_400(pasarela):
    """`payer_email` es obligatorio en `POST /preapproval`."""
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno(correo=""))

    with pytest.raises(suscripciones_mp.ErrorSuscripcion) as error:
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert error.value.status_code == 400
    assert sesion.agregados == [] and pasarela.payloads == []



# ── 2. Los atajos: no emitir dos autorizaciones al mismo alumno ─────────────
def test_un_preapproval_pendiente_se_reusa(pasarela):
    """Dos clics no pueden producir dos cobros recurrentes del mismo plan."""
    previa = _suscripcion(preapproval_id="pre-viejo")
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno(), previa=previa)

    resultado = suscripciones_mp.crear_suscripcion_mp(
        sesion, current_user=ALUMNO, plan_id=3)

    assert pasarela.leidos == ["pre-viejo"]
    assert pasarela.payloads == [], "no se emite una segunda autorización"
    assert sesion.agregados == []
    assert resultado["suscripcion_id"] == previa.id
    assert resultado["init_point"] == "https://mp/reuso"


def test_un_preapproval_autorizado_responde_409(monkeypatch, pasarela):
    doble = _con_sdk(monkeypatch, _PreapprovalMP(actual={
        "status": 200,
        "response": {"id": "pre-viejo", "status": "authorized"}}))
    previa = _suscripcion(estado=EstadoSuscripcion.activo,
                          preapproval_id="pre-viejo")
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno(), previa=previa)

    with pytest.raises(suscripciones_mp.ErrorSuscripcion) as error:
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert error.value.status_code == 409
    assert doble.payloads == []
    assert sesion.agregados == []


def test_un_preapproval_cancelado_permite_uno_nuevo(monkeypatch, pasarela):
    doble = _con_sdk(monkeypatch, _PreapprovalMP(actual={
        "status": 200,
        "response": {"id": "pre-viejo", "status": "cancelled"}}))
    previa = _suscripcion(estado=EstadoSuscripcion.inactiva,
                          preapproval_id="pre-viejo")
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno(), previa=previa)

    resultado = suscripciones_mp.crear_suscripcion_mp(
        sesion, current_user=ALUMNO, plan_id=3)

    assert len(doble.payloads) == 1, "la anterior ya no cobra: hace falta otra"
    assert len(sesion.agregados) == 1
    assert resultado["init_point"] == "https://mp/checkout"


def test_si_no_se_puede_leer_la_anterior_falla_cerrado(monkeypatch, pasarela):
    """Sin saber si la anterior sigue autorizada, no se emite otra (503)."""
    doble = _con_sdk(monkeypatch,
                     _PreapprovalMP(error_get=RuntimeError("timeout")))
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno(),
                          previa=_suscripcion(preapproval_id="pre-viejo"))

    with pytest.raises(suscripciones_mp.ErrorSuscripcion) as error:
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert error.value.status_code == 503
    assert doble.leidos == ["pre-viejo"], "se intentó releer en MP"
    assert doble.payloads == []
    assert sesion.agregados == []


# ── 3. Si MP falla, la fila pendiente se borra ──────────────────────────────
def test_si_mp_falla_la_fila_se_borra(monkeypatch):
    doble = _con_sdk(monkeypatch,
                     _PreapprovalMP(error_create=RuntimeError("boom")))
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno())

    with pytest.raises(mp.ErrorMercadoPago):
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert doble.payloads, "se intentó crear en MP"
    assert sesion.eliminados == sesion.agregados, \
        "nada a medias: la fila pendiente se va con el fallo de MP"


def test_sin_init_point_tambien_se_borra(monkeypatch):
    _con_sdk(monkeypatch, _PreapprovalMP(creado={
        "status": 201, "response": {"id": "pre-9", "status": "pending"}}))
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno())

    with pytest.raises(mp.ErrorMercadoPago):
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert sesion.eliminados == sesion.agregados



# ── 4. El resolver: id guardado -> referencia -> correo ─────────────────────
def test_el_resolver_prioriza_el_id_guardado():
    fila = _suscripcion(preapproval_id="pre-1")
    sesion = _SesionSecuencial(suscripcion=[fila])

    encontrada, via = suscripciones_mp.buscar_suscripcion(
        sesion, {"id": "pre-1", "external_reference": "sus:999",
                 "payer_email": "otro@test.com"})

    assert encontrada is fila
    assert via == suscripciones_mp.VIA_PREAPPROVAL


def test_el_resolver_usa_la_referencia_si_no_hay_id_guardado():
    """El aviso puede llegar antes de que se guarde el `mp_preapproval_id`."""
    fila = _suscripcion()
    sesion = _SesionSecuencial(suscripcion=[None, fila])

    encontrada, via = suscripciones_mp.buscar_suscripcion(
        sesion, {"id": "pre-nuevo", "external_reference": "sus:77",
                 "payer_email": "otro@test.com"})

    assert encontrada is fila
    assert via == suscripciones_mp.VIA_REFERENCIA


def test_el_correo_es_el_ultimo_recurso():
    fila = _suscripcion()
    sesion = _SesionSecuencial(suscripcion=[None, fila], usuario=[_alumno()])

    encontrada, via = suscripciones_mp.buscar_suscripcion(
        sesion, {"id": "pre-nuevo", "external_reference": "otro:9",
                 "payer_email": "alumno@test.com"})

    assert encontrada is fila
    assert via == suscripciones_mp.VIA_CORREO


def test_sin_ningun_dato_no_inventa_una_suscripcion():
    sesion = _SesionSecuencial(suscripcion=[None], usuario=[None])

    encontrada, via = suscripciones_mp.buscar_suscripcion(
        sesion, {"id": "pre-x", "payer_email": "nadie@test.com"})

    assert (encontrada, via) == (None, None)


def test_un_preapproval_nuevo_se_vincula_por_la_referencia_y_abre_el_periodo():
    """El caso del bug: la fila no tenía id de MP y el correo no coincidía."""
    fila = _suscripcion(dias=10)  # pendiente, sin `mp_preapproval_id`
    sesion = _SesionSecuencial(suscripcion=[None, fila], plan=[_plan()])

    resultado = suscripciones_mp.procesar_preapproval(sesion, {
        "id": "pre-nuevo", "status": "authorized",
        "external_reference": "sus:77", "payer_email": "otro@correo.com"})

    assert resultado == suscripciones_mp.RESULTADO_ACTUALIZADA
    assert fila.mp_preapproval_id == "pre-nuevo", "el vínculo queda guardado"
    assert fila.estado is EstadoSuscripcion.activo
    assert fila.mp_estado == "authorized"
    # El periodo arranca al autorizar, no cuando se abrió el checkout.
    assert fila.fecha_inicio > datetime.now(timezone.utc) - timedelta(days=1)
    assert fila.fecha_expiracion == fin_de_plan_chile(fila.fecha_inicio, 30)
    assert sesion.commits == 1


# ── 5. El contrato de `POST /pagos/suscripcion` ─────────────────────────────
def _app(sesion):
    """App mínima: sólo el router de pagos, con base y guard sustituidos."""
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api_pagos.router, prefix="/pagos")
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[require_full_access] = lambda: dict(ALUMNO)
    return TestClient(app, raise_server_exceptions=False)


def test_el_endpoint_devuelve_el_init_point(pasarela):
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno())

    respuesta = _app(sesion).post("/pagos/suscripcion", json={"plan_id": 3})

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"suscripcion_id": ID_FILA,
                                "init_point": "https://mp/checkout",
                                "monto_clp": PRECIO, "estado": "pendiente"}


def test_el_endpoint_traduce_el_fallo_de_mp_a_503(monkeypatch, pasarela):
    _con_sdk(monkeypatch,
             _PreapprovalMP(error_create=RuntimeError("boom")))
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno())

    respuesta = _app(sesion).post("/pagos/suscripcion", json={"plan_id": 3})

    assert respuesta.status_code == 503, respuesta.text
    assert "Mercado Pago" in respuesta.json()["detail"]


def test_el_endpoint_apagado_responde_503_con_transferencia(monkeypatch,
                                                           pasarela):
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", False, raising=False)
    sesion = _SesionFalsa(plan=_plan(), usuario=_alumno())

    respuesta = _app(sesion).post("/pagos/suscripcion", json={"plan_id": 3})

    assert respuesta.status_code == 503, respuesta.text
    assert "transferencia" in respuesta.json()["detail"]
    assert sesion.agregados == []


def test_el_endpoint_responde_409_si_el_plan_ya_esta_autorizado(monkeypatch,
                                                               pasarela):
    _con_sdk(monkeypatch, _PreapprovalMP(actual={
        "status": 200,
        "response": {"id": "pre-viejo", "status": "authorized"}}))
    sesion = _SesionFalsa(
        plan=_plan(), usuario=_alumno(),
        previa=_suscripcion(estado=EstadoSuscripcion.activo,
                            preapproval_id="pre-viejo"))

    respuesta = _app(sesion).post("/pagos/suscripcion", json={"plan_id": 3})

    assert respuesta.status_code == 409, respuesta.text
    assert "activo" in respuesta.json()["detail"]
    assert sesion.agregados == []


# ── 6. La carrera del alta (índice parcial de la migración 082) ─────────────
def test_dos_altas_simultaneas_dejan_una_fila_y_un_solo_preapproval(
        monkeypatch, pasarela):
    """La carrera real: la segunda llega MIENTRAS la primera espera a MP.

    No hacen falta threads: la primera llamada ya confirmó su fila `pendiente`
    (sin `mp_preapproval_id`) y el mock de MP dispara la segunda en ese hueco
    exacto, que es donde el k6 encontró los duplicados.
    """
    sesion = _SesionCarrera(plan=_plan(), usuario=_alumno())
    errores = []
    primera_vez = []
    crear_original = pasarela.create

    def create_con_carrera(datos):
        if not primera_vez:
            primera_vez.append(True)
            # Precondición del bug: la fila de la primera ya está confirmada y
            # todavía NO tiene el id de MP.
            assert sesion.pendientes[0].mp_preapproval_id is None
            try:
                suscripciones_mp.crear_suscripcion_mp(
                    sesion, current_user=ALUMNO, plan_id=3)
            except suscripciones_mp.ErrorSuscripcion as error:
                errores.append(error)
        return crear_original(datos)

    monkeypatch.setattr(pasarela, "create", create_con_carrera)

    resultado = suscripciones_mp.crear_suscripcion_mp(
        sesion, current_user=ALUMNO, plan_id=3)

    assert len(errores) == 1, "la segunda solicitud recibió el 409"
    assert errores[0].status_code == 409
    assert "en proceso" in errores[0].detalle
    assert not isinstance(errores[0], mp.ErrorMercadoPago)
    assert len(pasarela.payloads) == 1, \
        "la segunda NUNCA llega a crear un `preapproval` en MP"
    assert len(sesion.pendientes) == 1, "una sola fila `pendiente`"
    assert sesion.duplicados == 1 and sesion.rollbacks == 1
    assert sesion.pendientes[0].mp_preapproval_id == "pre-1"
    assert resultado["suscripcion_id"] == sesion.pendientes[0].id
    assert resultado["init_point"] == "https://mp/checkout"


def test_el_alta_normal_no_pasa_por_el_camino_de_carrera(pasarela):
    """Sin competencia, el alta sigue creando su fila + su preapproval igual."""
    sesion = _SesionCarrera(plan=_plan(), usuario=_alumno())

    resultado = suscripciones_mp.crear_suscripcion_mp(
        sesion, current_user=ALUMNO, plan_id=3)

    assert len(pasarela.payloads) == 1
    assert len(sesion.pendientes) == 1
    assert sesion.duplicados == 0 and sesion.rollbacks == 0
    assert resultado == {"suscripcion_id": sesion.pendientes[0].id,
                         "init_point": "https://mp/checkout",
                         "monto_clp": PRECIO, "estado": "pendiente"}


def test_otro_integrity_error_no_se_convierte_en_409(pasarela):
    """Sólo la violación del índice de pendientes es la carrera: el resto sube."""
    class _SesionRota(_SesionCarrera):
        def commit(self):
            self.commits += 1
            raise IntegrityError(
                "INSERT INTO suscripciones ...", {},
                Exception("insert or update violates foreign key constraint"))

    sesion = _SesionRota(plan=_plan(), usuario=_alumno())

    with pytest.raises(IntegrityError):
        suscripciones_mp.crear_suscripcion_mp(sesion, current_user=ALUMNO,
                                             plan_id=3)

    assert pasarela.payloads == [], "nunca se llegó a llamar a MP"


def test_el_endpoint_responde_409_si_hay_un_alta_en_proceso(pasarela):
    """No hace falta tocar el endpoint: `ErrorSuscripcion` ya se traduce solo."""
    sesion = _SesionCarrera(plan=_plan(), usuario=_alumno(),
                            pendientes=[_suscripcion()])

    respuesta = _app(sesion).post("/pagos/suscripcion", json={"plan_id": 3})

    assert respuesta.status_code == 409, respuesta.text
    assert "en proceso" in respuesta.json()["detail"]
    assert pasarela.payloads == []
    assert len(sesion.pendientes) == 1


def test_la_violacion_del_indice_se_reconoce_por_su_nombre():
    error = IntegrityError(
        "INSERT INTO suscripciones ...", {},
        Exception("duplicate key value violates unique constraint "
                  f'"{NOMBRE_INDICE_PENDIENTE_UNICA}"'))

    assert es_suscripcion_pendiente_duplicada(error) is True
    assert es_suscripcion_pendiente_duplicada(IntegrityError(
        "INSERT INTO suscripciones ...", {},
        Exception("insert or update violates foreign key constraint"))) is False


# ── 7. Modelo y migración 082: el mismo índice, una sola cabeza ─────────────
VERSIONES = BACKEND / "alembic" / "versions"
MIGRACION_082 = "082_suscripcion_pendiente_unica"


def _modulo_migracion(nombre: str):
    ruta = VERSIONES / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _indice_del_modelo():
    for indice in Suscripcion.__table__.indexes:
        if indice.name == NOMBRE_INDICE_PENDIENTE_UNICA:
            return indice
    raise AssertionError("el modelo no declara el índice único de pendientes")


def test_el_modelo_y_la_migracion_082_declaran_el_mismo_indice():
    """Si divergen, `create_all` (TEST) y las migraciones (PROD) no coinciden."""
    migracion = _modulo_migracion(MIGRACION_082)
    indice = _indice_del_modelo()

    assert migracion.TABLA == Suscripcion.__tablename__ == "suscripciones"
    assert migracion.INDICE == indice.name == NOMBRE_INDICE_PENDIENTE_UNICA
    assert indice.unique is True
    assert [c.name for c in indice.columns] == ["usuario_id", "plan_id"]
    predicado = indice.dialect_options["postgresql"]["where"].text
    assert predicado == migracion.PREDICADO == PREDICADO_PENDIENTE
    assert predicado == "estado = 'pendiente'"


def test_la_082_es_la_unica_cabeza_sobre_la_081():
    migracion = _modulo_migracion(MIGRACION_082)
    assert migracion.revision == MIGRACION_082
    assert migracion.down_revision == "081_wod_resultados"
    assert len(migracion.revision) <= 32, \
        "alembic_version.version_num es VARCHAR(32)"

    hijas = [ruta.stem for ruta in VERSIONES.glob("*.py")
             if re.search(r"down_revision[^=]*=\s*['\"]081_wod_resultados['\"]",
                          ruta.read_text(encoding="utf-8-sig", errors="ignore"))]
    assert hijas == [MIGRACION_082], f"cabezas sobre 081_wod_resultados: {hijas}"


def test_el_downgrade_de_la_082_dropea_el_mismo_indice():
    fuente = (VERSIONES / f"{MIGRACION_082}.py").read_text(
        encoding="utf-8-sig", errors="ignore")

    assert "op.drop_index(INDICE, table_name=TABLA)" in fuente
    assert 'op.create_index(INDICE, TABLA, ["usuario_id", "plan_id"]' in fuente
    assert "unique=True" in fuente
    assert "postgresql_where=sa.text(PREDICADO)" in fuente

