"""Cuentas PERMANENTES del instituto — guards de los scripts de limpieza (tests AISLADOS).

Qué fija este archivo, SIN base de datos y SIN red:

  A. La lista es UNA: `scripts/cuentas_instituto.py` tiene exactamente las 3 cuentas y
     `crear_usuarios_demo.py` usa las mismas (se auto-verifica al importarse).
  B. `--borrar` de `crear_usuarios_demo.py` se NIEGA sin
     `--forzar-borrado-cuentas-instituto`, y aborta ANTES de la confirmación y de la base.
  C. Re-ejecutar el script NO rota la contraseña: `upsert_usuario` sólo escribe
     `password_hash` cuando se pide `--cambiar-password` (se ejercita con una sesión falsa).
  D. `--extender-plan` valida la fecha (YYYY-MM-DD real) y es excluyente con `--borrar`.
  E. Los otros scripts de limpieza/purga usan el módulo: `borrar_usuarios_prueba.py`
     guarda su lista, `borrar_seed_anual.py` guarda su LIKE y `run_setup_test_db.py`
     captura/restaura las cuentas alrededor de la limpieza total de TEST.

Correr (aislado, sin conftest ni servidor):
    cd backend && py -3.12 -m pytest tests/test_cuentas_instituto.py -q --noconftest
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

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


def _fuente(nombre: str) -> str:
    """Fuente de un script: en `backend/scripts/` o, si no está, en `backend/` (los
    orquestadores como `run_setup_test_db.py` viven en la raíz del backend)."""
    ruta = SCRIPTS / nombre
    if not ruta.exists():
        ruta = BACKEND / nombre
    return ruta.read_text(encoding="utf-8")


cert = _cargar("cuentas_instituto")
demo = _cargar("crear_usuarios_demo")

ESPERADAS = ("demo.admin@urbanbox.cl", "demo.coach@urbanbox.cl", "demo.alumno@urbanbox.cl")


# ── A. Una sola lista ───────────────────────────────────────────────────────
def test_a_la_lista_es_unica_y_el_script_usa_la_misma():
    assert cert.CUENTAS_INSTITUTO == ESPERADAS
    assert demo.CORREOS_DEMO == cert.CUENTAS_INSTITUTO, (
        "crear_usuarios_demo tiene que operar SOBRE las cuentas del instituto")
    assert demo.CORREO_ADMIN == ESPERADAS[0]
    assert demo.CORREO_COACH == ESPERADAS[1]
    assert demo.CORREO_ALUMNO == ESPERADAS[2]


def test_a_reconoce_las_cuentas_sin_importar_mayusculas():
    assert cert.es_cuenta_instituto("Demo.Admin@UrbanBox.cl ") is True
    assert cert.es_cuenta_instituto("cualquiera@gmail.com") is False
    assert cert.es_cuenta_instituto(None) is False
    assert cert.cuentas_instituto_en(["x@y.cl", ESPERADAS[2]]) == (ESPERADAS[2],)


def test_a_aborta_al_alcanzarlas_y_devuelve_cuales():
    with pytest.raises(cert.CuentaInstituto) as e:
        cert.abortar_si_hay_cuentas_instituto(["otro@x.cl", *ESPERADAS], "prueba")
    assert ESPERADAS[0] in str(e.value) and "instituto" in str(e.value)
    # Con `forzar=True` no aborta pero igual informa cuáles son.
    assert cert.abortar_si_hay_cuentas_instituto(ESPERADAS, "prueba", forzar=True) == ESPERADAS
    # Una lista limpia pasa sin ruido.
    assert cert.abortar_si_hay_cuentas_instituto(["a@b.cl"], "prueba") == ()


def test_a_guarda_los_borrados_por_patron():
    assert cert.patron_alcanza_cuentas_instituto("demo.", "@urbanbox.cl") == ESPERADAS
    assert cert.patron_alcanza_cuentas_instituto("demo.prod.", "@example.com") == ()
    with pytest.raises(cert.CuentaInstituto):
        cert.abortar_si_patron_alcanza_instituto("demo.", "@urbanbox.cl", "seed")
    assert cert.abortar_si_patron_alcanza_instituto("ml.seed.", "@test.local", "seed") == ()


def test_a_el_sql_masivo_excluye_las_cuentas():
    sql = cert.sql_no_instituto("correo")
    assert sql.startswith("correo NOT IN (")
    for c in ESPERADAS:
        assert f"'{c}'" in sql


# ── B. `--borrar` se niega sin el flag (y falla CERRADO) ────────────────────
def test_b_borrar_sin_flag_aborta_antes_de_confirmar_y_de_la_base(capsys):
    rc = demo.main(["--destino", "test", "--borrar"])
    assert rc == 1, "sin --forzar-borrado-cuentas-instituto, --borrar no puede seguir"
    salida = capsys.readouterr().out
    assert "--forzar-borrado-cuentas-instituto" in salida
    for c in ESPERADAS:
        assert c in salida
    assert "SI QUIERO TEST" not in salida, (
        "ni siquiera se llega a la confirmación: el guard va primero")


def test_b_borrar_y_extender_plan_son_excluyentes(capsys):
    rc = demo.main(["--destino", "test", "--borrar",
                    "--forzar-borrado-cuentas-instituto",
                    "--extender-plan", "2026-12-31"])
    assert rc == 1
    assert "acciones distintas" in capsys.readouterr().out


def test_b_los_flags_nuevos_parsean_con_defaults_seguros():
    args = demo.parsear_args(["--destino", "test"])
    assert args.cambiar_password is False, "por defecto NO se rota la clave"
    assert args.extender_plan is None
    assert args.forzar_borrado_cuentas_instituto is False
    args2 = demo.parsear_args(["--destino", "test", "--cambiar-password",
                               "--extender-plan", "2026-12-31"])
    assert args2.cambiar_password is True and args2.extender_plan == "2026-12-31"


# ── C. Re-ejecutar NO rota la contraseña ───────────────────────────────────
class _Res:
    def __init__(self, primera):
        self._primera = primera

    def first(self):
        return self._primera


class _DbFalso:
    """Sesión mínima: registra el SQL y devuelve una fila (o None) en `first()`."""

    def __init__(self, primera):
        self._primera = primera
        self.llamadas = []

    def execute(self, sentencia, params=None):
        self.llamadas.append((str(sentencia), dict(params or {})))
        return _Res(self._primera)


def test_c_una_cuenta_que_existe_conserva_su_clave(capsys):
    db = _DbFalso(SimpleNamespace(id=530))
    assert demo.upsert_usuario(db, ESPERADAS[0], None, False) == 530
    sql, params = db.llamadas[-1]
    assert sql.startswith("UPDATE usuarios SET")
    assert "password_hash" not in sql, "sin --cambiar-password no se toca la clave"
    assert "p" not in params
    assert "clave intacta" in capsys.readouterr().out


def test_c_con_cambiar_password_si_escribe_el_hash():
    db = _DbFalso(SimpleNamespace(id=531))
    demo.upsert_usuario(db, ESPERADAS[1], "hash-nuevo", True)
    sql, params = db.llamadas[-1]
    assert "password_hash = :p" in sql and params["p"] == "hash-nuevo"


def test_c_una_cuenta_nueva_exige_contraseña():
    with pytest.raises(demo.GuardError):
        demo.upsert_usuario(_DbFalso(None), ESPERADAS[2], None, False)


# ── D. `--extender-plan` valida la fecha ───────────────────────────────────
def test_d_la_fecha_tiene_que_ser_iso_y_real():
    assert demo.parsear_fecha_hasta("2026-12-31") == date(2026, 12, 31)
    assert demo.parsear_fecha_hasta(" 2027-01-01 ") == date(2027, 1, 1)
    for malo in ("31/12/2026", "2026-02-30", "2026-13-01", "", "hoy", None):
        with pytest.raises(demo.GuardError):
            demo.parsear_fecha_hasta(malo)


# ── E. Los otros scripts de limpieza usan el módulo ────────────────────────
def test_e_borrar_usuarios_prueba_guarda_su_lista():
    # Es un script LOCAL de purga (está en .gitignore, tiene correos reales): si el clon
    # no lo tiene, no hay nada que verificar.
    if not (SCRIPTS / "borrar_usuarios_prueba.py").exists():
        pytest.skip("borrar_usuarios_prueba.py no está en este clon")
    fuente = _fuente("borrar_usuarios_prueba.py")
    assert "cuentas_instituto" in fuente
    assert "abortar_si_hay_cuentas_instituto(CORREOS_A_BORRAR" in fuente
    assert "cuentas_instituto_en(CORREOS_A_BORRAR)" in fuente, (
        "el borrado real (borrar()) tiene que volver a chequear: falla CERRADO")


def test_e_borrar_seed_anual_guarda_su_like():
    fuente = _fuente("borrar_seed_anual.py")
    assert "cuentas_instituto" in fuente
    assert "abortar_si_patron_alcanza_instituto" in fuente


def test_e_run_setup_test_db_captura_y_restaura():
    fuente = _fuente("run_setup_test_db.py")
    assert 'importlib.import_module("scripts.cuentas_instituto")' in fuente
    assert "_instituto.capturar(db)" in fuente, (
        "las cuentas se capturan ANTES del DELETE (tenant_id es CASCADE)")
    assert "_instituto.restaurar(db, _instituto_previas)" in fuente
    # La captura va ANTES de la limpieza y la restauración DESPUÉS del borrado de tenants.
    assert fuente.index("_instituto.capturar(db)") < fuente.index("DELETE FROM usuarios")
    assert fuente.index("_instituto.restaurar(db") > fuente.index("DELETE FROM tenants")
