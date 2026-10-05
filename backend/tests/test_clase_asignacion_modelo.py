"""
El modelo `Clase` declara las columnas de la asignación de coach (migración 042).

QUÉ PASÓ (bug de PROD, desplegado en 2dddbfa)
---------------------------------------------
La migración 042 creó `clases.asignacion_origen / asignada_por / asignada_en`,
pero `app/models/clase.py` NO las declaraba. Resultado: NINGUNA clase se generaba
—`'asignacion_origen' is an invalid keyword argument for Clase`— en el arranque
(`main.py`), en el job de las 00:05 (`services/scheduler.py`) y en el respaldo de
`GET /clases`; el rango HOY + 28 días quedaba vacío (el último día, p. ej.
2026-11-02, con 0/26).

¿Por qué los tests aislados de B2 no lo vieron?
-----------------------------------------------
Porque miraban el OTRO camino de escritura:

  * `services/asignaciones_clases.py` (`marcar_clase` / `liberar_clase`) escribe
    por ATRIBUTO (`clase.asignacion_origen = ...`) y eso funciona igual en un
    objeto Python aunque la columna no esté mapeada: el valor queda en el
    `__dict__` de la instancia (y quien escribe de verdad en la tabla es SQL
    crudo). Los tests de B2 usaban `Clase()` + `marcar_clase` → verde.
  * `services/generar_clases.py` las pasa al CONSTRUCTOR
    (`Clase(asignacion_origen=..., asignada_por=..., asignada_en=...)`) y el
    constructor de SQLAlchemy SÍ valida los kwargs → TypeError. Ningún test
    ejecutaba ese armado.

Estos tests cierran las dos puertas:
  * el constructor acepta las 3 y quedan MAPEADAS (no sueltas en `__dict__`);
  * `generar_clases_para_fecha` y `generar_clases_para_rango` se EJECUTAN con una
    sesión falsa (sin BD): se arma la clase de verdad y se revisa la traza;
  * guard por AST: TODO kwarg del constructor `Clase(...)` del código de la app
    tiene que estar mapeado (red general: esto habría cazado el bug sin saber
    dónde estaba, y avisa igual el día que alguien agregue otra columna).

    cd backend && py -3.12 -m pytest tests/test_clase_asignacion_modelo.py -q --noconftest
"""
import ast
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.models.clase import Clase
from app.models.horario_base import HorarioBase
from app.services import asignaciones_clases as asig
from app.services import generar_clases as gen

RAIZ = Path(__file__).resolve().parents[1]          # .../backend

# Lunes 2026-10-05 = el "hoy" del bug; 2026-11-02 = hoy + 28 (el último día del
# rango, el que quedaba en 0/26).
LUNES = date(2026, 10, 5)
ULTIMO_DIA = date(2026, 11, 2)

MAPEADAS = ("asignacion_origen", "asignada_por", "asignada_en")


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


class _Consulta:
    def __init__(self, filas):
        self._filas = list(filas)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._filas)

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFalsa:
    """Sesión mínima para el generador: horarios, "ya existe", `add` y `commit`."""

    def __init__(self, horarios=(), existente=None):
        self._horarios = list(horarios)
        self._existente = existente
        self.agregadas = []
        self.commits = 0
        self.consultas = []

    def query(self, modelo):
        self.consultas.append(modelo)
        if modelo is HorarioBase:
            return _Consulta(self._horarios)
        if modelo is Clase:
            return _Consulta([self._existente] if self._existente else [])
        raise AssertionError(f"consulta inesperada a {modelo!r}")

    def add(self, obj):
        self.agregadas.append(obj)

    def commit(self):
        self.commits += 1


def _horario(horario_id=5, disciplina_id=3, cupo=20):
    return SimpleNamespace(id=horario_id, disciplina_id=disciplina_id,
                           hora_inicio=time(19, 0), hora_fin=time(20, 0),
                           cupo_maximo=cupo, dia_semana=LUNES.weekday())


# ── 1. El constructor (lo que reventaba en PROD) ───────────────────────────

def test_el_constructor_acepta_las_tres_columnas_de_la_042():
    ahora = datetime.now(timezone.utc)
    clase = Clase(
        tenant_id=1, horario_base_id=5, disciplina_id=3, fecha=ULTIMO_DIA,
        hora_inicio=time(19, 0), hora_fin=time(20, 0), cupo_maximo=20,
        cupo_original=20, asistentes_confirmados=0, cancelada=False, coach_id=7,
        asignacion_origen=asig.ORIGEN_COACH, asignada_por=7, asignada_en=ahora,
    )
    assert (clase.coach_id, clase.asignacion_origen) == (7, "coach")
    assert clase.asignada_por == 7
    assert clase.asignada_en == ahora


