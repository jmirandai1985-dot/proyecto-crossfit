# Segmentación de alumnos: arquetipos (K-Means + escalera)

> Documento de SOLO LECTURA del código. Explica, en lenguaje simple, cómo el sistema
> agrupa a los alumnos del box en **arquetipos**, por qué hay **6 arquetipos con K=5** y
> qué significa el **silhouette ≈ 0.41**. Fuentes: `backend/ml/segmentacion.py`,
> `frontend/src/components/kpis/arquetipoEstilo.js` y `backend/ml/features.py`.

## 1. ¿Qué es esto?

Es un modelo de **retención**: mira cómo se comporta cada alumno (hace cuánto que no viene,
cuántas veces entrena, si tiene plan) y lo mete en un **grupo**. Cada grupo recibe un
nombre entendible —un **arquetipo**— para que el equipo sepa a quién cuidar primero.

Ejemplos de preguntas que responde: ¿a quién estoy por perder? ¿quién ya se fue y quizás
pueda volver? ¿quién es fiel? ¿quién es nuevo y todavía se está enganchando?

## 2. Cómo se calcula (paso a paso)

1. **Se arma una tabla con una fila por alumno** y **5 datos** de cada uno
   (`FEATURES_SEGMENTACION`):
   - `dias_desde_ultima_asistencia` (cuántos días pasaron desde la última clase),
   - `asistencias_ultimos_30_dias`,
   - `asistencias_ultimos_90_dias`,
   - `antiguedad_dias` (hace cuánto es alumno),
   - `tiene_suscripcion_activa` (0 o 1).
   Salen de las **mismas consultas** que usan los KPIs (`ml/features.py`): hay una sola
   definición de "asistencia" en todo el proyecto.
2. **Se escalan** los 5 datos (`StandardScaler`). Es obligatorio porque se mide distancia:
   sin escalar, "asistencias en 90 días" (que llega a decenas) taparía a "tiene plan" (0/1).
3. **K-Means** agrupa a los alumnos en **5 grupos** (`K_CLUSTERS = 5`), con
   `random_state = 42` y `n_init = 10` (para que el resultado sea reproducible).
4. **Se etiqueta cada grupo** con la escalera de la sección 4.
5. Si el box tiene **menos de 25 alumnos** (`MIN_ALUMNOS`), no se entrena: K-Means no es
   confiable con tan poca gente (el endpoint responde **409**, no inventa grupos).

## 3. Dato clave: 6 arquetipos ≠ 5 grupos

**K = 5 es cuántos grupos arma el algoritmo** (cuántas "nubes" de alumnos separa por
distancia). **6 es el vocabulario de etiquetas de negocio** que existen para nombrar a esos
grupos. Son dos cosas distintas:

- El algoritmo siempre deja **5 grupos** (o menos si hay menos alumnos que grupos).
- Cada grupo se **etiqueta con UNA** de las 6 etiquetas de la escalera (sección 4).
- Por eso, en una corrida puede haber **hasta 5 etiquetas distintas** (nunca las 6 a la
  vez). Y puede haber etiquetas con **0 alumnos** si ningún grupo cayó en esa regla: son
  franjas del negocio que existen aunque esta foto no las use.

**Cómo se asigna el arquetipo a cada alumno:** NO se decide alumno por alumno. Se decide
**por grupo**: se miran las **medianas** del grupo (5 números "típicos", robustos a valores
raros) y la escalera dice qué etiqueta le toca al grupo entero. Todos los alumnos de ese
grupo reciben el mismo arquetipo. Detalle importante: **% de suscripción activa** se mira
como proporción del grupo (no como mediana), porque es un dato 0/1.

## 4. La escalera de 6 reglas (gana la PRIMERA que matchea)

Se evalúan en orden sobre las medianas del grupo; la primera que se cumple gana. `med(x)`
es la mediana de `x` en el grupo; el umbral de abandono son **45 días** (el mismo del label
de churn del proyecto, `features.UMBRAL_ABANDONO_DIAS`).

