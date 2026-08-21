"""
Harness de validación FASE 1 — Ranking de Asistencia por Plan (endpoint público).

Misma estrategia que _fase1_validation_pg.py:
- SEED aislado con prefijo inconfundible (subdomain 'test-ranking-*') sobre la
  base TEST (branch small-butterfly), verificado vía /debug/db-url antes de
  tocar cualquier dato.
- 20 checks contra GET /api/v1/ranking/asistencia/{public_id}.
- CLEANUP al final (borra todo lo creado con el prefijo; re-ejecutable).

Uso:
  1) Levantar el servidor en TEST:
       $env:ENVIRONMENT="test"; py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  2) py -3.12 _validar_ranking_asistencia.py

Sellos/estrellas esperados (escala confirmada):
  100% → sello "100% PERFECTO" · 80-99%→4★ · 60-79%→3★ · 40-59%→2★ ·
  20-39%→1★ · <20%→0★ · ilimitado > máx no-ilimitado → sello "🦍 MONSTRUO" + 5★
"""
import os

os.environ["ENVIRONMENT"] = "test"  # IMPORTANTE: antes de importar la app

import sys

# Consola en UTF-8 (cp1252 de Windows rompe con los emojis de ✅/❌).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import uuid
from datetime import date, datetime, time, timedelta, timezone

import requests
from sqlalchemy import text

# El harness escribe en la BD TEST a través de los modelos de la app.
from app.db.database import SessionLocal
from app.models.clase import Clase
from app.models.disciplina import Disciplina
from app.models.horario_base import HorarioBase
from app.models.plan import Plan
from app.models.reserva import Reserva
from app.models.suscripcion import Suscripcion
from app.models.tenant import Tenant
from app.models.usuario import Usuario, RolUsuario

BASE = "http://localhost:8000/api/v1"
PREFIX = f"test-ranking-{uuid.uuid4().hex[:6]}"
SUB = f"sub-{PREFIX}"

# Mes de prueba: mayo 2026 (cerrado, fijo y determinista para las aserciones).
MES = (2026, 5)

resultados = []


def check(nombre, ok, esperado, real):
    resultados.append(ok)
    print(f"[{'✅' if ok else '❌'}] {nombre}  →  esperado={esperado} | real={real}")


