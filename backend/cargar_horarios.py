"""
Script para cargar todos los horarios del Urban Training Box
"""
import requests

BASE_URL = "http://localhost:8000/api/v1"
TENANT_ID = 1

# IDs de disciplinas
CROSSFIT = 1
MUSCULACION = 3
OPEN_BOX = 4
LEVANTAMIENTO = 5
INTENSIVA_SAB = 6

# dias: 0=Lunes, 1=Martes, 2=Miercoles, 3=Jueves, 4=Viernes, 5=Sabado
LUNES_VIERNES = [0, 1, 2, 3, 4]
LMV = [0, 2, 4]  # Lunes, Miercoles, Viernes

horarios = [
    # CrossFit Lun-Vie mañana
    *[{"dia": d, "inicio": "07:00", "fin": "08:00",
        "disciplina": CROSSFIT, "cupo": 16} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "08:00", "fin": "09:00",
        "disciplina": CROSSFIT, "cupo": 16} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "09:00", "fin": "10:00",
        "disciplina": CROSSFIT, "cupo": 16} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "14:00", "fin": "15:00",
        "disciplina": CROSSFIT, "cupo": 16} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "18:00", "fin": "19:00",
        "disciplina": CROSSFIT, "cupo": 16} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "19:00", "fin": "20:00",
        "disciplina": CROSSFIT, "cupo": 16} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "20:00", "fin": "21:00",
        "disciplina": CROSSFIT, "cupo": 16} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "21:00", "fin": "22:00",
        "disciplina": CROSSFIT, "cupo": 16} for d in LUNES_VIERNES],

    # Musculacion Lun-Vie
    *[{"dia": d, "inicio": "07:00", "fin": "08:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "08:00", "fin": "09:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "09:00", "fin": "10:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "10:00", "fin": "14:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "14:00", "fin": "15:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "15:00", "fin": "17:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "18:00", "fin": "19:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "19:00", "fin": "20:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "20:00", "fin": "21:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "21:00", "fin": "22:00",
        "disciplina": MUSCULACION, "cupo": 50} for d in LUNES_VIERNES],

    # Open Box Lun-Vie
    *[{"dia": d, "inicio": "07:00", "fin": "08:00",
        "disciplina": OPEN_BOX, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "08:00", "fin": "09:00",
        "disciplina": OPEN_BOX, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "09:00", "fin": "10:00",
        "disciplina": OPEN_BOX, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "10:00", "fin": "14:00",
        "disciplina": OPEN_BOX, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "14:00", "fin": "15:00",
        "disciplina": OPEN_BOX, "cupo": 50} for d in LUNES_VIERNES],
    *[{"dia": d, "inicio": "15:00", "fin": "17:00",
        "disciplina": OPEN_BOX, "cupo": 50} for d in LUNES_VIERNES],

    # Levantamiento solo Lun, Mie, Vie
    *[{"dia": d, "inicio": "19:00", "fin": "20:00",
        "disciplina": LEVANTAMIENTO, "cupo": 12} for d in LMV],
    *[{"dia": d, "inicio": "20:00", "fin": "21:00",
        "disciplina": LEVANTAMIENTO, "cupo": 12} for d in LMV],

    # Sabado
    {"dia": 5, "inicio": "09:00", "fin": "13:00",
        "disciplina": INTENSIVA_SAB, "cupo": 16},
]


def cargar():
    print(f"Cargando {len(horarios)} horarios...")
    ok = 0
    error = 0
    for h in horarios:
        r = requests.post(f"{BASE_URL}/horarios", params={
            "tenant_id": TENANT_ID,
            "disciplina_id": h["disciplina"],
            "dia_semana": h["dia"],
            "hora_inicio": h["inicio"],
            "hora_fin": h["fin"],
            "cupo_maximo": h["cupo"]
        })
        if r.status_code == 201:
            ok += 1
        else:
            error += 1
            print(f"  ❌ Error: {h} → {r.text}")

    print(f"\n✅ Cargados: {ok}")
    print(f"❌ Errores: {error}")


if __name__ == "__main__":
    cargar()
