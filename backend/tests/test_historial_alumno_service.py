"""Historial del alumno (servicio): las reglas del panel, con un caso armado a mano.

Por qué existe este archivo
---------------------------
El panel del Historial es el ÚNICO lugar donde el alumno y el box ven sus números juntos
(asistencia, plata, membresías, RMs). Este test fija esas reglas y, sobre todo, el dinero de
las cancelaciones:

  A. PURAS (sin BD): los 5 estados de una reserva, el corte de las 6 h, "mes con plan", la
     paginación y el menú de secciones. Es lo que no puede cambiar sin un negocio distinto.
  B. SECCIONES contra TEST (in-process): la envoltura, el paginado, que `rms` devuelva LO MISMO
     que `rms_service` y que la privacidad del alumno (`incluir_privado=False`) no exponga la
     gestión del box.
  C. CASO ARMADO (escribe y RESTAURA): un alumno temporal con dos membresías que cuentan (una
     vencida y una vigente) y una que no (pendiente), un pedido del Bazar validado y uno
     pendiente, las 5 formas de una reserva y una clase suspendida por el box. Fija el total
     pagado, el % de asistencia (la cancelación TARDE cuenta como falta) y el promedio semanal,
     y compara "mes con plan" contra el predicado SQL compartido (`sql_suscripcion_vigente`).
     Al final borra todo lo que creó.

No usa el servidor: habla con la MISMA rama TEST por `SessionLocal` (igual que la parte
in-process de `test_bi_mrr_vivo.py`). El guard `is_test_db_url` falla CERRADO: si el proceso no
está apuntando a TEST (o sea, si no definiste `ENVIRONMENT=test`), no corre nada.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_historial_alumno_service.py -q
"""
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import historial_alumno_service as svc          # noqa: E402
from app.utils.santiago import SANTIAGO                            # noqa: E402

