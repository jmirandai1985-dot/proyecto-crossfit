"""
Supervisión B1 -> `GET /supervision/grilla`: rango lunes-sábado + resumen.

QUÉ SE PRUEBA (integraciones reales contra la API del branch TEST):

  * el rango devuelve `dias` **sin domingos** y con `dia_semana` == `date.weekday()`
    (0=Lunes … 6=Domingo: el bug de "DOW" que corría la grilla un día);
  * `plantillas` sale de la tabla `horarios` (la real) y sólo de disciplinas
    `activo` + `requiere_coach=true` con horarios activos;
  * cada clase de `celdas` trae su `marca` (sin_coach / coach / admin / emergencia);
  * `resumen` cuadra con las celdas (total = con_coach + sin_coach, etc.);
  * validaciones: `desde > hasta` → 400, rango > 62 días → 400 y un rango de sólo
    domingos → 400.

⚠️ INTEGRACIÓN (no unitario): requiere la API corriendo contra el branch TEST
(`conftest.BASE`). Sólo LEE (no crea ni modifica nada).
NO se ejecuta en la validación local (esa va con `--noconftest`).
"""
from datetime import date, timedelta

import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from app.services.asignaciones_clases import MARCAS_VALIDAS
from app.utils.semana import lunes_de, sabado_de_semana
from tests.conftest import BASE, TENANT_ID

HOY = date.today()
LUNES = lunes_de(HOY)
DOMINGO = sabado_de_semana(HOY) + timedelta(days=1)


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _all(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).fetchall()


def _admin_activo():
    return _one(
        "SELECT id, tenant_id, correo, nombre FROM usuarios "
        "WHERE tenant_id = :t AND rol::text IN ('administrador', 'admin') "
        "AND estado = 'activo' ORDER BY id LIMIT 1", t=TENANT_ID)


def _headers_admin():
    admin = _admin_activo()
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": admin.id,
        "tenant_id": admin.tenant_id,
        "rol": "administrador",
        "correo": admin.correo,
    })}


def _grilla(desde, hasta, **extra):
    params = {"desde": str(desde), "hasta": str(hasta)}
    params.update(extra)
    return requests.get(f"{BASE}/supervision/grilla", params=params,
                        headers=_headers_admin())


def test_la_grilla_es_lunes_sabado_con_dia_semana_correcto():
    r = _grilla(LUNES, DOMINGO)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["desde"] == str(LUNES)
    assert data["hasta"] == str(DOMINGO)

    fechas = [d["fecha"] for d in data["dias"]]
    assert fechas == [str(LUNES + timedelta(days=i)) for i in range(6)]  # sin domingo
    for dia in data["dias"]:
        esperado = date.fromisoformat(dia["fecha"]).weekday()
        assert dia["dia_semana"] == esperado
        assert dia["dia_semana"] != 6, "un domingo no debería aparecer en la grilla"
        assert dia["nombre_dia"]  # Lunes..Sábado


def test_las_plantillas_son_de_la_tabla_horarios_y_requieren_coach():
    r = _grilla(LUNES, DOMINGO)
    assert r.status_code == 200, r.text
    plantillas = r.json()["plantillas"]
    assert plantillas, "el box de TEST debería tener plantillas de horario"

    de_bd = _all(
        "SELECT h.id FROM horarios h JOIN disciplinas d ON d.id = h.disciplina_id "
        "WHERE h.tenant_id = :t AND h.activo = true AND d.activo = true "
        "AND d.requiere_coach = true", t=TENANT_ID)
    ids_bd = {f.id for f in de_bd}
    assert {p["horario_id"] for p in plantillas} == ids_bd
    for p in plantillas:
        assert p["dia_semana"] in range(6)
        assert p["marca"] in MARCAS_VALIDAS


def test_las_celdas_traen_marca_y_el_resumen_cuadra():
    r = _grilla(LUNES, DOMINGO)
    assert r.status_code == 200, r.text
    data = r.json()

    total = 0
    con_coach = 0
    for celda in data["celdas"]:
        assert celda["dia_semana"] in range(6)
        for clase in celda["clases"]:
            total += 1
            assert clase["marca"] in MARCAS_VALIDAS
            if clase["coach_id"]:
                con_coach += 1
            if clase["marca"] == "emergencia":
                assert clase["cobertura_emergencia"] is True

    resumen = data["resumen"]
    assert resumen["total_clases"] == total
    assert resumen["con_coach"] == con_coach
    assert resumen["sin_coach"] == total - con_coach
    assert 0.0 <= resumen["cobertura_pct"] <= 100.0
    assert resumen["plantillas_activas"] == len(data["plantillas"])


def test_la_grilla_valida_el_rango():
    assert _grilla(LUNES, LUNES - timedelta(days=1)).status_code == 400
    assert _grilla(LUNES, LUNES + timedelta(days=90)).status_code == 400
    # Un rango de sólo domingos no tiene días hábiles.
    assert _grilla(DOMINGO, DOMINGO).status_code == 400
    # Un solo día hábil sí funciona.
    assert _grilla(LUNES, LUNES).status_code == 200
