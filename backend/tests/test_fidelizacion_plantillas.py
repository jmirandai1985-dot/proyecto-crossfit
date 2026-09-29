"""Plantillas de Fidelización (F1): catálogo, preview y envío — SIN mandar correo real.

Por qué existe este archivo
---------------------------
La Acción Rápida del panel mandaba correos a ciegas: el admin elegía `inactividad` o
`vencimiento` y nunca veía el mensaje. La F1 lo cambia por "elegir plantilla → ver el correo
EXACTO → enviar", y este test fija las tres cosas que no pueden romperse:

  A. PURAS (sin BD): el catálogo (ids únicos, campos completos), que el grupo reservado
     `beneficios` NO se anuncie (Fase 2), que lo que viaja al frontend no filtre las funciones
     internas, que una plantilla desconocida NO caiga en un default y que el modo prueba
     (`EMAIL_MODO=noop`) sea la ÚNICA forma de no mandar de verdad.
  B. SERVICIO contra TEST (escribe y RESTAURA): un alumno temporal con una asistencia de 10 días
     atrás y una membresía vigente a 5 días. Fija los días de inactividad, el plan y el
     vencimiento del preview, el rechazo cuando NO hay membresía vigente y que un envío en modo
     prueba quede `simulado` (nunca `enviado`) sin dejar basura en el log de correos.
  C. API (TestClient): catálogo sólo para el admin (alumno y coach 403), preview y envío del
     mismo mensaje (asunto y HTML IDÉNTICOS: si divergieran, el preview sería una mentira) y los
     errores claros (422 plantilla desconocida, 404 alumno de otro box, 400 sin datos).

El modo prueba es obligatorio: cada test que ENVÍA pone `EMAIL_MODO=noop` antes (`monkeypatch`),
así que ningún caso puede mandar un correo real a nadie. El guard `is_test_db_url` falla CERRADO.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_fidelizacion_plantillas.py -q
"""
import sys
from datetime import datetime, time as _time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1 import fidelizacion_plantillas as api                    # noqa: E402
from app.core.config import settings                                     # noqa: E402
from app.core.security import create_access_token                        # noqa: E402
from app.services import email_service                                   # noqa: E402
from app.services import fidelizacion_plantillas as svc                  # noqa: E402
from app.utils.santiago import SANTIAGO, hoy_santiago                    # noqa: E402

TENANT_ID = 1
BASE = "/api/v1/fidelizacion"

