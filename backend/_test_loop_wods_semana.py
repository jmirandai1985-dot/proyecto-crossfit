"""
TEST LOOP AUTONOMO: Publicar WOD para CADA DIA de la semana en CADA disciplina.
Max 8 iteraciones. Crea datos de prueba, verifica, documenta, y limpia.
Solo BD de TEST - usa ENVIRONMENT=test.
"""
import os
import sys
import json
import requests
import time
from datetime import datetime, timedelta, date, time as dtime

os.environ["ENVIRONMENT"] = "test"

BASE = "http://localhost:8000/api/v1"
TENANT_ID = 1
COACH_ID = 1000
ALUMNO_ID = 999
HOY = date.today()

DISCIPLINAS = [
    "CrossFit",
    "Levantamiento Olimpico",
    "Clase Intensiva Sabado",
]

LOG = []


def log(msg, data=None):
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(entry)
    if data:
        print(f"  DATA: {json.dumps(data, indent=2, default=str)[:200]}")
    LOG.append(
        entry + (f"\n  DATA: {json.dumps(data, default=str)[:300]}" if data else ""))


def api_get(path, params=None):
    r = requests.get(f"{BASE}{path}", params=params, timeout=10)
    if r.status_code >= 400:
        log(f"  GET {path} -> {r.status_code}: {r.text[:100]}")
    return r


def api_post(path, data=None, params=None):
    r = requests.post(f"{BASE}{path}", json=data, params=params, timeout=10)
    if r.status_code >= 400:
        log(f"  POST {path} -> {r.status_code}: {r.text[:200]}")
    return r


def api_put(path, data=None, params=None):
    r = requests.put(f"{BASE}{path}", json=data, params=params, timeout=10)
    if r.status_code >= 400:
        log(f"  PUT {path} -> {r.status_code}: {r.text[:200]}")
    return r


def api_delete(path, params=None):
    r = requests.delete(f"{BASE}{path}", params=params, timeout=10)
    return r


# ─── STEP 0: Verificar/Agregar disciplinas faltantes ───
log("=== FASE 0: SETUP DISCIPLINAS Y HORARIOS ===")
r = api_get(f"/disciplinas", {"tenant_id": TENANT_ID})
disciplinas_existentes = r.json() if r.status_code == 200 else []
log(f"Disciplinas existentes: {[d['nombre'] for d in disciplinas_existentes]}")

# Crear disciplinas faltantes
disciplina_ids = {}
for d in disciplinas_existentes:
    disciplina_ids[d['nombre']] = d['id']

for nombre in DISCIPLINAS:
    if nombre not in disciplina_ids:
        r = api_post(f"/disciplinas/", {"tenant_id": TENANT_ID,
                     "nombre": nombre, "activo": True}, {"tenant_id": TENANT_ID})
        if r.status_code in (200, 201):
            d = r.json()
            disciplina_ids[nombre] = d.get('id', d.get('data', {}).get('id'))
            log(
                f"Creada disciplina '{nombre}' con id={disciplina_ids[nombre]}")
        else:
            log(
                f"ERROR creando disciplina '{nombre}': {r.status_code} {r.text[:100]}")

log(f"Disciplina IDs: {disciplina_ids}")

# ─── STEP 1: Para cada dia de la semana (Lun-Dom), para cada disciplina ───
log("\n=== FASE 1: CREAR WODS POR DIA Y DISCIPLINA ===")

dias_semana_names = ["Lunes", "Martes", "Miercoles",
                     "Jueves", "Viernes", "Sabado", "Domingo"]
wods_creados = []
reservas_creadas = []

