"""Plantillas de Fidelización (F1): catálogo por situación, sugerencia, preview y envío.

Por qué existe este archivo
---------------------------
La Acción Rápida del panel mandaba correos a ciegas: el admin elegía un texto genérico y nunca
veía el mensaje. La F1 lo cambia por "elegir plantilla → ver el correo EXACTO → enviar", y este
test fija las cuatro cosas que no pueden romperse:

  A. PURAS (sin BD): el catálogo (ids únicos, campos completos, **una entrada por situación** y
     un correo DISTINTO por plantilla), que el grupo reservado `beneficios` NO se anuncie (Fase
     2), que lo que viaja al frontend no filtre las funciones internas, que una plantilla
     desconocida NO caiga en un default y que el modo prueba (`EMAIL_MODO=noop`) sea la ÚNICA
     forma de no mandar de verdad.
  B. SERVICIO contra TEST (escribe y RESTAURA): un alumno temporal con una asistencia de 10 días
     atrás y una membresía vigente a 5 días. Fija los días de inactividad, el plan y el
     vencimiento del preview, el rechazo cuando NO hay membresía vigente, que un envío en modo
     prueba quede `simulado` (nunca `enviado`) sin dejar basura en el log de correos, y todo el
     comportamiento del catálogo por situación:
       * `sugerir()` aplica las reglas en orden y **dice cuál ganó** (renovación → plan sin usar →
         sin plan → riesgo alto → 15-30 → 7-14 → ninguna);
       * cada tramo RECHAZA los días que no le tocan, nombrando el que sí corresponde;
       * el mensaje de fondo es SOLO para quien ya no tiene plan vigente;
       * el correo de riesgo alto NO menciona la probabilidad del modelo (dato del admin).
  C. API (TestClient): catálogo y sugerencia sólo para el admin (alumno y coach 403), preview y
     envío del mismo mensaje (asunto y HTML IDÉNTICOS: si divergieran, el preview sería una
     mentira) y los errores claros (422 plantilla desconocida, 404 alumno de otro box, 400 sin
     datos o tramo mal elegido).

El modo prueba es obligatorio: cada test que ENVÍA pone `EMAIL_MODO=noop` antes (`monkeypatch`),
así que ningún caso puede mandar un correo real a nadie. El guard `is_test_db_url` falla CERRADO.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_fidelizacion_plantillas.py -q
"""
import sys
from datetime import date, datetime, time as _time, timedelta
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
# Con 10 días de inactividad el tramo que le corresponde es el TEMPRANO (7 a 14). Los otros
# tramos se prueban moviendo los datos REALES del escenario (no hay dos caminos paralelos).
P_TRAMO = svc.P_INACTIVIDAD_7_14
DIAS_TRAMO_MEDIO = 20   # 15 a 30 días
DIAS_TRAMO_LARGO = 40   # más de 30 días
DIAS_AL_DIA = 2         # menos del piso del catálogo: no le corresponde ninguna plantilla


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
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
            db.execute(text("DELETE FROM predictions_churn WHERE usuario_id = :a"),
                       {"a": alumno_id})
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


# ── Mover los datos REALES del escenario (un test = una situación) ────────────
# Los helpers escriben SÓLO el escenario temporal del test: su limpieza borra todo al salir.
def _fijar_dias(db, escenario, dias):
    """Última asistencia a `dias` días atrás (lo que decide los días de inactividad)."""
    db.execute(text("UPDATE asistencias SET fecha = :f WHERE usuario_id = :a"),
               {"f": hoy_santiago() - timedelta(days=dias), "a": escenario["alumno_id"]})
    db.commit()


def _fijar_vencimiento(db, escenario, dias):
    """Membresía que vence en `dias` días (o VENCIDA hace `abs(dias)` si es negativo)."""
    db.execute(text("UPDATE suscripciones SET fecha_expiracion = :f, "
                    "estado = CAST(:e AS estado_suscripcion) WHERE usuario_id = :a"),
               {"f": datetime.combine(hoy_santiago() + timedelta(days=dias), _time(12, 0),
                                      tzinfo=SANTIAGO),
                "e": "activo" if dias > 0 else "vencido",
                "a": escenario["alumno_id"]})
    db.commit()


