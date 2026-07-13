"""
Test del Panel del Alumno - Suite completa en pytest (16 pruebas).
Reemplaza al script _test_panel_alumno_completo.py (que daba 41/41 checks).

Cada función test_* prueba un endpoint o flujo específico.
Usa datos del Alumno Demo (id=5) y marca datos creados como "TEST".

Requisito: La API debe estar corriendo en localhost:8000.
  uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
import pytest
import requests
import json
from datetime import date, timedelta

from tests.conftest import BASE, ALUMNO_ID, TENANT_ID, HOY, HOY_STR


# ── Estado compartido entre tests (se llena en orden) ──
class Shared:
    membresia = None      # respuesta de membresia-activa
    creditos_antes = None
    reserva_id = None
    creditos_post_reserva = None
    clase_a_reservar = None
    clases_7dias = None
    movimientos = None
    mov_fuerza_id = None
    mov_gimnastico_id = None
    mov_cardio_id = None
    mov_metabolico_id = None
    # Para limpieza al final
    rms_creados = []
    wod_creado_id = None


# ===================================================================
# BLOQUE 1 — DASHBOARD GENERAL (tests 1-6)
# ===================================================================

def test_health_check():
    """Verificar que la API esté viva antes de arrancar."""
    r = requests.get(f"{BASE.replace('/api/v1', '')}/health", timeout=15)
    assert r.status_code == 200, f"API no responde: {r.status_code}"


def test_01_dashboard_membresia():
    """[1] GET /planes/membresia-activa - Membresía activa del alumno."""
    r = requests.get(f"{BASE}/planes/membresia-activa",
                     params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert "activa" in data, "Falta campo 'activa'"
    Shared.membresia = data
    Shared.creditos_antes = data.get("clases_disponibles")
    if data.get("activa"):
        assert data.get("plan_nombre"), "Debe tener plan_nombre si está activa"
        assert data.get("dias_restantes",
                        0) >= 0, "dias_restantes debe ser >=0"


def test_02_dashboard_nivel_fuerza():
    """[2] GET /historial-rm/alumnos/{id}/nivel-fuerza - Nivel de fuerza."""
    r = requests.get(f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/nivel-fuerza",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert data.get("nivel") is not None, "Debe tener 'nivel'"
    top_rms = data.get("top_rms", [])
    assert isinstance(top_rms, list), "top_rms debe ser lista"
    assert len(top_rms) <= 3, f"top_rms tiene {len(top_rms)}, max 3 esperado"


def test_03_dashboard_nivel_gimnastico():
    """[3] GET /historial-rm/alumnos/{id}/nivel-gimnastico - Nivel gimnástico."""
    r = requests.get(f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/nivel-gimnastico",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert data.get("nivel") is not None, "Debe tener 'nivel'"
    top_rms = data.get("top_rms", [])
    assert isinstance(top_rms, list), "top_rms debe ser lista"


def test_04_dashboard_wod_hoy():
    """[4] GET /wods/hoy - WOD de hoy."""
    r = requests.get(f"{BASE}/wods/hoy", params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    # Puede ser un dict (un WOD) o una lista (varios WODs), ambos son válidos
    assert isinstance(data, (dict, list)
                      ), f"Tipo inesperado: {type(data).__name__}"


def test_05_dashboard_asistencia_mes():
    """[5] GET /reservas/asistencia-mes - Asistencia del mes."""
    r = requests.get(f"{BASE}/reservas/asistencia-mes",
                     params={"tenant_id": TENANT_ID, "usuario_id": ALUMNO_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    for key in ("total_reservas", "solo_futuras", "reservas_futuras"):
        assert key in data, f"Falta campo '{key}'"
    assert isinstance(data.get("reservas_futuras", 0), (int, list)), (
        f"reservas_futuras debe ser int o list, es {type(data.get('reservas_futuras')).__name__}"
    )


def test_06_dashboard_clases_7dias():
    """[6] GET /clases (7 días) - Clases disponibles en los próximos 7 días."""
    desde = HOY_STR
    hasta = str(HOY + timedelta(days=6))
    r = requests.get(f"{BASE}/clases",
                     params={"tenant_id": TENANT_ID, "fecha_desde": desde,
                             "fecha_hasta": hasta, "limit": 500})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    clases = data if isinstance(data, list) else data.get("clases", [])
    assert isinstance(clases, list), "Clases debe ser una lista"
    assert len(clases) > 0, "Debe haber al menos 1 clase en los próximos 7 días"
    Shared.clases_7dias = clases


# ===================================================================
# BLOQUE 2 — FLUJO DE RESERVA (tests 7-9)
# ===================================================================

def test_07_reserva_clase_futura():
    """[7] Reservar clase futura (>6h) y verificar descuento de crédito."""
    assert Shared.clases_7dias is not None, "Depende de test_06"
    # Buscar clase futura con cupo
    futuras = [c for c in Shared.clases_7dias
               if c.get("fecha", "") > HOY_STR
               and (c.get("cupo_maximo", 0) - c.get("asistentes_confirmados", 0)) > 0]
    if not futuras:
        pytest.skip("No hay clases futuras con cupo disponible")
    clase = futuras[0]
    Shared.clase_a_reservar = clase

    payload = {
        "tenant_id": TENANT_ID,
        "alumno_id": ALUMNO_ID,
        "clase_id": clase["id"],
        "estado": "confirmada",
    }
    r = requests.post(f"{BASE}/reservas", json=payload)
    assert r.status_code < 300, f"Status {r.status_code}: {r.text[:200]}"
    Shared.reserva_id = r.json().get("id")
    assert Shared.reserva_id is not None, "Debe devolver un id de reserva"

    # Verificar descuento de crédito
    if Shared.creditos_antes is not None:
        r2 = requests.get(f"{BASE}/planes/membresia-activa",
                          params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
        Shared.creditos_post_reserva = r2.json().get("clases_disponibles", 0)
        assert Shared.creditos_post_reserva < Shared.creditos_antes, (
            f"Crédito no se descontó: {Shared.creditos_antes} -> {Shared.creditos_post_reserva}"
        )


def test_08_cancelar_reserva_devuelve_credito():
    """[8] Cancelar reserva (>6h) y verificar devolución de crédito."""
    if Shared.reserva_id is None:
        pytest.skip(
            "No hay reserva que cancelar (probablemente no había clases futuras)")
    r = requests.delete(f"{BASE}/reservas/{Shared.reserva_id}",
                        params={"tenant_id": TENANT_ID})
    assert r.status_code < 300, f"Status {r.status_code}: {r.text[:200]}"

    # Verificar devolución de crédito
    r3 = requests.get(f"{BASE}/planes/membresia-activa",
                      params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
    creditos_final = r3.json().get("clases_disponibles", 0)
    creditos_post = Shared.creditos_post_reserva or Shared.creditos_antes or 0
    assert creditos_final >= creditos_post, (
        f"Crédito no devuelto: {creditos_post} -> {creditos_final}"
    )


def test_09_reserva_cancelacion_clase_hoy():
    """[9] Reservar y cancelar clase de HOY (<6h, puede no devolver)."""
    if Shared.clases_7dias is None:
        pytest.skip("No se obtuvieron clases en test_06")
    hoy_clases = [c for c in Shared.clases_7dias
                  if c.get("fecha", "") == HOY_STR
                  and (c.get("cupo_maximo", 0) - c.get("asistentes_confirmados", 0)) > 0]
    if not hoy_clases:
        pytest.skip("No hay clases de HOY con cupo")
    clase_hoy = hoy_clases[0]

    # Reservar
    payload = {
        "tenant_id": TENANT_ID,
        "alumno_id": ALUMNO_ID,
        "clase_id": clase_hoy["id"],
        "estado": "confirmada",
    }
    r = requests.post(f"{BASE}/reservas", json=payload)
    if r.status_code >= 300:
        pytest.skip(f"No se pudo reservar clase hoy: status {r.status_code}")
    reserva_hoy_id = r.json().get("id")
    assert reserva_hoy_id is not None

    # Obtener crédito antes de cancelar
    r_cred = requests.get(f"{BASE}/planes/membresia-activa",
                          params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
    cred_antes = r_cred.json().get("clases_disponibles", 0)

    # Cancelar (como es HOY, si faltan <6h NO devuelve crédito)
    r = requests.delete(f"{BASE}/reservas/{reserva_hoy_id}",
                        params={"tenant_id": TENANT_ID})
    assert r.status_code < 300, f"Cancelación falló: status {r.status_code}"

    r_cred2 = requests.get(f"{BASE}/planes/membresia-activa",
                           params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
    cred_desp = r_cred2.json().get("clases_disponibles", 0)
    # No hacemos assert sobre si devuelve o no, porque depende de la hora
    # Solo verificamos que la operación completa fue exitosa


# ===================================================================
# BLOQUE 3 — RMs TODAS LAS CATEGORIAS (tests 10-13)
# ===================================================================

def _obtener_movimientos():
    """Carga los movimientos si no están cargados."""
    if Shared.movimientos is None:
        r = requests.get(f"{BASE}/movimientos",
                         params={"tenant_id": TENANT_ID})
        assert r.status_code == 200, f"Status {r.status_code}"
        Shared.movimientos = r.json()
    return Shared.movimientos


def test_10_rm_fuerza():
    """[10] POST /historial-rm - Crear RM de fuerza."""
    movs = _obtener_movimientos()
    fuerza = [m for m in movs if m.get("categoria") == "fuerza"]
    if not fuerza:
        pytest.skip("No hay movimientos de fuerza")
    mov = fuerza[0]
    Shared.mov_fuerza_id = mov["id"]

    payload = {"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID,
               "movimiento_id": mov["id"], "peso_kg": 50, "repeticiones": 5,
               "series": 3, "fecha": HOY_STR, "notas": "TEST fuerza"}
    r = requests.post(f"{BASE}/historial-rm", json=payload)
    assert r.status_code < 300, f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data.get(
        "peso_kg") == 50, f"peso_kg esperado=50, real={data.get('peso_kg')}"
    assert data.get(
        "repeticiones") == 5, f"repeticiones esperado=5, real={data.get('repeticiones')}"
    if data.get("id"):
        Shared.rms_creados.append(data["id"])


def test_11_rm_gimnastico():
    """[11] POST /historial-rm - Crear RM gimnástico."""
    movs = _obtener_movimientos()
    gim = [m for m in movs if m.get("categoria") == "gimnastico"]
    if not gim:
        pytest.skip("No hay movimientos gimnásticos")
    mov = gim[0]
    Shared.mov_gimnastico_id = mov["id"]

    payload = {"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID,
               "movimiento_id": mov["id"], "peso_kg": 10, "repeticiones": 12,
               "series": 3, "fecha": HOY_STR, "notas": "TEST gimnastico"}
    r = requests.post(f"{BASE}/historial-rm", json=payload)
    assert r.status_code < 300, f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data.get(
        "repeticiones") == 12, f"repeticiones esperado=12, real={data.get('repeticiones')}"
    assert data.get(
        "series") == 3, f"series esperado=3, real={data.get('series')}"
    if data.get("id"):
        Shared.rms_creados.append(data["id"])


def test_12_rm_cardio():
    """[12] POST /historial-rm - Crear RM de cardio (ski NO incluido)."""
    movs = _obtener_movimientos()
    cardio = [m for m in movs if m.get("categoria") == "cardio"
              and "ski" not in m.get("nombre", "").lower()]
    if not cardio:
        pytest.skip("No hay movimientos cardio (sin ski)")
    mov = cardio[0]
    Shared.mov_cardio_id = mov["id"]

    payload = {"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID,
               "movimiento_id": mov["id"], "peso_kg": 1, "minutos": 2,
               "km": 0.4, "vueltas": 1, "fecha": HOY_STR, "notas": "TEST cardio"}
    r = requests.post(f"{BASE}/historial-rm", json=payload)
    assert r.status_code < 300, f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data.get(
        "minutos") == 2, f"minutos esperado=2, real={data.get('minutos')}"
    assert data.get("km") == 0.4, f"km esperado=0.4, real={data.get('km')}"
    assert data.get(
        "vueltas") == 1, f"vueltas esperado=1, real={data.get('vueltas')}"
    if data.get("id"):
        Shared.rms_creados.append(data["id"])


def test_13_rm_maquinas_y_pizarra():
    """[13] POST /historial-rm (metabólico) y verificar que aparece en Pizarra."""
    movs = _obtener_movimientos()
    meta = [m for m in movs if m.get("categoria") == "metabolico"]
    if not meta:
        pytest.skip("No hay movimientos metabólicos")
    mov = meta[0]
    Shared.mov_metabolico_id = mov["id"]

    # Crear RM metabólico
    payload = {"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID,
               "movimiento_id": mov["id"], "peso_kg": 1, "calorias": 300,
               "km": 3.5, "vueltas": 10, "fecha": HOY_STR,
               "notas": "TEST maquinas nuevo"}
    r = requests.post(f"{BASE}/historial-rm", json=payload)
    assert r.status_code < 300, f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data.get(
        "calorias") == 300, f"calorias esperado=300, real={data.get('calorias')}"
    if data.get("id"):
        Shared.rms_creados.append(data["id"])

    # Verificar en Pizarra (GET /historial-rm/alumnos/{id}/rms)
    r = requests.get(f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/rms",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    rms_list = r.json()
    rm_pizarra = [x for x in rms_list if x.get("movimiento_id") == mov["id"]]
    assert len(rm_pizarra) > 0, "El RM metabólico no aparece en la Pizarra"
    rm_mostrado = rm_pizarra[0]
    assert rm_mostrado.get("calorias") == 300, (
        f"Pizarra no muestra el RECIENTE (calorias=300): {rm_mostrado.get('calorias')}"
    )


# ===================================================================
# BLOQUE 4 — PLANES Y PERFIL (tests 14-15)
# ===================================================================

def test_14_planes_filtro_genero():
    """[14] GET /planes con filtro de género."""
    # Femenino
    r = requests.get(f"{BASE}/planes",
                     params={"tenant_id": TENANT_ID, "genero": "femenino"})
    assert r.status_code == 200, f"Status {r.status_code}"
    planes_f = r.json()
    assert isinstance(planes_f, list), "Debe ser una lista"

    # Masculino
    r = requests.get(f"{BASE}/planes",
                     params={"tenant_id": TENANT_ID, "genero": "masculino"})
    assert r.status_code == 200, f"Status {r.status_code}"
    planes_m = r.json()
    assert isinstance(planes_m, list), "Debe ser una lista"

    # Todos
    r = requests.get(f"{BASE}/planes", params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    planes_todos = r.json()
    assert isinstance(planes_todos, list), "Debe ser una lista"

    # Sanity check: suma de filtrados no debería exceder el total (más de 1)
    assert len(planes_f) + len(planes_m) <= len(planes_todos) + 1, (
        f"femenino({len(planes_f)}) + masculino({len(planes_m)}) "
        f"> total({len(planes_todos)}) + 1"
    )


def test_15_actualizar_peso_alumno():
    """[15] PUT /usuarios/{id} - Actualizar peso y restaurar."""
    # Obtener usuario actual
    r = requests.get(f"{BASE}/usuarios/{ALUMNO_ID}",
                     params={"tenant_id": TENANT_ID})
    if r.status_code != 200:
        pytest.skip(f"No se pudo obtener usuario: status {r.status_code}")
    usuario = r.json()
    peso_original = usuario.get("peso_kg")

    # Actualizar peso
    nuevo_peso = (peso_original or 70) + 5
    r = requests.put(f"{BASE}/usuarios/{ALUMNO_ID}",
                     params={"tenant_id": TENANT_ID},
                     json={"peso_kg": nuevo_peso})
    assert r.status_code < 300, f"Status {r.status_code}: {r.text[:200]}"
    assert r.json().get("peso_kg") == nuevo_peso, (
        f"peso_kg no actualizado: esperado={nuevo_peso}, real={r.json().get('peso_kg')}"
    )

    # Recalcular nivel fuerza
    if Shared.mov_fuerza_id:
        r = requests.post(f"{BASE}/historial-rm/nivel-fuerza",
                          params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID,
                                  "movimiento_id": Shared.mov_fuerza_id, "peso_rm": 50})
        assert r.status_code in (200, 404), (
            f"nivel-fuerza endpoint inesperado: {r.status_code}"
        )

    # Restaurar peso original
    if peso_original is not None:
        requests.put(f"{BASE}/usuarios/{ALUMNO_ID}",
                     params={"tenant_id": TENANT_ID},
                     json={"peso_kg": peso_original})


# ===================================================================
# BLOQUE 5 — WOD (test 16)
# ===================================================================

def test_16_crear_wod_y_verificar_hoy():
    """[16] POST /wods/ y GET /wods/hoy - Crear WOD (v2 texto libre) y verificar."""
    payload = {
        "tenant_id": TENANT_ID,
        "fecha": HOY_STR,
        "titulo": "WOD Test v2 - borrar",
        "descripcion": "WOD creado por test (v2 texto libre)",
        "calentamiento": "Movilidad articular y activacion\n5 min de cardio ligero",
        "fuerza_habilidad": "Clean 5x3 @ 75%\nPush Press 3x5",
        "wod_principal": "AMRAP 12 minutos:\n10 Clean\n15 Box Jumps\n20 Burpees",
        "tipo_metcon": "AMRAP",
        "coach_id": 1000,
        "estado": "publicado"
    }
    r = requests.post(f"{BASE}/wods/", json=payload,
                      params={"tenant_id": TENANT_ID})
    assert r.status_code < 300, f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    wod_id = data.get("id")
    assert wod_id is not None, "Debe devolver id del WOD"
    # Verificar campos de texto libre
    assert data.get("calentamiento") == payload["calentamiento"], \
        f"calentamiento no coincide: {data.get('calentamiento')}"
    assert data.get("fuerza_habilidad") == payload["fuerza_habilidad"], \
        f"fuerza_habilidad no coincide: {data.get('fuerza_habilidad')}"
    assert data.get("wod_principal") == payload["wod_principal"], \
        f"wod_principal no coincide: {data.get('wod_principal')}"
    assert data.get("tipo_metcon") == payload["tipo_metcon"], \
        f"tipo_metcon no coincide: {data.get('tipo_metcon')}"
    Shared.wod_creado_id = wod_id

    # Verificar que aparece en /wods/hoy
    r = requests.get(f"{BASE}/wods/hoy", params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    wod_hoy = r.json()
    if isinstance(wod_hoy, dict):
        assert wod_hoy.get("id") == wod_id, (
            f"/wods/hoy no muestra el WOD: esperado id={wod_id}, real id={wod_hoy.get('id')}"
        )
        assert wod_hoy.get("calentamiento") == payload["calentamiento"]
        assert wod_hoy.get("tipo_metcon") == payload["tipo_metcon"]
    elif isinstance(wod_hoy, list):
        ids = [w.get("id") for w in wod_hoy]
        assert wod_id in ids, f"/wods/hoy no contiene el WOD (ids: {ids})"
    else:
        pytest.fail(
            f"Formato inesperado de /wods/hoy: {type(wod_hoy).__name__}")


# ===================================================================
# LIMPIEZA DE DATOS DE PRUEBA (no es un test, se ejecuta al final)
# ===================================================================

def test_cleanup():
    """Limpieza: elimina datos de prueba creados durante los tests."""
    # Eliminar WOD de prueba
    if Shared.wod_creado_id:
        try:
            requests.delete(f"{BASE}/wods/{Shared.wod_creado_id}",
                            params={"tenant_id": TENANT_ID})
        except Exception:
            pass

    # Eliminar RMs de prueba (se eliminan en orden inverso)
    for rm_id in reversed(Shared.rms_creados):
        try:
            requests.delete(f"{BASE}/historial-rm/{rm_id}",
                            params={"tenant_id": TENANT_ID})
        except Exception:
            pass

    # Si quedó alguna reserva sin cancelar, cancelarla
    if Shared.reserva_id:
        try:
            requests.delete(f"{BASE}/reservas/{Shared.reserva_id}",
                            params={"tenant_id": TENANT_ID})
        except Exception:
            pass
