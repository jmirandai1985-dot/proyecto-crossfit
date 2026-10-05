"""
Supervisión B2 -> panel del coach: TOMAR / SOLTAR clase y horario recurrente.

QUÉ SE PRUEBA (integraciones reales contra la API del branch TEST):

  * `POST /clases/{id}/tomar?alcance=clase` deja `coach_id` + `asignacion_origen='coach'`
    (marca ✅) y acepta sólo si la clase no es de otro coach;
  * tomar una clase que ya tiene OTRO coach -> **409** con su nombre en el detalle;
  * tomar una clase pasada -> 409;
  * `alcance=horario` (recurrente): crea la vigencia en `horarios_coach` y hace
    backfill de las clases FUTURAS del horario (nunca pisa a otro coach -> 409);
  * **hook de generación**: una clase generada DESPUÉS hereda al coach vigente
    (`POST /horarios/generar-clases-dia` + `GET /clases`);
  * `POST /clases/{id}/soltar` (clase y horario) limpia coach + marca, cierra la
    vigencia y libera las clases futuras del horario;
  * `GET /clases` devuelve `marca`, `asignacion_origen` y `horario_coach_*`.

⚠️ INTEGRACIÓN (no unitario): requiere la API corriendo contra el branch TEST
(`conftest.BASE`) y BORRA lo que crea (clase de prueba + filas de `horarios_coach`).
NO se ejecuta en la validación local (esa va con `--noconftest`): se deja escrito
para correrlo cuando el stack esté levantado.
"""
from datetime import date, timedelta

import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID

HOY = date.today()


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _all(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).fetchall()


def _exec(sql, **params):
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _token(row, rol):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": row.id,
        "tenant_id": row.tenant_id,
        "rol": rol,
        "correo": row.correo,
    })}


def _coach_activo():
    return _one(
        "SELECT id, tenant_id, correo, nombre FROM usuarios "
        "WHERE tenant_id = :t AND rol::text = 'coach' AND estado = 'activo' "
        "ORDER BY id LIMIT 1", t=TENANT_ID)


def _admin_activo():
    return _one(
        "SELECT id, tenant_id, correo, nombre FROM usuarios "
        "WHERE tenant_id = :t AND rol::text IN ('administrador', 'admin') "
        "AND estado = 'activo' ORDER BY id LIMIT 1", t=TENANT_ID)


def _horario_con_coach(tenant_id=None):
    """Plantilla (tabla `horarios`) de una disciplina que requiere coach."""
    return _one(
        "SELECT h.id, h.disciplina_id, h.hora_inicio, h.hora_fin, h.cupo_maximo "
        "FROM horarios h JOIN disciplinas d ON d.id = h.disciplina_id "
        "WHERE h.tenant_id = :t AND h.activo = true AND d.activo = true "
        "AND d.requiere_coach = true ORDER BY h.id LIMIT 1", t=tenant_id or TENANT_ID)


def _crear_clase(fecha, horario):
    fila = _one(
        "INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, "
        "hora_inicio, hora_fin, cupo_maximo, cupo_original, asistentes_confirmados, "
        "cancelada) VALUES (:t, :h, :d, :f, :hi, :hf, :c, :c, 0, false) "
        "RETURNING id",
        t=TENANT_ID, h=horario.id, d=horario.disciplina_id, f=fecha,
        hi=horario.hora_inicio, hf=horario.hora_fin, c=horario.cupo_maximo)
    return fila.id


def _borrar_clase(clase_id):
    _exec("DELETE FROM clases WHERE id = :id", id=clase_id)


def _recoger_clases_futuras(horario_id):
    """clases futuras del horario (para restaurarlas después del test)."""
    return _all(
        "SELECT id, coach_id, asignacion_origen, asignada_por, asignada_en "
        "FROM clases WHERE tenant_id = :t AND horario_base_id = :h AND fecha >= :hoy",
        t=TENANT_ID, h=horario_id, hoy=HOY)


def _restaurar_clases(filas):
    for f in filas:
        _exec(
            "UPDATE clases SET coach_id = :c, asignacion_origen = :o, "
            "asignada_por = :p, asignada_en = :e WHERE id = :id",
            c=f.coach_id, o=f.asignacion_origen, p=f.asignada_por,
            e=f.asignada_en, id=f.id)


def _borrar_vigencias(horario_id):
    _exec("DELETE FROM horarios_coach WHERE tenant_id = :t AND horario_id = :h",
          t=TENANT_ID, h=horario_id)


def _clase_api(clase_id, headers):
    r = requests.get(f"{BASE}/clases/", params={"fecha_desde": str(HOY),
                                                "fecha_hasta": str(HOY + timedelta(days=30)),
                                                "limit": 200}, headers=headers)
    assert r.status_code == 200, r.text
    for c in r.json():
        if c["id"] == clase_id:
            return c
    raise AssertionError(f"La clase {clase_id} no vino en GET /clases")


