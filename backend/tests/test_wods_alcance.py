"""
Test del ALCANCE al publicar un WOD (punto 2) — POST /wods/batch-create.

REPRODUCCIÓN (antes/después):
  ANTES: el coach entraba a "Publicar Entrenamiento" desde la tarjeta de UNA
  clase (ej. la de las 07:00) y el WOD quedaba vinculado a TODAS las clases de
  esa fecha + disciplina (8 clases de crossfit, de 07:00 a 21:00), no solo a la
  elegida. El frontend no tenía forma de elegir alcance porque el endpoint no lo
  aceptaba.
  DESPUÉS: el body acepta `clase_ids` (opcional) y el backend vincula SOLO esas
  clases, validadas contra el tenant del token + la fecha/disciplina de cada WOD.

Casos:
  a01 sin clase_ids      → día completo (retrocompatible = comportamiento viejo)
  a02 clase_ids=[1 id]   → SOLO esa clase (EL FIX); las demás quedan sin WOD
  a03 clase_ids=[]       → 400 (nunca "publicado en 0 clases" en silencio)
  a04 clase inexistente / de otro gimnasio → 404 y NO se escribe nada
  a05 clase de OTRA fecha → 400 y NO se escribe nada
  a06 multi-día con un día sin la clase elegida → rollback TOTAL
  a07 un alumno no puede publicar → 403
  a08 tenant_id del query se ignora (sale del token)

SEGURIDAD DE DATOS: este módulo NO borra ni recrea datos. Descubre días FUTUROS
con >=2 clases de la misma disciplina SIN WOD (así no toca el WOD real que ya
existe en la rama) y en el teardown borra los WODs que creó (la FK
clases.wod_id es ON DELETE SET NULL) y restaura el coach_id que el endpoint
auto-asigna a clases que lo tenían NULL.
"""
from datetime import date, timedelta

import pytest
import requests

from tests.conftest import BASE, TENANT_ID, HOY, get_alumno_token, create_access_token

# Personas REALES de la rama (se resuelven en el fixture: los datos clonados no
# tienen los ids demo 1000/1001/999 de run_setup_test_db.py).
H_PUBLICA = None    # headers de una persona con permiso para publicar WODs
H_ALUMNO = None     # headers de un alumno real
PERSONA = None      # (usuario_id, rol)


class Shared:
    grupos = []            # [{fecha, disciplina_id, clases:[...]}] con >=2 clases sin WOD
    clase_todas = {}       # id -> clase (todas las del rango escaneado)
    touched = {}           # clase_id -> coach_id original (para restaurar)
    wods_creados = []      # ids de WODs creados acá (para borrarlos)


def _db_ids(sql, params=None):
    """Ids reales leídos de la BD (solo ENVIRONMENT=test). [] si no se puede."""
    import os
    if (os.environ.get("ENVIRONMENT") or "").strip() != "test":
        print(f"  [aviso] ENVIRONMENT={os.environ.get('ENVIRONMENT')!r}: sin acceso a la BD")
        return []
    try:
        from sqlalchemy import text
        from app.db.database import SessionLocal
    except Exception as e:  # pragma: no cover
        print(f"  [aviso] no se pudo importar la BD: {type(e).__name__}: {e}")
        return []
    db = SessionLocal()
    try:
        return [r[0] for r in db.execute(text(sql), params or {}).all()]
    except Exception as e:  # pragma: no cover
        print(f"  [aviso] error consultando ids reales: {type(e).__name__}: {e}")
        return []
    finally:
        db.close()


def _headers(usuario_id, rol):
    tok = create_access_token({"usuario_id": usuario_id, "tenant_id": TENANT_ID,
                               "rol": rol, "correo": f"u{usuario_id}@test.com"})
    return {"Authorization": f"Bearer {tok}"}


def _token_valido(usuario_id, rol):
    """Devuelve headers si el usuario existe/está activo, si no None."""
    h = _headers(usuario_id, rol)
    try:
        r = requests.get(f"{BASE}/clases", params={"limit": 1}, headers=h, timeout=15)
    except requests.RequestException:
        return None
    return h if r.status_code == 200 else None


