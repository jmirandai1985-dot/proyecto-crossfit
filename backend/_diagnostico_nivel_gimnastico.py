"""
Diagnóstico: ¿por qué top_rms gimnásticos vienen vacíos?
Ejecutar con: python _diagnostico_nivel_gimnastico.py
"""
import requests
import json

BASE = "http://localhost:8000/api/v1"
ALUMNO_ID = 5
TENANT_ID = 1


def print_json(label, data):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# 1. Nivel gimnástico
r = requests.get(
    f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/nivel-gimnastico",
    params={"tenant_id": TENANT_ID}
)
print_json("RESPUESTA COMPLETA /nivel-gimnastico", r.json())

# 2. Nivel fuerza (para comparar)
r2 = requests.get(
    f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/nivel-fuerza",
    params={"tenant_id": TENANT_ID}
)
print_json("RESPUESTA /nivel-fuerza (comparación)", r2.json())

# 3. Todos los RMs del alumno (para ver qué movimientos gimnásticos existen realmente)
r3 = requests.get(
    f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/rms",
    params={"tenant_id": TENANT_ID}
)
print_json("TODOS LOS RMs DEL ALUMNO", r3.json())

# 4. Listar movimientos con categoría gimnastico
r4 = requests.get(
    f"{BASE}/movimientos",
    params={"tenant_id": TENANT_ID}
)
data4 = r4.json()
gimnasticos = [m for m in data4 if isinstance(
    m, dict) and m.get("categoria") == "gimnastico"]
print_json(f"MOVIMIENTOS GIMNÁSTICOS ({len(gimnasticos)})", gimnasticos)
