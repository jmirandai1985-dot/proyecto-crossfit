"""API de Beneficios (F2 de Fidelización): lo que el panel puede hacer y lo que NO.

Qué cubre (todo visto desde HTTP, la misma app que sirve el navegador)
---------------------------------------------------------------------
  * ACL y tenant: alumno y coach no entran; el alumno/beneficio de otro box es 404.
  * El alta: descuento sin correo, y clases gratis que abren un PASE (plan no comercial) o se
    SUMAN al plan vigente del alumno.
  * La regla del regalo único: un segundo beneficio VIVO del mismo tipo es **409 con el texto de
    `aviso_vigente()`** — el mismo que el panel muestra en la fila — y no crea ni toca créditos.
  * La anulación: el motivo es OBLIGATORIO (422 sin él) y revoca el pase; repetirla es 409.
  * El correo: la vista previa NO crea nada y el envío real (en `EMAIL_MODO=noop`) manda
    EXACTAMENTE el mismo render y deja el beneficio ligado a su fila del log.
  * El listado de la pestaña Beneficios: filtros por estado/tipo/alumno/búsqueda y el resumen
    (las métricas de la F4) contando lo mismo que la tabla.
  * La sugerencia en LOTE (la columna "Recomendación") dice lo mismo que la de a uno.

Reglas de test del proyecto: se escribe y se RESTAURA en la rama TEST (nunca PROD), no se manda
correo real y nada depende de datos que ya existan en TEST (todo sale del escenario).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                                    # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.services import beneficios_service as svc                      # noqa: E402
from app.services import email_service                                  # noqa: E402
from app.services import fidelizacion_plantillas as plantillas          # noqa: E402
from app.utils.santiago import SANTIAGO                                 # noqa: E402

TENANT_ID = 1
CLASES = 3
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=SANTIAGO)
BASE_BENEFICIOS = "/api/v1/beneficios"


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
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


@pytest.fixture
def escenario(db):
    """Dos alumnos de prueba, el PLAN del pase (no comercial) y un plan de pago.

    El plan del pase se crea `activo=false` y `es_comercial=false` a propósito: un plan regalo no se
    vende y no cuenta como membresía (corrección A), pero el pase tiene que dar acceso igual (el
    criterio NO es `planes.activo`, corrección C). El plan comercial es "el plan del alumno": con él
    vigente, las clases gratis se SUMAN a su suscripción. Borra TODO lo que creó.
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    ids = []
    plan_pase = plan_pago = None
    try:
        for n in (1, 2):
            ids.append(db.execute(text("""
                INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                                      estado, created_at)
                VALUES (:t, :r, :nom, :c, 'x', 'alumno', true, 'activo', :alta)
                RETURNING id"""),
                {"t": TENANT_ID, "r": f"9{n}{sufijo[-7:]}-{n}",
                 "nom": f"Alumno Beneficios API TEST {n}",
                 "c": f"beneficios.api{n}.{sufijo}@test.local",
                 "alta": datetime.combine(T0.date() - timedelta(days=120), T0.time(),
                                          tzinfo=SANTIAGO)}).scalar())
        plan_pase = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, :cr, false, 25000, 14, false, false) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Pase de regreso TEST {sufijo}", "cr": CLASES}).scalar()
        plan_pago = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 10, false, 40000, 30, true, true) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Plan mensual TEST {sufijo}"}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        raise

    yield {"db": db, "alumno_id": ids[0], "otro_id": ids[1], "plan_pase_id": plan_pase,
           "plan_pago_id": plan_pago, "sufijo": sufijo,
           "correo": f"beneficios.api1.{sufijo}@test.local"}

    # ── limpieza (siempre, aunque el test falle) ──
    db.rollback()
    try:
        for i in ids:
            db.execute(text("DELETE FROM beneficios WHERE alumno_id = :a"), {"a": i})
            db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"), {"a": i})
            db.execute(text("DELETE FROM notificaciones_enviadas WHERE alumno_id = :a"), {"a": i})
            db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": i})
        for p in (plan_pase, plan_pago):
            if p is not None:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": p})
        db.commit()
    except Exception as e:      # el borrado no debe tapar el fallo real del test
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de beneficios: {e}")


