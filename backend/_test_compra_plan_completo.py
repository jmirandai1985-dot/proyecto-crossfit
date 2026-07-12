"""
Script de prueba end-to-end: compra de plan hasta reservar clase.
Ejecutar con: python _test_compra_plan_completo.py
"""
import requests
import json
import random
import sys
from datetime import date, datetime

BASE = "http://localhost:8000/api/v1"
TENANT_ID = 1
ADMIN_ID = 1


def generar_rut_valido():
    """Genera un RUT chileno válido: 8 dígitos + guión + dígito verificador."""
    cuerpo = random.randint(10000000, 99999999)
    # Calcular dígito verificador (módulo 11)
    suma = 0
    multiplicador = 2
    for c in reversed(str(cuerpo)):
        suma += int(c) * multiplicador
        multiplicador = 9 if multiplicador == 7 else multiplicador + 1
    resto = suma % 11
    dv = str(11 - resto) if resto > 1 else ('0' if resto == 0 else 'K')
    return f"{cuerpo}-{dv}"


# Usuario de prueba con RUT y correo únicos
ts = int(datetime.now().timestamp() * 1000)
TEST_USER = {
    "tenant_id": TENANT_ID,
    "rut": generar_rut_valido(),
    "nombre": "Test Auto Prueba",
    "correo": f"test_auto_{ts}@prueba.cl",
    "password": "test123",
    "telefono": "+569 0000 0000",
    "rol": "alumno"
}

results = []


def registrar_paso(paso, ok, detalle=""):
    status = "✅ PASÓ" if ok else "❌ FALLÓ"
    results.append(f"  {status} | Paso {paso}: {detalle}")
    return ok


def print_sep(titulo):
    print(f"\n{'='*60}")
    print(f"  {titulo}")
    print(f"{'='*60}")


def print_json(label, data):
    print(f"\n  {label}:")
    print(f"  {json.dumps(data, indent=2, ensure_ascii=False, default=str)}")


hoy = str(date.today())

print("\n🚀 INICIANDO PRUEBA: COMPRA DE PLAN → RESERVAR CLASE")
print(f"   Usuario: {TEST_USER['correo']}, RUT={TEST_USER['rut']}")

# ═══════════════════════════════════════════════════════════════
# PASO 1: Crear usuario de prueba
# ═══════════════════════════════════════════════════════════════
print_sep("PASO 1: CREAR USUARIO DE PRUEBA")

r = requests.post(f"{BASE}/usuarios/", json=TEST_USER)
if r.status_code == 201:
    test_user_id = r.json().get("id")
    print(f"  Usuario creado: ID={test_user_id}")
else:
    print(f"  Error: {r.text[:200]}")
    sys.exit(1)

ok = test_user_id is not None
registrar_paso(1, ok, f"Usuario ID={test_user_id}")

# Verificar que NO tiene membresía activa
r = requests.get(f"{BASE}/planes/membresia-activa",
                 params={"tenant_id": TENANT_ID, "alumno_id": test_user_id})
membresia = r.json()
print(f"  Membresía activa ANTES: {membresia.get('activa', '?')}")
registrar_paso(1.1, not membresia.get("activa", False),
               f"Sin plan activo: activa={membresia.get('activa')}")

# ═══════════════════════════════════════════════════════════════
# PASO 2: Consultar planes y elegir uno
# ═══════════════════════════════════════════════════════════════
print_sep("PASO 2: CONSULTAR PLANES")

r = requests.get(f"{BASE}/planes",
                 params={"tenant_id": TENANT_ID, "activo": "true"})
planes = r.json() if isinstance(r.json(), list) else []
print(f"  Planes disponibles: {len(planes)}")

plan_elegido = next((p for p in planes if p.get("nombre") == "Simio"), None)
if not plan_elegido and planes:
    plan_elegido = planes[0]

plan_id = plan_elegido["id"]
plan_nombre = plan_elegido["nombre"]
plan_creditos = plan_elegido.get("creditos") or 0
print(f"  Plan: {plan_nombre} (ID={plan_id}, créditos={plan_creditos})")
registrar_paso(2, True, f"Plan: {plan_nombre}")

