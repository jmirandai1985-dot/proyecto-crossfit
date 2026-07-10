"""
Script de UNA SOLA VEZ para backfill de niveles calculados en historial_rm.

Ejecutar CON el servidor corriendo: python backend/backfill_niveles_rm.py
"""
import urllib.request
import urllib.error
import urllib.parse
import json
import sys
import time

API_BASE = "http://localhost:8000/api/v1"
TENANT_ID = 1


def api_get(path):
    url = f"{API_BASE}{path}"
    try:
        r = urllib.request.urlopen(url, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        print(f"  ERROR GET {url}: {e}")
        return None


def api_put(path, data):
    url = f"{API_BASE}{path}"
    try:
        req = urllib.request.Request(
            url, data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='PUT'
        )
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  ERROR PUT {url}: {e.code} - {body[:200]}")
        return None
    except Exception as e:
        print(f"  ERROR PUT {url}: {e}")
        return None


def api_post_nivel(path, params):
    """POST con query params para endpoints de nivel"""
    qs = urllib.parse.urlencode(params)
    url = f"{API_BASE}{path}?{qs}"
    try:
        req = urllib.request.Request(url, method='POST')
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"{e.code}: {body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 70)
    print("BACKFILL DE NIVELES CALCULADOS EN HISTORIAL_RM")
    print("=" * 70)

    # 1. Obtener movimientos
    print("\n[1] Obteniendo movimientos...")
    movs = api_get(f"/movimientos?tenant_id={TENANT_ID}")
    if not movs:
        print("ERROR: No se pudieron obtener movimientos")
        sys.exit(1)

    from app.db.crossfit_ratios import CROSSFIT_RATIOS
    from app.db.crossfit_habilidades import CROSSFIT_HABILIDADES

    grupo_a = {m['id'] for m in movs if m['nombre'] in CROSSFIT_RATIOS}
    grupo_b = {m['id'] for m in movs if m['nombre'] in CROSSFIT_HABILIDADES}
    grupo_c = {m['id'] for m in movs
               if m['nombre'] not in CROSSFIT_RATIOS
               and m['nombre'] not in CROSSFIT_HABILIDADES}

    print(f"  Grupo A (Fuerza): {len(grupo_a)} movs")
    print(f"  Grupo B (Gimnástico): {len(grupo_b)} movs")
    print(f"  Grupo C (No aplica): {len(grupo_c)} movs")

    # 2. Obtener registros sin nivel_calculado
    print("\n[2] Buscando registros sin nivel_calculado...")
    todos = api_get(f"/historial-rm?tenant_id={TENANT_ID}&limit=5000")
    if not todos:
        print("ERROR: No se pudieron obtener registros")
        sys.exit(1)

    pendientes = [r for r in todos if not r.get('nivel_calculado')]
    print(f"  Total registros: {len(todos)}")
    print(f"  Pendientes: {len(pendientes)}")

    if not pendientes:
        print("\n  No hay registros pendientes.")
        return

    # 3. Procesar
    print("\n[3] Calculando niveles via API...")
    act = 0
    salt = 0
    noap = 0
    err = 0

    for i, rm in enumerate(pendientes):
        rid = rm['id']
        mid = rm['movimiento_id']
        uid = rm['alumno_id']
        peso = rm['peso_kg']

        print(
            f"\n  #{i+1}/{len(pendientes)}: ID={rid}, alumno={uid}, mov_id={mid}, peso={peso}kg")

        if mid in grupo_c:
            print("    -> Grupo C: no aplica")
            noap += 1
            continue

        if mid in grupo_a:
            resp = api_post_nivel("/historial-rm/nivel-fuerza", {
                "alumno_id": uid, "movimiento_id": mid,
                "peso_rm": peso, "tenant_id": TENANT_ID
            })
        else:
            resp = api_post_nivel("/historial-rm/nivel-gimnastico", {
                "alumno_id": uid, "movimiento_id": mid,
                "valor": peso, "tenant_id": TENANT_ID
            })

        if not resp:
            print(f"    -> ERROR: sin respuesta")
            err += 1
            continue

        if resp.get("error"):
            print(f"    -> ERROR: {resp['error']}")
            err += 1
            continue

        if not resp.get("clasificable"):
            mensaje = resp.get("mensaje", "")
            if "peso corporal" in mensaje or "género" in mensaje:
                print(f"    -> SALTADO (sin datos de peso/género del alumno)")
                salt += 1
            else:
                print(
                    f"    -> No clasificable: {json.dumps(resp, ensure_ascii=False)[:100]}")
                err += 1
            continue

        nivel = resp["nivel"]
        upd = api_put(f"/historial-rm/{rid}?tenant_id={TENANT_ID}",
                      {"nivel_calculado": nivel})
        if upd:
            extra = f" (ratio={resp.get('ratio', '?')})" if mid in grupo_a else ""
            print(f"    -> ACTUALIZADO: {nivel}{extra}")
            act += 1
        else:
            print(f"    -> ERROR al actualizar nivel={nivel}")
            err += 1

        time.sleep(0.05)

    print("\n" + "=" * 70)
    print("RESUMEN DEL BACKFILL")
    print("=" * 70)
    print(f"  Procesados:           {len(pendientes)}")
    print(f"  Actualizados:         {act}")
    print(f"  Saltados (sin datos): {salt}")
    print(f"  Grupo C (no aplica):  {noap}")
    print(f"  Errores:              {err}")
    print("=" * 70)


if __name__ == "__main__":
    main()
