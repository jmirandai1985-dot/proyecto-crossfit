"""
Tramos del invitador (Parte C) — integración contra la rama TEST.

Qué cubre, con la app real (TestClient) y la rama TEST:

  1. Un ciclo cerrado con 3 referidos y escalera 1/2/3 crea **UNA** fila, la
     del tramo 3 (exclusividad). Correr la evaluación otra vez no duplica.
  2. Confirmar `mes_gratis` extiende la suscripción vigente 30 días y una
     segunda confirmación responde 409.
  3. Confirmar SIN plan vigente deja el premio `confirmado` + `aplicado_en NULL`
     (no 409) y el job lo aplica cuando el alumno contrata un plan.
  4. Confirmar `descuento_extra` crea UN crédito pendiente ligado al premio. Los
     créditos NO se suman: cada uno se consume en una compra distinta.
  5. El motor es ÚNICO: con `motor_premios='tramos'` la detección por mes
     calendario (Fase 5) no evalúa ese box; al volver a `'promociones'`, sí.
  6. `GET /referidos/mi-progreso` muestra el ciclo EN CURSO del alumno con su
     escalón alcanzado y cuánto le falta.
  7. Seguridad: 401 sin token y 403 para un alumno en los endpoints de admin.

Se escribe y se BORRA en TEST (nunca PROD). La configuración del box (incluido
`motor_premios`) se RESTAURA aunque un test falle y `EMAIL_MODO=noop` evita
mandar correo real (el intento queda en `notificaciones_enviadas`).

    cd backend && py -3.12 -m pytest tests/test_tramos_referidos_integracion.py -q -s
"""
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_test_db_url, settings                    # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.services import promociones_referidos_service as promos_svc    # noqa: E402
from app.services import referidos_service as ref_svc                  # noqa: E402
from app.services import tramos_referidos_service as tramos_svc        # noqa: E402
from app.utils.santiago import (fin_de_plan_chile, fecha_chile,        # noqa: E402
                               hoy_santiago, inicio_del_dia_chile)

TENANT_ID = 1
BASE = "/api/v1/referidos"
BASE_USUARIOS = "/api/v1/usuarios"
PREFIJO_CORREO = "tramo.ref.%@tramos-test.com"
PREFIJO_PROMO = "Promo tramos TEST%"
TIPO_NOTIFICACION = tramos_svc.TIPO_NOTIFICACION


@pytest.fixture(autouse=True)
def _sin_correo_real(monkeypatch):
    """La evaluación/confirmación no manda SMTP: registra el intento simulado."""
    from app.services import email_service

    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)


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


@pytest.fixture(scope="module")
def admin_headers(db, box):
    """Token REAL del admin del box de prueba (mismo camino que el navegador)."""
    fila = db.execute(text(
        "SELECT id, correo, rol FROM usuarios WHERE tenant_id = :t "
        "AND rol = 'administrador' AND estado = 'activo' "
        "ORDER BY id LIMIT 1"), {"t": box["tenant_id"]}).first()
    if fila is None:
        pytest.skip("el box de prueba no tiene administrador")
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": int(fila.id), "tenant_id": box["tenant_id"],
        "rol": fila.rol, "correo": fila.correo})}


