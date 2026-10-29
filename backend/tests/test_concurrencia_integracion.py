"""Concurrencia REAL contra la API (TEST): las carreras de negocio, con requests simultáneos.

Qué prueba (dos hilos que salen A LA VEZ, no en secuencia)
----------------------------------------------------------
1. **Último cupo** (`POST /reservas`): dos alumnos reservando la única butaca de
   una clase CON tope. Entra UNO (201) y el otro recibe 400; la clase queda con
   `asistentes_confirmados = 1` y una sola reserva viva. La protección es el
   `UPDATE ... WHERE asistentes_confirmados < cupo_maximo` (atómico en la base);
   con `cupo_maximo IS NULL` (Musculación / Open Box) la reserva nunca se rechaza.
2. **Compras concurrentes del mismo alumno** (`POST /suscripciones`): el doble
   clic del mesón. Una sola alta (201) y la otra 409, con UN ingreso en caja.
   La protección es el `SELECT ... FOR UPDATE` de la fila del alumno.
3. **Stock del Bazar** (`POST /pedidos`): dos alumnos comprando el último ítem.
   Un pedido (201) y el otro 400; `productos.stock` queda en 0, nunca negativo.
   La protección es el `UPDATE ... WHERE stock >= cantidad`.
4. **Compra de emergencia** (`POST /comprar-emergencia`): dos requests del mismo
   alumno. Sin lock los dos "compraban" (el cupo es 1 por año); con el
   `FOR UPDATE` de la suscripción el segundo cae en 400.

Cómo se corre
-------------
Es integración REAL (API en :8000 + base TEST): crea usuarios, clases y
productos propios y los borra en el `finally` de cada test. Se saltea sola si la
API no está arriba o si el proceso no corre con `ENVIRONMENT=test`.

    $env:ENVIRONMENT='test'
    py -3.12 -m pytest tests/test_concurrencia_integracion.py -q
"""
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

if os.getenv("ENVIRONMENT") != "test":
    pytest.skip("concurrencia: exige ENVIRONMENT=test (escribe en TEST)",
                allow_module_level=True)

from sqlalchemy import create_engine, text

from app.core.config import is_test_db_url, settings
from app.core.security import create_access_token
from app.utils.santiago import hoy_santiago
from shared import estados

BASE = "http://localhost:8000/api/v1"
TENANT = 1
TIMEOUT = 30
CANCELADAS = estados.lista_sql()      # la MISMA lista de estados que usa la app


@pytest.fixture(scope="module")
def engine():
    """Engine de la base TEST, o skip si la API no está arriba."""
    try:
        r = requests.get("http://localhost:8000/health", timeout=5)
        if r.status_code != 200:
            pytest.skip("API no disponible en :8000")
    except requests.RequestException:
        pytest.skip("API no disponible en :8000")

    url = settings.DIRECT_URL or settings.DATABASE_URL
    if not is_test_db_url(url):
        pytest.fail("la URL configurada NO es TEST: aborto (exporta ENVIRONMENT=test)")
    return create_engine(url)


def headers(usuario_id, rol="alumno", tenant=TENANT):
    """Token firmado igual que `tests/conftest.py` (no hace falta login)."""
    token = create_access_token({
        "usuario_id": usuario_id, "tenant_id": tenant, "rol": rol,
        "correo": f"{rol}{usuario_id}@test.local",
    })
    return {"Authorization": f"Bearer {token}"}


def en_paralelo(acciones):
    """Corre todas las acciones en hilos distintos, arrancando juntas.

    La `Barrier` es el punto: ningún request sale hasta que están TODOS listos,
    así la ventana de carrera es real y no "el primero terminó antes del segundo".
    """
    barrera = threading.Barrier(len(acciones))

    def correr(accion):
        barrera.wait(timeout=10)
        return accion()

    with ThreadPoolExecutor(max_workers=len(acciones)) as pool:
        futuros = [pool.submit(correr, accion) for accion in acciones]
        return [f.result(timeout=TIMEOUT) for f in futuros]


