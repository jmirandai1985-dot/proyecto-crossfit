"""
Test permanente para el endpoint de Gestion de Cupos (Tarea 3).
Verifica que PATCH /supervision/cupo-disciplina actualiza TODOS los
horario_base de una disciplina y rechaza valores fuera de 1-200.
"""
import pytest
import requests
from tests.conftest import BASE, TENANT_ID


def test_cupo_actualiza_todos_los_horarios():
    """Verifica que PATCH cupo-disciplina actualiza TODOS los horario_base de la disciplina."""
    # Obtener cantidad actual de horarios para disciplina 1 (CrossFit)
    r = requests.get(f"{BASE}/supervision/cupos-disciplinas",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200
    data = r.json()
    disc = [d for d in data if d["id"] == 1]
    assert len(disc) == 1, "Disciplina 1 debe existir"
    cupo_anterior = disc[0]["cupo_actual"]

    # Cambiar cupo a 99
    r2 = requests.patch(f"{BASE}/supervision/cupo-disciplina",
                        params={"disciplina_id": 1, "cupo_maximo": 99, "tenant_id": TENANT_ID})
    assert r2.status_code == 200, f"Status {r2.status_code}: {r2.text[:200]}"
    resp = r2.json()
    assert resp["ok"] is True
    assert resp["cupo_maximo"] == 99
    assert resp["horarios_actualizados"] > 0, "Debe actualizar al menos 1 horario"

    # Verificar que el cambio persistió
    r3 = requests.get(f"{BASE}/supervision/cupos-disciplinas",
                      params={"tenant_id": TENANT_ID})
    assert r3.status_code == 200
    data2 = r3.json()
    disc2 = [d for d in data2 if d["id"] == 1][0]
    assert disc2["cupo_actual"] == 99, f"Esperaba 99, obtuvo {disc2['cupo_actual']}"
    print(
        f"  [OK] Cupo cambiado de {cupo_anterior} a 99, {resp['horarios_actualizados']} horarios actualizados")

    # Restaurar cupo original
    requests.patch(f"{BASE}/supervision/cupo-disciplina",
                   params={"disciplina_id": 1, "cupo_maximo": cupo_anterior, "tenant_id": TENANT_ID})
    print(f"  [OK] Cupo restaurado a {cupo_anterior}")


def test_cupo_rechaza_cero():
    """Verifica que cupo=0 es rechazado (minimo 1)."""
    r = requests.patch(f"{BASE}/supervision/cupo-disciplina",
                       params={"disciplina_id": 1, "cupo_maximo": 0, "tenant_id": TENANT_ID})
    assert r.status_code == 422, f"Esperaba 422, obtuvo {r.status_code}"
    print(f"  [OK] Cupo=0 rechazado (422)")


def test_cupo_rechaza_negativo():
    """Verifica que cupo negativo es rechazado."""
    r = requests.patch(f"{BASE}/supervision/cupo-disciplina",
                       params={"disciplina_id": 1, "cupo_maximo": -5, "tenant_id": TENANT_ID})
    assert r.status_code == 422, f"Esperaba 422, obtuvo {r.status_code}"
    print(f"  [OK] Cupo=-5 rechazado (422)")


def test_cupo_rechaza_mayor_200():
    """Verifica que cupo>200 es rechazado (maximo 200)."""
    r = requests.patch(f"{BASE}/supervision/cupo-disciplina",
                       params={"disciplina_id": 1, "cupo_maximo": 201, "tenant_id": TENANT_ID})
    assert r.status_code == 422, f"Esperaba 422, obtuvo {r.status_code}"
    print(f"  [OK] Cupo=201 rechazado (422)")
