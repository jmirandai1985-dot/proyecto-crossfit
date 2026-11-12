"""Importador del padrón de BoxMagic (`scripts/importar_candidatos_boxmagic.py`) — AISLADO.

Cubre, SIN BD y SIN red (Excel de prueba chiquito generado con openpyxl en `tmp_path` y
una sesión falsa — NUNCA se usa el Excel real de `backend/data/`, que tiene datos
personales, ni se toca ninguna base):

  * lectura del Excel con las columnas REALES del archivo de BoxMagic;
  * derivación de `grupo` desde `Estado` (Inactivo -> recuperacion, el resto -> activacion);
  * normalización del correo (sin espacios, minúsculas) y de los estados;
  * una fila sin correo (o sin nombre) se SALTEA y se reporta con su N° Socio;
  * un correo repetido dentro del Excel no se importa dos veces;
  * UPSERT por (tenant_id, correo): correrlo dos veces NO duplica y actualiza los cambios;
  * `--tenant-id` es obligatorio y `--dry-run` no escribe en la base.

    cd backend && py -3.12 -m pytest tests/test_importar_candidatos_boxmagic.py -q --noconftest
"""
import sys
from dataclasses import replace
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.candidato_boxmagic import (  # noqa: E402
    ESTADOS_BOXMAGIC, GRUPO_ACTIVACION, GRUPO_RECUPERACION, CandidatoBoxmagic,
    grupo_desde_estado,
)
from scripts import importar_candidatos_boxmagic as importador  # noqa: E402

TENANT = 3

# Las columnas REALES del Excel de BoxMagic (2026-11-05). El importador sólo usa
# Nombre / Email / Estado / N° Socio, pero el archivo trae estas 16.
COLUMNAS = [
    "N° Socio", "Nombre", "Inscripción", "Estado", "MATRÍCULA", "Acepta Contrato",
    "Email", "RUT/DNI", "Fecha Nacimiento", "Dirección", "Teléfono",
    "Teléfono Emergencia", "Sexo", "Observación", "Estatura", "Carrera",
]

FILAS = [
    # socio, nombre, estado, email
    (1001, "Ana Pérez", "Activo", "Ana.Perez@Example.COM"),
    (1002, "Bruno Díaz", "Inactivo", "bruno@example.com"),
    (1003, "Carla Sin Correo", "Inactivo", ""),              # -> se salta
    (1004, "", "Nuevo", "sin.nombre@example.com"),           # -> se salta
    (1005, "Duplicado", "Activo", "ana.perez@example.com"),   # -> duplicado del 1001
    (1006, "Estado Raro", "Suspendido", "raro@example.com"),  # -> se importa y se avisa
]


def _crear_excel(ruta, filas=FILAS):
    """Escribe un xlsx igual al de BoxMagic (mismas columnas), con las filas dadas."""
    from openpyxl import Workbook

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Clientes BoxMagic"
    hoja.append(COLUMNAS)
    for socio, nombre, estado, correo in filas:
        fila = {columna: "" for columna in COLUMNAS}
        fila["N° Socio"] = socio
        fila["Nombre"] = nombre
        fila["Estado"] = estado
        fila["Email"] = correo
        fila["MATRÍCULA"] = "MAT-%s" % socio
        hoja.append([fila[columna] for columna in COLUMNAS])
    libro.save(ruta)
    return ruta


class _Consulta:
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *criterios):
        """El fake entiende UN criterio: `CandidatoBoxmagic.tenant_id == N`.

        Es lo único que usa `aplicar`, y hace falta respetarlo: sin el filtro, el upsert
        de otro box "vería" las filas de este y no se podría probar el aislamiento entre
        tenants. El valor se lee del bind parameter del criterio (la sesión real lo
        resuelve Postgres).
        """
        for criterio in criterios:
            valor = getattr(getattr(criterio, "right", None), "value", None)
            if valor is not None:
                self._filas = [f for f in self._filas if f.tenant_id == valor]
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self._filas


