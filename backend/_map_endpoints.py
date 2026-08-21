"""Mapea cada endpoint de api/v1 -> dependencia de autenticación (diagnóstico)."""
import os, re

p = "app/api/v1"
files = sorted(f for f in os.listdir(p) if f.endswith(".py"))
for f in files:
    lines = open(os.path.join(p, f), encoding="utf-8-sig").read().splitlines()
    # ruta completa del router desde __init__/main
    prefix = ""
    prev_dep = ""
    current_method = ""
    current_path = ""
    print(f"\n===== {f} =====")
    for n in lines:
        s = n.strip()
        m = re.match(r'@router\.(get|post|put|patch|delete)\("?([^"()]*)', s)
        if m:
            current_method = m.group(1)
            current_path = m.group(2)
            prev_dep = ""
        if "Depends(get_current" in s:
            dep = re.search(r'get_current_\w+', s)
            prev_dep = dep.group(0) if dep else s
            if current_method:
                print(f"  {current_method.upper():6s} {current_path:45s} -> {prev_dep}")
                current_method = ""
                current_path = ""
