"""Permisos de /configuracion contra la API de TEST (integración) — ESCRITO, NO EJECUTADO.

⚠️ ESTE TEST ESCRIBE EN LA RAMA TEST: hace un PUT con el token de un admin real (crea o
actualiza la fila de `configuracion_negocio` de su box) y RESTAURA el estado al terminar
(borra la fila si no existía, devuelve los valores si existía, y borra la traza que el PUT
dejó en `auditoria` y el aviso `config_bancaria` de la campana). El guardia `_guardia_test`
corta todo si la API no es TEST (fail-closed, mismo criterio que `test_bi_mrr_vivo.py`).

⛔ NO se ejecutó todavía: activar este archivo es una decisión aparte (implica la migración
046 aplicada en TEST). Queda escrito para que la cobertura de permisos exista.

Qué verifica (hoy ningún test cubre los permisos de este endpoint):

  1. GET sin token -> 401 · token basura -> 401 (antes era 200 sin credencial: R1).
  2. GET con token de alumno y de coach -> 200 con el box del TOKEN, aunque el query diga
     `?tenant_id=3` (el parámetro se ignora; 3 = el otro box con usuarios en TEST).
  3. PUT: alumno -> 403 · coach -> 403 · admin -> 200 (sólo admin).
  4. El PUT del admin deja la fila en `auditoria` (`UPDATE` / `configuracion_negocio` con
     `detalle.antes` y `detalle.despues`) y un aviso `config_bancaria` por cada admin activo
     del box (I1).
  5. Validaciones (I2/M2/M3): cuenta con letras, RUT con el dígito verificador cambiado y
     una clave desconocida -> 422.
  6. Round-trip: lo que guardó el admin lo lee el alumno (es el dato que copia para
     transferir).

Correr (API de TEST en 8001 y migración 046 aplicada):
    ENVIRONMENT=test API_BASE=http://localhost:8001/api/v1 ^
      py -3.12 -m pytest tests/test_configuracion_permisos.py -q --noconftest

Verificación manual del rastro, después del test (debería quedar limpio):
    SELECT count(*) FROM configuracion_negocio WHERE tenant_id = 1;
    SELECT id, accion, entidad, usuario_id, detalle FROM auditoria
      WHERE entidad = 'configuracion_negocio' ORDER BY id DESC LIMIT 5;
"""
import os
import sys
from pathlib import Path

import pytest
import requests

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_test_db_url, settings                 # noqa: E402
from app.core.security import create_access_token                     # noqa: E402

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api/v1")
HOST = API_BASE.replace("/api/v1", "")
TENANT_ID = 1
# El "otro box" con usuarios REALES en TEST: el box 2 existe pero está vacío (0 usuarios),
# así que el aislamiento se prueba contra el 3 (tiene 1 admin activo). Si algún día se
# vacía, el test se salta con un mensaje claro en vez de mentir.
OTRO_TENANT_ID = 3
RUT_OK = "12345678-5"
RUT_DV_MALO = "12.345.678-9"
COLUMNAS = ("banco", "numero_cuenta", "tipo_cuenta", "rut",
            "email_comprobantes", "whatsapp")


