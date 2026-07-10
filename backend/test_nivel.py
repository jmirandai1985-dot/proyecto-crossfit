"""
Script de prueba para el cálculo de nivel.
"""
import requests
import json

BASE = "http://localhost:8000"

token = None
tenant_id = 1
alumno_id = None

try:
    # 1. Login as admin
    r = requests.post(f"{BASE}/api/v1/auth/login", json={
        "correo": "admin@urbanbox.cl",
        "password": "admin123"
    })
    print(f"1. Login: {r.status_code}")
    if r.status_code == 200:
        token = r.json().get("access_token")
        print(f"   Token: {token[:30]}...")
    else:
        print(f"   Error: {r.text}")
        # Try default admin
        r = requests.post(f"{BASE}/api/v1/auth/login", json={
            "correo": "admin@test.com",
            "password": "admin123"
        })
        print(f"   Login alt: {r.status_code}")
        if r.status_code == 200:
            token = r.json().get("access_token")

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # 2. Find first alumno
    r = requests.get(
        f"{BASE}/api/v1/usuarios?tenant_id={tenant_id}&rol=alumno", headers=headers)
    print(f"2. Alumnos: {r.status_code}")
    if r.status_code == 200:
        alumnos = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
        if alumnos and len(alumnos) > 0:
            alumno_id = alumnos[0].get("id") if isinstance(
                alumnos[0], dict) else alumnos[0][0]
            print(f"   Alumno ID: {alumno_id}")

            # 3. Set peso_kg and genero for test alumno
            name = alumno_id
            r = requests.put(f"{BASE}/api/v1/usuarios/{alumno_id}", headers=headers, json={
                "peso_kg": 75,
                "genero": "M"
            })
            print(f"3. Set perfil: {r.status_code}")

            # 4. Test nivel-fuerza endpoint (Back Squat=2799, peso_rm=130)
            r = requests.post(f"{BASE}/api/v1/historial-rm/nivel-fuerza",
                              params={
                                  "alumno_id": alumno_id, "movimiento_id": 2799, "peso_rm": 130, "tenant_id": 1},
                              headers=headers)
            print(
                f"4. Nivel fuerza (Back Squat 130kg @ 75kg): {r.status_code}")
            if r.status_code == 200:
                print(f"   Resultado: {json.dumps(r.json(), indent=2)}")

            # 5. Test nivel-gimnastico (T2B=2803, valor=12 reps)
            r = requests.post(f"{BASE}/api/v1/historial-rm/nivel-gimnastico",
                              params={
                                  "alumno_id": alumno_id, "movimiento_id": 2803, "valor": 12, "tenant_id": 1},
                              headers=headers)
            print(f"5. Nivel gimnastico (T2B 12 reps): {r.status_code}")
            if r.status_code == 200:
                print(f"   Resultado: {json.dumps(r.json(), indent=2)}")

            # 6. Test nivel-general
            r = requests.get(f"{BASE}/api/v1/historial-rm/alumnos/{alumno_id}/nivel-general",
                             params={"tenant_id": 1}, headers=headers)
            print(f"6. Nivel general: {r.status_code}")
            if r.status_code == 200:
                print(f"   Resultado: {json.dumps(r.json(), indent=2)}")

            # 7. Test Wall Balls (Grupo C - no debe aplicar)
            r = requests.post(f"{BASE}/api/v1/historial-rm/nivel-fuerza",
                              params={
                                  "alumno_id": alumno_id, "movimiento_id": 2814, "peso_rm": 20, "tenant_id": 1},
                              headers=headers)
            print(f"7. Nivel fuerza (Wall Balls): {r.status_code}")
            if r.status_code == 200:
                print(f"   Resultado: {json.dumps(r.json(), indent=2)}")
    else:
        print(f"   Error: {r.text}")

except Exception as e:
    print(f"ERROR: {e}")
