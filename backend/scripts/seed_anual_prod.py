"""
Seed ANUAL de datos sintéticos para ML — 300 alumnos, 12 meses — PROD y TEST.

Reemplaza al seed viejo (`seed_ml_data_prod.py`, 100 alumnos / 8 meses / sólo asistencias)
y agrega lo que faltaba para que los modelos y los KPIs tengan de dónde aprender:
clases, reservas, créditos, cancelaciones, perfiles de churn y 12 meses de pagos.

⚠️  ESCRIBE EN LA BASE DE DATOS REAL DE PRODUCCIÓN (o en TEST, según `--destino`).
    PROD todavía NO tiene alumnos reales y los datos son para la demo de la defensa de
    título. Por eso los guards son duros y hay que CONFIRMAR POR TECLADO antes de escribir.

──────────────────────────────────────────────────────────────────────────────
GUARDS (todos deben pasar; corren ANTES de leer/escribir cualquier fila)
──────────────────────────────────────────────────────────────────────────────
1. `--destino prod|test` es OBLIGATORIO (no hay default). De él sale `ENVIRONMENT`
   (`production` / `test`) y por lo tanto qué `.env` lee `app.core.config`.
2. La URL tiene que coincidir EXACTAMENTE con el destino:
     * prod: el endpoint de PROD (`PROD_BRANCH_ID` = `ep-nameless-sound-b6km6wyi`,
       host `nameless-sound`). Cualquier OTRO host aborta.
     * test: un endpoint de TEST (`TEST_BRANCH_IDS` = `ep-jolly-butterfly-b6ty2z89`,
       host `jolly-butterfly`) y NUNCA el de PROD (denylist).
   Los ids se leen de `app.core.config` (única fuente de verdad) y además se valida
   que el de PROD siga siendo `nameless-sound`: si Neon vuelve a recrear el endpoint,
   el script aborta en vez de escribir en una base que ya no es la que espera.
   ⚠️ `withered-silence` era el endpoint de PROD **viejo** (migración del 2026-09-24).
   El guard del seed anterior (`"withered-silence" in DATABASE_URL`) ya NO puede pasar:
   por eso este script no lo usa ni como host ni como confirmación.
3. VENTANA DE EJECUCIÓN (**sólo con `--destino prod`**): aborta si hoy es día 1 o 15 (el
   mantenimiento escribe esos días: pasos 1-9 = vencidos, huérfanas, cierre de asistencia y
   aforo) o si el mes en curso es septiembre de 2026 (el run del 1/10 vencería TODAS las
   suscripciones de septiembre y cortaría por `MAX_VENCIDOS_PCT`). Ventana prevista en PROD:
   2 a 5 de octubre de 2026. En TEST no corre ningún cron de mantenimiento, así que no hay
   nada que romper: la ventana NO aplica y se puede sembrar cualquier día.
4. Confirmación por teclado con frase exacta: `SI QUIERO PROD` / `SI QUIERO TEST`.
   Se pide ANTES del dry-run y antes de cualquier escritura o borrado.
   (Si ya hay datos del seed, se pide una SEGUNDA confirmación para el recambio.)

──────────────────────────────────────────────────────────────────────────────
MARCADORES (lo que hace el seed idempotente y reversible)
──────────────────────────────────────────────────────────────────────────────
Los datos sintéticos se identifican por TRES marcas, ninguna de las cuales toca filas
reales (ver `borrar_seed_anual.py`):
  * usuarios:        `correo LIKE 'demo.prod.anual.%@example.com'`
                     (prefijo nuevo DENTRO de `PROD_PERMITIDOS` = `demo.prod.%@example.com`,
                     así que A.1(c) del mantenimiento los sigue viendo como demo declarada
                     y NO hace falta tocar `PROD_PERMITIDOS` en Render).
  * transacciones:   `descripcion LIKE 'DEMOPRODANUAL%'` (también cae dentro de
                     `DEMOPROD%`, el LIKE del seed viejo).
  * clases:          `created_at = MARCA_TS` (timestamp constante y absurdo). `clases` no
                     tiene ninguna columna libre ni UNIQUE, así que el marcador es esa
                     constante: al borrar se exige `created_at = MARCA_TS` Y que la clase
                     se haya quedado sin reservas y sin asistencias.
`clases` y `reservas` NO tienen UNIQUE (sólo PK + índices planos), así que la
idempotencia NO puede usar `ON CONFLICT`: es "borrar por marca + reinsertar", en la
MISMA transacción (si el insert falla, el rollback deja los datos viejos intactos).

──────────────────────────────────────────────────────────────────────────────
INVARIANTES QUE EL SEED RESPETA (0 cambios / 0 detecciones nuevas en el mantenimiento)
──────────────────────────────────────────────────────────────────────────────
`mantenimiento_cloud.py` con `DRY_RUN=1` tiene que dar EXACTAMENTE los mismos hallazgos
antes y después del seed (salvo A.1(c), que es el conteo informativo de demo: sube en
N_ALUMNOS por diseño). Lo que sostiene eso:
 1. Label de churn (`ml/features.label_abandonado`): sin suscripción vigente hoy Y > 45
    días sin asistir ⇔ perfil BAJA. Los otros perfiles tienen suscripción vigente y
    asistencia de los últimos 45 días. Un alumno de BAJA no vuelve a asistir.
 2. `suscripciones.estado` sólo `activo` (la del mes en curso) o `vencido` (las pasadas):
    NO se generan `pendiente` (el paso 2 y `transacciones_huerfanas.py` las rechazarían) ni
    `rechazado`. `usuarios.estado` sólo `activo` o `baja`, con
    `activo = (estado == 'activo')` (CHECK `ck_usuarios_activo_estado` y detección A.1(a)).
 3. Paso 8 (cierre de asistencia): TODA reserva viva de una clase ya terminada tiene
    `asistencia_marcada_at` (nunca `asistencia_via='cierre'`: esa vía la escribe el job).
    `asistio = true ⇒ asistencia_marcada_at IS NOT NULL` (detección A.4(b)).
 4. Paso 9 / A.2(a) (aforo): `clases.asistentes_confirmados` == reservas VIVAS de la clase
    (`estado NOT IN ('cancelled','cancelada')`) para TODA clase que el seed toca, incluidas
    las clases REALES que reciben reservas de alumnos del seed.
 5. A.2(c): nunca más reservas vivas que `cupo_maximo` (el sábado queda exacto en el cupo
    16 del único horario real, que es el techo de la grilla).
 6. A.2(b): un alumno no tiene dos reservas vivas en la misma clase (ni dos clases el
    mismo día).
 7. A.3 (créditos): por suscripción, `creditos_totales - creditos_disponibles` == reservas
    vivas de la ventana + cancelaciones TARDÍAS (>= 6 h antes ⇒ no hubo devolución). Los
    planes ilimitados van con `creditos_* = NULL` (excluidos de A.3, igual que la app).
    Las cancelaciones se generan con márgenes holgados (24 h antes / 2 h después del
    inicio) para que la clasificación temprana/tardía NO dependa del offset de DST.
 8. A.5 (coaches): no se crean clases FUTURAS (las de los próximos 7 días son las reales
    que ya generó la app). En las clases del seed sólo se usa un `coach_id` que sea coach
    activo de esa disciplina (round-robin) y NULL cuando `disciplinas.requiere_coach=false`
    (Musculación / Open Box).
 9. Agenda real: la grilla sale de `horarios` (7:00-22:00 × crossfit/Musculación/Open
    Box/Gap, sábado sólo 10:00-12:00) y las clases que ya existen se REUSAN. Domingo sin
    asistencia.

──────────────────────────────────────────────────────────────────────────────
USO (PowerShell, desde backend/)
──────────────────────────────────────────────────────────────────────────────
    $env:ENVIRONMENT="test";       python3.12 scripts\\seed_anual_prod.py --destino test --dry-run
    $env:ENVIRONMENT="test";       python3.12 scripts\\seed_anual_prod.py --destino test
    $env:ENVIRONMENT="production"; python3.12 scripts\\seed_anual_prod.py --destino prod --dry-run
    $env:ENVIRONMENT="production"; python3.12 scripts\\seed_anual_prod.py --destino prod
Reversión:  python3.12 scripts\\borrar_seed_anual.py --destino <test|prod>
Limpieza OBLIGATORIA antes del próximo día 1 (1/11/2026): ese día el paso 1 marcaría
vencidas las suscripciones del mes del seed y el run cortaría por `MAX_VENCIDOS_PCT`
(ver README_seed_anual.md).
"""
from __future__ import annotations

import argparse
import importlib
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence

# Consola de Windows: al pipear la salida los emojis/acentos romperían con cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════════
#  1. CONFIGURACIÓN  (editar SOLO acá)
# ══════════════════════════════════════════════════════════════════════════
TENANT_ID = 1
N_ALUMNOS = 300
PERFILES = ("FIEL", "REACTIVADO", "PRUEBA", "BAJA")
PROPORCION = {"FIEL": 0.55, "REACTIVADO": 0.15, "PRUEBA": 0.15, "BAJA": 0.15}

MESES_HISTORIA = 12
DIAS_VENTANA = 365          # ventana hacia atrás: 12 meses de historia
DIAS_RESERVA_FUTURA = 7     # reservas de los próximos 7 días (decisión 5)
ASISTENCIAS_DIA_LV = 100    # objetivo medio por día hábil (ponderado por PESO_MES)
ASISTENCIAS_SABADO = 16     # cupo del único horario de sábado (no se puede superar)
UMBRAL_ABANDONO_DIAS = 45   # regla del label (ml/features.UMBRAL_ABANDONO_DIAS)
DIAS_CIERRE_MANTENIMIENTO = 7   # paso 8: cierra clases terminadas hace más de 7 días
HORAS_DEVOLUCION = 6        # app/A.3: >= 6 h antes de la clase ⇒ se devuelve el crédito
DIAS_RECIENTE_MAX = 40      # tope duro: ningún perfil activo queda más de esto sin asistir
DIAS_PRUEBA_MAX = 45        # perfil PRUEBA: alta dentro de estos días

SEMILLA_RANDOM = 20260912   # fija el dataset: el dry-run es igual a la ejecución
PREFIJO_CORREO = "demo.prod.anual."
DOMINIO_CORREO = "@example.com"   # reservado por IANA: pasa EmailStr y no es de nadie
PASSWORD_SINTETICA = "MlAnual1234!"
MARCA_DESC = "DEMOPRODANUAL"      # prefijo de transacciones_financieras.descripcion
# Marcador de las clases del seed. Constante (no `now()`): el borrado exige este valor, así
# que el seed es idempotente/reversible sin tocar ninguna columna real de `clases`.
MARCA_TS = datetime(2026, 10, 2, 4, 17, 3, 123456, tzinfo=timezone.utc)

# ── Ventana de ejecución prohibida (guard 3) — SÓLO se evalúa con `--destino prod` ──
DIAS_MANTENIMIENTO = (1, 15)      # el job escribe esos días
MES_PROHIBIDO = "2026-09"         # el run del 1/10 vencería todas las de septiembre
# ── Hosts de Neon (denylist/allowlist; los ids completos salen de app.core.config) ──
HOST_PROD = "nameless-sound"      # ep-nameless-sound-b6km6wyi (rama principal)
HOST_TEST = "jolly-butterfly"     # ep-jolly-butterfly-b6ty2z89 (rama de desarrollo)
HOST_PROD_VIEJO = "withered-silence"   # PROD ANTES del 2026-09-24 (endpoint ya retirado)

