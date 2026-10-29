"""
Reservas y Solicitudes de plan — guard anti N+1 (auditoría 2026-10-29).

ANTES:
  · `GET /reservas/por-clase/{clase_id}` (el padrón que abre el panel del coach):
    1 SELECT de `reservas` + 1 SELECT de `usuarios` por CADA reserva ⇒ 1+N
    (una clase de 25 alumnos = 26 consultas, y el panel la pide por clase y día).
  · `GET /solicitudes-planes/pendientes` (la cola del admin): 1 SELECT de
    `solicitudes_planes` + 2 por CADA fila (`planes` y `usuarios`) ⇒ 1+2N
    (con 20 pendientes eran 41 consultas).

AHORA: ambos resuelven el nombre con LEFT JOIN en UNA sola consulta, sin cambiar
lo que devuelven:
  · reservas: JOIN a `usuarios` por (id, tenant_id) — el mismo filtro de tenant de
    antes, así que un alumno de otro box sigue cayendo en `Alumno #<id>`.
  · solicitudes: JOIN a `planes` y `usuarios` por `id` — el criterio de antes (el
    nombre se resolvía por id, sin filtro de tenant), así que una solicitud
    huérfana sigue devolviendo "Desconocido".

Los tests de fuente corren SIN red y SIN base de datos:

    cd backend && py -3.12 -m pytest tests/test_sin_n1_reservas_y_solicitudes.py -q

Los de integración usan la BD TEST (fallan cerrado si la URL no es de test) y se
SALTAN si la tabla no tiene filas para medir.
"""
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]

# Llamadas que "tocan" la base si aparecen DENTRO de un `for`: son justo las que
# convertían estos endpoints en N+1 (una por fila).
LLAMADAS_POR_FILA = {"query", "first", "all", "scalar", "one", "one_or_none"}


def _fuente(relativa: str) -> str:
    # utf-8-sig: los routers traen BOM y `ast.parse` no lo acepta.
    return (RAIZ / relativa).read_text(encoding="utf-8-sig")


def _funcion(arbol: ast.Module, nombre: str):
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"No se encontró la función {nombre!r}")


def _consultas_dentro_de_bucles(funcion) -> list[str]:
    """Consultas ejecutadas DENTRO de un `for` (el patrón N+1)."""
    encontradas = []
    for nodo in ast.walk(funcion):
        if not isinstance(nodo, (ast.For, ast.AsyncFor)):
            continue
        for hijo in ast.walk(nodo):
            if isinstance(hijo, ast.Call) and isinstance(hijo.func, ast.Attribute):
                if hijo.func.attr in LLAMADAS_POR_FILA:
                    encontradas.append(f".{hijo.func.attr}() en la línea {hijo.lineno}")
    return encontradas


# ── Guard de fuente (sin base de datos) ─────────────────────────────────────

def test_el_padron_de_la_clase_resuelve_los_nombres_en_la_misma_consulta():
    fuente = _fuente("backend/app/api/v1/reservas.py")
    endpoint = _funcion(ast.parse(fuente), "listar_reservas_por_clase")
    segmento = ast.get_source_segment(fuente, endpoint)

    assert "outerjoin(" in segmento, "el padrón debe traer el nombre con un JOIN"
    # El filtro de tenant del JOIN es lo que mantiene el fallback `Alumno #<id>`
    # para un alumno de otro box: no puede quedar sólo en el WHERE.
    assert ("and_(Usuario.id == Reserva.alumno_id, "
            "Usuario.tenant_id == tenant_id)") in segmento

    sobrantes = _consultas_dentro_de_bucles(endpoint)
    assert sobrantes == [], (
        "el padrón volvió a consultar por fila (N+1): " + ", ".join(sobrantes)
    )


def test_la_cola_de_pendientes_resuelve_plan_y_alumno_en_la_misma_consulta():
    fuente = _fuente("backend/app/api/v1/solicitudes_planes.py")
    endpoint = _funcion(ast.parse(fuente), "listar_solicitudes_pendientes")
    segmento = ast.get_source_segment(fuente, endpoint)

    assert segmento.count("outerjoin(") == 2, (
        "plan y alumno tienen que venir en el mismo SELECT (2 LEFT JOIN)"
    )
    assert "Plan.id == SolicitudPlan.plan_id" in segmento
    assert "Usuario.id == SolicitudPlan.alumno_id" in segmento
    # El import dentro del bucle era parte del N+1 (se resolvía fila por fila).
    assert "from app.models.usuario import Usuario" not in segmento

    sobrantes = _consultas_dentro_de_bucles(endpoint)
    assert sobrantes == [], (
        "la cola de pendientes volvió a consultar por fila (N+1): " + ", ".join(sobrantes)
    )


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
            "No se ejecutan consultas de reservas ni de solicitudes contra producción."
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


