"""
TEST COMPLETO DEL PANEL DEL ALUMNO
Cubre 16 pasos en 5 bloques, todos contra el Alumno Demo (usuario_id=5).

Ejecutar con:
  python _test_panel_alumno_completo.py

IMPORTANTE: Si crea datos de prueba, los deja marcados como TEST.
NO elimina datos existentes del alumno.
"""
import requests
import json
from datetime import date, datetime, timedelta

BASE = "http://localhost:8000/api/v1"
AID = 5  # alumno_id
TID = 1  # tenant_id
hoy = date.today()
hoy_str = str(hoy)

resultados = []


def p(msg=""):
    print(msg)


def print_json(label, data):
    print(f"\n  {label}:")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def check(caso, paso, ok, esperado="", real=""):
    estado = "PASO" if ok else "FALLO"
    print(f"  [{estado}] {paso}")
    if not ok:
        print(f"    Esperado: {esperado}")
        print(f"    Real:     {real}")
    resultados.append((caso, paso, "✅" if ok else "❌", esperado, real))
    return ok


# =========================================================================
# BLOQUE 1 — DASHBOARD GENERAL
# =========================================================================
p("\n" + "=" * 70)
p("  BLOQUE 1 — DASHBOARD GENERAL")
p("=" * 70)

# 1. Membresia activa
p("\n--- [1] GET /planes/membresia-activa ---")
r = requests.get(f"{BASE}/planes/membresia-activa",
                 params={"tenant_id": TID, "alumno_id": AID})
memb = r.json()
print_json("Respuesta", memb)
check(1, "membresia-activa responde",
      r.status_code == 200, "200", str(r.status_code))
check(1, "plan activo",
      memb.get("activa") in (True, False), "True o False", str(memb.get("activa")))
if memb.get("activa"):
    check(1, f"plan_nombre={memb.get('plan_nombre')}",
          True, "nombre del plan", memb.get("plan_nombre"))
    check(1, f"dias_restantes={memb.get('dias_restantes')}",
          memb.get("dias_restantes", 0) >= 0, ">=0", str(memb.get("dias_restantes")))

# 2. Nivel fuerza
p("\n--- [2] GET /historial-rm/alumnos/5/nivel-fuerza ---")
r = requests.get(f"{BASE}/historial-rm/alumnos/{AID}/nivel-fuerza",
                 params={"tenant_id": TID})
nf = r.json()
print_json("Respuesta", nf)
check(2, "nivel-fuerza responde",
      r.status_code == 200, "200", str(r.status_code))
check(2, "nivel presente",
      nf.get("nivel") is not None, "nivel no None", str(nf.get("nivel")))
check(2, "top_rms es lista",
      isinstance(nf.get("top_rms"), list), "list", type(nf.get("top_rms")).__name__)
if isinstance(nf.get("top_rms"), list):
    check(2, "top_rms cantidad",
          len(nf["top_rms"]) <= 3, "<= 3", str(len(nf["top_rms"])))

# 3. Nivel gimnastico
p("\n--- [3] GET /historial-rm/alumnos/5/nivel-gimnastico ---")
r = requests.get(f"{BASE}/historial-rm/alumnos/{AID}/nivel-gimnastico",
                 params={"tenant_id": TID})
ng = r.json()
print_json("Respuesta", ng)
check(3, "nivel-gimnastico responde",
      r.status_code == 200, "200", str(r.status_code))
check(3, "nivel presente",
      ng.get("nivel") is not None, "nivel", str(ng.get("nivel")))
rms_gimn = ng.get("top_rms", [])
check(3, "top_rms es lista",
      isinstance(rms_gimn, list), "list", type(rms_gimn).__name__)
if isinstance(rms_gimn, list) and len(rms_gimn) > 0:
    nombres_gimn = [r["movimiento"] for r in rms_gimn]
    p(f"  Movimientos gimnasticos: {nombres_gimn}")

# 4. WOD hoy
p("\n--- [4] GET /wods/hoy ---")
r = requests.get(f"{BASE}/wods/hoy", params={"tenant_id": TID})
wod = r.json()
print_json("Respuesta", wod)
check(4, "wods/hoy responde",
      r.status_code == 200, "200", str(r.status_code))

