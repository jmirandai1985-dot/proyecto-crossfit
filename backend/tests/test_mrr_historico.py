"""MRR y churn HISTÓRICOS: la vigencia la deciden las FECHAS, no el estado de hoy (2026-09-27).

Bug corregido: `mrr_mes_anterior` (y la cohorte de retención de 30 días) miraban las suscripciones
`estado = 'activo'`, que es el estado de **hoy**. Vencida una suscripción hoy (pasa a `vencido`),
desaparecía también de las fechas PASADAS en las que sí estuvo vigente, así que:

  * el MRR de referencia (último día del mes anterior) bajaba y `variacion_mrr_pct` cambiaba sin que
    hubiera pasado nada en el negocio;
  * la base de la cohorte de retención de hace 30 días perdía al alumno y el churn del correo se
    movía solo, con cada vencimiento.

Ahora la vigencia en una fecha es `shared.estados.sql_suscripcion_vigente()`: el MISMO predicado en
la app (`app/services/metricas_service.py`) y en el SQL del job
(`maintenance/mantenimiento_cloud.py`). Con una excepción EXPLÍCITA: una suscripción que NUNCA
estuvo vigente (`pendiente`, `rechazado`) no suma en ninguna fecha, aunque sus fechas caigan dentro
de la ventana (por eso el predicado no es "cualquier fecha que cubra el día", que contaría también
lo rechazado).

Los dos casos que este test fija (pedido del negocio):

  1. vencer una suscripción HOY no cambia el MRR de los meses pasados (el de hoy sí: deja de estar
     vigente);
  2. una rechazada no suma nunca, ni con una ventana que la cubra.

Sin red y sin base: el SQL se captura con una sesión doble y la vigencia por fecha se evalúa con la
spec de Python de más abajo, que usa la MISMA lista (`ESTADOS_SUSCRIPCION_NUNCA_VIGENTES`).

Se corre con:
    py -3.12 -m pytest tests/test_mrr_historico.py -q --noconftest
"""
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services import metricas_service as metricas  # noqa: E402
from shared import estados  # noqa: E402

TENANT = 1
HOY = date(2026, 10, 1)
FIN_MES_ANTERIOR = date(2026, 9, 30)      # el MRR de referencia: último día del mes anterior
HACE_30 = date(2026, 9, 1)


def vigente_en(estado, inicio, expiracion, fecha) -> bool:
    """¿Estaba vigente EN ESA FECHA? — la regla de negocio que el SQL tiene que implementar.

    Es la spec del predicado, no una copia del SQL: la lista de estados que nunca fueron vigentes se
    lee de `shared.estados` (una sola definición) y las fechas se comparan inclusivas, igual que el
    `::date` del SQL (una suscripción que vence el último día del mes cuenta ese día).
    """
    if estado in estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES:
        return False
    return inicio <= fecha <= expiracion


class SesionFalsa:
    """Sesión mínima para el lado app: guarda `(SQL, params)` y devuelve valores de una cola.

    No hay base ni red: lo que se verifica es QUÉ consulta se arma (predicado y parámetros), que es
    donde vivía el bug.
    """

    def __init__(self, *valores):
        self.valores = list(valores)
        self.consultas = []

    def execute(self, sentencia, params=None):
        self.consultas.append((str(sentencia), dict(params or {})))
        return self

    def scalar(self):
        return self.valores.pop(0) if self.valores else 0


# ── A. El predicado: uno solo, armado con la lista de "nunca vigentes" ──────────────────────────
def test_a_el_predicado_se_arma_con_la_lista_de_nunca_vigentes():
    """`sql_suscripcion_vigente()` no puede volver a `estado = 'activo'` ni a una fecha fija: el
    alias y la fecha son parámetros, así que la MISMA definición sirve para hoy, para el último día
    del mes anterior y para hace 30 días."""
    assert estados.sql_suscripcion_vigente() == (
        "s.estado NOT IN (" + estados.lista_sql(estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES) + ")"
        " AND (s.fecha_inicio AT TIME ZONE 'America/Santiago')::date"
        " <= (now() AT TIME ZONE 'America/Santiago')::date"
        " AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date"
        " >= (now() AT TIME ZONE 'America/Santiago')::date")
    assert estados.sql_suscripcion_vigente("s", "'{fin_ant}'::date") == (
        "s.estado NOT IN ('pendiente', 'rechazado')"
        " AND (s.fecha_inicio AT TIME ZONE 'America/Santiago')::date <= '{fin_ant}'::date"
        " AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date >= '{fin_ant}'::date")
    assert estados.sql_suscripcion_vigente("s2", ":hasta") == (
        "s2.estado NOT IN ('pendiente', 'rechazado')"
        " AND (s2.fecha_inicio AT TIME ZONE 'America/Santiago')::date <= :hasta"
        " AND (s2.fecha_expiracion AT TIME ZONE 'America/Santiago')::date >= :hasta")

    assert estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES == ("pendiente", "rechazado")
    assert estados.ESTADOS_SUSCRIPCION_VIGENTES == ("activo", "vencido")


