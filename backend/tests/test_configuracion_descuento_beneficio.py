"""M4 — tope de descuento de beneficios (`beneficio_descuento_max_pct`) en /admin/configuracion.

Qué fija este archivo (guard del BACKEND + del FRONTEND, sin red y sin base):

  A. El campo acepta 0-100 y RECHAZA fuera de rango (es dinero: un descuento > 100% regala plata).
  B. El tope `0` es VÁLIDO ("este box no autoriza descuentos"); el saneador y la validación del
     endpoint coinciden en el rango (antes el saneador trataba 0 como inválido -> 50).
  C. El campo queda AUDITADO: está en `CAMPOS_EDITABLES`, lo que compara la auditoría antes/después.
  D. El default se mantiene en 50 (mismo valor en el diseño y en el saneador).
  E. El frontend tiene el campo (0-100).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_configuracion_descuento_beneficio.py -q --noconftest
"""
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1.configuracion import CAMPOS_EDITABLES, ConfiguracionUpdate   # noqa: E402
from app.services import beneficios_service as bs                            # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
CONFIG_JSX = "frontend/src/pages/admin/Configuracion.jsx"


def test_a_acepta_0_y_100_y_el_valor_tipico():
    assert ConfiguracionUpdate(beneficio_descuento_max_pct=0).beneficio_descuento_max_pct == 0
    assert ConfiguracionUpdate(beneficio_descuento_max_pct=100).beneficio_descuento_max_pct == 100
    assert ConfiguracionUpdate(beneficio_descuento_max_pct=30).beneficio_descuento_max_pct == 30
    # No mandarlo es válido (se conserva lo guardado).
    assert ConfiguracionUpdate().beneficio_descuento_max_pct is None


def test_a2_rechaza_fuera_de_rango():
    for malo in (-1, 101):
        with pytest.raises(Exception):
            ConfiguracionUpdate(beneficio_descuento_max_pct=malo)


def test_b_el_cero_es_valido_y_no_cae_al_default():
    assert bs._normalizar_tope(0) == 0        # "no autorizo descuentos"
    assert bs._normalizar_tope(50) == 50
    assert bs._normalizar_tope(100) == 100


def test_b2_basura_o_fuera_de_rango_usa_el_default():
    assert bs._normalizar_tope(101) == bs.TOPE_DESCUENTO_DEFAULT
    assert bs._normalizar_tope(-5) == bs.TOPE_DESCUENTO_DEFAULT
    assert bs._normalizar_tope(None) == bs.TOPE_DESCUENTO_DEFAULT
    assert bs._normalizar_tope(True) == bs.TOPE_DESCUENTO_DEFAULT
    assert bs._normalizar_tope("50") == bs.TOPE_DESCUENTO_DEFAULT


def test_c_el_campo_queda_auditado():
    assert "beneficio_descuento_max_pct" in CAMPOS_EDITABLES
    # La auditoría de los datos bancarios sigue intacta.
    for campo in ("banco", "numero_cuenta", "tipo_cuenta", "rut",
                  "email_comprobantes", "whatsapp"):
        assert campo in CAMPOS_EDITABLES


def test_d_el_default_sigue_siendo_50():
    assert bs.TOPE_DESCUENTO_DEFAULT == 50


def test_e_el_frontend_tiene_el_campo():
    fuente = (RAIZ / CONFIG_JSX).read_text(encoding="utf-8")
    assert 'name="beneficio_descuento_max_pct"' in fuente
    assert 'data-testid="config-descuento-max"' in fuente
    assert "min={0} max={100}" in fuente