def _valor_descuento(db):
    """Un % válido para este box, sin depender de cómo esté configurado el tope en TEST."""
    return min(10, svc.tope_descuento(db, TENANT_ID))


def _beneficios_de(db, alumno_id):
    """Las filas de la tabla para ESE alumno (los tests no dependen de lo que ya haya en TEST)."""
    return db.execute(text("SELECT id, estado::text, valor, plan_id, suscripcion_id, "
                           "notificacion_id FROM beneficios WHERE alumno_id = :a ORDER BY id"),
                      {"a": alumno_id}).all()


def _creditos(db, suscripcion_id):
    return db.execute(text("SELECT creditos_disponibles FROM suscripciones WHERE id = :i"),
                      {"i": suscripcion_id}).scalar()


def _dar(cliente, cabeceras, alumno_id, tipo, valor, **extra):
    """POST /beneficios con el cuerpo mínimo + lo que pase el test."""
    cuerpo = {"alumno_id": alumno_id, "tipo": tipo, "valor": valor, **extra}
    return cliente.post(BASE_BENEFICIOS, json=cuerpo, headers=cabeceras)


# ══════════════════════════════════════════════════════════════════════════════
# A. Las rutas y el ACL (no tocan datos: no necesitan escenario)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_las_rutas_de_beneficios_existen():
    """Las rutas del panel (y la de sugerencias en lote) están registradas en la app."""
    from app.main import app
    rutas = [r.path for r in app.routes]

    assert f"{BASE_BENEFICIOS}/tipos" in rutas
    assert f"{BASE_BENEFICIOS}/alumno/{{alumno_id}}" in rutas
    assert f"{BASE_BENEFICIOS}/preview" in rutas
    assert f"{BASE_BENEFICIOS}/{{beneficio_id}}/anular" in rutas
    assert BASE_BENEFICIOS in rutas, "el listado y el alta comparten la ruta (GET y POST)"
    assert "/api/v1/fidelizacion/sugerencias" in rutas


def test_a2_solo_el_admin_del_box_entra(cliente, tokens):
    """Alumno y coach NO entran: dar un regalo es una decisión del admin del box (403)."""
    peticiones = [
        ("get", f"{BASE_BENEFICIOS}/tipos", None),
        ("get", f"{BASE_BENEFICIOS}/alumno/999999", None),
        ("get", BASE_BENEFICIOS, None),
        ("post", BASE_BENEFICIOS, {"alumno_id": 999999, "tipo": "descuento", "valor": 10}),
        ("post", f"{BASE_BENEFICIOS}/preview",
         {"alumno_id": 999999, "tipo": "descuento", "valor": 10}),
        ("post", f"{BASE_BENEFICIOS}/999999/anular", {"motivo": "prueba de ACL"}),
        ("post", "/api/v1/fidelizacion/sugerencias", {"alumno_ids": [999999]}),
    ]
    for rol in ("alumno", "coach"):
        for metodo, url, cuerpo in peticiones:
            llamada = getattr(cliente, metodo)
            respuesta = (llamada(url, headers=tokens[rol]) if cuerpo is None
                         else llamada(url, json=cuerpo, headers=tokens[rol]))
            assert respuesta.status_code == 403, \
                f"{rol} no puede {metodo.upper()} {url} (dio {respuesta.status_code})"


def test_a3_el_admin_sin_token_no_entra(cliente):
    """Sin `Authorization` la respuesta es 401/403 (nunca 200): acá hay dinero y créditos."""
    respuesta = cliente.get(f"{BASE_BENEFICIOS}/tipos")
    assert respuesta.status_code in (401, 403)


