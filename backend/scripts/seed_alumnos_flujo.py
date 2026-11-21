"""Seed de alumnos DEMO pasando por el FLUJO REAL de la app (solo TEST).

QUE HACE
--------
Crea N alumnos (400 por defecto) repartidos en 4 cohortes y, a diferencia de los
otros seeds, NO escribe membresias ni movimientos "a mano": cada compra recorre

    SolicitudPlan (pending)  ->  aprobacion_planes.activar_plan(...)

que es la MISMA funcion que usan `PUT /solicitudes/{id}/aprobar` y el webhook de
Mercado Pago. De ahi salen, sin intervencion del script:

  * la `Suscripcion` (o la compra `en_cola` si el alumno ya tiene un plan pago
    vigente: el script NO fuerza ese estado, lo decide el servicio);
  * la `TransaccionFinanciera` de membresia;
  * la `TransaccionFinanciera` de MATRICULA (solo si `matricula_service` dice que
    corresponde: alumno nuevo + matricula vigente). El monto se congela en la
    solicitud (`matricula_clp_snapshot`), igual que en la app;
  * la notificacion de "plan aprobado" y la auditoria del admin.

Lo unico que el script escribe directo (porque el flujo pedido no lo cubre o no
tiene servicio propio) es: el alta del `Usuario`, la `Suscripcion` "Prueba" del
trial (espejo de `POST /alumnos/registro/alumno-nuevo`), las membresias
HISTORICAS de los alumnos que renuevan/churnean, y el estado final que deja el
sistema en esas membresias (`vencido`, `baja`). Nada de eso saltea reglas de
negocio de una compra: las compras SIEMPRE pasan por `activar_plan`.

DISTRIBUCION (400)
------------------
| Cohorte   | N   | Detalle                                                        |
|-----------|-----|----------------------------------------------------------------|
| nuevos    | 160 | 96 mensual / 36 trimestral / 20 semestral / 8 anual. MATRICULA. |
| renovando | 120 | 84 con plan vencido (activan ya) / 36 con plan vigente (cola). |
| trial     |  60 | 40 vigentes / 12 por vencer / 8 ya vencidos (plan Prueba).      |
| churned   |  60 | 42 con plan vencido / 18 dados de baja (estado='baja').         |

`--alumnos N` reescala proporcionalmente y siempre suma exacto N.

GUARDS (fail-closed, igual que `seed_anual_prod.py`)
----------------------------------------------------
1. ENVIRONMENT=test forzado ANTES de importar `app.core.config`.
2. `is_test_db_url()` sobre DATABASE_URL y DIRECT_URL. Si alguna no es un
   endpoint TEST conocido => exit 2. Es IMPOSIBLE que escriba en PROD.
3. `EMAIL_MODO=noop` obligatorio: 400 altas + ~220 aprobaciones no pueden
   mandar correos reales.
4. `SCHEDULER_ENABLED=false` (el script no importa `app.main`, pero se exige
   igual para que el entorno sea el de TEST).
5. `TEST_SEED_PASSWORD` presente (la password de los 400 alumnos es esa, con
   un unico hash bcrypt).
6. Si ya existen usuarios del seed y no se pasa `--reemplazar`/`--borrar`
   => aborta (no duplica).
7. `--dry-run` no abre ninguna transaccion de escritura.

MARCADORES Y LIMPIEZA
---------------------
* Correos: `seed.0001@urbanbox.test` ... `seed.NNNN@urbanbox.test`
  (TLD `.test` = RFC 2606, nunca es un correo real).
* Los indices son CONTIGUOS por cohorte: nuevos, despues renovando, trial y
  churned. Sirve para auditar/limpiar por rango.
* `--borrar` elimina SOLO lo que cuelga de esos correos (transacciones por
  referencia, notificaciones, solicitudes, suscripciones y usuarios). No toca
  `auditoria` (append-only) ni ningun usuario ajeno al prefijo.

USO (desde backend/)
--------------------
    py -3.12 scripts/seed_alumnos_flujo.py --dry-run
    py -3.12 scripts/seed_alumnos_flujo.py
    py -3.12 scripts/seed_alumnos_flujo.py --reemplazar
    py -3.12 scripts/seed_alumnos_flujo.py --borrar
"""
import argparse
import importlib
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# En Windows la consola es cp1252: cualquier caracter fuera de ese charset rompe
# un `print` redirigido. Todo el script es ASCII, pero se fija igual.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Marcadores y topologia ────────────────────────────────────────────────────
PREFIJO_CORREO = "seed."
DOMINIO_CORREO = "@urbanbox.test"
TENANT_DEFECTO = 1
ALUMNOS_DEFECTO = 400
MAX_ALUMNOS = 5000
MATRICULA_MONTO_DEFECTO = 25_000

# ── Distribucion (pesos relativos: `repartir()` normaliza y ajusta el resto) ──
COHORTES = (
    ("nuevos", 40),
    ("renovando", 30),
    ("trial", 15),
    ("churned", 15),
)
TRAMOS_NUEVOS = (("mensual", 600), ("trimestral", 225), ("semestral", 125), ("anual", 50))
TRAMOS_RENOVANDO = (("mensual", 70), ("trimestral", 20), ("semestral", 10))
RENOVANDO_SUB = (("vencido", 70), ("vigente", 30))
TRIAL_SUB = (("vigente", 40), ("por_vencer", 12), ("vencido", 8))
CHURNED_SUB = (("vencido", 42), ("baja", 18))

# Duracion de cada tramo (la usan los planes largos que crea el script).
DURACION_TRAMO = {"mensual": 30, "trimestral": 90, "semestral": 180, "anual": 365}

# Decision del dueno (2026-11-18): planes largos unisex, con el mensual de
# $44.000 como referencia del badge de ahorro (10% / 15% / 20%).
PLANES_LARGOS = (
    {"nombre": "Trimestral", "duracion_dias": 90, "precio_clp": 118_800},
    {"nombre": "Semestral", "duracion_dias": 180, "precio_clp": 224_400},
    {"nombre": "Anual", "duracion_dias": 365, "precio_clp": 422_400},
)
PLAN_PRUEBA = {"nombre": "Prueba", "duracion_dias": 7, "precio_clp": 0, "creditos": 1}

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_NEGOCIO = 3
EXIT_INESPERADO = 4

