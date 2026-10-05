"""
Voucher de plan y alta de alumno -> campana del ADMIN (tabla `notificaciones`).

QUÉ SE PRUEBA (integraciones reales contra la API del branch TEST):

  * POST /solicitudes/solicitar -> 1 fila `plan_solicitado` por cada admin ACTIVO
    del box (y 0 para los admins de OTRO box), con el plan y el #id adentro del
    mensaje;
  * POST /alumnos/registro/alumno-nuevo -> 1 fila `alumno_nuevo` por cada admin
    ACTIVO del box, con el correo del alumno nuevo.

Por qué existen: esos dos flujos NO avisaban a nadie en el panel (la solicitud
vivía sólo en el Dashboard del admin y el alta sólo mandaba correo, que con
EMAIL_MODO=noop en TEST no llega). El aislamiento entre boxes lo cubre el mismo
criterio que el Bazar (tests/test_pedidos_notificaciones.py): el destinatario se
elige por `usuarios.tenant_id` porque `notificaciones` no tiene `tenant_id`.

⚠️ INTEGRACIÓN (no unitario): requiere la API corriendo contra el branch TEST
(conftest.BASE) y NO se ejecuta en la validación local. Crea datos REALES y los
BORRA al terminar:

  * la solicitud se pide con un alumno SIN solicitud pendiente (el endpoint
    responde 400 al que ya tiene una) y SIN descuento vigente (solicitar CONSUME
    el beneficio: esta prueba no viene a gastar el regalo de nadie);
  * el alta usa un correo y un RUT únicos por corrida (con su DV calculado, que
    el endpoint valida) y borra el usuario y su suscripción de prueba.

Correr (con el stack de TEST levantado):
    py -3.12 -m pytest tests/test_notificaciones_admin_flujos.py -q
"""
from datetime import datetime, timezone
import time

import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _all(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).fetchall()


def _exec(sql, **params):
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _token(row, rol):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": row.id,
        "tenant_id": row.tenant_id,
        "rol": rol,
        "correo": row.correo,
    })}


def _admins(tenant_id):
    return _all(
        "SELECT id FROM usuarios WHERE tenant_id = :t "
        "AND rol::text = 'administrador' AND estado = 'activo' ORDER BY id",
        t=tenant_id)


def _notifs(tipo, alumno_ids, desde):
    """Avisos de ese tipo creados DESPUÉS de `desde` para esos destinatarios."""
    if not alumno_ids:
        return []
    ids_sql = ", ".join(str(int(i)) for i in alumno_ids)
    return _all(
        f"SELECT alumno_id, mensaje FROM notificaciones WHERE tipo = :tipo "
        f"AND created_at >= :desde AND alumno_id IN ({ids_sql})",
        tipo=tipo, desde=desde)


def _alumno_para_solicitar():
    """Alumno activo del box sin solicitud pendiente y sin descuento vigente."""
    return _one(
        "SELECT u.id, u.tenant_id, u.correo FROM usuarios u "
        "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' "
        "AND u.estado = 'activo' AND u.correo IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM solicitudes_plan s "
        "                WHERE s.alumno_id = u.id AND s.estado = 'pending') "
        "AND NOT EXISTS (SELECT 1 FROM beneficios b "
        "                WHERE b.alumno_id = u.id "
        "                AND b.tipo::text = 'descuento' "
        "                AND b.estado::text = 'ofrecido') "
        "ORDER BY (u.correo LIKE '%test%') DESC, u.id LIMIT 1",
        t=TENANT_ID)


def _plan_del_box():
    return _one(
        "SELECT id, nombre FROM planes WHERE tenant_id = :t AND activo = true "
        "ORDER BY id LIMIT 1", t=TENANT_ID)


def _dv(cuerpo: str) -> str:
    """Dígito verificador del RUT (módulo 11: la misma regla que valida el alta)."""
    suma, multiplo = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    return "K" if resto == 10 else str(resto)