| # | Arquetipo | Regla (sobre las medianas del grupo) | En palabras |
|---|---|---|---|
| L1 | **ABANDONADO_PERDIDO** | `%susc < 0.50` y `med(dias) > 45` y `med(a90) == 0` | Sin plan y más de 45 días sin venir, y **nada** en 90 días: ya se fue. |
| L2 | **ABANDONADO_RECUPERABLE** | `%susc < 0.50` y `med(dias) > 45` y `med(a90) > 0` | Igual, pero **algo** vino en 90 días: vale una campaña de recuperación. |
| L3 | **EN_RIESGO** | `med(dias) > 30` | Se está alejando (más de 30 días) sin llegar a "abandonó". |
| L4 | **NUEVO** | `med(antiguedad) <= 60` y `med(dias) <= 10` | Recién entra (≤ 60 días) y ya viene seguido. |
| L5 | **ACTIVO_EN_DECLIVE** | `med(asist_30) < 8` | Tiene plan pero bajó la frecuencia (< 8 clases en 30 días). |
| L6 | **ACTIVO_FIEL** | (default) | El resto: alta frecuencia sostenida (≥ 8 en 30 días). |

Descripciones para el usuario (las mismas que muestra el panel) en `DESCRIPCIONES`.

## 5. Por qué K=5 (y no K=4 u otro)

Se probó contra **datos reales de PROD (106 alumnos)** y K=5 ganó:

- **Separa mejor:** silhouette **0.4699** con K=5 vs **0.4450** con K=4 (más alto = grupos
  más compactos y más lejanos entre sí).
- **Es estable:** probado con **10 semillas** distintas, el resultado casi no cambia
  (**ARI mínimo 0.9714**; 9 de 10 semillas dan **exactamente la misma** partición). Un
  modelo que cambia de grupos al azar no sirve para decidir.
- Se **descartaron features derivadas** (`ratio_caida`, `asist_semanal_90`): son funciones
  de las 5 de arriba (colineales), bajaban la estabilidad (ARI mínimo 0.873) y mezclaban
  grupos (aparecía un grupo con 68% de suscripción activa). Con 5 features "puras" los
  grupos quedan más interpretables.

> ⚠️ El código lo dice: `K_CLUSTERS = 5` está "validado empíricamente; NO cambiar sin
> re-validar". Cambiar K obliga a repetir este análisis.

## 6. ¿Qué significa "silhouette 0.41"?

El **silhouette** mide en una escala de **−1 a 1** qué tan bien armados están los grupos:

- **Cerca de 1:** cada alumno está mucho más cerca de su grupo que de los demás (grupos
  muy limpios y separados).
- **Cerca de 0:** los grupos se tocan entre sí (fronteras difusas).
- **Negativo:** muchos alumnos quedaron en el grupo equivocado.

**≈ 0.41 es una separación MODERADA**: claramente mejor que agrupar al azar, y bastante
bueno para datos de **comportamiento humano** (que es "ruidoso" por naturaleza: dos
alumnos parecidos pueden caer en grupos distintos por un día de diferencia). No es
"perfecto", y no tiene que serlo: el objetivo no es etiquetar a la perfección sino
**ordenar la prioridad de acción** (a quién llamar primero).

Nota: el valor cambia un poco entre corridas porque depende de cuántos alumnos haya y de
la fecha de referencia. El diseño se validó con **0.4699** (106 alumnos) y el número que
suele aparecer en la defensa es **≈ 0.41** del último entrenamiento en PROD. Lo importante
es que sea **establemente > 0** y que la partición sea reproducible (sección 5).

## 7. Frases listas para la defensa

1. "El sistema tiene **6 arquetipos pero el algoritmo agrupa en 5 grupos**: K es cuántas
   nubes de comportamiento separa K-Means, y los 6 arquetipos son las etiquetas de negocio
   que repartimos sobre esos grupos; cada grupo recibe una sola etiqueta."
2. "Elegí **K=5** porque lo medí contra datos reales: separa mejor que K=4 (silhouette
   0.47 vs 0.45) y es **estable**: con 10 semillas distintas da la misma partición 9 de
   10 veces (ARI mínimo 0.97)."
3. "El **silhouette ≈ 0.41** quiere decir que los grupos están **moderadamente separados**:
   mucho mejor que azar, y normal para datos de comportamiento humano; el objetivo es
   **priorizar a quién atender**, no una etiqueta perfecta."
4. "El arquetipo NO se calcula alumno por alumno: se calcula **por grupo**, mirando las
   **medianas** del grupo (que no se dejan arrastrar por casos raros), y se asigna esa
   etiqueta a todo el grupo."