def _anotar_riesgo(db, escenario, nivel="CRITICO", probabilidad=98.97):
    """Inserta la fila del data mart que hace que el modelo lo marque en riesgo."""
    return db.execute(text("""
        INSERT INTO predictions_churn (tenant_id, usuario_id, probabilidad_churn, riesgo_nivel,
                                       motivo, created_at)
        VALUES (:t, :u, :p, :n, 'TEST · modelo de riesgo', now()) RETURNING id"""),
        {"t": TENANT_ID, "u": escenario["alumno_id"], "p": probabilidad, "n": nivel}).scalar()


# ══════════════════════════════════════════════════════════════════════════════
# A. Reglas puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_el_catalogo_cubre_las_seis_situaciones():
    """Una entrada por SITUACIÓN, ids únicos, campos completos y el patrón que sale del catálogo."""
    ids = [p["id"] for p in svc.PLANTILLAS]

    assert ids == [svc.P_VENCIMIENTO, svc.P_PLAN_SIN_USAR, svc.P_INACTIVIDAD_7_14,
                   svc.P_INACTIVIDAD_15_30, svc.P_INACTIVIDAD_MAS_30, svc.P_RIESGO_ALTO,
                   # Fase 2: los dos correos del grupo `beneficios` (uno por tipo de regalo).
                   svc.P_BENEFICIO_DESCUENTO, svc.P_BENEFICIO_CLASES_GRATIS]
    assert len(ids) == len(set(ids)), "dos plantillas con el mismo id"
    assert svc.PATRON_IDS == "^(" + "|".join(ids) + ")$", \
        "el patrón del router sale del catálogo: una plantilla nueva no puede quedar fuera"
    for p in svc.PLANTILLAS:
        assert set(svc.CAMPOS_PUBLICOS).issubset(p), f"a {p['id']} le falta un campo público"
        assert p["label"] and p["descripcion"] and p["requiere"] and p["tipo_envio"]
        assert p["grupo"] in dict(svc.GRUPOS)
        assert p["tipo_envio"] in (svc.TIPO_INACTIVIDAD, svc.TIPO_VENCIMIENTO,
                                   svc.TIPO_RIESGO_ALTO, svc.TIPO_PLAN_SIN_USAR,
                                   svc.P_BENEFICIO_DESCUENTO, svc.P_BENEFICIO_CLASES_GRATIS)
        # Los correos de un regalo no se pueden armar sólo con el alumno: están declarados
        # como los que necesitan los datos del beneficio.
        assert (p["id"] in svc.PLANTILLAS_CON_DATOS) == (p["grupo"] == svc.GRUPO_BENEFICIOS)


def test_a2_beneficios_no_se_anuncia_hasta_la_fase_2():
    """El grupo `beneficios` está RESERVADO: existe, pero no viaja al frontend (criterio 6)."""
    grupos = [g["id"] for g in svc.grupos_disponibles()]

    assert grupos == [svc.GRUPO_GESTION]
    assert svc.GRUPO_BENEFICIOS in dict(svc.GRUPOS), "el grupo tiene que estar declarado"
    assert svc.grupo_disponible(svc.GRUPO_BENEFICIOS) is False
    assert all(p["grupo"] != svc.GRUPO_BENEFICIOS for p in svc.plantillas_disponibles())
    # Lo reservado no se anuncia, pero nada del catálogo PÚBLICO se pierde en el camino.
    assert [p["id"] for p in svc.plantillas_disponibles()] == [
        p["id"] for p in svc.PLANTILLAS if p["grupo"] != svc.GRUPO_BENEFICIOS]
    # Y al revés: las del grupo reservado existen (las usa el alta de un beneficio con
    # "Avisar por correo"), pero NO viajan en el catálogo del modal.
    assert [p["id"] for p in svc.PLANTILLAS if p["grupo"] == svc.GRUPO_BENEFICIOS] == \
        list(svc.PLANTILLAS_CON_DATOS)


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
    assert svc.plantilla(None) is None
    assert svc.normalizar_plantilla(P_TRAMO)["id"] == P_TRAMO

    with pytest.raises(svc.PlantillaDesconocida):
        svc.contexto(None, None, "no_existe")


