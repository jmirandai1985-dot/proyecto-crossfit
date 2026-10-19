"""
Código de REFERIDO del alumno (Fase 2) — tests AISLADOS, sin BD y sin red.

Qué se prueba
-------------
  * FORMATO: 1 inicial del nombre + 5 letras del apellido + 3 dígitos, en
    mayúsculas (`PATRON_CODIGO` es la única fuente de verdad).
  * NORMALIZACIÓN: tildes, ñ/diéresis, signos y espacios desaparecen; el
    apellido COMPUESTO usa sólo su primera palabra y el corto se rellena con X.
  * UNICIDAD: `generar_codigo_referido` regenera SÓLO los 3 dígitos cuando el
    código ya existe y cae al sufijo UUID si el prefijo agota sus 1.000
    combinaciones (se rinde ruidosamente si tampoco así hay lugar).
  * ALCANCE: `asignar_codigo_referido` devuelve `None` para admin/coach sin
    tocar la BD, es idempotente por `usuario_id`, agrega la fila con
    `activo=True` y hace `flush()` — NUNCA `commit()` (el commit es del alta).
  * WIRING: las DOS altas (admin y auto-registro) asignan el código ANTES de
    su `db.commit()`, sólo para `alumno`, y revierten todo si la generación falla.

    cd backend && py -3.12 -m pytest tests/test_referidos_service.py -q
"""
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from app.models.usuario import RolUsuario
from app.services import referidos_service as rs

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit


class _SesionFalsa:
    """Sesión mínima, sin BD: sólo lo que usa el servicio.

    * `filas`: lo que devuelve `first()` cuando ya no hay colisiones (para
      simular un código que YA existe, por ejemplo en la prueba de idempotencia);
    * `colisiones`: cuántos `first()` seguidos devuelven una fila antes de
      devolver `None` (simula códigos ya ocupados);
    * `agregados` / `eventos`: qué se agregó y en qué orden (`add`, `flush`).
      No tiene `commit()` a propósito: si el servicio commitea, el test falla.
    """

    def __init__(self, filas=None, colisiones=0):
        self.filas = filas
        self.restantes = colisiones
        self.consultas = 0
        self.agregados = []
        self.eventos = []

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        self.consultas += 1
        if self.restantes > 0:
            self.restantes -= 1
            return (1,)
        return self.filas

    def add(self, fila):
        self.eventos.append("add")
        self.agregados.append(fila)

    def flush(self):
        self.eventos.append("flush")


class _SesionProhibida:
    """Para admin/coach: si el servicio consulta la BD, el test explota."""

    def query(self, *args, **kwargs):
        raise AssertionError(
            "admin/coach no deben generar ni consultar códigos de referido")


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _bloque(fuente: str, inicio: str) -> str:
    """Desde `inicio` hasta el próximo `@router.` (una función de endpoint)."""
    i = fuente.index(inicio)
    fin = fuente.find("\n@router.", i + len(inicio))
    return fuente[i:fin if fin != -1 else len(fuente)]


# ── Formato y normalización ──────────────────────────────────────────────────

def test_el_formato_es_inicial_mas_cinco_letras_mas_tres_digitos():
    for _ in range(200):
        codigo = rs.generar_codigo_referido("Juan", "Pérez", _SesionFalsa())
        assert rs.PATRON_CODIGO.match(codigo), codigo
        assert codigo.startswith("JPEREZ")
        assert len(codigo) == 1 + rs.LARGO_APELLIDO + rs.DIGITOS_ALEATORIOS


def test_apellido_corto_se_rellena_con_x():
    assert rs.construir_prefijo("Ana", "Ruiz") == "ARUIZX"
    assert rs.construir_prefijo("Ana", "") == "AXXXXX"
    assert rs.construir_prefijo("", "") == "XXXXXX"


def test_tildes_enie_y_dieresis_se_normalizan():
    assert rs.construir_prefijo("José", "Ñúñez") == "JNUNEZ"
    assert rs.construir_prefijo("Müller", "Güemes") == "MGUEME"
    assert rs.normalizar_letras("  María-José  ") == "MARIAJOSE"


def test_apellido_compuesto_usa_solo_la_primera_palabra():
    assert rs.construir_prefijo("María", "De La Torre") == "MDEXXX"
    assert rs.construir_prefijo("Juan", "Pérez Soto") == "JPEREZ"


def test_dividir_nombre_completo():
    assert rs.dividir_nombre_completo("Ana María Ñuñez de la Fuente") == (
        "Ana", "María Ñuñez de la Fuente")
    assert rs.dividir_nombre_completo("  Ana   ") == ("Ana", "")
    assert rs.dividir_nombre_completo("") == ("", "")
    assert rs.dividir_nombre_completo(None) == ("", "")


def test_sin_letras_utilizables_el_prefijo_sigue_siendo_valido():
    # Basura/símbolos no rompen el formato: el prefijo se rellena con X.
    assert rs.construir_prefijo("123", "@@@") == "XXXXXX"


# ── Unicidad y reintentos ────────────────────────────────────────────────────

def test_colision_regenera_solo_los_digitos(monkeypatch):
    vistos = []

    def _en_uso(db, codigo):
        vistos.append(codigo)
        return len(vistos) <= 2          # los dos primeros ya existen

    digitos = iter(["111", "222", "333"])
    monkeypatch.setattr(rs, "_codigo_en_uso", _en_uso)
    monkeypatch.setattr(rs, "_digitos_aleatorios", lambda: next(digitos))

    codigo = rs.generar_codigo_referido("Juan", "Pérez", _SesionFalsa())

    assert codigo == "JPEREZ333"
    assert vistos == ["JPEREZ111", "JPEREZ222", "JPEREZ333"], \
        "el prefijo NO cambia: sólo se regeneran los 3 dígitos"


