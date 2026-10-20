"""
El esquema de Referidos + Invitación por correo es el contrato de las fases 1-5.
Este test lo cuida SIN base de datos (`--noconftest`):

  * las tablas del módulo existen en el metadata con las columnas pedidas,
    incluido el snapshot del premio de Fase 5 (`promociones_referidos_detectadas`);
  * los enums del modelo y los de la migración 051 son el MISMO set (un estado
    agregado en un solo lado rompería el INSERT o la UI en silencio);
  * el CHECK anti-auto-referido está en el modelo y en la migración;
  * las FK, UNIQUE y defaults clave (incluido el código único por alumno);
  * la 054 es la única cabeza sobre la 053 (dos heads rompen el deploy) y su
    revision id cabe en VARCHAR(32);
  * los modelos están registrados en `app/models/__init__.py` (es lo que hace
    que `Base.metadata.create_all()` —el setup de TEST— cree las tablas).

    cd backend && py -3.12 -m pytest tests/test_referidos_modelo.py -q --noconftest
"""
import re
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.referidos import (
    CodigoReferido, ConfiguracionReferidos, CreditoReferido,
    EstadoInvitacion, EstadoPromocionDetectada, EstadoReferido, Invitacion,
    OrigenInvitacion, PeriodoPromocion, PromocionReferidos,
    PromocionReferidosDetectada, ReferidoAplicado, TipoPremio,
)

RAIZ = Path(__file__).resolve().parents[1]          # .../backend
VERSIONES = RAIZ / "alembic" / "versions"
MIGRACION = "051_referidos_invitaciones.py"
MIGRACION_CREDITO = "052_creditos_referido.py"
MIGRACION_PROMOCIONES = "053_promociones_referidos.py"
MIGRACION_INVITACIONES_ALUMNO = "054_invitaciones_alumno.py"

REVISION_PROMOCIONES = "053_promociones_referidos"
REVISION = "054_invitaciones_alumno"
REVISION_PADRE = "053_promociones_referidos"

MODELOS = {
    "invitaciones": Invitacion,
    "codigos_referido": CodigoReferido,
    "referidos_aplicados": ReferidoAplicado,
    "configuracion_referidos": ConfiguracionReferidos,
    "promociones_referidos": PromocionReferidos,
    "promociones_referidos_detectadas": PromocionReferidosDetectada,
    "creditos_referido": CreditoReferido,
}

ENUMS_MODELO = {
    "origen_invitacion": OrigenInvitacion,
    "estado_invitacion": EstadoInvitacion,
    "estado_referido": EstadoReferido,
    "periodo_promocion": PeriodoPromocion,
    "tipo_premio_referido": TipoPremio,
    "estado_promocion_detectada": EstadoPromocionDetectada,
}


def _fuente(relativa: str) -> str:
    # utf-8-sig: varios módulos del repo arrancan con BOM.
    return (RAIZ / relativa).read_text(encoding="utf-8-sig")


def _columnas(modelo) -> list:
    return [c.name for c in modelo.__table__.columns]


def _constraint(modelo, nombre, tipo=CheckConstraint):
    encontrados = [c for c in modelo.__table__.constraints
                   if isinstance(c, tipo) and c.name == nombre]
    assert len(encontrados) == 1, f"{modelo.__tablename__} / {nombre}"
    return encontrados[0]


def _ondelete(modelo, columna):
    fks = list(modelo.__table__.c[columna].foreign_keys)
    assert len(fks) == 1, f"{modelo.__tablename__}.{columna}"
    return fks[0].ondelete, fks[0].column.table.name


# ── 1. Las 6 tablas y sus columnas ──────────────────────────────────────────

def test_las_seis_tablas_existen_en_el_metadata():
    from app.db.database import Base
    for tabla in MODELOS:
        assert tabla in Base.metadata.tables, tabla


def test_columnas_de_invitaciones():
    assert _columnas(Invitacion) == [
        "id", "tenant_id", "origen", "enviado_por_usuario_id",
        "correo_prospecto", "estado", "fecha_envio", "fecha_registro",
        "usuario_registrado_id", "codigo_referido_id", "token_rastreo"]


def test_columnas_de_codigos_referido():
    assert _columnas(CodigoReferido) == [
        "id", "usuario_id", "codigo", "fecha_creacion", "activo"]


