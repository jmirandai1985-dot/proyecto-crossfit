"""Crear/editar horario leen el body JSON (POST/PUT /horarios), no query params.

El bug: `crear_horario` y `actualizar_horario` declaraban sus campos como
parámetros SUELTOS (`disciplina_id: int = None`, …). En FastAPI un `int`/`str`/
`bool` suelto (sin `Body()` ni un modelo Pydantic) se lee como QUERY PARAM, pero
el panel manda `api.post('/api/v1/horarios', payload)`, es decir body JSON de
axios. Consecuencia:

  * POST: `disciplina_id` llegaba `None` → 404 "La disciplina no existe o no
    pertenece a este box" con CUALQUIER disciplina (crear era imposible);
  * PUT: todos los campos `Optional` llegaban `None` = "no cambiar nada" → 200
    sin aplicar ningún cambio (edición silenciosa, sin error visible).

Lo que fija este archivo (todo por HTTP, contra la misma app que sirve el navegador):
  1. POST con `json=` y una disciplina CUALQUIERA del box → 201 y el horario
     queda guardado con los valores enviados.
  2. POST sin body (sólo `params=`) → 422: el contrato es body JSON.
  3. PUT con `json=` → los cambios se aplican de verdad (día, horas, cupo) y
     quedan en la BD, no sólo en la respuesta.
  4. PUT con `activo` y con `disciplina_id` en el body (B6) también se aplican.
  5. Migración 066: el PUT rechaza fijar cupo a una disciplina de acceso libre
     (400). El caso "una sala libre se guarda con NULL" queda como `xfail`: el
     `default=15` del modelo gana sobre el `None` explícito (bug pre-existente,
     del modelo, no de la lectura del body).

Requiere la rama TEST (falla cerrado) y usa un box TEMPORAL que se borra al final.

Correr:
    cd backend && py -3.12 -m pytest tests/test_horarios_body_json.py -q --noconftest
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                   # noqa: E402
from app.core.security import create_access_token     # noqa: E402

API = "/api/v1"
HORARIOS = f"{API}/horarios"


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
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
def box(db):
    """Box temporal: tenant + admin + 3 disciplinas (2 normales, 1 de acceso libre)."""
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"
    alta = datetime.now(timezone.utc)
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Horarios TEST {sufijo}", "s": f"box-horarios-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        admin = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Admin Horarios TEST', :c, 'x', 'administrador',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": f"77{sufijo[-6:]}-7",
             "c": f"horarios.admin.{sufijo}@test.local", "alta": alta}).scalar()
        # Nombre ARBITRARIO a propósito: el bug fallaba con cualquier disciplina,
        # no sólo con la que se llame "crossfit".
        disciplinas = {}
        for clave, es_open_box in (("normal", False), ("otra", False),
                                   ("libre", True)):
            disciplinas[clave] = db.execute(text("""
                INSERT INTO disciplinas (tenant_id, nombre, es_open_box,
                                         requiere_coach, activo)
                VALUES (:t, :n, :o, true, true) RETURNING id"""),
                {"t": tenant, "n": f"Funcional {clave} {sufijo}",
                 "o": es_open_box}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        raise

    token = "Bearer " + create_access_token({
        "usuario_id": admin, "tenant_id": tenant, "rol": "administrador",
        "correo": "horarios@test.local"})
    datos = {"db": db, "tenant_id": tenant, "admin_id": admin,
             "admin": {"Authorization": token}, "disciplinas": disciplinas}
    try:
        yield datos
    finally:
        db.rollback()
        pendientes = ["auditoria", "horarios", "disciplinas", "usuarios"]
        for _ in range(2):
            for tabla in list(pendientes):
                try:
                    with db.begin_nested():
                        db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"),
                                   {"t": tenant})
                except Exception:
                    continue
                pendientes.remove(tabla)
            if not pendientes:
                break
        try:
            with db.begin_nested():
                db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
        except Exception:
            pendientes.append("tenants")
        db.commit()
        if pendientes:
            print(f"\n[WARN] limpieza test_horarios_body_json: quedó {pendientes}")


def _crear(cliente, box, disciplina=None, dia=1, ini="08:00", fin="09:00", cupo=16):
    """Crea un horario por el endpoint real (body JSON) y devuelve el JSON."""
    r = cliente.post(HORARIOS, headers=box["admin"], json={
        "disciplina_id": (box["disciplinas"]["normal"] if disciplina is None
                          else disciplina),
        "dia_semana": dia, "hora_inicio": ini, "hora_fin": fin,
        "cupo_maximo": cupo})
    assert r.status_code == 201, r.text
    return r.json()


def _en_bd(db, horario_id):
    """Fila COMMITEADA del horario (rollback para no leer caché de la sesión)."""
    db.rollback()
    fila = db.execute(text("""
        SELECT disciplina_id, dia_semana, hora_inicio::text AS hora_inicio,
               hora_fin::text AS hora_fin, cupo_maximo, activo
        FROM horarios WHERE id = :h
    """), {"h": horario_id}).first()
    return dict(fila._mapping) if fila else None


# ── 1. POST con body JSON: crea (antes: 404 con cualquier disciplina) ────────
def test_post_crea_el_horario_con_body_json(cliente, box):
    disc = box["disciplinas"]["normal"]
    r = cliente.post(HORARIOS, headers=box["admin"], json={
        "disciplina_id": disc, "dia_semana": 2,
        "hora_inicio": "07:00", "hora_fin": "08:00", "cupo_maximo": 14})

    assert r.status_code == 201, r.text
    creado = r.json()
    assert creado["disciplina_id"] == disc
    assert creado["dia_semana"] == 2
    assert creado["hora_inicio"].startswith("07:00")
    assert creado["hora_fin"].startswith("08:00")
    assert creado["cupo_maximo"] == 14
    assert creado["activo"] is True

    guardado = _en_bd(box["db"], creado["id"])
    assert guardado is not None, "el horario no quedó guardado"
    assert guardado["disciplina_id"] == disc
    assert guardado["dia_semana"] == 2
    assert guardado["hora_inicio"].startswith("07:00")
    assert guardado["hora_fin"].startswith("08:00")
    assert guardado["cupo_maximo"] == 14


# ── 2. Contrato: los campos NO se leen del query string ─────────────────────
def test_post_sin_body_es_422(cliente, box):
    """Sin body JSON no hay horario: los query params ya no crean nada."""
    params = {"disciplina_id": box["disciplinas"]["normal"], "dia_semana": 3,
              "hora_inicio": "09:00", "hora_fin": "10:00", "cupo_maximo": 10}
    r = cliente.post(HORARIOS, headers=box["admin"], params=params)
    assert r.status_code == 422, r.text

    # Body vacío tampoco: `disciplina_id`, día y horas son obligatorios.
    r = cliente.post(HORARIOS, headers=box["admin"], json={})
    assert r.status_code == 422, r.text


# ── 3. PUT con body JSON: aplica los cambios (antes los ignoraba) ───────────
def test_put_aplica_los_cambios_del_body(cliente, box):
    horario = _crear(cliente, box, dia=1, ini="08:00", fin="09:00", cupo=16)

    r = cliente.put(f"{HORARIOS}/{horario['id']}", headers=box["admin"], json={
        "dia_semana": 5, "hora_inicio": "19:30", "hora_fin": "20:30",
        "cupo_maximo": 9})

    assert r.status_code == 200, r.text
    editado = r.json()
    assert editado["dia_semana"] == 5
    assert editado["hora_inicio"].startswith("19:30")
    assert editado["hora_fin"].startswith("20:30")
    assert editado["cupo_maximo"] == 9

    guardado = _en_bd(box["db"], horario["id"])
    assert guardado["dia_semana"] == 5, "el día no se guardó (edición silenciosa)"
    assert guardado["hora_inicio"].startswith("19:30")
    assert guardado["hora_fin"].startswith("20:30")
    assert guardado["cupo_maximo"] == 9


def test_put_puede_desactivar_y_cambiar_disciplina_desde_el_body(cliente, box):
    horario = _crear(cliente, box, dia=4)

    r = cliente.put(f"{HORARIOS}/{horario['id']}", headers=box["admin"],
                    json={"activo": False})
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is False
    assert _en_bd(box["db"], horario["id"])["activo"] is False

    # B6: la disciplina nueva también tiene que llegar por el body.
    otra = box["disciplinas"]["otra"]
    r = cliente.put(f"{HORARIOS}/{horario['id']}", headers=box["admin"],
                    json={"disciplina_id": otra})
    assert r.status_code == 200, r.text
    assert r.json()["disciplina_id"] == otra
    assert _en_bd(box["db"], horario["id"])["disciplina_id"] == otra


# ── 5. Migración 066: el PUT no deja fijar cupo a una sala libre ────────────
def test_put_no_deja_fijar_cupo_a_una_disciplina_de_acceso_libre(cliente, box):
    horario = _crear(cliente, box, disciplina=box["disciplinas"]["libre"],
                     dia=6, ini="09:00", fin="10:00")

    r = cliente.put(f"{HORARIOS}/{horario['id']}", headers=box["admin"],
                    json={"cupo_maximo": 12})
    assert r.status_code == 400, r.text
    assert _en_bd(box["db"], horario["id"])["cupo_maximo"] != 12


@pytest.mark.xfail(strict=False, reason=(
    "Bug PRE-EXISTENTE, ajeno a este arreglo: `HorarioBase.cupo_maximo` tiene "
    "`default=15` y SQLAlchemy aplica ese default cuando el endpoint asigna "
    "None, así que una plantilla de acceso libre se guarda con 15 en vez de "
    "NULL (migración 066). Se documenta acá para no perderlo de vista; "
    "corregirlo implica tocar el modelo, no la lectura del body."))
def test_acceso_libre_deberia_guardarse_sin_cupo(cliente, box):
    horario = _crear(cliente, box, disciplina=box["disciplinas"]["libre"],
                     dia=6, ini="10:00", fin="11:00")
    assert horario["cupo_maximo"] is None