NOMBRES_F = (
    "Camila", "Josefa", "Martina", "Antonia", "Valentina", "Isidora", "Florencia",
    "Catalina", "Fernanda", "Constanza", "Daniela", "Javiera", "Ignacia",
    "Trinidad", "Amanda", "Emilia", "Paz", "Rocio", "Magdalena", "Sofia",
)
NOMBRES_M = (
    "Matias", "Benjamin", "Vicente", "Sebastian", "Tomas", "Joaquin", "Diego",
    "Agustin", "Felipe", "Cristobal", "Nicolas", "Martin", "Lucas", "Ignacio",
    "Gaspar", "Maximiliano", "Alonso", "Renato", "Bastian", "Esteban",
)
APELLIDOS = (
    "Gonzalez", "Munoz", "Rojas", "Diaz", "Perez", "Soto", "Contreras",
    "Silva", "Martinez", "Sepulveda", "Morales", "Rodriguez", "Lopez",
    "Fuentes", "Hernandez", "Torres", "Araya", "Flores", "Espinoza", "Valdes",
)


class SeedError(RuntimeError):
    """Un guard o una regla de negocio no paso. Lleva el exit code."""

    def __init__(self, mensaje: str, codigo: int = EXIT_NEGOCIO):
        super().__init__(mensaje)
        self.codigo = codigo


# ════════════════════════════════════════════════════════════════════════════
#  1. REGLAS PURAS (sin base, sin config: las testea el unitario)
# ════════════════════════════════════════════════════════════════════════════
def repartir(total: int, pesos) -> dict:
    """Reparte `total` segun `pesos` con el metodo del mayor resto.

    Garantiza que la suma sea EXACTAMENTE `total` (sin perder ni inventar
    alumnos por redondeo) y es determinista: los empates se resuelven por el
    orden de `pesos`.
    """
    total = max(0, int(total))
    pesos = [(clave, max(0, int(peso))) for clave, peso in pesos]
    suma = sum(peso for _, peso in pesos)
    if total == 0 or suma == 0:
        return {clave: 0 for clave, _ in pesos}
    crudos = {clave: total * peso / suma for clave, peso in pesos}
    salida = {clave: int(valor) for clave, valor in crudos.items()}
    resto = total - sum(salida.values())
    orden = sorted(crudos, key=lambda clave: crudos[clave] - salida[clave], reverse=True)
    for clave in orden[:resto]:
        salida[clave] += 1
    return salida


def repartir_cohortes(total: int) -> dict:
    """{nuevos, renovando, trial, churned} que suman `total`."""
    return repartir(total, COHORTES)


def calcular_dv(numero: int) -> str:
    """Digito verificador del RUT chileno (modulo 11)."""
    suma, factor = 0, 2
    while numero:
        numero, digito = divmod(numero, 10)
        suma += digito * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def formatear_rut(numero: int, dv: str) -> str:
    """`12345678` + `5` -> `12.345.678-5` (formato que guarda la app)."""
    return f"{numero:,}".replace(",", ".") + f"-{dv}"


def rut_valido(rut: str) -> bool:
    """True si el RUT viene en formato chileno y el DV cierra."""
    try:
        cuerpo, dv = (rut or "").strip().upper().split("-")
        numero = int(cuerpo.replace(".", ""))
    except (AttributeError, ValueError):
        return False
    return numero > 0 and calcular_dv(numero) == dv


def generar_rut(usados: set, rng: random.Random) -> str:
    """RUT valido y no usado. Muta `usados` (el llamador no repite)."""
    for _ in range(200):
        numero = rng.randint(12_000_000, 26_999_999)
        rut = formatear_rut(numero, calcular_dv(numero))
        if rut not in usados:
            usados.add(rut)
            return rut
    raise SeedError("no se pudo generar un RUT libre (rango agotado)", EXIT_INESPERADO)


def perfil_aleatorio(rng: random.Random) -> str:
    """`femenino` | `masculino` (los planes del catalogo son por genero)."""
    return "femenino" if rng.random() < 0.5 else "masculino"


def nombre_aleatorio(rng: random.Random, genero: str) -> str:
    nombres = NOMBRES_F if genero == "femenino" else NOMBRES_M
    return f"{rng.choice(nombres)} {rng.choice(APELLIDOS)}"


def telefono_aleatorio(rng: random.Random) -> str:
    return f"+569{rng.randint(10_000_000, 99_999_999)}"


def correo_de(indice: int) -> str:
    """`seed.0001@urbanbox.test` (indice 1-based, 4 digitos)."""
    return f"{PREFIJO_CORREO}{indice:04d}{DOMINIO_CORREO}"


def fecha_nacimiento_aleatoria(rng: random.Random, hoy: Optional[date] = None) -> date:
    hoy = hoy or date.today()
    edad = rng.randint(18, 60)
    return date(hoy.year - edad, rng.randint(1, 12), rng.randint(1, 28))


def elegir_plan(planes, genero: str, duracion: Optional[int] = None,
                rng: Optional[random.Random] = None):
    """Plan ACTIVO, comercial y pago del genero (o unisex), opcionalmente por duracion.

    Es la misma regla que usa la app para ofrecer planes (`es_comercial` +
    `precio_clp > 0`): "Prueba" y "Pase de regreso" quedan afuera solos.
    """
    candidatos = [
        plan for plan in planes
        if getattr(plan, "activo", False)
        and getattr(plan, "es_comercial", False)
        and (getattr(plan, "precio_clp", 0) or 0) > 0
        and (getattr(plan, "genero", None) in (None, "", genero))
        and (duracion is None or getattr(plan, "duracion_dias", None) == duracion)
    ]
    if not candidatos:
        raise SeedError(
            f"no hay planes pagos para genero={genero!r} duracion={duracion!r}", EXIT_CONFIG)
    return (rng or random).choice(candidatos)


# ════════════════════════════════════════════════════════════════════════════
#  2. ENTORNO Y GUARDS (todo lo pesado se importa ACA, no al importar el modulo)
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Contexto:
    """Estado de la corrida (modulos, RNG, hash y contadores)."""

    tenant_id: int
    rng: random.Random
    ahora: datetime
    password_hash: str
    admin_id: int
    dry_run: bool
    mod: dict = field(default_factory=dict)
    planes: list = field(default_factory=list)
    plan_prueba: object = None
    creados: list = field(default_factory=list)
    usados: set = field(default_factory=set)
    resumen: dict = field(default_factory=dict)