@pytest.fixture(scope="module", autouse=True)
def _guardia_test():
    """Falla CERRADO: sin confirmación de que la API y la BD son TEST, no corre nada."""
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    try:
        r = requests.get(f"{HOST}/debug/db-url", timeout=5)
    except requests.RequestException as e:
        pytest.skip(f"API no disponible en {HOST}: {e}")
    if r.status_code != 200 or not r.json().get("is_safe"):
        pytest.fail(f"El API en {HOST} NO es TEST ({r.status_code}): {r.text[:150]}")


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (sólo para tokens y traza)."""
    from app.db.database import SessionLocal

    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def tokens(db):
    """Token de un ADMIN, un ALUMNO y un COACH reales del box TEST (activos)."""
    from sqlalchemy import text

    def _uno(rol):
        fila = db.execute(text(
            "SELECT id, correo FROM usuarios WHERE tenant_id = :t AND rol::text = :r "
            "AND estado = 'activo' ORDER BY id LIMIT 1"),
            {"t": TENANT_ID, "r": rol}).first()
        if fila is None:
            pytest.skip(f"TEST no tiene un usuario con rol {rol} activo")
        return create_access_token({
            "usuario_id": int(fila[0]), "tenant_id": TENANT_ID,
            "rol": rol, "correo": fila[1] or f"{rol}@test.com"})

    return {
        "admin": {"Authorization": f"Bearer {_uno('administrador')}"},
        "alumno": {"Authorization": f"Bearer {_uno('alumno')}"},
        "coach": {"Authorization": f"Bearer {_uno('coach')}"},
    }


@pytest.fixture
def fila_del_box(db):
    """Deja `configuracion_negocio` del box TEST como estaba (y sin la traza del test).

    Mismo criterio que el fixture de `test_email_marca_contacto.py`: se anota de dónde
    sale cada cosa y se borra SÓLO lo que creó este archivo.
    """
    from sqlalchemy import text

    def _snapshot():
        fila = db.execute(text(
            "SELECT banco, numero_cuenta, tipo_cuenta, rut, email_comprobantes, whatsapp "
            "FROM configuracion_negocio WHERE tenant_id = :t"), {"t": TENANT_ID}).first()
        return dict(zip(COLUMNAS, fila)) if fila else None

    def _max_id(tabla):
        return db.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {tabla}")).scalar()

    previo = _snapshot()
    notif_desde = _max_id("notificaciones")
    audit_desde = _max_id("auditoria")

    yield {"previo": previo}

    db.rollback()
    if previo is None:
        db.execute(text("DELETE FROM configuracion_negocio WHERE tenant_id = :t"),
                   {"t": TENANT_ID})
    else:
        sets = ", ".join(f"{c} = :{c}" for c in COLUMNAS)
        db.execute(text(f"UPDATE configuracion_negocio SET {sets} WHERE tenant_id = :t"),
                   {**previo, "t": TENANT_ID})
    db.execute(text("DELETE FROM notificaciones WHERE id > :i AND tipo = 'config_bancaria'"),
               {"i": notif_desde})
    db.execute(text("DELETE FROM auditoria WHERE id > :i "
                    "AND entidad = 'configuracion_negocio'"), {"i": audit_desde})
    db.commit()
    # ⚠️ `updated_at` / `updated_by` NO se restauran: son la marca del cambio que el test
    # hizo de verdad (y la fila se borra entera cuando no existía antes).


def _get(headers=None, tenant_id=None):
    url = f"{API_BASE}/configuracion"
    if tenant_id is not None:
        url += f"?tenant_id={tenant_id}"
    return requests.get(url, headers=headers or {}, timeout=10)


def _put(cuerpo, headers=None):
    return requests.put(f"{API_BASE}/configuracion", json=cuerpo,
                        headers=headers or {}, timeout=10)


# ── 1) R1: el GET ya no es público ──────────────────────────────────────────
def test_01_get_sin_token_es_401():
    assert _get().status_code == 401


def test_02_get_con_token_basura_es_401():
    r = _get({"Authorization": "Bearer basura"})

    assert r.status_code == 401


def test_03_get_con_token_de_alumno_y_coach_es_200_y_del_token(tokens):
    """El alumno y el coach leen los datos de SU box; el `tenant_id` del query se ignora."""
    for rol in ("alumno", "coach"):
        r = _get(tokens[rol], tenant_id=OTRO_TENANT_ID)

        assert r.status_code == 200, (rol, r.text)
        assert r.json()["tenant_id"] == TENANT_ID, f"{rol}: leyó otro box"
        assert set(r.json()) >= {"banco", "numero_cuenta", "tipo_cuenta", "rut",
                                 "email_comprobantes", "whatsapp", "configurado"}


# ── 2) PUT: sólo el admin del box ───────────────────────────────────────────
@pytest.mark.parametrize("rol", ["alumno", "coach"])
def test_04_put_de_alumno_o_coach_es_403(rol, tokens):
    r = _put({"banco": "No debería guardarse"}, tokens[rol])

    assert r.status_code == 403


def test_05_put_sin_token_es_401():
    assert _put({"banco": "x"}).status_code == 401


def test_06_put_del_admin_escribe_traza_y_avisa(tokens, db, fila_del_box):
    """I1: 200, fila en `auditoria` con antes/después y el aviso `config_bancaria`."""
    from sqlalchemy import text

    antes_notif = db.execute(text(
        "SELECT COALESCE(MAX(id), 0) FROM notificaciones")).scalar()
    datos = {"banco": "Banco de Prueba TEST", "numero_cuenta": "0012 3456 7890",
             "tipo_cuenta": "Corriente", "rut": RUT_OK,
             "email_comprobantes": "pagos@test.com", "whatsapp": "+56 9 1111 2222"}

    r = _put(datos, tokens["admin"])

    assert r.status_code == 200, r.text
    guardado = r.json()
    assert guardado["configurado"] is True
    assert guardado["numero_cuenta"] == "001234567890", "la cuenta se guarda sólo con dígitos"
    assert guardado["updated_by"] and guardado["updated_at"]

    auditoria = db.execute(text(
        "SELECT accion, entidad, usuario_id, detalle FROM auditoria "
        "WHERE entidad = 'configuracion_negocio' ORDER BY id DESC LIMIT 1")).first()
    assert auditoria is not None, "el PUT no dejó fila en auditoria"
    assert auditoria[0] == "UPDATE" and auditoria[1] == "configuracion_negocio"
    detalle = auditoria[3]
    assert set(detalle) == {"antes", "despues"}
    assert detalle["despues"]["banco"] == "Banco de Prueba TEST"

    avisos = db.execute(text(
        "SELECT tipo, alumno_id FROM notificaciones WHERE id > :i"), {"i": antes_notif}).all()
    admins = db.execute(text(
        "SELECT id FROM usuarios WHERE tenant_id = :t AND rol::text = 'administrador' "
        "AND estado = 'activo'"), {"t": TENANT_ID}).scalars().all()
    assert {a[0] for a in avisos} == {"config_bancaria"}, "el aviso no es config_bancaria"
    assert {a[1] for a in avisos} == {int(i) for i in admins}, "no avisó a todos los admins"


def test_07_lo_que_guarda_el_admin_lo_lee_el_alumno(tokens, fila_del_box):
    """Round-trip del dato que el alumno copia para transferir."""
    _put({"banco": "Banco de Prueba TEST", "numero_cuenta": "12345678",
          "tipo_cuenta": "Vista", "rut": RUT_OK}, tokens["admin"])

    r = _get(tokens["alumno"])

    assert r.status_code == 200
    assert r.json()["banco"] == "Banco de Prueba TEST"
    assert r.json()["numero_cuenta"] == "12345678"
    assert r.json()["rut"] == RUT_OK


# ── 3) Validaciones del PUT (I2/M2/M3) ──────────────────────────────────────
@pytest.mark.parametrize("caso,cuerpo", [
    ("cuenta con letras", {"numero_cuenta": "12a456"}),
    ("RUT con el DV cambiado", {"rut": RUT_DV_MALO}),
    ("tipo de cuenta inventado", {"tipo_cuenta": "Corriente GOLD"}),
    ("clave desconocida", {"otra_clave": 1}),
    ("email que no es email", {"email_comprobantes": "pagos arroba box.cl"}),
    ("sin body", None),
])
def test_08_un_dato_bancario_invalido_no_se_guarda(caso, cuerpo, tokens):
    if cuerpo is None:
        r = requests.put(f"{API_BASE}/configuracion", headers=tokens["admin"], timeout=10)
    else:
        r = _put(cuerpo, tokens["admin"])

    assert r.status_code == 422, f"{caso}: {r.status_code} {r.text[:200]}"


def test_09_un_token_de_otro_box_lee_su_propio_box(db):
    """El aislamiento no depende del query: con el token del OTRO box, el GET trae ese box."""
    from sqlalchemy import text

    otro = db.execute(text(
        "SELECT id, correo FROM usuarios WHERE tenant_id = :t AND estado = 'activo' "
        "ORDER BY id LIMIT 1"), {"t": OTRO_TENANT_ID}).first()
    if otro is None:
        pytest.skip(f"TEST no tiene usuarios activos en el box {OTRO_TENANT_ID}")
    token = create_access_token({"usuario_id": int(otro[0]),
                                 "tenant_id": OTRO_TENANT_ID,
                                 "rol": "administrador",
                                 "correo": otro[1] or "box3@test.com"})

    r = _get({"Authorization": f"Bearer {token}"}, tenant_id=TENANT_ID)

    assert r.status_code == 200
    assert r.json()["tenant_id"] == OTRO_TENANT_ID, "el query pudo cambiar el box"
    assert r.json()["tenant_id"] != TENANT_ID, "devolvió el box del QUERY y no el del token"