# El escenario: asistió hace DIAS_ASISTENCIA y su plan vence en DIAS_VENCIMIENTO días.
DIAS_ASISTENCIA = 10
DIAS_VENCIMIENTO = 5


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(definí ENVIRONMENT=test / revisá .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin levantar servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def tokens(db):
    """Tokens REALES (mismo camino que el navegador) para admin, alumno y coach de TEST."""
    def _buscar(rol):
        fila = db.execute(text(
            "SELECT id FROM usuarios WHERE tenant_id = :t AND rol = :r "
            "AND estado = 'activo' ORDER BY id LIMIT 1"),
            {"t": TENANT_ID, "r": rol}).first()
        return int(fila[0]) if fila else None

    ids = {rol: _buscar(rol) for rol in ("administrador", "alumno", "coach")}
    faltan = [rol for rol, valor in ids.items() if valor is None]
    if faltan:
        pytest.skip(f"TEST no tiene usuarios de estos roles: {', '.join(faltan)}")

    def _token(rol, correo):
        return {"Authorization": "Bearer " + create_access_token({
            "usuario_id": ids[rol], "tenant_id": TENANT_ID, "rol": rol, "correo": correo})}

    return {
        "ids": ids,
        "admin": _token("administrador", "admin@test.com"),
        "alumno": _token("alumno", "alumno@test.com"),
        "coach": _token("coach", "coach@test.com"),
    }



# ── Escenario (escribe en TEST y RESTAURA) ────────────────────────────────────
@pytest.fixture
def escenario(db):
    """Alumno temporal: asistió hace `DIAS_ASISTENCIA` y su plan vence en `DIAS_VENCIMIENTO`.

    Se anclan las fechas a "hoy" (Chile) porque los números del correo son días, no meses.
    Borra TODO lo que creó, incluidas las filas del log de correos que apunten a su correo.
    """
    hoy = hoy_santiago()
    fecha_asistencia = hoy - timedelta(days=DIAS_ASISTENCIA)
    vence = hoy + timedelta(days=DIAS_VENCIMIENTO)
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    correo = f"fidelizacion.{sufijo}@test.local"
    plan_nombre = f"Plan Fidelizacion TEST {sufijo}"
    alumno_id = plan_id = None
    try:
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                                  estado, created_at)
            VALUES (:t, :r, 'Alumno Fidelizacion TEST', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"97{sufijo[-8:]}-9", "c": correo,
             "alta": datetime.combine(hoy - timedelta(days=60), _time(12, 0), tzinfo=SANTIAGO)}
        ).scalar()

        db.execute(text("""
            INSERT INTO asistencias (tenant_id, usuario_id, fecha, clase, presente)
            VALUES (:t, :u, :f, 'WOD', true)"""),
            {"t": TENANT_ID, "u": alumno_id, "f": fecha_asistencia})

        plan_id = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo)
            VALUES (:t, :n, 12, false, 33000, 30, true) RETURNING id"""),
            {"t": TENANT_ID, "n": plan_nombre}).scalar()

        db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, CAST('activo' AS estado_suscripcion), 12, 12, :i, :f)"""),
            {"t": TENANT_ID, "u": alumno_id, "p": plan_id,
             "i": datetime.combine(hoy - timedelta(days=25), _time(12, 0), tzinfo=SANTIAGO),
             "f": datetime.combine(vence, _time(12, 0), tzinfo=SANTIAGO)})

        db.commit()
        yield {"alumno_id": alumno_id, "correo": correo, "plan_id": plan_id,
               "plan_nombre": plan_nombre, "fecha_asistencia": fecha_asistencia, "vence": vence}
    finally:
        db.rollback()
        try:
            db.execute(text("DELETE FROM notificaciones_enviadas WHERE destinatario_correo = :c"),
                       {"c": correo})
            db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"),
                       {"a": alumno_id})
            db.execute(text("DELETE FROM asistencias WHERE usuario_id = :a"), {"a": alumno_id})
            if plan_id:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
            if alumno_id:
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
            db.commit()
        except Exception as e:      # el borrado no debe tapar el fallo real del test
            db.rollback()
            print(f"\n[WARN] no se pudo limpiar el escenario: {e}")


def _alumno(db, escenario):
    from app.models.usuario import Usuario
    return db.query(Usuario).filter(Usuario.id == escenario["alumno_id"]).first()


# ══════════════════════════════════════════════════════════════════════════════
# A. Reglas puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_el_catalogo_es_consistente():
    """Ids únicos, campos completos y un `tipo_envio` que el log de correos ya conoce."""
    ids = [p["id"] for p in svc.PLANTILLAS]

    assert len(ids) == len(set(ids)), "dos plantillas con el mismo id"
    assert svc.P_INACTIVIDAD in ids and svc.P_VENCIMIENTO in ids
    assert svc.PATRON_IDS == "^(inactividad|vencimiento)$"
    for p in svc.PLANTILLAS:
        assert set(svc.CAMPOS_PUBLICOS).issubset(p), f"a {p['id']} le falta un campo público"
        assert p["label"] and p["descripcion"] and p["requiere"] and p["tipo_envio"]
        assert p["grupo"] in dict(svc.GRUPOS)


def test_a2_beneficios_no_se_anuncia_hasta_la_fase_2():
    """El grupo `beneficios` está RESERVADO: existe, pero no viaja al frontend (criterio 6)."""
    grupos = [g["id"] for g in svc.grupos_disponibles()]

    assert grupos == [svc.GRUPO_GESTION]
    assert svc.GRUPO_BENEFICIOS in dict(svc.GRUPOS), "el grupo tiene que estar declarado"
    assert svc.grupo_disponible(svc.GRUPO_BENEFICIOS) is False
    assert all(p["grupo"] != svc.GRUPO_BENEFICIOS for p in svc.plantillas_disponibles())
    assert [p["id"] for p in svc.plantillas_disponibles()] == [svc.P_INACTIVIDAD,
                                                               svc.P_VENCIMIENTO]