def test_columnas_de_referidos_aplicados():
    assert _columnas(ReferidoAplicado) == [
        "id", "codigo_referido_id", "usuario_invitador_id",
        "usuario_invitado_id", "fecha_ingreso_codigo", "estado",
        "fecha_conversion", "descuento_aplicado_invitado",
        "descuento_aplicado_invitador"]


def test_columnas_de_configuracion_referidos():
    assert _columnas(ConfiguracionReferidos) == [
        "id", "tenant_id", "porcentaje_descuento_invitado",
        "porcentaje_descuento_invitador", "activo"]


def test_columnas_de_promociones_referidos():
    assert _columnas(PromocionReferidos) == [
        "id", "tenant_id", "nombre", "umbral_referidos_convertidos",
        "periodo", "tipo_premio", "valor_premio", "activo"]


def test_columnas_de_promociones_referidos_detectadas():
    assert _columnas(PromocionReferidosDetectada) == [
        "id", "promocion_id", "usuario_id", "periodo_cumplido",
        "nombre_promocion", "umbral_referidos_convertidos", "tipo_premio",
        "valor_premio", "fecha_deteccion", "estado", "fecha_confirmacion",
        "confirmado_por_usuario_id"]


def test_columnas_del_credito_con_los_dos_origenes():
    assert _columnas(CreditoReferido) == [
        "id", "tenant_id", "usuario_id", "referido_aplicado_id",
        "promocion_detectada_id", "porcentaje", "estado", "fecha_otorgado",
        "fecha_usado", "descuento_aplicado_clp", "suscripcion_id"]


# ── 2. Enums: modelo ↔ migración ────────────────────────────────────────────

def _enums_de_la_migracion() -> dict:
    fuente = _fuente(f"alembic/versions/{MIGRACION}")
    bloque = re.search(r"ENUMS = \((.*?)\n\)", fuente, re.S).group(1)
    enums = {}
    for m in re.finditer(r"\(\s*['\"]([a-z_]+)['\"]\s*,\s*\(([^)]*)\)\s*\)",
                         bloque):
        enums[m.group(1)] = tuple(re.findall(r"['\"]([^'\"]+)['\"]",
                                             m.group(2)))
    return enums


def _valores_nuevos_de_la_054() -> dict:
    """Valores de enum que agrega la 054 (el modelo ya no es espejo de la 051)."""
    fuente = _fuente(f"alembic/versions/{MIGRACION_INVITACIONES_ALUMNO}")
    m = re.search(r"VALORES_NUEVOS_ORIGEN\s*=\s*\(([^)]*)\)", fuente)
    assert m, "VALORES_NUEVOS_ORIGEN"
    return {"origen_invitacion": tuple(re.findall(r"['\"]([^'\"]+)['\"]",
                                                   m.group(1)))}


def test_los_enums_del_modelo_y_la_migracion_son_el_mismo_set():
    migracion = _enums_de_la_migracion()
    assert set(migracion) == set(ENUMS_MODELO)
    # El modelo = lo que crea la 051 + lo que agrega la 054, en ese orden.
    nuevos = _valores_nuevos_de_la_054()
    for nombre, enum_modelo in ENUMS_MODELO.items():
        assert tuple(e.value for e in enum_modelo) == \
            migracion[nombre] + nuevos.get(nombre, ()), nombre


def test_las_columnas_enum_apuntan_al_tipo_nativo_correcto():
    assert Invitacion.__table__.c.origen.type.name == "origen_invitacion"
    assert Invitacion.__table__.c.estado.type.name == "estado_invitacion"
    assert ReferidoAplicado.__table__.c.estado.type.name == "estado_referido"
    assert PromocionReferidos.__table__.c.periodo.type.name == \
        "periodo_promocion"
    assert PromocionReferidos.__table__.c.tipo_premio.type.name == \
        "tipo_premio_referido"
    assert PromocionReferidosDetectada.__table__.c.estado.type.name == \
        "estado_promocion_detectada"


# ── 3. Constraints e integridad ─────────────────────────────────────────────

def test_check_anti_auto_referido_en_modelo_y_migracion():
    check = _constraint(ReferidoAplicado,
                        "ck_referidos_aplicados_no_auto_referido")
    assert "usuario_invitador_id" in str(check.sqltext)
    assert "usuario_invitado_id" in str(check.sqltext)
    assert "<>" in str(check.sqltext)

    migracion = re.sub(r"\s+", " ", _fuente(f"alembic/versions/{MIGRACION}"))
    assert "ck_referidos_aplicados_no_auto_referido" in migracion
    assert "usuario_invitador_id <> usuario_invitado_id" in migracion


