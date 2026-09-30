"""Corrección C de la F2: con el "Pase de regreso" puesto el alumno PUEDE RESERVAR.

Qué fija este archivo
---------------------
El pase se materializa como una suscripción de un plan que NO está en el catálogo
(`planes.activo = false` y `es_comercial = false`, migración 037). Si el criterio para reservar fuera
`Suscripcion.estado == 'activo'` —el estado COMERCIAL de hoy— el regalo queda inusable en cuanto su
fila no sea exactamente `activo`. Lo que decide quién puede reservar son la VIGENCIA (días de Chile,
último día COMPLETO) y los CRÉDITOS: `app.core.estados.da_acceso_hoy()`, el espejo ORM de
`shared.estados.sql_suscripcion_vigente()` —la MISMA definición que usa el mantenimiento—, donde
`pendiente` (todavía no se aprobó) y `rechazado` (no se aprobó nunca) NUNCA dan acceso y el resto lo
deciden las fechas.

  A. PURAS (sin BD): el predicado descarta los estados que nunca dan acceso, trae el día CHILENO y no
     es `estado = 'activo'`; y las DOS puertas de `reservas.py` (reservar y devolver el crédito) usan
     ESE predicado en vez de comparar el estado a mano.
  B. CONTRA TEST (escribe y RESTAURA): el endpoint REAL por `TestClient` (sin levantar servidor):
     * el pase (plan `activo = false`, fuera del catálogo) reserva -> 201 y gasta 1 crédito;
     * una fila que YA NO dice `activo` (el mantenimiento la pasó a `vencido`) pero con la ventana
       abierta, reserva igual -> 201: es el caso que rompía el filtro viejo y con el que se prueba
       que el `activo` comercial dejó de decidir;
     * con la ventana cerrada (vence ayer, fila `activo`) -> 400 "No tienes una membresía activa";
     * `pendiente` vigente -> 400: sacar el `activo` NO abrió la puerta a un plan sin aprobar;
     * sin créditos -> 400 "No te quedan clases disponibles";
     * la OTRA puerta (DELETE) devuelve el crédito con el MISMO criterio de vigencia.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_pase_puede_reservar.py -q
"""
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core import estados as app_estados                                     # noqa: E402
from app.core.config import settings                                           # noqa: E402
from app.core.security import create_access_token                              # noqa: E402
from app.models.suscripcion import EstadoSuscripcion, Suscripcion               # noqa: E402
from app.utils.santiago import SANTIAGO, hoy_santiago                          # noqa: E402
from shared import estados                                                     # noqa: E402

TENANT_ID = 1


def _sql(predicado) -> str:
    """El predicado ORM compilado a SQL, sin ejecutar nada (no necesita base)."""
    return str(predicado.compile(compile_kwargs={"literal_binds": True}))


def _predicado():
    return app_estados.da_acceso_hoy(Suscripcion.estado, Suscripcion.fecha_expiracion)


# ══════════════════════════════════════════════════════════════════════════════
# A. Reglas puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_c1_el_predicado_descarta_lo_que_nunca_dio_acceso_y_no_es_el_estado_comercial():
    """El `activo` COMERCIAL deja de ser el criterio; queda la vigencia + los dos estados de corte."""
    sql = _sql(_predicado())

    assert "NOT IN ('pendiente', 'rechazado')" in sql, sql
    assert app_estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES == ("pendiente", "rechazado")
    assert "= 'activo'" not in sql, f"el estado comercial sigue decidiendo: {sql}"


def test_c2_la_fecha_se_mide_en_dias_de_chile_y_el_ultimo_dia_cuenta_completo():
    """Vigencia en DÍAS de Chile: `AT TIME ZONE` en el SQL (no la TZ de la sesión) y hoy chileno."""
    sql = _sql(_predicado())

    assert "America/Santiago" in sql, sql
    assert sql.count("America/Santiago") == 1, sql          # sólo `fecha_expiracion`, medido en Chile
    assert "fecha_expiracion" in sql and str(hoy_santiago()) in sql, sql