def preparar_entorno(tenant_id: int, rng_seed: int, dry_run: bool) -> Contexto:
    """Fija ENVIRONMENT=test, valida los guards e importa app/models/servicios.

    Nada de esto corre al importar el modulo: el unitario puede importarlo sin
    `.env`, sin base y sin red.
    """
    os.environ["ENVIRONMENT"] = "test"
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    os.chdir(BACKEND_DIR)

    config = importlib.import_module("app.core.config")
    settings = config.settings

    # ── Guard 1/2: la base tiene que ser TEST, en las DOS URLs ──
    for nombre in ("DATABASE_URL", "DIRECT_URL"):
        url = getattr(settings, nombre, "") or ""
        if not url:
            raise SeedError(f"{nombre} vacia: se esperaba la rama TEST", EXIT_CONFIG)
        if not config.is_test_db_url(url):
            raise SeedError(
                f"{nombre} NO es un endpoint TEST conocido ({config.PROD_BRANCH_ID} es "
                "PROD): este seed no corre fuera de TEST", EXIT_CONFIG)

    # ── Guard 3: 400 altas + ~220 aprobaciones no pueden mandar correos ──
    if getattr(settings, "EMAIL_MODO", "") != "noop":
        raise SeedError(
            f"EMAIL_MODO={settings.EMAIL_MODO!r}: el seed exige 'noop' "
            "(backend/.env.test) para no mandar cientos de correos", EXIT_CONFIG)

    # ── Guard 4: entorno de TEST sin scheduler ──
    if getattr(settings, "SCHEDULER_ENABLED", True):
        raise SeedError(
            "SCHEDULER_ENABLED=true: el seed corre con el scheduler apagado "
            "(backend/.env.test)", EXIT_CONFIG)

    # ── Guard 5: la password de los alumnos ──
    if not getattr(settings, "TEST_SEED_PASSWORD", ""):
        raise SeedError(
            "falta TEST_SEED_PASSWORD en backend/.env.test (o como env var)",
            EXIT_CONFIG)

    Tenant = importlib.import_module("app.models.tenant").Tenant
    Usuario = importlib.import_module("app.models.usuario").Usuario
    RolUsuario = importlib.import_module("app.models.usuario").RolUsuario
    Plan = importlib.import_module("app.models.plan").Plan
    SolicitudPlan = importlib.import_module("app.models.solicitud_plan").SolicitudPlan
    Suscripcion = importlib.import_module("app.models.suscripcion").Suscripcion
    Notificacion = importlib.import_module("app.models.notificacion").Notificacion
    TransaccionFinanciera = importlib.import_module(
        "app.models.transaccion_financiera").TransaccionFinanciera
    SessionLocal = importlib.import_module("app.db.database").SessionLocal
    matricula_service = importlib.import_module("app.services.matricula_service")
    aprobacion_planes = importlib.import_module("app.services.aprobacion_planes")
    get_password_hash = importlib.import_module("app.core.security").get_password_hash

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant is None:
            raise SeedError(f"no existe el tenant {tenant_id}", EXIT_CONFIG)
        admin = (db.query(Usuario)
                 .filter(Usuario.tenant_id == tenant_id,
                         Usuario.rol == RolUsuario.administrador)
                 .order_by(Usuario.id)
                 .all())
        if not admin:
            raise SeedError(
                f"el tenant {tenant_id} no tiene ningun admin para `actor_id`", EXIT_CONFIG)
        admin_id = next(
            (u.id for u in admin if u.correo == "demo.admin@urbanbox.cl"), admin[0].id)
    finally:
        db.close()

    ctx = Contexto(
        tenant_id=tenant_id,
        rng=random.Random(rng_seed),
        ahora=datetime.now(timezone.utc),
        password_hash=get_password_hash(settings.TEST_SEED_PASSWORD),
        admin_id=admin_id,
        dry_run=dry_run,
        mod={
            "tenant": tenant,
            "Tenant": Tenant,
            "Usuario": Usuario,
            "RolUsuario": RolUsuario,
            "Plan": Plan,
            "SolicitudPlan": SolicitudPlan,
            "Suscripcion": Suscripcion,
            "Notificacion": Notificacion,
            "TransaccionFinanciera": TransaccionFinanciera,
            "SessionLocal": SessionLocal,
            "matricula_service": matricula_service,
            "aprobacion_planes": aprobacion_planes,
        },
    )

    print("=" * 72)
    print(f"BD TEST: {config._host_de_url(settings.DATABASE_URL)}")
    print(f"tenant={tenant_id} | admin actor_id={admin_id} | EMAIL_MODO=noop | "
          f"{'DRY-RUN (no escribe)' if dry_run else 'ESCRITURA'}")
    print("=" * 72)
    return ctx


# ════════════════════════════════════════════════════════════════════════════
#  3. PREPARACION (planes y matricula: configuracion, no alumnos)
# ════════════════════════════════════════════════════════════════════════════
def _stub_plan(spec: dict):
    """Plan "de mentira" para el dry-run cuando todavia no existe en la base."""
    from types import SimpleNamespace
    return SimpleNamespace(
        id=None, nombre=spec["nombre"], duracion_dias=spec["duracion_dias"],
        precio_clp=spec["precio_clp"], activo=True, es_comercial=True,
        genero=None, es_ilimitado=True, creditos=None, plan_referencia_id=None)


