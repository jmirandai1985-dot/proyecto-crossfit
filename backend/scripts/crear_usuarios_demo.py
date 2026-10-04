"""
Usuarios de DEMO (presentación) — 3 cuentas reales en el box (`TENANT_ID = 1`).

Crea (o ACTUALIZA, si ya existen) exactamente 3 usuarios:

  demo.admin@urbanbox.cl    rol 'administrador'
  demo.coach@urbanbox.cl    rol 'coach'  -> queda asignado a TODAS las disciplinas
                                           activas que tengan horarios activos
  demo.alumno@urbanbox.cl   rol 'alumno' -> `estado = 'activo'` **y** `activo = true`
                                           (el CHECK `ck_usuarios_activo_estado` los exige
                                           juntos: con uno solo, el login falla), con
                                           suscripción VIGENTE a un plan REAL (con
                                           créditos) y reservas + asistencias de las
                                           últimas semanas para que su panel no se vea
                                           vacío.

CONTRASEÑA: una sola para los 3, se pide con `getpass` (no vive en el código ni en el
repo) y se hashea con `app.core.security.get_password_hash` (bcrypt), el mismo hasher que
usa el login. El script NO envía ningún correo: no importa ni llama a `email_service`.

"Modo prueba" (`es_usuario_prueba`): NO es una columna de `usuarios`. Es la función
`app.core.dependencies.es_usuario_prueba`, que devuelve True sólo si el usuario tiene una
suscripción ACTIVA al plan llamado exactamente "Prueba". Como el alumno queda suscrito a
un plan REAL (este script EXCLUYE el plan "Prueba" a propósito), esa función da False y
el panel del alumno no queda con el acceso limitado.

IDEMPOTENTE: upsert por `uq_correo_por_tenant (tenant_id, correo)`. A un usuario que ya
existe NO se le toca el RUT (evita chocar con `uq_rut_por_tenant`). Los datos del alumno
demo (suscripción, reservas, asistencias) se recalculan desde cero: el script es el único
dueño de esas 3 direcciones de correo.

INVARIANTES DEL MANTENIMIENTO que el script respeta y VERIFICA al final:
  * paso 9 / A.2(a): `clases.asistentes_confirmados` == reservas VIVAS de la clase
    -> cada reserva creada incrementa el aforo y `--borrar` lo decrementa.
  * paso 8: ninguna reserva viva en una clase terminada hace >7 días sin
    `asistencia_marcada_at` -> las reservas nacen con la auditoría de marcado completa.
  * A.3: créditos descuadrados == 0 -> `creditos_disponibles = creditos_totales - N`
    y TODAS las clases reservadas caen dentro de la ventana de la suscripción.

GUARDS (mismos que `seed_anual_prod.py`):
  1. `--destino prod|test` es OBLIGATORIO (no hay default).
  2. La URL tiene que ser EXACTAMENTE la del destino: PROD = `PROD_BRANCH_ID`
     (y aborta si el endpoint de PROD ya no es `nameless-sound`); TEST = un endpoint de
     `TEST_BRANCH_IDS` y NUNCA el de PROD (denylist primero).
  3. Ventana de ejecución: en PROD aborta el día 1 y el 15 (el mantenimiento ya escribe
     esos días). `--forzar-ventana` lo salta a propósito.
  4. Confirmación por teclado con la frase exacta `SI QUIERO PROD` / `SI QUIERO TEST`.
  5. `--dry-run`: muestra todo sin escribir nada y sin pedir la contraseña.

Uso (desde `backend/`):
    # TEST (rama ep-summer-river-b6c8fj2f)
    $env:ENVIRONMENT="test";       py -3.12 scripts\\crear_usuarios_demo.py --destino test --dry-run
    $env:ENVIRONMENT="test";       py -3.12 scripts\\crear_usuarios_demo.py --destino test
    $env:ENVIRONMENT="test";       py -3.12 scripts\\crear_usuarios_demo.py --destino test --borrar

    # PROD (rama principal) -> lo corre el dueño del box, a mano
    $env:ENVIRONMENT="production"; py -3.12 scripts\\crear_usuarios_demo.py --destino prod --dry-run
    $env:ENVIRONMENT="production"; py -3.12 scripts\\crear_usuarios_demo.py --destino prod
    $env:ENVIRONMENT="production"; py -3.12 scripts\\crear_usuarios_demo.py --destino prod --borrar

LIMITACIÓN A PROPÓSITO: no se crean filas en `transacciones_financieras` (el pago del
plan) para no tocar los ingresos/KPIs de PROD: la suscripción del alumno demo es vigente
pero NO suma al MRR.
"""
from __future__ import annotations

import argparse
import getpass
import importlib
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import text

# Consola de Windows: al pipear la salida los acentos romperían con cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

# ════════════════════════════════════════════════════════════════════════════
#  1. CONFIGURACIÓN  (editar SOLO acá)
# ════════════════════════════════════════════════════════════════════════════
TENANT_ID = 1

CORREO_ADMIN = "demo.admin@urbanbox.cl"
CORREO_COACH = "demo.coach@urbanbox.cl"
CORREO_ALUMNO = "demo.alumno@urbanbox.cl"
CORREOS_DEMO = (CORREO_ADMIN, CORREO_COACH, CORREO_ALUMNO)

NOMBRES = {
    CORREO_ADMIN: "Admin Demo",
    CORREO_COACH: "Coach Demo",
    CORREO_ALUMNO: "Alumno Demo",
}
ROLES = {
    CORREO_ADMIN: "administrador",
    CORREO_COACH: "coach",
    CORREO_ALUMNO: "alumno",
}
# RUT de relleno (prefijo 90xxxxxx reservado para datos de prueba). Sin puntos, como los
# del box. Si está ocupado, `rut_libre()` busca otro.
RUTS_PREFERIDOS = {
    CORREO_ADMIN: "90000001-1",
    CORREO_COACH: "90000002-2",
    CORREO_ALUMNO: "90000003-3",
}

RESERVAS_DEFAULT = 6          # reservas/asistencias del alumno demo
DIAS_VENTANA_DEFAULT = 21     # ventana hacia atrás donde se eligen las clases
DIAS_ALTA_DEFAULT = 15        # antigüedad con la que "nace" el alumno
DIAS_VENCIMIENTO_MINIMO = 5   # la suscripción vence, como mínimo, a N días vista