def test_un_codigo_por_alumno_y_codigo_unico():
    usuario = _constraint(CodigoReferido, "uq_codigos_referido_usuario_id",
                          UniqueConstraint)
    codigo = _constraint(CodigoReferido, "uq_codigos_referido_codigo",
                         UniqueConstraint)
    assert _columnas_de(usuario) == ["usuario_id"]
    assert _columnas_de(codigo) == ["codigo"]


def test_una_configuracion_por_box():
    unico = _constraint(ConfiguracionReferidos,
                        "uq_configuracion_referidos_tenant_id",
                        UniqueConstraint)
    assert _columnas_de(unico) == ["tenant_id"]


def test_deteccion_idempotente_por_promocion_alumno_y_periodo():
    unico = _constraint(
        PromocionReferidosDetectada,
        "uq_promociones_referidos_detectadas_periodo", UniqueConstraint)
    assert _columnas_de(unico) == [
        "promocion_id", "usuario_id", "periodo_cumplido"]


def _columnas_de(constraint) -> list:
    return [col.name for col in constraint.columns]


def test_credito_tiene_exactamente_un_origen():
    """Un crédito nace de UN referido O de UNA detección, nunca de ambos."""
    assert _constraint(CreditoReferido,
                       "uq_creditos_referido_referido_aplicado_id",
                       UniqueConstraint)
    assert _constraint(CreditoReferido,
                       "uq_creditos_referido_promocion_detectada_id",
                       UniqueConstraint)
    check = _constraint(CreditoReferido, "ck_creditos_referido_un_origen")
    texto = str(check.sqltext)
    assert "referido_aplicado_id IS NOT NULL" in texto
    assert "promocion_detectada_id IS NOT NULL" in texto
    assert "= 1" in texto

    assert _ondelete(CreditoReferido, "promocion_detectada_id") == \
        ("CASCADE", "promociones_referidos_detectadas")
    assert CreditoReferido.__table__.c.referido_aplicado_id.nullable is True
    assert CreditoReferido.__table__.c.promocion_detectada_id.nullable is True


def test_fk_de_invitaciones():
    assert _ondelete(Invitacion, "tenant_id") == ("CASCADE", "tenants")
    assert _ondelete(Invitacion, "enviado_por_usuario_id") == \
        ("SET NULL", "usuarios")
    assert _ondelete(Invitacion, "usuario_registrado_id") == \
        ("SET NULL", "usuarios")
    # 054: la invitación de un alumno guarda SU código (sin borrar la traza si
    # el código se elimina) y el token del link es único.
    assert _ondelete(Invitacion, "codigo_referido_id") == \
        ("SET NULL", "codigos_referido")
    assert Invitacion.__table__.c.token_rastreo.nullable is True
    unico = _constraint(Invitacion, "uq_invitaciones_token_rastreo",
                        UniqueConstraint)
    assert _columnas_de(unico) == ["token_rastreo"]
    # La invitación nace `enviada` y el envío queda fechado por la BD.
    assert Invitacion.__table__.c.estado.nullable is False
    assert Invitacion.__table__.c.fecha_envio.nullable is False
    assert Invitacion.__table__.c.fecha_registro.nullable is True


def test_fk_de_codigos_y_referidos_aplicados():
    assert _ondelete(CodigoReferido, "usuario_id") == ("CASCADE", "usuarios")
    assert _ondelete(ReferidoAplicado, "codigo_referido_id") == \
        ("CASCADE", "codigos_referido")
    assert _ondelete(ReferidoAplicado, "usuario_invitador_id") == \
        ("CASCADE", "usuarios")
    assert _ondelete(ReferidoAplicado, "usuario_invitado_id") == \
        ("CASCADE", "usuarios")
    # Nace pendiente, sin fecha de conversión ni descuentos aplicados.
    assert ReferidoAplicado.__table__.c.estado.nullable is False
    assert ReferidoAplicado.__table__.c.fecha_conversion.nullable is True
    assert ReferidoAplicado.__table__.c.descuento_aplicado_invitado.nullable \
        is True
    assert ReferidoAplicado.__table__.c.descuento_aplicado_invitador.nullable \
        is True


