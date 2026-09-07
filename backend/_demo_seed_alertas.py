"""DEMO FASE: sembrar 3 alumnos de prueba para las alertas programadas del scheduler.

Alumnos en tenant_id=1 (el tenant que consultan los endpoints manuales
/notificaciones/enviar-alertas-*):
  1. "Test Vence en 3 días" → jmirandai1985@gmail.com, suscripción activa, expira hoy+3.
  2. "Test Vence Hoy"       → jmirandai1985+vencahoy@gmail.com, suscripción activa, expira hoy.
  3. "Test Inactivo 7+"     → jmirandai1985+inactivo@gmail.com, suscripción activa vigente,
                               última asistencia hace 9 días.
NOTA: hay UNIQUE (uq_correo_por_tenant) en (tenant_id, correo), por lo que los 3
NO pueden compartir el string exacto. Gmail es case-insensitive en la entrega:
variantes de mayúsculas del local-part llegan a la MISMA bandeja
(jmirandai1985@gmail.com) y son strings distintos para la constraint.
(Se probó '+tag' pero smtp.gmail.com lo rechaza en RCPT: 553 no es RFC 5321.)
Además crea (si no existe) un admin dedicado para el login del demo.
Idempotente: si se re-corre, reutiliza los usuarios existentes por nombre.
"""
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.database import SessionLocal
from app.models.asistencia import Asistencia
from app.models.plan import Plan
from app.models.suscripcion import Suscripcion
from app.models.usuario import Usuario, RolUsuario

if "polished-term" not in settings.DATABASE_URL:
    print("ABORT: la BD no es polished-term")
    raise SystemExit(1)

TENANT_ID = 1
PASS_ADMIN = "AdminDemo123!"
PASS_ALUMNO = "Demo123456!"

db = SessionLocal()
try:
    # ── Admin dedicado para el demo ──
    adm = db.query(Usuario).filter(
        Usuario.tenant_id == TENANT_ID,
        Usuario.correo == "demo_alertas_admin@test.cl").first()
    if not adm:
        adm = Usuario(tenant_id=TENANT_ID, rut=f"11{uuid.uuid4().hex[:6]}-K",
                      nombre="Admin Demo Alertas",
                      correo="demo_alertas_admin@test.cl",
                      password_hash=get_password_hash(PASS_ADMIN),
                      rol=RolUsuario.administrador, activo=True, estado="activo")
        db.add(adm)
        db.flush()
    admin_id = adm.id

    # ── Plan del tenant 1 (reusar el primero o crear uno) ──
    plan = db.query(Plan).filter(Plan.tenant_id == TENANT_ID).order_by(Plan.id).first()
    if not plan:
        plan = Plan(tenant_id=TENANT_ID, nombre="Plan Demo Alertas", creditos=8,
                    es_ilimitado=False, precio_clp=30000, duracion_dias=30, activo=True)
        db.add(plan)
        db.flush()
    plan_id = plan.id

    # ── 3 alumnos (correo: variante de caso → bandeja de jmirandai1985@gmail.com) ──
    hoy = date.today()
    casos = [
        ("Test Vence en 3 días", "JMIRANDAI1985@gmail.com",     hoy + timedelta(days=3), None),
        ("Test Vence Hoy",       "Jmirandai1985@gmail.com",     hoy,                     None),
        ("Test Inactivo 7+",     "jMirandai1985@gmail.com",     hoy + timedelta(days=30), hoy - timedelta(days=9)),
    ]
    ids = {}
    for nombre, correo, exp, ultima_asis in casos:
        u = db.query(Usuario).filter(
            Usuario.tenant_id == TENANT_ID, Usuario.nombre == nombre).first()
        if not u:
            u = Usuario(tenant_id=TENANT_ID, rut=f"12{uuid.uuid4().hex[:6]}-K",
                        nombre=nombre, correo=correo,
                        password_hash=get_password_hash(PASS_ALUMNO),
                        rol=RolUsuario.alumno, activo=True, estado="activo")
            db.add(u)
            db.flush()
        elif u.correo != correo:
            u.correo = correo  # corregir email (idempotencia tras el cambio de approach)
        ids[nombre] = u.id

        # Suscripción activa con la expiración del caso (estado='activo', NO 'activa').
        # Verificar por SQL crudo (la columna estado es enum estado_suscripcion).
        exp_ts = datetime.combine(exp, datetime.min.time(), tzinfo=timezone.utc)
        ya = db.execute(text(
            "SELECT count(*) FROM suscripciones "
            "WHERE usuario_id=:u AND estado='activo' AND fecha_expiracion=:e"),
            {"u": u.id, "e": exp_ts}).scalar()
        if ya == 0:
            sub = Suscripcion(
                tenant_id=TENANT_ID, usuario_id=u.id, plan_id=plan_id, estado="activo",
                creditos_totales=8, creditos_disponibles=8,
                fecha_inicio=datetime.now(timezone.utc),
                fecha_expiracion=exp_ts)
            db.add(sub)
            db.flush()  # INSERT único por fila (evita insertmanyvalues + enum estado_suscripcion)
        if ultima_asis and db.query(Asistencia).filter(
                Asistencia.usuario_id == u.id).count() == 0:
            db.add(Asistencia(tenant_id=TENANT_ID, usuario_id=u.id,
                              fecha=ultima_asis, clase="WOD"))
    db.commit()

    # ── Reporte ──
    print("admin_id (login):", admin_id)
    print("plan_id:", plan_id)
    for nombre, uid in ids.items():
        u = db.query(Usuario).get(uid)
        print(f"alumno '{nombre}': id={uid} correo={u.correo}")
        for tipo in ("renovacion_plan", "vencimiento_inminente", "inactividad"):
            n = db.execute(text(
                "SELECT count(*) FROM notificaciones_enviadas "
                "WHERE alumno_id=:a AND tipo=:t"), {"a": uid, "t": tipo}).scalar()
            print(f"   notificaciones previas tipo={tipo}: {n}")
finally:
    db.close()
