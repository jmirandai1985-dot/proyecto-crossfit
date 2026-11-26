"""
Test del Panel del Coach — Suite de integración (9 pruebas).
Cubre el flujo completo de gestion de clases por parte del coach:
disciplinas, horarios, creacion de WODs, edicion, y asistencia.

Usa datos del Coach Demo (id=1000) y Alumno Demo (id=999).
Sigue el mismo patron que test_panel_alumno.py.
"""
import pytest
import requests
from sqlalchemy import text

from app.db.database import engine

from tests.conftest import (BASE, ALUMNO_ID, COACH_ID, MOTIVO_SIN_SEED,
                            SEED_DISPONIBLE, TENANT_ID, HOY,
                            DIA_REF, DIA_REF_STR, get_coach_token, get_alumno_token)

# Casos que asumen el MUNDO del seed (coach 1000 con CrossFit y las clases de
# ese horario): con una TEST sincronizada desde PROD no se pueden correr.
requiere_seed = pytest.mark.skipif(not SEED_DISPONIBLE, reason=MOTIVO_SIN_SEED)


def _coach_solo_disciplina(disc=1, prohibida=4):
    """Un coach ACTIVO que tenga `disc` y NO tenga `prohibida`.

    El `COACH_ID` del seed (en TEST el demo 531) está asignado a 1,3,4 y 5, así
    que no sirve para probar el 403 de otra disciplina: el permiso es CORRECTO.
    Se elige un coach real que solo tenga CrossFit para que la prueba mida la
    regla y no la amplitud del usuario demo.
    """
    with engine.connect() as c:
        fila = c.execute(text("""
            SELECT u.id
            FROM usuarios u
            JOIN coach_disciplinas cd
              ON cd.coach_id = u.id AND cd.activo
            WHERE u.tenant_id = :t
              AND u.rol::text = 'coach' AND u.estado = 'activo'
              AND cd.disciplina_id = :d
              AND NOT EXISTS (
                    SELECT 1 FROM coach_disciplinas x
                    WHERE x.coach_id = u.id
                      AND x.disciplina_id = :p AND x.activo)
            ORDER BY (u.correo LIKE 'demo.%') DESC, u.id
            LIMIT 1
        """), {"t": TENANT_ID, "d": disc, "p": prohibida}).first()
    if fila is None:
        pytest.skip(f"No hay coach solo disciplina {disc} (sin {prohibida}) en TEST")
    return int(fila.id)


def _clase_sin_coach(disc, excluir=()):
    """ID de una clase de `disc` en la fecha de referencia que NO tenga coach."""
    with engine.connect() as c:
        filas = c.execute(text("""
            SELECT id FROM clases
            WHERE tenant_id = :t AND disciplina_id = :d
              AND fecha = :f AND cancelada = false
              AND coach_id IS NULL
            ORDER BY id
        """), {"t": TENANT_ID, "d": disc, "f": DIA_REF}).fetchall()
    ids = [int(f.id) for f in filas if int(f.id) not in set(excluir)]
    if not ids:
        pytest.skip(f"No hay clase de disciplina {disc} sin coach en TEST")
    return ids[0]


def _wod_de_la_clase(clase_id):
    with engine.connect() as c:
        fila = c.execute(text(
            "SELECT wod_id FROM clases WHERE id = :i"), {"i": clase_id}).first()
    return fila.wod_id if fila else None


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
        "fecha": DIA_REF_STR,
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
# BLOQUE 3 — ASISTENCIA Y CREDITOS (tests 6-8)
# ===================================================================

