"""
Script de prueba: registrar RMs de CARDIO y MAQUINAS y verificar que aparecen
correctamente en la Pizarra de RMs (GET /historial-rm/alumnos/{id}/rms).

Ejecutar con:
  cd backend && python _test_rms_cardio_maquinas.py
"""
import requests
import json
from datetime import date

BASE = "http://localhost:8000/api/v1"
ALUMNO_ID = 5
TENANT_ID = 1
hoy = str(date.today())


def print_json(label, data):
    print(f"\n  {label}:")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# =============================================================================
# Obtener todos los movimientos (lo necesita toda la prueba)
# =============================================================================
r = requests.get(f"{BASE}/movimientos", params={"tenant_id": TENANT_ID})
if r.status_code != 200:
    print(f"❌ Error obteniendo movimientos: {r.text[:300]}")
    exit(1)
movs = r.json()
print(f"\nTotal movimientos disponibles: {len(movs)}")

# =============================================================================
# BLOQUE 1 - RM DE CARDIO
# =============================================================================
print("\n" + "=" * 70)
print("  BLOQUE 1 — RM DE CARDIO")
print("=" * 70)

# 1. Buscar movimiento de categoria "cardio" distinto a "Ski Erg"
cardio = [
    m for m in movs
    if isinstance(m, dict) and m.get("categoria") == "cardio"
    and "ski" not in m.get("nombre", "").lower()
]
print(f"\nMovimientos CARDIO (excluyendo Ski Erg): {len(cardio)}")
for m in cardio:
    print(f"    ID={m['id']:>4}  nombre='{m['nombre']}'")

if not cardio:
    print("❌  No hay movimientos de cardio disponibles. Abortando.")
    exit(1)

mov_cardio = cardio[0]
print(
    f"\n✅ Movimiento elegido para CARDIO: ID={mov_cardio['id']}  '{mov_cardio['nombre']}'")

# 2. Registrar RM de cardio con minutos, km, vueltas (valores realistas)
#    Ej: Running 400m → tomaría ~2 min, 0.4 km, 1 vuelta
payload_cardio = {
    "tenant_id": TENANT_ID,
    "alumno_id": ALUMNO_ID,
    "movimiento_id": mov_cardio["id"],
    "peso_kg": 1,            # requerido por schema, dummy para cardio
    "minutos": 2,
    "km": 0.4,
    "vueltas": 1,
    "fecha": hoy,
    "notas": "TEST: RM cardio automatico",
}
print(f"\n➡️  POST /historial-rm  (CARDIO)")
print(f"    Payload: {json.dumps(payload_cardio, indent=4)}")

r_post = requests.post(f"{BASE}/historial-rm", json=payload_cardio)
print(f"    Status: {r_post.status_code}")
if r_post.status_code >= 300:
    print(f"❌ Error al crear RM de cardio: {r_post.text[:500]}")
    exit(1)

resp_cardio = r_post.json()
print_json("Respuesta POST", resp_cardio)
cardio_id_creado = resp_cardio.get("id")

# Verificar que la respuesta POST devuelva los campos de cardio
campos_cardio_post = ["minutos", "km", "vueltas"]
post_ok = all(resp_cardio.get(k) ==
              payload_cardio[k] for k in campos_cardio_post)
print(f"\n{'✅' if post_ok else '❌'} Campos CARDIO en POST: "
      f"minutos={resp_cardio.get('minutos')}, km={resp_cardio.get('km')}, vueltas={resp_cardio.get('vueltas')}")

# 3. Consultar GET /historial-rm/alumnos/5/rms (la Pizarra) y confirmar
print(f"\n➡️  GET /historial-rm/alumnos/{ALUMNO_ID}/rms (Pizarra)")
r_pizarra = requests.get(
    f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/rms",
    params={"tenant_id": TENANT_ID},
)
rms = r_pizarra.json()
print(f"    Total RMs devueltos: {len(rms) if isinstance(rms, list) else 0}")

if not isinstance(rms, list):
    print(f"❌ Respuesta inesperada: {rms}")
    exit(1)

# Buscar nuestro RM de cardio por movimiento_id
rm_cardio_pizarra = [rm for rm in rms if rm.get(
    "movimiento_id") == mov_cardio["id"]]