# Find which day of week is "sabado" (6)
for offset in range(7):
    dia = HOY + timedelta(days=offset)
    dia_semana = dia.weekday()  # 0=Monday, 6=Sunday
    dia_nombre = dias_semana_names[dia_semana]
    fecha_str = str(dia)

    log(f"\n--- DIA {offset+1}: {dia_nombre} ({fecha_str}) ---")

    for disc_nombre in DISCIPLINAS:
        # Skip "Clase Intensiva Sabado" if not Saturday
        if disc_nombre == "Clase Intensiva Sabado" and dia_semana != 5:
            log(f"  SKIP {disc_nombre}: solo aplica Sabado")
            continue

        disc_id = disciplina_ids.get(disc_nombre)
        if not disc_id:
            log(f"  SKIP {disc_nombre}: sin disciplina_id")
            continue

        # a) Check if there's a class for this day + disciplina
        r = api_get(f"/clases", {"tenant_id": TENANT_ID,
                    "fecha_desde": fecha_str, "fecha_hasta": fecha_str, "limit": 50})
        clases = r.json() if r.status_code == 200 else []
        if isinstance(clases, dict):
            clases = clases.get("clases", [])

        # Find classes matching this disciplina
        clases_disc = [c for c in clases if c.get("disciplina_id") == disc_id]

        if not clases_disc:
            log(f"  SKIP {disc_nombre}: sin clase para {fecha_str}")
            continue

        clase = clases_disc[0]
        clase_id = clase.get("id")
        log(f"  Clase encontrada: id={clase_id}, hora={clase.get('hora_inicio')}")

        # b) Create a WOD with distinctive title
        wod_title = f"TEST {dia_nombre.upper()} - {disc_nombre}"
        wod_data = {
            "titulo": wod_title,
            "calentamiento": f"Calentamiento TEST para {dia_nombre}",
            "fuerza_habilidad": f"Fuerza TEST para {dia_nombre}",
            "wod_principal": f"WOD PRINCIPAL: 21-15-9 de {disc_nombre} para {dia_nombre}",
            "tipo_metcon": "AMRAP",
            "estado": "publicado",
            "fecha": fecha_str,
            "coach_id": COACH_ID,
            "tenant_id": TENANT_ID
        }
        r = api_post(f"/wods/", wod_data, {"tenant_id": TENANT_ID})

        if r.status_code in (200, 201):
            wod_res = r.json()
            wod_id = wod_res.get("id")
            log(f"  WOD CREADO: id={wod_id}, titulo='{wod_title}'")
            wods_creados.append(wod_id)

            # c) Assign WOD to class
            r2 = api_post(
                f"/wods/clases/{clase_id}/asignar-wod/{wod_id}", {}, {"tenant_id": TENANT_ID})
            if r2.status_code in (200, 201):
                log(f"  WOD asignado a clase {clase_id}")
            else:
                log(
                    f"  WARNING: Asignacion WOD a clase: {r2.status_code} {r2.text[:100]}")

            # d) Create reservation for alumno 999
            r3 = api_post(f"/reservas/", {
                "tenant_id": TENANT_ID,
                "alumno_id": ALUMNO_ID,
                "clase_id": clase_id,
                "fecha": fecha_str,
                "estado": "confirmada"
            }, {"tenant_id": TENANT_ID})
            if r3.status_code in (200, 201):
                res_id = r3.json().get("id")
                reservas_creadas.append(res_id)
                log(f"  RESERVA CREADA: id={res_id}")
            else:
                log(f"  WARNING: Reserva: {r3.status_code} {r3.text[:100]}")

            # e) Verify via API that alumno 999 would see the WOD
            r4 = api_get(
                f"/wods/hoy", {"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID, "fecha": fecha_str})
            if r4.status_code == 200:
                wod_visto = r4.json()
                wod_visto_title = wod_visto.get("titulo") if isinstance(wod_visto, dict) else (
                    wod_visto[0].get("titulo") if isinstance(wod_visto, list) and len(wod_visto) > 0 else "N/A")
                log(
                    f"  VERIFICACION ALUMNO: WOD visto = '{wod_visto_title}'", wod_visto)
            else:
                log(
                    f"  VERIFICACION ALUMNO: GET /wods/hoy -> {r4.status_code}", r4.text[:100])
        else:
            log(f"  ERROR creando WOD: {r.status_code} {r.text[:200]}")

    # Max 8 iterations
    if offset >= 7:
        break

# ─── STEP 2: Write log file ───
log_text = "\n".join(LOG)
with open("LOG_TEST_WODS_SEMANA.md", "w", encoding="utf-8") as f:
    f.write("# LOG TEST WODS SEMANA\n\n")
    f.write(f"Fecha ejecucion: {datetime.now().isoformat()}\n")
    f.write(f"WODs creados: {len(wods_creados)}\n")
    f.write(f"Reservas creadas: {len(reservas_creadas)}\n\n")
    f.write("## Log detallado\n\n")
    f.write("```\n")
    f.write(log_text)
    f.write("\n```\n")

print("\n\n=" * 40)
print(f"LOG escrito en LOG_TEST_WODS_SEMANA.md")
print(f"WODs creados: {wods_creados}")
print(f"Reservas creadas: {reservas_creadas}")
print("=" * 40)