def test_a3_lo_publico_no_filtra_las_funciones_internas():
    """El catálogo tiene las funciones (son su definición); el JSON NO puede llevarlas."""
    for p in svc.plantillas_disponibles():
        assert set(p) == set(svc.CAMPOS_PUBLICOS)
        assert not any(clave.startswith("_") for clave in p)

    for p in svc.PLANTILLAS:
        assert callable(p["_render"]) and callable(p["_contexto"])


def test_a4_una_plantilla_desconocida_no_cae_en_un_default():
    """A diferencia de las secciones del Historial, acá NO hay fallback: se rechaza."""
    assert svc.normalizar_plantilla("no_existe") is None
    assert svc.plantilla("pase_regreso") is None
    assert svc.normalizar_plantilla(svc.P_INACTIVIDAD)["id"] == svc.P_INACTIVIDAD

    with pytest.raises(svc.PlantillaDesconocida):
        svc.contexto(None, None, "no_existe")


def test_a5_el_modo_prueba_solo_se_activa_con_noop(monkeypatch):
    """`EMAIL_MODO=noop` es la única forma de no mandar; un valor raro NO prueba nada."""
    monkeypatch.setattr(settings, "EMAIL_MODO", "noop")
    assert email_service.es_modo_simulado() is True
    assert email_service.modo_envio() == email_service.MODO_NOOP

    monkeypatch.setattr(settings, "EMAIL_MODO", "real")
    assert email_service.es_modo_simulado() is False

    for raro in ("", "off", "simulado", "false"):
        monkeypatch.setattr(settings, "EMAIL_MODO", raro)
        assert email_service.modo_envio() == email_service.MODO_REAL, \
            f"'{raro}' NO puede dejar el sistema en modo prueba"


# ══════════════════════════════════════════════════════════════════════════════
# B. El servicio contra TEST (escribe y RESTAURA)
# ══════════════════════════════════════════════════════════════════════════════
def test_b1_los_dias_de_inactividad_son_los_reales(db, escenario):
    """Ni 7 fijo ni 0: los días que salen de su ÚLTIMA asistencia (mínimo 1)."""
    alumno = _alumno(db, escenario)
    preview = svc.render(db, alumno, svc.P_INACTIVIDAD)

    assert svc.dias_inactividad(db, alumno) == DIAS_ASISTENCIA
    assert preview["tipo_envio"] == "inactividad"
    assert preview["destinatario"] == escenario["correo"]
    assert preview["contexto"]["ultima_asistencia"] == escenario["fecha_asistencia"]
    assert preview["contexto"]["dias_inactividad"] == DIAS_ASISTENCIA
    # El correo dice el número REAL y lleva el layout de marca (uno solo para todos).
    assert str(DIAS_ASISTENCIA) in preview["html"]
    assert "URBAN" in preview["html"] and "Volver a entrenar" in preview["html"]
    assert preview["asunto"] and "Te extrañamos" in preview["asunto"]


def test_b2_el_vencimiento_sale_de_la_membresia_vigente(db, escenario):
    preview = svc.render(db, _alumno(db, escenario), svc.P_VENCIMIENTO)

    assert preview["tipo_envio"] == "vencimiento"
    assert preview["contexto"]["plan"] == escenario["plan_nombre"]
    assert preview["contexto"]["fecha_expiracion"] == escenario["vence"]
    assert preview["contexto"]["dias_restantes"] == DIAS_VENCIMIENTO
    assert escenario["plan_nombre"] in preview["asunto"]
    assert escenario["vence"].strftime("%d/%m/%Y") in preview["html"]


def test_b3_sin_membresia_vigente_la_renovacion_se_rechaza(db, escenario):
    """Una membresía VENCIDA no sirve para ofrecer una renovación (criterio 5)."""
    db.execute(text("UPDATE suscripciones SET estado = CAST('vencido' AS estado_suscripcion) "
                    "WHERE usuario_id = :a"), {"a": escenario["alumno_id"]})
    db.commit()

    with pytest.raises(svc.PlantillaSinDatos) as error:
        svc.render(db, _alumno(db, escenario), svc.P_VENCIMIENTO)
    assert "membresía vigente" in str(error.value)
    assert svc.suscripcion_vigente(db, _alumno(db, escenario)) is None
    # La de inactividad NO depende de la membresía: sigue disponible.
    assert svc.render(db, _alumno(db, escenario), svc.P_INACTIVIDAD)["asunto"]