# ─────────────────────────────────────────────────────────────────────────────
# SEED — datos aislados con prefijo (todo queda bajo el tenant de PREFIX)
# ─────────────────────────────────────────────────────────────────────────────
def seed():
    db = SessionLocal()
    try:
        tenant = Tenant(
            nombre=f"TENANT TEST RANKING {PREFIX}",
            subdomain=SUB,
            public_id=str(uuid.uuid4()),
            activo=True,
        )
        db.add(tenant)
        db.flush()

        def plan(nombre, creditos, ilimitado=False, estudiante=False):
            p = Plan(
                tenant_id=tenant.id, nombre=nombre, creditos=creditos,
                es_ilimitado=ilimitado, es_estudiante=estudiante,
                precio_clp=10000, duracion_dias=30, activo=True,
            )
            db.add(p)
            db.flush()
            return p

        # Tramos (decisión: agrupar por creditos, ilimitado aparte).
        p8 = plan("Mono Pequeño", 8)
        p8e = plan("Changuito Estudiante", 8, estudiante=True)   # se fusiona al 8
        p10 = plan("Mono Mediano", 10)
        p12 = plan("Gorila", 12)
        p16 = plan("Alpha", 16)
        p16b = plan("Super Woman", 16)   # tramo 16 con 3 nombres → loguea el resto
        pfull = plan("King Kong", 0, ilimitado=True)
        pfulle = plan("Donkey Kong", 0, ilimitado=True, estudiante=True)

        idx = [0]

        def alumno(nombre):
            idx[0] += 1
            u = Usuario(
                tenant_id=tenant.id,
                rut=f"11{idx[0]:07d}-{idx[0] % 10}",
                nombre=nombre,
                correo=f"a{idx[0]}@{PREFIX}.test",
                password_hash="x",
                rol=RolUsuario.alumno,
                activo=True,
                estado="activo",
            )
            db.add(u)
            db.flush()
            return u

        def sus(alumno_obj, plan_obj, anio, mes, dias=31, estado="activo"):
            s = Suscripcion(
                tenant_id=tenant.id,
                usuario_id=alumno_obj.id,
                plan_id=plan_obj.id,
                estado=estado,
                creditos_totales=None if plan_obj.es_ilimitado else plan_obj.creditos,
                creditos_disponibles=None if plan_obj.es_ilimitado else plan_obj.creditos,
                fecha_inicio=datetime(anio, mes, 1, tzinfo=timezone.utc),
                fecha_expiracion=datetime(anio, mes, dias, 23, 59, 59, tzinfo=timezone.utc),
            )
            db.add(s)
            db.flush()
            return s

        # Disciplina + horario base para poder crear clases válidas.
        disc = Disciplina(tenant_id=tenant.id, nombre="CrossFit Test Ranking", activo=True)
        db.add(disc)
        db.flush()
        hb = HorarioBase(
            tenant_id=tenant.id, disciplina_id=disc.id, dia_semana=0,
            hora_inicio=time(18, 0), hora_fin=time(19, 0), activo=True,
        )
        db.add(hb)
        db.flush()

        def asistencia(alumno_obj, anio, mes, total, asistidas):
            """Crea `total` reservas del alumno en el mes; las primeras
            `asistidas` con asistio=True. Días rotativos para no chocar.
            BATCH: 1 flush para las clases + 1 flush para las reservas
            (evita cientos de round-trips a Neon)."""
            clases = []
            for i in range(total):
                c = Clase(
                    tenant_id=tenant.id, horario_base_id=hb.id,
                    disciplina_id=disc.id, fecha=date(anio, mes, (i % 28) + 1),
                    hora_inicio=time(18, 0), hora_fin=time(19, 0),
                    cupo_maximo=20, cancelada=False,
                )
                db.add(c)
                clases.append(c)
            db.flush()
            for i, c in enumerate(clases):
                r = Reserva(
                    tenant_id=tenant.id, clase_id=c.id,
                    alumno_id=alumno_obj.id, asistio=i < asistidas,
                    tokens_gastados=1, estado="confirmada",
                )
                db.add(r)
            db.flush()

        # ── Alumnos y suscripciones del mes cerrado (mayo 2026) ──
        s1 = alumno("Carlos Pérez Gómez")   # 8/8 → PERFECTO
        sus(s1, p8, *MES, estado="vencido")  # mes ya cerrado → 'vencido'
        asistencia(s1, *MES, total=8, asistidas=8)

        s2 = alumno("María González Pérez")  # 7/8 → 88% → 4★
        sus(s2, p8, *MES)
        asistencia(s2, *MES, total=8, asistidas=7)

        s3 = alumno("Ana Torres Ruiz")       # 5/10 → 50% → 2★
        sus(s3, p10, *MES)
        asistencia(s3, *MES, total=10, asistidas=5)

        s4 = alumno("Pedro Soto")            # 12/12 → PERFECTO (tramo 12)
        sus(s4, p12, *MES)
        asistencia(s4, *MES, total=12, asistidas=12)

        s5 = alumno("Luis Núñez")            # 3/16 → 19% → 0★
        sus(s5, p16, *MES)
        asistencia(s5, *MES, total=16, asistidas=3)

        s6 = alumno("Sofía Vargas")          # FULL 20 asistencias > 16 → MONSTRUO
        sus(s6, pfull, *MES)
        asistencia(s6, *MES, total=20, asistidas=20)

        s7 = alumno("Javiera Morales")       # FULL 12 asistencias → 12/16=75% → 3★
        sus(s7, pfulle, *MES)
        asistencia(s7, *MES, total=12, asistidas=12)

        # Empate por asistencias (4 y 4) → desempata la RACHA.
        s8 = alumno("Diego Fuentes Lara")    # racha 2 (abril 2/2 + mayo 2/2)
        sus(s8, p12, *MES)
        sus(s8, p12, 2026, 4, dias=30)
        asistencia(s8, *MES, total=4, asistidas=4)
        asistencia(s8, 2026, 4, total=2, asistidas=2)

        s9 = alumno("Camila Rojas Vera")     # racha 1 (solo mayo 2/2)
        sus(s9, p12, *MES)
        asistencia(s9, *MES, total=4, asistidas=4)

        # Relleno para probar el límite de TOP 10 en el tramo 12.
        relleno = [
            ("Rodrigo Castro Peña", 11), ("Valentina Díaz Muñoz", 10),
            ("Felipe Aguirre Soto", 9), ("Constanza Bravo Lara", 8),
            ("Matías Herrera Cruz", 7), ("Antonia Reyes Fuentes", 6),
            ("Nicolás Sandoval Ríos", 5), ("Fernanda Tapia Leiva", 3),
            ("Joaquín Villalobos Mora", 3),
        ]
        for nombre, asist in relleno:
            u = alumno(nombre)
            sus(u, p12, *MES)
            asistencia(u, *MES, total=12, asistidas=asist)

        db.commit()
        return tenant.public_id, tenant.id
    finally:
        db.close()

