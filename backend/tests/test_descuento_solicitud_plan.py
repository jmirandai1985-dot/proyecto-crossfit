"""El descuento de un beneficio aplicado a la solicitud de un plan (dinero, F2).

Qué cubre
---------
  * `POST /solicitudes/solicitar`: el descuento VIGENTE se aplica a la compra —el precio de lista
    queda como snapshot (P0-4) y la solicitud guarda el % y el precio final— y el beneficio pasa a
    `usado` (la conversión que mide la F4, UNA sola vez).
  * `GET /solicitudes/pendientes`: el admin ve el % aplicado y el precio final, no sólo la lista.
  * `PUT /solicitudes/{id}/aprobar`: el INGRESO es el precio FINAL (cobrar la lista sería cobrar el
    descuento que el box regaló).
  * `GET /alumnos/{id}/historial?seccion=beneficios`: la sección se anuncia y muestra el regalo.
  * `GET /beneficios/mios`: el alumno ve su % y hasta cuándo, y deja de verlo cuando lo usó.

Escribe y RESTAURA en la rama TEST (nunca PROD) y no manda correo real.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                                    # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.services import beneficios_service as svc                      # noqa: E402
from app.services import historial_alumno_service as historial          # noqa: E402
from app.utils.santiago import SANTIAGO                                 # noqa: E402

TENANT_ID = 1
PRECIO_LISTA = 40000
DESCUENTO_PCT = 25
CLASES_PLAN = 10
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=SANTIAGO)


@pytest.fixture(autouse=True)
def _sin_correo_real(monkeypatch):
    """NINGÚN test de este módulo manda correo de verdad.

    Aprobar una solicitud dispara el correo de confirmación del plan: con `EMAIL_MODO=real` (el
    default de `.env.test`) saldría por SMTP de verdad a una dirección inventada. Con `noop` queda
    registrado como `simulado` y el envío no sale (regla del proyecto: nada de correo real).
    """
    from app.services import email_service

    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin levantar servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def tokens(db):
    """Token de admin REAL del box + tokens para los alumnos del escenario."""
    fila = db.execute(text(
        "SELECT id FROM usuarios WHERE tenant_id = :t AND rol = 'administrador' "
        "AND estado = 'activo' ORDER BY id LIMIT 1"), {"t": TENANT_ID}).first()
    if fila is None:
        pytest.skip("TEST no tiene un administrador activo")

    def _token(usuario_id, rol, correo):
        return {"Authorization": "Bearer " + create_access_token({
            "usuario_id": usuario_id, "tenant_id": TENANT_ID, "rol": rol, "correo": correo})}

    return {
        "admin": _token(int(fila[0]), "administrador", "admin@test.com"),
        "alumno": _token,       # se completa por el escenario (necesita su id)
    }


@pytest.fixture
def escenario(db, tokens):
    """Un alumno temporal con un plan de PAGO (precio de lista conocido) y su token.

    El precio es fijo (40.000) para poder afirmar la aritmética del descuento sin depender de
    cómo esté configurado el box. Borra TODO lo que creó: solicitudes, suscripciones, la
    transacción del ingreso (si hubo aprobación), notificaciones, beneficios y el plan.
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alumno_id = plan_id = None
    try:
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                                  estado, created_at)
            VALUES (:t, :r, 'Alumno Descuento TEST', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"98{sufijo[-8:]}-4",
             "c": f"descuento.{sufijo}@test.local",
             "alta": datetime.combine(T0.date() - timedelta(days=90), T0.time(),
                                      tzinfo=SANTIAGO)}).scalar()
        plan_id = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, :cr, false, :p, 30, true, true) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Plan descuento TEST {sufijo}", "cr": CLASES_PLAN,
             "p": PRECIO_LISTA}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        raise

    yield {"db": db, "alumno_id": alumno_id, "plan_id": plan_id,
           "correo": f"descuento.{sufijo}@test.local",
           "token_alumno": tokens["alumno"](alumno_id, "alumno",
                                            f"descuento.{sufijo}@test.local")}

    # ── limpieza (siempre, aunque el test falle) ──
    db.rollback()
    try:
        db.execute(text("DELETE FROM transacciones_financieras WHERE descripcion LIKE :d"),
                   {"d": f"%(usuario #{alumno_id})%"})
        db.execute(text("DELETE FROM notificaciones WHERE alumno_id = :a"), {"a": alumno_id})
        db.execute(text("DELETE FROM solicitudes_planes WHERE alumno_id = :a"), {"a": alumno_id})
        db.execute(text("DELETE FROM beneficios WHERE alumno_id = :a"), {"a": alumno_id})
        db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"), {"a": alumno_id})
        if plan_id is not None:
            db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
        if alumno_id is not None:
            db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
        db.commit()
    except Exception as e:      # el borrado no debe tapar el fallo real del test
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de descuento: {e}")


