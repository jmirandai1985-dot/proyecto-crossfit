"""
Activación MANUAL de un plan por el admin (`POST /admin/planes/{id}/activar-manual`).

Por qué existe: el guard de `_validar_aprobacion_manual` prohíbe aprobar a mano
una solicitud con pago online NO confirmado (409). Si Mercado Pago cobró pero el
webhook nunca llegó, el alumno quedaba sin plan y el admin sin salida. Este
endpoint es el rescate humano: retoma (o crea) la solicitud y delega en
`activar_plan` con `forzar=True`, así el plan nace con inicio HOY y pasa por la
MISMA lógica (créditos, transacción, auditoría, correo).

Dos bloques, sin red y sin base:

1. **Contrato HTTP** (app mínima con sólo el router de admin, `get_db` y
   `get_current_admin` sustituidos, y el servicio monkeypatcheado): el tenant y
   el actor salen del token —nunca del body—, los 404/409/422 del endpoint y la
   forma de la respuesta.
2. **Reglas del servicio** con una sesión de mentira: crea la solicitud cuando no
   existe, reusa la `pending`, REABRE la `iniciado`/`expirada` (el caso del
   webhook perdido), no duplica si ya está activa o en cola, y `forzar=True`
   salta el guard del pago online sin confirmar.

Correr (aislado, sin servidor ni suite completa):
    cd backend && py -3.12 -m pytest tests/test_activar_plan_manual.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import admin as api_admin                       # noqa: E402
from app.core.dependencies import get_current_admin             # noqa: E402
from app.db.database import get_db                              # noqa: E402
from app.models.pago import Pago                                # noqa: E402
from app.models.plan import Plan                                # noqa: E402
from app.models.solicitud_plan import SolicitudPlan             # noqa: E402
from app.models.usuario import Usuario                          # noqa: E402
from app.services import aprobacion_planes                      # noqa: E402

RUTA = "/api/v1/admin/planes/2/activar-manual"


# ── Datos de mentira ────────────────────────────────────────────────────────
def _plan(**extra):
    datos = {"id": 2, "tenant_id": 1, "nombre": "Plan Full",
             "precio_clp": 30000, "duracion_dias": 30, "creditos": 12}
    datos.update(extra)
    return SimpleNamespace(**datos)


def _alumno(**extra):
    datos = {"id": 3, "tenant_id": 1, "nombre": "Ana", "correo": "ana@box.cl"}
    datos.update(extra)
    return SimpleNamespace(**datos)


def _solicitud(**extra):
    datos = {"id": 55, "tenant_id": 1, "alumno_id": 3, "plan_id": 2,
             "estado": "pending", "origen_pago": "manual", "pago_id": None,
             "precio_clp_snapshot": 30000, "precio_final_clp": None,
             "beneficio_id": None, "voucher_url": None,
             "comentario_admin": None}
    datos.update(extra)
    return SimpleNamespace(**datos)


# ── Bloque 1: contrato HTTP ─────────────────────────────────────────────────
class _SesionVacia:
    """La base no se toca: el servicio está monkeypatcheado en estos tests."""


def _app_http(monkeypatch, servicio):
    monkeypatch.setattr(aprobacion_planes, "activar_plan_manual", servicio)
    app = FastAPI()
    app.include_router(api_admin.router, prefix="/api/v1/admin")
    app.dependency_overrides[get_db] = lambda: _SesionVacia()
    app.dependency_overrides[get_current_admin] = lambda: {
        "usuario_id": 9, "tenant_id": 1, "rol": "admin"}
    return TestClient(app, raise_server_exceptions=False)


def test_activa_y_usa_el_tenant_y_el_actor_del_token(monkeypatch):
    llamadas = []

    def falso(db, **kwargs):
        llamadas.append(kwargs)
        return {"status": "approved", "message": "Plan activado exitosamente"}

    cliente = _app_http(monkeypatch, falso)
    respuesta = cliente.post(RUTA, json={"alumno_id": 3,
                                         "motivo": "pagó por transferencia"})

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "approved"
    assert len(llamadas) == 1
    envio = dict(llamadas[0])
    assert envio.pop("background_tasks") is not None  # correo/churn programados
    assert envio == {
        "tenant_id": 1,      # del token, no del body
        "alumno_id": 3,
        "plan_id": 2,        # del path
        "actor_id": 9,       # del token
        "motivo": "pagó por transferencia",
    }


def test_el_body_no_puede_elegir_el_tenant(monkeypatch):
    """Un `tenant_id` en el body se ignora: sólo cuenta el JWT del admin."""
    llamadas = []

    def falso(db, **kwargs):
        llamadas.append(kwargs)
        return {"status": "approved", "message": "ok"}

    cliente = _app_http(monkeypatch, falso)
    cliente.post(RUTA, json={"alumno_id": 3, "tenant_id": 999})

    assert llamadas[0]["tenant_id"] == 1


def test_plan_inexistente_es_404(monkeypatch):
    def falso(db, **kwargs):
        raise aprobacion_planes.PlanNoEncontrado(2)

    respuesta = _app_http(monkeypatch, falso).post(RUTA, json={"alumno_id": 3})

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "Plan no encontrado"


def test_alumno_inexistente_es_404(monkeypatch):
    def falso(db, **kwargs):
        raise aprobacion_planes.AlumnoNoEncontrado(3)

    respuesta = _app_http(monkeypatch, falso).post(RUTA, json={"alumno_id": 3})

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "Alumno no encontrado"


@pytest.mark.parametrize("motivo", ["ya_en_cola", "otra_pendiente", "ya_activa",
                                    "ya_procesada"])
def test_conflictos_del_negocio_son_409(monkeypatch, motivo):
    def falso(db, **kwargs):
        raise aprobacion_planes.SolicitudNoProcesable(motivo)

    respuesta = _app_http(monkeypatch, falso).post(RUTA, json={"alumno_id": 3})

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]


@pytest.mark.parametrize("cuerpo", [{}, {"alumno_id": 0}, {"alumno_id": "x"}])
def test_body_invalido_es_422(monkeypatch, cuerpo):
    def falso(db, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("no debería llegar al servicio")

    respuesta = _app_http(monkeypatch, falso).post(RUTA, json=cuerpo)

    assert respuesta.status_code == 422


def test_el_endpoint_exige_admin_por_token():
    ruta = next(r for r in api_admin.router.routes
                if getattr(r, "path", "") == "/planes/{plan_id}/activar-manual")
    dependencias = [dep.call for dep in ruta.dependant.dependencies]
    assert get_current_admin in dependencias


# ── Bloque 2: reglas del servicio (sesión de mentira) ───────────────────────
class _Consulta:
    """Cadena `query(...).filter(...).order_by(...).first()` de mentira.

    Cada modelo entrega la LISTA de resultados que cargó el test, en orden: así
    se distinguen las dos consultas a `solicitudes_planes` (la de "otra
    pendiente" y la de "la última de este plan").
    """

    def __init__(self, resultados):
        self._resultados = resultados

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._resultados.pop(0) if self._resultados else None

    def all(self):
        return []


class _Ejecucion:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount


class _SesionFalsa:
    """Sesión de mentira: por modelo, la lista de resultados en orden."""

    def __init__(self, *, planes=(), usuarios=(), solicitudes=(), pagos=(),
                 rowcount=1):
        self.resultados = {
            Plan: list(planes),
            Usuario: list(usuarios),
            SolicitudPlan: list(solicitudes),
            Pago: list(pagos),
        }
        self.rowcount = rowcount
        self.agregados = []
        self.sentencias = []
        self.flushes = 0

    def query(self, modelo):
        return _Consulta(self.resultados.get(modelo, []))

    def add(self, obj):
        self.agregados.append(obj)

    def flush(self):
        self.flushes += 1
        for numero, obj in enumerate(self.agregados, start=100):
            if getattr(obj, "id", None) is None:
                obj.id = numero

    def execute(self, sentencia):
        self.sentencias.append(sentencia)
        return _Ejecucion(self.rowcount)

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def activacion(monkeypatch):
    """Sustituye `activar_plan` y devuelve las llamadas (el camino pesado tiene
    sus propios tests)."""
    llamadas = []

    def falso(db, solicitud_id, **kwargs):
        llamadas.append({"solicitud_id": solicitud_id, **kwargs})
        return {"status": "approved", "message": "Plan activado exitosamente"}

    monkeypatch.setattr(aprobacion_planes, "activar_plan", falso)
    return llamadas


def test_crea_la_solicitud_y_activa_con_forzar(activacion):
    sesion = _SesionFalsa(planes=[_plan()], usuarios=[_alumno()],
                          solicitudes=[None, None])

    resultado = aprobacion_planes.activar_plan_manual(
        sesion, tenant_id=1, alumno_id=3, plan_id=2, actor_id=9,
        motivo="pagó por transferencia")

    assert len(sesion.agregados) == 1
    solicitud = sesion.agregados[0]
    assert (solicitud.tenant_id, solicitud.alumno_id, solicitud.plan_id) == (1, 3, 2)
    assert solicitud.estado == "pending"
    assert solicitud.origen_pago == "manual"
    assert solicitud.precio_clp_snapshot == 30000
    assert sesion.flushes == 1
    assert activacion == [{
        "solicitud_id": 100,
        "tenant_id": 1,
        "actor_id": 9,
        "origen": "manual",
        "background_tasks": None,
        "forzar": True,
        "comentario": "Activación manual del admin: pagó por transferencia",
    }]
    assert resultado["solicitud_id"] == 100
    assert resultado["alumno_id"] == 3
    assert resultado["plan_id"] == 2


def test_reusa_la_solicitud_pendiente_sin_tocar_nada(activacion):
    pendiente = _solicitud(id=55, estado="pending", origen_pago="mercadopago",
                           pago_id=7, precio_final_clp=27000)
    sesion = _SesionFalsa(planes=[_plan()], usuarios=[_alumno()],
                          solicitudes=[None, pendiente])

    resultado = aprobacion_planes.activar_plan_manual(
        sesion, tenant_id=1, alumno_id=3, plan_id=2)

    assert sesion.agregados == []
    assert sesion.sentencias == []
    assert activacion[0]["solicitud_id"] == 55
    assert activacion[0]["forzar"] is True
    assert activacion[0]["comentario"] == "Activación manual del admin"
    assert resultado["solicitud_id"] == 55


@pytest.mark.parametrize("estado", ["iniciado", "expirada"])
def test_reabre_la_compra_online_que_quedo_sin_webhook(activacion, estado):
    """El caso del incidente: MP cobró y la solicitud quedó `iniciado`/`expirada`."""
    vieja = _solicitud(id=77, estado=estado, origen_pago="mercadopago",
                       pago_id=7)
    sesion = _SesionFalsa(planes=[_plan()], usuarios=[_alumno()],
                          solicitudes=[None, vieja])

    aprobacion_planes.activar_plan_manual(
        sesion, tenant_id=1, alumno_id=3, plan_id=2)

    assert len(sesion.sentencias) == 1      # UPDATE estado -> pending
    assert vieja.estado == "pending"
    assert sesion.agregados == []
    assert activacion[0]["solicitud_id"] == 77


def test_si_otro_la_movio_antes_es_conflicto(activacion):
    vieja = _solicitud(id=77, estado="expirada")
    sesion = _SesionFalsa(planes=[_plan()], usuarios=[_alumno()],
                          solicitudes=[None, vieja], rowcount=0)

    with pytest.raises(aprobacion_planes.SolicitudNoProcesable) as error:
        aprobacion_planes.activar_plan_manual(
            sesion, tenant_id=1, alumno_id=3, plan_id=2)

    assert error.value.motivo == "ya_procesada"
    assert activacion == []


@pytest.mark.parametrize("estado,motivo", [
    ("approved", "ya_activa"),
    ("en_cola", "ya_en_cola"),
])
def test_no_duplica_un_plan_ya_activo_o_en_cola(activacion, estado, motivo):
    sesion = _SesionFalsa(planes=[_plan()], usuarios=[_alumno()],
                          solicitudes=[None, _solicitud(estado=estado)])

    with pytest.raises(aprobacion_planes.SolicitudNoProcesable) as error:
        aprobacion_planes.activar_plan_manual(
            sesion, tenant_id=1, alumno_id=3, plan_id=2)

    assert error.value.motivo == motivo
    assert activacion == []


def test_otra_solicitud_pendiente_de_otro_plan_bloquea(activacion):
    sesion = _SesionFalsa(planes=[_plan()], usuarios=[_alumno()],
                          solicitudes=[_solicitud(id=60, plan_id=5)])

    with pytest.raises(aprobacion_planes.SolicitudNoProcesable) as error:
        aprobacion_planes.activar_plan_manual(
            sesion, tenant_id=1, alumno_id=3, plan_id=2)

    assert error.value.motivo == "otra_pendiente"
    assert activacion == []


def test_plan_de_otro_box_es_404(activacion):
    sesion = _SesionFalsa(planes=[], usuarios=[_alumno()])

    with pytest.raises(aprobacion_planes.PlanNoEncontrado):
        aprobacion_planes.activar_plan_manual(
            sesion, tenant_id=1, alumno_id=3, plan_id=2)

    assert sesion.agregados == []
    assert activacion == []


def test_alumno_de_otro_box_es_404(activacion):
    sesion = _SesionFalsa(planes=[_plan()], usuarios=[])

    with pytest.raises(aprobacion_planes.AlumnoNoEncontrado):
        aprobacion_planes.activar_plan_manual(
            sesion, tenant_id=1, alumno_id=3, plan_id=2)

    assert activacion == []


# ── `activar_plan(forzar=True)`: la única puerta que salta el guard ──────────
def _solicitud_online(**extra):
    datos = {"id": 7, "tenant_id": 1, "alumno_id": 3, "plan_id": 2,
             "estado": "iniciado", "origen_pago": "mercadopago",
             "pago_id": 99}
    datos.update(extra)
    return SimpleNamespace(**datos)


def test_forzar_saltea_el_guard_del_pago_online_sin_confirmar():
    """Sin `forzar`, una compra online sin cobro aprobado corta con 409.

    Con `forzar=True` la ejecución SIGUE: acá el plan no existe (el fake no lo
    carga), así que corta más adelante con `PlanNoEncontrado` — esa es la prueba
    de que el guard del pago online NO corrió.
    """
    solicitud = _solicitud_online()
    pago = SimpleNamespace(id=99, estado="pendiente")
    sesion = _SesionFalsa(planes=[], usuarios=[],
                          solicitudes=[solicitud, solicitud], pagos=[pago])

    with pytest.raises(aprobacion_planes.PagoOnlineNoConfirmado):
        aprobacion_planes.activar_plan(
            sesion, 7, tenant_id=1, origen=aprobacion_planes.ORIGEN_MANUAL)

    with pytest.raises(aprobacion_planes.PlanNoEncontrado):
        aprobacion_planes.activar_plan(
            sesion, 7, tenant_id=1, origen=aprobacion_planes.ORIGEN_MANUAL,
            forzar=True)


def test_el_webhook_no_corre_el_guard_manual():
    """`ORIGEN_MERCADOPAGO` nunca valida el pago a mano (no hay humano)."""
    sesion = _SesionFalsa(planes=[], usuarios=[],
                          solicitudes=[_solicitud_online(estado="pending")])

    with pytest.raises(aprobacion_planes.PlanNoEncontrado):
        aprobacion_planes.activar_plan(
            sesion, 7, tenant_id=1,
            origen=aprobacion_planes.ORIGEN_MERCADOPAGO)
