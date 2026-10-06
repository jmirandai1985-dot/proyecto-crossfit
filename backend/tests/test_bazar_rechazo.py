"""Rechazo de un pedido pendiente del Bazar (T3) — puro + endpoint con dobles.

Qué fija este archivo (sin red y sin base de datos):

  A. El motivo viaja en el mensaje de campana del alumno (`texto_rechazo`).
  B. `rechazado` NO cuenta como venta del Bazar (la lista compartida sigue siendo
     `validado` + `entregado`): no suma en el BI, ni en el Excel, ni en el historial.
  C. El endpoint devuelve el stock y avisa al alumno; sólo desde `pendiente`.
  D. El motivo es obligatorio y con largo mínimo (el alumno tiene que entender por qué).

La verificación con la API y el branch TEST reales vive aparte, escrita y NO ejecutada
(`test_pedidos_admin.py::test_ped_09_...`).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_bazar_rechazo.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException                                     # noqa: E402
from app.api.v1 import pedidos as ped                                 # noqa: E402
from app.models.pedido import Pedido                                  # noqa: E402
from app.models.producto import Producto                              # noqa: E402
from app.schemas.pedido import PedidoRechazoRequest                   # noqa: E402
from shared.estados import ESTADOS_PAGO_BAZAR                         # noqa: E402


class _FakeQuery:
    def __init__(self, resultado):
        self._resultado = resultado

    def filter(self, *a, **k):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._resultado


class _FakeDB:
    """Sesión mínima: distingue Pedido de Producto y registra commit/refresh."""

    def __init__(self, pedido, producto=None):
        self._pedido = pedido
        self._producto = producto
        self.committed = False
        self.rolled_back = False

    def query(self, modelo):
        if modelo is Pedido:
            return _FakeQuery(self._pedido)
        if modelo is Producto:
            return _FakeQuery(self._producto)
        raise AssertionError(f"modelo inesperado: {modelo}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, obj):
        pass


def _pedido(estado="pendiente", cantidad=3):
    return SimpleNamespace(id=7, tenant_id=1, alumno_id=42, producto_id=5,
                           cantidad=cantidad, estado=estado)


def _producto(stock=10):
    return SimpleNamespace(id=5, nombre="Polera", stock=stock)


# ── A / B: puro ───────────────────────────────────────────────────────────────
def test_a_el_motivo_viaja_en_el_mensaje():
    texto = ped.texto_rechazo("Polera", 3, "comprobante ilegible")
    assert "Polera" in texto and "x3" in texto and "rechazado" in texto.lower()
    assert texto.endswith("Motivo: comprobante ilegible")


def test_b_rechazado_no_cuenta_como_venta_del_bazar():
    assert set(ESTADOS_PAGO_BAZAR) == {"validado", "entregado"}
    assert "rechazado" not in ESTADOS_PAGO_BAZAR
    assert "rechazado" in ped.MENSAJES_ESTADO_PEDIDO       # el aviso existe
    assert "validado" not in ped.MENSAJES_ESTADO_PEDIDO    # el de validado lleva el código


# ── D: validación del motivo ──────────────────────────────────────────────────
def test_d_el_motivo_es_obligatorio_y_con_largo_minimo():
    with pytest.raises(Exception):
        PedidoRechazoRequest()                              # sin motivo -> 422
    with pytest.raises(Exception):
        PedidoRechazoRequest(motivo="x")                    # demasiado corto
    assert PedidoRechazoRequest(motivo="comprobante ilegible").motivo


# ── C: el endpoint ────────────────────────────────────────────────────────────
def test_c_rechazar_devuelve_stock_y_avisa(monkeypatch):
    avisos = []
    monkeypatch.setattr(
        ped, "notificar_alumno",
        lambda db, alumno_id, tipo, mensaje, **k: avisos.append((alumno_id, tipo, mensaje)))
    p, prod = _pedido(), _producto(stock=10)
    db = _FakeDB(p, prod)

    resultado = ped.rechazar_pedido(
        pedido_id=7, data=SimpleNamespace(motivo="comprobante ilegible"),
        db=db, current_user={"tenant_id": 1, "usuario_id": 9})

    assert resultado is p
    assert p.estado == "rechazado"
    assert prod.stock == 13                              # 10 + 3 devueltas (atómico)
    assert db.committed is True
    assert avisos and avisos[0][0] == 42
    assert avisos[0][1] == "pedido_rechazado"
    assert "comprobante ilegible" in avisos[0][2]


def test_c2_no_se_rechaza_un_pedido_ya_cobrado(monkeypatch):
    monkeypatch.setattr(ped, "notificar_alumno", lambda *a, **k: None)
    p = _pedido(estado="validado")
    db = _FakeDB(p, _producto(stock=10))

    with pytest.raises(HTTPException) as exc:
        ped.rechazar_pedido(pedido_id=7, data=SimpleNamespace(motivo="no me gusta el pago"),
                            db=db, current_user={"tenant_id": 1, "usuario_id": 9})

    assert exc.value.status_code == 400
    assert p.estado == "validado"                        # no se tocó
    assert db.committed is False and db.rolled_back is False


def test_c3_otro_tenant_no_ve_el_pedido(monkeypatch):
    """El filtro es por tenant del token: la query no devuelve nada -> 404."""
    monkeypatch.setattr(ped, "notificar_alumno", lambda *a, **k: None)
    db = _FakeDB(None, _producto())

    with pytest.raises(HTTPException) as exc:
        ped.rechazar_pedido(pedido_id=7, data=SimpleNamespace(motivo="motivo largo"),
                            db=db, current_user={"tenant_id": 2, "usuario_id": 9})

    assert exc.value.status_code == 404
    assert db.committed is False
