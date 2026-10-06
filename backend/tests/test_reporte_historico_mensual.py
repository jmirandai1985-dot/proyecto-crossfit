"""El Excel de /reportes/export: el MRR de cada mes es el de `metricas_service` (una sola versión).

Bug corregido (2026-09-27, el mismo del correo de mantenimiento): la tabla "Historico Mensual" se
calculaba su PROPIA copia del MRR por mes

    WHERE s.tenant_id = :tid AND s.estado = 'activo' AND s.fecha_expiracion >= :fin

y la columna "Alumnos activos fin de mes" con el mismo filtro. Le faltaban las dos cosas que
definen la vigencia EN UNA FECHA:

  * `fecha_inicio <= :fin`: una suscripción que empieza el mes que viene sumaba al mes pasado;
  * las fechas en vez del estado: `estado = 'activo'` es el estado de HOY, así que una suscripción
    vencida hoy desaparecía también de los meses YA CERRADOS en los que sí estuvo vigente (el mes
    del Excel cambiaba según el día en que se descargaba).

Ahora:
  * el MRR de cada mes es `metricas_service.mrr(db, tenant_id, corte_del_mes)`: la MISMA función del
    dashboard (`app/api/v1/reportes.py`) y del BI (`kpis_populate.py`, que persiste el mes cerrado con
    el mismo `fin`), así que no hay una tercera versión del número; el corte lo define
    `reportes_service._corte_suscripciones` (el último día del mes; HOY en el mes EN CURSO);
  * la columna de alumnos usa `shared.estados.sql_suscripcion_vigente("s", ":corte")`;
  * la tarjeta KPI "MRR" del Resumen Ejecutivo (que también tenía su copia del SQL, con la fecha del
    día) pasa a ser `metricas_service.mrr` con el corte del MES ELEGIDO, el MISMO corte que la celda
    de "Historico Mensual" de ese mes, así la tarjeta y la tabla del propio archivo no pueden mostrar
    números distintos. Si el mes elegido es el EN CURSO, el corte es HOY (como el dashboard) y la
    etiqueta lo dice: "MRR al 28/09/2026".

Los casos que fija este test (los pedidos de la tarea):
  1. el MRR de un mes pasado del export COINCIDE con `metricas_service.mrr` para la misma fecha;
  2. vencer una suscripción HOY no lo altera;
  3. la tarjeta KPI de MRR es el corte del mes elegido (el de la celda de "Historico Mensual" del
     mismo mes) y su etiqueta dice la fecha del corte; con el mes EN CURSO, la fecha es HOY.

Sin red y sin base: el .xlsx se genera DE VERDAD (con una sesión doble que guarda `(SQL, params)` y,
para las consultas que usan el predicado compartido, evalúa el SQL capturado contra filas de fixture)
y después se lee: la celda de MRR del mes pasado de la hoja "Historico Mensual" y la tarjeta del KPI.
Por eso una regresión en el predicado o en la fecha del corte se ve como un número distinto.

Se corre con:
    py -3.12 -m pytest tests/test_reporte_historico_mensual.py -q --noconftest
"""
import calendar
import inspect
import re
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services import metricas_service as metricas  # noqa: E402
from app.services import reportes_service as rep  # noqa: E402
from app.utils.santiago import hoy_santiago  # noqa: E402  (el "hoy" de Chile)
from shared import estados  # noqa: E402

TENANT = 7

# Precios = la única marca de cada fila de fixture (el precio es lo que suma al MRR si la fila
# cuenta al corte del mes pasado).
PRECIO_VENCIO_AYER = 45000          # venció el último día del mes pasado ⇒ ese mes SÍ contaba
PRECIO_VIGENTE_LARGA = 30000        # sigue vigente
PRECIO_RECHAZADA = 99000            # nunca suma, aunque sus fechas cubran el mes
PRECIO_EMPIEZA_DESPUES = 60000      # empieza el mes que viene ⇒ no estaba vigente al corte
PRECIO_VENCIO_ANTES = 70000         # venció antes del corte ⇒ no estaba vigente al corte
PRECIO_EMPIEZA_MANANA = 80000       # arranca MAÑANA ⇒ no cuenta hoy (sí al "cierre" del mes en curso)

MRR_MES_PASADO = PRECIO_VENCIO_AYER + PRECIO_VIGENTE_LARGA
ALUMNOS_MES_PASADO = 2
# HOY: la que venció en el corte del mes pasado ya no cuenta, y la que arranca este mes sí.
MRR_HOY = PRECIO_VIGENTE_LARGA + PRECIO_EMPIEZA_DESPUES


