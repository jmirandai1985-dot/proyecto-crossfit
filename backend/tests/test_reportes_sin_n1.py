"""
Reportes — guard anti N+1 y paridad de valores (Parte 4 del fix 2026-10).

ANTES (`GET /reportes/`):
  · ocupación por disciplina: 1 consulta + 1 por CADA disciplina (N+1);
  · histórico de membresías: 6 COUNT(*) (uno por mes);
  · histórico de ingresos: 6 × `metricas.ingresos_netos()` = 12 consultas
    (esa función hace 2 SUM: ingreso y egreso).
  Total del endpoint: 19 + N consultas.

AHORA: 3 consultas únicas (`_ocupacion_por_disciplina`,
`_historico_membresias_6m`, `_historico_ingresos_6m`) y el endpoint queda en
~19 consultas, sin importar cuántas disciplinas haya.

REVISIÓN 2026-10-22 (Parte B del rediseño): se agregaron 2 bloques FIJOS —
ranking de planes del mes (`planesMasVendidos`) y Bazar del mes anterior
(`ventasBazarMesAnterior`/`ventasBazarVariacion`). El detalle de "Planes
Vencidos" no sumó consulta: reemplazó al COUNT de `cancelacionesMes` (mismo
WHERE, el número es `len(planes_vencidos_rows)`). Total: 21 fijas.

Los tests de fuente + helpers falsos corren SIN red y SIN base de datos:

    cd backend && py -3.12 -m pytest tests/test_reportes_sin_n1.py --noconftest -q

Los tests de integración usan la BD TEST (fallan cerrado si la URL no es de
test) y se SALTAN si el branch no está disponible:
  - cuentan las consultas reales del endpoint (deben ser ≤ 21);
  - comparan los 3 bloques nuevos contra la implementación anterior (N+1).
"""
import ast
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
HELPERS = (
    "_ocupacion_por_disciplina",
    "_historico_membresias_6m",
    "_historico_ingresos_6m",
)


def _fuente(relativa: str) -> str:
    # utf-8-sig: reportes.py trae BOM y `ast.parse` no lo acepta.
    return (RAIZ / relativa).read_text(encoding="utf-8-sig")


def _funcion(arbol: ast.Module, nombre: str):
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"No se encontró la función {nombre!r}")


def _execute_count(funcion) -> int:
    total = 0
    for nodo in ast.walk(funcion):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute):
            if nodo.func.attr == "execute":
                total += 1
    return total


# ── Guard de fuente ─────────────────────────────────────────────────────────

def test_el_endpoint_usa_los_tres_helpers_y_ya_no_tiene_bucles_n_mas_1():
    fuente = _fuente("backend/app/api/v1/reportes.py")
    arbol = ast.parse(fuente)
    endpoint = _funcion(arbol, "obtener_reportes_analytics")
    segmento = ast.get_source_segment(fuente, endpoint)

    for helper in HELPERS:
        assert f"{helper}(" in segmento, f"el endpoint debe llamar a {helper}"

    # Los viejos bucles de consultas por mes desaparecieron del endpoint.
    assert "for i in range(5, -1, -1)" not in segmento
    # ...y la consulta por disciplina (N+1) tampoco está.
    assert "c.disciplina_id = :did" not in fuente
    assert "GROUP BY c.disciplina_id" not in segmento

    # Cada helper hace EXACTAMENTE una consulta.
    for helper in HELPERS:
        funcion = _funcion(arbol, helper)
        assert _execute_count(funcion) == 1, (
            f"{helper} debe resolver todo con una sola consulta"
        )


# ── Helpers con DB falsa (sin red) ──────────────────────────────────────────

class _ResultadoFalso:
    def __init__(self, filas=None, escalar=None):
        self._filas = filas or []
        self._escalar = escalar

    def fetchall(self):
        return self._filas

    def scalar(self):
        return self._escalar


class _DbFalsa:
    def __init__(self, resultado):
        self.resultado = resultado
        self.consultas = []

    def execute(self, sql, params=None):
        self.consultas.append((str(sql), params or {}))
        return self.resultado


def _reportes():
    from app.api.v1 import reportes
    return reportes