def test_fk_de_configuracion_promociones_y_detectadas():
    assert _ondelete(ConfiguracionReferidos, "tenant_id") == \
        ("CASCADE", "tenants")
    assert _ondelete(PromocionReferidos, "tenant_id") == ("CASCADE", "tenants")
    assert _ondelete(PromocionReferidosDetectada, "promocion_id") == \
        ("CASCADE", "promociones_referidos")
    assert _ondelete(PromocionReferidosDetectada, "usuario_id") == \
        ("CASCADE", "usuarios")
    assert _ondelete(PromocionReferidosDetectada,
                     "confirmado_por_usuario_id") == ("SET NULL", "usuarios")


# ── 4. Migración y registro para create_all ─────────────────────────────────

def _datos_de_la_migracion(nombre: str = MIGRACION_PROMOCIONES) -> dict:
    fuente = _fuente(f"alembic/versions/{nombre}")
    datos = {}
    for clave in ("revision", "down_revision"):
        m = re.search(rf"^{clave}\s*(?::[^=]+)?=\s*['\"]([^'\"]+)['\"]",
                      fuente, re.M)
        assert m, clave
        datos[clave] = m.group(1)
    return datos


def test_la_053_sigue_siendo_la_unica_hija_de_la_052():
    datos = _datos_de_la_migracion()
    assert datos["revision"] == REVISION_PROMOCIONES
    assert datos["down_revision"] == "052_creditos_referido"

    # Cadena de las fases de Referidos, sin saltos ni ramas.
    assert _datos_de_la_migracion(MIGRACION_CREDITO)["down_revision"] == \
        "051_referidos_invitaciones"
    assert _datos_de_la_migracion(MIGRACION)["down_revision"] == \
        "050_auditoria_accion_varchar50"

    hijos = [archivo.stem for archivo in VERSIONES.glob("*.py")
             if _datos_de_archivo(archivo.name)["down_revision"] ==
             "052_creditos_referido"]
    assert hijos == [REVISION_PROMOCIONES], \
        f"cabezas sobre 052_creditos_referido: {hijos}"


def test_la_054_es_la_unica_cabeza_sobre_la_053():
    datos = _datos_de_la_migracion(MIGRACION_INVITACIONES_ALUMNO)
    assert datos["revision"] == REVISION
    assert datos["down_revision"] == REVISION_PADRE
    assert len(REVISION) <= 32, "alembic_version.version_num es VARCHAR(32)"

    hijos = [archivo.stem for archivo in VERSIONES.glob("*.py")
             if _datos_de_archivo(archivo.name)["down_revision"] ==
             REVISION_PADRE]
    assert hijos == [REVISION], f"cabezas sobre {REVISION_PADRE}: {hijos}"


def _datos_de_archivo(nombre: str) -> dict:
    fuente = _fuente(f"alembic/versions/{nombre}")
    datos = {}
    for clave in ("revision", "down_revision"):
        m = re.search(rf"^{clave}\s*(?::[^=]+)?=\s*['\"]([^'\"]+)['\"]",
                      fuente, re.M)
        datos[clave] = m.group(1) if m else None
    return datos


def test_los_modelos_estan_registrados_para_create_all():
    fuente = _fuente("app/models/__init__.py")
    assert "from app.models.referidos import (" in fuente
    for nombre in ("Invitacion", "CodigoReferido", "ReferidoAplicado",
                   "ConfiguracionReferidos", "PromocionReferidos",
                   "PromocionReferidosDetectada"):
        assert f'"{nombre}"' in fuente, nombre


def test_defaults_del_esquema():
    # El código nace activo y la fila de detección nace por confirmar.
    assert CodigoReferido.__table__.c.activo.nullable is False
    assert ConfiguracionReferidos.__table__.c.activo.nullable is False
    assert PromocionReferidos.__table__.c.activo.nullable is False
    assert PromocionReferidos.__table__.c.valor_premio.nullable is True
    detectada = PromocionReferidosDetectada.__table__.c
    assert detectada.estado.nullable is False
    assert detectada.fecha_confirmacion.nullable is True
    assert detectada.confirmado_por_usuario_id.nullable is True
    # El premio se congela al detectar: nombre, umbral y tipo son obligatorios;
    # el valor sólo aplica a días/porcentaje.
    assert detectada.nombre_promocion.nullable is False
    assert detectada.umbral_referidos_convertidos.nullable is False
    assert detectada.tipo_premio.nullable is False
    assert detectada.valor_premio.nullable is True
    # Los porcentajes del box son obligatorios (default 0 en la BD).
    assert ConfiguracionReferidos.__table__.c \
        .porcentaje_descuento_invitado.nullable is False
    assert ConfiguracionReferidos.__table__.c \
        .porcentaje_descuento_invitador.nullable is False
