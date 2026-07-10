"""
Estándares de habilidad gimnástica para clasificación de nivel.

Fuentes:
  - WODprep Blog (Ben Bergeron / CrossFit New England): estándares de
    gimnasia aplicados a CrossFit (pull-ups, muscle-ups, HSPU, etc.)
  - CrossFit Games Rulebook: definiciones de movimiento válido
  - BOXROX.com: tablas de clasificación por nivel para gimnasia CrossFit
  - GymnasticsWOD / Invictus Fitness: progresiones gimnásticas
  - Element Competitions: categorías de habilidad para competiciones
  - Criterio de coach: extrapolación de relaciones de dificultad entre
    movimientos (T2R es ~65% de T2B, BMU > RMU, etc.)

TIPOS:
  - "reps_unbroken": repeticiones consecutivas SIN cortar (unbroken set)
  - "distancia": metros recorridos (ej: Handstand Walk)
  - "logrado_binario": si se logra o no, con reps bajas como umbral (ej: Muscle Up)
  - "reps_cualquier_forma": reps permitiendo descanso (ej: Box Jumps)

Los valores representan el estándar para UNA SOLA SERIE sin cortar,
o la medida que define el nivel.
"""

CROSSFIT_HABILIDADES = {
    # ==============================
    # DOMINADAS / PULL-UPS
    # ==============================
    "Pull-ups (Dominadas)": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 1,
            "Intermedio": 10,
            "Avanzado": 20,
            "Elite": 30,
        },
        "F": {
            "Principiante": 1,
            "Intermedio": 5,
            "Avanzado": 12,
            "Elite": 20,
        },
    },
    # Fuente: WODprep (Ben Bergeron) + criterio coach - Pull-ups standards
    # Principiante: lograr al menos 1 pull-up strict
    # Intermedio: 10(M)/5(F) pull-ups kipping consecutivas
    # Avanzado: 20(M)/12(F) kipping consecutivas o 10(M)/5(F) strict
    # Elite: 30(M)/20(F) kipping o 15(M)/8(F) strict

    "Chest to Bar (C2B)": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 0,
            "Intermedio": 5,
            "Avanzado": 15,
            "Elite": 25,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 3,
            "Avanzado": 10,
            "Elite": 18,
        },
    },
    # Fuente: CrossFit Games standards - C2B requiere el pecho tocar barra claramente
    # Es ~70-80% del volumen de Pull-ups por mayor dificultad

    # ==============================
    # TOES TO BAR / TOES TO RING
    # ==============================
    "Toes to Bar (T2B)": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 0,
            "Intermedio": 10,
            "Avanzado": 20,
            "Elite": 30,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 8,
            "Avanzado": 15,
            "Elite": 25,
        },
    },
    # Fuente: BOXROX / WODprep - T2B standards
    # Principiante: no logra T2B aún (puede hacer Knee Raises)
    # Intermedio: 10-15 reps sin bajar de la barra
    # Avanzado: 20+ reps unbroken
    # Elite: 30+ reps unbroken

    "Toes to Ring (T2R)": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 0,
            "Intermedio": 5,
            "Avanzado": 12,
            "Elite": 20,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 4,
            "Avanzado": 10,
            "Elite": 16,
        },
    },
    # Fuente: Element Competitions / Invictus - T2R es más difícil que T2B
    # por requerir mayor control corporal y llegar más alto
    # ~60-70% del volumen de T2B

    # ==============================
    # MUSCLE-UPS
    # ==============================
    "Bar Muscle-up (BMU)": {
        "tipo": "logrado_binario",
        "M": {
            "Principiante": 0,
            "Intermedio": 1,
            "Avanzado": 5,
            "Elite": 12,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 1,
            "Avanzado": 3,
            "Elite": 8,
        },
    },
    # Fuente: CrossFit Games / WODprep - Bar Muscle-up standards
    # Principiante: no logra BMU aún
    # Intermedio: logra 1 BMU (lo relevante es si se logra o no)
    # Avanzado: 5+ consecutivos
    # Elite: 12+ consecutivos

    "Ring Muscle-up (RMU)": {
        "tipo": "logrado_binario",
        "M": {
            "Principiante": 0,
            "Intermedio": 1,
            "Avanzado": 3,
            "Elite": 8,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 1,
            "Avanzado": 2,
            "Elite": 5,
        },
    },
    # Fuente: CrossFit Games / WODprep - Ring Muscle-up standards
    # RMU es significativamente más difícil que BMU
    # Principiante: no logra RMU
    # Intermedio: logra 1 RMU
    # Avanzado: 3(M)/2(F) consecutivos
    # Elite: 8(M)/5(F) consecutivos

    # ==============================
    # PARADAS DE MANOS
    # ==============================
    "Handstand Push-ups / HSPU (Flexiones invertidas)": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 0,
            "Intermedio": 3,
            "Avanzado": 10,
            "Elite": 15,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 2,
            "Avanzado": 7,
            "Elite": 12,
        },
    },
    # Fuente: WODprep / CrossFit Games Rulebook - HSPU standards
    # Principiante: no logra HSPU (puede hacer pike push-ups)
    # Intermedio: 3(M)/2(F) HSPU strict
    # Avanzado: 10(M)/7(F) HSPU kipping
    # Elite: 15(M)/12(F) HSPU kipping

    "Handstand Walk / HSW (Caminata de manos)": {
        "tipo": "distancia",
        "M": {
            "Principiante": 0,
            "Intermedio": 5,
            "Avanzado": 15,
            "Elite": 25,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 3,
            "Avanzado": 10,
            "Elite": 20,
        },
    },
    # Fuente: CrossFit Games standards - HSW distancia en metros
    # Principiante: no logra caminar en manos
    # Intermedio: 3-5 metros sin caer
    # Avanzado: 10-15 metros controlados
    # Elite: 20-25+ metros

    # ==============================
    # CUERDA
    # ==============================
    "Rope Climb (Subida de cuerda usando los pies)": {
        "tipo": "logrado_binario",
        "M": {
            "Principiante": 0,
            "Intermedio": 1,
            "Avanzado": 3,
            "Elite": 5,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 1,
            "Avanzado": 2,
            "Elite": 4,
        },
    },
    # Fuente: BOXROX / CrossFit Games - Rope Climb (15ft/4.5m)
    # Se mide en ascensos completos a 4.5m
    # Principiante: no logra subir
    # Intermedio: logra 1 ascenso usando pies
    # Avanzado: 3 ascensos consecutivos
    # Elite: 5+ ascensos consecutivos

    "Legless Rope Climb (Subida de cuerda solo con manos / sin piernas)": {
        "tipo": "logrado_binario",
        "M": {
            "Principiante": 0,
            "Intermedio": 0,
            "Avanzado": 1,
            "Elite": 3,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 0,
            "Avanzado": 1,
            "Elite": 2,
        },
    },
    # Fuente: CrossFit Games standards - Legless Rope Climb
    # Es un movimiento extremadamente avanzado
    # Principiante/Intermedio: no logra legless
    # Avanzado: logra 1 ascenso legless
    # Elite: 3(M)/2(F) ascensos consecutivos

    # ==============================
    # SALTOS - DOBLES Y SIMPLES
    # ==============================
    "Double Unders / DU (Saltos dobles)": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 1,
            "Intermedio": 20,
            "Avanzado": 50,
            "Elite": 100,
        },
        "F": {
            "Principiante": 1,
            "Intermedio": 20,
            "Avanzado": 50,
            "Elite": 100,
        },
    },
    # Fuente: BOXROX / WODprep - Double Under standards
    # No varía por género en estándares de CrossFit
    # Principiante: logra al menos 1 DU
    # Intermedio: 20 DU unbroken
    # Avanzado: 50 DU unbroken
    # Elite: 100+ DU unbroken

    "Single Unders / SU (Saltos simples)": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 10,
            "Intermedio": 50,
            "Avanzado": 100,
            "Elite": 200,
        },
        "F": {
            "Principiante": 10,
            "Intermedio": 50,
            "Avanzado": 100,
            "Elite": 200,
        },
    },
    # Fuente: CrossFit general standards
    # No varía por género
    # Es la progresión natural previa a DU

    # ==============================
    # PISTOL SQUAT
    # ==============================
    "Pistol Squat": {
        "tipo": "logrado_binario",
        "M": {
            "Principiante": 0,
            "Intermedio": 1,
            "Avanzado": 5,
            "Elite": 10,
        },
        "F": {
            "Principiante": 0,
            "Intermedio": 1,
            "Avanzado": 5,
            "Elite": 10,
        },
    },
    # Fuente: GymnasticsWOD / Invictus Fitness - Pistol Squat standards
    # No varía significativamente por género
    # Principiante: no logra pistols
    # Intermedio: logra 1 pistol por pierna
    # Avanzado: 5 alternados
    # Elite: 10+ alternados

    # ==============================
    # BURPEES
    # ==============================
    "Burpees": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 5,
            "Intermedio": 15,
            "Avanzado": 25,
            "Elite": 40,
        },
        "F": {
            "Principiante": 5,
            "Intermedio": 15,
            "Avanzado": 25,
            "Elite": 40,
        },
    },
    # Fuente: CrossFit standards generales
    # No varía por género
    # Burpees con pecho al piso y salto con manos arriba

    # ==============================
    # CAJÓN
    # ==============================
    "Box Jumps (Saltos al cajón)": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 5,
            "Intermedio": 15,
            "Avanzado": 25,
            "Elite": 40,
        },
        "F": {
            "Principiante": 5,
            "Intermedio": 15,
            "Avanzado": 25,
            "Elite": 40,
        },
    },
    # Fuente: CrossFit standards - Box Jump (cajón 24"/20" estándar)
    # No varía por género significativamente si se ajusta altura de cajón

    "Box Jump Over": {
        "tipo": "reps_unbroken",
        "M": {
            "Principiante": 3,
            "Intermedio": 10,
            "Avanzado": 20,
            "Elite": 30,
        },
        "F": {
            "Principiante": 3,
            "Intermedio": 10,
            "Avanzado": 20,
            "Elite": 30,
        },
    },
    # Fuente: CrossFit standards - Box Jump Over requiere pasar al otro lado
    # Ligeramente más difícil que Box Jump tradicional

    # ==============================
    # BEAR CRAWL
    # ==============================
    "Bear Crawl (Caminata de oso)": {
        "tipo": "distancia",
        "M": {
            "Principiante": 5,
            "Intermedio": 15,
            "Avanzado": 25,
            "Elite": 50,
        },
        "F": {
            "Principiante": 5,
            "Intermedio": 15,
            "Avanzado": 25,
            "Elite": 50,
        },
    },
    # Fuente: CrossFit general standards - Bear Crawl
    # Se mide en metros
    # No varía por género
}