def test_ocupacion_por_disciplina_es_una_consulta_y_conserva_los_calculos():
    reportes = _reportes()
    fila = SimpleNamespace(
        id=1, nombre=" CrossFit ", total_clases=10, clases_sin_tope=0,
        asistentes=50, asistentes_con_tope=50, cupo=100, alumnos_unicos=7,
        reservas=52,
    )
    db = _DbFalsa(_ResultadoFalso(filas=[fila]))

    inicio, fin = reportes._inicio_fin_mes(0)
    resultado = reportes._ocupacion_por_disciplina(db, 1, inicio, fin)

    assert len(db.consultas) == 1
    assert resultado == [{
        "id": 1,
        "nombre": "CrossFit",
        "clases": 10,
        "clases_sin_tope": 0,
        "sin_tope": False,
        "asistentes": 50,
        "reservas": 52,
        "cupo_total": 100,
        "alumnos_unicos": 7,
        "ocupacion_pct": 50,        # round(50 / 100 * 100)
    }]


def test_ocupacion_por_disciplina_cupo_cero_no_divide_por_cero():
    reportes = _reportes()
    fila = SimpleNamespace(
        id=2, nombre="Yoga", total_clases=0, clases_sin_tope=0,
        asistentes=0, asistentes_con_tope=0, cupo=0, alumnos_unicos=0,
        reservas=0,
    )
    db = _DbFalsa(_ResultadoFalso(filas=[fila]))

    inicio, fin = reportes._inicio_fin_mes(0)
    resultado = reportes._ocupacion_por_disciplina(db, 1, inicio, fin)

    assert len(db.consultas) == 1
    assert resultado[0]["ocupacion_pct"] == 0


def test_ocupacion_por_disciplina_sin_tope_informa_reservas_y_no_porcentaje():
    """Migración 066: una sala de acceso libre no tiene denominador."""
    reportes = _reportes()
    fila = SimpleNamespace(
        id=3, nombre="Musculacion", total_clases=40, clases_sin_tope=40,
        asistentes=87, asistentes_con_tope=0, cupo=0, alumnos_unicos=31,
        reservas=87,
    )
    db = _DbFalsa(_ResultadoFalso(filas=[fila]))

    inicio, fin = reportes._inicio_fin_mes(0)
    resultado = reportes._ocupacion_por_disciplina(db, 1, inicio, fin)

    assert resultado[0]["sin_tope"] is True
    assert resultado[0]["ocupacion_pct"] is None, "sin cupo no hay % honesto"
    assert resultado[0]["reservas"] == 87, "el uso se informa como conteo"
    assert resultado[0]["cupo_total"] == 0


def test_historico_membresias_es_una_consulta_y_rellena_con_cero():
    reportes = _reportes()
    inicio, _ = reportes._inicio_fin_mes(0)
    db = _DbFalsa(_ResultadoFalso(
        filas=[SimpleNamespace(mes=inicio.date(), membresias=3)]))

    resultado = reportes._historico_membresias_6m(db, 1)

    assert len(db.consultas) == 1
    assert len(resultado) == 6
    assert resultado[-1]["membresias"] == 3
    assert all(fila["membresias"] == 0 for fila in resultado[:-1])


def test_historico_ingresos_es_una_consulta_y_usa_el_neto():
    reportes = _reportes()
    inicio, _ = reportes._inicio_fin_mes(0)
    db = _DbFalsa(_ResultadoFalso(
        filas=[SimpleNamespace(mes=inicio.date(), neto=Decimal("1234.50"))]))

    resultado = reportes._historico_ingresos_6m(db, 1)

    assert len(db.consultas) == 1
    assert len(resultado) == 6
    assert resultado[-1]["ingresos"] == 1234.5
    assert all(fila["ingresos"] == 0.0 for fila in resultado[:-1])


# ── Integración contra la BD TEST ───────────────────────────────────────────

@pytest.fixture(scope="module")
def db_test():
    """Sesión a la BD TEST. Falla cerrado si la URL no es de test."""
    from sqlalchemy import text

    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal, engine

    if not is_test_db_url(str(settings.DATABASE_URL)):
        pytest.fail(
            "SEGURIDAD: DATABASE_URL no es del branch TEST. "
            "No se ejecutan consultas de reportes contra producción."
        )

    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except Exception as e:                       # red/Neon no disponible
        pytest.skip(f"BD TEST no disponible: {type(e).__name__}: {e}")

    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.rollback()
        sesion.close()


