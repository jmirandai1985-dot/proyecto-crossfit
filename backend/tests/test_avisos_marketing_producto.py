"""
El aviso de producto nuevo del Bazar (Bloque 3): derivado, y sin romper la foto.

QUÉ CUIDA ESTE TEST
-------------------
`productos.dias_anuncio` (migración 049) es la ÚNICA perilla que el admin usa:
"anúncialo N días". Todo lo demás es DERIVADO y tiene trampas caras:

  * la VENTANA cuenta HOY como el primer día (1 día = sólo hoy hasta las 23:59:59
    de Chile). Si contara desde mañana, "anunciar 1 día" no anunciaría nada;
  * editar un producto NO puede REINICIAR el anuncio: si cada guardado reabriera la
    ventana, un admin que toca el stock todos los días tendría el producto
    anunciado para siempre y no habría forma de que caducara;
  * el "flyer" de este aviso ES la foto del producto (`imagen_url` compartida):
    borrar el aviso NO puede borrar el archivo, o el producto se queda sin foto en
    el Bazar. Es el error silencioso más caro de este bloque;
  * el aviso de un producto NO se edita a mano (su título, precio y foto salen del
    producto): la API del admin lo rechaza.

    cd backend && py -3.12 -m pytest tests/test_avisos_marketing_producto.py -q --noconftest
"""
import ast
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.aviso_marketing import TIPO_PRODUCTO_BAZAR, TIPO_PROMOCION
from app.models.producto import Producto
from app.schemas.producto import (ProductoCreate, ProductoListItem,
                                  ProductoUpdate)
from app.services import avisos_marketing as servicio
from app.utils.santiago import fecha_chile, hoy_santiago

RAIZ = Path(__file__).resolve().parents[1]          # .../backend
VERSIONES = RAIZ / "alembic" / "versions"
PRODUCTOS_PY = RAIZ / "app" / "api" / "v1" / "productos.py"
MARKETING_PY = RAIZ / "app" / "api" / "v1" / "marketing.py"

HOY = hoy_santiago()
AHORA = datetime.combine(HOY, time(12, 0), tzinfo=timezone.utc)


def _producto(**cambios):
    base = dict(id=3, tenant_id=7, nombre="Polera Urban Box", precio=12990.0,
                imagen_url="/static/uploads/polera.png", activo=True,
                dias_anuncio=5)
    base.update(cambios)
    return SimpleNamespace(**base)


def _aviso(**cambios):
    base = dict(
        id=1, tenant_id=7, tipo=TIPO_PRODUCTO_BAZAR, titulo="Polera Urban Box",
        texto="Disponible en el Bazar", imagen_url="/static/uploads/polera.png",
        nombre_aliado=None, fecha_evento=None,
        vigente_desde=datetime.combine(HOY, time(0, 0), tzinfo=timezone.utc),
        vigente_hasta=datetime.combine(HOY + timedelta(days=4), time(23, 59, 59),
                                       tzinfo=timezone.utc),
        fijado_arriba=False, producto_id=3, creado_por=None,
        creado_en=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
    )
    base.update(cambios)
    return SimpleNamespace(**base)


class _Consulta:
    def __init__(self, fila=None):
        self.fila = fila
        self.filtros = []

    def filter(self, *criterios):
        self.filtros.extend(criterios)
        return self

    def first(self):
        return self.fila


class _SesionFalsa:
    def __init__(self, aviso=None):
        self.consulta = _Consulta(aviso)
        self.agregadas = []
        self.borradas = []
        self.commits = 0

    def query(self, *args):
        return self.consulta

    def add(self, objeto):
        self.agregadas.append(objeto)

    def delete(self, objeto):
        self.borradas.append(objeto)

    def commit(self):
        self.commits += 1

    def refresh(self, objeto):
        pass


# ── 1. La columna, la migración y los esquemas ─────────────────────────────-

def test_la_migracion_049_agrega_la_columna_con_default_cero():
    fuente = (VERSIONES / "049_productos_dias_anuncio.py").read_text(
        encoding="utf-8-sig")
    assert 'revision: str = "049_productos_dias_anuncio"' in fuente
    assert 'down_revision: Union[str, None] = "048_avisos_marketing"' in fuente
    assert "DIAS_DEFAULT = 0" in fuente
    assert "server_default=sa.text(str(DIAS_DEFAULT))" in fuente
    assert "nullable=False" in fuente


def test_la_049_es_la_unica_cabeza_sobre_la_048():
    hijos = []
    for archivo in VERSIONES.glob("*.py"):
        texto = archivo.read_text(encoding="utf-8-sig")
        if 'down_revision: Union[str, None] = "048_avisos_marketing"' in texto:
            hijos.append(archivo.stem)
    assert hijos == ["049_productos_dias_anuncio"], hijos