TENANT_ID = 1
ALUMNO_ID = 999          # alumno del seed de TEST (el mismo id que usa el resto de la suite)


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(definí ENVIRONMENT=test / revisá .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    session = SessionLocal()
    yield session
    session.close()


# ── Helpers de objetos en memoria (parte A) ───────────────────────────────────
def _clase(fecha, hora_inicio, cancelada=False, clase_id=1):
    return SimpleNamespace(id=clase_id, fecha=fecha, hora_inicio=hora_inicio,
                           hora_fin=hora_inicio, cancelada=cancelada)


def _reserva(estado="confirmada", asistio=False, updated_at=None, reserva_id=9):
    return SimpleNamespace(id=reserva_id, estado=estado, asistio=asistio,
                           updated_at=updated_at, tokens_gastados=1)


def _suscripcion(inicio: date, fin: date, estado="activo"):
    return SimpleNamespace(
        id=1, plan_id=1,
        estado=estado,
        fecha_inicio=datetime.combine(inicio, time(12, 0), tzinfo=SANTIAGO),
        fecha_expiracion=datetime.combine(fin, time(12, 0), tzinfo=SANTIAGO),
    )


# ══════════════════════════════════════════════════════════════════════════════
# A. Reglas puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_los_5_estados_de_una_reserva():
    """asistio / falto / reservada / cancelada / cancelada_tarde, cada uno con su caso."""
    ahora = datetime(2026, 3, 10, 12, 0, tzinfo=SANTIAGO)
    pasada = _clase(date(2026, 3, 9), time(19, 0))
    futura = _clase(date(2026, 3, 11), time(19, 0))

    assert svc.estado_asistencia(_reserva(asistio=True), pasada, ahora) == "asistio"
    assert svc.estado_asistencia(_reserva(), pasada, ahora) == "falto"
    assert svc.estado_asistencia(_reserva(), futura, ahora) == "reservada"

    # Cancelada con 10 h de margen: a tiempo (el crédito vuelve).
    hace_10h = datetime(2026, 3, 9, 9, 0, tzinfo=SANTIAGO)
    assert svc.estado_asistencia(
        _reserva(estado="cancelled", updated_at=hace_10h), pasada, ahora) == "cancelada"

    # Cancelada 2 h antes del inicio: TARDE (el crédito se gastó).
    assert svc.estado_asistencia(
        _reserva(estado="cancelled", updated_at=datetime(2026, 3, 9, 17, 0, tzinfo=SANTIAGO)),
        pasada, ahora) == "cancelada_tarde"

    # Las DOS formas de "cancelada" del sistema (el enum viejo y la que escribe la app).
    for estado in ("cancelled", "cancelada"):
        assert svc.estado_asistencia(
            _reserva(estado=estado, updated_at=hace_10h), pasada, ahora) == "cancelada"

    # Sin timestamp de cancelación no se inventa "tarde".
    assert svc.estado_asistencia(
        _reserva(estado="cancelled", updated_at=None), pasada, ahora) == "cancelada"

    # Una variante desconocida NO es cancelación (criterio exacto de shared.estados): la clase
    # ya pasó y no asistió => falto.
    assert svc.estado_asistencia(_reserva(estado="cancelled_x"), pasada, ahora) == "falto"


def test_a2_el_limite_de_la_cancelacion_tardia_son_6_horas():
    """A las 6 h exactas todavía es "a tiempo"; un minuto después, "tarde"."""
    inicio = datetime(2026, 3, 10, 19, 0, tzinfo=SANTIAGO)
    clase = _clase(inicio.date(), inicio.time())

    exacto = _reserva(estado="cancelled", updated_at=inicio - timedelta(hours=6))
    un_minuto_tarde = _reserva(estado="cancelled",
                               updated_at=inicio - timedelta(hours=6) + timedelta(minutes=1))

    assert svc.estado_asistencia(exacto, clase) == "cancelada"
    assert svc.estado_asistencia(un_minuto_tarde, clase) == "cancelada_tarde"


def test_a3_el_umbral_de_6h_es_el_mismo_en_los_tres_lugares():
    """Guard de divergencia: el corte de las 6 h vive en 4 lugares y tiene que seguir siendo 6.

    1. `HORAS_CANCELACION_TARDIA` (este servicio: el estado que ve el alumno);
    2. `HORAS_DEVOLUCION` del mantenimiento (A.3: el descuadre de créditos);
    3. `DELETE /reservas/{id}` (`>= 6` / `< 6`: si el crédito vuelve o no) — inline, así que se
       vigila el texto;
    4. `HORAS_DEVOLUCION` del seed anual (los datos con los que A.3 se compara).
    Cambiarlo en un solo lugar deja al panel mintiendo: este test obliga a cambiarlo en los
    cuatro a la vez.
    """
    from maintenance import mantenimiento_cloud as men

    reservas = (_BACKEND / "app" / "api" / "v1" / "reservas.py").read_text(encoding="utf-8-sig")
    seed = (_BACKEND / "scripts" / "seed_anual_prod.py").read_text(encoding="utf-8-sig")

    assert svc.HORAS_CANCELACION_TARDIA == 6
    assert men.HORAS_DEVOLUCION == svc.HORAS_CANCELACION_TARDIA, "A.3 cambió el umbral"
    assert re.search(r"^HORAS_DEVOLUCION\s*=\s*6\b", seed, re.M), "el seed cambió su umbral"
    assert ">= 6" in reservas and "< 6" in reservas, "cambió la devolución del crédito"


def test_a4_mes_con_plan_lo_deciden_las_fechas_y_el_estado():
    """`suscripcion_del_mes`: espejo en Python de `sql_suscripcion_vigente`."""
    a_caballo = _suscripcion(date(2026, 2, 20), date(2026, 3, 20))

    assert svc.suscripcion_del_mes([a_caballo], 2026, 3) is not None
    assert svc.suscripcion_del_mes([a_caballo], 2026, 4) is None        # dejó de cubrir

    # Los bordes del mes cuentan (comparación inclusiva, como el SQL).
    assert svc.suscripcion_del_mes([_suscripcion(date(2026, 3, 31), date(2026, 6, 1))],
                                   2026, 3) is not None
    assert svc.suscripcion_del_mes([_suscripcion(date(2026, 1, 1), date(2026, 3, 1))],
                                   2026, 3) is not None
    assert svc.suscripcion_del_mes([_suscripcion(date(2026, 1, 1), date(2026, 2, 28))],
                                   2026, 3) is None

    # Lo que NUNCA estuvo vigente no cubre un mes, aunque sus fechas caigan adentro.
    for estado in ("pendiente", "rechazado"):
        assert svc.suscripcion_del_mes(
            [_suscripcion(date(2026, 3, 1), date(2026, 3, 30), estado=estado)], 2026, 3) is None
    # Y una liquidada ("vencido") SÍ cubre los meses en los que estuvo vigente.
    assert svc.suscripcion_del_mes(
        [_suscripcion(date(2026, 2, 1), date(2026, 4, 5), estado="vencido")], 2026, 3) is not None

    # Dos planes en el mismo mes: gana el que empezó más tarde (cubrió más días del mes).
    primero = _suscripcion(date(2026, 3, 1), date(2026, 3, 31))
    segundo = _suscripcion(date(2026, 3, 20), date(2026, 4, 20))
    assert svc.suscripcion_del_mes([primero, segundo], 2026, 3) is segundo


def test_a5_el_menu_de_secciones_tiene_6_y_beneficios_reservada():
    secciones = svc.secciones_disponibles()

    assert [s["id"] for s in secciones] == ["resumen", "asistencia", "pagos",
                                            "membresias", "rms", "beneficios"]
    assert sum(1 for s in secciones if s["disponible"]) == 5
    reservada = secciones[-1]
    assert reservada["id"] == "beneficios" and reservada["disponible"] is False
    assert "Fase 2" in reservada["motivo"]


def test_a6_paginado_y_seccion_normalizada():
    items = list(range(1, 26))
    pag = svc._paginado(items, 2, 10)
    assert pag["items"] == list(range(11, 21)) and pag["paginas"] == 3 and pag["total"] == 25

    # Una página fuera de rango devuelve vacío, no rompe.
    assert svc._paginado(items, 9, 10)["items"] == []
    assert svc.normalizar_seccion("no_existe") == svc.DEFAULT_SECCION
    assert svc.normalizar_seccion("pagos") == "pagos"


# ══════════════════════════════════════════════════════════════════════════════
# B. Las secciones contra TEST (in-process, sólo lectura)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def alumno_test(db):
    """Un alumno real de TEST (se prefiere el del seed). Se omite si la rama no tiene."""
    fila = db.execute(text(
        "SELECT id FROM usuarios WHERE tenant_id = :t AND rol = 'alumno' "
        "ORDER BY (id = :preferido) DESC, id LIMIT 1"),
        {"t": TENANT_ID, "preferido": ALUMNO_ID}).first()
    if fila is None:
        pytest.skip("TEST no tiene alumnos")
    return int(fila[0])


def test_b1_la_envoltura_es_la_misma_en_las_6_secciones(db, alumno_test):
    for seccion in ("resumen", "asistencia", "pagos", "membresias", "rms", "beneficios"):
        panel = svc.panel(db, alumno_test, TENANT_ID, seccion=seccion)

        assert set(panel) == {"alumno", "seccion", "secciones", "incluye_privado", "datos"}
        assert panel["seccion"] == seccion
        assert panel["alumno"]["id"] == alumno_test
        assert len(panel["secciones"]) == 6
        assert isinstance(panel["datos"], dict)


def test_b2_alumno_inexistente_y_seccion_desconocida(db, alumno_test):
    assert svc.panel(db, 999_999_999, TENANT_ID, seccion="asistencia") is None
    # El tenant del token manda: el mismo id en OTRO tenant no existe.
    assert svc.panel(db, alumno_test, 999_999) is None
    assert svc.panel(db, alumno_test, TENANT_ID, seccion="no_existe")["seccion"] == "resumen"


def test_b3_asistencia_suma_los_5_estados_y_el_pct_no_se_sale_de_rango(db, alumno_test):
    datos = svc.panel(db, alumno_test, TENANT_ID, seccion="asistencia")["datos"]
    totales = datos["totales"]

    assert totales["total"] == sum(totales[e] for e in svc.ESTADOS_ASISTENCIA)
    assert totales["cuentan"] == sum(totales[e] for e in svc.ESTADOS_QUE_CUENTAN)
    assert 0 <= totales["pct_asistencia"] <= 100
    assert datos["paginado"]["total"] == totales["total"]
    assert len(datos["por_mes"]) <= svc.MESES_EN_PAYLOAD
    for item in datos["items"]:
        assert item["estado_asistencia"] in svc.ESTADOS_ASISTENCIA


def test_b4_pagos_cuadra_y_rms_es_el_mismo_que_rms_service(db, alumno_test):
    from app.services.rms_service import CAMPOS_SCHEMA, mejor_rm_por_movimiento

    pagos = svc.panel(db, alumno_test, TENANT_ID, seccion="pagos")["datos"]
    totales = pagos["totales"]
    assert totales["total_clp"] == totales["membresias_clp"] + totales["bazar_clp"]
    assert sum(a["total"] for a in pagos["por_anio"]) == totales["total_clp"]

    del_servicio = mejor_rm_por_movimiento(db, alumno_test, TENANT_ID)
    rms = svc.panel(db, alumno_test, TENANT_ID, seccion="rms", por_pagina=100)["datos"]

    assert rms["totales"]["movimientos"] == len(del_servicio)
    assert ([i["id"] for i in rms["items"]]
            == [r["id"] for r in del_servicio[:100]]), "la sección rms divergió del servicio"
    for item in rms["items"]:
        assert set(CAMPOS_SCHEMA).issubset(set(item))


def test_b5_membresias_cuadra_y_beneficios_esta_reservada(db, alumno_test):
    datos = svc.panel(db, alumno_test, TENANT_ID, seccion="membresias")["datos"]
    resumen = datos["resumen"]

    assert resumen["meses_con_plan"] + resumen["meses_sin_plan"] == resumen["meses_como_alumno"]
    assert datos["paginado"]["total"] == resumen["meses_como_alumno"]

    beneficios = svc.panel(db, alumno_test, TENANT_ID, seccion="beneficios")["datos"]
    assert beneficios["disponible"] is False and beneficios["items"] == []


def test_b6_la_gestion_del_box_no_viaja_al_alumno(db, alumno_test):
    de_staff = svc.panel(db, alumno_test, TENANT_ID, seccion="resumen", incluir_privado=True)
    del_alumno = svc.panel(db, alumno_test, TENANT_ID, seccion="resumen", incluir_privado=False)

    assert de_staff["incluye_privado"] is True
    assert del_alumno["incluye_privado"] is False
    assert "gestion" in de_staff["datos"]
    assert "gestion" not in del_alumno["datos"]
    # Lo demás es idéntico: la privacidad no cambia ningún número del alumno.
    assert del_alumno["datos"]["asistencia"] == de_staff["datos"]["asistencia"]
    assert del_alumno["datos"]["pagos"] == de_staff["datos"]["pagos"]


# ══════════════════════════════════════════════════════════════════════════════
# C. Caso armado (escribe en TEST y RESTAURA al final)
# ══════════════════════════════════════════════════════════════════════════════
PRECIO_PLAN = 33000
BAZAR_VALIDADO = 12500
BAZAR_PENDIENTE = 9999


def _mes_menos(anio: int, mes: int, k: int) -> tuple:
    """`(anio, mes)` de k meses antes (k >= 0)."""
    total = anio * 12 + (mes - 1) - k
    return total // 12, total % 12 + 1


@pytest.fixture
def escenario(db):
    """Alumno temporal con membresías, pedidos, las 5 reservas y una clase suspendida.

    Escribe en TEST y BORRA todo al salir (en orden inverso). Se omite si la rama no tiene
    horario base / disciplina / producto: no se inventan catálogos.
    """
    from app.utils.santiago import hoy_santiago

    hoy = hoy_santiago()
    horario = db.execute(text("SELECT id FROM horarios WHERE tenant_id = :t ORDER BY id LIMIT 1"),
                         {"t": TENANT_ID}).scalar()
    disciplina = db.execute(text("SELECT id FROM disciplinas WHERE tenant_id = :t "
                                 "ORDER BY id LIMIT 1"), {"t": TENANT_ID}).scalar()
    producto = db.execute(text("SELECT id FROM productos WHERE tenant_id = :t "
                               "ORDER BY id LIMIT 1"), {"t": TENANT_ID}).scalar()
    if not (horario and disciplina and producto):
        pytest.skip("TEST no tiene horario base / disciplina / producto para el caso armado")

    clases, alumno_id, plan_id = [], None, None
    sufijo = f"{datetime.now():%Y%m%d%H%M%S}"
    mes_actual = (hoy.year, hoy.month)
    mes_2atras = _mes_menos(*mes_actual, 2)
    primero_m2, ultimo_m2 = svc._rango_mes(*mes_2atras)

    def _clase(dias, cancelada=False):
        return db.execute(text("""
            INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio,
                                hora_fin, cupo_maximo, cupo_original, asistentes_confirmados,
                                cancelada)
            VALUES (:t, :h, :d, :f, '03:00', '04:00', 16, 16, 0, :c) RETURNING id"""),
            {"t": TENANT_ID, "h": horario, "d": disciplina,
             "f": hoy + timedelta(days=dias), "c": cancelada}).scalar()

    try:
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                                  estado, created_at)
            VALUES (:t, :r, 'Alumno Historial TEST', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"99{sufijo[-8:]}-9", "c": f"historial.{sufijo}@test.local",
             "alta": datetime.combine(hoy - timedelta(days=56), time(12, 0), tzinfo=SANTIAGO)}
        ).scalar()

        plan_id = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo)
            VALUES (:t, :n, 12, false, :p, 30, true) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Plan Historial TEST {sufijo}", "p": PRECIO_PLAN}).scalar()

        # Membresías: una VENCIDA en el mes de hace dos meses, una VIGENTE en el mes en curso
        # (el mes pasado queda SIN plan: el caso cubre el hueco) y una PENDIENTE, que nunca
        # contó. Fechas ancladas a MESES y no a "hoy - N días" para que el resultado no dependa
        # del día del mes en que se corra el test.
        for desde, hasta, estado in (
            (primero_m2, ultimo_m2, "vencido"),
            (date(mes_actual[0], mes_actual[1], 1), hoy + timedelta(days=10), "activo"),
            (hoy - timedelta(days=5), hoy + timedelta(days=25), "pendiente"),
        ):
            db.execute(text("""
                INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                           creditos_totales, creditos_disponibles,
                                           fecha_inicio, fecha_expiracion)
                VALUES (:t, :u, :p, CAST(:e AS estado_suscripcion), 12, 3, :i, :f)"""),
                {"t": TENANT_ID, "u": alumno_id, "p": plan_id, "e": estado,
                 "i": datetime.combine(desde, time(12, 0), tzinfo=SANTIAGO),
                 "f": datetime.combine(hasta, time(12, 0), tzinfo=SANTIAGO)})

        # Bazar: uno validado (cuenta como plata) y uno pendiente (no).
        for estado, total in (("validado", BAZAR_VALIDADO), ("pendiente", BAZAR_PENDIENTE)):
            db.execute(text("""
                INSERT INTO pedidos (tenant_id, alumno_id, producto_id, cantidad, total, estado)
                VALUES (:t, :a, :p, 1, :tt, :e)"""),
                {"t": TENANT_ID, "a": alumno_id, "p": producto, "tt": total, "e": estado})

        # Las 5 formas de una reserva + una sobre una clase que suspendió el BOX.
        clases = [_clase(-30), _clase(-20), _clase(-10), _clase(-10), _clase(10),
                  _clase(-25, cancelada=True)]
        inicio_tarde = datetime.combine(hoy - timedelta(days=10), time(3, 0), tzinfo=SANTIAGO)

        def _reserva(indice, estado, asistio, updated_at=None):
            db.execute(text("""
                INSERT INTO reservas (tenant_id, clase_id, alumno_id, estado, asistio,
                                      tokens_gastados, updated_at)
                VALUES (:t, :c, :a, :e, :as, 1, COALESCE(CAST(:u AS timestamptz), now()))"""),
                {"t": TENANT_ID, "c": clases[indice], "a": alumno_id, "e": estado,
                 "as": asistio, "u": updated_at})

        _reserva(0, "confirmada", True)
        _reserva(1, "confirmada", False)
        _reserva(2, "cancelled", False, inicio_tarde - timedelta(hours=12))   # a tiempo
        _reserva(3, "cancelada", False, inicio_tarde - timedelta(hours=2))    # TARDE
        _reserva(4, "confirmada", False)                                      # futura
        _reserva(5, "confirmada", False)                                      # clase suspendida

        db.commit()
        yield {"alumno_id": alumno_id, "hoy": hoy, "sufijo": sufijo,
               "mes_2atras": mes_2atras}
    finally:
        db.rollback()
        try:
            db.execute(text("DELETE FROM reservas WHERE alumno_id = :a"), {"a": alumno_id})
            db.execute(text("DELETE FROM pedidos WHERE alumno_id = :a"), {"a": alumno_id})
            db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"), {"a": alumno_id})
            if clases:
                db.execute(text("DELETE FROM clases WHERE id = ANY(:ids)"), {"ids": clases})
            if alumno_id:
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
            if plan_id:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
            db.commit()
        except Exception as e:      # el borrado no debe tapar el fallo real del test
            db.rollback()
            print(f"\n[WARN] no se pudo limpiar el escenario: {e}")