# ── tomar una clase puntual ────────────────────────────────────────────────

def test_tomar_clase_puntual_deja_la_marca_del_coach():
    coach = _coach_activo()
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=3), horario)
    headers = _token(coach, "coach")
    try:
        r = requests.post(f"{BASE}/clases/{clase_id}/tomar",
                          params={"alcance": "clase"}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["origen"] == "coach"
        assert r.json()["marca"] == "coach"

        en_bd = _one("SELECT coach_id, asignacion_origen, asignada_por "
                     "FROM clases WHERE id = :id", id=clase_id)
        assert en_bd.coach_id == coach.id
        assert en_bd.asignacion_origen == "coach"
        # Sin vigencia de horario: la toma fue puntual.
        assert _one("SELECT id FROM horarios_coach WHERE tenant_id = :t "
                    "AND horario_id = :h", t=TENANT_ID, h=horario.id) is None
    finally:
        _borrar_clase(clase_id)


def test_tomar_una_clase_de_otro_coach_da_409_con_su_nombre():
    coach = _coach_activo()
    otro = _one("SELECT id, nombre FROM usuarios WHERE tenant_id = :t "
                "AND rol::text = 'coach' AND id <> :c LIMIT 1",
                t=TENANT_ID, c=coach.id)
    if not otro:
        pytest.skip("Hace falta un segundo coach en TEST")
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=3), horario)
    _exec("UPDATE clases SET coach_id = :c WHERE id = :id", c=otro.id, id=clase_id)
    try:
        r = requests.post(f"{BASE}/clases/{clase_id}/tomar",
                          params={"alcance": "clase"}, headers=_token(coach, "coach"))
        assert r.status_code == 409, r.text
        assert otro.nombre in r.json()["detail"]
        assert _one("SELECT coach_id FROM clases WHERE id = :id",
                    id=clase_id).coach_id == otro.id
    finally:
        _borrar_clase(clase_id)


def test_no_se_puede_tomar_una_clase_pasada():
    coach = _coach_activo()
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY - timedelta(days=2), horario)
    try:
        r = requests.post(f"{BASE}/clases/{clase_id}/tomar",
                          params={"alcance": "clase"}, headers=_token(coach, "coach"))
        assert r.status_code == 409, r.text
        assert "ya pasó" in r.json()["detail"]
    finally:
        _borrar_clase(clase_id)


# ── tomar el horario recurrente ────────────────────────────────────────────

def test_tomar_horario_recurrente_hace_backfill_y_vigencia():
    coach = _coach_activo()
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=4), horario)
    previas = _recoger_clases_futuras(horario.id)
    headers = _token(coach, "coach")
    try:
        r = requests.post(f"{BASE}/clases/{clase_id}/tomar",
                          params={"alcance": "horario"}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["horario_coach_vigente"] is True
        assert r.json()["clases_tocadas"] >= 1

        vigencia = _one("SELECT coach_id, vigente_desde, vigente_hasta "
                        "FROM horarios_coach WHERE tenant_id = :t AND horario_id = :h "
                        "AND vigente_hasta IS NULL", t=TENANT_ID, h=horario.id)
        assert vigencia is not None and vigencia.coach_id == coach.id
        assert vigencia.vigente_desde == HOY

        # Backfill: las futuras del horario que estaban sin coach quedaron suyas.
        sin_coach = _one("SELECT COUNT(*) AS n FROM clases WHERE tenant_id = :t "
                         "AND horario_base_id = :h AND fecha >= :hoy "
                         "AND cancelada = false AND coach_id IS NULL",
                         t=TENANT_ID, h=horario.id, hoy=HOY)
        assert sin_coach.n == 0
        assert _clase_api(clase_id, headers)["marca"] == "coach"
    finally:
        _borrar_vigencias(horario.id)
        _borrar_clase(clase_id)
        _restaurar_clases(previas)


def test_tomar_un_horario_ocupado_da_409_con_el_nombre():
    coach = _coach_activo()
    otro = _one("SELECT id, nombre FROM usuarios WHERE tenant_id = :t "
                "AND rol::text = 'coach' AND id <> :c LIMIT 1",
                t=TENANT_ID, c=coach.id)
    if not otro:
        pytest.skip("Hace falta un segundo coach en TEST")
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=5), horario)
    hermana_id = _crear_clase(HOY + timedelta(days=12), horario)
    _exec("UPDATE clases SET coach_id = :c WHERE id = :id", c=otro.id, id=hermana_id)
    try:
        r = requests.post(f"{BASE}/clases/{clase_id}/tomar",
                          params={"alcance": "horario"}, headers=_token(coach, "coach"))
        assert r.status_code == 409, r.text
        assert otro.nombre in r.json()["detail"]
    finally:
        _borrar_clase(clase_id)
        _borrar_clase(hermana_id)