class Escenario:
    """Filas propias de un test, con limpieza garantizada (`finally`)."""

    def __init__(self, engine):
        self.engine = engine
        self.usuarios = []
        self.suscripciones = []
        self.clases = []
        self.productos = []
        with engine.connect() as c:
            planes = [r[0] for r in c.execute(text(
                "select id from planes where tenant_id = :t order by id limit 2"),
                {"t": TENANT}).fetchall()]
            self.horario = c.execute(text(
                "select id, disciplina_id from horarios where tenant_id = :t "
                "order by id limit 1"), {"t": TENANT}).first()
        self.plan = planes[0] if planes else None
        # Plan DISTINTO para la compra concurrente: la suscripción que crea el
        # fixture usa `self.plan`, y la ventana de idempotencia del alta (10 min)
        # respondería 409 antes de la carrera.
        self.plan_compra = planes[1] if len(planes) > 1 else None
        if not self.plan or not self.horario:
            pytest.skip("TEST sin planes u horarios base: nada que escenificar")

    # ── alta ────────────────────────────────────────────────────────────────
    def alumno(self, creditos=5):
        return self.usuario(creditos=creditos, rol="alumno")

    def admin(self):
        return self.usuario(creditos=5, rol="administrador")

    def usuario(self, creditos=5, rol="alumno"):
        sufijo = uuid.uuid4().hex[:10]
        with self.engine.begin() as c:
            uid = c.execute(text("""
                insert into usuarios
                    (tenant_id, rut, nombre, correo, password_hash, rol, activo, estado)
                values (:t, :rut, :nom, :mail, 'x', :rol, true, 'activo')
                returning id"""), {
                "t": TENANT, "rut": f"9{sufijo[:7]}",
                "nom": f"Concurrencia {sufijo}",
                "mail": f"concurrencia-{sufijo}@test.local",
                "rol": rol,
            }).scalar()
            self.usuarios.append(uid)
            sid = c.execute(text("""
                insert into suscripciones
                    (tenant_id, usuario_id, plan_id, estado, creditos_totales,
                     creditos_disponibles, fecha_inicio, fecha_expiracion)
                values (:t, :u, :p, 'activo', :cr, :cr, now(),
                        now() + interval '30 days')
                returning id"""), {
                "t": TENANT, "u": uid, "p": self.plan, "cr": creditos,
            }).scalar()
            self.suscripciones.append(sid)
        return uid

    def clase(self, cupo=1):
        """Una clase PROPIA para hoy (el alta de reservas rechaza fechas pasadas)."""
        with self.engine.begin() as c:
            cid = c.execute(text("""
                insert into clases
                    (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio,
                     hora_fin, cupo_maximo, cupo_original, asistentes_confirmados,
                     cancelada)
                values (:t, :h, :d, :f, time '09:00', time '10:00', :cupo, :cupo,
                        0, false)
                returning id"""), {
                "t": TENANT, "h": self.horario.id, "d": self.horario.disciplina_id,
                "f": hoy_santiago(), "cupo": cupo,
            }).scalar()
            self.clases.append(cid)
        return cid

    def producto(self, stock=1, precio=1000):
        with self.engine.begin() as c:
            pid = c.execute(text("""
                insert into productos (tenant_id, nombre, precio, stock, activo,
                                       dias_anuncio, alerta_stock_enviada)
                values (:t, :nom, :precio, :stock, true, 0, false)
                returning id"""), {
                "t": TENANT, "nom": f"Producto concurrencia {uuid.uuid4().hex[:8]}",
                "precio": precio, "stock": stock,
            }).scalar()
            self.productos.append(pid)
        return pid

    # ── baja ────────────────────────────────────────────────────────────────
    def limpiar(self):
        ids_u = self.usuarios or [0]
        ids_c = self.clases or [0]
        ids_p = self.productos or [0]
        ids_s = self.suscripciones or [0]
        with self.engine.begin() as c:
            # FKs NO ACTION/SET NULL que apuntan a `usuarios`: primero los avisos
            # (el POST /pedidos y el alta de membresía mandan correo/campana).
            c.execute(text("delete from notificaciones_enviadas "
                           "where alumno_id = any(:u)"), {"u": ids_u})
            c.execute(text("delete from notificaciones "
                           "where alumno_id = any(:u)"), {"u": ids_u})
            c.execute(text("delete from pedidos where alumno_id = any(:u) "
                           "or producto_id = any(:p)"), {"u": ids_u, "p": ids_p})
            c.execute(text("delete from reservas where alumno_id = any(:u) "
                           "or clase_id = any(:c)"), {"u": ids_u, "c": ids_c})
            c.execute(text("delete from transacciones_financieras "
                           "where referencia_tipo = 'suscripcion' and referencia_id in "
                           "(select id from suscripciones where usuario_id = any(:u) "
                           " or id = any(:s))"), {"u": ids_u, "s": ids_s})
            c.execute(text("delete from suscripciones where usuario_id = any(:u) "
                           "or id = any(:s)"), {"u": ids_u, "s": ids_s})
            c.execute(text("delete from productos where id = any(:p)"), {"p": ids_p})
            c.execute(text("delete from clases where id = any(:c)"), {"c": ids_c})
            c.execute(text("delete from usuarios where id = any(:u)"), {"u": ids_u})



# ── 1. Último cupo: dos alumnos, una butaca ──────────────────────────────────
def test_ultimo_cupo_solo_entra_uno(engine):
    esc = Escenario(engine)
    try:
        alumno_a, alumno_b = esc.alumno(), esc.alumno()
        clase = esc.clase(cupo=1)

        def reservar(alumno_id):
            return requests.post(
                f"{BASE}/reservas",
                json={"tenant_id": TENANT, "clase_id": clase,
                      "alumno_id": alumno_id},
                headers=headers(alumno_id), timeout=TIMEOUT)

        r_a, r_b = en_paralelo([
            lambda: reservar(alumno_a), lambda: reservar(alumno_b)])

        assert sorted([r_a.status_code, r_b.status_code]) == [201, 400], (
            f"esperaba 201 + 400, llegaron {r_a.status_code}/{r_b.status_code}: "
            f"{r_a.text[:200]} | {r_b.text[:200]}")

        with engine.connect() as c:
            asistentes = c.execute(text(
                "select asistentes_confirmados from clases where id = :id"),
                {"id": clase}).scalar()
            vivas = c.execute(text(
                f"select count(*) from reservas where clase_id = :id "
                f"and estado not in ({CANCELADAS})"), {"id": clase}).scalar()
        assert asistentes == 1, "el aforo no puede pasar del cupo"
        assert vivas == 1, "dos alumnos no pueden quedar reservados en una butaca"
    finally:
        esc.limpiar()


