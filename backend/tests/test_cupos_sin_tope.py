"""Cupos sin tope (Musculación / Open Box): la regla en UN solo lugar.

Qué fija este archivo (sin red y sin base de datos, salvo el último test que es
read-only sobre TEST):

1. **Modelo y migración 066**: `clases.cupo_maximo` y `horarios.cupo_maximo`
   aceptan NULL; el backfill pone en NULL el cupo de las disciplinas con
   `es_open_box = true` (y limpia `cupo_original`, el techo de "ampliar cupo").
2. **Reservas**: `POST /reservas` y la presencia sin cargo de Asistencia tratan
   `cupo_maximo IS NULL` como SIN TOPE (`or_(...is_(None), ...)`); sin eso,
   comparar contra NULL rechazaría todas las reservas de una sala libre.
3. **Panel**: "solo con cupo" incluye las clases sin tope; ampliar cupo responde
   400; `PATCH /supervision/cupo-disciplina` rechaza las disciplinas libres y
   `GET /supervision/cupos-disciplinas` las marca `sin_tope`.
4. **KPIs**: el denominador de ocupación suma sólo las clases CON cupo y las
   disciplinas sin tope informan el CONTEO de reservas (`ocupacion_pct = None`).
5. **Front**: el util compartido (`historialAsistencia.js`) separa los dos
   universos y las pantallas pintan "sin cupo" / conteo en vez de un %.
6. **Seed**: `run_setup_test_db.py` crea Open Box y Musculación con
   `es_open_box=True` y sus horarios sin cupo (si no, el re-seed de TEST
   volvería a inventar el placeholder).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_cupos_sin_tope.py -q --noconftest
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

FRONT = REPO / "frontend" / "src"
MIGRACION = BACKEND / "alembic" / "versions" / "066_cupos_sin_tope_open_box.py"


def fuente(*partes):
    return (BACKEND.joinpath(*partes)).read_text(encoding="utf-8")


def fuente_front(*partes):
    return FRONT.joinpath(*partes).read_text(encoding="utf-8")


# ── 1. Modelo + migración ────────────────────────────────────────────────────
def test_el_modelo_permite_cupo_null_en_clases_y_horarios():
    from app.models.clase import Clase
    from app.models.horario_base import HorarioBase

    assert Clase.__table__.c.cupo_maximo.nullable is True, (
        "clases.cupo_maximo tiene que aceptar NULL (= sin tope)")
    assert Clase.__table__.c.cupo_original.nullable is True
    assert HorarioBase.__table__.c.cupo_maximo.nullable is True, (
        "horarios.cupo_maximo tiene que aceptar NULL: generar_clases copia ese valor")


def test_la_migracion_066_declara_la_cadena_y_el_backfill():
    texto = MIGRACION.read_text(encoding="utf-8")
    assert 'revision = "066_cupos_sin_tope_open_box"' in texto
    assert 'down_revision = "065_retencion_datos"' in texto
    # Las dos columnas pasan a nullable.
    assert texto.count("nullable=True") >= 2
    assert 'op.alter_column("clases", "cupo_maximo"' in texto
    assert 'op.alter_column("horarios", "cupo_maximo"' in texto
    # El backfill usa el criterio de NEGOCIO (`es_open_box`), no una lista de nombres.
    assert texto.count("d.es_open_box = true") >= 2
    assert "cupo_original = NULL" in texto
    # Contrato en la base: NULL o positivo.
    assert "cupo_maximo IS NULL OR cupo_maximo > 0" in texto
    assert "ck_clases_cupo_maximo_positivo" in texto
    assert "ck_horarios_cupo_maximo_positivo" in texto


def test_la_migracion_066_es_la_cabeza_de_la_cadena():
    versiones = {p.stem for p in (BACKEND / "alembic" / "versions").glob("*.py")}
    assert "066_cupos_sin_tope_open_box" in versiones
    assert not {v for v in versiones if v[:3] in ("067", "068")}


# ── 2. Reservas: NULL = sin tope ─────────────────────────────────────────────
def test_post_reservas_trata_null_como_sin_tope():
    texto = fuente("app", "api", "v1", "reservas.py")
    assert "Clase.cupo_maximo.is_(None)" in texto, (
        "el UPDATE de aforo tiene que dejar pasar la reserva cuando el cupo es NULL")
    assert "asistentes_confirmados < Clase.cupo_maximo" in texto, (
        "con cupo real el tope se sigue respetando igual que antes")


def test_la_presencia_sin_cargo_tambien_acepta_sin_tope():
    texto = fuente("app", "api", "v1", "asistencia.py")
    assert "Clase.cupo_maximo.is_(None)" in texto


def test_el_filtro_solo_con_cupo_incluye_las_salas_libres():
    texto = fuente("app", "api", "v1", "clases.py")
    assert "(c.cupo_maximo IS NULL" in texto
    assert "OR c.asistentes_confirmados < c.cupo_maximo)" in texto


def test_ampliar_cupo_sin_cupo_es_un_400_no_un_500():
    texto = fuente("app", "api", "v1", "clases.py")
    # El guard va ANTES de `original + 10` (un None + int era un 500).
    pos_guard = texto.index("if clase.cupo_maximo is None:")
    pos_suma = texto.index("tope = original + 10")
    assert pos_guard < pos_suma
    assert "no hay cupo que" in texto



# ── 3. Panel: horarios y supervisión ─────────────────────────────────────────
def test_crear_horario_fuerza_null_en_disciplinas_de_acceso_libre():
    texto = fuente("app", "api", "v1", "horarios.py")
    assert "None if disc.es_open_box else cupo_maximo" in texto
    assert "if nueva.es_open_box:" in texto, (
        "cambiar la plantilla a una disciplina libre tiene que limpiar el cupo")


def test_supervision_no_deja_fijar_cupo_a_una_sala_libre():
    texto = fuente("app", "api", "v1", "supervision.py")
    assert "SELECT id, es_open_box FROM disciplinas" in texto
    assert "if disc.es_open_box:" in texto
    assert '"sin_tope": bool(r.es_open_box)' in texto
    # El listado no inventa un 16 para una disciplina sin cupo.
    assert "CASE WHEN d.es_open_box THEN NULL" in texto


# ── 4. KPIs: sólo las clases con tope tienen denominador ─────────────────────
def test_el_kpi_por_disciplina_separa_los_dos_universos():
    texto = fuente("app", "api", "v1", "reportes.py")
    assert "FILTER (WHERE c.cupo_maximo IS NOT NULL)" in texto
    assert '"sin_tope": sin_tope' in texto
    assert '"reservas": r.reservas' in texto
    assert '"ocupacion_pct": pct' in texto
    # Sin `COALESCE(cupo_maximo, 1)`: ese 1 por clase era el invento.
    assert "SUM(COALESCE(c.cupo_maximo, 1))" not in texto


def test_la_ocupacion_promedio_no_mezcla_reservas_sin_cupo():
    texto = fuente("app", "services", "metricas_service.py")
    assert texto.count("FILTER (WHERE c.cupo_maximo IS NOT NULL)") >= 2
    assert "def reservas_sin_tope(" in texto
    assert "c.cupo_maximo IS NULL" in texto
    # El endpoint de Reportes expone el conteo aparte.
    assert '"reservasSinCupo": reservas_sin_cupo' in fuente(
        "app", "api", "v1", "reportes.py")


def test_el_excel_de_reportes_informa_reservas_en_vez_de_porcentaje():
    texto = fuente("app", "services", "reportes_service.py")
    assert "FILTER (WHERE c.cupo_maximo IS NOT NULL)" in texto
    assert "reservas (sin cupo)" in texto
    assert "clases_sin_tope" in texto


# ── 5. Front: el util compartido y las pantallas ─────────────────────────────
def test_el_util_del_historial_separa_cupos_de_reservas_sin_tope():
    texto = fuente_front("utils", "historialAsistencia.js")
    assert "export const sinTopeDe" in texto
    assert "reservasSinTope" in texto
    assert "clasesSinTope" in texto
    assert "conTope.length === 0 ? null : porcentaje(presentesConTope, cupos)" in texto
    # La ficha de una clase sin tope no pinta `0%`.
    assert "pct: sinTope ? null : porcentaje(" in texto


def test_las_pantallas_muestran_sin_cupo_y_no_un_cero_por_ciento():
    historial = fuente_front("components", "HistorialAsistencia.jsx")
    assert "const textoPct = (totales) =>" in historial
    assert "'sin cupo'" in historial
    assert "reservas (sin cupo)" in historial

    reportes = fuente_front("pages", "admin", "Reportes.jsx")
    assert "reservas (sin cupo)" in reportes
    assert "reservasSinCupo" in reportes

    franjas = fuente_front("utils", "franjasAsistencia.js")
    assert "sinTope" in franjas and "reservasSinTope" in franjas

    cupos = fuente_front("utils", "cuposClase.js")
    assert "export const sinTopeClase" in cupos

    for archivo in (("pages", "alumno", "Dashboard.jsx"),
                    ("pages", "alumno", "InicioMobile.jsx"),
                    ("pages", "coach", "DashboardCoach.jsx")):
        texto = fuente_front(*archivo)
        assert "cupo_maximo === null" in texto, f"{archivo[-1]} no distingue sin tope"



# ── 6. Seed de TEST ──────────────────────────────────────────────────────────
def test_el_seed_marca_open_box_y_no_le_pone_cupo():
    texto = fuente("run_setup_test_db.py")
    assert "open_box = {2, 3}" in texto
    assert "es_open_box=(d_id in open_box)" in texto
    # Los horarios de esas dos disciplinas se siembran sin cupo.
    assert "(2, 2, time(10, 0), time(11, 0), None, dia_horario)" in texto
    assert "(3, 3, time(10, 0), time(11, 0), None, dia_horario)" in texto


# ── 7. Invariante de datos en TEST (read-only) ───────────────────────────────
def test_en_test_ninguna_sala_libre_tiene_cupo_numerico():
    if os.getenv("ENVIRONMENT") != "test":
        pytest.skip("invariante de datos: exige ENVIRONMENT=test")

    from sqlalchemy import create_engine, text

    from app.core.config import is_test_db_url, settings

    url = settings.DIRECT_URL or settings.DATABASE_URL
    if not is_test_db_url(url):
        pytest.fail("la URL configurada NO es TEST")

    engine = create_engine(url)
    with engine.connect() as c:
        sobrantes = c.execute(text("""
            select d.nombre, count(*) from clases c
              join disciplinas d on d.id = c.disciplina_id
             where d.es_open_box and c.cupo_maximo is not null
             group by 1
        """)).fetchall()
        horarios = c.execute(text("""
            select d.nombre, count(*) from horarios h
              join disciplinas d on d.id = h.disciplina_id
             where d.es_open_box and h.cupo_maximo is not null
             group by 1
        """)).fetchall()
    assert not sobrantes, f"clases de acceso libre con cupo: {sobrantes}"
    assert not horarios, f"horarios de acceso libre con cupo: {horarios}"