# ── B. Caso 1: vencer HOY no reescribe el MRR del pasado ────────────────────────────────────────
def test_b_vencer_una_suscripcion_hoy_no_cambia_el_mrr_de_los_meses_pasados():
    """La foto del último día del mes anterior no depende del estado de hoy."""
    vencida = ("vencido", date(2026, 8, 1), FIN_MES_ANTERIOR)   # venció ayer: hoy ya no está vigente

    assert vigente_en(*vencida, FIN_MES_ANTERIOR) is True       # el mes pasado SÍ estaba vigente
    assert vigente_en(*vencida, HOY) is False                   # y hoy ya no
    assert vigente_en("activo", date(2026, 8, 1), date(2027, 1, 1), HOY) is True

    # El lado app: `mrr()` es UNA consulta de fecha (el pasado y hoy comparten el SQL; sólo cambia
    # `hasta`), y el estado que mira es el de "nunca vigente", no el de hoy.
    del_mes_anterior = SesionFalsa(45000)
    de_hoy = SesionFalsa(60000)
    previo = metricas.mrr(del_mes_anterior, TENANT, FIN_MES_ANTERIOR)
    ahora = metricas.mrr(de_hoy, TENANT, HOY)

    sql_previo, params_previo = del_mes_anterior.consultas[0]
    sql_hoy, params_hoy = de_hoy.consultas[0]

    assert sql_previo == sql_hoy, "el MRR del pasado no puede tener una consulta distinta"
    assert estados.sql_suscripcion_vigente("s", ":hasta") in sql_previo
    assert "estado = 'activo'" not in sql_previo
    assert params_previo == {"tid": TENANT, "hasta": FIN_MES_ANTERIOR}
    assert params_hoy == {"tid": TENANT, "hasta": HOY}
    assert (previo, ahora) == (45000.0, 60000.0)


# ── C. Caso 2: lo que nunca estuvo vigente no suma nunca ────────────────────────────────────────
def test_c_una_rechazada_o_pendiente_no_suma_nunca():
    """Aunque la ventana de fechas la cubra: `pendiente`/`rechazado` no son "vigente" en ninguna
    fecha (al invertir el filtro se colarían por tener fechas). El literal del enum es `rechazado`
    (con `o`): los labels vienen de `estado_suscripcion` y los fija test_g del test compartido."""
    cubre_el_mes_anterior = (date(2026, 8, 1), FIN_MES_ANTERIOR)

    for estado in estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES:
        assert vigente_en(estado, *cubre_el_mes_anterior, FIN_MES_ANTERIOR) is False, estado
        assert vigente_en(estado, *cubre_el_mes_anterior, HOY) is False, estado

    # Y una que todavía no empieza tampoco cuenta (fecha_inicio > fecha).
    assert vigente_en("activo", date(2026, 10, 15), date(2027, 1, 15), HOY) is False


# ── D. Retención/churn de 30 días: la cohorte también es por fecha ──────────────────────────────
def test_d_el_churn_de_la_cohorte_de_30_dias_no_depende_del_estado_de_hoy():
    """Las DOS consultas de la cohorte (base de hace 30 días y "siguen vigentes") usan el mismo
    predicado de fecha: la base no puede encogerse porque hoy venció una suscripción."""
    sesion = SesionFalsa(40, 36)          # base 40 (hace 30 días), 36 siguen hoy
    retencion, base = metricas.retencion_cohorte(sesion, TENANT, HACE_30, HOY)

    sql_base, params_base = sesion.consultas[0]
    sql_siguen, params_siguen = sesion.consultas[1]

    assert (retencion, base) == (90, 40)                       # 36/40 ⇒ 90 %, churn 10 %
    assert metricas.churn_desde_retencion(retencion) == 10.0
    assert estados.sql_suscripcion_vigente("s", ":desde") in sql_base
    assert estados.sql_suscripcion_vigente("s2", ":hasta") in sql_siguen
    assert "estado = 'activo'" not in sql_base + sql_siguen
    assert params_base == {"tid": TENANT, "desde": HACE_30}
    assert params_siguen == {"tid": TENANT, "desde": HACE_30, "hasta": HOY}

    # Con base chica el churn sigue sin publicarse (el umbral no cambió con este fix).
    assert metricas.retencion_cohorte(SesionFalsa(2), TENANT, HACE_30, HOY) == (None, 2)
    assert metricas.churn_desde_retencion(None) is None
