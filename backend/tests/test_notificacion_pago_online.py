"""
Campana del admin cuando se cobra un PLAN por Mercado Pago
(`services/pagos._avisar_pago_online`).

Antes el aviso salía como `plan_solicitado`, que abre la pestaña de solicitudes
con VOUCHER: para un cobro online esa pestaña no tiene nada que revisar. Ahora es
`plan_pagado_online`, con el monto REAL que confirma MP, y la campana lo lleva a
"Pagos del día".

Sin red y sin base: sesión de mentira y `notificar_admins_del_tenant`
monkeypatcheado (la campana real tiene sus propios tests en
`tests/test_notificaciones_panel.py`).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_notificacion_pago_online.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.notificacion import Notificacion          # noqa: E402
from app.models.plan import Plan                           # noqa: E402
from app.models.solicitud_plan import SolicitudPlan        # noqa: E402
from app.models.usuario import Usuario                     # noqa: E402
from app.services import pagos                             # noqa: E402

TIPO = "plan_pagado_online"


class _Consulta:
    def __init__(self, resultados):
        self.resultados = resultados

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.resultados.pop(0) if self.resultados else None


class _SesionFalsa:
    """Devuelve, por modelo, los resultados cargados (en orden)."""

    def __init__(self, *, alumno=None, solicitud=None, plan="Plan Full"):
        self.resultados = {
            Usuario: [alumno],
            SolicitudPlan: [solicitud],
            Plan: [(plan,)] if plan is not None else [],
        }

    def query(self, modelo):
        # `db.query(Usuario)` -> la clase; `db.query(Plan.nombre)` -> una columna
        # cuya clase es `Plan`.
        if modelo in self.resultados:
            return _Consulta(self.resultados[modelo])
        return _Consulta(self.resultados.get(getattr(modelo, "class_", None), []))


def _pago(**extra):
    datos = {"id": 12, "tenant_id": 1, "usuario_id": 3,
             "concepto": "membresia", "monto_clp": 40000, "referencia_id": 55}
    datos.update(extra)
    return SimpleNamespace(**datos)


def _detalle(status="approved", **extra):
    datos = {"status": status, "transaction_amount": 40000}
    datos.update(extra)
    return datos


@pytest.fixture
def enviados(monkeypatch):
    """Captura los avisos en vez de escribir en `notificaciones`."""
    lista = []

    def falso(db, tenant_id, tipo, mensaje, **kwargs):
        lista.append({"tenant_id": tenant_id, "tipo": tipo, "mensaje": mensaje})
        return 1

    monkeypatch.setattr(pagos, "notificar_admins_del_tenant", falso)
    return lista


def _avisar(detalle, *, primera_vez=True, pago=None):
    return pagos._avisar_pago_online(
        _SesionFalsa(alumno=SimpleNamespace(id=3, nombre="Ana Pérez"),
                     solicitud=SimpleNamespace(id=55, plan_id=2)),
        pago=pago or _pago(), detalle=detalle, primera_vez=primera_vez)


def test_el_tipo_entra_en_la_columna_de_notificaciones():
    largo = Notificacion.__table__.c.tipo.type.length
    assert len(TIPO) <= largo == 20


def test_pago_aprobado_avisa_que_pago_con_el_monto_real(enviados):
    _avisar(_detalle())

    assert enviados == [{
        "tenant_id": 1,
        "tipo": TIPO,
        "mensaje": "💳 Ana Pérez pagó plan Plan Full — $40.000 vía MercadoPago",
    }]


def test_el_monto_sale_de_mp_y_no_del_esperado(enviados):
    """MP puede cobrar otro monto (matrícula, ajuste): se informa el cobrado."""
    _avisar(_detalle(transaction_amount=38000))

    assert "$38.000" in enviados[0]["mensaje"]
    assert "$40.000" not in enviados[0]["mensaje"]


def test_sin_monto_de_mp_cae_al_monto_del_pago(enviados):
    _avisar(_detalle(transaction_amount=None))

    assert "$40.000" in enviados[0]["mensaje"]


def test_el_primer_aviso_sin_aprobar_dice_que_inicio_el_pago(enviados):
    _avisar(_detalle(status="in_process"))

    assert enviados[0]["tipo"] == TIPO
    assert "inició el pago de Plan Full" in enviados[0]["mensaje"]
    assert enviados[0]["mensaje"].endswith("(sin confirmar)")


def test_un_aviso_posterior_sin_aprobar_no_manda_nada(enviados):
    _avisar(_detalle(status="pending"), primera_vez=False)

    assert enviados == []


def test_el_bazar_no_genera_un_aviso_de_plan(enviados):
    _avisar(_detalle(), pago=_pago(concepto="bazar"))

    assert enviados == []


def test_si_la_campana_falla_el_pago_no_se_rompe(monkeypatch):
    def revienta(*args, **kwargs):
        raise RuntimeError("campana caída")

    monkeypatch.setattr(pagos, "notificar_admins_del_tenant", revienta)

    # Best-effort: el aviso es lo último que importa, nunca tumba el cobro.
    _avisar(_detalle())