def test_a5_el_modo_prueba_solo_se_activa_con_noop(monkeypatch):
    """En PRODUCCIÓN `EMAIL_MODO=noop` es la única forma de no mandar y un valor raro NO
    prueba nada; fuera de producción el fail-safe fuerza `noop` pase lo que pase."""
    # Producción: manda exactamente lo que diga EMAIL_MODO.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "EMAIL_MODO", "noop")
    assert email_service.es_modo_simulado() is True
    assert email_service.modo_envio() == email_service.MODO_NOOP

    monkeypatch.setattr(settings, "EMAIL_MODO", "real")
    assert email_service.es_modo_simulado() is False

    for raro in ("", "off", "simulado", "false"):
        monkeypatch.setattr(settings, "EMAIL_MODO", raro)
        assert email_service.modo_envio() == email_service.MODO_REAL, \
            f"'{raro}' NO puede dejar el sistema en modo prueba"

    # Fuera de producción el fail-safe fuerza `noop` aunque EMAIL_MODO diga "real".
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "EMAIL_MODO", "real")
    assert email_service.modo_envio() == email_service.MODO_NOOP


def test_a6_cada_plantilla_manda_un_correo_distinto():
    """Una entrada del catálogo = un correo. Tres plantillas con el mismo texto y distinta
    etiqueta son una lista que le miente al admin (regla 8).

    Se comparan los correos REALES de las cinco situaciones (asunto Y cuerpo), y además el
    cuerpo del mensaje de fondo cuando el plan venció (misma plantilla, otra frase).
    """
    catalogo = [
        email_service.render_email_vencimiento_plan("Ana Pérez", "Plan 12", date(2026, 10, 5)),
        email_service.render_email_fidelizacion_temprana("Ana Pérez", 10),
        email_service.render_email_fidelizacion("Ana Pérez", 20),
        email_service.render_email_fidelizacion_larga("Ana Pérez", 40),
        email_service.render_email_riesgo_alto("Ana Pérez", 40),
    ]
    asuntos = [asunto for asunto, _ in catalogo]
    variantes = catalogo + [email_service.render_email_fidelizacion_larga("Ana Pérez", 40, True)]

    assert len(set(asuntos)) == len(catalogo), f"hay dos plantillas con el mismo asunto: {asuntos}"
    assert len({html for _, html in variantes}) == len(variantes), \
        "hay dos variantes con el mismo cuerpo (una plantilla no puede ser copia de otra)"
    # Cada entrada del catálogo tiene su PROPIO render (no dos apuntando a la misma función).
    assert len({p["_render"] for p in svc.PLANTILLAS}) == len(svc.PLANTILLAS)


def test_a7_el_correo_no_le_dice_al_alumno_que_esta_en_riesgo():
    """Los números del modelo son del ADMIN (regla 9): al alumno se le escribe como persona.

    El correo de acompañamiento sale del MISMO dato que el panel (`predictions_churn`), pero el
    mensaje no menciona riesgo, probabilidad ni el modelo: un alumno que recibe "98 % de
    probabilidad de abandono" se va del box.
    """
    _, html = email_service.render_email_riesgo_alto("Ana Pérez", 45)

    for palabra in ("riesgo", "probabilidad", "churn", "modelo", "predicción", "prediccion"):
        assert palabra not in html.lower(), \
            f"el correo de acompañamiento no puede hablar de '{palabra}'"
    assert "45" in html, "el único número del correo son sus días reales sin venir"