def _resolver_personas():
    """Elige una persona real que pueda publicar (administrador > coach) y un
    alumno real. Con los datos seedeados del suite caen los ids demo."""
    global H_PUBLICA, H_ALUMNO, PERSONA

    candidatos = [(uid, "administrador") for uid in _db_ids(
        "SELECT id FROM usuarios WHERE activo = true AND rol::text IN ('administrador','admin') ORDER BY id")]
    candidatos += [(1001, "administrador")]  # datos demo de run_tests.bat
    candidatos += [(uid, "coach") for uid in _db_ids(
        "SELECT id FROM usuarios WHERE activo = true AND rol::text = 'coach' ORDER BY id")]
    candidatos += [(1000, "coach")]
    for uid, rol in candidatos:
        h = _token_valido(uid, rol)
        if h:
            H_PUBLICA, PERSONA = h, (uid, rol)
            break
    if not H_PUBLICA:
        pytest.skip("No hay ningún administrador/coach activo en la rama para publicar")

    alumnos = _db_ids(
        "SELECT id FROM usuarios WHERE activo = true AND rol::text = 'alumno' ORDER BY id LIMIT 5")
    for uid in alumnos + [999]:  # 999 = alumno demo de run_tests.bat
        h = _token_valido(uid, "alumno")
        if h:
            H_ALUMNO = h
            break



def _clases(desde, hasta, disciplina_id=None, headers=None):
    params = {"fecha_desde": str(desde), "fecha_hasta": str(hasta), "limit": 500}
    if disciplina_id:
        params["disciplina_id"] = disciplina_id
    r = requests.get(f"{BASE}/clases", params=params,
                     headers=headers or H_PUBLICA, timeout=30)
    assert r.status_code == 200, f"GET /clases {r.status_code}: {r.text[:200]}"
    data = r.json()
    return data if isinstance(data, list) else data.get("clases", [])


def _clases_del_dia(fecha, disciplina_id=None):
    return {c["id"]: c for c in _clases(fecha, fecha, disciplina_id)}


def _wods_del_dia(fecha):
    r = requests.get(f"{BASE}/wods/", params={"fecha": str(fecha)},
                     headers=H_PUBLICA, timeout=30)
    assert r.status_code == 200, f"GET /wods {r.status_code}: {r.text[:200]}"
    return r.json() or []


def _payload(fecha, titulo):
    """WOD mínimo completo (los campos de texto libre que pide el panel Coach)."""
    return {
        "fecha": str(fecha),
        "titulo": titulo,
        "calentamiento": "TEST alcance: movilidad 5 min + activación",
        "fuerza_habilidad": "TEST alcance: Back squat 5x3 @ 70%",
        "wod_principal": "TEST alcance: 10-8-6 thrusters + pull-ups",
        "tipo_metcon": "FOR TIME",
        "estado": "publicado",
    }


def _publicar(fechas, disciplina_id, clase_ids=None, headers=None):
    """POST /wods/batch-create. `clase_ids` solo se manda si NO es None
    (así se prueba el contrato retrocompatible del endpoint)."""
    body = {
        "wods": [_payload(f, f"TEST alcance ({f})") for f in fechas],
    }
    if clase_ids is not None:
        body["clase_ids"] = clase_ids
    return requests.post(
        f"{BASE}/wods/batch-create",
        params={"disciplina_id": disciplina_id, "tenant_id": TENANT_ID},
        json=body,
        headers=headers or H_PUBLICA,
        timeout=60,
    )


def _recordar(clases):
    """Guarda el coach_id original de las clases que el test puede tocar."""
    for c in clases:
        Shared.touched.setdefault(c["id"], c.get("coach_id"))


