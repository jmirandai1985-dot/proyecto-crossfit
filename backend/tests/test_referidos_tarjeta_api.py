"""
Tarjeta FIJA del carrusel "Invita y Gana" `GET/PUT /referidos/tarjeta` — TEST.

Qué cubre, visto desde HTTP (la app real contra la rama TEST, sin servidor):

  * `GET /referidos/tarjeta` lo lee CUALQUIER autenticado (el alumno del Inicio,
    también con plan de prueba): 401 sin token, 200 con token de alumno.
  * `GET` sin fila devuelve el copy por defecto y NO crea nada (leer no escribe),
    con el mismo cuerpo para alumno y admin: nunca porcentajes del box.
  * `PUT /referidos/tarjeta` es SÓLO admin (403 alumno) y hace upsert de UNA
    fila: cada texto NULL o en blanco cae a su default, `visible` se apaga sin
    tocar el copy y los inválidos (máximos, `visible` ausente, campos ajenos)
    son 422 sin escribir en la BD.
  * Guardar la tarjeta NO toca `configuracion_referidos`: el copy del alumno no
    puede encender ni configurar el programa de referidos.

Reglas de test del proyecto: se escribe y se BORRA en TEST (nunca PROD) y el
estado del box 1 se RESTAURA en el `finally`, aunque el test falle.

    cd backend && py -3.12 -m pytest tests/test_referidos_tarjeta_api.py -q
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_test_db_url, settings                    # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.schemas import referidos as esquemas                           # noqa: E402
from app.services import referidos_service as svc                       # noqa: E402

TENANT_ID = 1
RUTA = "/api/v1/referidos/tarjeta"


# ── Infraestructura de test (mismo patrón que test_referidos_api) ────────────

@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _token_de(db, rol: str):
    """Token REAL de un usuario activo del box 1, sin crear ni borrar nada."""
    fila = db.execute(text(
        "SELECT id, correo, rol FROM usuarios WHERE tenant_id = :t "
        "AND rol = :r AND estado = 'activo' ORDER BY id LIMIT 1"),
        {"t": TENANT_ID, "r": rol}).first()
    if fila is None:
        pytest.skip(f"TEST no tiene un {rol} activo en el box 1")
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": int(fila.id), "tenant_id": TENANT_ID,
        "rol": fila.rol, "correo": fila.correo})}


@pytest.fixture(scope="module")
def admin_headers(db):
    return _token_de(db, "administrador")


@pytest.fixture(scope="module")
def alumno_headers(db):
    return _token_de(db, "alumno")


# ── Lectura del estado real ─────────────────────────────────────────────────

def _tarjeta_de(db, tenant_id: int = TENANT_ID):
    db.rollback()
    return db.execute(text(
        "SELECT id, tenant_id, titulo, texto, cta, visible "
        "FROM tarjeta_referidos WHERE tenant_id = :t"), {"t": tenant_id}).first()


def _filas_de_tarjeta(db) -> int:
    db.rollback()
    return db.execute(text(
        "SELECT count(*) FROM tarjeta_referidos WHERE tenant_id = :t"),
        {"t": TENANT_ID}).scalar()


def _configs_del_box(db) -> int:
    """Guardar la tarjeta NO puede crear ni encender el programa de referidos."""
    db.rollback()
    return db.execute(text(
        "SELECT count(*) FROM configuracion_referidos WHERE tenant_id = :t"),
        {"t": TENANT_ID}).scalar()


def test_tarjeta_no_hereda_los_porcentajes_del_box(cliente, admin_headers):
    """El alumno ve el copy, NUNCA los porcentajes (eso es `GET /configuracion`)."""
    respuesta = cliente.get(RUTA, headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    assert set(respuesta.json()) == {
        "titulo", "texto", "cta", "visible", "personalizada"}


@pytest.fixture(scope="module")
def sin_tarjeta(db):
    """Deja el box 1 SIN fila de tarjeta y la RESTAURA al terminar."""
    original = _tarjeta_de(db)
    db.execute(text("DELETE FROM tarjeta_referidos WHERE tenant_id = :t"),
               {"t": TENANT_ID})
    db.commit()
    yield original

    db.rollback()
    db.execute(text("DELETE FROM tarjeta_referidos WHERE tenant_id = :t"),
               {"t": TENANT_ID})
    if original is not None:
        db.execute(text(
            "INSERT INTO tarjeta_referidos "
            "(id, tenant_id, titulo, texto, cta, visible) "
            "VALUES (:id, :t, :titulo, :texto, :cta, :visible)"),
            {"id": original.id, "t": TENANT_ID, "titulo": original.titulo,
             "texto": original.texto, "cta": original.cta,
             "visible": original.visible})
    db.commit()


POR_DEFECTO = {
    "titulo": svc.TARJETA_REFERIDOS_TITULO,
    "texto": svc.TARJETA_REFERIDOS_TEXTO,
    "cta": svc.TARJETA_REFERIDOS_CTA,
    "visible": True,
    "personalizada": False,
}


def test_get_tarjeta_lo_lee_el_alumno_y_no_escribe(cliente, db, sin_tarjeta,
                                                   admin_headers,
                                                   alumno_headers):
    """Sin fila: el copy por defecto, igual para alumno y admin."""
    assert cliente.get(RUTA).status_code == 401

    respuesta = cliente.get(RUTA, headers=alumno_headers)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == POR_DEFECTO
    assert _tarjeta_de(db) is None, "GET no debe crear la tarjeta"
    # El copy no depende del rol: el admin ve exactamente lo mismo.
    assert cliente.get(RUTA, headers=admin_headers).json() == POR_DEFECTO
    # Y el alumno nunca recibe los porcentajes del box.
    assert "porcentaje_descuento_invitado" not in respuesta.json()


def test_put_tarjeta_es_solo_admin_y_hace_upsert(cliente, db, sin_tarjeta,
                                                 admin_headers,
                                                 alumno_headers):
    """El admin edita el copy; cada texto en blanco vuelve a heredar el default."""
    configs_antes = _configs_del_box(db)

    # ── Sólo admin escribe ──
    respuesta = cliente.put(
        RUTA, json={"titulo": "Trae a tu parcero", "visible": True},
        headers=alumno_headers)
    assert respuesta.status_code == 403, respuesta.text
    assert "administrador" in respuesta.json()["detail"].lower()
    assert cliente.put(RUTA, json={"visible": False}).status_code == 401
    assert _tarjeta_de(db) is None, "un 403 no puede escribir"

    # ── PUT: crea la fila con los textos propios y deja el resto en NULL ──
    respuesta = cliente.put(RUTA, json={
        "titulo": "  Trae a tu parcero  ",
        "texto": "   ",
        "cta": "Quiero mi mes gratis",
        "visible": True,
    }, headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    creada = _tarjeta_de(db)
    assert creada is not None
    assert creada.titulo == "Trae a tu parcero"   # recortado
    assert creada.texto is None                   # blanco = default
    assert creada.cta == "Quiero mi mes gratis"
    assert creada.visible is True
    assert _filas_de_tarjeta(db) == 1, "upsert: una sola fila por box"

    # El texto no guardado lo resuelve el SERVIDOR: el alumno lo ve lleno.
    assert respuesta.json() == {
        "titulo": "Trae a tu parcero",
        "texto": svc.TARJETA_REFERIDOS_TEXTO,
        "cta": "Quiero mi mes gratis",
        "visible": True,
        "personalizada": True,
    }
    assert cliente.get(RUTA, headers=alumno_headers).json() == respuesta.json()

    # ── Apagar la tarjeta no borra el copy ──
    respuesta = cliente.put(
        RUTA, json={"titulo": "Trae a tu parcero", "visible": False},
        headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["visible"] is False
    assert respuesta.json()["personalizada"] is True
    apagada = _tarjeta_de(db)
    assert apagada.id == creada.id, "el upsert no debe crear otra fila"
    assert apagada.titulo == "Trae a tu parcero", "apagar no borra el copy"
    # Y el alumno deja de verla (el carrusel la salta), pero la fila sigue.
    assert cliente.get(RUTA, headers=alumno_headers).json()["visible"] is False

    # ── Volver al default: blanco = NULL (sigue heredando el genérico) ──
    respuesta = cliente.put(RUTA, json={
        "titulo": "", "texto": None, "cta": "  ", "visible": True},
        headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == POR_DEFECTO
    sin_copy = _tarjeta_de(db)
    assert sin_copy.id == creada.id
    assert (sin_copy.titulo, sin_copy.texto, sin_copy.cta) == (None, None, None)

    # ── Inválidos: 422 y la fila queda como estaba (Pydantic valida primero) ──
    for invalido in (
        {"titulo": "a" * esquemas.TARJETA_TITULO_MAX + "a", "visible": True},
        {"texto": "a" * esquemas.TARJETA_TEXTO_MAX + "a", "visible": True},
        {"cta": "a" * esquemas.TARJETA_CTA_MAX + "a", "visible": True},
        {"titulo": "Sin visible"},
        {"titulo": "Otro box", "visible": True, "tenant_id": 2},
    ):
        respuesta = cliente.put(RUTA, json=invalido, headers=admin_headers)
        assert respuesta.status_code == 422, (invalido, respuesta.text)
    assert _filas_de_tarjeta(db) == 1
    assert _tarjeta_de(db).titulo is None

    # ── Guardar la tarjeta NO toca el programa de referidos del box ──
    assert _configs_del_box(db) == configs_antes