# ══════════════════════════════════════════════════════════════════════════════
# B. Contra TEST (escribe y RESTAURA)
# ══════════════════════════════════════════════════════════════════════════════
def test_b1_los_tipos_traen_el_catalogo_y_el_tope_del_box(cliente, tokens, db):
    """El modal no inventa el máximo: lo pregunta (y viene del catálogo del servicio)."""
    respuesta = cliente.get(f"{BASE_BENEFICIOS}/tipos", headers=tokens["admin"])

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert [t["id"] for t in datos["tipos"]] == list(svc.TIPOS_VALIDOS)
    assert datos["tope_descuento"] == svc.tope_descuento(db, TENANT_ID)
    # El valor y su unidad viajan juntos: 3 no significa lo mismo en un % que en clases.
    por_tipo = {t["id"]: t for t in datos["tipos"]}
    assert por_tipo[svc.TIPO_DESCUENTO]["unidad"] == "pct"
    assert por_tipo[svc.TIPO_CLASES_GRATIS]["unidad"] == "clases"
    assert por_tipo[svc.TIPO_CLASES_GRATIS]["valores"] == list(svc.CLASES_VALIDAS)
    # La ventana viaja como DATO (el panel la muestra, no la decide).
    assert datos["dias_vigencia"] == svc.DIAS_VIGENCIA


def test_b2_un_descuento_sin_correo_queda_vigente_y_no_deja_log(cliente, tokens, db, escenario):
    """El regalo vale igual sin correo (no es obligatorio) y la fila nace `ofrecido`/vigente."""
    valor = _valor_descuento(db)
    antes_log = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM notificaciones_enviadas")).scalar()

    respuesta = _dar(cliente, tokens["admin"], escenario["alumno_id"],
                     svc.TIPO_DESCUENTO, valor)

    assert respuesta.status_code == 201
    datos = respuesta.json()
    beneficio = datos["beneficio"]
    assert datos["correo"] is None
    assert beneficio["estado"] == "vigente" and beneficio["estado_bd"] == "ofrecido"
    assert beneficio["puede_anular"] is True
    assert beneficio["notificacion_id"] is None
    assert beneficio["descuento_clp"] is None, "el descuento se calcula al usarlo, no al darlo"
    assert beneficio["dias_hasta_uso"] is None
    assert beneficio["unidad"] == "pct" and beneficio["valor"] == valor
    # La ventana la fija el SERVICIO (15 días), no el frontend.
    assert beneficio["vigente_hasta"].startswith(str(svc.ventana().date()))

    filas = _beneficios_de(db, escenario["alumno_id"])
    assert len(filas) == 1 and filas[0].notificacion_id is None
    assert db.execute(text("SELECT COALESCE(MAX(id), 0) FROM notificaciones_enviadas")
                      ).scalar() == antes_log, \
        "sin 'Avisar por correo' no se manda ni se registra ningún correo"


def test_b3_un_segundo_regalo_vivo_del_mismo_tipo_es_409_con_el_aviso_del_panel(
        cliente, tokens, db, escenario):
    """Regla 9 del servicio: un solo regalo vivo por alumno y tipo (y el texto es el del panel)."""
    valor = _valor_descuento(db)
    primero = _dar(cliente, tokens["admin"], escenario["alumno_id"], svc.TIPO_DESCUENTO, valor)
    assert primero.status_code == 201

    # El panel lo puede saber ANTES de intentar crear: el aviso viaja en la consulta del alumno.
    estado = cliente.get(f"{BASE_BENEFICIOS}/alumno/{escenario['alumno_id']}",
                         headers=tokens["admin"]).json()
    assert estado["avisos"][svc.TIPO_DESCUENTO] is not None
    assert f"{valor} %" in estado["avisos"][svc.TIPO_DESCUENTO]
    assert estado["avisos"][svc.TIPO_CLASES_GRATIS] is None, "otro tipo no bloquea nada"
    assert [v["id"] for v in estado["vivos"]] == [primero.json()["beneficio"]["id"]]

    segundo = _dar(cliente, tokens["admin"], escenario["alumno_id"], svc.TIPO_DESCUENTO, valor)

    assert segundo.status_code == 409
    # El 409 y la fila del panel dicen LO MISMO (mismo `aviso_vigente`): ni un día de diferencia.
    assert segundo.json()["detail"] == estado["avisos"][svc.TIPO_DESCUENTO]
    assert len(_beneficios_de(db, escenario["alumno_id"])) == 1, \
        "un alta rechazada no puede dejar una segunda fila"