# ═══════════════════════════════════════════════════════════════
# PASO 3: Subir voucher
# ═══════════════════════════════════════════════════════════════
print_sep("PASO 3: SUBIR VOUCHER")

voucher_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
r = requests.post(f"{BASE}/upload/voucher",
                  files={"file": ("voucher_test.png", voucher_content, "image/png")})
voucher_url = r.json().get("url", "") if r.status_code == 201 else ""
print(f"  Voucher URL: {voucher_url}")
registrar_paso(3, bool(voucher_url), f"Voucher: {voucher_url[:40]}...")

# ═══════════════════════════════════════════════════════════════
# PASO 4: Crear solicitud
# ═══════════════════════════════════════════════════════════════
print_sep("PASO 4: CREAR SOLICITUD")

r = requests.post(f"{BASE}/solicitudes/solicitar", json={
    "tenant_id": TENANT_ID, "alumno_id": test_user_id,
    "plan_id": plan_id, "voucher_url": voucher_url
})
sol_ok = r.status_code == 201
solicitud_id = r.json().get("id") if sol_ok else None
sol_estado = r.json().get("status", "") if sol_ok else ""
print(f"  Solicitud ID={solicitud_id}, status={sol_estado}")
registrar_paso(4, sol_ok, f"Solicitud ID={solicitud_id}")

# ═══════════════════════════════════════════════════════════════
# PASO 5: Admin aprueba
# ═══════════════════════════════════════════════════════════════
print_sep("PASO 5: ADMIN APRUEBA")

r = requests.put(f"{BASE}/solicitudes/{solicitud_id}/aprobar",
                 params={"admin_id": ADMIN_ID})
aprob_ok = r.status_code == 200 and r.json().get("status") == "approved"
print(f"  Aprobación: {'✅' if aprob_ok else '❌'}")
registrar_paso(5, aprob_ok, "")

# ═══════════════════════════════════════════════════════════════
# PASO 6: Verificar membresía
# ═══════════════════════════════════════════════════════════════
print_sep("PASO 6: VERIFICAR MEMBRESÍA")

r = requests.get(f"{BASE}/planes/membresia-activa",
                 params={"tenant_id": TENANT_ID, "alumno_id": test_user_id})
m = r.json()
print_json("Membresía", m)
creditos = m.get("clases_disponibles", 0)
ok6 = m.get("activa") and creditos == plan_creditos and m.get(
    "plan_nombre") == plan_nombre
registrar_paso(6, ok6, f"Créditos={creditos} (esperado={plan_creditos})")

# ═══════════════════════════════════════════════════════════════
# PASO 7: Reservar clase
# ═══════════════════════════════════════════════════════════════
print_sep("PASO 7: RESERVAR CLASE")

r = requests.get(f"{BASE}/clases",
                 params={"tenant_id": TENANT_ID, "limit": 100})
clases = r.json() if isinstance(r.json(), list) else []
clase = next((c for c in clases if (c.get("cupo_maximo", 0) -
             c.get("asistentes_confirmados", 0)) > 0), None)

if clase:
    r = requests.post(f"{BASE}/reservas", json={
        "tenant_id": TENANT_ID, "alumno_id": test_user_id,
        "clase_id": clase["id"], "estado": "confirmada"
    })
    reserva_ok = r.status_code < 300
    creditos_post = requests.get(f"{BASE}/planes/membresia-activa",
                                 params={"tenant_id": TENANT_ID, "alumno_id": test_user_id}).json().get("clases_disponibles", 0)
    ok7 = reserva_ok and creditos_post == plan_creditos - 1
    print(
        f"  Créditos: {creditos} → {creditos_post} (esperado: {plan_creditos - 1})")
    registrar_paso(7, ok7, f"Créditos: {creditos}→{creditos_post}")
else:
    print("  ❌ Sin clases disponibles")
    registrar_paso(7, False, "Sin clases")

# ═══════════════════════════════════════════════════════════════
# RESUMEN
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  📊 RESUMEN")
print("="*60)
for r_line in results:
    print(r_line)
total_ok = sum(1 for r_line in results if "✅" in r_line)
print(f"\n  {total_ok}/{len(results)} pasos exitosos")
print(f"  {'✅ COMPLETADA' if total_ok == len(results) else '⚠️  HUBO FALLOS'}")
print("="*60)
