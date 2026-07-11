"""
Prueba: verificar que GET /clases genera clases automáticamente cuando
se consulta una fecha vacía (simulando que no hay clases para hoy)
"""
import urllib.request
import json
import sys

BASE = "http://127.0.0.1:8000"


def test_fecha_sin_clases():
    """Prueba: consultar una fecha que NO tiene clases (ej: mañana sábado 2026-07-11)
    Debería auto-generarlas desde horarios_base"""
    url = f"{BASE}/api/v1/clases/?tenant_id=1&fecha=2026-07-11&limit=50"
    print(f"Consultando: {url}")
    try:
        r = urllib.request.urlopen(url)
        data = json.loads(r.read())
        print(f"  Status: {r.status}")
        print(f"  Clases encontradas: {len(data)}")
        for c in data[:3]:
            print(
                f"    id={c['id']} | {c['hora_inicio']}-{c['hora_fin']} | {c['disciplina_nombre']}")
        return data
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


def test_fecha_hoy():
    """Prueba: consultar la fecha de HOY"""
    from datetime import date
    hoy = date.today().isoformat()
    url = f"{BASE}/api/v1/clases/?tenant_id=1&fecha={hoy}&solo_con_cupo=true&limit=50"
    print(f"\nConsultando HOY ({hoy}): {url}")
    try:
        r = urllib.request.urlopen(url)
        data = json.loads(r.read())
        print(f"  Status: {r.status}")
        print(f"  Clases encontradas: {len(data)}")
        return data
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


if __name__ == "__main__":
    print("=" * 60)
    print("TEST: AUTO-GENERACIÓN DE CLASES")
    print("=" * 60)

    # Test 1: fecha sin clases (sábado 2026-07-11)
    data1 = test_fecha_sin_clases()

    # Test 2: fecha de hoy
    print()
    data2 = test_fecha_hoy()

    print("\n" + "=" * 60)
    print("RESUMEN:")
    print(f"  Sábado 2026-07-11: {len(data1)} clases")
    print(f"  Hoy: {len(data2)} clases")
    print("=" * 60)