def test_c3_el_orm_y_el_sql_del_mantenimiento_leen_la_misma_lista():
    """Una sola definición de "nunca dio acceso": el ORM y el SQL crudo no pueden divergir."""
    lista = estados.lista_sql(estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES)

    assert f"NOT IN ({lista})" in _sql(_predicado())
    assert f"NOT IN ({lista})" in estados.sql_suscripcion_vigente("s")


def test_c4_las_dos_puertas_de_reservas_usan_ese_predicado_y_no_el_estado():
    """Fuente de `reservas.py`: reservar (POST) y devolver el crédito (DELETE) comparten la MISMA
    puerta, y ya no hay ninguna comparación de estado escrita a mano."""
    fuente = (BACKEND / "app/api/v1/reservas.py").read_text(encoding="utf-8-sig")

    assert fuente.count("da_acceso_hoy(Suscripcion.estado, Suscripcion.fecha_expiracion)") == 2, (
        "las dos puertas (reservar / reembolsar) tienen que usar `da_acceso_hoy`")
    for escrito_a_mano in ('Suscripcion.estado == "activo"', "Suscripcion.estado == 'activo'"):
        assert escrito_a_mano not in fuente, f"quedó el filtro comercial: {escrito_a_mano}"


# ══════════════════════════════════════════════════════════════════════════════
# B. Contra TEST (escribe y RESTAURA): el endpoint real, con el pase puesto
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def db():
    """Sesión contra la MISMA rama TEST que ve la app (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(definí ENVIRONMENT=test / revisá .env.test)")
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def cliente():
    """`TestClient` del app real: no levanta servidor, pero pega contra la BD del proceso (TEST)."""
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def _crear_suscripcion(db, alumno_id, plan_id, vence, estado=EstadoSuscripcion.activo, creditos=1):
    """La suscripción del pase: `fecha_inicio` AHORA y `fecha_expiracion` a las 23:59:59 de Chile del
    último día (así el test mide el día COMPLETO, no un instante)."""
    etiqueta = estado.value if isinstance(estado, EstadoSuscripcion) else estado
    return db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado, creditos_totales,
                                   creditos_disponibles, fecha_inicio, fecha_expiracion)
        VALUES (:t, :u, :p, CAST(:e AS estado_suscripcion), :c, :c, :i, :f)
        RETURNING id"""),
        {"t": TENANT_ID, "u": alumno_id, "p": plan_id, "e": etiqueta, "c": creditos,
         "i": datetime.now(SANTIAGO),
         "f": datetime.combine(vence, time(23, 59, 59), tzinfo=SANTIAGO)}).scalar()


def _ventana(db, sub_id, vence, estado=None, creditos=None):
    """Mueve la ventana (y opcionalmente el estado o los créditos) de la suscripción del pase."""
    cambios = {"f": datetime.combine(vence, time(23, 59, 59), tzinfo=SANTIAGO), "s": sub_id}
    sql = "UPDATE suscripciones SET fecha_expiracion = :f"
    if estado is not None:
        sql += ", estado = CAST(:e AS estado_suscripcion)"
        cambios["e"] = estado
    if creditos is not None:
        sql += ", creditos_disponibles = :c"
        cambios["c"] = creditos
    db.execute(text(sql + " WHERE id = :s"), cambios)
    db.commit()