def test_la_clase_generada_despues_hereda_al_coach_vigente():
    admin = _admin_activo()
    coach = _coach_activo()
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=6), horario)
    previas = _recoger_clases_futuras(horario.id)
    try:
        requests.post(f"{BASE}/clases/{clase_id}/tomar",
                      params={"alcance": "horario"}, headers=_token(coach, "coach"))
        # El botón explícito de Admin (mismo servicio que startup y scheduler).
        r = requests.post(f"{BASE}/horarios/generar-clases-dia",
                          params={"fecha": str(HOY + timedelta(days=7))},
                          headers=_token(admin, "administrador"))
        assert r.status_code == 200, r.text

        nueva = _one("SELECT c.id, c.coach_id, c.asignacion_origen FROM clases c "
                     "WHERE c.tenant_id = :t AND c.horario_base_id = :h "
                     "AND c.fecha = :f", t=TENANT_ID, h=horario.id,
                     f=HOY + timedelta(days=7))
        if nueva is None:
            pytest.skip("Ese día de la semana no tiene clases para ese horario")
        assert nueva.coach_id == coach.id
        assert nueva.asignacion_origen == "coach"
        _borrar_clase(nueva.id)
    finally:
        _borrar_vigencias(horario.id)
        _borrar_clase(clase_id)
        _restaurar_clases(previas)


# ── soltar ─────────────────────────────────────────────────────────────────

def test_soltar_clase_y_horario():
    coach = _coach_activo()
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=8), horario)
    previas = _recoger_clases_futuras(horario.id)
    headers = _token(coach, "coach")
    try:
        requests.post(f"{BASE}/clases/{clase_id}/tomar",
                      params={"alcance": "horario"}, headers=headers)
        r = requests.post(f"{BASE}/clases/{clase_id}/soltar",
                          params={"alcance": "horario"}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["horario_cerrado"] is True
        assert r.json()["marca"] == "sin_coach"

        assert _one("SELECT coach_id FROM clases WHERE id = :id",
                    id=clase_id).coach_id is None
        assert _one("SELECT id FROM horarios_coach WHERE tenant_id = :t "
                    "AND horario_id = :h AND vigente_hasta IS NULL",
                    t=TENANT_ID, h=horario.id) is None
    finally:
        _borrar_vigencias(horario.id)
        _borrar_clase(clase_id)
        _restaurar_clases(previas)


def test_un_coach_no_puede_soltar_la_clase_de_otro():
    coach = _coach_activo()
    otro = _one("SELECT id FROM usuarios WHERE tenant_id = :t "
                "AND rol::text = 'coach' AND id <> :c LIMIT 1",
                t=TENANT_ID, c=coach.id)
    if not otro:
        pytest.skip("Hace falta un segundo coach en TEST")
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=9), horario)
    _exec("UPDATE clases SET coach_id = :c WHERE id = :id", c=otro.id, id=clase_id)
    try:
        r = requests.post(f"{BASE}/clases/{clase_id}/soltar",
                          params={"alcance": "clase"}, headers=_token(coach, "coach"))
        assert r.status_code == 403, r.text
        assert _one("SELECT coach_id FROM clases WHERE id = :id",
                    id=clase_id).coach_id == otro.id
    finally:
        _borrar_clase(clase_id)


# ── B3: asignación de emergencia del admin (🟦) + campana del coach ────────

def _avisos_de(usuario_id, tipo):
    return _all("SELECT id, tipo, mensaje, leida FROM notificaciones "
                "WHERE alumno_id = :u AND tipo = :t ORDER BY id DESC",
                u=usuario_id, t=tipo)


def _borrar_avisos(filas):
    for f in filas:
        _exec("DELETE FROM notificaciones WHERE id = :id", id=f.id)


def test_admin_asigna_clase_y_le_avisa_al_coach():
    admin = _admin_activo()
    coach = _coach_activo()
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=10), horario)
    try:
        r = requests.post(f"{BASE}/supervision/clases/{clase_id}/asignar",
                          json={"coach_id": coach.id, "motivo": "test"},
                          headers=_token(admin, "administrador"))
        assert r.status_code == 200, r.text
        assert r.json()["coach_id"] == coach.id
        assert r.json()["origen"] == "admin"
        assert r.json()["marca"] in ("admin", "emergencia")
        assert coach.id in r.json()["avisados"]

        en_bd = _one("SELECT coach_id, asignacion_origen, asignada_por "
                     "FROM clases WHERE id = :id", id=clase_id)
        assert en_bd.coach_id == coach.id
        assert en_bd.asignacion_origen == "admin"
        assert en_bd.asignada_por == admin.id

        avisos = _avisos_de(coach.id, "clase_asignada")
        assert avisos, "el coach no recibió el aviso en su campana"
        assert "clase" in avisos[0].mensaje
        assert avisos[0].leida is False
        _borrar_avisos(avisos)
    finally:
        _borrar_clase(clase_id)


