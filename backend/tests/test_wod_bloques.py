"""WOD con bloques (Bloque 3) — endpoints aislados con SQLite EN MEMORIA.

QUÉ CUBRE
---------
* WOD SIN bloques: se registra igual que antes (regresión) y el segundo POST
  ACTUALIZA la misma fila (UPSERT de siempre).
* WOD con 2+ bloques: un resultado por bloque, sin chocar con la unicidad; el
  mismo bloque repetido actualiza (no duplica) y un INSERT duplicado directo es
  rechazado por el índice único parcial.
* El candado de `asistio=True` también aplica al endpoint por bloque.
* Validación por tipo del BLOQUE: tiempo (FOR TIME), peso (RM).
* Lectura: `GET /me/wods-pendientes`, `GET /me/wods-historial` y
  `GET /wods/hoy` devuelven `bloques: [...]` (vacío en el WOD simple).

    cd backend && py -3.12 -m pytest tests/test_wod_bloques.py -q --noconftest
"""
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import alumnos
from app.api.v1 import wods as wods_api
from app.core.dependencies import get_current_user
from app.db.database import Base, get_db
from app.models.clase import Clase
from app.models.disciplina import Disciplina
from app.models.horario_base import HorarioBase
from app.models.reserva import Reserva
from app.models.tenant import Tenant
from app.models.usuario import RolUsuario, Usuario
from app.models.wod import EstadoWod, Wod
from app.models.wod_bloque import WodBloque
from app.models.wod_movimiento import WodMovimiento
from app.models.wod_resultado import WodResultado
from app.utils.santiago import SANTIAGO

TENANT = 1
ALUMNO = 10
OTRO_ALUMNO = 11
AHORA = datetime(2026, 11, 13, 12, 0, tzinfo=SANTIAGO)

WOD_SIMPLE = 201
WOD_CON_BLOQUES = 202
WOD_SIN_ASISTENCIA = 203
WOD_BORRADOR = 204

BLOQUE_METCON = 301        # FOR TIME
BLOQUE_RM = 302            # RM Final
BLOQUE_SIN_ASISTENCIA = 303
BLOQUE_BORRADOR = 304

TABLAS = [
    Tenant.__table__, Usuario.__table__, Disciplina.__table__,
    HorarioBase.__table__, Wod.__table__, WodMovimiento.__table__,
    WodBloque.__table__, Clase.__table__, Reserva.__table__,
    WodResultado.__table__,
]


def _fecha_hora(horas_atras):
    momento = AHORA - timedelta(hours=horas_atras)
    return momento.date(), momento.time().replace(second=0, microsecond=0)


def _wod(id_, horas_atras, titulo, tipo_metcon, estado=EstadoWod.publicado):
    fecha, _ = _fecha_hora(horas_atras)
    return Wod(id=id_, tenant_id=TENANT, fecha=fecha, titulo=titulo,
               wod_principal="Trabajo prescrito", tipo_metcon=tipo_metcon,
               estado=estado, activo=True)


def _clase(id_, wod_id, horas_atras):
    fecha, hora_inicio = _fecha_hora(horas_atras)
    hora_fin = (datetime.combine(fecha, hora_inicio, tzinfo=SANTIAGO)
                + timedelta(hours=1)).time()
    return Clase(id=id_, tenant_id=TENANT, horario_base_id=1, disciplina_id=1,
                 fecha=fecha, hora_inicio=hora_inicio, hora_fin=hora_fin,
                 cupo_maximo=20, asistentes_confirmados=0, cancelada=False,
                 wod_id=wod_id)


def _reserva(id_, clase_id, alumno_id, asistio, horas_atras):
    return Reserva(
        id=id_, tenant_id=TENANT, clase_id=clase_id, alumno_id=alumno_id,
        fecha_reserva=AHORA - timedelta(hours=horas_atras),
        # `created_at` decide cuál reserva elige /wods/hoy: se fija explícito
        # para que el escenario sea determinista.
        created_at=AHORA - timedelta(hours=horas_atras),
        asistio=asistio, tokens_gastados=0, estado="reserved",
    )


