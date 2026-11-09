"""API de Suspensión de plan: el POST que toca dinero/fechas de vencimiento.

Cubre el flujo self-service del alumno contra la app real (TestClient):
  * caso feliz: recalcula `fecha_expiracion`, cancela SÓLO las reservas del rango
    (estado nuevo `cancelada_por_suspension`) y deja intactas las de fuera;
  * créditos insuficientes -> 400;
  * menos de 10 días para vencer -> 400;
  * pedir más días que el saldo del ciclo -> 400 (defensa en profundidad).

REQUISITO PREVIO: la migración `073_suspensiones_plan` debe estar aplicada en la
rama TEST (la tabla `suspensiones_plan`), y el servidor/BD apuntando a TEST.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suspensiones_api.py -q
"""
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.security import create_access_token                    # noqa: E402
from app.utils.santiago import SANTIAGO, fin_del_dia_chile, hoy_santiago  # noqa: E402


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin levantar servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _insertar_alumno(db, tenant_id, correo, creado):
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, :nom, :c, 'x', 'alumno', true, 'activo', :alta)
        RETURNING id"""),
        {"t": tenant_id, "r": uuid.uuid4().hex[:10], "nom": f"Alumno Susp {correo}",
         "c": correo, "alta": creado}).scalar()


@pytest.fixture
def escenario(db):
    """Un box propio con alumno, plan, disciplina, clases y reservas.

    Crea todo desde cero (no depende de datos que ya estén en TEST) y lo borra al
    final. El alumno queda con un plan limitado de 20 créditos que vence en 30 días,
    y 3 reservas: dos DENTRO del rango de la suspensión y una FUERA.
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    hoy = hoy_santiago()
    creado = datetime.combine(hoy - timedelta(days=200), datetime.min.time(),
                              tzinfo=SANTIAGO)
    expiracion = fin_del_dia_chile(hoy + timedelta(days=30))
    fecha_inicio = hoy + timedelta(days=7)
    dias = 3

    ids = {"tenant": None, "alumno": None, "plan": None, "disc": None,
           "horario": None, "suscripcion": None, "clases": [], "reservas": []}
    try:
        ids["tenant"] = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, now()) RETURNING id"""),
            {"n": f"Box Susp TEST {sufijo}", "s": f"box-susp-{sufijo}",
             "pub": str(uuid.uuid4())}).scalar()
        t = ids["tenant"]
        ids["alumno"] = _insertar_alumno(db, t, f"susp.{sufijo}@test.local", creado)
        ids["disc"] = db.execute(text("""
            INSERT INTO disciplinas (tenant_id, nombre, activo)
            VALUES (:t, :n, true) RETURNING id"""),
            {"t": t, "n": f"CrossFit Susp {sufijo}"}).scalar()
        ids["horario"] = db.execute(text("""
            INSERT INTO horarios (tenant_id, disciplina_id, dia_semana, hora_inicio,
                                  hora_fin, activo)
            VALUES (:t, :d, 1, '19:00', '20:00', true) RETURNING id"""),
            {"t": t, "d": ids["disc"]}).scalar()
        ids["plan"] = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 20, false, 40000, 30, true, true) RETURNING id"""),
            {"t": t, "n": f"Plan Susp TEST {sufijo}"}).scalar()
        ids["suscripcion"] = db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, 'activo', 20, 20, now(), :exp) RETURNING id"""),
            {"t": t, "u": ids["alumno"], "p": ids["plan"], "exp": expiracion}).scalar()

        for dia, asistentes in ((fecha_inicio, 1), (fecha_inicio + timedelta(days=2), 1),
                                (fecha_inicio + timedelta(days=10), 0)):
            cid = db.execute(text("""
                INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha,
                                    hora_inicio, hora_fin, cupo_maximo,
                                    asistentes_confirmados, cancelada)
                VALUES (:t, :h, :d, :f, '19:00', '20:00', 20, :a, false) RETURNING id"""),
                {"t": t, "h": ids["horario"], "d": ids["disc"], "f": dia,
                 "a": asistentes}).scalar()
            ids["clases"].append(cid)
            rid = db.execute(text("""
                INSERT INTO reservas (tenant_id, clase_id, alumno_id, tokens_gastados,
                                      suscripcion_id, estado)
                VALUES (:t, :c, :a, 1, :s, 'reserved') RETURNING id"""),
                {"t": t, "c": cid, "a": ids["alumno"], "s": ids["suscripcion"]}).scalar()
            ids["reservas"].append(rid)
        db.commit()
    except Exception:
        db.rollback()
        raise

    token = {"Authorization": "Bearer " + create_access_token({
        "usuario_id": ids["alumno"], "tenant_id": t, "rol": "alumno",
        "correo": f"susp.{sufijo}@test.local"})}

    yield {"db": db, "ids": ids, "token": token, "hoy": hoy,
           "fecha_inicio": fecha_inicio, "dias": dias,
           "expiracion_original": expiracion}

    # ── limpieza (siempre, aunque el test falle) ──
    db.rollback()
    t = ids["tenant"]
    try:
        for tabla in ("reservas", "suspensiones_plan", "clases", "horarios",
                      "suscripciones", "usuarios", "disciplinas", "planes"):
            db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"), {"t": t})
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": t})
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de suspensiones: {e}")


def _estados(db, ids_reservas):
    filas = db.execute(text("SELECT id, estado FROM reservas WHERE id = ANY(:ids)"),
                       {"ids": ids_reservas}).all()
    return {f.id: f.estado for f in filas}


def test_caso_feliz(escenario, cliente):
    ids = escenario["ids"]
    resp = cliente.post(
        "/api/v1/alumnos/me/suspension",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "dias": escenario["dias"]},
        headers=escenario["token"],
    )
    assert resp.status_code == 201, resp.text
    datos = resp.json()
    assert datos["suspension"]["dias"] == 3
    assert datos["suspension"]["reservas_canceladas"] == 2
    assert len(datos["reservas_canceladas"]) == 2

    db = escenario["db"]
    db.expire_all()

    # fecha_expiracion += 3 días (misma fórmula para ambos tipos de plan).
    exp = db.execute(text("SELECT fecha_expiracion FROM suscripciones WHERE id = :i"),
                     {"i": ids["suscripcion"]}).scalar()
    assert exp == escenario["expiracion_original"] + timedelta(days=3)

    # Las dos reservas del rango quedaron con el estado NUEVO; la de fuera, intacta.
    estados = _estados(db, ids["reservas"])
    assert estados[ids["reservas"][0]] == "cancelada_por_suspension"
    assert estados[ids["reservas"][1]] == "cancelada_por_suspension"
    assert estados[ids["reservas"][2]] == "reserved"

    # El aforo de las clases del rango bajó en 1; la de fuera no.
    aforos = db.execute(text("SELECT id, asistentes_confirmados FROM clases "
                             "WHERE id = ANY(:ids)"),
                        {"ids": ids["clases"]}).all()
    aforo = {c.id: c.asistentes_confirmados for c in aforos}
    assert aforo[ids["clases"][0]] == 0
    assert aforo[ids["clases"][1]] == 0
    assert aforo[ids["clases"][2]] == 0


def test_creditos_insuficientes_rechaza(escenario, cliente):
    ids = escenario["ids"]
    db = escenario["db"]
    db.execute(text("UPDATE suscripciones SET creditos_disponibles = 3 WHERE id = :i"),
               {"i": ids["suscripcion"]})
    db.commit()

    resp = cliente.post(
        "/api/v1/alumnos/me/suspension",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "dias": escenario["dias"]},
        headers=escenario["token"],
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "No disponible — te quedan solo 3 créditos, necesitas al menos 4"


def test_menos_de_10_dias_rechaza(escenario, cliente):
    ids = escenario["ids"]
    db = escenario["db"]
    nueva = fin_del_dia_chile(escenario["hoy"] + timedelta(days=9))
    db.execute(text("UPDATE suscripciones SET fecha_expiracion = :e WHERE id = :i"),
               {"e": nueva, "i": ids["suscripcion"]})
    db.commit()

    resp = cliente.post(
        "/api/v1/alumnos/me/suspension",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "dias": escenario["dias"]},
        headers=escenario["token"],
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "No disponible — faltan 9 días para poder suspender"


def test_mas_dias_que_saldo_rechaza(escenario, cliente):
    ids = escenario["ids"]
    db = escenario["db"]
    # Consume 12 de los 14 días del ciclo (deja saldo 2). Se inserta en el PASADO
    # (no activa hoy) para no chocar con la regla nueva de "no solapar suspensiones".
    db.execute(text("""
        INSERT INTO suspensiones_plan (tenant_id, usuario_id, suscripcion_id,
                                       fecha_inicio, fecha_fin, dias,
                                       fecha_expiracion_original, reservas_canceladas)
        VALUES (:t, :u, :s, now() - interval '20 days', now() - interval '8 days',
                12, now(), 0)"""),
        {"t": ids["tenant"], "u": ids["alumno"], "s": ids["suscripcion"]})
    db.commit()

    resp = cliente.post(
        "/api/v1/alumnos/me/suspension",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "dias": escenario["dias"]},
        headers=escenario["token"],
    )
    assert resp.status_code == 400
    assert "2 día" in resp.json()["detail"]


# ── Cancelación de suspensión (fix del abuso en plan ilimitado) ─────────────
def _crear_suspension_activa(cliente, escenario, dias=3):
    """Crea una suspensión ACTIVA hoy (fecha_inicio = hoy) y devuelve su id."""
    resp = cliente.post(
        "/api/v1/alumnos/me/suspension",
        json={"fecha_inicio": str(escenario["hoy"]), "dias": dias},
        headers=escenario["token"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["suspension"]["id"]


def test_cancelar_suspension_caso_feliz(escenario, cliente):
    ids = escenario["ids"]
    expiracion_original = escenario["expiracion_original"]

    sid = _crear_suspension_activa(cliente, escenario, dias=3)

    resp = cliente.post(
        f"/api/v1/alumnos/me/suspension/{sid}/cancelar",
        headers=escenario["token"],
    )
    assert resp.status_code == 200, resp.text

    db = escenario["db"]
    db.expire_all()

    # Reversión EXACTA: la fecha vuelve a la original (no un cálculo proporcional).
    exp = db.execute(text("SELECT fecha_expiracion FROM suscripciones WHERE id = :i"),
                     {"i": ids["suscripcion"]}).scalar()
    assert exp == expiracion_original

    fila = db.execute(text("SELECT cancelada, cancelada_en FROM suspensiones_plan "
                           "WHERE id = :i"), {"i": sid}).one()
    assert fila.cancelada is True
    assert fila.cancelada_en is not None


def test_cancelar_segunda_vez_en_el_ciclo_rechaza(escenario, cliente):
    # Primera suspensión + cancelación (consume el cupo anual).
    sid = _crear_suspension_activa(cliente, escenario, dias=2)
    r1 = cliente.post(f"/api/v1/alumnos/me/suspension/{sid}/cancelar",
                      headers=escenario["token"])
    assert r1.status_code == 200, r1.text

    # Segunda suspensión: el cupo anual ya está usado -> 400.
    sid2 = _crear_suspension_activa(cliente, escenario, dias=2)
    r2 = cliente.post(f"/api/v1/alumnos/me/suspension/{sid2}/cancelar",
                      headers=escenario["token"])
    assert r2.status_code == 400
    assert "una vez por ciclo" in r2.json()["detail"]


def test_cancelar_suspension_inexistente_404(escenario, cliente):
    resp = cliente.post("/api/v1/alumnos/me/suspension/999999999/cancelar",
                        headers=escenario["token"])
    assert resp.status_code == 404


def test_cancelar_suspension_ya_terminada_400(escenario, cliente):
    ids = escenario["ids"]
    db = escenario["db"]
    # Suspensión que YA terminó (fecha_fin < hoy): no se puede cancelar.
    sid = db.execute(text("""
        INSERT INTO suspensiones_plan (tenant_id, usuario_id, suscripcion_id,
                                       fecha_inicio, fecha_fin, dias,
                                       fecha_expiracion_original, reservas_canceladas)
        VALUES (:t, :u, :s, now() - interval '10 days', now() - interval '5 days',
                3, now(), 0)
        RETURNING id"""),
        {"t": ids["tenant"], "u": ids["alumno"], "s": ids["suscripcion"]}).scalar()
    db.commit()

    resp = cliente.post(f"/api/v1/alumnos/me/suspension/{sid}/cancelar",
                        headers=escenario["token"])
    assert resp.status_code == 400
    assert "no está activa hoy" in resp.json()["detail"]


# ── Fix de visibilidad: no solapar suspensiones + historial del alumno ───────
def test_crear_suspension_rechaza_si_ya_hay_una_activa(escenario, cliente):
    # Primera suspensión activa hoy.
    _crear_suspension_activa(cliente, escenario, dias=3)

    # Segunda suspensión (mismo día) -> 400, aunque quede saldo.
    resp = cliente.post(
        "/api/v1/alumnos/me/suspension",
        json={"fecha_inicio": str(escenario["hoy"]), "dias": 2},
        headers=escenario["token"],
    )
    assert resp.status_code == 400
    assert "Ya tienes una suspensión activa" in resp.json()["detail"]


def test_historial_de_suspensiones_del_alumno(escenario, cliente):
    ids = escenario["ids"]
    db = escenario["db"]

    # Tres suspensiones en estados distintos, insertadas por SQL (bypass del POST,
    # que hoy impide solapar o pasar de 2 períodos): pasada, activa y cancelada.
    db.execute(text("""
        INSERT INTO suspensiones_plan (tenant_id, usuario_id, suscripcion_id,
                                       fecha_inicio, fecha_fin, dias,
                                       fecha_expiracion_original, cancelada,
                                       cancelada_en, reservas_canceladas)
        VALUES
          (:t, :u, :s, now() - interval '20 days', now() - interval '15 days', 5,
           now(), false, NULL, 0),
          (:t, :u, :s, now() - interval '2 days',  now() + interval '3 days',  3,
           now(), false, NULL, 0),
          (:t, :u, :s, now() - interval '5 days',  now() + interval '2 days',  2,
           now(), true,  now() - interval '1 day', 0)"""),
        {"t": ids["tenant"], "u": ids["alumno"], "s": ids["suscripcion"]})
    db.commit()

    resp = cliente.get("/api/v1/alumnos/me/suspensiones", headers=escenario["token"])
    assert resp.status_code == 200, resp.text
    items = resp.json()

    estados = [s["estado"] for s in items]
    assert estados.count("pasada") == 1
    assert estados.count("activa") == 1
    assert estados.count("cancelada") == 1
    # La pasada es la de 5 días; la cancelada lleva su flag en True.
    assert [s for s in items if s["estado"] == "pasada"][0]["dias"] == 5
    assert [s for s in items if s["estado"] == "cancelada"][0]["cancelada"] is True