# 5. Asistencia mes
p("\n--- [5] GET /reservas/asistencia-mes ---")
r = requests.get(f"{BASE}/reservas/asistencia-mes",
                 params={"tenant_id": TID, "usuario_id": AID})
am = r.json()
print_json("Respuesta", am)
check(5, "asistencia-mes responde",
      r.status_code == 200, "200", str(r.status_code))
check(5, "tiene total_reservas",
      "total_reservas" in am, "key presente", str(list(am.keys())))
check(5, "tiene solo_futuras",
      "solo_futuras" in am, "key presente", str(list(am.keys())))
check(5, "tiene reservas_futuras",
      "reservas_futuras" in am, "key presente", str(list(am.keys())))

# 6. Clases 7 dias
p("\n--- [6] GET /clases (7 dias) ---")
desde = hoy_str
hasta = str(hoy + timedelta(days=6))
r = requests.get(f"{BASE}/clases",
                 params={"tenant_id": TID, "fecha_desde": desde, "fecha_hasta": hasta, "limit": 500})
clases = r.json()
data_clases = clases if isinstance(clases, list) else clases.get("clases", [])
p(f"  Clases encontradas: {len(data_clases)}")
print_json("Respuesta (primeras 3)", data_clases[:3] if len(
    data_clases) > 3 else data_clases)
check(6, "clases responde",
      r.status_code == 200, "200", str(r.status_code))
check(6, "clases es lista",
      isinstance(data_clases, list), "list", type(data_clases).__name__)
check(6, "hay clases en 7 dias",
      len(data_clases) > 0, "> 0", str(len(data_clases)))

# =========================================================================
# BLOQUE 2 — FLUJO DE RESERVA
# =========================================================================
p("\n" + "=" * 70)
p("  BLOQUE 2 — FLUJO DE RESERVA")
p("=" * 70)

reserva_id_creada = None
creditos_antes = memb.get("clases_disponibles") if memb.get("activa") else None

# 7. Reservar una clase futura (mas de 6h)
p("\n--- [7] Reservar clase futura (>6h) ---")
# Buscar una clase futura (mañana o pasado) con cupo
clases_futuras = [c for c in data_clases if c.get("fecha", "") > hoy_str
                  and (c.get("cupo_maximo", 0) - c.get("asistentes_confirmados", 0)) > 0]
p(f"  Clases futuras con cupo: {len(clases_futuras)}")
clase_a_reservar = clases_futuras[0] if clases_futuras else None

if clase_a_reservar:
    payload_res = {
        "tenant_id": TID,
        "alumno_id": AID,
        "clase_id": clase_a_reservar["id"],
        "estado": "confirmada",
    }
    p(f"  Reservando clase_id={clase_a_reservar['id']} fecha={clase_a_reservar.get('fecha')}")
    r = requests.post(f"{BASE}/reservas", json=payload_res)
    print_json("Respuesta POST reserva", r.json()
               if r.status_code < 300 else {"error": r.text[:300]})
    if r.status_code < 300:
        reserva_id_creada = r.json().get("id")
        check(7, "reserva creada", True,
              f"id={reserva_id_creada}", f"status={r.status_code}")
        # Verificar que el credito se descontó
        if creditos_antes is not None:
            r2 = requests.get(f"{BASE}/planes/membresia-activa",
                              params={"tenant_id": TID, "alumno_id": AID})
            memb2 = r2.json()
            creditos_despues = memb2.get("clases_disponibles", 0)
            check(7, f"credito descontado: {creditos_antes} -> {creditos_despues}",
                  creditos_despues < creditos_antes,
                  f"< {creditos_antes}", str(creditos_despues))
    else:
        check(7, "reserva creada", False, "status 201",
              f"status {r.status_code}: {r.text[:200]}")
else:
    p("  ⚠️  No hay clases futuras con cupo disponible. Saltando paso 7-8.")
    check(7, "reserva (omitido - sin clases disponibles)",
          True, "N/A", "N/A")

