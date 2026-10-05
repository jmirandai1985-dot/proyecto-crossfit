"""
Marcas de la grilla de Supervisión (app/services/asignaciones_clases.py).

Qué se prueba, SIN red y SIN base de datos (B1; B2/B3/B6 agregan los tests de las
operaciones contra la BD):

  * prioridad de `marca_cobertura`: ⚠️ emergencia > 🔴 sin coach > 🟦 admin > ✅ coach;
  * `coach_id` vacío gana sobre un `origen` seteado (dato sucio: no puede haber
    "asignada por el admin" sin coach);
  * `porcentaje_cobertura` (0.0 sin clases, redondeo a 1 decimal);
  * B2: `marcar_clase` / `liberar_clase` / `abrir_vigencia` / `cerrar_vigencia`
    (esta última sin violar el CHECK `vigente_hasta >= vigente_desde`);
  * B2: la forma del SQL de `backfill_horario` (no pisa a otro coach), de
    `liberar_clases_futuras_de_horario` y de `conflicto_futuro_en_horario`,
    capturada con una sesión FALSA (sin BD);
  * B2: el encadenado de las migraciones 042/043 y el índice único PARCIAL.

    cd backend && py -3.12 -m pytest tests/test_asignaciones_clases.py --noconftest -q
"""
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.models.clase import Clase
from app.services import asignaciones_clases as asig
from app.services.asignaciones_clases import (
    MARCAS_VALIDAS,
    MARCA_ADMIN,
    MARCA_COACH,
    MARCA_EMERGENCIA,
    MARCA_SIN_COACH,
    ORIGEN_ADMIN,
    ORIGEN_COACH,
    marca_cobertura,
    porcentaje_cobertura,
)

HOY = date(2026, 4, 10)          # viernes
DESDE = HOY


class _SesionFalsa:
    """Sesión mínima: registra `add` y devuelve stubs de `execute` (sin BD)."""

    def __init__(self, rowcount=3, primera_fila=None):
        self.agregadas = []
        self.ejecutados = []          # [(sql, params)]
        self.rowcount = rowcount
        self.primera_fila = primera_fila

    def add(self, obj):
        self.agregadas.append(obj)

    def execute(self, sql, params=None):
        self.ejecutados.append((str(sql), params))
        padre = self

        class _Res:
            rowcount = padre.rowcount

            def first(self):
                return padre.primera_fila

        return _Res()


# ── marca_cobertura ────────────────────────────────────────────────────────

def test_sin_coach():
    assert marca_cobertura(None) == MARCA_SIN_COACH
    assert marca_cobertura(0) == MARCA_SIN_COACH
    assert marca_cobertura(None, ORIGEN_COACH) == MARCA_SIN_COACH


def test_tomada_por_el_coach():
    assert marca_cobertura(7) == MARCA_COACH
    assert marca_cobertura(7, ORIGEN_COACH) == MARCA_COACH


def test_asignada_por_el_admin():
    assert marca_cobertura(7, ORIGEN_ADMIN) == MARCA_ADMIN


def test_la_emergencia_gana_siempre():
    assert marca_cobertura(7, ORIGEN_COACH, True) == MARCA_EMERGENCIA
    assert marca_cobertura(7, ORIGEN_ADMIN, True) == MARCA_EMERGENCIA
    assert marca_cobertura(None, None, True) == MARCA_EMERGENCIA


def test_origen_desconocido_cae_a_coach():
    """Un origen raro (dato viejo) no puede marcar 🟦: la marca por defecto es ✅."""
    assert marca_cobertura(7, "otro") == MARCA_COACH


def test_las_marcas_son_las_del_frontend():
    assert sorted(MARCAS_VALIDAS) == ["admin", "coach", "emergencia", "sin_coach"]


# ── porcentaje_cobertura ───────────────────────────────────────────────────

def test_porcentaje_cobertura():
    assert porcentaje_cobertura(0, 0) == 0.0
    assert porcentaje_cobertura(20, 20) == 100.0
    assert porcentaje_cobertura(20, 24) == 83.3
    assert porcentaje_cobertura(1, 3) == 33.3
    assert porcentaje_cobertura(5, 0) == 0.0


