#!/usr/bin/env python
"""Siembra de carga para los escenarios k6 del box de TEST (idempotente).

Qué hace
--------
1. Verifica que la BD configurada sea TEST (`is_test_db_url`). Si no lo es, aborta
   ANTES de tocar nada: `backend/.env` en disco apunta a PRODUCCIÓN.
2. Borra lo que él mismo sembró (usuarios `carga_k6_*`, producto `CARGA_K6*` y
   todas sus filas hijas) para poder correr el seed N veces sin duplicar.
3. Siembra contra el tenant REAL de TEST (por defecto `maipu` = "Urban training
   box", id 1): admin + coach + N alumnos con suscripción activa, una clase de
   HOY con reservas en ventana de QR (G1), producto de bazar con un pedido
   `validado` (código de retiro) y otros `pendiente` (G3/G6), alumnos
   `pendiente_activacion` (G8), solicitudes de plan `pending` (C/E), códigos de
   referido (G4) e historial de RM para el grupo `vol` (F1).
4. Escribe `k6-tests/tokens.json` (JWTs por alumno) y actualiza
   `k6-tests/load_config.json` con TODOS los ids reales del seed.

Uso
---
    python k6-tests/_seed_load_test.py                 # 200 alumnos
    python k6-tests/_seed_load_test.py --alumnos 500   # 500 alumnos (escenario F2)
    python k6-tests/_seed_load_test.py --alumnos 500 --sin-historial
    python k6-tests/_seed_load_test.py --solo-limpiar  # borra el seed, no siembra

Notas
-----
- NO usa la API (login/registro están rate-limitados): inserta directo en BD.
- NO commitea nada al repo; sólo escribe tokens.json / load_config.json.
- Los correos del seed empiezan con `carga_k6_` y los RUT son válidos (módulo 11):
  así se distinguen de los datos reales del box y se pueden borrar sin riesgo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time as hora, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

K6_DIR = Path(__file__).resolve().parent
BACKEND_DIR = K6_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)  # .env / .env.test se resuelven relativos al backend

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import is_test_db_url, settings  # noqa: E402
from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from app.services.codigos_retiro import generar_codigo_unico  # noqa: E402
from app.services.referidos_service import asignar_codigo_referido  # noqa: E402

PREFIJO_CORREO = "carga_k6_"
PRODUCTO_NOMBRE = "CARGA_K6 Bazar"
PASSWORD = "Test1234!"  # la usan test_500_logins.js y scenario_e_mix.js
SANTIAGO = ZoneInfo("America/Santiago")

N_VOL = 20                 # alumnos con historial de RM (grupo 'vol' de F1)
N_HISTORIAL = 20           # filas de historial_rm por alumno 'vol'
N_SOLICITUDES = 20         # solicitudes de plan 'pending' (escenarios C y E)
N_PENDIENTES = 20          # alumnos 'pendiente_activacion' (escenario G8)
N_D = 20                   # default de n_d / n_vol / n_conc / n_a si no existían
STOCK_INICIAL = 100
PRECIO_BAZAR = 10_000.0
VOUCHER_URL = "/privado/vouchers/carga_k6_voucher.jpg"  # ruta ficticia del seed

NOMBRES = ["Josefa", "Matias", "Camila", "Benjamin", "Antonia", "Vicente",
           "Florencia", "Diego", "Martina", "Ignacio", "Catalina", "Tomas",
           "Amanda", "Lucas", "Trinidad", "Agustin", "Javiera", "Maximiliano",
           "Emilia", "Cristobal"]
APELLIDOS = ["Rojas", "Munoz", "Contreras", "Sepulveda", "Morales", "Fuentes",
             "Araya", "Venegas", "Pizarro", "Caceres", "Navarrete", "Tapia",
             "Riquelme", "Soto", "Cordero", "Bustamante", "Figueroa", "Olea",
             "Maldonado", "Zuniga"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def log(msg: str = "") -> None:
    print(msg, flush=True)


def dv_rut(cuerpo: int) -> str:
    """RUT chileno válido (módulo 11), formato '{cuerpo}-{dv}'."""
    suma, mult = 0, 2
    for d in reversed(str(cuerpo)):
        suma += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    dv = 11 - (suma % 11)
    if dv == 11:
        dv = 0
    elif dv == 10:
        dv = "K"
    return f"{cuerpo}-{dv}"


def nombre_por_indice(i: int) -> str:
    return f"{NOMBRES[i % len(NOMBRES)]} {APELLIDOS[(i * 7) % len(APELLIDOS)]}"


def correo_por_indice(i: int) -> str:
    return f"{PREFIJO_CORREO}alumno{i:04d}@load.test"


def resumen_bd() -> str:
    """URL de la BD sin credenciales, para que el operador vea DÓNDE escribe."""
    url = make_url(settings.DATABASE_URL)
    return f"{url.host}/{url.database}"


def ruts_libres(conn, tenant_id: int, cantidad: int) -> list[str]:
    """Genera `cantidad` RUTs válidos que no existan en el tenant."""
    usados = {r[0] for r in conn.execute(text(
        "SELECT rut FROM usuarios WHERE tenant_id = :t"), {"t": tenant_id})}
    libres: list[str] = []
    cuerpo = 21_000_000
    while len(libres) < cantidad:
        rut = dv_rut(cuerpo)
        if rut not in usados:
            usados.add(rut)
            libres.append(rut)
        cuerpo += 1
    return libres


# ── Limpieza del seed anterior ────────────────────────────────────────────────
def limpiar(conn, tenant_id: int, horario_id_previo: int | None) -> list[tuple[str, int]]:
    """Borra el seed previo respetando las FKs sin ON DELETE CASCADE.

    Sólo toca filas del seed (correos `carga_k6_*`, producto `CARGA_K6*`): nunca
    alumnos reales del box. `usuarios` va al final porque casi todo cuelga de él;
    `horarios_base.coach_id`, `notificaciones.alumno_id` y `solicitudes_planes`
    NO tienen CASCADE y hay que borrarlos a mano.
    """
    params = {"t": tenant_id, "p": f"{PREFIJO_CORREO}%", "p2": "CARGA_K6%",
              "h": horario_id_previo or -1}
    sel_usuarios = ("SELECT id FROM usuarios WHERE tenant_id = :t "
                    "AND correo LIKE :p")
    pasos: list[tuple[str, str]] = [
        ("solicitudes_planes (alumno/aprobador)",
         "DELETE FROM solicitudes_planes WHERE alumno_id IN (%s) "
         "OR aprobado_por IN (%s)" % (sel_usuarios, sel_usuarios)),
        ("notificaciones", "DELETE FROM notificaciones WHERE alumno_id IN (%s)"
         % sel_usuarios),
        ("notificaciones_enviadas",
         "DELETE FROM notificaciones_enviadas WHERE alumno_id IN (%s)"
         % sel_usuarios),
        ("pedidos", "DELETE FROM pedidos WHERE alumno_id IN (%s)" % sel_usuarios),
        ("reservas", "DELETE FROM reservas WHERE alumno_id IN (%s)" % sel_usuarios),
        ("asistencias",
         "DELETE FROM asistencias WHERE usuario_id IN (%s)" % sel_usuarios),
        ("historial_rm",
         "DELETE FROM historial_rm WHERE alumno_id IN (%s)" % sel_usuarios),
        ("codigos_referido",
         "DELETE FROM codigos_referido WHERE usuario_id IN (%s)" % sel_usuarios),
        # Las FKs de `invitaciones` son SET NULL: si no se borran ANTES de
        # `usuarios`, quedan invitaciones huérfanas del seed para siempre.
        ("invitaciones (referidos)",
         "DELETE FROM invitaciones WHERE enviado_por_usuario_id IN (%s) "
         "OR usuario_registrado_id IN (%s)" % (sel_usuarios, sel_usuarios)),
        ("suscripciones",
         "DELETE FROM suscripciones WHERE usuario_id IN (%s)" % sel_usuarios),
        ("clases (del coach del seed)",
         "DELETE FROM clases WHERE coach_id IN (%s)" % sel_usuarios),
        ("horarios_base (del coach del seed)",
         "DELETE FROM horarios_base WHERE coach_id IN (%s)" % sel_usuarios),
        # Sólo se borra el horario si lo creó este seed (queda anotado en el config).
        ("horarios (creado por el seed)",
         "DELETE FROM horarios WHERE id = :h AND tenant_id = :t"),
        ("usuarios", "DELETE FROM usuarios WHERE tenant_id = :t AND correo LIKE :p"),
        ("productos", "DELETE FROM productos WHERE tenant_id = :t AND nombre LIKE :p2"),
    ]
    hechas: list[tuple[str, int]] = []
    for nombre, sql in pasos:
        hechas.append((nombre, conn.execute(text(sql), params).rowcount))
    return hechas


# ── Resolución de catálogos reales del box ────────────────────────────────────
def resolver_tenant(conn, subdominio: str) -> dict:
    fila = conn.execute(text(
        "SELECT id, nombre, subdomain, public_id FROM tenants "
        "WHERE subdomain = :s"), {"s": subdominio}).first()
    if not fila:
        disponibles = [tuple(r) for r in conn.execute(text(
            "SELECT id, nombre, subdomain FROM tenants ORDER BY id"))]
        raise SystemExit(
            f"No existe el tenant con subdominio '{subdominio}' en TEST.\n"
            f"Tenants disponibles: {disponibles}")
    return {"id": fila[0], "nombre": fila[1], "subdomain": fila[2],
            "public_id": fila[3]}


def resolver_plan(conn, tenant_id: int, plan_id: int | None) -> dict:
    sql = ("SELECT id, nombre, creditos, es_ilimitado, precio_clp FROM planes "
           "WHERE tenant_id = :t AND activo AND nombre <> 'Prueba'")
    if plan_id:
        fila = conn.execute(text(sql + " AND id = :p"),
                            {"t": tenant_id, "p": plan_id}).first()
    else:
        fila = conn.execute(text(sql + " ORDER BY id LIMIT 1"),
                            {"t": tenant_id}).first()
    if not fila:
        raise SystemExit(f"El tenant {tenant_id} no tiene planes activos de pago "
                         f"(nombre != 'Prueba').")
    return {"id": fila[0], "nombre": fila[1], "creditos": fila[2] or 1,
            "es_ilimitado": fila[3], "precio_clp": fila[4] or 0}


def resolver_movimientos(conn, tenant_id: int) -> tuple[int, int]:
    """Dos movimientos de fuerza: MOV_F1 (lecturas de F1) y MOV_G1 (altas de F2)."""
    ids = [r[0] for r in conn.execute(text(
        "SELECT id FROM movimientos WHERE tenant_id = :t AND activo "
        "AND categoria = 'fuerza' ORDER BY id LIMIT 2"), {"t": tenant_id})]
    if len(ids) < 2:
        raise SystemExit(f"El tenant {tenant_id} necesita >= 2 movimientos de "
                         f"fuerza activos (encontrados: {ids}).")
    return ids[0], ids[1]


def resolver_disciplina(conn, tenant_id: int) -> int:
    fila = conn.execute(text(
        "SELECT id FROM disciplinas WHERE tenant_id = :t AND activo "
        "AND NOT es_open_box ORDER BY id LIMIT 1"), {"t": tenant_id}).first()
    if not fila:
        raise SystemExit(f"El tenant {tenant_id} no tiene disciplinas activas.")
    return fila[0]


# ── Siembra ───────────────────────────────────────────────────────────────────
def insertar_lote(db, tabla: str, filas: list[dict], *,
                  casts: dict[str, str] | None = None, chunk: int = 200) -> None:
    """INSERT de muchas filas en UN statement por chunk.

    Neon está lejos (~150-250 ms por roundtrip): un `executemany` de 400 filas
    son 400 viajes y el seed se vuelve eterno. Acá cada chunk de `chunk` filas
    viaja una sola vez. `casts` permite que una columna viaje con CAST explícito
    (enums): {"rol": "rol_usuario"} → CAST(:p3_rol AS rol_usuario).
    """
    if not filas:
        return
    casts = casts or {}
    columnas = list(filas[0])
    for inicio in range(0, len(filas), chunk):
        trozo = filas[inicio:inicio + chunk]
        valores, params = [], {}
        for j, fila in enumerate(trozo):
            marcas = []
            for col in columnas:
                clave = f"p{j}_{col}"
                if col in casts:
                    marcas.append(f"CAST(:{clave} AS {casts[col]})")
                else:
                    marcas.append(f":{clave}")
                params[clave] = fila[col]
            valores.append("(" + ", ".join(marcas) + ")")
        db.execute(text(f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES "
                        + ", ".join(valores)), params)


def sembrar(db, *, tenant: dict, plan: dict, mov_f1: int, mov_g1: int,
            disciplina_id: int, n_alumnos: int, con_historial: bool) -> dict:
    """Inserta todo el dataset de carga y devuelve lo necesario para el config."""
    ahora = datetime.now(SANTIAGO)
    hoy: date = ahora.date()
    hash_pw = get_password_hash(PASSWORD)  # una sola vez: bcrypt es caro

    # ── 1) Usuarios: admin, coach y N alumnos con RUT válido ──
    ruts = ruts_libres(db, tenant["id"], n_alumnos + 2 + N_PENDIENTES)
    admin_correo = f"{PREFIJO_CORREO}admin@load.test"
    coach_correo = f"{PREFIJO_CORREO}coach@load.test"

    def fila_usuario(rut: str, nombre: str, correo: str, rol: str, *,
                     activo: bool = True, estado: str = "activo",
                     peso=None, genero=None, cambiar_pw: bool = False) -> dict:
        return {"tenant_id": tenant["id"], "rut": rut, "nombre": nombre,
                "correo": correo, "password_hash": hash_pw, "rol": rol,
                "activo": activo, "estado": estado,
                "cambiar_password_al_login": cambiar_pw,
                "peso_kg": peso, "genero": genero}

    filas = [fila_usuario(ruts[0], "Carga K6 Admin", admin_correo,
                          "administrador"),
             fila_usuario(ruts[1], "Carga K6 Coach", coach_correo, "coach")]
    for i in range(1, n_alumnos + 1):
        filas.append(fila_usuario(
            ruts[1 + i], nombre_por_indice(i), correo_por_indice(i), "alumno",
            peso=60.0 + (i % 25),  # peso corporal: nivel de fuerza calculable (F1)
            genero="M" if i % 2 else "F"))
    # Alumnos en la cola de activación del admin (G8): estado pendiente, sin peso.
    for j in range(1, N_PENDIENTES + 1):
        filas.append(fila_usuario(
            ruts[n_alumnos + 1 + j], nombre_por_indice(j),
            f"{PREFIJO_CORREO}pend{j:02d}@load.test", "alumno",
            activo=False, estado="pendiente_activacion", cambiar_pw=True))
    insertar_lote(db, "usuarios", filas, casts={"rol": "rol_usuario"})
    log(f"  usuarios: {len(filas)} (1 admin, 1 coach, {n_alumnos} alumnos, "
        f"{N_PENDIENTES} pendiente_activacion)")

    ids = {r[0]: r[1] for r in db.execute(text(
        "SELECT correo, id FROM usuarios WHERE tenant_id = :t AND correo LIKE :p"),
        {"t": tenant["id"], "p": f"{PREFIJO_CORREO}%"})}
    admin_id, coach_id = ids[admin_correo], ids[coach_correo]
    alumnos = [{"id": ids[correo_por_indice(i)], "correo": correo_por_indice(i),
                "nombre": nombre_por_indice(i)} for i in range(1, n_alumnos + 1)]
    pendientes = [ids[f"{PREFIJO_CORREO}pend{j:02d}@load.test"]
                  for j in range(1, N_PENDIENTES + 1)]

    # ── 2) Suscripciones activas (plan real del box, NO "Prueba") ──
    inicio = ahora - timedelta(days=2)
    fin = ahora + timedelta(days=28)
    insertar_lote(db, "suscripciones", [
        {"tenant_id": tenant["id"], "usuario_id": a["id"], "plan_id": plan["id"],
         "estado": "activo", "creditos_totales": plan["creditos"],
         "creditos_disponibles": max(plan["creditos"] - 1, 0),
         "fecha_inicio": inicio, "fecha_expiracion": fin,
         "aprobado_por": admin_id} for a in alumnos],
        casts={"estado": "estado_suscripcion"})
    susc = {r[0]: r[1] for r in db.execute(text(
        "SELECT usuario_id, id FROM suscripciones WHERE tenant_id = :t "
        "AND usuario_id = ANY(:ids)"),
        {"t": tenant["id"], "ids": [a["id"] for a in alumnos]})}
    log(f"  suscripciones: {len(alumnos)} (plan {plan['id']})")

    # ── 3) Clase de HOY con reservas en la ventana del QR (G1) ──
    # Ventana del backend: [hora_inicio - 60 min, hora_fin). Se siembra la clase
    # empezada hace 10 min, así el check-in cae dentro con margen.
    ini_t = (ahora - timedelta(minutes=10)).time().replace(second=0, microsecond=0)
    fin_dt = ahora + timedelta(minutes=50)
    fin_t = (hora(23, 59) if fin_dt.date() != hoy
             else fin_dt.time().replace(second=0, microsecond=0))

    horario = db.execute(text(
        "SELECT id FROM horarios WHERE tenant_id = :t AND disciplina_id = :d "
        "AND activo ORDER BY cupo_maximo DESC, id LIMIT 1"),
        {"t": tenant["id"], "d": disciplina_id}).first()
    if horario:
        horario_id, horario_creado = horario[0], None
    else:
        horario_creado = db.execute(text(
            "INSERT INTO horarios (tenant_id, disciplina_id, dia_semana, "
            "hora_inicio, hora_fin, cupo_maximo, activo) "
            "VALUES (:t, :d, :ds, :hi, :hf, :c, TRUE) RETURNING id"),
            {"t": tenant["id"], "d": disciplina_id, "ds": hoy.weekday(),
             "hi": ini_t, "hf": fin_t, "c": n_alumnos + 20}).scalar_one()
        horario_id = horario_creado

    clase_id = db.execute(text(
        "INSERT INTO clases (tenant_id, horario_base_id, coach_id, disciplina_id, "
        "fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, "
        "cancelada) VALUES (:t, :h, :c, :d, :f, :hi, :hf, :cupo, :conf, FALSE) "
        "RETURNING id"),
        {"t": tenant["id"], "h": horario_id, "c": coach_id, "d": disciplina_id,
         "f": hoy, "hi": ini_t, "hf": fin_t, "cupo": n_alumnos + 20,
         "conf": n_alumnos}).scalar_one()

    insertar_lote(db, "reservas", [
        {"tenant_id": tenant["id"], "clase_id": clase_id, "alumno_id": a["id"],
         "estado": "confirmada", "asistio": False, "tokens_gastados": 1,
         "suscripcion_id": susc.get(a["id"])} for a in alumnos])
    log(f"  clase de hoy: {clase_id} ({ini_t}-{fin_t}) con "
        f"{len(alumnos)} reservas")

    # ── 3b) Segunda clase de HOY, dedicada a G7 (pestaña Asistencia del coach) ──
    # El `confirmar` del coach escribe `asistencia_via='batch'` sobre TODAS las
    # reservas que toca (asistencia.py:461-466) y G1 verifica
    # `asistencia_via='qr_alumno'` en la clase del QR: con una sola clase, el
    # verificador que corra segundo falla según el orden. Con clase propia los dos
    # flujos quedan independientes y G7 se puede repetir (el batch es idempotente).
    clase_g7_id = db.execute(text(
        "INSERT INTO clases (tenant_id, horario_base_id, coach_id, disciplina_id, "
        "fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, "
        "cancelada) VALUES (:t, :h, :c, :d, :f, :hi, :hf, :cupo, :conf, FALSE) "
        "RETURNING id"),
        {"t": tenant["id"], "h": horario_id, "c": coach_id, "d": disciplina_id,
         "f": hoy, "hi": ini_t, "hf": fin_t, "cupo": n_alumnos + 20,
         "conf": n_alumnos}).scalar_one()

    insertar_lote(db, "reservas", [
        {"tenant_id": tenant["id"], "clase_id": clase_g7_id, "alumno_id": a["id"],
         "estado": "confirmada", "asistio": False, "tokens_gastados": 1,
         "suscripcion_id": susc.get(a["id"])} for a in alumnos])
    reservas_g7 = [r[0] for r in db.execute(text(
        "SELECT id FROM reservas WHERE clase_id = :c ORDER BY id"),
        {"c": clase_g7_id})]
    log(f"  clase G7 (coach): {clase_g7_id} con {len(reservas_g7)} reservas "
        "sin marcar")

    # ── 4) Bazar: producto propio + pedidos en cada estado que usan G3/G6 ──
    producto_id = db.execute(text(
        "INSERT INTO productos (tenant_id, nombre, descripcion, precio, stock, "
        "activo, stock_minimo, dias_anuncio) VALUES (:t, :n, :d, :pr, :st, TRUE, "
        "0, 0) RETURNING id"),
        {"t": tenant["id"], "n": PRODUCTO_NOMBRE, "pr": PRECIO_BAZAR,
         "d": "Producto de carga k6 (borrable)", "st": STOCK_INICIAL}).scalar_one()
    precio = PRECIO_BAZAR

    codigo_retiro = generar_codigo_unico(db, tenant["id"])
    insertar_lote(db, "pedidos", [
        {"tenant_id": tenant["id"], "alumno_id": a["id"], "producto_id": producto_id,
         "cantidad": 1, "total": precio, "estado": estado,
         "voucher_url": VOUCHER_URL, "codigo_retiro": codigo}
        for a, estado, codigo in [
            (alumnos[0], "validado", codigo_retiro),
            (alumnos[1], "pendiente", None),   # G3: entrega por código / rechazo
            (alumnos[2], "pendiente", None),   # G6: el admin lo aprueba
            (alumnos[3], "pendiente", None),   # G6: el admin lo rechaza
        ]])
    ids_pedidos = [r[0] for r in db.execute(text(
        "SELECT id FROM pedidos WHERE tenant_id = :t AND producto_id = :p "
        "ORDER BY id"), {"t": tenant["id"], "p": producto_id})]
    pedido_codigo_id = ids_pedidos[0]
    pedido_pendiente_id = ids_pedidos[1]
    pedido_voucher_aprobar_id = ids_pedidos[2]
    pedido_voucher_rechazar_id = ids_pedidos[3]
    # El alta por API descuenta stock al crear el pedido (pedidos.py:171-184). El
    # seed inserta directo, así que replica ese efecto: si no, el rechazo de G3
    # "devuelve" una unidad que nunca se descontó y el stock queda inflado (+1).
    db.execute(text(
        "UPDATE productos SET stock = stock - ("
        "  SELECT COALESCE(SUM(cantidad), 0) FROM pedidos WHERE producto_id = :p"
        ") WHERE id = :p"), {"p": producto_id})
    log(f"  bazar: producto {producto_id}, 4 pedidos "
        f"(validado {pedido_codigo_id} código {codigo_retiro})")

    # ── 5) Solicitud del plan elegido por cada alumno pendiente (cola de G8) ──
    # Es lo que el admin ve en la cola de activación: sin solicitud no hay plan.
    insertar_lote(db, "solicitudes_planes", [
        {"tenant_id": tenant["id"], "alumno_id": uid, "plan_id": plan["id"],
         "estado": "pending", "voucher_url": VOUCHER_URL,
         "precio_clp_snapshot": plan["precio_clp"]} for uid in pendientes])
    log(f"  pendiente_activacion: {len(pendientes)}")

    # G8 aprueba en carrera la solicitud de un TERCER pendiente (`pendientes[2]`):
    # la lista `solicitudes` de §6 es de los alumnos ya activos y la usan los
    # escenarios C y E, que ya la aprueban. Reutilizarla dejaría la carrera de G8
    # sin ganador (todos 400) y el verificador no mediría nada.
    solicitud_carrera_id = db.execute(text(
        "SELECT id FROM solicitudes_planes WHERE tenant_id = :t AND alumno_id = :u "
        "ORDER BY id DESC LIMIT 1"),
        {"t": tenant["id"], "u": pendientes[2]}).scalar_one()
    log(f"  solicitud de la carrera G8: {solicitud_carrera_id} "
        f"(alumno {pendientes[2]})")

    # ── 6) Solicitudes de plan `pending` para los escenarios C y E ──
    ids_solicitud = [a["id"] for a in alumnos[:N_SOLICITUDES]]
    insertar_lote(db, "solicitudes_planes", [
        {"tenant_id": tenant["id"], "alumno_id": uid, "plan_id": plan["id"],
         "estado": "pending", "voucher_url": VOUCHER_URL,
         "precio_clp_snapshot": plan["precio_clp"],
         "created_at": ahora - timedelta(hours=1)} for uid in ids_solicitud])
    solicitudes = [{"solicitud_id": r[0], "alumno_id": r[1]}
                   for r in db.execute(text(
                       "SELECT id, alumno_id FROM solicitudes_planes "
                       "WHERE tenant_id = :t AND alumno_id = ANY(:ids) "
                       "ORDER BY id"),
                       {"t": tenant["id"], "ids": ids_solicitud})]
    log(f"  solicitudes de plan pending: {len(solicitudes)}")

    # ── 7) Historial de RM del grupo 'vol' (F1): 20 alumnos × 20 filas ──
    filas_rm = []
    if con_historial:
        for k, a in enumerate(alumnos[:N_VOL]):
            for j in range(N_HISTORIAL):
                filas_rm.append({
                    "tenant_id": tenant["id"], "alumno_id": a["id"],
                    "movimiento_id": mov_f1, "peso_kg": 40.0 + k + j * 2.5,
                    "fecha": hoy - timedelta(days=((N_HISTORIAL - 1 - j) * 7) + 1),
                    "tipo_rm": "peso",
                })
        insertar_lote(db, "historial_rm", filas_rm)
        log(f"  historial_rm: {len(filas_rm)} filas")

    return {"ahora": ahora, "hoy": hoy, "admin_id": admin_id, "coach_id": coach_id,
            "alumnos": alumnos, "clase_id": clase_id,
            "horario_creado": horario_creado, "admin_correo": admin_correo,
            "coach_correo": coach_correo, "producto_id": producto_id,
            "pedido_codigo_id": pedido_codigo_id, "codigo_retiro": codigo_retiro,
            "pedido_pendiente_id": pedido_pendiente_id,
            "pedido_voucher_aprobar_id": pedido_voucher_aprobar_id,
            "pedido_voucher_rechazar_id": pedido_voucher_rechazar_id,
            "clase_g7_id": clase_g7_id, "reservas_g7": reservas_g7,
            "solicitud_carrera_id": solicitud_carrera_id,
            "pendientes": pendientes, "solicitudes": solicitudes,
            "filas_rm": len(filas_rm)}


# ── Códigos de referido (G4) ──────────────────────────────────────────────────
def sembrar_codigos_referido(db, alumno_ids: list[int]) -> int:
    """Crea un `codigos_referido` por alumno con la MISMA función del alta real.

    Se usa el servicio (`asignar_codigo_referido`) y no un INSERT a mano: si el
    formato del código cambia, el seed sigue generando códigos válidos.
    """
    usuarios = db.query(Usuario).filter(Usuario.id.in_(alumno_ids)).all()
    creados = 0
    for usuario in usuarios:
        if asignar_codigo_referido(db, usuario) is not None:
            creados += 1
    return creados


# ── Tokens y config para k6 ───────────────────────────────────────────────────
def construir_tokens(alumnos: list[dict], tenant_id: int, horas: int) -> list[dict]:
    """tokens.json con los grupos que filtran los escenarios.

    - `alumno`: la lista base (G1, G4, B, D, E indexan tokens[__VU-1]).
    - `vol`:    los primeros N_VOL, para F1 (`tokens.filter(t => t.grupo==='vol')`).
    - `conc`:   todos, para F2 (`grupo==='conc'`). Para 500 VUs de F2 hay que
                sembrar con `--alumnos 500`.
    """
    base, vol, conc = [], [], []
    for a in alumnos:
        token = create_access_token(
            {"usuario_id": a["id"], "tenant_id": tenant_id, "rol": "alumno",
             "correo": a["correo"], "nombre": a["nombre"]},
            expires_delta=timedelta(hours=horas))
        entrada = {"alumno_id": a["id"], "token": token, "correo": a["correo"]}
        base.append({**entrada, "grupo": "alumno"})
        conc.append({**entrada, "grupo": "conc"})
    for entrada in base[:N_VOL]:
        vol.append({**entrada, "grupo": "vol"})
    return base + vol + conc


def construir_config(*, base_url: str, tenant: dict, plan: dict, disco: dict,
                     mov_f1: int, mov_g1: int, disciplina_id: int,
                     n_alumnos: int, admin_token: str, coach_token: str) -> dict:
    """Todas las claves que leen lib/config.js y lib/config_flujos.js."""
    return {
        "base_url": base_url,
        # ── tenant ──
        "tenant_id": tenant["id"],
        "tenant_public_id": tenant["public_id"],
        "tenant_subdominio": tenant["subdomain"],
        # ── arnés previo (A-E, F1, F2) ──
        "n_alumnos": n_alumnos,
        "clase_id": disco["clase_id"],
        "product_id": disco["producto_id"],
        "stock_inicial": STOCK_INICIAL,
        "plan_pago_id": plan["id"],
        "password": PASSWORD,
        "mov_f1": mov_f1,
        "mov_g1": mov_g1,
        "historial_rows": N_HISTORIAL,
        "solicitudes": disco["solicitudes"],
        # ── flujos nuevos (G1-G8) ──
        "clase_qr_id": disco["clase_id"],
        "disciplina_id": disciplina_id,
        "pedido_codigo": disco["codigo_retiro"],
        "pedido_pendiente_id": disco["pedido_pendiente_id"],
        "pedido_voucher_aprobar_id": disco["pedido_voucher_aprobar_id"],
        "pedido_voucher_rechazar_id": disco["pedido_voucher_rechazar_id"],
        # ── G7: pestaña Asistencia del coach (clase propia, ver sembrar 3b) ──
        "clase_g7_id": disco["clase_g7_id"],
        "reservas_g7": disco["reservas_g7"],
        # ── G8: cola de activación (un alumno por camino) ──
        # `solicitud_carrera_id` es la de un `pendiente_activacion` que NO usan ni
        # C/E (ellos aprueban las de los alumnos activos) ni los otros caminos de G8.
        "solicitud_carrera_id": disco["solicitud_carrera_id"],
        "alumno_activar_id": disco["pendientes"][1],
        "alumno_para_wods": disco["alumnos"][0]["id"],
        # pendientes[0] queda reservado al rechazo de G8; la activación usa el resto.
        "alumnos_pendientes_activacion": disco["pendientes"][1:],
        "alumno_rechazo_activacion": disco["pendientes"][0],
        # ── credenciales de staff ──
        "admin_id": disco["admin_id"],
        "coach_id": disco["coach_id"],
        "admin_correo": disco["admin_correo"],
        "coach_correo": disco["coach_correo"],
        "admin_token": admin_token,
        "coach_token": coach_token,
        # ── metadata del seed ──
        "seed": {
            "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bd": resumen_bd(),
            "tenant_nombre": tenant["nombre"],
            "n_alumnos": n_alumnos,
            "n_grupo_vol": min(N_VOL, n_alumnos),
            "filas_historial_rm": disco["filas_rm"],
            "horario_creado": disco["horario_creado"],
            "n_solicitudes_pending": len(disco["solicitudes"]),
            "n_pendientes_activacion": len(disco["pendientes"]),
        },
    }


def leer_json(ruta: Path) -> dict:
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def escribir_json(ruta: Path, datos) -> None:
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


# ── CLI / main ────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Siembra el dataset de carga k6 en la BD de TEST.")
    p.add_argument("--alumnos", type=int, default=200,
                   help="cantidad de alumnos con suscripción activa (default 200)")
    p.add_argument("--subdominio", default="maipu",
                   help="subdominio del tenant de TEST (default maipu)")
    p.add_argument("--plan-id", type=int, default=None,
                   help="plan de pago a usar (default: el primero activo != Prueba)")
    p.add_argument("--sin-historial", action="store_true",
                   help="no sembrar historial_rm (seed rápido)")
    p.add_argument("--solo-limpiar", action="store_true",
                   help="borrar el seed anterior y salir, sin sembrar")
    p.add_argument("--horas-token", type=int, default=12,
                   help="vigencia de los JWT de tokens.json (default 12 h)")
    p.add_argument("--base-url", default="http://localhost:8000",
                   help="base_url que se escribe en load_config.json")
    args = p.parse_args()
    if not args.solo_limpiar and args.alumnos < N_SOLICITUDES:
        p.error(f"--alumnos debe ser >= {N_SOLICITUDES} (solicitudes/pedidos del seed)")
    return args


def main() -> int:
    args = parse_args()
    log("=" * 78)
    log("SEED DE CARGA k6 — SÓLO BASE DE DATOS DE TEST")
    log("=" * 78)

    # 🔒 PRIMER chequeo, antes de abrir sesión o tocar una sola fila.
    if not is_test_db_url(settings.DATABASE_URL):
        log(f"ABORTADO: DATABASE_URL NO es de TEST → {resumen_bd()}")
        log("El seed escribe datos: se niega a correr contra producción.")
        log("Revisa backend/.env (o .env.test) y confirma que la app en :8000 "
            "apunta a TEST.")
        return 2
    log(f"BD: {resumen_bd()}  (TEST confirmado)")

    cfg_path = K6_DIR / "load_config.json"
    tokens_path = K6_DIR / "tokens.json"
    previo = leer_json(cfg_path)
    horario_previo = (previo.get("seed") or {}).get("horario_creado")

    with SessionLocal() as db:
        tenant = resolver_tenant(db, args.subdominio)
        log(f"Tenant: id={tenant['id']} «{tenant['nombre']}» "
            f"(subdominio {tenant['subdomain']})")

        # ── Limpieza idempotente ──
        log("\nLimpiando el seed anterior (sólo filas carga_k6_* / CARGA_K6*):")
        borradas = limpiar(db, tenant["id"], horario_previo)
        for nombre, filas in borradas:
            if filas:
                log(f"  - {nombre}: {filas}")
        if args.solo_limpiar:
            db.commit()
            log("\n--solo-limpiar: seed borrado, no se sembró nada.")
            return 0

        # ── Catálogos reales del box ──
        plan = resolver_plan(db, tenant["id"], args.plan_id)
        mov_f1, mov_g1 = resolver_movimientos(db, tenant["id"])
        disciplina_id = resolver_disciplina(db, tenant["id"])
        log(f"\nPlan: {plan['id']} «{plan['nombre']}» ({plan['creditos']} créditos)")
        log(f"Movimientos fuerza: F1={mov_f1} / G1={mov_g1} | "
            f"Disciplina: {disciplina_id}")

        # ── Siembra ──
        log("\nSembrando:")
        disco = sembrar(db, tenant=tenant, plan=plan, mov_f1=mov_f1,
                        mov_g1=mov_g1, disciplina_id=disciplina_id,
                        n_alumnos=args.alumnos,
                        con_historial=not args.sin_historial)
        n_codigos = sembrar_codigos_referido(
            db, [a["id"] for a in disco["alumnos"][:N_D]])
        db.commit()

    # ── Tokens (fuera de la sesión: ya está todo commiteado) ──
    expira = timedelta(hours=args.horas_token)
    tokens = construir_tokens(disco["alumnos"], tenant["id"], args.horas_token)
    admin_token = create_access_token(
        {"usuario_id": disco["admin_id"], "tenant_id": tenant["id"],
         "rol": "administrador", "correo": disco["admin_correo"],
         "nombre": "Carga K6 Admin"}, expires_delta=expira)
    coach_token = create_access_token(
        {"usuario_id": disco["coach_id"], "tenant_id": tenant["id"],
         "rol": "coach", "correo": disco["coach_correo"],
         "nombre": "Carga K6 Coach"}, expires_delta=expira)

    nuevo = construir_config(
        base_url=args.base_url, tenant=tenant, plan=plan, disco=disco,
        mov_f1=mov_f1, mov_g1=mov_g1, disciplina_id=disciplina_id,
        n_alumnos=args.alumnos, admin_token=admin_token, coach_token=coach_token)
    # Claves legacy del arnés previo (n_d/n_vol/n_conc/n_a…) que el usuario
    # hubiera calibrado a mano: se conservan salvo que el seed las recalcule.
    config = {"n_d": N_D, "n_vol": min(N_VOL, args.alumnos),
              "n_conc": args.alumnos, "n_a": 40, **previo, **nuevo}

    escribir_json(tokens_path, tokens)
    escribir_json(cfg_path, config)

    # ── Resumen ──
    log("\nSembrado:")
    log(f"  usuarios: 1 admin + 1 coach + {args.alumnos} alumnos "
        f"(+{N_PENDIENTES} pendiente_activacion)")
    log(f"  clase de hoy: id={disco['clase_id']} con {args.alumnos} reservas")
    log(f"  bazar: producto id={disco['producto_id']} | pedido validado "
        f"id={disco['pedido_codigo_id']} código {disco['codigo_retiro']}")
    log(f"  pedidos pendientes: {disco['pedido_pendiente_id']} (G3), "
        f"{disco['pedido_voucher_aprobar_id']} / "
        f"{disco['pedido_voucher_rechazar_id']} (G6)")
    log(f"  solicitudes de plan pending: {len(disco['solicitudes'])} | "
        f"códigos de referido: {n_codigos}")
    log(f"  historial_rm: {disco['filas_rm']} filas (grupo 'vol')")
    log(f"  tokens.json: {len(tokens)} entradas "
        f"(alumno={args.alumnos}, vol={min(N_VOL, args.alumnos)}, "
        f"conc={args.alumnos}) — vencen en {args.horas_token} h")
    log(f"\nEscrito:\n  {tokens_path}\n  {cfg_path}")
    if args.alumnos < 500:
        log(f"\nAVISO: F2 (concurrencia) usa 500 VUs; con --alumnos {args.alumnos} "
            f"sólo hay {args.alumnos} tokens 'conc'. Para F2 full: --alumnos 500.")
    log("\nListo. k6 pega contra el backend en TEST (:8000), no contra la BD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