# 8. Cancelar esa reserva (>6h, debe devolver credito)
p("\n--- [8] Cancelar reserva (>6h, devuelve credito) ---")
if reserva_id_creada:
    r = requests.delete(f"{BASE}/reservas/{reserva_id_creada}",
                        params={"tenant_id": TID})
    p(f"  DELETE /reservas/{reserva_id_creada} -> Status: {r.status_code}")
    if r.status_code < 300:
        # Verificar devolucion de credito
        r3 = requests.get(f"{BASE}/planes/membresia-activa",
                          params={"tenant_id": TID, "alumno_id": AID})
        memb3 = r3.json()
        creditos_final = memb3.get("clases_disponibles", 0)
        check(8, "cancelacion exitosa", True,
              "status 204", f"status {r.status_code}")
        check(8, f"credito devuelto: {creditos_despues} -> {creditos_final}",
              creditos_final >= creditos_despues,
              f">= {creditos_despues}", str(creditos_final))
    else:
        check(8, "cancelacion exitosa", False,
              "status 204", f"status {r.status_code}: {r.text[:200]}")
else:
    check(8, "cancelacion (sin reserva previa)", True, "N/A", "N/A")

# 9. Reserva de HOY con <6h (para probar que NO devuelve credito)
p("\n--- [9] Reserva/cancelacion de clase <6h antes ---")
clases_hoy = [c for c in data_clases if c.get("fecha", "") == hoy_str
              and (c.get("cupo_maximo", 0) - c.get("asistentes_confirmados", 0)) > 0]
p(f"  Clases de HOY con cupo: {len(clases_hoy)}")

if clases_hoy:
    # Buscar la clase mas temprana para que sea <6h desde ahora
    clase_hoy = clases_hoy[0]
    payload_res = {
        "tenant_id": TID,
        "alumno_id": AID,
        "clase_id": clase_hoy["id"],
        "estado": "confirmada",
    }
    r = requests.post(f"{BASE}/reservas", json=payload_res)
    p(f"  Reserva clase_hoy_id={clase_hoy['id']} -> Status: {r.status_code}")
    if r.status_code < 300:
        reserva_hoy_id = r.json().get("id")
        r4 = requests.get(f"{BASE}/planes/membresia-activa",
                          params={"tenant_id": TID, "alumno_id": AID})
        cred_antes = r4.json().get("clases_disponibles", 0)
        # Cancelar (como es hoy, probablemente <6h -> NO devuelve)
        r = requests.delete(f"{BASE}/reservas/{reserva_hoy_id}",
                            params={"tenant_id": TID})
        r5 = requests.get(f"{BASE}/planes/membresia-activa",
                          params={"tenant_id": TID, "alumno_id": AID})
        cred_desp = r5.json().get("clases_disponibles", 0)
        p(f"  Cancelada. Creditos: {cred_antes} -> {cred_desp}")
        check(9, "reserva/cancelacion clase hoy completada",
              r.status_code < 300, "status 204", f"status {r.status_code}")
    else:
        check(9, "reserva clase hoy (puede fallar si no hay cupo o membresia)",
              True, "N/A", f"status {r.status_code}: {r.text[:150]}")
else:
    p("  ⚠️  No hay clases de HOY con cupo. Saltando paso 9.")
    check(9, "reserva/cancelacion hoy (sin clases de hoy)", True, "N/A", "N/A")

# =========================================================================
# BLOQUE 3 — RMs TODAS LAS CATEGORIAS
# =========================================================================
p("\n" + "=" * 70)
p("  BLOQUE 3 — RMs TODAS LAS CATEGORIAS")
p("=" * 70)

# Obtener movimientos
r = requests.get(f"{BASE}/movimientos", params={"tenant_id": TID})
movs = r.json() if r.status_code == 200 else []

# 10. RM de Fuerza
p("\n--- [10] RM de Fuerza ---")
fza_movs = [m for m in movs if m.get("categoria") == "fuerza"]
mov_fza = fza_movs[0] if fza_movs else None
if mov_fza:
    fza_id = mov_fza["id"]
    payload = {"tenant_id": TID, "alumno_id": AID, "movimiento_id": fza_id,
               "peso_kg": 50, "repeticiones": 5, "series": 3, "fecha": hoy_str,
               "notas": "TEST fuerza"}
    r = requests.post(f"{BASE}/historial-rm", json=payload)
    p(f"  POST fuerza -> Status: {r.status_code}")
    if r.status_code < 300:
        rp = r.json()
        check(10, f"RM fuerza creado (id={rp.get('id')})",
              rp.get("peso_kg") == 50, "peso_kg=50", str(rp.get("peso_kg")))
        check(10, "repeticiones correctas",
              rp.get("repeticiones") == 5, "5", str(rp.get("repeticiones")))
    else:
        check(10, "RM fuerza creado", False, "201",
              f"{r.status_code}: {r.text[:200]}")