def test_solicitar_plan_con_voucher_avisa_a_los_admins():
    alumno = _alumno_para_solicitar()
    if alumno is None:
        pytest.skip("TEST no tiene un alumno activo libre de solicitud y descuento")
    admins = _admins(TENANT_ID)
    if not admins:
        pytest.skip("TEST no tiene administradores activos en el box 1")
    plan = _plan_del_box()
    if plan is None:
        pytest.skip("TEST no tiene un plan activo en el box 1")

    ids_admins = [a.id for a in admins]
    headers = _token(alumno, "alumno")
    inicio = datetime.now(timezone.utc)
    solicitud_id = None
    try:
        r = requests.post(f"{BASE}/solicitudes/solicitar", headers=headers, json={
            "tenant_id": TENANT_ID,
            "alumno_id": alumno.id,
            "plan_id": plan.id,
            "voucher_url": "https://example.test/voucher.png",
        }, timeout=30)
        assert r.status_code in (200, 201), r.text[:300]
        solicitud_id = r.json()["id"]

        # 1 aviso 'plan_solicitado' por admin ACTIVO del box, con el plan y el #id
        avisos = _notifs("plan_solicitado", ids_admins, inicio)
        assert len(avisos) == len(admins), avisos
        assert {a.alumno_id for a in avisos} == set(ids_admins)
        for aviso in avisos:
            assert plan.nombre in aviso.mensaje, aviso.mensaje
            assert f"#{solicitud_id}" in aviso.mensaje, aviso.mensaje

        # Y nadie de OTRO box (si TEST tiene un segundo box)
        otros_admins = [a.id for a in _all(
            "SELECT id FROM usuarios WHERE tenant_id <> :t "
            "AND rol::text = 'administrador' AND estado = 'activo' LIMIT 20",
            t=TENANT_ID)]
        if otros_admins:
            assert _notifs("plan_solicitado", otros_admins, inicio) == []
    finally:
        # Limpieza: los avisos de esta corrida y la solicitud (nada más)
        ids_sql = ", ".join(str(int(i)) for i in ids_admins)
        if ids_sql:
            _exec(
                "DELETE FROM notificaciones WHERE created_at >= :desde "
                "AND tipo = 'plan_solicitado' "
                f"AND alumno_id IN ({ids_sql})", desde=inicio)
        if solicitud_id is not None:
            _exec("DELETE FROM solicitudes_plan WHERE id = :id", id=solicitud_id)



def test_registro_de_alumno_avisa_a_los_admins():
    admins = _admins(TENANT_ID)
    if not admins:
        pytest.skip("TEST no tiene administradores activos en el box 1")

    ids_admins = [a.id for a in admins]
    # Correo y RUT únicos por corrida (el alta exige que no existan y valida el DV)
    marca = str(int(time.time()))
    cuerpo_rut = "9" + marca[-7:]
    correo = f"prueba.campana.{marca}@example.test"
    inicio = datetime.now(timezone.utc)
    usuario_id = None
    try:
        # Endpoint PÚBLICO: sin Authorization (es el autoservicio del alumno)
        r = requests.post(f"{BASE}/alumnos/registro/alumno-nuevo", json={
            "nombre": "Alumno de prueba (campana admin)",
            "correo": correo,
            "rut": f"{cuerpo_rut}-{_dv(cuerpo_rut)}",
            "tenant_id": TENANT_ID,
            "peso": 70.5,
            "estatura": 175,
        }, timeout=30)
        assert r.status_code == 201, r.text[:300]

        fila = _one("SELECT id FROM usuarios WHERE correo = :c", c=correo)
        assert fila is not None, "el alta no creó el usuario"
        usuario_id = fila.id

        # 1 aviso 'alumno_nuevo' por admin ACTIVO del box, con el correo del alta
        avisos = _notifs("alumno_nuevo", ids_admins, inicio)
        assert len(avisos) == len(admins), avisos
        assert {a.alumno_id for a in avisos} == set(ids_admins)
        for aviso in avisos:
            assert correo in aviso.mensaje, aviso.mensaje
    finally:
        # Limpieza: avisos de esta corrida, la suscripción de prueba y el usuario
        # (en ese orden: la suscripción referencia al usuario)
        ids_sql = ", ".join(str(int(i)) for i in ids_admins)
        if ids_sql:
            _exec(
                "DELETE FROM notificaciones WHERE created_at >= :desde "
                "AND tipo = 'alumno_nuevo' "
                f"AND alumno_id IN ({ids_sql})", desde=inicio)
        if usuario_id is not None:
            _exec("DELETE FROM suscripciones WHERE usuario_id = :u", u=usuario_id)
            _exec("DELETE FROM usuarios WHERE id = :u", u=usuario_id)
