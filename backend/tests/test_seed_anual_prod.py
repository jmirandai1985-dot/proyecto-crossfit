"""Tests unitarios del seed anual y de su borrado — SIN base de datos.

Cubren los invariantes que sostienen el "0 cambios / 0 detecciones nuevas" del
mantenimiento (§2) y el invariante de créditos de A.3 (§6), más los guards y la
reversibilidad. Nada de esto toca Neon: todo se ejercita sobre el plan en memoria que
produce `scripts/seed_anual_prod.construir_plan` con una grilla sintética chica.

Para ejecutar (desde backend/):
    py -3.12 -m pytest tests/test_seed_anual_prod.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _cargar(nombre: str):
    """Importa un script de `backend/scripts` por ruta (esa carpeta no es un paquete)."""
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, SCRIPTS / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


# `borrar_seed_anual` importa constantes del seed: se carga después para que lo encuentre.
seed = _cargar("seed_anual_prod")
borrar = _cargar("borrar_seed_anual")

HOY = date(2026, 10, 3)
DIAS_VENTANA = 120
N_ALUMNOS = 60
ASISTENCIAS_DIA = 40
SEMILLA = 7
PROD_ID = "ep-nameless-sound-b6km6wyi"
TEST_IDS = ("ep-jolly-butterfly-b6ty2z89",)


# ══════════════════════════════════════════════════════════════════════════
#  Fixtures: grilla sintética + plan (módulo, para no regenerarlo en cada test)
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def horarios():
    """Grilla sintética parecida a la real: L-V 07/08/09/19 (Gap a las 19) y sábado."""
    filas, hid = [], 0
    for dia in range(5):
        for hora in (7, 8, 9, 19):
            hid += 1
            filas.append({"id": hid, "disciplina_id": 1 if hora != 19 else 5,
                          "dia_semana": dia, "hora_inicio": time(hora, 0),
                          "hora_fin": time(hora + 1, 0),
                          "cupo_maximo": 16 if hora != 19 else 12, "activo": True})
    hid += 1
    filas.append({"id": hid, "disciplina_id": 1, "dia_semana": 5,
                  "hora_inicio": time(10, 0), "hora_fin": time(12, 0),
                  "cupo_maximo": 16, "activo": True})
    return filas


@pytest.fixture(scope="module")
def clases_reales():
    """Clases ya existentes: las de los últimos 40 días hábiles (aforo base 1) + futuras."""
    filas, cid = [], 100
    for i in range(0, 40):
        f = HOY - timedelta(days=i)
        if f.weekday() > 4:
            continue
        cid += 1
        filas.append({"id": cid, "fecha": f, "horario_base_id": 1, "disciplina_id": 1,
                      "hora_inicio": time(7, 0), "hora_fin": time(8, 0),
                      "cupo_maximo": 16, "cancelada": False,
                      "asistentes_confirmados": 1})
    for i in range(1, 8):
        cid += 1
        filas.append({"id": cid, "fecha": HOY + timedelta(days=i), "horario_base_id": 1,
                      "disciplina_id": 1, "hora_inicio": time(7, 0),
                      "hora_fin": time(8, 0), "cupo_maximo": 16, "cancelada": False,
                      "asistentes_confirmados": 0})
    return filas


@pytest.fixture(scope="module")
def planes():
    """Un plan de 16 créditos y uno ilimitado (decisión 2: sin planes chicos)."""
    return [
        {"id": 1, "nombre": "Super Woman", "creditos": 16, "es_ilimitado": False,
         "precio_clp": 54000},
        {"id": 2, "nombre": "Diosa Griega", "creditos": 0, "es_ilimitado": True,
         "precio_clp": 64000},
    ]


@pytest.fixture(scope="module")
def plan(horarios, clases_reales, planes):
    """El plan completo en memoria (es lo que el seed insertaría fila por fila)."""
    return seed.construir_plan(
        HOY, horarios=horarios, clases_reales=clases_reales, planes=planes,
        coaches={1: [7], 5: [10]}, requiere_coach={1: True, 5: True},
        ruts_usados={"20000001"}, n_alumnos=N_ALUMNOS, dias_ventana=DIAS_VENTANA,
        asistencias_dia=ASISTENCIAS_DIA, asistencias_sabado=16, dias_futuro=7,
        semilla=SEMILLA, validar=False)


def _clases(plan):
    return {c["clave"]: c for c in plan["clases"]}


def _sub_de(plan, alumno_idx, fecha):
    for alumno in plan["alumnos"]:
        if alumno["idx"] == alumno_idx:
            return seed.sub_del_dia(alumno, fecha)
    return None


def _consumo_a3(plan):
    """Réplica EXACTA de A.3 con el offset real de Chile (el que usa el SQL del job)."""
    clt = _zona_chile()
    clases = _clases(plan)
    vivas, tardias = defaultdict(int), defaultdict(int)
    for reserva in plan["reservas"]:
        clase = clases[reserva["clase"]]
        sub = _sub_de(plan, reserva["alumno"], clase["fecha"])
        assert sub is not None, "reserva sin suscripción que la cubra"
        clave = (reserva["alumno"], sub["mes"])
        if reserva["estado"] == seed.ESTADO_RESERVA_VIVA:
            vivas[clave] += 1
        else:
            inicio = datetime(clase["fecha"].year, clase["fecha"].month,
                              clase["fecha"].day, clase["hora_inicio"].hour,
                              tzinfo=clt)
            if reserva["updated_at"] > inicio - timedelta(hours=seed.HORAS_DEVOLUCION):
                tardias[clave] += 1
    return vivas, tardias


def _zona_chile():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Santiago")
    except Exception:                       # pragma: no cover  (sin tzdata en el host)
        pytest.skip("sin tzdata: no se puede verificar el corte de 6 h con el offset real")


# ══════════════════════════════════════════════════════════════════════════
#  §2 — invariantes frente al mantenimiento
# ══════════════════════════════════════════════════════════════════════════
def test_plan_cumple_todos_los_invariantes(plan):
    """`validar_plan` no levanta y el resumen coincide con las listas del plan."""
    resumen = seed.validar_plan(plan)
    assert resumen["alumnos"] == len(plan["alumnos"]) == N_ALUMNOS
    assert resumen["reservas"] == len(plan["reservas"])
    assert resumen["asistencias"] == len(plan["asistencias"])
    assert resumen["clases_seed"] == sum(1 for c in plan["clases"] if c["seed"])
    assert resumen["suscripciones"] == len(plan["suscripciones"])


def test_aforo_es_reservas_vivas_mas_la_base(plan):
    """Paso 9/A.2(a): `asistentes_confirmados` = base de la clase + reservas vivas."""
    vivas = defaultdict(int)
    for reserva in plan["reservas"]:
        if reserva["estado"] == seed.ESTADO_RESERVA_VIVA:
            vivas[reserva["clase"]] += 1
    for clase in plan["clases"]:
        assert clase["asistentes_confirmados"] == clase["aforo_base"] + vivas[clase["clave"]]
        assert clase["asistentes_confirmados"] <= clase["cupo_maximo"], "A.2(c) sobrecupo"


def test_reservas_pasadas_tienen_marcada_at_y_nunca_cierre(plan):
    """Paso 8 y A.4(b): ninguna reserva viva y vieja queda sin marcar."""
    corte = HOY - timedelta(days=seed.DIAS_CIERRE_MANTENIMIENTO)
    clases = _clases(plan)
    for reserva in plan["reservas"]:
        clase = clases[reserva["clase"]]
        assert reserva["asistencia_via"] != "cierre", "esa vía la escribe el paso 8"
        assert reserva["asistencia_marcada_por"] is None, "decisión 7"
        if reserva["asistio"]:
            assert reserva["asistencia_marcada_at"] is not None, "A.4(b)"
        if reserva["estado"] == seed.ESTADO_RESERVA_VIVA and clase["fecha"] < corte:
            assert reserva["asistencia_marcada_at"] is not None, "el paso 8 la tocaría"


def test_reservas_futuras_sobre_clases_reales_y_sin_marcar(plan):
    """Decisión 5: los próximos 7 días van sobre clases REALES y sin asistencia."""
    clases = _clases(plan)
    futuras = [r for r in plan["reservas"] if clases[r["clase"]]["fecha"] > HOY]
    assert futuras, "la fase de reservas futuras quedó vacía"
    for reserva in futuras:
        assert not clases[reserva["clase"]]["seed"], "no se crean clases futuras (A.5)"
        assert reserva["estado"] == seed.ESTADO_RESERVA_VIVA
        assert reserva["asistio"] is False
        assert reserva["asistencia_marcada_at"] is None


def test_clases_del_seed_no_son_futuras_y_tienen_coach_valido(plan):
    """A.5: sólo coaches activos de la disciplina; NULL en las self-service."""
    for clase in plan["clases"]:
        if not clase["seed"]:
            continue
        assert clase["fecha"] <= HOY
        if clase["requiere_coach"]:
            esperado = {7} if clase["disciplina_id"] != 5 else {10}
            assert clase["coach_id"] in esperado
        else:
            assert clase["coach_id"] is None


def test_estados_de_usuario_y_suscripcion_validos(plan):
    """A.1(a)/(b): `activo = (estado == 'activo')` y estados del enum conocidos."""
    for alumno in plan["alumnos"]:
        assert alumno["estado"] in seed.ESTADOS_USUARIO
        assert alumno["activo"] == (alumno["estado"] == "activo")
        if alumno["perfil"] == "BAJA":
            assert alumno["estado"] == "baja" and alumno["fecha_baja"] < HOY
        else:
            assert alumno["estado"] == "activo" and alumno["fecha_baja"] is None
    for sub in plan["suscripciones"]:
        assert sub["estado"] in seed.ESTADOS_SUSCRIPCION
        assert sub["estado"] in ("activo", "vencido"), "el paso 2 no debe tener trabajo"
        assert sub["expiracion"] >= sub["inicio"]


def test_una_sola_suscripcion_vigente_por_alumno(plan):
    """A.3 sólo evalúa alumnos con UNA suscripción vigente: ventanas sin solape."""
    por_alumno = defaultdict(list)
    for sub in plan["suscripciones"]:
        por_alumno[sub["alumno"]].append(sub)
    for alumno in plan["alumnos"]:
        subs = sorted(por_alumno[alumno["idx"]], key=lambda s: s["inicio"])
        for previa, siguiente in zip(subs, subs[1:]):
            assert previa["expiracion"] < siguiente["inicio"], "ventanas solapadas"
        vigentes = [s for s in subs if s["inicio"] <= HOY <= s["expiracion"]]
        if alumno["perfil"] == "BAJA":
            assert not vigentes
        else:
            assert len(vigentes) == 1 and vigentes[0]["estado"] == "activo"


def test_label_de_churn_equivale_al_perfil_baja(plan):
    """§2.1 (y `ml/features.label_abandonado`): el label ⇔ perfil BAJA."""
    ultimas = {}
    for asistencia in plan["asistencias"]:
        ultimas[asistencia["alumno"]] = max(
            ultimas.get(asistencia["alumno"], asistencia["fecha"]), asistencia["fecha"])
    vigentes = defaultdict(int)
    for sub in plan["suscripciones"]:
        if sub["inicio"] <= HOY <= sub["expiracion"]:
            vigentes[sub["alumno"]] += 1
    for alumno in plan["alumnos"]:
        ultima = ultimas.get(alumno["idx"])
        dias = (HOY - ultima).days if ultima else (HOY - alumno["alta"]).days
        label = (vigentes[alumno["idx"]] == 0) and dias > seed.UMBRAL_ABANDONO_DIAS
        assert label == (alumno["perfil"] == "BAJA"), f"{alumno['correo']} ({dias} días)"
        if alumno["perfil"] != "BAJA":
            assert dias <= seed.DIAS_RECIENTE_MAX, \
                f"{alumno['correo']} sin asistir hace {dias} días"


def test_sin_reservas_huerfanas_y_sin_duplicados(plan):
    """A.2(b) + §6: cada reserva cae en la ventana de una suscripción del alumno."""
    clases = _clases(plan)
    vivas = set()
    for reserva in plan["reservas"]:
        clase = clases[reserva["clase"]]
        assert _sub_de(plan, reserva["alumno"], clase["fecha"]) is not None
        clave = (reserva["alumno"], reserva["clase"])
        if reserva["estado"] == seed.ESTADO_RESERVA_VIVA:
            assert clave not in vivas, "A.2(b) reserva viva duplicada"
            vivas.add(clave)


def test_una_asistencia_por_reserva_asistida(plan):
    """Coherencia entre `reservas.asistio` y `asistencias` (lo que lee el ML)."""
    asistidas = {(r["alumno"], r["clase"]) for r in plan["reservas"] if r["asistio"]}
    vistas = {(a["alumno"], a["clase"]) for a in plan["asistencias"]}
    assert asistidas == vistas
    for asistencia in plan["asistencias"]:
        assert asistencia["fecha"].weekday() != 6, "no hay clases los domingos"
        assert asistencia["fecha"] <= HOY


def test_transacciones_una_por_suscripcion_y_no_futuras(plan):
    """El forecast necesita la serie mensual: un pago por suscripción, nunca en futuro."""
    assert len(plan["transacciones"]) == len(plan["suscripciones"])
    for transaccion in plan["transacciones"]:
        sub = plan["suscripciones"][transaccion["sub"]]
        assert transaccion["fecha"] <= HOY
        assert transaccion["descripcion"].startswith(seed.MARCA_DESC)
        assert sub["inicio"] <= transaccion["fecha"] <= sub["inicio"] + timedelta(days=2)


def test_reparto_del_dia_sin_domingos_y_respetando_el_sabado(plan):
    """Domingo sin clases y sábado acotado al cupo del único horario real."""
    por_dia = defaultdict(int)
    for asistencia in plan["asistencias"]:
        por_dia[asistencia["fecha"]] += 1
    for fecha, cuantos in por_dia.items():
        assert fecha.weekday() != 6
        if fecha.weekday() == 5:
            assert cuantos <= 16


# ══════════════════════════════════════════════════════════════════════════
#  §6 — el invariante de créditos de A.3 (contra el offset REAL de Chile)
# ══════════════════════════════════════════════════════════════════════════
def test_creditos_cuadran_con_a3(plan):
    """`totales - disponibles` == vivas + tardías, con el corte de 6 h del job."""
    vivas, tardias = _consumo_a3(plan)
    revisadas = 0
    for sub in plan["suscripciones"]:
        clave = (sub["alumno"], sub["mes"])
        if sub["es_ilimitado"]:
            assert sub["creditos_totales"] is None and sub["creditos_disponibles"] is None
            continue
        revisadas += 1
        consumo = vivas[clave] + tardias[clave]
        assert sub["creditos_totales"] - sub["creditos_disponibles"] == consumo, \
            f"A.3 {clave}: {sub['creditos_totales']} - {sub['creditos_disponibles']} != {consumo}"
        assert sub["creditos_disponibles"] >= 0
    assert revisadas, "ninguna suscripción con créditos: A.3 no tendría nada que verificar"


def test_cancelaciones_tempranas_y_tardias_se_clasifican_por_el_corte_de_6h(plan):
    """El `updated_at` de cada cancelación cae del lado correcto del corte de A.3."""
    clt = _zona_chile()
    clases = _clases(plan)
    tempranas = tardias = 0
    for reserva in plan["reservas"]:
        if reserva["estado"] != seed.ESTADO_RESERVA_CANCELADA:
            continue
        clase = clases[reserva["clase"]]
        inicio = datetime(clase["fecha"].year, clase["fecha"].month, clase["fecha"].day,
                          clase["hora_inicio"].hour, tzinfo=clt)
        corte = inicio - timedelta(hours=seed.HORAS_DEVOLUCION)
        if reserva["temprana"]:
            assert reserva["updated_at"] <= corte, "temprana: el crédito vuelve"
            tempranas += 1
        else:
            assert reserva["updated_at"] > corte, "tardía: el crédito NO vuelve"
            tardias += 1
        assert reserva["asistencia_marcada_at"] is None
        assert reserva["asistio"] is False
    assert tempranas and tardias, "hacen falta cancelaciones de los dos tipos"


# ══════════════════════════════════════════════════════════════════════════
#  Generador: determinismo, reparto del día y helpers puros
# ══════════════════════════════════════════════════════════════════════════
def test_determinismo_misma_semilla_mismo_plan(horarios, clases_reales, planes):
    """El dry-run tiene que anticipar la ejecución: mismo día + semilla ⇒ mismo plan."""
    def huella(plan):
        return (
            len(plan["alumnos"]), len(plan["suscripciones"]), len(plan["clases"]),
            len(plan["reservas"]), len(plan["asistencias"]),
            sum(t["monto"] for t in plan["transacciones"]),
            sorted((r["alumno"], r["clase"], r["estado"], str(r["updated_at"]))
                   for r in plan["reservas"])[:50],
        )

    args = dict(horarios=horarios, clases_reales=clases_reales, planes=planes,
                coaches={1: [7], 5: [10]}, requiere_coach={1: True, 5: True},
                ruts_usados={"20000001"}, n_alumnos=N_ALUMNOS, dias_ventana=DIAS_VENTANA,
                asistencias_dia=ASISTENCIAS_DIA, asistencias_sabado=16, dias_futuro=7,
                semilla=SEMILLA)
    assert huella(seed.construir_plan(HOY, **args)) == \
        huella(seed.construir_plan(HOY, **args))


def test_reparto_por_slots_respeta_cupo_y_suma():
    """El reparto nunca pasa el cupo y, si hay lugar, entrega el objetivo completo."""
    slots = [{"hora_inicio": time(7, 0), "cupo_maximo": 4},
             {"hora_inicio": time(19, 0), "cupo_maximo": 3}]
    conteos = seed.repartir_por_slots(5, slots)
    assert sum(conteos) == 5 and all(c <= s["cupo_maximo"] for c, s in zip(conteos, slots))
    assert seed.repartir_por_slots(50, slots) == [4, 3]      # objetivo > capacidad
    parejos = [{"hora_inicio": time(7, 0), "cupo_maximo": 20},
               {"hora_inicio": time(19, 0), "cupo_maximo": 20}]
    manana, tarde = seed.repartir_por_slots(20, parejos)
    assert tarde > manana, "el peak de la tarde se lleva más gente que la mañana"
    assert seed.repartir_por_slots(10, []) == []


def test_objetivo_del_dia_por_dia_de_semana():
    """Domingo 0, sábado el cupo real y los días hábiles con estacionalidad."""
    import random as _random
    rng = _random.Random(1)
    assert seed.objetivo_asistencias(date(2026, 10, 4), rng, 100, 16) == 0      # domingo
    assert seed.objetivo_asistencias(date(2026, 10, 3), rng, 100, 16) == 16     # sábado
    marzo = seed.objetivo_asistencias(date(2026, 3, 10), rng, 100, 16)
    enero = seed.objetivo_asistencias(date(2026, 1, 13), rng, 100, 16)
    assert marzo > enero > 0, "la estacionalidad chilena tiene que verse en el día a día"


def test_helpers_de_rut_y_fechas():
    """`calcular_dv`/`rut_valido` y los helpers de meses son la base de los datos."""
    assert seed.calcular_dv(12345678) == "5"
    assert seed.rut_valido("12345678-5") and not seed.rut_valido("12345678-9")
    assert not seed.rut_valido("12345678") and not seed.rut_valido("")
    assert seed.ultimo_dia_mes(date(2026, 2, 10)) == date(2026, 2, 28)
    assert seed.ultimo_dia_mes(date(2026, 12, 1)) == date(2026, 12, 31)
    assert seed.correr_mes(date(2026, 1, 15), -2) == date(2025, 11, 1)
    assert seed.mes_iso(date(2026, 9, 3)) == "2026-09"
    import random as _random
    rng = _random.Random(3)
    usados = set()
    ruts = [seed.generar_rut(usados, rng) for _ in range(20)]
    assert len(set(ruts)) == 20 and all(seed.rut_valido(r) for r in ruts)


def test_sub_del_dia_y_credito_disponible():
    """La ventana de la suscripción es la que decide qué reserva consume qué crédito."""
    alumno = {"idx": 1, "alta": date(2026, 9, 10), "plan": {"creditos": 2},
              "suscripciones": [{"mes": "2026-09", "inicio": date(2026, 9, 10),
                                 "expiracion": date(2026, 9, 30), "es_ilimitado": False}]}
    assert seed.sub_del_dia(alumno, date(2026, 9, 15)) is not None
    assert seed.sub_del_dia(alumno, date(2026, 10, 1)) is None
    assert seed.sub_del_dia(alumno, date(2026, 9, 9)) is None
    consumo = {(1, "2026-09"): 1}
    assert seed.credito_disponible(alumno, alumno["suscripciones"][0], consumo)
    consumo[(1, "2026-09")] = 2
    assert not seed.credito_disponible(alumno, alumno["suscripciones"][0], consumo)
    ilimitado = dict(alumno["suscripciones"][0], es_ilimitado=True)
    assert seed.credito_disponible(alumno, ilimitado, consumo)


# ══════════════════════════════════════════════════════════════════════════
#  Guards: destino/URL, ventana de ejecución y pureza del módulo
# ══════════════════════════════════════════════════════════════════════════
def test_guard_de_url_por_destino():
    """prod sólo con el endpoint de PROD; test sólo con TEST y jamás PROD."""
    url_prod = ("postgresql://u:p@ep-nameless-sound-b6km6wyi-pooler.c-7.us-east-1"
                ".aws.neon.tech/neondb")
    url_test = ("postgresql://u:p@ep-jolly-butterfly-b6ty2z89-pooler.c-7.us-east-1"
                ".aws.neon.tech/neondb")
    url_viejo = ("postgresql://u:p@ep-withered-silence-123456-pooler.us-east-1"
                 ".aws.neon.tech/neondb")
    assert seed.validar_url_destino(url_prod, "prod", PROD_ID, TEST_IDS) is None
    assert seed.validar_url_destino(url_test, "test", PROD_ID, TEST_IDS) is None
    assert seed.validar_url_destino(url_test, "prod", PROD_ID, TEST_IDS)
    assert seed.validar_url_destino(url_prod, "test", PROD_ID, TEST_IDS)
    assert seed.validar_url_destino(url_viejo, "prod", PROD_ID, TEST_IDS)
    assert seed.validar_url_destino(url_viejo, "test", PROD_ID, TEST_IDS)
    assert seed.validar_url_destino("", "prod", PROD_ID, TEST_IDS)
    cruzada = url_prod + "?options=branch:ep-jolly-butterfly-b6ty2z89"
    assert seed.validar_url_destino(cruzada, "test", PROD_ID, TEST_IDS)


def test_guard_de_ventana_de_ejecucion_solo_en_prod():
    """PROD: nunca día 1 ni 15 (el mantenimiento escribe) ni septiembre de 2026."""
    assert seed.validar_ventana(date(2026, 10, 1), "prod")
    assert seed.validar_ventana(date(2026, 10, 15), "prod")
    assert seed.validar_ventana(date(2026, 11, 1), "prod")
    assert seed.validar_ventana(date(2026, 9, 20), "prod")
    for dia in (2, 3, 4, 5, 14, 16, 28):
        assert seed.validar_ventana(date(2026, 10, dia), "prod") is None
    # El default es el lado ESTRICTO: una llamada sin destino se evalúa como PROD.
    assert seed.validar_ventana(date(2026, 10, 1))
    assert seed.validar_ventana(date(2026, 9, 20))


def test_guard_de_ventana_no_aplica_en_test():
    """TEST no tiene ningún cron de mantenimiento ⇒ cualquier día es ejecutable."""
    for fecha in (date(2026, 9, 1), date(2026, 9, 15), date(2026, 9, 20), date(2026, 9, 28),
                  date(2026, 10, 1), date(2026, 10, 15), date(2026, 11, 1)):
        assert seed.validar_ventana(fecha, "test") is None


def _hoy_falso(monkeypatch, valor: date) -> None:
    """Fija `date.today()` DENTRO del módulo del seed (sin tocar el reloj del sistema)."""
    class _Hoy(date):
        @classmethod
        def today(cls):
            return valor

    monkeypatch.setattr(seed, "date", _Hoy)


def test_main_se_niega_a_sembrar_en_prod_dentro_de_la_ventana(monkeypatch, capsys):
    """Con destino=prod la ventana corta ANTES de pedir teclado, del `.env` y de la base."""
    _hoy_falso(monkeypatch, date(2026, 9, 20))
    monkeypatch.setattr(seed, "pedir", lambda *a, **k: pytest.fail("no debe pedir confirmación"))
    monkeypatch.setattr(seed, "preparar_entorno",
                        lambda *a, **k: pytest.fail("no debe llegar al .env ni a la base"))
    assert seed.main(["--destino", "prod", "--dry-run"]) == 1
    assert "ABORTADO" in capsys.readouterr().out


def test_main_en_test_no_evalua_la_ventana(monkeypatch, capsys):
    """La MISMA fecha que PROD rechaza, en TEST pasa el guard 3 y avisa que no aplica."""
    _hoy_falso(monkeypatch, date(2026, 9, 20))
    llamadas = []
    monkeypatch.setattr(seed, "pedir",
                        lambda frase, prompt: (llamadas.append(frase), True)[1])

    def _corte(destino):
        llamadas.append(f"preparar_entorno:{destino}")
        raise seed.GuardError("corte del test: la base no se toca")

    monkeypatch.setattr(seed, "preparar_entorno", _corte)
    assert seed.main(["--destino", "test", "--dry-run"]) == 1
    assert llamadas == ["SI QUIERO TEST", "preparar_entorno:test"]
    assert "no aplica en TEST" in capsys.readouterr().out


def test_el_seed_no_importa_la_app_al_importarse():
    """La app se importa DENTRO de las funciones: así los tests corren sin credenciales."""
    fuente = (SCRIPTS / "seed_anual_prod.py").read_text(encoding="utf-8")
    for numero, linea in enumerate(fuente.splitlines(), start=1):
        assert not linea.startswith("from app."), f"línea {numero}: import de app arriba"
        assert not linea.startswith("import app"), f"línea {numero}: import de app arriba"
    assert hasattr(seed, "preparar_entorno")


# ══════════════════════════════════════════════════════════════════════════
#  Idempotencia y reversibilidad: marcadores y recálculo del aforo
# ══════════════════════════════════════════════════════════════════════════
def test_marcadores_coherentes_entre_seed_y_borrado():
    """El borrado tiene que apuntar EXACTAMENTE a lo que crea el seed."""
    assert borrar.MARCA_TS == seed.MARCA_TS
    assert borrar.PREFIJO_CORREO == seed.PREFIJO_CORREO == "demo.prod.anual."
    assert borrar.MARCA_DESC == seed.MARCA_DESC
    # El prefijo cae DENTRO de PROD_PERMITIDOS ('demo.prod.%@example.com'): A.1(c) lo ve
    # como demo declarada y no hay que tocar la variable de Render.
    assert seed.PREFIJO_CORREO.startswith("demo.prod.")
    assert seed.DOMINIO_CORREO == "@example.com"
    # Y dentro del LIKE del seed viejo ('DEMOPROD%'), que también lo borraría.
    assert seed.MARCA_DESC.startswith("DEMOPROD")
    correo = f"{seed.PREFIJO_CORREO}7{seed.DOMINIO_CORREO}"
    assert correo.startswith("demo.prod.") and correo.endswith("@example.com")


def test_filtros_del_borrado_por_defecto_vs_limpiar_viejo():
    """Por defecto se borra SÓLO el seed anual; con `--limpiar-viejo`, los dos (decisión 4)."""
    where, params = borrar.filtro_usuarios()
    assert "demo.prod.anual." in params["nuevo"] and "@example.com" in params["nuevo"]
    assert where == "correo LIKE :nuevo"
    where, params = borrar.filtro_usuarios(incluir_viejo=True)
    # El LIKE ancho es el de PROD_PERMITIDOS: abarca el viejo y el nuevo.
    assert params["demo"] == "demo.prod.%@example.com"
    where, params = borrar.filtro_transacciones()
    assert params["nuevo"] == f"{seed.MARCA_DESC}%"
    where, params = borrar.filtro_transacciones(incluir_viejo=True)
    assert params["demo"] == "DEMOPROD%"


def test_pasos_de_borrado_en_orden():
    """El orden ES el invariante: hojas primero y el aforo justo después de las reservas."""
    pasos = borrar.pasos_borrado()
    assert pasos.index("asistencias") < pasos.index("reservas") < pasos.index("clases_seed")
    assert (pasos.index("reservas") < pasos.index("aforo_clases_reales")
            < pasos.index("clases_seed"))
    assert pasos.index("suscripciones") < pasos.index("usuarios")
    assert pasos[-1] == "clases_seed"


def test_reversion_deja_el_aforo_de_las_clases_reales_como_estaba():
    """Corrección 3: borrar las reservas del seed y recalcular ⇒ el paso 9 da 0."""
    aforo_antes = {97: 1, 1500: 0, 2001: 3}          # aforo REAL pre-seed
    clases_seed = {9001, 9002}
    reservas_seed = [{"clase_id": 97}, {"clase_id": 97}, {"clase_id": 97},
                     {"clase_id": 2001}, {"clase_id": 2001},
                     {"clase_id": 9001}, {"clase_id": 9002}]
    afectadas = borrar.clases_a_resincronizar(reservas_seed, clases_seed)
    assert afectadas == {97, 2001}, "las clases del seed se borran enteras: no se resincronizan"
    vivas_reales = {97: 1, 2001: 3}                  # lo que dejaron los alumnos reales
    esperado = borrar.aforo_final(vivas_reales, sorted(afectadas))
    assert esperado == {97: 1, 2001: 3}
    for clase_id in afectadas:
        assert esperado[clase_id] == aforo_antes[clase_id], "el paso 9 tendría trabajo"
    assert borrar.clases_a_resincronizar([], clases_seed) == set()
    assert borrar.aforo_final({}, []) == {}


def test_estimar_filas_cuenta_lo_que_se_inserta(plan):
    """El dry-run reporta lo que `escribir_plan` inserta (las clases, sólo las del seed)."""
    filas = seed.estimar_filas(plan)
    assert filas["clases"] == sum(1 for c in plan["clases"] if c["seed"])
    assert filas["reservas"] == len(plan["reservas"])
    assert filas["TOTAL"] == sum(v for k, v in filas.items() if k != "TOTAL")
    assert "usuarios=3" in borrar.resumen_borrado({"usuarios": 3, "reservas": 0})