def _restaurar_coach_ids():
    """Devuelve clases.coach_id a su valor original.

    El endpoint auto-asigna un coach a las clases que lo tienen NULL (misma
    regla que POST /wods/batch) y eso NO se deshace al borrar el WOD. Se
    restaura por SQL porque no existe endpoint para desvincular coach.
    Solo corre con ENVIRONMENT=test (conftest aborta si el server no es TEST).
    """
    import os
    if (os.environ.get("ENVIRONMENT") or "").strip() != "test":
        print("  [limpieza] ENVIRONMENT != test: NO se toca coach_id (usar run_tests.bat)")
        return
    try:
        from sqlalchemy import text
        from app.db.database import SessionLocal
    except Exception as e:  # pragma: no cover
        print(f"  [limpieza] sin acceso directo a la BD: {e}")
        return
    db = SessionLocal()
    try:
        for clase_id, coach_id in Shared.touched.items():
            db.execute(
                text("UPDATE clases SET coach_id = :coach WHERE id = :id "
                     "AND coach_id IS DISTINCT FROM :coach"),
                {"coach": coach_id, "id": clase_id},
            )
        db.commit()
    except Exception as e:  # pragma: no cover
        db.rollback()
        print(f"  [limpieza] error restaurando coach_id: {e}")
    finally:
        db.close()


@pytest.fixture(scope="module", autouse=True)
def datos_y_limpieza():
    """Descubre datos reales de la rama y garantiza la limpieza del módulo."""
    _resolver_personas()
    print(f"  [persona] usuario_id={PERSONA[0]} rol={PERSONA[1]}"
          f"{' · alumno ok' if H_ALUMNO else ' · SIN alumno (a07 se saltea)'}")
    desde = HOY + timedelta(days=1)
    hasta = HOY + timedelta(days=14)
    todas = _clases(desde, hasta)
    for c in todas:
        Shared.clase_todas[c["id"]] = c

    grupos = {}
    for c in todas:
        if c.get("wod_id"):
            continue  # nunca tocar clases que YA tienen WOD (ej. el WOD real de hoy)
        grupos.setdefault((str(c["fecha"]), c["disciplina_id"]), []).append(c)

    Shared.grupos = sorted(
        ({"fecha": f, "disciplina_id": d,
          "clases": sorted(cs, key=lambda x: str(x["hora_inicio"]))}
         for (f, d), cs in grupos.items() if len(cs) >= 2),
        key=lambda g: (g["fecha"], g["disciplina_id"]),
    )
    if len(Shared.grupos) < 2:
        pytest.skip(
            f"Faltan datos para probar el alcance: se necesitan 2 grupos "
            f"(fecha+disciplina) con >=2 clases sin WOD entre {desde} y {hasta} "
            f"(encontrados: {len(Shared.grupos)})")

    for g in Shared.grupos:
        _recordar(g["clases"])   # cualquier grupo puede quedar tocado por los tests
    print(f"\n  [datos] grupo A: {Shared.grupos[0]['fecha']} disc "
          f"{Shared.grupos[0]['disciplina_id']} ({len(Shared.grupos[0]['clases'])} clases) · "
          f"grupo B: {Shared.grupos[1]['fecha']} disc {Shared.grupos[1]['disciplina_id']} "
          f"({len(Shared.grupos[1]['clases'])} clases)")

    yield

    # ── LIMPIEZA ────────────────────────────────────────────────────────────
    for wod_id in Shared.wods_creados:
        r = requests.delete(f"{BASE}/wods/{wod_id}", headers=H_PUBLICA, timeout=30)
        print(f"  [limpieza] DELETE /wods/{wod_id} -> {r.status_code}")
    _restaurar_coach_ids()
    print(f"  [limpieza] {len(Shared.wods_creados)} WOD(s) de prueba borrados · "
          f"{len(Shared.touched)} clase(s) revisadas para restaurar coach_id")



# ===================================================================
# CASOS DE ALCANCE
# ===================================================================

