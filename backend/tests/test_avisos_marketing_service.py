"""
Los avisos de marketing: la ventana de vigencia, las reglas por tipo y el orden.

POR QUÉ AISLADO (y qué cierra)
------------------------------
El carrusel del Inicio del alumno es la cara visible de esto, pero los errores
caros son silenciosos y NO se ven en la pantalla del admin:

  * la VENTANA. El admin elige dos DÍAS ("del 12 al 31 de octubre") y la BD guarda
    INSTANTES de Chile. Si el `vigente_hasta` se guardara a las 00:00, el aviso
    desaparecería el propio 31 a la madrugada (el día de cierre tiene que valer
    completo, la misma regla de `suscripciones.fecha_expiracion`); si se guardara
    con la TZ del proceso (UTC en PROD), un aviso que empieza "hoy" no se vería
    hasta las 03:00 hora de Chile.
  * el ORDEN. `fijado_arriba` primero y, a igualdad, `creado_en DESC`: si el orden
    se invirtiera, "fijar arriba" no haría nada y nadie lo notaría hasta que el
    admin reclamara.
  * las REGLAS por tipo (Colaboración pide aliado, Evento pide fecha) y el apagado
    de los campos que no aplican: un aliado guardado dentro de una Promoción
    reaparece si después alguien cambia el tipo.
  * el TENANT y quién puede escribir: todas las mutaciones son del ADMIN y el
    tenant sale del TOKEN (un aviso de un box no se ve ni se toca desde otro).

    cd backend && py -3.12 -m pytest tests/test_avisos_marketing_service.py -q --noconftest
"""
import ast
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.aviso_marketing import (TIPO_AVISO, TIPO_COLABORACION,
                                        TIPO_EVENTO, TIPO_PRODUCTO_BAZAR,
                                        TIPO_PROMOCION, AvisoMarketing)
from app.models.producto import Producto
from app.services import avisos_marketing as servicio
from app.utils.santiago import fecha_chile, hoy_santiago

RAIZ = Path(__file__).resolve().parents[1]          # .../backend
ROUTER = RAIZ / "app" / "api" / "v1" / "marketing.py"

HOY = hoy_santiago()


def _aviso(**cambios):
    """Una fila `avisos_marketing` de mentira (sólo atributos: no hay BD)."""
    base = dict(
        id=1, tenant_id=7, tipo=TIPO_PROMOCION, titulo="Trae un amigo",
        texto="20% de descuento", imagen_url=None, nombre_aliado=None,
        fecha_evento=None,
        vigente_desde=datetime.combine(HOY - timedelta(days=1), time(0, 0),
                                       tzinfo=timezone.utc),
        vigente_hasta=datetime.combine(HOY + timedelta(days=5), time(23, 59, 59),
                                       tzinfo=timezone.utc),
        fijado_arriba=False, producto_id=None, creado_por=None,
        creado_en=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
    )
    base.update(cambios)
    return SimpleNamespace(**base)


def _producto(**cambios):
    base = dict(id=3, nombre="Polera Urban Box", precio=12990.0,
                imagen_url="/static/uploads/polera.png", activo=True)
    base.update(cambios)
    return SimpleNamespace(**base)


def _datos(**cambios):
    """Payload válido de una Promoción; cada test cambia lo que le importa."""
    base = dict(tipo=TIPO_PROMOCION, titulo="Trae un amigo este mes",
                texto="Tú y tu invitado reciben 20% de descuento.",
                nombre_aliado=None, fecha_evento=None,
                vigente_desde=HOY, vigente_hasta=HOY + timedelta(days=19),
                fijado_arriba=False)
    base.update(cambios)
    return base


class _Consulta:
    """La cadena `query(...).outerjoin(...).filter(...).order_by(...).all()`."""

    def __init__(self, filas=()):
        self.filas = list(filas)
        self.filtros = []
        self.orden = ()
        self.joins = []

    def outerjoin(self, *args, **kwargs):
        self.joins.append(args)
        return self

    def filter(self, *criterios):
        self.filtros.extend(criterios)
        return self

    def order_by(self, *criterios):
        self.orden = criterios
        return self

    def all(self):
        return list(self.filas)