def _arranca_manana() -> bool:
    """¿Mañana todavía cae dentro del mes en curso? (si hoy es el último día, no hay días que falten)."""
    hoy = datetime.now(timezone.utc).date()
    return (hoy + timedelta(days=1)).month == hoy.month


def _mrr_al_cierre_del_mes_en_curso() -> float:
    """El MRR con el corte del ÚLTIMO DÍA de este mes: distinto del de hoy por la fila que empieza
    mañana (salvo que hoy sea el último día del mes, que es cuando "cierre" y "hoy" son lo mismo).

    Es el número que saldría si el mes en curso se cortara "al cierre" —contando días que todavía no
    pasaron, adelantando suscripciones futuras—: justo lo que el test F caza.
    """
    return MRR_HOY + (PRECIO_EMPIEZA_MANANA if _arranca_manana() else 0)

Susc = namedtuple("Susc", "estado inicio expiracion precio")


def _meses_esperados() -> list:
    """Los 6 meses del Excel (año, mes, corte), con el mismo cálculo que el servicio.

    `_build_historico_mensual` toma los últimos 6 meses desde `datetime.now(timezone.utc)` y el corte
    de cada uno es el que define `reportes_service._corte_suscripciones`: el ÚLTIMO DÍA del mes (HOY
    en el mes EN CURSO, que todavía no cerró); el test recalcula lo mismo para poder afirmar la fecha.
    """
    hoy = datetime.now(timezone.utc).date()
    ahora = datetime.now(timezone.utc)
    meses = []
    for i in range(5, -1, -1):
        m = ahora.month - i
        y = ahora.year
        while m <= 0:
            m += 12
            y -= 1
        corte = date(y, m, calendar.monthrange(y, m)[1])
        if (y, m) == (hoy.year, hoy.month):
            corte = hoy                     # el mes en curso se corta a HOY (todavía no cerró)
        meses.append((y, m, corte))
    return meses


def _filas_de_ejemplo(estado_de_la_vencida: str = "vencido") -> list:
    """Las "suscripciones" de la base, con una por alumno (por eso el conteo es `len(vigentes)`).

    `estado_de_la_vencida` es el estado de HOY de la fila que vence en el corte: `vencido` (ya se
    venció) o `activo` (todavía no). El mes pasado tiene que dar lo mismo de las dos formas.

    La última fila arranca MAÑANA: hoy no cuenta, y al "cierre" del mes en curso sí (es la que separa
    el corte de HOY del corte del último día del mes).
    """
    hoy = datetime.now(timezone.utc).date()
    _, _, corte = _meses_esperados()[-2]
    principio = corte.replace(day=1)
    return [
        Susc(estado_de_la_vencida, principio, corte, PRECIO_VENCIO_AYER),
        Susc("activo", principio, date(corte.year + 1, 1, 31), PRECIO_VIGENTE_LARGA),
        Susc("rechazado", principio, date(corte.year + 1, 1, 31), PRECIO_RECHAZADA),
        Susc("activo", corte + timedelta(days=1), date(corte.year + 1, 6, 30),
             PRECIO_EMPIEZA_DESPUES),                     # arranca DESPUÉS del corte
        Susc("vencido", principio, corte.replace(day=1), PRECIO_VENCIO_ANTES),
        Susc("activo", hoy + timedelta(days=1), date(hoy.year + 1, 6, 30),
             PRECIO_EMPIEZA_MANANA),                      # arranca MAÑANA ⇒ hoy no cuenta
    ]


# ── El SQL capturado, evaluado contra las filas (sin base) ───────────────────────────────────────
_RE_NUNCA = re.compile(r"estado NOT IN \(([^)]*)\)")
_RE_INICIO = re.compile(r"fecha_inicio AT TIME ZONE '[^']+'\)::date <= ([^\s,)]+)")
_RE_FIN = re.compile(r"fecha_expiracion AT TIME ZONE '[^']+'\)::date >= ([^\s,)]+)")


