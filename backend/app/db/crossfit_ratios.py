"""
Estándares de ratio peso levantado / peso corporal para clasificación de nivel.

Fuentes:
  - strengthlevel.com: datos agregados de miles de levantadores reales con percentiles
  - Starting Strength (Mark Rippetoe): estándares de squat, deadlift, press
  - StrongFirst (Pavel Tsatsouline): estándares de kettlebell (Simple & Sinister)
  - CrossFit Games Rulebook: standards de movimiento válido
  - Criterio de coach: extrapolación entre movimientos (Front Squat ~80% Back Squat,
    OHS ~65% Front Squat, Snatch ~75% Clean, Jerk ~90% Clean)

Solo incluye movimientos de FUERZA que se miden por 1RM.
Quedan excluidos: movimientos con peso fijo (Wall Balls, Kettlebell Swing, Dumbbell Snatch)
y movimientos gimnásticos (ver crossfit_habilidades.py).

Cada movimiento tiene:
  - "unidad": "ratio" (peso/peso corporal)
  - "M": niveles para Masculino
  - "F": niveles para Femenino
"""

CROSSFIT_RATIOS = {
    # ==============================
    # SENTADILLAS
    # ==============================
    "Back Squat (Sentadilla Trasera)": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.8,
            "Intermedio": 1.5,
            "Avanzado": 2.0,
            "Elite": 2.5,
        },
        "F": {
            "Principiante": 0.6,
            "Intermedio": 1.2,
            "Avanzado": 1.6,
            "Elite": 2.0,
        },
    },
    # Fuente: strengthlevel.com (percentiles: 25%=0.8x, 50%=1.5x, 80%=2.0x, 99%=2.5x+ para M 80kg)
    # Diferencia M/F: ~20% menor en F por composición corporal estándar

    "Front Squat (Sentadilla Frontal)": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.6,
            "Intermedio": 1.2,
            "Avanzado": 1.6,
            "Elite": 2.0,
        },
        "F": {
            "Principiante": 0.5,
            "Intermedio": 0.9,
            "Avanzado": 1.3,
            "Elite": 1.6,
        },
    },
    # Fuente: strengthlevel.com + criterio coach: Front Squat ~80% del Back Squat

    "Overhead Squat (Sentadilla Over-Head)": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.4,
            "Intermedio": 0.8,
            "Avanzado": 1.1,
            "Elite": 1.4,
        },
        "F": {
            "Principiante": 0.3,
            "Intermedio": 0.6,
            "Avanzado": 0.9,
            "Elite": 1.1,
        },
    },
    # Fuente: criterio coach: OHS ~65% del Front Squat por requerimientos de movilidad y estabilidad

    # ==============================
    # PESO MUERTO
    # ==============================
    "Deadlift (Peso Muerto)": {
        "unidad": "ratio",
        "M": {
            "Principiante": 1.0,
            "Intermedio": 1.5,
            "Avanzado": 2.0,
            "Elite": 2.5,
        },
        "F": {
            "Principiante": 0.8,
            "Intermedio": 1.2,
            "Avanzado": 1.6,
            "Elite": 2.0,
        },
    },
    # Fuente: strengthlevel.com (percentiles: 25%=1.0x, 50%=1.5x, 80%=2.0x, 95%+=2.5x para M 80kg)
    # Ajustado a contexto CrossFit (no powerlifting): Elite 2.5x en vez de 3.0x
    # WODprep (Ben Bergeron) usa 2.5x como techo realista para atleta de CrossFit

    # ==============================
    # LEVANTAMIENTOS OLÍMPICOS
    # ==============================
    "Clean (Cargada)": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.5,
            "Intermedio": 1.0,
            "Avanzado": 1.3,
            "Elite": 1.7,
        },
        "F": {
            "Principiante": 0.4,
            "Intermedio": 0.8,
            "Avanzado": 1.0,
            "Elite": 1.3,
        },
    },
    # Fuente: strengthlevel.com (Clean percentiles) + criterio coach

    "Snatch (Arrancada)": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.4,
            "Intermedio": 0.8,
            "Avanzado": 1.0,
            "Elite": 1.3,
        },
        "F": {
            "Principiante": 0.3,
            "Intermedio": 0.6,
            "Avanzado": 0.8,
            "Elite": 1.0,
        },
    },
    # Fuente: strengthlevel.com + criterio coach: Snatch ~75% del Clean

    "Jerk (Envión)": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.5,
            "Intermedio": 0.9,
            "Avanzado": 1.2,
            "Elite": 1.5,
        },
        "F": {
            "Principiante": 0.4,
            "Intermedio": 0.7,
            "Avanzado": 0.9,
            "Elite": 1.2,
        },
    },
    # Fuente: criterio coach: Jerk ~90% del Clean (split jerk > push jerk > push press)

    # ==============================
    # THRUSTER
    # ==============================
    "Thruster": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.4,
            "Intermedio": 0.8,
            "Avanzado": 1.0,
            "Elite": 1.3,
        },
        "F": {
            "Principiante": 0.3,
            "Intermedio": 0.6,
            "Avanzado": 0.8,
            "Elite": 1.0,
        },
    },
    # Fuente: criterio coach: Thruster (Front Squat + Push Press) ~65-70% del Clean

    # ==============================
    # D5 (2026-10-28): variantes de arrancada/cargada que el box programa
    # ==============================
    # ESTIMADO, no medido: mismas reglas de extrapolación que declara el encabezado del archivo
    # (el doc `PROPUESTA_CLASIFICACION_NIVEL.md` §5.2 las deriva de las tablas existentes).
    # Ajustar con el coach si el box tiene datos propios.
    "Power Clean": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.40,
            "Intermedio": 0.80,
            "Avanzado": 1.05,
            "Elite": 1.35,
        },
        "F": {
            "Principiante": 0.32,
            "Intermedio": 0.64,
            "Avanzado": 0.80,
            "Elite": 1.05,
        },
    },
    # Estimado: Power Clean ~80% del Clean (la barra no baja al piso).
    # Split Jerk NO lleva tabla: es alias de "Jerk (Envión)" (nivel_service.ALIAS_ESTANDAR).

    "Power Snatch": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.32,
            "Intermedio": 0.64,
            "Avanzado": 0.80,
            "Elite": 1.05,
        },
        "F": {
            "Principiante": 0.24,
            "Intermedio": 0.48,
            "Avanzado": 0.64,
            "Elite": 0.80,
        },
    },
    # Estimado: Power Snatch ~80% del Snatch.

    "Push Jerk": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.45,
            "Intermedio": 0.81,
            "Avanzado": 1.08,
            "Elite": 1.35,
        },
        "F": {
            "Principiante": 0.36,
            "Intermedio": 0.63,
            "Avanzado": 0.81,
            "Elite": 1.08,
        },
    },
    # Estimado: Push Jerk ~90% del Split Jerk (no hay split, se recibe en fuerza).

    "Push Press": {
        "unidad": "ratio",
        "M": {
            "Principiante": 0.40,
            "Intermedio": 0.72,
            "Avanzado": 0.96,
            "Elite": 1.20,
        },
        "F": {
            "Principiante": 0.32,
            "Intermedio": 0.56,
            "Avanzado": 0.72,
            "Elite": 0.96,
        },
    },
    # Estimado: Push Press ~80% del Split Jerk (usa el impulso de piernas, sin split).
}
