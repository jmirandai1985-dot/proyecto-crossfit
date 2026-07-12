"""
Diagnostico: llama a la API real y cuenta clases de manana/tarde
"""
import urllib.request
import json

try:
    url = 'http://127.0.0.1:8000/api/v1/clases?tenant_id=1&fecha=2026-07-13'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())

    total = len(data)
    manana = 0
    tarde = 0
    for c in data:
        hora_str = (c.get('hora_inicio') or '00:00').split(':')[0]
        hora = int(hora_str)
        if hora < 14:
            manana += 1
        else:
            tarde += 1

    print(f'=== API RESPONSE para 2026-07-13 ===')
    print(f'Total clases devueltas: {total}')
    print(f'MAÑANA (hora<14):       {manana}')
    print(f'TARDE (hora>=14):       {tarde}')

    # Agrupar por (disciplina, hora_inicio, hora_fin) como hace el frontend
    grupos = {}
    for c in data:
        key = (c.get('disciplina_nombre', ''), c.get(
            'hora_inicio', ''), c.get('hora_fin', ''))
        if key not in grupos:
            grupos[key] = c
    agrupadas = list(grupos.values())
    manana_ag = sum(1 for c in agrupadas if int(
        (c.get('hora_inicio') or '00:00').split(':')[0]) < 14)
    tarde_ag = sum(1 for c in agrupadas if int(
        (c.get('hora_inicio') or '00:00').split(':')[0]) >= 14)
    print(f'\n=== DESPUES DE AGRUPAR (como hace frontend) ===')
    print(f'MAÑANA (agrupado): {manana_ag}')
    print(f'TARDE (agrupado): {tarde_ag}')
    print(f'Total unicos: {len(agrupadas)}')

    # Mostrar las primeras filas de tarde para debug
    print(f'\n=== CLASES DE TARDE ===')
    for c in agrupadas:
        hora = int((c.get('hora_inicio') or '00:00').split(':')[0])
        if hora >= 14:
            print(
                f'  {c.get("hora_inicio")}-{c.get("hora_fin")} {c.get("disciplina_nombre", "?"):>25}')

except Exception as e:
    print(f'ERROR: {e}')