def test_agotar_los_digitos_cae_al_sufijo_uuid(monkeypatch):
    consultas = []
    largo_normal = 1 + rs.LARGO_APELLIDO + rs.DIGITOS_ALEATORIOS

    def _en_uso(db, codigo):
        consultas.append(codigo)
        return len(codigo) == largo_normal    # todos los "normales" ocupados

    monkeypatch.setattr(rs, "_codigo_en_uso", _en_uso)
    monkeypatch.setattr(rs, "_digitos_aleatorios", lambda: "000")
    monkeypatch.setattr(rs.uuid, "uuid4",
                        lambda: uuid.UUID("1234567890abcdef1234567890abcdef"))

    codigo = rs.generar_codigo_referido("Juan", "Pérez", _SesionFalsa())

    assert codigo == "JPEREZ12345678"
    assert consultas[-1] == codigo
    assert sum(1 for c in consultas if len(c) == largo_normal) == rs.INTENTOS_DIGITOS


def test_si_tampoco_hay_codigo_libre_se_rinde_ruidosamente(monkeypatch):
    consultas = []
    monkeypatch.setattr(rs, "_codigo_en_uso",
                        lambda db, codigo: consultas.append(codigo) or True)
    monkeypatch.setattr(rs, "_digitos_aleatorios", lambda: "000")

    with pytest.raises(RuntimeError) as error:
        rs.generar_codigo_referido("Juan", "Pérez", _SesionFalsa())

    assert "JPEREZ" in str(error.value)
    assert len(consultas) == rs.INTENTOS_DIGITOS + rs.INTENTOS_FALLBACK


# ── Asignación: sólo alumnos, idempotente y sin commit ───────────────────────

def test_admin_y_coach_no_reciben_codigo():
    for rol in (RolUsuario.administrador, RolUsuario.coach,
                "administrador", "coach"):
        usuario = SimpleNamespace(id=1, nombre="Admin Uno", rol=rol)
        assert rs.asignar_codigo_referido(_SesionProhibida(), usuario) is None


def test_alumno_recibe_codigo_y_solo_se_hace_flush(monkeypatch):
    monkeypatch.setattr(rs, "_digitos_aleatorios", lambda: "007")
    db = _SesionFalsa()
    usuario = SimpleNamespace(id=42, nombre="Juan Pérez Soto",
                              rol=RolUsuario.alumno)

    fila = rs.asignar_codigo_referido(db, usuario)

    assert fila.usuario_id == 42
    assert fila.codigo == "JPEREZ007"
    assert fila.activo is True
    assert db.agregados == [fila]
    assert db.eventos == ["add", "flush"], "flush sí, commit no (lo hace el alta)"


def test_tambien_acepta_el_rol_como_texto_plano(monkeypatch):
    monkeypatch.setattr(rs, "_digitos_aleatorios", lambda: "001")
    fila = rs.asignar_codigo_referido(
        _SesionFalsa(),
        SimpleNamespace(id=7, nombre="Ana Ruiz", rol="alumno"))
    assert fila.codigo == "ARUIZX001"


def test_si_el_alumno_ya_tiene_codigo_no_genera_otro(monkeypatch):
    existente = SimpleNamespace(codigo="JPEREZ007")
    db = _SesionFalsa(filas=existente)

    def _no_generar(*args, **kwargs):
        raise AssertionError("no debe generar otro código para el mismo alumno")

    monkeypatch.setattr(rs, "generar_codigo_referido", _no_generar)

    fila = rs.asignar_codigo_referido(
        db, SimpleNamespace(id=42, nombre="Juan Pérez", rol=RolUsuario.alumno))

    assert fila is existente
    assert db.agregados == [] and db.eventos == []


def test_el_alumno_debe_estar_flusheado_para_tener_id():
    with pytest.raises(ValueError):
        rs.asignar_codigo_referido(
            _SesionFalsa(),
            SimpleNamespace(id=None, nombre="Ana Ruiz", rol=RolUsuario.alumno))


# ── Wiring: las dos altas asignan antes del commit y revierten si falla ───────

def test_el_servicio_no_commitea_nunca():
    fuente = _fuente("backend/app/services/referidos_service.py")
    assert "db.commit(" not in fuente, "el commit es del alta, no del servicio"
    assert "db.flush()" in fuente


def test_el_alta_del_admin_asigna_antes_del_commit_y_solo_al_alumno():
    bloque = _bloque(_fuente("backend/app/api/v1/usuarios.py"),
                     "def crear_usuario(")
    assert "if usuario_data.rol == RolUsuario.alumno:" in bloque
    assert "asignar_codigo_referido(db, db_usuario)" in bloque
    assert bloque.index("asignar_codigo_referido(db") < bloque.index("db.commit()")
    assert "db.rollback()" in bloque
    assert "HTTP_500_INTERNAL_SERVER_ERROR" in bloque


def test_el_auto_registro_asigna_antes_del_commit_y_solo_al_alumno():
    bloque = _bloque(_fuente("backend/app/api/v1/alumnos.py"),
                     "def registrar_alumno_nuevo(")
    assert "if usuario.rol == RolUsuario.alumno:" in bloque
    assert "asignar_codigo_referido(db, usuario)" in bloque
    assert bloque.index("asignar_codigo_referido(db") < bloque.index("db.commit()")
    assert "db.rollback()" in bloque
    assert "HTTP_500_INTERNAL_SERVER_ERROR" in bloque