def _fecha_del_operando(operando: str, params: dict) -> date:
    """La fecha con la que se compara (`:hasta`/`:fin` del binding, HOY en Chile o un literal)."""
    if operando.startswith(":"):
        valor = params[operando[1:]]
        assert isinstance(valor, date), f"{operando} no se ligó a una fecha: {valor!r}"
        return valor
    if "now() AT TIME ZONE" in operando:      # default de `sql_suscripcion_vigente`: HOY en Chile
        return hoy_santiago()
    if operando == "current_date":
        return datetime.now(timezone.utc).date()
    literal = re.fullmatch(r"'(\d{4}-\d{2}-\d{2})'(?:::date)?", operando)
    assert literal, f"fecha no reconocida en el SQL: {operando}"
    return date.fromisoformat(literal.group(1))


def evalua(sql: str, params: dict, filas: list):
    """Qué devolvería esa consulta, leída DEL PROPIO SQL capturado.

    Extrae el predicado compartido (`estado NOT IN …`, `fecha_inicio <= …`, `fecha_expiracion >= …`)
    y lo aplica a las filas. Si el SQL pierde una condición o cambia la fecha del corte, el número
    cambia: es justo lo que se quiere ver, y no puede pasar en silencio.
    """
    nunca, inicio, fin = _RE_NUNCA.search(sql), _RE_INICIO.search(sql), _RE_FIN.search(sql)
    assert nunca and inicio and fin, f"el SQL no tiene el predicado completo:\n{sql}"

    excluidos = {s.strip().strip("'") for s in nunca.group(1).split(",")}
    assert excluidos == set(estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES), excluidos

    fecha = _fecha_del_operando(inicio.group(1), params)
    assert fecha == _fecha_del_operando(fin.group(1), params), "las dos fechas del predicado difieren"
    vigentes = [f for f in filas if f.estado not in excluidos and f.inicio <= fecha <= f.expiracion]

    if "SUM(p.precio_clp)" in sql:
        return sum(f.precio for f in vigentes)
    assert "COUNT(DISTINCT u.id)" in sql, f"consulta inesperada:\n{sql}"
    return len(vigentes)


class SesionFalsa:
    """Sesión mínima: guarda `(SQL, params)` y responde las consultas HISTÓRICAS con `evalua()`.

    Sólo se evalúan las consultas que usan el predicado compartido (el MRR por mes y el conteo de
    alumnos al corte); el resto (ingresos, egresos, nuevos, bazar y el KPI vivo de "hoy") devuelve 0,
    porque lo que se verifica es QUÉ consulta se arma y con qué fecha, que es donde vivía el bug.
    """

    def __init__(self, filas=()):
        self.filas = list(filas)
        self.consultas = []

    def execute(self, sentencia, params=None):
        self.consultas.append((str(sentencia), dict(params or {})))
        return self

    def scalar(self):
        sql, params = self.consultas[-1]
        if any(estados.sql_suscripcion_vigente("s", p) in sql for p in (":corte", ":fin", ":hasta")):
            return evalua(sql, params, self.filas)
        return 0

    def fetchall(self):
        return []

    def fetchone(self):
        return None


def _consultas(sesion: SesionFalsa, fragmento: str) -> list:
    return [c for c in sesion.consultas if fragmento in c[0]]


# ── El Excel de verdad: se genera y se lee (hoja oculta "Historico Mensual" + tarjeta del KPI) ───
# "Historico Mensual": fila 1 = encabezados, filas 2..7 = los 6 meses (del más viejo al actual).
#   A Año | B Mes | C MesNum | D Ingresos | E Alumnos Activos | F Nuevos | G MRR | H Ventas | I Egresos
COL_ALUMNOS, COL_MRR = 5, 7
FILA_MES_PASADO, FILA_MES_ACTUAL = 6, 7
# Tarjeta KPI del "Resumen Ejecutivo": fila 5 = etiqueta, 6 = valor, 7 = subtítulo (col 4 = MRR).
FILA_LABEL_KPI, FILA_VALOR_KPI, COL_KPI_MRR = 5, 6, 4


def _mes_actual() -> tuple:
    """El mes del período que se exporta (mes, año)."""
    ahora = datetime.now(timezone.utc)
    return ahora.month, ahora.year


def _genera_excel(sesion: SesionFalsa, mes: int = None, anio: int = None):
    """El .xlsx real en memoria: lo que devuelve `/reportes/monthly-sales`.

    Sin argumentos exporta el mes EN CURSO (el que elige la UI por defecto); con un mes pasado, la
    tarjeta del KPI tiene que salir con el corte de ESE mes.
    """
    if mes is None or anio is None:
        mes, anio = _mes_actual()
    datos = rep.crear_reporte_ventas_mensual_bytes(sesion, TENANT, mes, anio)
    return load_workbook(BytesIO(datos))


