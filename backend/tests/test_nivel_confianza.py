"""D1 — confianza mínima para publicar nivel (decisión de negocio 2026-10-28).

QUÉ FIJA ESTE ARCHIVO
---------------------
`nivel_desde_mejores` publica el nivel de un eje **solo si ese eje tiene al menos
`NIVEL_MIN_MOVS_EJE` movimientos clasificables** (default 2). Con una sola marca el eje queda
"Sin datos", aunque la marca sea Elite: era lo que producía los falsos "Elite" de PROD (la
alumna 9 tenía 2 marcas de fuerza y 0 de gimnasia → badge global Elite).

También fija el resto del contrato que consume el frontend (D3):
  · `nivel_atleta` = MENOR de los ejes publicados (la regla que antes vivía en
    `frontend/src/utils/niveles.js`), "Sin datos" si ninguno publica;
  · `movs_fuerza` / `movs_gimnasia` = cuántos movimientos CLASIFICARON (no cuántos hay);
  · `nivel_confianza` = alta (los dos ejes publican) / media (los dos tienen evidencia pero a
    alguno le falta muestra) / baja (un solo eje con evidencia) / sin_datos;
  · el mínimo es configurable por parámetro (el default sale de `NIVEL_MIN_MOVS_EJE`).

Es PURO (sin DB, sin conftest):
    cd backend && py -3.12 -m pytest tests/test_nivel_confianza.py -q --noconftest
"""

BACK_SQUAT = "Back Squat (Sentadilla Trasera)"    # M: 0.8 / 1.5 / 2.0 / 2.5
FRONT_SQUAT = "Front Squat (Sentadilla Frontal)"  # M: 0.6 / 1.2 / 1.6 / 2.0
PULL_UPS = "Pull-ups (Dominadas)"                 # M: 1 / 10 / 20 / 30
T2B = "Toes to Bar (T2B)"                         # M: 0 / 10 / 20 / 30


def _dos_fuerza():
    # 200 kg (Elite) + 170 kg (Elite con 80 kg de peso corporal).
    return [(1, 200.0, BACK_SQUAT), (2, 170.0, FRONT_SQUAT)]


def _dos_gimnasia():
    return [(3, 10.0, PULL_UPS), (4, 15.0, T2B)]


def test_una_marca_por_eje_no_publica():
    from app.services.nivel_service import nivel_desde_mejores

    r = nivel_desde_mejores([(1, 200.0, BACK_SQUAT)], 80, "M")
    assert r["nivel_fuerza"] == "Sin datos"
    assert r["movs_fuerza"] == 1
    assert r["nivel_confianza"] == "baja"


def test_dos_marcas_por_eje_publican_y_confianza_alta():
    from app.services.nivel_service import nivel_desde_mejores

    r = nivel_desde_mejores(_dos_fuerza() + _dos_gimnasia(), 80, "M")
    assert r["nivel_fuerza"] == "Elite"
    assert r["nivel_gimnastico"] == "Intermedio"
    assert (r["movs_fuerza"], r["movs_gimnasia"]) == (2, 2)
    assert r["nivel_confianza"] == "alta"
    # nivel_atleta = MENOR de los publicados (Intermedio < Elite).
    assert r["nivel_atleta"] == "Intermedio"


def test_un_eje_con_evidencia_y_otro_sin_muestra_no_publica_ese_eje():
    from app.services.nivel_service import nivel_desde_mejores

    r = nivel_desde_mejores(_dos_fuerza() + [(3, 10.0, PULL_UPS)], 80, "M")
    assert r["nivel_fuerza"] == "Elite"
    assert r["nivel_gimnastico"] == "Sin datos"
    assert (r["movs_fuerza"], r["movs_gimnasia"]) == (2, 1)
    assert r["nivel_atleta"] == "Elite"
    # Los DOS ejes tienen alguna marca clasificable; a gimnasia le falta muestra -> media.
    assert r["nivel_confianza"] == "media"


def test_un_solo_eje_con_evidencia_es_confianza_baja():
    from app.services.nivel_service import nivel_desde_mejores

    r = nivel_desde_mejores(_dos_fuerza(), 80, "M")
    assert r["nivel_fuerza"] == "Elite"
    assert r["movs_gimnasia"] == 0
    assert r["nivel_confianza"] == "baja"


def test_dos_ejes_con_una_marca_cada_uno_es_confianza_media():
    from app.services.nivel_service import nivel_desde_mejores

    r = nivel_desde_mejores(
        [(1, 200.0, BACK_SQUAT), (3, 10.0, PULL_UPS)], 80, "M")
    assert r["nivel_fuerza"] == "Sin datos"
    assert r["nivel_gimnastico"] == "Sin datos"
    assert r["nivel_atleta"] == "Sin datos"
    assert r["nivel_confianza"] == "media"


def test_el_minimo_es_configurable_para_reproducir_el_comportamiento_viejo():
    from app.services.nivel_service import nivel_desde_mejores

    # Con min_movs_eje=1 una sola marca vuelve a publicar (escape hatch del box).
    r = nivel_desde_mejores([(1, 200.0, BACK_SQUAT)], 80, "M", min_movs_eje=1)
    assert r["nivel_fuerza"] == "Elite"
    assert r["min_movs_eje"] == 1
    assert r["nivel_confianza"] == "baja"


def test_el_minimo_nunca_es_cero():
    """Un mínimo 0 publicaría un eje vacío; el servicio lo eleva a 1."""
    from app.services.nivel_service import nivel_desde_mejores

    r = nivel_desde_mejores([], 80, "M", min_movs_eje=0)
    assert r["min_movs_eje"] == 1
    assert r["nivel_fuerza"] == "Sin datos"


def test_el_detalle_conserva_las_marcas_no_publicadas():
    """El eje no publica, pero el detalle sigue mostrando qué se cargó (la UI lo lista)."""
    from app.services.nivel_service import nivel_desde_mejores

    r = nivel_desde_mejores([(1, 200.0, BACK_SQUAT)], 80, "M")
    assert r["detalle_fuerza"] == [
        {"movimiento": BACK_SQUAT, "movimiento_id": 1, "nivel": "Elite"}]