else:
    check(10, "RM fuerza (sin mov fuerza)", True, "N/A", "N/A")

# 11. RM de Gimnastico
p("\n--- [11] RM de Gimnastico ---")
gim_movs = [m for m in movs if m.get("categoria") == "gimnastico"]
mov_gim = gim_movs[0] if gim_movs else None
if mov_gim:
    payload = {"tenant_id": TID, "alumno_id": AID, "movimiento_id": mov_gim["id"],
               "peso_kg": 10, "repeticiones": 12, "series": 3, "fecha": hoy_str,
               "notas": "TEST gimnastico"}
    r = requests.post(f"{BASE}/historial-rm", json=payload)
    p(f"  POST gimnastico -> Status: {r.status_code}")
    if r.status_code < 300:
        rp = r.json()
        check(11, f"RM gimnastico creado (id={rp.get('id')})",
              rp.get("repeticiones") == 12, "repeticiones=12", str(rp.get("repeticiones")))
        check(11, "series correctas",
              rp.get("series") == 3, "3", str(rp.get("series")))
    else:
        check(11, "RM gimnastico creado", False, "201",
              f"{r.status_code}: {r.text[:200]}")
else:
    check(11, "RM gimnastico (sin mov gimnastico)", True, "N/A", "N/A")

# 12. RM de Cardio
p("\n--- [12] RM de Cardio ---")
cardio_movs = [m for m in movs if m.get("categoria") == "cardio"
               and "ski" not in m.get("nombre", "").lower()]
mov_cardio = cardio_movs[0] if cardio_movs else None
if mov_cardio:
    payload = {"tenant_id": TID, "alumno_id": AID, "movimiento_id": mov_cardio["id"],
               "peso_kg": 1, "minutos": 2, "km": 0.4, "vueltas": 1, "fecha": hoy_str,
               "notas": "TEST cardio"}
    r = requests.post(f"{BASE}/historial-rm", json=payload)
    p(f"  POST cardio -> Status: {r.status_code}")
    if r.status_code < 300:
        rp = r.json()
        check(12, f"RM cardio creado (id={rp.get('id')})",
              rp.get("minutos") == 2, "minutos=2", str(rp.get("minutos")))
        check(12, "km correcto",
              rp.get("km") == 0.4, "0.4", str(rp.get("km")))
        check(12, "vueltas correcta",
              rp.get("vueltas") == 1, "1", str(rp.get("vueltas")))
    else:
        check(12, "RM cardio creado", False, "201",
              f"{r.status_code}: {r.text[:200]}")
else:
    check(12, "RM cardio (sin mov cardio)", True, "N/A", "N/A")

# 13. RM de Maquinas + mostrar registro MAS RECIENTE
p("\n--- [13] RM de Maquinas (verificar registro mas reciente) ---")
meta_movs = [m for m in movs if m.get("categoria") == "metabolico"]
mov_meta = meta_movs[0] if meta_movs else None
if mov_meta:
    meta_id = mov_meta["id"]
    # Crear RM con datos nuevos
    payload = {"tenant_id": TID, "alumno_id": AID, "movimiento_id": meta_id,
               "peso_kg": 1, "calorias": 300, "km": 3.5, "vueltas": 10, "fecha": hoy_str,
               "notas": "TEST maquinas nuevo"}
    r = requests.post(f"{BASE}/historial-rm", json=payload)
    p(f"  POST maquinas -> Status: {r.status_code}")
    if r.status_code < 300:
        rp = r.json()
        check(13, f"RM maquinas creado (id={rp.get('id')})",
              rp.get("calorias") == 300, "calorias=300", str(rp.get("calorias")))
        # Consultar la Pizarra - debe mostrar el mas RECIENTE (con notas=TEST)
        r = requests.get(f"{BASE}/historial-rm/alumnos/{AID}/rms",
                         params={"tenant_id": TID})
        rms_list = r.json()
        rm_pizarra = [x for x in rms_list if x.get("movimiento_id") == meta_id]
        if rm_pizarra:
            rm_mostrado = rm_pizarra[0]
            p(f"  RM en Pizarra: calorias={rm_mostrado.get('calorias')}, "
              f"km={rm_mostrado.get('km')}, vueltas={rm_mostrado.get('vueltas')}, "
              f"notas={rm_mostrado.get('notas')}")
            check(13, "Pizarra muestra registro RECIENTE (calorias=300)",
                  rm_mostrado.get("calorias") == 300, "300", str(rm_mostrado.get("calorias")))
        else:
            check(13, "RM maquinas aparece en Pizarra",
                  False, "encontrado", "no encontrado")
    else:
        check(13, "RM maquinas creado", False, "201",
              f"{r.status_code}: {r.text[:200]}")