# ══════════════════════════════════════════════════════════════════════════════
# B. El servicio contra TEST (escribe y RESTAURA)
# ══════════════════════════════════════════════════════════════════════════════
def test_b1_los_dias_de_inactividad_son_los_reales(db, escenario):
    """Ni 7 fijo ni 0: los días que salen de su ÚLTIMA asistencia (mínimo 1)."""
    alumno = _alumno(db, escenario)
    preview = svc.render(db, alumno, P_TRAMO)

    assert svc.dias_inactividad(db, alumno) == DIAS_ASISTENCIA
    assert preview["tipo_envio"] == "inactividad"
    assert preview["destinatario"] == escenario["correo"]
    assert preview["contexto"]["ultima_asistencia"] == escenario["fecha_asistencia"]
    assert preview["contexto"]["dias_inactividad"] == DIAS_ASISTENCIA
    # El correo dice el número REAL y lleva el layout de marca (uno solo para todos).
    assert str(DIAS_ASISTENCIA) in preview["html"]
    assert "URBAN" in preview["html"] and "Volver a entrenar" in preview["html"]
    assert preview["asunto"] and "Hace unos días" in preview["asunto"]


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
    assert svc.render(db, _alumno(db, escenario), P_TRAMO)["asunto"]


def test_b4_un_alumno_sin_correo_no_tiene_plantilla(db, escenario):
    """Sin destinatario no hay mensaje: se rechaza antes de intentar enviar."""
    alumno = _alumno(db, escenario)
    alumno.correo = ""
    db.commit()

    with pytest.raises(svc.PlantillaSinDatos):
        svc.render(db, alumno, P_TRAMO)


def test_b5_el_envio_en_modo_prueba_queda_simulado_y_no_ensucia_el_log(db, escenario,
                                                                      monkeypatch):
    """`noop`: no sale correo, pero el log lo dice (`simulado`), no `enviado`."""
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)
    antes = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM notificaciones_enviadas")).scalar()

    resultado = svc.enviar(db, _alumno(db, escenario), P_TRAMO)

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
    preview = svc.render(db, _alumno(db, escenario), P_TRAMO)
    resultado = svc.enviar(db, _alumno(db, escenario), P_TRAMO)

    assert resultado["ok"] is True
    assert capturado["html"] == preview["html"], "el envío tiene que usar el MISMO render"
    assert capturado["asunto"] == preview["asunto"]
    assert capturado["destinatario"] == preview["destinatario"]
    assert capturado["tipo"] == "inactividad"


# ── La sugerencia y el catálogo por situación ────────────────────────────────
def test_b7_la_sugerencia_es_la_de_la_situacion_real(db, escenario):
    """Regla 1: el plan por vencer gana (el escenario vence en 5 días y lleva 10 sin venir).

    La sugerencia también dice POR QUÉ: sin el motivo, el admin no puede decidir si está de
    acuerdo con lo que eligió el sistema.
    """
    sugerencia = svc.sugerir(db, _alumno(db, escenario))

    assert sugerencia["plantilla"] == svc.P_VENCIMIENTO
    assert sugerencia["regla"] == svc.P_VENCIMIENTO
    assert f"{DIAS_VENCIMIENTO} día" in sugerencia["motivo"]
    assert sugerencia["contexto"]["dias_para_vencer"] == DIAS_VENCIMIENTO
    assert sugerencia["label"] and sugerencia["tipo_envio"] == svc.TIPO_VENCIMIENTO


def test_b8_sin_plan_vigente_la_sugerencia_es_el_mensaje_de_fondo(db, escenario):
    """Regla 2: si dejó de pagar, el mensaje de fondo (aunque lleve pocos días sin venir)."""
    _fijar_vencimiento(db, escenario, -10)   # su membresía venció hace 10 días

    sugerencia = svc.sugerir(db, _alumno(db, escenario))

    assert sugerencia["plantilla"] == svc.P_INACTIVIDAD_MAS_30
    assert sugerencia["motivo"] == "No tiene un plan vigente."
    assert svc.tiene_membresia_vigente(db, _alumno(db, escenario)) is False