class _SesionFalsa:
    def __init__(self, filas=()):
        self.consulta = _Consulta(filas)
        self.agregadas = []
        self.borradas = []
        self.commits = 0
        self.args_query = None

    def query(self, *args):
        self.args_query = args
        return self.consulta

    def add(self, objeto):
        self.agregadas.append(objeto)

    def delete(self, objeto):
        self.borradas.append(objeto)

    def commit(self):
        self.commits += 1

    def refresh(self, objeto):
        pass


def _sql(criterios) -> str:
    return " | ".join(str(criterio) for criterio in criterios)


# ── 1. La ventana: de DÍAS del admin a INSTANTES de Chile ───────────────────

def test_rango_vigencia_toma_el_dia_completo_en_chile():
    desde, hasta = servicio.rango_vigencia(date(2026, 10, 12), date(2026, 10, 31))
    assert (desde.hour, desde.minute, desde.second) == (0, 0, 0)
    # El ÚLTIMO día vale completo: si fuera 00:00, el aviso desaparecería el propio
    # 31 a la madrugada.
    assert (hasta.hour, hasta.minute, hasta.second) == (23, 59, 59)
    # Los dos instantes caen en el día calendario que eligió el admin (Chile).
    assert fecha_chile(desde) == date(2026, 10, 12)
    assert fecha_chile(hasta) == date(2026, 10, 31)


def test_un_aviso_de_un_solo_dia_dura_ese_dia_entero():
    desde, hasta = servicio.rango_vigencia(HOY, HOY)
    assert servicio.esta_vigente(desde, hasta, ahora=desde)
    assert servicio.esta_vigente(desde, hasta, ahora=hasta)
    assert fecha_chile(desde) == fecha_chile(hasta) == HOY


def test_los_bordes_de_la_ventana_estan_incluidos():
    desde, hasta = servicio.rango_vigencia(date(2026, 10, 12), date(2026, 10, 31))
    assert servicio.esta_vigente(desde, hasta, ahora=desde)
    assert servicio.esta_vigente(desde, hasta, ahora=hasta)
    # Un segundo afuera ya no: es lo que hace que "hasta el 31" no incluya el 1.
    assert not servicio.esta_vigente(desde, hasta,
                                     ahora=desde - timedelta(seconds=1))
    assert not servicio.esta_vigente(desde, hasta,
                                     ahora=hasta + timedelta(seconds=1))


def test_una_ventana_sin_fechas_nunca_esta_vigente():
    assert servicio.esta_vigente(None, None) is False


# ── 2. Las reglas por tipo ──────────────────────────────────────────────────

def test_una_promocion_completa_no_tiene_errores():
    assert servicio.validar(_datos()) == []


def test_el_titulo_y_el_texto_son_obligatorios():
    errores = servicio.validar(_datos(titulo="   ", texto=""))
    assert any("título" in error for error in errores)
    assert any("texto" in error for error in errores)


def test_los_largos_maximos_son_los_de_las_columnas():
    assert any("150" in error
               for error in servicio.validar(_datos(titulo="x" * 151)))
    assert any("1000" in error
               for error in servicio.validar(_datos(texto="x" * 1001)))


def test_la_vigencia_es_obligatoria():
    errores = servicio.validar(_datos(vigente_desde=None, vigente_hasta=None))
    assert any("obligatoria" in error for error in errores)


def test_la_vigencia_no_puede_terminar_antes_de_empezar():
    errores = servicio.validar(_datos(vigente_desde=date(2026, 10, 31),
                                      vigente_hasta=date(2026, 10, 12)))
    assert any("antes de empezar" in error for error in errores)