def test_el_constructor_sigue_rechazando_una_columna_que_no_existe():
    """Control: el TypeError de SQLAlchemy es real (no un falso positivo nuestro)."""
    import pytest

    with pytest.raises(TypeError, match="invalid keyword argument"):
        Clase(esta_columna_no_existe=1)


def test_las_tres_columnas_estan_mapeadas_en_el_modelo():
    mapeadas = set(Clase.__mapper__.attrs.keys())
    tabla = set(Clase.__table__.columns.keys())
    for columna in MAPEADAS:
        assert columna in mapeadas, f"{columna} no está mapeada: vuelve el bug"
        assert columna in tabla, f"{columna} no está en la tabla del modelo"


def test_lo_que_escribe_marcar_clase_llega_a_una_columna():
    """El camino de B2 (por atributo) tiene que caer en columnas, no en `__dict__`."""
    clase = Clase()
    asig.marcar_clase(clase, coach_id=7, origen=asig.ORIGEN_COACH, quien_id=7)
    mapeadas = set(Clase.__mapper__.attrs.keys())
    for columna in MAPEADAS:
        assert columna in mapeadas
        assert getattr(clase, columna) is not None
    asig.liberar_clase(clase)
    assert all(getattr(clase, columna) is None for columna in MAPEADAS)



def test_leer_la_asignacion_de_una_clase_recien_cargada_no_revienta():
    """`supervision.py` lee `clase.asignacion_origen` de una clase de la BD."""
    clase = Clase()
    assert clase.asignacion_origen is None
    assert clase.asignada_por is None
    assert clase.asignada_en is None


# ── 2. El CHECK y el índice: mismos nombres que la migración 042 ───────────

def test_el_check_y_el_indice_llevan_los_nombres_de_la_042():
    m042 = _fuente("alembic/versions/042_clases_asignacion_coach.py")

    assert "ck_clases_asignacion_origen" in m042
    nombres_check = {c.name for c in Clase.__table__.constraints if c.name}
    assert "ck_clases_asignacion_origen" in nombres_check
    check = next(c for c in Clase.__table__.constraints
                 if c.name == "ck_clases_asignacion_origen")
    assert "asignacion_origen IN ('coach', 'admin')" in str(check.sqltext)
    assert "asignacion_origen IN ('coach', 'admin')" in m042

    assert "ix_clases_asignacion_origen" in m042
    indice = next((i for i in Clase.__table__.indexes
                   if i.name == "ix_clases_asignacion_origen"), None)
    assert indice is not None
    assert [c.name for c in indice.columns] == ["tenant_id", "asignacion_origen"]


def test_la_fk_de_asignada_por_no_arrastra_al_usuario():
    """La migración 042 la creó ON DELETE SET NULL: borrar un usuario no borra clases."""
    fk = next(iter(Clase.__table__.c.asignada_por.foreign_keys), None)
    assert fk is not None
    assert fk.target_fullname == "usuarios.id"
    assert fk.ondelete == "SET NULL"


# ── 3. El armado real de `generar_clases_para_fecha` (sesión falsa) ─────────

def test_arma_las_clases_con_la_traza_del_coach_vigente(monkeypatch):
    db = _SesionFalsa(horarios=[_horario()])
    monkeypatch.setattr(asig, "vigencias_por_horario",
                        lambda *a, **k: {5: SimpleNamespace(coach_id=7)})

    resultado = gen.generar_clases_para_fecha(db, tenant_id=1, fecha=LUNES)

    assert (resultado["creadas"], resultado["total_horarios"]) == (1, 1)
    assert db.commits == 1
    clase = db.agregadas[0]
    assert (clase.tenant_id, clase.horario_base_id, clase.fecha) == (1, 5, LUNES)
    assert (clase.cupo_maximo, clase.cupo_original) == (20, 20)
    # La traza que rompía el constructor:
    assert (clase.coach_id, clase.asignacion_origen) == (7, asig.ORIGEN_COACH)
    assert clase.asignada_por == 7
    assert clase.asignada_en is not None


def test_sin_vigencia_la_clase_nace_sin_coach_ni_marca(monkeypatch):
    db = _SesionFalsa(horarios=[_horario()])
    monkeypatch.setattr(asig, "vigencias_por_horario", lambda *a, **k: {})

    gen.generar_clases_para_fecha(db, tenant_id=1, fecha=LUNES)

    clase = db.agregadas[0]
    assert clase.coach_id is None
    assert clase.asignacion_origen is None
    assert clase.asignada_por is None
    assert clase.asignada_en is None


