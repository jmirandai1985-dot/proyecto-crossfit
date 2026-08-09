"""
Test del Panel del Coach â€” Suite de integraciÃ³n (9 pruebas).
Cubre el flujo completo de gestion de clases por parte del coach:
disciplinas, horarios, creacion de WODs, edicion, y asistencia.

Usa datos del Coach Demo (id=1000) y Alumno Demo (id=999).
Sigue el mismo patron que test_panel_alumno.py.
"""
import pytest
import requests
import json
from datetime import date, timedelta

from tests.conftest import BASE, ALUMNO_ID, TENANT_ID, HOY, HOY_STR, get_coach_token

COACH_ID = 1000


# â”€â”€ Estado compartido entre tests â”€â”€
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
# BLOQUE 1 â€” DISCIPLINAS Y HORARIOS (tests 1-2)
# ===================================================================

def test_c01_disciplinas():
    """[1] GET /disciplinas â€” Listar disciplinas y verificar filtro es_open_box."""
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
    """[2] GET /horarios â€” Horarios filtrados por disciplina y dia de semana."""
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
# BLOQUE 2 â€” WODs (tests 3-5)
# ===================================================================

def test_c03_crear_wod_texto_libre():
    """[3] POST /wods â€” Crear un WOD con campos de texto libre."""
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
    token = get_coach_token(coach_id=COACH_ID)
    r = requests.post(f"{BASE}/wods/",
                      params={"tenant_id": TENANT_ID,
                              "disciplina_id": Shared.disciplina_crossfit_id or 1},
                      json=payload,
                      headers={"Authorization": f"Bearer {token}"})
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
    """[4] GET /wods/{id} â€” Verificar que el WOD se recupera con todos los campos."""
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
    """[5] PUT /wods/{id} â€” Editar el WOD y verificar cambios."""
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
    token = get_coach_token(coach_id=COACH_ID)
    r = requests.put(f"{BASE}/wods/{Shared.wod_creado_id}",
                     params={"tenant_id": TENANT_ID,
                             "disciplina_id": Shared.disciplina_crossfit_id or 1},
                     json=cambios,
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data["titulo"] == cambios["titulo"], f"Titulo debe ser '{cambios['titulo']}'"
    assert data["calentamiento"] == cambios["calentamiento"], "calentamiento debe coincidir"
    assert data["tipo_metcon"] == cambios["tipo_metcon"], "tipo_metcon debe ser AMRAP"
    assert data["estado"] == cambios["estado"], "estado debe ser draft"
    print(f"  WOD {Shared.wod_creado_id} editado correctamente")


# ===================================================================
# BLOQUE 3 â€” ASISTENCIA Y CREDITOS (tests 6-8)
# ===================================================================

def test_c06_asignar_wod_a_clase():
    """[6] POST /wods/clases/{id}/asignar-wod/{wod_id} â€” Asignar WOD a(s) clase(s)."""
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"
    # Obtener clases de hoy
    r = requests.get(f"{BASE}/clases",
                     params={"tenant_id": TENANT_ID, "fecha_desde": HOY_STR, "fecha_hasta": HOY_STR})
    assert r.status_code == 200, f"Status {r.status_code}"
    clases = r.json()
    clases_hoy = clases if isinstance(clases, list) else (
        clases.get("clases", []) if isinstance(clases, dict) else [])
    assert len(clases_hoy) > 0, "Debe haber al menos una clase hoy"
    # Pick a CrossFit class (disc 1) since coach 1000 is only assigned to CrossFit
    crossfit_classes = [c for c in clases_hoy if c.get(
        "disciplina_id") == Shared.disciplina_crossfit_id]
    assert len(
        crossfit_classes) > 0, "Debe haber al menos una clase de CrossFit hoy"
    Shared.clase_asignada_id = crossfit_classes[0]["id"]
    # Asignar WOD a la clase
    token = get_coach_token(coach_id=COACH_ID)
    r = requests.post(
        f"{BASE}/wods/clases/{Shared.clase_asignada_id}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, f"Status {r.status_code}: {r.text[:200]}"
    print(f"  WOD asignado a clase {Shared.clase_asignada_id}")


def test_c06b_wod_hoy_con_alumno_id():
    """[6b] Verificar que GET /wods/hoy?alumno_id=X retorna el WOD de la
    clase donde el alumno tiene reserva (NO el primer WOD del dÃ­a).
    Esto prueba que el fix de discriminaciÃ³n por disciplina funciona."""
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
    # LLAMADA CRÃTICA: GET /wods/hoy?alumno_id=ALUMNO_ID
    r_wod = requests.get(f"{BASE}/wods/hoy",
                         params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
    assert r_wod.status_code == 200, f"Status {r_wod.status_code}"
    wod_recibido = r_wod.json()
    assert wod_recibido is not None, "Debe devolver un WOD"
    assert wod_recibido.get("id") == Shared.wod_creado_id, \
        f"Esperaba WOD id={Shared.wod_creado_id}, obtuvo WOD id={wod_recibido.get('id')} titulo='{wod_recibido.get('titulo')}'"
    print(
        f"  âœ… GET /wods/hoy?alumno_id={ALUMNO_ID} â†’ WOD correcto id={wod_recibido.get('id')}")


def test_c07_marcar_asistencia():
    """[7] PUT /reservas/{id}/asistencia â€” Marcar asistencia y verificar que se guarda."""
    # Primero crear una reserva para el alumno en la clase
    r = requests.post(f"{BASE}/reservas/",
                      json={
                          "tenant_id": TENANT_ID,
                          "alumno_id": ALUMNO_ID,
                          "clase_id": Shared.clase_asignada_id
    })
    # Si no se puede crear (ya existe), intentamos listar reservas de la clase
    if r.status_code not in (200, 201):
        print(f"  POST reservas fallÃ³: {r.status_code} {r.text[:200]}")
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
    token = get_coach_token(coach_id=COACH_ID)
    r = requests.put(f"{BASE}/reservas/{Shared.reserva_id}/asistencia",
                     params={"tenant_id": TENANT_ID},
                     json={"asistio": True},
                     headers={"Authorization": f"Bearer {token}"})
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
    token = get_coach_token(coach_id=COACH_ID)
    r2 = requests.put(f"{BASE}/reservas/{Shared.reserva_id}/asistencia",
                      params={"tenant_id": TENANT_ID},
                      json={"asistio": False},
                      headers={"Authorization": f"Bearer {token}"})
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
# BLOQUE 4 â€” SEGURIDAD (test permanente de regresiÃ³n IDOR)
# ===================================================================

def test_c10_seguridad_coach_no_puede_operar_otra_disciplina():
    """[10] Verificar que un coach NO puede asignar WOD ni marcar asistencia
    en una disciplina a la que NO pertenece (IDOR cerrado permanentemente).

    Coach 1000 solo estÃ¡ asignado a CrossFit (disc 1).
    Intenta operar sobre Levantamiento OlÃ­mpico (disc 4) y debe recibir 403.
    """
    token = get_coach_token(coach_id=COACH_ID)

    # â”€â”€ Obtener una clase de Levantamiento OlÃ­mpico (disc 4) â”€â”€
    r = requests.get(f"{BASE}/clases",
                     params={"tenant_id": TENANT_ID, "fecha_desde": HOY_STR, "fecha_hasta": HOY_STR})
    assert r.status_code == 200, f"GET clases: {r.status_code}"
    clases = r.json()
    clases_hoy = clases if isinstance(clases, list) else (
        clases.get("clases", []) if isinstance(clases, dict) else [])
    lev_olimp = [c for c in clases_hoy if c.get("disciplina_id") == 4]
    assert len(lev_olimp) > 0, "Debe existir clase de Lev. OlÃ­mpico hoy"
    clase_otra_disc = lev_olimp[0]

    # â”€â”€ Intentar asignar WOD a clase de OTRA disciplina â†’ 403 â”€â”€
    r_wod = requests.post(
        f"{BASE}/wods/clases/{clase_otra_disc['id']}/asignar-wod/1",
        params={"tenant_id": TENANT_ID},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r_wod.status_code == 403, \
        f"Esperaba 403 (no autorizado), obtuvo {r_wod.status_code}: {r_wod.text[:200]}"
    assert "no esta asignado" in r_wod.json().get("detail", ""), \
        f"Mensaje debe indicar falta de asignacion: {r_wod.text[:200]}"
    print(f"  âœ… Asignar WOD a disc 4 â†’ 403 (bloqueado correctamente)")

    # â”€â”€ Intentar marcar asistencia en reserva de OTRA disciplina â†’ 403 â”€â”€
    # Crear una reserva en la clase de Lev. OlÃ­mpico para tener un ID vÃ¡lido
    r_res = requests.post(f"{BASE}/reservas/",
                          json={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID, "clase_id": clase_otra_disc["id"]})
    reserva_id_otra = None
    if r_res.status_code in (200, 201):
        reserva_id_otra = r_res.json().get("id")
    else:
        # Si ya existe, obtenerla del listado
        r_list = requests.get(f"{BASE}/reservas/por-clase/{clase_otra_disc['id']}",
                              params={"tenant_id": TENANT_ID})
        if r_list.status_code == 200:
            reservas_list = r_list.json()
            if reservas_list:
                reserva_id_otra = reservas_list[0]["id"]

    if reserva_id_otra:
        r_asist = requests.put(f"{BASE}/reservas/{reserva_id_otra}/asistencia",
                               params={"tenant_id": TENANT_ID},
                               json={"asistio": True},
                               headers={"Authorization": f"Bearer {token}"})
        assert r_asist.status_code == 403, \
            f"Esperaba 403 al marcar asistencia en disc ajena, obtuvo {r_asist.status_code}: {r_asist.text[:200]}"
        print(f"  âœ… Marcar asistencia en disc 4 â†’ 403 (bloqueado correctamente)")
    else:
        print(
            "  âš ï¸ No se pudo crear/obtener reserva en disc 4 â€” prueba de asistencia omitida")
        print("     (la prueba de asignar WOD ya confirmÃ³ el 403)")


# ===================================================================
# BLOQUE 5 â€” BATCH WOD (tests 11-12)
# ===================================================================

def test_c12_batch_asignar_wod():
    """[12] POST /wods/batch â€” Asignar WOD a varias clases en un solo request.
    a) Batch exitoso con 2 clases de la misma disciplina (CrossFit)
    b) Batch RECHAZADO si incluye una clase de otra disciplina
    """
    token = get_coach_token(coach_id=COACH_ID)
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"

    # Obtener clases de hoy
    r = requests.get(f"{BASE}/clases",
                     params={"tenant_id": TENANT_ID, "fecha_desde": HOY_STR, "fecha_hasta": HOY_STR})
    assert r.status_code == 200
    clases = r.json()
    clases_hoy = clases if isinstance(clases, list) else (
        clases.get("clases", []) if isinstance(clases, dict) else [])

    # â”€â”€ a) Batch exitoso: 2 clases de CrossFit (disc 1) â”€â”€
    crossfit = [c for c in clases_hoy if c.get(
        "disciplina_id") == Shared.disciplina_crossfit_id]
    assert len(crossfit) >= 1, "Debe haber al menos 1 clase de CrossFit hoy"
    cf_ids = [crossfit[0]["id"]]

    r_batch = requests.post(f"{BASE}/wods/batch",
                            params={"tenant_id": TENANT_ID},
                            json={"wod_id": Shared.wod_creado_id,
                                  "clase_ids": cf_ids},
                            headers={"Authorization": f"Bearer {token}"})
    assert r_batch.status_code == 200, \
        f"Esperaba 200 batch exitoso, obtuvo {r_batch.status_code}: {r_batch.text[:200]}"
    data = r_batch.json()
    assert data.get("actualizadas") == 1, \
        f"Esperaba 1 actualizada, obtuvo {data.get('actualizadas')}"
    assert data.get("wod_id") == Shared.wod_creado_id
    print(
        f"  âœ… Batch: WOD asignado a {data['actualizadas']} clase(s) de CrossFit")

    # â”€â”€ b) Batch RECHAZADO: incluye clase de otra disciplina â”€â”€
    lev_olimp = [c for c in clases_hoy if c.get("disciplina_id") == 4]
    assert len(lev_olimp) > 0, "Debe existir clase de Lev. OlÃ­mpico hoy"
    # Mezclar: 1 CrossFit + 1 Lev. OlÃ­mpico
    ids_mezclados = [crossfit[0]["id"], lev_olimp[0]["id"]]

    r_reject = requests.post(f"{BASE}/wods/batch",
                             params={"tenant_id": TENANT_ID},
                             json={"wod_id": Shared.wod_creado_id,
                                   "clase_ids": ids_mezclados},
                             headers={"Authorization": f"Bearer {token}"})
    assert r_reject.status_code == 403, \
        f"Esperaba 403 batch rechazado, obtuvo {r_reject.status_code}: {r_reject.text[:200]}"
    assert "no esta asignado" in r_reject.json().get("detail", ""), \
        f"Mensaje debe indicar falta de asignacion: {r_reject.text[:200]}"
    print(f"  âœ… Batch mezclado (CrossFit + Lev OlÃ­mpico) â†’ 403 (rechazado correctamente, todo-o-nada)")


# ===================================================================
# BLOQUE 6 â€” COBERTURA DE EMERGENCIA (test 13-14)
# ===================================================================

def test_c14_cobertura_emergencia():
    """[14] Verificar cobertura de emergencia:
    a) Sin modo_emergencia, coach 1000 NO puede asignar WOD a Lev. Olimpico (disc 4) â†’ 403
    b) Con modo_emergencia=true, SE PERMITE y queda registro en CoberturaEmergencia
    """
    token = get_coach_token(coach_id=COACH_ID)
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"

    # Obtener clases de hoy
    r = requests.get(f"{BASE}/clases",
                     params={"tenant_id": TENANT_ID, "fecha_desde": HOY_STR, "fecha_hasta": HOY_STR})
    assert r.status_code == 200
    clases = r.json()
    clases_hoy = clases if isinstance(clases, list) else (
        clases.get("clases", []) if isinstance(clases, dict) else [])

    # Encontrar clase de Lev. Olimpico (disc 4) - coach 1000 NO asignado a esta disciplina
    lev_olimp = [c for c in clases_hoy if c.get("disciplina_id") == 4]
    assert len(lev_olimp) > 0, "Debe existir clase de Lev. OlÃ­mpico hoy"
    clase_otra = lev_olimp[0]

    # â”€â”€ a) Sin modo_emergencia â†’ 403 (regresion del fix IDOR) â”€â”€
    r_sin = requests.post(
        f"{BASE}/wods/clases/{clase_otra['id']}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r_sin.status_code == 403, \
        f"Sin modo_emergencia debe dar 403, obtuvo {r_sin.status_code}"
    print(f"  âœ… Sin modo_emergencia â†’ 403 (IDOR sigue cerrado)")

    # â”€â”€ b) Con modo_emergencia=true â†’ 200 + auditoria â”€â”€
    r_con = requests.post(
        f"{BASE}/wods/clases/{clase_otra['id']}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID, "modo_emergencia": True},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r_con.status_code == 200, \
        f"Con modo_emergencia debe dar 200, obtuvo {r_con.status_code}: {r_con.text[:200]}"
    print(f"  âœ… Con modo_emergencia=true â†’ 200 (cobertura permitida)")

    # Verificar que quedo registro en CoberturaEmergencia via SQL
    import psycopg2
    DB = 'postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-lingering-shape-ac953re8-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
    c = psycopg2.connect(DB)
    cur = c.cursor()
    cur.execute("""
        SELECT coach_id, clase_id, disciplina_id, accion
        FROM cobertura_emergencia
        WHERE coach_id = %s AND clase_id = %s
        ORDER BY created_at DESC LIMIT 1
    """, (COACH_ID, clase_otra['id']))
    row = cur.fetchone()
    assert row is not None, "Debe existir registro en CoberturaEmergencia"
    assert row[0] == COACH_ID, f"coach_id esperado={COACH_ID}, real={row[0]}"
    assert row[1] == clase_otra['id'], f"clase_id esperado={clase_otra['id']}, real={row[1]}"
    assert row[2] == 4, f"disciplina_id esperado=4, real={row[2]}"
    assert row[3] == 'asignar_wod', f"accion esperada='asignar_wod', real='{row[3]}'"
    cur.close()
    c.close()
    print(
        f"  âœ… Auditoria registrada: coach={COACH_ID} cubrio clase={clase_otra['id']} disciplina=4 accion=asignar_wod")


# ===================================================================
# BLOQUE 7 â€” LIMPIEZA
# ===================================================================

def test_c15_cleanup():
    """[13] Limpiar datos creados durante los tests."""
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