def _solicitar(cliente, cabeceras, alumno_id, plan_id):
    """POST /solicitudes/solicitar como el alumno (el tenant sale del token)."""
    return cliente.post("/api/v1/solicitudes/solicitar",
                        json={"tenant_id": TENANT_ID, "alumno_id": alumno_id,
                              "plan_id": plan_id, "voucher_url": "test://voucher.png"},
                        headers=cabeceras)


def _dar_descuento(cliente, cabeceras, alumno_id, valor=DESCUENTO_PCT):
    """Da el descuento como lo hace el panel (sin avisar por correo)."""
    return cliente.post("/api/v1/beneficios",
                        json={"alumno_id": alumno_id, "tipo": svc.TIPO_DESCUENTO, "valor": valor},
                        headers=cabeceras)


def _fila_solicitud(db, solicitud_id):
    return db.execute(text(
        "SELECT id, estado, precio_clp_snapshot, descuento_pct, precio_final_clp, beneficio_id "
        "FROM solicitudes_planes WHERE id = :i"), {"i": solicitud_id}).first()


def _estado_beneficio(db, beneficio_id):
    return db.execute(text("SELECT estado::text FROM beneficios WHERE id = :i"),
                      {"i": beneficio_id}).scalar()


def _esperado_final():
    """El precio final del descuento (la MISMA aritmética del servicio, escrita con números)."""
    return PRECIO_LISTA - round(PRECIO_LISTA * DESCUENTO_PCT / 100)


# ══════════════════════════════════════════════════════════════════════════════
# A. La sección del historial (regla, sin datos)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_la_seccion_de_beneficios_se_anuncia_en_el_historial():
    """La F2 implementó la 6ª sección: ya no está reservada y el menú la trae."""
    secciones = historial.secciones_disponibles()

    assert "beneficios" in [s["id"] for s in secciones]
    assert all(s["disponible"] for s in secciones)
    assert historial.SECCIONES_RESERVADAS == (), \
        "una sección implementada no puede seguir reservada: no se anunciaría"


# ══════════════════════════════════════════════════════════════════════════════
# B. El descuento aplicado a la compra (contra TEST: escribe y RESTAURA)
# ══════════════════════════════════════════════════════════════════════════════
def test_b1_el_descuento_se_aplica_al_solicitar_y_el_beneficio_queda_usado(
        cliente, tokens, db, escenario):
    """El precio de lista se conserva, la solicitud guarda el final y el regalo se marca usado."""
    dado = _dar_descuento(cliente, tokens["admin"], escenario["alumno_id"])
    assert dado.status_code == 201, dado.text
    beneficio_id = dado.json()["beneficio"]["id"]

    # El alumno ve su descuento ANTES de comprar (su propia puerta).
    mios = cliente.get("/api/v1/beneficios/mios", headers=escenario["token_alumno"])
    assert mios.status_code == 200, mios.text
    assert mios.json()["descuento_pct"] == DESCUENTO_PCT
    assert mios.json()["descuento_hasta"], "el alumno tiene que saber hasta cuándo vale"

    # Y el precio final de SUS planes lo calcula el backend (la pantalla lo muestra, no lo calcula).
    con_precios = cliente.get("/api/v1/beneficios/mios",
                              params={"plan_ids": str(escenario["plan_id"])},
                              headers=escenario["token_alumno"]).json()
    desglose_plan = con_precios["precios"][str(escenario["plan_id"])]
    assert desglose_plan["precio_lista_clp"] == PRECIO_LISTA
    assert desglose_plan["descuento_clp"] == PRECIO_LISTA - _esperado_final()
    assert desglose_plan["precio_final_clp"] == _esperado_final()

    respuesta = _solicitar(cliente, escenario["token_alumno"], escenario["alumno_id"],
                           escenario["plan_id"])

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["descuento_pct"] == DESCUENTO_PCT
    assert cuerpo["precio_lista_clp"] == PRECIO_LISTA
    assert cuerpo["precio_final_clp"] == _esperado_final()
    assert cuerpo["beneficio_id"] == beneficio_id

    fila = _fila_solicitud(db, cuerpo["id"])
    assert fila.precio_clp_snapshot == PRECIO_LISTA, \
        "el snapshot del precio de lista no se pierde (P0-4)"
    assert fila.descuento_pct == DESCUENTO_PCT
    assert fila.precio_final_clp == _esperado_final()
    assert fila.beneficio_id == beneficio_id
    assert _estado_beneficio(db, beneficio_id) == "usado", \
        "usar el descuento es la conversión que mide la F4: ocurre una sola vez"

    # Y ya no lo ve vigente: no se le puede prometer un precio que no se va a aplicar.
    assert cliente.get("/api/v1/beneficios/mios",
                       headers=escenario["token_alumno"]).json()["descuento_pct"] is None


