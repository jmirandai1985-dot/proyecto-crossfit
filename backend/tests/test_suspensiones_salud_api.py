"""API de Suspensión por salud (admin): los 3 endpoints nuevos contra el app real.

Cubre el flujo del admin (crea/cancela suspensión por salud desde la ficha):
  * preview (`?preview=true`): días calculados + nueva fecha + reservas a cancelar;
  * caso feliz: `fecha_expiracion += dias`, cancela SÓLO las reservas del rango;
  * la suspensión `admin_salud` NO mueve el saldo del alumno (vista alumno);
  * cancelar revierte `fecha_expiracion` EXACTA (sin cupo anual);
  * historial por alumno.

REQUISITO PREVIO: la migración `075_suspension_salud` aplicada en la rama TEST
(columnas `origen`/`motivo`/`creada_por_usuario_id` de `suspensiones_plan`).

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suspensiones_salud_api.py -q
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

from app.core.security import create_access_token                        # noqa: E402
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
    """Box propio con alumno, admin, plan, disciplina, clases y reservas.

    El alumno queda con un plan limitado de 20 créditos que vence en 30 días, y 3
    reservas: dos DENTRO del rango de la suspensión por salud y una FUERA. El admin
    (rol 'administrador') es quien crea/cancela la suspensión por salud.
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    hoy = hoy_santiago()
    creado = datetime.combine(hoy - timedelta(days=200), datetime.min.time(),
                              tzinfo=SANTIAGO)
    expiracion = fin_del_dia_chile(hoy + timedelta(days=30))
    fecha_inicio = hoy + timedelta(days=7)
    fecha_fin = hoy + timedelta(days=9)   # 3 días inclusive

    ids = {"tenant": None, "alumno": None, "admin": None, "plan": None,
           "disc": None, "horario": None, "suscripcion": None,
           "clases": [], "reservas": []}
    try:
        ids["tenant"] = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, now()) RETURNING id"""),
            {"n": f"Box Salud TEST {sufijo}", "s": f"box-salud-{sufijo}",
             "pub": str(uuid.uuid4())}).scalar()
        t = ids["tenant"]
        ids["alumno"] = _insertar_usuario(db, t, "alumno", f"salud.{sufijo}@test.local", creado)
        ids["admin"] = _insertar_usuario(db, t, "administrador", f"adm.{sufijo}@test.local", creado)
        ids["disc"] = db.execute(text("""
            INSERT INTO disciplinas (tenant_id, nombre, activo)
            VALUES (:t, :n, true) RETURNING id"""),
            {"t": t, "n": f"CrossFit Salud {sufijo}"}).scalar()
        ids["horario"] = db.execute(text("""
            INSERT INTO horarios (tenant_id, disciplina_id, dia_semana, hora_inicio,
                                  hora_fin, activo)
            VALUES (:t, :d, 1, '19:00', '20:00', true) RETURNING id"""),
            {"t": t, "d": ids["disc"]}).scalar()
        ids["plan"] = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 20, false, 40000, 30, true, true) RETURNING id"""),
            {"t": t, "n": f"Plan Salud TEST {sufijo}"}).scalar()
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

    token_alumno = {"Authorization": "Bearer " + create_access_token({
        "usuario_id": ids["alumno"], "tenant_id": t, "rol": "alumno",
        "correo": f"salud.{sufijo}@test.local"})}
    token_admin = {"Authorization": "Bearer " + create_access_token({
        "usuario_id": ids["admin"], "tenant_id": t, "rol": "administrador",
        "correo": f"adm.{sufijo}@test.local"})}

    yield {"db": db, "ids": ids, "token_alumno": token_alumno,
           "token_admin": token_admin, "hoy": hoy, "fecha_inicio": fecha_inicio,
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
        print(f"\n[WARN] no se pudo limpiar el escenario de suspensiones-salud: {e}")


def _estados(db, ids_reservas):
    filas = db.execute(text("SELECT id, estado FROM reservas WHERE id = ANY(:ids)"),
                       {"ids": ids_reservas}).all()
    return {f.id: f.estado for f in filas}


# ── preview ──────────────────────────────────────────────────────────────────
def test_preview_suspension_salud(escenario, cliente):
    resp = cliente.post(
        f"/api/v1/admin/alumnos/{escenario['ids']['alumno']}/suspension-salud"
        "?preview=true",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "fecha_fin": str(escenario["fecha_fin"]),
              "motivo": "licencia médica"},
        headers=escenario["token_admin"],
    )
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    assert datos["dias"] == 3
    # La fecha vuelve en UTC (+00:00); se compara por INSTANTE con la original
    # (que está en Chile, -03:00), no por su representación string.
    nueva = datetime.fromisoformat(datos["fecha_expiracion_nueva"])
    assert nueva == escenario["expiracion_original"] + timedelta(days=3)
    assert len(datos["reservas_a_cancelar"]) == 2

    # El preview NO escribe: no hay suspensión nueva en BD.
    n = escenario["db"].execute(text(
        "SELECT count(*) FROM suspensiones_plan WHERE tenant_id = :t"),
        {"t": escenario["ids"]["tenant"]}).scalar()
    assert n == 0


