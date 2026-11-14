"""Ciclo COMPLETO de un WOD (coach → clase → alumno → Performance Hub) — integración.

QUÉ CUBRE (contra la rama TEST real, con TestClient y sin levantar servidor)
---------------------------------------------------------------------------
1. El coach crea un WOD en `draft` con `tipo_metcon="FOR TIME"` (`POST /wods/`).
2. Lo publica (`PUT /wods/{id}` con `estado="publicado"`).
3. Crea una clase real de HOY (`POST /clases/`) y le asigna ese WOD
   (`POST /wods/clases/{clase_id}/asignar-wod/{wod_id}`).
4. El alumno reserva la clase (`POST /reservas`) y el coach marca la asistencia
   (`PUT /reservas/{id}/asistencia`).
5. `GET /me/wods-pendientes` incluye el WOD.
6. El alumno registra `rx` + tiempo (`POST /me/wods/{wod_id}/resultado`).
7. El WOD deja de estar pendiente.
8. `GET /me/wods-historial` trae el resultado con la prescripción REAL del WOD.
9. Se documenta que el Hub de RMs/Intensidad no depende de `wod_resultados`.

Todos los datos son de un tenant NUEVO y se borran en el `finally` del fixture.
Falla cerrado si la URL no es de TEST (nunca PROD). El correo queda en `noop`.

    cd backend && ENVIRONMENT=test py -3.12 -m pytest tests/test_wod_ciclo_completo_integracion.py -q --noconftest
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

from app.core.config import is_test_db_url, settings
from app.core.security import create_access_token
from app.utils.santiago import fin_del_dia_chile, hoy_santiago


def _insertar_usuario(db, tenant_id, rol, correo, nombre):
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                              rol, activo, estado, created_at)
        VALUES (:t, :r, :nom, :c, 'x', :rol, true, 'activo', now())
        RETURNING id"""),
        {"t": tenant_id, "r": uuid.uuid4().hex[:10], "nom": nombre,
         "c": correo, "rol": rol}).scalar()


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient de la app real, sin levantar uvicorn ni ejecutar el lifespan."""
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def _auth(usuario_id, tenant_id, rol, correo):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": usuario_id, "tenant_id": tenant_id,
        "rol": rol, "correo": correo,
    })}


@pytest.fixture()
def escenario(db):
    """Tenant + coach/admin/alumno + disciplina/horario + plan/suscripción."""
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    hoy = hoy_santiago()
    t = None
    try:
        t = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, now()) RETURNING id"""),
            {"n": f"Box E2E WOD {sufijo}",
             "s": f"box-e2e-wod-{sufijo}", "pub": str(uuid.uuid4())}).scalar()

        correo_coach = f"coach.wod.{sufijo}@test.local"
        correo_admin = f"admin.wod.{sufijo}@test.local"
        correo_alumno = f"alumno.wod.{sufijo}@test.local"
        coach = _insertar_usuario(db, t, "coach", correo_coach, "Coach WOD E2E")
        admin = _insertar_usuario(db, t, "administrador", correo_admin, "Admin WOD E2E")
        alumno = _insertar_usuario(db, t, "alumno", correo_alumno, "Alumno WOD E2E")

        disc = db.execute(text(
            "INSERT INTO disciplinas (tenant_id, nombre, activo) "
            "VALUES (:t, :n, true) RETURNING id"),
            {"t": t, "n": f"CrossFit E2E {sufijo}"}).scalar()
        horario = db.execute(text("""
            INSERT INTO horarios (tenant_id, disciplina_id, dia_semana,
                                  hora_inicio, hora_fin, activo)
            VALUES (:t, :d, 0, '00:00', '01:00', true) RETURNING id"""),
            {"t": t, "d": disc}).scalar()
        db.execute(text("""
            INSERT INTO coach_disciplinas (tenant_id, coach_id, disciplina_id, activo)
            VALUES (:t, :c, :d, true)"""),
            {"t": t, "c": coach, "d": disc})

        plan = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado,
                                precio_clp, duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 10, false, 0, 30, true, true) RETURNING id"""),
            {"t": t, "n": f"Plan E2E WOD {sufijo}"}).scalar()
        db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, 'activo', 10, 10, now(), :exp)"""),
            {"t": t, "u": alumno, "p": plan,
             "exp": fin_del_dia_chile(hoy + timedelta(days=30))})
        db.commit()
    except Exception:
        db.rollback()
        raise

    yield {
        "tenant": t, "hoy": hoy, "sufijo": sufijo,
        "coach": coach, "admin": admin, "alumno": alumno,
        "disc": disc, "horario": horario,
        "coach_headers": _auth(coach, t, "coach", correo_coach),
        "admin_headers": _auth(admin, t, "administrador", correo_admin),
        "alumno_headers": _auth(alumno, t, "alumno", correo_alumno),
    }

    # Limpieza: primero las tablas que referencian a otras, después el tenant.
    db.rollback()
    try:
        for tabla in (
            "wod_resultados", "reservas", "clases", "horarios",
            "coach_disciplinas", "suscripciones", "planes", "wods",
            "notificaciones_enviadas", "usuarios", "disciplinas",
        ):
            db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"), {"t": t})
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": t})
        db.commit()
    except Exception as e:  # noqa: BLE001 — la limpieza no debe tapar el test
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario E2E WOD: {e}")