def test_b4_sin_plan_vigente_las_clases_abren_el_pase(cliente, tokens, db, escenario):
    """Regla 3: sin plan vigente la alta NECESITA el plan del pase, y con él abre el acceso."""
    sin_plan = _dar(cliente, tokens["admin"], escenario["alumno_id"],
                    svc.TIPO_CLASES_GRATIS, CLASES)

    assert sin_plan.status_code == 400, "sin plan del pase no hay acceso que dar"
    assert "plan_id" in sin_plan.json()["detail"]
    assert _beneficios_de(db, escenario["alumno_id"]) == []

    con_pase = _dar(cliente, tokens["admin"], escenario["alumno_id"],
                    svc.TIPO_CLASES_GRATIS, CLASES, plan_id=escenario["plan_pase_id"])

    assert con_pase.status_code == 201
    beneficio = con_pase.json()["beneficio"]
    assert beneficio["estado"] == "vigente" and beneficio["valor"] == CLASES
    filas = _beneficios_de(db, escenario["alumno_id"])
    assert len(filas) == 1
    pase = filas[0]
    assert pase.plan_id == escenario["plan_pase_id"]
    assert pase.suscripcion_id is not None, "el pase se materializa al darlo (sin aceptación)"
    assert _creditos(db, pase.suscripcion_id) == CLASES
    # El pase es un plan NO comercial: no cuenta como membresía (corrección A) pero da acceso (C).
    assert db.execute(text("SELECT es_comercial FROM planes WHERE id = :p"),
                      {"p": escenario["plan_pase_id"]}).scalar() is False
    estado = cliente.get(f"{BASE_BENEFICIOS}/alumno/{escenario['alumno_id']}",
                         headers=tokens["admin"]).json()
    assert estado["plan_vigente"] is None, "un pase no es 'el plan del alumno'"
    assert estado["planes_pase"], "el modal tiene que poder ofrecer el plan del pase"


def test_b5_el_tipo_y_el_valor_se_validan_antes_de_regalar(cliente, tokens, db, escenario):
    """Un typo en el tipo es 422; pasarse del tope del box es 400 (y no deja fila ni créditos)."""
    malo = _dar(cliente, tokens["admin"], escenario["alumno_id"], "pase_gratis", 3)
    assert malo.status_code == 422
    assert "descuento" in malo.json()["detail"], "el mensaje dice qué tipos existen"

    tope = svc.tope_descuento(db, TENANT_ID)
    sobre_tope = _dar(cliente, tokens["admin"], escenario["alumno_id"],
                      svc.TIPO_DESCUENTO, tope + 1)
    assert sobre_tope.status_code == 400, "el tope del box no se negocia desde el panel"
    assert f"hasta {tope}%" in sobre_tope.json()["detail"], \
        "el mensaje dice el máximo que autoriza ESTE box"
    assert _beneficios_de(db, escenario["alumno_id"]) == [], "un valor inválido no crea nada"