def test_a01_sin_clase_ids_publica_en_todo_el_dia():
    """[a01] Retrocompatible: SIN clase_ids el WOD va a TODAS las clases de esa
    fecha + disciplina. Es el comportamiento viejo (el que causaba el bug cuando
    el coach solo quería una hora) y debe seguir funcionando igual."""
    g = Shared.grupos[1]
    r = _publicar([g["fecha"]], g["disciplina_id"])
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    data = r.json()
    assert data["alcance"] == "dia_completo", f"alcance={data.get('alcance')}"
    assert data["clases_vinculadas"] == len(g["clases"]), \
        f"esperaba {len(g['clases'])} clases y vinculó {data['clases_vinculadas']}"
    wod_id = data["wods"][0]["wod"]["id"]
    Shared.wods_creados.append(wod_id)

    del_dia = _clases_del_dia(g["fecha"], g["disciplina_id"])
    sin_wod = [c["id"] for c in g["clases"] if del_dia[c["id"]]["wod_id"] != wod_id]
    assert sin_wod == [], f"estas clases del día no recibieron el WOD: {sin_wod}"
    print(f"  {g['fecha']} disc {g['disciplina_id']}: {data['clases_vinculadas']} clases "
          f"vinculadas al WOD {wod_id} (todo el día)")


def test_a02_con_clase_ids_publica_solo_en_esa_hora():
    """[a02] EL FIX: con clase_ids=[X] SOLO X recibe el WOD.
    Antes, publicar desde la tarjeta de una clase vinculaba todas las del día."""
    g = Shared.grupos[0]
    elegida, otras = g["clases"][0], g["clases"][1:]

    r = _publicar([g["fecha"]], g["disciplina_id"], clase_ids=[elegida["id"]])
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    data = r.json()
    assert data["alcance"] == "seleccion", f"alcance={data.get('alcance')}"
    assert data["clases_vinculadas"] == 1, \
        f"vinculó {data['clases_vinculadas']} clases: se esperaba 1"
    assert data["wods"][0]["clase_ids"] == [elegida["id"]], data["wods"][0]["clase_ids"]
    wod_id = data["wods"][0]["wod"]["id"]
    Shared.wods_creados.append(wod_id)

    del_dia = _clases_del_dia(g["fecha"], g["disciplina_id"])
    assert del_dia[elegida["id"]]["wod_id"] == wod_id, \
        f"la clase elegida ({elegida['id']}) no quedó vinculada"
    intrusas = [c["id"] for c in otras if del_dia[c["id"]]["wod_id"] is not None]
    assert intrusas == [], f"BUG: el WOD se publicó también en {intrusas}"
    print(f"  {g['fecha']} {elegida['hora_inicio']}: 1 clase vinculada (la elegida) y "
          f"{len(otras)} clases del mismo día intactas")


def test_a03_clase_ids_vacio_da_400():
    """[a03] clase_ids=[] es ambiguo ("no publiques en ninguna"): 400 explícito,
    nunca un éxito silencioso con 0 clases."""
    g = Shared.grupos[0]
    antes = {w["id"] for w in _wods_del_dia(g["fecha"])}
    r = _publicar([g["fecha"]], g["disciplina_id"], clase_ids=[])
    assert r.status_code == 400, f"{r.status_code}: {r.text[:200]}"
    assert "vacía" in r.json().get("detail", ""), r.json().get("detail")
    assert {w["id"] for w in _wods_del_dia(g["fecha"])} == antes, "se creó un WOD pese al 400"


def test_a04_clase_inexistente_da_404_sin_escribir():
    """[a04] Una clase que no existe (o de otro gimnasio) no se vincula nunca."""
    g = Shared.grupos[0]
    antes = {w["id"] for w in _wods_del_dia(g["fecha"])}
    r = _publicar([g["fecha"]], g["disciplina_id"], clase_ids=[999999999])
    assert r.status_code == 404, f"{r.status_code}: {r.text[:200]}"
    assert "no encontrada" in r.json().get("detail", "").lower()
    assert {w["id"] for w in _wods_del_dia(g["fecha"])} == antes, "se creó un WOD pese al 404"


