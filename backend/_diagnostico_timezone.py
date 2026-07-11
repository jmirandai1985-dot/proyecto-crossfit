"""
Diagnóstico de timezone: ¿Qué fecha usará el frontend?
"""
from datetime import datetime, timezone

local = datetime.now()
utc = datetime.now(timezone.utc)

print("=== DIAGNÓSTICO TIMEZONE ===")
print(f"1. Hora local (America/Santiago): {local}")
print(f"2. Hora UTC: {utc}")
print(f"3. Diferencia: UTC-4 (Chile en invierno)")

# Simular lo que hace el frontend:
# const TODAY = new Date().toISOString().split('T')[0];
# new Date() en JS usa la hora LOCAL del browser
# toISOString() CONVIERTE a UTC antes de formatear

# En el browser del usuario, su new Date() crea un objeto en hora local
# pero toISOString() devuelve la hora UTC

print(f"\n4. Fecha local (YYYY-MM-DD): {local.strftime('%Y-%m-%d')}")

# Simular TOISOString en UTC
utc_str = utc.strftime('%Y-%m-%d')
print(f"5. Fecha UTC (simula toISOString): {utc_str}")

# ¡¡ PROBLEMA !!
# Local: 2026-07-10 20:20 UTC-4
# UTC:   2026-07-11 00:20
# Frontend busca: 2026-07-11 -> 0 clases
# Debería buscar: 2026-07-10 -> 41 clases

print(f"\n6. Conclusión:")
print(f"   Si local=2026-07-10 20:20 UTC-4 → UTC=2026-07-11 00:20")
print(f"   toISOString() devuelve 2026-07-11")
print(f"   Frontend pide clases con fecha=2026-07-11 → 0 resultados")
print(f"   ¿El WOD funciona? Probablemente usa endpoint interno con fecha local")