def _sembrar(db):
    db.add(Tenant(id=TENANT, nombre="Box Bloques", subdomain="box-bloques",
                  public_id="box-bloques-public-id", activo=True))
    db.add_all([
        Usuario(id=ALUMNO, tenant_id=TENANT, rut="11111111-1",
                nombre="Alumno Bloques", correo="bloques@test.com",
                password_hash="x", rol=RolUsuario.alumno,
                activo=True, estado="activo"),
        Usuario(id=OTRO_ALUMNO, tenant_id=TENANT, rut="22222222-2",
                nombre="Otro Alumno", correo="otro-bloques@test.com",
                password_hash="x", rol=RolUsuario.alumno,
                activo=True, estado="activo"),
    ])
    db.add(Disciplina(id=1, tenant_id=TENANT, nombre="CrossFit",
                      es_open_box=False, requiere_coach=True, activo=True))
    db.add(HorarioBase(id=1, tenant_id=TENANT, disciplina_id=1, dia_semana=0,
                       hora_inicio=time(9), hora_fin=time(10),
                       cupo_maximo=20, activo=True))
    db.add_all([
        _wod(WOD_SIMPLE, 2, "WOD simple", "FOR TIME"),
        _wod(WOD_CON_BLOQUES, 2, "Dos metcons + RM", None),
        _wod(WOD_SIN_ASISTENCIA, 2, "No fui", "FOR TIME"),
        _wod(WOD_BORRADOR, 2, "Borrador", "FOR TIME", EstadoWod.draft),
    ])
    db.add_all([
        _clase(211, WOD_SIMPLE, 2),
        _clase(212, WOD_CON_BLOQUES, 2),
        _clase(213, WOD_SIN_ASISTENCIA, 2),
        _clase(214, WOD_BORRADOR, 2),
    ])
    db.add_all([
        _reserva(311, 211, ALUMNO, True, 3),
        _reserva(312, 212, ALUMNO, True, 2),
        _reserva(313, 213, ALUMNO, False, 2),
        _reserva(314, 214, ALUMNO, True, 2),
    ])
    db.add_all([
        WodBloque(id=BLOQUE_METCON, wod_id=WOD_CON_BLOQUES, orden=1,
                  titulo="Metcon 1", tipo_metcon="FOR TIME",
                  descripcion="21-15-9 Thrusters + Pull-ups"),
        WodBloque(id=BLOQUE_RM, wod_id=WOD_CON_BLOQUES, orden=2,
                  titulo="RM Final", tipo_metcon="RM",
                  descripcion="1RM Back Squat"),
        WodBloque(id=BLOQUE_SIN_ASISTENCIA, wod_id=WOD_SIN_ASISTENCIA, orden=1,
                  titulo="Metcon", tipo_metcon="AMRAP"),
        WodBloque(id=BLOQUE_BORRADOR, wod_id=WOD_BORRADOR, orden=1,
                  titulo="Metcon", tipo_metcon="FOR TIME"),
    ])
    db.commit()


