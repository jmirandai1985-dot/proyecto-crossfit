"""Tests unitarios del seed de alumnos por el flujo real (sin base, sin `.env`).

Se corre SIN `conftest.py` (ese conftest habla con la API en :8000):

    py -3.12 -m pytest tests/test_seed_alumnos_flujo_unit.py -q --noconftest

Que se cubre:
  * los repartos suman EXACTO (cohortes, tramos y sub-cohortes);
  * RUT: DV modulo 11, formato, validez y 400 unicos;
  * eleccion de plan: genero/unisex, activo, comercial, pago y duracion;
  * las constantes que decidio el dueno (planes largos y monto de matricula);
  * correos/telefonos/perfiles/fechas dentro de rango;
  * la CLI (defaults y validaciones) y la simulacion del dry-run;
  * el modulo se importa sin leer config ni abrir base.
"""
import importlib.util
import pathlib
import random
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _cargar(nombre: str, archivo: str):
    spec = importlib.util.spec_from_file_location(nombre, BACKEND / "scripts" / archivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


seed = _cargar("seed_alumnos_flujo", "seed_alumnos_flujo.py")


def _plan(nombre, genero, precio, duracion=30, activo=True, comercial=True):
    return SimpleNamespace(
        id=None, nombre=nombre, genero=genero, precio_clp=precio,
        duracion_dias=duracion, activo=activo, es_comercial=comercial,
        es_ilimitado=False, creditos=10)


PLANES = [
    _plan("Fem", "femenino", 44_000),
    _plan("Masc", "masculino", 49_000),
    _plan("Unisex 90", None, 118_800, 90),
    _plan("Prueba", None, 0, 7),
    _plan("Apagado", "femenino", 44_000, activo=False),
    _plan("No comercial", "femenino", 44_000, comercial=False),
]


# ── 1) Repartos ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("total", [0, 1, 7, 37, 399, 400, 1234])
def test_repartir_suma_exacta(total):
    salida = seed.repartir(total, seed.COHORTES)
    assert sum(salida.values()) == total
    assert set(salida) == {"nuevos", "renovando", "trial", "churned"}


def test_repartir_pesos_en_cero():
    salida = seed.repartir(50, (("a", 0), ("b", 0)))
    assert salida == {"a": 0, "b": 0}


def test_distribucion_de_400():
    assert seed.repartir_cohortes(400) == {
        "nuevos": 160, "renovando": 120, "trial": 60, "churned": 60}


def test_tramos_de_los_160_nuevos():
    tramos = seed.repartir(160, seed.TRAMOS_NUEVOS)
    assert sum(tramos.values()) == 160
    assert tramos == {"mensual": 96, "trimestral": 36, "semestral": 20, "anual": 8}


def test_subcohortes_de_400():
    dist = seed.repartir_cohortes(400)
    assert seed.repartir(dist["renovando"], seed.RENOVANDO_SUB) == {
        "vencido": 84, "vigente": 36}
    assert seed.repartir(dist["trial"], seed.TRIAL_SUB) == {
        "vigente": 40, "por_vencer": 12, "vencido": 8}
    assert seed.repartir(dist["churned"], seed.CHURNED_SUB) == {
        "vencido": 42, "baja": 18}


# ── 2) RUT ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("numero,dv", [
    (12_345_678, "5"),
    (11_111_111, "1"),
    (99_999_999, "9"),
    (20_000_001, "3"),
    (12_000_008, "K"),
])
def test_calcular_dv(numero, dv):
    assert seed.calcular_dv(numero) == dv


def test_formatear_y_validar_rut():
    assert seed.formatear_rut(12_345_678, "5") == "12.345.678-5"
    assert seed.rut_valido("12.345.678-5") is True
    assert seed.rut_valido("12.345.678-4") is False
    assert seed.rut_valido("12345678-5") is True
    assert seed.rut_valido("") is False
    assert seed.rut_valido("abc") is False
    assert seed.rut_valido("12.345.678") is False


def test_generar_400_ruts_unicos_y_validos():
    rng = random.Random(7)
    usados = set()
    ruts = [seed.generar_rut(usados, rng) for _ in range(400)]
    assert len(set(ruts)) == 400
    assert all(seed.rut_valido(rut) for rut in ruts)


