"""Suspensión por salud: integración del SERVICIO contra la BD de TEST.

A diferencia del test de API (TestClient), acá se llama directo a
`suspensiones_service.crear_suspension_salud` / `cancelar_suspension_salud` con una
`SessionLocal` real, para fijar que toca `fecha_expiracion` y las reservas como la
self-service (sin el costo de importar `app.main`).

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suspensiones_salud_service_integracion.py -q
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

from app.services import suspensiones_service as svc           # noqa: E402
from app.utils.santiago import SANTIAGO, fin_del_dia_chile, hoy_santiago  # noqa: E402

# El servicio usa el ORM (`db.add(SuspensionPlan)` / `db.query(Suscripcion)`), que
# al hacer flush configura TODAS las FKs. Sin `app.main`, faltan tablas en el
# metadata (p.ej. `pagos`, referenciada por `suscripciones.pago_id`): acá se
# registran para que el mapper no explote con NoReferencedTableError.
import app.models  # noqa: E402,F401
from app.models.pago import Pago, PagoEvento  # noqa: E402,F401


@pytest.fixture(scope="module")
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


def _insertar_usuario(db, tenant_id, rol, correo, creado):
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, :nom, :c, 'x', :rol, true, 'activo', :alta)
        RETURNING id"""),
        {"t": tenant_id, "r": uuid.uuid4().hex[:10],
         "nom": f"Usr {rol} {correo}", "c": correo, "rol": rol,
         "alta": creado}).scalar()


@pytest.fixture
def escenario(db):
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    hoy = hoy_santiago()
    creado = datetime.combine(hoy - timedelta(days=200), datetime.min.time(),
                              tzinfo=SANTIAGO)
    expiracion = fin_del_dia_chile(hoy + timedelta(days=30))
    fecha_inicio = hoy + timedelta(days=7)
    fecha_fin = hoy + timedelta(days=9)

    ids = {"tenant": None, "alumno": None, "admin": None, "plan": None,
           "disc": None, "horario": None, "suscripcion": None,
           "clases": [], "reservas": []}
    try:
        ids["tenant"] = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, now()) RETURNING id"""),
            {"n": f"Box Salud SVC {sufijo}", "s": f"box-salud-svc-{sufijo}",
             "pub": str(uuid.uuid4())}).scalar()
        t = ids["tenant"]
        ids["alumno"] = _insertar_usuario(db, t, "alumno", f"saludsvc.{sufijo}@test.local", creado)
        ids["admin"] = _insertar_usuario(db, t, "administrador", f"admsvc.{sufijo}@test.local", creado)
        ids["disc"] = db.execute(text(
            "INSERT INTO disciplinas (tenant_id, nombre, activo) "
            "VALUES (:t, :n, true) RETURNING id"),
            {"t": t, "n": f"CrossFit Salud SVC {sufijo}"}).scalar()
        ids["horario"] = db.execute(text("""
            INSERT INTO horarios (tenant_id, disciplina_id, dia_semana, hora_inicio,
                                  hora_fin, activo)
            VALUES (:t, :d, 1, '19:00', '20:00', true) RETURNING id"""),
            {"t": t, "d": ids["disc"]}).scalar()
        ids["plan"] = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 20, false, 40000, 30, true, true) RETURNING id"""),
            {"t": t, "n": f"Plan Salud SVC {sufijo}"}).scalar()
        ids["suscripcion"] = db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, 'activo', 20, 20, now(), :exp) RETURNING id"""),
            {"t": t, "u": ids["alumno"], "p": ids["plan"],
             "exp": expiracion}).scalar()

        for dia in (fecha_inicio, fecha_fin, fecha_inicio + timedelta(days=10)):
            cid = db.execute(text("""
                INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha,
                                    hora_inicio, hora_fin, cupo_maximo,
                                    asistentes_confirmados, cancelada)
                VALUES (:t, :h, :d, :f, '19:00', '20:00', 20, 1, false) RETURNING id"""),
                {"t": t, "h": ids["horario"], "d": ids["disc"], "f": dia}).scalar()
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

    yield {"db": db, "ids": ids, "fecha_inicio": fecha_inicio,
           "fecha_fin": fecha_fin, "expiracion_original": expiracion}

    db.rollback()
    t = ids["tenant"]
    try:
        for tabla in ("reservas", "suspensiones_plan", "clases", "horarios",
                      "suscripciones", "usuarios", "disciplinas", "planes"):
            db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"), {"t": t})
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": t})
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario svc-salud: {e}")


def _estados(db, ids_reservas):
    filas = db.execute(text("SELECT id, estado FROM reservas WHERE id = ANY(:ids)"),
                       {"ids": ids_reservas}).all()
    return {f.id: f.estado for f in filas}


def test_crear_suspension_salud_extiende_y_cancela(escenario):
    db = escenario["db"]
    ids = escenario["ids"]

    susp = svc.crear_suspension_salud(
        db, ids["alumno"], ids["admin"],
        escenario["fecha_inicio"], escenario["fecha_fin"], "cirugía")

    db.expire_all()
    exp = db.execute(text("SELECT fecha_expiracion FROM suscripciones WHERE id = :i"),
                     {"i": ids["suscripcion"]}).scalar()
    assert exp == escenario["expiracion_original"] + timedelta(days=3)

    assert susp.origen == "admin_salud"
    assert susp.motivo == "cirugía"
    assert susp.creada_por_usuario_id == ids["admin"]

    estados = _estados(db, ids["reservas"])
    assert estados[ids["reservas"][0]] == "cancelada_por_suspension"
    assert estados[ids["reservas"][1]] == "cancelada_por_suspension"
    assert estados[ids["reservas"][2]] == "reserved"


def test_cancelar_suspension_salud_revierte_exacto(escenario):
    db = escenario["db"]
    ids = escenario["ids"]

    susp = svc.crear_suspension_salud(
        db, ids["alumno"], ids["admin"],
        escenario["fecha_inicio"], escenario["fecha_fin"])
    svc.cancelar_suspension_salud(db, susp.id, ids["admin"])

    db.expire_all()
    exp = db.execute(text("SELECT fecha_expiracion FROM suscripciones WHERE id = :i"),
                     {"i": ids["suscripcion"]}).scalar()
    assert exp == escenario["expiracion_original"]


def test_admin_salud_no_afecta_saldo_en_ciclo(escenario):
    db = escenario["db"]
    ids = escenario["ids"]

    susp = svc.crear_suspension_salud(
        db, ids["alumno"], ids["admin"],
        escenario["fecha_inicio"], escenario["fecha_fin"], "licencia médica")

    # La fila es admin_salud: `dias_usados_en_ciclo` la ignora (saldo intacto).
    assert susp.origen == "admin_salud"
    from app.models.usuario import Usuario
    usuario = db.query(Usuario).get(ids["alumno"])
    ciclo_inicio, ciclo_fin = svc.ciclo_vigente(usuario.created_at, hoy_santiago())
    assert svc.dias_usados_en_ciclo([susp], ciclo_inicio, ciclo_fin) == 0


def test_crear_suspension_salud_rechaza_fecha_invertida(escenario):
    db = escenario["db"]
    ids = escenario["ids"]
    with pytest.raises(ValueError):
        svc.crear_suspension_salud(
            db, ids["alumno"], ids["admin"],
            escenario["fecha_fin"], escenario["fecha_inicio"])
