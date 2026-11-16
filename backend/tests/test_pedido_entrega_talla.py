"""Entrega de pedidos del Bazar — la respuesta de `POST /entregar` incluye la TALLA.

Bug corregido
-------------
El coach entregaba un pedido con variantes y la pantalla sólo mostraba el nombre del
producto: no sabía qué talla entregar. `pedidos.talla` ya existe (snapshot de la
migración 083); faltaba exponerlo en `PedidoEntregaResponse`.

QUÉ FIJA ESTE ARCHIVO (aislado: sin red, sin API, sin base de datos)
--------------------------------------------------------------------
1. Un pedido CON variante devuelve `talla` (el texto del snapshot) y la respuesta
   serializada la incluye.
2. Un pedido de un producto SIN variantes devuelve `talla = None` (la pantalla no
   muestra nada, comportamiento intacto).
3. La entrega NO ejecuta ninguna escritura de stock: el único statement es el
   UPDATE del pedido. El descuento/devolución por variante vive en otros endpoints
   y no se toca acá.

POR QUÉ CON DOBLES Y NO CON SQLITE
----------------------------------
La tabla `pedidos` tiene un CHECK con regex de Postgres
(`codigo_retiro ~ '^UB-...'`) y `pagos` usa JSONB: `create_all` sobre SQLite no
puede crear ese esquema. El patrón aislado del repo para estos endpoints es el
doble de sesión (ver `tests/test_bazar_rechazo.py`), así que se reutiliza acá.
Se llama a `__wrapped__` para saltear sólo el rate-limit (slowapi); la lógica del
endpoint es la REAL, incluida la construcción de `PedidoEntregaResponse`.

    cd backend && py -3.12 -m pytest tests/test_pedido_entrega_talla.py -q --noconftest
"""
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1 import pedidos as ped
from app.models.pedido import Pedido
from app.models.producto import Producto
from app.models.usuario import Usuario
from app.schemas.pedido import PedidoEntregaRequest

COACH_ID = 77
TENANT = 1
AHORA = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


class _FakeQuery:
    def __init__(self, resultado):
        self._resultado = resultado

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._resultado


class _FakeDB:
    """Sesión mínima: responde Pedido / Producto.nombre / Usuario.nombre.

    Si el endpoint intentara tocar stock (ProductoVariante / UPDATE productos),
    `query` levantaría AssertionError: el test también vigila que la entrega sea
    SÓLO lectura del pedido.
    """

    def __init__(self, pedido, producto_nombre="Polera Urban Box",
                 alumno_nombre="Ana Alumna"):
        self.pedido = pedido
        self._producto_nombre = producto_nombre
        self._alumno_nombre = alumno_nombre
        self.consultas = []
        self.sentencias = []
        self.committed = False
        self.rolled_back = False

    def query(self, entidad):
        if entidad is Pedido:
            self.consultas.append("pedido")
            return _FakeQuery(self.pedido)
        if entidad is Producto.nombre:
            self.consultas.append("producto")
            return _FakeQuery(SimpleNamespace(nombre=self._producto_nombre))
        if entidad is Usuario.nombre:
            self.consultas.append("alumno")
            return _FakeQuery(SimpleNamespace(nombre=self._alumno_nombre))
        raise AssertionError(f"consulta inesperada: {entidad}")

    def execute(self, sentencia):
        # El endpoint hace un UPDATE condicional (estado sigue validado).
        self.sentencias.append(str(sentencia))
        self.pedido.estado = "entregado"
        self.pedido.entregado_por = COACH_ID
        self.pedido.entregado_en = AHORA
        return SimpleNamespace(rowcount=1)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, obj):
        pass


def _pedido(*, talla, variante_id):
    return SimpleNamespace(
        id=901, tenant_id=TENANT, alumno_id=42, producto_id=5,
        variante_id=variante_id, talla=talla, cantidad=2,
        estado="validado", codigo_retiro="UB-ABCD",
        entregado_por=None, entregado_en=None,
    )


def _entregar(db, monkeypatch):
    """Ejecuta el endpoint REAL salteando sólo el decorador de rate-limit."""
    # El aviso a la campana del alumno no es parte de este contrato.
    monkeypatch.setattr(ped, "notificar_alumno", lambda *a, **k: None)
    return ped.entregar_pedido_con_codigo.__wrapped__(
        request=None,
        data=PedidoEntregaRequest(codigo="UB-ABCD"),
        db=db,
        current_user={"usuario_id": COACH_ID, "tenant_id": TENANT,
                      "rol": "coach"},
    )


def test_entrega_con_variante_devuelve_la_talla(monkeypatch):
    db = _FakeDB(_pedido(talla="M", variante_id=55))

    respuesta = _entregar(db, monkeypatch)

    assert respuesta.pedido_id == 901
    assert respuesta.talla == "M"
    assert respuesta.producto_nombre == "Polera Urban Box"
    assert respuesta.cantidad == 2
    assert respuesta.codigo == "UB-ABCD"
    assert respuesta.entregado_en is not None

    # Lo que FastAPI serializa: la clave `talla` viaja con el valor del snapshot.
    cuerpo = respuesta.model_dump()
    assert cuerpo["talla"] == "M"
    # El contrato del coach sigue sin montos.
    assert "total" not in cuerpo and "precio" not in cuerpo

    # La talla sale del SNAPSHOT del pedido: no se consultó `producto_variantes`.
    assert db.consultas == ["pedido", "producto", "alumno"]
    assert db.committed and not db.rolled_back


def test_entrega_sin_variantes_devuelve_talla_none(monkeypatch):
    db = _FakeDB(_pedido(talla=None, variante_id=None))

    respuesta = _entregar(db, monkeypatch)

    assert respuesta.talla is None
    assert respuesta.model_dump()["talla"] is None
    # El resto de la respuesta no cambia para productos sin tallas.
    assert respuesta.producto_nombre == "Polera Urban Box"
    assert respuesta.cantidad == 2
    assert respuesta.codigo == "UB-ABCD"


def test_la_entrega_no_escribe_stock(monkeypatch):
    """Sólo se actualiza el pedido: el stock por variante no se toca en /entregar."""
    db = _FakeDB(_pedido(talla="S", variante_id=56))

    _entregar(db, monkeypatch)

    assert len(db.sentencias) == 1
    unico = db.sentencias[0].upper()
    assert unico.startswith("UPDATE PEDIDOS")
    assert "PRODUCTO_VARIANTES" not in unico
    assert "PRODUCTOS" not in unico

