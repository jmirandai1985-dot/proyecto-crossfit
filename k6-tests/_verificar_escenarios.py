#!/usr/bin/env python
"""Verifica en la BD que cada escenario k6 dejó el efecto que promete (SÓLO TEST).

Por qué existe
--------------
Los `check()` de k6 miran el **HTTP** (status, body). No ven si la transacción
quedó a medias, si el stock no volvió o si el check-in marcó la reserva
equivocada. Estos verificadores cierran ese hueco: se corren DESPUÉS del
escenario y leen la base para confirmar el estado de negocio.

Uso
---
    python k6-tests/_verificar_escenarios.py g1
    python k6-tests/_verificar_escenarios.py g3
    python k6-tests/_verificar_escenarios.py g6
    python k6-tests/_verificar_escenarios.py todos

    # (los mismos flags que el seed, por si se sembró en otro tenant/subdominio)
    python k6-tests/_verificar_escenarios.py g1 --alumnos 20

Salida: una línea `[ok]`/`[FALLO]` por chequeo + resumen. Código de salida 1 si
algún chequeo falló (sirve para encadenarlo en un .ps1/.sh), 2 si la BD no es TEST.

Estado: G1-G8 implementados. G6/G7/G8 leen las claves que el seed dejó en
load_config.json (pedido_voucher_*_id, clase_g7_id + reservas_g7,
solicitud_carrera_id, alumno_activar_id, alumno_rechazo_activacion): si el seed
es viejo, esos verificadores avisan que falta la clave en vez de fallar raro.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Importar el seed da el guard de TEST, el chdir al backend y el `sys.path`, así
# que el verificador no duplica esa lógica (ni puede apuntar a otra BD…salvo que
# alguien cambie el .env, cosa que el guard vuelve a chequear acá abajo).
from _seed_load_test import SANTIAGO, leer_json, resumen_bd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import is_test_db_url, settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402

FALLOS: list[str] = []
OKS = 0
FORMATO_CODIGO = re.compile(r"^[A-Z]{6}\d{3}$")

# En Windows, redirigir la salida a un archivo deja stdout en cp1252 y los '·', '→'
# y '—' de los mensajes romperían el print. Con utf-8 + errors='replace' el
# reporte se puede guardar con `> salida.txt` sin sorpresas.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── Helpers de reporte ────────────────────────────────────────────────────────
def info(msg: str) -> None:
    print(f"           · {msg}")


def check(nombre: str, ok: bool, detalle: str = "") -> bool:
    global OKS
    sufijo = f" — {detalle}" if detalle else ""
    if ok:
        OKS += 1
        print(f"  [ok]    {nombre}{sufijo}")
    else:
        FALLOS.append(nombre)
        print(f"  [FALLO] {nombre}{sufijo}")
    return ok


def seccion(titulo: str) -> None:
    print(f"\n{titulo}")


def filas(db, sql: str, **params) -> list:
    return list(db.execute(text(sql), params))


def escalar(db, sql: str, **params):
    return db.execute(text(sql), params).scalar()


# ── Carga de config ───────────────────────────────────────────────────────────
def cargar_config() -> dict:
    cfg = leer_json(Path(__file__).resolve().parent / "load_config.json")
    if not cfg.get("tenant_id"):
        print("ABORTADO: falta k6-tests/load_config.json (corré _seed_load_test.py)")
        raise SystemExit(2)
    return cfg


def cargar_tokens() -> list[dict]:
    datos = leer_json(Path(__file__).resolve().parent / "tokens.json")
    return datos if isinstance(datos, list) else []


# ── G1: check-in por QR ───────────────────────────────────────────────────────
def verificar_g1(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G1 — check-in por QR (POST /asistencia/qr/{public_id}/check-in)")
    clase_id = cfg.get("clase_qr_id")
    if not check("load_config.json trae clase_qr_id", bool(clase_id), str(clase_id)):
        return

    fila = db.execute(text("SELECT fecha FROM clases WHERE id = :c"),
                      {"c": clase_id}).first()
    if not check("la clase del QR existe", fila is not None, f"clase_id={clase_id}"):
        return

    hoy = datetime.now(SANTIAGO).date()
    check("la clase es de HOY (si no, el QR da 'sin_reserva')",
          fila[0] == hoy, f"fecha clase={fila[0]} · hoy={hoy}")

    total = escalar(db, "SELECT count(*) FROM reservas WHERE clase_id = :c",
                    c=clase_id)
    check("reservas de la clase == alumnos sembrados",
          total == cfg.get("n_alumnos"), f"{total} vs n_alumnos={cfg.get('n_alumnos')}")

    marcadas = filas(db, """
        SELECT alumno_id, asistencia_via, asistencia_marcada_at,
               asistencia_marcada_por
        FROM reservas
        WHERE clase_id = :c AND asistio
        ORDER BY alumno_id
    """, c=clase_id)
    check("al menos una reserva quedó marcada", len(marcadas) > 0,
          f"{len(marcadas)} de {total}")

    otra_via = [r[0] for r in marcadas if r[1] != "qr_alumno"]
    check("todas las marcadas tienen asistencia_via='qr_alumno'",
          not otra_via, f"alumnos con otra vía: {otra_via[:5]}")

    sin_fecha = [r[0] for r in marcadas if r[2] is None]
    check("todas las marcadas tienen asistencia_marcada_at",
          not sin_fecha, f"sin fecha: {sin_fecha[:5]}")

    # reservas.alumno_id apunta a usuarios.id, igual que asistencia_marcada_por
    # (asistencia.py:876): en un auto check-in tienen que coincidir.
    mal_autor = [r[0] for r in marcadas if r[3] != r[0]]
    check("asistencia_marcada_por == el alumno que escaneó (auto check-in)",
          not mal_autor, f"alumnos con otro autor: {mal_autor[:5]}")

    ids_tokens = {t["alumno_id"] for t in tokens}
    de_tokens = [r[0] for r in marcadas if r[0] in ids_tokens]
    check("marcó alumnos de tokens.json (los que usan los VUs)",
          bool(de_tokens), f"{len(de_tokens)}/{len(ids_tokens)}")
    info("si el run tuvo qr_429 (rate limit 30/min/IP), el resto queda sin "
         "marcar: es esperado, no un fallo")


# ── G2: WOD masivo ────────────────────────────────────────────────────────────
def verificar_g2(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G2 — WOD masivo (POST /wods/batch-create y POST /wods/)")
    tenant = cfg["tenant_id"]
    n = int(cfg.get("n_g2") or 10)  # el default vive en lib/config_flujos.js
    hoy = datetime.now(SANTIAGO).date()

    total = escalar(db, """
        SELECT count(*) FROM wods
        WHERE tenant_id = :t AND titulo LIKE 'K6 %'
    """, t=tenant)
    check("hay >= 5*N_G2 (batch) + N_G2 (simple) WODs del escenario",
          total >= 6 * n, f"{total} filas · esperado >= {6 * n}")

    fuera_draft = escalar(db, """
        SELECT count(*) FROM wods
        WHERE tenant_id = :t AND titulo LIKE 'K6 %' AND estado <> 'draft'
    """, t=tenant)
    check("todos los WODs del escenario quedaron en 'draft'",
          fuera_draft == 0, f"{fuera_draft} fuera de draft")

    desalineados = escalar(db, """
        SELECT count(*) FROM wods
        WHERE tenant_id = :t AND titulo LIKE 'K6 %'
          AND titulo <> 'K6 ' || to_char(fecha, 'YYYY-MM-DD')
    """, t=tenant)
    check("titulo == 'K6 ' || fecha (el payload se persistió completo)",
          desalineados == 0, f"{desalineados} filas desalineadas")

    vacios = escalar(db, """
        SELECT count(*) FROM wods
        WHERE tenant_id = :t AND titulo LIKE 'K6 %'
          AND (calentamiento IS NULL OR wod_principal IS NULL)
    """, t=tenant)
    check("todos traen calentamiento y wod_principal", vacios == 0,
          f"{vacios} vacíos")

    desde = hoy + timedelta(days=400 + 10)  # bloque del VU 1 (base = 400 + VU*10)
    hasta = desde + timedelta(days=4)
    presentes = escalar(db, """
        SELECT count(DISTINCT fecha) FROM wods
        WHERE tenant_id = :t AND titulo LIKE 'K6 %'
          AND fecha BETWEEN :a AND :b
    """, t=tenant, a=desde, b=hasta)
    check("el bloque de 5 fechas del VU 1 está completo (batch atómico)",
          presentes == 5, f"{presentes}/5 entre {desde} y {hasta}")


# ── G3: bazar, entrega por código + rechazo ───────────────────────────────────
def verificar_g3(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G3 — bazar: entrega por código + rechazo con devolución de stock")
    tenant = cfg["tenant_id"]
    codigo = cfg.get("pedido_codigo")

    entregado = db.execute(text("""
        SELECT id, estado, entregado_en, entregado_por
        FROM pedidos
        WHERE tenant_id = :t AND codigo_retiro = :c
    """), {"t": tenant, "c": codigo}).first()
    if check("existe el pedido del código de retiro", entregado is not None,
             f"codigo_retiro={codigo}"):
        check("quedó en estado 'entregado'", entregado[1] == "entregado",
              f"estado={entregado[1]}")
        check("entregado_en quedó seteado", entregado[2] is not None,
              str(entregado[2]))
        check("entregado_por == el admin que llamó (no el alumno)",
              entregado[3] == cfg.get("admin_id"),
              f"{entregado[3]} vs admin_id={cfg.get('admin_id')}")

    pendiente = db.execute(text("SELECT id, estado FROM pedidos WHERE id = :i"),
                           {"i": cfg.get("pedido_pendiente_id")}).first()
    if check("existe el pedido a rechazar", pendiente is not None,
             f"id={cfg.get('pedido_pendiente_id')}"):
        check("quedó en estado 'rechazado'", pendiente[1] == "rechazado",
              f"estado={pendiente[1]}")

    # Invariante de stock. El seed descuenta el stock de los 4 pedidos que inserta
    # (igual que hace la API al crear), así que en todo momento:
    #     stock + reservado_en_pedidos == stock_inicial - unidades_entregadas
    # Si el rechazo "devuelve" una unidad que nunca se descontó, esto se rompe.
    prod = cfg.get("product_id")
    stock = escalar(db, "SELECT stock FROM productos WHERE id = :p", p=prod)
    reservado = escalar(db, """
        SELECT COALESCE(SUM(cantidad), 0) FROM pedidos
        WHERE producto_id = :p AND estado IN ('pendiente', 'validado')
    """, p=prod)
    entregadas = escalar(db, """
        SELECT COALESCE(SUM(cantidad), 0) FROM pedidos
        WHERE producto_id = :p AND estado = 'entregado'
    """, p=prod)
    inicial = int(cfg.get("stock_inicial") or 100)
    check("stock + reservado == stock_inicial - entregado",
          stock + reservado == inicial - entregadas,
          f"stock={stock} + reservado={reservado} = {stock + reservado} · "
          f"esperado {inicial - entregadas}")

    pedidos = escalar(db, "SELECT count(*) FROM pedidos WHERE producto_id = :p",
                      p=prod)
    check("no aparecieron pedidos nuevos (el escenario no crea)",
          pedidos == 4, f"{pedidos} pedidos del producto {prod}")


# ── G4: embudo de referidos ───────────────────────────────────────────────────
def verificar_g4(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G4 — embudo de referidos (mi-codigo / mi-invitacion / invitaciones)")
    # tokens.json repite cada alumno en 3 grupos (alumno / vol / conc): el embudo
    # se valida sobre la lista base para no contar 3 veces al mismo usuario.
    base = [t for t in tokens if t.get("grupo") == "alumno"] or tokens
    ids = sorted({t["alumno_id"] for t in base})
    if not check("tokens.json trae alumnos del seed", bool(ids), f"{len(ids)}"):
        return

    codigos = filas(db, """
        SELECT usuario_id, codigo, activo
        FROM codigos_referido
        WHERE usuario_id = ANY(:ids)
    """, ids=ids)
    check("cada alumno del seed tiene su código de referido",
          len(codigos) == len(ids), f"{len(codigos)} vs {len(ids)} alumnos")
    inactivos = [r[1] for r in codigos if not r[2]]
    check("todos los códigos están activos", not inactivos, f"{inactivos[:5]}")
    invalidos = [r[1] for r in codigos if not FORMATO_CODIGO.match(r[1] or "")]
    check("los códigos respetan el formato del generador", not invalidos,
          f"fuera de formato: {invalidos[:5]}")

    invitaciones = filas(db, """
        SELECT estado, correo_prospecto, codigo_referido_id
        FROM invitaciones
        WHERE enviado_por_usuario_id = ANY(:ids)
        ORDER BY id DESC
    """, ids=ids)
    check("el POST de invitación escribió filas", len(invitaciones) > 0,
          f"{len(invitaciones)} invitaciones")
    sin_codigo = [r[1] for r in invitaciones if r[2] is None]
    check("cada invitación quedó ligada al código del invitador",
          not sin_codigo, f"sin codigo_referido_id: {sin_codigo[:5]}")
    ajenos = [r[1] for r in invitaciones if not (r[1] or "").startswith("k6-g4-")]
    check("los correos son los del escenario (k6-g4-*)", not ajenos,
          f"otros correos: {ajenos[:5]}")
    info("estados de invitación observados: "
         f"{sorted({str(r[0]) for r in invitaciones})}")

    # validar-codigo con el código PROPIO tiene que ser 400 y no escribir nada
    aplicados = escalar(db, """
        SELECT count(*) FROM referidos_aplicados
        WHERE usuario_invitador_id = ANY(:ids) OR usuario_invitado_id = ANY(:ids)
    """, ids=ids)
    check("validar el código propio no creó referidos_aplicados",
          aplicados == 0, f"{aplicados} filas")


# ── G6: admin aprueba / rechaza vouchers del bazar ────────────────────────────
def verificar_g6(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G6 — admin aprueba/rechaza vouchers (PUT estado · POST rechazar)")
    aprobar = cfg.get("pedido_voucher_aprobar_id")
    rechazar = cfg.get("pedido_voucher_rechazar_id")
    if not check("load_config.json trae pedido_voucher_aprobar_id y "
                 "pedido_voucher_rechazar_id",
                 bool(aprobar) and bool(rechazar),
                 f"aprobar={aprobar} · rechazar={rechazar}"):
        return

    fila = db.execute(text(
        "SELECT id, estado, codigo_retiro, total FROM pedidos WHERE id = :i"),
        {"i": aprobar}).first()
    if check("existe el pedido que se aprueba", fila is not None, f"id={aprobar}"):
        # Si la carrera dejara pasar dos VUs, el segundo 200 habría re-generado el
        # código: el estado sigue siendo 'validado' pero el código cambiaría. La
        # prueba dura de que ganó uno solo es el contador g6_aprobado_200<=1 de k6.
        check("quedó en 'validado' (la carrera la ganó un solo VU)",
              fila[1] == "validado", f"estado={fila[1]}")
        check("el código de retiro quedó generado", bool(fila[2]),
              f"codigo_retiro={fila[2]}")

    fila_r = db.execute(text("SELECT id, estado FROM pedidos WHERE id = :i"),
                        {"i": rechazar}).first()
    if check("existe el pedido que se rechaza", fila_r is not None,
             f"id={rechazar}"):
        check("quedó en 'rechazado'", fila_r[1] == "rechazado",
              f"estado={fila_r[1]}")

    # Mismo invariante que G3. Rechazar DEVUELVE la unidad (pedidos.py:585-596),
    # validar NO toca el stock: si la devolución no ocurriera, `stock + reservado`
    # quedaría uno por debajo de `stock_inicial - entregadas`.
    prod = cfg.get("product_id")
    stock = escalar(db, "SELECT stock FROM productos WHERE id = :p", p=prod)
    reservado = escalar(db, """
        SELECT COALESCE(SUM(cantidad), 0) FROM pedidos
        WHERE producto_id = :p AND estado IN ('pendiente', 'validado')
    """, p=prod)
    entregadas = escalar(db, """
        SELECT COALESCE(SUM(cantidad), 0) FROM pedidos
        WHERE producto_id = :p AND estado = 'entregado'
    """, p=prod)
    inicial = int(cfg.get("stock_inicial") or 100)
    check("stock + reservado == stock_inicial - entregado (el rechazo devolvió)",
          stock + reservado == inicial - entregadas,
          f"stock={stock} + reservado={reservado} = {stock + reservado} · "
          f"esperado {inicial - entregadas}")

    pedidos = escalar(db, "SELECT count(*) FROM pedidos WHERE producto_id = :p",
                      p=prod)
    check("no aparecieron pedidos nuevos (el escenario no crea ni duplica)",
          pedidos == 4, f"{pedidos} pedidos del producto {prod}")
    codigos = escalar(db, """
        SELECT count(*) FROM pedidos
        WHERE producto_id = :p AND codigo_retiro IS NOT NULL
    """, p=prod)
    info(f"pedidos con código de retiro: {codigos} (1 sembrado para G3 + 1 "
         "generado acá; más de 2 = validación duplicada)")


# ── G7: pestaña Asistencia del coach ──────────────────────────────────────────
def verificar_g7(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G7 — pestaña Asistencia del coach (confirmar batch + lecturas)")
    clase_id = cfg.get("clase_g7_id")
    esperadas = len(cfg.get("reservas_g7") or [])
    if not check("load_config.json trae clase_g7_id + reservas_g7",
                 bool(clase_id) and esperadas > 0,
                 f"clase={clase_id} · {esperadas} reservas"):
        return

    clase = db.execute(text("SELECT fecha, coach_id FROM clases WHERE id = :c"),
                       {"c": clase_id}).first()
    if not check("la clase G7 existe", clase is not None, f"clase_id={clase_id}"):
        return
    hoy = datetime.now(SANTIAGO).date()
    check("la clase es de HOY en Chile (si no, /confirmar da 403)",
          clase[0] == hoy, f"{clase[0]} vs {hoy}")
    check("la clase es del coach del token", clase[1] == cfg.get("coach_id"),
          f"coach de la clase={clase[1]} · config={cfg.get('coach_id')}")

    reservas = filas(db, """
        SELECT id, asistio, asistencia_via, asistencia_marcada_por,
               asistencia_marcada_at
        FROM reservas
        WHERE clase_id = :c AND estado <> 'cancelada'
        ORDER BY id
    """, c=clase_id)
    check("la clase tiene las reservas sembradas", len(reservas) == esperadas,
          f"{len(reservas)} vs {esperadas}")

    sin_marcar = [r[0] for r in reservas if not r[1]]
    check("todas quedaron con asistio=True (el batch cubrió la clase)",
          not sin_marcar, f"sin marcar: {sin_marcar[:5]}")

    vias = sorted({str(r[2]) for r in reservas})
    check("asistencia_via='batch' (viene del Confirmar, no del QR del alumno)",
          vias == ["batch"], f"vías encontradas: {vias}")

    otro_autor = [r[0] for r in reservas if r[3] != cfg.get("coach_id")]
    check("asistencia_marcada_por == el coach del token", not otro_autor,
          f"otro autor: {otro_autor[:5]}")

    sin_fecha = [r[0] for r in reservas if r[4] is None]
    check("asistencia_marcada_at quedó seteado", not sin_fecha,
          f"sin fecha: {sin_fecha[:5]}")

    # La clase del QR (G1) es OTRA a propósito: si el escenario hubiera reusado esa
    # clase, `confirmar` habría pisado `asistencia_via='qr_alumno'` y G1 fallaría.
    qr = cfg.get("clase_qr_id")
    if qr and qr != clase_id:
        pisadas = escalar(db, """
            SELECT count(*) FROM reservas
            WHERE clase_id = :c AND asistencia_via = 'batch'
        """, c=qr)
        check("la clase del QR no recibió marcas 'batch' (clases separadas)",
              pisadas == 0, f"{pisadas} reservas pisadas")


# ── G8: cola de activación (carrera + activar + rechazar) ────────────────────
def verificar_g8(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G8 — cola de activación (aprobar en carrera · activar · rechazar)")
    sid = cfg.get("solicitud_carrera_id")
    alumno_ok = cfg.get("alumno_activar_id")
    alumno_no = cfg.get("alumno_rechazo_activacion")
    if not check("load_config.json trae solicitud_carrera_id + los dos alumnos",
                 bool(sid) and bool(alumno_ok) and bool(alumno_no),
                 f"solicitud={sid} · activar={alumno_ok} · rechazar={alumno_no}"):
        return

    sol = db.execute(text("""
        SELECT estado, alumno_id, aprobado_por, plan_id
        FROM solicitudes_planes WHERE id = :i
    """), {"i": sid}).first()
    if check("existe la solicitud de la carrera", sol is not None, f"id={sid}"):
        check("quedó 'approved' (uno solo ganó la carrera)",
              sol[0] == "approved", f"estado={sol[0]}")
        check("aprobado_por == el admin del token (no el alumno)",
              sol[2] == cfg.get("admin_id"),
              f"{sol[2]} vs admin_id={cfg.get('admin_id')}")
        # El UPDATE atómico (solicitudes_planes.py:346-364) sólo deja pasar a uno:
        # si el filtro `estado='pending'` se cayera, acá habría 2 suscripciones.
        nuevas = escalar(db, """
            SELECT count(*) FROM suscripciones
            WHERE usuario_id = :u AND tenant_id = :t AND plan_id = :p
              AND fecha_inicio > now() - interval '1 day'
        """, u=sol[1], t=cfg["tenant_id"], p=sol[3])
        check("la aprobación creó UNA sola suscripción (no hubo doble proceso)",
              nuevas <= 1, f"{nuevas} suscripciones nuevas del plan {sol[3]}")
        avisos = escalar(db, """
            SELECT count(*) FROM notificaciones
            WHERE alumno_id = :u AND tipo = 'aprobado'
        """, u=sol[1])
        check("una sola notificación 'aprobado' para el alumno", avisos <= 1,
              f"{avisos} notificaciones")
        activas = escalar(db, """
            SELECT count(*) FROM suscripciones
            WHERE usuario_id = :u AND tenant_id = :t AND estado = 'activo'
        """, u=sol[1], t=cfg["tenant_id"])
        info(f"suscripciones activas del alumno {sol[1]}: {activas}")

    act = db.execute(text("""
        SELECT estado, activo, cambiar_password_al_login
        FROM usuarios WHERE id = :i
    """), {"i": alumno_ok}).first()
    if check("existe el alumno a activar", act is not None, f"id={alumno_ok}"):
        check("quedó estado='activo' y activo=True",
              act[0] == "activo" and bool(act[1]),
              f"estado={act[0]} activo={act[1]}")
        check("se le marcó cambiar_password_al_login (password provisional)",
              bool(act[2]), f"cambiar_password_al_login={act[2]}")
        audit = escalar(db, """
            SELECT count(*) FROM auditoria
            WHERE entidad = 'usuario' AND entidad_id = :i
              AND accion = 'UPDATE' AND detalle->>'estado' = 'activo'
        """, i=alumno_ok)
        check("la activación dejó UNA fila de auditoría", audit <= 1,
              f"{audit} filas UPDATE/usuario para {alumno_ok}")

    rec = db.execute(text("SELECT estado, activo FROM usuarios WHERE id = :i"),
                     {"i": alumno_no}).first()
    if check("existe el alumno a rechazar", rec is not None, f"id={alumno_no}"):
        # ⚠️ Documentado: /rechazar NO tiene guarda de estado (alumnos.py:513-529),
        # así que esto pasa incluso si el alumno no estaba pendiente.
        check("quedó estado='rechazado' y activo=False",
              rec[0] == "rechazado" and not rec[1],
              f"estado={rec[0]} activo={rec[1]}")


# ── G5: panel admin (sólo lectura) ────────────────────────────────────────────
def verificar_g5(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G5 — panel admin / BI (sólo lecturas: no hay estado que verificar)")
    tenant = cfg["tenant_id"]
    churn = escalar(db, "SELECT count(*) FROM predictions_churn WHERE tenant_id = :t",
                    t=tenant)
    info(f"predictions_churn del tenant {tenant}: {churn} filas "
         "(si son 0, /kpis/churn no encola ningún recálculo)")
    info("acá lo que manda son los counters y thresholds de k6: "
         "panel_5xx==0, panel_otros==0 y las duraciones de línea base")


VERIFICADORES = {
    "g1": verificar_g1,
    "g2": verificar_g2,
    "g3": verificar_g3,
    "g4": verificar_g4,
    "g5": verificar_g5,
    "g6": verificar_g6,
    "g7": verificar_g7,
    "g8": verificar_g8,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verifica en la BD el efecto de cada escenario k6 (SÓLO TEST).")
    parser.add_argument("escenario", nargs="?", default="todos",
                        choices=[*VERIFICADORES, "todos"],
                        help="qué escenario verificar (default: todos)")
    args = parser.parse_args()

    if not is_test_db_url(settings.DATABASE_URL):
        print(f"ABORTADO: DATABASE_URL NO es de TEST → {resumen_bd()}")
        return 2

    print("=" * 78)
    print("VERIFICACIÓN DE ESCENARIOS k6 — SÓLO BD DE TEST")
    print("=" * 78)
    print(f"BD: {resumen_bd()}  (TEST confirmado)")

    cfg = cargar_config()
    tokens = cargar_tokens()
    nombres = list(VERIFICADORES) if args.escenario == "todos" else [args.escenario]

    with SessionLocal() as db:
        for nombre in nombres:
            fallos_antes = len(FALLOS)
            VERIFICADORES[nombre](db, cfg, tokens)
            if len(FALLOS) == fallos_antes:
                print(f"  → {nombre.upper()}: OK")

    print("\n" + "=" * 78)
    if FALLOS:
        print(f"RESULTADO: {OKS} ok · {len(FALLOS)} FALLOS")
        for nombre in FALLOS:
            print(f"  x {nombre}")
        return 1
    print(f"RESULTADO: {OKS} ok · 0 fallos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