# ── caso feliz ───────────────────────────────────────────────────────────────
def test_crear_suspension_salud_caso_feliz(escenario, cliente):
    ids = escenario["ids"]
    resp = cliente.post(
        f"/api/v1/admin/alumnos/{ids['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "fecha_fin": str(escenario["fecha_fin"]),
              "motivo": "cirugía"},
        headers=escenario["token_admin"],
    )
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    assert datos["suspension"]["dias"] == 3
    assert datos["suspension"]["motivo"] == "cirugía"
    assert datos["suspension"]["reservas_canceladas"] == 2
    assert len(datos["reservas_canceladas"]) == 2

    db = escenario["db"]
    db.expire_all()

    # fecha_expiracion += 3 días y origen/motivo/creada_por guardados.
    fila = db.execute(text(
        "SELECT fecha_expiracion FROM suscripciones WHERE id = :i"),
        {"i": ids["suscripcion"]}).scalar()
    assert fila == escenario["expiracion_original"] + timedelta(days=3)

    susp = db.execute(text(
        "SELECT origen, motivo, creada_por_usuario_id FROM suspensiones_plan "
        "WHERE usuario_id = :u"), {"u": ids["alumno"]}).first()
    assert susp.origen == "admin_salud"
    assert susp.motivo == "cirugía"
    assert susp.creada_por_usuario_id == ids["admin"]

    # Las dos reservas del rango canceladas; la de fuera, intacta.
    estados = _estados(db, ids["reservas"])
    assert estados[ids["reservas"][0]] == "cancelada_por_suspension"
    assert estados[ids["reservas"][1]] == "cancelada_por_suspension"
    assert estados[ids["reservas"][2]] == "reserved"


# ── la admin_salud NO afecta el saldo del alumno ─────────────────────────────
def test_admin_salud_no_afecta_saldo_alumno(escenario, cliente):
    ids = escenario["ids"]
    # El admin crea una suspensión por salud (misma ventana que el caso feliz).
    resp = cliente.post(
        f"/api/v1/admin/alumnos/{ids['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "fecha_fin": str(escenario["fecha_fin"])},
        headers=escenario["token_admin"],
    )
    assert resp.status_code == 200, resp.text

    # Vista alumno: el saldo de 14 días/año NO se mueve (la admin_salud no cuenta).
    r = cliente.get("/api/v1/alumnos/me/suspension/elegibilidad",
                    headers=escenario["token_alumno"])
    assert r.status_code == 200, r.text
    assert r.json()["saldo_disponible"] == 14


# ── cancelar (reversión exacta, sin cupo anual) ──────────────────────────────
def test_cancelar_suspension_salud_revierte_fecha(escenario, cliente):
    ids = escenario["ids"]
    creada = cliente.post(
        f"/api/v1/admin/alumnos/{ids['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "fecha_fin": str(escenario["fecha_fin"])},
        headers=escenario["token_admin"],
    ).json()
    sid = creada["suspension"]["id"]

    resp = cliente.post(f"/api/v1/admin/suspensiones/{sid}/cancelar-salud",
                        headers=escenario["token_admin"])
    assert resp.status_code == 200, resp.text

    db = escenario["db"]
    db.expire_all()
    fila = db.execute(text(
        "SELECT fecha_expiracion FROM suscripciones WHERE id = :i"),
        {"i": ids["suscripcion"]}).scalar()
    assert fila == escenario["expiracion_original"]
    cancelada = db.execute(text(
        "SELECT cancelada FROM suspensiones_plan WHERE id = :i"), {"i": sid}).scalar()
    assert cancelada is True