def test_b7_el_endpoint_de_rms_delega_y_devuelve_lo_mismo(db, alumno_test):
    """`GET /historial-rm/alumnos/{id}/rms` ahora delega en el servicio: mismos ids y orden."""
    from app.api.v1 import historial_rm
    from app.services.rms_service import mejor_rm_por_movimiento

    del_servicio = mejor_rm_por_movimiento(db, alumno_test, TENANT_ID)
    del_endpoint = historial_rm.obtener_rms_alumno(
        alumno_id=alumno_test, tenant_id=None, db=db,
        current_user={"usuario_id": 1, "tenant_id": TENANT_ID, "rol": "administrador"})

    assert [r.id for r in del_endpoint] == [r["id"] for r in del_servicio]
    assert ([r.movimiento_nombre for r in del_endpoint]
            == [r["movimiento_nombre"] for r in del_servicio])
    for fila in del_endpoint:
        assert fila.tipo_rm, "tipo_rm tiene que venir con su default 'peso'"


def test_b8_el_endpoint_de_rms_ignora_el_tenant_del_query_param(db, alumno_test):
    """El tenant sale del token: pedir otro tenant no cambia el resultado."""
    from app.api.v1 import historial_rm

    mio = historial_rm.obtener_rms_alumno(
        alumno_id=alumno_test, tenant_id=None, db=db,
        current_user={"usuario_id": 1, "tenant_id": TENANT_ID, "rol": "administrador"})
    ajeno = historial_rm.obtener_rms_alumno(
        alumno_id=alumno_test, tenant_id=999_999, db=db,
        current_user={"usuario_id": 1, "tenant_id": TENANT_ID, "rol": "administrador"})

    assert [r.id for r in mio] == [r.id for r in ajeno]