def test_b9_cada_tramo_le_corresponde_a_sus_dias(db, escenario):
    """Reglas 5-6: el tramo sale de los días REALES; con plan vigente, por encima de 30 días el
    mensaje de fondo NUNCA aplica (es para quien ya no tiene plan): si la última asistencia es
    ANTERIOR al inicio del plan, es `plan_sin_usar`."""
    _fijar_vencimiento(db, escenario, 60)     # un plan lejano: no compite con la inactividad

    _fijar_dias(db, escenario, DIAS_TRAMO_MEDIO)
    assert svc.sugerir(db, _alumno(db, escenario))["regla"] == svc.P_INACTIVIDAD_15_30

    # 40 días sin venir, pero el plan (inicio hace 25 días) arrancó DESPUÉS de su última
    # asistencia: compró el plan y no lo estrenó -> "plan sin usar", no el mensaje de fondo.
    _fijar_dias(db, escenario, DIAS_TRAMO_LARGO)
    assert svc.sugerir(db, _alumno(db, escenario))["regla"] == svc.P_PLAN_SIN_USAR

    _fijar_dias(db, escenario, DIAS_ASISTENCIA)
    assert svc.sugerir(db, _alumno(db, escenario))["regla"] == svc.P_INACTIVIDAD_7_14


def test_b10_el_riesgo_alto_gana_cuando_lo_marca_el_modelo(db, escenario):
    """Regla 3: paga hoy y no está por vencer, pero el modelo dice que se va."""
    _fijar_vencimiento(db, escenario, 60)
    _fijar_dias(db, escenario, DIAS_ASISTENCIA)

    # Sin predicción (o con el alumno fuera del riesgo alto) la regla no aplica.
    assert svc.sugerir(db, _alumno(db, escenario))["regla"] == svc.P_INACTIVIDAD_7_14
    _anotar_riesgo(db, escenario, nivel="BAJO", probabilidad=12.5)
    _anotar_riesgo(db, escenario, nivel="MEDIO", probabilidad=55.0)
    assert svc.sugerir(db, _alumno(db, escenario))["regla"] == svc.P_INACTIVIDAD_7_14

    # Con ALTO/CRÍTICO gana sobre el tramo de inactividad, y el dato viaja en el contexto.
    _anotar_riesgo(db, escenario, nivel="ALTO", probabilidad=77.4)
    sugerencia = svc.sugerir(db, _alumno(db, escenario))
    assert sugerencia["regla"] == svc.P_RIESGO_ALTO
    assert sugerencia["contexto"]["riesgo_nivel"] == "ALTO"
    assert sugerencia["contexto"]["probabilidad_churn"] == 77.4


def test_b11_un_alumno_al_dia_no_tiene_plantilla_sugerida(db, escenario):
    """Regla 6: no se inventa un correo para el que entrenó ayer (devuelve vacío, no un error)."""
    _fijar_vencimiento(db, escenario, 60)
    _fijar_dias(db, escenario, DIAS_AL_DIA)

    sugerencia = svc.sugerir(db, _alumno(db, escenario))

    assert sugerencia["plantilla"] is None
    assert sugerencia["regla"] == svc.REGLA_SIN_SITUACION
    assert "Entrenó hace" in sugerencia["motivo"]
    assert sugerencia["contexto"]["dias_inactividad"] == DIAS_AL_DIA


def test_b12_cada_tramo_rechaza_los_dias_que_no_le_tocan(db, escenario):
    """Regla 8: un tramo mal elegido se rechaza Y el error dice cuál corresponde."""
    _fijar_vencimiento(db, escenario, 60)
    _fijar_dias(db, escenario, DIAS_TRAMO_LARGO)

    with pytest.raises(svc.PlantillaSinDatos) as error:
        svc.render(db, _alumno(db, escenario), svc.P_INACTIVIDAD_7_14)
    assert str(DIAS_TRAMO_LARGO) in str(error.value)
    assert svc.P_INACTIVIDAD_MAS_30 in str(error.value), "el error tiene que decir cuál sí"

    _fijar_dias(db, escenario, DIAS_ASISTENCIA)
    with pytest.raises(svc.PlantillaSinDatos) as error2:
        svc.render(db, _alumno(db, escenario), svc.P_INACTIVIDAD_15_30)
    assert svc.P_INACTIVIDAD_7_14 in str(error2.value)

    # Y el tramo que SÍ corresponde a esos días se puede mandar.
    assert svc.render(db, _alumno(db, escenario), svc.P_INACTIVIDAD_7_14)["asunto"]


