"""Mis WODs (Performance Hub) — endpoints aislados con SQLite EN MEMORIA.

QUÉ CUBRE
---------
`GET /me/wods-pendientes`, `POST /me/wods/{wod_id}/resultado` y
`GET /me/wods-historial` contra la app REAL del router `alumnos` y una base SQLite
en memoria (sin red, sin TEST ni PROD). Se siembran clases/reservas reales para que
los filtros se ejerzan de verdad:

  * registrar con `reserva.asistio=True` → 200 y fila en `wod_resultados`;
  * sin asistencia (o sin reserva) → 403 y NO se escribe nada;
  * segundo registro del mismo WOD → actualiza la MISMA fila (UNIQUE + UPSERT);
  * pendientes excluye el WOD ya registrado, el no asistido y el de hace >14 días;
  * el mismo WOD dictado en dos clases aparece UNA vez y guarda la reserva más reciente;
  * validación de tiempo/rondas según `wods.tipo_metcon`.

    cd backend && py -3.12 -m pytest tests/test_mis_wods.py -q --noconftest
"""
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import alumnos
from app.core.dependencies import get_current_user
from app.db.database import Base, get_db
from app.models.clase import Clase
from app.models.disciplina import Disciplina
from app.models.horario_base import HorarioBase
from app.models.reserva import Reserva
from app.models.tenant import Tenant
from app.models.usuario import RolUsuario, Usuario
from app.models.wod import EstadoWod, Wod
from app.models.wod_resultado import WodResultado
from app.utils.santiago import hoy_santiago

TENANT = 1
ALUMNO = 10
OTRO_ALUMNO = 11
HOY = hoy_santiago()

# WODs del escenario (ids fijos para leer los tests sin sorpresas).
WOD_FOR_TIME = 101          # dos clases con asistencia (la más reciente manda)
WOD_AMRAP_CON_RESULTADO = 102
WOD_VIEJO = 103             # fuera de la ventana de 14 días
WOD_SIN_ASISTENCIA = 104    # reserva con asistio=False
WOD_SIN_RESERVA = 105
WOD_SIN_TIPO = 106          # tipo_metcon NULL: acepta tiempo o rondas

TABLAS = [
    Tenant.__table__, Usuario.__table__, Disciplina.__table__,
    HorarioBase.__table__, Wod.__table__, Clase.__table__,
    Reserva.__table__, WodResultado.__table__,
]


def _wod(id_, fecha, titulo, tipo_metcon, principal="Trabajo prescrito"):
    return Wod(id=id_, tenant_id=TENANT, fecha=fecha, titulo=titulo,
               wod_principal=principal, tipo_metcon=tipo_metcon,
               estado=EstadoWod.publicado, activo=True)


def _clase(id_, wod_id, fecha):
    return Clase(id=id_, tenant_id=TENANT, horario_base_id=1, disciplina_id=1,
                 fecha=fecha, hora_inicio=time(9), hora_fin=time(10),
                 cupo_maximo=20, asistentes_confirmados=0, cancelada=False,
                 wod_id=wod_id)


def _reserva(id_, clase_id, alumno_id, asistio, horas_atras):
    return Reserva(
        id=id_, tenant_id=TENANT, clase_id=clase_id, alumno_id=alumno_id,
        fecha_reserva=datetime.now(UTC) - timedelta(hours=horas_atras),
        asistio=asistio, tokens_gastados=0, estado="reserved",
    )