def test_b2_sin_beneficio_la_solicitud_no_lleva_descuento(cliente, db, escenario):
    """Control: sin regalo vivo la compra queda como siempre (lista = final, sin %)."""
    respuesta = _solicitar(cliente, escenario["token_alumno"], escenario["alumno_id"],
                           escenario["plan_id"])

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["descuento_pct"] is None and cuerpo["precio_final_clp"] is None
    fila = _fila_solicitud(db, cuerpo["id"])
    assert fila.precio_clp_snapshot == PRECIO_LISTA and fila.beneficio_id is None


def test_b3_los_pendientes_muestran_el_beneficio_aplicado(cliente, tokens, escenario):
    """El admin ve el % aplicado y el precio final (no sólo el precio de lista)."""
    _dar_descuento(cliente, tokens["admin"], escenario["alumno_id"])
    creada = _solicitar(cliente, escenario["token_alumno"], escenario["alumno_id"],
                        escenario["plan_id"]).json()

    pendientes = cliente.get("/api/v1/solicitudes/pendientes", headers=tokens["admin"]).json()

    mia = next(p for p in pendientes if p["id"] == creada["id"])
    assert mia["plan_precio"] == PRECIO_LISTA
    assert mia["descuento_pct"] == DESCUENTO_PCT
    assert mia["precio_final"] == _esperado_final()


def test_b4_la_aprobacion_cobra_el_precio_final(cliente, tokens, db, escenario):
    """El INGRESO es lo que el alumno paga: con descuento, el final (no la lista)."""
    _dar_descuento(cliente, tokens["admin"], escenario["alumno_id"])
    creada = _solicitar(cliente, escenario["token_alumno"], escenario["alumno_id"],
                        escenario["plan_id"]).json()

    aprobada = cliente.put(f"/api/v1/solicitudes/{creada['id']}/aprobar",
                           headers=tokens["admin"])

    assert aprobada.status_code == 200, aprobada.text
    monto = db.execute(text(
        "SELECT monto FROM transacciones_financieras WHERE descripcion LIKE :d ORDER BY id DESC"),
        {"d": f"%(usuario #{escenario['alumno_id']})%"}).scalar()
    assert monto == _esperado_final(), \
        "cobrar la lista sería cobrarle el descuento que el box le regaló"


def test_b5_el_descuento_no_se_usa_dos_veces(cliente, tokens, db, escenario):
    """Un regalo = una compra: el ciclo completo y la segunda solicitud sin descuento."""
    dado = _dar_descuento(cliente, tokens["admin"], escenario["alumno_id"])
    beneficio_id = dado.json()["beneficio"]["id"]
    primera = _solicitar(cliente, escenario["token_alumno"], escenario["alumno_id"],
                         escenario["plan_id"]).json()
    assert primera["descuento_pct"] == DESCUENTO_PCT
    cliente.put(f"/api/v1/solicitudes/{primera['id']}/aprobar", headers=tokens["admin"])

    # Se puede volver a pedir (la anterior ya no está pendiente) y ya NO lleva el descuento.
    segunda = _solicitar(cliente, escenario["token_alumno"], escenario["alumno_id"],
                         escenario["plan_id"])

    assert segunda.status_code == 201, segunda.text
    assert segunda.json()["descuento_pct"] is None
    assert segunda.json()["precio_final_clp"] is None
    assert _estado_beneficio(db, beneficio_id) == "usado"
    assert svc.vigente(db, escenario["alumno_id"], tipo=svc.TIPO_DESCUENTO) is None


def test_b6_el_historial_del_alumno_muestra_el_beneficio(cliente, tokens, escenario):
    """La 6ª sección del historial dejó de estar vacía: muestra el regalo y su estado real."""
    dado = _dar_descuento(cliente, tokens["admin"], escenario["alumno_id"])
    beneficio_id = dado.json()["beneficio"]["id"]

    respuesta = cliente.get(f"/api/v1/alumnos/{escenario['alumno_id']}/historial",
                            params={"seccion": "beneficios"}, headers=tokens["admin"])

    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()["datos"]
    assert datos["disponible"] is True and datos["motivo"] is None
    assert datos["totales"]["vigentes"] == 1
    item = next(i for i in datos["items"] if i["id"] == beneficio_id)
    assert item["estado"] == "vigente"
    assert item["unidad"] == "pct" and item["valor"] == DESCUENTO_PCT
    assert item["tipo_label"] == svc.etiqueta(svc.TIPO_DESCUENTO)
    assert item["avisado_por_correo"] is False, "este regalo se dio sin correo"

