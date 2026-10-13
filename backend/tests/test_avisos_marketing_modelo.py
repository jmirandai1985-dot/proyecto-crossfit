"""
El modelo `AvisoMarketing` (migración 048) es el contrato de la tabla del carrusel.

QUÉ CUIDA ESTE TEST (y por qué aislado)
---------------------------------------
La tabla `avisos_marketing` la usan TRES caminos distintos —la pantalla Marketing
del admin, el Bazar cuando publica un producto con `dias_anuncio > 0` y el
carrusel del Inicio del alumno— y ninguno de los tres "ve" a los otros. El mismo
bug de la 042 (`clases.asignacion_origen`: migración creada, modelo sin la
columna → `TypeError` en el arranque) se repetiría acá en silencio: los avisos
del admin se guardarían y el carrusel no mostraría nada.

Estos tests cierran las puertas sin BD (`--noconftest`), contra el metadata del
modelo:
  * el constructor mapea TODAS las columnas (no quedan sueltas en `__dict__`);
  * el CHECK de tipos del modelo y el de la migración 048 son el MISMO set
    (si alguien agrega un tipo en un solo lado, el aviso se rechaza en la BD
    —o el carrusel no sabe pintarlo— y este test lo nombra);
  * la vigencia es obligatoria, `producto_id`/`creado_por` tienen el `ondelete`
    que evita avisos huérfanos, y hay UN solo aviso por producto y box;
  * la 048 es la única cabeza sobre la 047 (un segundo `down_revision` sobre la
    misma revisión = dos heads → `alembic upgrade head` falla en el deploy);
  * el modelo está exportado en `app/models/__init__.py` (es lo que hace que
    `Base.metadata.create_all()` —el setup de TEST— cree la tabla);
  * guard por AST: todo kwarg de un `AvisoMarketing(...)` del código de la app
    tiene que ser una columna mapeada (red general para los bloques 2 y 3).

    cd backend && py -3.12 -m pytest tests/test_avisos_marketing_modelo.py -q --noconftest
"""
import ast
import re
from pathlib import Path

from sqlalchemy import CheckConstraint

from app.models.aviso_marketing import (
    TIPOS_AVISO, TIPOS_EDITABLES, TIPO_AVISO, TIPO_COLABORACION, TIPO_EVENTO,
    TIPO_PRODUCTO_BAZAR, TIPO_PROMOCION, AvisoMarketing,
)

RAIZ = Path(__file__).resolve().parents[1]          # .../backend
VERSIONES = RAIZ / "alembic" / "versions"

REVISION = "048_avisos_marketing"
REVISION_PADRE = "047_notif_dia_chile"

# Los valores que declara el CHECK del modelo/migración, en el orden del mockup.
TIPOS_ESPERADOS = ("promocion", "colaboracion", "aviso", "evento",
                   "producto_bazar")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _fuente(relativa: str) -> str:
    # utf-8-sig: varios módulos del repo arrancan con BOM.
    return (RAIZ / relativa).read_text(encoding="utf-8-sig")


def _tipos_del_check(predicado: str) -> set:
    """Los valores tipo `'x'` o `"x"` de un `tipo IN ('x', 'y')`.

    El modelo escribe el CHECK con comillas simples (SQL) y la migración arma su
    lista TIPOS con dobles (Python): el helper acepta las dos.
    """
    return set(re.findall(r"['\"]([^'\"]+)['\"]", predicado))


def _check_del_modelo() -> str:
    """El SQL del CHECK de tipos declarado en el modelo."""
    checks = [c for c in AvisoMarketing.__table__.constraints
              if isinstance(c, CheckConstraint)
              and c.name == "ck_avisos_marketing_tipo"]
    assert len(checks) == 1, "el modelo declara exactamente un CHECK de tipo"
    return str(checks[0].sqltext)


# Los dos formatos históricos: `revision: str = 'x'` / `down_revision = "x"` /
# `down_revision: Union[str, None] = "x"` / la raíz `= None` (sin comillas).
_PATRON_REVISION = re.compile(
    r"^(?P<clave>(?:down_)?revision)\s*(?::\s*[^=]+)?=\s*['\"](?P<valor>[^'\"]+)['\"]",
    re.M)


def _migracion(relativa: str) -> dict:
    """Los identificadores de una migración, leídos del texto (sin importarla).

    Formatos históricos del repo: `revision: str = 'x'`, `down_revision = "x"`,
    `down_revision: Union[str, None] = "x"` y la raíz con `= None` (que queda en
    `None`).
    """
    fuente = (VERSIONES / relativa).read_text(encoding="utf-8-sig")
    datos = {"revision": None, "down_revision": None}
    for match in _PATRON_REVISION.finditer(fuente):
        datos[match.group("clave")] = match.group("valor")
    return datos


