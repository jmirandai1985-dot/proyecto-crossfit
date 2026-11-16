"""Familias de formulario de entrenamiento (fijas).

Cada disciplina declara con qué formulario se publican sus entrenamientos. El
valor viaja a `disciplinas.tipo_formulario` y el modal del coach lo usa para
elegir el componente de formulario. Las seis familias son parte del contrato:
agregar una nueva exige código (frontend y, si cambia la validación, backend).
"""

TIPOS_FORMULARIO = (
    "wod_metcon",       # CrossFit, Funcional, HIIT (formulario histórico)
    "fuerza",           # GAP, Levantamiento Olímpico, Musculación, Calistenia
    "secuencia",        # Yoga, Pilates, Movilidad
    "rounds_tecnica",   # Boxeo, Kickboxing, Artes marciales
    "intervalos",       # Running, Ciclismo, Natación
    "libre",            # Zumba, Baile, otros (catch-all)
)

TIPO_FORMULARIO_DEFAULT = "wod_metcon"