def test_b13_el_mensaje_de_fondo_es_solo_sin_plan_vigente(db, escenario):
    """El tramo de fondo aplica SOLO sin plan vigente: con plan activo se rechaza SIEMPRE."""
    with pytest.raises(svc.PlantillaSinDatos):
        svc.render(db, _alumno(db, escenario), svc.P_INACTIVIDAD_MAS_30)  # 10 días, plan vigente

    _fijar_vencimiento(db, escenario, -10)
    preview = svc.render(db, _alumno(db, escenario), svc.P_INACTIVIDAD_MAS_30)
    assert preview["contexto"]["plan_vencido"] is True
    assert "no tienes un plan vigente" in preview["html"]

    # Con plan vigente (aunque lleve más de 30 días) el mismo tramo NO se puede mandar.
    _fijar_vencimiento(db, escenario, 60)
    _fijar_dias(db, escenario, DIAS_TRAMO_LARGO)
    with pytest.raises(svc.PlantillaSinDatos):
        svc.render(db, _alumno(db, escenario), svc.P_INACTIVIDAD_MAS_30)


def test_b14_la_plantilla_de_riesgo_necesita_un_riesgo_real(db, escenario):
    """Sin predicción, o con un riesgo que no es alto, la plantilla se rechaza."""
    with pytest.raises(svc.PlantillaSinDatos) as error:
        svc.render(db, _alumno(db, escenario), svc.P_RIESGO_ALTO)
    assert "riesgo alto" in str(error.value)

    _anotar_riesgo(db, escenario, nivel="MEDIO", probabilidad=55.0)
    with pytest.raises(svc.PlantillaSinDatos):
        svc.render(db, _alumno(db, escenario), svc.P_RIESGO_ALTO)

    _anotar_riesgo(db, escenario, nivel="CRITICO", probabilidad=98.97)
    preview = svc.render(db, _alumno(db, escenario), svc.P_RIESGO_ALTO)

    assert preview["tipo_envio"] == svc.TIPO_RIESGO_ALTO
    assert preview["contexto"]["riesgo_nivel"] == "CRITICO"
    assert preview["contexto"]["probabilidad_churn"] == 98.97
    # El dato del modelo viaja al ADMIN (contexto del preview), no al correo del alumno.
    assert "98.97" not in preview["html"] and "CRITICO" not in preview["html"]


# ══════════════════════════════════════════════════════════════════════════════
# C. La API (misma app, TestClient)
# ══════════════════════════════════════════════════════════════════════════════
def test_c0_las_cuatro_rutas_estan_en_el_router():
    """El contrato de F1 son cinco rutas, colgando del mismo prefijo de Fidelización.

    Las cuatro de la F1 (catálogo, sugerencia, preview y envío) y la del LOTE que usa la columna
    "Recomendación" del panel (`/sugerencias`, F2): la columna y el modal tienen que salir de la
    misma regla, así que se piden por el mismo router.
    """
    assert [r.path for r in api.router.routes] == ["/plantillas", "/sugerir", "/sugerencias",
                                                  "/preview", "/enviar"]


def test_c1_el_catalogo_es_del_box_y_no_anuncia_beneficios(cliente, tokens):
    """Admin 200; alumno y coach 403 (la pantalla trae correos de todos los alumnos)."""
    r = cliente.get(f"{BASE}/plantillas", headers=tokens["admin"])

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["modo_envio"] in (email_service.MODO_REAL, email_service.MODO_NOOP)
    assert [g["id"] for g in cuerpo["grupos"]] == [svc.GRUPO_GESTION]
    assert [p["id"] for p in cuerpo["plantillas"]] == [p["id"] for p in svc.plantillas_disponibles()]
    assert "beneficios" not in [g["id"] for g in cuerpo["grupos"]]
    assert all(p["id"] not in svc.PLANTILLAS_CON_DATOS for p in cuerpo["plantillas"]), \
        "los correos de un regalo no son una plantilla de gestión: se mandan desde el beneficio"
    for p in cuerpo["plantillas"]:
        assert set(p) == set(svc.CAMPOS_PUBLICOS), "el JSON no puede llevar las funciones"

    assert cliente.get(f"{BASE}/plantillas", headers=tokens["alumno"]).status_code == 403
    assert cliente.get(f"{BASE}/plantillas", headers=tokens["coach"]).status_code == 403
    assert cliente.get(f"{BASE}/plantillas").status_code in (401, 403)


