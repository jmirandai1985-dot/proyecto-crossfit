"""
Resumen de CAJA de un día (pura, sin base de datos) — para el KPI "Ingresos de hoy".

POR QUÉ EXISTE
--------------
El panel admin móvil (<768px) muestra "Ingresos de hoy" con datos REALES del día en
curso. El único lugar donde ese dato vive hoy es `transacciones_financieras` (la MISMA
tabla que alimenta los KPIs: `app/api/v1/kpis_populate.py` suma `tipo='ingreso'` por
rango de fechas). El endpoint del data mart (`GET /kpis/diario`) NO sirve para esto:
lo escribe un job BI y, si aún no publicó el día, la respuesta es 404 (el panel admin
ya muestra "s/d" en esas tarjetas).

Este módulo es el CÁLCULO, separado del acceso a datos, para poder probarlo aislado
(sin red y sin base): el endpoint le pasa las filas agregadas por SQL y acá se decide
qué es ingreso, qué es egreso y cuántos pagos hubo.

REGLA
-----
`transacciones_financieras.tipo` solo puede ser 'ingreso' o 'egreso' (CHECK del modelo
`TransaccionFinanciera`). Un tipo desconocido se IGNORA: no se suma a ningún total ni
se cuenta como pago (nunca inventar un número).
"""
from typing import Iterable, Sequence

INGRESO = "ingreso"
EGRESO = "egreso"


def resumir_dia(filas: Iterable[Sequence]) -> dict:
    """Resume las filas `(tipo, total, n)` que devuelve el GROUP BY del día.

    - `ingresos`: suma de los montos con `tipo='ingreso'` (lo recaudado hoy).
    - `egresos`:  suma de los montos con `tipo='egreso'`.
    - `neto`:     ingresos - egresos (puede ser negativo; NO se recorta a 0).
    - `pagos`:    CUÁNTAS transacciones de ingreso hubo hoy (la tarjeta dice
                  "4 pagos registrados"): los egresos no cuentan como pago.

    Sin filas (un día sin movimientos) devuelve ceros, no `None`: "0 pesos y 0 pagos"
    es un dato válido y distinto de "no pude leer la caja".
    """
    ingresos = 0.0
    egresos = 0.0
    pagos = 0

    for tipo, total, n in filas:
        monto = float(total or 0)
        if tipo == INGRESO:
            ingresos += monto
            pagos += int(n or 0)
        elif tipo == EGRESO:
            egresos += monto
        # tipo desconocido: se ignora a propósito (ver docstring del módulo).

    return {
        "ingresos": ingresos,
        "egresos": egresos,
        "neto": ingresos - egresos,
        "pagos": pagos,
    }
