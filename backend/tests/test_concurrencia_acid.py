"""ACID / concurrencia: las cuatro carreras que se cerraron en el backend.

Qué fija este archivo (sin red y sin base de datos):

  A. `POST /reservas` — dos reservas simultáneas del MISMO alumno en la MISMA
     clase dejan UNA reserva, UN crédito gastado y UN asiento ocupado.
  B. `POST /reservas` — dos reservas simultáneas del MISMO alumno en DOS clases
     distintas con UN solo crédito: la segunda NO se crea (double-spend).
  C. `POST /suscripciones` — dos altas simultáneas iguales crean UNA suscripción
     y UN ingreso en caja (idempotencia del alta manual).
  D. `DELETE /pedidos/{id}` — dos borrados simultáneos devuelven el stock UNA vez
     y el segundo responde 404.
  E. `PUT /pedidos/{id}` — ya no escribe `estado` a mano: delega en las reglas de
     `PUT /{id}/estado` (transiciones, código de retiro, traza de entrega).
  F. La red de la BASE: el índice único parcial `uq_reservas_clase_alumno_viva`
     (migración 057) declara lo mismo que el modelo y la app traduce su
     violación a 400 (`es_reserva_duplicada`).

Cómo se simula Postgres sin Postgres
------------------------------------
`_Sesion` imita lo ÚNICO que decide estas carreras:

  * cada request trabaja sobre una COPIA de la fila (su snapshot), que se
    escribe en la "tabla" recién al commitear — así una lectura vieja NO ve
    mágicamente lo que escribió el otro request;
  * `with_for_update()` **bloquea** la fila hasta el commit/rollback: el segundo
    request ESPERA y, al entrar, descarta su snapshot y lee lo que el primero
    commiteó (READ COMMITTED + lock, que es lo que hace Postgres);
  * `commit()` aplica el índice único parcial de reservas vivas (057).

`_filas()` duerme `RETARDO` DESPUÉS de leer: es la ventana en la que los dos
requests leen el mismo valor. Sin eso, los dos hilos podrían turnarse por azar y
el test pasaría sin probar nada.

Dos guardas de sensibilidad apagan la protección a propósito y muestran el bug:
con el índice apagado entra una segunda reserva viva (`test_a_meta...`) y sin el
`FOR UPDATE` el mismo crédito paga dos clases (`test_b_meta...`). No es
decoración: sin ellas, un test verde no diría si el verde se debe al arreglo o a
que los dos hilos se turnaron por azar.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_concurrencia_acid.py -q --noconftest
"""
import importlib.util
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException                                       # noqa: E402
from sqlalchemy.exc import IntegrityError                             # noqa: E402

from app.api.v1 import pedidos as ped                                  # noqa: E402
from app.api.v1 import reservas as res                                 # noqa: E402
from app.api.v1 import suscripciones as sus                            # noqa: E402
from app.models.reserva import (                                       # noqa: E402
    NOMBRE_INDICE_RESERVA_UNICA, Reserva, es_reserva_duplicada,
)
from app.schemas.pedido import PedidoUpdate                            # noqa: E402
from app.schemas.reserva import ReservaCreate                          # noqa: E402
from app.utils.santiago import hoy_santiago                            # noqa: E402
from shared.estados import ESTADOS_CANCELADA                           # noqa: E402

RETARDO = 0.10                      # segundos de ventana de carrera tras cada lectura
# Sólo las tablas en las que se pelea el valor: dormir en todas haría el archivo lento.
_TABLAS_EN_DISPUTA = {"suscripciones", "reservas", "pedidos", "productos"}


