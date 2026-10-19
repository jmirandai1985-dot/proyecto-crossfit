"""
Endpoints de REFERIDOS (Fase 3a) — integración contra la MISMA rama TEST.

Qué cubre, visto desde HTTP (la app real, sin levantar servidor):

  * `GET /referidos/mi-codigo`: devuelve el código del DUEÑO DEL TOKEN (no hay
    forma de pedir el de otro), 403 para coach y 401 sin token.
  * `POST /referidos/validar-codigo`: código inexistente, inactivo, propio y ya
    referido (400 con el motivo exacto); el camino válido crea UNA fila en
    `referidos_aplicados` en estado `pendiente` y la segunda validación del
    mismo alumno falla. Se comprueba además que NO se tocan montos: los
    descuentos de la fila quedan NULL y la suscripción del invitado no cambia.
  * `GET/PUT /referidos/configuracion`: sólo admin (403 alumno, 401 sin token),
    GET sin fila devuelve defaults SIN crear nada, PUT hace upsert de UNA sola
    fila y 422 fuera de 0..100.

Reglas de test del proyecto: se escribe y se BORRA en TEST (nunca PROD); el
escenario se crea solo (alumnos y coach vía alta del admin) y se limpia en el
`finally`. `EMAIL_MODO=noop` evita correos reales. La configuración del box 1 se
guarda y se RESTAURA al terminar, aunque el test falle.

    cd backend && py -3.12 -m pytest tests/test_referidos_api.py -q
"""
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_test_db_url, settings                    # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.services import referidos_service as svc                       # noqa: E402

TENANT_ID = 1
BASE = "/api/v1/referidos"
BASE_USUARIOS = "/api/v1/usuarios"


