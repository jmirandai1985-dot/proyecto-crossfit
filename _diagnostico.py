import requests
import json
import sys

BASE = 'http://localhost:8000/api/v1'


def print_sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# PROBLEMA 3: Clases para hoy (10 Jul 2026)
print_sep("CLASES HOY (10 Jul 2026)")
r = requests.get(f'{BASE}/clases',
                 params={'tenant_id': 1, 'fecha': '2026-07-10'})
try:
    data = r.json()
    print(f"Status: {r.status_code}")
    if isinstance(data, list):
        print(f"Total clases: {len(data)}")
        for c in data:
            print(f"  ID={c.get('id')} {c.get('disciplina_nombre', '?')} {c.get('hora_inicio', '')}-{c.get('hora_fin', '')} cupo={c.get('cupo_maximo', 0)} asistentes={c.get('asistentes_confirmados', 0)}")
    else:
        print(f"Respuesta: {json.dumps(data, indent=2)[:300]}")
except Exception as e:
    print(f"Error: Status {r.status_code} - {r.text[:300]}")

# Clases MAÑANA (11 Jul)
print_sep("CLASES MAÑANA (11 Jul 2026)")
r = requests.get(f'{BASE}/clases',
                 params={'tenant_id': 1, 'fecha': '2026-07-11'})
try:
    data = r.json()
    print(f"Status: {r.status_code}")
    if isinstance(data, list):
        print(f"Total: {len(data)}")
        for c in data:
            print(
                f"  ID={c.get('id')} {c.get('disciplina_nombre', '?')} {c.get('hora_inicio', '')}-{c.get('hora_fin', '')}")
    else:
        print(f"Data: {json.dumps(data, indent=2)[:300]}")
except:
    print(f"Error: Status {r.status_code} - {r.text[:300]}")

# Todas las clases
print_sep("TODAS LAS CLASES (limit=10)")
r = requests.get(f'{BASE}/clases', params={'tenant_id': 1, 'limit': 10})
try:
    data = r.json()
    if isinstance(data, list):
        print(f"Total: {len(data)}")
        for c in data[:10]:
            print(f"  ID={c.get('id')} fecha={c.get('fecha', '?')} {c.get('disciplina_nombre', '?')} {c.get('hora_inicio', '')}-{c.get('hora_fin', '')}")
    else:
        print(f"Data: {json.dumps(data, indent=2)[:300]}")
except:
    print(f"Error: Status {r.status_code} - {r.text[:300]}")

# PROBLEMA 5: Historial RM del alumno
print_sep("HISTORIAL RM (alumno_id=1)")
r = requests.get(f'{BASE}/historial-rm',
                 params={'tenant_id': 1, 'alumno_id': 1})
try:
    data = r.json()
    print(f"Status: {r.status_code}")
    if isinstance(data, list):
        print(f"Total registros: {len(data)}")
        for rm in data:
            print(
                f"  movimiento_id={rm.get('movimiento_id')} nombre={rm.get('movimiento_nombre', '?')} peso={rm.get('peso_kg')} tipo={rm.get('tipo_rm')} fecha={rm.get('fecha')}")
    else:
        print(f"Data: {json.dumps(data, indent=2)[:300]}")
except:
    print(f"Error: Status {r.status_code}")

# RMs agrupados por movimiento
print_sep("RMS ALUMNO 1 (mejor por movimiento)")
r = requests.get(f'{BASE}/historial-rm/alumnos/1/rms', params={'tenant_id': 1})
try:
    data = r.json()
    print(f"Status: {r.status_code}")
    if isinstance(data, list):
        print(f"Total movimientos con RM: {len(data)}")
        for rm in data:
            print(
                f"  movimiento_id={rm.get('movimiento_id')} nombre={rm.get('movimiento_nombre')} peso={rm.get('peso_kg')} tipo={rm.get('tipo_rm')}")
    else:
        print(f"Data: {json.dumps(data, indent=2)[:300]}")
except:
    print(f"Error: Status {r.status_code}")

# Nivel gimnastico endpoint
print_sep("NIVEL GIMNASTICO ALUMNO 1")
r = requests.get(
    f'{BASE}/historial-rm/alumnos/1/nivel-gimnastico', params={'tenant_id': 1})
try:
    data = r.json()
    print(f"Status: {r.status_code}")
    print(f"Respuesta: {json.dumps(data, indent=2, ensure_ascii=False)}")
except:
    print(f"Error: Status {r.status_code} - {r.text[:300]}")

# Nivel fuerza endpoint
print_sep("NIVEL FUERZA ALUMNO 1")
r = requests.get(
    f'{BASE}/historial-rm/alumnos/1/nivel-fuerza', params={'tenant_id': 1})
try:
    data = r.json()
    print(f"Status: {r.status_code}")
    print(f"Respuesta: {json.dumps(data, indent=2, ensure_ascii=False)}")
except:
    print(f"Error: Status {r.status_code} - {r.text[:300]}")

# PROBLEMA 2: Reservas del alumno
print_sep("RESERVAS ALUMNO 1 (usuario_id=1)")
r = requests.get(f'{BASE}/reservas', params={'tenant_id': 1,
                 'usuario_id': 1, 'estado': 'confirmada'})
try:
    data = r.json()
    print(f"Status: {r.status_code}")
    if isinstance(data, list):
        print(f"Total reservas activas: {len(data)}")
        for rv in data[:5]:
            print(
                f"  ID={rv.get('id')} clase_id={rv.get('clase_id')} alumno_id={rv.get('alumno_id')} estado={rv.get('estado')}")
    else:
        print(f"Data: {json.dumps(data, indent=2)[:300]}")
except:
    print(f"Error: Status {r.status_code} - {r.text[:300]}")

# PROBLEMA 4: WOD hoy
print_sep("WOD HOY")
r = requests.get(f'{BASE}/wods/hoy', params={'tenant_id': 1})
print(f"Status: {r.status_code}")
try:
    data = r.json()
    if data:
        print(f"Titulo: {data.get('titulo')}")
        print(f"Descripcion: {str(data.get('descripcion', ''))[:100]}")
        movs = data.get('movimientos', [])
        fases = data.get('fases', [])
        print(f"Movimientos directos: {len(movs)}")
        print(f"Fases: {len(fases)}")
        if fases:
            for f in fases:
                fm = f.get('movimientos', [])
                print(f"  Fase {f.get('nombre')}: {len(fm)} movimientos")
                for m in fm[:3]:
                    print(
                        f"    - {m.get('nombre')} series={m.get('series')} reps={m.get('repeticiones')} peso={m.get('peso')}")
        if movs:
            for m in movs[:3]:
                print(
                    f"  - {m.get('nombre')} series={m.get('series')} reps={m.get('repeticiones')} peso={m.get('peso')}")
    else:
        print("Body: null (no hay WOD para hoy)")
except Exception as e:
    print(f"Error parsing: {e}")
    print(f"Raw: {r.text[:300]}")

# Movimientos disponibles
print_sep("MOVIMIENTOS")
r = requests.get(f'{BASE}/movimientos', params={'tenant_id': 1})
try:
    data = r.json()
    if isinstance(data, list):
        print(f"Total movimientos: {len(data)}")
        for m in data[:10]:
            print(
                f"  ID={m.get('id')} {m.get('nombre')} cat={m.get('categoria', '?')}")
        if len(data) > 10:
            print(f"  ... y {len(data)-10} mas")
    else:
        print(f"Data: {json.dumps(data, indent=2)[:300]}")
except:
    print(f"Error: Status {r.status_code}")

print("\n=== DIAGNOSTICO COMPLETADO ===")