def test_admin_reasigna_y_avisa_al_coach_nuevo_y_al_anterior():
    admin = _admin_activo()
    coach = _coach_activo()
    otro = _one("SELECT id, nombre FROM usuarios WHERE tenant_id = :t "
                "AND rol::text = 'coach' AND id <> :c LIMIT 1",
                t=TENANT_ID, c=coach.id)
    if not otro:
        pytest.skip("Hace falta un segundo coach en TEST")
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=11), horario)
    _exec("UPDATE clases SET coach_id = :c WHERE id = :id", c=otro.id, id=clase_id)
    try:
        r = requests.post(f"{BASE}/supervision/clases/{clase_id}/asignar",
                          json={"coach_id": coach.id},
                          headers=_token(admin, "administrador"))
        assert r.status_code == 200, r.text
        assert r.json()["coach_anterior_id"] == otro.id

        avisos_nuevo = _avisos_de(coach.id, "clase_asignada")
        avisos_anterior = _avisos_de(otro.id, "clase_reasignada")
        assert avisos_nuevo and avisos_anterior
        assert coach.nombre in avisos_anterior[0].mensaje
        _borrar_avisos(avisos_nuevo)
        _borrar_avisos(avisos_anterior)
    finally:
        _borrar_clase(clase_id)


def test_admin_quita_al_coach_y_le_avisa():
    admin = _admin_activo()
    coach = _coach_activo()
    horario = _horario_con_coach()
    clase_id = _crear_clase(HOY + timedelta(days=13), horario)
    _exec("UPDATE clases SET coach_id = :c, asignacion_origen = 'coach', "
          "asignada_por = :c WHERE id = :id", c=coach.id, id=clase_id)
    try:
        r = requests.delete(f"{BASE}/supervision/clases/{clase_id}/asignar",
                            headers=_token(admin, "administrador"))
        assert r.status_code == 200, r.text
        assert r.json()["marca"] == "sin_coach"
        assert r.json()["notificado"] is True

        en_bd = _one("SELECT coach_id, asignacion_origen FROM clases WHERE id = :id",
                     id=clase_id)
        assert en_bd.coach_id is None and en_bd.asignacion_origen is None
        avisos = _avisos_de(coach.id, "clase_liberada")
        assert avisos
        _borrar_avisos(avisos)
    finally:
        _borrar_clase(clase_id)


def test_asignar_un_coach_de_otra_disciplina_marca_emergencia():
    admin = _admin_activo()
    horario = _horario_con_coach()
    ajeno = _one(
        "SELECT u.id, u.nombre FROM usuarios u "
        "WHERE u.tenant_id = :t AND u.rol::text = 'coach' AND u.estado = 'activo' "
        "AND NOT EXISTS (SELECT 1 FROM coach_disciplinas cd WHERE cd.coach_id = u.id "
        "  AND cd.disciplina_id = :d AND cd.activo = true) "
        "ORDER BY u.id LIMIT 1", t=TENANT_ID, d=horario.disciplina_id)
    if not ajeno:
        pytest.skip("No hay un coach de otra disciplina en TEST")
    clase_id = _crear_clase(HOY + timedelta(days=14), horario)
    try:
        # Sin forzar: 409 (el admin tiene que confirmar la cobertura).
        r = requests.post(f"{BASE}/supervision/clases/{clase_id}/asignar",
                          json={"coach_id": ajeno.id, "forzar_emergencia": False},
                          headers=_token(admin, "administrador"))
        assert r.status_code == 409, r.text

        r = requests.post(f"{BASE}/supervision/clases/{clase_id}/asignar",
                          json={"coach_id": ajeno.id, "forzar_emergencia": True},
                          headers=_token(admin, "administrador"))
        assert r.status_code == 200, r.text
        assert r.json()["emergencia"] is True
        assert r.json()["marca"] == "emergencia"

        cobertura = _one("SELECT c.id FROM cobertura_emergencia c "
                         "WHERE c.clase_id = :id", id=clase_id)
        assert cobertura is not None
        _borrar_avisos(_avisos_de(ajeno.id, "clase_asignada"))
    finally:
        _exec("DELETE FROM cobertura_emergencia WHERE clase_id = :id", id=clase_id)
        _borrar_clase(clase_id)