# ── B2: marcar / liberar una clase ─────────────────────────────────────────

def test_marcar_clase_guarda_origen_y_quien():
    clase = Clase()
    asig.marcar_clase(clase, coach_id=7, origen=ORIGEN_COACH, quien_id=7)
    assert (clase.coach_id, clase.asignacion_origen) == (7, "coach")
    assert clase.asignada_por == 7
    assert clase.asignada_en is not None


def test_marcar_clase_por_admin_deja_a_quien_la_asigno():
    clase = Clase()
    asig.marcar_clase(clase, coach_id=7, origen=ORIGEN_ADMIN, quien_id=1)
    assert clase.coach_id == 7
    assert clase.asignacion_origen == "admin"
    assert clase.asignada_por == 1


def test_liberar_clase_limpia_todo():
    clase = Clase()
    asig.marcar_clase(clase, 7, ORIGEN_COACH)
    asig.liberar_clase(clase)
    assert clase.coach_id is None
    assert clase.asignacion_origen is None
    assert clase.asignada_por is None
    assert clase.asignada_en is None


# ── B2: vigencia del horario recurrente ────────────────────────────────────

def test_abrir_vigencia_sin_creado_por_usa_al_coach():
    db = _SesionFalsa()
    vigencia = asig.abrir_vigencia(db, tenant_id=1, horario_id=5, coach_id=7,
                                   desde=DESDE)
    assert db.agregadas == [vigencia]
    assert vigencia.vigente_desde == DESDE
    assert vigencia.vigente_hasta is None
    assert vigencia.creado_por == 7


def test_cerrar_vigencia_termina_ayer():
    vigencia = SimpleNamespace(vigente_desde=DESDE - timedelta(days=10),
                               vigente_hasta=None)
    asig.cerrar_vigencia(vigencia, DESDE)
    assert vigencia.vigente_hasta == DESDE - timedelta(days=1)


def test_cerrar_vigencia_no_viola_el_check():
    """Si la vigencia empezó hoy (o después), no puede cerrar antes de empezar."""
    vigencia = SimpleNamespace(vigente_desde=DESDE, vigente_hasta=None)
    asig.cerrar_vigencia(vigencia, DESDE)
    assert vigencia.vigente_hasta == DESDE
    assert vigencia.vigente_hasta >= vigencia.vigente_desde

    futura = SimpleNamespace(vigente_desde=DESDE + timedelta(days=3),
                             vigente_hasta=None)
    asig.cerrar_vigencia(futura, DESDE)
    assert futura.vigente_hasta == futura.vigente_desde


# ── B2: forma del SQL (sin BD) ─────────────────────────────────────────────

def test_backfill_no_pisa_a_otro_coach():
    db = _SesionFalsa(rowcount=4)
    tocadas = asig.backfill_horario(db, 1, 5, 7, quien_id=7, desde=DESDE)
    sql, params = db.ejecutados[-1]
    assert tocadas == 4
    # Sólo clases sin coach o que ya eran suyas:
    assert "(coach_id IS NULL OR coach_id = :cid)" in sql
    assert "asignacion_origen = :origen" in sql
    assert "fecha >= COALESCE(:desde, fecha)" in sql
    assert params["cid"] == 7 and params["origen"] == ORIGEN_COACH
    assert params["desde"] == DESDE


def test_liberar_clases_futuras_sin_coach_no_filtra_por_coach():
    db = _SesionFalsa(rowcount=2)
    asig.liberar_clases_futuras_de_horario(db, 1, 5, DESDE)
    sql, params = db.ejecutados[-1]
    assert "coach_id = :cid" not in sql
    assert "cid" not in params
    assert "coach_id IS NOT NULL" in sql


def test_liberar_clases_futuras_de_un_coach_lo_filtra():
    db = _SesionFalsa(rowcount=1)
    asig.liberar_clases_futuras_de_horario(db, 1, 5, DESDE, coach_id=9)
    sql, params = db.ejecutados[-1]
    assert "coach_id = :cid" in sql
    assert params["cid"] == 9