# Estacionalidad chilena: enero/febrero y julio son vacaciones; marzo y septiembre son
# picos. Pondera la asistencia diaria y las altas: sin esto el dataset es plano y el
# modelo de forecast no tiene ciclo anual que aprender.
PESO_MES = {
    1: 0.45, 2: 0.55, 3: 1.30, 4: 1.10, 5: 1.00, 6: 0.95,
    7: 0.75, 8: 1.00, 9: 1.30, 10: 1.05, 11: 1.00, 12: 0.80,
}
# Peso relativo de cada perfil al repartir los cupos del día (los FIEL van más).
PESO_PERFIL = {"FIEL": 3.0, "REACTIVADO": 2.2, "PRUEBA": 0.7, "BAJA": 2.6}
# Bandas horarias (hora de inicio, fin exclusivo) para la afinidad alumno-horario.
BANDAS = ((7, 9), (9, 14), (14, 18), (18, 22))
# Peso de cada franja al repartir el objetivo del día entre los slots: los peaks reales
# del box son 7-9 y 18-22.
PESO_FRANJA = {(7, 9): 1.0, (9, 14): 0.6, (14, 18): 0.9, (18, 22): 2.2}
# Las suscripciones se anclan a MEDIODÍA UTC: así `fecha_inicio::date` y
# `fecha_expiracion::date` dan el MISMO día en UTC y en America/Santiago (la sesión de
# `psql` del mantenimiento usa TZ de Chile). Un `00:00:00+00` se correría un día.
HORA_UTC_SUSCRIPCION = 12

NOMBRES = [
    "Camila", "Josefa", "Martina", "Antonia", "Valentina", "Isidora", "Florencia",
    "Catalina", "Fernanda", "Constanza", "Daniela", "Javiera", "Ignacia", "Trinidad",
    "Matías", "Benjamín", "Vicente", "Sebastián", "Tomás", "Joaquín", "Diego",
    "Cristóbal", "Nicolás", "Felipe", "Andrés", "Rodrigo", "Ignacio", "Maximiliano",
    "Gabriel", "Lucas", "Amanda", "Paz", "Rocío", "Magdalena", "Emilia", "Violeta",
]
APELLIDOS = [
    "González", "Muñoz", "Rojas", "Díaz", "Pérez", "Soto", "Contreras", "Silva",
    "Martínez", "Sepúlveda", "Morales", "Rodríguez", "López", "Fuentes", "Hernández",
    "Torres", "Araya", "Flores", "Espinoza", "Valenzuela", "Castillo", "Tapia",
    "Reyes", "Núñez", "Bravo", "Vergara", "Cáceres", "Vidal", "Pizarro", "Leiva",
]

ESTADOS_USUARIO = ("activo", "pendiente_activacion", "rechazado", "baja")
ESTADOS_SUSCRIPCION = ("pendiente", "activo", "vencido", "rechazado")
ESTADO_RESERVA_VIVA = "confirmada"       # lo que escribe la app al reservar
ESTADO_RESERVA_CANCELADA = "cancelled"   # shared.estados.ESTADO_CANCELADO
ASISTENCIA_VIA = "batch"                 # vía de la app que deja marcada_por


class InvarianteError(AssertionError):
    """El plan generado no cumple una regla de negocio: NO se escribe nada."""


class GuardError(RuntimeError):
    """Un guard no pasó (destino/URL/ventana): el script aborta sin tocar la base."""


# ══════════════════════════════════════════════════════════════════════════
#  2. HELPERS PUROS  (sin base, sin app: los tests los importan tal cual)
# ══════════════════════════════════════════════════════════════════════════
def calcular_dv(rut_numero: int) -> str:
    """Dígito verificador de un RUT chileno (módulo 11)."""
    suma, multiplicador = 0, 2
    for digito in reversed(str(rut_numero)):
        suma += int(digito) * multiplicador
        multiplicador = multiplicador + 1 if multiplicador < 7 else 2
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def rut_valido(rut: str) -> bool:
    """Valida formato + DV (mismo criterio que `app.api.v1.alumnos.validar_rut`)."""
    if not rut or "-" not in rut:
        return False
    cuerpo, _, dv = rut.rpartition("-")
    if not cuerpo.isdigit() or len(cuerpo) not in (7, 8):
        return False
    return calcular_dv(int(cuerpo)).upper() == dv.upper()


def generar_rut(usados: set, rng: random.Random) -> str:
    """RUT válido y único en toda la corrida (y que no exista ya en la base)."""
    while True:
        numero = rng.randint(20_000_000, 32_999_999)
        if numero in usados:
            continue
        usados.add(numero)
        rut = f"{numero}-{calcular_dv(numero)}"
        if rut_valido(rut):
            return rut


def dt_utc(d: date, hora: int = HORA_UTC_SUSCRIPCION) -> datetime:
    """`date` -> datetime tz-aware UTC (para columnas TIMESTAMPTZ)."""
    return datetime(d.year, d.month, d.day, hora, 0, tzinfo=timezone.utc)


def primer_dia_mes(d: date) -> date:
    """Primer día del mes de `d`."""
    return date(d.year, d.month, 1)


def ultimo_dia_mes(d: date) -> date:
    """Último día del mes de `d`."""
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def mes_iso(d: date) -> str:
    """'YYYY-MM' del mes de `d` (clave de suscripción)."""
    return f"{d.year:04d}-{d.month:02d}"


