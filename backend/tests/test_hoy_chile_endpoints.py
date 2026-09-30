"""El día de HOY sale de Chile, no del reloj del proceso (TZ=UTC en el contenedor).

Qué fija este archivo
---------------------
`date.today()` devuelve el día del PROCESO. En un contenedor con TZ=UTC (producción) eso ya es el
día siguiente entre las 21:00 y las 23:59 CLT —el cierre del box—, así que los endpoints que deciden
con el día corrían un día adelante: "las clases de hoy" del dashboard, desde qué día se generan las
clases, qué clases ve supervisión, y la fecha que queda escrita en el ingreso de una membresía.

Lo que estaba roto y acá no puede volver: ocho `date.today()` en la app (clases, dashboard, horarios,
supervision, solicitudes_planes, suscripciones, los DOS callbacks del startup en main y el job del
scheduler). Ahora todos le piden el día al helper único de `app/utils/santiago.py` (`hoy_santiago()`),
el mismo que ya usaban la vigencia de los planes y el mantenimiento.

  A. GUARD (lee las fuentes): en `app/` no puede quedar NI UN `.today()` —el AST ignora comentarios y
     docstrings a propósito, porque ahí el bug se sigue nombrando para explicarlo— y los ocho módulos
     tocados tienen que importar el helper (y el MISMO: es una identidad, no una copia del cálculo).
  B. SIN BD (con el reloj inyectado): los que arman SQL se llaman con una sesión falsa que captura
     `(SQL, params)`, y el parámetro del día tiene que ser el de Chile; `POST /horarios/generar-clases-dia`
     sin `fecha` genera para el día de Chile (y con `fecha` explícita la respeta); y el job de las 00:05
     CLT se corre con `hoy_santiago` inyectado en un año lejano: el rango que anuncia el log sólo puede
     venir de ese helper.

Los dos `fecha=` de los ingresos (`POST /suscripciones` y aprobar una solicitud) y los dos callbacks
del startup de `main.py` no se pueden llamar sin base / sin levantar la app, así que los cubre el guard
de fuentes (A), que es justo la regresión que este commit previene.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_hoy_chile_endpoints.py -q
"""
import ast
import asyncio
import importlib
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.utils.santiago import hoy_santiago     # noqa: E402

APP = BACKEND / "app"
TENANT_ID = 1
# Un martes de un año lejano: si aparece en el SQL o en el log, el día lo dio el helper.
FECHA_INYECTADA = date(2031, 7, 15)

MODULOS_TOCADOS = (
    "app.api.v1.clases",
    "app.api.v1.dashboard",
    "app.api.v1.horarios",
    "app.api.v1.solicitudes_planes",
    "app.api.v1.supervision",
    "app.api.v1.suscripciones",
    "app.main",
    "app.services.scheduler",
)


class SesionFalsa:
    """Sesión mínima: captura `(SQL, params)` y no devuelve filas (no necesita base)."""

    def __init__(self, primera=None, filas=None):
        self.consultas = []
        self._primera = primera
        self._filas = filas or []

    def execute(self, sentencia, params=None):
        self.consultas.append((str(sentencia), dict(params or {})))
        return self

    def first(self):
        return self._primera

    def fetchall(self):
        return self._filas


# ══════════════════════════════════════════════════════════════════════════════
# A. Guard de fuentes (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_en_la_app_no_queda_ningun_date_today():
    """El día no puede volver a salir del reloj del proceso en NINGÚN módulo de la app."""
    llamadas = []
    for ruta in sorted(APP.rglob("*.py")):
        arbol = ast.parse(ruta.read_text(encoding="utf-8-sig"))
        llamadas += [(ruta.relative_to(APP).as_posix(), nodo.lineno)
                     for nodo in ast.walk(arbol)
                     if isinstance(nodo, ast.Call)
                     and isinstance(nodo.func, ast.Attribute)
                     and nodo.func.attr == "today"]

    assert llamadas == [], (
        "usar `app.utils.santiago.hoy_santiago()`: el reloj del proceso (UTC) no es el de Chile -> "
        f"{llamadas}")


def test_a2_los_ocho_modulos_del_cambio_piden_el_dia_al_mismo_helper():
    """Cada módulo tocado importa `hoy_santiago` de `app/utils/santiago.py` (una sola definición)."""
    for nombre in MODULOS_TOCADOS:
        modulo = importlib.import_module(nombre)
        assert getattr(modulo, "hoy_santiago", None) is hoy_santiago, (
            f"{nombre} no está usando el helper único del día de Chile")


# ══════════════════════════════════════════════════════════════════════════════
# B. El día del SQL y de los jobs (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_b1_el_dashboard_pregunta_por_el_dia_chileno():
    """`GET /dashboard/{tenant_id}/ocupacion-hoy`: el `:hoy` de las clases es el de Chile."""
    from app.api.v1 import dashboard

    db = SesionFalsa()
    dashboard.ocupacion_hoy(db=db, current_user={"tenant_id": TENANT_ID})

    sql, params = db.consultas[0]
    assert params["hoy"] == hoy_santiago()
    assert "c.fecha = :hoy" in sql


def test_b2_supervision_busca_la_proxima_clase_desde_el_dia_chileno():
    """`GET /supervision/proxima-clase-reservas`: la próxima clase se busca desde HOY en Chile."""
    from app.api.v1 import supervision

    db = SesionFalsa()
    respuesta = supervision.proxima_clase_reservas(
        horario_base_id=99, db=db, current_user={"tenant_id": TENANT_ID})

    sql, params = db.consultas[0]
    assert params["hoy"] == hoy_santiago()
    assert "c.fecha >= :hoy" in sql
    assert respuesta["hay_clase"] is False        # la sesión falsa no devuelve clase


def test_b3_generar_clases_sin_fecha_usa_el_dia_chileno(monkeypatch):
    """`POST /horarios/generar-clases-dia` sin `fecha` genera para HOY en Chile; con `fecha`, esa."""
    from app.api.v1 import horarios
    from app.services import generar_clases

    pedidas = []
    monkeypatch.setattr(
        generar_clases, "generar_clases_para_fecha",
        lambda db, tenant_id, fecha: pedidas.append((db, tenant_id, fecha)) or {})

    db = SesionFalsa()
    horarios.generar_clases_dia_route(db=db, current_user={"tenant_id": TENANT_ID})
    assert pedidas == [(db, TENANT_ID, hoy_santiago())]

    explicita = date(2031, 1, 2)
    horarios.generar_clases_dia_route(fecha=explicita, db=db,
                                      current_user={"tenant_id": TENANT_ID})
    assert pedidas[-1][2] == explicita            # la fecha pedida manda sobre el HOY


def test_b4_el_job_diario_genera_desde_el_dia_chileno(monkeypatch, caplog):
    """El job de las 00:05 CLT arranca el rango en el día de Chile (no el del proceso)."""
    from app.services import scheduler as sched

    monkeypatch.setattr(sched, "hoy_santiago", lambda: FECHA_INYECTADA)
    corridas = []

    async def _callback():
        corridas.append(True)
        return {"creadas": 3, "omitidas": 1}

    monkeypatch.setattr(sched, "generar_clases_callback", _callback)

    with caplog.at_level(logging.INFO, logger="uvicorn.scheduler"):
        asyncio.run(sched.job_generar_clases_diarias())

    assert corridas == [True], "el job tiene que llegar a generar (no cortar antes)"
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert FECHA_INYECTADA.isoformat() in texto, texto
    assert (FECHA_INYECTADA + timedelta(days=sched.DIAS_ANTICIPACION)).isoformat() in texto, texto