# ══════════════════════════════════════════════════════════════════════════════
#  Doble de la BD: "tablas" en memoria + una sesión por request
# ══════════════════════════════════════════════════════════════════════════════
class _Almacen:
    """Estado compartido por las dos requests (la base de datos)."""

    def __init__(self, sin_indice=False, **tablas):
        self._mutex = threading.Lock()
        self._candados = {}
        self.tablas = {nombre: [dict(f) for f in filas]
                       for nombre, filas in tablas.items()}
        # Arranca arriba del id más alto sembrado: un INSERT no puede pisar una fila.
        self._secuencia = max([f.get("id") or 0 for filas in self.tablas.values()
                               for f in filas] or [0])
        self.sin_indice = sin_indice

    # ── filas (con el mutex: los dos hilos leen/escriben acá) ──
    def candado(self, tabla):
        with self._mutex:
            return self._candados.setdefault(tabla, threading.Lock())

    def filas(self, tabla):
        with self._mutex:
            return [dict(f) for f in self.tablas.get(tabla, [])]

    def nuevo_id(self):
        with self._mutex:
            self._secuencia += 1
            return self._secuencia

    def guardar(self, tabla, fila):
        with self._mutex:
            destino = self.tablas.setdefault(tabla, [])
            for i, actual in enumerate(destino):
                if actual.get("id") == fila.get("id"):
                    destino[i] = dict(fila)
                    return
            destino.append(dict(fila))

    def borrar(self, tabla, ident):
        with self._mutex:
            self.tablas[tabla] = [f for f in self.tablas.get(tabla, [])
                                  if f.get("id") != ident]


def _fila_de(obj) -> dict:
    """Columnas de un modelo ORM, como dict (lo que el INSERT escribiría)."""
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _viva(fila) -> bool:
    """¿La reserva está viva? El predicado del índice parcial de la 057."""
    return getattr(fila, "estado", None) not in ESTADOS_CANCELADA


def _id_del_update(sentencia):
    """El `id` del `WHERE` de un `UPDATE` (los endpoints filtran por id)."""
    for criterio in getattr(sentencia, "_where_criteria", ()):
        izquierda = getattr(criterio, "left", None)
        if getattr(izquierda, "key", None) == "id":
            return getattr(getattr(criterio, "right", None), "value", None)
    return None


class _Consulta:
    """`db.query(Modelo)` con lo que usan estos cuatro endpoints."""

    def __init__(self, sesion, tabla):
        self.ses = sesion
        self.tabla = tabla
        self.criterios = []
        self.bloquear = False

    # ── API fluida ──
    def filter(self, *criterios):
        self.criterios.extend(criterios)
        return self

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self):
        self.bloquear = True
        return self

    def all(self):
        return self._filas()

    def first(self):
        filas = self._filas()
        return filas[0] if filas else None

    # ── el fondo ──
    def _filas(self):
        bloqueado = self.bloquear and not _Sesion.sin_lock
        if bloqueado:
            # Postgres: la segunda request ESPERA acá hasta que la primera
            # commitee, y recién entonces lee (su snapshot viejo se descarta).
            candado = self.ses.almacen.candado(self.tabla)
            candado.acquire()
            self.ses._retener(candado)
            self.ses._olvidar(self.tabla)
        filas = [f for f in self.ses._ver(self.tabla) if _cumple(f, self.criterios)]
        if self.tabla in _TABLAS_EN_DISPUTA and not bloqueado:
            # La copia YA se tomó: dormir acá es la ventana del bug. (También
            # cuando no hay filas: "no existe todavía" es justo lo que leen los
            # dos requests para crear el duplicado.)
            time.sleep(RETARDO)
        return filas