def _indice(nombre: str):
    indices = [i for i in AvisoMarketing.__table__.indexes if i.name == nombre]
    assert len(indices) == 1, f"falta el índice {nombre}"
    return indices[0]


def _columnas_de(comparacion) -> list:
    """Los nombres de columna de una comparación de índice, con o sin `.c.`."""
    nombres = []
    for parte in comparacion:
        texto = str(parte)
        # "avisos_marketing.tenant_id" -> "tenant_id" (también con `c.`).
        nombres.append(texto.rsplit(".", 1)[-1].strip())
    return nombres


def _kwargs_sin_mapear(fuente: str) -> list:
    """Kwargs de TODO `AvisoMarketing(...)` del código que no son columnas."""
    mapeadas = set(AvisoMarketing.__mapper__.attrs.keys())
    faltantes = []
    for nodo in ast.walk(ast.parse(fuente)):
        es_aviso = (isinstance(nodo, ast.Call)
                    and getattr(nodo.func, "id", None) == "AvisoMarketing")
        if not es_aviso:
            continue
        faltantes += [kw.arg for kw in nodo.keywords
                      if kw.arg and kw.arg not in mapeadas]
    return faltantes


# ── 1. El modelo mapea las columnas que la tabla necesita ───────────────────

def test_el_constructor_mapea_todas_las_columnas_del_aviso():
    """Si una columna no está mapeada, el `INSERT` del aviso se rompe en PROD."""
    aviso = AvisoMarketing(
        tenant_id=1, tipo=TIPO_PROMOCION, titulo="Trae un amigo este mes",
        texto="20% de descuento en su primera clase juntos.",
        imagen_url="/static/uploads/flyer.png", nombre_aliado=None,
        fecha_evento=None, vigente_desde=None, vigente_hasta=None,
        fijado_arriba=True, producto_id=None, creado_por=7,
    )
    mapeadas = set(AvisoMarketing.__mapper__.attrs.keys())
    assert {"tenant_id", "tipo", "titulo", "texto", "imagen_url",
            "nombre_aliado", "fecha_evento", "vigente_desde", "vigente_hasta",
            "fijado_arriba", "producto_id", "creado_por",
            "creado_en"} <= mapeadas
    # El valor quedó en el atributo mapeado, no suelto en `__dict__`.
    assert aviso.tipo == TIPO_PROMOCION and aviso.fijado_arriba is True
    assert aviso.creado_por == 7


def test_la_vigencia_es_obligatoria_y_el_contenido_opcional():
    """No hay aviso sin ventana (la sección se muestra sólo si está vigente)."""
    columnas = AvisoMarketing.__table__.c
    for obligatoria in ("tenant_id", "tipo", "titulo", "vigente_desde",
                        "vigente_hasta", "fijado_arriba", "creado_en"):
        assert columnas[obligatoria].nullable is False, obligatoria
    # Lo opcional: sin flyer la tarjeta se pinta con el color del tipo; el texto
    # puede faltar (un aviso del box puede ser sólo el titular).
    for opcional in ("texto", "imagen_url", "nombre_aliado", "fecha_evento",
                     "producto_id", "creado_por"):
        assert columnas[opcional].nullable is True, opcional


def test_el_orden_del_carrusel_tiene_sus_dos_columnas():
    """`fijado_arriba` primero y, a igualdad, `creado_en DESC`: sin default en
    `fijado_arriba` el `ORDER BY` compararía NULLs y el fijado no subiría."""
    columnas = AvisoMarketing.__table__.c
    assert columnas.fijado_arriba.default.arg is False
    assert columnas.fijado_arriba.nullable is False
    assert columnas.creado_en.server_default is not None


# ── 2. Tipos: modelo ↔ migración ↔ pantalla, un solo set ────────────────────

def test_los_tipos_del_check_son_los_esperados():
    assert TIPOS_AVISO == TIPOS_ESPERADOS
    assert _tipos_del_check(_check_del_modelo()) == set(TIPOS_ESPERADOS)


def test_el_check_de_la_migracion_es_espejo_del_modelo():
    """Agregar un tipo en un solo lado se caza acá (no en PROD)."""
    fuente = (VERSIONES / f"{REVISION}.py").read_text(encoding="utf-8-sig")
    tipos_migracion = re.search(r"^TIPOS = \(([^)]*)\)", fuente, re.M | re.S)
    assert tipos_migracion, "la migración declara TIPOS"
    assert _tipos_del_check(tipos_migracion.group(1)) == set(TIPOS_AVISO)
    # El CHECK de la migración se arma desde esa lista (una sola fuente).
    assert "_check_tipo_sql()" in fuente
    assert "name=CHECK_TIPO" in fuente