def preparar_planes(db, ctx: Contexto, crear: bool) -> None:
    """Asegura 'Prueba' y los largos (idempotente). Deja `ctx.planes` listo.

    `crear=False` (`--sin-planes`): si falta algun largo, aborta en vez de
    inventarlo. En dry-run no escribe: informa lo que crearia y usa stubs para
    poder simular la eleccion.
    """
    Plan = ctx.mod["Plan"]
    planes = db.query(Plan).filter(Plan.tenant_id == ctx.tenant_id).all()
    por_nombre = {p.nombre: p for p in planes}
    avisos = []

    prueba = por_nombre.get(PLAN_PRUEBA["nombre"])
    if prueba is None:
        if ctx.dry_run or not crear:
            if not crear:
                raise SeedError("falta el plan 'Prueba' y se paso --sin-planes", EXIT_CONFIG)
            avisos.append("se crearia el plan 'Prueba' (7 dias, 1 credito, gratis)")
            prueba = _stub_plan(PLAN_PRUEBA)
        else:
            prueba = Plan(
                tenant_id=ctx.tenant_id, nombre=PLAN_PRUEBA["nombre"],
                creditos=PLAN_PRUEBA["creditos"], es_ilimitado=False,
                precio_clp=0, duracion_dias=PLAN_PRUEBA["duracion_dias"],
                activo=True, es_comercial=True, genero=None)
            db.add(prueba)
            db.commit()
            db.refresh(prueba)
            avisos.append("creado el plan 'Prueba'")

    # Referencia del badge de ahorro: el mensual pago mas barato del box.
    referencia = (
        db.query(Plan)
        .filter(Plan.tenant_id == ctx.tenant_id, Plan.duracion_dias == 30,
                Plan.activo.is_(True), Plan.es_comercial.is_(True),
                Plan.precio_clp > 0)
        .order_by(Plan.precio_clp, Plan.id)
        .first())

    faltantes = []
    for spec in PLANES_LARGOS:
        existente = por_nombre.get(spec["nombre"])
        if existente is not None:
            continue
        if not crear:
            faltantes.append(spec["nombre"])
            continue
        if ctx.dry_run:
            avisos.append(
                f"se crearia '{spec['nombre']}' ({spec['duracion_dias']}d, "
                f"${spec['precio_clp']:,})".replace(",", "."))
            continue
        nuevo = Plan(
            tenant_id=ctx.tenant_id, nombre=spec["nombre"], creditos=None,
            es_ilimitado=True, precio_clp=spec["precio_clp"],
            duracion_dias=spec["duracion_dias"], activo=True, es_comercial=True,
            genero=None, plan_referencia_id=referencia.id if referencia else None)
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        avisos.append(
            f"creado el plan '{spec['nombre']}' ({spec['duracion_dias']}d, "
            f"${spec['precio_clp']:,})".replace(",", "."))

    if faltantes:
        raise SeedError(
            "faltan los planes largos " + ", ".join(faltantes)
            + " y se paso --sin-planes (crealos desde el panel o quita el flag)",
            EXIT_CONFIG)

    # Releer para tener ids reales (los stubs del dry-run no se persisten).
    planes = db.query(Plan).filter(Plan.tenant_id == ctx.tenant_id).all()
    if ctx.dry_run:
        nombres = {p.nombre for p in planes}
        planes = list(planes) + [
            _stub_plan(spec) for spec in PLANES_LARGOS if spec["nombre"] not in nombres]
        if PLAN_PRUEBA["nombre"] not in nombres:
            planes.append(_stub_plan(PLAN_PRUEBA))
    ctx.planes = planes
    ctx.plan_prueba = next(
        (p for p in planes if p.nombre == PLAN_PRUEBA["nombre"]), None)
    ctx.resumen["planes_avisos"] = avisos


def preparar_matricula(db, ctx: Contexto, monto: int, tocar: bool) -> None:
    """Deja la matricula del box activa con `monto` (decision del dueno).

    `--sin-matricula` no toca nada: si estaba apagada, ningun alumno paga y el
    resumen lo dice. En dry-run solo informa.
    """
    Tenant = ctx.mod["Tenant"]
    tenant = db.get(Tenant, ctx.tenant_id)
    antes = (bool(tenant.matricula_activa), tenant.matricula_monto_clp)
    ctx.resumen["matricula_antes"] = antes
    ctx.resumen["matricula_tocar"] = bool(tocar)

    if not tocar:
        ctx.resumen["matricula_monto_efectivo"] = int(antes[1] or 0) if antes[0] else 0
        ctx.resumen["matricula_aviso"] = (
            "no se toco (--sin-matricula): "
            + ("ACTIVA" if antes[0] else "APAGADA (0 alumnos pagaran matricula)"))
        return

    ctx.resumen["matricula_monto_efectivo"] = int(monto)

    cambios = []
    if not tenant.matricula_activa:
        tenant.matricula_activa = True
        tenant.matricula_activada_en = ctx.ahora
        cambios.append("activada")
    if tenant.matricula_monto_clp != monto:
        tenant.matricula_monto_clp = monto
        cambios.append(f"monto=${monto:,}".replace(",", "."))
    if cambios:
        if ctx.dry_run:
            ctx.resumen["matricula_aviso"] = "se aplicaria: " + ", ".join(cambios)
        else:
            db.commit()
            ctx.resumen["matricula_aviso"] = "aplicado: " + ", ".join(cambios)
    else:
        ctx.resumen["matricula_aviso"] = f"ya estaba activa en ${monto:,}".replace(",", ".")


# ════════════════════════════════════════════════════════════════════════════
#  4. PIEZAS DEL FLUJO (alta / solicitud / activacion / historicas / trial)
# ════════════════════════════════════════════════════════════════════════════
def crear_alumno(db, ctx: Contexto, indice: int, genero: str):
    """Alta del alumno (lo unico que el flujo de compra no cubre)."""
    Usuario = ctx.mod["Usuario"]
    RolUsuario = ctx.mod["RolUsuario"]
    alumno = Usuario(
        tenant_id=ctx.tenant_id,
        rut=generar_rut(ctx.usados, ctx.rng),
        nombre=nombre_aleatorio(ctx.rng, genero),
        telefono=telefono_aleatorio(ctx.rng),
        correo=correo_de(indice),
        password_hash=ctx.password_hash,
        rol=RolUsuario.alumno,
        activo=True,
        estado="activo",
        cambiar_password_al_login=False,
        peso_kg=round(ctx.rng.uniform(50, 95), 1),
        estatura_cm=ctx.rng.randint(150, 195),
        genero=genero,
        fecha_nacimiento=fecha_nacimiento_aleatoria(ctx.rng),
        acepta_tyc_en=ctx.ahora,
        acepta_tyc_version="v1",
        acepta_salud_en=ctx.ahora,
        acepta_salud_version="v1",
        acepta_correo_reactivacion=True,
    )
    db.add(alumno)
    db.commit()
    db.refresh(alumno)
    ctx.creados.append(alumno.id)
    return alumno


def crear_solicitud(db, ctx: Contexto, alumno, plan) -> tuple:
    """Solicitud PENDIENTE con los snapshots que congela el endpoint real.

    Devuelve `(solicitud, monto_matricula)`: el monto sale de
    `matricula_service.monto_para_alumno` (vigente + alumno nuevo), exactamente
    la misma funcion que usa `POST /solicitudes/solicitar`.
    """
    SolicitudPlan = ctx.mod["SolicitudPlan"]
    matricula = ctx.mod["matricula_service"]
    monto_matricula = matricula.monto_para_alumno(db, ctx.tenant_id, alumno.id)
    solicitud = SolicitudPlan(
        tenant_id=ctx.tenant_id,
        alumno_id=alumno.id,
        plan_id=plan.id,
        estado="pending",
        precio_clp_snapshot=plan.precio_clp,
        matricula_clp_snapshot=monto_matricula,
        origen_pago="manual",
    )
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)
    return solicitud, monto_matricula


