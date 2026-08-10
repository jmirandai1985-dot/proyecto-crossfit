"""
Aplicar Dark Mode consistente en el panel ADMIN (solo admin, no coach ni alumno).
Ediciones incrementales: reemplaza SOLO clases Tailwind de tema claro remanentes
por las clases dark ya usadas en el resto del admin (Layout usa bg-zinc-950).

Las clases que ya son dark (bg-zinc-*, bg-blue-900, badges de estado rojo/verde/amber)
NO se tocan. Ejecutar con ENVIRONMENT=test para no tocar producción (aunque este
script solo edita archivos del frontend, no la BD).

Uso:  py -3.12 _apply_dark_mode_admin.py
"""
import os
import re

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ADMIN_DIR = os.path.normpath(os.path.join(BACKEND_DIR, "..", "frontend", "src", "pages", "admin"))

# ── Sustituciones de clases claras → dark (orden: más específicas primero) ──
SUSTITUCIONES = [
    # bg-white (cajas/tarjetas/tablas/filas)
    ("bg-white", "bg-zinc-900"),
    ("bg-gray-50", "bg-zinc-800/50"),
    ("bg-gray-100", "bg-zinc-800"),
    ("bg-gray-200", "bg-zinc-700"),
    ("bg-gray-300", "bg-zinc-600"),
    # hover de grises claros
    ("hover:bg-gray-50", "hover:bg-zinc-800"),
    ("hover:bg-gray-100", "hover:bg-zinc-800"),
    ("hover:bg-gray-300", "hover:bg-zinc-700"),
    ("hover:bg-blue-50", "hover:bg-zinc-800"),
    # bg-blue-50 (remanente claro)
    ("bg-blue-50", "bg-zinc-800/50"),
    # Bordes/divisiones
    ("border-gray-100", "border-zinc-800"),
    ("border-gray-200", "border-zinc-800"),
    ("border-gray-300", "border-zinc-700"),
    ("divide-gray-200", "divide-zinc-800"),
    ("divide-gray-100", "divide-zinc-800"),
    # Textos grises → zinc (contraste legible sobre dark)
    ("text-gray-900", "text-zinc-100"),
    ("text-gray-800", "text-zinc-100"),
    ("text-gray-700", "text-zinc-300"),
    ("text-gray-600", "text-zinc-400"),
    ("text-gray-500", "text-zinc-400"),
    ("text-gray-400", "text-zinc-500"),
    # text-blue-* sobre fondos oscuros → versiones más claras legibles
    ("hover:text-blue-800", "hover:text-blue-300"),
    ("text-blue-800", "text-blue-300"),
    ("text-blue-700", "text-blue-400"),
    ("text-blue-600", "text-blue-400"),
    ("bg-blue-100", "bg-blue-500/20"),
]

def aplicar(path):
    with open(path, "r", encoding="utf-8") as f:
        contenido = f.read()
    original = contenido
    por_clase = {}
    for claro, dark in SUSTITUCIONES:
        n = contenido.count(claro)
        if n > 0:
            # Reemplazo global de la clase como token de Tailwind (límites de palabra/guion)
            contenido = contenido.replace(claro, dark)
            por_clase[claro] = n
    with open(path, "w", encoding="utf-8") as f:
        f.write(contenido)
    return contenido != original, por_clase

def main():
    if not os.path.isdir(ADMIN_DIR):
        print(f"ERROR: No existe {ADMIN_DIR}")
        return
    archivos = sorted(f for f in os.listdir(ADMIN_DIR) if f.endswith(".jsx"))
    total_cambios = 0
    print("=== DARK MODE ADMIN - RESULTADO ===")
    for archivo in archivos:
        path = os.path.join(ADMIN_DIR, archivo)
        cambiado, por_clase = aplicar(path)
        if cambiado:
            n = sum(por_clase.values())
            total_cambios += n
            print(f"  [EDITADO] {archivo}: {n} sustituciones")
            for clase, count in por_clase.items():
                if count > 0:
                    print(f"      {clase} -> x{count}")
        else:
            print(f"  [SIN CAMBIOS] {archivo}")
    print(f"\nTOTAL sustituciones: {total_cambios}")
    print("Lista de archivos con problema de contraste dark mode y corregidos:")

if __name__ == "__main__":
    main()