def test_una_colaboracion_necesita_el_nombre_del_aliado():
    assert any("aliado" in error
               for error in servicio.validar(_datos(tipo=TIPO_COLABORACION)))
    assert servicio.validar(_datos(tipo=TIPO_COLABORACION,
                                   nombre_aliado="Nutri Maipú")) == []


def test_un_evento_necesita_su_fecha():
    assert any("fecha" in error
               for error in servicio.validar(_datos(tipo=TIPO_EVENTO)))
    assert servicio.validar(_datos(tipo=TIPO_EVENTO,
                                   fecha_evento=HOY + timedelta(days=12))) == []


def test_el_aviso_de_producto_del_bazar_no_se_crea_a_mano():
    """`producto_bazar` lo mantiene el Bazar: por la API del admin no entra."""
    errores = servicio.validar(_datos(tipo=TIPO_PRODUCTO_BAZAR))
    assert any("tipo" in error for error in errores)


# ── 3. Normalizar: los campos que no aplican se APAGAN ──────────────────────

def test_normalizar_apaga_los_campos_que_no_aplican_al_tipo():
    limpio = servicio.normalizar(_datos(tipo=TIPO_PROMOCION,
                                        nombre_aliado="Nutri Maipú",
                                        fecha_evento=HOY))
    assert limpio["nombre_aliado"] is None
    assert limpio["fecha_evento"] is None


def test_normalizar_conserva_lo_que_si_aplica():
    colaboracion = servicio.normalizar(
        _datos(tipo=TIPO_COLABORACION, nombre_aliado="  Nutri Maipú  "))
    assert colaboracion["nombre_aliado"] == "Nutri Maipú"
    evento = servicio.normalizar(_datos(tipo=TIPO_EVENTO, fecha_evento=HOY))
    assert evento["fecha_evento"] == HOY


def test_normalizar_recorta_y_deja_none_el_texto_vacio():
    limpio = servicio.normalizar(_datos(titulo="  Trae un amigo  ", texto="   "))
    assert limpio["titulo"] == "Trae un amigo"
    assert limpio["texto"] is None


# ── 4. Serializar y el orden del carrusel ───────────────────────────────────

def test_serializar_marca_la_vigencia_y_trae_los_datos_del_producto():
    fila = servicio.serializar(_aviso(producto_id=3), _producto())
    assert fila["vigente"] is True
    # La tarjeta del alumno muestra el producto REAL: si el admin cambia el precio
    # en el Bazar, el aviso lo refleja.
    assert fila["producto_nombre"] == "Polera Urban Box"
    assert fila["producto_precio"] == 12990.0
    assert fila["producto_imagen_url"] == "/static/uploads/polera.png"


def test_serializar_sin_producto_no_inventa_datos():
    fila = servicio.serializar(_aviso())
    assert fila["producto_id"] is None
    assert fila["producto_nombre"] is None
    assert fila["producto_precio"] is None


def test_serializar_marca_vencido_un_aviso_que_ya_paso():
    pasado = _aviso(vigente_hasta=datetime.combine(
        HOY - timedelta(days=10), time(23, 59, 59), tzinfo=timezone.utc))
    assert servicio.serializar(pasado)["vigente"] is False


def test_el_orden_del_carrusel_es_fijado_primero_y_despues_el_mas_nuevo():
    primero, segundo = servicio.orden_carrusel()
    assert "fijado_arriba DESC" in str(primero)
    assert "creado_en DESC" in str(segundo)


# ── 5. Las consultas (con la sesión falsa) ──────────────────────────────────

def test_vigentes_pide_solo_los_avisos_vigentes_del_box():
    db = _SesionFalsa(filas=[(_aviso(), None), (_aviso(id=2), _producto())])
    filas = servicio.vigentes(db, 7)

    assert [fila["id"] for fila in filas] == [1, 2]
    # UN JOIN a productos (la tarjeta necesita foto/nombre/precio del producto).
    assert db.args_query == (AvisoMarketing, Producto)
    criterios = _sql(db.consulta.filtros)
    assert "avisos_marketing.tenant_id" in criterios
    assert "vigente_desde <=" in criterios and "vigente_hasta >=" in criterios
    # Un producto retirado (activo=false) no se anuncia.
    assert "productos.activo" in criterios
    assert db.consulta.orden, "el carrusel SIEMPRE viene ordenado"


