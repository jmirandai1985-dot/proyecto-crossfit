"""
N-9 (auditoría panel Alumno, TAREA 5) — POST /reservas para el staff.

HALLAZGO: `POST /reservas` exigía `alumno_id == usuario_id` para TODOS los roles,
así que el box no podía reservar por un alumno (mostrador/llamada) aunque
`POST /pedidos` y `POST /solicitudes-planes` sí lo permitían con el patrón
"staff del mismo box".

CONTRATO QUE SE PRUEBA ACÁ:
  1. el ALUMNO sigue reservando SÓLO para sí mismo (403 si intenta por otro);
  2. el STAFF (coach/admin del box) reserva para un alumno DE SU BOX: 201, cupo
     y créditos se mueven igual que en el caso 1, y un segundo intento idéntico
     da 400 (mismo control de duplicados). La reserva "en nombre de" queda en la
     auditoría;
  3. el STAFF DE OTRO BOX recibe 403 y no toca cupo ni créditos (nada escrito).

Requiere: API corriendo contra el branch TEST. Todo lo que escribe (reservas,
aforo, créditos, auditoría y el usuario temporal del otro box) se RESTAURA al
terminar cada test.
"""
import uuid

import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from app.utils.santiago import hoy_santiago
from tests.conftest import BASE, TENANT_ID


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _exec(sql, **params):
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _headers(u, rol=None):
    token = create_access_token({
        "usuario_id": u.id,
        "tenant_id": u.tenant_id,
        "rol": rol or u.rol,
        "correo": u.correo,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def alumno():
    """Alumno del box 1 con membresía activa y créditos (el POST exige ambos)."""
    a = _one(
        "SELECT u.id, u.tenant_id, u.correo, u.rol::text AS rol, "
        "s.id AS suscripcion_id, s.creditos_disponibles "
        "FROM usuarios u JOIN suscripciones s ON s.usuario_id = u.id "
        "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' AND u.estado = 'activo' "
        "AND s.estado = 'activo' AND s.fecha_expiracion > now() "
        "AND coalesce(s.creditos_disponibles, 1) > 0 "
        "ORDER BY (u.correo LIKE '%test%') DESC, s.creditos_disponibles DESC, u.id LIMIT 1",
        t=TENANT_ID)
    if a is None:
        pytest.skip("TEST no tiene alumno con membresía activa y créditos")
    return a


@pytest.fixture(scope="module")
def clase(alumno):
    """Clase futura (hoy en Santiago) del box 1 con cupo libre y SIN reserva del
    alumno elegido (si no, el POST daría 400 por duplicado)."""
    c = _one(
        "SELECT id, cupo_maximo, asistentes_confirmados FROM clases "
        "WHERE tenant_id = :t AND fecha >= :h AND cancelada = false "
        "AND asistentes_confirmados < cupo_maximo "
        "AND NOT EXISTS (SELECT 1 FROM reservas r WHERE r.clase_id = clases.id "
        "                AND r.alumno_id = :a "
        "                AND lower(r.estado::text) NOT LIKE 'cancel%') "
        "ORDER BY fecha, hora_inicio LIMIT 1",
        t=TENANT_ID, h=hoy_santiago(), a=alumno.id)
    if c is None:
        pytest.skip("TEST no tiene clases futuras con cupo libre para ese alumno")
    return c


@pytest.fixture(scope="module")
def staff():
    """Un miembro del staff (coach/admin) del box 1."""
    s = _one(
        "SELECT id, tenant_id, correo, rol::text AS rol FROM usuarios "
        "WHERE tenant_id = :t AND rol::text != 'alumno' AND activo = true "
        "ORDER BY (rol::text = 'administrador') DESC, id LIMIT 1", t=TENANT_ID)
    if s is None:
        pytest.skip("TEST no tiene staff activo en el box 1")
    return s


@pytest.fixture(scope="module")
def staff_otro_box():
    """Usuario TEMPORAL de staff en otro box (se borra al terminar el módulo).

    Igual que en el test de N-3: el rut es varchar(12) en la BD, así que el
    sufijo se mantiene corto.
    """
    otro = _one("SELECT id FROM tenants WHERE id != :t ORDER BY id LIMIT 1", t=TENANT_ID)
    if otro is None:
        pytest.skip("TEST tiene un solo tenant: no se puede probar cross-tenant")

    sufijo = uuid.uuid4().hex[:8]
    with engine.begin() as c:
        fila = c.execute(text(
            "INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol) "
            "VALUES (:t, :rut, :nombre, :correo, :pwd, 'administrador') RETURNING id"),
            {"t": otro.id, "rut": f"N9-{sufijo}",
             "nombre": "Admin Otro Box TEST (N-9)",
             "correo": f"test.n9.{sufijo}@test.local", "pwd": "no-login-test"}
        ).first()
    try:
        yield _one("SELECT id, tenant_id, correo, rol::text AS rol FROM usuarios "
                   "WHERE id = :i", i=fila.id)
    finally:
        _exec("DELETE FROM usuarios WHERE id = :i", i=fila.id)
        _exec("DELETE FROM auditoria WHERE usuario_id = :i", i=fila.id)


def _reservar(headers, alumno_id, clase_id):
    return requests.post(f"{BASE}/reservas", headers=headers, timeout=30, json={
        "clase_id": clase_id,
        "alumno_id": alumno_id,
        "tenant_id": TENANT_ID,      # el servidor lo ignora: sale del token
        "estado": "cancelada",       # P0-2: el servidor lo fuerza a 'confirmada'
        "asistio": True,             # P0-2: el servidor lo fuerza a False
    })


def _estado_bd(alumno_id, clase_id, suscripcion_id):
    aforo = _one("SELECT asistentes_confirmados FROM clases WHERE id = :c", c=clase_id)
    creditos = _one("SELECT creditos_disponibles FROM suscripciones WHERE id = :s",
                    s=suscripcion_id)
    reserva = _one("SELECT id, estado, asistio, tokens_gastados FROM reservas "
                   "WHERE clase_id = :c AND alumno_id = :a", c=clase_id, a=alumno_id)
    return {"aforo": aforo.asistentes_confirmados if aforo else None,
            "creditos": creditos.creditos_disponibles if creditos else None,
            "reserva": reserva}


def _limpiar(clase_id, suscripcion_id, aforo_antes, credito_antes, reserva_id=None):
    """Deja clase/créditos/reservas como estaban (los datos son de la demo).

    Borra SÓLO la reserva que creó el test (por id) y su registro de auditoría:
    así nunca se toca una reserva preexistente del seed.
    """
    if reserva_id is not None:
        _exec("DELETE FROM reservas WHERE id = :i", i=reserva_id)
        _exec("DELETE FROM auditoria WHERE entidad = 'reserva' AND entidad_id = :i",
              i=reserva_id)
    _exec("UPDATE clases SET asistentes_confirmados = :n WHERE id = :c",
          n=aforo_antes, c=clase_id)
    _exec("UPDATE suscripciones SET creditos_disponibles = :n WHERE id = :s",
          n=credito_antes, s=suscripcion_id)


def test_res_01_el_alumno_reserva_para_si_mismo(alumno, clase):
    """Sin regresión: el camino del alumno sigue igual (201 + cupo + crédito)."""
    antes = _estado_bd(alumno.id, clase.id, alumno.suscripcion_id)
    reserva_id = None
    try:
        r = _reservar(_headers(alumno), alumno.id, clase.id)
        assert r.status_code == 201, f"{r.status_code}: {r.text[:200]}"
        reserva_id = r.json()["id"]

        despues = _estado_bd(alumno.id, clase.id, alumno.suscripcion_id)
        assert despues["aforo"] == antes["aforo"] + 1, "no se incrementó el aforo"
        assert despues["creditos"] == antes["creditos"] - 1, "no se descontó el crédito"
        # P0-2: el servidor fuerza estado/asistio (el body los mandaba invertidos).
        assert despues["reserva"].estado == "confirmada"
        assert despues["reserva"].asistio is False
        assert despues["reserva"].tokens_gastados == 1
    finally:
        _limpiar(clase.id, alumno.suscripcion_id, antes["aforo"], antes["creditos"],
                 reserva_id)
    assert _one("SELECT id FROM reservas WHERE id = :i",
                i=reserva_id or -1) is None, "la reserva del test quedó en la BD"


def test_res_02_el_staff_reserva_para_un_alumno_de_su_box(alumno, clase, staff):
    """N-9: coach/admin reservan para un alumno del MISMO box (mismas reglas)."""
    antes = _estado_bd(alumno.id, clase.id, alumno.suscripcion_id)
    reserva_id = None
    try:
        r = _reservar(_headers(staff), alumno.id, clase.id)
        assert r.status_code == 201, (
            f"el staff del box {staff.tenant_id} no pudo reservar para el alumno "
            f"{alumno.id}: {r.status_code} {r.text[:200]}")
        reserva_id = r.json()["id"]
        assert r.json()["alumno_id"] == alumno.id, "la reserva quedó para otro alumno"

        despues = _estado_bd(alumno.id, clase.id, alumno.suscripcion_id)
        assert despues["aforo"] == antes["aforo"] + 1, "no se incrementó el aforo"
        assert despues["creditos"] == antes["creditos"] - 1, (
            "el crédito no se descontó del alumno destino")
        assert despues["reserva"].estado == "confirmada"
        assert despues["reserva"].asistio is False

        # Mismo control de duplicados que en el camino del alumno.
        repetida = _reservar(_headers(staff), alumno.id, clase.id)
        assert repetida.status_code == 400, (
            f"se esperaba 400 por duplicado, dio {repetida.status_code}: "
            f"{repetida.text[:200]}")

        # Trazabilidad: la reserva "en nombre de" queda auditada por el staff.
        auditoria = _one(
            "SELECT accion, entidad, detalle FROM auditoria "
            "WHERE entidad = 'reserva' AND entidad_id = :i AND usuario_id = :u",
            i=reserva_id, u=staff.id)
        assert auditoria is not None, "no quedó registro de auditoría de la reserva del staff"
        assert auditoria.detalle.get("en_nombre_de") is True
        assert auditoria.detalle.get("alumno_id") == alumno.id
    finally:
        _limpiar(clase.id, alumno.suscripcion_id, antes["aforo"], antes["creditos"],
                 reserva_id)


def test_res_03_el_staff_de_otro_box_recibe_403(alumno, clase, staff_otro_box):
    """El caso del hallazgo: reservar para un alumno de OTRO box debe dar 403."""
    antes = _estado_bd(alumno.id, clase.id, alumno.suscripcion_id)

    r = _reservar(_headers(staff_otro_box), alumno.id, clase.id)
    assert r.status_code == 403, (
        f"el staff del box {staff_otro_box.tenant_id} pudo reservar para el alumno "
        f"{alumno.id} del box {TENANT_ID} ({r.status_code}: {r.text[:200]})")

    despues = _estado_bd(alumno.id, clase.id, alumno.suscripcion_id)
    assert despues["aforo"] == antes["aforo"], "el 403 dejó el aforo incrementado"
    assert despues["creditos"] == antes["creditos"], "el 403 consumió un crédito"
    assert despues["reserva"] == antes["reserva"], "el 403 modificó/creó la reserva"


def test_res_04_el_alumno_no_puede_reservar_para_otro(alumno, clase, staff):
    """Regresión del IDOR: el alumno sigue sin poder reservar por un tercero."""
    antes = _estado_bd(alumno.id, clase.id, alumno.suscripcion_id)

    r = _reservar(_headers(alumno), staff.id, clase.id)   # el 'alumno destino' es el staff
    assert r.status_code == 403, f"se esperaba 403, dio {r.status_code}: {r.text[:200]}"

    despues = _estado_bd(alumno.id, clase.id, alumno.suscripcion_id)
    assert despues["aforo"] == antes["aforo"] and despues["creditos"] == antes["creditos"]
    assert despues["reserva"] == antes["reserva"]