@pytest.fixture(scope="module", autouse=True)
def box(db):
    """Box de prueba PROPIO (tenant nuevo): aislamiento total y cero residuo.

    La escalera, el motor y los premios viven en un tenant que sólo existe
    durante el módulo: no se apaga ni se toca la configuración del box 1 (el
    real de TEST) y el `DELETE FROM tenants` final se lleva todo por CASCADE.
    Además, un tramo de otro box no puede evaluarse ni confirmarse por error.
    """
    global TENANT_ID

    db.rollback()
    # Residuo de una corrida cortada (el box de prueba siempre se llama igual).
    for (tenant_viejo,) in db.execute(text(
            "SELECT id FROM tenants WHERE nombre LIKE 'Tramos TEST%'")).fetchall():
        _borrar_tenant(db, int(tenant_viejo))
    db.commit()

    tenant_id = db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo)
        VALUES (:n, :s, :p, true) RETURNING id"""),
        {"n": f"Tramos TEST {_sufijo()}",
         "s": f"tramos-test-{uuid.uuid4().hex[:10]}",
         "p": str(uuid.uuid4())}).scalar()
    db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                              rol, activo, estado)
        VALUES (:t, :r, 'Admin Tramos', :c, 'test', 'administrador',
                true, 'activo')"""),
        {"t": tenant_id, "r": _rut_valido(),
         "c": f"tramo.ref.admin.{_sufijo()}@tramos-test.com"})
    db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, precio_clp, duracion_dias,
                            es_ilimitado, es_comercial, activo)
        VALUES (:t, 'Plan Tramos TEST', 50000, 30, false, true, true)"""),
        {"t": tenant_id})
    db.commit()

    anterior = TENANT_ID
    TENANT_ID = int(tenant_id)
    print(f"\n[OK] box de prueba creado en TEST: tenant {tenant_id}\n")
    try:
        yield {"tenant_id": int(tenant_id)}
    finally:
        TENANT_ID = anterior
        db.rollback()
        try:
            db.execute(text("DELETE FROM notificaciones WHERE tipo = :t"),
                       {"t": TIPO_NOTIFICACION})
            _borrar_tenant(db, int(tenant_id))
            db.commit()
        except Exception as error:  # pragma: no cover - aviso, no falla
            db.rollback()
            print(f"\n[WARN] no se pudo borrar el box de prueba: {error}")


def _borrar_tenant(db, tenant_id: int) -> None:
    """Borra el box de prueba sin chocar con las FK que no son CASCADE.

    `notificaciones_enviadas.tenant_id` es RESTRICT (es el log de correos), así
    que se limpia ANTES del `DELETE FROM tenants`; el resto cae por CASCADE.
    """
    db.execute(text("DELETE FROM notificaciones_enviadas WHERE tenant_id = :t"),
               {"t": tenant_id})
    db.execute(text("DELETE FROM notificaciones WHERE tipo = :t"),
               {"t": TIPO_NOTIFICACION})
    db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})



# ── Datos únicos, altas y limpieza ──────────────────────────────────────────

# Premios creados por la EVALUACIÓN en este módulo (incluidos los de ciclos
# ajenos que el barrido de TEST encuentre): se borran al terminar.
PREMIOS_EVALUADOS: set[int] = set()


def _sufijo() -> str:
    return f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"


def _rut_valido() -> str:
    cuerpo = str(10_000_000 + uuid.uuid4().int % 90_000_000)
    suma, multiplo = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1
    resto = 11 - suma % 11
    dv = "0" if resto == 11 else ("K" if resto == 10 else str(resto))
    return f"{cuerpo}-{dv}"


def _borrar_usuario(db, usuario_id: int) -> None:
    """Borra lo que el flujo pudo crear para ese usuario (orden de FKs)."""
    for consulta in (
        "DELETE FROM premios_tramo_ciclo WHERE usuario_id = :u "
        "OR confirmado_por_usuario_id = :u",
        "DELETE FROM creditos_referido WHERE usuario_id = :u",
        "DELETE FROM referidos_aplicados WHERE usuario_invitador_id = :u "
        "OR usuario_invitado_id = :u",
        "DELETE FROM invitaciones WHERE enviado_por_usuario_id = :u "
        "OR usuario_registrado_id = :u",
        "DELETE FROM suscripciones WHERE usuario_id = :u",
        "DELETE FROM auditoria WHERE entidad = 'usuario' AND entidad_id = :u",
    ):
        db.execute(text(consulta), {"u": usuario_id})
    db.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": usuario_id})


@pytest.fixture
def escenario(db):
    """Datos del test; se borran SIEMPRE al final (aunque falle)."""
    datos = {"usuarios": [], "promos": []}
    yield datos

    db.rollback()
    try:
        for usuario_id in datos["usuarios"]:
            _borrar_usuario(db, usuario_id)
        for promocion_id in datos["promos"]:
            db.execute(text("DELETE FROM promociones_referidos WHERE id = :p"),
                       {"p": promocion_id})
        db.commit()
    except Exception as error:  # pragma: no cover - aviso, no falla el test
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario: {error}")


# ── Fixtures de la escalera y del motor ────────────────────────────────────

@pytest.fixture
def escalera(cliente, admin_headers):
    """Escalera 1 → 10 %, 2 → 20 %, 3 → mes gratis; se borra al terminar."""
    tramos = [
        _crear_tramo(cliente, admin_headers, umbral=1,
                     tipo="descuento_extra", valor=10),
        _crear_tramo(cliente, admin_headers, umbral=2,
                     tipo="descuento_extra", valor=20),
        _crear_tramo(cliente, admin_headers, umbral=3, tipo="mes_gratis"),
    ]
    yield tramos

    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        for tramo in tramos:
            tramo_id = int(tramo["id"])
            db.execute(text("DELETE FROM premios_tramo_ciclo "
                            "WHERE tramo_id = :x"), {"x": tramo_id})
            db.execute(text("DELETE FROM tramos_referido WHERE id = :x"),
                       {"x": tramo_id})
        db.commit()
    finally:
        db.close()


@pytest.fixture
def motor_tramos(cliente, admin_headers):
    """Enciende el motor de tramos y lo devuelve a 'promociones' al terminar."""
    respuesta = cliente.put(BASE + "/tramos/motor",
                            json={"motor_premios": "tramos"},
                            headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    yield "tramos"
    cliente.put(BASE + "/tramos/motor",
                json={"motor_premios": "promociones"}, headers=admin_headers)


@pytest.fixture
def motor_promociones(cliente, admin_headers):
    """Deja el motor en 'promociones' (Fase 5) durante el test."""
    respuesta = cliente.put(BASE + "/tramos/motor",
                            json={"motor_premios": "promociones"},
                            headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    yield "promociones"


# ── Helpers de datos ───────────────────────────────────────────────────────

def _crear_tramo(cliente, admin_headers, *, umbral, tipo, valor=None,
                 activo=True):
    respuesta = cliente.post(
        BASE + "/tramos",
        json={"umbral_referidos": umbral, "tipo_premio": tipo,
              "valor_premio": valor, "activo": activo},
        headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _crear_alumno(cliente, admin_headers, escenario, nombre="Alumno Tramos"):
    """Alta por el endpoint real: le asigna su `codigo_referido`."""
    correo = f"tramo.ref.alumno.{_sufijo()}@tramos-test.com"
    respuesta = cliente.post(
        BASE_USUARIOS + "/",
        json={
            "rut": _rut_valido(), "nombre": nombre, "correo": correo,
            "rol": "alumno", "tenant_id": TENANT_ID,
            "password": "Temporal123", "estado": "activo",
        },
        headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    usuario_id = int(respuesta.json()["id"])
    escenario["usuarios"].append(usuario_id)
    return {"id": usuario_id, "correo": correo, "nombre": nombre,
            "rol": "alumno"}


def _headers(usuario):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": usuario["id"], "tenant_id": TENANT_ID,
        "rol": usuario["rol"], "correo": usuario["correo"]})}


def _plan_id(db) -> int:
    plan_id = db.execute(text(
        "SELECT id FROM planes WHERE tenant_id = :t ORDER BY id LIMIT 1"),
        {"t": TENANT_ID}).scalar()
    assert plan_id is not None, "TEST no tiene planes en el box 1"
    return int(plan_id)


def _crear_suscripcion(db, usuario_id, *, inicio: date, fin: date,
                       estado="activo") -> int:
    """Suscripción directa con la ventana del ciclo que pide el test."""
    suscripcion_id = db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                   fecha_inicio, fecha_expiracion,
                                   es_compra_emergencia, puede_comprar_emergencia)
        VALUES (:t, :u, :p, :e, :i, :f, false, true)
        RETURNING id"""),
        {"t": TENANT_ID, "u": usuario_id, "p": _plan_id(db), "e": estado,
         "i": inicio_del_dia_chile(inicio),
         "f": fin_de_plan_chile(inicio, (fin - inicio).days)}).scalar()
    db.commit()
    return int(suscripcion_id)