class _Sesion:
    """Sesión mínima: un request = una sesión (como `get_db`)."""

    sin_lock = False                        # meta-tests: apaga el `FOR UPDATE`

    def __init__(self, almacen):
        self.almacen = almacen
        self._copias = {}                   # (tabla, id) -> snapshot del request
        self._nuevos = []                   # [(tabla, obj)] sin commitear
        self._borrados = set()              # {(tabla, id)}
        self._candados = []
        self.committed = False
        self.rolled_back = False

    # ── API de Session ──
    def query(self, modelo):
        return _Consulta(self, modelo.__tablename__)

    def execute(self, sentencia):
        tabla = sentencia.table.name
        copia = self._fila(tabla, _id_del_update(sentencia))
        if tabla == "clases":
            # `UPDATE clases SET asistentes_confirmados = +1 WHERE ... < cupo`
            if copia.asistentes_confirmados < copia.cupo_maximo:
                copia.asistentes_confirmados += 1
                return SimpleNamespace(rowcount=1)
            return SimpleNamespace(rowcount=0)
        if tabla == "suscripciones":
            # `UPDATE suscripciones SET creditos_disponibles = -1 WHERE > 0`
            actuales = copia.creditos_disponibles
            if actuales is not None and actuales > 0:
                copia.creditos_disponibles = actuales - 1
                return SimpleNamespace(rowcount=1)
            return SimpleNamespace(rowcount=0)
        raise AssertionError(f"UPDATE inesperado sobre {tabla}")

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self.almacen.nuevo_id()
        self._nuevos.append((self._tabla_de(obj), obj))

    def delete(self, obj):
        self._borrados.add((self._tabla_de(obj), obj.id))

    def flush(self):
        pass                                # los ids se asignan en `add`

    def _tabla_de(self, obj):
        """A qué tabla pertenece el objeto (los modelos ORM lo dicen; las copias no)."""
        if hasattr(obj.__class__, "__tablename__"):
            return obj.__tablename__
        for (tabla, _ident), copia in self._copias.items():
            if copia is obj:
                return tabla
        raise AssertionError(f"no sé a qué tabla pertenece {obj!r}")

    def commit(self):
        for tabla, obj in self._nuevos:
            self._verificar_indice(tabla, obj)
        for tabla, ident in self._borrados:
            self.almacen.borrar(tabla, ident)
        for (tabla, ident), copia in list(self._copias.items()):
            if (tabla, ident) in self._borrados:
                continue
            self.almacen.guardar(tabla, dict(vars(copia)))
        for tabla, obj in self._nuevos:
            self.almacen.guardar(tabla, _fila_de(obj))
        self._liberar()
        self.committed = True

    def rollback(self):
        self._copias.clear()
        self._nuevos.clear()
        self._borrados.clear()
        self._liberar()
        self.rolled_back = True

    def refresh(self, obj):
        pass

    # ── el fondo ──
    def _ver(self, tabla):
        """Las filas visibles para ESTA sesión, con identidad estable."""
        filas = {f.get("id"): f for f in self.almacen.filas(tabla)}
        for (suya, ident), copia in self._copias.items():
            if suya == tabla:
                filas[ident] = dict(vars(copia))
        for suya, obj in self._nuevos:
            if suya == tabla:
                filas[getattr(obj, "id", None)] = _fila_de(obj)
        for suya, ident in self._borrados:
            if suya == tabla:
                filas.pop(ident, None)
        salida = []
        for ident, bruta in filas.items():
            clave = (tabla, ident)
            if clave not in self._copias:
                self._copias[clave] = SimpleNamespace(**bruta)
            salida.append(self._copias[clave])
        return salida

    def _fila(self, tabla, ident):
        filas = self._ver(tabla)
        if ident is not None:
            for fila in filas:
                if getattr(fila, "id", None) == ident:
                    return fila
            raise AssertionError(f"{tabla} id={ident} no existe")
        assert len(filas) == 1, f"se esperaba una sola fila en {tabla}: {filas}"
        return filas[0]

    def _verificar_indice(self, tabla, obj):
        """El índice único PARCIAL de la 057: una reserva viva por (clase, alumno)."""
        if tabla != "reservas" or self.almacen.sin_indice or not _viva(obj):
            return
        for otra in self.almacen.filas("reservas"):
            gemela = SimpleNamespace(**otra)
            if (_viva(gemela)
                    and gemela.clase_id == obj.clase_id
                    and gemela.alumno_id == obj.alumno_id):
                raise IntegrityError(
                    "INSERT INTO reservas ...", {},
                    Exception("duplicate key value violates unique constraint "
                              f'"{NOMBRE_INDICE_RESERVA_UNICA}"'))

    def _retener(self, candado):
        self._candados.append(candado)

    def _olvidar(self, tabla):
        for clave in [c for c in self._copias if c[0] == tabla]:
            del self._copias[clave]

    def _liberar(self):
        while self._candados:
            self._candados.pop().release()


