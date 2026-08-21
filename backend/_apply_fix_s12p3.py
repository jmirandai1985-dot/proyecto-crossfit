"""Aplica los fixes S12 (historicoIngresos real) y P3 (alta admin crea Prueba).

S12 : reportes.py       -> historicoIngresos desde transacciones_financieras (6 meses).
P3  : usuarios.py       -> alta de alumno por admin crea suscripcion 'Prueba' activa.
P3b : suscripciones.py  -> crear suscripcion paga expira la 'Prueba' activa (consistencia
                           con aprobar_solicitud; evita quedar trabado en modo prueba).
Preserva CRLF/LF y verifica cada reemplazo (1 match).
"""
import io
import os

BASE = r"c:\Users\Asus\Desktop\Proyectos\proyecto-crossfit\backend"


def _leer(ruta):
    with io.open(ruta, "r", encoding="utf-8", newline="") as f:
        return f.read()


def aplicar(rel, tag, old, new):
    ruta = os.path.join(BASE, rel)
    src = _leer(ruta)
    e = "\r\n" if "\r\n" in src else "\n"
    old_crlf = old.replace("\n", e)
    new_crlf = new.replace("\n", e)
    n = src.count(old_crlf)
    if n != 1:
        raise SystemExit(f"[{tag}] bloque no encontrado o ambiguo (matches={n}) en {rel}")
    src = src.replace(old_crlf, new_crlf)
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print(f"[{tag}] OK - {rel}")


# ═══════════════ FIX S12 — reportes.py (historicoIngresos) ═══════════════
aplicar(
    r"app\api\v1\reportes.py", "S12 historico ingresos",
    '''        # Historico ingresos 6 meses - PENDIENTE: no existe tabla de transacciones
        historico_ingresos = []''',
    '''        # --- 15b. HISTORICO INGRESOS 6 MESES (desde transacciones_financieras) ---
        # FIX S12: antes hardcodeado [] con comentario desactualizado ("no existe
        # tabla de transacciones"). La tabla SI existe y es la misma fuente que
        # ingresos_mes: se agrupa por mes (ingreso - egreso) los ultimos 6 meses.
        historico_ingresos = []
        for i in range(5, -1, -1):
            ini_h, fin_h = _inicio_fin_mes(-i)
            label_h = f"{MESES[ini_h.month - 1]} {ini_h.year}"
            ing_h = db.execute(sql_text("""
                SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE 0 END), 0)
                FROM transacciones_financieras
                WHERE tenant_id = :tid AND fecha >= :ini_d AND fecha <= :fin_d
            """), {"tid": tenant_id, "ini_d": ini_h.date(), "fin_d": fin_h.date()}).scalar() or 0
            eg_h = db.execute(sql_text("""
                SELECT COALESCE(SUM(CASE WHEN tipo='egreso' THEN monto ELSE 0 END), 0)
                FROM transacciones_financieras
                WHERE tenant_id = :tid AND fecha >= :ini_d AND fecha <= :fin_d
            """), {"tid": tenant_id, "ini_d": ini_h.date(), "fin_d": fin_h.date()}).scalar() or 0
            historico_ingresos.append({
                "mes": label_h,
                "ingresos": float(ing_h) - float(eg_h),
            })''',
)

# ═══════════════ FIX P3 — usuarios.py (imports) ═══════════════
aplicar(
    r"app\api\v1\usuarios.py", "P3 imports",
    '''from app.db.database import get_db
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate, UsuarioResponse, UsuarioListItem''',
    '''from app.db.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.plan import Plan
from app.models.suscripcion import Suscripcion
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate, UsuarioResponse, UsuarioListItem''',
)

aplicar(
    r"app\api\v1\usuarios.py", "P3 imports datetime",
    '''import bcrypt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional''',
    '''import bcrypt
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional''',
)

# ═══════════════ FIX P3 — usuarios.py (alta de alumno crea Prueba) ═══════════════
aplicar(
    r"app\api\v1\usuarios.py", "P3 alta alumno Prueba",
    '''    db.add(db_usuario)
    db.commit()
    db.refresh(db_usuario)''',
    '''    db.add(db_usuario)
    db.flush()

    # ── FIX P3 (consistencia: alta por admin == flujo de landing) ──
    # Antes el alta directa dejaba al alumno SIN suscripción: no entraba al gate
    # de modo prueba (veía todo el menú) y además no podía reservar (sin
    # membresía activa). Ahora se crea la misma suscripción "Prueba" del landing
    # (1 token, 7 días), en estado ACTIVO porque el usuario ya se crea activo
    # (en el landing la suscripción pasa de pendiente→activa al activarse).
    # Resultado: el alumno entra al modo prueba real (require_full_access).
    if usuario_data.rol == RolUsuario.alumno:
        plan_prueba = db.query(Plan).filter(
            Plan.tenant_id == db_usuario.tenant_id,
            Plan.nombre == "Prueba",
        ).first()
        if not plan_prueba:
            plan_prueba = Plan(
                tenant_id=db_usuario.tenant_id, nombre="Prueba", creditos=1,
                es_ilimitado=False, precio_clp=0, duracion_dias=7, activo=True,
            )
            db.add(plan_prueba)
            db.flush()
        db.add(Suscripcion(
            tenant_id=db_usuario.tenant_id,
            usuario_id=db_usuario.id,
            plan_id=plan_prueba.id,
            estado="activo",
            creditos_totales=1,
            creditos_disponibles=1,
            fecha_inicio=datetime.now(timezone.utc),
            fecha_expiracion=datetime.now(timezone.utc) + timedelta(days=7),
        ))

    db.commit()
    db.refresh(db_usuario)''',
)

# ═══════════════ FIX P3b — suscripciones.py (expirar Prueba al pagar) ═══════════════
aplicar(
    r"app\api\v1\suscripciones.py", "P3b expirar Prueba",
    '''    db.add(db_sus)
    db.commit()
    db.refresh(db_sus)

    # ── Auditoría interna: alta de suscripción (ajuste de tokens) ──''',
    '''    db.add(db_sus)
    db.commit()
    db.refresh(db_sus)

    # ── FIX P3b (consistencia con aprobar_solicitud): al crear una membresía
    # paga, expirar la suscripción "Prueba" activa del alumno (estado='vencido')
    # para que el gate de modo prueba se desbloquee (es_usuario_prueba → False).
    # Mismo criterio que solicitudes_planes (FIX 3). No aplica si el plan nuevo
    # es "Prueba". Nunca debe impedir la creación si falla.
    try:
        from app.models.plan import Plan
        plan_nuevo = db.query(Plan).filter(Plan.id == data.plan_id).first()
        if plan_nuevo and plan_nuevo.nombre != "Prueba":
            sus_prueba = db.query(Suscripcion).join(
                Plan, Suscripcion.plan_id == Plan.id
            ).filter(
                Suscripcion.usuario_id == data.usuario_id,
                Suscripcion.estado == "activo",
                Plan.nombre == "Prueba",
            ).all()
            for sp in sus_prueba:
                sp.estado = "vencido"
            db.commit()
    except Exception as e:
        import logging
        logging.getLogger("uvicorn").warning(f"No se pudo expirar suscripcion Prueba: {e}")

    # ── Auditoría interna: alta de suscripción (ajuste de tokens) ──''',
)

print("\nTODOS LOS FIXES S12/P3 APLICADOS.")