def test_a05_clase_de_otra_fecha_da_400_sin_escribir():
    """[a05] La clase elegida debe ser DE ESA FECHA: si es de otro día, 400 y no
    se escribe nada (el vínculo viejo era por disciplina + fecha del WOD, sin
    mirar qué clase eligió el coach)."""
    g = Shared.grupos[0]
    otra = next((c for c in Shared.clase_todas.values()
                 if str(c["fecha"]) != g["fecha"] and c["disciplina_id"] == g["disciplina_id"]), None)
    if not otra:
        pytest.skip("No hay una clase de la misma disciplina en otra fecha")
    antes = {w["id"] for w in _wods_del_dia(g["fecha"])}
    r = _publicar([g["fecha"]], g["disciplina_id"], clase_ids=[otra["id"]])
    assert r.status_code == 400, f"{r.status_code}: {r.text[:200]}"
    detalle = r.json().get("detail", "")
    assert "no se publicó nada" in detalle, detalle
    assert {w["id"] for w in _wods_del_dia(g["fecha"])} == antes, "se creó un WOD pese al 400"
    print(f"  clase {otra['id']} es del {otra['fecha']} y el WOD del {g['fecha']}: "
          f"rechazado sin escribir nada")


def test_a06_multidia_atomico_rollback():
    """[a06] Multi-día atómico: si el 2º día no tiene ninguna de las clases
    elegidas, el WOD ya creado para el 1º día también se revierte."""
    g_dia, g_otro = Shared.grupos[1], next(
        (g for g in Shared.grupos if g["fecha"] != Shared.grupos[1]["fecha"]), None)
    if g_otro is None:
        pytest.skip("Todos los grupos son de la misma fecha: no sirve para probar atomicidad")

    elegida = g_dia["clases"][0]
    antes_1 = {w["id"] for w in _wods_del_dia(g_dia["fecha"])}
    antes_2 = {w["id"] for w in _wods_del_dia(g_otro["fecha"])}
    # Estado previo de la clase elegida (puede tener un WOD de un test anterior):
    # lo que importa es que el 400 NO lo modifique.
    wod_antes = _clases_del_dia(g_dia["fecha"], g_dia["disciplina_id"])[elegida["id"]]["wod_id"]
    # Orden: 1º el día que SÍ tiene la clase elegida (se crea el WOD) y 2º el día
    # que NO la tiene (falla) → el WOD del 1º debe desaparecer.
    r = _publicar([g_dia["fecha"], g_otro["fecha"]], g_dia["disciplina_id"],
                  clase_ids=[elegida["id"]])
    assert r.status_code == 400, f"{r.status_code}: {r.text[:200]}"
    assert {w["id"] for w in _wods_del_dia(g_dia["fecha"])} == antes_1, \
        "el WOD del 1º día quedó guardado: la tanda NO fue atómica"
    assert {w["id"] for w in _wods_del_dia(g_otro["fecha"])} == antes_2
    assert _clases_del_dia(g_dia["fecha"], g_dia["disciplina_id"])[elegida["id"]]["wod_id"] == wod_antes, \
        "el vínculo de la clase elegida cambió pese al 400"
    print(f"  {g_dia['fecha']} + {g_otro['fecha']}: 2do dia invalido -> rollback total verificado")


def test_a07_alumno_no_puede_publicar():
    """[a07] Un alumno no tiene permiso para publicar WODs."""
    if not H_ALUMNO:
        pytest.skip("No se encontró un alumno activo en la rama")
    g = Shared.grupos[0]
    r = _publicar([g["fecha"]], g["disciplina_id"],
                  clase_ids=[g["clases"][0]["id"]], headers=H_ALUMNO)
    assert r.status_code == 403, f"{r.status_code}: {r.text[:200]}"


def test_a08_tenant_del_query_se_ignora():
    """[a08] tenant_id del query se ignora: el tenant sale del token. Si el
    endpoint confiara en el query, este request (tenant 999) fallaría."""
    g = Shared.grupos[0]
    elegida = g["clases"][-1]
    r = requests.post(
        f"{BASE}/wods/batch-create",
        params={"disciplina_id": g["disciplina_id"], "tenant_id": 999},
        json={"wods": [_payload(g["fecha"], "TEST alcance tenant")],
              "clase_ids": [elegida["id"]]},
        headers=H_PUBLICA,
        timeout=60,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    data = r.json()
    assert data["clases_vinculadas"] == 1, data
    wod_id = data["wods"][0]["wod"]["id"]
    Shared.wods_creados.append(wod_id)
    assert _clases_del_dia(g["fecha"], g["disciplina_id"])[elegida["id"]]["wod_id"] == wod_id