def _cumple(fila, criterios) -> bool:
    return all(_evalua(fila, criterio) for criterio in criterios)


def _evalua(fila, criterio) -> bool:
    """Evalúa eq / comparaciones / NOT IN; los `and_()` compuestos se ignoran."""
    izquierda = getattr(criterio, "left", None)
    derecha = getattr(criterio, "right", None)
    clave = getattr(izquierda, "key", None)
    if clave is None or derecha is None:
        return True
    actual = getattr(fila, clave, None)
    valor = getattr(derecha, "value", derecha)
    operador = getattr(getattr(criterio, "operator", None), "__name__", "")
    if operador == "eq":
        return actual == valor
    if operador in ("not_in_op", "notin_op"):
        return actual not in (valor or ())
    if operador in ("ge", "le", "gt", "lt"):
        try:
            if operador == "ge":
                return actual >= valor
            if operador == "le":
                return actual <= valor
            if operador == "gt":
                return actual > valor
            return actual < valor
        except TypeError:       # columna sin dato comparable en el doble: no filtra
            return True
    return True


def _en_paralelo(*tareas):
    """Corre las tareas en hilos que arrancan a la vez (dos requests de verdad)."""
    salida = [None] * len(tareas)
    barrera = threading.Barrier(len(tareas))

    def correr(indice, tarea):
        barrera.wait(timeout=10)
        try:
            salida[indice] = ("ok", tarea())
        except Exception as error:      # noqa: BLE001  (el test compara el tipo)
            salida[indice] = ("error", error)

    hilos = [threading.Thread(target=correr, args=(i, t)) for i, t in enumerate(tareas)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=20)
        assert not hilo.is_alive(), "un request quedó colgado (deadlock)"
    return salida


def _exitos(resultados):
    return [valor for etiqueta, valor in resultados if etiqueta == "ok"]


def _fallos(resultados):
    return [valor for etiqueta, valor in resultados if etiqueta == "error"]


# ══════════════════════════════════════════════════════════════════════════════
#  Andamiaje: rate limit / efectos de segundo plano apagados
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _sin_rate_limit():
    """`POST /reservas` y `POST /suscripciones` están detrás de slowapi.

    Acá se llaman como funciones: sin `Request` real, slowapi se apaga (es su
    forma documentada de testear; `enabled` se mira en cada llamada).
    """
    previo_res, previo_sus = res.limiter.enabled, sus.limiter.enabled
    res.limiter.enabled = False
    sus.limiter.enabled = False
    yield
    res.limiter.enabled = previo_res
    sus.limiter.enabled = previo_sus


@pytest.fixture(autouse=True)
def _sin_segundo_plano(monkeypatch):
    """Churn (BackgroundTasks), auditoría y referidos no son parte de la carrera."""
    from app.services import churn_service
    monkeypatch.setattr(churn_service, "programar_recalculo", lambda *a, **k: None)
    monkeypatch.setattr(res, "registrar_auditoria", lambda *a, **k: None)
    monkeypatch.setattr(sus, "registrar_auditoria", lambda *a, **k: None)
    monkeypatch.setattr(sus.referidos_service, "confirmar_compra", lambda *a, **k: None)


# ══════════════════════════════════════════════════════════════════════════════
#  Semilla
# ══════════════════════════════════════════════════════════════════════════════
HOY = hoy_santiago()
VENCE = datetime.now(timezone.utc) + timedelta(days=10)


def _clase(ident, cupo=10, asistentes=0):
    return {"id": ident, "tenant_id": 1, "fecha": HOY, "cancelada": False,
            "cupo_maximo": cupo, "asistentes_confirmados": asistentes}


def _alumno(ident=42):
    return {"id": ident, "tenant_id": 1, "rol": "alumno"}


