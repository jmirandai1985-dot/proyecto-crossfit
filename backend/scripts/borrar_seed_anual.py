"""
Borrado del seed ANUAL (`seed_anual_prod.py`) — PROD o TEST, sin tocar nada real.

⚠️  BORRA FILAS. Sólo borra lo que lleva los marcadores del seed:
      * usuarios      → `correo LIKE 'demo.prod.anual.%@example.com'`
      * transacciones → `descripcion LIKE 'DEMOPRODANUAL%'`
      * clases        → `created_at = MARCA_TS` (y que se hayan quedado sin reservas ni
                        asistencias: si no, se dejan y se avisa, en vez de arrastrar
                        datos que no serían del seed)
    Nada más. Las clases REALES que el seed usó sólo se les RECALCULA el aforo
    (`asistentes_confirmados` = reservas vivas), que es exactamente lo que haría el
    paso 9 del mantenimiento: por eso, después de borrar, el paso 9 da 0.

──────────────────────────────────────────────────────────────────────────────
POR QUÉ EL ORDEN IMPORTA
──────────────────────────────────────────────────────────────────────────────
`asistencias`, `reservas` y `suscripciones` tienen FK a `usuarios` (ON DELETE CASCADE)
y `asistencias`/`reservas` tienen FK a `clases` (NO ACTION). El borrado va de la hoja al
tronco y el recálculo del aforo va JUSTO DESPUÉS de borrar las reservas (antes de borrar
las clases del seed, que ya no existen cuando termina):

    1. asistencias del seed             (usuario_id o clase_id del seed)
    2. reservas del seed                (alumno_id o clase_id del seed)
    3. aforo de las clases REALES       (= reservas vivas; lo mismo que el paso 9)
    4. transacciones del seed           (por descripcion)
    5. suscripciones del seed           (por usuario)
    6. usuarios del seed                (por correo; cascada: predictions_churn,
                                         student_segments, segmentacion_alumnos, …)
    7. clases del seed                  (sólo si quedaron vacías)

──────────────────────────────────────────────────────────────────────────────
USO (PowerShell, desde backend/)
──────────────────────────────────────────────────────────────────────────────
    $env:ENVIRONMENT="test";       python3.12 scripts\\borrar_seed_anual.py --destino test --dry-run
    $env:ENVIRONMENT="test";       python3.12 scripts\\borrar_seed_anual.py --destino test
    $env:ENVIRONMENT="production"; python3.12 scripts\\borrar_seed_anual.py --destino prod
⚠️ Hacerlo ANTES del día 1 del mes siguiente al seed (1/11/2026): ese día el paso 1 del
mantenimiento marcaría vencidas las suscripciones del seed y el run cortaría por
`MAX_VENCIDOS_PCT`. Borrar cualquier otro día es seguro.

`--limpiar-viejo` agrega el borrado del seed VIEJO (`seed_ml_data_prod.py`): sus 104
usuarios `demo.prod.N@example.com` y sus `DEMOPROD%`. Existe porque el LIKE del seed
viejo (`demo.prod.%`) también matchea al nuevo: borrar "los demo" sin distinguir se
llevaría los dos, así que el borrado del viejo pide una confirmación aparte.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections import defaultdict
from datetime import date
from typing import Optional, Sequence

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Los marcadores y los guards viven en el seed: UNA sola definición de qué es "el seed".
from seed_anual_prod import (  # noqa: E402
    DOMINIO_CORREO, MARCA_DESC, MARCA_TS, PREFIJO_CORREO, TENANT_ID, GuardError,
    mes_iso, preparar_entorno, pedir,
)
# Las cuentas del instituto son permanentes: este borrado masivo por patrón se NIEGA si
# su LIKE pudiera alcanzarlas (mismo guard que usan los otros scripts de limpieza).
from cuentas_instituto import (  # noqa: E402
    CuentaInstituto, abortar_si_patron_alcanza_instituto,
)

MES_ALERTA_LIMPIEZA = "2026-11"      # el run del 1/11 vencería las suscripciones del seed
PREFIJO_VIEJO = "demo.prod."         # seed viejo (`seed_ml_data_prod.py`)
MARCA_DESC_VIEJA = "DEMOPROD"        # descripcion del seed viejo ("DEMOPROD pago plan X")


# ══════════════════════════════════════════════════════════════════════════
#  PARTE PURA  (los tests la ejercitan sin base)
# ══════════════════════════════════════════════════════════════════════════
def pasos_borrado() -> tuple:
    """Orden de borrado por FKs (+ el recálculo del aforo, que va justo tras las reservas).

    Es una constante y no una lista suelta porque el orden ES el invariante: borrar
    `clases` antes que `reservas` choca con la FK (NO ACTION) y recalcular el aforo
    antes de borrar las reservas recalcula con las reservas del seed todavía ahí.
    """
    return ("asistencias", "reservas", "aforo_clases_reales", "transacciones",
            "suscripciones", "usuarios", "clases_seed")


def clases_a_resincronizar(reservas_seed: Sequence[dict],
                           clases_seed: set) -> set:
    """Clases que quedan con el aforo inflado por el seed (las REALES afectadas).

    De las reservas del seed, las que estaban en una clase del seed no dejan rastro
    (esa clase se borra entera). Las que estaban en clases REALES sí: su
    `asistentes_confirmados` se recalculó sumando nuestras reservas y hay que devolverlo
    a "reservas vivas".
    """
    return {r["clase_id"] for r in reservas_seed
            if r["clase_id"] is not None and r["clase_id"] not in clases_seed}


def aforo_final(vivas_reales: dict, afectadas: Sequence[int]) -> dict:
    """`{clase_id: asistentes_confirmados}` esperado tras el borrado.

    `vivas_reales` es el conteo de reservas VIVAS por clase que quedan en la base
    (sólo las reales). Es la misma definición que el paso 9 del mantenimiento: si el
    resultado no coincide, el paso 9 tendría algo que corregir.
    """
    return {cid: int(vivas_reales.get(cid, 0)) for cid in afectadas}


def resumen_borrado(conteos: dict) -> str:
    """Línea legible con los conteos del borrado."""
    return " · ".join(f"{k}={v}" for k, v in conteos.items())


def filtro_usuarios(incluir_viejo: bool = False) -> tuple:
    """`(WHERE, params)` de los correos demo a borrar: el anual, o también el viejo.

    El prefijo del seed anual (`demo.prod.anual.`) EMPIEZA con el del viejo
    (`demo.prod.`), así que el filtro ancho es el de `PROD_PERMITIDOS`
    (`demo.prod.%@example.com`) y el angosto es el que deja al seed viejo en paz. Es la
    decisión 4 (reemplazar el seed viejo) sin el pie de la barra: el LIKE ancho borra
    los dos, y por eso pide su propia confirmación (`--limpiar-viejo`).
    """
    if incluir_viejo:
        return "correo LIKE :demo", {"demo": f"{PREFIJO_VIEJO}%{DOMINIO_CORREO}"}
    return "correo LIKE :nuevo", {"nuevo": f"{PREFIJO_CORREO}%{DOMINIO_CORREO}"}


def filtro_transacciones(incluir_viejo: bool = False) -> tuple:
    """`(WHERE, params)` de las transacciones del seed (o de los dos seeds: `DEMOPROD%`).

    `MARCA_DESC` (`DEMOPRODANUAL`) empieza con `DEMOPROD`: el filtro ancho abarca los
    dos seeds y el angosto sólo el nuevo (el test lo verifica).
    """
    if incluir_viejo:
        return "descripcion LIKE :demo", {"demo": f"{MARCA_DESC_VIEJA}%"}
    return "descripcion LIKE :nuevo", {"nuevo": f"{MARCA_DESC}%"}


# ══════════════════════════════════════════════════════════════════════════
#  BASE: conteo, borrado (en UNA transacción) y verificación
# ══════════════════════════════════════════════════════════════════════════
def _sql_text():
    return importlib.import_module("sqlalchemy").text


def ids_del_seed(db, env: dict, tenant_id: int = TENANT_ID,
                 incluir_viejo: bool = False) -> dict:
    """Ids del seed presentes en la base (alumnos y clases)."""
    t = _sql_text()
    where, params = filtro_usuarios(incluir_viejo)
    return {
        "ids": [f[0] for f in db.execute(
            t(f"SELECT id FROM usuarios WHERE {where}"), params).fetchall()],
        "clases": [r[0] for r in db.query(env["Clase"].id).filter(
            env["Clase"].tenant_id == tenant_id,
            env["Clase"].created_at == MARCA_TS).all()],
    }


def _where_de_reserva(ids: Sequence[int], clases: Sequence[int]) -> tuple:
    """`(WHERE, params)` de "reservas del seed": por alumno o por clase del seed.

    Las condiciones son literales del código (nunca texto de afuera); los ids van por
    bind. Si no hay ids, el WHERE es `false` (no borra nada por accidente).
    """
    condiciones, params = [], {}
    if ids:
        condiciones.append("alumno_id = ANY(:ids)")
        params["ids"] = list(ids)
    if clases:
        condiciones.append("clase_id = ANY(:clases)")
        params["clases"] = list(clases)
    return (" OR ".join(condiciones) if condiciones else "false"), params


def contar_seed(db, env: dict, tenant_id: int = TENANT_ID,
                incluir_viejo: bool = False) -> dict:
    """Cuántas filas del seed hay (para el dry-run y para decidir si hay algo que hacer)."""
    t = _sql_text()
    base = ids_del_seed(db, env, tenant_id, incluir_viejo)
    where, params = _where_de_reserva(base["ids"], base["clases"])
    where_tx, params_tx = filtro_transacciones(incluir_viejo)
    return {
        "usuarios": len(base["ids"]),
        "clases_seed": len(base["clases"]),
        "reservas": db.execute(t(f"SELECT count(*) FROM reservas WHERE {where}"),
                               params).scalar() or 0,
        "asistencias": db.execute(t(
            f"SELECT count(*) FROM asistencias WHERE {where.replace('alumno_id', 'usuario_id')}"),
            params).scalar() or 0,
        "transacciones": db.execute(t(
            f"SELECT count(*) FROM transacciones_financieras WHERE {where_tx}"),
            params_tx).scalar() or 0,
        "suscripciones": db.execute(t(
            "SELECT count(*) FROM suscripciones WHERE usuario_id = ANY(:ids)"),
            {"ids": list(base["ids"]) or [0]}).scalar() or 0,
    }


def clases_reales_afectadas(db, ids: Sequence[int], clases: Sequence[int]) -> list:
    """Clases REALES con reservas del seed (las que hay que resincronizar al borrar)."""
    t = _sql_text()
    where, params = _where_de_reserva(ids, clases)
    filas = db.execute(t(f"SELECT id, clase_id FROM reservas WHERE {where}"), params).fetchall()
    return sorted(clases_a_resincronizar([{"clase_id": f[1]} for f in filas], set(clases)))


def borrar_en_transaccion(db, env: dict, tenant_id: int = TENANT_ID,
                          incluir_viejo: bool = False) -> dict:
    """Borra el seed completo y deja el aforo de las clases REALES como estaba.

    NO hace commit (lo hace quien llama): el seed la usa para reciclar en la MISMA
    transacción de la inserción, así "borrar y volver a sembrar" y "borrar a mano" son
    exactamente el mismo borrado. Orden: ver `pasos_borrado()`.
    `incluir_viejo`: además del seed anual, borra el seed VIEJO
    (`demo.prod.N@example.com` / `DEMOPROD%`) — decisión 4: el anual lo reemplaza.
    """
    t = _sql_text()
    base = ids_del_seed(db, env, tenant_id, incluir_viejo)
    ids, clases = base["ids"], base["clases"]
    where, params = _where_de_reserva(ids, clases)
    where_asist = where.replace("alumno_id", "usuario_id")
    where_usr, params_usr = filtro_usuarios(incluir_viejo)
    where_tx, params_tx = filtro_transacciones(incluir_viejo)
    afectadas = clases_reales_afectadas(db, ids, clases)

    conteos = {}
    # 1) asistencias (hoja: FK a usuarios y a clases)
    conteos["asistencias"] = db.execute(
        t(f"DELETE FROM asistencias WHERE {where_asist}"), params).rowcount
    # 2) reservas (antes de las clases: su FK es NO ACTION)
    conteos["reservas"] = db.execute(
        t(f"DELETE FROM reservas WHERE {where}"), params).rowcount
    # 3) aforo de las clases REALES = reservas vivas (lo que hace el paso 9 y lo que
    #    deshace el "+nuestras reservas" del seed). Justo acá: después de borrar las
    #    reservas y antes de borrar las clases del seed.
    conteos["aforo_clases_reales"] = 0
    if afectadas:
        conteos["aforo_clases_reales"] = db.execute(t(
            "UPDATE clases SET asistentes_confirmados = (SELECT count(*) FROM reservas r "
            " WHERE r.clase_id = clases.id "
            "   AND r.estado NOT IN ('cancelled', 'cancelada')), updated_at = now() "
            "WHERE id = ANY(:afectadas)"), {"afectadas": afectadas}).rowcount
    # 4) transacciones (sin FK a usuarios: se identifican por el marcador)
    conteos["transacciones"] = db.execute(t(
        f"DELETE FROM transacciones_financieras WHERE {where_tx}"), params_tx).rowcount
    # 5) suscripciones y 6) usuarios (cascada: predictions_churn, student_segments, …)
    conteos["suscripciones"] = db.execute(t(
        "DELETE FROM suscripciones WHERE usuario_id = ANY(:ids)"),
        {"ids": ids or [0]}).rowcount
    conteos["usuarios"] = db.execute(t(
        f"DELETE FROM usuarios WHERE {where_usr}"), params_usr).rowcount
    # 7) clases del seed: sólo si quedaron VACÍAS (si no, se dejan y la verificación avisa)
    conteos["clases_seed"] = db.execute(t(
        "DELETE FROM clases AS c WHERE c.id = ANY(:clases) "
        "AND NOT EXISTS (SELECT 1 FROM reservas r WHERE r.clase_id = c.id) "
        "AND NOT EXISTS (SELECT 1 FROM asistencias a WHERE a.clase_id = c.id)"),
        {"clases": clases or [0]}).rowcount
    conteos["aforo_recalculado"] = len(afectadas)
    return conteos


def verificar(db, env: dict, tenant_id: int = TENANT_ID,
              incluir_viejo: bool = False) -> bool:
    """Verificación posterior: 0 filas del seed, 0 huérfanas y el paso 9 en 0.

    El paso 9 se corre con el MISMO SQL del mantenimiento: si después de borrar diera
    distinto de 0, quedaría una clase con el aforo inflado (o desinflado) y el próximo
    run tendría un cambio para aplicar.
    """
    from seed_anual_prod import SQL_PASO_9
    t = _sql_text()
    restante = contar_seed(db, env, tenant_id, incluir_viejo)
    paso9 = db.execute(t(SQL_PASO_9)).scalar()
    huerfanas = db.execute(t(
        "SELECT count(*) FROM reservas r WHERE NOT EXISTS "
        "(SELECT 1 FROM clases c WHERE c.id = r.clase_id)")).scalar()
    huerfanas += db.execute(t(
        "SELECT count(*) FROM asistencias a WHERE a.clase_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM clases c WHERE c.id = a.clase_id)")).scalar()
    print("\n[verificación] después del borrado:")
    print(f"      restos del seed: {resumen_borrado(restante)}  (esperado todo 0)")
    print(f"      clases huérfanas (reservas/asistencias sin clase): {huerfanas}  (esperado 0)")
    print(f"      paso 9 del mantenimiento (aforo desincronizado)  : {paso9}  (esperado 0)")
    return (not any(restante.values())) and paso9 == 0 and huerfanas == 0


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════
def parsear_args(argv=None):
    """`--destino` OBLIGATORIO (igual que el seed): sin default no hay accidentes."""
    parser = argparse.ArgumentParser(
        description="Borra los datos del seed anual (sólo las filas marcadas).",
        epilog="Hacerlo antes del día 1 del mes siguiente al seed (1/11/2026).")
    parser.add_argument("--destino", choices=("prod", "test"), required=True,
                        help="prod = base real; test = rama de TEST (jamás PROD).")
    parser.add_argument("--dry-run", action="store_true",
                        help="cuenta y muestra qué borraría, sin borrar nada.")
    parser.add_argument("--limpiar-viejo", action="store_true",
                        help="borra TAMBIÉN el seed viejo (demo.prod.N@example.com / "
                             "DEMOPROD%): decisión 4, el seed anual lo reemplaza.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parsear_args(argv)
    print("=" * 74)
    print("  BORRADO DEL SEED ANUAL - sólo las filas marcadas")
    print("=" * 74)
    print(f"destino={args.destino.upper()}" + ("  [DRY-RUN]" if args.dry_run else ""))
    print(f"  usuarios      : correo LIKE '{PREFIJO_CORREO}%{DOMINIO_CORREO}'")
    print(f"  transacciones : descripcion LIKE '{MARCA_DESC}%'")
    print(f"  clases        : created_at = {MARCA_TS.isoformat()}")
    if mes_iso(date.today()) >= MES_ALERTA_LIMPIEZA:
        print("[nota] ya pasó el mes del seed: el mantenimiento pudo haber marcado sus "
              "suscripciones como vencidas. Es irrelevante para este borrado.")
    if args.destino == "prod":
        print(f"\n⚠️  Esto BORRA filas en la base de datos de PRODUCCIÓN.")
    if args.limpiar_viejo:
        print("⚠️  --limpiar-viejo: se borran TAMBIÉN los datos del seed viejo")
        print(f"     (usuarios 'demo.prod.%{DOMINIO_CORREO}' y transacciones "
              f"'{MARCA_DESC_VIEJA}%'), no sólo los del seed anual.")

    # ── GUARD: las cuentas del instituto no pueden caer en este borrado masivo ──
    # El filtro es un LIKE por prefijo + dominio (el del seed, y el del viejo si se pide
    # --limpiar-viejo): si alguno alcanzara demo.*@urbanbox.cl, se aborta.
    try:
        for prefijo in ((PREFIJO_CORREO, PREFIJO_VIEJO) if args.limpiar_viejo
                        else (PREFIJO_CORREO,)):
            abortar_si_patron_alcanza_instituto(prefijo, DOMINIO_CORREO,
                                                "borrar_seed_anual.py")
    except CuentaInstituto as e:
        print(f"[guard] ABORTADO: {e}")
        return 1

    # Se pide ANTES del dry-run y antes de cualquier borrado (igual que el seed).
    frase = "BORRAR SEED PROD" if args.destino == "prod" else "BORRAR SEED TEST"
    if not pedir(frase, f"\nEscribí '{frase}' para continuar: "):
        return 1
    if args.limpiar_viejo:
        if not pedir("TAMBIEN EL VIEJO",
                     "Confirma el borrado del seed viejo (escribe 'TAMBIEN EL VIEJO'): "):
            return 1
    if args.destino == "prod":
        print("[ok] confirmado: se opera contra PRODUCCIÓN.\n")

    try:
        env = preparar_entorno(args.destino)
    except GuardError as e:
        print(f"[guard] ABORTADO: {e}")
        return 1

    db = env["SessionLocal"]()
    try:
        conteos = contar_seed(db, env, incluir_viejo=args.limpiar_viejo)
        if not any(conteos.values()):
            print("\n[nada que borrar] no hay filas del seed en esta base.")
            return 0
        ids = ids_del_seed(db, env, incluir_viejo=args.limpiar_viejo)
        afectadas = clases_reales_afectadas(db, ids["ids"], ids["clases"])
        print(f"\n[encontrado] {resumen_borrado(conteos)}")
        print(f"[encontrado] clases REALES a las que se les recalcula el aforo: "
              f"{len(afectadas)}")

        if args.dry_run:
            print("\n[dry-run] no se borró nada. Para borrar de verdad: quita --dry-run.")
            return 0
        if not pedir("BORRAR", "\nEscribí 'BORRAR' para confirmar el borrado: "):
            return 1

        conteos = borrar_en_transaccion(db, env, incluir_viejo=args.limpiar_viejo)
        db.commit()
        print(f"\n[borrado] COMMIT OK -> {resumen_borrado(conteos)}")
        ok = verificar(db, env, incluir_viejo=args.limpiar_viejo)
    except Exception as e:      # noqa: BLE001  (se reporta y se revierte todo)
        db.rollback()
        print(f"[borrado] ERROR -> ROLLBACK (no se borró nada): {type(e).__name__}: {e}")
        return 1
    finally:
        db.close()

    print("\n" + "=" * 74)
    print("  RESULTADO:", "OK - seed borrado y verificado" if ok else "REVISAR - quedan restos")
    print("  Recuerda: los modelos de ML quedaron entrenados con datos que ya no están;")
    print("  si vas a usar la base sin el seed, reentrena (/ml/reentrenar) cuando toque.")
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
