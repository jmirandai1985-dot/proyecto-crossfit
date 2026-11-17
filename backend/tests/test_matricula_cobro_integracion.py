"""Matrícula configurable: cobro REAL en los sitios donde nace una SolicitudPlan.

Qué fija este archivo (integración contra la MISMA rama TEST que ve la API)
--------------------------------------------------------------------------
Para cada uno de los tres flujos que crean una `SolicitudPlan`:

  1. `POST /api/v1/solicitudes/solicitar`  (transferencia / voucher manual)
  2. `services/pagos.crear_pago_membresia` (Checkout Pro de Mercado Pago)
  3. `services/suscripciones_mp`           (suscripción recurrente / preapproval)

se cubren los tres casos pedidos:

  * alumno NUEVO con matrícula ACTIVA  -> se cobra y queda el snapshot;
  * alumno NUEVO con matrícula INACTIVA -> no se cobra (snapshot NULL);
  * alumno NO NUEVO con matrícula ACTIVA -> no se cobra (snapshot NULL).

Además:
  * el snapshot NO cambia si el admin apaga o cambia el monto DESPUÉS;
  * al activar el plan se crean DOS transacciones: membresía + matrícula
    (`categoria='matricula'`, referencia a la suscripción) y el KPI
    `/kpis/financiero.matricula` las cuenta;
  * el flujo RECURRENTE no suma la matrícula al cobro mensual (no hay "primer
    pago" en un preapproval) y la rama de cola queda con snapshot NULL.

Ningún test llama a Mercado Pago: `configuracion`/`crear_preferencia`/
`crear_preapproval` se monkeypatchean. Cada test crea un BOX TEMPORAL y lo borra.

Correr:
    cd backend && ENVIRONMENT=test py -3.12 -m pytest tests/test_matricula_cobro_integracion.py -q
"""
import sys
import uuid

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Sin `app.main`, el ORM necesita TODAS las tablas registradas (FKs del mapper).
import app.models  # noqa: E402,F401
from app.core.config import is_test_db_url, settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models.pago import Pago  # noqa: E402
from app.models.plan import Plan  # noqa: E402
from app.models.solicitud_plan import SolicitudPlan  # noqa: E402
from app.models.suscripcion import EstadoSuscripcion, Suscripcion  # noqa: E402
from app.models.transaccion_financiera import TransaccionFinanciera  # noqa: E402
from app.models.usuario import RolUsuario, Usuario  # noqa: E402
from app.services import matricula_service  # noqa: E402
from app.services import pagos as pagos_service  # noqa: E402
from app.services import suscripciones_mp  # noqa: E402

PRECIO = 40000
MATRICULA = 15000


# ── Infraestructura ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def db():
    """Sesión contra la rama TEST (falla cerrado si la URL no es de test)."""
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (in-process, sin uvicorn)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _sufijo() -> str:
    return f"{datetime.now():%Y%m%d%H%M%S%f}"



