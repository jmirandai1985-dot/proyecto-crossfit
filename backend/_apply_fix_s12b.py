"""Aplica SOLO el fix adicional S12b: _inicio_fin_mes con aritmética de meses.

La versión anterior (day=28 + 4*offset).replace(day=1) colapsaba los offsets
-1..-5 al MES ACTUAL, rompiendo ingresos_mes_ant, historico_membresias y el
nuevo historico_ingresos. Preserva CRLF y verifica 1 match.
"""
import io
import os

BASE = r"c:\Users\Asus\Desktop\Proyectos\proyecto-crossfit\backend"


def aplicar(rel, tag, old, new):
    ruta = os.path.join(BASE, rel)
    with io.open(ruta, "r", encoding="utf-8", newline="") as f:
        src = f.read()
    e = "\r\n" if "\r\n" in src else "\n"
    old_crlf = old.replace("\n", e)
    new_crlf = new.replace("\n", e)
    n = src.count(old_crlf)
    if n != 1:
        raise SystemExit(f"[{tag}] bloque no encontrado o ambiguo (matches={n}) en {rel}")
    src = src.replace(old_crlf, new_crlf)
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print(f"[{tag}] OK - {rel}")


aplicar(
    r"app\api\v1\reportes.py", "S12b _inicio_fin_mes",
    '''def _inicio_fin_mes(offset_meses=0):
    """Retorna (inicio_mes, fin_mes) para el mes actual + offset_meses."""
    ahora = datetime.now(timezone.utc)
    # Calcular primer día del MES ACTUAL
    inicio_actual = ahora.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    # Si offset=0: mes actual. Si offset=-1: mes anterior
    inicio = (inicio_actual.replace(day=28) + timedelta(days=4*offset_meses)
              ).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
    return inicio, fin''',
    '''def _inicio_fin_mes(offset_meses=0):
    """Retorna (inicio_mes, fin_mes) para el mes actual + offset_meses.

    FIX S12b: la versión anterior usaba (day=28 + 4*offset).replace(day=1), que
    para offsets -1..-5 colapsaba al MES ACTUAL (28-4=24, 28-8=20, ... siempre
    dentro del mismo mes). Consecuencia: ingresos_mes_ant, historico_membresias
    e historico_ingresos mostraban siempre el mes actual. Se reemplaza por
    aritmética de meses (calendar-safe, no depende de la duración del mes).
    """
    ahora = datetime.now(timezone.utc)
    # Primer día del MES ACTUAL
    inicio_actual = ahora.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    # Desplazamiento en meses sin depender de la duración del mes
    total_meses = inicio_actual.year * 12 + (inicio_actual.month - 1) + offset_meses
    anio_obj = total_meses // 12
    mes_obj = total_meses % 12 + 1
    inicio = inicio_actual.replace(
        year=anio_obj, month=mes_obj, day=1,
        hour=0, minute=0, second=0, microsecond=0)
    fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
    return inicio, fin''',
)

print("\nOK: _inicio_fin_mes corregido (S12b).")