def test_vigentes_devuelve_vacio_si_no_hay_nada_vigente():
    """Sin avisos, el Inicio no dibuja la sección (nunca un carrusel vacío)."""
    assert servicio.vigentes(_SesionFalsa(filas=[]), 7) == []


def test_el_filtro_todos_no_agrega_ventana():
    db = _SesionFalsa()
    servicio.listar(db, 7, filtro="todos")
    assert "vigente_desde <=" not in _sql(db.consulta.filtros)


@pytest.mark.parametrize("filtro,predicado", [
    ("vigentes", "vigente_desde <="),
    ("programados", "vigente_desde >"),
    ("vencidos", "vigente_hasta <"),
])
def test_cada_filtro_del_admin_es_un_predicado_distinto(filtro, predicado):
    db = _SesionFalsa()
    servicio.listar(db, 7, filtro=filtro)
    assert predicado in _sql(db.consulta.filtros), filtro


def test_un_filtro_desconocido_cae_en_todos():
    db = _SesionFalsa()
    servicio.listar(db, 7, filtro="cualquier-cosa")
    assert "vigente_desde <=" not in _sql(db.consulta.filtros)


# ── 6. Crear / actualizar / eliminar ────────────────────────────────────────

def test_crear_guarda_la_ventana_como_instantes_y_el_autor():
    db = _SesionFalsa()
    servicio.crear(db, tenant_id=7, datos=_datos(), creado_por=42)

    aviso = db.agregadas[0]
    assert aviso.tenant_id == 7 and aviso.creado_por == 42
    assert aviso.tipo == TIPO_PROMOCION
    assert (aviso.vigente_desde.hour, aviso.vigente_hasta.hour) == (0, 23)
    assert aviso.fijado_arriba is False
    assert db.commits == 1


def test_crear_es_fijable_y_acepta_el_flyer_ya_subido():
    db = _SesionFalsa()
    servicio.crear(db, 7, _datos(fijado_arriba=True,
                                 imagen_url="/static/uploads/flyer.png"))
    aviso = db.agregadas[0]
    assert aviso.fijado_arriba is True
    assert aviso.imagen_url == "/static/uploads/flyer.png"


def test_crear_rechaza_un_payload_invalido_sin_tocar_la_bd():
    db = _SesionFalsa()
    with pytest.raises(ValueError) as error:
        servicio.crear(db, 7, _datos(tipo=TIPO_COLABORACION))
    assert any("aliado" in mensaje for mensaje in error.value.args[0])
    assert db.agregadas == [] and db.commits == 0


def test_actualizar_reemplaza_los_campos_editables():
    aviso = _aviso()
    db = _SesionFalsa()
    servicio.actualizar(db, aviso, _datos(
        tipo=TIPO_AVISO, titulo="  Mantención sábado  ",
        texto="No habrá clases en la mañana.", fijado_arriba=True))

    assert aviso.tipo == TIPO_AVISO
    assert aviso.titulo == "Mantención sábado"
    assert aviso.fijado_arriba is True
    assert (aviso.vigente_desde.hour, aviso.vigente_hasta.hour) == (0, 23)
    assert aviso.producto_id is None, "el vínculo con el Bazar no se toca"
    assert db.commits == 1


def test_actualizar_apaga_los_campos_del_tipo_anterior():
    aviso = _aviso(tipo=TIPO_COLABORACION, nombre_aliado="Nutri Maipú")
    servicio.actualizar(_SesionFalsa(), aviso, _datos(tipo=TIPO_PROMOCION))
    assert aviso.nombre_aliado is None