ESTADO_RESERVA_VIVA = "confirmada"        # lo que escribe la app al reservar
# Las clases "vivas" del job son `estado NOT IN ('cancelled', 'cancelada')`: la app
# escribe 'cancelled' y la base vieja 'cancelada'. Ese filtro va en cada SQL de acá abajo.
ASISTENCIA_VIA = "coach"                  # auditoría: quién marcó la asistencia
PLAN_EXCLUIDO = "Prueba"                  # reservado para el flujo de alumno nuevo
LABEL_ASISTENCIA = "WOD"                  # `asistencias.clase` (así está el histórico)

DIAS_MANTENIMIENTO = (1, 15)              # el job escribe esos días
HOST_PROD = "nameless-sound"              # ep-nameless-sound-b6km6wyi
HOST_PROD_VIEJO = "withered-silence"      # PROD ANTES del 2026-09-24 (retirado)


class GuardError(RuntimeError):
    """Un guard no pasó (destino/URL/ventana): el script aborta sin tocar la base."""


# ════════════════════════════════════════════════════════════════════════════
#  2. GUARDS Y HELPERS PUROS  (sin base y sin app: se pueden testear tal cual)
# ════════════════════════════════════════════════════════════════════════════
def validar_url_destino(url: str, destino: str, prod_id: str,
                        test_ids: Sequence[str]) -> Optional[str]:
    """Motivo del rechazo de la URL, o `None` si corresponde al destino.

    Misma regla que `seed_anual_prod.py`:
      * prod: tiene que ser EXACTAMENTE el endpoint de PROD y no contener un id de TEST.
      * test: denylist primero (PROD nunca es TEST) y después allowlist de TEST.
    """
    u = url or ""
    if not u:
        return "DATABASE_URL vacía"
    if HOST_PROD_VIEJO in u:
        return (f"la URL apunta a {HOST_PROD_VIEJO}, que era el PROD viejo (endpoint "
                f"retirado el 2026-09-24): corrige el .env antes de correr")
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


def host_de(url: str) -> str:
    """Host de la URL (para el log: nunca se imprime la credencial)."""
    try:
        from urllib.parse import urlsplit
        return urlsplit(url).hostname or "?"
    except Exception:  # noqa: BLE001
        return "?"


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


def pedir_password() -> str:
    """Pide la contraseña dos veces por teclado (nunca se imprime ni queda en disco)."""
    while True:
        try:
            p1 = getpass.getpass("Contraseña para los 3 usuarios demo: ")
            p2 = getpass.getpass("Repite la contraseña: ")
        except EOFError as e:
            raise GuardError("sin entrada interactiva para la contraseña (EOF)") from e
        if p1 != p2:
            print("  [x] no coinciden, otra vez.")
            continue
        if len(p1) < 8:
            print("  [x] mínimo 8 caracteres.")
            continue
        if not any(c.isalpha() for c in p1) or not any(c.isdigit() for c in p1):
            print("  [x] usa al menos una letra y un número.")
            continue
        return p1


def parsear_args(argv=None):
    """`--destino` es OBLIGATORIO: no hay default, para que nadie corra 'por defecto'."""
    parser = argparse.ArgumentParser(
        description="Crea/actualiza los 3 usuarios de DEMO (admin, coach, alumno) del box.",
        epilog="Probar SIEMPRE primero con --destino test --dry-run.")
    parser.add_argument("--destino", choices=("prod", "test"), required=True,
                        help="prod = base real; test = rama de TEST (jamás PROD).")
    parser.add_argument("--dry-run", action="store_true",
                        help="muestra el plan completo sin escribir nada.")
    parser.add_argument("--borrar", action="store_true",
                        help="elimina SOLO estos 3 usuarios y sus datos.")
    parser.add_argument("--forzar-ventana", action="store_true",
                        help="permite correr en PROD el día 1 o 15 (mantenimiento).")
    parser.add_argument("--plan", default=None,
                        help=f"nombre exacto del plan del alumno (default: automático, "
                             f"excluyendo '{PLAN_EXCLUIDO}').")
    parser.add_argument("--reservas", type=int, default=RESERVAS_DEFAULT,
                        help=f"reservas/asistencias a crear (default {RESERVAS_DEFAULT}).")
    parser.add_argument("--dias", type=int, default=DIAS_VENTANA_DEFAULT,
                        help=f"ventana hacia atrás para elegir las clases "
                             f"(default {DIAS_VENTANA_DEFAULT}).")
    return parser.parse_args(argv)


