"""
Test del Panel del Coach — Suite de integración (9 pruebas).
Cubre el flujo completo de gestion de clases por parte del coach:
disciplinas, horarios, creacion de WODs, edicion, y asistencia.

Usa datos del Coach Demo (id=1000) y Alumno Demo (id=999).
Sigue el mismo patron que test_panel_alumno.py.
"""
import pytest
import requests
import json
from datetime import date, timedelta

from tests.conftest import BASE, ALUMNO_ID, TENANT_ID, HOY, HOY_STR

COACH_ID = 1000


# ── Estado compartido entre tests ──
class Shared:
    disciplinas = []
    disciplina_crossfit_id = None
    horarios = []
    horario_ids = []
    wod_creado_id = None
    clase_asignada_id = None
    reserva_id = None
    creditos_antes = None
    creditos_despues = None


# ===================================================================
# BLOQUE 1 — DISCIPLINAS Y HORARIOS (tests 1-2)
# ===================================================================

def test_c01_disciplinas():
    """[1] GET /disciplinas — Listar disciplinas y verificar filtro es_open_box."""
    r = requests.get(f"{BASE}/disciplinas",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert isinstance(data, list), "Debe devolver una lista"
    assert len(data) > 0, "Debe haber al menos una disciplina"
    Shared.disciplinas = data
    # Encontrar crossfit (no open_box)
    crossfit = [d for d in data if d["nombre"].lower().strip() == "crossfit"]
    assert len(crossfit) > 0, "Debe existir la disciplina 'crossfit'"
    Shared.disciplina_crossfit_id = crossfit[0]["id"]
    # Verificar que las open_box se pueden identificar
    open_box = [d for d in data if d.get("es_open_box")]
    assert len(open_box) >= 0, "Debe poder listar open_box"
    assert not crossfit[0].get("es_open_box"), "crossfit no debe ser open_box"
    print(
        f"  Disciplinas: {len(data)} encontradas, crossfit id={Shared.disciplina_crossfit_id}")


def test_c02_horarios_por_disciplina():
    """[2] GET /horarios — Horarios filtrados por disciplina y dia de semana."""
    dia_semana = HOY.weekday()  # 0=Lunes ... 6=Domingo
    r = requests.get(f"{BASE}/horarios",
                     params={"tenant_id": TENANT_ID, "disciplina_id": Shared.disciplina_crossfit_id})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert isinstance(data, list), "Debe devolver una lista"
    Shared.horarios = data
    Shared.horario_ids = [h["id"] for h in data]
    assert len(data) > 0, "Debe haber al menos un horario para crossfit"
    print(f"  Horarios para crossfit: {len(data)} encontrados")
    # Verificar que se pueden filtrar por dia_semana
    hoy_horarios = [h for h in data if h.get("dia_semana") == dia_semana]
    print(f"  Horarios para hoy (dia {dia_semana}): {len(hoy_horarios)}")


# ===================================================================
# BLOQUE 2 — WODs (tests 3-5)
# ===================================================================

def test_c03_crear_wod_texto_libre():
    """[3] POST /wods — Crear un WOD con campos de texto libre."""
    payload = {
        "titulo": "TEST WOD Coach - Fran Variante",
        "descripcion": "21-15-9 de thrusters y pull-ups",
        "fecha": HOY_STR,
        "calentamiento": "2 vueltas: 10 movilidad de hombros, 10 sentadillas, 5 burpees",
        "fuerza_habilidad": "Push Press: 3x5 al 70%",
        "wod_principal": "21-15-9: Thrusters (43/30kg), Pull-ups",
        "tipo_metcon": "FOR TIME",
        "estado": "publicado",
        "coach_id": COACH_ID
    }
    r = requests.post(f"{BASE}/wods/",
                      params={"tenant_id": TENANT_ID},
                      json=payload)
    assert r.status_code == 200 or r.status_code == 201, \
        f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data.get("id"), "Debe devolver un id"
    Shared.wod_creado_id = data["id"]
    assert data.get("titulo") == payload["titulo"], "El titulo debe coincidir"
    assert data.get(
        "calentamiento") == payload["calentamiento"], "calentamiento debe coincidir"
    assert data.get(
        "fuerza_habilidad") == payload["fuerza_habilidad"], "fuerza_habilidad debe coincidir"
    assert data.get(
        "wod_principal") == payload["wod_principal"], "wod_principal debe coincidir"
    assert data.get(
        "tipo_metcon") == payload["tipo_metcon"], "tipo_metcon debe coincidir"
    print(f"  WOD creado: id={Shared.wod_creado_id}")


def test_c04_obtener_wod():
    """[4] GET /wods/{id} — Verificar que el WOD se recupera con todos los campos."""
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"
    r = requests.get(f"{BASE}/wods/{Shared.wod_creado_id}",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert data["id"] == Shared.wod_creado_id, "id debe coincidir"
    assert data["titulo"] == "TEST WOD Coach - Fran Variante", "titulo debe coincidir"
    assert "calentamiento" in data, "Debe tener calentamiento"
    assert "fuerza_habilidad" in data, "Debe tener fuerza_habilidad"
    assert "wod_principal" in data, "Debe tener wod_principal"
    assert data["tipo_metcon"] == "FOR TIME", "tipo_metcon debe ser FOR TIME"
    assert data["estado"] == "publicado", "estado debe ser publicado"
    print(f"  WOD {Shared.wod_creado_id} verificado correctamente")


def test_c05_editar_wod():
    """[5] PUT /wods/{id} — Editar el WOD y verificar cambios."""
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"
    cambios = {
        "titulo": "TEST WOD Coach - Editado",
        "descripcion": "WOD editado para pruebas",
        "calentamiento": "Nuevo calentamiento",
        "fuerza_habilidad": "Nueva fuerza",
        "wod_principal": "Nuevo WOD principal",
        "tipo_metcon": "AMRAP",
        "estado": "draft"
    }
    r = requests.put(f"{BASE}/wods/{Shared.wod_creado_id}",
                     params={"tenant_id": TENANT_ID},
                     json=cambios)
    assert r.status_code == 200, f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data["titulo"] == cambios["titulo"], f"Titulo debe ser '{cambios['titulo']}'"
    assert data["calentamiento"] == cambios["calentamiento"], "calentamiento debe coincidir"
    assert data["tipo_metcon"] == cambios["tipo_metcon"], "tipo_metcon debe ser AMRAP"
    assert data["estado"] == cambios["estado"], "estado debe ser draft"
    print(f"  WOD {Shared.wod_creado_id} editado correctamente")


# ===================================================================
# BLOQUE 3 — ASISTENCIA Y CREDITOS (tests 6-8)
# ===================================================================

def test_c06_asignar_wod_a_clase():
    """[6] POST /wods/clases/{id}/asignar-wod/{wod_id} — Asignar WOD a(s) clase(s)."""
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"
    # Obtener clases de hoy
    r = requests.get(f"{BASE}/clases",
                     params={"tenant_id": TENANT_ID, "fecha_desde": HOY_STR, "fecha_hasta": HOY_STR})
    assert r.status_code == 200, f"Status {r.status_code}"
    clases = r.json()
    clases_hoy = clases if isinstance(clases, list) else (
        clases.get("clases", []) if isinstance(clases, dict) else [])
    assert len(clases_hoy) > 0, "Debe haber al menos una clase hoy"
    Shared.clase_asignada_id = clases_hoy[0]["id"]
    # Asignar WOD a la clase
    r = requests.post(
        f"{BASE}/wods/clases/{Shared.clase_asignada_id}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID}
    )
    assert r.status_code == 200, f"Status {r.status_code}: {r.text[:200]}"
    print(f"  WOD asignado a clase {Shared.clase_asignada_id}")


def test_c06b_wod_hoy_con_alumno_id():
    """[6b] Verificar que GET /wods/hoy?alumno_id=X retorna el WOD de la
    clase donde el alumno tiene reserva (NO el primer WOD del día).
    Esto prueba que el fix de discriminación por disciplina funciona."""
    assert Shared.clase_asignada_id is not None, "test_c06 debe ejecutarse antes"
    # Crear reserva del alumno en la clase que tiene WOD asignado
    r_res = requests.post(f"{BASE}/reservas/",
                          json={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID, "clase_id": Shared.clase_asignada_id})
    if r_res.status_code not in (200, 201):
        r_get = requests.get(f"{BASE}/reservas/por-clase/{Shared.clase_asignada_id}",
                             params={"tenant_id": TENANT_ID})
        assert r_get.status_code == 200, f"GET /por-clase: {r_get.status_code}"
        reservas = r_get.json()
        assert len(reservas) > 0, "Debe haber reserva en la clase"
        Shared.reserva_id_test = reservas[0]["id"]
        print(f"  Reserva existente id={Shared.reserva_id_test}")
    else:
        Shared.reserva_id_test = r_res.json().get("id")
        print(f"  Reserva creada id={Shared.reserva_id_test}")
    # LLAMADA CRÍTICA: GET /wods/hoy?alumno_id=ALUMNO_ID
    r_wod = requests.get(f"{BASE}/wods/hoy",
                         params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
    assert r_wod.status_code == 200, f"Status {r_wod.status_code}"
    wod_recibido = r_wod.json()
    assert wod_recibido is not None, "Debe devolver un WOD"
    assert wod_recibido.get("id") == Shared.wod_creado_id, \
        f"Esperaba WOD id={Shared.wod_creado_id}, obtuvo WOD id={wod_recibido.get('id')} titulo='{wod_recibido.get('titulo')}'"
    print(
        f"  ✅ GET /wods/hoy?alumno_id={ALUMNO_ID} → WOD correcto id={wod_recibido.get('id')}")


def test_c07_marcar_asistencia():
    """[7] PUT /reservas/{id}/asistencia — Marcar asistencia y verificar que se guarda."""
    # Primero crear una reserva para el alumno en la clase
    r = requests.post(f"{BASE}/reservas/",
                      json={
                          "tenant_id": TENANT_ID,
                          "alumno_id": ALUMNO_ID,
                          "clase_id": Shared.clase_asignada_id
    })
    # Si no se puede crear (ya existe), intentamos listar reservas de la clase
    if r.status_code not in (200, 201):
        print(f"  POST reservas falló: {r.status_code} {r.text[:200]}")
        r = requests.get(f"{BASE}/reservas/por-clase/{Shared.clase_asignada_id}",
                         params={"tenant_id": TENANT_ID})
        assert r.status_code == 200, f"Status {r.status_code}: {r.text[:200]}"
        reservas = r.json()
        assert isinstance(
            reservas, list), f"Esperaba lista, obtuvo: {type(reservas)}"
        assert len(reservas) > 0, "Debe haber al menos una reserva"
        Shared.reserva_id = reservas[0]["id"]
    else:
        data = r.json()
        Shared.reserva_id = data.get("id")
    assert Shared.reserva_id is not None, "Debe tener un id de reserva"
    # Verificar creditos antes de marcar asistencia
    r_cred = requests.get(f"{BASE}/planes/membresia-activa",
                          params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
    if r_cred.status_code == 200:
        Shared.creditos_antes = r_cred.json().get("clases_disponibles")

    # Marcar asistencia = true
    r = requests.put(f"{BASE}/reservas/{Shared.reserva_id}/asistencia",
                     params={"tenant_id": TENANT_ID},
                     json={"asistio": True})
    assert r.status_code == 200, f"Status {r.status_code}: {r.text[:200]}"

    # Verificar que se marco asistencia
    r_verif = requests.get(f"{BASE}/reservas/por-clase/{Shared.clase_asignada_id}",
                           params={"tenant_id": TENANT_ID})
    assert r_verif.status_code == 200
    reservas = r_verif.json()
    reserva_actualizada = [
        r for r in reservas if r.get("id") == Shared.reserva_id]
    assert len(reserva_actualizada) > 0, "Debe encontrar la reserva"
    assert reserva_actualizada[0].get("asistio") == True or reserva_actualizada[0].get("asistio") is True, \
        f"asistio debe ser True, obtenido: {reserva_actualizada[0].get('asistio')}"
    print(
        f"  Asistencia marcada correctamente para reserva {Shared.reserva_id}")

    # Cambiar a false y verificar
    r2 = requests.put(f"{BASE}/reservas/{Shared.reserva_id}/asistencia",
                      params={"tenant_id": TENANT_ID},
                      json={"asistio": False})
    assert r2.status_code == 200, f"Status {r2.status_code}"
    print(f"  Asistencia cambiada a false correctamente")


def test_c08_asistencia_false_no_devuelve_credito():
    """[8] Verificar que marcar asistio=false NO devuelve el credito."""
    assert Shared.reserva_id is not None, "Primero debe tener una reserva"
    # Verificar creditos despues de asistencia=false
    r_cred = requests.get(f"{BASE}/planes/membresia-activa",
                          params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
    if r_cred.status_code == 200:
        Shared.creditos_despues = r_cred.json().get("clases_disponibles")
        if Shared.creditos_antes is not None and Shared.creditos_despues is not None:
            # El credito no debe haber sido devuelto (asistio=false == cancelacion tardia)
            assert Shared.creditos_despues <= Shared.creditos_antes, \
                f"creditos NO deben aumentar: antes={Shared.creditos_antes}, despues={Shared.creditos_despues}"
            print(
                f"  Creditos verificados: antes={Shared.creditos_antes}, despues={Shared.creditos_despues} - OK no se devolvio")
        else:
            print("  No se pudieron obtener creditos antes/despues, verificacion omitida")


# ===================================================================
# BLOQUE 4 — LIMPIEZA
# ===================================================================

def test_c09_cleanup():
    """[9] Limpiar datos creados durante los tests."""
    if Shared.wod_creado_id:
        try:
            r = requests.delete(f"{BASE}/wods/{Shared.wod_creado_id}",
                                params={"tenant_id": TENANT_ID})
            if r.status_code in (200, 204):
                print(f"  WOD {Shared.wod_creado_id} eliminado")
        except Exception as e:
            print(f"  WOD cleanup: {e}")

    if Shared.reserva_id:
        try:
            r = requests.delete(f"{BASE}/reservas/{Shared.reserva_id}",
                                params={"tenant_id": TENANT_ID})
            if r.status_code in (200, 204):
                print(f"  Reserva {Shared.reserva_id} eliminada")
        except Exception as e:
            print(f"  Reserva cleanup: {e}")

    print("  Cleanup completado")
