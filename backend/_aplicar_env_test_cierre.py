"""Cierre del ambiente de test:

1) Reemplaza el identificador 'lingering-shape' -> 'small-butterfly' (nueva
   branch de test) en TODOS los scripts con guard, y el 'muddy' obsoleto de
   iniciar_servidor.py.
2) Actualiza el header de advertencia de .env.test (SOLO comentarios; la
   linea DATABASE_URL no se toca: la edita el usuario).
3) Actualiza la nota de backend/README.md.

Preserva CRLF/LF. NO imprime credenciales (solo nombres de archivo + conteos).
"""
import io
import os

BASE = r"c:\Users\Asus\Desktop\Proyectos\proyecto-crossfit\backend"

GUARD_FILES = [
    "app/main.py",
    "iniciar_servidor.py",
    "run_setup_test_db.py",
    "tests/conftest.py",
    "scripts/aplicar_overrides_test.py",
    "scripts/sync_test_from_prod.py",
    "_diag_c16_causa.py",
    "_diag_horarios_clases.py",
    "_diag_supervision_clases.py",
    "_reactivar_suscripcion_alumno5.py",
    "_verificar_asistencia_dashboard.py",
    "_verificar_flujo_admin_coach_alumno.py",
    "_verify_sync_result.py",
]


def _leer(ruta):
    with io.open(ruta, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _escribir(ruta, src):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(src)


def _reemplazar(rel, old, new, min_esperados=1):
    ruta = os.path.join(BASE, rel)
    src = _leer(ruta)
    n = src.count(old)
    if n < min_esperados:
        raise SystemExit(f"[{rel}] no encontre '{old[:40]}' (matches={n})")
    src = src.replace(old, new)
    _escribir(ruta, src)
    print(f"[{rel}] reemplazos '{old[:30]}...': {n}")


# ── 1) guards: lingering-shape -> small-butterfly ──
for rel in GUARD_FILES:
    _reemplazar(rel, "lingering-shape", "small-butterfly")

# iniciar_servidor.py ademas tenia el identificador 'muddy' obsoleto
_reemplazar("iniciar_servidor.py", '"muddy"', '"small-butterfly"')

print("\n--- guards actualizados ---")

# ── 2) header de .env.test (solo comentarios; NO toca DATABASE_URL) ──
ENV_TEST = os.path.join(BASE, ".env.test")
src = _leer(ENV_TEST)
OLD_HEADER = (
    "# ============================================================\n"
    "# ADVERTENCIA (19/08/2026) - NO USAR EN PRODUCCION\n"
    "# ============================================================\n"
    "# ESTE ARCHIVO APUNTA A UNA BASE DE DATOS MUERTA.\n"
    "# La branch TEST (ep-lingering-shape) tiene las credenciales ROTADAS\n"
    "# y REJECTADAS por Neon. NO USAR mientras no exista una branch TEST valida.\n"
    "# NUNCA apuntar este archivo a la BD real (ep-withered-silence): scripts\n"
    "# como sync_test_from_prod.py hacen TRUNCATE de la base destino.\n"
    "# Para reutilizarlo: crear branch TEST nueva y actualizar DATABASE_URL.\n"
    "# ============================================================\n"
)
NEW_HEADER = (
    "# ============================================================\n"
    "# BRANCH DE TEST - copia aislada de PRODUCCION\n"
    "# ============================================================\n"
    "# Este archivo apunta a la branch TEST de Neon (copia aislada de\n"
    "# production), segura para pruebas destructivas. Los scripts de test\n"
    "# (sync_test_from_prod, run_setup_test_db) hacen TRUNCATE de la base\n"
    "# destino.\n"
    "# NUNCA usar en produccion real ni apuntar este archivo a la BD real\n"
    "# (ep-withered-silence).\n"
    "# ============================================================\n"
)
e = "\r\n" if "\r\n" in src else "\n"
n = src.count(OLD_HEADER.replace("\n", e))
if n != 1:
    raise SystemExit(f"[.env.test] header no encontrado o ambiguo (matches={n})")
src = src.replace(OLD_HEADER.replace("\n", e), NEW_HEADER.replace("\n", e))
_escribir(ENV_TEST, src)
print("[.env.test] header actualizado (DATABASE_URL NO modificada)")

# ── 3) nota de backend/README.md ──
README = os.path.join(BASE, "README.md")
src = _leer(README)
OLD_NOTE = (
    "apunta a la BD de TEST `ep-lingering-shape`, cuyas credenciales estan "
    "**rotadas/muertas**"
)
NEW_NOTE = (
    "apunta a la **branch TEST** de Neon (copia aislada de produccion, segura "
    "para pruebas destructivas)"
)
if OLD_NOTE in src:
    src = src.replace(OLD_NOTE, NEW_NOTE)
    print("[README.md] nota de iniciar_servidor actualizada")
else:
    print("[README.md] aviso: nota 1 no encontrada, se intenta variante acentuada")
    OLD2 = OLD_NOTE.replace("estan", "están")
    if OLD2 in src:
        src = src.replace(OLD2, NEW_NOTE)
        print("[README.md] nota de iniciar_servidor actualizada (variante acentuada)")
    else:
        raise SystemExit("[README.md] no se pudo localizar la nota 1")

OLD_NOTE2 = (
    "apunta a la branch TEST `ep-lingering-shape` (credenciales **rotadas/muertas**)"
)
NEW_NOTE2 = (
    "apunta a la **branch TEST** (copia aislada de produccion, segura para "
    "pruebas destructivas)"
)
if OLD_NOTE2 in src:
    src = src.replace(OLD_NOTE2, NEW_NOTE2)
    print("[README.md] nota de .env.test actualizada")
else:
    OLD2B = OLD_NOTE2.replace("rotadas/muertas", "rotadas / muertas")
    if OLD2B in src:
        src = src.replace(OLD2B, NEW_NOTE2)
        print("[README.md] nota de .env.test actualizada (variante)")
    else:
        print("[README.md] aviso: nota 2 no localizada exacta; se revisa manualmente")

_escribir(README, src)

print("\nOK: cierre del ambiente de test aplicado.")