class _SesionFalsa:
    """Session mínima: guarda las filas de `candidatos_boxmagic` en memoria y aplica la
    MISMA clave única (tenant_id, correo) que la base."""

    def __init__(self):
        self.filas = []
        self.commits = 0
        self._siguiente_id = 0

    def query(self, *modelos):
        assert modelos[0] is CandidatoBoxmagic, modelos
        return _Consulta(self.filas)

    def add(self, obj):
        self._siguiente_id += 1
        obj.id = self._siguiente_id
        self.filas.append(obj)

    def commit(self):
        self.commits += 1


@pytest.fixture()
def excel(tmp_path):
    return _crear_excel(tmp_path / "candidatos_test.xlsx")


# ── 1. Lectura del Excel ────────────────────────────────────────────────────
def test_lee_las_filas_usables_y_normaliza_el_correo(excel):
    resultado = importador.leer_excel(excel)

    assert resultado.total_filas == 6
    # 1003 (sin correo) y 1004 (sin nombre) se saltean; 1005 es duplicado del 1001.
    assert len(resultado.filas) == 3
    correos = [fila.correo for fila in resultado.filas]
    assert correos == ["ana.perez@example.com", "bruno@example.com", "raro@example.com"]
    # El correo se guarda normalizado: es la clave del cruce con `usuarios`.
    assert "Ana.Perez@Example.COM" not in correos


def test_el_estado_se_guarda_canonico_y_el_raro_se_reporta(excel):
    resultado = importador.leer_excel(excel)

    por_correo = {fila.correo: fila for fila in resultado.filas}
    assert por_correo["ana.perez@example.com"].estado_boxmagic == "Activo"
    assert por_correo["bruno@example.com"].estado_boxmagic == "Inactivo"
    # Un estado que BoxMagic no tiene se importa igual, con su nombre crudo...
    assert por_correo["raro@example.com"].estado_boxmagic == "Suspendido"
    # ...y queda a la vista para revisarlo a mano.
    assert [raro["estado"] for raro in resultado.estados_raros] == ["Suspendido"]
    assert resultado.estados_raros[0]["socio"] == "1006"


def test_filas_sin_correo_o_sin_nombre_se_reportan_con_su_socio(excel):
    resultado = importador.leer_excel(excel)

    saltadas = {fila["socio"]: fila["motivo"] for fila in resultado.saltadas}
    assert saltadas == {"1003": "sin correo", "1004": "sin nombre"}


def test_el_correo_repetido_en_el_excel_no_se_importa_dos_veces(excel):
    resultado = importador.leer_excel(excel)

    assert [duplicado["socio"] for duplicado in resultado.duplicados] == ["1005"]
    assert resultado.duplicados[0]["correo"] == "ana.perez@example.com"


def test_un_excel_sin_columnas_obligatorias_falla_claro(tmp_path):
    from openpyxl import Workbook

    libro = Workbook()
    libro.active.append(["Nombre", "Teléfono"])       # sin Email ni Estado
    libro.active.append(["Alguien", "123"])
    ruta = tmp_path / "malo.xlsx"
    libro.save(ruta)

    with pytest.raises(ValueError) as error:
        importador.leer_excel(ruta)

    assert "Email" in str(error.value)
    assert "Estado" in str(error.value)


# ── 2. Derivación de grupo (la regla del modelo) ────────────────────────────
@pytest.mark.parametrize("estado,esperado", [
    ("Activo", GRUPO_ACTIVACION),
    ("Congelado", GRUPO_ACTIVACION),
    ("Nuevo", GRUPO_ACTIVACION),
    ("Prueba", GRUPO_ACTIVACION),
    ("Inactivo", GRUPO_RECUPERACION),
    # Mayúsculas y espacios no cambian la regla.
    (" inactivo ", GRUPO_RECUPERACION),
    ("ACTIVO", GRUPO_ACTIVACION),
])
def test_grupo_desde_estado(estado, esperado):
    assert grupo_desde_estado(estado) == esperado


