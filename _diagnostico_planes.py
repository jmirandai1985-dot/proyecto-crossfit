import requests
import json

BASE = 'http://localhost:8000/api/v1'

# 1. Buscar al usuario Alumno Demo por email
print("=" * 60)
print("1. BUSCAR USUARIO alumno@urbantraining.cl")
print("=" * 60)
users = requests.get(f'{BASE}/usuarios', params={'tenant_id': 1}).json()
alumno = None
for u in users:
    if 'alumno' in u.get('correo', '').lower() or u.get('id') == 5:
        alumno = u
        print(
            f"  ID={u.get('id')} nombre={u.get('nombre')} correo={u.get('correo')} rol={u.get('rol')}")
print(
    f"\n  Alumno encontrado: ID={alumno.get('id') if alumno else 'NO ENCONTRADO'}")

if alumno:
    uid = alumno['id']

    # 2. Suscripciones del alumno
    print("\n" + "=" * 60)
    print(f"2. SUSCRIPCIONES DEL USUARIO {uid}")
    print("=" * 60)
    # No hay endpoint directo, consultamos el endpoint que usa admin (suscripciones)
    from datetime import datetime, timezone
    subs = requests.get(f'{BASE}/suscripciones',
                        params={'tenant_id': 1, 'usuario_id': uid}).json()
    if isinstance(subs, list):
        print(f"  Total suscripciones: {len(subs)}")
        for s in subs:
            print(
                f"  ID={s.get('id')} plan_id={s.get('plan_id')} estado={s.get('estado')}")
            print(
                f"    creditos_totales={s.get('creditos_totales')} creditos_disponibles={s.get('creditos_disponibles')}")
            print(
                f"    fecha_inicio={s.get('fecha_inicio')} fecha_expiracion={s.get('fecha_expiracion')}")
    else:
        print(f"  Respuesta: {json.dumps(subs, indent=2)[:300]}")

    # 3. Membresia-activa (lo que usa el Dashboard)
    print("\n" + "=" * 60)
    print(f"3. MEMBRESIA-ACTIVA (Dashboard alumno) para usuario {uid}")
    print("=" * 60)
    try:
        res = requests.get(f'{BASE}/planes/membresia-activa',
                           params={'tenant_id': 1, 'alumno_id': uid})
        print(f"  Status: {res.status_code}")
        print(
            f"  Respuesta: {json.dumps(res.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"  Error: {e}")
        print(f"  Raw: {res.text[:300]}")

    # 4. Reservas POST - probar crear una
    print("\n" + "=" * 60)
    print(f"4. SIMULAR CREACION DE RESERVA para usuario {uid}")
    print("=" * 60)
    # Primero buscar una clase disponible hoy
    hoy = '2026-07-10'
    clases = requests.get(
        f'{BASE}/clases', params={'tenant_id': 1, 'fecha': hoy, 'limit': 3}).json()
    if isinstance(clases, list) and len(clases) > 0:
        clase_id = clases[0]['id']
        print(
            f"  Clase seleccionada: ID={clase_id} {clases[0].get('disciplina_nombre')} {clases[0].get('hora_inicio')}")

        # Intentar crear reserva
        payload = {
            'tenant_id': 1,
            'clase_id': clase_id,
            'alumno_id': uid,
            'estado': 'confirmada'
        }
        try:
            res = requests.post(f'{BASE}/reservas', json=payload)
            print(f"  Status: {res.status_code}")
            if res.status_code < 300:
                print(
                    f"  ✅ Reserva creada: {json.dumps(res.json(), indent=2, ensure_ascii=False)[:200]}")
            else:
                print(f"  ❌ Error: {res.text[:500]}")
        except Exception as e:
            print(f"  Exception: {e}")
    else:
        print(f"  No hay clases disponibles para hoy")
else:
    print("  No se pudo encontrar al alumno")
