"""Accesos staff de Pato y Seba — chequeos AISLADOS (sin BD, sin red, sin correos).

Congela lo que el script de aprovisionamiento tiene que cumplir antes de tocar PROD:
  * 6 cuentas, 3 roles por persona, en el orden del informe.
  * Correos reales de los admin + alias `+alumno`/`+coach` únicos.
  * Guardas de destino: solo PROD actual, nunca TEST ni PROD retirados.
  * Claves provisionales fuertes, únicas y generadas en runtime (no en el repo).
  * El script NO importa ni llama a `email_service`/`send_*` (cero correos).

    cd backend && py -3.12 -m pytest tests/test_accesos_staff_pato_seba.py -q --noconftest
"""
import importlib.util
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCRIPT = BACKEND / "scripts" / "accesos_staff_pato_seba.py"

_spec = importlib.util.spec_from_file_location("accesos_staff_pato_seba", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
# `dataclasses` resuelve `cls.__module__` en sys.modules: hay que registrarlo antes.
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


def test_las_seis_cuentas_y_el_orden_del_informe():
    eq = [
        ("Pato", "administrador", "perez.patricio89@gmail.com"),
        ("Pato", "alumno", "perez.patricio89+alumno@gmail.com"),
        ("Pato", "coach", "perez.patricio89+coach@gmail.com"),
        ("Seba", "administrador", "sebamedina2022@gmail.com"),
        ("Seba", "alumno", "sebamedina2022+alumno@gmail.com"),
        ("Seba", "coach", "sebamedina2022+coach@gmail.com"),
    ]
    assert mod.plan_de_cuentas() == eq
    assert mod.resumen_por_persona() == {
        "Pato": ["administrador", "alumno", "coach"],
        "Seba": ["administrador", "alumno", "coach"],
    }
    correos = [correo for _, _, correo in mod.plan_de_cuentas()]
    assert len(correos) == len(set(correos)), "un correo por cuenta (clave única)"
    assert all(c.endswith("@gmail.com") for c in correos)


def test_correos_reales_y_alias():
    por_rol = {(c.persona, c.rol): c for c in mod.CUENTAS}
    assert por_rol[("Pato", "administrador")].correo == "perez.patricio89@gmail.com"
    assert por_rol[("Seba", "administrador")].correo == "sebamedina2022@gmail.com"
    # Los alias caen en la MISMA bandeja real (Gmail +), sin inventar dominios.
    assert por_rol[("Pato", "alumno")].correo.startswith("perez.patricio89+")
    assert por_rol[("Pato", "coach")].correo.startswith("perez.patricio89+")
    assert por_rol[("Seba", "alumno")].correo.startswith("sebamedina2022+")
    assert por_rol[("Seba", "coach")].correo.startswith("sebamedina2022+")
    # Pato ya existe: conserva su nombre/RUT (el script no los inventa).
    assert por_rol[("Pato", "administrador")].existente is True
    assert por_rol[("Pato", "administrador")].rut is None


def test_guardas_de_destino_solo_prod_actual():
    prod = "ep-winter-star-akwis51j"
    test = ("ep-crimson-tooth-akhx7q2s",)
    retirados = ("ep-bitter-cloud-arat6wil", "ep-withered-silence")
    assert mod.validar_destino(
        f"postgresql://u:p@host/{prod}?sslmode=require",
        "production", prod, test, retirados) is None
    assert mod.validar_destino(
        f"postgresql://u:p@host/{prod}", "test", prod, test, retirados)
    assert mod.validar_destino(
        f"postgresql://u:p@host/{test[0]}", "production", prod, test, retirados)
    assert mod.validar_destino(
        "postgresql://u:p@host/ep-bitter-cloud-arat6wil",
        "production", prod, test, retirados)
    assert mod.validar_destino(
        "postgresql://u:p@host/otra-rama", "production", prod, test, retirados)
    assert mod.validar_destino("", "production", prod, test, retirados)


def test_password_provisional_fuerte_y_unica():
    claves = {mod.generar_password() for _ in range(200)}
    assert len(claves) == 200, "las claves no se repiten"
    for clave in claves:
        assert clave.startswith(mod.PREFIJO_PASSWORD)
        assert len(clave) == len(mod.PREFIJO_PASSWORD) + mod.LARGO_PASSWORD
        assert all(ch in mod.ALFABETO_PASSWORD for ch in clave[len(mod.PREFIJO_PASSWORD):])


def test_el_script_no_manda_correos():
    fuente = SCRIPT.read_text(encoding="utf-8")
    # El docstring NOMBRA el servicio para explicar que no se usa; lo que no puede
    # existir es el import ni la llamada.
    assert "from app.services import email_service" not in fuente
    assert "from app.services.email_service" not in fuente
    assert "send_solicitud_prueba_clase(" not in fuente
    assert "smtplib" not in fuente
    # No hay contraseñas hardcodeadas: la única forma es el generador runtime.
    import re
    assert not re.search(r"UTB-[A-Za-z0-9]{12}", fuente)
    assert "secrets.choice" in fuente


def test_el_script_es_idempotente_y_deja_los_datos_pedidos():
    fuente = SCRIPT.read_text(encoding="utf-8")
    # Plan interno ilimitado NO comercial (no suma MRR) y fuera del catálogo.
    assert "es_ilimitado=True" in fuente
    assert "es_comercial=False" in fuente
    assert "activo=False" in fuente
    assert "precio_clp=0" in fuente
    assert "creditos_totales=None" in fuente
    assert "creditos_disponibles=None" in fuente
    # Fuerza cambio de clave y replica el alta (referido incluido).
    assert "cambiar_password_al_login=True" in fuente
    assert "asignar_codigo_referido" in fuente
    assert "get_password_hash" in fuente
    # Guardas explícitas de escritura.
    assert 'choices=("prod",)' in fuente
    assert "SI QUIERO PROD" in fuente
    assert "--aplicar" in fuente
    assert "PROD_BRANCH_ID" in fuente
    assert "TEST_BRANCH_IDS" in fuente
    assert "ENDPOINTS_RETIRADOS" in fuente