# ─────────────────────────────────────────────────────────────────────────────
# VALIDACIÓN — 20 checks contra el endpoint público
# ─────────────────────────────────────────────────────────────────────────────
def columna_por_tramo(data, tramo):
    for c in data["columnas"]:
        if c["tramo_clases"] == tramo:
            return c
    return None


def fila_por_nombre(col, nombre):
    for f in col.get("top", []):
        if f["nombre"] == nombre:
            return f
    return None


def correr_checks(public_id):
    url = f"{BASE}/ranking/asistencia/{public_id}"

    # 1. 404 genérico para un public_id inexistente (no revelar existencia).
    r = requests.get(f"{BASE}/ranking/asistencia/{uuid.uuid4()}", timeout=10)
    check("1. 404 genérico si box_public_id no existe",
          r.status_code == 404 and r.json().get("detail") == "No encontrado",
          "404 detail='No encontrado'", f"{r.status_code} {r.json().get('detail')}")

    # 2. 400 para mes inválido (2026-13).
    r = requests.get(url, params={"mes": "2026-13"}, timeout=10)
    check("2. 400 si mes fuera de rango (2026-13)",
          r.status_code == 400, "400", str(r.status_code))

    # 3. 200 con mes explícito.
    r = requests.get(url, params={"mes": "2026-05"}, timeout=15)
    check("3. 200 con mes=2026-05", r.status_code == 200, "200", str(r.status_code))
    data = r.json()

    # 4. Default = mes cerrado más reciente (mes anterior a hoy Santiago).
    hoy = datetime.now(timezone.utc).date()
    anio_prev, mes_prev = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    r2 = requests.get(url, timeout=15)
    ok4 = r2.status_code == 200 and r2.json()["mes"] == f"{anio_prev}-{mes_prev:02d}"
    check("4. Default mes = mes cerrado más reciente",
          ok4, f"{anio_prev}-{mes_prev:02d}", r2.json().get("mes") if r2.status_code == 200 else r2.status_code)

    # 5. 5 columnas ordenadas 8, 10, 12, 16, ilimitado.
    tramos = [c["tramo_clases"] for c in data["columnas"]]
    check("5. 5 columnas en orden [8,10,12,16,ilimitado]",
          tramos == [8, 10, 12, 16, None],
          "[8, 10, 12, 16, None]", tramos)

    # 6. Encabezado tramo 8 fusiona normal + estudiante (2 nombres) + flag.
    c8 = columna_por_tramo(data, 8)
    ok6 = (sorted(c8["nombres_marketing"]) == sorted(["Mono Pequeño", "Changuito Estudiante"])
           and c8.get("incluye_estudiante") is True
           and columna_por_tramo(data, None).get("incluye_estudiante") is True)
    check("6. Encabezado tramo 8 = normal + estudiante fusionados (+flag)",
          ok6,
          "['Mono Pequeño', 'Changuito Estudiante'] + incluye_estudiante=True",
          f"{c8['nombres_marketing']} incl_est={c8.get('incluye_estudiante')}")

    # 7. S1: 8/8 → sello 100% PERFECTO (estrellas 0).
    f = fila_por_nombre(c8, "Carlos P. G.")
    ok7 = f and f["asistencias"] == 8 and f["contratadas"] == 8 \
        and f["sello"] == "100% PERFECTO" and f["estrellas"] == 0
    check("7. Carlos 8/8 → sello 100% PERFECTO", ok7,
          "8/8 sello PERFECTO ★0", f if f else "NO ENCONTRADO")

    # 8. S2: 7/8 = 88% → 4★, sin sello.
    f = fila_por_nombre(c8, "María G. P.")
    ok8 = f and f["asistencias"] == 7 and f["estrellas"] == 4 and not f["sello"]
    check("8. María 7/8 → 4★ (88%)", ok8, "7/8 ★4 sin sello", f if f else "NO ENCONTRADO")

    # 9. S3: 5/10 = 50% → 2★.
    c10 = columna_por_tramo(data, 10)
    f = fila_por_nombre(c10, "Ana T. R.")
    ok9 = f and f["asistencias"] == 5 and f["estrellas"] == 2 and not f["sello"]
    check("9. Ana 5/10 → 2★ (50%)", ok9, "5/10 ★2", f if f else "NO ENCONTRADO")

    # 10. S4: 12/12 → PERFECTO (tramo 12).
    c12 = columna_por_tramo(data, 12)
    f = fila_por_nombre(c12, "Pedro S.")
    ok10 = f and f["asistencias"] == 12 and f["contratadas"] == 12 \
        and f["sello"] == "100% PERFECTO"
    check("10. Pedro 12/12 → PERFECTO (tramo 12)", ok10,
          "12/12 sello PERFECTO", f if f else "NO ENCONTRADO")

    # 11. Límite TOP 10 (el tramo 12 tiene 12 alumnos).
    ok11 = c12["alumnos_activos"] == 12 and len(c12["top"]) == 10
    check("11. Top 10 por columna (12 alumnos → 10 filas)",
          ok11, "alumnos=12, top=10", f"alumnos={c12['alumnos_activos']}, top={len(c12['top'])}")

    # 12. Orden estrictamente desc por asistencias.
    asis = [f["asistencias"] for f in c12["top"]]
    ok12 = asis == sorted(asis, reverse=True)
    check("12. Orden por asistencias desc", ok12, asis, asis)

    # 13. Empate por racha desc (Diego racha 2 antes que Camila racha 1).
    idx_d = next(i for i, f in enumerate(c12["top"]) if f["nombre"] == "Diego F. L.")
    idx_c = next(i for i, f in enumerate(c12["top"]) if f["nombre"] == "Camila R. V.")
    ok13 = idx_d < idx_c and c12["top"][idx_d]["racha"] == 2 \
        and c12["top"][idx_c]["racha"] == 1
    check("13. Empate → racha desc (Diego racha2 > Camila racha1)",
          ok13, "Diego(4, r2) antes que Camila(4, r1)",
          f"Diego pos={idx_d} r={c12['top'][idx_d]['racha']} | Camila pos={idx_c} r={c12['top'][idx_c]['racha']}")

    # 14. S5: 3/16 = 19% → 0★.
    c16 = columna_por_tramo(data, 16)
    f = fila_por_nombre(c16, "Luis N.")
    ok14 = f and f["asistencias"] == 3 and f["estrellas"] == 0 and not f["sello"]
    check("14. Luis 3/16 → 0★ (19%)", ok14, "3/16 ★0", f if f else "NO ENCONTRADO")

    # 15. S6: FULL 20 asistencias > máx 16 → MONSTRUO.
    cfull = columna_por_tramo(data, None)
    f = fila_por_nombre(cfull, "Sofía V.")
    ok15 = f and f["asistencias"] == 20 and f["contratadas"] is None \
        and f["sello"] == "🦍 MONSTRUO" and f["estrellas"] == 5
    check("15. Sofía FULL 20 > 16 → sello 🦍 MONSTRUO + 5★",
          ok15, "20, contratadas=null, MONSTRUO, ★5", f if f else "NO ENCONTRADO")

    # 16. S7: FULL 12 → 12/16 = 75% → 3★ (relativo al máximo, sin denominador).
    f = fila_por_nombre(cfull, "Javiera M.")
    ok16 = f and f["asistencias"] == 12 and f["estrellas"] == 3 and not f["sello"]
    check("16. Javiera FULL 12 → 3★ (75% relativo al máx 16)",
          ok16, "12, ★3, sin sello", f if f else "NO ENCONTRADO")

    # 17. max_no_ilimitado leído de BD (16), nunca hardcodeado.
    check("17. max_no_ilimitado == 16 (leído de BD)",
          data["max_no_ilimitado"] == 16, "16", data["max_no_ilimitado"])

    # 18. Formato de nombres con iniciales (token único sin cambio).
    check("18. Formato 'Nombre + iniciales'",
          bool(fila_por_nombre(c8, "Carlos P. G."))
          and bool(fila_por_nombre(c12, "Pedro S.")),
          "'Carlos P. G.', 'Pedro S.'", "verificado en checks 7/10/13/15/16")

    # 19. Conteo de alumnos activos por tramo.
    ok19 = (c8["alumnos_activos"] == 2 and c10["alumnos_activos"] == 1
            and c12["alumnos_activos"] == 12 and c16["alumnos_activos"] == 1
            and cfull["alumnos_activos"] == 2)
    check("19. Conteo alumnos activos por tramo",
          ok19, "8→2, 10→1, 12→12, 16→1, FULL→2",
          f"8→{c8['alumnos_activos']}, 10→{c10['alumnos_activos']}, "
          f"12→{c12['alumnos_activos']}, 16→{c16['alumnos_activos']}, "
          f"FULL→{cfull['alumnos_activos']}")

    # 20. Sin PII: no aparecen apellidos completos ni correos.
    texto = r.text
    pii = ("Pérez Gómez" in texto or "González Pérez" in texto or "Fuentes Lara" in texto
           or "@" in texto)
    check("20. Sin PII (sin apellidos completos ni correos)",
          not pii, "sin apellidos/correos", "⚠️ contiene PII" if pii else "limpio")



# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP + ejecución
# ─────────────────────────────────────────────────────────────────────────────
def cleanup(tenant_id):
    """Borra todo lo creado con el prefijo (mismo patrón que el resto de
    harness: datos identificables por subdomain 'test-ranking-*').
    Borra TODOS los tenants que matcheen el patrón (robusto ante corridas
    previas fallidas)."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        ids = [r[0] for r in db.execute(
            text("SELECT id FROM tenants WHERE subdomain LIKE 'sub-test-ranking-%'")
        ).fetchall()]
        if tenant_id is not None and tenant_id not in ids:
            ids.append(tenant_id)
        for tid in ids:
            for tabla in ("reservas", "clases", "suscripciones", "planes",
                          "usuarios", "horarios", "disciplinas"):
                db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"), {"t": tid})
            db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        db.commit()
        print(f"  [cleanup] OK — {len(ids)} tenant(s) de prueba eliminados")
    except Exception as e:
        db.rollback()
        print(f"  [cleanup] FALLO — quedan filas identificables {PREFIX}: {e}")
    finally:
        db.close()


def main():
    # Seguridad: verificar que el servidor apunte a TEST (branch small-butterfly).
    try:
        r = requests.get("http://localhost:8000/debug/db-url", timeout=5)
        if r.status_code != 200 or not r.json().get("is_safe"):
            print("[SEGURIDAD] El servidor NO apunta a TEST. Abortando.")
            return 1
        print("[OK] Servidor apunta a TEST BRANCH\n")
    except requests.ConnectionError:
        print("[ERROR] API no disponible en localhost:8000. "
              "Levantá el servidor en TEST primero (ver docstring).")
        return 1

    print("=" * 72)
    print(f"SEED con prefijo {PREFIX} (subdomain {SUB})")
    print("=" * 72)
    public_id, tenant_id = seed()

    try:
        correr_checks(public_id)
    finally:
        print("\n" + "=" * 72)
        print("CLEANUP")
        print("=" * 72)
        cleanup(tenant_id)

    total = len(resultados)
    aprobados = sum(resultados)
    print("\n" + "=" * 72)
    print(f"RESULTADO: {aprobados}/{total} checks aprobados "
          f"({'✅ 20/20' if aprobados == total == 20 else '❌ revisar'})")
    print("=" * 72)
    return 0 if aprobados == total == 20 else 2


if __name__ == "__main__":
    raise SystemExit(main())