def _membresia(creditos, ident=1, usuario_id=42):
    return {"id": ident, "tenant_id": 1, "usuario_id": usuario_id, "plan_id": 3,
            "estado": "activo", "creditos_totales": creditos,
            "creditos_disponibles": creditos,
            "fecha_inicio": HOY, "fecha_expiracion": VENCE}


def _pedido(estado="pendiente", cantidad=3):
    return {"id": 7, "tenant_id": 1, "alumno_id": 42, "producto_id": 5,
            "cantidad": cantidad, "estado": estado}


def _producto(stock=10):
    return {"id": 5, "tenant_id": 1, "nombre": "Polera", "stock": stock}


def _con_sesion(almacen, llamada):
    """Corre la llamada con su propia sesión; si falla, la cierra (rollback).

    Es lo que hace `get_db` al cerrar la sesión: la transacción (y sus locks) se
    suelta. Sin esto, un error dentro de un endpoint dejaría el lock tomado y el
    OTRO request quedaría esperando para siempre.
    """
    sesion = _Sesion(almacen)
    try:
        return llamada(sesion)
    except BaseException:
        sesion.rollback()
        raise


def _reservar(almacen, clase_id):
    """Un request de `POST /reservas`: el alumno 42 reservando para sí mismo."""
    return _con_sesion(almacen, lambda sesion: res.crear_reserva(
        request=None,                   # slowapi se apaga en el fixture
        reserva_data=ReservaCreate(clase_id=clase_id, alumno_id=42, tenant_id=1),
        background_tasks=None,
        db=sesion,
        current_user={"tenant_id": 1, "usuario_id": 42, "rol": "alumno"},
    ))


def _borrar_pedido(almacen):
    """Un request de `DELETE /pedidos/{id}` (admin del box 1)."""
    return _con_sesion(almacen, lambda sesion: ped.eliminar_pedido(
        pedido_id=7,
        db=sesion,
        current_user={"tenant_id": 1, "usuario_id": 9, "rol": "admin"},
    ))


def _alta_de_plan(almacen):
    """Un request de `POST /suscripciones` (alta manual del admin)."""
    return _con_sesion(almacen, lambda sesion: sus.crear_suscripcion(
        request=None,                   # slowapi se apaga en el fixture
        data=sus.SuscripcionCreate(tenant_id=1, usuario_id=42, plan_id=3,
                                   creditos_totales=10, creditos_disponibles=10),
        background_tasks=None,
        db=sesion,
        current_user={"tenant_id": 1, "usuario_id": 9, "rol": "admin"},
    ))


def _almacen_de_reservas(creditos, *clases):
    return _Almacen(clases=list(clases), usuarios=[_alumno()],
                    suscripciones=[_membresia(creditos)], reservas=[])


# ══════════════════════════════════════════════════════════════════════════════
#  A. POST /reservas: el duplicado (misma clase, dos clics)
# ══════════════════════════════════════════════════════════════════════════════
def test_a_dos_reservas_simultaneas_de_la_misma_clase_dejan_una():
    almacen = _almacen_de_reservas(2, _clase(3))

    resultados = _en_paralelo(lambda: _reservar(almacen, 3),
                              lambda: _reservar(almacen, 3))

    assert len(_exitos(resultados)) == 1, resultados
    fallos = _fallos(resultados)
    assert [f.status_code for f in fallos] == [400]
    assert "ya tiene una reserva activa" in fallos[0].detail

    assert len(almacen.filas("reservas")) == 1          # UNA reserva, no dos
    assert almacen.filas("clases")[0]["asistentes_confirmados"] == 1   # un asiento
    assert almacen.filas("suscripciones")[0]["creditos_disponibles"] == 1  # un crédito