def test_el_padron_de_una_clase_hace_una_consulta_y_devuelve_los_mismos_nombres(db_test):
    from sqlalchemy import text

    fila = db_test.execute(text("""
        SELECT clase_id, tenant_id, COUNT(*) AS total
        FROM reservas
        GROUP BY clase_id, tenant_id
        ORDER BY total DESC
        LIMIT 1
    """)).first()
    if not fila:
        pytest.skip("La BD TEST no tiene reservas: no se puede medir el N+1")
    clase_id, tenant_id, total = int(fila[0]), int(fila[1]), int(fila[2])

    from app.api.v1 import reservas

    resultado, consultas = _contar_consultas(
        db_test,
        lambda: reservas.listar_reservas_por_clase(
            clase_id=clase_id,
            db=db_test,
            current_user={"tenant_id": tenant_id, "rol": "admin", "usuario_id": 0},
            modo_emergencia=False,
        ),
    )

    # 1 SELECT fijo: el número NO depende de cuántos alumnos tenga la clase
    # (antes eran 1 + `total`). El margen de 2 tolera el pre-ping del pool.
    assert len(consultas) <= 2, (
        f"El padrón ejecutó {len(consultas)} consultas para {total} reservas "
        f"(máximo 2).\n" + "\n\n".join(consultas)
    )
    assert len(resultado) == total

    # Paridad exacta con el criterio anterior (LEFT JOIN por id + tenant_id).
    esperado = db_test.execute(text("""
        SELECT r.id, u.nombre
        FROM reservas r
        LEFT JOIN usuarios u
               ON u.id = r.alumno_id AND u.tenant_id = r.tenant_id
        WHERE r.clase_id = :cid
          AND r.tenant_id = :tid
        ORDER BY r.created_at ASC, r.id ASC
    """), {"cid": clase_id, "tid": tenant_id}).fetchall()

    assert [(f["id"], f["alumno_nombre"]) for f in resultado] == [
        (fila_id, nombre or f"Alumno #{fila_id}") for fila_id, nombre in esperado
    ]


def test_la_cola_de_pendientes_hace_una_consulta_y_devuelve_lo_mismo(db_test):
    from sqlalchemy import text

    fila = db_test.execute(text("""
        SELECT tenant_id, COUNT(*) AS total
        FROM solicitudes_planes
        WHERE estado = 'pending'
        GROUP BY tenant_id
        ORDER BY total DESC
        LIMIT 1
    """)).first()
    if not fila or int(fila[1]) == 0:
        pytest.skip("La BD TEST no tiene solicitudes pendientes: no se puede medir el N+1")
    tenant_id, total = int(fila[0]), int(fila[1])

    from app.api.v1 import solicitudes_planes

    resultado, consultas = _contar_consultas(
        db_test,
        lambda: solicitudes_planes.listar_solicitudes_pendientes(
            db=db_test,
            current_user={"tenant_id": tenant_id, "rol": "admin", "usuario_id": 0},
        ),
    )

    # 1 SELECT fijo (antes: 1 + 2 × pendientes).
    assert len(consultas) <= 2, (
        f"La cola ejecutó {len(consultas)} consultas para {total} pendientes "
        f"(máximo 2).\n" + "\n\n".join(consultas)
    )
    assert len(resultado) == total

    # Paridad con el criterio anterior: plan y alumno resueltos por `id`, y los
    # precios con la precedencia snapshot → precio del plan.
    for item in resultado:
        snapshot, final, plan_nombre, plan_precio, alumno_nombre, alumno_correo = \
            db_test.execute(text("""
                SELECT s.precio_clp_snapshot, s.precio_final_clp,
                       p.nombre, p.precio_clp, u.nombre, u.correo
                FROM solicitudes_planes s
                LEFT JOIN planes p ON p.id = s.plan_id
                LEFT JOIN usuarios u ON u.id = s.alumno_id
                WHERE s.id = :sid
            """), {"sid": item["id"]}).first()

        precio_lista = plan_precio if plan_precio is not None else 0
        precio_esperado = snapshot if snapshot is not None else precio_lista
        final_esperado = final if final is not None else precio_esperado

        assert item["plan_nombre"] == (plan_nombre or "Desconocido")
        assert item["alumno_nombre"] == (alumno_nombre or "Desconocido")
        assert item["alumno_email"] == (alumno_correo or "")
        assert item["plan_precio"] == precio_esperado
        assert item["precio_final"] == final_esperado