def _tenant_con_clases(db) -> int:
    from sqlalchemy import text
    fila = db.execute(text("""
        SELECT tenant_id, COUNT(*) AS clases
        FROM clases
        GROUP BY tenant_id
        ORDER BY clases DESC
        LIMIT 1
    """)).first()
    if not fila:
        pytest.skip("La BD TEST no tiene clases: no se puede medir el N+1")
    return int(fila[0])


def _contar_consultas(db, funcion):
    """Ejecuta `funcion()` y devuelve (resultado, lista de SQL ejecutado)."""
    from sqlalchemy import event, text

    engine = db.get_bind()
    consultas = []

    def antes(conn, cursor, statement, parameters, context, executemany):
        consultas.append(statement)

    # Deja la conexión lista (y la transacción abierta) ANTES de contar, para
    # que el pre-ping del pool no se cuele en la medición.
    db.execute(text("SELECT 1"))

    event.listen(engine, "before_cursor_execute", antes)
    try:
        resultado = funcion()
    finally:
        event.remove(engine, "before_cursor_execute", antes)
    return resultado, consultas


def test_el_endpoint_hace_a_lo_mas_22_consultas(db_test):
    reportes = _reportes()
    tenant_id = _tenant_con_clases(db_test)

    datos, consultas = _contar_consultas(
        db_test,
        lambda: reportes.obtener_reportes_analytics(
            tenant_id=tenant_id,
            db=db_test,
            current_user={"tenant_id": tenant_id},
        ),
    )

    # 22 = 19 históricas (endpoint sin N+1) + 2 bloques FIJOS de la revisión
    # 2026-10-22 (Parte B): ranking de planes del mes y Bazar del mes anterior
    # + 1 de la migración 066 (`metricas.reservas_sin_tope`: el conteo de las
    # disciplinas de acceso libre, que NO entra al denominador de ocupación).
    # El detalle de "Planes Vencidos" no sumó: reemplazó al COUNT de
    # `cancelacionesMes` (mismo WHERE). Si la base no alcanza el mínimo de
    # retención, `retencion_cohorte` corta antes y son menos: el tope sigue en 22.
    assert len(consultas) <= 22, (
        f"El endpoint ejecutó {len(consultas)} consultas (máximo 22).\n"
        + "\n\n".join(consultas)
    )

    # La ocupación se resolvió en UNA sola consulta, sin importar N.
    consultas_disc = [
        sql for sql in consultas
        if "WITH clases_disc AS" in sql and "alumnos_disc AS" in sql
    ]
    assert len(consultas_disc) == 1
    assert not any("c.disciplina_id = :did" in sql for sql in consultas)
    assert datos["ocupacionPorDisciplina"] is not None