def test_a_meta_con_indice_apagado_entran_dos_reservas(monkeypatch):
    """Guarda de sensibilidad del ÍNDICE (secuencial, sin depender del timing).

    El pre-check de duplicados no puede ser la garantía: bajo concurrencia los dos
    requests pueden leer "no hay nada" (ver el meta-test del lock, abajo). Acá se
    apaga el índice y se ve que el segundo INSERT **entra**: sin él, no hay nada
    que impida la segunda reserva viva.
    """
    almacen = _Almacen(sin_indice=True, clases=[_clase(3)], usuarios=[_alumno()],
                       suscripciones=[_membresia(2)],
                       reservas=[{"id": 1, "clase_id": 3, "alumno_id": 42,
                                  "tenant_id": 1, "estado": "confirmada"}])
    sesion = _Sesion(almacen)
    sesion.add(Reserva(tenant_id=1, clase_id=3, alumno_id=42, estado="confirmada"))

    sesion.commit()                     # con el índice prendido esto sería IntegrityError

    assert len(almacen.filas("reservas")) == 2


# ══════════════════════════════════════════════════════════════════════════════
#  B. POST /reservas: el crédito (dos clases, un solo crédito)
# ══════════════════════════════════════════════════════════════════════════════
def test_b_un_credito_no_paga_dos_clases_simultaneas():
    almacen = _almacen_de_reservas(1, _clase(3), _clase(4))

    resultados = _en_paralelo(lambda: _reservar(almacen, 3),
                              lambda: _reservar(almacen, 4))

    assert len(_exitos(resultados)) == 1, resultados
    fallos = _fallos(resultados)
    assert [f.status_code for f in fallos] == [400]
    assert "No te quedan clases disponibles" in fallos[0].detail

    assert len(almacen.filas("reservas")) == 1          # una clase, no dos
    assert almacen.filas("suscripciones")[0]["creditos_disponibles"] == 0
    # El asiento de la clase que se quedó sin crédito se devuelve (rollback).
    asientos = sorted(c["asistentes_confirmados"] for c in almacen.filas("clases"))
    assert asientos == [0, 1]


def test_b_meta_sin_lock_el_test_detecta_el_doble_gasto(monkeypatch):
    """Guarda de sensibilidad: sin `FOR UPDATE`, un crédito paga DOS clases."""
    monkeypatch.setattr(_Sesion, "sin_lock", True)
    almacen = _almacen_de_reservas(1, _clase(3), _clase(4))

    resultados = _en_paralelo(lambda: _reservar(almacen, 3),
                              lambda: _reservar(almacen, 4))

    assert len(_exitos(resultados)) == 2, "el doble ya no reproduce la carrera"
    assert len(almacen.filas("reservas")) == 2
    assert almacen.filas("suscripciones")[0]["creditos_disponibles"] == 0


# ══════════════════════════════════════════════════════════════════════════════
#  C. POST /suscripciones: el alta manual repetida (doble ingreso en caja)
# ══════════════════════════════════════════════════════════════════════════════
PLAN = {"id": 3, "tenant_id": 1, "nombre": "Mensual", "duracion_dias": 30,
        "precio_clp": 30000, "activo": True}


def test_c_dos_altas_simultaneas_iguales_crean_una_sola():
    almacen = _Almacen(usuarios=[_alumno()], planes=[PLAN],
                       suscripciones=[], transacciones_financieras=[])

    resultados = _en_paralelo(lambda: _alta_de_plan(almacen),
                              lambda: _alta_de_plan(almacen))

    assert len(_exitos(resultados)) == 1, resultados
    fallos = _fallos(resultados)
    assert [f.status_code for f in fallos] == [409]
    assert "Ya existe una suscripción de este plan" in fallos[0].detail

    assert len(almacen.filas("suscripciones")) == 1        # una membresía
    # El ingreso en caja es el que duele: dos altas = el box facturaba doble.
    assert len(almacen.filas("transacciones_financieras")) == 1