def test_actualizar_no_deja_un_evento_sin_fecha():
    """Cambiar un Aviso a Evento tiene que pedir la fecha en la misma vuelta."""
    with pytest.raises(ValueError) as error:
        servicio.actualizar(_SesionFalsa(), _aviso(), _datos(tipo=TIPO_EVENTO))
    assert any("fecha" in mensaje for mensaje in error.value.args[0])


def test_eliminar_devuelve_el_flyer_para_borrar_el_archivo():
    aviso = _aviso(imagen_url="/static/uploads/flyer.png")
    db = _SesionFalsa()
    assert servicio.eliminar(db, aviso) == "/static/uploads/flyer.png"
    assert db.borradas == [aviso] and db.commits == 1


def test_eliminar_un_aviso_sin_flyer_no_pide_borrar_nada():
    assert servicio.eliminar(_SesionFalsa(), _aviso()) is None


# ── 7. El router: quién puede escribir y de dónde sale el tenant ────────────

MUTACIONES = ("post", "put", "patch", "delete")


def _rutas() -> list:
    """`[(metodo, ruta, nodo_funcion, nodo_decorador)]` de `@router.<metodo>(...)`."""
    fuente = ROUTER.read_text(encoding="utf-8-sig")
    rutas = []
    for nodo in ast.walk(ast.parse(fuente)):
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for decorador in nodo.decorator_list:
            es_router = (isinstance(decorador, ast.Call)
                         and isinstance(decorador.func, ast.Attribute)
                         and isinstance(decorador.func.value, ast.Name)
                         and decorador.func.value.id == "router")
            if es_router and decorador.args:
                rutas.append((decorador.func.attr,
                              ast.literal_eval(decorador.args[0]),
                              nodo, decorador))
    return rutas


def test_las_mutaciones_del_carrusel_son_solo_del_admin():
    rutas = _rutas()
    assert rutas, "el router no declara ninguna ruta"
    for metodo, ruta, nodo, decorador in rutas:
        if metodo in MUTACIONES:
            assert "get_current_admin" in ast.unparse(nodo), \
                f"{metodo.upper()} {ruta}"
            assert "require_full_access" in ast.unparse(decorador), \
                f"{metodo.upper()} {ruta}"


def test_la_unica_lectura_abierta_es_la_del_carrusel():
    """`/vigentes` lo pide el Inicio del alumno; la lista completa es del admin."""
    abiertas = [ruta for metodo, ruta, nodo, decorador in _rutas()
                if metodo == "get"
                and "require_full_access" not in ast.unparse(decorador)]
    assert abiertas == ["/vigentes"]


def test_el_tenant_sale_del_token_y_nunca_de_un_parametro():
    fuente = ROUTER.read_text(encoding="utf-8-sig")
    assert 'current_user["tenant_id"]' in fuente
    for sospechoso in ("tenant_id: Optional[int]", "tenant_id: int = Query",
                       "tenant_id: int = Form", "tenant_id: int = None"):
        assert sospechoso not in fuente, sospechoso


def test_el_router_esta_montado_en_la_app():
    main = (RAIZ / "app" / "main.py").read_text(encoding="utf-8-sig")
    assert "beneficios, marketing" in main
    assert ('app.include_router(marketing.router, prefix="/api/v1/marketing"'
            in main)


def test_el_flyer_comparte_el_camino_de_la_foto_del_producto():
    """Aviso y producto suben imágenes con la MISMA función (y sus chequeos)."""
    productos = (RAIZ / "app" / "api" / "v1" / "productos.py").read_text(
        encoding="utf-8-sig")
    for fuente in (ROUTER.read_text(encoding="utf-8-sig"), productos):
        assert ("from app.core.imagenes_publicas import guardar_imagen_publica"
                in fuente)
        assert "guardar_imagen_publica(" in fuente
    # ... y ese módulo es el único que valida el contenido real por magic bytes.
    core = (RAIZ / "app" / "core" / "imagenes_publicas.py").read_text(
        encoding="utf-8-sig")
    assert "validar_archivo" in core
    assert "storage.guardar_publico" in core