def test_los_4_tipos_del_selector_y_el_automatico_del_bazar():
    """El admin elige 4 (los del mockup); `producto_bazar` NO se crea a mano."""
    assert TIPOS_EDITABLES == (TIPO_PROMOCION, TIPO_COLABORACION, TIPO_AVISO,
                               TIPO_EVENTO)
    assert TIPO_PRODUCTO_BAZAR not in TIPOS_EDITABLES
    assert TIPO_PRODUCTO_BAZAR in TIPOS_AVISO


# ── 3. Los vínculos: producto y autor ───────────────────────────────────────

def _ondelete(columna: str) -> str:
    fks = list(AvisoMarketing.__table__.c[columna].foreign_keys)
    assert len(fks) == 1, columna
    return fks[0].ondelete


def test_un_solo_aviso_por_producto_y_box():
    """Re-publicar un producto del Bazar actualiza su aviso, no acumula tarjetas."""
    indice = _indice("uq_avisos_marketing_producto")
    assert indice.unique is True
    assert _columnas_de(indice.columns) == ["tenant_id", "producto_id"]


def test_los_vinculos_no_dejan_avisos_huerfanos():
    # Borrado duro del producto → se lleva su aviso; baja del usuario → el aviso
    # sigue (se pierde el nombre de quien lo publicó, no el aviso).
    assert _ondelete("producto_id") == "CASCADE"
    assert _ondelete("creado_por") == "SET NULL"
    assert _ondelete("tenant_id") == "CASCADE"


def test_los_indices_de_la_consulta_del_carrusel_existen():
    assert _columnas_de(_indice("ix_avisos_marketing_tenant_id").columns) == \
        ["tenant_id"]
    vigencia = _indice("ix_avisos_marketing_tenant_vigencia")
    assert _columnas_de(vigencia.columns) == [
        "tenant_id", "vigente_desde", "vigente_hasta"]


# ── 4. La migración y el registro del modelo ────────────────────────────────

def test_la_048_es_la_unica_cabeza_sobre_la_047():
    """Dos hijos de la misma revisión = dos heads y el deploy muere."""
    datos = _migracion(f"{REVISION}.py")
    assert datos["revision"] == REVISION
    assert datos["down_revision"] == REVISION_PADRE
    assert len(REVISION) <= 32, "alembic_version.version_num es VARCHAR(32)"

    hijos = [archivo.stem for archivo in VERSIONES.glob("*.py")
             if _migracion(archivo.name)["down_revision"] == REVISION_PADRE]
    assert hijos == [REVISION], f"cabezas sobre {REVISION_PADRE}: {hijos}"


def test_el_modelo_esta_registrado_para_create_all():
    """El setup de TEST crea las tablas con `create_all`: sin registrar, la tabla
    no existe y los tests de integración del carrusel darían 500."""
    fuente = _fuente("app/models/__init__.py")
    assert "from app.models.aviso_marketing import AvisoMarketing" in fuente
    assert '"AvisoMarketing"' in fuente


# ── 5. Guard general: ningún kwarg del constructor sin columna ──────────────

def test_ningun_kwarg_del_constructor_de_aviso_queda_sin_mapear():
    """Red general para los bloques 2 y 3 (el Bazar crea avisos por constructor)."""
    problemas = []
    for archivo in sorted((RAIZ / "app").rglob("*.py")):
        faltantes = _kwargs_sin_mapear(archivo.read_text(encoding="utf-8-sig"))
        problemas += [f"{archivo.relative_to(RAIZ)}: {kw}" for kw in faltantes]
    assert problemas == [], (
        "kwargs del constructor `AvisoMarketing(...)` que NO son columnas "
        f"mapeadas: {problemas}")


def test_el_guard_detecta_de_verdad_un_kwarg_inventado():
    """Meta-test: el guard de arriba no es decorativo."""
    fuente = ("def f(x):\n"
              "    return AvisoMarketing(id=x, tipo='promocion', inventada=1)\n")
    assert _kwargs_sin_mapear(fuente) == ["inventada"]
    assert _kwargs_sin_mapear("AvisoMarketing(vigente_desde=None)") == []


def test_el_parser_de_tipos_del_check_no_es_decorativo():
    """Meta-test del helper que compara modelo ↔ migración."""
    assert _tipos_del_check("tipo IN ('a', 'b')") == {"a", "b"}
    # La migración declara los tipos con comillas dobles (lista de Python).
    assert _tipos_del_check('TIPOS = ("a", "b")') == {"a", "b"}
    assert _tipos_del_check("tipo IN ('a', 'b')") != {"a"}
