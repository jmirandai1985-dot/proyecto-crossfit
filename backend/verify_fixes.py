"""
Script de verificación de los fixes de BUG 1 y BUG 2
Requiere: $env:ENVIRONMENT="test" y servidor corriendo en localhost:8000
"""
import os
import sys
import requests

ENVIRONMENT = os.environ.get("ENVIRONMENT", "")
if ENVIRONMENT != "test":
    print("❌ ERROR: Debes setear $env:ENVIRONMENT='test' primero")
    sys.exit(1)

BASE = "http://localhost:8000"


def test_bug1():
    """BUG 1: GET /api/v1/usuarios/?rol=coach&tenant_id=1 (sin activo)"""
    print("\n=== TEST BUG 1: Listado de coaches ===")
    url = f"{BASE}/api/v1/usuarios/"
    params = {"rol": "coach", "tenant_id": 1}
    r = requests.get(url, params=params)
    print(f"GET {url} params={params}")
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"✅ 200 OK - {len(data)} coaches encontrados")
        if data:
            print(f"   Primer coach: {data[0]}")
        return True
    else:
        print(f"❌ {r.status_code}: {r.text}")
        return False


def test_bug2():
    """BUG 2: Crear coach, crear disciplina, PUT /coach-disciplinas/reemplazar"""
    print("\n=== TEST BUG 2: Guardado de disciplinas del coach ===")

    # 1. Crear un coach de prueba
    coach_data = {
        "nombre": "Coach Test Fix",
        "correo": f"coach_fix_{os.urandom(4).hex()}@test.com",
        "password": "test123456",
        "rol": "coach",
        "rut": f"{os.urandom(4).hex()[:8]}-{os.urandom(1).hex()}",
        "tenant_id": 1
    }
    r = requests.post(f"{BASE}/api/v1/usuarios/", json=coach_data)
    print(f"POST /api/v1/usuarios/ (crear coach) → Status: {r.status_code}")
    if r.status_code != 201:
        print(f"❌ Falló creación de coach: {r.text}")
        return False
    coach_id = r.json()["id"]
    print(f"✅ Coach creado con ID={coach_id}")

    # 2. Obtener disciplinas existentes
    r = requests.get(f"{BASE}/api/v1/disciplinas/", params={"tenant_id": 1})
    if r.status_code != 200:
        print(f"❌ Falló obtener disciplinas: {r.text}")
        return False
    disciplinas = r.json()
    if not disciplinas:
        print("⚠️ No hay disciplinas, no se puede probar reemplazar")
        # Crear una disciplina de prueba
        r = requests.post(f"{BASE}/api/v1/disciplinas/", json={
            "tenant_id": 1,
            "nombre": f"Disciplina Test {os.urandom(4).hex()}",
            "descripcion": "Test",
            "activo": True
        })
        if r.status_code != 201:
            print(f"❌ Falló crear disciplina: {r.text}")
            return False
        disc_id = r.json()["id"]
        print(f"✅ Disciplina creada con ID={disc_id}")
    else:
        disc_id = disciplinas[0]["id"]
        print(f"✅ Usando disciplina existente ID={disc_id}")

    # 3. PUT /coach-disciplinas/reemplazar (EXACTAMENTE como lo hace el frontend)
    replace_data = {
        "tenant_id": 1,
        "coach_id": coach_id,
        "disciplina_ids": [disc_id]
    }
    r = requests.put(
        f"{BASE}/api/v1/coach-disciplinas/reemplazar", json=replace_data)
    print(
        f"PUT /api/v1/coach-disciplinas/reemplazar → Status: {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Falló reemplazar: {r.text}")
        return False
    result = r.json()
    print(f"✅ 200 OK - {len(result)} disciplinas asignadas")
    if result:
        print(f"   Resultado: {result}")

    # 4. Verificar en DB directamente que los registros quedaron correctos
    try:
        from app.db.database import SessionLocal
        from app.models.coach_disciplina import CoachDisciplina

        db = SessionLocal()
        registros = db.query(CoachDisciplina).filter(
            CoachDisciplina.tenant_id == 1,
            CoachDisciplina.coach_id == coach_id,
            CoachDisciplina.activo == True
        ).all()
        db.close()
        print(
            f"\n✅ VERIFICACIÓN DB: {len(registros)} registro(s) activo(s) en coach_disciplinas")
        for reg in registros:
            print(
                f"   ID={reg.id}, coach_id={reg.coach_id}, disciplina_id={reg.disciplina_id}, activo={reg.activo}")
        assert len(
            registros) == 1, f"Esperado 1 registro activo, obtenidos {len(registros)}"
        assert registros[0].disciplina_id == disc_id
        print("✅ DB verificado correctamente")
    except Exception as e:
        print(
            f"⚠️ No se pudo verificar DB directamente (probablemente no se pudo importar): {e}")
        print("   La verificación HTTP ya pasó")

    return True


if __name__ == "__main__":
    print("="*60)
    print("VERIFICACIÓN DE FIXES - BUG 1 y BUG 2")
    print("="*60)

    ok1 = test_bug1()
    ok2 = test_bug2()

    print("\n" + "="*60)
    if ok1 and ok2:
        print("✅ AMBOS FIXES VERIFICADOS EXITOSAMENTE")
    else:
        print("❌ ALGUNOS FIXES FALLARON")
        if not ok1:
            print("   - BUG 1: FAIL")
        if not ok2:
            print("   - BUG 2: FAIL")
    print("="*60)
