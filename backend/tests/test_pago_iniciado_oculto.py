"""Pago de membresía OCULTO hasta el primer webhook real de Mercado Pago.

Tests AISLADOS (sin red y sin base de datos): la regla de visibilidad, el guard
de intentos en curso y el cierre por rechazo, con una DB falsa.

Qué congelan:

  * un clic en "Pagar con tarjeta" deja el pago en `iniciado`: NO reserva el
    guard para siempre (la ventana es de 5 min) y NO se confunde con un pago
    `pendiente` ni con el Bazar;
  * el PRIMER webhook abre la solicitud oculta (`iniciado` -> `pending`) o la
    cierra (`rejected`) si MP rechaza/cancela/reembolsa;
  * un webhook repetido o un estado desconocido no vuelve a tocar nada;
  * el guard bloquea otra compra con una solicitud `pending` o con un pago
    `iniciado` fresco, y la libera cuando el intento ya venció.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_pago_iniciado_oculto.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import pagos as servicio_pagos  # noqa: E402

AHORA = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def _pago(*, estado="iniciado", concepto="membresia", minutos=0,
          referencia_id=10, tenant_id=1, pago_id=1):
    return SimpleNamespace(
        id=pago_id, concepto=concepto, estado=estado,
        referencia_id=referencia_id, tenant_id=tenant_id,
        monto_clp=44000, created_at=AHORA - timedelta(minutes=minutos))


def _detalle(status, status_detail=None):
    return {"status": status, "status_detail": status_detail}


class _Resultado:
    def __init__(self, rowcount):
        self.rowcount = rowcount


def _valores(stmt):
    out = {}
    for col, param in getattr(stmt, "_values", {}).items():
        out[col.name] = getattr(param, "value", param)
    return out


class _DBPromocion:
    """DB mínima para `_promover_solicitud_webhook`: registra el UPDATE."""

    def __init__(self, rowcount):
        self.rowcount = rowcount
        self.tabla = None
        self.valores = None
        self.updates = 0

    def execute(self, stmt):
        self.updates += 1
        self.tabla = stmt.table.name
        self.valores = _valores(stmt)
        return _Resultado(self.rowcount)


# ── Ventana del guard ────────────────────────────────────────────────────────
def test_un_iniciado_de_4_minutos_sigue_reservando_el_guard():
    assert servicio_pagos.iniciado_vigente(
        _pago(minutos=4), ahora=AHORA) is True


def test_un_iniciado_de_6_minutos_ya_no_reserva_el_guard():
    assert servicio_pagos.iniciado_vigente(
        _pago(minutos=6), ahora=AHORA) is False


@pytest.mark.parametrize("pago", [
    None,
    _pago(estado="pendiente"),
    _pago(estado="aprobado"),
    _pago(concepto="bazar"),
    SimpleNamespace(concepto="membresia", estado="iniciado", created_at=None),
])
def test_no_reservan_el_guard_los_pagos_que_no_son_un_iniciado_vigente(pago):
    assert servicio_pagos.iniciado_vigente(pago, ahora=AHORA) is False


# ── Primer webhook: abrir o cerrar la solicitud oculta ───────────────────────
@pytest.mark.parametrize("status", ["approved", "pending", "in_process",
                                    "authorized"])
def test_el_primer_aviso_real_hace_visible_la_solicitud(status):
    db = _DBPromocion(rowcount=1)

    resultado = servicio_pagos._promover_solicitud_webhook(
        db, _pago(), _detalle(status))

    assert resultado == "pending"
    assert db.tabla == "solicitudes_planes"
    assert db.valores == {"estado": "pending"}


@pytest.mark.parametrize("status", ["rejected", "cancelled", "refunded",
                                    "charged_back"])
def test_un_rechazo_cancela_o_reembolso_CIERRA_la_solicitud(status):
    db = _DBPromocion(rowcount=1)

    resultado = servicio_pagos._promover_solicitud_webhook(
        db, _pago(), _detalle(status, "cc_rejected_other_reason"))

    assert resultado == "rejected"
    assert db.valores["estado"] == "rejected"
    assert "Mercado Pago" in db.valores["comentario_admin"]
    assert "cc_rejected_other_reason" in db.valores["comentario_admin"]


def test_un_webhook_repetido_no_vuelve_a_promover_ni_a_avisar():
    """La solicitud ya está `pending` (o `approved`): el UPDATE no toca filas y
    no se manda una segunda campana al admin."""
    db = _DBPromocion(rowcount=0)

    assert servicio_pagos._promover_solicitud_webhook(
        db, _pago(estado="pendiente"), _detalle("pending")) is None
    assert db.updates == 1


@pytest.mark.parametrize("status", ["unknown", None, ""])
def test_un_estado_de_MP_desconocido_no_inventa_visibilidad(status):
    db = _DBPromocion(rowcount=1)

    assert servicio_pagos._promover_solicitud_webhook(
        db, _pago(), _detalle(status)) is None
    assert db.updates == 0


def test_el_webhook_del_bazar_no_toca_solicitudes_de_plan():
    db = _DBPromocion(rowcount=1)

    assert servicio_pagos._promover_solicitud_webhook(
        db, _pago(concepto="bazar"), _detalle("approved")) is None
    assert db.updates == 0


# ── Guard: una sola solicitud/checkout en curso ──────────────────────────────
class _QueryFalsa:
    def __init__(self, primero=None, todos=()):
        self._primero = primero
        self._todos = list(todos)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._primero

    def all(self):
        return self._todos


class _DBGuard:
    def __init__(self, *, pendiente=None, pagos=()):
        self.pendiente = pendiente
        self.pagos = list(pagos)

    def query(self, objetivo):
        tabla = getattr(getattr(objetivo, "table", None), "name", None)
        if tabla is None:
            tabla = getattr(getattr(objetivo, "__table__", None), "name", None)
        if tabla == "solicitudes_planes":
            return _QueryFalsa(primero=self.pendiente)
        if tabla == "pagos":
            return _QueryFalsa(todos=self.pagos)
        raise AssertionError(f"query inesperada: {objetivo}")


def test_el_guard_sigue_bloqueando_una_solicitud_pending():
    db = _DBGuard(pendiente=77)

    assert servicio_pagos.bloqueo_solicitud_en_curso(
        db, tenant_id=1, alumno_id=2) == "solicitud_pendiente"


def test_el_guard_bloquea_un_segundo_checkout_con_un_iniciado_fresco():
    db = _DBGuard(pagos=[_pago(minutos=4)])

    assert servicio_pagos.bloqueo_solicitud_en_curso(
        db, tenant_id=1, alumno_id=2, ahora=AHORA) == "pago_en_curso"


def test_el_guard_se_libera_cuando_el_iniciado_ya_vencio():
    db = _DBGuard(pagos=[_pago(minutos=6)])

    assert servicio_pagos.bloqueo_solicitud_en_curso(
        db, tenant_id=1, alumno_id=2, ahora=AHORA) is None


def test_el_guard_no_confunde_un_pago_pendiente_con_un_checkout_abierto():
    db = _DBGuard(pagos=[_pago(estado="pendiente", minutos=1)])

    assert servicio_pagos.bloqueo_solicitud_en_curso(
        db, tenant_id=1, alumno_id=2, ahora=AHORA) is None


# ── Red de seguridad para el webhook perdido ────────────────────────────────
def test_la_reconciliacion_de_webhooks_perdidos_incluye_los_iniciado():
    """El primer aviso de MP puede perderse: el job de reconciliación tiene que
    levantar también un pago `iniciado` (si MP tiene un cobro real, lo aplica; si
    no, no hace nada)."""
    fuente = (_BACKEND / "maintenance" / "reconciliar_pagos.py").read_text(
        encoding="utf-8")
    assert 'Pago.estado == "iniciado"' in fuente
    assert 'Pago.estado.in_(("iniciado", "pendiente", "en_proceso"))' in fuente