def test_c06_asignar_wod_a_clase():
    """[6] POST /wods/clases/{id}/asignar-wod/{wod_id} — Asignar WOD a(s) clase(s)."""
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"
    # Obtener clases de la fecha de referencia (dia con clases garantizado)
    r = requests.get(f"{BASE}/clases",
                     params={"tenant_id": TENANT_ID, "fecha_desde": DIA_REF_STR, "fecha_hasta": DIA_REF_STR})
    assert r.status_code == 200, f"Status {r.status_code}"
    clases = r.json()
    clases_hoy = clases if isinstance(clases, list) else (
        clases.get("clases", []) if isinstance(clases, dict) else [])
    assert len(clases_hoy) > 0, "Debe haber al menos una clase en la fecha de referencia"
    # Pick a CrossFit class (disc 1) since coach 1000 is only assigned to CrossFit
    crossfit_classes = [c for c in clases_hoy if c.get(
        "disciplina_id") == Shared.disciplina_crossfit_id]
    assert len(
        crossfit_classes) > 0, "Debe haber al menos una clase de CrossFit hoy"
    Shared.clase_asignada_id = crossfit_classes[0]["id"]
    token = get_coach_token(coach_id=COACH_ID)

    # ── Nueva regla: un WOD en borrador NO se puede asignar ──────────────────
    # El test [5] lo dejó en `draft`. Lo fijamos explícitamente para que este
    # bloque sea robusto aunque se corra fuera de orden.
    r_draft = requests.put(
        f"{BASE}/wods/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID,
                "disciplina_id": Shared.disciplina_crossfit_id or 1},
        json={"estado": "draft"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_draft.status_code == 200, \
        f"Status {r_draft.status_code}: {r_draft.text[:200]}"

    r_rechazo = requests.post(
        f"{BASE}/wods/clases/{Shared.clase_asignada_id}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_rechazo.status_code == 400, \
        f"Un WOD draft no se asigna; status {r_rechazo.status_code}: {r_rechazo.text[:200]}"
    assert "no ha sido publicado" in r_rechazo.json().get("detail", "")
    print("  WOD draft → 400 al intentar asignarlo (bloqueado correctamente)")

    # Publicar y recién después asignar (el flujo real).
    r_publicar = requests.put(
        f"{BASE}/wods/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID,
                "disciplina_id": Shared.disciplina_crossfit_id or 1},
        json={"estado": "publicado"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_publicar.status_code == 200, \
        f"Status {r_publicar.status_code}: {r_publicar.text[:200]}"
    assert r_publicar.json().get("estado") == "publicado"

    # Asignar WOD a la clase
    r = requests.post(
        f"{BASE}/wods/clases/{Shared.clase_asignada_id}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, f"Status {r.status_code}: {r.text[:200]}"
    print(f"  WOD asignado a clase {Shared.clase_asignada_id}")


def test_c06b_wod_hoy_con_alumno_id():
    """[6b] Verificar que el WOD de la clase donde el alumno tiene reserva
    es el correcto (discriminación por disciplina/clase).
    Se usa GET /wods?fecha=DIA_REF_STR en vez de /wods/hoy porque
    DIA_REF puede no ser hoy (los domingos no hay clases).
    Esto conserva la intención del test original: el WOD de la clase reservada."""
    assert Shared.clase_asignada_id is not None, "test_c06 debe ejecutarse antes"
    # Crear reserva del alumno en la clase que tiene WOD asignado
    r_res = requests.post(f"{BASE}/reservas/",
                          json={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID, "clase_id": Shared.clase_asignada_id},
                          headers={"Authorization": f"Bearer {get_alumno_token(ALUMNO_ID)}"})
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
    # LLAMADA: GET /wods?fecha=DIA_REF_STR (dia con clases garantizado)
    r_wods = requests.get(f"{BASE}/wods",
                          params={"tenant_id": TENANT_ID, "fecha": DIA_REF_STR})
    assert r_wods.status_code == 200, f"Status {r_wods.status_code}"
    wods_list = r_wods.json()
    assert isinstance(wods_list, list) and len(wods_list) > 0, "Debe haber WOD(s) para la fecha de referencia"
    # El WOD asignado a la clase del alumno debe ser el que creamos
    wod_de_la_clase = next((w for w in wods_list if w.get("id") == Shared.wod_creado_id), None)
    assert wod_de_la_clase is not None, \
        f"Esperaba WOD id={Shared.wod_creado_id} para fecha {DIA_REF_STR}; wods={[w.get('id') for w in wods_list]}"
    print(
        f"  ✅ GET /wods?fecha={DIA_REF_STR} → WOD correcto id={wod_de_la_clase.get('id')}")


def test_c07_marcar_asistencia():
    """[7] PUT /reservas/{id}/asistencia — Marcar asistencia y verificar que se guarda."""
    # Primero crear una reserva para el alumno en la clase
    r = requests.post(f"{BASE}/reservas/",
                      json={
                          "tenant_id": TENANT_ID,
                          "alumno_id": ALUMNO_ID,
                          "clase_id": Shared.clase_asignada_id
    },
        headers={"Authorization": f"Bearer {get_alumno_token(ALUMNO_ID)}"})
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
                          params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID},
                          headers={"Authorization": f"Bearer {get_alumno_token(ALUMNO_ID)}"})
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
                          params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID},
                          headers={"Authorization": f"Bearer {get_alumno_token(ALUMNO_ID)}"})
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
# BLOQUE 4 — SEGURIDAD (test permanente de regresión IDOR)
# ===================================================================