def test_omite_las_clases_que_ya_existen(monkeypatch):
    db = _SesionFalsa(horarios=[_horario()], existente=SimpleNamespace(id=99))
    monkeypatch.setattr(asig, "vigencias_por_horario",
                        lambda *a, **k: {5: SimpleNamespace(coach_id=7)})

    resultado = gen.generar_clases_para_fecha(db, tenant_id=1, fecha=LUNES)

    assert (resultado["creadas"], resultado["omitidas"]) == (0, 1)
    assert db.agregadas == []
    assert db.commits == 1


def test_un_domingo_no_toca_la_base():
    db = _SesionFalsa()
    resultado = gen.generar_clases_para_fecha(db, tenant_id=1,
                                              fecha=date(2026, 11, 1))
    assert resultado["creadas"] == 0
    assert "Domingo" in resultado["message"]
    assert db.consultas == [] and db.commits == 0


def test_el_ultimo_dia_del_rango_hoy_mas_28_tambien_se_genera(monkeypatch):
    """El día que quedó vacío en PROD: el ÚLTIMO del rango (hoy + DIAS_ANTICIPACION).

    `main.py` (arranque) y `scheduler.py` (00:05) generan [hoy, hoy + 28] y
    2026-11-02 es ese último día. El rango tiene que ser INCLUSIVO.
    """
    assert gen.DIAS_ANTICIPACION == 28
    assert LUNES + timedelta(days=gen.DIAS_ANTICIPACION) == ULTIMO_DIA
    db = _SesionFalsa(horarios=[_horario()])
    monkeypatch.setattr(asig, "vigencias_por_horario", lambda *a, **k: {})

    resultado = gen.generar_clases_para_rango(db, 1, LUNES, ULTIMO_DIA)

    fechas = [c.fecha for c in db.agregadas]
    assert ULTIMO_DIA in fechas, "el último día del rango quedó sin generar"
    assert date(2026, 11, 1) not in fechas          # domingo: nunca se genera
    assert resultado["creadas"] == len(fechas) > 0
    assert resultado["fecha_hasta"] == ULTIMO_DIA.isoformat()


def test_los_tres_disparadores_usan_el_mismo_DIAS_ANTICIPACION():
    """Arranque, scheduler y respaldo de GET /clases: una sola constante."""
    for relativa in ("app/main.py", "app/services/scheduler.py",
                     "app/api/v1/clases.py"):
        fuente = _fuente(relativa)
        assert "from app.services.generar_clases import" in fuente, relativa
        assert "DIAS_ANTICIPACION" in fuente, relativa


# ── 4. Guard general: ningún kwarg del constructor sin columna en el modelo ──

def _kwargs_sin_mapear(fuente: str) -> list:
    """Kwargs de TODO `Clase(...)` del código que no son columnas mapeadas."""
    mapeadas = set(Clase.__mapper__.attrs.keys())
    faltantes = []
    for nodo in ast.walk(ast.parse(fuente)):
        es_clase = (isinstance(nodo, ast.Call)
                    and getattr(nodo.func, "id", None) == "Clase")
        if not es_clase:
            continue
        faltantes += [kw.arg for kw in nodo.keywords
                      if kw.arg and kw.arg not in mapeadas]
    return faltantes


def test_ningun_kwarg_del_constructor_de_clase_queda_sin_mapear():
    """Red general: esto habría cazado el bug sin saber dónde estaba.

    Si mañana alguien agrega un kwarg al constructor `Clase(...)` y olvida la
    columna en el modelo, este test lo nombra (y evita otro "Error al generar
    clases" en PROD).
    """
    problemas = []
    for archivo in sorted((RAIZ / "app").rglob("*.py")):
        # utf-8-sig: varios módulos del repo arrancan con BOM y `ast.parse` lo
        # rechaza como carácter no imprimible.
        fuente = archivo.read_text(encoding="utf-8-sig")
        faltantes = _kwargs_sin_mapear(fuente)
        problemas += [f"{archivo.relative_to(RAIZ)}: {kw}" for kw in faltantes]
    assert problemas == [], (
        "kwargs del constructor `Clase(...)` que NO son columnas mapeadas: "
        f"{problemas}")


def test_el_guard_detecta_de_verdad_un_kwarg_inventado():
    """Meta-test: el guard de arriba no es decorativo."""
    fuente = ("def f(x):\n"
              "    asignacion_origen = 'coach'\n"
              "    return Clase(id=x, asignacion_origen=asignacion_origen,\n"
              "                 inventada=1)\n")
    assert _kwargs_sin_mapear(fuente) == ["inventada"]
    assert _kwargs_sin_mapear("x = Clase(otra=None)") == ["otra"]
    assert _kwargs_sin_mapear("x = Clase(estado='validado')") == ["estado"]