def test_b4_un_alumno_sin_correo_no_tiene_plantilla(db, escenario):
    """Sin destinatario no hay mensaje: se rechaza antes de intentar enviar."""
    alumno = _alumno(db, escenario)
    alumno.correo = ""
    db.commit()

    with pytest.raises(svc.PlantillaSinDatos):
        svc.render(db, alumno, svc.P_INACTIVIDAD)


def test_b5_el_envio_en_modo_prueba_queda_simulado_y_no_ensucia_el_log(db, escenario,
                                                                      monkeypatch):
    """`noop`: no sale correo, pero el log lo dice (`simulado`), no `enviado`."""
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)
    antes = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM notificaciones_enviadas")).scalar()

    resultado = svc.enviar(db, _alumno(db, escenario), svc.P_INACTIVIDAD)

    assert resultado["ok"] is True
    assert resultado["estado"] == email_service.ESTADO_SIMULADO
    assert resultado["modo_envio"] == email_service.MODO_NOOP
    assert resultado["destinatario"] == escenario["correo"]
    assert resultado["detalle_error"] is None

    filas = db.execute(text("SELECT estado, destinatario_correo, tipo, tenant_id "
                            "FROM notificaciones_enviadas WHERE id > :antes ORDER BY id"),
                       {"antes": antes}).all()
    assert len(filas) == 1, "el envío simulado tiene que dejar UNA fila (el intento)"
    assert filas[0][0] == email_service.ESTADO_SIMULADO, "un simulado NO puede figurar enviado"
    assert filas[0][1] == escenario["correo"]
    assert filas[0][2] == "inactividad" and filas[0][3] == TENANT_ID

    # El test no deja rastro en el log de correos de TEST.
    db.execute(text("DELETE FROM notificaciones_enviadas WHERE id > :antes"), {"antes": antes})
    db.commit()


def test_b6_lo_que_se_manda_es_lo_que_se_ve(db, escenario, monkeypatch):
    """El envío usa EXACTAMENTE el render del preview (se captura el correo que sale).

    Es la garantía de fondo de la F1 y no se puede mirar desde la API (la respuesta del
    envío no devuelve el HTML: el admin ya lo vio en el preview). Acá se intercepta la
    puerta de salida y se compara con lo que devolvió el preview.
    """
    capturado = {}
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)

    def _capturar(destinatario, asunto, html, alumno_id=None, tipo="", tenant_id=None):
        capturado.update(destinatario=destinatario, asunto=asunto, html=html, tipo=tipo)
        return True

    monkeypatch.setattr(email_service, "enviar_renderizado", _capturar)
    preview = svc.render(db, _alumno(db, escenario), svc.P_INACTIVIDAD)
    resultado = svc.enviar(db, _alumno(db, escenario), svc.P_INACTIVIDAD)

    assert resultado["ok"] is True
    assert capturado["html"] == preview["html"], "el envío tiene que usar el MISMO render"
    assert capturado["asunto"] == preview["asunto"]
    assert capturado["destinatario"] == preview["destinatario"]
    assert capturado["tipo"] == "inactividad"


# ══════════════════════════════════════════════════════════════════════════════
# C. La API (misma app, TestClient)
# ══════════════════════════════════════════════════════════════════════════════
def test_c0_las_tres_rutas_estan_en_el_router():
    """El contrato de F1 son tres rutas, colgando del mismo prefijo de Fidelización."""
    assert [r.path for r in api.router.routes] == ["/plantillas", "/preview", "/enviar"]


