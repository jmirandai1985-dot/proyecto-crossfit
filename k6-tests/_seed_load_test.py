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
   Además siembra lo que necesitan los flujos G9-G14 (§10 de FLUJOS_NUEVOS.md):
   alumno del checkout recurrente, correos de las altas end-to-end, invitador +
   invitados de referidos y su escalera de tramos (dato de PRUEBA), candidatos
   del padrón con promoción de recuperación (uno vencido a propósito), WOD
   publicado con su clase de hoy y reservas asistidas, y una cola de activación
   propia para G14.

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
import uuid
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
PASSWORD = settings.TEST_SEED_PASSWORD  # la usan test_500_logins.js y scenario_e_mix.js
if not PASSWORD:
    # Auditoría 4.1: la clave ya no se versiona; se lee de backend/.env.test.
    sys.exit(
        "FATAL: define TEST_SEED_PASSWORD (backend/.env.test o variable de entorno) "
        "antes de sembrar los usuarios de carga."
    )
SANTIAGO = ZoneInfo("America/Santiago")

# Los logs llevan '·', '→' y '—'. Con stdout redirigido a un archivo, Windows usa
# cp1252 y un carácter fuera de esa tabla lanza UnicodeEncodeError EN MEDIO del
# seed (nos pasó con '→': el `except` de un helper se lo tragó y G9 quedó sin
# comprador de prueba). Mismo blindaje que `_verificar_escenarios.py`.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


N_VOL = 20                 # alumnos con historial de RM (grupo 'vol' de F1)
N_HISTORIAL = 20           # filas de historial_rm por alumno 'vol'
N_SOLICITUDES = 20         # solicitudes de plan 'pending' (escenarios C y E)
N_PENDIENTES = 20          # alumnos 'pendiente_activacion' (escenario G8)
N_D = 20                   # default de n_d / n_vol / n_conc / n_a si no existían
STOCK_INICIAL = 100
PRECIO_BAZAR = 10_000.0
VOUCHER_URL = "/privado/vouchers/carga_k6_voucher.jpg"  # ruta ficticia del seed