def _crear_premio(db, usuario_id, *, tramo_id=None, suscripcion_id=None,
                  umbral=1, tipo="mes_gratis", valor=None,
                  convertidos=1, inicio=None, fin=None,
                  estado="pendiente_confirmacion") -> int:
    """Premio ya detectado (lo que el job habría escrito) para probar la cola."""
    inicio = inicio or (hoy_santiago() - timedelta(days=40))
    fin = fin or (hoy_santiago() - timedelta(days=10))
    premio_id = db.execute(text("""
        INSERT INTO premios_tramo_ciclo (
            tenant_id, usuario_id, tramo_id, suscripcion_id, ciclo_inicio,
            ciclo_fin, referidos_convertidos, umbral_referidos, tipo_premio,
            valor_premio, estado)
        VALUES (:t, :u, :tramo, :s, :i, :f, :c, :umbral, :tipo, :valor, :estado)
        RETURNING id"""),
        {"t": TENANT_ID, "u": usuario_id, "tramo": tramo_id,
         "s": suscripcion_id, "i": inicio, "f": fin, "c": convertidos,
         "umbral": umbral, "tipo": tipo, "valor": valor,
         "estado": estado}).scalar()
    db.commit()
    return int(premio_id)


def _codigo_de(db, usuario_id: int):
    fila = db.execute(text(
        "SELECT id, codigo FROM codigos_referido WHERE usuario_id = :u"),
        {"u": usuario_id}).first()
    if fila is not None:
        return fila
    return db.execute(text(
        "INSERT INTO codigos_referido (usuario_id, codigo) "
        "VALUES (:u, :c) RETURNING id, codigo"),
        {"u": usuario_id,
         "c": f"TR{uuid.uuid4().hex[:8].upper()}"}).first()