def test_c_meta_sin_lock_el_test_detecta_la_doble_suscripcion(monkeypatch):
    """Guarda de sensibilidad: sin el lock del alumno, entran las dos altas."""
    monkeypatch.setattr(_Sesion, "sin_lock", True)
    almacen = _Almacen(usuarios=[_alumno()], planes=[PLAN],
                       suscripciones=[], transacciones_financieras=[])

    resultados = _en_paralelo(lambda: _alta_de_plan(almacen),
                              lambda: _alta_de_plan(almacen))

    assert len(_exitos(resultados)) == 2, "el doble ya no reproduce la carrera"
    assert len(almacen.filas("suscripciones")) == 2
    assert len(almacen.filas("transacciones_financieras")) == 2


# ══════════════════════════════════════════════════════════════════════════════
#  D. DELETE /pedidos/{id}: el stock devuelto dos veces
# ══════════════════════════════════════════════════════════════════════════════
def test_d_dos_borrados_simultaneos_devuelven_el_stock_una_sola_vez():
    almacen = _Almacen(pedidos=[_pedido()], productos=[_producto(stock=10)])

    resultados = _en_paralelo(lambda: _borrar_pedido(almacen),
                              lambda: _borrar_pedido(almacen))

    assert len(_exitos(resultados)) == 1, resultados
    fallos = _fallos(resultados)
    assert [f.status_code for f in fallos] == [404]

    assert almacen.filas("pedidos") == []
    assert almacen.filas("productos")[0]["stock"] == 13     # 10 + 3, UNA vez


def test_d_meta_sin_lock_el_test_detecta_el_doble_borrado(monkeypatch):
    """Guarda de sensibilidad: sin `FOR UPDATE`, los dos borrados "funcionan"."""
    monkeypatch.setattr(_Sesion, "sin_lock", True)
    almacen = _Almacen(pedidos=[_pedido()], productos=[_producto(stock=10)])

    resultados = _en_paralelo(lambda: _borrar_pedido(almacen),
                              lambda: _borrar_pedido(almacen))

    assert len(_exitos(resultados)) == 2, "el doble ya no reproduce la carrera"




# ══════════════════════════════════════════════════════════════════════════════
#  E. PUT /pedidos/{id}: el estado ya no se escribe a mano
# ══════════════════════════════════════════════════════════════════════════════
def _fuente(relativa):
    return (_BACKEND / relativa).read_text(encoding="utf-8-sig")


def _bloque(fuente, desde, hasta="\n@router."):
    """Texto desde `desde` hasta el próximo endpoint (mismo helper de los tests)."""
    inicio = fuente.index(desde)
    resto = fuente[inicio:]
    fin = resto.find(hasta, len(desde))
    return resto if fin == -1 else resto[:fin]


def test_e_put_del_pedido_delega_en_las_reglas_del_estado(monkeypatch):
    llamadas = []

    def _falso(**kwargs):
        llamadas.append(kwargs)
        return "pedido-validado"

    monkeypatch.setattr(ped, "actualizar_estado_pedido", _falso)

    resultado = ped.actualizar_pedido(
        pedido_id=7, pedido_data=PedidoUpdate(estado="validado"), db=None,
        current_user={"tenant_id": 1, "usuario_id": 9})

    assert resultado == "pedido-validado"
    assert llamadas == [{"pedido_id": 7, "nuevo_estado": "validado", "db": None,
                         "current_user": {"tenant_id": 1, "usuario_id": 9}}]


def test_e2_un_put_sin_estado_no_toca_el_pedido(monkeypatch):
    monkeypatch.setattr(ped, "actualizar_estado_pedido",
                        lambda **kw: pytest.fail("no debe delegar sin estado"))

    with pytest.raises(HTTPException) as exc:
        ped.actualizar_pedido(pedido_id=7, pedido_data=PedidoUpdate(), db=None,
                              current_user={"tenant_id": 1, "usuario_id": 9})

    assert exc.value.status_code == 400


def test_e3_la_fuente_del_put_ya_no_escribe_el_estado_a_mano():
    bloque = _bloque(_fuente("app/api/v1/pedidos.py"), "def actualizar_pedido")
    assert "for field, value in update_data.items()" not in bloque
    assert "actualizar_estado_pedido(" in bloque