@pytest.fixture()
def entorno(monkeypatch):
    """App real de los routers + SQLite en memoria con el escenario sembrado."""
    monkeypatch.setattr(alumnos, "ahora_santiago", lambda: AHORA)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TABLAS)
    Sesion = sessionmaker(bind=engine, expire_on_commit=False)
    db = Sesion()
    _sembrar(db)

    token = {
        "usuario_id": ALUMNO,
        "tenant_id": TENANT,
        "rol": "alumno",
        "correo": "bloques@test.com",
        "nombre": "Alumno Bloques",
        "activo": True,
        "estado": "activo",
    }

    app = FastAPI()
    app.include_router(alumnos.router, prefix="/api/v1/alumnos")
    # El router de wods YA trae su prefijo (`/api/v1/wods`) en `APIRouter(...)`.
    app.include_router(wods_api.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    cliente = TestClient(app)

    yield cliente, db

    db.close()
    engine.dispose()


def _post_bloque(cliente, wod_id, bloque_id, **payload):
    return cliente.post(
        f"/api/v1/alumnos/me/wods/{wod_id}/bloques/{bloque_id}/resultado",
        json=payload,
    )


def _post_wod(cliente, wod_id, **payload):
    return cliente.post(
        f"/api/v1/alumnos/me/wods/{wod_id}/resultado", json=payload)


def _pendientes(cliente):
    r = cliente.get("/api/v1/alumnos/me/wods-pendientes")
    assert r.status_code == 200, r.text
    return {w["wod_id"]: w for w in r.json()}


def _resultados(db, wod_id=None):
    q = db.query(WodResultado)
    if wod_id is not None:
        q = q.filter(WodResultado.wod_id == wod_id)
    return q.order_by(WodResultado.id).all()


# ── Regresión: WOD simple (sin bloques) ──────────────────────────────────────
def test_wod_sin_bloques_sigue_funcionando_igual(entorno):
    cliente, db = entorno

    r = _post_wod(cliente, WOD_SIMPLE, modo="rx", tiempo_segundos=300,
                  nota="como siempre")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["bloque_id"] is None
    assert cuerpo["peso_kg"] is None
    assert cuerpo["bloques"] == []

    # Segundo POST: MISMA fila (UPSERT), no un duplicado.
    r2 = _post_wod(cliente, WOD_SIMPLE, modo="escalado", tiempo_segundos=280)
    assert r2.status_code == 200, r2.text
    filas = _resultados(db, WOD_SIMPLE)
    assert len(filas) == 1
    assert filas[0].tiempo_segundos == 280
    assert filas[0].modo == "escalado"

    # El WOD simple ya registrado deja de estar pendiente.
    assert WOD_SIMPLE not in _pendientes(cliente)


# ── WOD con 2+ bloques ───────────────────────────────────────────────────────
def test_un_resultado_por_bloque_sin_chocar_con_la_unicidad(entorno):
    cliente, db = entorno

    r_metcon = _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_METCON,
                            modo="rx", tiempo_segundos=420)
    assert r_metcon.status_code == 200, r_metcon.text
    assert r_metcon.json()["bloque_id"] == BLOQUE_METCON

    r_rm = _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_RM,
                        modo="rx", peso_kg=120.5)
    assert r_rm.status_code == 200, r_rm.text
    assert r_rm.json()["bloque_id"] == BLOQUE_RM
    assert r_rm.json()["peso_kg"] == pytest.approx(120.5)

    # Dos resultados del MISMO WOD (uno por bloque): la unicidad no choca.
    filas = _resultados(db, WOD_CON_BLOQUES)
    assert len(filas) == 2
    assert {f.bloque_id for f in filas} == {BLOQUE_METCON, BLOQUE_RM}

    # Repetir el MISMO bloque actualiza la fila (UPSERT), no duplica.
    r_metcon2 = _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_METCON,
                             modo="escalado", tiempo_segundos=400)
    assert r_metcon2.status_code == 200, r_metcon2.text
    filas = _resultados(db, WOD_CON_BLOQUES)
    assert len(filas) == 2
    metcon = next(f for f in filas if f.bloque_id == BLOQUE_METCON)
    assert metcon.tiempo_segundos == 400
    assert metcon.modo == "escalado"


def test_duplicado_directo_en_el_mismo_bloque_es_rechazado(entorno):
    cliente, db = entorno
    r = _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_METCON,
                     modo="rx", tiempo_segundos=420)
    assert r.status_code == 200, r.text

    db.add(WodResultado(
        tenant_id=TENANT, alumno_id=ALUMNO, wod_id=WOD_CON_BLOQUES,
        bloque_id=BLOQUE_METCON, modo="rx", tiempo_segundos=999,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert len(_resultados(db, WOD_CON_BLOQUES)) == 1



# ── Candado de asistencia + publicación ──────────────────────────────────────
def test_candado_de_asistencia_tambien_aplica_al_bloque(entorno):
    cliente, db = entorno

    r = _post_bloque(cliente, WOD_SIN_ASISTENCIA, BLOQUE_SIN_ASISTENCIA,
                     modo="rx", rondas=5)
    assert r.status_code == 403, r.text
    assert "no asististe" in r.json()["detail"].lower()
    assert _resultados(db, WOD_SIN_ASISTENCIA) == []


def test_bloque_de_un_wod_borrador_no_se_puede_registrar(entorno):
    cliente, db = entorno

    r = _post_bloque(cliente, WOD_BORRADOR, BLOQUE_BORRADOR,
                     modo="rx", tiempo_segundos=300)
    assert r.status_code == 403, r.text
    assert _resultados(db, WOD_BORRADOR) == []


def test_bloque_de_otro_wod_devuelve_404(entorno):
    cliente, db = entorno

    r = _post_bloque(cliente, WOD_CON_BLOQUES, 999999,
                     modo="rx", tiempo_segundos=300)
    assert r.status_code == 404, r.text
    assert _resultados(db) == []


# ── Validación del campo según el tipo del BLOQUE ───────────────────────────
def test_bloque_rm_exige_peso_en_kg(entorno):
    cliente, _ = entorno

    r = _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_RM,
                     modo="rx", tiempo_segundos=300)
    assert r.status_code == 422, r.text
    assert "RM" in r.json()["detail"]


def test_bloque_por_tiempo_exige_tiempo(entorno):
    cliente, _ = entorno

    r = _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_METCON, modo="rx")
    assert r.status_code == 422, r.text