@pytest.fixture
def escenario(db):
    """Alumno NUEVO y ACTIVO con el "Pase de regreso" puesto: plan `activo = false` (como el pase
    REAL, que no está en el catálogo del box), `es_comercial = false`, 1 crédito y una ventana que
    cierra en 3 días a las 23:59:59 de Chile. Además, una clase futura PROPIA (no se toca ninguna
    clase del seed: el aforo y el contador se crean y se borran con el escenario).
    """
    sufijo = uuid.uuid4().hex[:12]
    hoy = hoy_santiago()
    ids = {"alumno_id": None, "plan_id": None, "sub_id": None, "clase_id": None}
    try:
        ids["alumno_id"] = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo, estado,
                                  created_at)
            VALUES (:t, :r, 'Alumno Pase Reserva TEST', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"97{sufijo[:8]}-9",
             "c": f"pase.reserva.{sufijo}@test.local", "alta": datetime.now(SANTIAGO)}).scalar()

        ids["plan_id"] = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias,
                                activo, es_comercial)
            VALUES (:t, :n, 1, false, 0, 7, false, false)
            RETURNING id"""),
            {"t": TENANT_ID, "n": f"Pase de regreso reserva TEST {sufijo}"}).scalar()

        ids["sub_id"] = _crear_suscripcion(db, ids["alumno_id"], ids["plan_id"],
                                           hoy + timedelta(days=3))

        horario_id = db.execute(text("SELECT id FROM horarios ORDER BY id LIMIT 1")).scalar()
        disciplina_id = db.execute(text("SELECT id FROM disciplinas ORDER BY id LIMIT 1")).scalar()
        assert horario_id and disciplina_id, "TEST no tiene horarios/disciplinas para la clase"
        ids["clase_id"] = db.execute(text("""
            INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio,
                                hora_fin, cupo_maximo, cupo_original, asistentes_confirmados, cancelada)
            VALUES (:t, :h, :d, :f, '19:00', '20:00', 20, 20, 0, false)
            RETURNING id"""),
            {"t": TENANT_ID, "h": horario_id, "d": disciplina_id,
             "f": hoy + timedelta(days=3)}).scalar()

        db.commit()
        yield ids
    finally:
        db.rollback()
        try:
            if ids["clase_id"]:
                db.execute(text("DELETE FROM reservas WHERE clase_id = :c"), {"c": ids["clase_id"]})
                db.execute(text("DELETE FROM clases WHERE id = :c"), {"c": ids["clase_id"]})
            if ids["alumno_id"]:
                db.execute(text("DELETE FROM reservas WHERE alumno_id = :a"),
                           {"a": ids["alumno_id"]})
                db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"),
                           {"a": ids["alumno_id"]})
            if ids["plan_id"]:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": ids["plan_id"]})
            if ids["alumno_id"]:
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": ids["alumno_id"]})
            db.commit()
        except Exception as e:      # el borrado no debe tapar el fallo real del test
            db.rollback()
            print(f"\n[WARN] no se pudo limpiar el escenario: {e}")


BASE = "/api/v1/reservas"


def _headers(alumno_id, rol="alumno"):
    """Token REAL del alumno del escenario (mismo camino que el navegador)."""
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": alumno_id, "tenant_id": TENANT_ID, "rol": rol,
        "correo": f"pase.reserva.{alumno_id}@test.local",
    })}


def _reservar(cliente, escenario, alumno_id):
    """El POST REAL, como lo manda el alumno para sí mismo (el pase es del alumno, no del staff)."""
    return cliente.post(BASE, headers=_headers(alumno_id), json={
        "clase_id": escenario["clase_id"], "alumno_id": alumno_id, "tenant_id": TENANT_ID,
    })


def _creditos(db, sub_id):
    return db.execute(text("SELECT creditos_disponibles FROM suscripciones WHERE id = :s"),
                      {"s": sub_id}).scalar()


def test_b1_el_pase_reserva_aunque_su_plan_no_este_en_el_catalogo(cliente, db, escenario):
    """El caso del diseño: plan `activo = false` (fuera del catálogo) + suscripción con 1 crédito ->
    201 y el crédito se gasta. Antes del fix, el `activo` comercial del PLAN no se miraba en ningún
    lado, pero la suscripción tenía que ser exactamente `activo` para pasar el filtro."""
    plan = db.execute(text("SELECT activo, es_comercial FROM planes WHERE id = :p"),
                      {"p": escenario["plan_id"]}).first()
    assert (plan.activo, plan.es_comercial) == (False, False), "el escenario tiene que ser el PASE"
    assert _creditos(db, escenario["sub_id"]) == 1

    r = _reservar(cliente, escenario, escenario["alumno_id"])

    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "confirmada"
    assert _creditos(db, escenario["sub_id"]) == 0


def test_b2_la_fila_del_pase_ya_no_dice_activo_y_el_alumno_reserva_igual(cliente, db, escenario):
    """El CORAZÓN de la corrección C: `estado` es el estado COMERCIAL de hoy, no el permiso.

    La fila del pase pasa a `vencido` (lo que hace el mantenimiento cuando la fecha se cumplió, o una
    corrección a mano) pero su VENTANA sigue abierta y tiene créditos: reserva igual -> 201. Con el
    filtro viejo (`Suscripcion.estado == 'activo' AND vigente_hoy(...)`) este caso daba 400 y el
    regalo quedaba inusable; el criterio es el MISMO del mantenimiento
    (`shared.estados.sql_suscripcion_vigente()`), donde el estado sólo descarta lo que NUNCA dio
    acceso (`pendiente`/`rechazado`).
    """
    _ventana(db, escenario["sub_id"], hoy_santiago() + timedelta(days=2), estado="vencido")

    r = _reservar(cliente, escenario, escenario["alumno_id"])

    assert r.status_code == 201, r.text
    assert _creditos(db, escenario["sub_id"]) == 0


def test_b3_ventana_cerrada_no_reserva_aunque_la_fila_diga_activo(cliente, db, escenario):
    """El otro lado del criterio: manda la VIGENCIA. Roto el día (vence ayer) con la fila en `activo`,
    el POST responde 400 con el mensaje de siempre (el front lo muestra tal cual)."""
    _ventana(db, escenario["sub_id"], hoy_santiago() - timedelta(days=1))

    r = _reservar(cliente, escenario, escenario["alumno_id"])

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "No tienes una membresía activa"
    assert _creditos(db, escenario["sub_id"]) == 1


def test_b4_pendiente_vigente_no_reserva(cliente, db, escenario):
    """Sacar el filtro `activo` NO abrió la puerta a un plan sin aprobar: `pendiente` (igual que
    `rechazado`) NUNCA dio acceso, tenga las fechas que tenga."""
    _ventana(db, escenario["sub_id"], hoy_santiago() + timedelta(days=2), estado="pendiente")

    r = _reservar(cliente, escenario, escenario["alumno_id"])

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "No tienes una membresía activa"


def test_b5_sin_creditos_no_reserva(cliente, db, escenario):
    """El pase reserva por VIGENCIA **y CRÉDITOS**: sin clases disponibles el regalo no es un plan
    ilimitado, así que 400 (mismo mensaje que para una membresía pagada)."""
    _ventana(db, escenario["sub_id"], hoy_santiago() + timedelta(days=3), creditos=0)

    r = _reservar(cliente, escenario, escenario["alumno_id"])

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "No te quedan clases disponibles. Renueva tu plan."


def test_b6_la_puerta_de_cancelar_devuelve_el_credito_con_el_mismo_criterio(cliente, db,
                                                                           escenario):
    """`DELETE /reservas/{id}` es la OTRA puerta que buscaba membresía por `estado == 'activo'`:
    con el pase en `vencido` y la ventana abierta (más de 6 h antes de la clase) el crédito vuelve."""
    reserva_id = _reservar(cliente, escenario, escenario["alumno_id"]).json()["id"]
    _ventana(db, escenario["sub_id"], hoy_santiago() + timedelta(days=2), estado="vencido")
    assert _creditos(db, escenario["sub_id"]) == 0

    r = cliente.delete(f"{BASE}/{reserva_id}", headers=_headers(escenario["alumno_id"]))

    assert r.status_code == 200, r.text
    assert r.json()["reembolsado"] is True
    assert _creditos(db, escenario["sub_id"]) == 1