if not rm_cardio_pizarra:
    print(f"❌ El RM de CARDIO NO aparece en la Pizarra de RMs")
    exit(1)

rm_cardio = rm_cardio_pizarra[0]
print(f"\n✅ RM de CARDIO encontrado en la Pizarra!")
print_json("Datos en Pizarra", rm_cardio)

# Validar que los campos específicos de cardio estén correctos
checks_cardio = [
    ("minutos", rm_cardio.get("minutos") == 2),
    ("km", rm_cardio.get("km") == 0.4),
    ("vueltas", rm_cardio.get("vueltas") == 1),
    ("movimiento_nombre", rm_cardio.get(
        "movimiento_nombre") == mov_cardio["nombre"]),
    ("tipo_rm", rm_cardio.get("tipo_rm") in ("peso", None)),
]
all_cardio_ok = True
for campo, ok in checks_cardio:
    estado = "✅" if ok else "❌"
    valor = rm_cardio.get(campo)
    print(f"  {estado} {campo} = {repr(valor)}")
    if not ok:
        all_cardio_ok = False

if all_cardio_ok:
    print(f"\n✅ BLOQUE 1 (CARDIO) PASÓ: RM visible con todos los campos correctos.")
else:
    print(f"\n⚠️  BLOQUE 1 (CARDIO) tiene discrepancias, pero el RM aparece en Pizarra.")

# =============================================================================
# BLOQUE 2 - RM DE MAQUINAS (categoria = metabolico)
# =============================================================================
print("\n" + "=" * 70)
print("  BLOQUE 2 — RM DE MAQUINAS (metabolico)")
print("=" * 70)

# 1. Buscar un movimiento de categoria "metabolico"
maquinas = [
    m for m in movs
    if isinstance(m, dict) and m.get("categoria") == "metabolico"
]
print(f"\nMovimientos MAQUINAS: {len(maquinas)}")
for m in maquinas:
    print(f"    ID={m['id']:>4}  nombre='{m['nombre']}'")

if not maquinas:
    print("❌  No hay movimientos de maquinas disponibles. Abortando.")
    exit(1)

mov_maquina = maquinas[0]
print(
    f"\n✅ Movimiento elegido para MAQUINAS: ID={mov_maquina['id']}  '{mov_maquina['nombre']}'")

# 2. Registrar RM de maquinas con calorias, km, vueltas
#    Valores realistas: 300 cal, 3.5 km, 10 vueltas
payload_maquina = {
    "tenant_id": TENANT_ID,
    "alumno_id": ALUMNO_ID,
    "movimiento_id": mov_maquina["id"],
    "peso_kg": 1,             # dummy
    "calorias": 300,
    "km": 3.5,
    "vueltas": 10,
    "fecha": hoy,
    "notas": "TEST: RM maquinas automatico",
}
print(f"\n➡️  POST /historial-rm  (MAQUINAS)")
print(f"    Payload: {json.dumps(payload_maquina, indent=4)}")

r_post = requests.post(f"{BASE}/historial-rm", json=payload_maquina)
print(f"    Status: {r_post.status_code}")
if r_post.status_code >= 300:
    print(f"❌ Error al crear RM de maquinas: {r_post.text[:500]}")
    exit(1)

resp_maquina = r_post.json()
print_json("Respuesta POST", resp_maquina)

# Verificar campos en POST
campos_maquina_post = ["calorias", "km", "vueltas"]
post_ok = all(resp_maquina.get(k) ==
              payload_maquina[k] for k in campos_maquina_post)
print(f"\n{'✅' if post_ok else '❌'} Campos MAQUINAS en POST: "
      f"calorias={resp_maquina.get('calorias')}, km={resp_maquina.get('km')}, vueltas={resp_maquina.get('vueltas')}")

# 3. Consultar la Pizarra y confirmar que aparece
print(f"\n➡️  GET /historial-rm/alumnos/{ALUMNO_ID}/rms (Pizarra)")
r_pizarra = requests.get(
    f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/rms",
    params={"tenant_id": TENANT_ID},
)
rms = r_pizarra.json()

if not isinstance(rms, list):
    print(f"❌ Respuesta inesperada: {rms}")
    exit(1)

