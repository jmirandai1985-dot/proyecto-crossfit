"""
Código de RETIRO del Bazar (`app/services/codigos_retiro.py`) — tests AISLADOS.

Qué se prueba, SIN red y SIN base de datos:

  * FORMATO: `UB-` + 4 símbolos, con el `PATRON` DERIVADO del alfabeto (una sola
    fuente de verdad), y **sin caracteres ambiguos** (0/O/1/I/L) — ni en el alfabeto
    ni en lo que genera;
  * NORMALIZACIÓN de lo que se tipea o se escanea: "ub-4827", "UB 4827", "ub4827",
    " ub-4827 " y hasta solo "4827" → `UB-4827`; basura / largo equivocado → `None`;
  * UNICIDAD POR BOX: `generar_codigo_unico` reintenta si el código ya está en uso y
    se rinde ruidosamente (`SinCodigoDisponible`) si no hay forma;
  * VALIDACIONES de la entrega: pendiente → `no_validado`, entregado → `ya_entregado`,
    validado → se puede; y los textos (fecha en hora de CHILE + quién entregó);
  * WIRING (guard de fuente, mismo patrón que test_asignaciones_clases.py): el
    endpoint de entrega saca el box del TOKEN, exige coach/admin del box, tiene rate
    limit, genera el código al VALIDAR, sella `entregado_por`/`entregado_en` y avisa
    al alumno; la migración 044 encadena con 043 y trae índice único + CHECK +
    backfill; y el front del admin/alumno/coach está conectado.

    cd backend && py -3.12 -m pytest tests/test_codigos_retiro.py --noconftest -q
"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import codigos_retiro as cr

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit


class _SesionFalsa:
    """Sesión mínima, sin BD: solo lo que usa el servicio.

    * `colisiones`: cuántos `first()` seguidos devuelven una fila (código ya en uso)
      antes de empezar a devolver `None`;
    * `filas`: fila fija que devuelve `first()` cuando ya no hay colisiones (para
      simular el pedido que se encuentra con el código);
    * `filtros`: los argumentos de cada `filter(...)`, para poder afirmar QUÉ filtra.
    """

    def __init__(self, filas=None, colisiones=0):
        self.filas = filas
        self.restantes = colisiones
        self.consultas = 0
        self.filtros = []

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        self.filtros.append(args)
        return self

    def first(self):
        self.consultas += 1
        if self.restantes > 0:
            self.restantes -= 1
            return (1,)
        return self.filas


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


# ── Formato y alfabeto ────────────────────────────────────────────────────────

def test_el_formato_es_ub_mas_cuatro_simbolos():
    for _ in range(200):
        codigo = cr.generar_codigo()
        assert cr.PATRON.match(codigo), codigo
        assert codigo.startswith(f"{cr.PREFIJO}-")
        assert len(codigo) == len(cr.PREFIJO) + 1 + cr.LARGO


def test_el_alfabeto_no_tiene_caracteres_ambiguos():
    for ambiguo in cr.AMBIGUOS:
        assert ambiguo not in cr.ALFABETO, f"{ambiguo!r} no deberia estar"
    for _ in range(200):
        cuerpo = cr.generar_codigo().split("-")[1]
        assert not (set(cuerpo) & set(cr.AMBIGUOS)), cuerpo


def test_el_patron_se_deriva_del_alfabeto():
    """Si alguien agrega un símbolo al alfabeto, el formato lo acepta solo."""
    assert cr.PATRON.match(f"{cr.PREFIJO}-{cr.ALFABETO[0] * cr.LARGO}")
    for ambiguo in cr.AMBIGUOS:
        assert not cr.PATRON.match(f"{cr.PREFIJO}-{ambiguo * cr.LARGO}")
    # Largo equivocado y sin prefijo.
    assert not cr.PATRON.match(f"{cr.PREFIJO}-{cr.ALFABETO[0] * (cr.LARGO - 1)}")
    assert not cr.PATRON.match(f"{cr.PREFIJO}-{cr.ALFABETO[0] * (cr.LARGO + 1)}")
    assert not cr.PATRON.match(cr.ALFABETO[0] * cr.LARGO)


def test_generar_codigo_es_inyectable_para_tests():
    assert cr.generar_codigo(lambda secuencia: "4") == "UB-4444"
    assert cr.generar_codigo(lambda secuencia: secuencia[0]) == "UB-2222"


# ── Normalización ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada", [
    "UB-4827", "ub-4827", " ub 4827 ", "ub4827", "UB–4827", "4827",
    ":UB-4827\n", "UB_4827", "Ub-4827",
])
def test_normalizar_acepta_lo_que_se_tipea_o_se_escanea(entrada):
    assert cr.normalizar(entrada) == "UB-4827"


@pytest.mark.parametrize("entrada", [
    None, "", "   ", "-", "UB-", "UB-123", "UB-48278", "P4827", "XXUB-4827",
    "codigo: 4827-",
])
def test_normalizar_rechaza_lo_que_no_es_un_codigo(entrada):
    assert cr.normalizar(entrada) is None


def test_codigo_valido_exige_el_alfabeto():
    assert cr.codigo_valido("ub 4827") is True
    # 'O' y '1' no existen en el alfabeto: normalizan pero NO son válidos.
    assert cr.normalizar("UB-4O27") == "UB-4O27"
    assert cr.codigo_valido("UB-4O27") is False
    assert cr.codigo_valido("UB-I111") is False
    assert cr.codigo_valido("UB-4O2") is False          # 3 símbolos
    assert cr.codigo_valido("UB-482799") is False       # 6 símbolos
    assert cr.codigo_valido("demasiado-largo") is False


# ── Unicidad por box ──────────────────────────────────────────────────────────

def test_codigo_en_uso_pregunta_a_la_bd():
    assert cr.codigo_en_uso(_SesionFalsa(colisiones=1), 1, "UB-4827") is True
    assert cr.codigo_en_uso(_SesionFalsa(colisiones=0), 1, "UB-4827") is False


def test_generar_codigo_unico_reintenta_si_el_box_ya_lo_tiene():
    db = _SesionFalsa(colisiones=3)
    codigo = cr.generar_codigo_unico(db, tenant_id=7)
    assert cr.codigo_valido(codigo)
    assert db.consultas == 4, "deberia haber reintentado 3 veces"


def test_generar_codigo_unico_avisa_si_no_hay_forma():
    db = _SesionFalsa(colisiones=1000)
    with pytest.raises(cr.SinCodigoDisponible) as error:
        cr.generar_codigo_unico(db, tenant_id=7, intentos=5)
    assert db.consultas == 5
    assert "box 7" in str(error.value)


def test_la_busqueda_filtra_por_el_box():
    """El código de OTRO box no existe: el filtro lleva el tenant_id."""
    db = _SesionFalsa(filas=None)
    cr.buscar_pedido_por_codigo(db, tenant_id=99, codigo="UB-4827")
    filtros = " ".join(str(a) for args in db.filtros for a in args)
    assert "pedidos.tenant_id" in filtros
    assert "pedidos.codigo_retiro" in filtros


def test_la_busqueda_normaliza_antes_de_consultar():
    pedido = SimpleNamespace(id=5, estado="validado")
    db = _SesionFalsa(filas=pedido)
    assert cr.buscar_pedido_por_codigo(db, 1, " ub 4827 ") is pedido
    assert db.consultas == 1


def test_la_busqueda_de_algo_sin_forma_no_toca_la_bd():
    db = _SesionFalsa(filas=SimpleNamespace(id=5))
    assert cr.buscar_pedido_por_codigo(db, 1, "no-es-un-codigo") is None
    assert cr.buscar_pedido_por_codigo(db, 1, None) is None
    assert db.consultas == 0


# ── Validaciones de la entrega (manda el estado del pedido) ───────────────────

def test_un_pedido_validado_se_puede_entregar():
    assert cr.motivo_no_entregable(SimpleNamespace(estado="validado")) is None


def test_un_pedido_pendiente_no_se_entrega():
    assert cr.motivo_no_entregable(
        SimpleNamespace(estado="pendiente")) == cr.MOTIVO_NO_VALIDADO


def test_un_pedido_ya_entregado_no_se_vuelve_a_entregar():
    assert cr.motivo_no_entregable(
        SimpleNamespace(estado="entregado")) == cr.MOTIVO_YA_ENTREGADO


def test_sin_pedido_no_se_entrega():
    assert cr.motivo_no_entregable(None) == cr.MOTIVO_NO_VALIDADO


def test_fmt_entrega_usa_la_hora_de_chile():
    # 2026-04-10 23:30 UTC = 19:30 en Chile (abril ya fuera del horario de verano).
    assert cr.fmt_entrega(
        datetime(2026, 4, 10, 23, 30, tzinfo=timezone.utc)) == "10/04/2026 19:30"
    # Un instante sin zona se asume UTC (lo que devuelve Postgres).
    assert cr.fmt_entrega(datetime(2026, 4, 10, 23, 30)) == "10/04/2026 19:30"
    assert cr.fmt_entrega(None) == "fecha desconocida"


def test_texto_validado_lleva_el_codigo():
    texto = cr.texto_validado("Polera", 2, "UB-4827")
    assert "fue validado" in texto
    assert "Código de retiro: UB-4827" in texto


def test_texto_no_validado_explica_que_falta_la_validacion():
    texto = cr.texto_no_validado(SimpleNamespace(id=12, estado="pendiente"))
    assert "#12" in texto
    assert "todavía no fue validado" in texto


def test_texto_ya_entregado_dice_fecha_y_quien_entrego():
    pedido = SimpleNamespace(
        entregado_en=datetime(2026, 4, 10, 23, 30, tzinfo=timezone.utc))
    assert cr.texto_ya_entregado(pedido, "Ana Admin") == (
        "Este pedido ya fue entregado el 10/04/2026 19:30 por Ana Admin")


def test_texto_ya_entregado_sin_datos_no_revienta():
    assert cr.texto_ya_entregado(SimpleNamespace(entregado_en=None), None) == (
        "Este pedido ya fue entregado el fecha desconocida por otro usuario")


# ── WIRING: migración 044 y modelo ────────────────────────────────────────────

def test_migracion_044_encadena_con_043():
    fuente = _fuente("backend/alembic/versions/044_pedidos_codigo_retiro.py")
    assert 'revision: str = "044_pedidos_codigo_retiro"' in fuente
    assert ('down_revision: Union[str, None] = "043_horarios_coach_vigencia"'
            in fuente)
    assert fuente.count('op.add_column("pedidos"') == 3
    for columna in ("codigo_retiro", "entregado_por", "entregado_en"):
        assert columna in fuente, columna


def test_migracion_044_trae_unico_check_y_backfill():
    fuente = _fuente("backend/alembic/versions/044_pedidos_codigo_retiro.py")
    assert 'op.create_index("uq_pedidos_codigo_retiro", "pedidos"' in fuente
    assert "unique=True" in fuente
    assert "ck_pedidos_codigo_retiro_formato" in fuente
    # Backfill: SOLO los pedidos ya validados y sin código (idempotente).
    assert "WHERE estado = 'validado' AND codigo_retiro IS NULL" in fuente
    assert fuente.count('op.drop_column("pedidos"') == 3
    # El alfabeto de la migración es el mismo del runtime (misma fuente de verdad).
    assert f'ALFABETO = "{cr.ALFABETO}"' in fuente
    assert f'PREFIJO = "{cr.PREFIJO}"' in fuente


def test_el_modelo_declara_las_columnas_el_unico_y_el_formato():
    fuente = _fuente("backend/app/models/pedido.py")
    assert "codigo_retiro = Column(String(12), nullable=True)" in fuente
    assert "entregado_por = Column(Integer, ForeignKey(" in fuente
    assert "entregado_en = Column(TIMESTAMP(timezone=True), nullable=True)" in fuente
    assert ("Index('uq_pedidos_codigo_retiro', 'tenant_id', 'codigo_retiro', "
            "unique=True)") in fuente
    assert "name='ck_pedidos_codigo_retiro_formato'" in fuente


# ── WIRING: endpoints del backend ─────────────────────────────────────────────

def _bloque(fuente: str, desde: str) -> str:
    """Texto desde `desde` hasta el siguiente decorador `@router.` (su endpoint)."""
    inicio = fuente.index(desde)
    resto = fuente[inicio:]
    siguiente = resto.find("@router.", len(desde))
    return resto if siguiente == -1 else resto[:siguiente]


def test_la_entrega_exige_coach_del_box_y_tiene_rate_limit():
    fuente = _fuente("backend/app/api/v1/pedidos.py")
    bloque = _bloque(fuente, '@router.post("/entregar"')
    # Quién entrega: coach o admin (get_current_coach), nunca un alumno.
    assert "Depends(get_current_coach)" in bloque
    # 🔒 El box sale del TOKEN: no hay query param `tenant_id` que se pueda falsear.
    assert 'tenant_id = current_user["tenant_id"]' in bloque
    assert "tenant_id: Optional[int] = None" not in bloque
    # Anti fuerza bruta del código.
    assert "@limiter.limit(LIMIT_CODIGO_RETIRO)" in bloque
    # 404 genérico (no revela si el código existe en otro box) y 409 con el detalle.
    assert "status.HTTP_404_NOT_FOUND" in bloque
    assert "status.HTTP_409_CONFLICT" in bloque
    assert "texto_ya_entregado" in bloque
    assert "texto_no_validado" in bloque


def test_la_entrega_es_atomica_y_sella_la_traza():
    """UPDATE condicional: dos escaneos simultáneos entregan UNA sola vez."""
    bloque = _bloque(_fuente("backend/app/api/v1/pedidos.py"),
                     '@router.post("/entregar"')
    assert "update(Pedido)" in bloque
    assert 'Pedido.estado == "validado"' in bloque
    assert 'estado="entregado"' in bloque
    assert 'entregado_por=current_user["usuario_id"]' in bloque
    assert "entregado_en=ahora_santiago()" in bloque
    assert "rowcount" in bloque


def test_al_validar_se_genera_el_codigo_una_sola_vez():
    bloque = _bloque(_fuente("backend/app/api/v1/pedidos.py"),
                     '@router.put("/{pedido_id}/estado"')
    assert 'nuevo_estado == "validado" and not pedido.codigo_retiro' in bloque
    assert "codigos_retiro.generar_codigo_unico(" in bloque
    assert "db, tenant_id" in bloque
    assert "texto_validado(" in bloque


def test_la_entrega_avisa_en_la_campana_del_alumno():
    fuente = _fuente("backend/app/api/v1/pedidos.py")
    assert 'notificar_alumno(\n' in fuente or "notificar_alumno(" in fuente
    assert '"pedido_entregado"' in fuente
    # El respaldo sin código (PUT /{id}/estado) también sella quién/cuándo.
    respaldo = _bloque(fuente, '@router.put("/{pedido_id}/estado"')
    assert 'nuevo_estado == "entregado"' in respaldo
    assert "entregado_por = current_user" in respaldo
    assert "entregado_en = ahora_santiago()" in respaldo


def test_el_qr_del_retiro_sirve_el_svg_del_codigo():
    bloque = _bloque(_fuente("backend/app/api/v1/pedidos.py"),
                     '@router.get("/{pedido_id}/qr.svg"')
    assert "segno" in bloque
    assert "image/svg+xml" in bloque
    assert "codigo_retiro" in bloque
    assert "puede_ver_documento" in bloque          # dueño o staff del box
    assert "Depends(get_current_user)" in bloque


def test_el_rate_limit_del_codigo_esta_declarado():
    fuente = _fuente("backend/app/core/rate_limit.py")
    assert 'LIMIT_CODIGO_RETIRO = "' in fuente
    assert 'LIMIT_CODIGO_RETIRO' in _fuente("backend/app/api/v1/pedidos.py")


def test_los_schemas_exponen_la_traza_de_la_entrega():
    fuente = _fuente("backend/app/schemas/pedido.py")
    for campo in ("codigo_retiro", "entregado_en", "entregado_por",
                  "entregado_por_nombre"):
        assert campo in fuente, campo
    # El coach NO ve montos: su respuesta solo trae alumno, producto, cantidad.
    inicio = fuente.index("class PedidoEntregaResponse")
    fin = fuente.find("\nclass ", inicio + 1)
    entrega = fuente[inicio:fin if fin != -1 else len(fuente)]
    assert "alumno_nombre" in entrega and "producto_nombre" in entrega
    assert "cantidad" in entrega and "entregado_en" in entrega
    assert "total:" not in entrega
    # …y el body de la entrega es el código (obligatorio).
    assert "class PedidoEntregaRequest" in fuente
    assert "codigo: str = Field(" in fuente
