"""`monthly_kpis.alumnos_activos_inicio`: el número de un mes CERRADO ya no depende de HOY.

Bug corregido (2026-10-01)
--------------------------
`_upsert_mes_monthly` (POST /kpis/populate/monthly) calculaba "cuántos alumnos había al abrir el
mes" con

    Suscripcion.estado == "activo"  AND  fecha_inicio <= inicio  AND  fecha_expiracion >= inicio

y `estado` es el estado de HOY: apenas vencían las suscripciones de ese mes, el mes YA CERRADO
pasaba a 0. Medido en TEST: los 12 meses del backfill daban 0, y por eso `GET
/kpis/estacionalidad` publicaba la serie de alumnos como NO disponible (`disponible: false` + el
motivo del fix anterior, que sólo tapaba el síntoma en la UI). El mismo 0 se llevaba puesto
`frecuencia_semanal` (divide por `alumnos_activos_inicio`).

Ahora el conteo es `metricas_service.alumnos_vigentes(db, tenant_id, inicio)`: la MISMA
definición que la cohorte de retención (`_vigente_sql` = `shared.estados.sql_suscripcion_vigente()`
+ `sql_plan_comercial()`), evaluada EN LA FECHA del corte. Una suscripción `vencido` HOY cuenta
para los meses en los que SÍ estaba vigente, y el "Pase de regreso" no cuenta nunca (da acceso
pero no es cliente).

Lo que fija este test (contra TEST: escribe y RESTAURA)
------------------------------------------------------
El escenario es exactamente el que fallaba: un alumno con plan COMERCIAL cuya suscripción cubrió
TODO el mes pasado y HOY está vencida (`estado = 'vencido'`).

  * con el criterio viejo, ese mes daba 0 (su estado no es `activo`);
  * con el nuevo, el mes pasado cuenta al escenario.

El teardown borra el escenario y RE-CALCULA el mes, así la fila de `monthly_kpis` queda con el
valor que tenía antes de correr el test.

Correr:
    py -3.12 -m pytest tests/test_kpis_alumnos_activos_inicio.py -q
"""
import sys
from datetime import date, datetime, time as _time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import kpis_populate as kp                                  # noqa: E402
from app.core.config import settings                                        # noqa: E402
from app.models.monthly_kpis import MonthlyKpi                              # noqa: E402
from app.utils.santiago import SANTIAGO                                     # noqa: E402

TENANT_ID = 1


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(revisa .env.test / ENVIRONMENT)")
    print("\n[OK] base de datos de TEST confirmada\n")
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def escenario(db):
    """Alumno con plan COMERCIAL que cubrió TODO el mes pasado y HOY está vencido.

    Es el caso que dejaba el mes en 0: el run del día 1 marca `vencido`, así que `estado` ya no
    es `activo`, pero las FECHAS de la suscripción cubren el mes pasado completo.
    """
    hoy = date.today()
    fin_mes = hoy.replace(day=1) - timedelta(days=1)    # último día del mes pasado
    ini_mes = fin_mes.replace(day=1)                    # primer día del mes pasado
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    correo = f"alumnos.inicio.{sufijo}@test.local"
    alumno_id = plan_id = None
    try:
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                                  estado, created_at)
            VALUES (:t, :r, 'Alumno Inicio Mes TEST', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"97{sufijo[-8:]}-7", "c": correo,
             "alta": datetime.combine(ini_mes - timedelta(days=30), _time(12, 0), tzinfo=SANTIAGO)}
        ).scalar()

        plan_id = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 12, false, :p, 30, true, true) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Mensual Inicio Mes TEST {sufijo}", "p": 30000}).scalar()

        db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, CAST('vencido' AS estado_suscripcion), 12, 0, :i, :f)"""),
            {"t": TENANT_ID, "u": alumno_id, "p": plan_id,
             "i": datetime.combine(ini_mes, _time(0, 0), tzinfo=SANTIAGO),
             "f": datetime.combine(fin_mes, _time(23, 59), tzinfo=SANTIAGO)})
        db.commit()
        yield {"alumno_id": alumno_id, "plan_id": plan_id, "correo": correo,
               "inicio_mes": ini_mes, "fin_mes": fin_mes}
    finally:
        db.rollback()
        try:
            db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"),
                       {"a": alumno_id})
            if plan_id:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
            if alumno_id:
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
            db.commit()
            if alumno_id:
                # La fila del mes se recalcula SIN el escenario: queda como estaba antes.
                kp._upsert_mes_monthly(db, TENANT_ID, ini_mes.year, ini_mes.month)
        except Exception as e:      # el borrado no debe tapar el fallo real del test
            db.rollback()
            print(f"\n[WARN] no se pudo limpiar el escenario: {e}")


def test_a_un_mes_pasado_cuenta_aunque_hoy_la_suscripcion_este_vencida(db, escenario):
    """El mes pasado cuenta al escenario aunque su `estado` de HOY ya sea `vencido`.

    Se mide como DELTA (con y sin el escenario vigente en ese mes): la base de TEST ya trae meses
    con alumnos, así que un número suelto no probaría nada.
    """
    ini = escenario["inicio_mes"]
    fin = escenario["fin_mes"]

    # 1) El escenario es el que dice el nombre: cubrió el mes pasado COMPLETO y su estado de HOY
    #    ya no es `activo` — eso es lo que hacía que el mes quedara en 0.
    vigente_ese_mes, es_activo_hoy = db.execute(text(
        "SELECT ((s.fecha_inicio AT TIME ZONE 'America/Santiago')::date <= :ini"
        "        AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date >= :fin),"
        "       s.estado = 'activo'"
        " FROM suscripciones s WHERE s.usuario_id = :u"),
        {"u": escenario["alumno_id"], "ini": ini, "fin": fin}).first()
    assert (vigente_ese_mes, es_activo_hoy) == (True, False)

    # 2) Con el escenario vigente en el mes, el conteo del mes lo incluye.
    con = kp._upsert_mes_monthly(db, TENANT_ID, ini.year, ini.month)
    assert con["valores"]["alumnos_activos_inicio"] >= 1

    # 3) El MISMO mes sin el escenario (sus fechas se corren a un mes viejo): exactamente uno
    #    menos. Con el criterio viejo (`estado == 'activo'`) los dos números eran IGUALES: una
    #    suscripción `vencido` no contaba nunca, ni siquiera en los meses en que estuvo vigente.
    db.execute(text("UPDATE suscripciones SET fecha_inicio = :i, fecha_expiracion = :f"
                    " WHERE usuario_id = :u"),
               {"u": escenario["alumno_id"],
                "i": datetime.combine(ini - timedelta(days=60), _time(0, 0), tzinfo=SANTIAGO),
                "f": datetime.combine(ini - timedelta(days=40), _time(23, 59), tzinfo=SANTIAGO)})
    db.commit()
    sin = kp._upsert_mes_monthly(db, TENANT_ID, ini.year, ini.month)
    assert sin["valores"]["alumnos_activos_inicio"] == (
        con["valores"]["alumnos_activos_inicio"] - 1)

    # 4) La fila del mes queda con el último cálculo (lo que leen la pestaña Mensual y el BI).
    fila = db.query(MonthlyKpi).filter(
        MonthlyKpi.tenant_id == TENANT_ID,
        MonthlyKpi.year == ini.year, MonthlyKpi.month == ini.month,
    ).one()
    assert fila.alumnos_activos_inicio == sin["valores"]["alumnos_activos_inicio"]
