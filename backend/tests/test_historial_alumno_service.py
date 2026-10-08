"""Historial del alumno (servicio): las reglas del panel, con un caso armado a mano.

Por qué existe este archivo
---------------------------
El panel del Historial es el ÚNICO lugar donde el alumno y el box ven sus números juntos
(asistencia, plata, membresías, RMs). Este test fija esas reglas y, sobre todo, el dinero de
las cancelaciones:

  A. PURAS (sin BD): los 5 estados de una reserva, el corte de las 6 h, "mes con plan", el
     dinero de las transacciones (lo cobrado vs. el precio de lista), la paginación y el menú
     de secciones. Es lo que no puede cambiar sin un negocio distinto.
  B. SECCIONES contra TEST (in-process): la envoltura, el paginado, que `rms` devuelva LO MISMO
     que `rms_service` y que la privacidad del alumno (`incluir_privado=False`) no exponga la
     gestión del box.
  C. CASO ARMADO (escribe y RESTAURA): un alumno temporal con dos membresías que cuentan (una
     vencida y una vigente) y una que no (pendiente), sus transacciones reales (la vencida
     cobrada al precio de lista y con una devolución anotada; la vigente con descuento), un
     pedido del Bazar validado y uno pendiente, las 5 formas de una reserva y una clase
     suspendida por el box. Fija el total pagado, el % de asistencia (la cancelación TARDE
     cuenta como falta) y el promedio semanal, y compara "mes con plan" contra el predicado SQL
     compartido (`sql_suscripcion_vigente`). Al final borra todo lo que creó.
  D. SUSCRIPCIÓN SIN `fecha_inicio` (regresión del bug de prod del 2026-10-08): un alumno cuya
     membresía de prueba tiene `fecha_inicio` NULL —así la dejaba el alta del landing— no puede
     tumbar NINGUNA de las 7 secciones del panel: el inicio real de esa membresía es su
     `created_at`. También fija que el 500 no era "no hay filas" (un alumno vacío siempre
     respondió bien) ni el orden: la fila sin fecha es la MÁS VIEJA, no la más nueva.

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
                    "(define ENVIRONMENT=test / revisa .env.test)")
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


def test_a5_el_menu_de_secciones_anuncia_las_7_y_ninguna_reservada():
    """El menú lista las 7 secciones, todas disponibles y sin motivo.

    Ni `beneficios` (F2 de Fidelización) ni `bazar` (detalle de pedidos) están reservadas:
    la sección se anuncia cuando tiene contenido, y las dos lo tienen.
    """
    secciones = svc.secciones_disponibles()

    assert [s["id"] for s in secciones] == ["resumen", "asistencia", "pagos",
                                            "membresias", "bazar", "rms", "beneficios"]
    assert all(s["disponible"] is True and s["motivo"] is None for s in secciones)
    assert svc.SECCIONES_RESERVADAS == ()
    assert svc.normalizar_seccion("beneficios") == "beneficios"


def test_a6_paginado_y_seccion_normalizada():
    items = list(range(1, 26))
    pag = svc._paginado(items, 2, 10)
    assert pag["items"] == list(range(11, 21)) and pag["paginas"] == 3 and pag["total"] == 25

    # Una página fuera de rango devuelve vacío, no rompe.
    assert svc._paginado(items, 9, 10)["items"] == []
    assert svc.normalizar_seccion("no_existe") == svc.DEFAULT_SECCION
    assert svc.normalizar_seccion("pagos") == "pagos"


def test_a7_lo_cobrado_son_las_transacciones_no_el_precio_de_lista():
    """Regla 4, en puro: ingreso suma, devolución resta y un tipo raro no mueve la aguja."""
    def tx(tipo, monto):
        return SimpleNamespace(tipo=tipo, monto=monto)

    # Una membresía sin transacciones se cobró $0 (no el precio de lista del plan).
    assert svc.monto_cobrado([]) == 0
    assert svc.monto_cobrado([tx("ingreso", 33000)]) == 33000
    # Un descuento es un ingreso MENOR: el número sale de la transacción, no del plan.
    assert svc.monto_cobrado([tx("ingreso", 28000)]) == 28000
    # Devolución (egreso) y renovación (dos ingresos) del mismo mes.
    assert svc.monto_cobrado([tx("ingreso", 33000), tx("egreso", 3000)]) == 30000
    assert svc.monto_cobrado([tx("ingreso", 20000), tx("ingreso", 15000)]) == 35000
    # Un tipo desconocido se ignora y un monto NULL no rompe el cálculo.
    assert svc.monto_cobrado([tx("ajuste", 999), tx("ingreso", None)]) == 0
    assert (svc.signo_transaccion("ingreso"), svc.signo_transaccion("egreso"),
            svc.signo_transaccion("otro")) == (1, -1, 0)


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


def test_b1_la_envoltura_es_la_misma_en_las_7_secciones(db, alumno_test):
    for seccion in ("resumen", "asistencia", "pagos", "membresias", "bazar", "rms",
                    "beneficios"):
        panel = svc.panel(db, alumno_test, TENANT_ID, seccion=seccion)

        assert set(panel) == {"alumno", "seccion", "secciones", "incluye_privado", "datos"}
        assert panel["seccion"] == seccion
        assert panel["alumno"]["id"] == alumno_test
        # Las 7 secciones existen Y se anuncian (las últimas en llegar fueron `beneficios`, F2,
        # y `bazar`, el detalle de pedidos).
        assert len(panel["secciones"]) == 7
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


def test_b5_membresias_cuadra_y_beneficios_tiene_su_seccion(db, alumno_test):
    datos = svc.panel(db, alumno_test, TENANT_ID, seccion="membresias")["datos"]
    resumen = datos["resumen"]

    assert resumen["meses_con_plan"] + resumen["meses_sin_plan"] == resumen["meses_como_alumno"]
    assert datos["paginado"]["total"] == resumen["meses_como_alumno"]

    # La sección de beneficios está ABIERTA (F2) y devuelve la misma envoltura que las demás: el
    # alumno de prueba no tiene regalos, así que la lista viene vacía con sus totales en cero.
    beneficios = svc.panel(db, alumno_test, TENANT_ID, seccion="beneficios")["datos"]
    assert beneficios["disponible"] is True and beneficios["motivo"] is None
    assert set(beneficios["totales"]) == {"total", "vigentes", "usados", "vencidos", "anulados"}
    assert beneficios["totales"]["total"] == len(beneficios["items"])


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
PRECIO_PLAN = 33000            # precio de lista del plan del caso armado
COBRADO_VIGENTE = 28000        # la membresía vigente se cobró CON descuento
DEVOLUCION_VENCIDA = 3000      # a la vencida se le anotó una devolución (egreso)
COBRADO_VENCIDA = PRECIO_PLAN - DEVOLUCION_VENCIDA
COBRADO_MEMBRESIAS = COBRADO_VENCIDA + COBRADO_VIGENTE
DESCUENTOS = (PRECIO_PLAN - COBRADO_VENCIDA) + (PRECIO_PLAN - COBRADO_VIGENTE)
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

    clases, alumno_id, plan_id, suscripciones_ids = [], None, None, []
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
            suscripciones_ids.append(db.execute(text("""
                INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                           creditos_totales, creditos_disponibles,
                                           fecha_inicio, fecha_expiracion)
                VALUES (:t, :u, :p, CAST(:e AS estado_suscripcion), 12, 3, :i, :f)
                RETURNING id"""),
                {"t": TENANT_ID, "u": alumno_id, "p": plan_id, "e": estado,
                 "i": datetime.combine(desde, time(12, 0), tzinfo=SANTIAGO),
                 "f": datetime.combine(hasta, time(12, 0), tzinfo=SANTIAGO)}).scalar())

        # El dinero que entró (regla 4): la VENCIDA se cobró al precio de lista y después se le
        # anotó una devolución; la VIGENTE se cobró con descuento; la PENDIENTE no tiene NINGUNA
        # transacción porque nunca se cobró. Este es el caso que el precio de lista no puede
        # representar.
        for indice, monto, tipo in ((0, PRECIO_PLAN, "ingreso"),
                                    (0, DEVOLUCION_VENCIDA, "egreso"),
                                    (1, COBRADO_VIGENTE, "ingreso")):
            db.execute(text("""
                INSERT INTO transacciones_financieras (tenant_id, tipo, categoria, monto,
                                                       descripcion, referencia_tipo,
                                                       referencia_id, fecha)
                VALUES (:t, :tp, 'membresia', :m, 'Cobro caso armado del historial',
                        'suscripcion', :r, :f)"""),
                {"t": TENANT_ID, "tp": tipo, "m": monto, "r": suscripciones_ids[indice],
                 "f": hoy - timedelta(days=30)})

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
               "mes_2atras": mes_2atras, "suscripciones": suscripciones_ids}
    finally:
        db.rollback()
        try:
            if suscripciones_ids:
                db.execute(text("DELETE FROM transacciones_financieras "
                                "WHERE referencia_tipo = 'suscripcion' "
                                "AND referencia_id = ANY(:ids)"),
                           {"ids": suscripciones_ids})
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


def test_c1_el_dinero_pagado_sale_de_las_transacciones_reales(db, escenario):
    """Membresías: lo COBRADO (vencida = lista menos su devolución; vigente = con descuento),
    NO el precio de lista; la membresía pendiente y el pedido pendiente no son plata."""
    datos = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="pagos")["datos"]
    totales = datos["totales"]

    assert totales["membresias_clp"] == COBRADO_MEMBRESIAS
    assert totales["descuentos_clp"] == DESCUENTOS
    assert totales["bazar_clp"] == BAZAR_VALIDADO
    assert totales["total_clp"] == COBRADO_MEMBRESIAS + BAZAR_VALIDADO
    assert totales["pagos"] == 3
    # El precio de lista NO se cuela en el total (2 x PRECIO_PLAN sería otra cifra).
    assert totales["membresias_clp"] != 2 * PRECIO_PLAN

    # Los 3 pagos están y la lista viene del más nuevo al más viejo (lo que promete el servicio).
    # NO se fija el orden EXACTO de los del MISMO día: el pedido de bazar es de HOY y la membresía
    # vigente arranca el 1° del mes, así que los días 1 del mes empatan y ese desempate no es lo que
    # este test mide (mide de dónde sale cada monto).
    assert sorted(i["tipo"] for i in datos["items"]) == ["bazar", "membresia", "membresia"]
    fechas = [i["fecha"] for i in datos["items"]]
    assert fechas == sorted(fechas, reverse=True), fechas

    # Se eligen por estado y no por posición: el orden de la lista no se asume acá.
    vigente = next(i for i in datos["items"]
                   if i["tipo"] == "membresia" and i["estado"] == "activo")
    vencida = next(i for i in datos["items"]
                   if i["tipo"] == "membresia" and i["estado"] == "vencido")
    assert (vencida["monto_clp"], vencida["precio_lista_clp"], vencida["descuento_clp"],
            vencida["transacciones"]) == (COBRADO_VENCIDA, PRECIO_PLAN,
                                          DEVOLUCION_VENCIDA, 2), \
        "la devolución (egreso) tiene que restar y contar como transacción"
    assert (vigente["monto_clp"], vigente["precio_lista_clp"], vigente["descuento_clp"],
            vigente["transacciones"]) == (COBRADO_VIGENTE, PRECIO_PLAN,
                                          PRECIO_PLAN - COBRADO_VIGENTE, 1), \
        "el descuento se ve en precio_lista_clp, pero se cobra lo que dice la transacción"
    # El Bazar ya viene por su total real: no tiene precio de lista ni descuento.
    bazar = next(i for i in datos["items"] if i["tipo"] == "bazar")
    assert (bazar["monto_clp"], bazar["precio_lista_clp"],
            bazar["descuento_clp"]) == (BAZAR_VALIDADO, None, 0)

    # La suscripción que NUNCA estuvo vigente no aparece como pago (ni con $0).
    cobradas = {i["referencia_id"] for i in datos["items"] if i["tipo"] == "membresia"}
    assert cobradas == set(escenario["suscripciones"][:2])
    assert escenario["suscripciones"][2] not in cobradas


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
    # "Alumno desde" (T2) es la PRIMERA suscripción (más antigua que el alta del usuario y
    # que la primera asistencia): los días como alumno y el promedio se miden desde ahí.
    primero_m2, _ultimo_m2 = svc._rango_mes(*escenario["mes_2atras"])
    desde = min(primero_m2, escenario["hoy"] - timedelta(days=56),
                escenario["hoy"] - timedelta(days=30))
    assert totales["dias_como_alumno"] == (escenario["hoy"] - desde).days
    assert totales["promedio_semanal"] == svc.promedio_semanal(
        1, desde, escenario["hoy"])                 # 1 asistencia / semanas REALES
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
        sql_fecha_en_chile, sql_suscripcion_vigente

    datos = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="membresias")["datos"]
    sql_mes_con_plan = f"""
        SELECT COUNT(*) FROM suscripciones s
        WHERE s.tenant_id = :t AND s.usuario_id = :u
          AND s.estado NOT IN ({lista_sql(ESTADOS_SUSCRIPCION_NUNCA_VIGENTES)})
          AND {sql_fecha_en_chile('s.fecha_inicio')} <= :ultimo
          AND {sql_fecha_en_chile('s.fecha_expiracion')} >= :primero"""
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
    # La lista de suscripciones se ordena por fecha de INICIO, de la más nueva a la más vieja, y
    # muestra la pendiente marcada como no vigente. Las fechas del escenario son relativas a hoy
    # (la pendiente arranca "hoy - 5 días" y la vigente el 1° del mes), así que en los primeros días
    # del mes la pendiente es la MÁS NUEVA y va primera: se comprueba la REGLA (el orden por fecha y
    # que una no cuente como vigente), no una lista literal que dependa del día en que se corre.
    assert sorted(s["cuenta_como_vigente"] for s in datos["suscripciones"]) == [False, True, True]
    inicios = [s["fecha_inicio"] for s in datos["suscripciones"]]
    assert inicios == sorted(inicios, reverse=True), inicios
    assert datos["membresia_actual"]["plan"].startswith("Plan Historial TEST")


def test_c4_el_alumno_ve_sus_numeros_sin_la_gestion_del_box(db, escenario):
    del_alumno = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="resumen",
                           incluir_privado=False)
    de_staff = svc.panel(db, escenario["alumno_id"], TENANT_ID, seccion="resumen")

    datos = del_alumno["datos"]
    assert "gestion" not in datos
    assert datos["asistencia"]["pct_asistencia"] == 33
    assert datos["membresia"]["meses_con_plan"] >= 2
    assert datos["pagos"]["total_clp"] == COBRADO_MEMBRESIAS + BAZAR_VALIDADO
    assert datos["membresia"]["actual"]["plan"].startswith("Plan Historial TEST")
    assert datos["asistencia"] == de_staff["datos"]["asistencia"]


def test_c5_la_racha_del_panel_ignora_el_mes_en_curso(db, alumno_test):
    """T2: la racha del Resumen arranca en el último mes COMPLETO.

    INTEGRACIÓN (se corre con el stack y el branch TEST arriba; acá no se ejecuta): el panel
    tiene que decir lo MISMO que `calcular_racha` arrancando en el mes ANTERIOR, no en el mes
    en curso. Un mes perfecto a mitad de camino no es un mes cerrado al 100%.
    """
    from app.services.asistencia_service import calcular_racha
    from app.utils.santiago import hoy_santiago

    hoy = hoy_santiago()
    anio_prev, mes_prev = svc._mes_anterior(hoy.year, hoy.month)
    esperado = calcular_racha(db, alumno_test, TENANT_ID, anio_prev, mes_prev)

    resumen = svc.panel(db, alumno_test, TENANT_ID, seccion="resumen")["datos"]
    assert resumen["asistencia"]["racha_meses_100"] == esperado



# ══════════════════════════════════════════════════════════════════════════════
# D. Suscripción SIN `fecha_inicio` (bug de prod del 2026-10-08, alumno 533)
# ══════════════════════════════════════════════════════════════════════════════
COBRADO_SIN_INICIO = 29000      # lo cobrado por la membresía que NO tiene fecha de inicio


@pytest.fixture
def escenario_sin_inicio(db):
    """Alumno temporal con la membresía de PRUEBA sin `fecha_inicio` (NULL en la BD).

    Es la fila que dejaba `POST /alumnos/registro` antes del arreglo (bug de prod del
    2026-10-08, alumno 533): esa alta no escribía `fecha_inicio` y, en la BD real, la columna es
    NULLABLE y SIN default (el modelo la declara NOT NULL, pero manda el esquema), así que el
    INSERT con NULL reproduce el caso exacto. Escribe en TEST y BORRA todo al salir.

    El alumno lleva DOS suscripciones que cuentan (la rota, de hace dos meses, y una vigente en
    el mes en curso) para que el panel tenga que ordenarlas y contarlas JUNTAS: el 500 no era
    "no hay suscripciones" —un alumno vacío siempre respondió bien—, era el NULL. Y las fechas
    van ancladas a MESES ("el 1° del mes de hace dos") para que el resultado no dependa del día
    del mes en que se corra el test.
    """
    from app.utils.santiago import hoy_santiago

    hoy = hoy_santiago()
    mes_2atras = _mes_menos(hoy.year, hoy.month, 2)
    creada = datetime.combine(svc._rango_mes(*mes_2atras)[0], time(12, 0), tzinfo=SANTIAGO)
    vence = creada + timedelta(days=7)
    alumno_id, plan_id = None, None
    sufijo = f"{datetime.now():%Y%m%d%H%M%S}"

    try:
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                                  estado, created_at)
            VALUES (:t, :r, 'Alumno Sin Inicio TEST', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"97{sufijo[-8:]}-7", "c": f"sininicio.{sufijo}@test.local",
             "alta": creada}).scalar()

        plan_id = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo)
            VALUES (:t, :n, 12, false, :p, 30, true) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Plan Sin Inicio TEST {sufijo}", "p": PRECIO_PLAN}).scalar()

        # La suscripción del bug: `fecha_inicio` NULL y su `created_at` como único instante.
        rota_id = db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado, creditos_totales,
                                       creditos_disponibles, fecha_inicio, fecha_expiracion,
                                       created_at)
            VALUES (:t, :u, :p, CAST('vencido' AS estado_suscripcion), 1, 1, NULL, :f, :c)
            RETURNING id"""),
            {"t": TENANT_ID, "u": alumno_id, "p": plan_id, "f": vence, "c": creada}).scalar()

        vigente_id = db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado, creditos_totales,
                                       creditos_disponibles, fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, CAST('activo' AS estado_suscripcion), 12, 3, :i, :f)
            RETURNING id"""),
            {"t": TENANT_ID, "u": alumno_id, "p": plan_id,
             "i": datetime.combine(date(hoy.year, hoy.month, 1), time(12, 0), tzinfo=SANTIAGO),
             "f": datetime.combine(hoy + timedelta(days=10), time(12, 0),
                                   tzinfo=SANTIAGO)}).scalar()

        # El cobro de la membresía sin fecha de inicio: su pago sólo tiene el `created_at`.
        db.execute(text("""
            INSERT INTO transacciones_financieras (tenant_id, tipo, categoria, monto, descripcion,
                                                   referencia_tipo, referencia_id, fecha)
            VALUES (:t, 'ingreso', 'membresia', :m, 'Cobro de la prueba sin fecha de inicio',
                    'suscripcion', :r, :f)"""),
            {"t": TENANT_ID, "m": COBRADO_SIN_INICIO, "r": rota_id, "f": creada})

        db.commit()
        yield {"alumno_id": alumno_id, "creada": creada, "vence": vence,
               "mes_2atras": mes_2atras, "rota_id": rota_id, "vigente_id": vigente_id}
    finally:
        db.rollback()
        try:
            if alumno_id:
                db.execute(text("DELETE FROM transacciones_financieras "
                                "WHERE referencia_tipo = 'suscripcion' AND referencia_id IN "
                                "(SELECT id FROM suscripciones WHERE usuario_id = :a)"),
                           {"a": alumno_id})
                db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"),
                           {"a": alumno_id})
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
            if plan_id:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
            db.commit()
        except Exception as e:      # el borrado no debe tapar el fallo real del test
            db.rollback()
            print(f"\n[WARN] no se pudo limpiar el escenario sin fecha de inicio: {e}")


def test_d1_ninguna_seccion_se_cae_con_una_suscripcion_sin_fecha_inicio(db, escenario_sin_inicio):
    """Regresión del 500 del alumno 533: `fecha_inicio` NULL no puede tumbar el panel.

    `resumen` y `membresias` morían en `_primer_mes` (`None.year` -> AttributeError) y `pagos`
    en su ordenamiento (comparar `None` con `date` -> TypeError). Se piden las 7 secciones: el
    bug no era de una pestaña, era el dato.
    """
    for seccion, _nombre in svc.SECCIONES:
        panel = svc.panel(db, escenario_sin_inicio["alumno_id"], TENANT_ID, seccion=seccion)
        assert panel["seccion"] == seccion
        assert panel["datos"] is not None


def test_d2_el_inicio_real_cae_al_created_at_de_la_suscripcion(db, escenario_sin_inicio):
    datos = svc.panel(db, escenario_sin_inicio["alumno_id"], TENANT_ID,
                      seccion="membresias")["datos"]

    # La membresía sin `fecha_inicio` muestra la fecha de su `created_at`, no un hueco.
    rota = next(s for s in datos["suscripciones"]
                if s["id"] == escenario_sin_inicio["rota_id"])
    assert rota["fecha_inicio"] == escenario_sin_inicio["creada"].date()
    assert rota["fecha_expiracion"] == escenario_sin_inicio["vence"].date()

    # Y ordena como la MÁS VIEJA: sin fecha no es "la más nueva" (un `DESC` la ponía primera).
    assert [s["id"] for s in datos["suscripciones"]] == [escenario_sin_inicio["vigente_id"],
                                                         escenario_sin_inicio["rota_id"]]


def test_d3_el_resumen_cuenta_los_meses_del_created_at(db, escenario_sin_inicio):
    """El mes de la membresía sin fecha es el de su `created_at`: ni se pierde ni se inventa."""
    mes_2atras = escenario_sin_inicio["mes_2atras"]
    resumen = svc.panel(db, escenario_sin_inicio["alumno_id"], TENANT_ID,
                        seccion="resumen")["datos"]

    assert resumen["membresia"]["meses_como_alumno"] == 3
    assert resumen["membresia"]["meses_con_plan"] == 2      # hace dos meses (la rota) + el actual
    assert resumen["membresia"]["meses_sin_plan"] == 1      # el mes pasado queda en el hueco
    assert resumen["membresia"]["actual"]["plan"].startswith("Plan Sin Inicio TEST")

    de_membresias = svc.panel(db, escenario_sin_inicio["alumno_id"], TENANT_ID,
                              seccion="membresias")["datos"]
    assert de_membresias["resumen"]["primer_mes"] == {"anio": mes_2atras[0],
                                                      "mes": mes_2atras[1]}
    # Del más nuevo al más viejo: mes en curso (vigente), el hueco y el de hace dos (la rota).
    assert [i["con_plan"] for i in de_membresias["items"]] == [True, False, True]


def test_d4_el_pago_de_la_membresia_sin_fecha_usa_el_created_at(db, escenario_sin_inicio):
    datos = svc.panel(db, escenario_sin_inicio["alumno_id"], TENANT_ID, seccion="pagos")["datos"]

    rota = next(i for i in datos["items"]
                if i["referencia_id"] == escenario_sin_inicio["rota_id"])
    assert rota["fecha"] == escenario_sin_inicio["creada"].date()
    assert rota["monto_clp"] == COBRADO_SIN_INICIO

    # Las DOS membresías que cuentan (la de prueba, ya cobrada, y la vigente), sin Bazar.
    assert datos["totales"]["pagos"] == 2
    assert datos["totales"]["total_clp"] == COBRADO_SIN_INICIO
    assert datos["totales"]["membresias_clp"] == COBRADO_SIN_INICIO
    assert datos["totales"]["bazar_clp"] == 0
    # Del más nuevo al más viejo: la vigente está en el mes en curso y la rota dos meses atrás.
    fechas = [i["fecha"] for i in datos["items"]]
    assert fechas == sorted(fechas, reverse=True), fechas
    assert datos["totales"]["ultimo_pago"] == fechas[0]