def test_conflicto_futuro_devuelve_el_nombre():
    fila = SimpleNamespace(clase_id=88, fecha="2026-04-14", coach_id=3,
                           coach_nombre="Ana")
    db = _SesionFalsa(primera_fila=fila)
    choque = asig.conflicto_futuro_en_horario(db, 1, 5, DESDE, coach_id=7)
    sql, params = db.ejecutados[-1]
    assert choque["clase_id"] == 88
    assert choque["coach_nombre"] == "Ana"
    assert "AND c.coach_id <> :cid" in sql
    assert params["cid"] == 7


def test_conflicto_futuro_sin_choque():
    db = _SesionFalsa(primera_fila=None)
    assert asig.conflicto_futuro_en_horario(db, 1, 5, DESDE, coach_id=7) is None


# ── B2: migraciones (encadenado + índice parcial) ──────────────────────────

def _fuente_migracion(nombre: str) -> str:
    raiz = Path(__file__).resolve().parents[1]      # .../backend
    return (raiz / "alembic" / "versions" / nombre).read_text(encoding="utf-8")


def test_cadena_de_migraciones_042_043():
    m042 = _fuente_migracion("042_clases_asignacion_coach.py")
    m043 = _fuente_migracion("043_horarios_coach_vigencia.py")
    assert 'revision: str = "042_clases_asignacion_coach"' in m042
    assert 'down_revision: Union[str, None] = "041_imagen_url_productos"' in m042
    assert 'revision: str = "043_horarios_coach_vigencia"' in m043
    assert 'down_revision: Union[str, None] = "042_clases_asignacion_coach"' in m043


def test_migracion_042_agrega_las_tres_columnas():
    m042 = _fuente_migracion("042_clases_asignacion_coach.py")
    for columna in ("asignacion_origen", "asignada_por", "asignada_en"):
        assert f'"{columna}"' in m042
    assert "ck_clases_asignacion_origen" in m042


def test_migracion_043_un_solo_vigente_por_horario():
    m043 = _fuente_migracion("043_horarios_coach_vigencia.py")
    assert 'unique=True, postgresql_where=sa.text("vigente_hasta IS NULL")' in m043
    assert "ck_horarios_coach_vigencia" in m043


# ── B3: avisos al coach (campana, sin correo) ──────────────────────────────

def test_los_tipos_de_aviso_entran_en_la_columna():
    """`notificaciones.tipo` es VARCHAR(20): los tipos de B3 tienen que caber."""
    for tipo in (asig.TIPO_CLASE_ASIGNADA, asig.TIPO_CLASE_REASIGNADA,
                 asig.TIPO_CLASE_LIBERADA):
        assert len(tipo) <= 20, tipo


def test_descripcion_de_clase_para_los_avisos():
    assert asig.descripcion_clase("CrossFit", "2026-04-14", "19:00:00") == \
        "clase de CrossFit del 2026-04-14 19:00"
    # Sin disciplina (dato sucio) sigue siendo legible.
    assert asig.descripcion_clase(None, "2026-04-14", "19:00:00") == \
        "clase del 2026-04-14 19:00"


def test_mensaje_asignada_normal_y_emergencia():
    normal = asig.mensaje_clase_asignada("clase de CrossFit del 2026-04-14 19:00",
                                         "Ana Admin")
    assert normal.startswith("🟦 Ana Admin te asignó la clase de CrossFit")
    emergencia = asig.mensaje_clase_asignada("clase de CrossFit del 2026-04-14 19:00",
                                             "Ana Admin", emergencia=True)
    assert "Cobertura de emergencia" in emergencia
    assert "Ana Admin" in emergencia


def test_mensaje_reasignada_nombra_al_coach_nuevo():
    texto = asig.mensaje_clase_reasignada("clase de CrossFit del 2026-04-14 19:00",
                                          "Ana Admin", "Pedro")
    assert "🔁" in texto
    assert "Pedro" in texto
    assert "Ya no está en tu panel" in texto


def test_mensaje_liberada():
    texto = asig.mensaje_clase_liberada("clase de CrossFit del 2026-04-14 19:00",
                                        "Ana Admin")
    assert texto.startswith("🔴 Ana Admin te quitó la clase de CrossFit")

