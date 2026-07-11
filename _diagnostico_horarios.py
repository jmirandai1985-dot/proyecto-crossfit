import requests
import json

BASE = 'http://localhost:8000/api/v1'

print("=== HORARIOS BASE (activos) ===")
r = requests.get(f'{BASE}/horarios', params={'tenant_id': 1, 'activo': True})
data = r.json()
print(f"Status: {r.status_code}")
if isinstance(data, list):
    print(f"Total activos: {len(data)}")
    dias = {0: 'Lun', 1: 'Mar', 2: 'Mie',
            3: 'Jue', 4: 'Vie', 5: 'Sab', 6: 'Dom'}
    for h in data:
        dia = dias.get(h.get('dia_semana'), h.get('dia_semana'))
        print(f"  ID={h.get('id')} {dia} {h.get('hora_inicio')}-{h.get('hora_fin')} cap={h.get('cupo_maximo')} activo={h.get('activo')}")

print()
print("=== HORARIOS BASE (todos) ===")
r2 = requests.get(f'{BASE}/horarios', params={'tenant_id': 1})
data2 = r2.json()
if isinstance(data2, list):
    print(f"Total: {len(data2)}")
    dias = {0: 'Lun', 1: 'Mar', 2: 'Mie',
            3: 'Jue', 4: 'Vie', 5: 'Sab', 6: 'Dom'}
    for h in data2:
        dia = dias.get(h.get('dia_semana'), h.get('dia_semana'))
        print(f"  ID={h.get('id')} {dia} {h.get('hora_inicio')}-{h.get('hora_fin')} disc_id={h.get('disciplina_id')} cap={h.get('cupo_maximo')} activo={h.get('activo')}")
else:
    print(f"Data: {json.dumps(data2, indent=2)[:300]}")

print()
print("=== DISCIPLINAS ===")
r3 = requests.get(f'{BASE}/disciplinas', params={'tenant_id': 1})
data3 = r3.json()
if isinstance(data3, list):
    print(f"Total: {len(data3)}")
    for d in data3:
        print(f"  ID={d.get('id')} nombre={d.get('nombre')}")
else:
    print(json.dumps(data3, indent=2)[:300])

# Buscar si hay algún endpoint o script de generación automática
print()
print("=== CLASES EXISTENTES ===")
r4 = requests.get(f'{BASE}/clases', params={'tenant_id': 1, 'limit': 50})
data4 = r4.json()
if isinstance(data4, list):
    print(f"Total: {len(data4)}")
    for c in data4:
        print(f"  ID={c.get('id')} fecha={c.get('fecha')} {c.get('hora_inicio')}-{c.get('hora_fin')} disc={c.get('disciplina_nombre', '?')} horario_base_id={c.get('horario_base_id')} coach={c.get('coach_nombre', '?')}")
else:
    print(json.dumps(data4, indent=2)[:300])
