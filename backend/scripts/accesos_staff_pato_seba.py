"""Accesos STAFF para Pato Pérez y Sebastián Medina — 3 roles por persona.

QUÉ HACE
--------
Deja TRES accesos por persona en el box (`TENANT_ID = 1`):

    Pato     admin (correo real) + alumno (alias) + coach (alias)
    Sebastián admin (correo real) + alumno (alias) + coach (alias)

* Pato ya existe como ALUMNO con su correo real: acá se le cambia el rol a
  ADMINISTRADOR y se le fija una contraseña provisional.
* Los alias de alumno/coach se crean con `+alumno` / `+coach` sobre el correo real
  (Gmail los entrega en la misma bandeja; no inventamos un dominio que no existe).
* Los dos alumnos quedan con una suscripción ACTIVA a un plan INTERNO ilimitado
  (`es_comercial=False`, `activo=False`): da acceso completo, no aparece en el catálogo
  y NO suma MRR/“alumnos vigentes” (no son clientes que pagaron).
* `cambiar_password_al_login=True` en las 6: al entrar, el sistema les exige cambiarla.

CERO CORREOS
------------
Este script NO importa `email_service` ni llama a `send_*`: replica el alta directa
(Usuario + Suscripción + código de referido) sin el envío que hace el endpoint. El
endpoint normal NO se modifica; esto es una operación puntual de aprovisionamiento.

GUARDAS (falla CERRADO)
-----------------------
1. `--destino prod` es OBLIGATORIO (no hay default) y solo acepta `prod`.
2. `ENVIRONMENT=production` y la URL tienen que ser de la rama PROD actual;
   se rechazan TEST y los PROD retirados.
3. Escribir exige `--aplicar` + `--confirmar "SI QUIERO PROD"`. Sin `--aplicar` es
   dry-run: muestra qué haría y no genera contraseñas ni escribe.
4. Idempotente por `(tenant_id, correo)`: si la cuenta ya existe, actualiza rol/clave;
   no duplica usuarios, suscripciones ni el plan interno.
5. Las contraseñas se generan con `secrets` en cada ejecución y NO viven en el repo.

USO
---
    cd backend
    $env:ENVIRONMENT="production"
    py -3.12 scripts/accesos_staff_pato_seba.py --destino prod
    py -3.12 scripts/accesos_staff_pato_seba.py --destino prod --aplicar `
        --confirmar "SI QUIERO PROD"

Al aplicar imprime el informe final (correo + rol + contraseña) para entregar en mano.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# El script vive en `backend/scripts/`: agregar `backend/` al path ANTES de importar
# la app (si no, `import app` falla al correrlo desde esa carpeta).
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

TENANT_ID = 1
PLAN_STAFF_NOMBRE = "Staff ilimitado (interno)"
PLAN_STAFF_DIAS = 3650          # 10 años: acceso de staff, sin renovaciones anuales

# Alfabeto sin caracteres ambiguos (0/O, 1/l/I): la clave se dicta en persona.
ALFABETO_PASSWORD = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
PREFIJO_PASSWORD = "UTB-"
LARGO_PASSWORD = 12
FRASE_CONFIRMACION = "SI QUIERO PROD"


@dataclass(frozen=True)
class Cuenta:
    persona: str
    rol: str
    correo: str
    nombre: str | None = None
    rut: str | None = None
    existente: bool = False


# Orden EXACTO del informe: persona -> admin, alumno, coach.
CUENTAS: tuple[Cuenta, ...] = (
    Cuenta("Pato", "administrador", "perez.patricio89@gmail.com",
           existente=True),
    Cuenta("Pato", "alumno", "perez.patricio89+alumno@gmail.com",
           nombre="Pato Pérez (Alumno)", rut="STF-PATO-AL"),
    Cuenta("Pato", "coach", "perez.patricio89+coach@gmail.com",
           nombre="Pato Pérez (Coach)", rut="STF-PATO-CO"),
    Cuenta("Seba", "administrador", "sebamedina2022@gmail.com",
           nombre="Sebastián Medina (Admin)", rut="STF-SEBA-AD"),
    Cuenta("Seba", "alumno", "sebamedina2022+alumno@gmail.com",
           nombre="Sebastián Medina (Alumno)", rut="STF-SEBA-AL"),
    Cuenta("Seba", "coach", "sebamedina2022+coach@gmail.com",
           nombre="Sebastián Medina (Coach)", rut="STF-SEBA-CO"),
)


def generar_password() -> str:
    """Clave provisional fuerte y legible (sin caracteres ambiguos)."""
    cuerpo = "".join(secrets.choice(ALFABETO_PASSWORD)
                     for _ in range(LARGO_PASSWORD))
    return f"{PREFIJO_PASSWORD}{cuerpo}"


def validar_destino(url: str, entorno: str, prod_id: str,
                    test_ids: tuple[str, ...],
                    retirados: tuple[str, ...] = ()) -> str | None:
    """Motivo por el que la URL NO es PROD, o `None` si es la rama correcta.

    Función pura (se prueba sin BD): falla cerrado ante URL vacía, TEST, un PROD
    retirado o cualquier endpoint distinto del PROD actual.
    """
    if str(entorno or "").strip().lower() != "production":
        return "ENVIRONMENT tiene que ser 'production' (no TEST)"
    u = str(url or "")
    if not u:
        return "la URL de la base está vacía"
    if any(branch in u for branch in retirados):
        return "la URL apunta a un PROD retirado (datos reales): corrige el .env"
    if any(branch in u for branch in test_ids):
        return "la URL apunta a TEST: este script es solo para PROD"
    if prod_id not in u:
        return f"la URL no es la rama PROD actual ({prod_id})"
    return None


def plan_de_cuentas() -> list[tuple[str, str, str]]:
    """(persona, rol, correo) en el orden del informe; pura y testeable."""
    return [(c.persona, c.rol, c.correo) for c in CUENTAS]


def resumen_por_persona() -> dict[str, list[str]]:
    """{persona: [roles en orden]}: Pato/Seba tienen que tener los 3 roles."""
    salida: dict[str, list[str]] = {}
    for cuenta in CUENTAS:
        salida.setdefault(cuenta.persona, []).append(cuenta.rol)
    return salida


from app.core.config import (                                          # noqa: E402
    ENDPOINTS_RETIRADOS, PROD_BRANCH_ID, TEST_BRANCH_IDS, settings,
)
from app.core.security import get_password_hash                       # noqa: E402
from app.db.database import SessionLocal                              # noqa: E402
from app.models.plan import Plan                                      # noqa: E402
# Importar `Pago` (aunque el script no lo use) para que el mapper resuelva la FK
# `suscripciones.pago_id -> pagos.id`; sin esto SQLAlchemy falla al crear la sesión.
from app.models.pago import Pago                                      # noqa: E402,F401
from app.models.suscripcion import EstadoSuscripcion, Suscripcion     # noqa: E402
from app.models.usuario import RolUsuario, Usuario                    # noqa: E402
from app.services.referidos_service import asignar_codigo_referido    # noqa: E402


def _usuario_por_correo(db, correo: str):
    return (db.query(Usuario)
            .filter(Usuario.tenant_id == TENANT_ID, Usuario.correo == correo)
            .first())


def _plan_staff(db):
    """El plan interno ilimitado (se crea una sola vez)."""
    plan = (db.query(Plan)
            .filter(Plan.tenant_id == TENANT_ID, Plan.nombre == PLAN_STAFF_NOMBRE)
            .first())
    creado = False
    if plan is None:
        plan = Plan(
            tenant_id=TENANT_ID,
            nombre=PLAN_STAFF_NOMBRE,
            creditos=0,                    # los ilimitados de PROD usan 0 + flag
            es_ilimitado=True,
            genero=None,
            es_estudiante=False,
            requiere_certificado_estudiante=False,
            precio_clp=0,                  # interno: no es una venta
            duracion_dias=PLAN_STAFF_DIAS,
            activo=False,                  # no aparece en el catálogo de compra
            es_comercial=False,            # no suma MRR/retención/“alumnos vigentes”
        )
        db.add(plan)
        db.flush()
        creado = True
    else:
        # Re-ejecución: el plan interno conserva SUS invariantes (ilimitado,
        # no comercial, fuera del catálogo), aunque alguien lo haya editado.
        plan.creditos = 0
        plan.es_ilimitado = True
        plan.es_comercial = False
        plan.precio_clp = 0
        plan.activo = False
        plan.duracion_dias = PLAN_STAFF_DIAS
    return plan, creado


def _suscripcion_staff_vigente(db, usuario, plan, ahora):
    return (db.query(Suscripcion)
            .filter(
                Suscripcion.tenant_id == TENANT_ID,
                Suscripcion.usuario_id == usuario.id,
                Suscripcion.plan_id == plan.id,
                Suscripcion.estado == EstadoSuscripcion.activo,
                Suscripcion.fecha_expiracion > ahora,
            )
            .first())


def _asegurar_suscripcion_staff(db, usuario, plan, ahora) -> bool:
    """True si creó la suscripción; False si ya había una vigente (idempotente)."""
    if _suscripcion_staff_vigente(db, usuario, plan, ahora) is not None:
        return False
    db.add(Suscripcion(
        tenant_id=TENANT_ID,
        usuario_id=usuario.id,
        plan_id=plan.id,
        estado=EstadoSuscripcion.activo,
        # NULL = ilimitado (misma convención que los planes ∞ de PROD).
        creditos_totales=None,
        creditos_disponibles=None,
        fecha_inicio=ahora,
        fecha_expiracion=ahora + timedelta(days=PLAN_STAFF_DIAS),
    ))
    db.flush()
    return True


def _aplicar_cuenta(db, cuenta: Cuenta, plan, ahora, password: str):
    """Crea/actualiza UNA cuenta. Devuelve (usuario, accion, suscripcion_creada)."""
    usuario = _usuario_por_correo(db, cuenta.correo)
    accion = "actualizada"
    if usuario is None:
        if not cuenta.nombre or not cuenta.rut:
            raise ValueError(f"{cuenta.correo}: falta nombre/rut de alta")
        usuario = Usuario(
            tenant_id=TENANT_ID,
            rut=cuenta.rut,
            nombre=cuenta.nombre,
            correo=cuenta.correo,
            password_hash=get_password_hash(password),
            rol=RolUsuario(cuenta.rol),
            activo=True,
            estado="activo",
            cambiar_password_al_login=True,
        )
        db.add(usuario)
        db.flush()
        accion = "creada"
    else:
        usuario.rol = RolUsuario(cuenta.rol)
        usuario.password_hash = get_password_hash(password)
        usuario.activo = True
        usuario.estado = "activo"
        usuario.cambiar_password_al_login = True

    # Alumno: código de referido + suscripción ilimitada (misma lógica que el
    # alta normal, SIN el correo). `asignar_codigo_referido` es idempotente.
    suscripcion_creada = False
    if cuenta.rol == "alumno":
        asignar_codigo_referido(db, usuario)
        suscripcion_creada = _asegurar_suscripcion_staff(db, usuario, plan, ahora)
    return usuario, accion, suscripcion_creada


def _verificar(db, plan, ahora) -> list[str]:
    """Comprueba el estado FINAL (rol + suscripción de los alumnos)."""
    problemas = []
    for cuenta in CUENTAS:
        usuario = _usuario_por_correo(db, cuenta.correo)
        if usuario is None:
            problemas.append(f"{cuenta.correo}: no existe")
            continue
        rol = usuario.rol.value if hasattr(usuario.rol, "value") else str(usuario.rol)
        if rol != cuenta.rol:
            problemas.append(f"{cuenta.correo}: rol {rol} != {cuenta.rol}")
        if usuario.estado != "activo" or not usuario.activo:
            problemas.append(f"{cuenta.correo}: no quedó activo")
        if cuenta.rol == "alumno" and _suscripcion_staff_vigente(
                db, usuario, plan, ahora) is None:
            problemas.append(f"{cuenta.correo}: sin suscripción ilimitada vigente")
    return problemas


def parsear_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Crea/actualiza los 3 accesos (admin/alumno/coach) de Pato y Seba.")
    parser.add_argument("--destino", required=True, choices=("prod",),
                        help="OBLIGATORIO: prod (este script no toca TEST)")
    parser.add_argument("--aplicar", action="store_true",
                        help="Escribe en la base (sin esto es dry-run)")
    parser.add_argument("--confirmar", default="",
                        help=f'Frase exacta para escribir: "{FRASE_CONFIRMACION}"')
    return parser.parse_args(argv)


def _validar_guardas() -> None:
    """Aborta si el entorno/URL no son PROD. Imprime solo el branch, nunca la URL."""
    urls = [u for u in (settings.DATABASE_URL, settings.DIRECT_URL) if u]
    if not urls:
        raise SystemExit("[abort] no hay DATABASE_URL/DIRECT_URL configurada")
    for url in urls:
        motivo = validar_destino(
            url, os.getenv("ENVIRONMENT", ""), PROD_BRANCH_ID,
            TEST_BRANCH_IDS, ENDPOINTS_RETIRADOS)
        if motivo:
            raise SystemExit(f"[abort] {motivo}")
    print(f"[guard] ENVIRONMENT=production | branch={PROD_BRANCH_ID} | "
          f"destino=prod | EMAIL_MODO={settings.EMAIL_MODO!r} "
          f"(este script NO envía correos)")


def _imprimir_dry_run(db) -> None:
    print("\n" + "=" * 78)
    print("  DRY-RUN — estado actual (no se escribe nada)")
    print("=" * 78)
    for cuenta in CUENTAS:
        usuario = _usuario_por_correo(db, cuenta.correo)
        if usuario is None:
            estado = "NO EXISTE -> se crea"
        else:
            rol = usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
            estado = f"existe (rol={rol}) -> se fija {cuenta.rol}"
        print(f"  {cuenta.persona:5} | {cuenta.rol:14} | {cuenta.correo:44} | {estado}")
    print("\n[dry-run] no se generaron contraseñas ni se escribió nada. "
          f'Para aplicar: --aplicar --confirmar "{FRASE_CONFIRMACION}"')


def _imprimir_informe(filas) -> None:
    print("\n" + "=" * 100)
    print("  ACCESOS LISTOS — entrega en mano (no se envió ningún correo)")
    print("=" * 100)
    print(f"  {'PERSONA':7} {'ROL':15} {'CORREO':44} {'CONTRASEÑA':18} {'ID':>5}")
    print("  " + "-" * 96)
    for persona, rol, correo, password, usuario_id in filas:
        print(f"  {persona:7} {rol:15} {correo:44} {password:18} {usuario_id:>5}")
    print("=" * 100)
    print("  Alumnos: suscripción ACTIVA al plan interno ilimitado "
          f"'{PLAN_STAFF_NOMBRE}'.")
    print("  Ese plan no es comercial (no suma MRR) y no aparece en el catálogo.")
    print("  Las 6 cuentas tienen cambiar_password_al_login=True: la clave se "
          "cambia al primer ingreso.")


def main(argv=None) -> int:
    args = parsear_args(argv)
    _validar_guardas()

    db = SessionLocal()
    try:
        if not args.aplicar:
            _imprimir_dry_run(db)
            return 0

        if args.confirmar.strip().upper() != FRASE_CONFIRMACION:
            print(f'[abort] falta --confirmar "{FRASE_CONFIRMACION}" exacto.')
            return 2

        # Contraseñas SOLO en memoria; se imprimen una vez al final.
        passwords = {cuenta.correo: generar_password() for cuenta in CUENTAS}
        ahora = datetime.now(timezone.utc)

        try:
            plan, plan_creado = _plan_staff(db)
            filas = []
            for cuenta in CUENTAS:
                usuario, accion, sub_creada = _aplicar_cuenta(
                    db, cuenta, plan, ahora, passwords[cuenta.correo])
                filas.append((cuenta, usuario, accion, sub_creada))
            db.commit()
        except Exception as e:  # noqa: BLE001 — una transacción, rollback total
            db.rollback()
            print(f"\n[ERROR] rollback: no se escribió nada: {e}")
            return 1

        problemas = _verificar(db, plan, ahora)
        if problemas:
            print("\n[verify] PROBLEMAS:")
            for p in problemas:
                print(f"  - {p}")
            return 1

        print(f"[ok] plan interno {'creado' if plan_creado else 'reutilizado'} "
              f"(id={plan.id})")
        for cuenta, usuario, accion, sub_creada in filas:
            extra = " + suscripción ilimitada" if sub_creada else ""
            print(f"[ok] {cuenta.correo}: {accion} como {cuenta.rol}{extra}")

        filas_informe = []
        for cuenta in CUENTAS:
            usuario = _usuario_por_correo(db, cuenta.correo)
            filas_informe.append((cuenta.persona, cuenta.rol, cuenta.correo,
                                  passwords[cuenta.correo], usuario.id))
        _imprimir_informe(filas_informe)
        print("\n[verify] 6/6 cuentas con el rol esperado y los alumnos con plan "
              "ilimitado vigente.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