def _celda_de_la_tarjeta(libro, fila: int):
    return libro.worksheets[0].cell(row=fila, column=COL_KPI_MRR).value


def _numero_de_la_tarjeta(libro) -> float:
    """El valor de la tarjeta KPI como número (la celda guarda el texto con formato moneda)."""
    texto = _celda_de_la_tarjeta(libro, FILA_VALOR_KPI)
    assert isinstance(texto, str) and texto.startswith("$"), texto
    return float(texto.replace("$", "").replace(",", ""))


# ── A. El MRR de cada mes sale de metricas_service, con el último día del mes ────────────────────
def test_a_el_mrr_de_cada_mes_lo_calcula_metricas_service_con_el_corte(monkeypatch):
    """El MRR del Excel no puede ser una copia propia: es `metricas_service.mrr` (la del dashboard y
    del BI) y la fecha es el corte que define `_corte_suscripciones`: el último día de cada mes (HOY
    en el mes en curso)."""
    llamadas = []

    def mrr_falso(db, tenant_id, hasta):
        llamadas.append((db, tenant_id, hasta))
        return float(hasta.day * 1000)      # valor distinto por mes: ata la columna a la llamada

    monkeypatch.setattr(metricas, "mrr", mrr_falso)

    sesion = SesionFalsa()
    historico = rep._build_historico_mensual(sesion, TENANT)
    esperados = _meses_esperados()

    assert [c[2] for c in llamadas] == [corte for _, _, corte in esperados], "fechas del corte"
    assert [c[1] for c in llamadas] == [TENANT] * 6
    assert {id(c[0]) for c in llamadas} == {id(sesion)}          # la misma sesión del Excel
    assert [(h["anio"], h["mes_num"]) for h in historico] == [(y, m) for y, m, _ in esperados]
    assert [h["mrr"] for h in historico] == [float(c.day * 1000) for _, _, c in esperados]


# ── B. Caso 1: el mes pasado del export == metricas_service para la misma fecha ──────────────────
def test_b_el_mes_pasado_del_export_coincide_con_metricas_service():
    """Caso 1, leído EN EL ARCHIVO: la celda de MRR del mes pasado de la hoja "Historico Mensual" es
    `metricas_service.mrr(db, tenant_id, ultimo_dia_del_mes_pasado)` (la del dashboard y del BI)."""
    filas = _filas_de_ejemplo()
    sesion = SesionFalsa(filas)
    libro = _genera_excel(sesion)

    _, _, corte_pasado = _meses_esperados()[-2]
    assert corte_pasado < datetime.now(timezone.utc).date(), "el corte tiene que ser del pasado"

    # El valor de la función compartida para esa fecha es el de la celda de la hoja histórica.
    valor_app = metricas.mrr(SesionFalsa(filas), TENANT, corte_pasado)
    assert valor_app == float(MRR_MES_PASADO)
    assert libro["Historico Mensual"].cell(
        row=FILA_MES_PASADO, column=COL_MRR).value == valor_app

    # Y la consulta emitida para ese mes es la MISMA del dashboard: texto y parámetros (la 1ª del
    # archivo es el KPI de "hoy", después vienen los 6 meses).
    por_fecha = {p["hasta"]: (sql, p)
                 for sql, p in _consultas(sesion, "SUM(p.precio_clp)")}
    sql_export, params_export = por_fecha[corte_pasado]
    assert params_export == {"tid": TENANT, "hasta": corte_pasado}

    sesion_app = SesionFalsa(filas)
    metricas.mrr(sesion_app, TENANT, corte_pasado)
    assert sql_export == sesion_app.consultas[0][0]
    assert params_export == sesion_app.consultas[0][1]
    assert evalua(sql_export, params_export, filas) == MRR_MES_PASADO