# ── historial ────────────────────────────────────────────────────────────────
def test_historial_suspensiones_salud(escenario, cliente):
    ids = escenario["ids"]
    # Una de salud (origen admin_salud) y otra self-service (origen alumno).
    cliente.post(
        f"/api/v1/admin/alumnos/{ids['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "fecha_fin": str(escenario["fecha_fin"]), "motivo": "cirugía"},
        headers=escenario["token_admin"],
    )
    db = escenario["db"]
    db.execute(text("""
        INSERT INTO suspensiones_plan (tenant_id, usuario_id, suscripcion_id,
                                       fecha_inicio, fecha_fin, dias,
                                       fecha_expiracion_original, reservas_canceladas)
        VALUES (:t, :u, :s, now() - interval '20 days', now() - interval '15 days',
                5, now(), 0)"""),
        {"t": ids["tenant"], "u": ids["alumno"], "s": ids["suscripcion"]})
    db.commit()

    resp = cliente.get(f"/api/v1/admin/alumnos/{ids['alumno']}/suspensiones-salud",
                       headers=escenario["token_admin"])
    assert resp.status_code == 200, resp.text
    items = resp.json()
    # Sólo la de salud (la self-service, con origen 'alumno', no aparece acá).
    assert len(items) == 1
    assert items[0]["motivo"] == "cirugía"
    assert items[0]["estado"] == "futura"


# ── validaciones / errores ───────────────────────────────────────────────────
def test_crear_suspension_salud_fecha_invalida_400(escenario, cliente):
    resp = cliente.post(
        f"/api/v1/admin/alumnos/{escenario['ids']['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["fecha_fin"]),
              "fecha_fin": str(escenario["fecha_inicio"])},
        headers=escenario["token_admin"],
    )
    assert resp.status_code == 400
    assert "posterior" in resp.json()["detail"]


def test_cancelar_suspension_salud_inexistente_404(escenario, cliente):
    resp = cliente.post("/api/v1/admin/suspensiones/999999999/cancelar-salud",
                        headers=escenario["token_admin"])
    assert resp.status_code == 404


def test_crear_suspension_salud_requiere_admin(escenario, cliente):
    # El alumno NO puede crear una suspensión por salud (403).
    resp = cliente.post(
        f"/api/v1/admin/alumnos/{escenario['ids']['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["fecha_inicio"]),
              "fecha_fin": str(escenario["fecha_fin"])},
        headers=escenario["token_alumno"],
    )
    assert resp.status_code == 403


# ── Visibilidad al alumno (Parte A): ve las admin_salud pero no las controla ──
def test_alumno_ve_suspension_salud_en_historial(escenario, cliente):
    ids = escenario["ids"]
    creada = cliente.post(
        f"/api/v1/admin/alumnos/{ids['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["hoy"]),
              "fecha_fin": str(escenario["hoy"] + timedelta(days=2)),
              "motivo": "cirugía"},
        headers=escenario["token_admin"],
    )
    assert creada.status_code == 200, creada.text

    resp = cliente.get("/api/v1/alumnos/me/suspensiones",
                       headers=escenario["token_alumno"])
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["origen"] == "admin_salud"
    assert items[0]["estado"] == "activa"


def test_alumno_ve_suspension_salud_en_elegibilidad(escenario, cliente):
    ids = escenario["ids"]
    creada = cliente.post(
        f"/api/v1/admin/alumnos/{ids['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["hoy"]),
              "fecha_fin": str(escenario["hoy"] + timedelta(days=2))},
        headers=escenario["token_admin"],
    )
    assert creada.status_code == 200, creada.text

    r = cliente.get("/api/v1/alumnos/me/suspension/elegibilidad",
                    headers=escenario["token_alumno"])
    assert r.status_code == 200, r.text
    datos = r.json()
    # La ve como suspensión activa, con su origen.
    assert datos["suspension_activa"]["origen"] == "admin_salud"
    # Pero el saldo de 14 días/año sigue intacto.
    assert datos["saldo_disponible"] == 14


def test_cancelar_self_service_rechaza_admin_salud(escenario, cliente):
    ids = escenario["ids"]
    creada = cliente.post(
        f"/api/v1/admin/alumnos/{ids['alumno']}/suspension-salud",
        json={"fecha_inicio": str(escenario["hoy"]),
              "fecha_fin": str(escenario["hoy"] + timedelta(days=2))},
        headers=escenario["token_admin"],
    ).json()
    sid = creada["suspension"]["id"]

    # El alumno NO puede cancelar una de salud por la ruta self-service, aunque
    # arme el request a mano.
    resp = cliente.post(f"/api/v1/alumnos/me/suspension/{sid}/cancelar",
                        headers=escenario["token_alumno"])
    assert resp.status_code == 400
    assert "salud" in resp.json()["detail"]