def test_c1_el_dinero_pagado_suma_membresias_y_bazar(db, escenario):
    """Membresías VENCIDA + VIGENTE (×2) más el pedido validado; la pendiente y el pedido
    pendiente NO son plata."""
    datos = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="pagos")["datos"]
    totales = datos["totales"]

    assert totales["membresias_clp"] == 2 * PRECIO_PLAN
    assert totales["bazar_clp"] == BAZAR_VALIDADO
    assert totales["total_clp"] == 2 * PRECIO_PLAN + BAZAR_VALIDADO
    assert totales["pagos"] == 3
    assert [i["tipo"] for i in datos["items"]] == ["bazar", "membresia", "membresia"]


def test_c2_los_5_estados_el_pct_y_el_promedio_semanal(db, escenario):
    datos = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="asistencia")["datos"]
    totales = datos["totales"]

    assert (totales["asistio"], totales["falto"], totales["cancelada"],
            totales["cancelada_tarde"], totales["reservada"]) == (1, 1, 1, 1, 1)
    assert totales["total"] == 5 and totales["cuentan"] == 3
    # 1 asistida sobre 3 que cuentan: la cancelación TARDE pesa, la de a tiempo no.
    assert totales["pct_asistencia"] == 33
    # La clase que suspendió el BOX queda fuera del listado y del porcentaje.
    assert totales["clases_suspendidas"] == 1
    assert totales["dias_como_alumno"] == 56
    assert totales["promedio_semanal"] == 0.1        # 1 asistencia / 8 semanas
    assert totales["ultima_asistencia"] == escenario["hoy"] - timedelta(days=30)


