"""
Script de prueba para verificar la política de cancelación con penalización.
Ejecutar con: python _test_penalizacion_cancelacion.py

Prerequisito: tener el backend corriendo y al menos 1 clase futura y 1 clase hoy.
"""
import requests
import json
from datetime import datetime, timezone

BASE = "http://localhost:8000/api/v1"
ALUMNO_ID = 5
TENANT_ID = 1


def print_sep(titulo):
    print(f"\n{'='*60}")
    print(f"  {titulo}")
    print(f"{'='*60}")


def get_creditos():
    r = requests.get(
        f"{BASE}/planes/membresia-activa",
        params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID}
    )
    data = r.json()
    print(f"  Créditos disponibles: {data.get('clases_disponibles', 'N/A')}")
    print(f"  Plan: {data.get('plan_nombre', 'N/A')}")
    print(f"  Activa: {data.get('activa', 'N/A')}")
    return data.get("clases_disponibles", 0)


def listar_clases(desde, hasta):
    r = requests.get(
        f"{BASE}/clases",
        params={"tenant_id": TENANT_ID, "fecha_desde": desde,
                "fecha_hasta": hasta, "limit": 50}
    )
    data = r.json()
    if isinstance(data, list):
        # Filtrar con cupo
        con_cupo = [c for c in data if (
            c.get("cupo_maximo", 0) - c.get("asistentes_confirmados", 0)) > 0]
        return con_cupo
    return []


def crear_reserva(clase_id):
    r = requests.post(f"{BASE}/reservas", json={
        "tenant_id": TENANT_ID,
        "alumno_id": ALUMNO_ID,
        "clase_id": clase_id,
        "estado": "confirmada"
    })
    print(f"  POST /reservas → Status: {r.status_code}")
    if r.status_code < 300:
        data = r.json()
        print(f"  Reserva ID: {data.get('id')}")
        return data.get("id")
    else:
        print(f"  Error: {r.text[:300]}")
        return None


def cancelar_reserva(reserva_id):
    r = requests.delete(f"{BASE}/reservas/{reserva_id}",
                        params={"tenant_id": TENANT_ID})
    print(f"  DELETE /reservas/{reserva_id} → Status: {r.status_code}")
    return r.status_code < 300


# ─── TEST ───────────────────────────────────────────────────────────
print("\n🚀 INICIANDO PRUEBA DE POLÍTICA DE CANCELACIÓN")
print(f"   Alumno ID: {ALUMNO_ID}, Tenant ID: {TENANT_ID}")
print(
    f"   Fecha/hora actual: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

# Paso 1: Créditos iniciales
print_sep("PASO 1: CRÉDITOS INICIALES")
creditos_inicial = get_creditos()

# Paso 2: Buscar una clase FUTURA (≥ 6h desde ahora) y una de HOY
print_sep("PASO 2: BUSCAR CLASES DISPONIBLES")
hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
manana = datetime.now(timezone.utc).strftime("%Y-%m-%d")

clases_hoy = listar_clases(hoy, hoy)
clases_futuras = listar_clases(hoy, "2026-07-20")  # Rango amplio

print(f"  Clases hoy con cupo: {len(clases_hoy)}")
for c in clases_hoy:
    print(
        f"    ID={c['id']} {c.get('disciplina_nombre', '?')} {c.get('fecha')} {c.get('hora_inicio')}")

print(f"  Clases futuras con cupo: {len(clases_futuras)}")
for c in clases_futuras:
    print(
        f"    ID={c['id']} {c.get('disciplina_nombre', '?')} {c.get('fecha')} {c.get('hora_inicio')}")

# Buscar una clase que cumpla ≥ 6h (futura)
clase_futura = None
clase_hoy_proxima = None
for c in clases_futuras:
    if c.get("fecha") and c.get("hora_inicio"):
        # Calcular si es ≥ 6h
        try:
            partes_hora = c["hora_inicio"].split(":")
            h = int(partes_hora[0])
            m = int(partes_hora[1])
            fecha_parts = c["fecha"].split("-")
            inicio = datetime(int(fecha_parts[0]), int(fecha_parts[1]), int(fecha_parts[2]),
                              h, m, tzinfo=timezone.utc)
            ahora = datetime.now(timezone.utc)
            horas = (inicio - ahora).total_seconds() / 3600
            if horas >= 6 and not clase_futura:
                clase_futura = c
                print(
                    f"\n  ✅ Clase FUTURA: ID={c['id']} {c.get('disciplina_nombre', '?')} ({horas:.0f}h de anticipación)")
            elif 0 <= horas < 6 and not clase_hoy_proxima:
                clase_hoy_proxima = c
                print(
                    f"\n  ⚠️ Clase PRÓXIMA: ID={c['id']} {c.get('disciplina_nombre', '?')} ({horas:.0f}h de anticipación)")
        except Exception as e:
            # Silently skip malformed data
            pass

if not clase_futura and not clase_hoy_proxima:
    print("\n  ❌ No se encontraron clases adecuadas para la prueba.")
    print("  Intenta con otro rango de fechas.")
    exit(1)

# Paso 3: Crear reserva en clase FUTURA
if clase_futura:
    print_sep("PASO 3: CREAR RESERVA EN CLASE FUTURA (≥ 6h)")
    res_id = crear_reserva(clase_futura["id"])
    if res_id:
        print_sep("PASO 4: CRÉDITOS DESPUÉS DE RESERVAR")
        creditos_post_reserva = get_creditos()
        print(f"\n  📊 Créditos iniciales: {creditos_inicial}")
        print(f"  📊 Créditos después de reservar: {creditos_post_reserva}")
        print(
            f"  📊 Diferencia: {creditos_post_reserva - creditos_inicial} (debería ser -1)")

        # Paso 5: Cancelar la reserva (debería devolver crédito)
        print_sep("PASO 5: CANCELAR RESERVA FUTURA (≥ 6h → debe devolver crédito)")
        cancelar_reserva(res_id)
        creditos_post_cancelacion = get_creditos()
        print(
            f"\n  📊 Créditos después de cancelar: {creditos_post_cancelacion}")
        print(
            f"  📊 Diferencia vs inicial: {creditos_post_cancelacion - creditos_inicial} (debería ser 0)")
        print(
            f"  ✅ Test {'PASÓ' if creditos_post_cancelacion == creditos_inicial else 'FALLÓ'}")

# Paso 6: Crear reserva en clase PRÓXIMA (< 6h)
if clase_hoy_proxima:
    print_sep("PASO 6: CREAR RESERVA EN CLASE PRÓXIMA (< 6h)")
    res_id2 = crear_reserva(clase_hoy_proxima["id"])
    if res_id2:
        creditos_post_reserva2 = get_creditos()
        print(
            f"\n  📊 Créditos después de reserva #2: {creditos_post_reserva2}")

        print_sep(
            "PASO 7: CANCELAR RESERVA PRÓXIMA (< 6h → NO debe devolver crédito)")
        cancelar_reserva(res_id2)
        creditos_post_cancelacion2 = get_creditos()
        print(
            f"\n  📊 Créditos después de cancelar #2: {creditos_post_cancelacion2}")
        # No debe haber devuelto el crédito
        sin_devolucion = creditos_post_cancelacion2 == creditos_post_reserva2
        print(f"  📊 Crédito sin devolver: {sin_devolucion} (debería ser True)")
        print(f"  ✅ Test {'PASÓ' if sin_devolucion else 'FALLÓ'}")

print("\n" + "="*60)
print("  PRUEBA COMPLETADA")
print("="*60)