# ── Infraestructura de test (mismo patrón que test_referidos_integracion) ────

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
    """TestClient del app real (sin servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def admin_headers(db):
    """Token REAL de un admin activo del box 1 (mismo camino que el navegador)."""
    fila = db.execute(text(
        "SELECT id, correo, rol FROM usuarios WHERE tenant_id = :t "
        "AND rol = 'administrador' AND estado = 'activo' "
        "ORDER BY id LIMIT 1"), {"t": TENANT_ID}).first()
    if fila is None:
        pytest.skip("TEST no tiene un administrador activo en el box 1")
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": int(fila.id), "tenant_id": TENANT_ID,
        "rol": fila.rol, "correo": fila.correo})}


# ── Datos únicos y limpieza ──────────────────────────────────────────────────

def _sufijo() -> str:
    return f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"


def _rut_valido() -> str:
    """RUT chileno válido y único (módulo 11), sin depender de datos de TEST."""
    cuerpo = str(10_000_000 + uuid.uuid4().int % 90_000_000)
    suma, multiplo = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1
    resto = 11 - suma % 11
    dv = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    return f"{cuerpo}-{dv}"


def _borrar_usuario(db, usuario_id: int) -> None:
    """Borra lo que crea un alta, en orden de dependencias (FKs NO ACTION)."""
    db.execute(text(
        "DELETE FROM referidos_aplicados "
        "WHERE usuario_invitado_id = :u OR usuario_invitador_id = :u"),
        {"u": usuario_id})
    for tabla, columna in (("notificaciones", "alumno_id"),
                           ("notificaciones_enviadas", "alumno_id"),
                           ("codigos_referido", "usuario_id"),
                           ("suscripciones", "usuario_id")):
        db.execute(text(f"DELETE FROM {tabla} WHERE {columna} = :u"),
                   {"u": usuario_id})
    db.execute(text("DELETE FROM auditoria WHERE entidad = 'usuario' "
                    "AND entidad_id = :u"), {"u": usuario_id})
    db.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": usuario_id})


@pytest.fixture
def escenario(db):
    """Lista de correos del test; al final borra TODO lo que el alta creó."""
    correos = []
    yield correos

    db.rollback()
    try:
        for correo in correos:
            fila = db.execute(text(
                "SELECT id FROM usuarios WHERE correo = :c AND tenant_id = :t"),
                {"c": correo, "t": TENANT_ID}).first()
            if fila is not None:
                _borrar_usuario(db, int(fila.id))
            # Avisos in-app del alta (el mensaje incluye el correo) y correos.
            db.execute(text("DELETE FROM notificaciones WHERE mensaje LIKE :p"),
                       {"p": f"%{correo}%"})
            db.execute(text("DELETE FROM notificaciones_enviadas "
                            "WHERE destinatario_correo = :c"), {"c": correo})
        db.commit()
    except Exception as error:      # la limpieza no debe tapar el fallo real
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de referidos: {error}")


def _crear_usuario(cliente, admin_headers, escenario, nombre, rol="alumno"):
    """Alta por el endpoint real del admin (le asigna código sólo al alumno)."""
    correo = f"ref.api.{rol}.{_sufijo()}@referidos-test.com"
    escenario.append(correo)
    respuesta = cliente.post(
        BASE_USUARIOS + "/",
        json={
            "rut": _rut_valido(),
            "nombre": nombre,
            "correo": correo,
            "rol": rol,
            "tenant_id": TENANT_ID,
            "password": "Temporal123",
            "estado": "activo",
        },
        headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    return {"id": respuesta.json()["id"], "correo": correo, "rol": rol,
            "nombre": nombre}


def _headers(usuario, tenant_id=TENANT_ID):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": usuario["id"], "tenant_id": tenant_id,
        "rol": usuario["rol"], "correo": usuario["correo"]})}


def _codigo_de(db, usuario_id: int):
    """Fila de `codigos_referido` del alumno (None si no tiene)."""
    db.rollback()
    return db.execute(text(
        "SELECT id, codigo, activo FROM codigos_referido "
        "WHERE usuario_id = :u"), {"u": usuario_id}).first()


def _aplicados_de(db, usuario_invitado_id: int):
    db.rollback()
    return db.execute(text("""
        SELECT ra.id, ra.codigo_referido_id, ra.usuario_invitador_id,
               ra.usuario_invitado_id, ra.estado, ra.fecha_ingreso_codigo,
               ra.descuento_aplicado_invitado, ra.descuento_aplicado_invitador
        FROM referidos_aplicados ra
        WHERE ra.usuario_invitado_id = :u
        ORDER BY ra.id
    """), {"u": usuario_invitado_id}).all()


def _suscripcion_de(db, usuario_id: int):
    """Snapshot de la membresía del invitado (para probar que NO se toca)."""
    db.rollback()
    return db.execute(text("""
        SELECT id, plan_id, estado, creditos_totales, creditos_disponibles,
               fecha_inicio, fecha_expiracion
        FROM suscripciones WHERE usuario_id = :u ORDER BY id
    """), {"u": usuario_id}).all()


# ── 1. Código propio + validación del código de otro alumno ──────────────────

def test_mi_codigo_y_validar_codigo(cliente, db, admin_headers, escenario):
    """Flujo alumno → alumno, de punta a punta, con la app real y la BD TEST."""
    alumno_a = _crear_usuario(cliente, admin_headers, escenario,
                              "Juan Pérez Soto", rol="alumno")
    alumno_b = _crear_usuario(cliente, admin_headers, escenario,
                              "Ana María Ñuñez", rol="alumno")
    coach = _crear_usuario(cliente, admin_headers, escenario,
                           "Carla Rojas", rol="coach")

    fila_a = _codigo_de(db, alumno_a["id"])
    fila_b = _codigo_de(db, alumno_b["id"])
    assert fila_a is not None and fila_b is not None, \
        "el alta del alumno debe crear su código"
    assert _codigo_de(db, coach["id"]) is None, "un coach no recibe código"
    assert fila_a.codigo != fila_b.codigo
    print(f"\n[CODIGOS] A={fila_a.codigo} B={fila_b.codigo}")

    headers_a = _headers(alumno_a)
    headers_b = _headers(alumno_b)

    # ── GET /mi-codigo: el código sale del TOKEN ──
    respuesta = cliente.get(BASE + "/mi-codigo", headers=headers_a)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"codigo", "activo", "fecha_creacion"}
    assert cuerpo["codigo"] == fila_a.codigo
    assert cuerpo["activo"] is True
    assert "usuario_id" not in cuerpo and "id" not in cuerpo
    datetime.fromisoformat(cuerpo["fecha_creacion"].replace("Z", "+00:00"))

    # Otro alumno recibe SU código, no el primero de la tabla.
    cuerpo_b = cliente.get(BASE + "/mi-codigo", headers=headers_b).json()
    assert cuerpo_b["codigo"] == fila_b.codigo
    assert cuerpo_b["codigo"] != cuerpo["codigo"]

    # Sin token y con un rol que no participa.
    assert cliente.get(BASE + "/mi-codigo").status_code == 401
    respuesta = cliente.get(BASE + "/mi-codigo", headers=_headers(coach))
    assert respuesta.status_code == 403, respuesta.text
    assert "alumno" in respuesta.json()["detail"].lower()

    # ── POST /validar-codigo: rechazos ──
    respuesta = cliente.post(BASE + "/validar-codigo",
                             json={"codigo": "NOEXISTE999"},
                             headers=headers_b)
    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"] == svc.MOTIVO_CODIGO_INEXISTENTE

    # Código real pero apagado por el admin.
    db.execute(text("UPDATE codigos_referido SET activo = false WHERE id = :i"),
               {"i": fila_a.id})
    db.commit()
    respuesta = cliente.post(BASE + "/validar-codigo",
                             json={"codigo": fila_a.codigo},
                             headers=headers_b)
    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"] == svc.MOTIVO_CODIGO_INACTIVO
    assert cliente.get(BASE + "/mi-codigo",
                       headers=headers_a).json()["activo"] is False

    db.execute(text("UPDATE codigos_referido SET activo = true WHERE id = :i"),
               {"i": fila_a.id})
    db.commit()

    # Auto-referido: con minúsculas y espacios, que se normaliza igual.
    respuesta = cliente.post(
        BASE + "/validar-codigo",
        json={"codigo": f"  {fila_b.codigo.lower()}  "}, headers=headers_b)
    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"] == svc.MOTIVO_CODIGO_PROPIO

    respuesta = cliente.post(BASE + "/validar-codigo",
                             json={"codigo": fila_a.codigo},
                             headers=headers_a)
    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"] == svc.MOTIVO_CODIGO_PROPIO

    # Contrato del body: no se acepta `usuario_id` (el invitado es el del JWT).
    respuesta = cliente.post(
        BASE + "/validar-codigo",
        json={"codigo": fila_b.codigo, "usuario_id": alumno_b["id"]},
        headers=headers_a)
    assert respuesta.status_code == 422, respuesta.text
    assert cliente.post(BASE + "/validar-codigo", json={},
                        headers=headers_a).status_code == 422
    respuesta = cliente.post(BASE + "/validar-codigo",
                             json={"codigo": fila_a.codigo},
                             headers=_headers(coach))
    assert respuesta.status_code == 403, respuesta.text
    assert cliente.post(BASE + "/validar-codigo",
                        json={"codigo": fila_a.codigo}).status_code == 401

    assert _aplicados_de(db, alumno_b["id"]) == [], \
        "ningún rechazo debe dejar fila en referidos_aplicados"

    # ── POST /validar-codigo: camino válido ──
    suscripcion_antes = [tuple(f) for f in _suscripcion_de(db, alumno_b["id"])]
    respuesta = cliente.post(
        BASE + "/validar-codigo",
        json={"codigo": f"  {fila_a.codigo.lower()}  "}, headers=headers_b)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"valido", "codigo", "referido_id", "estado",
                           "mensaje"}
    assert cuerpo["valido"] is True
    assert cuerpo["codigo"] == fila_a.codigo, "responde el código normalizado"
    assert cuerpo["estado"] == "pendiente"
    assert cuerpo["mensaje"] == svc.MENSAJE_REFERIDO_REGISTRADO
    assert isinstance(cuerpo["referido_id"], int)

    filas = _aplicados_de(db, alumno_b["id"])
    assert len(filas) == 1, "la validación válida crea EXACTAMENTE una fila"
    aplicado = filas[0]
    assert aplicado.id == cuerpo["referido_id"]
    assert aplicado.codigo_referido_id == fila_a.id
    assert aplicado.usuario_invitador_id == alumno_a["id"]
    assert aplicado.usuario_invitado_id == alumno_b["id"]
    assert getattr(aplicado.estado, "value", aplicado.estado) == "pendiente"
    assert aplicado.fecha_ingreso_codigo is not None

    # FASE 3a NO aplica descuentos: la fila nace sin montos y la membresía del
    # invitado queda intacta (no se cobra, no se rebaja, no se regala nada).
    assert aplicado.descuento_aplicado_invitado is None
    assert aplicado.descuento_aplicado_invitador is None
    assert [tuple(f) for f in _suscripcion_de(db, alumno_b["id"])] == \
        suscripcion_antes, "validar el código no debe tocar la suscripción"

    # Sólo se puede ser referido UNA vez (aunque siga `pendiente`).
    respuesta = cliente.post(BASE + "/validar-codigo",
                             json={"codigo": fila_a.codigo},
                             headers=headers_b)
    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"] == svc.MOTIVO_YA_REFERIDO
    assert len(_aplicados_de(db, alumno_b["id"])) == 1, \
        "el segundo intento no debe duplicar la fila"

    # ── Alumno histórico sin código (backfill pendiente) ──
    # Sin fila en `codigos_referido`, `mi-codigo` responde 404 con un mensaje
    # claro; nunca inventa un código ni devuelve un 500.
    sin_codigo = _crear_usuario(cliente, admin_headers, escenario,
                                "Pedro Antiguo", rol="alumno")
    db.execute(text("DELETE FROM codigos_referido WHERE usuario_id = :u"),
               {"u": sin_codigo["id"]})
    db.commit()
    respuesta = cliente.get(BASE + "/mi-codigo", headers=_headers(sin_codigo))
    assert respuesta.status_code == 404, respuesta.text
    assert "No tienes un código de referido" in respuesta.json()["detail"]


# ── 2. Configuración del box: sólo admin, defaults sin crear y upsert ────────

def test_configuracion_solo_admin_y_upsert(cliente, db, admin_headers,
                                           escenario):
    alumno = _crear_usuario(cliente, admin_headers, escenario,
                            "Diego Fuentes", rol="alumno")
    ruta = BASE + "/configuracion"
    datos_validos = {"porcentaje_descuento_invitado": 5.5,
                     "porcentaje_descuento_invitador": 10,
                     "activo": True}

    # ── Permisos ──
    assert cliente.get(ruta).status_code == 401
    respuesta = cliente.get(ruta, headers=_headers(alumno))
    assert respuesta.status_code == 403, respuesta.text
    assert "administrador" in respuesta.json()["detail"].lower()
    respuesta = cliente.put(ruta, json=datos_validos,
                            headers=_headers(alumno))
    assert respuesta.status_code == 403, respuesta.text

    # ── Estado original del box 1 (se restaura pase lo que pase) ──
    db.rollback()
    original = db.execute(text(
        "SELECT id, porcentaje_descuento_invitado, "
        "porcentaje_descuento_invitador, activo "
        "FROM configuracion_referidos WHERE tenant_id = :t"),
        {"t": TENANT_ID}).first()
    db.execute(text(
        "DELETE FROM configuracion_referidos WHERE tenant_id = :t"),
        {"t": TENANT_ID})
    db.commit()

    def _config_actual():
        db.rollback()
        return db.execute(text(
            "SELECT id, porcentaje_descuento_invitado, "
            "porcentaje_descuento_invitador, activo "
            "FROM configuracion_referidos WHERE tenant_id = :t"),
            {"t": TENANT_ID}).first()

    try:
        # GET sin fila: defaults y NINGUNA escritura.
        respuesta = cliente.get(ruta, headers=admin_headers)
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json() == {
            "porcentaje_descuento_invitado": 0.0,
            "porcentaje_descuento_invitador": 0.0,
            "activo": False,
            "configurada": False,
        }
        assert _config_actual() is None, "GET no debe crear la configuración"

        # PUT: crea la fila.
        respuesta = cliente.put(ruta, json=datos_validos, headers=admin_headers)
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json() == {
            "porcentaje_descuento_invitado": 5.5,
            "porcentaje_descuento_invitador": 10.0,
            "activo": True,
            "configurada": True,
        }
        creada = _config_actual()
        assert creada is not None
        assert float(creada.porcentaje_descuento_invitado) == 5.5
        assert float(creada.porcentaje_descuento_invitador) == 10.0
        assert creada.activo is True

        # GET posterior devuelve lo guardado.
        assert cliente.get(ruta, headers=admin_headers).json() == \
            respuesta.json()

        # Segundo PUT: actualiza la MISMA fila (upsert, no duplica).
        respuesta = cliente.put(
            ruta,
            json={"porcentaje_descuento_invitado": "0.00",
                  "porcentaje_descuento_invitador": 100,
                  "activo": False},
            headers=admin_headers)
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json() == {
            "porcentaje_descuento_invitado": 0.0,
            "porcentaje_descuento_invitador": 100.0,
            "activo": False,
            "configurada": True,
        }
        actualizada = _config_actual()
        assert actualizada.id == creada.id, "el upsert no debe crear otra fila"
        assert float(actualizada.porcentaje_descuento_invitador) == 100.0
        assert actualizada.activo is False
        assert db.execute(text(
            "SELECT count(*) FROM configuracion_referidos WHERE tenant_id = :t"),
            {"t": TENANT_ID}).scalar() == 1

        # Fuera de rango / demasiados decimales / falta `activo`: 422 y sin
        # cambios en la BD (Pydantic valida antes del UPDATE).
        for invalido in (
            {"porcentaje_descuento_invitado": -0.01,
             "porcentaje_descuento_invitador": 10, "activo": True},
            {"porcentaje_descuento_invitado": 10,
             "porcentaje_descuento_invitador": 100.01, "activo": True},
            {"porcentaje_descuento_invitado": "1.234",
             "porcentaje_descuento_invitador": 10, "activo": True},
            {"porcentaje_descuento_invitado": 10,
             "porcentaje_descuento_invitador": 10},
        ):
            respuesta = cliente.put(ruta, json=invalido,
                                    headers=admin_headers)
            assert respuesta.status_code == 422, respuesta.text

        sin_cambios = _config_actual()
        assert sin_cambios.id == creada.id
        assert float(sin_cambios.porcentaje_descuento_invitado) == 0.0
        assert float(sin_cambios.porcentaje_descuento_invitador) == 100.0
        assert sin_cambios.activo is False
    finally:
        db.rollback()
        db.execute(text(
            "DELETE FROM configuracion_referidos WHERE tenant_id = :t"),
            {"t": TENANT_ID})
        if original is not None:
            db.execute(text("""
                INSERT INTO configuracion_referidos
                    (id, tenant_id, porcentaje_descuento_invitado,
                     porcentaje_descuento_invitador, activo)
                VALUES (:id, :t, :invitado, :invitador, :activo)
            """), {"id": original.id, "t": TENANT_ID,
                   "invitado": original.porcentaje_descuento_invitado,
                   "invitador": original.porcentaje_descuento_invitador,
                   "activo": original.activo})
        db.commit()

