"""Importa el PADRÓN REAL de BoxMagic (Excel) a la tabla `candidatos_boxmagic`.

⚠️ DATOS PERSONALES: el Excel tiene RUT, fecha de nacimiento, dirección y teléfonos de
712 personas. Vive en `backend/data/` (ignorado por git) y de acá SÓLO se copian
`Nombre`, `Email` y `Estado`. El resto lo completa cada alumno en su propio formulario
el día que migre. Este script NO crea cuentas (`usuarios`): sólo arma el padrón que
leen los paneles de activación y recuperación.

QUÉ HACE
--------
1. Lee el Excel (hoja 1) y se queda con la primera fila de encabezados.
2. Por cada fila: `Nombre`, `Email` (los dos obligatorios) y `Estado`.
   - `correo` se NORMALIZA (sin espacios, minúsculas), porque es la clave del upsert y
     lo que después se cruza con `usuarios.correo` en el endpoint.
   - `estado_boxmagic` = el valor crudo del Excel (Activo/Inactivo/Congelado/Nuevo/
     Prueba) y `grupo` = derivado (`Inactivo` -> 'recuperacion', el resto ->
     'activacion'), con la MISMA función que usa el modelo (`grupo_desde_estado`).
3. UPSERT por `(tenant_id, correo)`: si el correo ya está en el padrón de ese box se
   ACTUALIZAN nombre/estado/grupo; si no, se crea. Correrlo dos veces (o con un Excel
   más nuevo) no duplica nada.
4. Imprime un resumen: creados, actualizados, sin cambios y las filas del Excel que se
   SALTARON (sin correo o sin nombre), con su N° Socio, para revisarlas a mano.

USO (desde `backend/`)
-----------------------
    py -3.12 scripts/importar_candidatos_boxmagic.py --tenant-id 1 --dry-run
    py -3.12 scripts/importar_candidatos_boxmagic.py --tenant-id 1

`--tenant-id` es OBLIGATORIO y no tiene default a propósito: el padrón es de UN box y
nunca se adivina cuál. `--archivo` apunta al Excel por defecto
(`data/candidatos_boxmagic_2026-11-05.xlsx`) o al que se le pase.
"""
import argparse
import os
import sys
import unicodedata
from dataclasses import dataclass, field

# Permite ejecutar `py -3.12 scripts/importar_candidatos_boxmagic.py` desde `backend/`.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from app.core.config import settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402  (después del sys.path)
from app.models.candidato_boxmagic import (  # noqa: E402
    ESTADOS_BOXMAGIC, CandidatoBoxmagic, estado_canonico, grupo_desde_estado,
    normalizar_correo,
)
from app.models.tenant import Tenant  # noqa: E402

ARCHIVO_POR_DEFECTO = os.path.join(
    BACKEND_DIR, "data", "candidatos_boxmagic_2026-11-05.xlsx")

# Alias aceptados de cada columna. Se comparan sin acentos, sin signos y en minúsculas,
# así 'N° Socio', 'N Socio' y 'nro socio' son la misma columna (el encabezado real
# trae un signo de grado que se rompe al abrir el archivo en otro editor).
ALIAS_COLUMNAS = {
    "socio": ("n socio", "nro socio", "numero socio", "socio"),
    "nombre": ("nombre", "nombres", "nombre completo"),
    "correo": ("email", "e mail", "correo", "correo electronico"),
    "estado": ("estado",),
}


@dataclass
class FilaCandidato:
    """Una fila ya limpia del Excel, lista para el upsert."""

    socio: str
    nombre: str
    correo: str
    estado_boxmagic: str
    grupo: str


@dataclass
class ResultadoLectura:
    """Lo que salió del Excel, separado por destino (nada se descarta en silencio)."""

    filas: list = field(default_factory=list)
    saltadas: list = field(default_factory=list)      # [{'socio', 'motivo'}]
    duplicados: list = field(default_factory=list)    # [{'socio', 'correo'}]
    estados_raros: list = field(default_factory=list)  # estados fuera de ESTADOS_BOXMAGIC
    total_filas: int = 0


def _sin_acentos(texto) -> str:
    """Texto comparable: sin acentos, sin signos y en minúsculas ('N° Socio' -> 'n socio')."""
    normal = unicodedata.normalize("NFKD", str(texto or ""))
    limpio = "".join(c for c in normal if not unicodedata.combining(c))
    limpio = "".join(c if (c.isalnum() or c.isspace()) else " " for c in limpio)
    return " ".join(limpio.lower().split())