# ── C. Caso 2: vencer HOY no cambia el mes pasado ────────────────────────────────────────────────
@pytest.mark.parametrize("estado_de_hoy", ["activo", "vencido"])
def test_c_vencer_una_suscripcion_hoy_no_altera_el_mes_pasado(estado_de_hoy):
    """Caso 2: la fila que estaba vigente al corte del mes pasado hoy puede estar `vencido` (se venció
    ayer) o todavía `activo`. El Excel tiene que salir IGUAL: el mismo MRR y el mismo conteo en el mes
    pasado, porque esa fecha no depende del estado de hoy.

    Con el filtro viejo esto cambiaba de un día para otro: `estado = 'activo'` sacaba la fila del mes
    pasado en cuanto pasaba a `vencido` (contra la base: 75.000 ⇒ 30.000 y los alumnos 2 ⇒ 1). Acá el
    control negativo falla todavía antes: el doble sólo evalúa la consulta del predicado compartido,
    así que con el SQL viejo la celda queda en 0 y la comparación lo caza igual.
    """
    filas = _filas_de_ejemplo(estado_de_la_vencida=estado_de_hoy)
    sesion = SesionFalsa(filas)
    hoja = _genera_excel(sesion)["Historico Mensual"]

    assert hoja.cell(row=FILA_MES_PASADO, column=COL_MRR).value == float(MRR_MES_PASADO)
    assert hoja.cell(row=FILA_MES_PASADO, column=COL_ALUMNOS).value == ALUMNOS_MES_PASADO

    corte_pasado = _meses_esperados()[-2][2]
    sql_mrr, _ = {p["hasta"]: (sql, p)
                  for sql, p in _consultas(sesion, "SUM(p.precio_clp)")}[corte_pasado]
    assert "estado = 'activo'" not in sql_mrr
    assert estados.sql_suscripcion_vigente("s", ":hasta") in sql_mrr


# ── D. La columna de alumnos del fin de mes: el predicado por fecha ──────────────────────────────
def test_d_la_columna_de_alumnos_del_corte_usa_el_predicado_por_fecha():
    """El corte lo decide `_corte_suscripciones` (el último día de cada mes; HOY en el mes en curso) y
    la vigencia en esa fecha, `sql_suscripcion_vigente` (con `fecha_inicio`, que era la condición que
    faltaba): la `rechazado`, la que arranca después del corte y la que venció antes NO cuentan; la
    que vence en el corte SÍ."""
    filas = _filas_de_ejemplo()
    sesion = SesionFalsa(filas)
    historico = rep._build_historico_mensual(sesion, TENANT)

    consultas = _consultas(sesion, "COUNT(DISTINCT u.id)")
    assert len(consultas) == len(_meses_esperados()) == 6
    for (sql, params), (anio, mes, corte) in zip(consultas, _meses_esperados()):
        assert estados.sql_suscripcion_vigente("s", ":corte") in sql, (anio, mes)
        # La prohibición es sobre el estado de la SUSCRIPCIÓN: el "vigente HOY" no puede decidir el
        # corte histórico. `u.estado = 'activo'` (el alumno habilitado) es otra cosa y desde T12 sí
        # aparece (antes era `u.activo = true`, el MISMO dato).
        assert "s.estado = 'activo'" not in sql, (anio, mes)
        assert params == {"tid": TENANT, "corte": corte}, (anio, mes)

    assert historico[-2]["alumnos"] == ALUMNOS_MES_PASADO
    assert historico[-2]["mrr"] == float(MRR_MES_PASADO)
    # El corte queda en el propio dato: es el que usan la celda y la tarjeta del mismo mes.
    assert [h["corte"] for h in historico] == [c for _, _, c in _meses_esperados()]
    assert historico[-1]["corte"] == datetime.now(timezone.utc).date(), "mes en curso = HOY"


# ── E. La guarda: el export no vuelve a escribir su propia copia del MRR ni de la fecha ──────────
def test_e_el_export_no_tiene_su_propia_copia_del_mrr_ni_de_la_fecha():
    """Si alguien re-inlinea el SQL del MRR en el Excel (estaba DOS veces: la columna del histórico y
    la tarjeta del KPI), este test lo frena ANTES de que las versiones diverjan: la definición es una
    sola y vive en `metricas_service`.

    Lo mismo con la FECHA del corte: la calcula `_corte_suscripciones` y la usan las dos columnas
    históricas y la tarjeta del KPI, así que la tarjeta y la celda del mismo mes no pueden separarse
    (si a la tarjeta le vuelven a poner la fecha de hoy escrita a mano, lo caza este test)."""
    fuente = inspect.getsource(rep)
    assert "SUM(p.precio_clp)" not in fuente
    # La tabla histórica no puede volver al "estado de hoy" (now()): su corte es por fecha.
    assert "now() AT TIME ZONE" not in inspect.getsource(rep._build_historico_mensual)
    for funcion in (rep._build_historico_mensual, rep.crear_reporte_ventas_mensual_bytes):
        codigo = inspect.getsource(funcion)
        assert "metricas.mrr(" in codigo, funcion.__name__
        assert "_corte_suscripciones(" in codigo, funcion.__name__


