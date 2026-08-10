"""
SOLO LECTURA: Cuenta cuantas veces aparece cada clase Tailwind de tema claro
en los archivos del panel ADMIN (sin modificar nada).
Para revision rapida en navegador antes de comitear (VERIFICACION 2).
Uso: py -3.12 _count_dark_mode_admin.py
"""
import os

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ADMIN_DIR = os.path.normpath(os.path.join(BACKEND_DIR, "..", "frontend", "src", "pages", "admin"))

CLASES_CLARAS = [
    "bg-white",
    "bg-gray-50",
    "bg-gray-100",
    "bg-gray-200",
    "bg-gray-300",
    "bg-blue-50",
    "hover:bg-blue-50",
    "hover:bg-gray-50",
    "hover:bg-gray-100",
    "hover:bg-gray-300",
    "border-gray-100",
    "border-gray-200",
    "border-gray-300",
    "divide-gray-200",
    "divide-gray-100",
    "text-gray-900",
    "text-gray-800",
    "text-gray-700",
    "text-gray-600",
    "text-gray-500",
    "text-gray-400",
    "text-blue-800",
    "text-blue-700",
    "text-blue-600",
    "hover:text-blue-800",
    "bg-blue-100",
]

def main():
    print("=== CONTEO CLASES CLARAS EN PANEL ADMIN (SOLO LECTURA) ===")
    archivos = sorted(f for f in os.listdir(ADMIN_DIR) if f.endswith(".jsx"))
    totales = {}
    resumen_por_archivo = {}
    for archivo in archivos:
        path = os.path.join(ADMIN_DIR, archivo)
        with open(path, "r", encoding="utf-8") as f:
            contenido = f.read()
        conteos = {}
        for clase in CLASES_CLARAS:
            n = contenido.count(clase)
            if n > 0:
                conteos[clase] = n
                totales[clase] = totales.get(clase, 0) + n
        if conteos:
            resumen_por_archivo[archivo] = conteos

    print(f"\nArchivos con clases claras: {len(resumen_por_archivo)} de {len(archivos)}")
    print("\n--- RESUMEN GLOBAL (clase clara -> total apariciones en admin) ---")
    for clase in CLASES_CLARAS:
        if totales.get(clase):
            print(f"  {clase}: {totales[clase]}")
    print(f"\n  TOTAL: {sum(totales.values())}")

    print("\n--- DETALLE POR ARCHIVO ---")
    for archivo in sorted(resumen_por_archivo.keys()):
        det = resumen_por_archivo[archivo]
        print(f"\n  {archivo}: {sum(det.values())} sustituciones")
        for clase, n in det.items():
            print(f"      {clase}: {n}")

if __name__ == "__main__":
    main()