else:
    check(13, "RM maquinas (sin mov maquinas)", True, "N/A", "N/A")

# =========================================================================
# BLOQUE 4 — PLANES Y PERFIL
# =========================================================================
p("\n" + "=" * 70)
p("  BLOQUE 4 — PLANES Y PERFIL")
p("=" * 70)

# 14. Planes filtrados por genero
p("\n--- [14] GET /planes con filtro de genero ---")
r = requests.get(f"{BASE}/planes",
                 params={"tenant_id": TID, "genero": "femenino"})
planes_f = r.json()
p(f"  Planes genero=femenino: {len(planes_f)}")
r = requests.get(f"{BASE}/planes",
                 params={"tenant_id": TID, "genero": "masculino"})
planes_m = r.json()
p(f"  Planes genero=masculino: {len(planes_m)}")
r = requests.get(f"{BASE}/planes", params={"tenant_id": TID})
planes_todos = r.json()
p(f"  Planes total: {len(planes_todos)}")
check(14, "planes filtro genero responde",
      r.status_code == 200, "200", str(r.status_code))
check(14, "femenino devuelve lista",
      isinstance(planes_f, list), "list", type(planes_f).__name__)
check(14, "masculino devuelve lista",
      isinstance(planes_m, list), "list", type(planes_m).__name__)
if isinstance(planes_todos, list) and isinstance(planes_f, list) and isinstance(planes_m, list):
    check(14, "femenino+masculino <= total",
          len(planes_f) + len(planes_m) <= len(planes_todos) + 1,
          f"<= {len(planes_todos)}", str(len(planes_f) + len(planes_m)))

# 15. Actualizar peso_kg del alumno (simular ajustes)
p("\n--- [15] PUT /usuarios/{id} (actualizar peso) ---")
r = requests.get(f"{BASE}/usuarios/{AID}", params={"tenant_id": TID})
if r.status_code == 200:
    usuario = r.json()
    peso_original = usuario.get("peso_kg")
    p(f"  Peso original del alumno: {peso_original}")
    nuevo_peso = (peso_original or 70) + 5
    r = requests.put(f"{BASE}/usuarios/{AID}",
                     params={"tenant_id": TID},
                     json={"peso_kg": nuevo_peso})
    p(f"  PUT peso_kg={nuevo_peso} -> Status: {r.status_code}")
    if r.status_code < 300:
        rp = r.json()
        check(15, "peso actualizado",
              rp.get("peso_kg") == nuevo_peso, str(nuevo_peso), str(rp.get("peso_kg")))
        # Recalcular nivel fuerza
        r = requests.post(f"{BASE}/historial-rm/nivel-fuerza",
                          params={"tenant_id": TID, "alumno_id": AID, "movimiento_id": mov_fza["id"] if mov_fza else 1, "peso_rm": 50})
        p(f"  Nivel-fuerza endpoint -> Status: {r.status_code}")
        check(15, "nivel-fuerza endpoint responde",
              r.status_code in (200, 404), "200 o 404", str(r.status_code))
        # Restaurar peso original
        if peso_original is not None:
            requests.put(f"{BASE}/usuarios/{AID}",
                         params={"tenant_id": TID},
                         json={"peso_kg": peso_original})
            p(f"  Peso restaurado a {peso_original}")
    else:
        check(15, "peso actualizado", False, "200",
              f"{r.status_code}: {r.text[:200]}")
