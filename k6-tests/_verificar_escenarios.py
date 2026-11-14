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

Estado: G1-G14 implementados. G6/G7/G8 leen las claves que el seed dejó en
load_config.json (pedido_voucher_*_id, clase_g7_id + reservas_g7,
solicitud_carrera_id, alumno_activar_id, alumno_rechazo_activacion): si el seed
es viejo, esos verificadores avisan que falta la clave en vez de fallar raro.
G9-G14 leen las claves de §10 del documento (alumno_g9, mp_webhook_*,
correos_g10, invitador_g11/invitados_g11, candidatos_g12, alumnos_g13,
alumnos_g14) y comparan la aritmética con las MISMAS funciones del backend
(`referidos_service.calcular_descuento_clp`, `tramos_referidos_service.umbral_mas_alto`).
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
# Las mismas funciones que usa el backend para la aritmética (no una copia):
# el % del descuento y el tramo alcanzado se comparan con la MISMA regla.
from app.services import referidos_service as referidos_svc  # noqa: E402
from app.services import tramos_referidos_service as tramos_svc  # noqa: E402

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
        print("ABORTADO: falta k6-tests/load_config.json (corre _seed_load_test.py)")
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


# ── G9: Mercado Pago (checkout recurrente + webhook) ─────────────────────────
def verificar_g9(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G9 — Mercado Pago: /pagos/suscripcion en carrera + webhook firmado")
    alumno = cfg.get("alumno_g9") or {}
    alumno_id = alumno.get("alumno_id")
    n = int(cfg.get("n_g9") or 5)
    if not check("load_config.json trae alumno_g9", bool(alumno_id), str(alumno)):
        return

    # La fila sembrada NO tiene mp_preapproval_id (el seed inserta directo): las
    # que sí lo tienen las creó el escenario. Con N VUs sobre el MISMO alumno y
    # el MISMO plan, lo correcto es UNA sola autorización recurrente.
    filas_pre = filas(db, """
        SELECT id, estado::text, plan_id, mp_preapproval_id, mp_estado,
               fecha_inicio
        FROM suscripciones
        WHERE usuario_id = :u AND mp_preapproval_id IS NOT NULL
        ORDER BY id
    """, u=alumno_id)
    ids = [r[0] for r in filas_pre]
    check(f"la carrera dejó UNA autorización recurrente (no {n})",
          len(filas_pre) == 1, f"{len(filas_pre)} suscripciones con preapproval: {ids}")
    for fila in filas_pre:
        info(f"suscripción {fila[0]}: estado={fila[1]} plan={fila[2]} "
             f"preapproval={fila[3]} mp_estado={fila[4]}")
    pendientes = [r for r in filas_pre if r[1] == "pendiente"]
    check("la autorización nace 'pendiente' (no da acceso todavía)",
          len(pendientes) == len(filas_pre),
          f"{len(pendientes)} pendientes de {len(filas_pre)}")

    notif = cfg.get("mp_webhook_notificacion_id")
    if not check("load_config.json trae mp_webhook_notificacion_id",
                 bool(notif), str(notif)):
        return
    eventos = filas(db, """
        SELECT id, tipo, recurso_id, firma_valida, resultado, procesado_en
        FROM pagos_eventos WHERE notificacion_id = :n ORDER BY id
    """, n=notif)
    check("los 3 reintentos del MISMO aviso dejaron UN solo evento",
          len(eventos) == 1, f"{len(eventos)} filas en pagos_eventos para {notif}")
    if eventos:
        ev = eventos[0]
        check("la firma HMAC fue aceptada (firma_valida=true)", bool(ev[3]),
              f"firma_valida={ev[3]} resultado={ev[4]}")
        check("el resultado NO es 'firma_invalida'", ev[4] != "firma_invalida",
              f"resultado={ev[4]}")
        info(f"evento {ev[0]}: tipo={ev[1]} recurso={ev[2]} "
             f"procesado_en={ev[5]}")

    # El webhook NUNCA crea un cobro nuevo: la plata se aplica sobre una fila
    # de `pagos` que ya existe (por `external_reference`). El pago de MP usado
    # en el aviso no es de este box, así que no debe haber fila ni cobro.
    pago_mp = cfg.get("mp_webhook_payment_id")
    if pago_mp:
        cobros = escalar(db, "SELECT count(*) FROM pagos WHERE payment_id = :p",
                         p=str(pago_mp))
        check("el webhook no creó ni cobró dos veces un pago", cobros == 0,
              f"{cobros} filas en pagos con payment_id={pago_mp}")


# ── G10: alumno nuevo end-to-end ──────────────────────────────────────────────
def verificar_g10(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G10 — alumno nuevo end-to-end (alta + correo + plan Prueba)")
    tenant = cfg["tenant_id"]
    correos = cfg.get("correos_g10") or []
    if not check("load_config.json trae correos_g10", bool(correos),
                 f"{len(correos)} correos"):
        return

    creados, sin_prueba, sin_correo, mal_duracion = [], [], [], []
    for correo in correos:
        usuario = db.execute(text("""
            SELECT id, estado, activo, cambiar_password_al_login
            FROM usuarios WHERE tenant_id = :t AND correo = :c
        """), {"t": tenant, "c": correo}).first()
        if usuario is None:
            creados.append(correo)
            continue

        envios = escalar(db, """
            SELECT count(*) FROM notificaciones_enviadas
            WHERE destinatario_correo = :c AND tipo = 'solicitud_prueba_clase'
        """, c=correo)
        if not envios:
            sin_correo.append(correo)

        prueba = db.execute(text("""
            SELECT s.fecha_inicio, s.fecha_expiracion, p.duracion_dias
            FROM suscripciones s JOIN planes p ON p.id = s.plan_id
            WHERE s.usuario_id = :u AND s.tenant_id = :t
              AND p.nombre = 'Prueba' AND s.estado::text = 'activo'
            ORDER BY s.id DESC LIMIT 1
        """), {"u": usuario[0], "t": tenant}).first()
        if prueba is None:
            sin_prueba.append(correo)
            continue
        dias = (prueba[1] - prueba[0]).total_seconds() / 86400 if prueba[0] else None
        if dias is None or abs(dias - float(prueba[2])) > 0.05:
            mal_duracion.append(f"{correo}: {dias} días (plan {prueba[2]})")

    check(f"las {len(correos)} altas existen en `usuarios`", not creados,
          f"faltan: {creados[:5]}")
    check("cada alumno quedó con su plan 'Prueba' ACTIVO", not sin_prueba,
          f"sin Prueba activa: {sin_prueba[:5]}")
    check("el plan Prueba dura 7 días (fecha_expiracion - fecha_inicio)",
          not mal_duracion, f"{mal_duracion[:3]}")
    check("se registró el intento de correo de credenciales "
          "(notificaciones_enviadas tipo solicitud_prueba_clase)",
          not sin_correo, f"sin fila de envío: {sin_correo[:5]}")
    estados = filas(db, """
        SELECT DISTINCT estado FROM notificaciones_enviadas
        WHERE destinatario_correo = ANY(:c) AND tipo = 'solicitud_prueba_clase'
    """, c=correos)
    info(f"estado de los envíos: {[r[0] for r in estados]} "
         "(con EMAIL_MODO=noop es 'simulado', no 'enviado')")



# ── G11: referidos con conversión real + escalera ────────────────────────────
def verificar_g11(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G11 — referidos: conversión + descuentos + créditos FIFO + escalera")
    tenant = cfg["tenant_id"]
    n = int(cfg.get("n_g11") or 3)
    invitador = cfg.get("invitador_g11") or {}
    invitados = cfg.get("invitados_g11") or []
    if not check("load_config.json trae invitador_g11 + invitados_g11",
                 bool(invitador.get("alumno_id")) and bool(invitados),
                 f"invitador={invitador.get('alumno_id')} · "
                 f"{len(invitados)} invitados"):
        return

    # 1) Las altas NUEVAS del flujo G10 (una por VU).
    correos_alta = cfg.get("correos_g11_alta") or []
    sin_alta = [c for c in correos_alta if db.execute(text(
        "SELECT 1 FROM usuarios WHERE tenant_id = :t AND correo = :c"),
        {"t": tenant, "c": c}).first() is None]
    check(f"las {len(correos_alta)} altas nuevas existen", not sin_alta,
          f"faltan: {sin_alta[:5]}")

    # 2) Reglas del programa: % del invitado/invitador + precio de lista.
    config = db.execute(text("""
        SELECT porcentaje_descuento_invitado, porcentaje_descuento_invitador
        FROM configuracion_referidos WHERE tenant_id = :t AND activo
    """), {"t": tenant}).first()
    if not check("hay configuración de referidos activa", config is not None):
        return
    pct_invitado, pct_invitador = config[0], config[1]
    id_plan = cfg.get("plan_pago_id")
    precio = db.execute(text("SELECT precio_clp FROM planes WHERE id = :p"),
                        {"p": id_plan}).scalar()
    if not check("el plan de la compra tiene precio de lista > 0",
                 isinstance(precio, int) and precio > 0,
                 f"plan={id_plan} ${precio}"):
        return
    esperado_invitado = referidos_svc.calcular_descuento_clp(precio, pct_invitado)
    esperado_invitador = referidos_svc.calcular_descuento_clp(precio, pct_invitador)
    info(f"% invitado={pct_invitado} → ${esperado_invitado} · "
         f"% invitador={pct_invitador} → ${esperado_invitador} · "
         f"precio lista=${precio}")

    # 3) Cada invitado convirtió SU referido con SU % individual.
    ids_invitados = [i["alumno_id"] for i in invitados]
    aplicados = filas(db, """
        SELECT id, usuario_invitado_id, estado::text, fecha_conversion,
               descuento_aplicado_invitado
        FROM referidos_aplicados
        WHERE usuario_invitador_id = :a AND usuario_invitado_id = ANY(:i)
        ORDER BY id
    """, a=invitador["alumno_id"], i=ids_invitados)
    check(f"los {n} invitados tienen su referido aplicado", len(aplicados) == n,
          f"{len(aplicados)} filas")
    no_convertidos = [r[1] for r in aplicados if r[2] != "convertido"]
    check("todos los referidos quedaron 'convertido'", not no_convertidos,
          f"pendientes: {no_convertidos[:5]}")
    mal_monto = [(r[1], r[4]) for r in aplicados
                 if r[4] is None or int(round(float(r[4]))) != esperado_invitado]
    check("cada invitado tiene aplicado SU % (descuento_aplicado_invitado)",
          not mal_monto, f"esperado ${esperado_invitado}: {mal_monto[:5]}")

    sin_solicitud, mal_descuento = [], []
    for uid in ids_invitados:
        sol = db.execute(text("""
            SELECT id, estado, descuento_pct, precio_final_clp,
                   precio_clp_snapshot
            FROM solicitudes_planes WHERE alumno_id = :u AND tenant_id = :t
            ORDER BY id DESC LIMIT 1
        """), {"u": uid, "t": tenant}).first()
        if sol is None or sol[1] != "approved":
            sin_solicitud.append(uid)
            continue
        final = sol[3] if sol[3] is not None else sol[4]
        if int(sol[2] or -1) != int(round(float(pct_invitado))) \
                or int(final) != precio - esperado_invitado:
            mal_descuento.append((uid, sol[0], sol[2], final))
    check("cada invitado tiene su solicitud APROBADA", not sin_solicitud,
          f"sin solicitud aprobada: {sin_solicitud[:5]}")
    check("la solicitud de cada invitado cobró el precio con SU descuento",
          not mal_descuento,
          f"esperado %{pct_invitado} y ${precio - esperado_invitado}: "
          f"{mal_descuento[:3]}")
    # 4) Créditos FIFO del invitador: uno por conversión, sin duplicar.
    creditos = filas(db, """
        SELECT id, porcentaje, estado::text, referido_aplicado_id,
               fecha_otorgado, descuento_aplicado_clp
        FROM creditos_referido WHERE usuario_id = :a
        ORDER BY fecha_otorgado, id
    """, a=invitador["alumno_id"])
    check(f"el invitador acumuló {n} créditos (uno por conversión)",
          len(creditos) == n, f"{len(creditos)} filas")
    origenes = [r[3] for r in creditos]
    check("ningún crédito está duplicado (un origen por crédito)",
          len(origenes) == len(set(origenes)),
          f"{len(origenes)} créditos, {len(set(origenes))} orígenes")
    mal_pct = [(r[0], r[1]) for r in creditos
               if int(round(float(r[1]))) != int(round(float(pct_invitador)))]
    check("los créditos congelaron el % del invitador", not mal_pct,
          f"{mal_pct[:3]}")

    usados = [r for r in creditos if r[2] == "usado"]
    pendientes = [r for r in creditos if r[2] == "pendiente"]
    check("la compra del invitador consumió UN solo crédito", len(usados) == 1,
          f"{len(usados)} usados / {len(pendientes)} pendientes")
    if usados and creditos:
        check("consumió el crédito MÁS VIEJO (FIFO, no salteó ninguno)",
              usados[0][0] == creditos[0][0],
              f"usado={usados[0][0]} · el más viejo={creditos[0][0]}")
        check("el crédito usado descontó el % del invitador",
              usados[0][5] is not None
              and int(usados[0][5]) == esperado_invitador,
              f"descuento_aplicado_clp={usados[0][5]} "
              f"(esperado {esperado_invitador})")
        origen = db.execute(text("""
            SELECT descuento_aplicado_invitador FROM referidos_aplicados
            WHERE id = :r
        """), {"r": usados[0][3]}).scalar()
        check("el snapshot del referido de origen tiene el monto del invitador",
              origen is not None
              and int(round(float(origen))) == esperado_invitador,
              f"descuento_aplicado_invitador={origen}")

    # 5) Escalera: con `n` convertidos se otorga SÓLO el tramo más alto.
    tramos = filas(db, """
        SELECT id, umbral_referidos, tipo_premio::text, valor_premio, activo
        FROM tramos_referido WHERE tenant_id = :t AND activo
        ORDER BY umbral_referidos
    """, t=tenant)
    umbrales = [int(r[1]) for r in tramos]
    info(f"escalera activa del box: umbrales {umbrales}")
    umbral_cfg = cfg.get("tramo_g11_umbral")
    if not check("la escalera tiene el tramo que el seed dejó para G11",
                 bool(umbral_cfg) and int(umbral_cfg) in umbrales,
                 f"umbrales={umbrales} · config={umbral_cfg}"):
        return
    check("hay más de un tramo alcanzable (la exclusividad no es trivial)",
          len([u for u in umbrales if u <= n]) > 1,
          f"umbrales <= {n}: {[u for u in umbrales if u <= n]}")

    class _Tramo:
        """Adaptador mínimo: `umbral_mas_alto` acepta ORM o dict-like."""

        def __init__(self, fila):
            self.id = fila[0]
            self.umbral_referidos = fila[1]
            self.tipo_premio = fila[2]
            self.valor_premio = fila[3]
            self.activo = fila[4]

    elegido = tramos_svc.umbral_mas_alto(n, [_Tramo(f) for f in tramos])
    check("umbral_mas_alto elige SÓLO el tramo de mayor umbral alcanzado",
          elegido is not None
          and int(elegido.umbral_referidos) == int(umbral_cfg),
          f"elegido={getattr(elegido, 'umbral_referidos', None)} "
          f"(esperado {umbral_cfg}, convertidos={n})")

    premios = escalar(db, """
        SELECT count(*) FROM premios_tramo_ciclo
        WHERE usuario_id = :a AND tenant_id = :t
    """, a=invitador["alumno_id"], t=tenant)
    check("no se otorgaron los 3 premios individuales como premios de tramo",
          premios <= 1, f"{premios} filas en premios_tramo_ciclo")
    if premios == 1:
        umbral_premio = escalar(db, """
            SELECT umbral_referidos FROM premios_tramo_ciclo
            WHERE usuario_id = :a AND tenant_id = :t ORDER BY id DESC LIMIT 1
        """, a=invitador["alumno_id"], t=tenant)
        check("el único premio de tramo es el del umbral más alto",
              int(umbral_premio) == int(umbral_cfg), f"umbral={umbral_premio}")
    else:
        info("el ciclo del invitador sigue ABIERTO (0 premios de tramo): el "
             "premio se emite al cierre del ciclo por el job diario, no acá")





# ── G12: reactivación / recuperación ─────────────────────────────────────────
def verificar_g12(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G12 — reactivación: padrón → promoción → Beneficio → 'recuperado'")
    tenant = cfg["tenant_id"]
    candidatos = cfg.get("candidatos_g12") or []
    vencido = cfg.get("candidato_vencido_g12") or {}
    if not check("load_config.json trae candidatos_g12 + candidato_vencido_g12",
                 bool(candidatos) and bool(vencido.get("promocion_id")),
                 f"{len(candidatos)} vigentes · vencido={vencido.get('promocion_id')}"):
        return

    sin_recuperar, sin_usuario, sin_beneficio, tipo_mal = [], [], [], []
    desconectados = []
    for cand in candidatos:
        promo = db.execute(text("""
            SELECT estado, usuario_id, tipo_beneficio, cantidad
            FROM promociones_recuperacion WHERE id = :p
        """), {"p": cand.get("promocion_id")}).first()
        if promo is None:
            sin_recuperar.append(cand.get("promocion_id"))
            continue
        if promo[0] != "recuperado":
            sin_recuperar.append(f"promo {cand['promocion_id']}={promo[0]}")
        usuario = db.execute(text("""
            SELECT id FROM usuarios WHERE tenant_id = :t AND correo = :c
        """), {"t": tenant, "c": cand["correo"]}).first()
        if usuario is None:
            sin_usuario.append(cand["correo"])
            continue
        if promo[1] is None or int(promo[1]) != int(usuario[0]):
            sin_usuario.append(f"{cand['correo']} sin usuario_id en la promo")

        beneficio = db.execute(text("""
            SELECT id, tipo::text, valor, estado::text, suscripcion_id, plan_id
            FROM beneficios WHERE alumno_id = :u ORDER BY id DESC LIMIT 1
        """), {"u": usuario[0]}).first()
        if beneficio is None:
            sin_beneficio.append(cand["correo"])
            continue
        esperado = ("clases_gratis" if promo[2] == "dias_gratis"
                    else "descuento")
        if beneficio[1] != esperado or int(beneficio[2]) != int(promo[3]):
            tipo_mal.append((cand["correo"], beneficio[1], beneficio[2],
                             esperado, promo[3]))
        if esperado == "clases_gratis":
            # Materializa acceso: o suma créditos a su plan vigente o abre un
            # pase. En los dos casos queda una suscripción conectada.
            if beneficio[4] is None:
                desconectados.append(cand["correo"])
            else:
                creditos = escalar(db, """
                    SELECT creditos_disponibles FROM suscripciones WHERE id = :s
                """, s=beneficio[4])
                if creditos is None or int(creditos) < int(promo[3]):
                    desconectados.append(
                        f"{cand['correo']} (créditos={creditos}, "
                        f"esperado>={promo[3]})")

    check(f"las {len(candidatos)} promociones vigentes quedaron 'recuperado'",
          not sin_recuperar, f"{sin_recuperar[:5]}")
    check("cada promoción quedó ligada al usuario nuevo (usuario_id)",
          not sin_usuario, f"{sin_usuario[:5]}")
    check("cada alumno tiene su Beneficio REAL creado", not sin_beneficio,
          f"sin beneficio: {sin_beneficio[:5]}")
    check("el Beneficio tiene el tipo y el valor de la oferta", not tipo_mal,
          f"{tipo_mal[:3]}")
    check("el acceso quedó CONECTADO (suscripción con los créditos del regalo)",
          not desconectados, f"{desconectados[:5]}")

    # La promoción VENCIDA no se aplica ni se marca: el correo dijo "hasta el X".
    promo_v = db.execute(text("""
        SELECT estado, usuario_id, vence_en FROM promociones_recuperacion
        WHERE id = :p
    """), {"p": vencido["promocion_id"]}).first()
    if check("existe la promoción vencida", promo_v is not None,
             f"id={vencido['promocion_id']}"):
        check("la promoción VENCIDA sigue 'enviada' (no se marcó recuperada)",
              promo_v[0] == "enviada", f"estado={promo_v[0]}")
        check("la promoción VENCIDA no se ligó a ningún usuario",
              promo_v[1] is None, f"usuario_id={promo_v[1]}")
        usuario_v = db.execute(text("""
            SELECT id FROM usuarios WHERE tenant_id = :t AND correo = :c
        """), {"t": tenant, "c": vencido["correo"]}).first()
        check("el correo vencido SÍ se registró (es un alumno más)",
              usuario_v is not None, vencido["correo"])
        if usuario_v is not None:
            beneficios_v = escalar(db, """
                SELECT count(*) FROM beneficios WHERE alumno_id = :u
            """, u=usuario_v[0])
            check("la oferta vencida no le creó ningún Beneficio",
                  beneficios_v == 0, f"{beneficios_v} beneficios")

    total = escalar(db, """
        SELECT count(*) FROM promociones_recuperacion WHERE tenant_id = :t
          AND candidato_id IN (SELECT id FROM candidatos_boxmagic
                               WHERE tenant_id = :t AND correo LIKE 'carga_k6_%')
    """, t=tenant)
    check(f"sólo existen las {len(candidatos) + 1} promociones del seed "
          "(ninguna duplicada)", total == len(candidatos) + 1, f"{total} filas")



# ── G13: ciclo de WODs con concurrencia ──────────────────────────────────────
def verificar_g13(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G13 — Mis WODs: WOD publicado + clase de hoy + resultados por alumno")
    tenant = cfg["tenant_id"]
    alumnos = cfg.get("alumnos_g13") or []
    wod_id = cfg.get("wod_g13_id")
    clase_id = cfg.get("clase_g13_id")
    clase_coach = cfg.get("clase_g13_coach_id")
    n = len(alumnos) or int(cfg.get("n_g13") or 5)
    if not check("load_config.json trae alumnos_g13 / wod_g13_id / clase_g13_id",
                 bool(alumnos) and bool(wod_id) and bool(clase_id),
                 f"{len(alumnos)} alumnos · wod={wod_id} · clase={clase_id}"):
        return

    wod = db.execute(text("""
        SELECT id, titulo, estado, tipo_metcon, fecha FROM wods
        WHERE id = :w AND tenant_id = :t
    """), {"w": wod_id, "t": tenant}).first()
    if not check("el WOD sembrado existe", wod is not None, f"id={wod_id}"):
        return
    check("el WOD está PUBLICADO", wod[2] == "publicado", f"estado={wod[2]}")
    check("el WOD es por rondas (AMRAP) y el escenario manda rondas",
          "AMRAP" in str(wod[3] or "").upper(), f"tipo_metcon={wod[3]}")

    clase = db.execute(text("""
        SELECT fecha, wod_id, coach_id FROM clases WHERE id = :c
    """), {"c": clase_id}).first()
    if check("la clase de los alumnos existe", clase is not None,
             f"id={clase_id}"):
        hoy = datetime.now(SANTIAGO).date()
        check("la clase es de HOY en Chile (si no, /wods-pendientes no la ve)",
              clase[0] == hoy, f"{clase[0]} vs {hoy}")
        check("la clase tiene asignado el WOD sembrado",
              int(clase[1] or 0) == int(wod_id), f"wod_id={clase[1]}")

    reservas = escalar(db, """
        SELECT count(*) FROM reservas
        WHERE clase_id = :c AND asistio IS TRUE
    """, c=clase_id)
    check(f"la clase tiene las {n} reservas con asistencia",
          int(reservas) == n, f"{reservas} reservas asistidas")

    resultados = filas(db, """
        SELECT alumno_id, reserva_id, modo, rondas, nota
        FROM wod_resultados WHERE wod_id = :w AND tenant_id = :t
        ORDER BY alumno_id
    """, w=wod_id, t=tenant)
    check(f"quedaron {n} resultados (uno por alumno)", len(resultados) == n,
          f"{len(resultados)} filas")
    ids_resultado = [r[0] for r in resultados]
    check("ningún alumno tiene dos resultados (no se pisaron filas)",
          len(ids_resultado) == len(set(ids_resultado)),
          f"{len(ids_resultado)} filas, {len(set(ids_resultado))} alumnos")
    # El VU k (1-based) manda `rondas = 20 + k`; cada fila tiene que conservar
    # SU valor: si dos alumnos hubieran compartido el UPSERT, uno perdería el suyo.
    esperado = {a["alumno_id"]: 20 + (i + 1) for i, a in enumerate(alumnos)}
    pisados = [(r[0], r[3], esperado.get(r[0])) for r in resultados
               if int(r[3] or -1) != esperado.get(r[0])]
    check("cada resultado guardó las rondas de SU VU (sin pisarse)", not pisados,
          f"(alumno, guardado, esperado): {pisados[:5]}")
    sin_reserva = [r[0] for r in resultados if r[1] is None]
    check("cada resultado apunta a la reserva que lo respalda",
          not sin_reserva, f"{sin_reserva[:5]}")
    sin_modo = [r[0] for r in resultados if r[2] != "rx"]
    check("todos se registraron en modo 'rx'", not sin_modo, f"{sin_modo[:5]}")

    # El camino del coach (sub-escenario): WOD creado + publicado + asignado.
    # El título arranca con `G13 K6` (no con `K6 `) a propósito: el verificador de
    # G2 filtra `titulo LIKE 'K6 %'` y estos WODs no son suyos.
    wods_coach = filas(db, """
        SELECT id, titulo, estado FROM wods
        WHERE tenant_id = :t AND titulo LIKE 'G13 K6 Coach%'
        ORDER BY id DESC
    """, t=tenant)
    check("el coach creó y publicó su WOD por API", bool(wods_coach),
          f"{len(wods_coach)} WODs 'G13 K6 Coach%'")
    if wods_coach:
        check("el WOD del coach quedó publicado", wods_coach[0][2] == "publicado",
              f"estado={wods_coach[0][2]}")
        asignado = escalar(db, "SELECT wod_id FROM clases WHERE id = :c",
                           c=clase_coach)
        check("el coach lo asignó a su clase de hoy",
              int(asignado or 0) == int(wods_coach[0][0]),
              f"clase {clase_coach} → wod_id={asignado} "
              f"(último creado {wods_coach[0][0]})")



# ── G14: activación end-to-end ───────────────────────────────────────────────
def verificar_g14(db, cfg: dict, tokens: list[dict]) -> None:
    seccion("G14 — activación end-to-end (activar → correo → clave → plan)")
    tenant = cfg["tenant_id"]
    alumnos = cfg.get("alumnos_g14") or []
    if not check("load_config.json trae alumnos_g14", bool(alumnos),
                 f"{len(alumnos)} alumnos"):
        return
    plan_id = cfg.get("plan_pago_id")

    sin_activar, sin_correo, sin_solicitud, multiple = [], [], [], []
    con_flag = []
    for alumno in alumnos:
        uid = alumno["alumno_id"]
        usuario = db.execute(text("""
            SELECT estado, activo, cambiar_password_al_login
            FROM usuarios WHERE id = :u AND tenant_id = :t
        """), {"u": uid, "t": tenant}).first()
        if usuario is None or usuario[0] != "activo" or not usuario[1]:
            sin_activar.append(f"{uid}: {usuario}")
            continue
        if usuario[2]:
            con_flag.append(uid)

        envios = escalar(db, """
            SELECT count(*) FROM notificaciones_enviadas
            WHERE destinatario_correo = :c AND tipo = 'bienvenida_activacion'
        """, c=alumno["correo"])
        if not envios:
            sin_correo.append(alumno["correo"])

        solicitudes = escalar(db, """
            SELECT count(*) FROM solicitudes_planes
            WHERE alumno_id = :u AND tenant_id = :t AND plan_id = :p
        """, u=uid, t=tenant, p=plan_id)
        if solicitudes == 0:
            sin_solicitud.append(uid)
        elif solicitudes > 1:
            multiple.append(f"{uid}: {solicitudes}")

    check(f"los {len(alumnos)} alumnos quedaron 'activo' y activo=True",
          not sin_activar, f"{sin_activar[:3]}")
    check("el cambio de contraseña inicial bajó cambiar_password_al_login",
          not con_flag, f"siguen con el flag: {con_flag[:5]}")
    check("se registró el correo de bienvenida/activación de cada alumno",
          not sin_correo,
          f"sin fila 'bienvenida_activacion': {sin_correo[:5]}")
    check("cada alumno pidió su plan (solicitud creada)", not sin_solicitud,
          f"sin solicitud: {sin_solicitud[:5]}")
    check("no se duplicó la solicitud de nadie", not multiple,
          f"{multiple[:3]}")

    estados = filas(db, """
        SELECT DISTINCT estado FROM solicitudes_planes
        WHERE alumno_id = ANY(:u) AND tenant_id = :t
    """, u=[a["alumno_id"] for a in alumnos], t=tenant)
    info("estado de las solicitudes de G14: "
         f"{[r[0] for r in estados]} — el escenario compra por transferencia "
         "(solicitud pendiente de aprobación), no por Mercado Pago")
    envios = filas(db, """
        SELECT estado, count(*) FROM notificaciones_enviadas
        WHERE tipo = 'bienvenida_activacion'
          AND destinatario_correo = ANY(:c)
        GROUP BY estado
    """, c=[a["correo"] for a in alumnos])
    info(f"correos de activación por estado: {[(r[0], r[1]) for r in envios]}")



VERIFICADORES = {
    "g1": verificar_g1,
    "g2": verificar_g2,
    "g3": verificar_g3,
    "g4": verificar_g4,
    "g5": verificar_g5,
    "g6": verificar_g6,
    "g7": verificar_g7,
    "g8": verificar_g8,
    "g9": verificar_g9,
    "g10": verificar_g10,
    "g11": verificar_g11,
    "g12": verificar_g12,
    "g13": verificar_g13,
    "g14": verificar_g14,
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
