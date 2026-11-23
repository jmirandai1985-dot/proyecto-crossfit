"""Fixture de integración del motor de KPIs — SÓLO TEST.

Todo se inserta dentro de UNA transacción que se revierte al salir del contexto:
no queda ni una fila en la base. Antes de insertar nada, `guard_test_db()`
aborta si el host de `DATABASE_URL` no es exactamente el de TEST.

═══ VALORES ESPERADOS (calculados a mano, NO copiados del código) ═══

El "mes KPI" es octubre 2026. Las fechas de alta/baja son relativas a `now()`
para que la vida promedio sea estable en cualquier día de ejecución.

15 alumnos REALES (`es_prueba=false`, `rol='alumno'`, `estado='activo'`):
  · 4 con alta hace 120 días (cohorte A) — plan $40.000.
  · 5 con alta hace  90 días (cohorte B) — plan $40.000.
  · 6 con alta hace  60 días (cohorte C) — 2 compran plan $60.000 en octubre,
    3 compran plan $60.000 en noviembre y 1 compra plan $40.000 en noviembre.
  → MRR (hoy) = 10 planes de $40.000 + 5 planes de $60.000
              = 400.000 + 300.000 = $700.000.
     (Los 5 es_prueba y los 3 rechazados también tienen suscripción
      date-vigente: si no se filtraran, el MRR subiría a $950.000 y $820.000.)
  → Alumnos vigentes hoy = 15 (los 2 de baja no tienen suscripción; los 3
     rechazados no son 'activo'; los 5 es_prueba se excluyen).
  → Alumnos vigentes al 31-oct = 4 A + 5 B + 2 compradores C = 11
     (los 4 C que compran en noviembre todavía no están vigentes al cierre).

5 cuentas de PRUEBA (`es_prueba=true`): suscripción pagada de $50.000 y una
transacción de $50.000 en octubre, más plan "Prueba" en octubre. No aparecen en
NINGUNA métrica.

3 usuarios RECHAZADOS con suscripción $40.000 date-vigente: NO cuentan en MRR
(estado excluido), ni en alumnos vigentes (no son 'activo'), ni en la vida/LTV
(sólo se promedian alumnos activos). No tienen transacciones.

2 usuarios de BAJA con `fecha_baja` hace 20 días: no tienen suscripción y
tampoco entran en la vida/LTV, que ahora se calcula sólo sobre activos.

── Dinero ──────────────────────────────────────────────────────────────────
Transacciones de membresía reales de octubre:
  4 A × $40.000 = $160.000
  5 B × $40.000 = $200.000
  2 C compradores × $60.000 = $120.000
  Total ingresos reales = $480.000
Egreso SIN referencia (caso ambiguo: se cuenta por instrucción) = $100.000.
  → ingresos_netos(octubre) = 480.000 − 100.000 = $380.000.
Las 5 transacciones de prueba ($250.000) quedan fuera; si no, el neto sería
$630.000. Los 4 C que compran en noviembre tienen su transacción en noviembre
(no contaminan octubre).
  → ticket global = (10×40.000 + 5×60.000) / 15 = 700.000 / 15 = $46.666,67
    → ROUND = $46.667; n_transacciones = 15; ingreso_total = $700.000.
  → Bazar: pedido real entregado $10.000; pedido de prueba $5.000 excluido;
    ventas_bazar(octubre) = $10.000.

── Conversión prueba → plan (octubre) ───────────────────────────────────────
6 alumnos C empiezan plan "Prueba" en octubre; 2 de ellos compran un plan pago
en octubre. 2 / 6 = 33,33 %. Las pruebas de las 5 cuentas es_prueba no cuentan;
los 13 alumnos A/B ya eran miembros y no están en el cohorte de prueba.
Además, A0 (miembro previo) compra una renovación paga de $60.000 en octubre:
hay 3 compras pagas reales en el mes (A0 + 2 C), pero A0 NO pertenece al
cohorte de prueba, así que el numerador de conversión sigue en 2. La renovación
vence antes del cierre y no tiene transacción, para no alterar MRR ni dinero.

── Retención por cohorte (asistencia real) ──────────────────────────────────
Cohorte A (4 alumnos, alta hace 120 días): 1 con asistencia en [alta, alta+30]
  → evaluables=4, activos=1, retención = n/d (None): 4 < MIN_BASE_RETENCION=5.
Cohorte B (5 alumnos, alta hace 90 días): 3 con asistencia en [alta, alta+30]
  → evaluables=5, activos=3, retención = 3/5 = 60,0 %.

── Asistencia real de octubre ───────────────────────────────────────────────
Clase realizada el 15-oct con 10 reservas REALES confirmadas: 6 con
`asistio=true` y 4 con `asistio=false`. Se agrega 1 reserva de una cuenta
`es_prueba` con `asistio=true` que NO cuenta. Asistencia real = 6 / 10 = 60,0 %.
NO se usa `asistentes_confirmados` (ese contador mide cupos reservados, no
asistencia).

── Vida promedio ────────────────────────────────────────────────────────────
Sólo entran los 15 alumnos ACTIVOS reales. Se excluyen los 3 rechazados, los
2 de baja y las 5 cuentas es_prueba:
  4×120 + 5×90 + 6×60 = 480 + 450 + 360 = 1.290 días
  1.290 / 15 = 86,0 días → 86 / 30,44 = 2,83 meses.
  n_alumnos = 15; n_con_baja = 0.
  (El valor anterior 111 días / 3,65 meses sumaba los 3 rechazados y los 2 de
  baja; el LTV ahora se calcula sobre la base activa.)

── Serie del forecast ───────────────────────────────────────────────────────
Octubre: ingresos reales $480.000 − egreso $100.000 = $380.000.
Las transacciones de prueba ($250.000) no entran a la serie.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.config import settings
from app.db.database import SessionLocal

# Allowlist EXACTA del endpoint de TEST (sin sufijo de dominio). El host real
# de Neon puede ser `<endpoint>.us-east-2.aws.neon.tech` o
# `<endpoint>-pooler...`; se valida el PRIMER label del host, no un substring.
HOST_TEST = "ep-spring-thunder-argjp1mm"
HOSTS_TEST = (HOST_TEST, f"{HOST_TEST}-pooler")
MES_KPI = date(2026, 10, 1)
FIN_KPI = date(2026, 10, 31)
MES_KPI_SIGUIENTE = date(2026, 11, 1)


ESPERADO = {
    # dinero
    "mrr": 700_000.0,
    "ingresos_netos_mes": 380_000.0,
    "alumnos_vigentes_hoy": 15,
    "alumnos_vigentes_cierre_mes": 11,
    "ticket_global": 46_667.0,
    "ticket_n": 15,
    "ticket_ingreso_total": 700_000.0,
    "bazar_mes": 10_000.0,
    "forecast_octubre_neto": 380_000.0,
    # conversión prueba → plan
    "alumnos_prueba": 6,
    "alumnos_plan_comprado": 2,
    "conversion_rate": 33.33,
    # retención por cohorte
    "cohorte_4_evaluables": 4,
    "cohorte_4_activos": 1,
    "cohorte_4_retencion_pct": None,
    "cohorte_5_evaluables": 5,
    "cohorte_5_activos": 3,
    "cohorte_5_retencion_pct": 60.0,
    # asistencia real
    "asistentes_mes": 6,
    "reservas_mes": 10,
    "asistencia_real_pct": 60.0,
    # ocupación: asistencias reales / cupos (clase de 20) = 30 %
    "ocupacion_real_pct": 30.0,
    # ARPU coherente con MRR (700.000) / 15 alumnos activos
    "arpu_actual": 46667.0,
    # vida
    "vida_dias": 86,
    "vida_meses": 2.83,
    "vida_n_alumnos": 15,
    "vida_n_con_baja": 0,
    # compras pagas reales del mes (incluye al miembro que renueva)
    "compras_pagas_mes": 3,
}


def guard_test_db() -> None:
    """Aborta salvo que `DATABASE_URL` apunte EXACTAMENTE al endpoint de TEST."""
    url = (getattr(settings, "DATABASE_URL", "") or "").strip()
    host = (urlparse(url).hostname or "").lower()
    endpoint = host.split(".")[0] if host else ""
    host_permitido = (
        host in HOSTS_TEST
        or (host.endswith(".neon.tech") and endpoint in HOSTS_TEST))
    if not host_permitido:
        raise RuntimeError(
            "ABORTADO: DATABASE_URL no apunta al host de TEST permitido "
            f"({', '.join(HOSTS_TEST)} en neon.tech). Host detectado: "
            f"{host or '<vacío>'}. No se insertó nada.")


@contextmanager
def motor_kpis_fixture():
    """Abre una transacción, inserta el escenario y la revierte al final."""
    guard_test_db()
    db = SessionLocal()
    trans = db.begin()
    try:
        datos = _insertar(db)
        db.flush()
        yield db, datos
    finally:
        trans.rollback()
        db.close()


def _uno(db, sql: str, **params):
    """Primera columna de `RETURNING id` / de un `SELECT` de una fila."""
    return db.execute(text(sql), params).scalar()


def _ejecutar(db, sql: str, **params):
    db.execute(text(sql), params)


def _insertar(db):
    """Inserta el escenario completo dentro de la transacción abierta."""
    sufijo = uuid.uuid4().hex[:8]
    tenant_id = _uno(db, """
        INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
        VALUES (:nombre, :sub, :pub, true, now())
        RETURNING id
    """, nombre=f"Box KPIs Fixture {sufijo}",
        sub=f"kpis-fixture-{sufijo}", pub=f"kpis-fixture-{sufijo}")

    def _plan(nombre, precio, comercial=True, duracion=30):
        return _uno(db, """
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado,
                                precio_clp, duracion_dias, activo, es_comercial)
            VALUES (:tid, :nombre, 1, false, :precio, :duracion, true, :comercial)
            RETURNING id
        """, tid=tenant_id, nombre=nombre, precio=precio,
            duracion=duracion, comercial=comercial)

    plan_prueba = _plan("Prueba", 0, comercial=False, duracion=7)
    plan_40 = _plan("Plan 40K", 40_000)
    plan_60 = _plan("Plan 60K", 60_000)
    plan_test = _plan("Plan Test 50K", 50_000)
    plan_renovacion = _plan("Renovación 60K", 60_000)

    secuencia = [0]

    def _alumno(nombre, created_sql, estado="activo", es_prueba=False,
                fecha_baja_sql="NULL"):
        if estado not in ("activo", "rechazado", "baja"):
            raise ValueError(f"estado no permitido en el fixture: {estado}")
        secuencia[0] += 1
        n = secuencia[0]
        activo = "true" if estado == "activo" else "false"
        prueba = "true" if es_prueba else "false"
        return _uno(db, f"""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                                  rol, activo, estado, es_prueba, created_at,
                                  fecha_baja)
            VALUES (:tid, :rut, :nombre, :correo, 'x', 'alumno', {activo},
                    '{estado}', {prueba}, {created_sql}, {fecha_baja_sql})
            RETURNING id
        """, tid=tenant_id, rut=f"F{sufijo[:5]}{n:03d}",
            nombre=nombre, correo=f"fixture+{sufijo}{n:03d}@example.test")

    a_users = [_alumno(f"Real A{i}", "now() - interval '120 days'")
               for i in range(4)]
    b_users = [_alumno(f"Real B{i}", "now() - interval '90 days'")
               for i in range(5)]
    c_users = [_alumno(f"Real C{i}", "now() - interval '60 days'")
               for i in range(6)]
    test_users = [
        _alumno(f"Cuenta Prueba {i}", "now() - interval '60 days'",
                es_prueba=True)
        for i in range(5)
    ]
    rechazados = [
        _alumno(f"Rechazado {i}", "now() - interval '180 days'",
                estado="rechazado")
        for i in range(3)
    ]
    bajas = [
        _alumno(f"Baja {i}", "now() - interval '210 days'", estado="baja",
                fecha_baja_sql="now() - interval '20 days'")
        for i in range(2)
    ]

    def _suscripcion(uid, plan_id, inicio_sql,
                     fin_sql="(now() + interval '30 days')::date"):
        return _uno(db, f"""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:tid, :uid, :pid, 'activo', 1, 1, {inicio_sql}, {fin_sql})
            RETURNING id
        """, tid=tenant_id, uid=uid, pid=plan_id)

    subs_a = {
        uid: _suscripcion(uid, plan_40, "(now() - interval '120 days')::date")
        for uid in a_users
    }

    # Miembro PREVIO que compra una renovación paga en octubre: la compra es
    # real para el embudo (la cuenta la contaría el numerador viejo), pero NO
    # pertenece al cohorte de prueba. Vence el 20-oct y no tiene transacción,
    # así no mueve MRR, alumnos vigentes, ingresos ni ticket.
    miembro_comprador = a_users[0]
    sub_renovacion = _suscripcion(
        miembro_comprador, plan_renovacion,
        "TIMESTAMPTZ '2026-10-09 12:00:00+00'",
        "TIMESTAMPTZ '2026-10-20 12:00:00+00'")
    subs_b = {
        uid: _suscripcion(uid, plan_40, "(now() - interval '90 days')::date")
        for uid in b_users
    }
    subs_c = {}
    for i, uid in enumerate(c_users):
        _suscripcion(uid, plan_prueba,
                     "TIMESTAMPTZ '2026-10-01 12:00:00+00'",
                     "TIMESTAMPTZ '2026-10-08 12:00:00+00'")
        if i < 2:
            plan = plan_60
            inicio = "TIMESTAMPTZ '2026-10-10 12:00:00+00'"
        elif i < 5:
            plan = plan_60
            inicio = "TIMESTAMPTZ '2026-11-01 12:00:00+00'"
        else:
            plan = plan_40
            inicio = "TIMESTAMPTZ '2026-11-01 12:00:00+00'"
        subs_c[uid] = _suscripcion(uid, plan, inicio)

    subs_test = []
    for uid in test_users:
        _suscripcion(uid, plan_prueba,
                     "TIMESTAMPTZ '2026-10-01 12:00:00+00'",
                     "TIMESTAMPTZ '2026-10-08 12:00:00+00'")
        subs_test.append(_suscripcion(
            uid, plan_test, "TIMESTAMPTZ '2026-10-01 12:00:00+00'"))

    subs_rechazados = [
        _suscripcion(uid, plan_40, "(now() - interval '180 days')::date")
        for uid in rechazados
    ]




    def _tx_susc(sid, monto, fecha_sql):
        _ejecutar(db, f"""
            INSERT INTO transacciones_financieras
                (tenant_id, tipo, categoria, monto, descripcion,
                 referencia_tipo, referencia_id, fecha)
            VALUES (:tid, 'ingreso', 'membresia', :monto, 'fixture',
                    'suscripcion', :ref, {fecha_sql})
        """, tid=tenant_id, monto=monto, ref=sid)

    def _tx_egreso(monto, fecha_sql):
        _ejecutar(db, f"""
            INSERT INTO transacciones_financieras
                (tenant_id, tipo, categoria, monto, descripcion,
                 referencia_tipo, referencia_id, fecha)
            VALUES (:tid, 'egreso', 'otros', :monto, 'egreso sin referencia',
                    NULL, NULL, {fecha_sql})
        """, tid=tenant_id, monto=monto)

    # Octubre: 4 A + 5 B + 2 compradores C = $480.000 reales.
    for uid in a_users:
        _tx_susc(subs_a[uid], 40_000, "DATE '2026-10-15'")
    for uid in b_users:
        _tx_susc(subs_b[uid], 40_000, "DATE '2026-10-15'")
    for uid in c_users[:2]:
        _tx_susc(subs_c[uid], 60_000, "DATE '2026-10-15'")

    # Noviembre: los 4 C que compran después (no contaminan octubre).
    for uid in c_users[2:5]:
        _tx_susc(subs_c[uid], 60_000, "DATE '2026-11-05'")
    _tx_susc(subs_c[c_users[5]], 40_000, "DATE '2026-11-05'")

    # Las 5 transacciones de prueba de octubre: deben quedar FUERA de todo.
    for sid in subs_test:
        _tx_susc(sid, 50_000, "DATE '2026-10-15'")

    # Egreso sin referencia: caso ambiguo que SÍ se cuenta.
    _tx_egreso(100_000, "DATE '2026-10-20'")

    # ── Bazar: 1 pedido real + 1 pedido de prueba, ambos de octubre ──
    producto_id = _uno(db, """
        INSERT INTO productos (tenant_id, nombre, precio, stock, activo)
        VALUES (:tid, 'Polera Fixture', 10000, 10, true)
        RETURNING id
    """, tid=tenant_id)
    for uid, total in ((a_users[0], 10_000), (test_users[0], 5_000)):
        _ejecutar(db, """
            INSERT INTO pedidos (tenant_id, alumno_id, producto_id, cantidad,
                                 total, estado, fecha_pedido, origen_pago)
            VALUES (:tid, :uid, :pid, 1, :total, 'entregado',
                    TIMESTAMPTZ '2026-10-15 12:00:00+00', 'manual')
        """, tid=tenant_id, uid=uid, pid=producto_id, total=total)

    # ── Clases / reservas: asistencia real de cohortes y del mes ──
    disciplina_id = _uno(db, """
        INSERT INTO disciplinas (tenant_id, nombre, es_open_box,
                                 requiere_coach, activo)
        VALUES (:tid, 'CrossFit Fixture', false, true, true)
        RETURNING id
    """, tid=tenant_id)
    horario_id = _uno(db, """
        INSERT INTO horarios (tenant_id, disciplina_id, dia_semana,
                              hora_inicio, hora_fin, cupo_maximo, activo)
        VALUES (:tid, :did, 0, '10:00', '11:00', 20, true)
        RETURNING id
    """, tid=tenant_id, did=disciplina_id)

    def _clase(fecha_sql, asistentes):
        return _uno(db, f"""
            INSERT INTO clases (tenant_id, horario_base_id, disciplina_id,
                                fecha, hora_inicio, hora_fin, cupo_maximo,
                                asistentes_confirmados, cancelada)
            VALUES (:tid, :hid, :did, {fecha_sql}, '10:00', '11:00', 20,
                    :asistentes, false)
            RETURNING id
        """, tid=tenant_id, hid=horario_id, did=disciplina_id,
            asistentes=asistentes)

    clase_a = _clase("(now() - interval '120 days')::date + 10", 4)
    clase_b = _clase("(now() - interval '90 days')::date + 10", 5)
    clase_mes = _clase("DATE '2026-10-15'", 10)

    def _reserva(clase_id, uid, asistio):
        _ejecutar(db, """
            INSERT INTO reservas (tenant_id, clase_id, alumno_id, asistio,
                                  tokens_gastados, estado)
            VALUES (:tid, :cid, :uid, :asistio, 0, 'confirmada')
        """, tid=tenant_id, cid=clase_id, uid=uid, asistio=asistio)

    for i, uid in enumerate(a_users):
        _reserva(clase_a, uid, i == 0)
    for i, uid in enumerate(b_users):
        _reserva(clase_b, uid, i < 3)

    # Asistencia real de octubre: 6 true / 10 confirmadas.
    for uid in c_users[:3]:
        _reserva(clase_mes, uid, True)
    for uid in a_users[:3]:
        _reserva(clase_mes, uid, True)
    _reserva(clase_mes, a_users[3], False)
    for uid in b_users[:3]:
        _reserva(clase_mes, uid, False)

    # Una asistencia de una cuenta es_prueba: el conteo real debe ignorarla.
    _reserva(clase_mes, test_users[0], True)

    def _label(dias):
        return _uno(db, (
            "SELECT to_char(date_trunc('month', now() - interval "
            f"'{int(dias)} days'), 'YYYY-MM')"))

    return {
        "tenant_id": tenant_id,
        "plan_prueba": plan_prueba,
        "plan_40": plan_40,
        "plan_60": plan_60,
        "plan_test": plan_test,
        "plan_renovacion": plan_renovacion,
        "miembro_comprador": miembro_comprador,
        "sub_renovacion": sub_renovacion,
        "a_users": a_users,
        "b_users": b_users,
        "c_users": c_users,
        "test_users": test_users,
        "rechazados": rechazados,
        "bajas": bajas,
        "subs_a": subs_a,
        "subs_b": subs_b,
        "subs_c": subs_c,
        "subs_test": subs_test,
        "subs_rechazados": subs_rechazados,
        "cohorte_4": _label(120),
        "cohorte_5": _label(90),
        "cohorte_6": _label(60),
        "clase_mes": clase_mes,
    }