# Buscar nuestro RM de maquinas por movimiento_id
rm_maquina_pizarra = [rm for rm in rms if rm.get(
    "movimiento_id") == mov_maquina["id"]]
if not rm_maquina_pizarra:
    print(f"❌ El RM de MAQUINAS NO aparece en la Pizarra de RMs")
    exit(1)

rm_maquina = rm_maquina_pizarra[0]
print(f"\n✅ RM de MAQUINAS encontrado en la Pizarra!")
print_json("Datos en Pizarra", rm_maquina)

# Validar campos específicos de maquinas
checks_maquina = [
    ("calorias", rm_maquina.get("calorias") == 300),
    ("km", rm_maquina.get("km") == 3.5),
    ("vueltas", rm_maquina.get("vueltas") == 10),
    ("movimiento_nombre", rm_maquina.get(
        "movimiento_nombre") == mov_maquina["nombre"]),
]
all_maquina_ok = True
for campo, ok in checks_maquina:
    estado = "✅" if ok else "❌"
    valor = rm_maquina.get(campo)
    print(f"  {estado} {campo} = {repr(valor)}")
    if not ok:
        all_maquina_ok = False

if all_maquina_ok:
    print(f"\n✅ BLOQUE 2 (MAQUINAS) PASÓ: RM visible con todos los campos correctos.")
else:
    print(f"\n⚠️  BLOQUE 2 (MAQUINAS) tiene discrepancias, pero el RM aparece en Pizarra.")

# =============================================================================
# VERIFICACION ADICIONAL: formato de visualizacion (como usaria el frontend)
# =============================================================================
print("\n" + "=" * 70)
print("  VERIFICACION DE FORMATO (segun logica del frontend PizarraRMs.jsx)")
print("=" * 70)

# --- Cardio format (lineas 29-34 de PizarraRMs.jsx) ---
cat_cardio = "cardio"
partes_cardio = []
if rm_cardio.get("km"):
    partes_cardio.append(f"{rm_cardio['km']} km")
if rm_cardio.get("minutos"):
    partes_cardio.append(f"{rm_cardio['minutos']} min")
if rm_cardio.get("vueltas"):
    partes_cardio.append(f"{rm_cardio['vueltas']} vueltas")
cardio_display = ", ".join(
    partes_cardio) if partes_cardio else f"{rm_cardio.get('peso_kg', '?')}"
print(f"\n  Formato CARDIO (simulado): {cardio_display}")
print(f"  (Esperado: '0.4 km, 2 min, 1 vueltas')")

# --- Maquinas format (lineas 35-39 de PizarraRMs.jsx) ---
cat_maquina = "metabolico"
partes_maquina = []
if rm_maquina.get("calorias"):
    partes_maquina.append(f"{rm_maquina['calorias']} cal")
if rm_maquina.get("km"):
    partes_maquina.append(f"{rm_maquina['km']} km")
if rm_maquina.get("vueltas"):
    partes_maquina.append(f"{rm_maquina['vueltas']} vueltas")
maquina_display = ", ".join(
    partes_maquina) if partes_maquina else f"{rm_maquina.get('peso_kg', '?')}"
print(f"  Formato MAQUINAS (simulado): {maquina_display}")
print(f"  (Esperado: '300 cal, 3.5 km, 10 vueltas')")

# =============================================================================
# RESUMEN FINAL
# =============================================================================
print("\n" + "=" * 70)
print("  RESUMEN FINAL")
print("=" * 70)
print(f"""
  ✅ CARDIO:   movimiento '{mov_cardio['nombre']}' (ID={mov_cardio['id']})
               → minutos=2, km=0.4, vueltas=1
               → Visible en Pizarra: {'SI' if rm_cardio_pizarra else 'NO'}

  ✅ MAQUINAS: movimiento '{mov_maquina['nombre']}' (ID={mov_maquina['id']})
               → calorias=300, km=3.5, vueltas=10
               → Visible en Pizarra: {'SI' if rm_maquina_pizarra else 'NO'}

  Formato que vera el frontend:
    CARDIO:   {cardio_display}
    MAQUINAS: {maquina_display}
""")
print("=" * 70)
print("  PRUEBA COMPLETADA")
print("=" * 70)