def _sembrar(db):
    """Padrón mínimo + WODs/clases/reservas que cubren todos los bordes."""
    db.add(Tenant(id=TENANT, nombre="Box Test", subdomain="box-test",
                  public_id="box-test-public-id", activo=True))
    db.add_all([
        Usuario(id=ALUMNO, tenant_id=TENANT, rut="11111111-1",
                nombre="Alumno Test", correo="alumno@test.com",
                password_hash="x", rol=RolUsuario.alumno,
                activo=True, estado="activo"),
        Usuario(id=OTRO_ALUMNO, tenant_id=TENANT, rut="22222222-2",
                nombre="Otro Alumno", correo="otro@test.com",
                password_hash="x", rol=RolUsuario.alumno,
                activo=True, estado="activo"),
    ])
    db.add(Disciplina(id=1, tenant_id=TENANT, nombre="CrossFit",
                      es_open_box=False, requiere_coach=True, activo=True))
    db.add(HorarioBase(id=1, tenant_id=TENANT, disciplina_id=1, dia_semana=0,
                       hora_inicio=time(9), hora_fin=time(10),
                       cupo_maximo=20, activo=True))
    db.add_all([
        _wod(WOD_FOR_TIME, HOY - timedelta(days=1), "Fran", "FOR TIME",
             "21-15-9 Thrusters + Pull-ups"),
        _wod(WOD_AMRAP_CON_RESULTADO, HOY - timedelta(days=2), "AMRAP 12",
             "AMRAP", "12 min: 10 wall balls + 10 box jumps"),
        _wod(WOD_VIEJO, HOY - timedelta(days=20), "WOD viejo", "FOR TIME"),
        _wod(WOD_SIN_ASISTENCIA, HOY - timedelta(days=2), "No fui", "AMRAP"),
        _wod(WOD_SIN_RESERVA, HOY - timedelta(days=3), "Sin reserva", "FOR TIME"),
        _wod(WOD_SIN_TIPO, HOY - timedelta(days=4), "Libre", None,
             "Sin tipo de metcon"),
    ])
    db.add_all([
        _clase(201, WOD_FOR_TIME, HOY - timedelta(days=3)),
        _clase(202, WOD_FOR_TIME, HOY - timedelta(days=1)),
        _clase(203, WOD_AMRAP_CON_RESULTADO, HOY - timedelta(days=2)),
        _clase(204, WOD_VIEJO, HOY - timedelta(days=20)),
        _clase(205, WOD_SIN_ASISTENCIA, HOY - timedelta(days=2)),
        _clase(206, WOD_SIN_RESERVA, HOY - timedelta(days=3)),
        _clase(207, WOD_SIN_TIPO, HOY - timedelta(days=4)),
    ])
    db.add_all([
        # Mismo WOD en dos clases: la reserva 302 es la MÁS RECIENTE.
        _reserva(301, 201, ALUMNO, True, 72),
        _reserva(302, 202, ALUMNO, True, 1),
        _reserva(303, 203, ALUMNO, True, 30),
        _reserva(304, 204, ALUMNO, True, 20),       # fuera de los 14 días
        _reserva(305, 205, ALUMNO, False, 5),       # no asistió
        _reserva(306, 207, ALUMNO, True, 10),       # WOD sin tipo
        _reserva(307, 201, OTRO_ALUMNO, True, 72),  # asistencia de OTRO alumno
    ])
    # Este WOD ya tiene resultado: no debe volver a "pendiente".
    db.add(WodResultado(
        id=401, tenant_id=TENANT, alumno_id=ALUMNO,
        wod_id=WOD_AMRAP_CON_RESULTADO, reserva_id=303,
        modo="escalado", rondas=5, reps_extra=3, nota="Última ronda incompleta",
    ))
    db.commit()


@pytest.fixture()
def entorno():
    """App real del router + SQLite en memoria con un escenario sembrado."""
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
        "correo": "alumno@test.com",
        "nombre": "Alumno Test",
        "activo": True,
        "estado": "activo",
    }

    app = FastAPI()
    app.include_router(alumnos.router, prefix="/api/v1/alumnos")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    cliente = TestClient(app)

    yield cliente, db

    db.close()
    engine.dispose()


def _post_resultado(cliente, wod_id, **payload):
    return cliente.post(f"/api/v1/alumnos/me/wods/{wod_id}/resultado",
                        json=payload)


def _pendientes(cliente):
    r = cliente.get("/api/v1/alumnos/me/wods-pendientes")
    assert r.status_code == 200, r.text
    return r.json()


def _ids_pendientes(cliente):
    return [item["wod_id"] for item in _pendientes(cliente)]