def test_los_cinco_estados_reales_estan_contemplados(excel):
    assert ESTADOS_BOXMAGIC == ("Activo", "Inactivo", "Congelado", "Nuevo", "Prueba")
    resultado = importador.leer_excel(excel)
    for fila in resultado.filas:
        assert fila.grupo in (GRUPO_ACTIVACION, GRUPO_RECUPERACION)


# ── 3. UPSERT (lo que lo hace seguro de correr varias veces) ────────────────
def test_la_primera_corrida_crea_todas_las_filas(excel):
    filas = importador.leer_excel(excel).filas
    sesion = _SesionFalsa()

    creados, actualizados, sin_cambios = importador.aplicar(sesion, TENANT, filas)

    assert (creados, actualizados, sin_cambios) == (3, 0, 0)
    assert len(sesion.filas) == 3
    assert sesion.commits == 1
    assert all(fila.tenant_id == TENANT for fila in sesion.filas)


def test_correrlo_dos_veces_no_duplica(excel):
    """El mismo Excel dos veces: la segunda corrida sólo actualiza (0 creados)."""
    filas = importador.leer_excel(excel).filas
    sesion = _SesionFalsa()

    importador.aplicar(sesion, TENANT, filas)
    creados, actualizados, sin_cambios = importador.aplicar(sesion, TENANT, filas)

    assert creados == 0
    assert actualizados == 3
    assert sin_cambios == 3          # nada cambió entre las dos corridas
    assert len(sesion.filas) == 3    # NO se duplicó nada
    correos = sorted(fila.correo for fila in sesion.filas)
    assert correos == ["ana.perez@example.com", "bruno@example.com", "raro@example.com"]


def test_el_upsert_actualiza_estado_y_grupo_si_el_excel_cambio(excel):
    """Un Excel nuevo (el alumno pasó de Activo a Inactivo) actualiza la MISMA fila."""
    filas = importador.leer_excel(excel).filas
    sesion = _SesionFalsa()
    importador.aplicar(sesion, TENANT, filas)

    ana = next(fila for fila in filas if fila.correo == "ana.perez@example.com")
    ana_inactiva = replace(
        ana, estado_boxmagic="Inactivo", grupo=GRUPO_RECUPERACION)

    creados, actualizados, sin_cambios = importador.aplicar(
        sesion, TENANT, [ana_inactiva])

    assert (creados, actualizados, sin_cambios) == (0, 1, 0)
    assert len(sesion.filas) == 3
    guardada = next(f for f in sesion.filas if f.correo == "ana.perez@example.com")
    assert guardada.estado_boxmagic == "Inactivo"
    assert guardada.grupo == GRUPO_RECUPERACION


def test_el_mismo_correo_en_dos_tenants_son_dos_filas(excel):
    """La clave única es (tenant_id, correo): otro box puede tener el mismo correo."""
    filas = importador.leer_excel(excel).filas
    sesion = _SesionFalsa()

    importador.aplicar(sesion, TENANT, filas)
    creados, _, _ = importador.aplicar(sesion, TENANT + 1, filas)

    assert creados == 3
    assert len(sesion.filas) == 6


# ── 4. CLI: --tenant-id obligatorio y --dry-run que no escribe ──────────────
def test_tenant_id_es_obligatorio(excel, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["importar_candidatos_boxmagic.py"])

    with pytest.raises(SystemExit):
        importador.main([])


def test_dry_run_no_toca_la_base(excel, monkeypatch):
    def _no_debe_llamarse():
        raise AssertionError("dry-run abrió una sesión de base de datos")

    monkeypatch.setattr(importador, "SessionLocal", _no_debe_llamarse)

    assert importador.main(["--tenant-id", str(TENANT), "--archivo", str(excel),
                            "--dry-run"]) == 0