def test_c3_mes_con_plan_coincide_con_el_criterio_compartido(db, escenario):
    """La caminata en Python tiene que decir lo MISMO que el criterio compartido de vigencia.

    `sql_suscripcion_vigente` mira UNA fecha, así que comparar contra "vigente el último día
    del mes" da falso negativo cuando el plan termina a mitad de mes (el caso armado: la
    suscripción vencida termina el 30/08 y agosto SÍ es un mes con plan). El equivalente SQL del
    mes es el SOLAPAMIENTO del rango con los mismos estados, que es lo que se compara acá; del
    predicado compartido se exige la implicación (vigente el 1° del mes ⇒ mes con plan).
    """
    from shared.estados import ESTADOS_SUSCRIPCION_NUNCA_VIGENTES, lista_sql, \
        sql_suscripcion_vigente

    datos = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="membresias")["datos"]
    sql_mes_con_plan = f"""
        SELECT COUNT(*) FROM suscripciones s
        WHERE s.tenant_id = :t AND s.usuario_id = :u
          AND s.estado NOT IN ({lista_sql(ESTADOS_SUSCRIPCION_NUNCA_VIGENTES)})
          AND s.fecha_inicio::date <= :ultimo
          AND s.fecha_expiracion::date >= :primero"""
    sql_vigente_en = f"""
        SELECT COUNT(*) FROM suscripciones s
        WHERE s.tenant_id = :t AND s.usuario_id = :u
          AND {sql_suscripcion_vigente('s', ':fecha')}"""

    for fila in datos["items"]:
        primero, ultimo = svc._rango_mes(fila["anio"], fila["mes"])
        params = {"t": TENANT_ID, "u": escenario["alumno_id"],
                  "primero": primero, "ultimo": ultimo}
        en_sql = db.execute(text(sql_mes_con_plan), params).scalar()

        assert fila["con_plan"] == (en_sql > 0), (
            f"{fila['anio']}-{fila['mes']} diverge del criterio SQL")

        vigente_el_primero = db.execute(
            text(sql_vigente_en), {"t": TENANT_ID, "u": escenario["alumno_id"],
                                   "fecha": primero}).scalar()
        if vigente_el_primero:
            assert fila["con_plan"] is True, "mes con plan contradice el predicado compartido"

    # La vencida cubre su mes y la vigente el suyo; la pendiente no cuenta para ninguno.
    assert datos["resumen"] == {
        "meses_como_alumno": 3,
        "meses_con_plan": 2,
        "meses_sin_plan": 1,
        "primer_mes": {"anio": escenario["mes_2atras"][0], "mes": escenario["mes_2atras"][1]},
    }
    # Del más nuevo al más viejo: mes en curso (vigente), mes pasado (hueco) y el de hace dos.
    assert [f["con_plan"] for f in datos["items"]] == [True, False, True]
    # La lista de suscripciones sí muestra la pendiente, marcada como no vigente.
    assert [s["cuenta_como_vigente"] for s in datos["suscripciones"]] == [False, True, True]
    assert datos["membresia_actual"]["plan"].startswith("Plan Historial TEST")


def test_c4_el_alumno_ve_sus_numeros_sin_la_gestion_del_box(db, escenario):
    del_alumno = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="resumen",
                           incluir_privado=False)
    de_staff = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="resumen")

    datos = del_alumno["datos"]
    assert "gestion" not in datos
    assert datos["asistencia"]["pct_asistencia"] == 33
    assert datos["membresia"]["meses_con_plan"] >= 2
    assert datos["pagos"]["total_clp"] == 2 * PRECIO_PLAN + BAZAR_VALIDADO
    assert datos["membresia"]["actual"]["plan"].startswith("Plan Historial TEST")
    assert datos["asistencia"] == de_staff["datos"]["asistencia"]