def test_b6_el_listado_filtra_y_el_resumen_cuenta_lo_mismo(cliente, tokens, db, escenario):
    """La pestaña Beneficios: filtros por estado/tipo/alumno/búsqueda y resumen sobre lo filtrado.

    Todo se consulta filtrando por los alumnos del ESCENARIO: en TEST puede haber beneficios de
    otras corridas y el test no puede depender de lo que ya esté ahí.
    """
    valor = _valor_descuento(db)
    vivo = _dar(cliente, tokens["admin"], escenario["alumno_id"],
                svc.TIPO_DESCUENTO, valor).json()["beneficio"]
    clases = _dar(cliente, tokens["admin"], escenario["otro_id"],
                  svc.TIPO_CLASES_GRATIS, CLASES,
                  plan_id=escenario["plan_pase_id"]).json()["beneficio"]
    anulado = _dar(cliente, tokens["admin"], escenario["alumno_id"],
                   svc.TIPO_CLASES_GRATIS, CLASES,
                   plan_id=escenario["plan_pase_id"]).json()["beneficio"]
    cliente.post(f"{BASE_BENEFICIOS}/{anulado['id']}/anular",
                 json={"motivo": "prueba del listado"}, headers=tokens["admin"])

    filtrado = cliente.get(BASE_BENEFICIOS, params={"alumno_id": escenario["alumno_id"]},
                           headers=tokens["admin"]).json()
    assert {i["estado"] for i in filtrado["items"]} == {"vigente", "anulado"}
    assert filtrado["total"] == 2
    assert filtrado["resumen"]["por_estado"] == {"vigente": 1, "usado": 0, "vencido": 0, "anulado": 1}
    assert filtrado["resumen"]["tasa_uso_pct"] == 0.0, "todavía no lo usó nadie"
    assert filtrado["resumen"]["dias_hasta_uso_promedio"] is None, \
        "sin usados no hay promedio (no se inventa un 0)"
    assert filtrado["resumen"]["descuento_clp_total"] == 0
    assert (filtrado["resumen"]["con_correo"], filtrado["resumen"]["sin_correo"]) == (0, 2)

    vigentes = cliente.get(BASE_BENEFICIOS,
                           params={"alumno_id": escenario["alumno_id"], "estado": "vigente"},
                           headers=tokens["admin"]).json()
    assert [i["id"] for i in vigentes["items"]] == [vivo["id"]]

    por_tipo = cliente.get(BASE_BENEFICIOS,
                           params={"alumno_id": escenario["otro_id"], "tipo": svc.TIPO_CLASES_GRATIS},
                           headers=tokens["admin"]).json()
    assert [i["id"] for i in por_tipo["items"]] == [clases["id"]]
    assert por_tipo["items"][0]["alumno_nombre"].startswith("Alumno Beneficios API TEST")
    assert por_tipo["items"][0]["tipo_label"] == svc.etiqueta(svc.TIPO_CLASES_GRATIS)

    # La búsqueda es por nombre o correo (el del escenario es único en toda la tabla).
    buscado = cliente.get(BASE_BENEFICIOS, params={"q": escenario["correo"]},
                          headers=tokens["admin"]).json()
    assert buscado["total"] == 2
    assert {i["alumno_id"] for i in buscado["items"]} == {escenario["alumno_id"]}

    # Un estado fuera del catálogo es un 422 del cliente, no una lista vacía silenciosa.
    assert cliente.get(BASE_BENEFICIOS, params={"estado": "cualquiera"},
                       headers=tokens["admin"]).status_code == 422

    # La paginación no cambia el resumen (se calcula sobre el filtro completo, no sobre la página).
    una = cliente.get(BASE_BENEFICIOS,
                      params={"alumno_id": escenario["alumno_id"], "por_pagina": 1},
                      headers=tokens["admin"]).json()
    assert len(una["items"]) == 1 and una["total"] == 2
    assert una["resumen"] == filtrado["resumen"]


def test_b7_anular_necesita_motivo_y_revoca_lo_entregado(cliente, tokens, db, escenario):
    """El motivo es obligatorio y anular le QUITA al alumno lo que el regalo le había dado."""
    creado = _dar(cliente, tokens["admin"], escenario["alumno_id"],
                  svc.TIPO_CLASES_GRATIS, CLASES,
                  plan_id=escenario["plan_pase_id"]).json()["beneficio"]
    fila = _beneficios_de(db, escenario["alumno_id"])[0]
    assert _creditos(db, fila.suscripcion_id) == CLASES

    # Sin motivo (o con uno demasiado corto) la petición ni llega al servicio: 422 del cuerpo.
    for cuerpo in ({}, {"motivo": ""}, {"motivo": "  "}):
        respuesta = cliente.post(f"{BASE_BENEFICIOS}/{creado['id']}/anular",
                                 json=cuerpo, headers=tokens["admin"])
        assert respuesta.status_code == 422
    assert _creditos(db, fila.suscripcion_id) == CLASES, "un intento rechazado no toca el saldo"

    anulada = cliente.post(f"{BASE_BENEFICIOS}/{creado['id']}/anular",
                           json={"motivo": "se le cargó un plan pagado"},
                           headers=tokens["admin"])
    assert anulada.status_code == 200
    datos = anulada.json()["beneficio"]
    assert datos["estado"] == "anulado" and datos["puede_anular"] is False
    assert datos["anulado_motivo"] == "se le cargó un plan pagado"
    assert datos["anulado_at"] is not None
    assert _creditos(db, fila.suscripcion_id) == 0, "el pase se queda sin los créditos del regalo"
    assert db.execute(text("SELECT estado::text FROM beneficios WHERE id = :i"),
                      {"i": creado["id"]}).scalar() == "anulado"

    repetida = cliente.post(f"{BASE_BENEFICIOS}/{creado['id']}/anular",
                            json={"motivo": "otra vez"}, headers=tokens["admin"])
    assert repetida.status_code == 409, "lo anulado no se anula dos veces"