# ── POST: asistencia real ────────────────────────────────────────────────────
def test_registrar_con_asistencia_crea_el_resultado(entorno):
    cliente, db = entorno

    r = _post_resultado(cliente, WOD_FOR_TIME, modo="rx",
                        tiempo_segundos=845, nota="Buen ritmo")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wod_id"] == WOD_FOR_TIME
    assert body["modo"] == "rx"
    assert body["tiempo_segundos"] == 845
    assert body["nota"] == "Buen ritmo"
    # La asistencia que respalda es la MÁS RECIENTE (302), no la primera (301).
    assert body["reserva_id"] == 302

    fila = db.query(WodResultado).filter_by(
        alumno_id=ALUMNO, wod_id=WOD_FOR_TIME).one()
    assert (fila.modo, fila.tiempo_segundos, fila.reserva_id) == ("rx", 845, 302)


def test_sin_asistencia_no_puede_registrar_403(entorno):
    cliente, db = entorno

    sin_asistir = _post_resultado(cliente, WOD_SIN_ASISTENCIA,
                                  modo="rx", rondas=5)
    sin_reserva = _post_resultado(cliente, WOD_SIN_RESERVA,
                                  modo="rx", tiempo_segundos=600)

    for r in (sin_asistir, sin_reserva):
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == "No puedes registrar un WOD al que no asististe"
    assert db.query(WodResultado).filter(
        WodResultado.alumno_id == ALUMNO,
        WodResultado.wod_id.in_([WOD_SIN_ASISTENCIA, WOD_SIN_RESERVA]),
    ).count() == 0


def test_registrar_dos_veces_actualiza_la_misma_fila(entorno):
    cliente, db = entorno

    primera = _post_resultado(cliente, WOD_FOR_TIME, modo="rx",
                              tiempo_segundos=845)
    segunda = _post_resultado(cliente, WOD_FOR_TIME, modo="escalado",
                              tiempo_segundos=900, nota="Corregido")

    assert primera.status_code == segunda.status_code == 200
    assert segunda.json()["id"] == primera.json()["id"], "UPSERT, no duplicado"

    filas = db.query(WodResultado).filter_by(
        alumno_id=ALUMNO, wod_id=WOD_FOR_TIME).all()
    assert len(filas) == 1
    assert (filas[0].modo, filas[0].tiempo_segundos, filas[0].nota) == \
        ("escalado", 900, "Corregido")


def test_amrap_guarda_rondas_y_reps_extra(entorno):
    cliente, db = entorno

    r = _post_resultado(cliente, WOD_AMRAP_CON_RESULTADO, modo="rx",
                        rondas=7, reps_extra=12)

    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["rondas"], body["reps_extra"], body["tiempo_segundos"]) == \
        (7, 12, None)
    fila = db.query(WodResultado).filter_by(
        alumno_id=ALUMNO, wod_id=WOD_AMRAP_CON_RESULTADO).one()
    assert (fila.rondas, fila.reps_extra, fila.modo) == (7, 12, "rx")


# ── Validación por tipo de metcon ────────────────────────────────────────────
def test_tipo_metcon_exige_el_campo_correcto(entorno):
    cliente, db = entorno

    for_time_sin_tiempo = _post_resultado(cliente, WOD_FOR_TIME, modo="rx",
                                          rondas=5)
    amrap_sin_rondas = _post_resultado(cliente, WOD_AMRAP_CON_RESULTADO,
                                      modo="rx", tiempo_segundos=600)

    assert for_time_sin_tiempo.status_code == 422, for_time_sin_tiempo.text
    assert amrap_sin_rondas.status_code == 422, amrap_sin_rondas.text
    assert db.query(WodResultado).filter_by(
        alumno_id=ALUMNO, wod_id=WOD_FOR_TIME).count() == 0


def test_tipo_metcon_null_acepta_tiempo_o_rondas(entorno):
    cliente, _ = entorno

    r = _post_resultado(cliente, WOD_SIN_TIPO, modo="escalado",
                        tiempo_segundos=600)

    assert r.status_code == 200, r.text
    assert r.json()["tiempo_segundos"] == 600


def test_sin_tiempo_ni_rondas_es_422(entorno):
    cliente, _ = entorno

    r = _post_resultado(cliente, WOD_SIN_TIPO, modo="rx", nota="Solo nota")

    assert r.status_code == 422, r.text