def test_ciclo_completo_wod(cliente, db, escenario):
    """Un solo hilo: WOD borrador → publicado → clase → reserva/asistencia → resultado."""
    tenant = escenario["tenant"]
    hoy = escenario["hoy"]
    coach = escenario["coach_headers"]
    admin = escenario["admin_headers"]
    alumno = escenario["alumno_headers"]
    titulo = f"Fran E2E {escenario['sufijo']}"
    principal = "21-15-9 Thrusters + Pull-ups"
    tipo = "FOR TIME"

    # ── 1. El COACH crea el WOD en borrador ──────────────────────────────────
    r = cliente.post(
        "/api/v1/wods/",
        params={"disciplina_id": escenario["disc"]},
        headers=coach,
        json={
            "fecha": hoy.isoformat(),
            "hora_inicio": "00:00:00",
            "hora_fin": "01:00:00",
            "titulo": titulo,
            "wod_principal": principal,
            "tipo_metcon": tipo,
            "estado": "draft",
            "coach_id": escenario["coach"],
        },
    )
    assert r.status_code == 200, r.text
    wod = r.json()
    wod_id = wod["id"]
    assert wod["estado"] == "draft"
    assert wod["tipo_metcon"] == tipo
    assert wod["titulo"] == titulo

    # ── 2. El COACH publica el WOD existente ─────────────────────────────────
    # El modal del panel usa `POST /wods/batch-create` cuando crea+publica de una;
    # para un WOD que YA existe, el endpoint real de publicación/edición es
    # `PUT /wods/{id}` con `estado="publicado"` (WodUpdate).
    r = cliente.put(
        f"/api/v1/wods/{wod_id}",
        params={"disciplina_id": escenario["disc"]},
        headers=coach,
        json={"estado": "publicado"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "publicado"

    # ── 3. Clase real de HOY + asignación explícita del WOD ──────────────────
    # Publicar NO propaga el WOD a las clases: la asignación es un paso aparte
    # (`POST /wods/clases/{id}/asignar-wod/{wod}`), que es el que usa el panel.
    r = cliente.post(
        "/api/v1/clases/",
        headers=coach,
        json={
            "tenant_id": tenant,
            "horario_base_id": escenario["horario"],
            "coach_id": escenario["coach"],
            "disciplina_id": escenario["disc"],
            "fecha": hoy.isoformat(),
            "hora_inicio": "00:00:00",
            "hora_fin": "01:00:00",
            "cupo_maximo": 5,
            "asistentes_confirmados": 0,
            "cancelada": False,
        },
    )
    assert r.status_code == 200, r.text
    clase_id = r.json()["id"]

    r = cliente.post(
        f"/api/v1/wods/clases/{clase_id}/asignar-wod/{wod_id}",
        headers=coach,
    )
    assert r.status_code == 200, r.text
    assert r.json()["wod_id"] == wod_id

    db.expire_all()
    assert db.execute(
        text("SELECT wod_id FROM clases WHERE id = :c"), {"c": clase_id}
    ).scalar() == wod_id

    # Verificación con el ADMIN (tercer rol real): la clase aparece con su WOD.
    r = cliente.get(
        "/api/v1/clases/",
        params={
            "fecha_desde": hoy.isoformat(),
            "fecha_hasta": hoy.isoformat(),
            "disciplina_id": escenario["disc"],
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    clase_api = next(c for c in r.json() if c["id"] == clase_id)
    assert clase_api["wod_id"] == wod_id
    assert clase_api["wod_titulo"] == titulo

    # ── 4. El ALUMNO reserva y el COACH marca la asistencia real ─────────────
    r = cliente.post(
        "/api/v1/reservas",
        headers=alumno,
        json={"tenant_id": tenant, "clase_id": clase_id,
              "alumno_id": escenario["alumno"]},
    )
    assert r.status_code == 201, r.text
    reserva_id = r.json()["id"]

    r = cliente.put(
        f"/api/v1/reservas/{reserva_id}/asistencia",
        headers=coach,
        json={"asistio": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["asistio"] is True
    db.expire_all()
    assert db.execute(
        text("SELECT asistio FROM reservas WHERE id = :r"), {"r": reserva_id}
    ).scalar() is True


    # ── 5. El ALUMNO ve el WOD pendiente ─────────────────────────────────────
    r = cliente.get("/api/v1/alumnos/me/wods-pendientes", headers=alumno)
    assert r.status_code == 200, r.text
    pendiente = next((p for p in r.json() if p["wod_id"] == wod_id), None)
    assert pendiente is not None, "el WOD publicado + asistido debe estar pendiente"
    assert pendiente["titulo"] == titulo
    assert pendiente["wod_principal"] == principal
    assert pendiente["tipo_metcon"] == tipo

    # ── 6. El ALUMNO registra su resultado real ──────────────────────────────
    r = cliente.post(
        f"/api/v1/alumnos/me/wods/{wod_id}/resultado",
        headers=alumno,
        json={"modo": "rx", "tiempo_segundos": 845, "nota": "Ciclo E2E"},
    )
    assert r.status_code == 200, r.text
    resultado = r.json()
    assert resultado["wod_id"] == wod_id
    assert resultado["modo"] == "rx"
    assert resultado["tiempo_segundos"] == 845

    # ── 7. Ya NO aparece como pendiente ──────────────────────────────────────
    r = cliente.get("/api/v1/alumnos/me/wods-pendientes", headers=alumno)
    assert r.status_code == 200, r.text
    assert all(p["wod_id"] != wod_id for p in r.json()), \
        "el WOD registrado no puede seguir pendiente"

    # ── 8. Aparece en el historial con la prescripción REAL del WOD ──────────
    r = cliente.get("/api/v1/alumnos/me/wods-historial", headers=alumno)
    assert r.status_code == 200, r.text
    historial = r.json()
    item = next((h for h in historial if h["wod_id"] == wod_id), None)
    assert item is not None, "el resultado registrado debe aparecer en el historial"
    assert item["titulo"] == titulo
    assert item["wod_principal"] == principal
    assert item["tipo_metcon"] == tipo
    assert item["modo"] == "rx"
    assert item["tiempo_segundos"] == 845
    assert item["nota"] == "Ciclo E2E"
    assert item["reserva_id"] == reserva_id, "la traza apunta a la asistencia real"

    # ── 9. Performance Hub: no hay OTRO cálculo que dependa de wod_resultados ─
    # `GET /wods/intensidad-relativa` (la sección "Intensidad en tus WODs" del Hub)
    # vive en wods.py y se calcula desde Asistencia/WODs, NO desde esta tabla. La
    # única referencia a WodResultado está en los endpoints /me/wods-* de alumnos.
    fuente_wods = (BACKEND / "app" / "api" / "v1" / "wods.py").read_text(
        encoding="utf-8")
    assert "WodResultado" not in fuente_wods
    assert "wod_resultados" not in fuente_wods

    r = cliente.get("/api/v1/wods/intensidad-relativa", headers=alumno)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