def preparar_entorno(destino: str) -> dict:
    """Guards 1-2: fija `ENVIRONMENT`, importa la app y valida la URL del destino.

    El import de `app.core.config` va DESPUÉS de fijar `ENVIRONMENT` (ese módulo elige
    `.env` o `.env.test` al importarse). Todo lo demás se importa acá adentro para que el
    módulo sea importable por los tests sin leer configuración ni tocar la base.
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
            f"{HOST_PROD}. Revisa la topología de Neon y actualiza los guards "
            f"(config.py + este script) antes de escribir.")
    motivo = validar_url_destino(config.settings.DATABASE_URL, destino, prod_id, test_ids)
    if motivo:
        raise GuardError(f"{motivo} (host actual: {host_de(config.settings.DATABASE_URL)})")

    print(f"[guard] ENVIRONMENT={os.environ['ENVIRONMENT']} | destino={destino} | "
          f"host={host_de(config.settings.DATABASE_URL)} | PROD_BRANCH_ID={prod_id}")
    print(f"[guard] EMAIL_MODO={config.settings.EMAIL_MODO!r} "
          f"(este script NO envía correos)")

    return {
        "config": config,
        "SessionLocal": importlib.import_module("app.db.database").SessionLocal,
        "get_password_hash": importlib.import_module("app.core.security").get_password_hash,
    }


# ════════════════════════════════════════════════════════════════════════════
#  3. LECTURA (solo SELECT): plan, disciplinas del coach y clases del alumno
# ════════════════════════════════════════════════════════════════════════════
def ids_usuarios_demo(db) -> dict:
    """`{correo: id}` de los usuarios demo que YA existen (vacío si no hay ninguno)."""
    filas = db.execute(text(
        "SELECT id, correo FROM usuarios WHERE tenant_id = :t AND correo = ANY(:c)"),
        {"t": TENANT_ID, "c": list(CORREOS_DEMO)}).fetchall()
    return {correo: uid for uid, correo in filas}


def elegir_plan(db, nombre: Optional[str]) -> dict:
    """Plan REAL del box para el alumno demo (NUNCA el plan 'Prueba').

    * `--plan NOMBRE`: ese plan exacto (tiene que existir, estar activo y tener créditos).
    * sin `--plan`: el primer plan de pago con créditos finitos, no-estudiante y
      comercial. Excluir 'Prueba' (y que sea comercial) es lo que deja
      `es_usuario_prueba(...) = False`: el alumno no queda con acceso limitado.
    """
    if nombre:
        fila = db.execute(text(
            "SELECT id, nombre, creditos, es_ilimitado, duracion_dias FROM planes "
            "WHERE tenant_id = :t AND activo AND lower(nombre) = lower(:n)"),
            {"t": TENANT_ID, "n": nombre}).first()
        if not fila:
            raise GuardError(f"no existe un plan activo llamado {nombre!r} en el box")
        if fila.es_ilimitado or not fila.creditos:
            raise GuardError(f"el plan {fila.nombre!r} no sirve para la demo: hace falta "
                             f"un plan con créditos finitos (creditos={fila.creditos}, "
                             f"ilimitado={fila.es_ilimitado})")
        return {"id": fila.id, "nombre": fila.nombre, "creditos": int(fila.creditos),
                "duracion_dias": int(fila.duracion_dias or 30)}

    fila = db.execute(text(
        "SELECT id, nombre, creditos, duracion_dias FROM planes "
        "WHERE tenant_id = :t AND activo AND es_comercial AND NOT es_ilimitado "
        "  AND NOT es_estudiante AND creditos > 0 AND nombre <> :exc "
        "ORDER BY id LIMIT 1"),
        {"t": TENANT_ID, "exc": PLAN_EXCLUIDO}).first()
    if not fila:
        raise GuardError("no hay ningún plan de pago con créditos en el box: pasa "
                         "--plan NOMBRE o revisa el catálogo de planes")
    print(f"[plan] elegido automáticamente: [{fila.id}] {fila.nombre} "
          f"({fila.creditos} créditos)")
    return {"id": fila.id, "nombre": fila.nombre, "creditos": int(fila.creditos),
            "duracion_dias": int(fila.duracion_dias or 30)}


def disciplinas_con_horarios(db) -> list:
    """Disciplinas ACTIVAS que tienen horarios ACTIVOS (lo que se le asigna al coach)."""
    return db.execute(text(
        "SELECT d.id, d.nombre, count(h.id) AS n_horarios "
        "FROM disciplinas d JOIN horarios h ON h.disciplina_id = d.id AND h.activo "
        "WHERE d.tenant_id = :t AND d.activo "
        "GROUP BY d.id, d.nombre ORDER BY d.id"), {"t": TENANT_ID}).fetchall()


def elegir_clases(db, n: int, dias: int) -> list:
    """Clases PASADAS (una por día, repartidas en los últimos `dias`) para el alumno.

    Se reserva en clases REALES que ya existen (no se crean clases): así `--borrar` no
    tiene que deshacer ninguna clase y el histórico del box queda como estaba.
    """
    hoy = date.today()
    desde = hoy - timedelta(days=dias)
    filas = db.execute(text(
        "SELECT c.id, c.fecha, c.hora_inicio, c.cupo_maximo, c.asistentes_confirmados, "
        "       d.nombre AS disciplina "
        "FROM clases c LEFT JOIN disciplinas d ON d.id = c.disciplina_id "
        "WHERE c.tenant_id = :t AND NOT c.cancelada "
        "  AND c.fecha >= :desde AND c.fecha < :hoy "
        "ORDER BY c.fecha, c.hora_inicio, c.id"),
        {"t": TENANT_ID, "desde": desde, "hoy": hoy}).fetchall()
    if not filas:
        raise GuardError(f"no hay clases entre {desde} y {hoy}: no se puede armar el "
                         f"panel del alumno (prueba con --dias más grande)")
    if n < 1:
        raise GuardError("--reservas tiene que ser >= 1")

    por_fecha = {}
    for f in filas:
        por_fecha.setdefault(f.fecha, f)        # primera clase del día (orden asc)
    fechas = sorted(por_fecha)
    n = min(n, len(fechas))
    if n == 1:
        elegidas = [fechas[-1]]
    else:
        # Reparto parejo (extremos incluidos): las reservas quedan "de las últimas
        # semanas", no todas amontonadas en los últimos días.
        idx = sorted({round(i * (len(fechas) - 1) / (n - 1)) for i in range(n)})
        elegidas = [fechas[i] for i in idx]

    # Sólo clases con CUPO (igual que el flujo real de reserva). Si una está llena se
    # completa con la fecha vecina más cercana.
    set_elegidas = set(elegidas)
    candidatas = list(elegidas) + [f for f in reversed(fechas) if f not in set_elegidas]
    clases, usadas = [], set()
    for fecha in candidatas:
        if len(clases) >= n:
            break
        if fecha in usadas:
            continue
        f = por_fecha[fecha]
        if int(f.asistentes_confirmados or 0) >= int(f.cupo_maximo or 0):
            continue
        usadas.add(fecha)
        clases.append({"id": f.id, "fecha": f.fecha, "hora_inicio": f.hora_inicio,
                       "disciplina": f.disciplina, "cupo_maximo": f.cupo_maximo,
                       "asistentes_confirmados": f.asistentes_confirmados})
    if not clases:
        raise GuardError("todas las clases de la ventana están llenas")
    if len(clases) < n:
        print(f"[aviso] sólo {len(clases)} clases con cupo en la ventana (pediste {n})")
    return sorted(clases, key=lambda c: (c["fecha"], c["hora_inicio"]))


def ventana_suscripcion(hoy: date, dias: int, duracion_dias: int) -> tuple:
    """`(fecha_inicio, fecha_expiracion)` (UTC mediodía) de la suscripción demo.

    Cumple dos cosas a la vez:
      * TODAS las clases reservadas (ventana de los últimos `max(dias, DIAS_ALTA)`) caen
        DENTRO de la suscripción -> el paso A.3 del mantenimiento no ve reservas fuera
        de la ventana y el descuadre de créditos da 0.
      * La suscripción sigue VIGENTE (vence a >= `DIAS_VENCIMIENTO_MINIMO` días vista).
    Se ancla a las 12:00 UTC (misma disciplina que el seed): así `fecha_inicio::date` y
    `fecha_expiracion::date` dan el MISMO día en UTC y en America/Santiago (un 00:00 UTC
    se correría un día).
    """
    antiguedad = max(dias, DIAS_ALTA_DEFAULT) + 1
    inicio = hoy - timedelta(days=antiguedad)
    expira = inicio + timedelta(days=max(duracion_dias, 1))
    minimo = hoy + timedelta(days=DIAS_VENCIMIENTO_MINIMO)
    if expira < minimo:
        expira = minimo
    return (datetime(inicio.year, inicio.month, inicio.day, 12, 0, tzinfo=timezone.utc),
            datetime(expira.year, expira.month, expira.day, 12, 0, tzinfo=timezone.utc))


def leer_entradas(db, args) -> dict:
    """Resuelve TODO (plan, disciplinas, clases, ventana) antes de escribir una fila."""
    plan = elegir_plan(db, args.plan)
    n = max(1, int(args.reservas))
    if n > plan["creditos"]:
        print(f"[ajuste] el plan {plan['nombre']} tiene {plan['creditos']} créditos: se "
              f"crean {plan['creditos']} reservas (no {n}) para no dejar saldo negativo.")
        n = plan["creditos"]
    disciplinas = disciplinas_con_horarios(db)
    if not disciplinas:
        raise GuardError("el box no tiene disciplinas activas con horarios activos")
    dias = max(1, int(args.dias))
    clases = elegir_clases(db, n, dias)
    inicio, expira = ventana_suscripcion(date.today(), dias, plan["duracion_dias"])
    return {"plan": plan, "n_reservas": n, "disciplinas": disciplinas, "clases": clases,
            "existentes": ids_usuarios_demo(db), "inicio": inicio, "expira": expira}


def imprimir_plan(entradas: dict, args) -> None:
    """Resumen de lo que se hará (lo que ve el `--dry-run`)."""
    plan = entradas["plan"]
    existentes = entradas["existentes"]
    print("\n" + "=" * 74)
    print("  PLAN DE LA OPERACIÓN" + ("   [DRY-RUN: no se escribe nada]" if args.dry_run
                                      else ""))
    print("=" * 74)
    print(f"Box                  : tenant_id={TENANT_ID}")
    print(f"Usuarios demo previos: {existentes or 'ninguno'} "
          f"(se ACTUALIZAN, nunca se duplican)")
    print(f"Admin                : {CORREO_ADMIN}")
    print(f"Coach                : {CORREO_COACH} -> "
          f"{len(entradas['disciplinas'])} disciplinas activas con horarios:")
    for d in entradas["disciplinas"]:
        print(f"    - [{d.id}] {d.nombre} ({d.n_horarios} horarios activos)")
    print(f"Alumno               : {CORREO_ALUMNO}")
    print(f"  plan               : [{plan['id']}] {plan['nombre']} — "
          f"{plan['creditos']} créditos / {plan['duracion_dias']} días")
    print(f"  suscripción        : {entradas['inicio'].date()} -> "
          f"{entradas['expira'].date()} (vigente, créditos "
          f"{plan['creditos'] - len(entradas['clases'])}/{plan['creditos']} disponibles)")
    print(f"  reservas/asistencias: {len(entradas['clases'])} clases REALES ya existentes "
          f"(últimos {args.dias} días):")
    for c in entradas["clases"]:
        print(f"    - clase {c['id']} | {c['fecha']} {c['hora_inicio']} | "
              f"{c['disciplina']} | cupo {c['asistentes_confirmados']}/{c['cupo_maximo']}")
    print(f"Contraseña           : se pide por teclado (getpass), una sola para los 3")


# ════════════════════════════════════════════════════════════════════════════
#  4. ESCRITURA (una sola transacción: si algo falla, rollback y no queda nada)
# ════════════════════════════════════════════════════════════════════════════
def rut_libre(db, preferido: str) -> str:
    """`preferido` si está libre en el box; si no, busca uno del patrón 90xxxxxx-d."""
    if not db.execute(text("SELECT 1 FROM usuarios WHERE tenant_id = :t AND rut = :r"),
                      {"t": TENANT_ID, "r": preferido}).first():
        return preferido
    for i in range(1, 10000):
        cand = f"90{i:06d}-{i % 10}"
        if not db.execute(text("SELECT 1 FROM usuarios WHERE tenant_id = :t AND rut = :r"),
                          {"t": TENANT_ID, "r": cand}).first():
            print(f"  [i] RUT {preferido} ocupado -> se usa {cand}")
            return cand
    raise GuardError("no se encontró un RUT libre en el box")


def upsert_usuario(db, correo: str, password_hash: str) -> int:
    """Crea o actualiza el usuario demo (devuelve su id). NO le toca el RUT si ya existe.

    `activo = true` y `estado = 'activo'` van SIEMPRE juntos: el CHECK
    `ck_usuarios_activo_estado` los mantiene sincronizados y el login lee `estado`
    (con 'pendiente_activacion'/'rechazado'/'baja' el login devuelve 403).
    `cambiar_password_al_login = false` para que la demo no pida cambio de clave y
    `acepta_correo_reactivacion = false` para que ningún correo automático de
    reactivación pueda llegarle a una cuenta de presentación.
    """
    fila = db.execute(text("SELECT id FROM usuarios WHERE tenant_id = :t AND correo = :c"),
                      {"t": TENANT_ID, "c": correo}).first()
    if fila:
        db.execute(text(
            "UPDATE usuarios SET nombre = :n, rol = :rol, password_hash = :p, "
            "  activo = true, estado = 'activo', cambiar_password_al_login = false, "
            "  acepta_correo_reactivacion = false, fecha_baja = NULL "
            "WHERE id = :id AND tenant_id = :t"),
            {"n": NOMBRES[correo], "rol": ROLES[correo], "p": password_hash,
             "id": fila.id, "t": TENANT_ID})
        print(f"  [ACTUALIZADO] id={fila.id:>4} | {ROLES[correo]:<14} | {correo}")
        return fila.id
    rut = rut_libre(db, RUTS_PREFERIDOS[correo])
    nueva = db.execute(text(
        "INSERT INTO usuarios (tenant_id, rut, nombre, telefono, correo, password_hash, "
        "  rol, activo, estado, acepta_correo_reactivacion, cambiar_password_al_login) "
        "VALUES (:t, :rut, :n, NULL, :c, :p, :rol, true, 'activo', false, false) "
        "RETURNING id"),
        {"t": TENANT_ID, "rut": rut, "n": NOMBRES[correo], "c": correo, "p": password_hash,
         "rol": ROLES[correo]}).first()
    print(f"  [CREADO]      id={nueva.id:>4} | {ROLES[correo]:<14} | {correo} | rut={rut}")
    return nueva.id


def asignar_coach(db, coach_id: int, disciplinas: list) -> int:
    """Deja al coach con EXACTAMENTE las disciplinas activas que tienen horarios.

    `coach_disciplinas` no tiene UNIQUE (tenant, coach, disciplina): se borran las filas
    del coach y se insertan de nuevo, y así el resultado es idempotente y sin duplicados.
    """
    ids = [d.id for d in disciplinas]
    borradas = db.execute(text("DELETE FROM coach_disciplinas WHERE coach_id = :id"),
                          {"id": coach_id}).rowcount
    if ids:
        db.execute(
            text("INSERT INTO coach_disciplinas (tenant_id, coach_id, disciplina_id, activo) "
                 "VALUES (:t, :coach, :disc, true)"),
            [{"t": TENANT_ID, "coach": coach_id, "disc": d} for d in ids])
    print(f"  [COACH]       {len(ids)} disciplinas asignadas (se reemplazaron "
          f"{borradas} filas previas)")
    return len(ids)


def upsert_suscripcion(db, alumno_id: int, plan: dict, creditos_disponibles: int,
                       inicio, expira) -> int:
    """Deja UNA sola suscripción del alumno demo: vigente, de un plan real y con créditos.

    Si ya existía, la actualiza (y borra cualquier otra del alumno, para no duplicar).
    `aprobado_por = NULL` a propósito: en el esquema real esa FK es NO ACTION, y apuntarla
    al admin demo impediría después borrar ese admin.
    """
    previas = db.execute(text("SELECT id FROM suscripciones WHERE usuario_id = :a "
                              "AND tenant_id = :t ORDER BY id"),
                         {"a": alumno_id, "t": TENANT_ID}).fetchall()
    valores = {"a": alumno_id, "t": TENANT_ID, "p": plan["id"],
               "ct": plan["creditos"], "cd": creditos_disponibles,
               "fi": inicio, "fe": expira}
    if previas:
        sid = previas[0].id
        if len(previas) > 1:
            sobrantes = [r.id for r in previas[1:]]
            db.execute(text("DELETE FROM suscripciones WHERE id = ANY(:ids)"),
                       {"ids": sobrantes})
            print(f"  [i] se borraron {len(sobrantes)} suscripciones duplicadas del alumno")
        db.execute(text(
            "UPDATE suscripciones SET plan_id = :p, estado = 'activo', "
            "  creditos_totales = :ct, creditos_disponibles = :cd, fecha_inicio = :fi, "
            "  fecha_expiracion = :fe, aprobado_por = NULL, es_compra_emergencia = false, "
            "  updated_at = now() WHERE id = :sid"), {**valores, "sid": sid})
        print(f"  [ACTUALIZADA] suscripción id={sid} | plan {plan['nombre']} | "
              f"créditos {creditos_disponibles}/{plan['creditos']} | "
              f"vence {expira.date()}")
        return sid
    nueva = db.execute(text(
        "INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado, "
        "  creditos_totales, creditos_disponibles, fecha_inicio, fecha_expiracion, "
        "  aprobado_por, es_compra_emergencia, puede_comprar_emergencia) "
        "VALUES (:t, :a, :p, 'activo', :ct, :cd, :fi, :fe, NULL, false, true) "
        "RETURNING id"), valores).first()
    print(f"  [CREADA]      suscripción id={nueva.id} | plan {plan['nombre']} | "
          f"créditos {creditos_disponibles}/{plan['creditos']} | vence {expira.date()}")
    return nueva.id


# SQL compartido por `limpiar_datos_previos()` y `borrar()`: devuelve el aforo de las
# clases que había reservado el alumno (es lo que mira el paso 9 del mantenimiento).
SQL_BAJAR_AFORO = (
    "UPDATE clases c SET asistentes_confirmados = "
    "  GREATEST(c.asistentes_confirmados - x.k, 0), updated_at = now() "
    "FROM (SELECT clase_id, count(*) AS k FROM reservas WHERE alumno_id = :a "
    "      AND estado NOT IN ('cancelled', 'cancelada') GROUP BY clase_id) x "
    "WHERE c.id = x.clase_id")


def limpiar_datos_previos(db, alumno_id: int) -> dict:
    """Deja al alumno demo SIN reservas ni asistencias y devuelve el aforo que había subido.

    Idempotencia: el alumno demo es 100% del script, así que sus reservas y asistencias se
    recalculan desde cero en cada corrida (si no, la segunda corrida duplicaría reservas y
    descuadraría los créditos de A.3). El aforo se corrige para que el paso 9 siga dando 0.
    """
    aforo = db.execute(text(SQL_BAJAR_AFORO), {"a": alumno_id}).rowcount
    reservas = db.execute(text("DELETE FROM reservas WHERE alumno_id = :a"),
                          {"a": alumno_id}).rowcount
    asistencias = db.execute(text("DELETE FROM asistencias WHERE usuario_id = :a"),
                             {"a": alumno_id}).rowcount
    if reservas or asistencias:
        print(f"  [limpieza]    reservas previas: {reservas} · asistencias previas: "
              f"{asistencias} · aforo corregido en {aforo} clases")
    return {"reservas": reservas, "asistencias": asistencias, "aforo": aforo}


def crear_reservas(db, alumno_id: int, coach_id: int, clases: list) -> int:
    """Reserva las clases (asistió + auditoría de marcado) y sube el aforo de cada una.

    * `asistencia_marcada_at` NO puede quedar NULL: el paso 8 del mantenimiento marca
      como pendiente toda reserva viva en una clase terminada hace >7 días.
    * `asistentes_confirmados` se incrementa en la MISMA transacción para que el paso 9
      (aforo == reservas vivas) siga dando 0. El `FOR UPDATE` evita pisarse con reservas
      reales que entren en paralelo.
    """
    creadas = 0
    for c in clases:
        actual = db.execute(text(
            "SELECT cupo_maximo, asistentes_confirmados FROM clases "
            "WHERE id = :id AND tenant_id = :t FOR UPDATE"),
            {"id": c["id"], "t": TENANT_ID}).first()
        if actual is None:
            continue
        if int(actual.asistentes_confirmados or 0) >= int(actual.cupo_maximo or 0):
            print(f"  [i] clase {c['id']} sin cupo: se saltea")
            continue
        db.execute(text(
            "INSERT INTO reservas (tenant_id, clase_id, alumno_id, fecha_reserva, asistio, "
            "  tokens_gastados, estado, asistencia_marcada_por, asistencia_marcada_at, "
            "  asistencia_via) "
            "SELECT :t, c.id, :a, "
            "  ((c.fecha + c.hora_inicio) AT TIME ZONE 'America/Santiago') - interval '2 days', "
            "  true, 1, :estado, :marcado_por, "
            "  ((c.fecha + c.hora_inicio) AT TIME ZONE 'America/Santiago') + interval '5 minutes', "
            "  :via FROM clases c WHERE c.id = :id AND c.tenant_id = :t"),
            {"t": TENANT_ID, "a": alumno_id, "estado": ESTADO_RESERVA_VIVA,
             "marcado_por": coach_id, "via": ASISTENCIA_VIA, "id": c["id"]})
        db.execute(text(
            "INSERT INTO asistencias (tenant_id, usuario_id, fecha, clase, clase_id, presente) "
            "SELECT :t, :a, c.fecha, :label, c.id, true FROM clases c "
            "WHERE c.id = :id AND c.tenant_id = :t"),
            {"t": TENANT_ID, "a": alumno_id, "label": LABEL_ASISTENCIA, "id": c["id"]})
        db.execute(text(
            "UPDATE clases SET asistentes_confirmados = asistentes_confirmados + 1, "
            "  updated_at = now() WHERE id = :id AND tenant_id = :t"),
            {"id": c["id"], "t": TENANT_ID})
        creadas += 1
        print(f"  [RESERVA]     clase {c['id']} | {c['fecha']} {c['hora_inicio']} | "
              f"{c['disciplina']}")
    return creadas


# ════════════════════════════════════════════════════════════════════════════
#  5. VERIFICACIÓN con los MISMOS SQL del mantenimiento (paso 9, paso 8 y A.3)
# ════════════════════════════════════════════════════════════════════════════
# Igual que A.2(a): aforo == reservas VIVAS, sin filtro de fecha (por eso el aforo se
# incrementa al crear y se decrementa al borrar).
SQL_PASO_9 = ("SELECT count(*) FROM clases c WHERE c.id = ANY(:clases) AND "
              "c.asistentes_confirmados <> (SELECT count(*) FROM reservas r "
              "WHERE r.clase_id = c.id AND r.estado NOT IN ('cancelled', 'cancelada'))")

# Igual que el paso 8: reservas vivas y sin marcar en clases cerradas (>7 días).
SQL_PASO_8 = ("SELECT count(*) FROM reservas r WHERE r.alumno_id = :a AND "
              "r.estado NOT IN ('cancelled', 'cancelada') AND r.asistencia_marcada_at IS NULL "
              "AND EXISTS (SELECT 1 FROM clases c WHERE c.id = r.clase_id "
              "AND (c.fecha + c.hora_fin) AT TIME ZONE 'America/Santiago' "
              "< now() - interval '7 days')")

# Igual que A.3 (`sql_descuadre_creditos`), acotada a los ids del demo.
SQL_A3 = ("SELECT count(*) FROM suscripciones s WHERE s.usuario_id = ANY(:ids) "
          "AND s.estado = 'activo' AND s.creditos_totales IS NOT NULL "
          "AND s.fecha_inicio::date <= current_date "
          "AND s.fecha_expiracion::date >= current_date "
          "AND s.creditos_totales - s.creditos_disponibles <> "
          "  (SELECT count(*) FROM reservas r JOIN clases c ON c.id = r.clase_id "
          "    WHERE r.alumno_id = s.usuario_id "
          "      AND r.estado NOT IN ('cancelled', 'cancelada') "
          "      AND c.fecha BETWEEN s.fecha_inicio::date AND s.fecha_expiracion::date) "
          "+ (SELECT count(*) FROM reservas r JOIN clases c ON c.id = r.clase_id "
          "    WHERE r.alumno_id = s.usuario_id "
          "      AND r.estado IN ('cancelled', 'cancelada') "
          "      AND c.fecha BETWEEN s.fecha_inicio::date AND s.fecha_expiracion::date "
          "      AND r.updated_at > ((c.fecha + c.hora_inicio) "
          "          AT TIME ZONE 'America/Santiago' - interval '6 hours'))")

# Criterio EXACTO de `app.core.dependencies.es_usuario_prueba`: True sólo si hay una
# suscripción ACTIVA al plan llamado "Prueba".
SQL_ES_PRUEBA = ("SELECT count(*) FROM suscripciones s JOIN planes p ON p.id = s.plan_id "
                 "WHERE s.usuario_id = :a AND s.estado = 'activo' AND p.nombre = :prueba")


def verificar(db, ids: dict, clases: list) -> bool:
    """Chequeo final (solo SELECT): deja `ok = True` sólo si TODO quedó como se espera."""
    ok = True
    alumno_id = ids.get(CORREO_ALUMNO)
    coach_id = ids.get(CORREO_COACH)
    estado = lambda b: "OK " if b else "MAL"  # noqa: E731
    print("\n" + "=" * 74)
    print("  VERIFICACIÓN")
    print("=" * 74)

    for correo in CORREOS_DEMO:
        uid = ids.get(correo)
        r = db.execute(text(
            "SELECT id, rol, activo, estado, cambiar_password_al_login, "
            "  (password_hash LIKE '$2%') AS bcrypt FROM usuarios WHERE id = :id"),
            {"id": uid}).first() if uid else None
        bien = bool(r and r.activo and r.estado == "activo" and r.bcrypt
                    and not r.cambiar_password_al_login)
        ok = ok and bien
        print(f"  {estado(bien)} {correo:<22} id={uid} rol={r.rol if r else '?'} "
              f"activo={r.activo if r else '?'} estado={r.estado if r else '?'} "
              f"bcrypt={r.bcrypt if r else '?'}")

    n_prueba = db.execute(text(SQL_ES_PRUEBA),
                          {"a": alumno_id, "prueba": PLAN_EXCLUIDO}).scalar()
    ok = ok and n_prueba == 0
    print(f"  {estado(n_prueba == 0)} es_usuario_prueba = {n_prueba > 0} "
          f"(criterio de app.core.dependencies; suscripciones al plan {PLAN_EXCLUIDO!r}: "
          f"{n_prueba})")

    hoy = date.today()
    sus = db.execute(text(
        "SELECT s.id, p.nombre, s.creditos_totales, s.creditos_disponibles, "
        "  s.fecha_inicio::date AS ini, s.fecha_expiracion::date AS fin FROM suscripciones s "
        "JOIN planes p ON p.id = s.plan_id WHERE s.usuario_id = :a AND s.estado = 'activo' "
        "ORDER BY s.id"), {"a": alumno_id}).fetchall()
    vigentes = {s.id for s in sus if s.ini <= hoy <= s.fin and (s.creditos_disponibles or 0) > 0}
    ok = ok and len(vigentes) == 1
    for s in sus:
        print(f"  {estado(s.id in vigentes)} suscripción id={s.id} | {s.nombre} | créditos "
              f"{s.creditos_disponibles}/{s.creditos_totales} | {s.ini} -> {s.fin} (activo)")

    res = db.execute(text(
        "SELECT count(*) AS total, count(*) FILTER (WHERE r.asistio) AS asistio, "
        "  count(*) FILTER (WHERE r.asistencia_marcada_at IS NULL) AS sin_marcar, "
        "  min(c.fecha) AS desde, max(c.fecha) AS hasta FROM reservas r "
        "JOIN clases c ON c.id = r.clase_id WHERE r.alumno_id = :a "
        "AND r.estado NOT IN ('cancelled', 'cancelada')"), {"a": alumno_id}).first()
    bien = res.total >= 1 and res.asistio == res.total and res.sin_marcar == 0
    ok = ok and bien
    print(f"  {estado(bien)} reservas vivas={res.total} (asistió={res.asistio}, "
          f"sin marcar={res.sin_marcar}) | {res.desde} -> {res.hasta}")

    n_asist = db.execute(text("SELECT count(*) FROM asistencias WHERE usuario_id = :a"),
                         {"a": alumno_id}).scalar()
    ok = ok and n_asist >= 1
    print(f"  {estado(n_asist >= 1)} asistencias del alumno = {n_asist}")

    n_disc = db.execute(text("SELECT count(*) FROM coach_disciplinas WHERE coach_id = :id"),
                        {"id": coach_id}).scalar()
    ok = ok and n_disc >= 1
    print(f"  {estado(n_disc >= 1)} disciplinas del coach = {n_disc}")

    ids_clases = [c["id"] for c in clases]
    paso9 = db.execute(text(SQL_PASO_9), {"clases": ids_clases}).scalar() if ids_clases else 0
    paso8 = db.execute(text(SQL_PASO_8), {"a": alumno_id}).scalar()
    a3 = db.execute(text(SQL_A3), {"ids": [alumno_id]}).scalar()
    ok = ok and paso9 == 0 and paso8 == 0 and a3 == 0
    print(f"  {estado(paso9 == 0)} paso 9 (aforo desincronizado) = {paso9}")
    print(f"  {estado(paso8 == 0)} paso 8 (reservas sin marcar)   = {paso8}")
    print(f"  {estado(a3 == 0)} A.3 (créditos descuadrados)       = {a3}")
    return ok


# ════════════════════════════════════════════════════════════════════════════
#  6. BORRADO (`--borrar`): SOLO los 3 usuarios demo y sus datos
# ════════════════════════════════════════════════════════════════════════════
# FKs hacia `usuarios.id` que el esquema real declara NO ACTION (verificado contra
# pg_constraint): hay que resolverlas ANTES de borrar el usuario.
#   * DELETE: filas que existen SÓLO por el usuario demo.
#   * NULL:   filas ajenas que quedarían apuntando a un usuario que ya no existe (una
#             suscripción real aprobada por el admin demo, un horario del coach demo).
#             OJO: el `coach_id` NO ACTION vive en la tabla LEGADO `horarios_base`
#             (`horarios`, la que usa la app, no tiene esa columna: verificado en la base).
NO_ACTION_DELETE = (
    ("notificaciones", "alumno_id"),
    ("notificaciones_enviadas", "alumno_id"),
    ("solicitudes_planes", "alumno_id"),
    ("solicitudes_planes", "aprobado_por"),
)
NO_ACTION_NULL = (
    ("suscripciones", "aprobado_por"),
    ("horarios_base", "coach_id"),
)
# Dependencias que el borrado del usuario arrastra solo (ON DELETE CASCADE): sirven para
# el resumen y para la verificación post-borrado.
CASCADE_RESUMEN = (
    ("suscripciones", "usuario_id"),
    ("reservas", "alumno_id"),
    ("asistencias", "usuario_id"),
    ("coach_disciplinas", "coach_id"),
)


def _existentes(db, tablas: tuple) -> tuple:
    """Subconjunto de `(tabla, col)` cuyas tablas existen en este esquema.

    Tolera esquemas sin las tablas legado (p.ej. `notificaciones` o `horarios_base`):
    se saltean en vez de romper el borrado.
    """
    salida = []
    for tabla, col in tablas:
        if db.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{tabla}"}).scalar():
            salida.append((tabla, col))
        else:
            print(f"  [i] {tabla} no existe en este esquema: se saltea")
    return tuple(salida)


def previsualizar_borrado(db, ids: dict) -> None:
    """Qué se va a borrar (lo que muestra `--borrar --dry-run`)."""
    uids = list(ids.values())
    print("\n" + "=" * 74)
    print("  BORRADO DE LOS 3 USUARIOS DEMO")
    print("=" * 74)
    for correo in CORREOS_DEMO:
        print(f"  {correo:<22} id={ids.get(correo)}")
    for etiqueta, tablas in (("DELETE ", NO_ACTION_DELETE),
                             ("NULL   ", NO_ACTION_NULL),
                             ("CASCADE", CASCADE_RESUMEN)):
        for tabla, col in _existentes(db, tablas):
            n = db.execute(text(f"SELECT count(*) FROM {tabla} WHERE {col} = ANY(:ids)"),
                           {"ids": uids}).scalar()
            print(f"  [{etiqueta}] {tabla}.{col}: {n} filas")


def borrar(db, ids: dict) -> dict:
    """Elimina a los 3 usuarios demo y sus datos, en UNA sola transacción.

    Orden: 1) devuelve el aforo de las clases que había reservado el alumno (así el paso 9
    vuelve a dar 0 como estaba antes de la demo), 2) resuelve las tablas NO ACTION,
    3) borra los usuarios (el resto cae por CASCADE).
    """
    uids = list(ids.values())
    alumno_id = ids.get(CORREO_ALUMNO)
    hechas = {}

    if alumno_id:
        r = db.execute(text(SQL_BAJAR_AFORO), {"a": alumno_id})
        hechas["aforo"] = r.rowcount
        print(f"  [aforo]    clases con el aforo corregido: {r.rowcount}")

    for tabla, col in _existentes(db, NO_ACTION_DELETE):
        r = db.execute(text(f"DELETE FROM {tabla} WHERE {col} = ANY(:ids)"), {"ids": uids})
        hechas[f"{tabla}.{col}"] = r.rowcount
        print(f"  [DELETE]   {tabla}.{col}: {r.rowcount}")
    for tabla, col in _existentes(db, NO_ACTION_NULL):
        r = db.execute(text(f"UPDATE {tabla} SET {col} = NULL WHERE {col} = ANY(:ids)"),
                       {"ids": uids})
        hechas[f"{tabla}.{col}(NULL)"] = r.rowcount
        print(f"  [NULL]     {tabla}.{col}: {r.rowcount}")

    r = db.execute(text("DELETE FROM usuarios WHERE tenant_id = :t AND correo = ANY(:c)"),
                   {"t": TENANT_ID, "c": list(CORREOS_DEMO)})
    hechas["usuarios"] = r.rowcount
    print(f"  [DELETE]   usuarios: {r.rowcount}")
    return hechas


def verificar_borrado(db, ids: dict) -> bool:
    """Post-borrado: no queda ningún usuario demo, ni sus datos, ni el aforo descuadrado."""
    ok = True
    estado = lambda b: "OK " if b else "MAL"  # noqa: E731
    uids = list(ids.values())
    print("\n" + "=" * 74)
    print("  VERIFICACIÓN POST-BORRADO")
    print("=" * 74)
    n_usr = db.execute(text("SELECT count(*) FROM usuarios WHERE tenant_id = :t "
                            "AND correo = ANY(:c)"),
                       {"t": TENANT_ID, "c": list(CORREOS_DEMO)}).scalar()
    ok = ok and n_usr == 0
    print(f"  {estado(n_usr == 0)} usuarios demo restantes = {n_usr}")
    for tabla, col in _existentes(db, CASCADE_RESUMEN + NO_ACTION_DELETE):
        n = db.execute(text(f"SELECT count(*) FROM {tabla} WHERE {col} = ANY(:ids)"),
                       {"ids": uids}).scalar()
        ok = ok and n == 0
        print(f"  {estado(n == 0)} {tabla}.{col} restantes = {n}")
    paso9 = db.execute(text(
        "SELECT count(*) FROM clases c WHERE c.tenant_id = :t AND "
        "c.asistentes_confirmados <> (SELECT count(*) FROM reservas r "
        "WHERE r.clase_id = c.id AND r.estado NOT IN ('cancelled', 'cancelada'))"),
        {"t": TENANT_ID}).scalar()
    ok = ok and paso9 == 0
    print(f"  {estado(paso9 == 0)} paso 9 (aforo desincronizado en el box) = {paso9}")
    return ok


# ════════════════════════════════════════════════════════════════════════════
#  7. MAIN
# ════════════════════════════════════════════════════════════════════════════
def main(argv=None) -> int:
    args = parsear_args(argv)
    print("=" * 74)
    print(f"  USUARIOS DE DEMO (admin, coach y alumno) — box tenant_id={TENANT_ID}")
    print("=" * 74)
    print(f"destino={args.destino.upper()} | hoy={date.today()} | "
          f"acción={'BORRAR' if args.borrar else 'CREAR/ACTUALIZAR'} | "
          f"reservas={args.reservas} | días={args.dias}"
          + ("  [DRY-RUN]" if args.dry_run else ""))

    # GUARD 3 (ventana): SÓLO con destino=prod. El mantenimiento escribe los días 1 y 15.
    if args.destino == "prod" and date.today().day in DIAS_MANTENIMIENTO:
        if not args.forzar_ventana:
            print(f"[guard] ABORTADO: hoy es día {date.today().day} y el mantenimiento de "
                  f"PROD escribe ese día (vencidos, huérfanas, cierre de asistencia y "
                  f"aforo). Corre otro día, o pasa --forzar-ventana a propósito.")
            return 1
        print(f"[guard] aviso: hoy es día {date.today().day} (día de mantenimiento) y se "
              f"pidió --forzar-ventana.")

    # GUARD 4 (confirmación escrita): antes del dry-run y de cualquier escritura/borrado.
    base = "PRODUCCIÓN" if args.destino == "prod" else "TEST"
    frase = "SI QUIERO PROD" if args.destino == "prod" else "SI QUIERO TEST"
    print(f"\n⚠️  Esto va a {'BORRAR de' if args.borrar else 'escribir en'} la base de {base}.")
    if not pedir(frase, f"Escribe '{frase}' para continuar: "):
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
        # ── Rama --borrar ───────────────────────────────────────────────────
        if args.borrar:
            ids = ids_usuarios_demo(db)
            if not ids:
                print("[fin] no hay ningún usuario demo que borrar.")
                return 0
            previsualizar_borrado(db, ids)
            if args.dry_run:
                print("\n[dry-run] no se borró nada.")
                return 0
            try:
                borrar(db, ids)
                db.commit()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                print(f"\n[ERROR] rollback: no se borró nada: {e}")
                return 1
            print("\n[commit] OK")
            return 0 if verificar_borrado(db, ids) else 1

        # ── Rama crear/actualizar ───────────────────────────────────────────
        entradas = leer_entradas(db, args)
        imprimir_plan(entradas, args)
        if args.dry_run:
            print("\n[dry-run] no se escribió nada (la contraseña no se pide en dry-run).")
            return 0

        try:
            password_hash = env["get_password_hash"](pedir_password())
        except GuardError as e:
            print(f"[abort] {e}")
            return 1

        print("\n" + "=" * 74)
        print("  ESCRITURA (una sola transacción)")
        print("=" * 74)
        try:
            ids = {CORREO_ADMIN: upsert_usuario(db, CORREO_ADMIN, password_hash),
                   CORREO_COACH: upsert_usuario(db, CORREO_COACH, password_hash),
                   CORREO_ALUMNO: upsert_usuario(db, CORREO_ALUMNO, password_hash)}
            asignar_coach(db, ids[CORREO_COACH], entradas["disciplinas"])
            # Idempotencia: el alumno demo es del script, así que sus reservas/asistencias
            # previas se borran (y se devuelve el aforo) antes de recrearlas.
            limpiar_datos_previos(db, ids[CORREO_ALUMNO])
            # Las reservas van ANTES de la suscripción: así los créditos disponibles se
            # calculan con la cantidad REAL de reservas creadas (invariante A.3).
            creadas = crear_reservas(db, ids[CORREO_ALUMNO], ids[CORREO_COACH],
                                     entradas["clases"])
            if creadas < 1:
                raise GuardError("no se pudo reservar ninguna clase")
            upsert_suscripcion(db, ids[CORREO_ALUMNO], entradas["plan"],
                               entradas["plan"]["creditos"] - creadas,
                               entradas["inicio"], entradas["expira"])
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"\n[ERROR] rollback: no se escribió nada: {e}")
            return 1
        print(f"\n[commit] OK — {len(ids)} usuarios, {creadas} reservas/asistencias")

        ok = verificar(db, ids, entradas["clases"])
        print("\n" + "=" * 74)
        print("  RESULTADO:", "OK - usuarios demo listos" if ok else "REVISAR - ver arriba")
        print("=" * 74)
        return 0 if ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
