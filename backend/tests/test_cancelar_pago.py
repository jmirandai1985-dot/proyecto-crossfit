"""Cancelar un pago con tarjeta ABANDONADO (`services/pagos.cancelar_pago`).

CASO REAL: el alumno toca "Pagar con tarjeta", el backend crea la `SolicitudPlan`
en `pending` + el `Pago` en `pendiente`, y el alumno se devuelve a la app SIN
meter los datos de la tarjeta. Mercado Pago no genera ningún pago que rechazar:
no hay webhook y la única forma de cerrarlo es que el alumno (o el admin) aprete
"Cancelar". Sin esto la solicitud queda bloqueando el guard "ya tienes una
solicitud pendiente" hasta la expiración automática.

Tests AISLADOS (sin red y sin base de datos): la regla y los guardas, con una
DB falsa que simula el `UPDATE ... WHERE estado IN (pendiente, en_proceso)`.

  * Un pago `pendiente`/`en_proceso` queda `cancelado` y su solicitud `rejected`
    con el comentario de cancelación (el MISMO valor que usa el rechazo por
    webhook: `_limpiar_cobro_fallido`).
  * Un pago ya `aprobado` por el webhook NO se cancela (409) y no toca la
    solicitud: lo que ya se cobró se devuelve con un reembolso, no se deshace.
  * Una solicitud que dejó de estar `pending` (el admin la aprobó en paralelo)
    no se pisa.
  * Bazar: el rechazo pasa por `pedidos_estado.rechazar_pedido` (devuelve stock).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_cancelar_pago.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import pagos as servicio_pagos          # noqa: E402


def _pago(concepto="membresia", estado="pendiente", referencia_id=10,
          tenant_id=1, pago_id=1):
    return SimpleNamespace(id=pago_id, concepto=concepto, estado=estado,
                           referencia_id=referencia_id, tenant_id=tenant_id,
                           monto_clp=50000, created_at=None)


def _solicitud(estado="pending", solicitud_id=10):
    return SimpleNamespace(id=solicitud_id, estado=estado, comentario_admin=None)


class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


def _valores(stmt) -> dict:
    """Valores de un `update()`: {columna: valor}, para afirmar el efecto."""
    out = {}
    for col, param in getattr(stmt, "_values", {}).items():
        out[col.name] = getattr(param, "value", param)
    return out


class _FakeQuery:
    def __init__(self, fila):
        self._fila = fila

    def filter(self, *a, **k):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._fila


class _FakeDB:
    """DB mínima: simula el CAS de `pagos` y el UPDATE de `solicitudes_planes`."""

    def __init__(self, pago, solicitud=None, pedido=None):
        self.pago = pago
        self.solicitud = solicitud
        self.pedido = pedido
        self.pago_valores = []
        self.solicitud_valores = []
        self.commits = 0
        self.rollbacks = 0
        self.expires = 0

    def execute(self, stmt):
        tabla = stmt.table.name
        valores = _valores(stmt)
        if tabla == "pagos":
            self.pago_valores.append(valores)
            # Simula `WHERE estado IN ('pendiente', 'en_proceso')`.
            if self.pago.estado in servicio_pagos.ESTADOS_PAGO_CANCELABLES:
                self.pago.estado = valores.get("estado", self.pago.estado)
                return _FakeResult(1)
            return _FakeResult(0)
        if tabla == "solicitudes_planes":
            self.solicitud_valores.append(valores)
            # Simula `WHERE estado = 'pending'`.
            if self.solicitud is not None and self.solicitud.estado == "pending":
                self.solicitud.estado = valores.get("estado", self.solicitud.estado)
                self.solicitud.comentario_admin = valores.get("comentario_admin")
                return _FakeResult(1)
            return _FakeResult(0)
        raise AssertionError(f"update inesperado: {tabla}")

    def query(self, modelo):
        assert modelo is servicio_pagos.Pedido, f"query inesperada: {modelo}"
        return _FakeQuery(self.pedido)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def expire(self, instancia):        # noqa: ARG002 - emula el refresh del ORM
        self.expires += 1


# ── El caso que resuelve: abandono antes de pagar ─────────────────────────────
def test_cancelar_un_pago_pendiente_lo_deja_cancelado_y_la_solicitud_rejected():
    pago = _pago(estado="pendiente")
    solicitud = _solicitud(estado="pending")
    db = _FakeDB(pago, solicitud=solicitud)

    resultado = servicio_pagos.cancelar_pago(db, pago)

    assert resultado == {"estado": "cancelado"}
    assert pago.estado == "cancelado"
    assert solicitud.estado == "rejected"
    assert solicitud.comentario_admin == servicio_pagos.COMENTARIO_CANCELADO_ALUMNO
    assert (solicitud.comentario_admin
            == "Cancelado por el alumno antes de completar el pago")
    # El UPDATE del pago se hizo contra los estados ABIERTOS (no a ciegas).
    assert db.pago_valores[0].get("estado") == "cancelado"
    assert db.commits == 1 and db.rollbacks == 0
    assert db.expires == 1, "el ORM tiene que releer el estado nuevo"


def test_cancelar_un_pago_en_proceso_tambien_se_cancela():
    pago = _pago(estado="en_proceso")
    solicitud = _solicitud(estado="pending")
    db = _FakeDB(pago, solicitud=solicitud)

    servicio_pagos.cancelar_pago(db, pago)

    assert pago.estado == "cancelado"
    assert solicitud.estado == "rejected"


# ── Lo que NO se puede cancelar ───────────────────────────────────────────────
@pytest.mark.parametrize("estado", ["aprobado", "cancelado", "expirado",
                                    "reembolsado", "rechazado"])
def test_un_pago_que_ya_no_esta_abierto_no_se_cancela(estado):
    pago = _pago(estado=estado)
    solicitud = _solicitud(estado="pending")
    db = _FakeDB(pago, solicitud=solicitud)

    with pytest.raises(servicio_pagos.ErrorPago) as excinfo:
        servicio_pagos.cancelar_pago(db, pago)

    assert excinfo.value.status_code == 409
    assert pago.estado == estado                    # el cobro NO se deshace
    assert solicitud.estado == "pending"            # la solicitud NO se toca
    assert solicitud.comentario_admin is None
    assert db.solicitud_valores == []
    assert db.commits == 0 and db.rollbacks == 1


def test_la_solicitud_que_ya_no_esta_pending_no_se_pisa():
    """El admin la aprobó/rechazó en paralelo: el CAS de `solicitudes_planes`
    (`WHERE estado = 'pending'`) la deja como está y no rompe la cancelación."""
    pago = _pago(estado="pendiente")
    solicitud = _solicitud(estado="approved")
    db = _FakeDB(pago, solicitud=solicitud)

    servicio_pagos.cancelar_pago(db, pago)

    assert pago.estado == "cancelado"
    assert solicitud.estado == "approved"
    assert solicitud.comentario_admin is None


# ── Bazar: el pedido se rechaza por el camino ya probado (devuelve stock) ─────
def test_cancelar_un_pago_de_bazar_rechaza_el_pedido(monkeypatch):
    pago = _pago(concepto="bazar", estado="pendiente")
    pedido = SimpleNamespace(id=pago.referencia_id, tenant_id=1,
                             estado="pendiente")
    llamadas = []

    def _rechazar(db, ped, motivo, *, origen=None):     # noqa: ARG001
        llamadas.append((ped.id, motivo, origen))
        ped.estado = "rechazado"

    monkeypatch.setattr(servicio_pagos.pedidos_estado, "rechazar_pedido",
                        _rechazar)
    db = _FakeDB(pago, pedido=pedido)

    servicio_pagos.cancelar_pago(db, pago)

    assert pago.estado == "cancelado"
    assert llamadas == [(
        pago.referencia_id,
        servicio_pagos.COMENTARIO_CANCELADO_ALUMNO,
        servicio_pagos.pedidos_estado.ORIGEN_MERCADOPAGO,
    )]