def activar(db, ctx: Contexto, solicitud) -> dict:
    """Aprueba por el MISMO servicio que el endpoint y el webhook de MP."""
    aprobacion = ctx.mod["aprobacion_planes"]
    try:
        return aprobacion.activar_plan(
            db,
            solicitud.id,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.admin_id,
            origen=aprobacion.ORIGEN_MANUAL,
            background_tasks=None,
        )
    except (aprobacion.SolicitudNoProcesable, aprobacion.PlanNoEncontrado,
            aprobacion.PagoOnlineNoConfirmado) as error:
        db.rollback()
        raise SeedError(
            f"activar_plan rechazo la solicitud {solicitud.id}: {error}", EXIT_NEGOCIO
        ) from error


def crear_membresia_historica(db, ctx: Contexto, alumno, plan, *,
                               estado: str, inicio: datetime,
                               expiracion: datetime, creditos_disponibles):
    """Membresia del PASADO (lo que ya existia antes de la compra de hoy).

    Se escribe directo a proposito: `activar_plan` siempre usa `ahora`, y estas
    filas representan compras viejas. `creditos_disponibles=None` = ilimitado.
    """
    Suscripcion = ctx.mod["Suscripcion"]
    sub = Suscripcion(
        tenant_id=ctx.tenant_id,
        usuario_id=alumno.id,
        plan_id=plan.id,
        estado=estado,
        creditos_totales=plan.creditos,
        creditos_disponibles=creditos_disponibles,
        fecha_inicio=inicio,
        fecha_expiracion=expiracion,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def crear_trial(db, ctx: Contexto, alumno, *, estado: str,
                expiracion: datetime):
    """Suscripcion 'Prueba' (1 credito / 7 dias), espejo del alta publica."""
    Suscripcion = ctx.mod["Suscripcion"]
    sub = Suscripcion(
        tenant_id=ctx.tenant_id,
        usuario_id=alumno.id,
        plan_id=ctx.plan_prueba.id,
        estado=estado,
        creditos_totales=1,
        creditos_disponibles=1,
        fecha_inicio=ctx.ahora - timedelta(days=ctx.rng.randint(0, 2)),
        fecha_expiracion=expiracion,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


# ════════════════════════════════════════════════════════════════════════════
#  5. COHORTES (cada alumno, por el flujo real)
# ════════════════════════════════════════════════════════════════════════════
def _stats(ctx: Contexto, cohorte: str) -> dict:
    return ctx.resumen.setdefault(cohorte, {
        "alumnos": 0, "activadas": 0, "en_cola": 0,
        "matriculas": 0, "vencidas": 0, "bajas": 0,
    })


def _progreso(ctx: Contexto, total: int) -> None:
    hechos = len(ctx.creados)
    if hechos % 25 == 0 or hechos == total:
        print(f"  ... {hechos}/{total} alumnos creados", flush=True)


def _anotar_compra(ctx: Contexto, cohorte: str, resultado: dict,
                   monto_matricula) -> None:
    stats = _stats(ctx, cohorte)
    if resultado.get("estado") == "en_cola":
        stats["en_cola"] += 1
    else:
        stats["activadas"] += 1
    if monto_matricula:
        stats["matriculas"] += 1


def ejecutar_nuevos(db, ctx: Contexto, total: int, indice: int, total_global: int):
    """Alumnos NUEVOS: plan pago + matricula (no tuvieron plan pago antes)."""
    tramos = repartir(total, TRAMOS_NUEVOS)
    for tramo, cantidad in tramos.items():
        duracion = DURACION_TRAMO[tramo]
        for _ in range(cantidad):
            indice += 1
            genero = perfil_aleatorio(ctx.rng)
            plan = elegir_plan(ctx.planes, genero, duracion, ctx.rng)
            alumno = crear_alumno(db, ctx, indice, genero)
            solicitud, monto_matricula = crear_solicitud(db, ctx, alumno, plan)
            resultado = activar(db, ctx, solicitud)
            _anotar_compra(ctx, "nuevos", resultado, monto_matricula)
            _stats(ctx, "nuevos")["alumnos"] += 1
            _progreso(ctx, total_global)
    return indice


def ejecutar_renovando(db, ctx: Contexto, total: int, indice: int, total_global: int):
    """ANTIGUOS: ya tenian plan pago y compran otro.

    Si el plan viejo sigue usable, `activar_plan` deja la compra `en_cola` (el
    script NO lo decide). Eso es lo que se verifica despues.
    """
    sub = repartir(total, RENOVANDO_SUB)
    tramos = repartir(total, TRAMOS_RENOVANDO)
    pendientes = [t for t, n in tramos.items() for _ in range(n)]
    ctx.rng.shuffle(pendientes)

    for tipo, cantidad in sub.items():
        for _ in range(cantidad):
            indice += 1
            genero = perfil_aleatorio(ctx.rng)
            plan_hist = elegir_plan(ctx.planes, genero, DURACION_TRAMO["mensual"], ctx.rng)
            plan_nuevo = elegir_plan(
                ctx.planes, genero, DURACION_TRAMO[pendientes.pop()], ctx.rng)
            alumno = crear_alumno(db, ctx, indice, genero)

            if tipo == "vigente":
                inicio = ctx.ahora - timedelta(days=ctx.rng.randint(5, 20))
                expiracion = ctx.ahora + timedelta(days=ctx.rng.randint(5, 25))
                crear_membresia_historica(
                    db, ctx, alumno, plan_hist, estado="activo", inicio=inicio,
                    expiracion=expiracion,
                    creditos_disponibles=(
                        None if plan_hist.es_ilimitado else plan_hist.creditos))
            else:
                inicio = ctx.ahora - timedelta(days=ctx.rng.randint(60, 180))
                expiracion = ctx.ahora - timedelta(days=ctx.rng.randint(1, 30))
                crear_membresia_historica(
                    db, ctx, alumno, plan_hist, estado="vencido", inicio=inicio,
                    expiracion=expiracion, creditos_disponibles=0)

            solicitud, monto_matricula = crear_solicitud(db, ctx, alumno, plan_nuevo)
            resultado = activar(db, ctx, solicitud)

            esperado = "en_cola" if tipo == "vigente" else "approved"
            if resultado.get("estado", "approved") != esperado:
                raise SeedError(
                    f"renovando/{tipo}: se esperaba {esperado} y activar_plan dijo "
                    f"{resultado.get('estado', 'approved')} (solicitud {solicitud.id})")
            if monto_matricula:
                raise SeedError(
                    f"renovando: la matricula NO corresponde (alumno {alumno.id}) "
                    f"y se congelo ${monto_matricula}")

            _anotar_compra(ctx, "renovando", resultado, monto_matricula)
            _stats(ctx, "renovando")["alumnos"] += 1
            _progreso(ctx, total_global)
    return indice


def ejecutar_trial(db, ctx: Contexto, total: int, indice: int, total_global: int):
    """TRIAL: alta + plan 'Prueba' (sin compra)."""
    sub = repartir(total, TRIAL_SUB)
    for tipo, cantidad in sub.items():
        for _ in range(cantidad):
            indice += 1
            genero = perfil_aleatorio(ctx.rng)
            alumno = crear_alumno(db, ctx, indice, genero)
            if tipo == "vencido":
                estado = "vencido"
                expiracion = ctx.ahora - timedelta(days=ctx.rng.randint(1, 10))
            elif tipo == "por_vencer":
                estado = "activo"
                expiracion = ctx.ahora + timedelta(days=1)
            else:
                estado = "activo"
                expiracion = ctx.ahora + timedelta(days=ctx.rng.randint(2, 6))
            crear_trial(db, ctx, alumno, estado=estado, expiracion=expiracion)
            stats = _stats(ctx, "trial")
            stats["alumnos"] += 1
            if estado == "vencido":
                stats["vencidas"] += 1
            _progreso(ctx, total_global)
    return indice


def ejecutar_churned(db, ctx: Contexto, total: int, indice: int, total_global: int):
    """CHURNED: plan vencido sin renovar; una parte ademas quedo de BAJA."""
    sub = repartir(total, CHURNED_SUB)
    for tipo, cantidad in sub.items():
        for _ in range(cantidad):
            indice += 1
            genero = perfil_aleatorio(ctx.rng)
            plan = elegir_plan(ctx.planes, genero, DURACION_TRAMO["mensual"], ctx.rng)
            alumno = crear_alumno(db, ctx, indice, genero)
            inicio = ctx.ahora - timedelta(days=ctx.rng.randint(120, 400))
            expiracion = ctx.ahora - timedelta(days=ctx.rng.randint(5, 90))
            crear_membresia_historica(
                db, ctx, alumno, plan, estado="vencido", inicio=inicio,
                expiracion=expiracion, creditos_disponibles=0)
            stats = _stats(ctx, "churned")
            stats["alumnos"] += 1
            stats["vencidas"] += 1
            if tipo == "baja":
                # CHECK ck_usuarios_activo_estado: activo = (estado='activo').
                alumno.estado = "baja"
                alumno.activo = False
                alumno.fecha_baja = ctx.ahora - timedelta(days=ctx.rng.randint(5, 60))
                db.commit()
                stats["bajas"] += 1
            _progreso(ctx, total_global)
    return indice


# ════════════════════════════════════════════════════════════════════════════
#  6. VERIFICACION, RESUMEN, SIMULACION Y LIMPIEZA
# ════════════════════════════════════════════════════════════════════════════
def verificar(db, ctx: Contexto) -> list:
    """Cuenta lo que quedo en la base y lo compara con lo que el plan esperaba."""
    from sqlalchemy import and_, or_

    SolicitudPlan = ctx.mod["SolicitudPlan"]
    Suscripcion = ctx.mod["Suscripcion"]
    TransaccionFinanciera = ctx.mod["TransaccionFinanciera"]
    ids = ctx.creados
    subs = db.query(Suscripcion).filter(Suscripcion.usuario_id.in_(ids)).all()
    sols = db.query(SolicitudPlan).filter(SolicitudPlan.alumno_id.in_(ids)).all()
    sub_ids = [s.id for s in subs] or [-1]
    sol_ids = [s.id for s in sols] or [-1]

    filtro_ref = or_(
        and_(TransaccionFinanciera.referencia_tipo == "suscripcion",
             TransaccionFinanciera.referencia_id.in_(sub_ids)),
        and_(TransaccionFinanciera.referencia_tipo == "solicitud_plan",
             TransaccionFinanciera.referencia_id.in_(sol_ids)),
    )
    tx = db.query(TransaccionFinanciera).filter(
        TransaccionFinanciera.tenant_id == ctx.tenant_id, filtro_ref).all()
    matriculas = [t for t in tx if t.categoria == "matricula"]
    membresias = [t for t in tx if t.categoria == "membresia"]

    datos = {
        "alumnos": len(ids),
        "activas": sum(1 for s in subs if str(s.estado) == "activo"),
        "vencidas": sum(1 for s in subs if str(s.estado) == "vencido"),
        "en_cola": sum(1 for s in sols if s.estado == "en_cola"),
        "pendientes": sum(1 for s in sols if s.estado == "pending"),
        "matriculas": len(matriculas),
        "membresias": len(membresias),
        "monto_matriculas": sum(t.monto for t in matriculas),
    }

    r = ctx.resumen
    esperado = {
        "alumnos": sum(r[c]["alumnos"] for c in ("nuevos", "renovando", "trial", "churned")),
        "activas": (r["nuevos"]["activadas"] + r["renovando"]["activadas"]
                    + r["trial"]["alumnos"] - r["trial"]["vencidas"]),
        "vencidas": r["trial"]["vencidas"] + r["churned"]["vencidas"],
        "en_cola": r["renovando"]["en_cola"],
        "pendientes": 0,
        "matriculas": r["nuevos"]["matriculas"],
        "membresias": (r["nuevos"]["activadas"] + r["nuevos"]["en_cola"]
                       + r["renovando"]["activadas"] + r["renovando"]["en_cola"]),
    }

    problemas = []
    for clave, valor in esperado.items():
        if datos[clave] != valor:
            problemas.append(f"{clave}: base={datos[clave]} plan={valor}")
    monto = r.get("matricula_monto_efectivo") or 0
    if datos["monto_matriculas"] != datos["matriculas"] * monto:
        problemas.append(
            f"monto de matriculas={datos['monto_matriculas']} no cierra con "
            f"{datos['matriculas']} x ${monto}")

    print("\n" + "=" * 72)
    print("VERIFICACION (base vs plan)")
    for clave in ("alumnos", "activas", "vencidas", "en_cola", "pendientes",
                  "matriculas", "membresias", "monto_matriculas"):
        print(f"  {clave:<16} base={datos[clave]:>7}  plan={esperado.get(clave, '-'):>7}")
    if problemas:
        print("  [!] DIFERENCIAS:")
        for p in problemas:
            print(f"      - {p}")
    else:
        print("  [OK] todo coincide")
    return problemas


def imprimir_resumen(ctx: Contexto) -> None:
    print("\n" + "=" * 72)
    print("RESUMEN POR COHORTE")
    print(f"  {'cohorte':<10}{'alumnos':>9}{'activadas':>11}{'en_cola':>9}"
          f"{'matriculas':>12}{'vencidas':>10}{'bajas':>7}")
    totales = {"alumnos": 0, "activadas": 0, "en_cola": 0, "matriculas": 0,
               "vencidas": 0, "bajas": 0}
    for cohorte in ("nuevos", "renovando", "trial", "churned"):
        s = ctx.resumen.get(cohorte, {})
        for clave in totales:
            totales[clave] += s.get(clave, 0)
        print(f"  {cohorte:<10}{s.get('alumnos', 0):>9}{s.get('activadas', 0):>11}"
              f"{s.get('en_cola', 0):>9}{s.get('matriculas', 0):>12}"
              f"{s.get('vencidas', 0):>10}{s.get('bajas', 0):>7}")
    print(f"  {'TOTAL':<10}{totales['alumnos']:>9}{totales['activadas']:>11}"
          f"{totales['en_cola']:>9}{totales['matriculas']:>12}"
          f"{totales['vencidas']:>10}{totales['bajas']:>7}")
    print(f"\n  matricula: {ctx.resumen.get('matricula_aviso', '-')}")
    for aviso in ctx.resumen.get("planes_avisos", []):
        print(f"  planes: {aviso}")


def simular(ctx: Contexto, total: int) -> None:
    """Dry-run: distribucion, una muestra de alumnos y lo que escribiria."""
    dist = repartir_cohortes(total)
    tramos_nuevos = repartir(dist["nuevos"], TRAMOS_NUEVOS)
    tramos_renov = repartir(dist["renovando"], TRAMOS_RENOVANDO)
    sub_renov = repartir(dist["renovando"], RENOVANDO_SUB)
    sub_trial = repartir(dist["trial"], TRIAL_SUB)
    sub_churn = repartir(dist["churned"], CHURNED_SUB)

    print("\nDISTRIBUCION")
    print(f"  nuevos    {dist['nuevos']:>4}  tramos={tramos_nuevos}")
    print(f"  renovando {dist['renovando']:>4}  sub={sub_renov}  tramos={tramos_renov}")
    print(f"  trial     {dist['trial']:>4}  sub={sub_trial}")
    print(f"  churned   {dist['churned']:>4}  sub={sub_churn}")
    print(f"  TOTAL     {sum(dist.values()):>4}")

    paga_matricula = ctx.resumen.get("matricula_monto_efectivo", 0) > 0
    print(f"\n  matricula: {ctx.resumen.get('matricula_aviso', '-')}")
    for aviso in ctx.resumen.get("planes_avisos", []):
        print(f"  planes: {aviso}")

    print("\nMUESTRA (alumnos nuevos, plan mensual)")
    # RNG FORKEADO: la muestra no consume la secuencia real, asi los primeros
    # 10 alumnos del run son exactamente los que se ven aca.
    rng = random.Random()
    rng.setstate(ctx.rng.getstate())
    usados = set(ctx.usados)
    mensuales = [p for p in ctx.planes
                 if getattr(p, "duracion_dias", None) == DURACION_TRAMO["mensual"]]
    for indice in range(1, min(10, dist["nuevos"]) + 1):
        genero = perfil_aleatorio(rng)
        plan = elegir_plan(mensuales or ctx.planes, genero, None, rng)
        precio = f"${plan.precio_clp:,}".replace(",", ".")
        print(f"  {correo_de(indice):<32} {nombre_aleatorio(rng, genero):<26} "
              f"{generar_rut(usados, rng):<14} {genero:<10} "
              f"{plan.nombre:<16} {precio:>12}"
              + ("  + matricula" if paga_matricula else ""))

    print("\nESCRITURAS QUE HARIA")
    print(f"  usuarios                   : {sum(dist.values())}")
    print(f"  solicitudes + activar_plan : {dist['nuevos'] + dist['renovando']}")
    print(f"  suscripciones activas      : "
          f"{dist['nuevos'] + sub_renov['vencido'] + sub_trial['vigente'] + sub_trial['por_vencer']}")
    print(f"  compras en cola            : {sub_renov['vigente']}")
    print(f"  suscripciones vencidas     : "
          f"{sub_trial['vencido'] + sub_churn['vencido'] + sub_churn['baja']}")
    print(f"  usuarios dados de baja     : {sub_churn['baja']}")
    print(f"  transacciones matricula    : {dist['nuevos'] if paga_matricula else 0}")
    print("\n[DRY-RUN] no se escribio nada.")


def borrar_seed(db, ctx: Contexto) -> dict:
    """Borra SOLO lo que cuelga de los correos del seed (orden FK-safe)."""
    from sqlalchemy import and_, or_, text

    Usuario = ctx.mod["Usuario"]
    SolicitudPlan = ctx.mod["SolicitudPlan"]
    Suscripcion = ctx.mod["Suscripcion"]
    Notificacion = ctx.mod["Notificacion"]
    TransaccionFinanciera = ctx.mod["TransaccionFinanciera"]

    ids = [fila[0] for fila in db.query(Usuario.id).filter(
        Usuario.tenant_id == ctx.tenant_id,
        Usuario.correo.like(f"{PREFIJO_CORREO}%{DOMINIO_CORREO}")).all()]
    if not ids:
        return {"usuarios": 0}

    sub_ids = [fila[0] for fila in db.query(Suscripcion.id).filter(
        Suscripcion.usuario_id.in_(ids)).all()] or [-1]
    sol_ids = [fila[0] for fila in db.query(SolicitudPlan.id).filter(
        SolicitudPlan.alumno_id.in_(ids)).all()] or [-1]

    conteos = {"usuarios": len(ids)}
    filtro_ref = or_(
        and_(TransaccionFinanciera.referencia_tipo == "suscripcion",
             TransaccionFinanciera.referencia_id.in_(sub_ids)),
        and_(TransaccionFinanciera.referencia_tipo == "solicitud_plan",
             TransaccionFinanciera.referencia_id.in_(sol_ids)),
    )
    conteos["transacciones"] = db.query(TransaccionFinanciera).filter(
        filtro_ref).delete(synchronize_session=False)
    conteos["notificaciones"] = db.query(Notificacion).filter(
        Notificacion.alumno_id.in_(ids)).delete(synchronize_session=False)
    conteos["solicitudes"] = db.query(SolicitudPlan).filter(
        SolicitudPlan.alumno_id.in_(ids)).delete(synchronize_session=False)

    # Data marts que pueden haberse poblado entre el seed y la limpieza.
    for tabla in ("predictions_churn", "segmentacion_alumnos"):
        try:
            db.execute(text(f"DELETE FROM {tabla} WHERE usuario_id = ANY(:ids)"),
                       {"ids": ids})
        except Exception:  # noqa: BLE001 (tabla ausente en algun entorno)
            db.rollback()

    conteos["suscripciones"] = db.query(Suscripcion).filter(
        Suscripcion.usuario_id.in_(ids)).delete(synchronize_session=False)
    conteos["usuarios"] = db.query(Usuario).filter(
        Usuario.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return conteos


# ════════════════════════════════════════════════════════════════════════════
#  7. CLI
# ════════════════════════════════════════════════════════════════════════════
def contar_seed(db, ctx: Contexto) -> int:
    Usuario = ctx.mod["Usuario"]
    return db.query(Usuario).filter(
        Usuario.tenant_id == ctx.tenant_id,
        Usuario.correo.like(f"{PREFIJO_CORREO}%{DOMINIO_CORREO}")).count()


def parsear_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Seed de alumnos demo por el flujo real (SOLO TEST).")
    parser.add_argument("--alumnos", type=int, default=ALUMNOS_DEFECTO,
                        help=f"cantidad total (default {ALUMNOS_DEFECTO}, max {MAX_ALUMNOS})")
    parser.add_argument("--seed", type=int, default=7,
                        help="semilla del RNG (mismos nombres/RUT/fechas entre corridas)")
    parser.add_argument("--tenant", type=int, default=TENANT_DEFECTO)
    parser.add_argument("--monto-matricula", type=int, default=MATRICULA_MONTO_DEFECTO,
                        help=f"monto con el que se activa la matricula (default "
                             f"{MATRICULA_MONTO_DEFECTO})")
    parser.add_argument("--sin-matricula", action="store_true",
                        help="no toca la config de matricula del box")
    parser.add_argument("--sin-planes", action="store_true",
                        help="no crea los planes largos (aborta si faltan)")
    parser.add_argument("--dry-run", action="store_true",
                        help="muestra el plan completo y NO escribe nada")
    parser.add_argument("--si", action="store_true", help="no pide confirmacion")
    parser.add_argument("--borrar", action="store_true",
                        help="solo borra los alumnos del seed")
    parser.add_argument("--reemplazar", action="store_true",
                        help="borra el seed existente y lo recrea")
    args = parser.parse_args(argv)
    if not 1 <= args.alumnos <= MAX_ALUMNOS:
        parser.error(f"--alumnos tiene que estar entre 1 y {MAX_ALUMNOS}")
    if args.monto_matricula < 0:
        parser.error("--monto-matricula no puede ser negativo")
    if args.borrar and args.reemplazar:
        parser.error("--borrar y --reemplazar son excluyentes")
    return args


def pedir_confirmacion(texto: str) -> bool:
    """Confirmacion tipografica (mismo patron que crear_usuarios_demo)."""
    try:
        respuesta = input(f"Escribe '{texto}' para continuar: ").strip()
    except EOFError:
        print("[abort] sin entrada interactiva (EOF).")
        return False
    if respuesta != texto:
        print(f"[abort] confirmacion invalida ('{respuesta}').")
        return False
    return True


def main(argv=None) -> int:
    args = parsear_args(argv)
    try:
        ctx = preparar_entorno(args.tenant, args.seed, args.dry_run)
    except SeedError as error:
        print(f"[FATAL] {error}")
        return error.codigo

    db = ctx.mod["SessionLocal"]()
    try:
        existentes = contar_seed(db, ctx)

        if args.borrar:
            print(f"usuarios del seed: {existentes}")
            if not existentes:
                print("nada que borrar.")
                return EXIT_OK
            if args.dry_run:
                print("[DRY-RUN] no se borro nada.")
                return EXIT_OK
            if not args.si and not pedir_confirmacion("BORRAR SEED"):
                return EXIT_NEGOCIO
            print(f"borrado: {borrar_seed(db, ctx)}")
            return EXIT_OK

        if existentes and not args.reemplazar:
            raise SeedError(
                f"ya existen {existentes} usuarios del seed; usa --reemplazar "
                "(borra y recrea) o --borrar", EXIT_CONFIG)
        if existentes:
            if args.dry_run:
                print(f"[DRY-RUN] se borrarian {existentes} usuarios del seed")
            else:
                if not args.si and not pedir_confirmacion("REEMPLAZAR SEED"):
                    return EXIT_NEGOCIO
                print(f"borrado previo: {borrar_seed(db, ctx)}")

        preparar_planes(db, ctx, crear=not args.sin_planes)
        preparar_matricula(db, ctx, args.monto_matricula,
                           tocar=not args.sin_matricula)

        if args.dry_run:
            simular(ctx, args.alumnos)
            return EXIT_OK

        if not args.si and not pedir_confirmacion(f"SEMBRAR {args.alumnos}"):
            print("no se toco nada.")
            return EXIT_NEGOCIO

        dist = repartir_cohortes(args.alumnos)
        indice = 0
        indice = ejecutar_nuevos(db, ctx, dist["nuevos"], indice, args.alumnos)
        indice = ejecutar_renovando(db, ctx, dist["renovando"], indice, args.alumnos)
        indice = ejecutar_trial(db, ctx, dist["trial"], indice, args.alumnos)
        indice = ejecutar_churned(db, ctx, dist["churned"], indice, args.alumnos)

        imprimir_resumen(ctx)
        problemas = verificar(db, ctx)
        if problemas:
            print("\n[!] El seed termino, pero la verificacion encontro diferencias.")
            return EXIT_NEGOCIO
        print(f"\n[OK] {len(ctx.creados)} alumnos creados por el flujo real.")
        return EXIT_OK
    except SeedError as error:
        db.rollback()
        print(f"\n[FATAL] {error}")
        return error.codigo
    except Exception as error:  # noqa: BLE001
        db.rollback()
        print(f"\n[ERROR] {type(error).__name__}: {error}")
        return EXIT_INESPERADO
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())











