"""Cuentas PERMANENTES del instituto — una sola lista y un solo guard.

El box se presenta con 3 cuentas que NO son datos de prueba:

    demo.admin@urbanbox.cl    rol 'administrador'
    demo.coach@urbanbox.cl    rol 'coach'
    demo.alumno@urbanbox.cl   rol 'alumno'

Las crea/actualiza `crear_usuarios_demo.py` y se quedan en el box: son las cuentas
de presentación del instituto. Este módulo centraliza la lista y los guards que las
protegen de CUALQUIER script de limpieza o purga:

  * `crear_usuarios_demo.py --borrar`  -> se NIEGA salvo que se pase
                                          `--forzar-borrado-cuentas-instituto`.
  * `borrar_usuarios_prueba.py`        -> aborta si su lista de correos las incluye.
  * `borrar_seed_anual.py`             -> aborta si su filtro `LIKE` las alcanzara.
  * `run_setup_test_db.py`             -> las CAPTURA antes de la limpieza de TEST y
                                          las REINSERTA después (usuarios.tenant_id es
                                          ON DELETE CASCADE y ese seed borra los tenants).

Qué NO hace: no importa la app, no lee `.env` ni abre conexiones. `capturar()` y
`restaurar()` reciben la sesión ya abierta por el script que las llama; importar este
módulo es gratis (y por eso los tests pueden ejercitarlo aislado).
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from sqlalchemy import text

# La lista es la FUENTE DE VERDAD: cualquier script que borre usuarios compara contra
# esto. `crear_usuarios_demo.py` la usa como sus 3 correos (y se auto-verifica).
CUENTAS_INSTITUTO: tuple = (
    "demo.admin@urbanbox.cl",
    "demo.coach@urbanbox.cl",
    "demo.alumno@urbanbox.cl",
)

MOTIVO = ("cuentas PERMANENTES del instituto (presentación del box): no son datos de "
          "prueba y ningún script de limpieza o purga las puede borrar")


class CuentaInstituto(RuntimeError):
    """Se intentó borrar/limpiar una cuenta del instituto sin autorización explícita."""


def es_cuenta_instituto(correo: Optional[str]) -> bool:
    """True si `correo` es una de las cuentas permanentes (sin importar mayúsculas)."""
    if not correo:
        return False
    return str(correo).strip().lower() in {c.lower() for c in CUENTAS_INSTITUTO}


def cuentas_instituto_en(correos: Iterable[str]) -> tuple:
    """Subconjunto de `correos` que son cuentas del instituto (en el orden de la lista)."""
    pedidos = {str(c).strip().lower() for c in correos or () if c}
    return tuple(c for c in CUENTAS_INSTITUTO if c.lower() in pedidos)


def abortar_si_hay_cuentas_instituto(correos: Iterable[str], contexto: str,
                                     forzar: bool = False) -> tuple:
    """Falla CERRADO si `correos` incluye cuentas del instituto.

    Devuelve la tupla de cuentas afectadas (vacía si no hay ninguna). Con `forzar=True`
    NO aborta (el llamador pidió explícitamente pisarlas) pero igual devuelve cuáles son,
    para que el script lo avise en pantalla.
    """
    afectadas = cuentas_instituto_en(correos)
    if afectadas and not forzar:
        raise CuentaInstituto(
            f"{contexto}: la operación alcanza {len(afectadas)} de las cuentas del "
            f"instituto ({', '.join(afectadas)}). {MOTIVO}.")
    return afectadas


def patron_alcanza_cuentas_instituto(prefijo: str, sufijo: str = "") -> tuple:
    """Cuentas del instituto que caerían en un filtro `correo LIKE '<prefijo>%<sufijo>'`.

    Sirve para los scripts que borran por PATRÓN (seed anual, ml): si el prefijo/sufijo
    alcanzara una cuenta del instituto, el borrado masivo se tiene que negar.
    """
    p = (prefijo or "").lower()
    s = (sufijo or "").lower()
    return tuple(c for c in CUENTAS_INSTITUTO
                 if c.lower().startswith(p) and c.lower().endswith(s))


def abortar_si_patron_alcanza_instituto(prefijo: str, sufijo: str, contexto: str) -> tuple:
    """Igual que `abortar_si_hay_cuentas_instituto` pero para borrados por patrón."""
    afectadas = patron_alcanza_cuentas_instituto(prefijo, sufijo)
    if afectadas:
        raise CuentaInstituto(
            f"{contexto}: el filtro 'correo LIKE {prefijo}%{sufijo}' alcanza "
            f"{', '.join(afectadas)}, que son {MOTIVO}.")
    return afectadas


def sql_no_instituto(columna: str = "correo") -> str:
    """`<columna> NOT IN ('a','b','c')` para blindar un DELETE masivo que no pasa por la
    lista de correos. Los valores son constantes del módulo (no hay inyección).
    """
    lista = ", ".join(f"'{c}'" for c in CUENTAS_INSTITUTO)
    return f"{columna} NOT IN ({lista})"


# ── Respaldo/restauración para los borrados TOTALES de TEST ─────────────────
# `run_setup_test_db.py` borra TODOS los usuarios y TODOS los tenants; como
# `usuarios.tenant_id` es ON DELETE CASCADE, las cuentas del instituto se irían con el
# tenant. Se capturan como JSON (el esquema manda: no se listan columnas a mano) y se
# reinsertan después de recrear el tenant 1, conservando id y password_hash.
def capturar(db) -> list:
    """Filas COMPLETAS (jsonb) de las cuentas del instituto que existan en la sesión."""
    filas = db.execute(
        text("SELECT to_jsonb(u) AS fila FROM usuarios u WHERE correo = ANY(:correos)"),
        {"correos": list(CUENTAS_INSTITUTO)}).fetchall()
    return [f.fila for f in filas if f.fila]


def restaurar(db, filas: Sequence[dict]) -> int:
    """Reinserta las filas capturadas con sus MISMOS ids/claves. Devuelve cuántas entraron.

    `ON CONFLICT DO NOTHING`: si el id o el correo ya están tomados, la fila se saltea
    (se avisa por stdout) en vez de romper el seed que la llama.
    """
    puestas = 0
    for fila in filas or ():
        cols = [c for c in fila if str(c).isidentifier()]
        if not cols:
            continue
        nombres = ", ".join(f'"{c}"' for c in cols)
        valores = ", ".join(f":v{i}" for i in range(len(cols)))
        params = {f"v{i}": fila[c] for i, c in enumerate(cols)}
        r = db.execute(
            text(f"INSERT INTO usuarios ({nombres}) VALUES ({valores}) "
                 "ON CONFLICT DO NOTHING"), params)
        puestas += r.rowcount or 0
        if not r.rowcount:
            print(f"  [i] {fila.get('correo')}: ya estaba (no se duplica)")
    return puestas