# ── Flujos G9-G14 (ver FLUJOS_NUEVOS.md §10) ─────────────────────────────────
N_G9 = 5                   # VUs que piden el MISMO checkout recurrente (1 alumno)
N_G10 = 5                  # altas end-to-end del escenario G10 (un correo por VU)
N_G11 = 3                  # invitados que convierten el código del invitador A
N_G12 = 3                  # candidatos de recuperación VIGENTES (+1 vencido)
N_G13 = 5                  # alumnos del ciclo de WODs
N_G14 = 3                  # alumnos pendiente_activacion del flujo completo
# Alumnos en la clase de G7. `POST /asistencia/clases/{id}/confirmar` hace UN
# UPDATE por reserva (ORM) y el escenario lo repite con 5 VUs: con las 500
# reservas del seed cada request pasaba los 60 s de timeout de k6 (medido el
# 2026-11-13) y quedaban 5 timeouts de cliente. 30 es un tamaño de clase real y
# mantiene el flujo (el verificador lee `reservas_g7`, no un número fijo).
N_G7_ALUMNOS = 30
# Los correos que pasan por POST /registro/alumno-nuevo NO pueden ser @load.test:
# el schema usa EmailStr y pydantic rechaza los dominios reservados (.test,
# .example, .invalid). `k6load.com` es sintácticamente válido y no se resuelve
# (pydantic no chequea DNS). Todos empiezan con `carga_k6_` para que la limpieza
# los borre igual que a los demás datos del seed.
DOMINIO_K6 = "k6load.com"
PREFIJO_G10 = "carga_k6_g10_"
PREFIJO_G11_ALTA = "carga_k6_g11_alta_"
PREFIJO_G12 = "carga_k6_g12_"
# Tipos de premio válidos del enum `tipo_premio_referido` (para la escalera G11).
TRAMOS_G11 = ((1, "dias_gratis", 1), (2, "dias_gratis", 3), (3, "mes_gratis", None))
# Id de un pago REAL de la cuenta TEST de Mercado Pago, sólo como fallback si la
# consulta de sólo lectura falla (`_ultimo_pago_mp`). El webhook RELÉE el pago en
# MP; con un id que MP no conoce el evento queda `resultado='error'` pendiente de
# reconciliación, con uno real cierra como `desconocido` (no hay fila en `pagos`).
MP_PAYMENT_ID_FALLBACK = "186288429133"


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
def limpiar(conn, tenant_id: int, horario_id_previo: int | None,
            notificacion_previa: str | None = None,
            tramos_previos: list[int] | None = None,
            alumno_g9_previo: int | None = None) -> list[tuple[str, int]]:
    """Borra el seed previo respetando las FKs sin ON DELETE CASCADE.

    Sólo toca filas del seed (correos `carga_k6_*`, producto `CARGA_K6*`, WODs
    `K6 G13*`): nunca alumnos reales del box. `usuarios` va al final porque casi
    todo cuelga de él; `horarios_base.coach_id`, `notificaciones.alumno_id` y
    `solicitudes_planes` NO tienen CASCADE y hay que borrarlos a mano.

    `notificacion_previa` y `tramos_previos` salen del load_config anterior: son
    las dos filas que el seed NO puede volver a crear con el mismo valor (el
    `notificacion_id` del webhook es UNIQUE — si quedara, G9b siempre vería
    "duplicado"— y los tramos de la escalera G11 se borran sólo si los creó este
    seed, para no tocar una escalera real del box).
    """
    params = {"t": tenant_id, "p": f"{PREFIJO_CORREO}%", "p2": "CARGA_K6%",
              "h": horario_id_previo or -1, "nid": notificacion_previa or "",
              "tramos": list(tramos_previos or []),
              "g9": alumno_g9_previo or -1}
    # El alumno de G9 puede tener un correo SIN el prefijo (comprador de prueba
    # de MP): además del LIKE se borra por el id que dejó el seed anterior.
    sel_usuarios = ("SELECT id FROM usuarios WHERE tenant_id = :t "
                    "AND (correo LIKE :p OR id = :g9)")
    sel_candidatos = ("SELECT id FROM candidatos_boxmagic "
                      "WHERE tenant_id = :t AND correo LIKE :p")
    pasos: list[tuple[str, str]] = [
        # ── G9-G14: hijos de usuarios (mismo orden que sus FKs) ──
        ("premios_tramo_ciclo (G11)",
         "DELETE FROM premios_tramo_ciclo WHERE usuario_id IN (%s)"
         % sel_usuarios),
        ("creditos_referido (G11)",
         "DELETE FROM creditos_referido WHERE usuario_id IN (%s)" % sel_usuarios),
        ("referidos_aplicados (G11)",
         "DELETE FROM referidos_aplicados WHERE usuario_invitador_id IN (%s) "
         "OR usuario_invitado_id IN (%s)" % (sel_usuarios, sel_usuarios)),
        ("beneficios (G12)",
         "DELETE FROM beneficios WHERE alumno_id IN (%s)" % sel_usuarios),
        ("promociones_recuperacion (G12)",
         "DELETE FROM promociones_recuperacion WHERE usuario_id IN (%s) "
         "OR candidato_id IN (%s)" % (sel_usuarios, sel_candidatos)),
        ("wod_resultados (G13)",
         "DELETE FROM wod_resultados WHERE alumno_id IN (%s)" % sel_usuarios),
        # ── los de siempre ──
        ("solicitudes_planes (alumno/aprobador)",
         "DELETE FROM solicitudes_planes WHERE alumno_id IN (%s) "
         "OR aprobado_por IN (%s)" % (sel_usuarios, sel_usuarios)),
        ("notificaciones", "DELETE FROM notificaciones WHERE alumno_id IN (%s)"
         % sel_usuarios),
        ("notificaciones_enviadas",
         "DELETE FROM notificaciones_enviadas WHERE alumno_id IN (%s) "
         "OR destinatario_correo LIKE :p" % sel_usuarios),
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
        ("coach_disciplinas (G13)",
         "DELETE FROM coach_disciplinas WHERE coach_id IN (%s)" % sel_usuarios),
        ("clases (del coach del seed)",
         "DELETE FROM clases WHERE coach_id IN (%s)" % sel_usuarios),
        ("horarios_base (del coach del seed)",
         "DELETE FROM horarios_base WHERE coach_id IN (%s)" % sel_usuarios),
        # Sólo se borra el horario si lo creó este seed (queda anotado en el config).
        ("horarios (creado por el seed)",
         "DELETE FROM horarios WHERE id = :h AND tenant_id = :t"),
        ("usuarios", "DELETE FROM usuarios WHERE tenant_id = :t "
         "AND (correo LIKE :p OR id = :g9)"),
        ("candidatos_boxmagic (G12)",
         "DELETE FROM candidatos_boxmagic WHERE tenant_id = :t AND correo LIKE :p"),
        ("wods del escenario G13",
         "DELETE FROM wods WHERE tenant_id = :t "
         "AND (titulo LIKE 'K6 G13%' OR titulo LIKE 'G13 K6%')"),
        ("tramos_referido (G11, sólo los del seed)",
         "DELETE FROM tramos_referido WHERE id = ANY(:tramos)"),
        ("pagos_eventos (G9b, webhook de la corrida anterior)",
         "DELETE FROM pagos_eventos WHERE notificacion_id = :nid"),
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


def resolver_plan_prueba(conn, tenant_id: int) -> int:
    """`planes.id` del plan "Prueba" (lo crea el alta pública si falta)."""
    fila = conn.execute(text(
        "SELECT id FROM planes WHERE tenant_id = :t AND nombre = 'Prueba' "
        "ORDER BY id LIMIT 1"), {"t": tenant_id}).first()
    if fila:
        return fila[0]
    return conn.execute(text(
        "INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, "
        "precio_clp, duracion_dias, activo) "
        "VALUES (:t, 'Prueba', 1, FALSE, 0, 7, TRUE) RETURNING id"),
        {"t": tenant_id}).scalar_one()


def _mp_test_user(previo: str | None = None, timeout: float = 20.0) -> str | None:
    """Email de un COMPRADOR de prueba de la cuenta TEST de MP (para G9a).

    `POST /preapproval` del sandbox exige que `payer_email` sea un usuario real o
    de prueba **distinto del cobrador**: un correo cualquiera (`@load.test`,
    `@k6load.com`) devuelve 400 "Both payer and collector must be real or test
    users" y el endpoint responde 503 sin crear nada. Por eso el alumno de G9 se
    siembra con el correo de un comprador de prueba:

    1. `MERCADOPAGO_TEST_BUYER_EMAIL` del entorno, si está definido;
    2. el que dejó el seed anterior en `load_config.json` (se REUSA: no se crea
       un usuario de prueba nuevo en cada corrida);
    3. si no hay ninguno, `POST /users/test_user` (sandbox) una sola vez.

    Si MP no está disponible devuelve `None` y el seed usa el correo `carga_k6_*`
    de siempre: G9a medirá entonces el fail-closed (503) del endpoint.
    """
    if not settings.MERCADOPAGO_HABILITADO or not settings.MERCADOPAGO_ACCESS_TOKEN:
        return None
    configurado = (settings.MERCADOPAGO_TEST_BUYER_EMAIL or "").strip()
    if configurado:
        return configurado
    # Ojo: NO reusar el valor de respaldo (`carga_k6_g9@load.test`), o el seed
    # se quedaría pegado al fallback para siempre.
    fallback = f"{PREFIJO_CORREO}g9@load.test"
    if previo and previo != fallback:
        return previo
    try:
        import httpx
        respuesta = httpx.post(
            "https://api.mercadopago.com/users/test_user",
            params={"access_token": settings.MERCADOPAGO_ACCESS_TOKEN},
            json={"site_id": "MLC"}, timeout=timeout)
        if respuesta.status_code not in (200, 201):
            raise RuntimeError(f"HTTP {respuesta.status_code}: {respuesta.text[:120]}")
        correo = str((respuesta.json() or {}).get("email") or "").strip()
        if correo:
            log(f"  MP: comprador de prueba creado para G9 -> {correo}")
            return correo
        return None
    except Exception as error:  # noqa: BLE001 - el seed no depende de MP
        log(f"  AVISO: no se pudo crear un comprador de prueba de MP "
            f"({type(error).__name__}: {error}); G9a usará el correo carga_k6_* "
            f"y medirá el fail-closed (503)")
        return None


def _ultimo_pago_mp(timeout: float = 8.0) -> str | None:
    """Id de un pago REAL de la cuenta TEST de MP (SÓLO LECTURA, GET /v1/payments).

    G9b manda un webhook firmado con ese `data.id`: el backend RELÉE el pago en
    MP (`payment().get`), así que con un id inventado el evento queda
    `resultado='error'` y pendiente de reconciliación. Con uno real el evento
    cierra como `desconocido` (no hay fila en `pagos` para ese
    `external_reference`) sin tocar datos de negocio, que es lo que se quiere
    medir. Nunca crea ni modifica nada en MP; si falla, se usa el fallback.
    """
    token = (settings.MERCADOPAGO_ACCESS_TOKEN or "").strip()
    if not token or not settings.MERCADOPAGO_HABILITADO:
        return None
    try:
        import httpx
        respuesta = httpx.get(
            "https://api.mercadopago.com/v1/payments/search",
            params={"sort": "date_created", "criteria": "desc", "limit": 1},
            headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        if respuesta.status_code != 200:
            raise RuntimeError(f"HTTP {respuesta.status_code}")
        resultados = (respuesta.json() or {}).get("results") or []
        if resultados and resultados[0].get("id") is not None:
            return str(resultados[0]["id"])
        return None
    except Exception as error:  # noqa: BLE001 - el seed no depende de MP
        log(f"  AVISO: no se pudo leer un pago de MP ({type(error).__name__}: "
            f"{error}); se usa el id de respaldo {MP_PAYMENT_ID_FALLBACK}")
        return None



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
            disciplina_id: int, n_alumnos: int, con_historial: bool,
            mp_payer: str | None = None) -> dict:
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
    #
    # ⚠️ Además la ventana del QR es `[hora_inicio - 60 min, hora_fin)`: si la
    # clase de G7 tuviera el MISMO horario (lo tenía) y los mismos 500 alumnos,
    # el check-in de TODOS respondería `ambiguo` y G1 no marcaría a nadie. Por
    # eso G7 termina unos minutos ANTES de que arranque esa ventana: el coach
    # igual puede marcar (el backend exige el mismo DÍA, no la hora) y el QR ve
    # una sola clase en curso. De madrugada (fin - 65 min cae ayer) se usa una
    # clase que empieza después de que la ventana del QR se cierre.
    ini_g7_dt = ahora - timedelta(minutes=65)
    fin_g7_dt = ahora - timedelta(minutes=5)
    if ini_g7_dt.date() != hoy:
        # Madrugada: una clase que EMPIEZA después de que la ventana del QR se
        # cierre (la ventana arranca 60 min antes y termina +50 min).
        ini_g7_dt = ahora + timedelta(minutes=75)
        fin_g7_dt = ahora + timedelta(minutes=135)
    ini_g7_t = ini_g7_dt.time().replace(second=0, microsecond=0)
    fin_g7_t = fin_g7_dt.time().replace(second=0, microsecond=0)
    clase_g7_id = db.execute(text(
        "INSERT INTO clases (tenant_id, horario_base_id, coach_id, disciplina_id, "
        "fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, "
        "cancelada) VALUES (:t, :h, :c, :d, :f, :hi, :hf, :cupo, :conf, FALSE) "
        "RETURNING id"),
        {"t": tenant["id"], "h": horario_id, "c": coach_id, "d": disciplina_id,
         "f": hoy, "hi": ini_g7_t, "hf": fin_g7_t, "cupo": n_alumnos + 20,
         "conf": min(n_alumnos, N_G7_ALUMNOS)}).scalar_one()

    insertar_lote(db, "reservas", [
        {"tenant_id": tenant["id"], "clase_id": clase_g7_id, "alumno_id": a["id"],
         "estado": "confirmada", "asistio": False, "tokens_gastados": 1,
         "suscripcion_id": susc.get(a["id"])}
        for a in alumnos[:min(n_alumnos, N_G7_ALUMNOS)]])
    reservas_g7 = [r[0] for r in db.execute(text(
        "SELECT id FROM reservas WHERE clase_id = :c ORDER BY id"),
        {"c": clase_g7_id})]
    log(f"  clase G7 (coach): {clase_g7_id} ({ini_g7_t}-{fin_g7_t}) con "
        f"{len(reservas_g7)} reservas sin marcar")


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

    # ══ 8) Flujos G9-G14 (ver FLUJOS_NUEVOS.md §10) ══════════════════════════
    # Correos de las altas que hace el ESCENARIO (no se crean acá: el escenario
    # las registra por API). Son ESTABLES para que el verificador y la limpieza
    # los encuentren; tienen que ser de un dominio no reservado (EmailStr).
    correos_g10 = [f"{PREFIJO_G10}{i:02d}@{DOMINIO_K6}"
                   for i in range(1, N_G10 + 1)]
    correos_g11_alta = [f"{PREFIJO_G11_ALTA}{i:02d}@{DOMINIO_K6}"
                        for i in range(1, N_G11 + 1)]

    # ── 8a) Usuarios propios de G9/G11/G13/G14 ──
    # El alumno de G9 usa el correo del COMPRADOR de prueba de MP (el sandbox no
    # acepta un payer_email que no sea usuario real/de prueba); si MP no está
    # disponible, cae al correo carga_k6_* y G9a medirá el 503 fail-closed.
    correo_g9 = mp_payer or f"{PREFIJO_CORREO}g9@load.test"
    correo_g11a = f"{PREFIJO_CORREO}g11a@load.test"
    correos_g11_inv = [f"{PREFIJO_CORREO}g11inv{i:02d}@load.test"
                       for i in range(1, N_G11 + 1)]
    correos_g13 = [f"{PREFIJO_CORREO}g13a{i:02d}@load.test"
                   for i in range(1, N_G13 + 1)]
    correos_g14 = [f"{PREFIJO_CORREO}g14p{i:02d}@load.test"
                   for i in range(1, N_G14 + 1)]
    correos_extra = ([correo_g9, correo_g11a] + correos_g11_inv
                     + correos_g13 + correos_g14)
    ruts_extra = ruts_libres(db, tenant["id"], len(correos_extra))
    extras = []
    for k, correo in enumerate(correos_extra):
        es_pendiente = correo in correos_g14
        es_invitado = correo in correos_g11_inv
        extras.append(fila_usuario(
            ruts_extra[k], nombre_por_indice(k + 1), correo, "alumno",
            activo=not es_pendiente,
            estado="pendiente_activacion" if es_pendiente else "activo",
            cambiar_pw=es_pendiente,
            # Sin peso los pendientes (no tienen plan) y los invitados de G11
            # (su Prueba no clasifica fuerza: no los usa el motor de niveles).
            peso=None if (es_pendiente or es_invitado) else 70.0,
            genero="M" if k % 2 else "F"))
    insertar_lote(db, "usuarios", extras, casts={"rol": "rol_usuario"})
    log(f"  flujos G9-G14: {len(extras)} usuarios (1 G9, 1 invitador G11, "
        f"{N_G11} invitados, {N_G13} de G13, {N_G14} pendiente_activacion)")

    ids_extra = {r[0]: r[1] for r in db.execute(text(
        "SELECT correo, id FROM usuarios WHERE tenant_id = :t "
        "AND correo = ANY(:c)"), {"t": tenant["id"], "c": correos_extra})}
    alumno_g9 = ids_extra[correo_g9]
    invitador_g11 = ids_extra[correo_g11a]
    invitados_g11 = [ids_extra[c] for c in correos_g11_inv]
    alumnos_g13 = [ids_extra[c] for c in correos_g13]
    pendientes_g14 = [ids_extra[c] for c in correos_g14]


    # ── 8b) Suscripciones ──
    # G9/G11A/G13: plan de pago → `require_full_access` deja pasar los endpoints
    # de pago. G11 invitados: plan "Prueba" (0 $, 7 días) para que su compra sea
    # la PRIMERA PAGA (`es_primera_compra_pagada`) y la conversión del referido
    # aplique. G14 no lleva suscripción: el admin se la activa en el escenario.
    plan_prueba_id = resolver_plan_prueba(db, tenant["id"])
    con_plan_pago = [alumno_g9, invitador_g11] + alumnos_g13
    insertar_lote(db, "suscripciones", [
        {"tenant_id": tenant["id"], "usuario_id": uid, "plan_id": plan["id"],
         "estado": "activo", "creditos_totales": plan["creditos"],
         "creditos_disponibles": plan["creditos"],
         "fecha_inicio": inicio, "fecha_expiracion": fin,
         "aprobado_por": admin_id} for uid in con_plan_pago
    ] + [
        {"tenant_id": tenant["id"], "usuario_id": uid,
         "plan_id": plan_prueba_id, "estado": "activo",
         "creditos_totales": 1, "creditos_disponibles": 1,
         "fecha_inicio": inicio, "fecha_expiracion": ahora + timedelta(days=7),
         "aprobado_por": admin_id} for uid in invitados_g11
    ], casts={"estado": "estado_suscripcion"})
    log(f"  suscripciones G9-G14: {len(con_plan_pago)} de pago + "
        f"{len(invitados_g11)} de prueba (invitados G11)")

    # ── 8c) G13: WOD publicado + clase de HOY con la asistencia YA marcada ──
    # `GET /me/wods-pendientes` exige reserva propia con `asistio=True` para una
    # clase del WOD que haya empezado en las últimas 48 h: por eso la clase se
    # siembra con la misma ventana que la del QR (empezada hace 10 min).
    wod_g13 = db.execute(text(
        "INSERT INTO wods (tenant_id, fecha, titulo, wod_principal, tipo_metcon, "
        "coach_id, estado, activo) VALUES (:t, :f, 'G13 K6 WOD', "
        "'AMRAP 12: 10 burpees / 15 KB swing', 'AMRAP 12', :c, 'publicado', TRUE) "
        "RETURNING id"),
        {"t": tenant["id"], "f": hoy, "c": coach_id}).scalar_one()

    def _insertar_clase_g13(cupo: int, confirmados: int, wod_id):
        return db.execute(text(
            "INSERT INTO clases (tenant_id, horario_base_id, coach_id, "
            "disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, "
            "asistentes_confirmados, cancelada, wod_id) "
            "VALUES (:t, :h, :c, :d, :f, :hi, :hf, :cupo, :conf, FALSE, :w) "
            "RETURNING id"),
            {"t": tenant["id"], "h": horario_id, "c": coach_id, "d": disciplina_id,
             "f": hoy, "hi": ini_t, "hf": fin_t, "cupo": cupo,
             "conf": confirmados, "w": wod_id}).scalar_one()

    clase_g13 = _insertar_clase_g13(N_G13 + 5, N_G13, wod_g13)
    # Segunda clase del MISMO día, vacía y sin WOD: la usa el sub-escenario
    # "coach" para asignarle el WOD que crea y publica por API. Así la clase de
    # los alumnos queda intacta aunque el coach falle a mitad de camino.
    clase_g13_coach = _insertar_clase_g13(10, 0, None)
    susc_g13 = {r[0]: r[1] for r in db.execute(text(
        "SELECT usuario_id, id FROM suscripciones WHERE tenant_id = :t "
        "AND usuario_id = ANY(:ids)"), {"t": tenant["id"], "ids": alumnos_g13})}
    insertar_lote(db, "reservas", [
        {"tenant_id": tenant["id"], "clase_id": clase_g13, "alumno_id": uid,
         "estado": "confirmada", "asistio": True, "tokens_gastados": 1,
         "suscripcion_id": susc_g13.get(uid)} for uid in alumnos_g13])
    log(f"  G13: WOD {wod_g13} publicado + clase {clase_g13} con "
        f"{len(alumnos_g13)} reservas asistidas (clase coach {clase_g13_coach})")

    # El coach del seed necesita la disciplina para crear/asignar WODs por API
    # (`verificar_coach_disciplina`). Sólo para G13: el resto usa el admin.
    db.execute(text(
        "INSERT INTO coach_disciplinas (tenant_id, coach_id, disciplina_id, activo) "
        "VALUES (:t, :c, :d, TRUE)"), {"t": tenant["id"], "c": coach_id,
                                       "d": disciplina_id})


    # ── 8d) G12: candidatos del padrón + promociones `enviada` ──
    # Uno de los candidatos queda con la promoción YA VENCIDA a propósito: el
    # registro de ese correo NO debe marcarlo recuperado (`vence_en > ahora`).
    candidatos_g12 = []
    for i in range(1, N_G12 + 1):
        correo = f"{PREFIJO_G12}cand{i:02d}@{DOMINIO_K6}"
        es_clases = i % 2 == 1
        tipo = "dias_gratis" if es_clases else "descuento_porcentaje"
        cantidad = 2 if es_clases else 15
        candidato_id = db.execute(text(
            "INSERT INTO candidatos_boxmagic (tenant_id, nombre, correo, "
            "estado_boxmagic, grupo) VALUES (:t, :n, :c, 'Inactivo', "
            "'recuperacion') RETURNING id"),
            {"t": tenant["id"], "n": nombre_por_indice(i),
             "c": correo}).scalar_one()
        promo_id = db.execute(text(
            "INSERT INTO promociones_recuperacion (tenant_id, candidato_id, "
            "tipo_beneficio, cantidad, vence_en, estado, creado_por) "
            "VALUES (:t, :c, :tb, :q, :v, 'enviada', :a) RETURNING id"),
            {"t": tenant["id"], "c": candidato_id, "tb": tipo, "q": cantidad,
             "v": ahora + timedelta(days=7), "a": admin_id}).scalar_one()
        candidatos_g12.append({
            "correo": correo, "candidato_id": candidato_id,
            "promocion_id": promo_id, "tipo_beneficio": tipo,
            "cantidad": cantidad,
        })
    correo_vencido = f"{PREFIJO_G12}venc01@{DOMINIO_K6}"
    candidato_vencido_id = db.execute(text(
        "INSERT INTO candidatos_boxmagic (tenant_id, nombre, correo, "
        "estado_boxmagic, grupo) VALUES (:t, 'Carga K6 Vencido', :c, "
        "'Inactivo', 'recuperacion') RETURNING id"),
        {"t": tenant["id"], "c": correo_vencido}).scalar_one()
    promo_vencida_id = db.execute(text(
        "INSERT INTO promociones_recuperacion (tenant_id, candidato_id, "
        "tipo_beneficio, cantidad, vence_en, estado, creado_por) "
        "VALUES (:t, :c, 'dias_gratis', 2, :v, 'enviada', :a) RETURNING id"),
        {"t": tenant["id"], "c": candidato_vencido_id,
         "v": ahora - timedelta(days=1), "a": admin_id}).scalar_one()
    log(f"  G12: {len(candidatos_g12)} candidatos con promo vigente + 1 vencida "
        f"(promo {promo_vencida_id})")

    # ── 8e) G11: escalera de tramos 1/2/3 (dato de PRUEBA, documentado) ──
    # El escenario verifica que con 3 convertidos se otorga SÓLO el tramo de 3
    # (`tramos_referidos_service.umbral_mas_alto`), no los tres. Sólo se crean
    # los umbrales que falten: si el box ya tiene una escalera real, se respeta.
    existentes = {int(r[0]) for r in db.execute(text(
        "SELECT umbral_referidos FROM tramos_referido WHERE tenant_id = :t"),
        {"t": tenant["id"]})}
    tramos_g11_creados = []
    for umbral, tipo_premio, valor in TRAMOS_G11:
        if umbral in existentes:
            continue
        tramos_g11_creados.append(db.execute(text(
            "INSERT INTO tramos_referido (tenant_id, umbral_referidos, "
            "tipo_premio, valor_premio, activo) "
            "VALUES (:t, :u, CAST(:tp AS tipo_premio_referido), :v, TRUE) "
            "RETURNING id"),
            {"t": tenant["id"], "u": umbral, "tp": tipo_premio,
             "v": valor}).scalar_one())
    umbrales = sorted({int(r[0]) for r in db.execute(text(
        "SELECT umbral_referidos FROM tramos_referido WHERE tenant_id = :t "
        "AND activo"), {"t": tenant["id"]})})
    tramo_g11_umbral = 3 if 3 in umbrales else (umbrales[-1] if umbrales else None)
    log(f"  G11: escalera {umbrales} (creados por el seed: "
        f"{tramos_g11_creados}, umbral a verificar: {tramo_g11_umbral})")

    # ── 8f) G9b: notificación y pago para el webhook firmado ──
    # `notificacion_id` es UNIQUE en `pagos_eventos`: si el seed reusara el de la
    # corrida anterior, TODOS los reintentos verían "duplicado" y no se mediría
    # nada. La limpieza borra el anterior (está en load_config.json).
    mp_payment_id = _ultimo_pago_mp() or MP_PAYMENT_ID_FALLBACK
    mp_notificacion_id = str(uuid.uuid4())
    log(f"  G9b: webhook con data.id={mp_payment_id} "
        f"(notificacion_id={mp_notificacion_id})")




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
            "filas_rm": len(filas_rm),
            # ── G9-G14 ──
            "alumno_g9": {"alumno_id": alumno_g9, "correo": correo_g9},
            "mp_payer_email": correo_g9,
            # Sólo cuando es un comprador de prueba REAL (no el fallback): es lo
            # que el próximo seed reusa para no crear un usuario de MP por corrida.
            "mp_test_user_email": mp_payer,
            "mp_payment_id": mp_payment_id,
            "mp_notificacion_id": mp_notificacion_id,
            "correos_g10": correos_g10,
            "invitador_g11": {"alumno_id": invitador_g11,
                              "correo": correo_g11a},
            "invitados_g11": [{"alumno_id": uid, "correo": correo}
                              for uid, correo in zip(invitados_g11,
                                                     correos_g11_inv)],
            "correos_g11_alta": correos_g11_alta,
            "tramo_g11_umbral": tramo_g11_umbral,
            "tramos_g11_creados": tramos_g11_creados,
            "candidatos_g12": candidatos_g12,
            "candidato_vencido_g12": {"correo": correo_vencido,
                                      "candidato_id": candidato_vencido_id,
                                      "promocion_id": promo_vencida_id},
            "alumnos_g13": [{"alumno_id": uid, "correo": correo}
                            for uid, correo in zip(alumnos_g13, correos_g13)],
            "wod_g13_id": wod_g13, "clase_g13_id": clase_g13,
            "clase_g13_coach_id": clase_g13_coach,
            "alumnos_g14": [{"alumno_id": uid, "correo": correo}
                            for uid, correo in zip(pendientes_g14, correos_g14)]}



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
                     n_alumnos: int, admin_token: str, coach_token: str,
                     mp: dict) -> dict:
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
        # ── G9: checkout recurrente + webhook firmado ──
        # El secreto es el `MERCADOPAGO_WEBHOOK_SECRET` del backend que se prueba
        # (backend/.env.test). load_config.json NO se versiona.
        "n_g9": N_G9,
        "alumno_g9": disco["alumno_g9"],
        "mp_webhook_secret": mp["secret"],
        "mp_webhook_notificacion_id": disco["mp_notificacion_id"],
        "mp_webhook_payment_id": disco["mp_payment_id"],
        "mp_webhook_reintentos": 3,
        # ── G10: altas end-to-end ──
        "n_g10": N_G10,
        "correos_g10": disco["correos_g10"],
        # ── G11: referidos con conversión + escalera ──
        "n_g11": N_G11,
        "invitador_g11": disco["invitador_g11"],
        "invitados_g11": disco["invitados_g11"],
        "correos_g11_alta": disco["correos_g11_alta"],
        "tramo_g11_umbral": disco["tramo_g11_umbral"],
        # ── G12: reactivación (padrón → promoción → beneficio) ──
        "n_g12": N_G12,
        "candidatos_g12": disco["candidatos_g12"],
        "candidato_vencido_g12": disco["candidato_vencido_g12"],
        # ── G13: ciclo de WODs ──
        "n_g13": N_G13,
        "alumnos_g13": disco["alumnos_g13"],
        "wod_g13_id": disco["wod_g13_id"],
        "clase_g13_id": disco["clase_g13_id"],
        "clase_g13_coach_id": disco["clase_g13_coach_id"],
        # Día de HOY en Chile (el WOD que crea el coach en G13 lleva esa fecha;
        # calcularlo con `new Date()` daría la fecha UTC y a las 21:00 CLT ya es
        # el día siguiente).
        "hoy_chile": disco["hoy"].isoformat(),
        # ── G14: activación end-to-end ──
        "n_g14": N_G14,
        "alumnos_g14": disco["alumnos_g14"],
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
            # Se guardan para que la PRÓXIMA limpieza borre exactamente lo que
            # creó este seed (no una escalera real del box ni un evento ajeno).
            "tramos_g11_creados": disco["tramos_g11_creados"],
            "mp_notificacion_id": disco["mp_notificacion_id"],
            # Para la limpieza: el alumno de G9 puede NO tener el prefijo
            # `carga_k6_` (usa el correo del comprador de prueba de MP).
            "alumno_g9_id": disco["alumno_g9"]["alumno_id"],
            "mp_test_user_email": disco["mp_test_user_email"],
        },
    }



