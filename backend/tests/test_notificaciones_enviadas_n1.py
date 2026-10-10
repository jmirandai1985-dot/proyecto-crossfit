"""GET /api/v1/notificaciones-enviadas: el N+1 de los nombres de alumnos.

Medido el 10/10/2026 contra TEST contando statements de SQLAlchemy:

    antes -> 55 consultas por request (50 eran el MISMO SELECT de `usuarios`,
             una por fila de la página: `limit` por defecto = 50)
    ahora ->  6 consultas (1 de auth + 2 del resumen + 1 del total +
             1 de la página + 1 de los nombres)

Este test fija el arreglo SIN mirar el número exacto de consultas: compara la
MISMA pantalla con páginas de distinto tamaño. Si vuelve el SELECT por fila, el
conteo de `limit=2` deja de ser igual al de `limit=40` y esto falla.

Se corre con:
    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_notificaciones_enviadas_n1.py -q --noconftest
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import event, text as sa_text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.api.v1.notificaciones_enviadas as ne  # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402

FILAS_MIN = 40          # página grande: sin suficientes filas el N+1 no se nota
CLAVES_ITEM = {"id", "alumno_id", "alumno_nombre", "destinatario_correo",
               "destinatario_nombre", "destinatario_rol", "tipo", "fecha_envio",
               "estado", "detalle_error"}


@pytest.fixture(autouse=True)
def solo_lectura_en_test():
    """Este test LEE la BD real: exige TEST (nunca PROD)."""
    from app.core.config import is_test_db_url, settings

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("Este test consulta la BD: debe correr contra TEST")


@pytest.fixture
def contador():
    """Cuenta los statements que se ejecutan entre dos lecturas."""
    estado = {"n": 0}

    def _contar(conn, cursor, statement, params, context, executemany):
        estado["n"] += 1

    event.listen(engine, "before_cursor_execute", _contar)
    try:
        yield estado
    finally:
        event.remove(engine, "before_cursor_execute", _contar)


def _tenant_con_pagina(db):
    """Tenant con al menos FILAS_MIN notificaciones (la pantalla es de su admin)."""
    return db.execute(sa_text(
        "SELECT tenant_id, count(*) AS n FROM notificaciones_enviadas "
        "WHERE tenant_id IS NOT NULL GROUP BY tenant_id "
        "HAVING count(*) >= :n ORDER BY count(*) DESC LIMIT 1"),
        {"n": FILAS_MIN}).first()


def _listar(tenant_id, limit, contador):
    """Atiende la pantalla como una request real: sesión nueva por llamada."""
    antes = contador["n"]
    with SessionLocal() as db:
        pag = ne.listar_notificaciones_enviadas(
            skip=0, limit=limit, tipo=None, estado=None, alumno_id=None,
            db=db, current_user={"tenant_id": tenant_id, "rol": "administrador"})
    return pag, contador["n"] - antes


def test_el_numero_de_consultas_no_crece_con_la_pagina(contador):
    with SessionLocal() as db:
        fila = _tenant_con_pagina(db)
    if not fila:
        pytest.skip(f"TEST no tiene un tenant con {FILAS_MIN}+ notificaciones")
    tenant_id = fila.tenant_id

    _, con_dos = _listar(tenant_id, 2, contador)
    pag, con_cuarenta = _listar(tenant_id, FILAS_MIN, contador)

    assert len(pag["items"]) == FILAS_MIN
    assert con_dos == con_cuarenta, (
        f"la página de 2 filas gasta {con_dos} consultas y la de {FILAS_MIN} "
        f"gasta {con_cuarenta}: volvió el SELECT por fila (N+1)")
    assert con_cuarenta <= 8, (
        f"{con_cuarenta} consultas por request (se esperaban <= 8)")


def test_el_payload_sigue_igual_y_los_nombres_son_los_de_la_bd(contador):
    with SessionLocal() as db:
        fila = _tenant_con_pagina(db)
        if not fila:
            pytest.skip(f"TEST no tiene un tenant con {FILAS_MIN}+ notificaciones")
        tenant_id = fila.tenant_id
        pag, _ = _listar(tenant_id, FILAS_MIN, contador)

        if not pag["items"]:
            pytest.skip("la página vino vacía")
        # El arreglo cambió CÓMO se leen los nombres, no QUÉ devuelve la pantalla.
        assert set(pag["items"][0]) == CLAVES_ITEM

        ids = {i["alumno_id"] for i in pag["items"] if i["alumno_id"]}
        esperados = dict(db.query(Usuario.id, Usuario.nombre)
                         .filter(Usuario.id.in_(ids)).all()) if ids else {}

    for item in pag["items"]:
        if item["alumno_id"]:
            assert item["alumno_nombre"] == esperados[item["alumno_id"]]
        else:
            # Filas del admin/lead (alumno_id NULL): nunca quedan sin destinatario.
            assert item["alumno_nombre"]