def test_el_modelo_declara_la_columna_con_default_cero():
    columna = Producto.__table__.c.dias_anuncio
    assert columna.nullable is False
    assert columna.default.arg == 0


def test_los_esquemas_exponen_los_dias_de_anuncio():
    # Crear: 0 por defecto (no anunciar).
    assert ProductoCreate(
        tenant_id=1, nombre="Polera", precio=1000, stock=1).dias_anuncio == 0
    # Editar: None por defecto, para NO tocarlo si el payload no lo manda.
    assert ProductoUpdate().dias_anuncio is None
    assert ProductoListItem.model_fields["dias_anuncio"].default == 0
    # El tope: un año (no tiene sentido anunciar para siempre).
    assert ProductoUpdate(dias_anuncio=365).dias_anuncio == 365
    with pytest.raises(Exception):
        ProductoUpdate(dias_anuncio=366)


# ── 2. Sin días: no se anuncia (y se quita lo que hubiera) ──────────────────

def test_sin_dias_y_sin_aviso_no_toca_nada():
    db = _SesionFalsa(aviso=None)
    assert servicio.sincronizar_producto(db, _producto(dias_anuncio=0),
                                         ahora=AHORA) is None
    assert db.agregadas == [] and db.borradas == [] and db.commits == 0


def test_con_cero_dias_se_quita_el_aviso_que_existia():
    aviso = _aviso()
    db = _SesionFalsa(aviso=aviso)
    assert servicio.sincronizar_producto(db, _producto(dias_anuncio=0),
                                         ahora=AHORA) is None
    assert db.borradas == [aviso]
    assert db.commits == 1


# ── 3. Con días: el aviso se crea con la ventana de HOY ─────────────────────

def test_con_dias_se_crea_el_aviso_del_producto():
    db = _SesionFalsa(aviso=None)
    fila = servicio.sincronizar_producto(db, _producto(dias_anuncio=5),
                                         creado_por=9, ahora=AHORA)

    creado = db.agregadas[0]
    assert creado.tipo == TIPO_PRODUCTO_BAZAR
    assert creado.tenant_id == 7
    # El VÍNCULO con el producto: sin `producto_id` la tarjeta no tendría de dónde
    # sacar la foto ni el precio (y el índice único de la 048 no haría nada).
    assert creado.producto_id == 3
    assert creado.creado_por == 9
    # Título, texto y foto salen del PRODUCTO (el mockup dice "Disponible en el Bazar").
    assert creado.titulo == "Polera Urban Box"
    assert creado.texto == servicio.TEXTO_PRODUCTO
    assert creado.imagen_url == "/static/uploads/polera.png"
    # Un aviso automático nunca queda fijado: lo que el admin fija manda.
    assert creado.fijado_arriba is False
    assert db.commits == 1
    # ... y se devuelve ya serializado, con los datos del producto resueltos.
    assert fila["producto_nombre"] == "Polera Urban Box"
    assert fila["vigente"] is True


def test_la_ventana_cuenta_hoy_como_el_primer_dia():
    db = _SesionFalsa(aviso=None)
    servicio.sincronizar_producto(db, _producto(dias_anuncio=1), ahora=AHORA)
    aviso = db.agregadas[0]
    # Un día = SÓLO hoy: arranca a las 00:00 y termina a las 23:59:59 de Chile.
    assert fecha_chile(aviso.vigente_desde) == HOY
    assert fecha_chile(aviso.vigente_hasta) == HOY
    assert aviso.vigente_desde.hour == 0 and aviso.vigente_hasta.hour == 23

    db = _SesionFalsa(aviso=None)
    servicio.sincronizar_producto(db, _producto(dias_anuncio=7), ahora=AHORA)
    siete = db.agregadas[0]
    assert fecha_chile(siete.vigente_hasta) == HOY + timedelta(days=6)


# ── 4. Editar el producto no puede estirar un anuncio en curso ──────────────

def test_un_aviso_vigente_conserva_su_ventana_y_refresca_su_contenido():
    db = _SesionFalsa(aviso=_aviso(titulo="Polera vieja",
                                   imagen_url="/static/uploads/vieja.png"))
    servicio.sincronizar_producto(
        db, _producto(nombre="Polera Urban Box v2",
                      imagen_url="/static/uploads/nueva.png", dias_anuncio=30),
        ahora=AHORA)

    aviso = db.consulta.fila
    assert fecha_chile(aviso.vigente_hasta) == HOY + timedelta(days=4), \
        "editar el producto NO puede reiniciar el plazo"
    assert aviso.titulo == "Polera Urban Box v2"
    assert aviso.imagen_url == "/static/uploads/nueva.png"
    assert db.commits == 1


