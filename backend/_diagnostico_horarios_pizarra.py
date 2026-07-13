"""
DIAGNOSTICO: Horarios reales en PRODUCCION vs grilla hardcodeada en Pizarra.jsx
SOLO LECTURA - No modifica datos
"""
from sqlalchemy import text
from app.core.config import settings
from app.db.database import SessionLocal
import os
import json
import sys
os.environ["ENVIRONMENT"] = ""


print("=" * 70)
print("PASO 1: Consulta real a GET /api/v1/horarios?tenant_id=1 (via DB directa)")
print("=" * 70)

db_url = settings.DATABASE_URL
if "soft-bar" in db_url:
    print("[ERROR] Conectado a TEST. Se requiere PRODUCCION.")
    sys.exit(1)

print("[OK] BD: " + db_url[:50] + "...")
print()

db = SessionLocal()
try:
    # Simular lo que devuelve GET /api/v1/horarios?tenant_id=1
    rows = db.execute(text("""
        SELECT id, tenant_id, disciplina_id, dia_semana,
               hora_inicio::text AS hora_inicio,
               hora_fin::text AS hora_fin,
               cupo_maximo, activo
        FROM horarios
        WHERE tenant_id = 1
        ORDER BY dia_semana, hora_inicio
    """)).fetchall()

    print("RESPUESTA del backend (formato exacto que devuelve la API):")
    print("-" * 70)

    DIAS = {0: "lunes", 1: "martes", 2: "miercoles",
            3: "jueves", 4: "viernes", 5: "sabado", 6: "domingo"}

    if not rows:
        print("  [] (vacio - no hay horarios configurados para tenant_id=1)")
    else:
        horarios_por_dia = {}
        for r in rows:
            d = dict(r._mapping)
            dia = d["dia_semana"]
            dia_nombre = DIAS.get(dia, f"dia_{dia}")
            if dia_nombre not in horarios_por_dia:
                horarios_por_dia[dia_nombre] = []
            # Formato que devuelve la API
            horarios_por_dia[dia_nombre].append({
                "id": d["id"],
                "tenant_id": d["tenant_id"],
                "disciplina_id": d["disciplina_id"],
                "dia_semana": d["dia_semana"],
                "hora_inicio": d["hora_inicio"],
                "hora_fin": d["hora_fin"],
                "cupo_maximo": d["cupo_maximo"],
                "activo": d["activo"]
            })
            print(json.dumps(d, default=str))

        print()
        print("AGRUPADO por dia de semana:")
        print("-" * 70)
        for dia_nombre in ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]:
            horarios = horarios_por_dia.get(dia_nombre, [])
            slots = [
                f"{h['hora_inicio'][:5]}-{h['hora_fin'][:5]}" for h in horarios]
            print(f"  {dia_nombre}: {slots if slots else '(sin horarios)'}")

    print()
    print("=" * 70)
    print("PASO 2: GRILLA HARDCODEADA en Pizarra.jsx (lineas 78-85)")
    print("=" * 70)
    HORARIOS_SEMANA = {
        "lunes": ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
        "martes": ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
        "miercoles": ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
        "jueves": ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
        "viernes": ['7:00-8:00', '8:00-9:00', '9:00-10:00', '10:00-11:00', '11:00-12:00', '15:00-16:00', '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00'],
        "sabado": ['10:00-12:00']
    }

    print()
    print("GRILLA HARDCODEADA (lo que ve el coach ahora):")
    print("-" * 70)
    for dia, slots in HORARIOS_SEMANA.items():
        print(f"  {dia}: {slots}")

    print()
    print("=" * 70)
    print("PASO 3: COMPARACION")
    print("=" * 70)

    print()
    print("DIFERENCIAS encontradas:")
    print("-" * 70)

    for dia_nombre in ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]:
        horarios_api = horarios_por_dia.get(dia_nombre, [])
        slots_api = set(
            f"{h['hora_inicio'][:5]}-{h['hora_fin'][:5]}" for h in horarios_api)
        slots_hardcode = set(HORARIOS_SEMANA.get(dia_nombre, []))

        # Normalizar formato: hardcode usa "7:00-8:00", API devuelve "07:00:00-08:00:00"
        slots_api_normalized = set()
        for s in slots_api:
            parts = s.split("-")
            if len(parts) == 2:
                h1 = parts[0].lstrip("0") or "0"
                if len(h1.split(":")[0]) == 1:
                    h1 = h1.zfill(2)
                h2 = parts[1].lstrip("0") or "0"
                if len(h2.split(":")[0]) == 1:
                    h2 = h2.zfill(2)
                # Quitar :00 del final
                h1_short = h1[:5].rstrip(":0") if ":" in h1 else h1
                h2_short = h2[:5].rstrip(":0") if ":" in h2 else h2
                slots_api_normalized.add(f"{h1_short}-{h2_short}")

        solo_en_api = slots_api_normalized - slots_hardcode
        solo_en_hardcode = slots_hardcode - slots_api_normalized

        if solo_en_api or solo_en_hardcode:
            print(f"  [{dia_nombre}]")
            if solo_en_api:
                print(f"    En BD pero NO en grilla: {sorted(solo_en_api)}")
            if solo_en_hardcode:
                print(
                    f"    En grilla pero NO en BD: {sorted(solo_en_hardcode)}")
        else:
            print(
                f"  [{dia_nombre}] COINCIDEN (ambos tienen {len(slots_hardcode)} slots)")

    print()
    print("NOTA: La grilla hardcodeada tambien se usa para determinar en")
    print("que celdas de la Pizarra se puede hacer clic y crear WODs.")
    print("Si cambia la fuente de datos, el mapeo dia/hora debe preservarse.")

finally:
    db.close()
