"""Expiración de pagos online no cobrados (`services/pagos.expirar_pendientes`).

Tests AISLADOS (sin red y sin base de datos): la regla del umbral y los guardas
de estado, no la consulta real.

  * `pago_vencido` es una función PURA: vence JUSTO en el límite de 24 h (no un
    minuto después) y no vence antes; un concepto sin expiración nunca vence.
  * `expirar_pendientes` sólo mira pagos abiertos (`pendiente`/`en_proceso`): un
    pago `aprobado` no entra a la lista, así que no expira.
  * La solicitud pasa a `expirada` sólo si seguía `pending`; una ya `rejected`
    no se toca.
  * Un pago aprobado DESPUÉS de expirar avisa a los admins (no se pierde plata).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_expirar_pendientes.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.models.pago import Pago                          # noqa: E402
from app.models.solicitud_plan import SolicitudPlan       # noqa: E402
from app.services import pagos as servicio_pagos          # noqa: E402

AHORA = datetime(2026, 1, 10, 12, 0, 0)


def _pago(concepto="membresia", estado="pendiente", creado=AHORA,
          referencia_id=10, tenant_id=1, pago_id=1):
    return SimpleNamespace(id=pago_id, concepto=concepto, estado=estado,
                           created_at=creado, referencia_id=referencia_id,
                           tenant_id=tenant_id, monto_clp=50000)


def _solicitud(estado="pending", solicitud_id=10):
    return SimpleNamespace(id=solicitud_id, estado=estado, comentario_admin=None)


# ── pago_vencido (puro) ───────────────────────────────────────────────────────
def test_justo_en_el_limite_de_24h_expira():
    pago = _pago(creado=AHORA - timedelta(hours=24))
    assert servicio_pagos.pago_vencido(pago, ahora=AHORA) is True


def test_antes_del_limite_no_expira():
    pago = _pago(creado=AHORA - timedelta(hours=23, minutes=59))
    assert servicio_pagos.pago_vencido(pago, ahora=AHORA) is False


def test_bazar_vence_a_los_30_minutos():
    vencido = _pago(concepto="bazar", creado=AHORA - timedelta(minutes=30))
    fresco = _pago(concepto="bazar", creado=AHORA - timedelta(minutes=29))
    assert servicio_pagos.pago_vencido(vencido, ahora=AHORA) is True
    assert servicio_pagos.pago_vencido(fresco, ahora=AHORA) is False


def test_sin_fecha_o_concepto_desconocido_no_expira():
    assert servicio_pagos.pago_vencido(_pago(creado=None), ahora=AHORA) is False
    assert servicio_pagos.pago_vencido(
        _pago(concepto="emergencia"), ahora=AHORA) is False


# ── expirar_pendientes (fake DB, camino membresía) ────────────────────────────
class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _FakeQueryList:
    def __init__(self, items):
        self._items = items

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


def _valores(stmt) -> dict:
    """Valores de un `update()`: {columna: valor}, para afirmar el efecto."""
    out = {}
    for col, param in getattr(stmt, "_values", {}).items():
        out[col.name] = getattr(param, "value", param)
    return out


class _FakeDBExpirar:
    def __init__(self, pagos, solicitud=None):
        self._pagos = pagos
        self._solicitud = solicitud
        self.commits = 0
        self.rollbacks = 0
        self.pago_valores = []
        self.solicitud_valores = []

    def query(self, modelo):
        if modelo is Pago:
            return _FakeQueryList(self._pagos)
        if modelo is SolicitudPlan:
            return _FakeQueryList([self._solicitud] if self._solicitud else [])
        raise AssertionError(f"modelo inesperado: {modelo}")

    def execute(self, stmt):
        valores = _valores(stmt)
        if stmt.table.name == "pagos":
            self.pago_valores.append(valores)
            return _FakeResult(1)
        if stmt.table.name == "solicitudes_planes":
            self.solicitud_valores.append(valores)
            # Simula el `WHERE ... estado = 'pending'` del UPDATE.
            if self._solicitud is not None and self._solicitud.estado == "pending":
                self._solicitud.estado = valores.get("estado", self._solicitud.estado)
                self._solicitud.comentario_admin = valores.get("comentario_admin")
                return _FakeResult(1)
            return _FakeResult(0)
        raise AssertionError(f"update inesperado: {stmt.table.name}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_solicitud_pendiente_pasada_24h_se_marca_expirada(monkeypatch):
    monkeypatch.setattr(servicio_pagos, "ahora_santiago", lambda: AHORA)
    pago = _pago(creado=AHORA - timedelta(hours=25))
    solicitud = _solicitud(estado="pending")
    db = _FakeDBExpirar([pago], solicitud)

    resultado = servicio_pagos.expirar_pendientes(db)

    assert resultado["expirados"] == 1
    assert resultado["solicitudes_expiradas"] == 1
    assert solicitud.estado == "expirada"
    assert solicitud.comentario_admin == "Expirada: pago online no completado en 24 h"
    assert db.pago_valores and db.pago_valores[0].get("estado") == "expirado"


def test_antes_de_24h_no_se_toca_nada(monkeypatch):
    monkeypatch.setattr(servicio_pagos, "ahora_santiago", lambda: AHORA)
    pago = _pago(creado=AHORA - timedelta(hours=23))
    solicitud = _solicitud(estado="pending")
    db = _FakeDBExpirar([pago], solicitud)

    resultado = servicio_pagos.expirar_pendientes(db)

    assert resultado["expirados"] == 0
    assert resultado["solicitudes_expiradas"] == 0
    assert db.pago_valores == [] and db.solicitud_valores == []


def test_solicitud_ya_rechazada_no_se_toca(monkeypatch):
    monkeypatch.setattr(servicio_pagos, "ahora_santiago", lambda: AHORA)
    pago = _pago(creado=AHORA - timedelta(hours=25))
    solicitud = _solicitud(estado="rejected")
    db = _FakeDBExpirar([pago], solicitud)

    resultado = servicio_pagos.expirar_pendientes(db)

    assert resultado["expirados"] == 1          # el pago sí expira
    assert resultado["solicitudes_expiradas"] == 0
    assert solicitud.estado == "rejected"       # la solicitud NO se toca


def test_ya_pagada_no_expira_porque_el_filtro_solo_mira_abiertos():
    """El `abiertos` se arma con `estado IN (pendiente, en_proceso)`: un pago
    `aprobado` (ya pagado) no entra a la lista y por lo tanto no expira."""
    fuente = (_BACKEND / "app" / "services" / "pagos.py").read_text(encoding="utf-8")
    assert 'Pago.estado.in_(("pendiente", "en_proceso"))' in fuente


# ── Pago aprobado DESPUÉS de expirar: avisa a los admins ──────────────────────
def test_pago_aprobado_sobre_solicitud_expirada_avisa_admins(monkeypatch):
    avisos = []

    def _activar(*a, **k):
        raise servicio_pagos.aprobacion_planes.SolicitudNoProcesable("ya_procesada")

    monkeypatch.setattr(servicio_pagos.aprobacion_planes, "activar_plan", _activar)
    monkeypatch.setattr(
        servicio_pagos, "_alertar_admins",
        lambda db, tenant_id, tipo, mensaje: avisos.append((tipo, mensaje)))

    pago = _pago(estado="aprobado", referencia_id=10)
    solicitud = _solicitud(estado="expirada")
    db = _FakeDBExpirar([pago], solicitud)

    servicio_pagos._aplicar_beneficio(db, pago)

    assert avisos and avisos[0][0] == "pago_aprobado_solicitud_rechazada"
    assert "EXPIRADA" in avisos[0][1]