# ── F. La tarjeta con el mes EN CURSO: la celda del mismo mes, que es HOY (como el dashboard) ────
def test_f_la_tarjeta_de_mrr_del_mes_en_curso_es_la_celda_de_ese_mes():
    """Con el mes EN CURSO elegido, la tarjeta KPI "MRR" del Resumen Ejecutivo es la de HOY —el mes
    todavía no cerró, así que su corte es hoy, igual que el dashboard (`reportes.py`)— y es el MISMO
    número que la celda de "Historico Mensual" de ese mes: la tarjeta y la tabla del propio archivo no
    pueden decir cosas distintas."""
    hoy = datetime.now(timezone.utc).date()
    filas = _filas_de_ejemplo()
    sesion = SesionFalsa(filas)
    libro = _genera_excel(sesion)

    esperado = metricas.mrr(SesionFalsa(filas), TENANT, hoy)     # la del dashboard, con hoy
    assert esperado == float(MRR_HOY)                            # la que venció ayer ya no cuenta hoy
    assert libro["Historico Mensual"].cell(row=FILA_MES_ACTUAL, column=COL_MRR).value == esperado
    assert _numero_de_la_tarjeta(libro) == esperado

    # La etiqueta dice la fecha del corte (hoy, porque el mes está en curso) y el subtítulo se mantiene.
    assert f"MRR al {hoy:%d/%m/%Y}" in _celda_de_la_tarjeta(libro, FILA_LABEL_KPI)
    assert _celda_de_la_tarjeta(libro, FILA_LABEL_KPI + 2) == "Ingresos recurrentes"

    # El corte es HOY, no el "cierre" del mes en curso: la suscripción que empieza mañana todavía no
    # cuenta (si hoy es el último día del mes, hoy y el cierre son la misma fecha y no hay qué separar).
    if _arranca_manana():
        assert esperado != _mrr_al_cierre_del_mes_en_curso()

    # Y la consulta de la tarjeta es la MISMA que la del mes en curso de la tabla (misma fecha).
    assert [p["hasta"] for _, p in _consultas(sesion, "SUM(p.precio_clp)")] == [hoy] + [
        corte for _, _, corte in _meses_esperados()]


# ── G. La tarjeta con un mes PASADO: la celda de ESE mes, no la de hoy ───────────────────────────
def test_g_la_tarjeta_de_mrr_de_un_mes_pasado_es_la_celda_de_ese_mes():
    """Con un mes PASADO elegido, la tarjeta usa el corte de ESE mes (su último día), no la fecha de
    hoy: es el mismo número que la fila de ese mes de "Historico Mensual" y distinto del de hoy (en
    las filas de fixture, la suscripción que venció en ese corte sumó al mes pasado y ya no suma hoy).
    Antes del fix, la tarjeta mostraba el MRR del día en que se descargaba el archivo."""
    anio, mes, corte_pasado = _meses_esperados()[-2]
    hoy = datetime.now(timezone.utc).date()
    assert corte_pasado < hoy, "el mes pasado tiene que estar cerrado"

    filas = _filas_de_ejemplo()
    sesion = SesionFalsa(filas)
    libro = _genera_excel(sesion, mes=mes, anio=anio)

    del_mes = metricas.mrr(SesionFalsa(filas), TENANT, corte_pasado)
    assert del_mes == float(MRR_MES_PASADO)
    assert libro["Historico Mensual"].cell(row=FILA_MES_PASADO, column=COL_MRR).value == del_mes
    assert _numero_de_la_tarjeta(libro) == del_mes, "la tarjeta es la celda del mes elegido"

    mrr_hoy = metricas.mrr(SesionFalsa(filas), TENANT, hoy)
    assert mrr_hoy == float(MRR_HOY) and mrr_hoy != del_mes      # NO es la foto de hoy

    # La etiqueta dice el corte del mes elegido (y no la fecha de hoy).
    etiqueta = _celda_de_la_tarjeta(libro, FILA_LABEL_KPI)
    assert f"MRR al {corte_pasado:%d/%m/%Y}" in etiqueta
    assert f"{hoy:%d/%m/%Y}" not in etiqueta

    # La 1ª consulta de MRR del archivo es la del mes elegido (su corte); después, los 6 de la tabla.
    assert [p["hasta"] for _, p in _consultas(sesion, "SUM(p.precio_clp)")] == [corte_pasado] + [
        corte for _, _, corte in _meses_esperados()]