def _texto(valor) -> str:
    """Celda -> texto recortado, sin el 'nan' que deja pandas en las celdas vacías."""
    if valor is None:
        return ""
    texto = str(valor).strip()
    return "" if texto.lower() in ("nan", "none", "nat") else texto


def _buscar_columna(columnas, clave):
    """Nombre REAL de la columna que corresponde a `clave` (None si no está)."""
    disponibles = {_sin_acentos(columna): columna for columna in columnas}
    for alias in ALIAS_COLUMNAS[clave]:
        if alias in disponibles:
            return disponibles[alias]
    return None


def leer_excel(ruta):
    """Lee el Excel y devuelve un `ResultadoLectura` (NO toca la base).

    Reglas de limpieza, en orden por fila:
      * sin nombre o sin correo -> se SALTEA y se reporta con su N° Socio (nunca se
        inventa ni se completa con datos de otra fila);
      * dos filas con el mismo correo normalizado -> la primera gana y la segunda se
        reporta como duplicada (la base tiene UNIQUE (tenant_id, correo): si no se
        resolviera acá, el upsert tendría dos candidatos para la misma clave);
      * un estado fuera de `ESTADOS_BOXMAGIC` -> se importa igual, con su grupo
        derivado por la misma regla, y se reporta para revisarlo a mano.
    """
    import pandas as pd   # import perezoso: el resto del script no necesita pandas

    tabla = pd.read_excel(ruta, sheet_name=0, dtype=object)
    columnas = list(tabla.columns)
    col_socio = _buscar_columna(columnas, "socio")
    col_nombre = _buscar_columna(columnas, "nombre")
    col_correo = _buscar_columna(columnas, "correo")
    col_estado = _buscar_columna(columnas, "estado")
    faltantes = [nombre for nombre, columna in (
        ("Nombre", col_nombre), ("Email", col_correo), ("Estado", col_estado),
    ) if columna is None]
    if faltantes:
        raise ValueError(
            "Al Excel le faltan columnas obligatorias: " + ", ".join(faltantes)
            + ". Columnas encontradas: " + ", ".join(str(c) for c in columnas))

    resultado = ResultadoLectura(total_filas=len(tabla))
    vistos: dict = {}

    for indice, fila in tabla.iterrows():
        # Fila del Excel como la ve el usuario: +2 (encabezado + índice 0).
        numero_fila = indice + 2
        socio = _texto(fila[col_socio]) if col_socio else ""
        nombre = " ".join(_texto(fila[col_nombre]).split())
        correo = normalizar_correo(_texto(fila[col_correo]))
        estado_crudo = _texto(fila[col_estado])
        referencia = socio or f"fila {numero_fila}"

        motivos = []
        if not nombre:
            motivos.append("sin nombre")
        if not correo:
            motivos.append("sin correo")
        if motivos:
            resultado.saltadas.append(
                {"socio": referencia, "motivo": " y ".join(motivos)})
            continue

        if correo in vistos:
            resultado.duplicados.append({"socio": referencia, "correo": correo})
            continue
        vistos[correo] = True

        estado_boxmagic = estado_canonico(estado_crudo)
        if estado_boxmagic.lower() not in {e.lower() for e in ESTADOS_BOXMAGIC}:
            resultado.estados_raros.append(
                {"socio": referencia, "estado": estado_boxmagic or "(vacío)"})

        resultado.filas.append(FilaCandidato(
            socio=referencia,
            nombre=nombre,
            correo=correo,
            estado_boxmagic=estado_boxmagic or "Activo",
            grupo=grupo_desde_estado(estado_boxmagic),
        ))

    return resultado


def aplicar(db, tenant_id, filas):
    """UPSERT por (tenant_id, correo). Devuelve (creados, actualizados, sin_cambios).

    Lee el padrón del box UNA vez (son cientos de filas, no miles) y decide fila por
    fila. No borra nada: un candidato que ya no viene en el Excel se queda como está
    (borrarlo sería perder el rastro de alguien que existió en BoxMagic).
    """
    existentes = {
        candidato.correo: candidato
        for candidato in db.query(CandidatoBoxmagic)
        .filter(CandidatoBoxmagic.tenant_id == tenant_id)
        .all()
    }

    creados = actualizados = sin_cambios = 0
    for fila in filas:
        actual = existentes.get(fila.correo)
        if actual is None:
            db.add(CandidatoBoxmagic(
                tenant_id=tenant_id,
                nombre=fila.nombre,
                correo=fila.correo,
                estado_boxmagic=fila.estado_boxmagic,
                grupo=fila.grupo,
            ))
            creados += 1
            continue

        actualizados += 1
        cambios = (actual.nombre, actual.estado_boxmagic, actual.grupo) != (
            fila.nombre, fila.estado_boxmagic, fila.grupo)
        if not cambios:
            sin_cambios += 1
            continue
        actual.nombre = fila.nombre
        actual.estado_boxmagic = fila.estado_boxmagic
        actual.grupo = fila.grupo

    db.commit()
    return creados, actualizados, sin_cambios


