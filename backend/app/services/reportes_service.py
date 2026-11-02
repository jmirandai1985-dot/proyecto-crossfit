"""
Servicio de Reportes Excel - Version Premium 4 pestanas
Genera reportes ejecutivos con diseno profesional, graficos y formulas reales
"""
import calendar
import io
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, PieChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.worksheet.datavalidation import DataValidation

from app.services import metricas_service as metricas
from app.services.clases_service import sql_clase_realizada
from app.utils.santiago import hoy_santiago
from shared.estados import (lista_sql_pago_bazar, sql_plan_comercial,
                            sql_suscripcion_vigente)


# ============================================================
# COLORES CORPORATIVOS (diseno aprobado)
# ============================================================
NAVY = "111827"
NAVY_HEADER = "1F3A5F"
ORANGE_ACCENT = "EA580C"
BLUE_KPI = "2563EB"
GREEN_KPI = "16A34A"
PURPLE_KPI = "7C3AED"
TEAL_KPI = "0D9488"
WHITE = "FFFFFF"
LIGHT_GRAY = "F3F4F6"
MEDIUM_GRAY = "D1D5DB"
DARK_TEXT = "1F2937"
RED = "DC2626"
GREEN = "16A34A"
YELLOW_BG = "FEF3C7"

# Barras de color para KPI cards
KPI_COLORS = {
    "ingresos": ORANGE_ACCENT,
    "alumnos": BLUE_KPI,
    "mrr": GREEN_KPI,
    "arpu": PURPLE_KPI,
    "nuevos": TEAL_KPI,
}

# Estilos reutilizables
header_fill = PatternFill(start_color=NAVY_HEADER,
                          end_color=NAVY_HEADER, fill_type="solid")
header_font = Font(bold=True, color=WHITE, size=11)
title_font = Font(bold=True, size=18, color=NAVY)
section_font = Font(bold=True, size=13, color=NAVY)
kpi_value_font = Font(bold=True, size=24, color=DARK_TEXT)
kpi_label_font = Font(bold=True, size=11, color=DARK_TEXT)
kpi_subtitle_font = Font(size=9, color="6B7280")
thin_border = Border(
    left=Side(style='thin', color=MEDIUM_GRAY),
    right=Side(style='thin', color=MEDIUM_GRAY),
    top=Side(style='thin', color=MEDIUM_GRAY),
    bottom=Side(style='thin', color=MEDIUM_GRAY),
)
alt_fill = PatternFill(start_color=LIGHT_GRAY,
                       end_color=LIGHT_GRAY, fill_type="solid")
total_fill = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
total_font = Font(bold=True, color=WHITE, size=11)
green_font = Font(bold=True, color=GREEN, size=11)
red_font = Font(bold=True, color=RED, size=11)


def _apply_kpi_card(ws, row, col, label, value, subtitle, accent_color, emoji):
    """Dibuja una tarjeta KPI con barra de color superior."""
    cell = ws.cell(row=row, column=col, value=emoji + "  " + label)
    cell.font = kpi_label_font
    cell.alignment = Alignment(horizontal='left', vertical='top')
    # Barra de color arriba (fila anterior, misma col)
    ws.cell(row=row - 1, column=col).fill = PatternFill(
        start_color=accent_color, end_color=accent_color, fill_type="solid")
    ws.cell(row=row - 1, column=col).border = Border(
        bottom=Side(style='medium', color=accent_color))
    # Valor
    cell_v = ws.cell(row=row + 1, column=col, value=value)
    cell_v.font = kpi_value_font
    cell_v.alignment = Alignment(horizontal='left', vertical='top')
    # Subtitulo
    cell_s = ws.cell(row=row + 2, column=col, value=subtitle)
    cell_s.font = kpi_subtitle_font
    cell_s.alignment = Alignment(horizontal='left', vertical='top')


def _style_section_header(ws, row, col, title, accent_color):
    """Barra de acento a la izquierda + titulo de seccion."""
    ws.cell(row=row, column=col, value="").fill = PatternFill(
        start_color=accent_color, end_color=accent_color, fill_type="solid")
    ws.cell(row=row, column=col).border = Border(
        right=Side(style='medium', color=accent_color))
    cell_title = ws.cell(row=row, column=col + 1, value=title)
    cell_title.font = section_font
    cell_title.alignment = Alignment(horizontal='left', vertical='center')


