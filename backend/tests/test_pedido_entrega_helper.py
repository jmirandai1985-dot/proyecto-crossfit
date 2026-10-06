"""El helper `_crear_pedido` de test_pedido_entrega_codigo.py manda `tenant_id` (T6).

`PedidoCreate.tenant_id` es OBLIGATORIO: un POST /pedidos sin él daba 422 y los dos tests
que arman un pedido con el helper fallaban antes de probar nada. Este guard de fuente lo
fija (el helper tiene que mandar `tenant_id` junto con `alumno_id`).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_pedido_entrega_helper.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
FUENTE = "backend/tests/test_pedido_entrega_codigo.py"
ESQUEMA = "backend/app/schemas/pedido.py"


def test_el_helper_de_pedido_manda_tenant_id():
    fuente = (RAIZ / FUENTE).read_text(encoding="utf-8")
    inicio = fuente.index("def _crear_pedido")
    bloque = fuente[inicio:inicio + 700]
    assert '"tenant_id": alumno.tenant_id' in bloque
    assert '"alumno_id": alumno.id' in bloque


def test_el_esquema_sigue_exigiendo_tenant_id():
    esquema = (RAIZ / ESQUEMA).read_text(encoding="utf-8")
    assert "tenant_id: int = Field(..., gt=0" in esquema