def _crear_box(db, *, matricula_activa=True, monto=MATRICULA) -> dict:
    """Box temporal con su admin (el admin tiene que existir: `aprobado_por` es FK)."""
    sufijo = _sufijo()
    tenant_id = db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo,
                             matricula_activa, matricula_monto_clp,
                             matricula_activada_en, created_at)
        VALUES (:n, :s, :p, true, :act, :monto,
                CASE WHEN :act THEN now() ELSE NULL END, now())
        RETURNING id
    """), {"n": f"Box matricula {sufijo}", "s": f"box-mat-{sufijo}",
           "p": str(uuid.uuid4()), "act": bool(matricula_activa),
           "monto": monto}).scalar()
    admin = _crear_usuario(db, tenant_id, "administrador",
                           f"mat.admin.{sufijo}@test.local")
    db.commit()
    return {"tenant_id": tenant_id, "admin_id": admin.id, "sufijo": sufijo}


def _crear_usuario(db, tenant_id: int, rol: str, correo: str) -> Usuario:
    usuario = Usuario(
        tenant_id=tenant_id,
        rut=f"9{uuid.uuid4().hex[:8]}-9",
        nombre=f"Matricula {rol} {correo[:10]}",
        correo=correo,
        password_hash="no-se-usa-en-este-test",
        rol=RolUsuario(rol),
        activo=True,
        estado="activo",
    )
    db.add(usuario)
    db.flush()
    return usuario


def _crear_plan(db, tenant_id: int, nombre: str, *, precio=PRECIO,
                duracion=30, genero="masculino", comercial=True) -> Plan:
    plan = Plan(
        tenant_id=tenant_id, nombre=nombre, creditos=10, es_ilimitado=False,
        precio_clp=precio, duracion_dias=duracion, activo=True,
        es_comercial=comercial, es_estudiante=False,
        requiere_certificado_estudiante=False, genero=genero,
    )
    db.add(plan)
    db.flush()
    return plan


def _crear_suscripcion(db, tenant_id: int, alumno_id: int, plan_id: int,
                       estado: str, *, dias=30) -> Suscripcion:
    ahora = datetime.now(timezone.utc)
    suscripcion = Suscripcion(
        tenant_id=tenant_id, usuario_id=alumno_id, plan_id=plan_id,
        # La columna es un ENUM nativo: se normaliza al miembro del enum.
        estado=EstadoSuscripcion(estado),
        fecha_inicio=ahora - timedelta(days=1),
        fecha_expiracion=ahora + timedelta(days=dias),
        creditos_totales=10, creditos_disponibles=10,
    )
    db.add(suscripcion)
    db.flush()
    return suscripcion


def _token(usuario_id: int, tenant_id: int, rol: str) -> dict:
    token = create_access_token({
        "usuario_id": usuario_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"mat.{rol}@test.local",
    })
    return {"Authorization": "Bearer " + token}


def _limpiar(db, tenant_id: int) -> None:
    """Borra el box temporal en el orden que exigen las FKs sin CASCADE.

    `solicitudes_planes` / `notificaciones*` apuntan a `usuarios` SIN cascade, así
    que se van primero; el resto cuelga del tenant con `ON DELETE CASCADE`.
    """
    db.rollback()
    try:
        ids = {"t": tenant_id}
        db.execute(text(
            "DELETE FROM notificaciones WHERE alumno_id IN "
            "(SELECT id FROM usuarios WHERE tenant_id = :t)"), ids)
        db.execute(text(
            "DELETE FROM notificaciones_enviadas WHERE alumno_id IN "
            "(SELECT id FROM usuarios WHERE tenant_id = :t)"), ids)
        db.execute(text("DELETE FROM solicitudes_planes WHERE tenant_id = :t"), ids)
        db.execute(text("DELETE FROM tenants WHERE id = :t"), ids)
        db.commit()
    except Exception as error:  # pragma: no cover - best-effort de limpieza
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el box {tenant_id}: {error}\n")



# ── 1) Transferencia / voucher manual (`POST /solicitudes/solicitar`) ────────
def _solicitar(cliente, token, tenant_id, alumno_id, plan_id):
    return cliente.post("/api/v1/solicitudes/solicitar", json={
        "tenant_id": tenant_id, "alumno_id": alumno_id, "plan_id": plan_id,
        "voucher_url": "test://voucher.png",
    }, headers=token)


def test_manual_alumno_nuevo_con_matricula_activa_congela_y_cobra(cliente, db):
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.nuevo.{box['sufijo']}@test.local")
        plan = _crear_plan(db, box["tenant_id"], f"Mensual mat {box['sufijo']}")
        db.commit()

        creada = _solicitar(cliente, _token(alumno.id, box["tenant_id"], "alumno"),
                            box["tenant_id"], alumno.id, plan.id)
        assert creada.status_code == 201, creada.text
        assert creada.json()["matricula_clp"] == MATRICULA

        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == creada.json()["id"]).one()
        assert solicitud.precio_clp_snapshot == PRECIO
        assert solicitud.matricula_clp_snapshot == MATRICULA, \
            "el monto de la matrícula se congela al crear la solicitud"
        assert solicitud.precio_final_clp is None, \
            "la matrícula NO se suma a precio_final (es otra categoría de ingreso)"

        # El admin la cambia y la apaga DESPUÉS: la solicitud en curso no se mueve.
        db.execute(text(
            "UPDATE tenants SET matricula_activa = false, "
            "matricula_monto_clp = 99999 WHERE id = :t"), {"t": box["tenant_id"]})
        db.commit()
        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == creada.json()["id"]).one()
        assert solicitud.matricula_clp_snapshot == MATRICULA, \
            "apagar/cambiar la matrícula no afecta una solicitud ya creada"

        admin = _token(box["admin_id"], box["tenant_id"], "administrador")
        aprobada = cliente.put(f"/api/v1/solicitudes/{creada.json()['id']}/aprobar",
                               headers=admin)
        assert aprobada.status_code == 200, aprobada.text

        db.rollback()
        transacciones = db.query(TransaccionFinanciera).filter(
            TransaccionFinanciera.tenant_id == box["tenant_id"]).all()
        por_categoria = {t.categoria: t for t in transacciones}
        assert por_categoria["membresia"].monto == PRECIO
        assert por_categoria["matricula"].monto == MATRICULA, \
            "la matrícula entra como ingreso SEPARADO (categoria='matricula')"
        assert por_categoria["matricula"].referencia_tipo == "suscripcion"
        assert (por_categoria["matricula"].referencia_id
                == por_categoria["membresia"].referencia_id), \
            "las dos transacciones apuntan a la MISMA suscripción"

        kpi = cliente.get("/api/v1/kpis/financiero", headers=admin)
        assert kpi.status_code == 200, kpi.text
        bloque = kpi.json()["matricula"]
        assert bloque["n_transacciones"] == 1
        assert bloque["ingreso_total"] == float(MATRICULA)
        assert bloque["global"] == float(MATRICULA), \
            "el ticket de la matrícula es el monto fijo cobrado"
        assert kpi.json()["ticket_promedio"]["ingreso_total"] == float(PRECIO), \
            "el ticket de membresía NO se infla con la matrícula"
    finally:
        _limpiar(db, box["tenant_id"])


def test_manual_alumno_nuevo_con_matricula_inactiva_no_cobra(cliente, db):
    box = _crear_box(db, matricula_activa=False)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.inact.{box['sufijo']}@test.local")
        plan = _crear_plan(db, box["tenant_id"], f"Mensual inact {box['sufijo']}")
        db.commit()

        creada = _solicitar(cliente, _token(alumno.id, box["tenant_id"], "alumno"),
                            box["tenant_id"], alumno.id, plan.id)
        assert creada.status_code == 201, creada.text
        assert creada.json()["matricula_clp"] is None

        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == creada.json()["id"]).one()
        assert solicitud.matricula_clp_snapshot is None
    finally:
        _limpiar(db, box["tenant_id"])


def test_manual_alumno_no_nuevo_con_matricula_activa_no_cobra(cliente, db):
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.viejo.{box['sufijo']}@test.local")
        plan_viejo = _crear_plan(db, box["tenant_id"],
                                 f"Mensual viejo {box['sufijo']}")
        plan = _crear_plan(db, box["tenant_id"], f"Mensual nuevo {box['sufijo']}")
        # Una membresía PAGADA (comercial, precio > 0) ya lo saca de "alumno nuevo".
        _crear_suscripcion(db, box["tenant_id"], alumno.id, plan_viejo.id, "vencido")
        db.commit()

        creada = _solicitar(cliente, _token(alumno.id, box["tenant_id"], "alumno"),
                            box["tenant_id"], alumno.id, plan.id)
        assert creada.status_code == 201, creada.text
        assert creada.json()["matricula_clp"] is None

        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == creada.json()["id"]).one()
        assert solicitud.matricula_clp_snapshot is None, \
            "la matrícula es sólo para el alumno nuevo"
    finally:
        _limpiar(db, box["tenant_id"])


# ── 2) Checkout Pro de Mercado Pago (`pagos.crear_pago_membresia`) ───────────
def _sin_mercado_pago(monkeypatch):
    """Nada de red: la preferencia y la configuración de MP son falsas."""
    from app.services import mercadopago_cliente as mp_cliente

    monkeypatch.setattr(mp_cliente, "configuracion", lambda: {})
    monkeypatch.setattr(
        mp_cliente, "crear_preferencia",
        lambda **kwargs: (f"pref-{uuid.uuid4().hex[:8]}",
                          "https://mp.test/checkout"))


def _checkout(db, box, alumno, plan):
    return pagos_service.crear_pago_membresia(
        db,
        current_user={"tenant_id": box["tenant_id"], "usuario_id": alumno.id},
        plan_id=plan.id,
    )


def test_mp_checkout_alumno_nuevo_con_matricula_activa_cobra_el_total(db, monkeypatch):
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.mp.{box['sufijo']}@test.local")
        plan = _crear_plan(db, box["tenant_id"], f"Mensual MP {box['sufijo']}")
        db.commit()
        _sin_mercado_pago(monkeypatch)

        resultado = _checkout(db, box, alumno, plan)
        assert resultado.get("init_point") == "https://mp.test/checkout"

        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.tenant_id == box["tenant_id"]).one()
        pago = db.query(Pago).filter(Pago.tenant_id == box["tenant_id"]).one()
        assert solicitud.estado == "iniciado" and pago.estado == "iniciado"
        assert solicitud.precio_final_clp == PRECIO
        assert solicitud.matricula_clp_snapshot == MATRICULA
        assert pago.monto_clp == PRECIO + MATRICULA, \
            "Mercado Pago cobra plan + matrícula (el webhook compara este número)"

        # El snapshot NO se mueve si el admin cambia el monto después.
        db.execute(text(
            "UPDATE tenants SET matricula_monto_clp = 99999 WHERE id = :t"),
            {"t": box["tenant_id"]})
        db.commit()
        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.tenant_id == box["tenant_id"]).one()
        pago = db.query(Pago).filter(Pago.tenant_id == box["tenant_id"]).one()
        assert solicitud.matricula_clp_snapshot == MATRICULA
        assert pago.monto_clp == PRECIO + MATRICULA
    finally:
        _limpiar(db, box["tenant_id"])


def test_mp_checkout_alumno_nuevo_con_matricula_inactiva_cobra_solo_el_plan(db, monkeypatch):
    box = _crear_box(db, matricula_activa=False)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.mp.off.{box['sufijo']}@test.local")
        plan = _crear_plan(db, box["tenant_id"], f"Mensual MP off {box['sufijo']}")
        db.commit()
        _sin_mercado_pago(monkeypatch)

        _checkout(db, box, alumno, plan)

        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.tenant_id == box["tenant_id"]).one()
        pago = db.query(Pago).filter(Pago.tenant_id == box["tenant_id"]).one()
        assert solicitud.matricula_clp_snapshot is None
        assert pago.monto_clp == PRECIO
    finally:
        _limpiar(db, box["tenant_id"])


def test_mp_checkout_alumno_no_nuevo_con_matricula_activa_no_cobra(db, monkeypatch):
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.mp.viejo.{box['sufijo']}@test.local")
        plan_viejo = _crear_plan(db, box["tenant_id"],
                                 f"Mensual MP viejo {box['sufijo']}")
        plan = _crear_plan(db, box["tenant_id"], f"Mensual MP nuevo {box['sufijo']}")
        _crear_suscripcion(db, box["tenant_id"], alumno.id, plan_viejo.id,
                           EstadoSuscripcion.vencido.value)
        db.commit()
        _sin_mercado_pago(monkeypatch)

        _checkout(db, box, alumno, plan)

        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.tenant_id == box["tenant_id"]).one()
        pago = db.query(Pago).filter(Pago.tenant_id == box["tenant_id"]).one()
        assert solicitud.matricula_clp_snapshot is None
        assert pago.monto_clp == PRECIO
    finally:
        _limpiar(db, box["tenant_id"])


# ── 3) Suscripción recurrente de Mercado Pago (preapproval) ─────────────────
def test_recurrente_no_suma_matricula_al_cobro_mensual(db, monkeypatch):
    """El preapproval cobra `transaction_amount` TODOS los meses.

    Sumarle la matrícula la cobraría en cada renovación, así que este flujo NO la
    incluye (decisión documentada en `suscripciones_mp.crear_suscripcion_mp`). Hoy
    además no tiene pantalla: el alumno paga con Checkout Pro o transferencia.
    """
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.rec.{box['sufijo']}@test.local")
        plan = _crear_plan(db, box["tenant_id"], f"Mensual rec {box['sufijo']}")
        db.commit()

        from app.services import mercadopago_cliente as mp_cliente
        monkeypatch.setattr(mp_cliente, "configuracion", lambda: {})
        monkeypatch.setattr(
            mp_cliente, "crear_preapproval",
            lambda **kwargs: (f"preapproval-{uuid.uuid4().hex[:8]}",
                              "https://mp.test/suscripcion"))

        resultado = suscripciones_mp.crear_suscripcion_mp(
            db,
            current_user={"tenant_id": box["tenant_id"],
                          "usuario_id": alumno.id},
            plan_id=plan.id,
        )
        assert resultado["monto_clp"] == PRECIO, \
            "el cobro recurrente es el precio del PLAN (sin matrícula)"
        assert resultado["init_point"] == "https://mp.test/suscripcion"

        db.rollback()
        assert db.query(SolicitudPlan).filter(
            SolicitudPlan.tenant_id == box["tenant_id"]).count() == 0, \
            "este flujo no crea SolicitudPlan en el camino normal"
        assert db.query(Suscripcion).filter(
            Suscripcion.tenant_id == box["tenant_id"]).count() == 1
    finally:
        _limpiar(db, box["tenant_id"])


def test_cola_recurrente_deja_la_matricula_en_null(db):
    """La rama `en_cola` sólo corre para un alumno que YA tiene plan PAGADO.

    Por la propia regla de la cola (`plan_vigente_usable` exige `precio_clp > 0`)
    ese alumno nunca es "nuevo": el snapshot queda NULL aunque el box tenga la
    matrícula activa. Se fija para que un cambio futuro de la regla no la esconda.
    """
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.cola.{box['sufijo']}@test.local")
        plan_actual = _crear_plan(db, box["tenant_id"],
                                  f"Mensual cola actual {box['sufijo']}")
        plan_nuevo = _crear_plan(db, box["tenant_id"],
                                 f"Mensual cola nuevo {box['sufijo']}")
        _crear_suscripcion(db, box["tenant_id"], alumno.id, plan_actual.id,
                           EstadoSuscripcion.activo.value)
        pendiente = _crear_suscripcion(db, box["tenant_id"], alumno.id,
                                       plan_nuevo.id,
                                       EstadoSuscripcion.pendiente.value)
        db.commit()

        solicitud_id = suscripciones_mp._encolar_recurrente(db, pendiente)
        db.commit()

        db.rollback()
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == solicitud_id).one()
        assert solicitud.estado == "en_cola"
        assert solicitud.matricula_clp_snapshot is None, \
            "un alumno con plan pagado vigente no es 'nuevo'"
    finally:
        _limpiar(db, box["tenant_id"])


# ── Configuración del panel + lo que ve el alumno ───────────────────────────
def test_config_api_activa_exige_monto_y_mi_estado(cliente, db):
    box = _crear_box(db, matricula_activa=False, monto=None)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.estado.{box['sufijo']}@test.local")
        db.commit()
        admin = _token(box["admin_id"], box["tenant_id"], "administrador")

        sin_monto = cliente.put("/api/v1/matricula",
                                json={"activa": True}, headers=admin)
        assert sin_monto.status_code == 400, \
            "una matrícula activa sin monto no es un cobro"

        guardada = cliente.put("/api/v1/matricula",
                               json={"activa": True, "monto_clp": MATRICULA},
                               headers=admin)
        assert guardada.status_code == 200, guardada.text
        assert guardada.json()["activa"] is True
        assert guardada.json()["monto_clp"] == MATRICULA
        assert guardada.json()["activada_en"], \
            "el panel muestra 'Activa desde el <fecha>'"
        assert guardada.json()["alumnos_cobrados"] == 0

        leida = cliente.get("/api/v1/matricula", headers=admin)
        assert leida.status_code == 200 and leida.json()["activa"] is True

        token_alumno = _token(alumno.id, box["tenant_id"], "alumno")
        estado = cliente.get("/api/v1/matricula/mi-estado",
                             headers=token_alumno)
        assert estado.status_code == 200, estado.text
        assert estado.json()["aplica"] is True
        assert estado.json()["monto_a_cobrar"] == MATRICULA

        # Con una membresía PAGADA deja de ser nuevo.
        plan = _crear_plan(db, box["tenant_id"], f"Mensual estado {box['sufijo']}")
        _crear_suscripcion(db, box["tenant_id"], alumno.id, plan.id,
                           EstadoSuscripcion.activo.value)
        db.commit()
        estado = cliente.get("/api/v1/matricula/mi-estado",
                             headers=token_alumno)
        assert estado.json()["aplica"] is False
        assert estado.json()["monto_a_cobrar"] is None

        # El staff nunca la paga.
        staff = cliente.get("/api/v1/matricula/mi-estado", headers=admin)
        assert staff.status_code == 200 and staff.json()["aplica"] is False
    finally:
        _limpiar(db, box["tenant_id"])




# ── La regla de "alumno nuevo" (criterio aprobado) ─────────────────────────
def test_plan_de_prueba_gratis_no_gasta_la_matricula(db):
    """El plan "Prueba" del alta (gratis) NO convierte al alumno en "existente".

    Casi todos los alumnos pasan por Prueba al registrarse: si contara, nadie
    pagaría la matrícula. El criterio es "nunca tuvo una membresía PAGADA".
    """
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.prueba.{box['sufijo']}@test.local")
        prueba = _crear_plan(db, box["tenant_id"], f"Prueba {box['sufijo']}",
                             precio=0, duracion=7)
        _crear_suscripcion(db, box["tenant_id"], alumno.id, prueba.id,
                           EstadoSuscripcion.activo.value, dias=7)
        db.commit()

        assert matricula_service.alumno_es_nuevo(db, box["tenant_id"],
                                                 alumno.id) is True
        assert matricula_service.monto_para_alumno(db, box["tenant_id"],
                                                   alumno.id) == MATRICULA
    finally:
        _limpiar(db, box["tenant_id"])


def test_pase_de_regreso_no_comercial_no_gasta_la_matricula(db):
    """El "Pase de regreso" (`es_comercial=False`) tampoco es una membresía."""
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.pase.{box['sufijo']}@test.local")
        pase = _crear_plan(db, box["tenant_id"], f"Pase {box['sufijo']}",
                           precio=25000, duracion=15, comercial=False)
        _crear_suscripcion(db, box["tenant_id"], alumno.id, pase.id,
                           EstadoSuscripcion.vencido.value, dias=15)
        db.commit()

        assert matricula_service.alumno_es_nuevo(db, box["tenant_id"],
                                                 alumno.id) is True
    finally:
        _limpiar(db, box["tenant_id"])


def test_membresia_pagada_ya_no_es_alumno_nuevo(db):
    """Control: una membresía comercial de precio > 0 sí lo saca de "nuevo"."""
    box = _crear_box(db)
    try:
        alumno = _crear_usuario(db, box["tenant_id"], "alumno",
                                f"mat.pago.{box['sufijo']}@test.local")
        plan = _crear_plan(db, box["tenant_id"], f"Mensual pago {box['sufijo']}")
        _crear_suscripcion(db, box["tenant_id"], alumno.id, plan.id,
                           EstadoSuscripcion.vencido.value)
        db.commit()

        assert matricula_service.alumno_es_nuevo(db, box["tenant_id"],
                                                 alumno.id) is False
        assert matricula_service.monto_para_alumno(db, box["tenant_id"],
                                                   alumno.id) is None
    finally:
        _limpiar(db, box["tenant_id"])

        _limpiar(db, box["tenant_id"])