def _style_table_header(ws, row, headers, start_col=1):
    """Encabezado de tabla con fondo navy y texto blanco."""
    for i, h in enumerate(headers):
        cell = ws.cell(row=row, column=start_col + i, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(
            horizontal='center', vertical='center', wrap_text=True)


def _style_data_row(ws, row, values, start_col=1, is_alt=False, is_percent_cols=None, is_money_cols=None):
    """Fila de datos con banding y formato."""
    for i, v in enumerate(values):
        cell = ws.cell(row=row, column=start_col + i, value=v)
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center', vertical='center')
        if is_alt:
            cell.fill = alt_fill
        col_idx = start_col + i
        if is_percent_cols and col_idx in is_percent_cols:
            cell.number_format = '0.0%'
        if is_money_cols and col_idx in is_money_cols:
            cell.number_format = '#,##0'
    return row


def _add_bar_chart(ws, data_rows, data_col, cat_col, title, position, color=ORANGE_ACCENT):
    """Agrega grafico de barras."""
    chart = BarChart()
    chart.type = "col"
    chart.title = title
    chart.style = 10
    chart.width = 13
    chart.height = 8
    data_ref = Reference(ws, min_col=data_col,
                         min_row=data_rows[0], max_row=data_rows[1])
    cats_ref = Reference(ws, min_col=cat_col,
                         min_row=data_rows[0], max_row=data_rows[1])
    chart.add_data(data_ref, titles_from_data=False)
    chart.set_categories(cats_ref)
    chart.series[0].graphicalProperties.solidFill = color
    ws.add_chart(chart, position)


def _add_pie_chart(ws, data_rows, data_col, cat_col, title, position):
    """Agrega grafico de torta."""
    chart = PieChart()
    chart.title = title
    chart.style = 10
    chart.width = 13
    chart.height = 8
    data_ref = Reference(ws, min_col=data_col,
                         min_row=data_rows[0], max_row=data_rows[1])
    cats_ref = Reference(ws, min_col=cat_col,
                         min_row=data_rows[0], max_row=data_rows[1])
    chart.add_data(data_ref, titles_from_data=False)
    chart.set_categories(cats_ref)
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showPercent = True
    chart.dataLabels.showCatName = True
    chart.dataLabels.showVal = False
    ws.add_chart(chart, position)


def _add_line_chart(ws, data_rows, data_col, cat_col, title, position, color=ORANGE_ACCENT):
    """Agrega grafico de linea."""
    chart = LineChart()
    chart.title = title
    chart.style = 10
    chart.width = 13
    chart.height = 8
    data_ref = Reference(ws, min_col=data_col,
                         min_row=data_rows[0], max_row=data_rows[1])
    cats_ref = Reference(ws, min_col=cat_col,
                         min_row=data_rows[0], max_row=data_rows[1])
    chart.add_data(data_ref, titles_from_data=False)
    chart.set_categories(cats_ref)
    chart.series[0].graphicalProperties.solidFill = color
    chart.series[0].graphicalProperties.line.solidFill = color
    ws.add_chart(chart, position)


def _corte_suscripciones(ultimo_dia: date) -> date:
    """La fecha de corte de las columnas de suscripciones ("Alumnos" y "MRR") de un mes.

    El corte de un mes ya cerrado es su ULTIMO DIA: la vigencia de una suscripcion es un intervalo
    de fechas, asi que el numero de ese mes no puede depender del estado de HOY (una `vencido` de
    hoy sigue contando en los meses que sus fechas cubren).

    El mes EN CURSO todavia no cerro, asi que se corta a HOY (en UTC, igual que el dashboard:
    `app/api/v1/reportes.py`); contar los dias que todavia no pasaron adelantaria al mes en curso
    las suscripciones que empiezan mas adelante.

    Es la MISMA fecha que recibe la tarjeta KPI de MRR del Resumen Ejecutivo y el parametro `hasta`
    de `metricas_service.mrr`, para que la tarjeta y la celda de "Historico Mensual" del mismo mes
    digan siempre lo mismo.
    """
    hoy = datetime.now(timezone.utc).date()
    if (ultimo_dia.year, ultimo_dia.month) == (hoy.year, hoy.month):
        return hoy
    return ultimo_dia


def _build_historico_mensual(db, tenant_id):
    """
    Construye la tabla Historico Mensual con datos reales de transacciones_financieras
    para los ultimos 6 meses.
    Retorna: list of dicts con Año, Mes, MesNum, IngresosTotales, Egresos, Neto

    El corte de las dos columnas de suscripciones ("Alumnos" y "MRR") es el que define
    `_corte_suscripciones` (el ULTIMO DIA de cada mes, u HOY si el mes es el en curso), y la vigencia
    EN ESA FECHA la decide el predicado compartido
    (`shared.estados.sql_suscripcion_vigente`), no `estado = 'activo'`: ese es el estado de HOY,
    así que usarlo en un mes ya cerrado hacía que el mes pasado se recalculase al vencerse una
    suscripción (una `vencido` desaparecía de los meses en los que sí estuvo vigente y una que
    empieza el mes que viene sumaba). Fix del 2026-09-27, el mismo del correo de mantenimiento.

    El MRR no se recalcula acá: es `metricas_service.mrr` con la fecha del corte, la MISMA función
    que usan el dashboard (`app/api/v1/reportes.py`) y el BI (`kpis_populate.py`, que persiste el
    mes cerrado con el mismo `fin`), para que el número no tenga dos versiones.

    El mes EN CURSO se corta a HOY (el mes todavía no cerró), con el mismo `_corte_suscripciones` que
    la tarjeta KPI de MRR del Resumen Ejecutivo: así la celda de ese mes en esta tabla y la tarjeta
    siempre dicen lo mismo.
    """
    historico = []
    ahora = datetime.now(timezone.utc)
    for i in range(5, -1, -1):
        # Calcular mes
        m = ahora.month - i
        y = ahora.year
        while m <= 0:
            m += 12
            y -= 1
        inicio = date(y, m, 1)
        if m == 12:
            fin = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            fin = date(y, m + 1, 1) - timedelta(days=1)

        # Ingresos
        ing = db.execute(text("""
            SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras
            WHERE tenant_id = :tid AND tipo = 'ingreso' AND fecha >= :ini AND fecha <= :fin
        """), {"tid": tenant_id, "ini": inicio, "fin": fin}).scalar() or 0

        # Egresos
        eg = db.execute(text("""
            SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras
            WHERE tenant_id = :tid AND tipo = 'egreso' AND fecha >= :ini AND fecha <= :fin
        """), {"tid": tenant_id, "ini": inicio, "fin": fin}).scalar() or 0

        # Corte de las DOS columnas de suscripciones (no es el `fin` de las columnas financieras:
        # ver `_corte_suscripciones`).
        corte = _corte_suscripciones(fin)

        # Alumnos vigentes al corte (por FECHA: ver el docstring). Sólo planes COMERCIALES: el
        # "Pase de regreso" da acceso pero no es un cliente (`sql_plan_comercial`).
        alumnos = db.execute(text("""
            SELECT COUNT(DISTINCT u.id) FROM usuarios u
            JOIN suscripciones s ON u.id = s.usuario_id
            JOIN planes p ON p.id = s.plan_id
            WHERE u.tenant_id = :tid AND u.rol = 'alumno' AND u.estado = 'activo'
              AND """ + sql_suscripcion_vigente("s", ":corte") + """
              AND """ + sql_plan_comercial("p") + """
        """), {"tid": tenant_id, "corte": corte}).scalar() or 0

        # Nuevos alumnos del mes
        nuevos = db.execute(text("""
            SELECT COUNT(*) FROM usuarios
            WHERE tenant_id = :tid AND rol = 'alumno'
              AND created_at::date >= :ini AND created_at::date <= :fin
        """), {"tid": tenant_id, "ini": inicio, "fin": fin}).scalar() or 0

        # MRR al corte: NO una copia acá, la misma definición del dashboard y del BI
        mrr_val = metricas.mrr(db, tenant_id, corte)

        # Ventas del Bazar del mes: MISMA definicion que el BI y que el historial del alumno
        # (`metricas_service.ventas_bazar` = pedidos cobrados). Antes era un SQL propio con
        # `estado != 'cancelado'`, que contaba tambien los pendientes: la celda de esta tabla y
        # la columna "Bazar / Tienda" del Resumen podian decir numeros distintos.
        ventas = metricas.ventas_bazar(db, tenant_id, inicio, fin)

        meses_es = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                    'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        label = f"{meses_es[m - 1]} {y}"

        ing_f = float(ing)
        eg_f = float(eg)

        historico.append({
            "anio": y,
            "mes": label,
            "mes_num": m,
            "corte": corte,
            "ingresos": ing_f,
            "egresos": eg_f,
            "neto": ing_f - eg_f,
            "alumnos": alumnos,
            "nuevos": nuevos,
            "mrr": float(mrr_val),
            "ventas": float(ventas),
        })
    return historico


def _pedidos_bazar_mes(db, tenant_id, inicio, fin):
    """Pedidos del Bazar COBRADOS en [inicio, fin) — el detalle del Excel.

    Solo `validado`/`entregado` (`lista_sql_pago_bazar()`, la lista COMPARTIDA con
    `metricas_service.ventas_bazar`): asi el detalle, su fila TOTAL y la columna
    "Bazar / Tienda" del Resumen cuentan lo MISMO. Los pedidos `pendiente` no son plata
    todavia y se resumen aparte en la tarjeta "Pendientes" del Excel.

    El rango es el del archivo (fin EXCLUSIVO, el primer dia del mes siguiente) y se compara
    por DIA CHILENO de `fecha_pedido`, igual que la metrica compartida.
    """
    try:
        rows = db.execute(text("""
            SELECT p.id, p.alumno_id, u.nombre as alumno_nombre,
                   pr.nombre as producto_nombre, p.cantidad, p.total, p.estado, p.fecha_pedido
            FROM pedidos p
            JOIN usuarios u ON p.alumno_id = u.id
            JOIN productos pr ON p.producto_id = pr.id
            WHERE p.tenant_id = :tid
              AND (p.fecha_pedido AT TIME ZONE 'America/Santiago')::date >= :ini
              AND (p.fecha_pedido AT TIME ZONE 'America/Santiago')::date < :fin
              AND p.estado IN (""" + lista_sql_pago_bazar() + """)
            ORDER BY p.fecha_pedido DESC
        """), {"tid": tenant_id, "ini": inicio, "fin": fin}).fetchall()
        return rows
    except Exception:
        return []


def _pedidos_bazar_pendientes_mes(db, tenant_id, inicio, fin) -> int:
    """Cuántos pedidos del mes quedaron SIN cobrar (`pendiente`): informativo, no es plata.

    Se cuenta aparte porque `_pedidos_bazar_mes` devuelve sólo los cobrados (el detalle y su
    total tienen que sumar igual). Antes la tarjeta salía de la lista completa, así que al
    corregir la definición habría quedado SIEMPRE en 0.
    """
    try:
        return int(db.execute(text("""
            SELECT COUNT(*) FROM pedidos p
            WHERE p.tenant_id = :tid
              AND (p.fecha_pedido AT TIME ZONE 'America/Santiago')::date >= :ini
              AND (p.fecha_pedido AT TIME ZONE 'America/Santiago')::date < :fin
              AND p.estado = 'pendiente'
        """), {"tid": tenant_id, "ini": inicio, "fin": fin}).scalar() or 0)
    except Exception:
        return 0


# ============================================================================
# REPORTE 4 PESTAÑAS COMPARATIVAS (MoM / YoY / YTD / ARPU)
# Reemplaza a `_crear_reporte_ventas_mensual_bytes_v1`. Reusa las helpers de
# estilo de arriba y las definiciones únicas de `metricas_service` (MRR, ARPU,
# alumnos vigentes, ventas del Bazar).
# ============================================================================
_MESES_ES_LARGOS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def _neto_rango(db, tenant_id, inicio, fin_exclusive):
    """(ingresos, egresos, neto) de [inicio, fin_exclusive) desde transacciones."""
    ing = db.execute(text("""
        SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras
        WHERE tenant_id = :tid AND tipo = 'ingreso' AND fecha >= :ini AND fecha < :fin
    """), {"tid": tenant_id, "ini": inicio, "fin": fin_exclusive}).scalar() or 0
    eg = db.execute(text("""
        SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras
        WHERE tenant_id = :tid AND tipo = 'egreso' AND fecha >= :ini AND fecha < :fin
    """), {"tid": tenant_id, "ini": inicio, "fin": fin_exclusive}).scalar() or 0
    ing_f, eg_f = float(ing), float(eg)
    return ing_f, eg_f, ing_f - eg_f


def _resumen_mes(db, tenant_id, anio, mes):
    """Resumen de UN mes (ingresos/egresos/neto, alumnos, nuevos, MRR y Bazar).

    MRR y ventas del Bazar salen de `metricas_service` (una sola definición);
    el corte del mes lo define `_corte_suscripciones`.
    """
    inicio = date(anio, mes, 1)
    fin_ex = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    ing, eg, neto = _neto_rango(db, tenant_id, inicio, fin_ex)
    corte = _corte_suscripciones(fin_ex - timedelta(days=1))
    nuevos = db.execute(text("""
        SELECT COUNT(*) FROM usuarios
        WHERE tenant_id = :tid AND rol = 'alumno'
          AND created_at::date >= :ini AND created_at::date < :fin
    """), {"tid": tenant_id, "ini": inicio, "fin": fin_ex}).scalar() or 0
    return {
        "anio": anio, "mes": mes, "corte": corte,
        "ingresos": ing, "egresos": eg, "neto": neto,
        "alumnos": int(metricas.alumnos_vigentes(db, tenant_id, corte)),
        "nuevos": int(nuevos),
        "mrr": float(metricas.mrr(db, tenant_id, corte)),
        "ventas": float(metricas.ventas_bazar(db, tenant_id, inicio, fin_ex)),
    }


def _meses_de_historia(db, tenant_id):
    """Meses de historial (desde la primera transacción/alta hasta hoy, en Chile)."""
    hoy = hoy_santiago()
    primera = db.execute(text("""
        SELECT MIN(f) FROM (
            SELECT fecha AS f FROM transacciones_financieras WHERE tenant_id = :tid
            UNION ALL
            SELECT created_at AS f FROM usuarios WHERE tenant_id = :tid AND rol = 'alumno'
        ) t WHERE f IS NOT NULL
    """), {"tid": tenant_id}).scalar()
    if primera is None:
        return 0
    return (hoy.year - primera.year) * 12 + (hoy.month - primera.month) + 1


def _pct(ahora, antes):
    """Variación porcentual; None si no hay base comparable."""
    return round((ahora - antes) / abs(antes) * 100, 1) if antes else None


def _fmt_pct(valor):
    """'—' si no hay dato; si no, '+12.3%' / '-4.5%'."""
    return "—" if valor is None else f"{valor:+.1f}%"


def _titulo_hoja(ws, titulo, subtitulo):
    """Banner navy + franja naranja + subtítulo (mismo patrón visual de la v1)."""
    for c in range(1, 9):
        ws.cell(row=1, column=c).fill = PatternFill(
            start_color=NAVY, end_color=NAVY, fill_type="solid")
    ws.merge_cells('A1:H1')
    cell = ws.cell(row=1, column=1, value=titulo)
    cell.font = Font(bold=True, size=20, color=WHITE)
    cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 40
    for c in range(1, 9):
        ws.cell(row=2, column=c).fill = PatternFill(
            start_color=ORANGE_ACCENT, end_color=ORANGE_ACCENT, fill_type="solid")
    ws.row_dimensions[2].height = 5
    ws.merge_cells('A3:H3')
    sub = ws.cell(row=3, column=1, value=subtitulo)
    sub.font = Font(size=10, color="6B7280")
    sub.alignment = Alignment(horizontal='center')

def crear_reporte_ventas_mensual_bytes(db, tenant_id, mes, anio):
    """Genera el reporte Excel con 4 pestañas comparativas: MoM, YoY, YTD, ARPU."""
    wb = Workbook()
    wb.remove(wb.active)
    hoy = hoy_santiago()
    label_mes = f"{_MESES_ES_LARGOS[mes - 1]} {anio}"

    actual = _resumen_mes(db, tenant_id, anio, mes)
    mes_ant, anio_ant = (12, anio - 1) if mes == 1 else (mes - 1, anio)
    anterior = _resumen_mes(db, tenant_id, anio_ant, mes_ant)
    label_ant = f"{_MESES_ES_LARGOS[mes_ant - 1]} {anio_ant}"

    arpu = metricas.arpu_mes_cerrado(db, tenant_id, hoy)
    alumnos_hoy = metricas.alumnos_vigentes(db, tenant_id, hoy)
    generado = f"Generado: {datetime.now():%d/%m/%Y %H:%M}"

    # ── 1) MoM: mes a mes (absorbe Resumen Ejecutivo + Flujo de Caja) ────────
    ws = wb.create_sheet("MoM", 0)
    ws.sheet_view.showGridLines = False
    for col, w in (('A', 3), ('B', 22), ('C', 22), ('D', 22),
                   ('E', 22), ('F', 22), ('G', 22), ('H', 3)):
        ws.column_dimensions[col].width = w
    _titulo_hoja(ws, "MoM — MES A MES", f"{label_mes} vs {label_ant}   ·   {generado}")

    kpi = 5
    _apply_kpi_card(ws, kpi, 2, "Ingresos netos", f"${actual['neto']:,.0f}",
                    label_mes, ORANGE_ACCENT, "💰")
    _apply_kpi_card(ws, kpi, 3, "vs mes anterior",
                    _fmt_pct(_pct(actual['neto'], anterior['neto'])),
                    label_ant, BLUE_KPI, "📊")
    _apply_kpi_card(ws, kpi, 4, "Alumnos activos", f"{alumnos_hoy}",
                    "Con suscripción vigente", GREEN_KPI, "👥")
    _apply_kpi_card(ws, kpi, 5, "MRR", f"${actual['mrr']:,.0f}",
                    f"al {actual['corte']:%d/%m/%Y}", PURPLE_KPI, "📈")
    _apply_kpi_card(ws, kpi, 6, "ARPU", f"${arpu:,.0f}",
                    "Último mes cerrado", TEAL_KPI, "🎯")
    ws.row_dimensions[kpi].height = 20
    ws.row_dimensions[kpi + 1].height = 35
    ws.row_dimensions[kpi + 2].height = 20

    r = 10
    _style_section_header(ws, r, 1, "Flujo de Caja (mes vs mes anterior)", BLUE_KPI)
    r += 1
    _style_table_header(ws, r, ["Concepto", label_mes, label_ant, "Variación"])
    r += 1
    filas = [
        ("Ingresos", actual["ingresos"], anterior["ingresos"]),
        ("Egresos", actual["egresos"], anterior["egresos"]),
        ("Neto", actual["neto"], anterior["neto"]),
        ("Ventas Bazar (cobradas)", actual["ventas"], anterior["ventas"]),
    ]
    for i, (concepto, ahora_v, antes_v) in enumerate(filas):
        variacion = _fmt_pct(_pct(ahora_v, antes_v))
        _style_data_row(ws, r, [concepto, f"${ahora_v:,.0f}", f"${antes_v:,.0f}", variacion],
                        is_alt=(i % 2 == 1), is_money_cols={2, 3})
        r += 1

    # ── 2) YoY: mismo mes vs mismo mes del año anterior ───────────────────────
    ws = wb.create_sheet("YoY", 1)
    ws.sheet_view.showGridLines = False
    for col, w in (('A', 3), ('B', 24), ('C', 24), ('D', 24), ('E', 24), ('H', 3)):
        ws.column_dimensions[col].width = w
    _titulo_hoja(ws, "YoY — AÑO A AÑO",
                 f"{label_mes} vs {_MESES_ES_LARGOS[mes - 1]} {anio - 1}   ·   {generado}")

    if _meses_de_historia(db, tenant_id) < 13:
        nota = ws.cell(row=5, column=2,
                       value="Datos insuficientes: se necesitan al menos 13 meses de historial para comparar año contra año.")
        nota.font = Font(size=12, bold=True, color=RED)
    else:
        mismo_mes_anterior = _resumen_mes(db, tenant_id, anio - 1, mes)
        label_yoy = f"{_MESES_ES_LARGOS[mes - 1]} {anio - 1}"
        _style_section_header(ws, 5, 1, "Comparación año contra año", BLUE_KPI)
        _style_table_header(ws, 6, ["Métrica", label_mes, label_yoy, "Variación"])
        yoy_filas = [
            ("Ingresos", actual["ingresos"], mismo_mes_anterior["ingresos"]),
            ("Egresos", actual["egresos"], mismo_mes_anterior["egresos"]),
            ("Neto", actual["neto"], mismo_mes_anterior["neto"]),
            ("MRR (al corte)", actual["mrr"], mismo_mes_anterior["mrr"]),
            ("Alumnos (al corte)", actual["alumnos"], mismo_mes_anterior["alumnos"]),
            ("Nuevos alumnos", actual["nuevos"], mismo_mes_anterior["nuevos"]),
            ("Ventas Bazar", actual["ventas"], mismo_mes_anterior["ventas"]),
        ]
        r = 7
        for i, (metrica, ahora_v, antes_v) in enumerate(yoy_filas):
            variacion = _fmt_pct(_pct(ahora_v, antes_v))
            _style_data_row(ws, r, [metrica, ahora_v, antes_v, variacion],
                            is_alt=(i % 2 == 1), is_money_cols={2, 3})
            r += 1

    # ── 3) YTD: año a la fecha (1 ene → hoy) vs mismo periodo del año anterior ──
    ws = wb.create_sheet("YTD", 2)
    ws.sheet_view.showGridLines = False
    for col, w in (('A', 3), ('B', 24), ('C', 26), ('D', 26), ('E', 24), ('H', 3)):
        ws.column_dimensions[col].width = w
    tope = hoy
    tope_ant = date(anio - 1, hoy.month, min(hoy.day, calendar.monthrange(anio - 1, hoy.month)[1]))
    ing_ytd, eg_ytd, neto_ytd = _neto_rango(db, tenant_id, date(anio, 1, 1), tope + timedelta(days=1))
    ing_ytd_a, eg_ytd_a, neto_ytd_a = _neto_rango(db, tenant_id, date(anio - 1, 1, 1), tope_ant + timedelta(days=1))

    def _nuevos_rango(ini, fin):
        return int(db.execute(text("""
            SELECT COUNT(*) FROM usuarios
            WHERE tenant_id = :tid AND rol = 'alumno'
              AND created_at::date >= :ini AND created_at::date < :fin
        """), {"tid": tenant_id, "ini": ini, "fin": fin}).scalar() or 0)

    nuevos_ytd = _nuevos_rango(date(anio, 1, 1), tope + timedelta(days=1))
    nuevos_ytd_a = _nuevos_rango(date(anio - 1, 1, 1), tope_ant + timedelta(days=1))

    _titulo_hoja(ws, "YTD — AÑO A LA FECHA",
                 f"1 ene → {hoy:%d/%m/%Y} de {anio} vs {anio - 1}   ·   {generado}")
    _style_section_header(ws, 5, 1, "Acumulado año a la fecha", BLUE_KPI)
    _style_table_header(ws, 6, ["Concepto", f"{anio} (YTD)", f"{anio - 1} (YTD)", "Variación"])
    ytd_filas = [
        ("Ingresos", ing_ytd, ing_ytd_a),
        ("Egresos", eg_ytd, eg_ytd_a),
        ("Neto", neto_ytd, neto_ytd_a),
        ("Nuevos alumnos", nuevos_ytd, nuevos_ytd_a),
    ]
    r = 7
    for i, (concepto, ahora_v, antes_v) in enumerate(ytd_filas):
        variacion = _fmt_pct(_pct(ahora_v, antes_v))
        _style_data_row(ws, r, [concepto, ahora_v, antes_v, variacion],
                        is_alt=(i % 2 == 1), is_money_cols={3, 4})
        r += 1

    # ── 4) ARPU: ingreso por alumno (absorbe Detalle Planes) ────────────────────
    ws = wb.create_sheet("ARPU", 3)
    ws.sheet_view.showGridLines = False
    for col, w in (('A', 3), ('B', 22), ('C', 20), ('D', 20),
                   ('E', 20), ('F', 20), ('G', 20), ('H', 3)):
        ws.column_dimensions[col].width = w
    _titulo_hoja(ws, "ARPU — INGRESO POR ALUMNO", f"{label_mes}   ·   {generado}")

    kpi = 5
    _apply_kpi_card(ws, kpi, 2, "ARPU", f"${arpu:,.0f}", "Último mes cerrado", PURPLE_KPI, "🎯")
    _apply_kpi_card(ws, kpi, 3, "Alumnos activos", f"{alumnos_hoy}",
                    "Con suscripción vigente", BLUE_KPI, "👥")
    ws.row_dimensions[kpi].height = 20
    ws.row_dimensions[kpi + 1].height = 35
    ws.row_dimensions[kpi + 2].height = 20

    planes = db.execute(text("""
        SELECT p.nombre, p.precio_clp, COUNT(DISTINCT s.id) AS suscripciones,
               COALESCE(ROUND(AVG(t.monto)), 0) AS ticket, COALESCE(SUM(t.monto), 0) AS ingreso
        FROM planes p
        LEFT JOIN suscripciones s ON s.plan_id = p.id AND s.tenant_id = :tid
        LEFT JOIN transacciones_financieras t ON t.referencia_id = s.id
            AND t.referencia_tipo = 'suscripcion' AND t.categoria = 'membresia'
            AND t.tipo = 'ingreso' AND t.tenant_id = :tid
        WHERE p.tenant_id = :tid
        GROUP BY p.id, p.nombre, p.precio_clp
        ORDER BY ingreso DESC, suscripciones DESC
    """), {"tid": tenant_id}).fetchall()

    gt = db.execute(text("""
        SELECT COUNT(*), COALESCE(ROUND(AVG(monto)), 0), COALESCE(SUM(monto), 0)
        FROM transacciones_financieras
        WHERE tenant_id = :tid AND tipo = 'ingreso' AND categoria = 'membresia'
    """), {"tid": tenant_id}).first()
    vida_dias = int(db.execute(text("""
        SELECT COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM (
            COALESCE(fecha_baja::timestamptz, NOW()) - created_at)) / 86400.0)), 0)
        FROM usuarios WHERE tenant_id = :tid AND rol = 'alumno'
    """), {"tid": tenant_id}).scalar() or 0)
    ltv = round((arpu or 0) * vida_dias / 30, 0)

    _style_section_header(ws, 10, 1, "Por plan", BLUE_KPI)
    _style_table_header(ws, 11, ["Plan", "Precio lista", "Suscripciones", "Ticket prom.", "Ingreso total"])
    r = 12
    for i, fila in enumerate(planes):
        _style_data_row(ws, r, [fila[0], fila[1] or 0, fila[2] or 0, fila[3] or 0, fila[4] or 0],
                        is_alt=(i % 2 == 1), is_money_cols={3, 5, 6})
        r += 1

    _style_section_header(ws, r + 1, 1, "Ticket promedio y LTV", BLUE_KPI)
    r += 2
    _style_table_header(ws, r, ["Métrica", "Valor"])
    r += 1
    extras = [
        ("Ticket promedio membresía", f"${int(gt[1] or 0):,}"),
        ("Transacciones membresía", int(gt[0] or 0)),
        ("Ingreso membresía total", f"${int(gt[2] or 0):,}"),
        ("Vida promedio (días)", vida_dias),
        ("LTV estimado (ARPU × vida)", f"${ltv:,}"),
    ]
    for i, (metrica, valor) in enumerate(extras):
        _style_data_row(ws, r, [metrica, valor], is_alt=(i % 2 == 1))
        r += 1

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

