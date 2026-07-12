"""
Script de diagnóstico: Analiza por qué "Asistencia del Mes" muestra
"Sin reservas este mes" cuando el alumno SI tiene 2 reservas activas,
solo que son para fechas futuras.

Ejecutar con:
  cd backend && python _test_asistencia_mes.py
"""
import requests
import json
from datetime import date, datetime

BASE = "http://localhost:8000/api/v1"
ALUMNO_ID = 5
TENANT_ID = 1
hoy = date.today()

print(f"Fecha actual del sistema: {hoy}")
print(f"Año: {hoy.year}, Mes: {hoy.month}")
print(f"Primer día del mes: {date(hoy.year, hoy.month, 1)}")
print(f"Último día del mes (estimado): NO APLICA (el endpoint usa hoy como tope)")
print()

# =============================================================================
# 1. CONSULTAR EL ENDPOINT DE ASISTENCIA-MES
# =============================================================================
print("=" * 70)
print("  1) GET /reservas/asistencia-mes")
print("=" * 70)

r = requests.get(
    f"{BASE}/reservas/asistencia-mes",
    params={"tenant_id": TENANT_ID, "usuario_id": ALUMNO_ID},
)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    data_asistencia = r.json()
    print(f"  Respuesta JSON:")
    print(json.dumps(data_asistencia, indent=4, ensure_ascii=False))
else:
    print(f"  Error: {r.text[:500]}")
    data_asistencia = {}

print()

# =============================================================================
# 2. CONSULTAR TODAS LAS RESERVAS DEL ALUMNO (sin filtro de estado)
# =============================================================================
print("=" * 70)
print("  2) GET /reservas?tenant_id=1&usuario_id=5 (TODAS)")
print("=" * 70)

r = requests.get(
    f"{BASE}/reservas",
    params={"tenant_id": TENANT_ID, "usuario_id": ALUMNO_ID, "limit": 200},
)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    reservas = r.json()
    print(f"  Total reservas del alumno: {len(reservas)}")
    print(f"  Reservas:")
    for i, res in enumerate(reservas):
        print(f"    [{i+1}] ID={res.get('id')} "
              f"clase_id={res.get('clase_id')} "
              f"fecha_clase={res.get('clase_fecha')} "
              f"estado={res.get('estado')} "
              f"asistio={res.get('asistio')} "
              f"disciplina={res.get('disciplina_nombre')}")
else:
    print(f"  Error: {r.text[:500]}")
    reservas = []

print()

# =============================================================================
# 3. ANALISIS DETALLADO: contar las de julio, pasado v/s futuro
# =============================================================================
print("=" * 70)
print("  3) ANALISIS: reservas de Julio 2026")
print("=" * 70)

total_julio = 0
pasadas = 0
futuras = 0
sin_fecha = 0

for res in reservas:
    fecha_str = res.get("clase_fecha")
    if not fecha_str:
        sin_fecha += 1
        continue

    try:
        fecha_clase = datetime.strptime(fecha_str[:10], "%Y-%m-%d").date()
    except ValueError:
        sin_fecha += 1
        continue

    if fecha_clase.year == 2026 and fecha_clase.month == 7:
        total_julio += 1
        if fecha_clase <= hoy:
            pasadas += 1
            print(f"    PASADA:  ID={res.get('id')} "
                  f"fecha={fecha_clase} estado={res.get('estado')} "
                  f"asistio={res.get('asistio')} "
                  f"→ ({res.get('disciplina_nombre')})")
        else:
            futuras += 1
            print(f"    FUTURA:  ID={res.get('id')} "
                  f"fecha={fecha_clase} estado={res.get('estado')} "
                  f"asistio={res.get('asistio')} "
                  f"→ ({res.get('disciplina_nombre')})")

print(f"\n  Resumen Julio 2026:")
print(f"    Total reservas en julio: {total_julio}")
print(f"    Pasadas (fecha <= {hoy}):    {pasadas}")
print(f"    Futuras (fecha > {hoy}):     {futuras}")
print(f"    Sin fecha:                   {sin_fecha}")

# =============================================================================
# 4. CONCLUSION
# =============================================================================
print()
print("=" * 70)
print("  4) CONCLUSION")
print("=" * 70)

if total_julio == 0:
    print("""
  El alumno NO tiene ninguna reserva en julio.
  → El mensaje 'Sin reservas este mes' es CORRECTO.
""")
elif pasadas == 0 and futuras > 0:
    print(f"""
  El alumno tiene {futuras} reserva(s) FUTURA(S) en julio pero NINGUNA pasada.
  El endpoint de asistencia-mes filtra con Clase.fecha <= hoy ({hoy}),
  por lo que EXCLUYE las reservas futuras. Esto es CORRECTO para calcular
  asistencia (no se puede medir asistencia a clases que aún no ocurren).

  El mensaje 'Sin reservas este mes' es TÉCNICAMENTE CORRECTO pero
  ENGAÑOSO: suena a que no hay ninguna reserva cuando sí las hay futuras.

  Posible mejora: cambiar el mensaje a algo como:
  - 'Sin clases completadas este mes' si hay reservas pero todas futuras
  - 'Sin reservas este mes' si no hay ninguna reserva en absoluto
""")
elif pasadas > 0:
    print(f"""
  El alumno tiene {pasadas} reserva(s) PASADA(S) en julio.
  Si el endpoint muestra 'Sin reservas', hay un BUG en otro lado.
""")
else:
    print("""
  Caso no contemplado. Revisar manualmente.
""")
