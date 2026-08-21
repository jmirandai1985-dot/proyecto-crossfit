"""
Constantes de negocio centrales de la plataforma.

Sellos y límites del Ranking de Asistencia por Plan (pantalla TV pública).
Los nombres de los sellos son CONFIGURABLES desde acá (no hardcodeados en el
frontend ni en el router), tal como pide el diseño confirmado.
"""
from typing import Final

# ── Sellos del ranking ────────────────────────────────────────────────────────
# Sello especial para el plan Full/ilimitado que en el mes cerrado supera al
# plan más alto NO ilimitado en asistencias reales.
SELLO_MONSTRUO: Final[str] = "🦍 MONSTRUO"

# Sello de cumplimiento total: asistencias == clases contratadas del plan.
SELLO_PERFECTO: Final[str] = "100% PERFECTO"

# ── Límites del ranking ───────────────────────────────────────────────────────
# Filas por columna (top 10 por tramo).
RANKING_TOP: Final[int] = 10

# ── Escala de estrellas por % de cumplimiento ────────────────────────────────
# Confirmada con el usuario. Piso INCLUSIVO:
#   100%            → sello "100% PERFECTO" (sin estrellas)
#   80%–99%         → 4 ★
#   60%–79%         → 3 ★
#   40%–59%         → 2 ★
#   20%–39%         → 1 ★
#   <20%            → 0 ★
# Para la columna ilimitado, el % se calcula relativo al máximo no-ilimitado
# (sin denominador fijo).
ESTRELLAS_POR_RANGO: Final[tuple] = (
    (80, 4),
    (60, 3),
    (40, 2),
    (20, 1),
    (0, 0),
)