def _imprimir_lectura(resultado, archivo):
    """Todo lo que hay que saber ANTES de escribir (y lo que se saltó, para revisarlo)."""
    print("=" * 70)
    print(f"Excel: {archivo}")
    print(f"Filas leídas: {resultado.total_filas}")
    print(f"Filas usables: {len(resultado.filas)}")
    grupos = {}
    for fila in resultado.filas:
        grupos[fila.grupo] = grupos.get(fila.grupo, 0) + 1
    print("Por grupo: " + ", ".join(
        f"{grupo}={cantidad}" for grupo, cantidad in sorted(grupos.items())))
    print(f"Saltadas (sin nombre o sin correo): {len(resultado.saltadas)}")
    for fila in resultado.saltadas:
        print(f"   - N° Socio {fila['socio']}: {fila['motivo']}")
    if resultado.duplicados:
        print(f"Duplicadas en el Excel (gana la primera): {len(resultado.duplicados)}")
        for fila in resultado.duplicados:
            print(f"   - N° Socio {fila['socio']}: {fila['correo']}")
    if resultado.estados_raros:
        print(f"Estados fuera de {ESTADOS_BOXMAGIC}: {len(resultado.estados_raros)}")
        for fila in resultado.estados_raros:
            print(f"   - N° Socio {fila['socio']}: '{fila['estado']}' "
                  f"(se importa igual, revisar a mano)")
    print("=" * 70)


def _host(url: str) -> str:
    """Host de la `DATABASE_URL` (para que el admin vea a qué base le está escribiendo)."""
    return (url or "").split("@")[-1].split("/")[0] or "(sin DATABASE_URL)"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Importa el padrón de BoxMagic (Excel) a `candidatos_boxmagic`. "
                    "No crea cuentas: sólo arma la lista que leen los paneles.")
    parser.add_argument("--tenant-id", type=int, required=True,
                        help="Box al que pertenece el padrón (obligatorio: no se adivina).")
    parser.add_argument("--archivo", default=ARCHIVO_POR_DEFECTO,
                        help="Excel a importar (default: data/candidatos_boxmagic_"
                             "2026-11-05.xlsx dentro de backend/).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Lee el Excel y muestra el resumen SIN escribir en la base.")
    args = parser.parse_args(argv)

    archivo = args.archivo
    if not os.path.isabs(archivo):
        archivo = os.path.join(BACKEND_DIR, archivo)
    if not os.path.isfile(archivo):
        sys.exit(f"FATAL: no existe el archivo {archivo}")

    resultado = leer_excel(archivo)
    _imprimir_lectura(resultado, archivo)

    if args.dry_run:
        print("DRY-RUN: no se escribió nada en la base.")
        return 0

    db = SessionLocal()
    try:
        # A qué base le va a escribir: el error caro sería importar el padrón en la base
        # equivocada (TEST en vez de PROD o al revés).
        print("=" * 70)
        print(f"Base de datos: {_host(settings.DATABASE_URL)} "
              f"(ENVIRONMENT={os.environ.get('ENVIRONMENT') or 'sin definir -> TEST'})")
        print("=" * 70)

        tenant = db.query(Tenant).filter(Tenant.id == args.tenant_id).first()
        if tenant is None:
            sys.exit(f"FATAL: no existe el tenant {args.tenant_id}. "
                     "No se escribió nada.")

        print(f"Importando {len(resultado.filas)} candidatos al tenant "
              f"{tenant.id} ({getattr(tenant, 'nombre', 'sin nombre')})...")
        creados, actualizados, sin_cambios = aplicar(db, args.tenant_id, resultado.filas)
    finally:
        db.close()

    print("=" * 70)
    print("RESULTADO")
    print(f"   Creados:      {creados}")
    detalle = "" if actualizados == 0 else f" ({sin_cambios} ya estaban igual)"
    print(f"   Actualizados: {actualizados}{detalle}")
    print(f"   Saltadas:     {len(resultado.saltadas) + len(resultado.duplicados)}"
          " (ver el detalle arriba)")
    print("=" * 70)
    print("Listo. Los paneles ya muestran el padrón:")
    print("   GET /api/v1/migracion-boxmagic/activacion    -> grupo 'activacion'")
    print("   GET /api/v1/migracion-boxmagic/recuperacion  -> grupo 'recuperacion'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