# ── 2. Compras concurrentes del mismo alumno (doble clic del mesón) ──────────
def test_doble_compra_del_mismo_alumno_crea_una_sola(engine):
    esc = Escenario(engine)
    try:
        alumno = esc.alumno()
        admin = esc.admin()
        plan = esc.plan_compra
        if plan is None:
            pytest.skip("TEST necesita dos planes para probar el alta concurrente")

        def comprar():
            return requests.post(
                f"{BASE}/suscripciones",
                json={"tenant_id": TENANT, "usuario_id": alumno,
                      "plan_id": plan},
                headers=headers(admin, rol="administrador"), timeout=TIMEOUT)

        r_1, r_2 = en_paralelo([comprar, comprar])

        assert sorted([r_1.status_code, r_2.status_code]) == [201, 409], (
            f"esperaba 201 + 409, llegaron {r_1.status_code}/{r_2.status_code}: "
            f"{r_1.text[:200]} | {r_2.text[:200]}")

        with engine.connect() as c:
            altas = c.execute(text(
                "select count(*) from suscripciones "
                "where usuario_id = :u and plan_id = :p"),
                {"u": alumno, "p": plan}).scalar()
            ingresos = c.execute(text(
                "select count(*) from transacciones_financieras "
                "where referencia_tipo = 'suscripcion' and referencia_id in "
                "(select id from suscripciones where usuario_id = :u "
                " and plan_id = :p)"), {"u": alumno, "p": plan}).scalar()
        assert altas == 1, "el doble clic no puede dejar dos suscripciones"
        assert ingresos == 1, "el doble clic no puede cobrar dos veces"
    finally:
        esc.limpiar()


# ── 3. Bazar: dos alumnos y el último ítem ───────────────────────────────────
def test_ultimo_item_del_bazar_no_se_vende_dos_veces(engine):
    esc = Escenario(engine)
    try:
        alumno_a, alumno_b = esc.alumno(), esc.alumno()
        producto = esc.producto(stock=1)

        def comprar(alumno_id):
            return requests.post(
                f"{BASE}/pedidos",
                json={"tenant_id": TENANT, "alumno_id": alumno_id,
                      "producto_id": producto, "cantidad": 1,
                      "voucher_url": "https://test.local/voucher.png"},
                headers=headers(alumno_id), timeout=TIMEOUT)

        r_a, r_b = en_paralelo([
            lambda: comprar(alumno_a), lambda: comprar(alumno_b)])

        assert sorted([r_a.status_code, r_b.status_code]) == [201, 400], (
            f"esperaba 201 + 400, llegaron {r_a.status_code}/{r_b.status_code}: "
            f"{r_a.text[:200]} | {r_b.text[:200]}")

        with engine.connect() as c:
            stock = c.execute(text("select stock from productos where id = :id"),
                              {"id": producto}).scalar()
            pedidos = c.execute(text(
                "select count(*) from pedidos where producto_id = :id"),
                {"id": producto}).scalar()
        assert stock == 0, f"el stock quedó en {stock}: se vendió de más"
        assert pedidos == 1
    finally:
        esc.limpiar()


# ── 4. Compra de emergencia: el cupo anual es 1 (lock de la suscripción) ─────
def test_compra_de_emergencia_simultanea_solo_una(engine):
    esc = Escenario(engine)
    try:
        # Sin créditos: es la condición de negocio para poder comprar emergencia.
        alumno = esc.alumno(creditos=0)

        def comprar():
            return requests.post(
                f"{BASE}/planes/comprar-emergencia",
                json={"tenant_id": TENANT, "alumno_id": alumno,
                      "plan_id": esc.plan},
                headers=headers(alumno), timeout=TIMEOUT)

        r_1, r_2 = en_paralelo([comprar, comprar])

        assert sorted([r_1.status_code, r_2.status_code]) == [200, 400], (
            f"esperaba 200 + 400, llegaron {r_1.status_code}/{r_2.status_code}: "
            f"{r_1.text[:200]} | {r_2.text[:200]}")
        with engine.connect() as c:
            fecha = c.execute(text(
                "select fecha_compra_emergencia from suscripciones where id = :s"),
                {"s": esc.suscripciones[0]}).scalar()
        assert fecha is not None, "la compra ganadora tiene que quedar registrada"
    finally:
        esc.limpiar()