def correr_mes(d: date, meses: int) -> date:
    """Primer día del mes desplazado `meses` (negativo = hacia atrás)."""
    total = (d.year * 12 + (d.month - 1)) + meses
    return date(total // 12, total % 12 + 1, 1)


def peso_estacional(d: date) -> float:
    """Peso del mes (pico marzo/septiembre, valle enero/febrero/julio)."""
    return PESO_MES[d.month]


def inicio_clase_naive(fecha: date, hora: time) -> datetime:
    """Inicio de clase como hora LOCAL chilena sin tz (así lo compara el SQL del job:
    `(c.fecha + c.hora_inicio) AT TIME ZONE 'America/Santiago'`)."""
    return datetime(fecha.year, fecha.month, fecha.day, hora.hour, hora.minute)


def franja_de(hora: time) -> tuple:
    """Franja horaria de una hora de inicio (para afinidad y reparto del día)."""
    for inicio, fin in BANDAS:
        if inicio <= hora.hour < fin:
            return (inicio, fin)
    return BANDAS[0]


def hora_min(hora: time) -> int:
    """Minutos desde las 00:00 (para ordenar horarios sin restar `time`)."""
    return hora.hour * 60 + hora.minute


def peso_franja(hora: time) -> float:
    """Peso de la franja al repartir el objetivo del día entre los slots."""
    return PESO_FRANJA[franja_de(hora)]


def ts_cancelacion(inicio_naive: datetime, temprana: bool) -> datetime:
    """Timestamp de cancelación SIN depender del offset de DST.

    El job (A.3) clasifica tardía si `updated_at > (inicio AT TIME ZONE 'Santiago')
    - 6 h`; como el offset de Chile es UTC-3/-4, escribir el naive con un margen de
    24 h hacia atrás (temprana) o 2 h hacia adelante (tardía) deja el resultado
    inequívoco en cualquiera de los dos offsets:
      * temprana: updated_at = naive - 24 h  ⇒ queda >= 14 h antes del corte.
      * tardía:   updated_at = naive + 2 h   ⇒ queda 4-5 h después del corte.
    """
    delta = timedelta(days=-1) if temprana else timedelta(hours=2)
    return (inicio_naive + delta).replace(tzinfo=timezone.utc)


def objetivo_asistencias(d: date, rng: random.Random, asistencias_dia: int,
                         asistencias_sabado: int) -> int:
    """Cuántas asistencias se buscan ese día.

    Domingo 0 (no hay clases); sábado el cupo del único horario real; día hábil
    ~`asistencias_dia` ponderado por PESO_MES (≈45 en enero, ≈130 en marzo) con un
    ruido de ±10 % para que la serie diaria no sea una línea recta.
    """
    if d.weekday() == 6:
        return 0
    if d.weekday() == 5:
        return asistencias_sabado
    base = asistencias_dia * peso_estacional(d)
    return max(20, int(round(base * rng.uniform(0.9, 1.1))))


def repartir_por_slots(objetivo: int, slots: Sequence[dict]) -> list:
    """Reparte `objetivo` entre los slots del día ponderando por franja horaria.

    Método del resto mayor: piso proporcional + reparto del sobrante entre los
    mayores restos. Nunca supera `cupo_maximo` (lo que no entra por cupo se
    redistribuye a los slots con lugar). Devuelve una lista alineada con `slots`.
    """
    if not slots:
        return []
    cupos = [int(s["cupo_maximo"]) for s in slots]
    objetivo = min(int(objetivo), sum(cupos))
    pesos = [peso_franja(s["hora_inicio"]) for s in slots]
    total_peso = sum(pesos) or 1.0
    exactos = [objetivo * p / total_peso for p in pesos]
    conteos = [min(cupos[i], int(e)) for i, e in enumerate(exactos)]
    resto = objetivo - sum(conteos)
    orden = sorted(range(len(slots)), key=lambda i: (-(exactos[i] - int(exactos[i])), i))
    while resto > 0:
        avanzo = False
        for i in orden:
            if resto == 0:
                break
            if conteos[i] < cupos[i]:
                conteos[i] += 1
                resto -= 1
                avanzo = True
        if not avanzo:      # no queda lugar: el objetivo se recorta al cupo real
            break
    return conteos


# ══════════════════════════════════════════════════════════════════════════
#  3. GENERACIÓN DEL PLAN  (en memoria; ninguna de estas funciones toca la BD)
# ══════════════════════════════════════════════════════════════════════════
def planes_preferidos(planes: Sequence[dict]) -> list:
    """Planes de pago, priorizando 16 créditos o ilimitado (decisión 2).

    Con ~100 asistencias/día entre 300 alumnos cada uno va ~2 veces por semana: los
    planes de 8 créditos quedan justos y obligarían a recortar la asistencia (los
    créditos se consumen de verdad en A.3). Si el box no tiene planes amplios, se
    cae a todos los de pago y el tope de créditos recorta lo que haga falta.
    """
    pagos = [p for p in planes if int(p["precio_clp"]) > 0]
    if not pagos:
        raise GuardError("no hay planes de pago activos para el tenant")
    amplios = [p for p in pagos if p["es_ilimitado"] or (p["creditos"] or 0) >= 16]
    return amplios or pagos


def cantidad_por_perfil(n: int) -> dict:
    """Reparte `n` alumnos en los 4 perfiles con la proporción configurada."""
    cantidades = {p: int(round(n * PROPORCION[p])) for p in PERFILES}
    cantidades["FIEL"] += n - sum(cantidades.values())   # el redondeo va al mayor
    return cantidades


def alta_aleatoria(desde: date, hasta: date, rng: random.Random) -> date:
    """Fecha de alta ponderada por mes (más altas en marzo/septiembre)."""
    if desde > hasta:
        desde = hasta
    dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
    return rng.choices(dias, weights=[peso_estacional(d) for d in dias], k=1)[0]


def ventanas_suscripcion(alta: date, ultimo: date,
                         saltear_mes: Optional[str] = None) -> list:
    """Ventanas mensuales `[(inicio, expiracion)]` desde el alta hasta `ultimo`.

    Cada ventana es el mes calendario completo (el plan vence el último día del mes,
    igual que en el box real) y el primer mes arranca el día del alta: una
    suscripción no puede empezar antes de que el alumno exista. `saltear_mes` (perfil
    REACTIVADO) omite un mes entero: sin suscripción no hay reservas ese mes, y el
    hueco resultante es el que rompe la separabilidad del label de churn.
    """
    ventanas, cursor = [], primer_dia_mes(alta)
    while cursor <= ultimo:
        if mes_iso(cursor) != saltear_mes:
            ventanas.append((max(cursor, alta), ultimo_dia_mes(cursor)))
        cursor = correr_mes(cursor, 1)
    return ventanas


def _suscripcion_dict(alumno_idx: int, plan: dict, inicio: date, fin: date,
                      hoy: date) -> dict:
    """Suscripción en memoria. Los créditos se llenan después (dependen del consumo)."""
    vigente_hoy = inicio <= hoy <= fin
    return {
        "alumno": alumno_idx,
        "plan_id": plan["id"],
        "plan_nombre": plan["nombre"],
        "mes": mes_iso(inicio),
        "inicio": inicio,
        "expiracion": fin,
        "estado": "activo" if vigente_hoy else "vencido",
        "es_ilimitado": bool(plan["es_ilimitado"]),
        "creditos_totales": None,        # se completa en `_asignar_creditos`
        "creditos_disponibles": None,
        "consumo": 0,
    }


def generar_alumnos(hoy: date, ventana_inicio: date, planes: Sequence[dict],
                    ruts_usados: set, n_alumnos: int = N_ALUMNOS,
                    semilla: int = SEMILLA_RANDOM) -> list:
    """Construye los N alumnos: perfil, alta, plan, cadena de suscripciones y topes.

    El reparto de las altas es lo que convierte la ventana en un año de negocio (y no
    en 300 altas el mismo día):
      * FIEL (55 %): alta en [ventana_inicio, hoy-60]; asiste hasta hoy.
      * REACTIVADO (15 %): se fue un mes entero (sin suscripción ⇒ sin reservas) y
        volvió. El hueco queda >= 46 días ⇒ el label de churn lo vio abandonado y hoy
        no lo está (es el caso que vuelve interesante al modelo).
      * PRUEBA (15 %): alta en los últimos DIAS_PRUEBA_MAX días y pocas clases: es el
        alumno nuevo del mes, el que alimenta "alumnos nuevos" de los KPIs.
      * BAJA (15 %): dejó de asistir hace 46-120 días y su última suscripción venció
        ese mes ⇒ sin suscripción vigente + > 45 días sin asistir = label True.
    """
    rng = random.Random(semilla)
    base = planes_preferidos(planes)
    cantidades = cantidad_por_perfil(n_alumnos)
    perfiles = []
    for perfil in PERFILES:
        perfiles.extend([perfil] * cantidades[perfil])
    # Se mezclan para que `idx`/correo no revelen el perfil (ni el orden de la ventana).
    rng.shuffle(perfiles)

    alumnos = []
    for idx, perfil in enumerate(perfiles, start=1):
        ultima_max = None            # techo de asistencia (sólo BAJA)
        restriccion = None           # (fin_actividad, inicio_reactivacion) del REACTIVADO
        saltear = None               # mes sin suscripción
        plan = dict(rng.choice(base))
        activo, fecha_baja, estado = True, None, "activo"

        if perfil == "FIEL":
            alta = alta_aleatoria(ventana_inicio, hoy - timedelta(days=60), rng)
            ultimo_sub = hoy

        elif perfil == "REACTIVADO":
            gap = correr_mes(hoy, -2 if rng.random() < 0.55 else -3)
            fin_previa = gap - timedelta(days=22)
            inicio_react = correr_mes(gap, 1) + timedelta(days=24)
            alta = max(ventana_inicio, alta_aleatoria(
                ventana_inicio, fin_previa - timedelta(days=20), rng))
            restriccion = (fin_previa, inicio_react)
            saltear = mes_iso(gap)
            ultimo_sub = hoy

        elif perfil == "PRUEBA":
            alta = alta_aleatoria(
                max(ventana_inicio, hoy - timedelta(days=DIAS_PRUEBA_MAX)),
                hoy - timedelta(days=2), rng)
            ultimo_sub = hoy

        else:   # BAJA
            ultima = hoy - timedelta(days=rng.randint(UMBRAL_ABANDONO_DIAS + 1, 120))
            alta = max(ventana_inicio, alta_aleatoria(
                max(ventana_inicio, ultima - timedelta(days=150)),
                ultima - timedelta(days=45), rng))
            ultimo_sub = ultimo_dia_mes(ultima)
            ultima_max = ultima
            fecha_baja = min(ultima + timedelta(days=rng.randint(1, 10)),
                             hoy - timedelta(days=1))
            activo, estado = False, "baja"

        subs = [_suscripcion_dict(idx, plan, ini, fin, hoy)
                for ini, fin in ventanas_suscripcion(alta, ultimo_sub, saltear)]
        vigente = any(s["inicio"] <= hoy <= s["expiracion"] for s in subs)
        if vigente != (perfil != "BAJA"):
            raise InvarianteError(
                f"{PREFIJO_CORREO}{idx} ({perfil}): vigente_hoy={vigente}")

        alumnos.append({
            "idx": idx,
            "perfil": perfil,
            "correo": f"{PREFIJO_CORREO}{idx}{DOMINIO_CORREO}",
            "rut": generar_rut(ruts_usados, rng),
            "nombre": " ".join([rng.choice(NOMBRES), rng.choice(APELLIDOS),
                                rng.choice(APELLIDOS)]),
            "telefono": f"+569{rng.randint(10_000_000, 99_999_999)}",
            "alta": alta,
            "estado": estado,
            "activo": activo,
            "fecha_baja": fecha_baja,
            "plan": plan,
            "entusiasmo": rng.uniform(0.6, 1.4),
            "banda": rng.choice(BANDAS),
            "suscripciones": subs,
            "restriccion": restriccion,
            "ultima_max": ultima_max,
            "peso_kg": round(rng.uniform(55, 95), 1),
            "estatura_cm": rng.randint(150, 195),
        })
    return alumnos


def indexar_grilla(horarios: Sequence[dict]) -> dict:
    """`{dia_semana: [horario, ...]}` sólo con los activos, ordenados por hora."""
    grilla = defaultdict(list)
    for h in horarios:
        if not h.get("activo", True):
            continue
        grilla[int(h["dia_semana"])].append(h)
    for lista in grilla.values():
        lista.sort(key=lambda h: (hora_min(h["hora_inicio"]), h["id"]))
    return dict(grilla)


def construir_clases(hoy: date, inicio: date, fin: date, grilla: dict,
                     clases_reales: Sequence[dict], coaches: dict,
                     requiere_coach: dict) -> list:
    """Todas las clases de `[inicio, fin]`: reusa las reales y crea las del seed.

    * Clase real (misma `fecha` + `horario_base_id`): se reusa TAL CUAL (nunca se
      duplica el slot) y el seed sólo le recalcula el aforo.
    * No existe y el día es `<= hoy`: se crea una clase del seed (marcada con
      MARCA_TS) con los datos del horario real.
    * No existe y el día es futuro: **no se crea**. A.5 del mantenimiento sólo mira
      las clases futuras (`c.fecha >= current_date`); las de los próximos 7 días son
      las que ya generó la app, y si no alcanzan, el dry-run lo avisa.
    * `coach_id`: round-robin entre los coaches activos de la disciplina; NULL cuando
      `requiere_coach` es falso. Sin coach disponible en una disciplina que lo exige
      la clase NO se crea: sería una fila nueva en A.5(a)/(b) (rojo/info).
    """
    reales = {}
    for c in clases_reales:
        if c.get("cancelada"):
            continue
        reales[(c["fecha"], c["horario_base_id"])] = c

    rr = defaultdict(int)          # contador del round-robin por disciplina
    clases = []
    dia = inicio
    while dia <= fin:
        for horario in grilla.get(dia.weekday(), ()):
            clave = (dia, horario["id"])
            real = reales.get(clave)
            if real is not None:
                clases.append({
                    "clave": clave, "fecha": dia, "horario_id": horario["id"],
                    "disciplina_id": real["disciplina_id"],
                    "hora_inicio": real["hora_inicio"], "hora_fin": real["hora_fin"],
                    "cupo_maximo": int(real["cupo_maximo"]),
                    "cupo_original": real.get("cupo_original"),
                    "seed": False, "id_real": real["id"], "coach_id": real.get("coach_id"),
                    "requiere_coach": bool(requiere_coach.get(real["disciplina_id"], True)),
                    "aforo_base": int(real.get("asistentes_confirmados") or 0),
                })
                continue
            if dia > hoy:
                continue           # futuro sin clase real: no se inventa (A.5)
            disc = horario["disciplina_id"]
            disponibles = list(coaches.get(disc, ())) if requiere_coach.get(disc, True) else []
            if requiere_coach.get(disc, True) and not disponibles:
                continue           # A.5(a)/(b): sin coach no se crea la clase
            coach_id = None
            if disponibles:
                coach_id = disponibles[rr[disc] % len(disponibles)]
                rr[disc] += 1
            clases.append({
                "clave": clave, "fecha": dia, "horario_id": horario["id"],
                "disciplina_id": disc,
                "hora_inicio": horario["hora_inicio"], "hora_fin": horario["hora_fin"],
                "cupo_maximo": int(horario["cupo_maximo"]),
                "cupo_original": int(horario["cupo_maximo"]),
                "seed": True, "id_real": None, "coach_id": coach_id,
                "requiere_coach": bool(requiere_coach.get(disc, True)),
                "aforo_base": 0,
            })
        dia += timedelta(days=1)

    for c in clases:
        c["asistentes_confirmados"] = 0     # se completa al asignar reservas
    return clases


# ── Pertenencia a una suscripción y consumo de créditos ─────────────────────
def sub_del_dia(alumno: dict, dia: date) -> Optional[dict]:
    """Suscripción del alumno que cubre `dia` (None si ese día no tenía plan)."""
    for s in alumno["suscripciones"]:
        if s["inicio"] <= dia <= s["expiracion"]:
            return s
    return None


def credito_disponible(alumno: dict, sub: dict, consumo: dict) -> bool:
    """¿Le quedan créditos? Un plan ilimitado (`creditos_*` NULL) nunca topa."""
    total = None if sub["es_ilimitado"] else (alumno["plan"]["creditos"] or 0)
    if not total:
        return True
    return consumo[(alumno["idx"], sub["mes"])] < total


def puede_asistir(alumno: dict, dia: date, consumo: dict) -> bool:
    """Reglas de negocio de "este alumno puede estar en clase ese día".

    Fuera de la ventana del seed, antes del alta, sin suscripción que cubra el día
    (nadie reserva sin plan activo), después de su última asistencia (perfil BAJA),
    dentro del hueco del REACTIVADO o sin créditos ⇒ no se le asigna nada.
    """
    if dia < alumno["alta"]:
        return False
    sub = sub_del_dia(alumno, dia)
    if sub is None:
        return False
    if alumno["ultima_max"] is not None and dia > alumno["ultima_max"]:
        return False
    if alumno["restriccion"] is not None:
        fin_previa, inicio_react = alumno["restriccion"]
        if fin_previa < dia < inicio_react:
            return False
    return credito_disponible(alumno, sub, consumo)


def peso_alumno(alumno: dict, slot: dict) -> float:
    """Peso del alumno para ese slot: perfil × entusiasmo × afinidad de franja."""
    afinidad = 2.5 if franja_de(slot["hora_inicio"]) == alumno["banda"] else 1.0
    return PESO_PERFIL[alumno["perfil"]] * alumno["entusiasmo"] * afinidad


def clase_naive(clase: dict) -> datetime:
    """Inicio de la clase en hora local chilena sin tz (ver `inicio_clase_naive`)."""
    return inicio_clase_naive(clase["fecha"], clase["hora_inicio"])


def reserva_dict(alumno_idx: int, clase: dict, estado: str, asistio: bool,
                 fecha_reserva: datetime, updated_at: datetime,
                 marcada_at: Optional[datetime], temprana: Optional[bool] = None) -> dict:
    """Reserva en memoria, con los valores EXACTOS que escribe la app.

    * `asistencia_marcada_por = NULL` (decisión 7) y `asistencia_via = 'n8n'` cuando
      hay `asistencia_marcada_at`: es una vía real del sistema (el modelo las
      documenta: coach|admin|batch|n8n) y NO es `'cierre'`, que es la que escribe el
      paso 8 del mantenimiento (si el seed la usara, el paso 8 no tendría nada que
      hacer y el dato mentiría sobre quién marcó).
    * `tokens_gastados = 1` siempre: es lo que hace la app (reservas.py) y A.3 lo
      ignora a propósito (documentado en el job).
    * `temprana` no va a la base: es la intención de la cancelación, para que los
      tests verifiquen la clasificación temprana/tardía de A.3 sin adivinar.
    """
    return {
        "alumno": alumno_idx,
        "clase": clase["clave"],
        "estado": estado,
        "asistio": asistio,
        "fecha_reserva": fecha_reserva,
        "updated_at": updated_at,
        "asistencia_marcada_at": marcada_at,
        "asistencia_marcada_por": None,
        "asistencia_via": None if marcada_at is None else ASISTENCIA_VIA,
        "tokens_gastados": 1,
        "temprana": temprana,
    }


def elegir_alumno(alumnos: Sequence[dict], usados: set, slot: dict, dia: date,
                  consumo: dict, rng: random.Random) -> Optional[dict]:
    """Elige UN alumno elegible para ese slot, ponderado y sin reemplazo en el día.

    `usados` son los `idx` que ya tienen una reserva ese día: nadie hace dos clases el
    mismo día (y así tampoco hay dos reservas vivas del mismo alumno en dos clases
    distintas de la misma fecha, que es lo que A.2(b) castiga).
    """
    pool, pesos = [], []
    for a in alumnos:
        if a["idx"] in usados:
            continue
        if not puede_asistir(a, dia, consumo):
            continue
        pool.append(a)
        pesos.append(peso_alumno(a, slot))
    if not pool:
        return None
    objetivo = rng.random() * sum(pesos)
    acumulado = 0.0
    for alumno, peso in zip(pool, pesos):
        acumulado += peso
        if objetivo <= acumulado:
            return alumno
    return pool[-1]


def asignar_reservas(hoy: date, inicio: date, alumnos: list, clases: list,
                     rng: random.Random, asistencias_dia: int,
                     asistencias_sabado: int) -> dict:
    """Reparte la asistencia día por día y devuelve reservas, asistencias y avisos.

    El DÍA manda: se fija un objetivo (≈100 en día hábil ponderado por mes, 16 el
    sábado, 0 el domingo), se reparte entre los slots por franja horaria y se eligen
    alumnos elegibles por peso. Sobre lo asistido se agregan faltazos (~10 %: reserva
    viva sin asistir, que igual consume crédito) y cancelaciones (~6 %, 60 % tempranas
    con devolución y 40 % tardías).
    """
    por_fecha = defaultdict(list)
    for c in clases:
        por_fecha[c["fecha"]].append(c)
    for lista in por_fecha.values():
        lista.sort(key=lambda c: (hora_min(c["hora_inicio"]), c["horario_id"]))

    aforo = defaultdict(int)        # clave -> reservas vivas (lo que espera el paso 9)
    consumo = defaultdict(int)      # (idx, mes) -> reservas que consumen crédito (A.3)
    vivas = set()                   # (idx, clave) de reservas vivas: sin duplicados
    ultima = {}                     # idx -> última asistencia (garantía de recencia)
    reservas, asistencias = [], []
    avisos = Counter()

    def intentar(alumno: dict, clase: dict, asistio: bool,
                 cancelar: Optional[bool] = None,
                 permitir_futuro: bool = False) -> bool:
        """Crea la reserva si TODAS las reglas se cumplen.

        `cancelar`: `None` = reserva viva; `True` = cancelación temprana (con
        devolución, no consume); `False` = tardía (no hubo devolución ⇒ consume).
        `permitir_futuro`: la reserva es de una clase que todavía no ocurre (próximos
        7 días): no hay asistencia que marcar y la reserva se hizo estos días.
        """
        futuro = clase["fecha"] > hoy
        if futuro and not (permitir_futuro and not asistio and cancelar is None):
            return False
        if not puede_asistir(alumno, clase["fecha"], consumo):
            return False
        if (alumno["idx"], clase["clave"]) in vivas:
            return False
        if clase["aforo_base"] + aforo[clase["clave"]] >= clase["cupo_maximo"]:
            avisos["cupo_insuficiente"] += 1
            return False

        sub = sub_del_dia(alumno, clase["fecha"])
        inicio_n = clase_naive(clase)
        if futuro:
            creada = dt_utc(hoy) - timedelta(days=rng.randint(0, 2))
        else:
            anticipacion = rng.randint(1, 6) if cancelar is None else rng.randint(3, 8)
            creada = (inicio_n - timedelta(days=anticipacion)).replace(tzinfo=timezone.utc)
        marcada = (inicio_n + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        if cancelar is None:
            reservas.append(reserva_dict(alumno["idx"], clase, ESTADO_RESERVA_VIVA,
                                         asistio, creada, creada,
                                         None if futuro else marcada))
            vivas.add((alumno["idx"], clase["clave"]))
            aforo[clase["clave"]] += 1
            consumo[(alumno["idx"], sub["mes"])] += 1
            if asistio:
                asistencias.append({"alumno": alumno["idx"], "clase": clase["clave"],
                                    "fecha": clase["fecha"], "created_at": marcada})
                ultima[alumno["idx"]] = max(ultima.get(alumno["idx"], clase["fecha"]),
                                            clase["fecha"])
            return True

        reservas.append(reserva_dict(
            alumno["idx"], clase, ESTADO_RESERVA_CANCELADA, False, creada,
            ts_cancelacion(inicio_n, cancelar), None, temprana=cancelar))
        if not cancelar:            # tardía: el crédito NO volvió ⇒ consume (A.3)
            consumo[(alumno["idx"], sub["mes"])] += 1
        return True

    # ── Fase A+B: el día manda (asistencia + faltazos + cancelaciones) ───────
    dia = inicio
    while dia <= hoy:
        slots = por_fecha.get(dia, [])
        objetivo = objetivo_asistencias(dia, rng, asistencias_dia, asistencias_sabado)
        if not slots:
            if objetivo:
                avisos["dias_sin_slots"] += 1
            dia += timedelta(days=1)
            continue

        usados = set()
        asignados = 0
        for slot, cuantos in zip(slots, repartir_por_slots(objetivo, slots)):
            for _ in range(cuantos):
                alumno = elegir_alumno(alumnos, usados, slot, dia, consumo, rng)
                if alumno is None:
                    break
                if intentar(alumno, slot, True):
                    usados.add(alumno["idx"])
                    asignados += 1

        # Faltazos: reserva viva sin asistir (consume crédito; no hay fila en asistencias).
        for _ in range(int(round(asignados * 0.10))):
            slot = rng.choice(slots)
            alumno = elegir_alumno(alumnos, usados, slot, dia, consumo, rng)
            if alumno is None:
                break
            if intentar(alumno, slot, False):
                usados.add(alumno["idx"])

        # Cancelaciones: 60 % tempranas (el crédito vuelve) y 40 % tardías.
        for _ in range(int(round(asignados * 0.06))):
            slot = rng.choice(slots)
            alumno = elegir_alumno(alumnos, usados, slot, dia, consumo, rng)
            if alumno is None:
                break
            if intentar(alumno, slot, False, cancelar=rng.random() < 0.6):
                usados.add(alumno["idx"])
        dia += timedelta(days=1)

    # ── Fase C: ningún perfil activo queda sin asistir hace más de 40 días ────
    # El reparto por día es probabilístico: un alumno de bajo peso podría quedarse
    # sin asistencia en la ventana reciente y el label de churn lo contaría como
    # abandonado (rompería el invariante del perfil). Se le agrega UNA asistencia en
    # el primer día reciente con lugar, respetando todas las reglas (créditos,
    # restricción del reactivado, cupo).
    for alumno in alumnos:
        if alumno["perfil"] == "BAJA":
            continue
        u = ultima.get(alumno["idx"])
        if u is not None and (hoy - u).days <= DIAS_RECIENTE_MAX:
            continue
        for delta in range(0, DIAS_RECIENTE_MAX + 1):
            dia_rec = hoy - timedelta(days=delta)
            if dia_rec < inicio:
                break
            slots_dia = por_fecha.get(dia_rec, [])
            if not slots_dia:
                continue
            if any(intentar(alumno, slot, True) for slot in
                   rng.sample(slots_dia, k=min(3, len(slots_dia)))):
                break
        if (hoy - ultima.get(alumno["idx"], alumno["alta"])).days > DIAS_RECIENTE_MAX:
            avisos["sin_asistencia_reciente"] += 1

    # ── Fase D: reservas de los próximos días (decisión 5) ───────────────────
    # SÓLO sobre clases REALES (no se crean clases futuras: sería sumarle filas a
    # A.5) y sólo dentro de la ventana de la suscripción vigente, que es la que las
    # cuenta en A.3 ⇒ `disponibles` las incluye y el descuadre sigue siendo 0.
    futuras = [c for c in clases if not c["seed"]
               and hoy < c["fecha"] <= hoy + timedelta(days=DIAS_RESERVA_FUTURA)]
    for alumno in alumnos:
        if alumno["perfil"] == "BAJA" or rng.random() >= 0.55:
            continue
        for _ in range(rng.randint(1, 2)):
            candidatas = [c for c in futuras
                          if sub_del_dia(alumno, c["fecha"]) is not None
                          and aforo[c["clave"]] < c["cupo_maximo"]
                          and (alumno["idx"], c["clave"]) not in vivas]
            if not candidatas:
                avisos["futuras_sin_clase"] += 1
                break
            if not intentar(alumno, rng.choice(candidatas), False,
                            permitir_futuro=True):
                break

    return {"reservas": reservas, "asistencias": asistencias, "avisos": avisos,
            "consumo": consumo, "aforo": aforo, "ultima": ultima,
            "futuras_disponibles": len(futuras)}


# ══════════════════════════════════════════════════════════════════════════
#  4. CRÉDITOS, PAGOS Y ARMADO DEL PLAN
# ══════════════════════════════════════════════════════════════════════════
def asignar_creditos(alumnos: Sequence[dict], consumo: dict) -> None:
    """Fija `creditos_totales` / `creditos_disponibles` de cada suscripción.

    Es el invariante de A.3 escrito al revés: el job reconstruye el consumo como
    `vivas + tardías`, así que acá `disponibles = totales - consumo` con el MISMO
    `consumo` que el generador contó (vivas + cancelaciones tardías de la ventana).
    Los planes ilimitados quedan con las dos columnas en NULL: la app tampoco las
    escribe (`if membresia.creditos_disponibles is not None`) y A.3 los excluye por
    `creditos_totales IS NOT NULL`.
    """
    for alumno in alumnos:
        for sub in alumno["suscripciones"]:
            usado = consumo.get((alumno["idx"], sub["mes"]), 0)
            if sub["es_ilimitado"]:
                sub["consumo"] = usado
                sub["creditos_totales"] = None
                sub["creditos_disponibles"] = None
                continue
            total = alumno["plan"]["creditos"] or 0
            if usado > total:
                raise InvarianteError(
                    f"{PREFIJO_CORREO}{alumno['idx']} {sub['mes']}: consumo={usado} "
                    f"> creditos_totales={total}")
            sub["consumo"] = usado
            sub["creditos_totales"] = total
            sub["creditos_disponibles"] = total - usado


def generar_transacciones(alumnos: Sequence[dict], suscripciones: Sequence[dict],
                          hoy: date, rng: random.Random) -> list:
    """Un ingreso por suscripción (12 meses de serie mensual para el forecast).

    La fecha es el inicio de la ventana (+0..2 días, nunca en el futuro) y el monto el
    precio del plan: mismo patrón que `seed_ml_data_prod` (`ingreso`/`membresia`,
    `referencia_tipo='suscripcion'`) pero con el prefijo `DEMOPRODANUAL`, que es el
    marcador con el que se borran y que además cae dentro de `DEMOPROD%`.
    """
    precios = {a["idx"]: a["plan"] for a in alumnos}
    transacciones = []
    for i, sub in enumerate(suscripciones):
        plan = precios[sub["alumno"]]
        fecha = min(sub["inicio"] + timedelta(days=rng.randint(0, 2)), hoy)
        transacciones.append({
            "sub": i,
            "fecha": fecha,
            "monto": int(plan["precio_clp"]),
            "descripcion": f"{MARCA_DESC} pago plan {sub['plan_nombre']}",
        })
    return transacciones


def construir_plan(hoy: date, *, horarios: Sequence[dict], clases_reales: Sequence[dict],
                   planes: Sequence[dict], coaches: dict, requiere_coach: dict,
                   ruts_usados: Iterable[str] = (), n_alumnos: int = N_ALUMNOS,
                   dias_ventana: int = DIAS_VENTANA, asistencias_dia: int = ASISTENCIAS_DIA_LV,
                   asistencias_sabado: int = ASISTENCIAS_SABADO,
                   dias_futuro: int = DIAS_RESERVA_FUTURA, semilla: int = SEMILLA_RANDOM,
                   validar: bool = True) -> dict:
    """Construye el plan completo en memoria (nada de esto toca la base).

    Toda la aleatoriedad sale de `semilla`: dos corridas con el mismo día y la misma
    semilla dan EXACTAMENTE el mismo plan (por eso el dry-run anticipa la ejecución).
    """
    inicio = hoy - timedelta(days=dias_ventana)
    alumnos = generar_alumnos(hoy, inicio, planes, set(ruts_usados), n_alumnos, semilla)
    grilla = indexar_grilla(horarios)
    clases = construir_clases(hoy, inicio, hoy + timedelta(days=dias_futuro), grilla,
                              clases_reales, coaches, requiere_coach)

    rng = random.Random(semilla + 7)
    asignacion = asignar_reservas(hoy, inicio, alumnos, clases, rng,
                                  asistencias_dia, asistencias_sabado)
    asignar_creditos(alumnos, asignacion["consumo"])

    suscripciones = [s for a in alumnos for s in a["suscripciones"]]
    transacciones = generar_transacciones(alumnos, suscripciones, hoy, rng)

    for clase in clases:
        clase["asistentes_confirmados"] = (clase["aforo_base"]
                                          + asignacion["aforo"].get(clase["clave"], 0))

    plan = {
        "hoy": hoy,
        "inicio": inicio,
        "fin": hoy + timedelta(days=dias_futuro),
        "alumnos": alumnos,
        "suscripciones": suscripciones,
        "clases": clases,
        "reservas": asignacion["reservas"],
        "asistencias": asignacion["asistencias"],
        "transacciones": transacciones,
        "avisos": asignacion["avisos"],
        "futuras_disponibles": asignacion["futuras_disponibles"],
        "opciones": {"dias_ventana": dias_ventana, "asistencias_dia": asistencias_dia,
                     "asistencias_sabado": asistencias_sabado,
                     "semilla": semilla, "dias_futuro": dias_futuro},
    }
    if validar:
        validar_plan(plan)
    return plan


# ══════════════════════════════════════════════════════════════════════════
#  5. VALIDACIÓN DE INVARIANTES  (§2 mantenimiento y §6 créditos)
# ══════════════════════════════════════════════════════════════════════════
def _error(faltas: list, mensaje: str) -> None:
    if len(faltas) < 10:
        faltas.append(mensaje)


def validar_plan(plan: dict) -> dict:
    """Verifica TODOS los invariantes sobre el plan en memoria y devuelve el resumen.

    Es la red que impide escribir datos que el mantenimiento vería como cambios (y el
    blanco de los tests unitarios, que la llaman con planes chicos). Levanta
    `InvarianteError` con los primeros 10 problemas encontrados.
    """
    hoy = plan["hoy"]
    inicio = plan["inicio"]
    alumnos, faltas = plan["alumnos"], []
    clases = {c["clave"]: c for c in plan["clases"]}
    subs = plan["suscripciones"]
    reservas = plan["reservas"]
    sub_por_alumno = defaultdict(list)
    for s in subs:
        sub_por_alumno[s["alumno"]].append(s)

    # ── 1. Usuarios: marcas, estados y el par activo/estado (A.1a/A.1b) ──
    correos, ruts = set(), set()
    for a in alumnos:
        if not a["correo"].startswith(PREFIJO_CORREO) or not a["correo"].endswith(DOMINIO_CORREO):
            _error(faltas, f"correo fuera del marcador: {a['correo']}")
        if a["correo"] in correos:
            _error(faltas, f"correo duplicado: {a['correo']}")
        correos.add(a["correo"])
        if a["rut"] in ruts or not rut_valido(a["rut"]):
            _error(faltas, f"RUT inválido o duplicado: {a['rut']}")
        ruts.add(a["rut"])
        if a["estado"] not in ESTADOS_USUARIO:
            _error(faltas, f"estado de usuario desconocido: {a['estado']}")
        if a["activo"] != (a["estado"] == "activo"):
            _error(faltas, f"A.1(a) {a['correo']}: activo={a['activo']} estado={a['estado']}")
        if a["perfil"] == "BAJA":
            if a["fecha_baja"] is None or a["fecha_baja"] >= hoy:
                _error(faltas, f"BAJA sin fecha_baja pasada: {a['correo']}")
        elif a["fecha_baja"] is not None:
            _error(faltas, f"perfil activo con fecha_baja: {a['correo']}")

    # ── 2. Suscripciones: estados del enum, vigencias y créditos (A.3 / §6) ──
    consumo_real = defaultdict(int)          # (idx, mes) -> vivas + tardías (A.3)
    por_idx = {a["idx"]: a for a in alumnos}
    for r in reservas:
        alumno = por_idx.get(r["alumno"])
        if alumno is None:
            _error(faltas, f"reserva de un alumno inexistente: {r['alumno']}")
            continue
        clase = clases.get(r["clase"])
        if clase is None:
            _error(faltas, f"reserva sin clase: {r['clase']}")
            continue
        duena = None
        for s in sub_por_alumno[r["alumno"]]:
            if s["inicio"] <= clase["fecha"] <= s["expiracion"]:
                duena = s
                break
        if duena is None:
            _error(faltas, f"reserva {r['alumno']} {r['clase']} sin suscripción que la "
                           f"cubra (A.3 la reconstruiría como descuadre)")
            continue
        if r["estado"] == ESTADO_RESERVA_VIVA:
            consumo_real[(r["alumno"], duena["mes"])] += 1
        elif r["estado"] == ESTADO_RESERVA_CANCELADA:
            if r["asistencia_marcada_at"] is not None or r["temprana"] is None:
                _error(faltas, f"cancelada mal formada: {r['alumno']} {r['clase']}")
            elif not r["temprana"]:          # tardía: no hubo devolución ⇒ consume
                consumo_real[(r["alumno"], duena["mes"])] += 1
        else:
            _error(faltas, f"estado de reserva inesperado: {r['estado']}")

    vigentes_por_alumno = defaultdict(int)
    for s in subs:
        if s["estado"] not in ESTADOS_SUSCRIPCION:
            _error(faltas, f"estado de suscripción desconocido: {s['estado']}")
        if s["expiracion"] < s["inicio"]:
            _error(faltas, f"suscripción con expiración anterior al inicio: {s}")
        vigente = s["inicio"] <= hoy <= s["expiracion"]
        if vigente:
            vigentes_por_alumno[s["alumno"]] += 1
        if (s["estado"] == "activo") != vigente:
            _error(faltas, f"estado/créditos: {s['alumno']} {s['mes']} estado={s['estado']} "
                           f"vigente={vigente}")
        usado = consumo_real.get((s["alumno"], s["mes"]), 0)
        if s["es_ilimitado"]:
            if s["creditos_totales"] is not None or s["creditos_disponibles"] is not None:
                _error(faltas, f"ilimitado con créditos: {s['alumno']} {s['mes']}")
        else:
            total, disp = s["creditos_totales"], s["creditos_disponibles"]
            if total is None or disp is None or total - disp != usado or disp < 0:
                _error(faltas, f"A.3 {s['alumno']} {s['mes']}: total={total} disp={disp} "
                               f"consumo_reconstruido={usado}")
    # ── 3. Reservas: duplicados, auditoría de marcado y clases futuras ──
    vivas, asistencias_esperadas = set(), 0
    for r in reservas:
        clave = (r["alumno"], r["clase"])
        clase = clases[r["clase"]]
        inicio_n = clase_naive(clase)
        naive_utc = inicio_n.replace(tzinfo=timezone.utc)
        if r["estado"] == ESTADO_RESERVA_VIVA:
            if clave in vivas:
                _error(faltas, f"A.2(b) reserva viva duplicada: {clave}")
            vivas.add(clave)
        if r["asistio"]:
            asistencias_esperadas += 1
            if r["asistencia_marcada_at"] is None:
                _error(faltas, f"A.4(b) asistió sin marcada_at: {clave}")
        if r["asistencia_marcada_por"] is not None:
            _error(faltas, f"asistencia_marcada_por no es NULL: {clave}")
        if r["asistencia_via"] == "cierre":
            _error(faltas, f"asistencia_via='cierre' (esa vía la escribe el paso 8): {clave}")
        if r["estado"] == ESTADO_RESERVA_CANCELADA:
            if r["temprana"] and r["updated_at"] > naive_utc - timedelta(hours=10):
                _error(faltas, f"cancelación 'temprana' demasiado cerca de la clase: {clave}")
            if not r["temprana"] and r["updated_at"] < naive_utc:
                _error(faltas, f"cancelación 'tardía' fuera de la ventana de 6 h: {clave}")
        if clase["fecha"] > hoy:
            if clase["seed"] or r["asistio"] or r["asistencia_marcada_at"] is not None:
                _error(faltas, f"reserva futura mal armada: {clave}")
        elif r["estado"] == ESTADO_RESERVA_VIVA and \
                clase["fecha"] < hoy - timedelta(days=DIAS_CIERRE_MANTENIMIENTO):
            if r["asistencia_marcada_at"] is None:
                _error(faltas, f"el paso 8 tendría que tocar esta reserva: {clave}")
        if r["fecha_reserva"] > dt_utc(hoy, 23):
            _error(faltas, f"reserva agendada después de hoy: {clave}")

    # ── 4. Clases: aforo = reservas vivas (paso 9) y cupo (A.2c) ──
    vivas_por_clase = Counter(r["clase"] for r in reservas
                              if r["estado"] == ESTADO_RESERVA_VIVA)
    for c in plan["clases"]:
        vivas_clase = vivas_por_clase.get(c["clave"], 0)
        if c["asistentes_confirmados"] != c.get("aforo_base", 0) + vivas_clase:
            _error(faltas, f"paso 9: {c['clave']} aforo={c['asistentes_confirmados']} "
                           f"base={c.get('aforo_base', 0)} vivas={vivas_clase}")
        if c["asistentes_confirmados"] > c["cupo_maximo"]:
            _error(faltas, f"A.2(c) sobrecupo: {c['clave']} ({c['asistentes_confirmados']})")
        if c["seed"] and c["fecha"] > hoy:
            _error(faltas, f"clase del seed en el futuro (A.5): {c['clave']}")
        if c["seed"] and c["requiere_coach"] and c["coach_id"] is None:
            _error(faltas, f"A.5 sin coach en una disciplina que lo exige: {c['clave']}")
        if c["seed"] and not c["requiere_coach"] and c["coach_id"] is not None:
            _error(faltas, f"coach en una disciplina self-service: {c['clave']}")

    # ── 5. Asistencias: una por reserva asistida, dentro de la ventana, sin domingos ──
    asistidas = {(r["alumno"], r["clase"]) for r in reservas if r["asistio"]}
    if len(plan["asistencias"]) != asistencias_esperadas:
        _error(faltas, f"asistencias={len(plan['asistencias'])} esperadas={asistencias_esperadas}")
    asistidas_vistas = set()
    for a in plan["asistencias"]:
        clave = (a["alumno"], a["clase"])
        if clave not in asistidas or clave in asistidas_vistas:
            _error(faltas, f"asistencia sin reserva asistida (o duplicada): {clave}")
        asistidas_vistas.add(clave)
        if a["fecha"].weekday() == 6:
            _error(faltas, f"asistencia en domingo: {clave}")
        if not inicio <= a["fecha"] <= hoy:
            _error(faltas, f"asistencia fuera de la ventana: {clave}")
        if sub_del_dia(por_idx[a["alumno"]], a["fecha"]) is None:
            _error(faltas, f"asistencia sin suscripción que la cubra: {clave}")

    # ── 6. Label de churn (§2.1: label ⇔ perfil BAJA) ──
    ultimas = {}
    for a in plan["asistencias"]:
        ultimas[a["alumno"]] = max(ultimas.get(a["alumno"], a["fecha"]), a["fecha"])
    for alumno in alumnos:
        ult = ultimas.get(alumno["idx"])
        dias = (hoy - ult).days if ult else (hoy - alumno["alta"]).days
        vigente = vigentes_por_alumno.get(alumno["idx"], 0) == 1
        label = (not vigente) and dias > UMBRAL_ABANDONO_DIAS
        if label != (alumno["perfil"] == "BAJA"):
            _error(faltas, f"label {alumno['correo']} ({alumno['perfil']}): dias={dias} "
                           f"vigente={vigente}")
        if alumno["perfil"] != "BAJA":
            if ult is None or dias > DIAS_RECIENTE_MAX:
                _error(faltas, f"{alumno['perfil']} sin asistencia reciente: {alumno['correo']} "
                               f"({dias} días)")
        else:
            if ult is not None and ult > alumno["ultima_max"]:
                _error(faltas, f"BAJA con asistencia posterior a su baja: {alumno['correo']}")
            if vigentes_por_alumno.get(alumno["idx"], 0) != 0:
                _error(faltas, f"BAJA con suscripción vigente: {alumno['correo']}")
        if alumno["perfil"] != "BAJA" and not vigente:
            _error(faltas, f"{alumno['perfil']} sin suscripción vigente: {alumno['correo']}")

    # ── 7. Reparto del día: sin domingos y sin pasarse del cupo del sábado ──
    por_fecha = Counter(a["fecha"] for a in plan["asistencias"])
    sabado = plan["opciones"]["asistencias_sabado"]
    for fecha, cuantos in por_fecha.items():
        if fecha.weekday() == 6:
            _error(faltas, f"asistencia un domingo: {fecha}")
        if fecha.weekday() == 5 and cuantos > sabado:
            _error(faltas, f"sábado {fecha} con {cuantos} asistencias (cupo {sabado})")

    if faltas:
        raise InvarianteError("invariantes incumplidos:\n  - " + "\n  - ".join(faltas))

    return {
        "alumnos": len(alumnos),
        "por_perfil": dict(Counter(a["perfil"] for a in alumnos)),
        "suscripciones": len(subs),
        "suscripciones_activas": sum(1 for s in subs if s["estado"] == "activo"),
        "clases": len(plan["clases"]),
        "clases_seed": sum(1 for c in plan["clases"] if c["seed"]),
        "clases_reales_tocadas": sum(1 for c in plan["clases"]
                                     if not c["seed"] and c["asistentes_confirmados"]),
        "reservas": len(reservas),
        "reservas_vivas": sum(1 for r in reservas if r["estado"] == ESTADO_RESERVA_VIVA),
        "faltazos": sum(1 for r in reservas if r["estado"] == ESTADO_RESERVA_VIVA
                        and not r["asistio"]),
        "cancelaciones": dict(Counter("temprana" if r["temprana"] else "tardia"
                                      for r in reservas
                                      if r["estado"] == ESTADO_RESERVA_CANCELADA)),
        "asistencias": len(plan["asistencias"]),
        "transacciones": len(plan["transacciones"]),
        "ingresos_mes": sum(t["monto"] for t in plan["transacciones"]
                            if (t["fecha"].year, t["fecha"].month) == (hoy.year, hoy.month)),
        "avisos": dict(plan["avisos"]),
    }


# ══════════════════════════════════════════════════════════════════════════
#  6. DRY-RUN  (no escribe nada; es el mismo plan que se va a insertar)
# ══════════════════════════════════════════════════════════════════════════
def estimar_filas(plan: dict) -> dict:
    """Filas por tabla y total (lo que se va a INSERTAR)."""
    filas = {
        "usuarios": len(plan["alumnos"]),
        "suscripciones": len(plan["suscripciones"]),
        "transacciones_financieras": len(plan["transacciones"]),
        "clases": sum(1 for c in plan["clases"] if c["seed"]),
        "reservas": len(plan["reservas"]),
        "asistencias": len(plan["asistencias"]),
    }
    filas["TOTAL"] = sum(filas.values())
    return filas


def imprimir_dry_run(plan: dict, resumen: dict, destino: str) -> None:
    """Reporte del plan + los avisos que importan antes de escribir."""
    filas = estimar_filas(plan)
    hoy, inicio = plan["hoy"], plan["inicio"]
    print(f"[dry-run] destino={destino.upper()} | hoy={hoy} | ventana={inicio}..{plan['fin']}"
          f" | semilla={plan['opciones']['semilla']}")
    print("\n[dry-run] registros a crear:")
    for tabla, n in filas.items():
        print(f"      {tabla:<26}: {n:>8}")
    print(f"      {'(≈MB con índices)':<26}: {filas['TOTAL'] * 230 / 1024 / 1024:>8.1f}")
    print("      clases reales SOLO aforo   :"
          f" {resumen['clases_reales_tocadas']:>8}  (update, no insert)")

    print("\n[dry-run] alumnos por perfil:")
    for perfil in PERFILES:
        n = resumen["por_perfil"].get(perfil, 0)
        print(f"      {perfil:<12}: {n:>4}  ({n / max(1, resumen['alumnos']) * 100:.0f}%)")

    print("\n[dry-run] reservas:")
    print(f"      vivas {resumen['reservas_vivas']} (faltazos {resumen['faltazos']}) · "
          f"cancelaciones {resumen['cancelaciones'].get('temprana', 0)} tempranas / "
          f"{resumen['cancelaciones'].get('tardia', 0)} tardías")
    print(f"      suscripciones activas (vigentes hoy): {resumen['suscripciones_activas']}")
    print(f"      ingresos del mes en curso: ${resumen['ingresos_mes']:,}")

    asis = [a["fecha"] for a in plan["asistencias"]]
    if asis:
        por_dia = Counter(asis)
        habiles = [n for f, n in por_dia.items() if f.weekday() < 5]
        sabados = [n for f, n in por_dia.items() if f.weekday() == 5]
        print(f"\n[dry-run] asistencias por día: {len(asis)} en {len(por_dia)} días")
        print(f"      día hábil: media {sum(habiles) / max(1, len(habiles)):.0f} "
              f"(min {min(habiles, default=0)} / max {max(habiles, default=0)})")
        print(f"      sábados  : {len(sabados)} días, media "
              f"{sum(sabados) / max(1, len(sabados)):.0f} (cupo {ASISTENCIAS_SABADO})")
        print(f"      domingos : {sum(1 for f in por_dia if f.weekday() == 6)} (esperado 0)")
        cupo = sum(c["cupo_maximo"] for c in plan["clases"] if c["fecha"] <= hoy)
        print(f"      ocupación: {len(asis)} asistentes / {cupo} lugares = "
              f"{len(asis) / max(1, cupo) * 100:.1f}%  (Σ asist. / Σ cupo de la ventana)")
        por_mes = Counter(mes_iso(f) for f in asis)
        print("      por mes  : " + " ".join(f"{m}:{n}" for m, n in sorted(por_mes.items())))
    altas = Counter(mes_iso(a["alta"]) for a in plan["alumnos"])
    print("      altas/mes: " + " ".join(f"{m}:{n}" for m, n in sorted(altas.items())))

    print("\n[dry-run] label de churn (abandonado ⇔ sin plan vigente y > 45 días): "
          f"{len(plan['alumnos'])}/{len(plan['alumnos'])} consistente")
    print("[dry-run] créditos A.3 (totales - disponibles == vivas + tardías): "
          f"{len(plan['suscripciones'])}/{len(plan['suscripciones'])} cuadran")

    if plan["avisos"]:
        print("\n[dry-run] avisos:")
        for clave, n in sorted(plan["avisos"].items()):
            print(f"      {clave}: {n}")
    if not resumen["clases_reales_tocadas"]:
        print("\n[aviso] no hay clases futuras en los próximos "
              f"{plan['opciones']['dias_futuro']} días: la fase de reservas futuras queda "
              "vacía (¿el generador de clases está al día?)")

    print("\n[dry-run] muestra de correos (identifican y permiten borrar el seed):")
    for alumno in plan["alumnos"][:2] + plan["alumnos"][-1:]:
        print(f"      {alumno['correo']}   [{alumno['perfil']}]")
    print("\n[aviso] A.1(c) del mantenimiento (demo declarada) va a subir en "
          f"{len(plan['alumnos'])}: es informativo y no cambia el exit code.")
    print("[aviso] limpiar el seed ANTES del día 1 del mes siguiente "
          "(el paso 1 vencería sus suscripciones): scripts\\borrar_seed_anual.py")


# ══════════════════════════════════════════════════════════════════════════
#  7. GUARDS, LECTURA Y ESCRITURA  (acá sí se toca la base)
# ══════════════════════════════════════════════════════════════════════════
def validar_url_destino(url: str, destino: str, prod_id: str,
                        test_ids: Sequence[str]) -> Optional[str]:
    """Motivo del rechazo de la URL, o `None` si corresponde al destino.

    Es PURA (recibe los ids): los tests la ejercitan sin leer `.env` ni tocar la base.
    * prod: la URL tiene que ser EXACTAMENTE el endpoint de PROD.
    * test: tiene que ser un endpoint de TEST conocido y NUNCA el de PROD (denylist
      primero, para que un copy/paste cruzado no habilite escribir en producción).
    * `withered-silence` (PROD viejo, retirado el 2026-09-24) se rechaza en los DOS
      destinos con su propio mensaje.
    """
    u = url or ""
    if not u:
        return "DATABASE_URL vacía"
    if HOST_PROD_VIEJO in u:
        return (f"la URL apunta a {HOST_PROD_VIEJO}, que era el PROD viejo (endpoint "
                f"retirado el 2026-09-24): corregí el .env antes de correr el seed")
    if destino == "prod":
        if prod_id not in u:
            return f"destino=prod pero la URL no es el endpoint de PROD ({prod_id})"
        if any(t in u for t in test_ids):
            return "destino=prod pero la URL contiene un endpoint de TEST"
        return None
    if prod_id in u:
        return "destino=test pero la URL es la de PROD (prohibido)"
    if not any(t in u for t in test_ids):
        return "destino=test pero la URL no es un endpoint de TEST conocido"
    return None


def validar_ventana(hoy: date, destino: str = "prod") -> Optional[str]:
    """Motivo del rechazo si hoy no es un día ejecutable (guard 3), o `None`.

    La ventana existe para proteger al **mantenimiento de PROD**, que escribe los días 1 y 15
    (vencidos, huérfanas, cierre de asistencia y aforo) y corta por `MAX_VENCIDOS_PCT`. Por eso
    se evalúa **sólo con `destino="prod"`**: en TEST no corre ningún cron de mantenimiento, así
    que sembrar cualquier día no puede romper nada.

    El default es `"prod"` a propósito: si una llamada se olvida el destino, queda del lado
    ESTRICTO (el que no puede lastimar producción).
    """
    if destino != "prod":
        return None
    if hoy.day in DIAS_MANTENIMIENTO:
        return (f"hoy es día {hoy.day}: el mantenimiento escribe ese día (vencidos, "
                f"huérfanas, cierre de asistencia y aforo). Corré entre el 2 y el 14, o "
                f"entre el 16 y el 28.")
    if mes_iso(hoy) == MES_PROHIBIDO:
        return (f"{MES_PROHIBIDO} está bloqueado: el run del 1/10 marcaría vencidas todas "
                f"las suscripciones de septiembre y cortaría por MAX_VENCIDOS_PCT.")
    return None


def host_de(url: str) -> str:
    """Host de la URL (para el log: nunca se imprime la credencial)."""
    try:
        from urllib.parse import urlsplit
        return urlsplit(url).hostname or "?"
    except Exception:
        return "?"


def preparar_entorno(destino: str) -> dict:
    """Guards 1-2: fija `ENVIRONMENT`, importa la app y valida la URL del destino.

    El import de `app.core.config` va DESPUÉS de fijar `ENVIRONMENT` (ese módulo elige
    `.env` o `.env.test` al importarse). Todo lo demás se importa acá adentro para que
    el módulo sea importable por los tests sin leer configuración ni tocar la base.
    """
    os.environ["ENVIRONMENT"] = "production" if destino == "prod" else "test"
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    os.chdir(backend_dir)

    config = importlib.import_module("app.core.config")
    prod_id = getattr(config, "PROD_BRANCH_ID", "")
    test_ids = tuple(getattr(config, "TEST_BRANCH_IDS", ()))
    if HOST_PROD not in prod_id:
        raise GuardError(
            f"PROD_BRANCH_ID cambió ({prod_id!r}): el script está escrito para "
            f"{HOST_PROD}. Revisá la topología de Neon y actualizá los guards "
            f"(config.py + este script) antes de escribir.")
    motivo = validar_url_destino(config.settings.DATABASE_URL, destino, prod_id, test_ids)
    if motivo:
        raise GuardError(f"{motivo} (host actual: {host_de(config.settings.DATABASE_URL)})")

    print(f"[guard] ENVIRONMENT={os.environ['ENVIRONMENT']} | destino={destino} | "
          f"host={host_de(config.settings.DATABASE_URL)} | PROD_BRANCH_ID={prod_id}")

    return {
        "config": config,
        "SessionLocal": importlib.import_module("app.db.database").SessionLocal,
        "Usuario": importlib.import_module("app.models.usuario").Usuario,
        "RolUsuario": importlib.import_module("app.models.usuario").RolUsuario,
        "Asistencia": importlib.import_module("app.models.asistencia").Asistencia,
        "Reserva": importlib.import_module("app.models.reserva").Reserva,
        "Clase": importlib.import_module("app.models.clase").Clase,
        "HorarioBase": importlib.import_module("app.models.horario_base").HorarioBase,
        "Disciplina": importlib.import_module("app.models.disciplina").Disciplina,
        "CoachDisciplina": importlib.import_module("app.models.coach_disciplina").CoachDisciplina,
        "Plan": importlib.import_module("app.models.plan").Plan,
        "Suscripcion": importlib.import_module("app.models.suscripcion").Suscripcion,
        "EstadoSuscripcion": importlib.import_module(
            "app.models.suscripcion").EstadoSuscripcion,
        "TransaccionFinanciera": importlib.import_module(
            "app.models.transaccion_financiera").TransaccionFinanciera,
        "hash_password": importlib.import_module("app.api.v1.usuarios").hash_password,
    }


def leer_entradas(db, env: dict, hoy: date, dias_futuro: int) -> dict:
    """SELECT de todo lo que el generador necesita (la grilla real y las clases, etc.).

    El seed NUNCA toca `horarios`, `disciplinas`, `planes` ni `coach_disciplinas`: son
    la realidad del box. Si falta lo mínimo (sin horarios activos, sin coaches en una
    disciplina que los exige, sin planes de pago) se aborta antes de calcular nada.
    """
    HorarioBase, Clase, Disciplina = env["HorarioBase"], env["Clase"], env["Disciplina"]
    CoachDisciplina, Usuario, Plan = env["CoachDisciplina"], env["Usuario"], env["Plan"]
    inicio = hoy - timedelta(days=DIAS_VENTANA)
    fin = hoy + timedelta(days=dias_futuro)

    horarios = [{"id": h.id, "disciplina_id": h.disciplina_id, "dia_semana": h.dia_semana,
                 "hora_inicio": h.hora_inicio, "hora_fin": h.hora_fin,
                 "cupo_maximo": h.cupo_maximo, "activo": h.activo}
                for h in db.query(HorarioBase).filter(
                    HorarioBase.tenant_id == TENANT_ID, HorarioBase.activo == True).all()]  # noqa: E712
    if not horarios:
        raise GuardError("no hay horarios activos: el seed no puede inventar la grilla")

    disc = {d.id: {"nombre": d.nombre, "requiere_coach": bool(d.requiere_coach)}
            for d in db.query(Disciplina).filter(Disciplina.tenant_id == TENANT_ID).all()}
    clases_reales = [{"id": c.id, "fecha": c.fecha, "horario_base_id": c.horario_base_id,
                      "disciplina_id": c.disciplina_id, "hora_inicio": c.hora_inicio,
                      "hora_fin": c.hora_fin, "cupo_maximo": c.cupo_maximo,
                      "cancelada": bool(c.cancelada),
                      "asistentes_confirmados": int(c.asistentes_confirmados or 0)}
                     for c in db.query(Clase).filter(
                         Clase.tenant_id == TENANT_ID, Clase.fecha >= inicio,
                         Clase.fecha <= fin).all()]

    coaches = defaultdict(list)
    for cd in db.query(CoachDisciplina).join(
            Usuario, Usuario.id == CoachDisciplina.coach_id).filter(
            CoachDisciplina.tenant_id == TENANT_ID, CoachDisciplina.activo == True,  # noqa: E712
            Usuario.rol == env["RolUsuario"].coach, Usuario.activo == True).order_by(  # noqa: E712
            CoachDisciplina.disciplina_id, CoachDisciplina.coach_id).all():
        coaches[cd.disciplina_id].append(cd.coach_id)

    planes = [{"id": p.id, "nombre": p.nombre, "creditos": p.creditos,
               "es_ilimitado": bool(p.es_ilimitado), "precio_clp": int(p.precio_clp)}
              for p in db.query(Plan).filter(
                  Plan.tenant_id == TENANT_ID, Plan.activo == True,  # noqa: E712
                  Plan.precio_clp > 0).order_by(Plan.id).all()]
    if not planes:
        raise GuardError("no hay planes de pago activos para el tenant")

    return {
        "horarios": horarios, "clases_reales": clases_reales,
        "planes": planes,
        "coaches": dict(coaches),
        "requiere_coach": {i: v["requiere_coach"] for i, v in disc.items()},
        "disciplinas": disc,
        "ruts_usados": ruts_en_uso(db, Usuario),
    }


def ruts_en_uso(db, Usuario) -> set:
    """Números de RUT ya usados (cuerpo, sin DV) para no generar duplicados.

    `verificar_integridad.py` (y la integridad del mantenimiento) marcan RUT repetidos
    como hallazgo: el generador tiene que esquivar los que ya existen.
    """
    usados = set()
    for (rut,) in db.query(Usuario.rut).all():
        cuerpo = (rut or "").split("-")[0].strip()
        if cuerpo.isdigit():
            usados.add(int(cuerpo))
    return usados


def contar_existentes(db, env: dict, tenant_id: int = TENANT_ID) -> dict:
    """Cuántas filas del seed hay ya (para decidir si hay que reciclar antes)."""
    Usuario, Clase = env["Usuario"], env["Clase"]
    Transaccion = env["TransaccionFinanciera"]
    return {
        "usuarios": db.query(Usuario).filter(
            Usuario.correo.like(f"{PREFIJO_CORREO}%{DOMINIO_CORREO}")).count(),
        "clases": db.query(Clase).filter(
            Clase.tenant_id == tenant_id, Clase.created_at == MARCA_TS).count(),
        "transacciones": db.query(Transaccion).filter(
            Transaccion.descripcion.like(f"{MARCA_DESC}%")).count(),
    }


def limpiar_previos(db, env: dict) -> dict:
    """Borra lo que ya exista del seed EN LA MISMA TRANSACCIÓN (idempotencia).

    Reutiliza `borrar_seed_anual.borrar_en_transaccion` para que "volver a sembrar" y
    "borrar y sembrar" sean EXACTAMENTE el mismo borrado (incluido el recálculo del
    aforo de las clases reales que hayan quedado con reservas nuestras).
    """
    ruta = os.path.dirname(os.path.abspath(__file__))
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
    borrar = importlib.import_module("borrar_seed_anual")
    return borrar.borrar_en_transaccion(db, env, tenant_id=TENANT_ID)


def escribir_plan(db, plan: dict, env: dict, hash_pwd: str) -> dict:
    """Inserta el plan completo. NO hace commit: lo hace `main`.

    Así el borrado previo (si había datos del seed) y la inserción son UNA sola
    transacción: si algo falla, el rollback deja la base exactamente como estaba.

    Orden por FKs: usuarios → suscripciones → transacciones → clases → reservas →
    asistencias, y al final el aforo de las clases REALES (las del seed ya nacen con el
    suyo). Las ids se recuperan con `RETURNING` por lote de 5 000 filas: el driver no se
    queda sin memoria y no hay 30 000 round-trips.
    """
    from sqlalchemy import insert, text
    Usuario, Clase = env["Usuario"], env["Clase"]
    Reserva, Asistencia = env["Reserva"], env["Asistencia"]
    Suscripcion, Transaccion = env["Suscripcion"], env["TransaccionFinanciera"]
    RolUsuario, EstadoSuscripcion = env["RolUsuario"], env["EstadoSuscripcion"]
    lote = 5000

    def por_lotes(filas):
        for i in range(0, len(filas), lote):
            yield filas[i:i + lote]

    def insertar(modelo, filas, con_id: bool):
        ids = []
        for trozo in por_lotes(filas):
            if not trozo:
                continue
            if con_id:
                ids.extend(db.execute(insert(modelo).returning(modelo.id),
                                      trozo).scalars().all())
            else:
                db.execute(insert(modelo), trozo)
        return ids

    # 1) usuarios (el hash se calcula UNA vez y se reusa: 300 hashes sería absurdo)
    ids_usuarios = insertar(Usuario, [{
        "tenant_id": TENANT_ID, "rut": a["rut"], "nombre": a["nombre"],
        "telefono": a["telefono"], "correo": a["correo"], "password_hash": hash_pwd,
        "rol": RolUsuario.alumno, "activo": a["activo"], "estado": a["estado"],
        "created_at": dt_utc(a["alta"]),
        "fecha_baja": dt_utc(a["fecha_baja"]) if a["fecha_baja"] else None,
        "peso_kg": a["peso_kg"], "estatura_cm": a["estatura_cm"],
        "cambiar_password_al_login": False, "acepta_correo_reactivacion": True,
    } for a in plan["alumnos"]], con_id=True)
    id_por_idx = {a["idx"]: uid for a, uid in zip(plan["alumnos"], ids_usuarios)}

    # 2) suscripciones. `estado` va como MIEMBRO del enum (no como str): la columna es
    #    el enum nativo `estado_suscripcion` y así el bind va tipado correctamente.
    estados = {"activo": EstadoSuscripcion.activo, "vencido": EstadoSuscripcion.vencido}
    ids_subs = insertar(Suscripcion, [{
        "tenant_id": TENANT_ID, "usuario_id": id_por_idx[s["alumno"]],
        "plan_id": s["plan_id"], "estado": estados[s["estado"]],
        "creditos_totales": s["creditos_totales"],
        "creditos_disponibles": s["creditos_disponibles"],
        "fecha_inicio": dt_utc(s["inicio"]), "fecha_expiracion": dt_utc(s["expiracion"]),
        "es_compra_emergencia": False, "puede_comprar_emergencia": True,
    } for s in plan["suscripciones"]], con_id=True)

    # 3) transacciones (sin FK a usuarios: se marcan por `descripcion` + referencia_id)
    insertar(Transaccion, [{
        "tenant_id": TENANT_ID, "tipo": "ingreso", "categoria": "membresia",
        "monto": t["monto"], "descripcion": t["descripcion"],
        "referencia_tipo": "suscripcion", "referencia_id": ids_subs[t["sub"]],
        "fecha": t["fecha"], "created_at": dt_utc(t["fecha"]),
    } for t in plan["transacciones"]], con_id=False)

    # 4) clases del seed (marcadas con MARCA_TS) y mapa clave -> id (reales + seed)
    nuevas = [c for c in plan["clases"] if c["seed"]]
    ids_clases = insertar(Clase, [{
        "tenant_id": TENANT_ID, "horario_base_id": c["horario_id"],
        "coach_id": c["coach_id"], "disciplina_id": c["disciplina_id"],
        "fecha": c["fecha"], "hora_inicio": c["hora_inicio"], "hora_fin": c["hora_fin"],
        "cupo_maximo": c["cupo_maximo"], "cupo_original": c["cupo_original"],
        "asistentes_confirmados": 0, "cancelada": False, "wod_id": None,
        "created_at": MARCA_TS, "updated_at": MARCA_TS,
    } for c in nuevas], con_id=True)
    id_de_clase = {c["clave"]: c["id_real"] for c in plan["clases"] if not c["seed"]}
    id_de_clase.update({c["clave"]: cid for c, cid in zip(nuevas, ids_clases)})

    # 5) reservas: `estado` es un varchar con default 'reserved' ⇒ se escribe explícito
    insertar(Reserva, [{
        "tenant_id": TENANT_ID, "clase_id": id_de_clase[r["clase"]],
        "alumno_id": id_por_idx[r["alumno"]], "fecha_reserva": r["fecha_reserva"],
        "asistio": r["asistio"], "tokens_gastados": r["tokens_gastados"],
        "estado": r["estado"], "asistencia_marcada_por": None,
        "asistencia_marcada_at": r["asistencia_marcada_at"],
        "asistencia_via": r["asistencia_via"],
        "created_at": r["fecha_reserva"], "updated_at": r["updated_at"],
    } for r in plan["reservas"]], con_id=False)

    # 6) asistencias (`clase='WOD'` es lo que ya hay en PROD; `clase_id` se agrega)
    insertar(Asistencia, [{
        "tenant_id": TENANT_ID, "usuario_id": id_por_idx[a["alumno"]],
        "fecha": a["fecha"], "clase": "WOD", "clase_id": id_de_clase[a["clase"]],
        "presente": True, "created_at": a["created_at"],
    } for a in plan["asistencias"]], con_id=False)

    # 7) aforo de las clases REALES tocadas: base + nuestras reservas vivas (así el paso
    #    9 no tiene nada que corregir y el borrado puede volver a `base`).
    reales = [(c["id_real"], c["asistentes_confirmados"]) for c in plan["clases"]
              if not c["seed"] and c["aforo_base"] != c["asistentes_confirmados"]]
    if reales:
        db.execute(text("UPDATE clases SET asistentes_confirmados = :n, "
                        "updated_at = now() WHERE id = :i"),
                   [{"i": i, "n": n} for i, n in reales])

    return {"usuarios": len(ids_usuarios), "suscripciones": len(ids_subs),
            "clases_seed": len(ids_clases), "reservas": len(plan["reservas"]),
            "asistencias": len(plan["asistencias"]),
            "transacciones": len(plan["transacciones"]),
            "clases_reales_actualizadas": len(reales)}


SQL_PASO_9 = (
    "SELECT count(*) FROM clases c WHERE c.asistentes_confirmados <> "
    "(SELECT count(*) FROM reservas r WHERE r.clase_id = c.id "
    " AND r.estado NOT IN ('cancelled', 'cancelada'))"
)
SQL_PASO_8 = (
    "SELECT count(*) FROM reservas r WHERE r.estado NOT IN ('cancelled', 'cancelada') "
    "AND r.asistencia_marcada_at IS NULL AND EXISTS (SELECT 1 FROM clases c "
    " WHERE c.id = r.clase_id AND (c.fecha + c.hora_fin) AT TIME ZONE 'America/Santiago' "
    " < now() - interval '7 days')"
)
# Misma fórmula que A.3 (mantenimiento_cloud.sql_descuadre_creditos), acotada a los
# alumnos del seed: es la verificación EXACTA del invariante de créditos contra Postgres.
SQL_A3 = (
    "SELECT count(*) FROM suscripciones s WHERE s.usuario_id = ANY(:ids) "
    "AND s.estado = 'activo' AND s.creditos_totales IS NOT NULL "
    "AND s.fecha_inicio::date <= current_date AND s.fecha_expiracion::date >= current_date "
    "AND s.creditos_totales - s.creditos_disponibles <> "
    "  (SELECT count(*) FROM reservas r JOIN clases c ON c.id = r.clase_id "
    "    WHERE r.alumno_id = s.usuario_id "
    "      AND r.estado NOT IN ('cancelled', 'cancelada') "
    "      AND c.fecha BETWEEN s.fecha_inicio::date AND s.fecha_expiracion::date) "
    "+ (SELECT count(*) FROM reservas r JOIN clases c ON c.id = r.clase_id "
    "    WHERE r.alumno_id = s.usuario_id "
    "      AND r.estado IN ('cancelled', 'cancelada') "
    "      AND c.fecha BETWEEN s.fecha_inicio::date AND s.fecha_expiracion::date "
    "      AND r.updated_at > ((c.fecha + c.hora_inicio) AT TIME ZONE 'America/Santiago' "
    "                          - interval '6 hours'))"
)


def verificar_post(db, env: dict) -> bool:
    """Verificación posterior con el SQL del propio mantenimiento (paso 8, paso 9, A.3).

    Es la parte que no se conforma con el modelo en memoria: corre las MISMAS
    condiciones que `mantenimiento_cloud` sobre lo que quedó en la base, acotadas a las
    filas del seed. Si algo de acá falla, el `main` avisa y el resultado es revisar.
    """
    from sqlalchemy import text
    Usuario, Clase = env["Usuario"], env["Clase"]
    ids = [r[0] for r in db.query(Usuario.id).filter(
        Usuario.correo.like(f"{PREFIJO_CORREO}%{DOMINIO_CORREO}")).all()]
    paso9 = db.execute(text(SQL_PASO_9)).scalar()
    paso8 = db.execute(text(SQL_PASO_8)).scalar()
    a3 = db.execute(text(SQL_A3), {"ids": ids}).scalar() if ids else 0
    n_clases = db.query(Clase).filter(Clase.created_at == MARCA_TS).count()
    print("\n[verificación] con el SQL del mantenimiento:")
    print(f"      alumnos del seed            : {len(ids)}")
    print(f"      clases del seed (MARCA_TS)  : {n_clases}")
    print(f"      paso 9 (aforo desincronizado): {paso9}  (esperado 0)")
    print(f"      paso 8 (reservas sin marcar) : {paso8}  (esperado 0)")
    print(f"      A.3 (créditos descuadrados)  : {a3}  (esperado 0)")
    return paso9 == 0 and paso8 == 0 and a3 == 0


# ══════════════════════════════════════════════════════════════════════════
#  8. MAIN
# ══════════════════════════════════════════════════════════════════════════
def parsear_args(argv=None):
    """`--destino` es OBLIGATORIO: no hay default, para que nadie corra "por defecto"."""
    parser = argparse.ArgumentParser(
        description="Seed anual de datos sintéticos para ML (300 alumnos / 12 meses).",
        epilog="Ejecución prevista en PROD: 2 a 5 de octubre de 2026 (nunca día 1 ni 15; "
               "esa ventana no aplica en TEST).")
    parser.add_argument("--destino", choices=("prod", "test"), required=True,
                        help="prod = base real; test = rama de TEST (jamás PROD).")
    parser.add_argument("--dry-run", action="store_true",
                        help="calcula y muestra todo, sin escribir ni borrar nada.")
    parser.add_argument("--alumnos", type=int, default=N_ALUMNOS,
                        help=f"cantidad de alumnos (default {N_ALUMNOS}).")
    parser.add_argument("--semilla", type=int, default=SEMILLA_RANDOM,
                        help=f"semilla del generador (default {SEMILLA_RANDOM}).")
    return parser.parse_args(argv)


def pedir(texto_exacto: str, prompt: str) -> bool:
    """Confirmación por teclado con frase exacta (guard 4)."""
    try:
        respuesta = input(prompt).strip()
    except EOFError:
        print("[abort] sin entrada interactiva (EOF). No se tocó nada.")
        return False
    if respuesta != texto_exacto:
        print(f"[abort] confirmación inválida ('{respuesta}'). No se tocó nada.")
        return False
    return True


def main(argv=None) -> int:
    args = parsear_args(argv)
    hoy = date.today()
    print("=" * 74)
    print("  SEED ANUAL (300 alumnos / 12 meses) - datos sintéticos para ML")
    print("=" * 74)
    print(f"destino={args.destino.upper()} | hoy={hoy} | alumnos={args.alumnos} | "
          f"semilla={args.semilla}" + ("  [DRY-RUN]" if args.dry_run else ""))

    # GUARD 3 (ventana): SÓLO con destino=prod (el mantenimiento escribe el 1 y el 15 y, en
    # septiembre, el run del 1/10 vencería todas las suscripciones del mes). En TEST no hay
    # ningún cron de mantenimiento: se puede sembrar cualquier día.
    motivo = validar_ventana(hoy, args.destino)
    if motivo:
        print(f"[guard] ABORTADO: {motivo}")
        return 1
    if args.destino == "test":
        print("[guard] ventana de ejecución: no aplica en TEST (no hay mantenimiento "
              "programado); en PROD se exige día != 1 != 15 y mes != 2026-09.")

    # GUARD 4 (confirmación): antes del dry-run y de cualquier escritura o borrado.
    base = "PRODUCCIÓN" if args.destino == "prod" else "TEST"
    frase = "SI QUIERO PROD" if args.destino == "prod" else "SI QUIERO TEST"
    print(f"\n⚠️  Esto va a escribir en la base de datos de {base}.")
    if not pedir(frase, f"Escribí '{frase}' para continuar: "):
        return 1
    print(f"[ok] confirmado: se opera contra {args.destino.upper()}.\n")

    # GUARDS 1-2 (ENVIRONMENT + URL): recién acá se importa la app.
    try:
        env = preparar_entorno(args.destino)
    except GuardError as e:
        print(f"[guard] ABORTADO: {e}")
        return 1

    db = env["SessionLocal"]()
    try:
        existentes = {k: v for k, v in contar_existentes(db, env).items() if v}
        if existentes:
            print(f"[aviso] ya hay datos del seed: {existentes}")
            if not args.dry_run:
                print("[aviso] se borran y se vuelven a generar en la MISMA transacción "
                      "(idempotencia por marcadores: si algo falla, el rollback los deja).")
                if not pedir("RECICLAR", "Escribí 'RECICLAR' para confirmar el recambio: "):
                    return 1

        entradas = leer_entradas(db, env, hoy, DIAS_RESERVA_FUTURA)
        print(f"[entradas] horarios={len(entradas['horarios'])} · "
              f"clases reales={len(entradas['clases_reales'])} · "
              f"planes de pago={len(entradas['planes'])} · "
              f"coaches/disciplina={ {d: len(c) for d, c in entradas['coaches'].items()} }")

        plan = construir_plan(hoy, horarios=entradas["horarios"],
                              clases_reales=entradas["clases_reales"],
                              planes=entradas["planes"], coaches=entradas["coaches"],
                              requiere_coach=entradas["requiere_coach"],
                              ruts_usados=entradas["ruts_usados"], validar=False,
                              n_alumnos=args.alumnos, semilla=args.semilla)
        print(f"[plan] en memoria: {len(plan['alumnos'])} alumnos · "
              f"{len(plan['suscripciones'])} suscripciones · {len(plan['clases'])} clases · "
              f"{len(plan['reservas'])} reservas · {len(plan['asistencias'])} asistencias")
        resumen = validar_plan(plan)
        print("[invariantes] OK (§2 + §6: label, aforo, paso 8, paso 9, cupos, "
              "cancelaciones y créditos)")

        imprimir_dry_run(plan, resumen, args.destino)
        if args.dry_run:
            print("\n[dry-run] no se escribió nada. Para ejecutar de verdad: quitá --dry-run.")
            return 0

        if not pedir("GENERAR", "\nEscribí 'GENERAR' para confirmar: "):
            return 1
        print("\n[seed] hasheando la password sintética...")
        hash_pwd = env["hash_password"](PASSWORD_SINTETICA)
        if existentes:
            print("[seed] reciclando: borrando el seed anterior en la misma transacción...")
            print(f"      {limpiar_previos(db, env)}")
        conteos = escribir_plan(db, plan, env, hash_pwd)
        db.commit()
        print(f"[seed] COMMIT OK -> {conteos}")
        ok = verificar_post(db, env)
    except InvarianteError as e:
        db.rollback()
        print(f"[seed] INVARIANTES INCUMPLIDOS -> ROLLBACK (no se escribió nada):\n{e}")
        return 1
    except Exception as e:      # noqa: BLE001  (se reporta y se revierte todo)
        db.rollback()
        print(f"[seed] ERROR -> ROLLBACK (no se escribió nada): {type(e).__name__}: {e}")
        return 1
    finally:
        db.close()

    print("\n" + "=" * 74)
    print(f"  Password de los alumnos del seed: {PASSWORD_SINTETICA}")
    print("  Reversión (borra SOLO lo del seed):")
    print(f"    python3.12 scripts\\borrar_seed_anual.py --destino {args.destino}")
    print("  Reversión manual (si hiciera falta):")
    print(f"    DELETE FROM usuarios WHERE correo LIKE '{PREFIJO_CORREO}%{DOMINIO_CORREO}';")
    print(f"    DELETE FROM transacciones_financieras WHERE descripcion LIKE '{MARCA_DESC}%';")
    print(f"    DELETE FROM clases WHERE created_at = '{MARCA_TS.isoformat()}';")
    print("  Recordá: limpiar ANTES del día 1 del mes siguiente (1/11: el paso 1 vencería "
          "las suscripciones del seed) y reentrenar los modelos de ML.")
    print("  RESULTADO:", "OK - datos consistentes" if ok else "REVISAR - hay discrepancias")
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