def test_c2_el_preview_es_exactamente_lo_que_se_manda(cliente, tokens, db, escenario,
                                                      monkeypatch):
    """Asunto y HTML idénticos entre preview y envío: si divergieran, el preview mentiría."""
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)
    cuerpo = {"plantilla": P_TRAMO, "alumno_id": escenario["alumno_id"]}
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
    """422 plantilla desconocida · 404 alumno de otro box · 400 plantilla sin datos o mal tramo."""
    alumno_id = escenario["alumno_id"]

    ajeno = cliente.post(f"{BASE}/preview",
                         json={"plantilla": P_TRAMO, "alumno_id": 999_999_999},
                         headers=tokens["admin"])
    assert ajeno.status_code == 404, ajeno.text

    desconocida = cliente.post(f"{BASE}/preview",
                               json={"plantilla": "no_existe", "alumno_id": alumno_id},
                               headers=tokens["admin"])
    assert desconocida.status_code == 422, "el patrón del catálogo tiene que rechazarla"

    # Un tramo que NO corresponde a sus días (10 días con la plantilla de 15 a 30): 400 y el
    # detalle dice cuál sí corresponde.
    mal_tramo = cliente.post(f"{BASE}/preview",
                             json={"plantilla": svc.P_INACTIVIDAD_15_30, "alumno_id": alumno_id},
                             headers=tokens["admin"])
    assert mal_tramo.status_code == 400, mal_tramo.text
    assert svc.P_INACTIVIDAD_7_14 in mal_tramo.json()["detail"]

    # Sin membresía vigente, la renovación se rechaza ANTES de intentar enviar.
    db.execute(text("UPDATE suscripciones SET estado = CAST('vencido' AS estado_suscripcion) "
                    "WHERE usuario_id = :a"), {"a": alumno_id})
    db.commit()
    sin_datos = cliente.post(f"{BASE}/enviar",
                             json={"plantilla": "vencimiento", "alumno_id": alumno_id},
                             headers=tokens["admin"])
    assert sin_datos.status_code == 400, sin_datos.text
    assert "membresía" in sin_datos.json()["detail"]


def test_c4_la_sugerencia_es_del_admin(cliente, tokens, escenario):
    """`POST /sugerir` es del admin (alumno y coach 403) y devuelve la regla que ganó."""
    cuerpo = {"alumno_id": escenario["alumno_id"]}

    r = cliente.post(f"{BASE}/sugerir", json=cuerpo, headers=tokens["admin"])

    assert r.status_code == 200, r.text
    sugerencia = r.json()
    # El escenario vence en DIAS_VENCIMIENTO días: la regla de renovación es la que gana.
    assert sugerencia["plantilla"] == svc.P_VENCIMIENTO
    assert sugerencia["regla"] == svc.P_VENCIMIENTO
    assert sugerencia["motivo"] and sugerencia["contexto"]["dias_para_vencer"] == DIAS_VENCIMIENTO

    assert cliente.post(f"{BASE}/sugerir", json=cuerpo,
                        headers=tokens["alumno"]).status_code == 403
    assert cliente.post(f"{BASE}/sugerir", json=cuerpo,
                        headers=tokens["coach"]).status_code == 403
    assert cliente.post(f"{BASE}/sugerir", json=cuerpo).status_code in (401, 403)
    # Un alumno de otro box es 404 (no se confirma que exista), igual que en el preview.
    ajeno = cliente.post(f"{BASE}/sugerir", json={"alumno_id": 999_999_999},
                         headers=tokens["admin"])
    assert ajeno.status_code == 404, ajeno.text