def test_d3_el_delete_bloquea_el_pedido_y_el_producto():
    """`FOR UPDATE` en las dos filas + stock devuelto con `or 0` (nunca `+=`)."""
    bloque = _bloque(_fuente("app/api/v1/pedidos.py"), "def eliminar_pedido")
    assert bloque.count("with_for_update()") == 2
    assert "producto.stock or 0" in bloque
    assert "producto.stock +=" not in bloque



# ══════════════════════════════════════════════════════════════════════════════
#  F. La red de la BASE: el índice único parcial (migración 057)
# ══════════════════════════════════════════════════════════════════════════════
def _indice_del_modelo():
    for indice in Reserva.__table__.indexes:
        if indice.name == NOMBRE_INDICE_RESERVA_UNICA:
            return indice
    raise AssertionError("el modelo no declara el índice único de reserva viva")


def _migracion(nombre):
    ruta = _BACKEND / "alembic" / "versions" / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_f_el_indice_del_modelo_es_unico_parcial_y_por_clase_alumno():
    indice = _indice_del_modelo()
    assert indice.unique is True
    assert [c.name for c in indice.columns] == ["clase_id", "alumno_id"]
    predicado = indice.dialect_options["postgresql"]["where"].text
    assert predicado.startswith("estado NOT IN (")
    for estado in ESTADOS_CANCELADA:
        assert f"'{estado}'" in predicado


def test_f2_el_modelo_y_la_migracion_057_declaran_el_mismo_indice():
    """Si el modelo y la migración divergen, `create_all` y PROD no coinciden."""
    migracion = _migracion("057_reserva_unica_viva")
    indice = _indice_del_modelo()

    assert migracion.TABLA == Reserva.__tablename__ == "reservas"
    assert migracion.INDICE == indice.name == NOMBRE_INDICE_RESERVA_UNICA
    assert migracion.PREDICADO == indice.dialect_options["postgresql"]["where"].text
    assert migracion.down_revision == "056_aviso_promocion"


def test_f3_la_057_es_la_unica_cabeza_sobre_la_056():
    """Dos `down_revision` sobre la misma revisión = dos heads = deploy roto."""
    hijas = [archivo.stem
             for archivo in (_BACKEND / "alembic" / "versions").glob("*.py")
             if re.search(r"down_revision[^=]*=\s*['\"]056_aviso_promocion['\"]",
                          archivo.read_text(encoding="utf-8-sig", errors="ignore"))]
    assert hijas == ["057_reserva_unica_viva"], hijas


def test_f4_la_app_traduce_la_violacion_del_indice_a_400():
    """Ese `IntegrityError` no puede terminar en 500 en ninguno de los dos caminos."""
    error = IntegrityError("INSERT INTO reservas ...", {},
                           Exception("duplicate key value violates unique constraint "
                                     f'"{NOMBRE_INDICE_RESERVA_UNICA}"'))
    assert es_reserva_duplicada(error) is True
    assert es_reserva_duplicada(
        IntegrityError("INSERT INTO reservas ...", {}, Exception("otra cosa"))) is False

    for ruta in ("reservas", "asistencia"):
        assert "es_reserva_duplicada(error)" in _fuente(f"app/api/v1/{ruta}.py"), ruta


def test_f5_el_indice_deja_volver_a_reservar_despues_de_cancelar():
    almacen = _Almacen(reservas=[{"id": 1, "clase_id": 3, "alumno_id": 42,
                                  "tenant_id": 1, "estado": "cancelada"}])

    primera = _Sesion(almacen)
    primera.add(Reserva(tenant_id=1, clase_id=3, alumno_id=42, estado="confirmada"))
    primera.commit()                       # la cancelada no choca
    assert len(almacen.filas("reservas")) == 2

    segunda = _Sesion(almacen)
    segunda.add(Reserva(tenant_id=1, clase_id=3, alumno_id=42, estado="confirmada"))
    with pytest.raises(IntegrityError) as exc:
        segunda.commit()
    assert es_reserva_duplicada(exc.value) is True