def test_un_aviso_vencido_se_reabre_desde_hoy():
    vencido = _aviso(vigente_hasta=datetime.combine(
        HOY - timedelta(days=3), time(23, 59, 59), tzinfo=timezone.utc))
    db = _SesionFalsa(aviso=vencido)
    servicio.sincronizar_producto(db, _producto(dias_anuncio=5), ahora=AHORA)

    assert fecha_chile(vencido.vigente_desde) == HOY
    assert fecha_chile(vencido.vigente_hasta) == HOY + timedelta(days=4)


# ── 5. La foto del producto NO se borra con el aviso ────────────────────────

def test_borrar_el_aviso_de_un_producto_no_pide_borrar_la_foto():
    """El `imagen_url` del aviso ES la foto del producto: borrarla lo dejaría sin
    foto en el Bazar (y nadie lo notaría hasta que alguien entrara a la tienda)."""
    aviso = _aviso()
    assert servicio.url_a_borrar(aviso) is None
    db = _SesionFalsa(aviso=aviso)
    assert servicio.eliminar(db, aviso) is None
    assert len(db.borradas) == 1 and db.commits == 1


def test_borrar_un_aviso_manual_si_devuelve_su_flyer():
    manual = _aviso(tipo=TIPO_PROMOCION, producto_id=None,
                    imagen_url="/static/uploads/flyer.png")
    assert servicio.url_a_borrar(manual) == "/static/uploads/flyer.png"


# ── 6. El cableado: quién llama al sync y quién edita el aviso ─────────────-

def _llamadas_al_sync(fuente: str) -> int:
    """Cuenta las LLAMADAS al sync (un comentario que lo mencione no cuenta)."""
    total = 0
    for nodo in ast.walk(ast.parse(fuente)):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "sincronizar_producto"):
            total += 1
    return total


def test_crear_y_editar_un_producto_sincronizan_su_aviso():
    fuente = PRODUCTOS_PY.read_text(encoding="utf-8-sig")
    assert "from app.services import avisos_marketing as avisos" in fuente
    # DOS llamadas: la del POST (producto recién creado) y la del PUT, que además
    # está guardada por `if "dias_anuncio" in update_data` para no reabrir un
    # anuncio viejo cada vez que alguien edita el stock.
    assert _llamadas_al_sync(fuente) == 2
    assert "avisos.sincronizar_producto(db, db_producto," in fuente
    assert "avisos.sincronizar_producto(db, producto," in fuente
    assert 'if "dias_anuncio" in update_data:' in fuente
    # El Form y el modelo llevan la columna (sin ella, el guardado la pierde).
    assert "dias_anuncio: Optional[int] = Form(None)" in fuente
    assert "dias_anuncio=max(int(dias_anuncio or 0), 0)" in fuente


def test_el_aviso_de_un_producto_no_se_edita_desde_marketing():
    fuente = MARKETING_PY.read_text(encoding="utf-8-sig")
    assert "def _solo_manuales(" in fuente
    # Tres usos además de la definición: PUT, subir flyer y quitar flyer.
    assert fuente.count("_solo_manuales(aviso)") == 3


def test_la_ventana_del_aviso_no_se_arma_a_mano_en_la_ruta():
    """Los días de calendario -> instantes de Chile son del SERVICIO (una sola vez)."""
    fuente = PRODUCTOS_PY.read_text(encoding="utf-8-sig")
    assert "fin_del_dia_chile" not in fuente
    assert "inicio_del_dia_chile" not in fuente
    servicio_py = (RAIZ / "app" / "services" / "avisos_marketing.py").read_text(
        encoding="utf-8-sig")
    assert "inicio_del_dia_chile(hoy)" in servicio_py
    assert "fin_del_dia_chile(desde + timedelta(days=" in servicio_py


def test_el_sync_tiene_una_sola_puerta():
    """Meta-guard: `sincronizar_producto` sólo lo LLAMA la ruta de productos."""
    llamadas = [archivo.name for archivo in sorted((RAIZ / "app").rglob("*.py"))
                if archivo.name != "avisos_marketing.py"
                and _llamadas_al_sync(archivo.read_text(encoding="utf-8-sig"))]
    assert llamadas == ["productos.py"], llamadas


def test_la_ruta_le_pasa_quien_publico_el_anuncio():
    """`creado_por`: la traza de quién anunció el producto (la usa el aviso)."""
    fuente = PRODUCTOS_PY.read_text(encoding="utf-8-sig")
    assert fuente.count('creado_por=current_user["usuario_id"]') == 2