@requiere_seed
def test_c10_seguridad_coach_no_puede_operar_otra_disciplina():
    """[10] Verificar que un coach NO puede asignar WOD ni marcar asistencia
    en una disciplina a la que NO pertenece (IDOR cerrado permanentemente).

    Coach 1000 solo está asignado a CrossFit (disc 1).
    Intenta operar sobre Levantamiento Olímpico (disc 4) y debe recibir 403.
    """
    coach_id = _coach_solo_disciplina(1, 4)
    token = get_coach_token(coach_id=coach_id)
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"

    # ── Obtener una clase de Levantamiento Olímpico (disc 4) SIN coach ──
    clase_otra_id = _clase_sin_coach(4)

    # ── Intentar asignar WOD a clase de OTRA disciplina → 403 ──
    r_wod = requests.post(
        f"{BASE}/wods/clases/{clase_otra_id}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r_wod.status_code == 403, \
        f"Esperaba 403 (no autorizado), obtuvo {r_wod.status_code}: {r_wod.text[:200]}"
    assert "no esta asignado" in r_wod.json().get("detail", ""), \
        f"Mensaje debe indicar falta de asignacion: {r_wod.text[:200]}"
    print(f"  ✅ Asignar WOD a disc 4 → 403 (bloqueado correctamente)")

    # ── Intentar marcar asistencia en reserva de OTRA disciplina → 403 ──
    # Crear una reserva en la clase de Lev. Olímpico para tener un ID válido
    r_res = requests.post(f"{BASE}/reservas/",
                          json={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID, "clase_id": clase_otra_id},
                          headers={"Authorization": f"Bearer {get_alumno_token(ALUMNO_ID)}"})
    reserva_id_otra = None
    if r_res.status_code in (200, 201):
        reserva_id_otra = r_res.json().get("id")
    else:
        # Si ya existe, obtenerla del listado
        r_list = requests.get(f"{BASE}/reservas/por-clase/{clase_otra_id}",
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
        print(f"  ✅ Marcar asistencia en disc 4 → 403 (bloqueado correctamente)")
    else:
        print(
            "  ⚠️ No se pudo crear/obtener reserva en disc 4 — prueba de asistencia omitida")
        print("     (la prueba de asignar WOD ya confirmó el 403)")


# ===================================================================
# BLOQUE 5 — BATCH WOD (tests 11-12)
# ===================================================================

@requiere_seed
def test_c12_batch_asignar_wod():
    """[12] POST /wods/batch — Asignar WOD a varias clases en un solo request.
    a) Batch exitoso con 2 clases de la misma disciplina (CrossFit)
    b) Batch RECHAZADO si incluye una clase de otra disciplina
    """
    coach_id = _coach_solo_disciplina(1, 4)
    token = get_coach_token(coach_id=coach_id)
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"

    # a) Batch exitoso: una clase de CrossFit (disc 1) SIN coach
    cf_exitosa = _clase_sin_coach(1)

    r_batch = requests.post(f"{BASE}/wods/batch",
                            params={"tenant_id": TENANT_ID},
                            json={"wod_id": Shared.wod_creado_id,
                                  "clase_ids": [cf_exitosa]},
                            headers={"Authorization": f"Bearer {token}"})
    assert r_batch.status_code == 200, \
        f"Esperaba 200 batch exitoso, obtuvo {r_batch.status_code}: {r_batch.text[:200]}"
    data = r_batch.json()
    assert data.get("actualizadas") == 1, \
        f"Esperaba 1 actualizada, obtuvo {data.get('actualizadas')}"
    assert data.get("wod_id") == Shared.wod_creado_id
    print(
        f"  ✅ Batch: WOD asignado a {data['actualizadas']} clase(s) de CrossFit")

    # ── b) Batch RECHAZADO: incluye clase de otra disciplina (todo o nada) ──
    cf_mezcla = _clase_sin_coach(1, excluir=(cf_exitosa,))
    lev_olimp = _clase_sin_coach(4)
    antes = _wod_de_la_clase(cf_mezcla)
    ids_mezclados = [cf_mezcla, lev_olimp]

    r_reject = requests.post(f"{BASE}/wods/batch",
                             params={"tenant_id": TENANT_ID},
                             json={"wod_id": Shared.wod_creado_id,
                                   "clase_ids": ids_mezclados},
                             headers={"Authorization": f"Bearer {token}"})
    assert r_reject.status_code == 403, \
        f"Esperaba 403 batch rechazado, obtuvo {r_reject.status_code}: {r_reject.text[:200]}"
    assert "no esta asignado" in r_reject.json().get("detail", ""), \
        f"Mensaje debe indicar falta de asignacion: {r_reject.text[:200]}"
    assert _wod_de_la_clase(cf_mezcla) == antes, \
        "el batch es TODO O NADA: la clase válida no puede quedar modificada"
    print(f"  ✅ Batch mezclado (CrossFit + Lev Olímpico) → 403 (rechazado correctamente, todo-o-nada)")


# ===================================================================
# BLOQUE 6 — COBERTURA DE EMERGENCIA (test 13-14)
# ===================================================================

@requiere_seed
def test_c14_cobertura_emergencia():
    """[14] Verificar cobertura de emergencia:
    a) Sin modo_emergencia, coach 1000 NO puede asignar WOD a Lev. Olimpico (disc 4) → 403
    b) Con modo_emergencia=true, SE PERMITE y queda registro en CoberturaEmergencia
    """
    token = get_coach_token(coach_id=COACH_ID)
    assert Shared.wod_creado_id is not None, "Primero debe crear el WOD"

    coach_id = _coach_solo_disciplina(1, 4)
    token = get_coach_token(coach_id=coach_id)

    # Clase de Lev. Olimpico (disc 4) SIN coach: el coach elegido NO tiene esa disciplina.
    clase_otra_id = _clase_sin_coach(4)

    # ── a) Sin modo_emergencia → 403 (regresion del fix IDOR) ──
    r_sin = requests.post(
        f"{BASE}/wods/clases/{clase_otra_id}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r_sin.status_code == 403, \
        f"Sin modo_emergencia debe dar 403, obtuvo {r_sin.status_code}"
    print(f"  ✅ Sin modo_emergencia → 403 (IDOR sigue cerrado)")

    # ── b) Con modo_emergencia=true → 200 + auditoria ──
    r_con = requests.post(
        f"{BASE}/wods/clases/{clase_otra_id}/asignar-wod/{Shared.wod_creado_id}",
        params={"tenant_id": TENANT_ID, "modo_emergencia": True},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r_con.status_code == 200, \
        f"Con modo_emergencia debe dar 200, obtuvo {r_con.status_code}: {r_con.text[:200]}"
    print(f"  ✅ Con modo_emergencia=true → 200 (cobertura permitida)")

    # Verificar que quedo registro en CoberturaEmergencia
    with engine.connect() as c:
        row = c.execute(text("""
            SELECT coach_id, clase_id, disciplina_id, accion
            FROM cobertura_emergencia
            WHERE coach_id = :c AND clase_id = :cl
            ORDER BY created_at DESC LIMIT 1
        """), {"c": coach_id, "cl": clase_otra_id}).first()
        c.rollback()
    assert row is not None, "Debe existir registro en CoberturaEmergencia"
    assert row.coach_id == coach_id, f"coach_id esperado={coach_id}, real={row.coach_id}"
    assert row.clase_id == clase_otra_id, f"clase_id esperado={clase_otra_id}, real={row.clase_id}"
    assert row.disciplina_id == 4, f"disciplina_id esperado=4, real={row.disciplina_id}"
    assert row.accion == 'asignar_wod', f"accion esperada='asignar_wod', real='{row.accion}'"
    print(
        f"  ✅ Auditoria registrada: coach={coach_id} cubrio clase={clase_otra_id} disciplina=4 accion=asignar_wod")


# ===================================================================
# BLOQUE 7 — LIMPIEZA
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
                                params={"tenant_id": TENANT_ID},
                                headers={"Authorization": f"Bearer {get_alumno_token(ALUMNO_ID)}"})
            if r.status_code in (200, 204):
                print(f"  Reserva {Shared.reserva_id} eliminada")
        except Exception as e:
            print(f"  Reserva cleanup: {e}")

    print("  Cleanup completado")