def test_b8_lo_que_el_alumno_ya_uso_no_se_anula(cliente, tokens, db, escenario):
    """Lo usado no se revierte: la clase ya se tomó (la historia no se reescribe)."""
    from app.models.beneficio import Beneficio as ModeloBeneficio

    usado = _dar(cliente, tokens["admin"], escenario["otro_id"],
                 svc.TIPO_DESCUENTO, _valor_descuento(db)).json()["beneficio"]
    objeto = db.query(ModeloBeneficio).filter(ModeloBeneficio.id == usado["id"]).first()
    svc.usar(db, objeto, precio_lista_clp=40000)

    respuesta = cliente.post(f"{BASE_BENEFICIOS}/{usado['id']}/anular",
                             json={"motivo": "no correspondía"}, headers=tokens["admin"])

    assert respuesta.status_code == 409
    assert "usado" in respuesta.json()["detail"]
    assert db.execute(text("SELECT estado::text FROM beneficios WHERE id = :i"),
                      {"i": usado["id"]}).scalar() == "usado"


def test_b9_la_vista_previa_del_correo_no_crea_ni_manda_nada(cliente, tokens, db, escenario):
    """El admin ve el correo EXACTO antes de dar el regalo (y sin dar nada)."""
    valor = _valor_descuento(db)
    antes_log = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM notificaciones_enviadas")).scalar()
    antes = len(_beneficios_de(db, escenario["alumno_id"]))

    respuesta = cliente.post(f"{BASE_BENEFICIOS}/preview",
                             json={"alumno_id": escenario["alumno_id"],
                                   "tipo": svc.TIPO_DESCUENTO, "valor": valor},
                             headers=tokens["admin"])

    assert respuesta.status_code == 200
    preview = respuesta.json()
    assert preview["plantilla"] == plantillas.P_BENEFICIO_DESCUENTO
    assert preview["destinatario"] == escenario["correo"]
    assert f"{valor} %" in preview["asunto"] and f"{valor} %" in preview["html"]
    # La fecha que promete el correo es la ventana REAL del alta (no una que invente el panel).
    assert svc.ventana().date().strftime("%d-%m-%Y") in preview["html"]

    assert len(_beneficios_de(db, escenario["alumno_id"])) == antes, "el preview no crea el regalo"
    assert db.execute(text("SELECT COALESCE(MAX(id), 0) FROM notificaciones_enviadas")
                      ).scalar() == antes_log, "el preview no manda ni registra correo"

    # Un tipo que no está en el catálogo se rechaza (422) en vez de renderizar cualquier cosa.
    assert cliente.post(f"{BASE_BENEFICIOS}/preview",
                        json={"alumno_id": escenario["alumno_id"],
                              "tipo": "pase_gratis", "valor": 1},
                        headers=tokens["admin"]).status_code == 422