def test_c1_el_catalogo_es_del_box_y_no_anuncia_beneficios(cliente, tokens):
    """Admin 200; alumno y coach 403 (la pantalla trae correos de todos los alumnos)."""
    r = cliente.get(f"{BASE}/plantillas", headers=tokens["admin"])

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["modo_envio"] in (email_service.MODO_REAL, email_service.MODO_NOOP)
    assert [g["id"] for g in cuerpo["grupos"]] == [svc.GRUPO_GESTION]
    assert [p["id"] for p in cuerpo["plantillas"]] == [svc.P_INACTIVIDAD, svc.P_VENCIMIENTO]
    assert "beneficios" not in [g["id"] for g in cuerpo["grupos"]]
    for p in cuerpo["plantillas"]:
        assert set(p) == set(svc.CAMPOS_PUBLICOS), "el JSON no puede llevar las funciones"

    assert cliente.get(f"{BASE}/plantillas", headers=tokens["alumno"]).status_code == 403
    assert cliente.get(f"{BASE}/plantillas", headers=tokens["coach"]).status_code == 403
    assert cliente.get(f"{BASE}/plantillas").status_code in (401, 403)


def test_c2_el_preview_es_exactamente_lo_que_se_manda(cliente, tokens, db, escenario,
                                                      monkeypatch):
    """Asunto y HTML idénticos entre preview y envío: si divergieran, el preview mentiría."""
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)
    cuerpo = {"plantilla": "inactividad", "alumno_id": escenario["alumno_id"]}
    antes = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM notificaciones_enviadas")).scalar()

    preview = cliente.post(f"{BASE}/preview", json=cuerpo, headers=tokens["admin"])
    envio = cliente.post(f"{BASE}/enviar", json=cuerpo, headers=tokens["admin"])

    assert preview.status_code == 200, preview.text
    assert envio.status_code == 200, envio.text
    p, e = preview.json(), envio.json()
    assert p["destinatario"] == escenario["correo"] == e["destinatario"]
    assert p["asunto"] == e["asunto"], "el preview tiene que ser el mismo asunto"
    assert p["html"], "el preview tiene que traer el HTML del correo"
    assert p["contexto"]["dias_inactividad"] == DIAS_ASISTENCIA
    # El envío NO devuelve el HTML (el admin ya lo vio): que sea el mismo render lo fija
    # `test_b6_lo_que_se_manda_es_lo_que_se_ve` interceptando la puerta de salida.
    assert "html" not in e
    assert e["ok"] is True and e["estado"] == email_service.ESTADO_SIMULADO
    assert e["tipo_envio"] == "inactividad"
    # El envío de prueba NO puede cerrar sin dejar rastro de lo que pasó.
    assert db.execute(text("SELECT COUNT(*) FROM notificaciones_enviadas "
                           "WHERE id > :antes AND estado = :estado"),
                      {"antes": antes, "estado": email_service.ESTADO_SIMULADO}).scalar() == 1

    db.execute(text("DELETE FROM notificaciones_enviadas WHERE id > :antes"), {"antes": antes})
    db.commit()


def test_c3_los_errores_son_claros(cliente, tokens, db, escenario):
    """422 plantilla desconocida · 404 alumno de otro box · 400 plantilla sin datos."""
    alumno_id = escenario["alumno_id"]

    ajeno = cliente.post(f"{BASE}/preview",
                         json={"plantilla": "inactividad", "alumno_id": 999_999_999},
                         headers=tokens["admin"])
    assert ajeno.status_code == 404, ajeno.text

    desconocida = cliente.post(f"{BASE}/preview",
                               json={"plantilla": "pase_regreso", "alumno_id": alumno_id},
                               headers=tokens["admin"])
    assert desconocida.status_code == 422, "el patrón del catálogo tiene que rechazarla"

    # Sin membresía vigente, la renovación se rechaza ANTES de intentar enviar.
    db.execute(text("UPDATE suscripciones SET estado = CAST('vencido' AS estado_suscripcion) "
                    "WHERE usuario_id = :a"), {"a": alumno_id})
    db.commit()
    sin_datos = cliente.post(f"{BASE}/enviar",
                             json={"plantilla": "vencimiento", "alumno_id": alumno_id},
                             headers=tokens["admin"])
    assert sin_datos.status_code == 400, sin_datos.text
    assert "membresía" in sin_datos.json()["detail"]