def _legacy_ocupacion(db, tenant_id, inicio_mes, fin_mes):
    """Implementación ANTERIOR (1 + N) para comparar valores.

    Actualizada a la regla de la migración 066 (Musculación / Open Box sin
    tope): el cupo suma sólo las clases CON cupo, el % es `None` cuando la
    disciplina no tiene denominador y `reservas` se cuenta aparte. La forma de
    calcular sigue siendo la vieja (1 consulta + 1 por disciplina), así que el
    test sigue probando que el CTE y la N+1 dan lo MISMO.
    """
    from sqlalchemy import text

    from app.core.estados import lista_sql
    from app.services.clases_service import sql_clase_realizada

    parametros = {
        "tid": tenant_id,
        "inicio_d": inicio_mes.date(),
        "fin_d": fin_mes.date(),
    }
    filas = db.execute(text("""
        SELECT d.id, d.nombre,
               COUNT(c.id) as total_clases,
               COUNT(c.id) FILTER (WHERE c.cupo_maximo IS NULL) as clases_sin_tope,
               COALESCE(SUM(COALESCE(c.asistentes_confirmados, 0)), 0) as asistentes,
               COALESCE(SUM(COALESCE(c.asistentes_confirmados, 0))
                        FILTER (WHERE c.cupo_maximo IS NOT NULL), 0) as asistentes_con_tope,
               COALESCE(SUM(c.cupo_maximo)
                        FILTER (WHERE c.cupo_maximo IS NOT NULL), 0) as cupo
        FROM clases c
        JOIN disciplinas d ON c.disciplina_id = d.id
        WHERE c.tenant_id = :tid
          AND c.fecha >= :inicio_d
          AND c.fecha <= :fin_d
          AND """ + sql_clase_realizada("c") + """
        GROUP BY d.id, d.nombre
        ORDER BY d.id
    """), parametros).fetchall()

    resultado = []
    for r in filas:
        alumnos = db.execute(text("""
            SELECT COUNT(DISTINCT r.alumno_id)
            FROM reservas r
            JOIN clases c ON r.clase_id = c.id
            WHERE c.tenant_id = :tid
              AND c.disciplina_id = :did
              AND r.asistio = true
              AND c.fecha >= :inicio_d
              AND c.fecha <= :fin_d
        """), {**parametros, "did": r.id}).scalar() or 0
        reservas = db.execute(text(
            "SELECT COUNT(r.id) FROM reservas r "
            "JOIN clases c ON r.clase_id = c.id "
            "WHERE c.tenant_id = :tid AND c.disciplina_id = :did "
            "  AND c.fecha >= :inicio_d AND c.fecha <= :fin_d "
            "  AND r.estado NOT IN (" + lista_sql() + ")"
        ), {**parametros, "did": r.id}).scalar() or 0
        cupo = r.cupo or 0
        sin_tope = (r.total_clases or 0) > 0 and (
            r.clases_sin_tope or 0) == r.total_clases
        resultado.append({
            "id": r.id,
            "nombre": r.nombre.strip() if r.nombre else "—",
            "clases": r.total_clases,
            "clases_sin_tope": r.clases_sin_tope or 0,
            "sin_tope": sin_tope,
            "asistentes": r.asistentes,
            "reservas": reservas,
            "cupo_total": cupo,
            "alumnos_unicos": alumnos,
            "ocupacion_pct": None if sin_tope else (
                round(r.asistentes_con_tope / cupo * 100) if cupo > 0 else 0),
        })
    return resultado


def test_los_tres_bloques_devuelven_exactamente_lo_mismo_que_antes(db_test):
    reportes = _reportes()
    tenant_id = _tenant_con_clases(db_test)

    datos = reportes.obtener_reportes_analytics(
        tenant_id=tenant_id,
        db=db_test,
        current_user={"tenant_id": tenant_id},
    )

    # 1. Ocupación por disciplina: contraste contra el 1 + N anterior.
    inicio, fin = reportes._inicio_fin_mes(0)
    assert datos["ocupacionPorDisciplina"] == _legacy_ocupacion(
        db_test, tenant_id, inicio, fin)

    # 2. Membresías: 6 COUNT por mes (el código anterior).
    from sqlalchemy import text
    esperado_membresias = []
    for i in range(5, -1, -1):
        ini, fin_mes = reportes._inicio_fin_mes(-i)
        cantidad = db_test.execute(text("""
            SELECT COUNT(*) FROM suscripciones
            WHERE tenant_id = :tid
              AND fecha_inicio >= :ini
              AND fecha_inicio <= :fin
        """), {"tid": tenant_id, "ini": ini, "fin": fin_mes}).scalar() or 0
        esperado_membresias.append({
            "mes": f"{reportes.MESES[ini.month - 1]} {ini.year}",
            "membresias": int(cantidad),
        })
    assert datos["historicoMembresias"] == esperado_membresias

    # 3. Ingresos: la implementación anterior llamaba `ingresos_netos` 6 veces.
    from app.services import metricas_service as metricas
    esperado_ingresos = []
    for i in range(5, -1, -1):
        ini, fin_mes = reportes._inicio_fin_mes(-i)
        esperado_ingresos.append({
            "mes": f"{reportes.MESES[ini.month - 1]} {ini.year}",
            "ingresos": metricas.ingresos_netos(
                db_test, tenant_id, ini.date(), fin_mes.date()),
        })
    assert datos["historicoIngresos"] == esperado_ingresos