def _crear_referidos_convertidos(db, escenario, invitador_id, cuantos, momento):
    """N aplicaciones YA convertidas del invitador (dato del ciclo)."""
    codigo = _codigo_de(db, invitador_id)
    for indice in range(cuantos):
        invitado_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                                  rol, activo, estado)
            VALUES (:t, :r, :n, :c, 'test', 'alumno', true, 'activo')
            RETURNING id"""),
            {"t": TENANT_ID, "r": _rut_valido(),
             "n": f"Invitado tramo {indice}",
             "c": f"tramo.ref.invitado.{_sufijo()}@tramos-test.com"}).scalar()
        escenario["usuarios"].append(int(invitado_id))
        db.execute(text("""
            INSERT INTO referidos_aplicados (
                codigo_referido_id, usuario_invitador_id, usuario_invitado_id,
                fecha_ingreso_codigo, estado, fecha_conversion)
            VALUES (:codigo, :invitador, :invitado, :momento,
                    'convertido', :momento)"""),
            {"codigo": codigo.id, "invitador": invitador_id,
             "invitado": int(invitado_id), "momento": momento})
    db.commit()


def _evaluar(db):
    """Corre la evaluación y registra los premios para la limpieza del módulo."""
    nuevos = tramos_svc.evaluar_ciclos(
        db, tenant_id=TENANT_ID, ahora=datetime.now(timezone.utc),
        dias_atras=120)
    db.commit()
    for premio in nuevos:
        PREMIOS_EVALUADOS.add(int(premio["premio_id"]))
    return nuevos


# ── 1. Evaluación al cierre del ciclo ──────────────────────────────────────

def test_ciclo_cerrado_paga_solo_el_tramo_mas_alto(
        cliente, admin_headers, db, escenario, escalera, motor_tramos):
    """3 referidos en un ciclo cerrado = UNA fila, la del tramo 3."""
    alumno = _crear_alumno(cliente, admin_headers, escenario)
    inicio = hoy_santiago() - timedelta(days=40)
    fin = hoy_santiago() - timedelta(days=10)
    _crear_suscripcion(db, alumno["id"], inicio=inicio, fin=fin)
    _crear_referidos_convertidos(
        db, escenario, alumno["id"], 3,
        momento=inicio_del_dia_chile(inicio + timedelta(days=5)))

    nuevos = [premio for premio in _evaluar(db)
              if premio["usuario_id"] == alumno["id"]]

    assert len(nuevos) == 1, nuevos
    assert nuevos[0]["umbral_referidos"] == 3
    assert nuevos[0]["referidos_convertidos"] == 3
    assert nuevos[0]["tipo_premio"] == "mes_gratis"

    # Correr la evaluación otra vez NO duplica (idempotente).
    otra = [premio for premio in _evaluar(db)
            if premio["usuario_id"] == alumno["id"]]
    assert otra == []

    # La cola del admin lo ve pendiente y sin aplicar.
    respuesta = cliente.get(BASE + "/tramos/premios", headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    fila = next(f for f in respuesta.json()
                if f["id"] == nuevos[0]["premio_id"])
    assert fila["estado"] == "pendiente_confirmacion"
    assert fila["pendiente_de_aplicar"] is False
    assert fila["ciclo_fin"] == fin.isoformat()


# ── 2. Confirmar mes gratis: extiende la suscripción vigente ───────────────

def test_confirmar_mes_gratis_extiende_la_suscripcion_una_sola_vez(
        cliente, admin_headers, db, escenario, escalera):
    alumno = _crear_alumno(cliente, admin_headers, escenario)
    suscripcion_id = _crear_suscripcion(
        db, alumno["id"], inicio=hoy_santiago() - timedelta(days=5),
        fin=hoy_santiago() + timedelta(days=25))
    premio_id = _crear_premio(
        db, alumno["id"], tramo_id=escalera[2]["id"],
        suscripcion_id=suscripcion_id, umbral=3, tipo="mes_gratis",
        convertidos=3)

    antes = db.execute(text(
        "SELECT fecha_expiracion FROM suscripciones WHERE id = :s"),
        {"s": suscripcion_id}).scalar()

    respuesta = cliente.post(
        BASE + f"/tramos/premios/{premio_id}/confirmar", headers=admin_headers)

    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert datos["status"] == "confirmado"
    assert datos["dias_extendidos"] == 30
    assert datos["pendiente_de_aplicar"] is False
    assert datos["suscripcion_id"] == suscripcion_id

    despues = db.execute(text(
        "SELECT fecha_expiracion FROM suscripciones WHERE id = :s"),
        {"s": suscripcion_id}).scalar()
    assert fecha_chile(despues) == fecha_chile(antes) + timedelta(days=30)

    # El premio se aplica UNA sola vez.
    repetida = cliente.post(
        BASE + f"/tramos/premios/{premio_id}/confirmar", headers=admin_headers)
    assert repetida.status_code == 409


# ── 3. Premio sin plan vigente: no se pierde ───────────────────────────────

def test_confirmar_sin_plan_vigente_queda_pendiente_y_se_aplica_despues(
        cliente, admin_headers, db, escenario, escalera):
    alumno = _crear_alumno(cliente, admin_headers, escenario)
    # El alta crea el plan de Prueba: se vence para probar "alumno entre planes".
    db.execute(text("UPDATE suscripciones SET fecha_expiracion = :f "
                    "WHERE usuario_id = :u"),
               {"u": alumno["id"],
                "f": inicio_del_dia_chile(hoy_santiago() - timedelta(days=2))})
    db.commit()
    premio_id = _crear_premio(
        db, alumno["id"], tramo_id=escalera[1]["id"], umbral=2,
        tipo="dias_gratis", valor=7, convertidos=2)

    respuesta = cliente.post(
        BASE + f"/tramos/premios/{premio_id}/confirmar", headers=admin_headers)

    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert datos["status"] == "confirmado"
    assert datos["pendiente_de_aplicar"] is True
    assert datos["suscripcion_id"] is None
    assert datos["dias_extendidos"] == 7

    fila = db.execute(text(
        "SELECT estado, aplicado_en FROM premios_tramo_ciclo WHERE id = :p"),
        {"p": premio_id}).first()
    assert str(fila.estado) == "confirmado"
    assert fila.aplicado_en is None

    # Contrata un plan: el job diario aplica el premio solo.
    suscripcion_id = _crear_suscripcion(
        db, alumno["id"], inicio=hoy_santiago() - timedelta(days=1),
        fin=hoy_santiago() + timedelta(days=29))
    antes = db.execute(text(
        "SELECT fecha_expiracion FROM suscripciones WHERE id = :s"),
        {"s": suscripcion_id}).scalar()

    resultado = tramos_svc.aplicar_pendientes(db, tenant_id=TENANT_ID)
    db.commit()

    assert any(aplicado["premio_id"] == premio_id
               for aplicado in resultado["aplicados"]), resultado
    despues = db.execute(text(
        "SELECT fecha_expiracion FROM suscripciones WHERE id = :s"),
        {"s": suscripcion_id}).scalar()
    assert fecha_chile(despues) == fecha_chile(antes) + timedelta(days=7)
    aplicado_en = db.execute(text(
        "SELECT aplicado_en FROM premios_tramo_ciclo WHERE id = :p"),
        {"p": premio_id}).scalar()
    assert aplicado_en is not None


# ── 4. descuento_extra: créditos INDEPENDIENTES (no se suman) ──────────────

def test_descuento_extra_crea_creditos_independientes_que_no_se_suman(
        cliente, admin_headers, db, escenario, escalera):
    """Dos premios de 15 % = DOS créditos de 15 %, no uno de 30 %."""
    alumno = _crear_alumno(cliente, admin_headers, escenario)
    vieja = _crear_suscripcion(
        db, alumno["id"], inicio=hoy_santiago() - timedelta(days=70),
        fin=hoy_santiago() - timedelta(days=40), estado="vencido")
    actual = _crear_suscripcion(
        db, alumno["id"], inicio=hoy_santiago() - timedelta(days=35),
        fin=hoy_santiago() - timedelta(days=5), estado="activo")

    premios = [
        _crear_premio(db, alumno["id"], tramo_id=escalera[0]["id"],
                      suscripcion_id=vieja, umbral=1,
                      tipo="descuento_extra", valor=15),
        _crear_premio(db, alumno["id"], tramo_id=escalera[0]["id"],
                      suscripcion_id=actual, umbral=1,
                      tipo="descuento_extra", valor=15),
    ]
    creditos = []
    for premio_id in premios:
        respuesta = cliente.post(
            BASE + f"/tramos/premios/{premio_id}/confirmar",
            headers=admin_headers)
        assert respuesta.status_code == 200, respuesta.text
        datos = respuesta.json()
        assert datos["porcentaje"] == 15.0
        assert datos["pendiente_de_aplicar"] is False
        creditos.append(datos["credito_referido_id"])

    assert len(set(creditos)) == 2
    filas = db.execute(text(
        "SELECT id, porcentaje, estado, premio_tramo_ciclo_id "
        "FROM creditos_referido WHERE usuario_id = :u ORDER BY id"),
        {"u": alumno["id"]}).fetchall()
    assert len(filas) == 2
    assert all(float(fila.porcentaje) == 15.0 for fila in filas)
    assert all(str(fila.estado) == "pendiente" for fila in filas)
    # Cada crédito conserva SU premio de origen (uno por ciclo).
    assert {int(fila.premio_tramo_ciclo_id) for fila in filas} == set(premios)

    # El consumo toma UN crédito por compra: no hay suma de porcentajes.
    pendiente = ref_svc._credito_pendiente(
        db, tenant_id=TENANT_ID, usuario_id=alumno["id"], bloquear=False)
    assert pendiente is not None
    assert float(pendiente.porcentaje) == 15.0


# ── 5. Motor único: tramos apaga la detección por mes calendario ───────────

def test_motor_tramos_apaga_la_deteccion_por_mes_calendario(
        cliente, admin_headers, db, escenario, escalera):
    respuesta = cliente.post(
        BASE + "/promociones",
        json={"nombre": f"{PREFIJO_PROMO} motor {_sufijo()}",
              "umbral_referidos_convertidos": 1, "periodo": "mensual",
              "tipo_premio": "descuento_extra", "valor_premio": 5,
              "activo": True},
        headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    promocion_id = int(respuesta.json()["id"])
    escenario["promos"].append(promocion_id)

    alumno = _crear_alumno(cliente, admin_headers, escenario)
    _crear_referidos_convertidos(
        db, escenario, alumno["id"], 1,
        momento=datetime.now(timezone.utc) - timedelta(days=1))

    try:
        # Motor tramos: la Fase 5 no evalúa este box (ni esta promoción).
        cambio = cliente.put(BASE + "/tramos/motor",
                             json={"motor_premios": "tramos"},
                             headers=admin_headers)
        assert cambio.status_code == 200, cambio.text
        nuevas = promos_svc.detectar_promociones(db, tenant_id=TENANT_ID)
        db.rollback()
        assert not any(deteccion["promocion_id"] == promocion_id
                       for deteccion in nuevas), nuevas

        # Motor promociones: vuelve a detectar (el flag es el interruptor).
        cambio = cliente.put(BASE + "/tramos/motor",
                             json={"motor_premios": "promociones"},
                             headers=admin_headers)
        assert cambio.status_code == 200, cambio.text
        nuevas = promos_svc.detectar_promociones(db, tenant_id=TENANT_ID)
        db.rollback()
        assert any(deteccion["promocion_id"] == promocion_id
                   for deteccion in nuevas), nuevas
    finally:
        cliente.put(BASE + "/tramos/motor",
                    json={"motor_premios": "promociones"},
                    headers=admin_headers)


# ── 6. Progreso del alumno ─────────────────────────────────────────────────

def test_mi_progreso_muestra_el_ciclo_en_curso(
        cliente, admin_headers, db, escenario, escalera, motor_tramos):
    alumno = _crear_alumno(cliente, admin_headers, escenario)
    inicio = hoy_santiago() - timedelta(days=10)
    _crear_suscripcion(db, alumno["id"], inicio=inicio,
                       fin=hoy_santiago() + timedelta(days=20))
    _crear_referidos_convertidos(
        db, escenario, alumno["id"], 2,
        momento=datetime.now(timezone.utc) - timedelta(days=2))

    respuesta = cliente.get(BASE + "/mi-progreso", headers=_headers(alumno))

    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert datos["motor"] == "tramos"
    assert datos["ciclo"] is not None
    assert datos["ciclo"]["inicio"] == inicio.isoformat()
    assert datos["referidos_convertidos"] == 2
    assert datos["tramo_alcanzado"]["umbral_referidos"] == 2
    assert datos["siguiente_tramo"]["umbral_referidos"] == 3
    assert datos["faltan_para_siguiente"] == 1
    assert [paso["umbral_referidos"] for paso in datos["escalera"]] == [1, 2, 3]


# ── 7. Publicación de la escalera en el carrusel ───────────────────────────

def test_publicar_escalera_muestra_toda_la_escalera(
        cliente, admin_headers, escalera):
    hoy = hoy_santiago()
    cuerpo = {"titulo": "Invita y gana", "texto": "Trae amigos al box",
              "vigente_desde": hoy.isoformat(),
              "vigente_hasta": (hoy + timedelta(days=30)).isoformat(),
              "fijado_arriba": False}
    try:
        respuesta = cliente.post(BASE + "/tramos/publicar", json=cuerpo,
                                 headers=admin_headers)
        assert respuesta.status_code == 200, respuesta.text
        datos = respuesta.json()
        assert datos["escalera_tramos"] is True
        # Decisión 4: la tarjeta anuncia la escalera COMPLETA, no un genérico.
        for paso in ("1 referido", "2 referidos", "3 referidos"):
            assert paso in datos["texto"], datos["texto"]
        assert "Trae amigos al box" in datos["texto"]

        # Republicar EDITA la misma tarjeta (una sola por box).
        otra = cliente.post(BASE + "/tramos/publicar", json=cuerpo,
                            headers=admin_headers)
        assert otra.status_code == 200, otra.text
        assert otra.json()["id"] == datos["id"]
    finally:
        cliente.delete(BASE + "/tramos/publicar", headers=admin_headers)


# ── 8. Seguridad ───────────────────────────────────────────────────────────

def test_endpoints_de_tramos_exigen_admin(cliente, admin_headers, escenario,
                                          escalera):
    assert cliente.get(BASE + "/tramos").status_code == 401

    alumno = _crear_alumno(cliente, admin_headers, escenario)
    headers_alumno = _headers(alumno)
    assert cliente.get(BASE + "/tramos",
                       headers=headers_alumno).status_code == 403
    assert cliente.get(BASE + "/tramos/premios",
                       headers=headers_alumno).status_code == 403
    assert cliente.post(BASE + "/tramos/premios/999999/confirmar",
                        headers=headers_alumno).status_code == 403
    assert cliente.get(BASE + "/mi-progreso",
                       headers=admin_headers).status_code == 403

    # Un premio inexistente con token de admin es 404 (no 500).
    assert cliente.post(BASE + "/tramos/premios/999999/confirmar",
                        headers=admin_headers).status_code == 404


def test_motor_tramos_sin_escalera_activa_es_rechazado(cliente, admin_headers):
    """No se puede apagar la Fase 5 sin escalera: el box no pagaría nada."""
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        previos = [int(fila[0]) for fila in db.execute(text(
            "SELECT id FROM tramos_referido WHERE tenant_id = :t AND activo"),
            {"t": TENANT_ID}).fetchall()]
        db.execute(text("UPDATE tramos_referido SET activo = false "
                        "WHERE tenant_id = :t"), {"t": TENANT_ID})
        db.commit()
        try:
            respuesta = cliente.put(BASE + "/tramos/motor",
                                    json={"motor_premios": "tramos"},
                                    headers=admin_headers)
            assert respuesta.status_code == 409, respuesta.text
        finally:
            for tramo_id in previos:
                db.execute(text("UPDATE tramos_referido SET activo = true "
                                "WHERE id = :x"), {"x": tramo_id})
            db.commit()
    finally:
        db.close()






