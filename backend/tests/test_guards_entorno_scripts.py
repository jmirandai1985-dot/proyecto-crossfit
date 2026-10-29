"""Guards de entorno de scripts/tests: que no queden pegados a un host de Neon retirado.

POR QUÉ EXISTE (auditoría de tests 2026-10-29): varios scripts comparaban la
`DATABASE_URL` contra un endpoint **hardcodeado** que ya no existe
(`billowing-violet-acdqud44`, `withered-silence`). Eso no es inseguro —abortan—
pero deja el script inusable y, peor, disfraza el problema: "el guard dice que no
es TEST" cuando la URL sí es TEST. La clasificación tiene UNA fuente
(`app.core.config.is_test_db_url` / `PROD_BRANCH_ID`) y estos tests la fijan.

También fija el contrato del seed y de `conftest`:
  * `run_setup_test_db.py` crea las personas fijas 999/1000/1001;
  * `conftest` firma tokens de personas que EXISTEN en la branch (si el seed no
    está, cae al primer usuario activo de ese rol en vez de firmar un id muerto).

Correr (aislado): `py -3.12 -m pytest tests/test_guards_entorno_scripts.py -q --noconftest`
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Endpoints que alguna vez fueron TEST/PROD y hoy no existen. Un guard nuevo
# puede MENCIONARLOS en un comentario (contexto histórico), nunca comparar.
RETIRADOS = (
    "billowing-violet-acdqud44",
    "withered-silence",
    "ep-lingering-fog-arywdnbg",
)

SCRIPTS_TEST = (
    "scripts/crear_usuarios_test.py",
    "scripts/borrar_usuarios_prueba.py",
    "scripts/seed_usuarios_prueba.py",
    "scripts/seed_ml_data.py",
)


def fuente(rel: str) -> str:
    return (BACKEND / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", SCRIPTS_TEST + ("scripts/seed_ml_data_prod.py",))
def test_ningun_guard_compara_contra_un_endpoint_retirado(rel):
    """Sólo las COMPARACIONES cuentan: mencionar el host en un comentario/docstring
    (contexto histórico) es válido; comparar la URL contra él, no.

    Cuatro de estos scripts están en `.gitignore` (helpers LOCALES de TEST: no se
    versionan). Si el archivo no está en el clon, no hay nada que revisar.
    """
    if not (BACKEND / rel).exists():
        pytest.skip(f"{rel} no está en esta copia (está en .gitignore)")
    lineas = [
        (n, linea.strip()) for n, linea in enumerate(fuente(rel).splitlines(), 1)
        if any(viejo in linea for viejo in RETIRADOS)
        and ("DATABASE_URL" in linea or "DB_URL" in linea)
        and not linea.strip().startswith("#")
    ]
    assert not lineas, (
        f"{rel} sigue comparando contra un endpoint retirado: {lineas[:3]}. "
        "Usá `app.core.config.is_test_db_url` (o `PROD_BRANCH_ID`)."
    )


@pytest.mark.parametrize("rel", SCRIPTS_TEST)
def test_los_scripts_de_test_usan_la_clasificacion_unica(rel):
    if not (BACKEND / rel).exists():
        pytest.skip(f"{rel} no está en esta copia (está en .gitignore)")
    assert "is_test_db_url" in fuente(rel), (
        f"{rel} tiene que decidir con `is_test_db_url`, no con un literal"
    )


def test_el_seed_de_prod_usa_la_prod_vigente_y_no_una_rama_test():
    rel = "scripts/seed_ml_data_prod.py"
    if not (BACKEND / rel).exists():
        pytest.skip(f"{rel} no está en esta copia (está en .gitignore)")
    texto = fuente(rel)
    assert "PROD_BRANCH_ID" in texto
    assert "is_test_db_url" in texto


def test_el_seed_de_test_crea_las_personas_fijas_de_la_suite():
    texto = fuente("run_setup_test_db.py")
    for persona in ("id=999", "id=1000", "id=1001"):
        assert persona in texto, f"el seed tiene que crear {persona}"


def test_conftest_firma_personas_que_existen():
    texto = fuente("tests/conftest.py")
    assert "def _resolver_persona_test(" in texto
    assert "COACH_ID = _resolver_persona_test(\"coach\", 1000)" in texto
    assert "ADMIN_ID = _resolver_persona_test(\"administrador\", 1001)" in texto
    # Los helpers NO pueden volver a firmar ids fijos.
    assert '"usuario_id": 1001' not in texto
    assert "def get_coach_token(coach_id=1000" not in texto