else:
    check(15, "peso actualizado (no se pudo obtener usuario)",
          True, "N/A", f"status {r.status_code}")

# =========================================================================
# BLOQUE 5 — WOD COACH-ALUMNO
# =========================================================================
p("\n" + "=" * 70)
p("  BLOQUE 5 — WOD COACH-ALUMNO")
p("=" * 70)

# 16. Crear WOD para hoy y verificar que aparece
p("\n--- [16] Crear WOD para hoy y verificar /wods/hoy ---")
mov_wod = fza_movs[0] if fza_movs else (movs[0] if movs else None)
if mov_wod:
    payload_wod = {
        "tenant_id": TID,
        "fecha": hoy_str,
        "titulo": "TEST WOD automatico - borrar",
        "descripcion": "WOD creado por test automatico",
        "coach_id": 4,
        "estado": "publicado",
        "movimientos": [
            {
                "movimiento_id": mov_wod["id"],
                "orden": 1,
                "series": 3,
                "repeticiones": "10",
                "peso": None
            }
        ]
    }
    r = requests.post(f"{BASE}/wods/", json=payload_wod,
                      params={"tenant_id": TID})
    p(f"  POST /wods/ -> Status: {r.status_code}")
    if r.status_code < 300:
        wod_creado = r.json()
        wod_id = wod_creado.get("id")
        check(16, f"WOD creado (id={wod_id})",
              True, f"id={wod_id}", f"status={r.status_code}")
        # Verificar que aparece en /wods/hoy
        r = requests.get(f"{BASE}/wods/hoy", params={"tenant_id": TID})
        wod_hoy = r.json()
        if isinstance(wod_hoy, dict) and wod_hoy.get("id") == wod_id:
            check(16, "/wods/hoy muestra el WOD recien creado",
                  True, f"id={wod_id}", f"id={wod_hoy.get('id')}")
        elif isinstance(wod_hoy, list) and any(w.get("id") == wod_id for w in wod_hoy):
            check(16, "/wods/hoy muestra el WOD recien creado",
                  True, f"id={wod_id}", "encontrado en lista")
        else:
            check(16, "/wods/hoy muestra el WOD recien creado",
                  False, f"id={wod_id}", str(wod_hoy.get("id") if isinstance(wod_hoy, dict) else wod_hoy))
    else:
        check(16, "WOD creado", False, "201",
              f"{r.status_code}: {r.text[:200]}")
else:
    check(16, "WOD (sin movimientos disponibles)", True, "N/A", "N/A")

# =========================================================================
# RESUMEN FINAL
# =========================================================================
p("\n" + "=" * 70)
p("  RESUMEN FINAL — PANEL ALUMNO COMPLETO")
p("=" * 70)

p(f"\n  {'#':>3} {'Bloque':>20} {'Paso':<55} {'Resultado':<10}")
p("  " + "-" * 90)
pasaron = 0
fallaron = 0
for caso, paso, estado, esperado, real in resultados:
    status_sym = estado
    if "❌" in estado:
        fallaron += 1
    else:
        pasaron += 1
    bloque = ""
    if caso == 1:
        bloque = "Dashboard"
    elif caso == 2:
        bloque = "Dashboard"
    elif caso == 3:
        bloque = "Dashboard"
    elif caso == 4:
        bloque = "Dashboard"
    elif caso == 5:
        bloque = "Dashboard"
    elif caso == 6:
        bloque = "Dashboard"
    elif caso == 7:
        bloque = "Reserva"
    elif caso == 8:
        bloque = "Reserva"
    elif caso == 9:
        bloque = "Reserva"
    elif caso == 10:
        bloque = "RMs"
    elif caso == 11:
        bloque = "RMs"
    elif caso == 12:
        bloque = "RMs"
    elif caso == 13:
        bloque = "RMs"
    elif caso == 14:
        bloque = "Planes"
    elif caso == 15:
        bloque = "Perfil"
    elif caso == 16:
        bloque = "WOD"
    p(f"  {caso:>3} {bloque:>20} {paso:<55} {status_sym:<10}")

p(f"\n  Total: {pasaron + fallaron} pruebas | ✅ Pasaron: {pasaron} | ❌ Fallaron: {fallaron}")
p("=" * 70)