def tokens_de_flujos(disco: dict, tenant_id: int, horas: int) -> None:
    """Agrega `token` (JWT) a los alumnos de G9/G11/G13.

    Esos usuarios NO están en `tokens.json` (que indexa por VU los 500 del
    arnés viejo): sus JWT viajan dentro de `load_config.json`, junto al id que
    los identifica, porque cada escenario los usa en un orden propio (y algunos
    necesitan la relación invitador → invitados).
    """
    def _token(usuario_id: int, correo: str, nombre: str) -> str:
        return create_access_token(
            {"usuario_id": usuario_id, "tenant_id": tenant_id, "rol": "alumno",
             "correo": correo, "nombre": nombre},
            expires_delta=timedelta(hours=horas))

    disco["alumno_g9"]["token"] = _token(
        disco["alumno_g9"]["alumno_id"], disco["alumno_g9"]["correo"],
        "Carga K6 G9")
    disco["invitador_g11"]["token"] = _token(
        disco["invitador_g11"]["alumno_id"], disco["invitador_g11"]["correo"],
        "Carga K6 Invitador A")
    for invitado in disco["invitados_g11"]:
        invitado["token"] = _token(
            invitado["alumno_id"], invitado["correo"], "Carga K6 G11 Invitado")
    for alumno in disco["alumnos_g13"]:
        alumno["token"] = _token(
            alumno["alumno_id"], alumno["correo"], "Carga K6 G13 Alumno")


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
    seed_previo = previo.get("seed") or {}
    horario_previo = seed_previo.get("horario_creado")
    notificacion_previa = seed_previo.get("mp_notificacion_id")
    tramos_previos = seed_previo.get("tramos_g11_creados") or []

    with SessionLocal() as db:
        tenant = resolver_tenant(db, args.subdominio)
        log(f"Tenant: id={tenant['id']} «{tenant['nombre']}» "
            f"(subdominio {tenant['subdomain']})")

        # ── Limpieza idempotente ──
        log("\nLimpiando el seed anterior (sólo filas carga_k6_* / CARGA_K6*):")
        borradas = limpiar(db, tenant["id"], horario_previo,
                           notificacion_previa=notificacion_previa,
                           tramos_previos=tramos_previos,
                           alumno_g9_previo=seed_previo.get("alumno_g9_id"))
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
        mp_payer = _mp_test_user(seed_previo.get("mp_test_user_email"))
        disco = sembrar(db, tenant=tenant, plan=plan, mov_f1=mov_f1,
                        mov_g1=mov_g1, disciplina_id=disciplina_id,
                        n_alumnos=args.alumnos,
                        con_historial=not args.sin_historial,
                        mp_payer=mp_payer)
        # Códigos para TODOS los alumnos del seed (no sólo N_D): G4 verifica que
        # cada alumno de tokens.json tenga el suyo, y con `--alumnos 500` (F2)
        # mirar sólo los primeros 20 dejaba el chequeo en "20 vs 500".
        n_codigos = sembrar_codigos_referido(
            db, [a["id"] for a in disco["alumnos"]]
            + [disco["invitador_g11"]["alumno_id"]])
        db.commit()
        # El código del invitador A es la entrada de G11 (validar-codigo): se lee
        # con la MISMA función que lo generó, no se inventa.
        disco["invitador_g11"]["codigo"] = db.execute(text(
            "SELECT codigo FROM codigos_referido WHERE usuario_id = :u"),
            {"u": disco["invitador_g11"]["alumno_id"]}).scalar()
        if not disco["invitador_g11"]["codigo"]:
            log("  AVISO: el invitador de G11 quedó sin código de referido")

    # ── Tokens (fuera de la sesión: ya está todo commiteado) ──
    expira = timedelta(hours=args.horas_token)
    tokens = construir_tokens(disco["alumnos"], tenant["id"], args.horas_token)
    tokens_de_flujos(disco, tenant["id"], args.horas_token)
    admin_token = create_access_token(
        {"usuario_id": disco["admin_id"], "tenant_id": tenant["id"],
         "rol": "administrador", "correo": disco["admin_correo"],
         "nombre": "Carga K6 Admin"}, expires_delta=expira)
    coach_token = create_access_token(
        {"usuario_id": disco["coach_id"], "tenant_id": tenant["id"],
         "rol": "coach", "correo": disco["coach_correo"],
         "nombre": "Carga K6 Coach"}, expires_delta=expira)

    mp = {"secret": (settings.MERCADOPAGO_WEBHOOK_SECRET or "").strip()}
    if not mp["secret"]:
        log("\nAVISO: MERCADOPAGO_WEBHOOK_SECRET vacío en el entorno de TEST: "
            "G9b recibirá 503 (fail-closed) y no podrá medir la idempotencia.")
    nuevo = construir_config(
        base_url=args.base_url, tenant=tenant, plan=plan, disco=disco,
        mov_f1=mov_f1, mov_g1=mov_g1, disciplina_id=disciplina_id,
        n_alumnos=args.alumnos, admin_token=admin_token, coach_token=coach_token,
        mp=mp)

    # Claves legacy del arnés previo (n_d/n_vol/n_conc/n_a…) que el usuario
    # hubiera calibrado a mano: se conservan salvo que el seed las recalcule.
    config = {"n_d": N_D, "n_vol": min(N_VOL, args.alumnos),
              "n_conc": args.alumnos, "n_a": 40, **previo, **nuevo}

    escribir_json(tokens_path, tokens)
    escribir_json(cfg_path, config)

    # ── Resumen ──
    log("\nSembrado:")
    log(f"  usuarios: 1 admin + 1 coach + {args.alumnos} alumnos "
        f"(+{N_PENDIENTES} pendiente_activacion) + "
        f"{2 + N_G11 + N_G13 + N_G14} de los flujos G9-G14")
    log(f"  clase de hoy: id={disco['clase_id']} con {args.alumnos} reservas")
    log(f"  bazar: producto id={disco['producto_id']} | pedido validado "
        f"id={disco['pedido_codigo_id']} código {disco['codigo_retiro']}")
    log(f"  pedidos pendientes: {disco['pedido_pendiente_id']} (G3), "
        f"{disco['pedido_voucher_aprobar_id']} / "
        f"{disco['pedido_voucher_rechazar_id']} (G6)")
    log(f"  solicitudes de plan pending: {len(disco['solicitudes'])} | "
        f"códigos de referido: {n_codigos}")
    log(f"  historial_rm: {disco['filas_rm']} filas (grupo 'vol')")
    log(f"  G9: alumno {disco['alumno_g9']['alumno_id']} "
        f"({disco['alumno_g9']['correo']}) · webhook "
        f"data.id={disco['mp_payment_id']} (notif {disco['mp_notificacion_id']})")
    log(f"  G10: {len(disco['correos_g10'])} correos para altas end-to-end")
    log(f"  G11: invitador {disco['invitador_g11']['alumno_id']} + "
        f"{len(disco['invitados_g11'])} invitados · escalera "
        f"{disco['tramo_g11_umbral']} · tramos creados "
        f"{disco['tramos_g11_creados']}")
    log(f"  G12: {len(disco['candidatos_g12'])} candidatos vigentes + 1 vencido")
    log(f"  G13: WOD {disco['wod_g13_id']} · clase {disco['clase_g13_id']} · "
        f"clase coach {disco['clase_g13_coach_id']}")
    log(f"  G14: {len(disco['alumnos_g14'])} alumnos pendiente_activacion")
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