def test_grupo_resultado_tolera_sufijos_del_tipo_metcon():
    """`tipo_metcon` es texto libre: "AMRAP 12" / "FOR TIME (cap)" cuentan igual."""
    from app.api.v1.alumnos import _grupo_resultado

    assert _grupo_resultado("AMRAP 12") == "rondas"
    assert _grupo_resultado("EMOM 10") == "rondas"
    assert _grupo_resultado("for_time (cap 20)") == "tiempo"
    assert _grupo_resultado(None) == "libre"




# ── GET pendientes ───────────────────────────────────────────────────────────
def test_pendientes_trae_asistidos_sin_resultado(entorno):
    cliente, _ = entorno

    ids = _ids_pendientes(cliente)

    assert WOD_FOR_TIME in ids
    assert WOD_SIN_TIPO in ids
    # El mismo WOD dictado en dos clases aparece UNA sola vez.
    assert ids.count(WOD_FOR_TIME) == 1


def test_pendientes_excluye_el_wod_ya_registrado(entorno):
    cliente, _ = entorno

    ids = _ids_pendientes(cliente)

    assert WOD_AMRAP_CON_RESULTADO not in ids


def test_pendientes_excluye_sin_asistencia_y_fuera_de_ventana(entorno):
    cliente, _ = entorno

    ids = _ids_pendientes(cliente)

    assert WOD_SIN_ASISTENCIA not in ids
    assert WOD_SIN_RESERVA not in ids
    assert WOD_VIEJO not in ids


def test_pendientes_devuelve_la_prescripcion_para_el_formulario(entorno):
    cliente, _ = entorno

    fila = next(i for i in _pendientes(cliente) if i["wod_id"] == WOD_FOR_TIME)

    assert set(fila) == {"wod_id", "fecha", "titulo", "wod_principal",
                         "tipo_metcon"}
    assert fila["titulo"] == "Fran"
    assert fila["tipo_metcon"] == "FOR TIME"
    assert "Thrusters" in fila["wod_principal"]


def test_pendientes_no_mezcla_los_datos_de_otro_alumno(entorno):
    """La asistencia del otro alumno no vuelve "pendiente" un WOD del mío."""
    cliente, db = entorno
    # El otro alumno asistió al WOD viejo, pero eso no lo hace pendiente para MÍ.
    assert WOD_VIEJO not in _ids_pendientes(cliente)
    assert db.query(Reserva).filter_by(
        alumno_id=OTRO_ALUMNO, asistio=True).count() == 1


# ── GET historial ────────────────────────────────────────────────────────────
def test_historial_lista_los_resultados_con_la_prescripcion(entorno):
    cliente, _ = entorno

    _post_resultado(cliente, WOD_FOR_TIME, modo="rx", tiempo_segundos=845)
    r = cliente.get("/api/v1/alumnos/me/wods-historial")

    assert r.status_code == 200, r.text
    historial = r.json()
    # WOD_FOR_TIME es más reciente que el AMRAP que ya estaba registrado.
    assert [item["wod_id"] for item in historial] == [
        WOD_FOR_TIME, WOD_AMRAP_CON_RESULTADO]
    primero = historial[0]
    assert primero["titulo"] == "Fran"
    assert primero["tipo_metcon"] == "FOR TIME"
    assert primero["modo"] == "rx"
    assert primero["tiempo_segundos"] == 845
    assert primero["reserva_id"] == 302
    segundo = historial[1]
    assert (segundo["modo"], segundo["rondas"], segundo["reps_extra"]) == \
        ("escalado", 5, 3)


def test_historial_vacio_devuelve_lista_vacia(entorno):
    cliente, db = entorno
    db.query(WodResultado).delete()
    db.commit()

    r = cliente.get("/api/v1/alumnos/me/wods-historial")

    assert r.status_code == 200, r.text
    assert r.json() == []


def test_el_modelo_queda_registrado_para_create_all():
    """El bootstrap de TEST (`Base.metadata.create_all`) tiene que crear la tabla."""
    from app.models import WodResultado as Exportado
    assert Exportado is WodResultado
    assert "wod_resultados" in Base.metadata.tables


