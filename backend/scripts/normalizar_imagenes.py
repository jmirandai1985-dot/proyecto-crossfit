"""
Repara las `imagen_url` VIEJAS que quedaron con la base pública de R2 multilínea.

CONTEXTO (Bug del Bazar): en PROD, `STORAGE_R2_PUBLIC_BASE_URL` llegó con el nombre del
bucket y la access key PEGADOS en la misma variable. El backend guardaba el valor crudo,
así que la BD quedó con:

    https://pub-xxxx.r2.dev\\n\\n<bucket>\\n\\n<access-key>\\n\\n/publico/<archivo>

El archivo SÍ estaba en R2, pero el navegador no podía cargar esa URL (foto rota). El
código ya no la genera —`storage._url_publica_base` toma sólo la primera URL y falla claro
si no es http(s)—; este script limpia las filas que ya estaban guardadas.

USO (por defecto NO escribe):
    py -3.12 scripts/normalizar_imagenes.py                  # informa (TEST según ENVIRONMENT)
    py -3.12 scripts/normalizar_imagenes.py --aplicar        # repara
    $env:ENVIRONMENT='production'; py -3.12 scripts/normalizar_imagenes.py --aplicar

Sólo toca valores con espacios/saltos de línea y reconstruye
`<primera URL>/publico/<archivo>`. Si no encuentra las dos partes, avisa y deja la fila
como está: nunca inventa una URL.
"""
import argparse
import os
import re
import sys

# Permite ejecutar `py -3.12 scripts/normalizar_imagenes.py` desde `backend/`.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from app.db.database import SessionLocal  # noqa: E402  (después del sys.path)
from app.models.aviso_marketing import AvisoMarketing  # noqa: E402
from app.models.producto import Producto  # noqa: E402

PATRON_URL = re.compile(r"https?://\S+")
PATRON_ARCHIVO = re.compile(r"publico/([A-Za-z0-9._-]+)")


def normalizar(valor: str):
    """URL limpia a partir del valor corrupto, o None si no se puede reconstruir."""
    base = PATRON_URL.search(valor or "")
    archivos = PATRON_ARCHIVO.findall(valor or "")
    if not base or not archivos:
        return None
    return f"{base.group(0).rstrip('/')}/publico/{archivos[-1]}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normaliza imagen_url con la base pública de R2 pegada en varias líneas.")
    parser.add_argument("--aplicar", action="store_true",
                        help="guarda los cambios (sin esto sólo informa)")
    args = parser.parse_args()

    db = SessionLocal()
    pendientes = 0
    try:
        for modelo, etiqueta in ((Producto, "productos"),
                                 (AvisoMarketing, "avisos_marketing")):
            filas = db.query(modelo).filter(modelo.imagen_url.isnot(None)).all()
            for fila in filas:
                valor = fila.imagen_url or ""
                if not any(c.isspace() for c in valor):
                    continue
                nueva = normalizar(valor)
                if not nueva:
                    print(f"[AVISO] {etiqueta} id={fila.id}: no se pudo reconstruir; "
                          "queda igual")
                    continue
                pendientes += 1
                print(f"{etiqueta} id={fila.id} -> {nueva}")
                if args.aplicar:
                    fila.imagen_url = nueva
        if args.aplicar:
            db.commit()
            print(f"\n{pendientes} fila(s) reparadas.")
        else:
            print(f"\n{pendientes} fila(s) a reparar. Repetí con --aplicar para guardar.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