def test_generar_rut_respeta_los_usados():
    rng = random.Random(7)
    primero = seed.generar_rut(set(), rng)
    usados = {primero}
    segundo = seed.generar_rut(usados, rng)
    assert segundo != primero and segundo in usados


# ── 3) Eleccion de plan ─────────────────────────────────────────────────────
def test_elegir_plan_por_genero():
    plan = seed.elegir_plan(PLANES, "femenino", 30)
    assert plan.nombre == "Fem"
    plan = seed.elegir_plan(PLANES, "masculino", 30)
    assert plan.nombre == "Masc"


def test_elegir_plan_unisex_para_largos():
    plan = seed.elegir_plan(PLANES, "femenino", 90)
    assert plan.nombre == "Unisex 90"
    plan = seed.elegir_plan(PLANES, "masculino", 90)
    assert plan.nombre == "Unisex 90"


def test_no_elige_prueba_ni_inactivos_ni_no_comerciales():
    for _ in range(50):
        plan = seed.elegir_plan(PLANES, "femenino", 30)
        assert plan.nombre not in ("Prueba", "Apagado", "No comercial")


def test_sin_candidatos_aborta():
    with pytest.raises(seed.SeedError):
        seed.elegir_plan([_plan("Solo fem", "femenino", 44_000)], "masculino", 30)


# ── 4) Decisiones del dueno ─────────────────────────────────────────────────
def test_planes_largos_decididos():
    esperado = [
        ("Trimestral", 90, 118_800),
        ("Semestral", 180, 224_400),
        ("Anual", 365, 422_400),
    ]
    assert [(p["nombre"], p["duracion_dias"], p["precio_clp"])
            for p in seed.PLANES_LARGOS] == esperado


def test_monto_de_matricula_por_defecto():
    assert seed.MATRICULA_MONTO_DEFECTO == 25_000


# ── 5) Datos generados ──────────────────────────────────────────────────────
def test_correos():
    assert seed.correo_de(1) == "seed.0001@urbanbox.test"
    assert seed.correo_de(400) == "seed.0400@urbanbox.test"
    assert len({seed.correo_de(i) for i in range(1, 401)}) == 400


def test_perfiles():
    rng = random.Random(7)
    for _ in range(200):
        assert seed.perfil_aleatorio(rng) in ("femenino", "masculino")


def test_telefono_y_fecha_de_nacimiento():
    rng = random.Random(7)
    for _ in range(50):
        telefono = seed.telefono_aleatorio(rng)
        assert telefono.startswith("+569") and len(telefono) == 12
        nacimiento = seed.fecha_nacimiento_aleatoria(rng)
        edad = datetime.now(timezone.utc).date().year - nacimiento.year
        assert 17 <= edad <= 61


# ── 6) CLI y simulacion ─────────────────────────────────────────────────────
def test_cli_defaults():
    args = seed.parsear_args([])
    assert args.alumnos == 400
    assert args.monto_matricula == 25_000
    assert args.dry_run is False and args.si is False


@pytest.mark.parametrize("argv", [
    ["--alumnos", "0"],
    ["--alumnos", str(seed.MAX_ALUMNOS + 1)],
    ["--monto-matricula", "-1"],
    ["--borrar", "--reemplazar"],
])
def test_cli_rechaza_invalidos(argv):
    with pytest.raises(SystemExit):
        seed.parsear_args(argv)


def test_simular_no_escribe_y_muestra_el_plan(capsys):
    ctx = seed.Contexto(
        tenant_id=1,
        rng=random.Random(7),
        ahora=datetime.now(timezone.utc),
        password_hash="x",
        admin_id=1,
        dry_run=True,
        planes=list(PLANES),
        plan_prueba=PLANES[3],
        resumen={"matricula_aviso": "se aplicaria: activada",
                 "matricula_monto_efectivo": 25_000},
    )
    seed.simular(ctx, 40)
    salida = capsys.readouterr().out
    assert "DISTRIBUCION" in salida
    assert "TOTAL" in salida
    assert "MUESTRA" in salida
    assert "transacciones matricula    : 16" in salida
    assert "DRY-RUN" in salida


def test_el_modulo_se_importa_sin_config():
    """Si el modulo leyera `.env` al importarse, este test no llegaria aca."""
    assert callable(seed.main)
    assert seed.BACKEND_DIR.endswith("backend")