# ── Lectura: pendientes / historial / wods hoy ──────────────────────────────
def test_pendientes_incluye_bloques_y_espera_todos(entorno):
    cliente, _ = entorno

    pendientes = _pendientes(cliente)
    assert WOD_CON_BLOQUES in pendientes
    assert WOD_SIMPLE in pendientes
    bloques = pendientes[WOD_CON_BLOQUES]["bloques"]
    assert [b["id"] for b in bloques] == [BLOQUE_METCON, BLOQUE_RM]
    assert [b["orden"] for b in bloques] == [1, 2]
    assert pendientes[WOD_SIMPLE]["bloques"] == []

    # Con UN bloque registrado el WOD SIGUE pendiente (falta el RM).
    _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_METCON,
                 modo="rx", tiempo_segundos=420)
    assert WOD_CON_BLOQUES in _pendientes(cliente)

    # Con TODOS los bloques registrados deja de estar pendiente.
    _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_RM, modo="rx", peso_kg=100)
    assert WOD_CON_BLOQUES not in _pendientes(cliente)

    # El WOD simple conserva su regla: con un resultado ya no está pendiente.
    _post_wod(cliente, WOD_SIMPLE, modo="rx", tiempo_segundos=300)
    assert WOD_SIMPLE not in _pendientes(cliente)


def test_historial_devuelve_bloques_y_peso(entorno):
    cliente, _ = entorno

    _post_wod(cliente, WOD_SIMPLE, modo="rx", tiempo_segundos=300)
    _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_METCON,
                 modo="rx", tiempo_segundos=420)
    _post_bloque(cliente, WOD_CON_BLOQUES, BLOQUE_RM,
                 modo="escalado", peso_kg=80)

    r = cliente.get("/api/v1/alumnos/me/wods-historial")
    assert r.status_code == 200, r.text
    items = r.json()

    simple = next(i for i in items if i["wod_id"] == WOD_SIMPLE)
    assert simple["bloque_id"] is None
    assert simple["bloques"] == []

    rm = next(i for i in items
              if i["wod_id"] == WOD_CON_BLOQUES and i["bloque_id"] == BLOQUE_RM)
    assert rm["peso_kg"] == pytest.approx(80.0)
    assert [b["id"] for b in rm["bloques"]] == [BLOQUE_METCON, BLOQUE_RM]


def test_wods_hoy_devuelve_bloques(entorno, monkeypatch):
    cliente, _ = entorno
    # /wods/hoy usa la fecha de HOY; se ancla a AHORA para que sea determinista.
    monkeypatch.setattr(
        "app.utils.santiago.hoy_santiago", lambda: AHORA.date())

    r = cliente.get(f"/api/v1/wods/hoy?alumno_id={ALUMNO}")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo is not None
    assert cuerpo["id"] == WOD_CON_BLOQUES
    assert [b["id"] for b in cuerpo["bloques"]] == [BLOQUE_METCON, BLOQUE_RM]
    assert cuerpo["bloques"][0]["titulo"] == "Metcon 1"
    assert cuerpo["bloques"][1]["tipo_metcon"] == "RM"

