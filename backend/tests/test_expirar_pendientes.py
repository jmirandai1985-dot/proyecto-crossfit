"""Expiración de pagos online no cobrados (`services/pagos.expirar_pendientes`).

Tests AISLADOS (sin red y sin base de datos): la regla del umbral y los guardas
de estado, no la consulta real.

  * `pago_vencido` es una función PURA: vence JUSTO en el límite de 30 min (no
    un minuto después) y no vence antes; un concepto sin expiración nunca vence.
  * Membresía y Bazar comparten el MISMO criterio (minutos): una intención de
    pago abandonada no puede bloquear al alumno ni reservar stock.
  * `expirar_pendientes` mira pagos abiertos (`iniciado`/`pendiente`/`en_proceso`):
    un pago `aprobado` no entra a la lista, así que no expira. `iniciado` es el
    checkout que nunca tuvo ningún aviso de MP: se cierra por housekeeping.
  * La solicitud pasa a `expirada` si seguía `iniciado` o `pending`; una ya
    `rejected` no se toca.
  * Un pago aprobado DESPUÉS de expirar avisa a los admins (no se pierde plata).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_expirar_pendientes.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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
def test_justo_en_el_limite_de_30_minutos_expira():
    pago = _pago(creado=AHORA - timedelta(minutes=30))
    assert servicio_pagos.pago_vencido(pago, ahora=AHORA) is True


def test_antes_del_limite_no_expira():
    pago = _pago(creado=AHORA - timedelta(minutes=29))
    assert servicio_pagos.pago_vencido(pago, ahora=AHORA) is False


def test_membresia_y_bazar_comparten_el_mismo_umbral():
    """Una sola decisión de negocio: la membresía NO espera horas. Si alguien
    vuelve a separar los criterios, este test lo obliga a justificarlo."""
    assert servicio_pagos.MINUTOS_MEMBRESIA == servicio_pagos.MINUTOS_BAZAR == 30
    for concepto in ("membresia", "bazar"):
        vencido = _pago(concepto=concepto, creado=AHORA - timedelta(minutes=30))
        fresco = _pago(concepto=concepto, creado=AHORA - timedelta(minutes=29))
        assert servicio_pagos.pago_vencido(vencido, ahora=AHORA) is True, concepto
        assert servicio_pagos.pago_vencido(fresco, ahora=AHORA) is False, concepto


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
            # Simula el `WHERE ... estado IN ('iniciado', 'pending')` del UPDATE.
            if (self._solicitud is not None
                    and self._solicitud.estado in ("iniciado", "pending")):
                self._solicitud.estado = valores.get("estado", self._solicitud.estado)
                self._solicitud.comentario_admin = valores.get("comentario_admin")
                return _FakeResult(1)
            return _FakeResult(0)
        raise AssertionError(f"update inesperado: {stmt.table.name}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_solicitud_pendiente_pasados_30_min_se_marca_expirada(monkeypatch):
    monkeypatch.setattr(servicio_pagos, "ahora_santiago", lambda: AHORA)
    pago = _pago(creado=AHORA - timedelta(minutes=31))
    solicitud = _solicitud(estado="pending")
    db = _FakeDBExpirar([pago], solicitud)

    resultado = servicio_pagos.expirar_pendientes(db)

    assert resultado["expirados"] == 1
    assert resultado["solicitudes_expiradas"] == 1
    assert solicitud.estado == "expirada"
    assert solicitud.comentario_admin == "Expirada: pago online no completado en 30 min"
    assert db.pago_valores and db.pago_valores[0].get("estado") == "expirado"


def test_solicitud_iniciada_pasados_30_min_se_marca_expirada(monkeypatch):
    """El checkout que nunca tuvo aviso de MP también se cierra (housekeeping).
    La fila era invisible para el admin, pero no se acumula para siempre."""
    monkeypatch.setattr(servicio_pagos, "ahora_santiago", lambda: AHORA)
    pago = _pago(estado="iniciado", creado=AHORA - timedelta(minutes=31))
    solicitud = _solicitud(estado="iniciado")
    db = _FakeDBExpirar([pago], solicitud)

    resultado = servicio_pagos.expirar_pendientes(db)

    assert resultado["expirados"] == 1
    assert resultado["solicitudes_expiradas"] == 1
    assert solicitud.estado == "expirada"


def test_antes_de_30_min_no_se_toca_nada(monkeypatch):
    monkeypatch.setattr(servicio_pagos, "ahora_santiago", lambda: AHORA)
    pago = _pago(creado=AHORA - timedelta(minutes=29))
    solicitud = _solicitud(estado="pending")
    db = _FakeDBExpirar([pago], solicitud)

    resultado = servicio_pagos.expirar_pendientes(db)

    assert resultado["expirados"] == 0
    assert resultado["solicitudes_expiradas"] == 0
    assert db.pago_valores == [] and db.solicitud_valores == []


def test_solicitud_ya_rechazada_no_se_toca(monkeypatch):
    monkeypatch.setattr(servicio_pagos, "ahora_santiago", lambda: AHORA)
    pago = _pago(creado=AHORA - timedelta(minutes=31))
    solicitud = _solicitud(estado="rejected")
    db = _FakeDBExpirar([pago], solicitud)

    resultado = servicio_pagos.expirar_pendientes(db)

    assert resultado["expirados"] == 1          # el pago sí expira
    assert resultado["solicitudes_expiradas"] == 0
    assert solicitud.estado == "rejected"       # la solicitud NO se toca


def test_ya_pagada_no_expira_porque_el_filtro_solo_mira_abiertos():
    """El `abiertos` se arma con `estado IN (iniciado, pendiente, en_proceso)`:
    un pago `aprobado` (ya pagado) no entra a la lista y por lo tanto no expira."""
    fuente = (_BACKEND / "app" / "services" / "pagos.py").read_text(encoding="utf-8")
    assert ('Pago.estado.in_(("iniciado", "pendiente", "en_proceso"))'
            in fuente)


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


# ── La regla está duplicada en el cron SQL: tiene que decir LO MISMO ──────────
def test_el_cron_sql_replica_los_mismos_umbrales_que_el_servicio():
    """`maintenance/expirar_pendientes.py` no puede importar la app (imagen de
    cron mínima), así que repite la regla en SQL. Este test es el candado para
    que los dos números no se separen (el de antes: 24 h en la app, 30 min en
    el Bazar)."""
    fuente = (_BACKEND / "maintenance" / "expirar_pendientes.py").read_text(
        encoding="utf-8")
    assert f"MINUTOS_MEMBRESIA = {servicio_pagos.MINUTOS_MEMBRESIA}" in fuente
    assert f"MINUTOS_BAZAR = {servicio_pagos.MINUTOS_BAZAR}" in fuente
    # SQL: intervalos en MINUTOS para los dos conceptos (ningún `hours`).
    assert "interval '{MINUTOS_MEMBRESIA} minutes'" in fuente
    assert "interval '{MINUTOS_BAZAR} minutes'" in fuente
    assert "hours" not in fuente
    # El cron también cierra los `iniciado` (checkout sin ningún aviso de MP).
    assert "estado IN ('iniciado', 'pendiente', 'en_proceso')" in fuente
    assert "s.estado IN ('iniciado', 'pending')" in fuente
    # El comentario que ve el admin es el MISMO de la app.
    assert "COMENTARIO_EXPIRADA = f\"Expirada: pago online no completado en " in fuente
    assert (servicio_pagos.COMENTARIO_EXPIRADA
            == "Expirada: pago online no completado en 30 min")
    # Y el cron es horario: el umbral nuevo se aplica con hasta ~1 h de retraso.
    render = (_BACKEND.parent / "render.yaml").read_text(encoding="utf-8")
    assert 'name: box-crossfit-expirar-pendientes' in render
    assert 'schedule: "0 * * * *"' in render