def test_b10_avisar_por_correo_manda_el_mismo_correo_y_lo_liga(cliente, tokens, db, escenario,
                                                               monkeypatch):
    """Con "Avisar por correo" el envío sale (simulado) y el beneficio queda LIGADO a su fila."""
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)
    valor = _valor_descuento(db)
    preview = cliente.post(f"{BASE_BENEFICIOS}/preview",
                           json={"alumno_id": escenario["alumno_id"],
                                 "tipo": svc.TIPO_DESCUENTO, "valor": valor},
                           headers=tokens["admin"]).json()
    antes_log = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM notificaciones_enviadas")).scalar()

    respuesta = _dar(cliente, tokens["admin"], escenario["alumno_id"], svc.TIPO_DESCUENTO, valor,
                     avisar_por_correo=True)

    assert respuesta.status_code == 201
    datos = respuesta.json()
    correo = datos["correo"]
    assert correo["estado"] == email_service.ESTADO_SIMULADO
    assert correo["modo_envio"] == email_service.MODO_NOOP
    assert correo["detalle_error"] is None
    assert correo["asunto"] == preview["asunto"], "lo que se manda es el MISMO render del preview"
    assert correo["notificacion_id"] is not None
    assert datos["beneficio"]["notificacion_id"] == correo["notificacion_id"], \
        "el beneficio queda ligado al correo que lo anunció (es lo que mide la F4)"

    filas = db.execute(text("SELECT id, tipo, estado, destinatario_correo "
                            "FROM notificaciones_enviadas WHERE id > :a ORDER BY id"),
                       {"a": antes_log}).all()
    assert len(filas) == 1, "un correo, una fila en el log"
    assert filas[0].id == correo["notificacion_id"]
    assert filas[0].tipo == plantillas.P_BENEFICIO_DESCUENTO
    assert filas[0].estado == email_service.ESTADO_SIMULADO, "un simulado NO puede figurar enviado"
    assert filas[0].destinatario_correo == escenario["correo"]
    # El resumen de la pestaña Beneficios cuenta el correo (la F4 lo necesita).
    listado = cliente.get(BASE_BENEFICIOS, params={"alumno_id": escenario["alumno_id"]},
                          headers=tokens["admin"]).json()
    assert listado["resumen"]["con_correo"] == 1


def test_b11_otro_box_o_algo_inexistente_es_404(cliente, tokens, escenario):
    """Un alumno/beneficio que no es de este box es 404 (no 403: no se filtra lo que hay)."""
    assert cliente.get(f"{BASE_BENEFICIOS}/alumno/999999999",
                       headers=tokens["admin"]).status_code == 404
    assert _dar(cliente, tokens["admin"], 999999999, svc.TIPO_DESCUENTO, 5).status_code == 404
    assert cliente.post(f"{BASE_BENEFICIOS}/999999999/anular",
                        json={"motivo": "no existe"},
                        headers=tokens["admin"]).status_code == 404


def test_b12_la_sugerencia_en_lote_es_la_misma_que_la_de_a_uno(cliente, tokens, escenario):
    """La columna "Recomendación" y el modal no pueden decir cosas distintas: UNA sola regla."""
    ids = [escenario["alumno_id"], escenario["otro_id"]]
    lote = cliente.post("/api/v1/fidelizacion/sugerencias", json={"alumno_ids": ids},
                        headers=tokens["admin"])

    assert lote.status_code == 200
    por_id = lote.json()["sugerencias"]
    assert set(por_id) == {str(i) for i in ids}
    for alumno_id in ids:
        uno = cliente.post("/api/v1/fidelizacion/sugerir", json={"alumno_id": alumno_id},
                           headers=tokens["admin"]).json()
        assert por_id[str(alumno_id)] == uno, \
            "el lote tiene que repetir EXACTAMENTE la sugerencia de a uno (misma regla)"

    # Un id que no es de este box se OMITE: una fila ajena no deja sin sugerencia a toda la tabla.
    con_ausente = cliente.post("/api/v1/fidelizacion/sugerencias",
                               json={"alumno_ids": ids + [999999999]},
                               headers=tokens["admin"]).json()["sugerencias"]
    assert set(con_ausente) == {str(i) for i in ids}

    # Un lote vacío no se acepta (422): el panel no pide sugerencias de nadie.
    assert cliente.post("/api/v1/fidelizacion/sugerencias", json={"alumno_ids": []},
                        headers=tokens["admin"]).status_code == 422

