"""Vencimiento de planes: el día de `fecha_expiracion` vale COMPLETO, en hora de CHILE.

Qué fija este archivo
---------------------
Regla del negocio (bug real del 30/09): un plan vale hasta las 23:59:59 del último día del mes,
hora de Chile. El 30/09 un plan de septiembre SIGUE VIGENTE; recién desde las 00:00 del 01/10 está
vencido.

Lo que estaba roto y acá no puede volver:

  * el correo del último día (`send_alerta_urgencia_renovacion`, job de las 06:00 CLT) decía
    "¡tu plan ha expirado!" / "ha caducado" la mañana del día en que el plan todavía servía;
  * la vigencia se decidía por INSTANTE (`fecha_expiracion > datetime.now(timezone.utc)`): con las
    fechas guardadas a las 23:59 UTC (20:59 CLT) el alumno quedaba sin plan las últimas 3 horas de
    su último día (no podía reservar a las 21:00 del 30/09 con su plan de septiembre);
  * el "hoy" salía de la TZ del proceso (`date.today()`) o de la sesión de Postgres
    (`columna::date`, UTC en Neon), así que entre las 21:00 y las 23:59 CLT —y con las filas
    guardadas como `01/10 02:59+00` de un plan que vence el 30/09— el día corría un lugar.

  A. PURAS (sin BD): la regla hora por hora (08:00 / 21:00 / 23:30 vigente, 00:01 del día
     siguiente vencido), el fin de mes que se ESCRIBE (23:59:59 de Chile, en los dos husos del
     año), el texto del correo del último día, la fecha mostrada en los correos y el criterio del
     job de urgencia.
  B. CONTRA TEST (solo lee): el cast del día chileno y el predicado ORM evaluados por Postgres,
     contra literales `timestamptz` (no escribe ni una fila). El job que marca `vencido` ya tiene
     su propia cobertura contra TEST en `test_mantenimiento_vencidos.py`.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_vigencia_plan_chile.py -q
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import literal_column, select, text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.estados import dia_chile, vigente_hoy                          # noqa: E402
from app.models.suscripcion import Suscripcion                               # noqa: E402
from app.utils.santiago import (SANTIAGO, dias_para_vencer, fecha_chile,     # noqa: E402
                                fin_de_mes_chile, hoy_santiago, vigente_el_dia)
from shared import estados                                                   # noqa: E402

# El caso del bug: un plan de septiembre.
DIA_VENCIMIENTO = date(2026, 9, 30)
# Dos formas REALES de guardar el MISMO día de vencimiento (las dos dan 30/09 en Chile):
FORMA_VIEJA = datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc)  # 20:59 CLT (filas legado)
FORMA_NUEVA = fin_de_mes_chile(DIA_VENCIMIENTO)                       # 23:59:59 CLT (lo que se escribe)


def _a_las(horas: int, minutos: int, dia: date = DIA_VENCIMIENTO) -> datetime:
    """Un instante en hora de Chile: ese día a esa hora."""
    return datetime(dia.year, dia.month, dia.day, horas, minutos, tzinfo=SANTIAGO)


# ══════════════════════════════════════════════════════════════════════════════
# A. La regla, sin base de datos
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("hora", [(8, 0), (21, 0), (23, 30)])
@pytest.mark.parametrize("expira", [FORMA_VIEJA, FORMA_NUEVA])
def test_a1_el_ultimo_dia_esta_vigente_a_toda_hora(expira, hora):
    """08:00, 21:00 y 23:30 del día de vencimiento (Chile) → VIGENTE, y quedan 0 días.

    La forma vieja (`23:59:59+00` = 20:59 CLT) y la nueva (`23:59:59` de Chile) se comportan IGUAL:
    por eso las filas que ya existen no necesitan migración.
    """
    ahora = _a_las(*hora)
    assert vigente_el_dia(expira, ahora=ahora) is True
    assert dias_para_vencer(expira, ahora=ahora) == 0


def test_a2_a_las_21_de_chile_en_utc_ya_es_manana():
    """El reloj que confundía a los jobs: 21:00 CLT del 30/09 = 01/10 00:00 UTC."""
    ahora = _a_las(21, 0)
    assert ahora.astimezone(timezone.utc).date() == date(2026, 10, 1)   # en UTC: mañana
    assert ahora.date() == DIA_VENCIMIENTO                             # en Chile: el día del plan
    assert vigente_el_dia(FORMA_NUEVA, ahora=ahora) is True
    assert vigente_el_dia(FORMA_VIEJA, ahora=ahora) is True


def test_a3_desde_las_0001_del_dia_siguiente_esta_vencido():
    """Recién el 01/10 a las 00:01 (Chile) el plan de septiembre está vencido."""
    siguiente = _a_las(0, 1, dia=DIA_VENCIMIENTO + timedelta(days=1))
    for expira in (FORMA_VIEJA, FORMA_NUEVA):
        assert vigente_el_dia(expira, ahora=siguiente) is False
    assert dias_para_vencer(FORMA_NUEVA, ahora=siguiente) == 0   # 0 = "ya venció", nunca negativo


def test_a4_sin_fecha_no_esta_vigente():
    """`None` → False (espejo del NULL del SQL: un NULL no pasa el `>=`)."""
    assert vigente_el_dia(None, ahora=_a_las(12, 0)) is False
    assert dias_para_vencer(None) is None


def test_a5_el_fin_de_mes_se_escribe_a_las_2359_de_chile_en_los_dos_husos():
    """`fin_de_mes_chile()` = 23:59:59 de Chile: -04 en invierno y -03 con horario de verano.

    Antes se guardaba `datetime.now(timezone.utc).replace(hour=23)` (= 20:59 CLT) y el último día
    del plan terminaba tres horas antes de lo que dice la regla.
    """
    julio = fin_de_mes_chile(date(2026, 7, 15))
    septiembre = fin_de_mes_chile(date(2026, 9, 15))

    assert (julio.utcoffset(), julio.strftime("%H:%M:%S")) == (timedelta(hours=-4), "23:59:59")
    assert (septiembre.utcoffset(), septiembre.strftime("%H:%M:%S")) == (timedelta(hours=-3), "23:59:59")
    assert julio.date() == date(2026, 7, 31) and septiembre.date() == DIA_VENCIMIENTO
    # El día CHILENO de lo escrito es el último del mes (y no el 01/10 que veía UTC).
    assert fecha_chile(julio) == date(2026, 7, 31)
    assert fecha_chile(septiembre) == DIA_VENCIMIENTO
    assert FORMA_NUEVA.astimezone(timezone.utc).date() == date(2026, 10, 1)


def test_a6_la_fecha_de_los_correos_se_muestra_en_dia_de_chile():
    """`formatear_fecha_es()` de un `timestamptz` = el día chileno (antes decía 1 de octubre)."""
    from app.services.email_service import formatear_fecha_es

    assert formatear_fecha_es(FORMA_NUEVA) == "30 de septiembre de 2026"
    assert formatear_fecha_es(FORMA_VIEJA) == "30 de septiembre de 2026"
    assert formatear_fecha_es(DIA_VENCIMIENTO) == "30 de septiembre de 2026"   # un `date` pasa igual


def test_a7_el_correo_del_ultimo_dia_avisa_que_vence_hoy_y_no_que_vencio(monkeypatch):
    """El texto del aviso del último día: "vence HOY a las 23:59", nunca "expirado"/"caducado".

    Es el bug reportado del 30/09: el correo del job de las 06:00 CLT decía que el plan ya había
    expirado cuando todavía era vigente hasta las 23:59.
    """
    from app.services import email_service as correo

    capturado = {}

    def _falso_enviar(destinatario, asunto, html, *args, **kwargs):
        capturado.update(asunto=asunto, html=html)
        return True

    monkeypatch.setattr(correo, "_enviar", _falso_enviar)
    assert correo.send_alerta_urgencia_renovacion("Ana", "ana@test.cl") is True

    texto = (capturado["asunto"] + " " + capturado["html"]).lower()
    assert "vence hoy a las 23:59" in texto
    for prohibido in ("ha expirado", "ha caducado", "venció", "expirado"):
        assert prohibido not in texto, f"el aviso del último día no puede decir {prohibido!r}"


class SesionFalsa:
    """Sesión mínima: captura `(SQL, params)` y no devuelve filas (así no manda correos)."""

    def __init__(self):
        self.consultas = []

    def execute(self, sentencia, params=None):
        self.consultas.append((str(sentencia), dict(params or {})))
        return self

    def fetchall(self):
        return []

    def commit(self):
        pass


def test_a8_el_job_de_urgencia_apunta_al_dia_chileno_de_vencimiento():
    """El job "planes que vencen HOY" (06:00 CLT) busca la `fecha_expiracion` de HOY en Chile."""
    from app.services.alertas_email_service import (enviar_alertas_renovacion,
                                                    enviar_alertas_urgencia)

    db = SesionFalsa()
    enviar_alertas_urgencia(db)
    sql, params = db.consultas[0]
    assert params["target"] == hoy_santiago().isoformat()
    assert "(s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date = :target" in sql
    assert "s.fecha_expiracion::date" not in sql          # el `::date` de la sesión ya no se usa

    db = SesionFalsa()
    enviar_alertas_renovacion(db, dias_aviso=3)
    _, params = db.consultas[0]
    assert params["target"] == (hoy_santiago() + timedelta(days=3)).isoformat()


def test_a9_el_predicado_orm_compara_dias_chilenos():
    """`vigente_hoy()` compila con `timezone('America/Santiago', …)::date` y el día inyectado."""
    consulta = select(vigente_hoy(Suscripcion.fecha_expiracion, hoy=date(2026, 9, 30)))
    sql = str(consulta.compile(compile_kwargs={"literal_binds": True}))
    assert "timezone('America/Santiago', suscripciones.fecha_expiracion)" in sql
    assert sql.count("date(timezone(") == 1
    assert ">= '2026-09-30'" in sql


def test_a10_el_sql_compartido_cuenta_el_dia_en_chile():
    """El predicado de las métricas/histórico usa el cast de Chile y HOY en Chile por defecto."""
    assert estados.ZONA_CHILE == "America/Santiago"
    assert estados.sql_hoy_chile() == "(now() AT TIME ZONE 'America/Santiago')::date"
    for alias in ("s", "s2"):
        sql = estados.sql_suscripcion_vigente(alias)
        assert f"({alias}.fecha_inicio AT TIME ZONE 'America/Santiago')::date <= " in sql
        assert f"({alias}.fecha_expiracion AT TIME ZONE 'America/Santiago')::date >= " in sql
        assert f"{alias}.fecha_expiracion::date" not in sql   # el `::date` de la sesión, jamás


# ══════════════════════════════════════════════════════════════════════════════
# B. Contra TEST (solo lee: literales, ninguna fila)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


def test_b1_postgres_da_el_dia_chileno_y_el_de_la_sesion_difiere(db):
    """La MISMA fila: día chileno 30/09 vs `::date` de la sesión (UTC) 01/10 — el bug."""
    filas = db.execute(select(
        dia_chile(literal_column("v.exp")),
        literal_column("(v.exp)::date"),
    ).select_from(text(
        "(VALUES (timestamptz '2026-09-30 23:59:59+00'), "
        "(timestamptz '2026-10-01 02:59:59+00')) AS v(exp)"))).all()

    assert [tuple(f) for f in filas] == [
        (date(2026, 9, 30), date(2026, 9, 30)),    # forma vieja: 20:59 CLT del 30/09
        (date(2026, 9, 30), date(2026, 10, 1)),    # forma nueva: 23:59:59 CLT del 30/09
    ]


def test_b2_el_predicado_dice_vigente_el_ultimo_dia_y_vencido_al_siguiente(db):
    """Las cuatro esquinas, evaluadas por Postgres (el `::date` de la sesión erraría dos)."""
    exp = literal_column("v.exp")
    filas = db.execute(select(
        vigente_hoy(exp, hoy=date(2026, 9, 30)),        # el día del plan
        vigente_hoy(exp, hoy=date(2026, 10, 1)),        # el día siguiente
    ).select_from(text(
        "(VALUES (timestamptz '2026-09-30 23:59:59+00'), "
        "(timestamptz '2026-10-01 02:59:59+00')) AS v(exp)"))).all()

    assert [tuple(f) for f in filas] == [(True, False), (True, False)]


def test_b3_el_predicado_orm_corre_contra_la_tabla_real(db):
    """`vigente_hoy(Suscripcion.fecha_expiracion)` es SQL válido sobre la tabla real (lee, no escribe)."""
    from sqlalchemy import func

    total = db.query(func.count(Suscripcion.id)).filter(
        Suscripcion.estado == "activo",
        vigente_hoy(Suscripcion.fecha_expiracion, hoy=date(2026, 9, 30)),
    ).scalar()
    assert isinstance(total, int) and total >= 0


