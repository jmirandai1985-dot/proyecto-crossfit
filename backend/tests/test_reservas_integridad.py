"""
P0-2 (auditoría panel Alumno) — integridad de reservas.

Reproducido en TEST el 2026-09-24, ANTES del fix:
  - POST /reservas guardaba `estado` y `asistio` del body tal cual: el alumno se
    auto-marcaba presente (`estado='completada'`, `asistio=true`) en una clase
    futura -> HTTP 201 y fila (3, 154, 1202, 'completada', True).
  - Se podía reservar una clase de una fecha PASADA (creó la reserva 4 sobre la
    clase del 23/09 pese a ser pasada).
  - PUT /reservas/{id} del propio alumno dejó la reserva en estado
    'cancelled_x' con tokens_gastados=0.
  - 3 DELETE seguidos devolvieron crédito 3 veces (996 -> 997 -> 998 -> 999).

Corre contra la API real en localhost:8000 (requiere ENVIRONMENT=test).
"""
from datetime import timedelta

import pytest
import requests

from tests.conftest import (ALUMNO_ID, BASE, HOY, HOY_STR, TENANT_ID,
                            get_alumno_token)


def _h():
    return {"Authorization": f"Bearer {get_alumno_token(ALUMNO_ID)}"}


def _clases_futuras():
    r = requests.get(
        f"{BASE}/clases",
        params={"fecha_desde": HOY_STR, "fecha_hasta": str(HOY + timedelta(days=7)),
                "limit": 200},
        headers=_h(), timeout=20)
    if r.status_code != 200:
        return []
    return [c for c in (r.json() or []) if not c.get("cancelada")]


def _clases_pasadas():
    r = requests.get(
        f"{BASE}/clases",
        params={"fecha_desde": str(HOY - timedelta(days=10)),
                "fecha_hasta": str(HOY - timedelta(days=1)), "limit": 200},
        headers=_h(), timeout=20)
    if r.status_code != 200:
        return []
    return [c for c in (r.json() or []) if not c.get("cancelada")]


def _post_reserva(clase_id, **extra):
    body = {"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID, "clase_id": clase_id}
    body.update(extra)
    return requests.post(f"{BASE}/reservas", headers=_h(), json=body, timeout=20)


def _reserva_para_tests():
    """Crea una reserva en la primera clase futura libre (o None si no se puede)."""
    for clase in _clases_futuras():
        r = _post_reserva(clase["id"])
        if r.status_code == 201:
            return r.json()
    return None


def _creditos():
    r = requests.get(f"{BASE}/planes/membresia-activa", headers=_h(), timeout=20)
    if r.status_code != 200:
        return None
    return r.json().get("clases_disponibles")


# ═══════════════════════════════════════════════════════════════════
# D-03 — el cliente no decide estado/asistencia, ni reserva al pasado
# ═══════════════════════════════════════════════════════════════════

def test_p02_post_reservas_ignora_estado_y_asistio_del_body():
    """Con estado/asistio hackeados en el body, la reserva nace 'confirmada' y
    SIN asistencia (antes: 'completada' + asistio=true = auto-marcarse presente)."""
    clase = next(iter(_clases_futuras()), None)
    if not clase:
        pytest.skip("No hay clases futuras disponibles en TEST")
    r = _post_reserva(clase["id"], estado="completada", asistio=True)
    if r.status_code != 201:
        pytest.skip(f"no se pudo crear la reserva: {r.status_code} {r.text[:120]}")
    data = r.json()
    assert data.get("estado") == "confirmada", (
        f"se respetó el estado del body: {data.get('estado')}")
    assert data.get("asistio") is False, "el alumno pudo auto-marcarse presente"
    requests.delete(f"{BASE}/reservas/{data['id']}", headers=_h(), timeout=20)


def test_p02_no_permite_reservar_clase_pasada():
    """POST /reservas sobre una clase de fecha pasada -> 400 (antes: 201)."""
    pasadas = _clases_pasadas()
    if not pasadas:
        pytest.skip("TEST no tiene clases pasadas para probar")
    r = _post_reserva(pasadas[0]["id"])
    assert r.status_code == 400, f"status {r.status_code}: {r.text[:200]}"
    assert "pasada" in (r.json().get("detail") or "").lower()


# ═══════════════════════════════════════════════════════════════════
# R-02 — el alumno no puede reescribir su reserva
# ═══════════════════════════════════════════════════════════════════

def test_p02_put_reserva_bloqueado_para_alumno():
    """PUT /reservas/{id} del propio alumno -> 403 y la fila no cambia."""
    reserva = _reserva_para_tests()
    if not reserva:
        pytest.skip("no se pudo crear la reserva de prueba")
    rid = reserva["id"]
    r = requests.put(
        f"{BASE}/reservas/{rid}", headers=_h(),
        json={"estado": "cancelled_x", "asistio": True, "tokens_gastados": 0},
        timeout=20)
    assert r.status_code == 403, f"status {r.status_code}: {r.text[:200]}"

    r2 = requests.get(f"{BASE}/reservas/{rid}", headers=_h(), timeout=20)
    if r2.status_code == 200:
        d = r2.json()
        assert d.get("estado") != "cancelled_x", "el alumno reescribió el estado"
        assert d.get("asistio") is False, "el alumno se auto-marcó presente"
        assert d.get("tokens_gastados") != 0, "el alumno tocó tokens_gastados"
    requests.delete(f"{BASE}/reservas/{rid}", headers=_h(), timeout=20)


# ═══════════════════════════════════════════════════════════════════
# R-03 — cancelar es idempotente (sin doble devolución de crédito)
# ═══════════════════════════════════════════════════════════════════

def test_p02_delete_de_reserva_es_idempotente():
    """1er DELETE -> 2xx; 2do -> 409 y SIN devolver el crédito otra vez."""
    reserva = _reserva_para_tests()
    if not reserva:
        pytest.skip("no se pudo crear la reserva de prueba")
    rid = reserva["id"]

    r1 = requests.delete(f"{BASE}/reservas/{rid}", headers=_h(), timeout=20)
    assert r1.status_code in (200, 204), f"1er DELETE: {r1.status_code} {r1.text[:200]}"
    creditos_1 = _creditos()

    r2 = requests.delete(f"{BASE}/reservas/{rid}", headers=_h(), timeout=20)
    assert r2.status_code == 409, (
        f"el 2do DELETE debería ser 409 (ya cancelada), fue {r2.status_code}")
    creditos_2 = _creditos()

    if creditos_1 is not None and creditos_2 is not None:
        assert creditos_1 == creditos_2, (
            f"doble devolución de crédito: {creditos_1} -> {creditos_2}")
